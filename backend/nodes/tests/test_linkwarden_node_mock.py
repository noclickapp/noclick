"""UNRUN actual schema/factory/connect and closed wire contract fixtures.

Only synthetic origins, IDs and tokens are supplied; no vendor examples or
provider calls are used. Runtime execution requires a separate root test lane.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import httpx
import pytest
from nodes import linkwarden_node as p
from nodes.core.registry import NodeFactory
from nodes.core import connection_evidence as evidence, credential_connect as cc

KEY = {"credential_type": p.TYPE, "instance_origin": "https://instance.example.test", "access_token": "synthetic_private_token"}
COLLECTION = {"id": 7, "name": "private-collection", "isPublic": True, "createdAt": "2026-10-01T00:00:00Z", "updatedAt": "2026-10-02T00:00:00Z", "_count": {"links": 3}, "ownerId": 100, "createdById": 200, "members": [{"user": {"username": "private-user"}}], "parentId": 999, "parent": {"id": 999, "name": "private-parent"}, "url": "private-capability", "links": [{"destination": "private-destination"}]}
TAG = {"id": 11, "name": "private-tag", "createdAt": "2026-10-01T00:00:00Z", "_count": {"links": 0}, "ownerId": 100}

@pytest.fixture
def ensure_native_db_pool(): yield

def create(operation, **args):
    return NodeFactory.create_node("fixture", "automation-linkwarden", {"config": {"operation": operation, **args}, "credentials": deepcopy(KEY)})

@pytest.fixture
def wire(monkeypatch):
    state = {"calls": [], "responses": {}, "status": 200, "content": None, "headers": {"content-type": "application/json"}}
    @asynccontextmanager
    async def client(**options):
        assert options == {"timeout": 12, "follow_redirects": False, "trust_env": False, "require_public": True}
        class Client:
            @asynccontextmanager
            async def stream(self, method, url, **kwargs):
                assert method == "GET" and url.startswith(KEY["instance_origin"] + "/api/v1/")
                assert kwargs["headers"]["Authorization"] == "Bearer " + KEY["access_token"]
                assert KEY["access_token"] not in url and KEY["access_token"] not in repr(kwargs)
                assert set(kwargs) == {"headers"}  # No collection parameters or tag cursor/search/sort invented.
                endpoint = url.removeprefix(KEY["instance_origin"] + "/api/v1")
                state["calls"].append(endpoint)
                payload = state["responses"].get(endpoint, {"/collections": {"response": [COLLECTION]}, "/collections/7": {"response": COLLECTION}, "/tags": {"success": True, "message": "private-service-message", "data": {"tags": [TAG], "nextCursor": None}}}[endpoint])
                if callable(payload): payload = payload()
                yield httpx.Response(state["status"], content=state["content"] if state["content"] is not None else json.dumps(payload).encode(), headers=state["headers"], request=httpx.Request(method, url))
        yield Client()
    monkeypatch.setattr(p, "guarded_async_client", client)
    return state


def test_real_native_schema_three_discriminators_visible_token_and_picker_id_boundary():
    schema = p.LinkwardenNode.get_config_schema()
    refs = schema["properties"]["config"].get("oneOf") or schema["properties"]["config"]["anyOf"]
    actual = {schema["$defs"][r["$ref"].rsplit("/", 1)[1]]["properties"]["operation"]["const"] for r in refs}
    assert actual == p.OPERATIONS == {"list_collections", "get_collection", "list_tags"}
    visible = {k: v for k, v in KEY.items() if k != "credential_type"}
    assert p.LinkwardenAccessTokenCredential.model_validate(visible).model_dump(exclude_unset=True) == KEY
    assert KEY["access_token"] not in repr(p.guard(KEY))
    assert create("get_collection", collection_id="7").config.config.collection_id == 7
    for value in (True, False, 0, -1, 1.5, "1.5", "1e1", "07", p.MAX_ID + 1):
        with pytest.raises(ValueError): create("get_collection", collection_id=value)
    for r in refs:
        props = schema["$defs"][r["$ref"].rsplit("/", 1)[1]]["properties"]
        assert not set(props) & {"url", "method", "headers", "body", "query", "cursor", "limit", "link_id", "user_id", "parent_id", "create", "delete"}


@pytest.mark.parametrize("origin", ["http://public.example", "https://localhost", "https://127.0.0.1", "https://[::1]", "https://public.example/api/v1", "https://user:secret@public.example", "https://public.example/?token=secret", "https://public.example/#secret"])
def test_origin_refuses_private_and_disguised_authority_without_token_disclosure(origin):
    with pytest.raises(ValueError) as error: p.guard({**KEY, "instance_origin": origin})
    assert KEY["access_token"] not in str(error.value) and "secret" not in str(error.value)


@pytest.mark.asyncio
async def test_actual_manual_connect_and_empty_catalog_are_reachability_not_identity(wire, monkeypatch):
    monkeypatch.setattr(cc, "_collect_evidence", evidence.collect_evidence)
    wire["responses"]["/collections"] = {"response": []}
    verdict = await cc.validate_for_connect(credential_type="LinkwardenAccessToken", credential_data={k: v for k, v in KEY.items() if k != "credential_type"}, user_id="fixture", probe=True)
    assert verdict.ok and verdict.credential_data == KEY
    assert verdict.evidence.reachable is True and verdict.evidence.proves == "reachability"
    assert verdict.evidence.account_label is None and verdict.evidence.answers_field is None
    assert wire["calls"] == ["/collections"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", sorted(p.OPERATIONS))
async def test_actual_factory_three_reads_projection_and_independent_tag_catalog(wire, operation):
    result = await create(operation, **({"collection_id": 7} if operation == "get_collection" else {})).execute({})
    serialized = json.dumps(result)
    assert not any(s in serialized for s in (KEY["access_token"], KEY["instance_origin"], "private-", "ownerId", "createdById", "parentId", "members", "nextCursor"))
    if operation == "get_collection":
        assert result["id"] == 7 and result["linked_resource_count"] == 3
        assert wire["calls"] == ["/collections", "/collections/7", "/collections"]
    else:
        assert result["completion_verified"] is False and result["has_more"] is None and result["total"] is None
    if operation == "list_tags": assert wire["calls"] == ["/tags"]


@pytest.mark.asyncio
async def test_names_opt_in_without_user_or_parent_and_absent_optional_fields(wire):
    result = await create("get_collection", collection_id=7, include_names=True).execute({})
    assert result["name"] == "private-collection" and "parent" not in result
    assert p.record({"id": 7}, "collection", names=True) == {"id": 7}
    assert p.record({"id": 11}, "tag", names=True) == {"id": 11}


@pytest.mark.asyncio
async def test_current_catalog_detail_catalog_identity_and_access_loss(wire):
    wire["responses"]["/collections"] = {"response": []}
    with pytest.raises(ValueError, match="unavailable"): await create("get_collection", collection_id=7).execute({})
    assert wire["calls"] == ["/collections"]
    wire["calls"].clear(); wire["responses"]["/collections"] = {"response": [COLLECTION]}
    wire["responses"]["/collections/7"] = {"response": {**COLLECTION, "id": 8}}
    with pytest.raises(ValueError, match="different"): await create("get_collection", collection_id=7).execute({})
    wire["responses"]["/collections/7"] = {"response": COLLECTION}
    catalogs = iter([{"response": [COLLECTION]}, {"response": []}])
    wire["responses"]["/collections"] = lambda: next(catalogs)
    with pytest.raises(ValueError, match="access changed"): await create("get_collection", collection_id=7).execute({})


@pytest.mark.parametrize("cursor,present", [(None, True), (0, True), (0.5, True), (-2.75, True), (None, False)])
def test_number_or_null_cursor_presence_never_implies_more_or_completion(cursor, present):
    data = {"tags": [TAG], **({"nextCursor": cursor} if present else {})}
    result = p.result_page({"success": True, "data": data}, "tag")
    assert result["next_cursor_witness_returned"] is (present and cursor is not None)
    assert result["has_more"] is None and result["completion_verified"] is False
    assert "nextCursor" not in json.dumps(result) and "next_cursor" not in result


@pytest.mark.asyncio
async def test_output_cap_explicit_and_picker_refuses_silent_truncation_no_paging(wire):
    rows = [{"id": n} for n in range(1, 102)]
    wire["responses"]["/collections"] = {"response": rows}
    result = await create("list_collections").execute({})
    assert result["count"] == 100 and result["truncated"] and result["completion_verified"] is False and result["total"] is None
    with pytest.raises(ValueError, match="local100"): await p.LinkwardenNode.load_field_options("collection_id", KEY)
    wire["responses"]["/collections"] = {"response": [COLLECTION]}
    options = await p.LinkwardenNode.load_field_options("collection_id", KEY, search_query="7")
    assert options == {"options": [{"value": "7", "label": "Collection 7"}], "next_page_token": None}
    wire["calls"].clear()
    with pytest.raises(ValueError): await p.LinkwardenNode.load_field_options("collection_id", KEY, page_token="foreign")
    assert wire["calls"] == []


@pytest.mark.parametrize("kind,payload", [("collection", {"response": {"id": 7}}), ("collection", {"response": [{"id": True}]}), ("collection", {"response": [COLLECTION, COLLECTION]}), ("collection", {"response": [{**COLLECTION, "isPublic": 1}]}), ("collection", {"response": [{**COLLECTION, "_count": {"links": True}}]}), ("tag", {"response": [TAG]}), ("tag", {"success": False, "data": {"tags": [TAG]}}), ("tag", {"data": {"tags": [TAG], "nextCursor": "11"}}), ("tag", {"data": {"tags": [TAG], "nextCursor": True}})])
def test_exact_optional_scalar_and_distinct_array_object_contract(kind, payload):
    with pytest.raises(ValueError): p.result_page(payload, kind)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,content,headers", [(401, None, None), (403, None, None), (404, None, None), (429, None, None), (302, None, {"location": "http://127.0.0.1"}), (200, b'[]', None), (200, b'{"response":[],"response":[]}', None), (200, b'{"response":[NaN]}', None), (200, b'private body', {"content-type": "text/plain"})])
async def test_sanitized_refusals_parser_no_retry_and_no_refusal_identity(wire, status, content, headers):
    wire.update(status=status, content=content)
    if headers is not None: wire["headers"] = headers
    with pytest.raises(ValueError) as error: await create("list_collections").execute({})
    assert len(wire["calls"]) == 1 and KEY["access_token"] not in str(error.value) and "private body" not in str(error.value)


@pytest.mark.asyncio
async def test_local_body_cap_and_closed_route_no_query_or_deprecated_link_escape(wire):
    wire["content"] = b'x' * (p.MAX_BYTES + 1)
    with pytest.raises(ValueError): await create("list_collections").execute({})
    assert len(wire["calls"]) == 1
    wire["calls"].clear()
    for endpoint in ("/links", "/collections/7/links", "/users/me", "/tags?cursor=1", "/collections/07", "/collections/0"):
        with pytest.raises(ValueError): await p.request(p.guard(KEY), endpoint)
    assert wire["calls"] == []
