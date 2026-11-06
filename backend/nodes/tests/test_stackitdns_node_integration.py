"""real native factory/run/collector/picker fixtures; HTTP boundary only."""
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict
import json
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.connection_evidence import collect_evidence
from nodes.stackitdns_node import STACKITDNSNode, _credential

TYPE = "automation-stackitdns"
USER, KEY = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
RAW = {"credential_type": "stackitdns_access_token", "access_token": "synthetic-stackit-secret", "project_id": "project-nonuuid"}
PARENTS = {"project_id": RAW["project_id"], "zone_id": "zone-nonuuid"}
RRARGS = {**PARENTS, "rrset_id": "rrset-nonuuid"}
TIMES = {"creationStarted": "2022-01-31 10:00:00+00:00", "creationFinished": "", "updateStarted": "2022-01-31 10:00:00+00:00", "updateFinished": ""}
ZONE = {"id": PARENTS["zone_id"], "type": "primary", "state": "CREATE_SUCCEEDED", "defaultTTL": 3600, "serialNumber": 2022111400, "active": True, "isReverseZone": False, "visibility": "public", "recordCount": 3, **TIMES, "name": "PRIVATE-user-name", "dnsName": "PRIVATE.example.test", "acl": "PRIVATE", "primaryNameServer": "PRIVATE", "contactEmail": "PRIVATE", "description": "PRIVATE", "error": "PRIVATE", "extensions": {"secret": "PRIVATE"}, "labelsMap": {"secret": "PRIVATE"}}
RR = {"id": RRARGS["rrset_id"], "type": "TXT", "state": "CREATE_SUCCEEDED", "ttl": 3600, "active": True, **TIMES, "name": "PRIVATE.example.test.", "records": [{"content": "PRIVATE"}], "comment": "PRIVATE", "error": "PRIVATE"}
CATALOG = {"zones": [ZONE], "itemsPerPage": 20, "totalItems": 1, "totalPages": 1, "message": "PRIVATE"}
RRCATALOG = {"rrSets": [RR], "itemsPerPage": 20, "totalItems": 1, "totalPages": 1, "message": "PRIVATE"}
ROOT = "/v1/projects/project-nonuuid/zones"
ZPATH = ROOT + "/zone-nonuuid"
RRPATH = ZPATH + "/rrsets"
ROWS = {ROOT: CATALOG, ZPATH: {"zone": ZONE, "message": "PRIVATE"}, RRPATH: RRCATALOG, RRPATH + "/rrset-nonuuid": {"rrset": RR, "message": "PRIVATE"}}


@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], {}
    def handle(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "dns.api.stackit.cloud" and request.url.scheme == "https"
        assert request.headers["Authorization"] == "Bearer " + RAW["access_token"] and request.headers["Accept"] == "application/json"
        assert not request.content and RAW["access_token"] not in str(request.url)
        path = request.url.path; assert path in ROWS
        params = dict(request.url.params)
        if path in {ROOT, RRPATH}:
            assert set(params) == {"page", "pageSize"} and 1 <= int(params["page"]) and 1 <= int(params["pageSize"]) <= 100
        else: assert not params
        reply = replies.get(path, (200, deepcopy(ROWS[path])))
        if callable(reply): reply = reply(request)
        if isinstance(reply, Exception): raise reply
        code, payload, *extra = reply
        headers = {"Content-Type": "application/json", "Link": '<https://PRIVATE.test/?token=PRIVATE>; rel="next"'}
        if extra: headers.update(extra[0])
        return httpx.Response(code, content=payload if isinstance(payload, bytes) else json.dumps(payload).encode(), headers=headers)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance
    monkeypatch.setattr("nodes.stackitdns_node.guarded_async_client", client)
    return calls, replies


async def run(operation, **arguments):
    return await run_node_operation(node_type=TYPE, operation=operation, arguments=arguments, credential_data=deepcopy(RAW), user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args", [("list_zones", {}), ("get_zone", PARENTS), ("list_rrsets", PARENTS), ("get_rrset", RRARGS)])
async def test_actual_four_factory_operations_exact_wrappers_parents_and_projection(transport, operation, args):
    result = await run(operation, **args)
    assert result["status"] == "success" and result["protected_reachability_verified"]
    assert not result["mutation_attempted"] and not result["snapshot_stable"] and not result["principal_identity_proven"] and not result["project_ownership_proven"]
    assert all(value not in json.dumps(result) for value in ("PRIVATE", RAW["access_token"], '"records"', "content", "contactEmail", "primaryNameServer", "labelsMap", "comment", "message"))
    data = result["data"] if isinstance(result["data"], dict) else result["data"][0]
    assert data["creationFinished"] == "" and data["creationStarted"] == TIMES["creationStarted"]
    assert "projectId" not in data and "zoneId" not in data
    if "rrset" in operation: assert "recordCount" not in data and data["ttl"] == 3600
    if operation.startswith("list_"): assert result["pagination_complete"] is True and result["totalItems"] == 1


@pytest.mark.asyncio
async def test_actual_config_lens_raw_witness_and_honest_collector(transport):
    node = NodeFactory.create_node("fixture", TYPE, {"credentials": RAW, "config": {"operation": "get_zone", **PARENTS, "label": "Saved canvas", "disabled": False}}, user_id=USER)
    assert (await node.execute({}))["data"]["id"] == PARENTS["zone_id"]
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=deepcopy(RAW))
    assert evidence.reachable is True and STACKITDNSNode.connection_evidence.proves == "reachability" and not evidence.account_label
    assert "PRIVATE" not in json.dumps(asdict(evidence))
    node.node_data["credentials"] = {**RAW, "credential_type": "foreign"}; transport[0].clear()
    with pytest.raises(ValueError): await node.execute({})
    assert not transport[0]


@pytest.mark.asyncio
async def test_empty_project_catalog_reachability_not_actor_or_zone_absence(transport):
    calls, replies = transport; replies[ROOT] = (200, {"zones": [], "itemsPerPage": 20, "totalItems": 0, "totalPages": 0})
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=RAW)
    assert evidence.reachable is True and not evidence.account_label
    assert (await run("get_zone", **PARENTS))["status"] == "error"
    assert not any(r.url.path == ZPATH for r in calls)
    picker = await STACKITDNSNode.load_field_options("project_id", RAW)
    assert picker["options"][0]["value"] == RAW["project_id"] and picker["options"][0]["metadata"]["binding_source"] == "supplied_project"


@pytest.mark.asyncio
async def test_scoped_picker_numeric_pages_and_names_opt_in(transport):
    calls, replies = transport
    for field, context, token in (("zone_id", {"project_id": "foreign"}, None), ("rrset_id", {}, None), ("zone_id", {}, "https://PRIVATE.test"), ("zone_id", {}, "0")):
        with pytest.raises(ValueError): await STACKITDNSNode.load_field_options(field, RAW, context=context, page_token=token)
    assert not calls
    picker = await STACKITDNSNode.load_field_options("zone_id", RAW)
    assert picker["options"][0]["label"] == PARENTS["zone_id"]
    replies[ROOT] = (200, {**CATALOG, "totalItems": 99, "totalPages": 8})
    picker = await STACKITDNSNode.load_field_options("zone_id", RAW, context={"include_names": True}, page_token="2")
    assert picker["options"][0]["label"] == ZONE["dnsName"] and picker["next_page_token"] == "3"
    assert calls[-1].url.params["page"] == "2"
    assert (await run("get_rrset", **RRARGS, include_names=True))["data"]["name"] == RR["name"]


@pytest.mark.asyncio
async def test_catalog_detail_rrset_membership_and_after_read_ancestry_race(transport):
    calls, replies = transport
    assert (await run("list_zones", project_id="foreign"))["status"] == "error" and not calls
    replies[ZPATH] = (200, {"zone": {**ZONE, "id": "foreign"}})
    assert (await run("list_rrsets", **PARENTS))["status"] == "error"
    assert not any(r.url.path == RRPATH for r in calls)
    replies.clear(); replies[RRPATH + "/rrset-nonuuid"] = (200, {"rrset": {**RR, "id": "foreign"}})
    assert (await run("get_rrset", **RRARGS))["status"] == "error"
    calls.clear(); replies.clear()
    def changed(request): return 200, {**RRCATALOG, "rrSets": [] if sum(r.url.path == RRPATH for r in calls) >= 2 else [RR]}
    replies[RRPATH] = changed
    assert (await run("get_rrset", **RRARGS))["status"] == "error"
    assert all(r.url.host == "dns.api.stackit.cloud" for r in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"zone": ZONE}, {**CATALOG, "totalItems": True}, {**CATALOG, "zones": [ZONE] * 21}, {**CATALOG, "zones": [{**ZONE, "defaultTTL": 59}]}, {**CATALOG, "zones": [{**ZONE, "creationStarted": None}]}, {**CATALOG, "zones": [{**ZONE, "active": 1}]}, {**CATALOG, "zones": [{**ZONE, "id": "../zone"}]}])
async def test_route_specific_wrappers_scalar_and_page_bounds(transport, payload):
    transport[1][ROOT] = (200, payload)
    result = await run("list_zones")
    assert result["status"] == "error" and "data" not in result and len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [401, 403, 404, 429, 204, httpx.ReadTimeout("synthetic"), b"x" * (2 * 1024 * 1024 + 1), (200, CATALOG, {"Content-Type": "text/plain"})])
async def test_private_errors_transport_bounds_and_no_retry_links(transport, reply):
    calls, replies = transport
    replies[ROOT] = reply if isinstance(reply, (Exception, tuple)) else (reply, b"PRIVATE") if isinstance(reply, int) else (200, reply)
    result = await run("list_zones")
    assert result["status"] == "error" and "data" not in result and len(calls) == 1 and "PRIVATE" not in json.dumps(result)
    if reply == 404: assert "missing-or-invisible" in result["error"]


def test_raw_family_safe_string_ids_and_four_native_schema_operations():
    assert _credential(RAW).project_id == "project-nonuuid"
    for patch in ({"credential_type": "foreign"}, {"project_id": "../project"}, {"access_token": "Bearer secret"}, {"host": "evil.test"}, {"refresh_token": "secret"}, {"token_version": True}):
        with pytest.raises(ValueError): _credential({**RAW, **patch})
    schema = STACKITDNSNode.get_config_schema()
    ops = {schema["$defs"][r["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for r in schema["properties"]["config"]["oneOf"]}
    assert ops == {"list_zones", "get_zone", "list_rrsets", "get_rrset"}
    for field in ("records", "RDATA", "comment", "acl", "labels", "url", "body", "orderBy", "dnsName[eq]"): assert field not in schema["$defs"]["STACKITDNSRRSetConfig"]["properties"]


@pytest.mark.asyncio
async def test_staging_guarded_client_with_native_request(monkeypatch):
    from unittest.mock import AsyncMock
    from utils.ssrf import guarded_async_client
    guard = AsyncMock()
    monkeypatch.setattr("utils.ssrf.assert_url_allowed", guard)
    calls = []
    def handle(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "dns.api.stackit.cloud"
        assert request.headers["Authorization"] == "Bearer " + RAW["access_token"]
        return httpx.Response(200, json=CATALOG)
    def client(**kwargs):
        return guarded_async_client(**kwargs, transport=httpx.MockTransport(handle))
    monkeypatch.setattr("nodes.stackitdns_node.guarded_async_client", client)
    result = await run("list_zones")
    assert result["status"] == "success" and len(calls) == 1
    guard.assert_awaited_once_with(str(calls[0].url))
