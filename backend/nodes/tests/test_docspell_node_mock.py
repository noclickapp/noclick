"""UNRUN native schema/factory/connect/wire/opaque-ID/projection fixtures."""
from contextlib import asynccontextmanager
from copy import deepcopy
from urllib.parse import quote
import httpx
import pytest
from pydantic import ValidationError
from nodes import docspell_node as p
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import collect_evidence
from nodes.core.credential_connect import validate_for_connect

KEY = {"credential_type": p.TYPE, "instance_origin": "https://instance.example.test", "auth_token": "synthetic_private_user_token"}
FOLDER = {"id": "opaque /?%é", "created": 123, "name": "Synthetic folder", "owner": {"name": "private"}, "isMember": True, "memberCount": 1, "members": [{"name": "private"}]}
TAG = {"id": "tag_A", "created": -1, "name": "Synthetic tag", "category": "private"}


def wire(monkeypatch, payloads=None, status=200, raw=None, mime="application/json"):
    calls = []
    defaults = {"/sec/folder": {"items": [FOLDER]}, "/sec/tag": {"count": 19, "items": [TAG]}, "/sec/folder/" + quote(FOLDER["id"], safe=""): FOLDER}
    @asynccontextmanager
    async def client(**options):
        assert options == {"timeout": 12, "follow_redirects": False, "trust_env": False, "require_public": True}
        class Client:
            @asynccontextmanager
            async def stream(self, method, url, **kwargs):
                endpoint = url.removeprefix(KEY["instance_origin"] + "/api/v1")
                assert method == "GET" and endpoint in defaults
                assert kwargs["headers"]["X-Docspell-Auth"] == KEY["auth_token"] and "Authorization" not in kwargs["headers"]
                assert KEY["auth_token"] not in repr(kwargs) and KEY["auth_token"] not in url
                assert set(kwargs) == {"headers"} and "?" not in url
                calls.append((endpoint, kwargs))
                payload = defaults[endpoint] if payloads is None else payloads(endpoint, len(calls))
                kwargs = {"content": raw, "headers": {"content-type": mime}} if raw is not None else {"json": payload, "headers": {"content-type": mime}}
                yield httpx.Response(status, request=httpx.Request(method, url), **kwargs)
        yield Client()
    monkeypatch.setattr(p, "guarded_async_client", client)
    return calls


def node(operation, **config):
    return NodeFactory.create_node("fixture", "automation-docspell", {"config": {"operation": operation, **config}, "credentials": KEY})


def test_actual_native_schema_and_visible_only_manual_credential():
    schema = p.DocspellNode.get_config_schema()
    constants = {d["properties"]["operation"]["const"] for d in schema["$defs"].values() if isinstance(d, dict) and "operation" in d.get("properties", {})}
    assert constants == {"list_folders", "get_folder", "list_tags"}
    shaped = p.DocspellAuthTokenCredential.model_validate({"instance_origin": KEY["instance_origin"], "auth_token": KEY["auth_token"]}).model_dump(exclude_unset=True)
    assert shaped["credential_type"] == p.TYPE and KEY["auth_token"] not in repr(p.guard(KEY))
    assert node("get_folder", folder_id=FOLDER["id"]).config.config.folder_id == FOLDER["id"]
    for bad in [1, True, None, "", ".", "..", "a\n", "x" * 257]:
        with pytest.raises(ValidationError): node("get_folder", folder_id=bad)
    for extra in ["q", "sort", "owning", "full", "page", "cursor", "path", "url", "method", "tag_id"]:
        with pytest.raises(ValidationError): node("list_folders", **{extra: "synthetic"})


@pytest.mark.asyncio
async def test_actual_factory_three_shapes_projection_and_encoded_single_segment(monkeypatch):
    calls = wire(monkeypatch)
    folder = await node("get_folder", folder_id=FOLDER["id"]).execute({})
    assert folder == {"id": FOLDER["id"], "created": 123}
    assert [c[0] for c in calls] == ["/sec/folder", "/sec/folder/" + quote(FOLDER["id"], safe=""), "/sec/folder"]
    named = await node("get_folder", folder_id=FOLDER["id"], include_names=True).execute({})
    assert named == {"id": FOLDER["id"], "created": 123, "name": FOLDER["name"]}
    calls.clear()
    tags = await node("list_tags").execute({})
    assert tags["items"] == [{"id": "tag_A", "created": -1}] and tags["catalog_count"] == 19 and tags["count"] == 1
    assert tags["has_more"] is None and tags["total"] is None and tags["completion_verified"] is False
    assert [c[0] for c in calls] == ["/sec/tag"]
    assert not ({"owner", "members", "isMember", "memberCount", "category", "created_unit"} & tags.keys())


@pytest.mark.asyncio
async def test_actual_empty_connect_evidence_is_reachability_only(monkeypatch):
    calls = wire(monkeypatch, lambda _path, _n: {"items": []})
    verdict = await validate_for_connect(credential_type=p.TYPE, credential_data={"instance_origin": KEY["instance_origin"], "auth_token": KEY["auth_token"]}, user_id="fixture")
    assert verdict.ok and verdict.credential_data["credential_type"] == p.TYPE
    evidence = await collect_evidence(node_type="automation-docspell", credential_data=KEY, user_id="fixture")
    assert evidence.reachable is True and evidence.proves == "reachability"
    assert all(path == "/sec/folder" for path, _ in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing_before", "foreign_detail", "lost_after"])
async def test_catalog_detail_catalog_access_witness_must_remain_exact(monkeypatch, case):
    def payload(path, n):
        if path == "/sec/folder": return {"items": [] if case == "missing_before" or (case == "lost_after" and n == 3) else [FOLDER]}
        return {**FOLDER, "id": "foreign"} if case == "foreign_detail" else FOLDER
    calls = wire(monkeypatch, payload)
    with pytest.raises(ValueError): await node("get_folder", folder_id=FOLDER["id"]).execute({})
    assert len(calls) == {"missing_before": 1, "foreign_detail": 2, "lost_after": 3}[case]


@pytest.mark.asyncio
async def test_local_output_and_picker_bounds_do_not_claim_completion(monkeypatch):
    rows = [{"id": f"folder_{i}", "created": i} for i in range(101)]
    calls = wire(monkeypatch, lambda _path, _n: {"items": rows})
    result = await node("list_folders").execute({})
    assert result["count"] == 100 and result["truncated"] and result["has_more"] is None and not result["completion_verified"]
    assert "catalog_count" not in result
    with pytest.raises(ValueError, match="local100"): await p.DocspellNode.load_field_options("folder_id", KEY)
    calls.clear()
    with pytest.raises(ValueError): await p.DocspellNode.load_field_options("folder_id", KEY, page_token="synthetic")
    assert calls == []
    wire(monkeypatch)
    options = await p.DocspellNode.load_field_options("folder_id", KEY, search="opaque")
    assert options == {"options": [{"value": FOLDER["id"], "label": "Folder " + FOLDER["id"]}], "next_page_token": None}


@pytest.mark.parametrize("kind,payload", [("folder", {"items": {}}), ("folder", {"items": [{"id": 1, "created": 123}]}), ("folder", {"items": [{"id": "x", "created": True}]}), ("folder", {"items": [{"id": "x"}]}), ("folder", {"items": [FOLDER, FOLDER]}), ("tag", {"items": [TAG]}), ("tag", {"count": True, "items": [TAG]}), ("tag", {"count": -1, "items": [TAG]}), ("tag", {"count": 2147483648, "items": [TAG]})])
def test_exact_selected_required_scalar_and_array_contracts(kind, payload):
    with pytest.raises(ValueError): p.result_page(payload, kind)
    good = p.result_page({"count": 0, "items": [TAG]}, "tag")
    assert good["catalog_count"] == 0 and good["count"] == 1 and good["has_more"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status,raw,mime", [(401, b'synthetic_private_error', "application/json"), (403, b'{}', "application/json"), (422, b'{}', "application/json"), (429, b'{}', "application/json"), (302, b'{}', "application/json"), (200, b'{"items":[],"items":[]}', "application/json"), (200, b'{"items":NaN}', "application/json"), (200, b'private', "text/plain"), (200, b'[]', "application/json")])
async def test_refusal_parse_and_format_are_sanitized_one_attempt(monkeypatch, status, raw, mime):
    calls = wire(monkeypatch, status=status, raw=raw, mime=mime)
    with pytest.raises(ValueError) as exc: await node("list_folders").execute({})
    assert KEY["auth_token"] not in str(exc.value) and "synthetic_private_error" not in str(exc.value) and KEY["instance_origin"] not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_closed_resource_transport_and_wrong_token_family_refuse_before_io(monkeypatch):
    calls = wire(monkeypatch)
    for resource in ["/sec/tag", "item", "user", "collective", "login", "extend", "https://other.example.test"]:
        with pytest.raises(ValueError): await p.request(p.guard(KEY), resource)
    for family in ["docspell_admin_secret", "docspell_share_token", "foreign"]:
        with pytest.raises(ValueError): await p.DocspellNode.freshen_credential({**KEY, "credential_type": family})
    assert calls == []
