"""Native native schema/factory/connect/scoped picker/wire fixtures.

All IDs and keys here are synthetic; provider boundaries are local fakes.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from uuid import UUID
import httpx
import pytest
from pydantic import ValidationError
from nodes import audiobookshelf_node as p
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import collect_evidence
from nodes.core.credential_connect import validate_for_connect

KEY = {"credential_type": p.TYPE, "instance_origin": "https://instance.example.test", "api_key": "synthetic_private_server_api_key"}
LID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
AID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OTHER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
LIBRARY = {"id": LID, "name": "Synthetic library", "mediaType": "vendor-defined-media", "displayOrder": 0, "createdAt": -7, "lastUpdate": 19, "folders": [{"fullPath": "synthetic-private"}], "settings": {"secret": "synthetic-private"}, "icon": "private", "provider": "private"}
AUTHOR = {"id": AID, "name": "Synthetic author", "addedAt": -1, "updatedAt": 42, "asin": "synthetic-private", "imagePath": "private", "libraryItems": [{"title": "private"}], "series": [{"name": "private"}]}
EXPANDED = {**AUTHOR, "numBooks": 12}


def wire(monkeypatch, payloads=None, status=200, raw=None, mime="application/json"):
    calls = []
    defaults = {"/libraries": {"libraries": [LIBRARY]}, "/libraries/" + LID: LIBRARY, "/libraries/" + LID + "/authors": {"authors": [EXPANDED]}, "/authors/" + AID: AUTHOR}
    @asynccontextmanager
    async def client(**options):
        assert options == {"timeout": 12, "follow_redirects": False, "trust_env": False}
        class Client:
            @asynccontextmanager
            async def stream(self, method, url, **kwargs):
                endpoint = url.removeprefix(KEY["instance_origin"] + "/api")
                assert method == "GET" and endpoint in defaults
                assert kwargs["headers"]["Authorization"] == "Bearer " + KEY["api_key"]
                assert KEY["api_key"] not in repr(kwargs) and KEY["api_key"] not in url
                assert set(kwargs) == {"headers"} and "?" not in url
                calls.append(endpoint)
                payload = defaults[endpoint] if payloads is None else payloads(endpoint, len(calls))
                args = {"content": raw, "headers": {"content-type": mime}} if raw is not None else {"json": payload, "headers": {"content-type": mime}}
                yield httpx.Response(status, request=httpx.Request(method, url), **args)
        yield Client()
    monkeypatch.setattr(p, "guarded_async_client", client)
    return calls


def node(operation, **config):
    return NodeFactory.create_node("fixture", "automation-audiobookshelf", {"config": {"operation": operation, **config}, "credentials": KEY})


def test_actual_native_schema_four_actions_and_visible_only_credential():
    schema = p.AudiobookshelfNode.get_config_schema()
    constants = {d["properties"]["operation"]["const"] for d in schema["$defs"].values() if isinstance(d, dict) and "operation" in d.get("properties", {})}
    assert constants == {"list_libraries", "get_library", "list_library_authors", "get_author"}
    shaped = p.AudiobookshelfAPIKeyCredential.model_validate({"instance_origin": KEY["instance_origin"], "api_key": KEY["api_key"]}).model_dump(exclude_unset=True)
    assert shaped["credential_type"] == p.TYPE and KEY["api_key"] not in repr(p.guard(KEY))
    assert node("get_author", library_id=LID, author_id=AID).config.config.author_id == AID
    for bad in [1, True, None, "", ".", "..", "legacy-author-id", "a\n", LID.replace("-", "")]:
        with pytest.raises(ConfigValidationError, match="library_id"): node("get_library", library_id=bad)
        with pytest.raises(ConfigValidationError, match="author_id"): node("get_author", library_id=LID, author_id=bad)
    for extra in ["include", "minified", "page", "cursor", "sort", "filter", "path", "url", "method"]:
        with pytest.raises(ConfigValidationError): node("list_libraries", **{extra: "synthetic"})


@pytest.mark.asyncio
async def test_actual_factory_four_shapes_projection_and_catalog_only_book_count(monkeypatch):
    calls = wire(monkeypatch)
    libraries = await node("list_libraries").execute({})
    safe_library = {"id": LID, "mediaType": "vendor-defined-media", "displayOrder": 0, "createdAt": -7, "lastUpdate": 19}
    assert libraries["items"] == [safe_library] and calls == ["/libraries"]
    calls.clear()
    assert await node("get_library", library_id=LID, include_names=True).execute({}) == {**safe_library, "name": LIBRARY["name"]}
    assert calls == ["/libraries", "/libraries/" + LID, "/libraries"]
    calls.clear()
    authors = await node("list_library_authors", library_id=LID).execute({})
    assert authors["items"] == [{"id": AID, "addedAt": -1, "updatedAt": 42, "resource_linked_book_count": 12}]
    assert all(authors[k] is False for k in ["completion_verified", "principal_identity_verified", "ownership_verified", "snapshot_verified"])
    assert authors["has_more"] is None and authors["total"] is None
    calls.clear()
    detail = await node("get_author", library_id=LID, author_id=AID, include_names=True).execute({})
    assert detail == {"id": AID, "addedAt": -1, "updatedAt": 42, "name": AUTHOR["name"]}
    assert calls == ["/libraries", "/libraries/" + LID, "/libraries", "/libraries/" + LID + "/authors", "/authors/" + AID, "/libraries/" + LID + "/authors", "/libraries", "/libraries/" + LID, "/libraries"]
    assert not ({"libraryId", "asin", "imagePath", "libraryItems", "series", "numBooks", "resource_linked_book_count"} & detail.keys())


@pytest.mark.asyncio
async def test_actual_empty_connect_collector_reachability_not_key_kind_identity(monkeypatch):
    calls = wire(monkeypatch, lambda _path, _n: {"libraries": []})
    verdict = await validate_for_connect(credential_type=p.TYPE, credential_data={"instance_origin": KEY["instance_origin"], "api_key": KEY["api_key"]}, user_id="fixture")
    assert verdict.ok and verdict.credential_data["credential_type"] == p.TYPE
    evidence = await collect_evidence(node_type="automation-audiobookshelf", credential_data=KEY, user_id="fixture")
    assert evidence.reachable is True
    assert all(path == "/libraries" for path in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing_library", "foreign_library", "lost_library", "wrong_parent", "foreign_author", "lost_author", "lost_parent_after_author"])
async def test_actual_parent_catalog_detail_catalog_fail_closed(monkeypatch, case):
    def payload(path, n):
        if path == "/libraries": return {"libraries": [] if case == "missing_library" or (case == "lost_library" and n == 3) or (case == "lost_parent_after_author" and n == 7) else [LIBRARY]}
        if path == "/libraries/" + LID: return {**LIBRARY, "id": OTHER} if case == "foreign_library" else LIBRARY
        if path.endswith("/authors"): return {"authors": [] if case == "wrong_parent" or (case == "lost_author" and n == 6) else [EXPANDED]}
        return {**AUTHOR, "id": OTHER} if case == "foreign_author" else AUTHOR
    calls = wire(monkeypatch, payload)
    with pytest.raises(ValueError): await node("get_author", library_id=LID, author_id=AID).execute({})
    assert len(calls) == {"missing_library": 1, "foreign_library": 2, "lost_library": 3, "wrong_parent": 4, "foreign_author": 5, "lost_author": 6, "lost_parent_after_author": 7}[case]
    if case == "wrong_parent": assert "/authors/" + AID not in calls


@pytest.mark.asyncio
async def test_actual_dependent_author_lookup_requires_parent_and_keeps_id_labels_private(monkeypatch):
    calls = wire(monkeypatch)
    with pytest.raises(ValueError): await p.AudiobookshelfNode.load_field_options("author_id", KEY, context={"organization_id": "forged", "workflow_id": "forged"})
    assert calls == []
    options = await p.AudiobookshelfNode.load_field_options("author_id", KEY, context={"library_id": LID})
    assert options == {"options": [{"value": AID, "label": "Author " + AID}], "next_page_token": None}
    assert "/authors/" + AID not in calls and len(calls) == 7
    calls.clear()
    for field in ["library_id", "author_id"]:
        with pytest.raises(ValueError): await p.AudiobookshelfNode.load_field_options(field, KEY, context={"library_id": LID}, page_token="synthetic")
    assert calls == []


@pytest.mark.asyncio
async def test_local_100_output_bound_and_unknown_completion_including_empty(monkeypatch):
    rows = [{"id": str(UUID(int=i + 1))} for i in range(101)]
    calls = wire(monkeypatch, lambda _path, _n: {"libraries": rows})
    result = await node("list_libraries").execute({})
    assert result["count"] == 100 and result["truncated"] and result["has_more"] is None and result["completion_verified"] is False
    with pytest.raises(ValueError, match="local 100"): await p.AudiobookshelfNode.load_field_options("library_id", KEY)
    with pytest.raises(ValueError, match="local 100"): await node("get_library", library_id=rows[0]["id"]).execute({})
    empty = p.result_page({"libraries": []}, "library")
    assert empty["items"] == [] and empty["has_more"] is None and empty["completion_verified"] is False


@pytest.mark.parametrize("kind,payload", [("library", {"libraries": {}}), ("library", {"libraries": [{"id": 1}]}), ("library", {"libraries": [{"id": LID, "createdAt": True}]}), ("library", {"libraries": [{"id": LID, "mediaType": None}]}), ("library", {"libraries": [LIBRARY, LIBRARY]}), ("author", {"authors": [{"id": AID, "numBooks": True}]}), ("author", {"authors": [{"id": AID, "addedAt": 1.5}]}), ("author", {"authors": [{"name": "private"}]})])
def test_actual_optional_scalar_contracts_without_defaults(kind, payload):
    with pytest.raises(ValueError): p.result_page(payload, kind)
    assert p.record({"id": LID}, "library") == {"id": LID}
    assert p.record({"id": AID, "numBooks": 99}, "author") == {"id": AID}
    assert p.record({"id": AID}, "author", expanded=True) == {"id": AID}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,raw,mime", [(401, b'synthetic_private_error', "application/json"), (403, b'{}', "application/json"), (404, b'{}', "application/json"), (429, b'{}', "application/json"), (302, b'{}', "application/json"), (200, b'{"libraries":[],"libraries":[]}', "application/json"), (200, b'{"libraries":NaN}', "application/json"), (200, b'private', "text/plain"), (200, b'[]', "application/json")])
async def test_refusal_parse_and_format_are_sanitized_one_attempt(monkeypatch, status, raw, mime):
    calls = wire(monkeypatch, status=status, raw=raw, mime=mime)
    with pytest.raises(ValueError) as exc: await node("list_libraries").execute({})
    assert KEY["api_key"] not in str(exc.value) and "synthetic_private_error" not in str(exc.value) and KEY["instance_origin"] not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_closed_transport_wrong_families_and_unsafe_origins_refuse_before_io(monkeypatch):
    calls = wire(monkeypatch)
    for resource in ["/libraries", "item", "media", "user", "auth", "login", "https://other.example.test"]:
        with pytest.raises(ValueError): await p.request(p.guard(KEY), resource)
    for family in ["audiobookshelf_legacy_token", "foreign"]:
        with pytest.raises(ValueError): await p.AudiobookshelfNode.freshen_credential({**KEY, "credential_type": family})
    for origin in ["http://instance.example.test", "https://127.0.0.1", "https://user:password@instance.example.test", "https://instance.example.test/api"]:
        with pytest.raises(ValidationError): p.AudiobookshelfAPIKeyCredential.model_validate({**KEY, "instance_origin": origin})
    assert calls == []
