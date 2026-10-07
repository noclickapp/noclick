"""UNRUN DNSimple native factory, collector and picker contract fixtures.
Only HTTP boundaries are mocked; native execute/config and scoped selection remain real.
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
from nodes.dnsimple_node import DNSimpleNode, _credential

TYPE = "automation-dnsimple"
USER, KEY = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
RAW = {"credential_type": "dnsimple_account_token", "access_token": "synthetic-dnsimple-secret", "account_id": 11, "environment": "production"}
PARENTS = {}
DARGS, ZARGS = {"domain_id": "101"}, {"zone_name": "private.example.test"}
DOMAIN = {"id": 101, "account_id": 11, "name": ZARGS["zone_name"], "unicode_name": "PRIVATE-Unicode.example.test", "state": "hosted", "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-02T01:02:03Z", "expires_at": None, "expires_on": "2026-10-07", "registrant_id": 77, "private_whois": True, "auto_renew": True, "trustee": True, "records": [{"content": "PRIVATE"}], "url": "PRIVATE"}
ZONE = {"id": 202, "account_id": 11, "name": ZARGS["zone_name"], "active": True, "reverse": False, "secondary": False, "last_transferred_at": None, "created_at": DOMAIN["created_at"], "updated_at": DOMAIN["updated_at"], "records_count": 7, "records_limit": 1000, "records": [{"content": "PRIVATE"}], "nameservers": ["PRIVATE"], "url": "PRIVATE"}
def catalog(rows, page=1, per_page=30, total=None, pages=1):
    return {"data": deepcopy(rows), "pagination": {"current_page": page, "per_page": per_page, "total_entries": len(rows) if total is None else total, "total_pages": pages}}
ROOT, ZROOT = "/v2/11/domains", "/v2/11/zones"
DETAIL, ZDETAIL = ROOT + "/101", ZROOT + "/" + ZARGS["zone_name"]
DCAT = catalog([DOMAIN])
ROWS = {ROOT: DCAT, DETAIL: {"data": DOMAIN}, ZROOT: catalog([ZONE]), ZDETAIL: {"data": ZONE}}

@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield

@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], {}
    def handle(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host in {"api.dnsimple.com", "api.sandbox.dnsimple.com"}
        assert request.headers["Authorization"] == "Bearer " + RAW["access_token"] and request.headers["Accept"] == "application/json"
        assert not request.content and RAW["access_token"] not in str(request.url)
        path = request.url.path; assert path in ROWS
        params = dict(request.url.params)
        if path in {ROOT, ZROOT}: assert set(params) == {"page", "per_page"} and 1 <= int(params["page"]) <= 10000 and 1 <= int(params["per_page"]) <= 100
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
        assert kwargs == {"require_public": True, "timeout": 20, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance
    monkeypatch.setattr("nodes.dnsimple_node.guarded_async_client", client)
    return calls, replies

async def run(operation, **arguments):
    return await run_node_operation(node_type=TYPE, operation=operation, arguments=arguments, credential_data=deepcopy(RAW), user_id=USER)

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args", [("list_domains", {}), ("get_domain", DARGS), ("list_zones", {}), ("get_zone", ZARGS)])
async def test_actual_four_operations_envelopes_auth_parents_and_privacy(transport, operation, args):
    result = await run(operation, **args)
    assert result["status"] == "success" and result["protected_reachability_verified"]
    assert not result["principal_identity_proven"] and not result["account_ownership_proven"] and not result["snapshot_stable"] and not result["mutation_attempted"]
    rendered = json.dumps(result); assert "PRIVATE" not in rendered and ZARGS["zone_name"] not in rendered and RAW["access_token"] not in rendered
    row = result["data"][0] if isinstance(result["data"], list) else result["data"]
    assert row["account_id"] == 11 and row["created_at"] == DOMAIN["created_at"]
    if operation.endswith("domain") or operation == "list_domains": assert row["state"] == "hosted" and row["expires_at"] is None
    else:
        assert row["last_transferred_at"] is None
        assert ("records_count" in row) is (operation == "get_zone")
    if operation.startswith("list_"):
        assert result["pagination"]["total_entries"] == 1 and result["pagination_complete"] is True
        assert result["count_scope"] == "current_token_filtered_collection" and not result["global_account_coverage_proven"]

@pytest.mark.asyncio
async def test_actual_config_lens_raw_witness_empty_catalog_and_separate_sandbox(transport):
    node = NodeFactory.create_node("fixture", TYPE, {"credentials": RAW, "config": {"operation": "get_domain", **DARGS, "label": "Saved canvas", "disabled": False}}, user_id=USER)
    assert (await node.execute({}))["data"]["id"] == 101
    node.node_data["credentials"] = {**RAW, "credential_type": "foreign"}; transport[0].clear()
    with pytest.raises(ValueError): await node.execute({})
    assert not transport[0]
    transport[1][ROOT] = (200, catalog([], pages=0))
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=deepcopy(RAW))
    assert evidence.reachable is True and evidence.proves == "reachability" and not evidence.account_label
    assert "PRIVATE" not in json.dumps(asdict(evidence))
    transport[0].clear()
    assert (await run("get_domain", **DARGS))["status"] == "error"
    assert not any(r.url.path == DETAIL for r in transport[0])
    transport[1].clear(); transport[0].clear()
    result = await run_node_operation(node_type=TYPE, operation="list_domains", arguments={}, credential_data={**RAW, "environment": "sandbox"}, user_id=USER)
    assert result["status"] == "success" and all(r.url.host == "api.sandbox.dnsimple.com" for r in transport[0])

@pytest.mark.asyncio
async def test_actual_scoped_pickers_names_opt_in_and_numeric_continuation(transport):
    domain = await DNSimpleNode.load_field_options("domain_id", RAW)
    assert domain["options"][0]["value"] == "101" and domain["options"][0]["label"] == "Domain 101"
    transport[0].clear()
    assert (await DNSimpleNode.load_field_options("zone_name", RAW))["options"] == [] and not transport[0]
    zone = await DNSimpleNode.load_field_options("zone_name", RAW, context={"include_names": True})
    assert zone["options"][0]["value"] == ZARGS["zone_name"] and not zone["options"][0]["metadata"]["ownership_proven"]
    named = await run("get_domain", **DARGS, include_names=True)
    assert named["data"]["name"] == ZARGS["zone_name"] and named["data"]["unicode_name"] == DOMAIN["unicode_name"]
    transport[1][ROOT] = (200, catalog([DOMAIN], page=2, total=45, pages=2))
    picker = await DNSimpleNode.load_field_options("domain_id", RAW, page_token="2")
    assert picker["options"][0]["value"] == "101" and picker["next_page_token"] is None
    for token in ("https://PRIVATE.test", "02", "10001", True):
        with pytest.raises(ValueError): await DNSimpleNode.load_field_options("domain_id", RAW, page_token=token)

@pytest.mark.asyncio
async def test_typed_pagination_and_local_truncation_never_short_page_global_absence(transport):
    transport[1][ROOT] = (200, catalog([DOMAIN], total=45, pages=2))
    result = await run("list_domains")
    assert result["has_more"] and result["next_page_token"] == "2" and result["pagination_complete"] is False
    rows = [{**DOMAIN, "id": i + 1, "name": f"zone-{i}.example.test"} for i in range(31)]
    transport[1][ROOT] = (200, catalog(rows, total=31))
    result = await run("list_domains")
    assert len(result["data"]) == 30 and result["returned_count"] == 31 and result["local_truncated"]
    assert result["has_more"] is None and result["pagination_complete"] is None and result["next_page_token"] is None

@pytest.mark.asyncio
@pytest.mark.parametrize("path,patch", [(DETAIL, {"account_id": 12}), (DETAIL, {"id": 102}), (DETAIL, {"name": "other.example.test"}), (ZDETAIL, {"account_id": 12}), (ZDETAIL, {"id": 203}), (ZDETAIL, {"name": "other.example.test"})])
async def test_exact_current_account_id_name_detail_ancestry(transport, path, patch):
    original = DOMAIN if path == DETAIL else ZONE
    transport[1][path] = (200, {"data": {**original, **patch}})
    result = await run("get_domain" if path == DETAIL else "get_zone", **(DARGS if path == DETAIL else ZARGS))
    assert result["status"] == "error" and "data" not in result

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,path", [("get_domain", DARGS, ROOT), ("get_zone", ZARGS, ZROOT)])
async def test_current_catalog_after_read_race_discards_payload(transport, operation, args, path):
    calls, replies = transport
    replies[path] = lambda r: (200, catalog([]) if sum(c.url.path == path for c in calls) > 1 else ROWS[path])
    assert (await run(operation, **args))["status"] == "error"

@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[DOMAIN], {"data": DOMAIN}, {"data": [DOMAIN]}, catalog([{**DOMAIN, "id": True}]), catalog([{**DOMAIN, "account_id": "11"}]), catalog([{**DOMAIN, "state": "unknown"}]), catalog([{k:v for k,v in DOMAIN.items() if k != "expires_at"}]), catalog([{**DOMAIN, "created_at": 1791000000}]), {**DCAT, "pagination": {"current_page": 1, "per_page": 30, "total_entries": True, "total_pages": 1}}])
async def test_exact_catalog_wrapper_required_scalars_null_fields_and_no_fallback(transport, payload):
    transport[1][ROOT] = (200, payload)
    result = await run("list_domains")
    assert result["status"] == "error" and "data" not in result

@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [401, 402, 403, 404, 412, 429, 204, httpx.ReadTimeout("synthetic"), b"x" * (2 * 1024 * 1024 + 1), (200, DCAT, {"Content-Type": "text/plain"})])
async def test_private_errors_and_no_retry_fallback_or_link_following(transport, reply):
    calls, replies = transport
    replies[ROOT] = reply if isinstance(reply, (Exception, tuple)) else (reply, b"PRIVATE") if isinstance(reply, int) else (200, reply)
    result = await run("list_domains")
    assert result["status"] == "error" and "data" not in result and len(calls) == 1 and "PRIVATE" not in json.dumps(result)

def test_raw_family_binding_and_closed_operation_schema():
    assert _credential(RAW).account_id == 11
    for patch in ({"credential_type": "foreign"}, {"account_id": "11"}, {"account_id": True}, {"account_id": 0}, {"environment": "other"}, {"access_token": "Bearer token"}, {"refresh_token": "PRIVATE"}, {"token_version": True}):
        with pytest.raises(ValueError): _credential({**RAW, **patch})
    for field in ("environment", "account_id"):
        with pytest.raises(ValueError): _credential({k:v for k,v in RAW.items() if k != field})
    schema = DNSimpleNode.get_config_schema()
    ops = {schema["$defs"][r["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for r in schema["properties"]["config"]["oneOf"]}
    assert ops == {"list_domains", "get_domain", "list_zones", "get_zone"}
    for field in ("records", "content", "account_id", "url", "headers", "registrant_id", "auto_renew"): assert field not in schema["$defs"]["DNSimpleZoneConfig"]["properties"]

