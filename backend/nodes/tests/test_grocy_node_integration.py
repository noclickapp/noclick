"""Native factory, catalog, picker, request and parser contracts.
HTTP and repository boundaries use synthetic test fixtures.
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
from nodes.grocy_node import GrocyNode, _credential

TYPE = "automation-grocy"
USER, KEY = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
RAW = {"credential_type": "grocy_api_key", "api_key": "synthetic-grocy-secret", "instance_url": "https://grocy.example.test"}
PARENTS, DARGS, TARGS = {}, {"location_id": "101"}, {"quantity_unit_id": "202"}
ROOT, TROOT = "/api/objects/locations", "/api/objects/quantity_units"
DETAIL, TDETAIL = ROOT + "/101", TROOT + "/202"
LOCATION = {"id": 101, "name": "PRIVATE location", "row_created_timestamp": "2026-01-01 01:02:03", "userfields": {"PRIVATE": "PRIVATE"}, "stock": "PRIVATE"}
UNIT = {"id": 202, "name": "PRIVATE unit", "row_created_timestamp": "raw-timestamp-not-converted", "name_plural": "PRIVATE", "plural_forms": "PRIVATE", "userfields": {"PRIVATE": "PRIVATE"}}
DCAT, TCAT = [LOCATION], [UNIT]
ROWS = {ROOT: DCAT, DETAIL: LOCATION, TROOT: TCAT, TDETAIL: UNIT}

@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield

@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], {}
    def handle(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "grocy.example.test"
        assert request.headers["GROCY-API-KEY"] == RAW["api_key"] and request.headers["Accept"] == "application/json"
        assert "Authorization" not in request.headers
        path = request.url.raw_path.split(b"?", 1)[0].decode()
        assert not request.content and RAW["api_key"] not in str(request.url) and path in ROWS
        params = dict(request.url.params)
        if path in {ROOT, TROOT}: assert set(params) == {"limit"} and 1 <= int(params["limit"]) <= 100
        else: assert not params
        reply = replies.get(path, (200, deepcopy(ROWS[path])))
        if callable(reply): reply = reply(request)
        if isinstance(reply, Exception): raise reply
        code, payload = reply
        return httpx.Response(code, content=payload if isinstance(payload, bytes) else json.dumps(payload).encode(), headers={"Content-Type": "application/json", "Link": '<https://PRIVATE.test>; rel="next"'})
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance
    monkeypatch.setattr("nodes.grocy_node.guarded_async_client", client)
    return calls, replies

async def run(operation, **arguments):
    return await run_node_operation(node_type=TYPE, operation=operation, arguments=arguments, credential_data=deepcopy(RAW), user_id=USER)

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,identifier", [("list_locations", {}, 101), ("get_location", DARGS, 101), ("list_quantity_units", {}, 202), ("get_quantity_unit", TARGS, 202)])
async def test_actual_four_operations_exact_header_bare_array_object_and_privacy(transport, operation, args, identifier):
    result = await run(operation, **args)
    assert result["status"] == "success" and result["protected_reachability_verified"] and not result["principal_identity_proven"] and not result["instance_ownership_proven"]
    assert not result["mutation_attempted"] and not result["snapshot_stable"]
    assert "PRIVATE" not in json.dumps(result) and RAW["api_key"] not in json.dumps(result)
    row = result["data"][0] if isinstance(result["data"], list) else result["data"]
    assert row == {"id": identifier, "row_created_timestamp": LOCATION["row_created_timestamp"] if identifier == 101 else UNIT["row_created_timestamp"]}
    assert type(row["id"]) is int
    if operation.startswith("list_"): assert result["pagination_complete"] is None and result["has_more"] is None and result["next_page_token"] is None

@pytest.mark.asyncio
async def test_real_factory_config_lens_optional_absence_and_empty_reachability(transport):
    calls, replies = transport; replies[ROOT] = (200, [{"id": 101}]); replies[DETAIL] = (200, {"id": 101})
    node = NodeFactory.create_node("fixture", TYPE, {"credentials": RAW, "config": {"operation": "get_location", **DARGS, "label": "Canvas", "disabled": False}}, user_id=USER)
    assert (await node.execute({}))["data"] == {"id": 101}
    node.node_data["credentials"] = {**RAW, "credential_type": "foreign"}; calls.clear()
    with pytest.raises(ValueError): await node.execute({})
    assert not calls
    replies[ROOT] = (200, [])
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=RAW)
    assert evidence.reachable is True and GrocyNode.connection_evidence.proves == "reachability" and not evidence.account_label and "PRIVATE" not in json.dumps(asdict(evidence))
    assert (await run("get_location", **DARGS))["status"] == "error" and not any(r.url.path == DETAIL for r in calls)

@pytest.mark.asyncio
async def test_real_independent_picker_decimal_values_and_opt_in_names(transport):
    locations = await GrocyNode.load_field_options("location_id", RAW)
    units = await GrocyNode.load_field_options("quantity_unit_id", RAW)
    assert locations["options"][0]["value"] == "101" and locations["options"][0]["label"] == "Location 101"
    assert units["options"][0]["value"] == "202" and units["has_more"] is None
    named = await run("get_quantity_unit", **TARGS, include_names=True)
    assert named["data"]["name"] == "PRIVATE unit" and "name_plural" not in named["data"] and "plural_forms" not in named["data"]
    assert (await run("get_location", location_id=101))["data"]["id"] == 101
    for token in ("synthetic-cursor", "https://PRIVATE.test", True):
        with pytest.raises(ValueError): await GrocyNode.load_field_options("quantity_unit_id", RAW, page_token=token)

@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", [True, 101.0, "0101", "+101", " 101", "101 ", "1e2", "101/..", 0, -1, 9007199254740992, "9007199254740992"])
async def test_picker_input_rejects_noncanonical_or_unsafe_id_before_provider(transport, identifier):
    with pytest.raises(ValueError): await run("get_location", location_id=identifier)
    assert not transport[0]

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"data": DCAT}, {"locations": DCAT}, None, {"id": 101}])
async def test_catalog_requires_bare_array_not_wrapper_or_object(transport, body):
    transport[1][ROOT] = (200, body)
    assert (await run("list_locations"))["status"] == "error"

@pytest.mark.asyncio
async def test_local_limit_truncation_and_empty_short_completion_unknown(transport):
    transport[1][ROOT] = (200, [{"id": 101}, {"id": 102}])
    result = await run("list_locations", limit=1)
    assert len(result["data"]) == 1 and result["local_truncated"] and result["pagination_complete"] is None
    for rows in ([], [{"id": 101}]):
        transport[1][ROOT] = (200, rows); result = await run("list_locations")
        assert result["pagination_complete"] is None and result["has_more"] is None and not result["global_coverage_proven"]
    transport[1][TROOT] = (200, [{"id": i} for i in range(1, 102)])
    result = await run("list_quantity_units")
    assert len(result["data"]) == 100 and result["local_truncated"] and result["pagination_complete"] is None

@pytest.mark.asyncio
@pytest.mark.parametrize("patch", [{"id": "101"}, {"id": True}, {"id": 101.0}, {"id": 202}, {"id": 9007199254740992}, {"row_created_timestamp": 1}, {"row_created_timestamp": None}])
async def test_provider_strict_integer_id_raw_timestamp_and_current_detail_refusal(transport, patch):
    transport[1][DETAIL] = (200, {**LOCATION, **patch})
    assert (await run("get_location", **DARGS))["status"] == "error"

@pytest.mark.asyncio
async def test_duplicate_catalog_or_current_membership_race_discards_detail(transport):
    calls, replies = transport; replies[ROOT] = (200, [{"id": 101}, {"id": 101}])
    assert (await run("get_location", **DARGS))["status"] == "error" and not any(r.url.path == DETAIL for r in calls)
    calls.clear(); replies[ROOT] = lambda r: (200, [] if sum(c.url.path == ROOT for c in calls) > 1 else DCAT)
    assert (await run("get_location", **DARGS))["status"] == "error"

@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [400, 401, 403, 404, 429, 500, 204, httpx.ReadTimeout("synthetic"), b"x" * (2 * 1024 * 1024 + 1)])
async def test_private_error_transport_no_retry_or_follow(transport, reply):
    calls, replies = transport; replies[ROOT] = reply if isinstance(reply, Exception) else (reply, b"PRIVATE") if isinstance(reply, int) else (200, reply)
    result = await run("list_locations")
    assert result["status"] == "error" and len(calls) == 1 and "PRIVATE" not in json.dumps(result)

def test_raw_family_closed_native_schema_and_local_bounds():
    for patch in ({"credential_type": "foreign"}, {"api_key": "Bearer token"}, {"instance_url": "https://127.0.0.1"}, {"instance_url": "https://grocy.example.test/api"}, {"user_id": 9}, {"refresh_token": "PRIVATE"}, {"token_version": True}):
        with pytest.raises(ValueError): _credential({**RAW, **patch})
    schema = GrocyNode.get_config_schema()
    ops = {schema["$defs"][r["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for r in schema["properties"]["config"]["oneOf"]}
    assert ops == {"list_locations", "get_location", "list_quantity_units", "get_quantity_unit"}
    for name in ("GrocyLocationConfig", "GrocyQuantityUnitConfig"):
        p = schema["$defs"][name]["properties"]
        assert p["limit"]["default"] == 100 and p["limit"]["minimum"] == 1 and p["limit"]["maximum"] == 100
        for field in ("page", "offset", "order", "entity", "url", "headers", "query", "userfields", "name_plural", "stock"): assert field not in p

def test_real_agent_catalog_and_independent_lookup_fields():
    from nodes.agent.node_op_tools import build_node_op_tools
    _, tools = build_node_op_tools(TYPE, ["list_locations", "get_location", "list_quantity_units", "get_quantity_unit"], node_id="fixture", credential_id=KEY)
    assert set(tools) == {"grocy__list_locations", "grocy__get_location", "grocy__list_quantity_units", "grocy__get_quantity_unit", "grocy__lookup_options"}
    assert tools["grocy__lookup_options"]["fields"] == {"location_id": "location_id", "quantity_unit_id": "quantity_unit_id"}
    assert tools["grocy__lookup_options"].get("field_dependencies", {}) == {}
