"""LinkAce factory/collector/selector and response contract fixtures.
Synthetic private fixtures only; HTTP boundary mocked, native config/execute real.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict
import json
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.connection_evidence import collect_evidence
from nodes.linkace_node import LinkAceNode, _credential

TYPE = "automation-linkace"
USER, KEY = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
RAW = {"credential_type": "linkace_user_token", "access_token": "synthetic-linkace-secret", "instance_url": "https://linkace.example.test"}
PARENTS, DARGS, TARGS = {}, {"list_id": "101"}, {"tag_id": "202"}
ROOT, TROOT = "/api/v2/lists", "/api/v2/tags"
DETAIL, TDETAIL = ROOT + "/101", TROOT + "/202"
LIST = {"id": 101, "name": "PRIVATE list", "visibility": 2, "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-02T00:00:00Z", "deleted_at": None, "user_id": 9999, "description": "PRIVATE", "links": "https://PRIVATE.test/?token=PRIVATE"}
TAG = {**LIST, "id": 202, "name": "PRIVATE tag", "visibility": 3}
def catalog(rows, **metadata): return {"data": deepcopy(rows), "per_page": "20", "current_page": 1, "last_page": 1, "total": len(rows), "next_page_url": None, "prev_page_url": None, "path": "https://PRIVATE.test", **metadata}
DCAT = catalog([LIST])
ROWS = {ROOT: DCAT, DETAIL: LIST, TROOT: catalog([TAG]), TDETAIL: TAG}

@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield

@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], {}
    def handle(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "linkace.example.test"
        assert request.headers["Authorization"] == "Bearer " + RAW["access_token"] and request.headers["Accept"] == "application/json"
        assert not request.content and RAW["access_token"] not in str(request.url) and request.url.path in ROWS
        params = dict(request.url.params)
        if request.url.path in {ROOT, TROOT}: assert set(params) == {"per_page"} and 1 <= int(params["per_page"]) <= 100
        else: assert not params
        reply = replies.get(request.url.path, (200, deepcopy(ROWS[request.url.path])))
        if callable(reply): reply = reply(request)
        if isinstance(reply, Exception): raise reply
        code, payload = reply
        return httpx.Response(code, content=payload if isinstance(payload, bytes) else json.dumps(payload).encode(), headers={"Content-Type": "application/json", "Link": '<https://PRIVATE.test>; rel="next"'})
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance
    monkeypatch.setattr("nodes.linkace_node.guarded_async_client", client)
    return calls, replies

async def run(operation, **arguments):
    return await run_node_operation(node_type=TYPE, operation=operation, arguments=arguments, credential_data=deepcopy(RAW), user_id=USER)

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,identifier", [("list_lists", {}, 101), ("get_list", DARGS, 101), ("list_tags", {}, 202), ("get_tag", TARGS, 202)])
async def test_actual_four_metadata_operations_auth_envelopes_and_projection(transport, operation, args, identifier):
    result = await run(operation, **args)
    assert result["status"] == "success" and result["protected_reachability_verified"] and not result["principal_identity_proven"] and not result["instance_ownership_proven"]
    assert not result["mutation_attempted"] and not result["snapshot_stable"]
    assert "PRIVATE" not in json.dumps(result) and "user_id" not in json.dumps(result) and RAW["access_token"] not in json.dumps(result)
    row = result["data"][0] if isinstance(result["data"], list) else result["data"]
    assert row["id"] == identifier and row["deleted_at"] is None and row["created_at"] == LIST["created_at"]
    if operation.startswith("list_"): assert result["pagination"]["per_page"] == "20" and result["pagination_complete"] is True and result["next_page_token"] is None

@pytest.mark.asyncio
async def test_optional_fields_empty_reachability_config_lens_and_raw_family(transport):
    calls, replies = transport; replies[ROOT] = (200, {"data": [{"id": 101}]}); replies[DETAIL] = (200, {"id": 101})
    node = NodeFactory.create_node("fixture", TYPE, {"credentials": RAW, "config": {"operation": "get_list", **DARGS, "label": "Canvas", "disabled": False}}, user_id=USER)
    assert (await node.execute({}))["data"] == {"id": 101}
    node.node_data["credentials"] = {**RAW, "credential_type": "foreign"}; calls.clear()
    with pytest.raises(ValueError): await node.execute({})
    assert not calls
    replies[ROOT] = (200, {"data": []})
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=RAW)
    assert evidence.reachable is True and LinkAceNode.connection_evidence.proves == "reachability" and not evidence.account_label and "PRIVATE" not in json.dumps(asdict(evidence))
    assert (await run("get_list", **DARGS))["status"] == "error" and not any(r.url.path == DETAIL for r in calls)

@pytest.mark.asyncio
async def test_actual_independent_current_id_pickers_names_opt_in_and_no_continuation(transport):
    lists = await LinkAceNode.load_field_options("list_id", RAW)
    tags = await LinkAceNode.load_field_options("tag_id", RAW)
    assert lists["options"][0]["value"] == "101" and lists["options"][0]["label"] == "List 101"
    assert tags["options"][0]["value"] == "202" and tags["options"][0]["metadata"]["catalog_kind"] == "tag"
    named = await run("get_tag", **TARGS, include_names=True)
    assert named["data"]["name"] == "PRIVATE tag" and "links" not in named["data"]
    for token in ("1", "2", "https://PRIVATE.test", True):
        with pytest.raises(ValueError): await LinkAceNode.load_field_options("list_id", RAW, page_token=token)

@pytest.mark.asyncio
@pytest.mark.parametrize("meta,complete,next_present", [({}, None, None), ({"current_page": 1}, None, None), ({"current_page": 1, "last_page": 1}, True, None), ({"current_page": 1, "last_page": 1, "next_page_url": "https://PRIVATE.test"}, False, True), ({"next_page_url": "https://PRIVATE.test"}, None, True)])
async def test_exact_optional_pagination_unknown_completion_and_url_witness_veto(transport, meta, complete, next_present):
    transport[1][ROOT] = (200, {"data": [LIST], **meta})
    result = await run("list_lists")
    assert result["pagination_complete"] is complete and result.get("next_page_url_present") is next_present
    assert "PRIVATE" not in json.dumps(result) and result["next_page_token"] is None

@pytest.mark.asyncio
async def test_local_truncation_overrides_complete_and_per_page_string_not_coerced(transport):
    transport[1][ROOT] = (200, catalog([{**LIST, "id": i + 1} for i in range(21)]))
    result = await run("list_lists")
    assert len(result["data"]) == 20 and result["local_truncated"] and result["pagination_complete"] is None
    transport[1][ROOT] = (200, {"data": [LIST], "per_page": 20})
    assert (await run("list_lists"))["status"] == "error"

@pytest.mark.asyncio
@pytest.mark.parametrize("path,patch", [(DETAIL, {"id": 202}), (TDETAIL, {"id": 101}), (DETAIL, {"visibility": True}), (DETAIL, {"visibility": 4}), (DETAIL, {"created_at": None}), (DETAIL, {"id": "101"})])
async def test_exact_detail_id_visibility_optional_date_contract_no_fallback(transport, path, patch):
    transport[1][path] = (200, {**(LIST if path == DETAIL else TAG), **patch})
    assert (await run("get_list" if path == DETAIL else "get_tag", **(DARGS if path == DETAIL else TARGS)))["status"] == "error"

@pytest.mark.asyncio
async def test_after_read_independent_catalog_race_discards_detail(transport):
    calls, replies = transport
    replies[ROOT] = lambda r: (200, {"data": []} if sum(c.url.path == ROOT for c in calls) > 1 else DCAT)
    assert (await run("get_list", **DARGS))["status"] == "error"

@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [401, 403, 404, 429, 204, httpx.ReadTimeout("synthetic"), b"x" * (2 * 1024 * 1024 + 1)])
async def test_private_errors_no_retries_or_url_following(transport, reply):
    calls, replies = transport; replies[ROOT] = reply if isinstance(reply, Exception) else (reply, b"PRIVATE") if isinstance(reply, int) else (200, reply)
    result = await run("list_lists")
    assert result["status"] == "error" and len(calls) == 1 and "PRIVATE" not in json.dumps(result)

def test_raw_user_token_instance_family_and_closed_schema():
    for patch in ({"credential_type": "linkace_system_token"}, {"access_token": "Bearer token"}, {"instance_url": "https://127.0.0.1"}, {"instance_url": "https://linkace.example.test/api/v2"}, {"user_id": 9999}, {"refresh_token": "PRIVATE"}, {"token_version": True}):
        with pytest.raises(ValueError): _credential({**RAW, **patch})
    schema = LinkAceNode.get_config_schema()
    ops = {schema["$defs"][r["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for r in schema["properties"]["config"]["oneOf"]}
    assert ops == {"list_lists", "get_list", "list_tags", "get_tag"}
    for field in ("page", "order_by", "links", "url", "user_id", "headers", "search", "trash"): assert field not in schema["$defs"]["LinkAceListConfig"]["properties"]

def test_actual_agent_native_operation_catalog_and_independent_lookup_fields():
    from nodes.agent.node_op_tools import build_node_op_tools
    _, tools = build_node_op_tools(TYPE, ["list_lists", "get_list", "list_tags", "get_tag"], node_id="fixture", credential_id=KEY)
    assert set(tools) == {"linkace__list_lists", "linkace__get_list", "linkace__list_tags", "linkace__get_tag", "linkace__lookup_options"}
    lookup = tools["linkace__lookup_options"]
    assert lookup["fields"] == {"list_id": "list_id", "tag_id": "tag_id"}
    assert tools["linkace__get_list"]["lookup_fields"] == ["list_id"]
    assert tools["linkace__get_tag"]["lookup_fields"] == ["tag_id"]
