import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from nodes import goatcounter_node as fn
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation, run_node_lookup

SITE_ID = 7
CREDS = {"credential_type": "goatcounter_api_token", "api_token": "synthetic+/=token", "site_origin": "https://selected.goatcounter.com", "site_id": SITE_ID}
STAMP = datetime(2026, 10, 7, tzinfo=timezone.utc)
SITE = {"id": SITE_ID, "parent": 0, "code": "selected", "cname": "", "state": "active", "received_data": True, "created_at": "2026-10-01T00:00:00Z", "settings": {"secret": "omit"}, "setttings": {"capability": "omit"}, "user_defaults": {"email": "omit"}, "link_domain": "https://never-follow.invalid"}
DAY = {"day": "2026-10-06", "daily": 4, "hourly": [0, 1, 3], "weekly": 4, "monthly": 4, "private": "omit"}
TOTALS = {"stats": [DAY], "total": 4, "total_events": 1, "total_utc": 3, "user": {"email": "omit"}}
HIT = {"path_id": 13, "count": 4, "event": False, "max": 3, "stats": [DAY], "path": "/private-page", "title": "Private title", "ref_scheme": "h", "device": "omit", "client": "omit"}
HITS = {"hits": [HIT], "more": True, "total": 4, "secret": "omit"}
RANGE = {"site_id": SITE_ID, "start": "2026-10-06T00:00:00Z", "end": "2026-10-07T00:00:00Z"}
OPS = ["test_connection", "list_sites", "get_site", "get_total_counts", "get_hits_counts"]

@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield

class Response:
    def __init__(self, body=None, *, status=200, raw=None, mime="application/json;charset=utf-8", after=None):
        self.body, self.raw, self.status_code, self.after = body, raw, status, after
        self.headers = {"Content-Type": mime}
    async def __aenter__(self): return self
    async def __aexit__(self, *args):
        if self.after: self.after()
    async def aiter_bytes(self, chunk_size):
        assert chunk_size == 65536
        yield self.raw if self.raw is not None else json.dumps(self.body).encode("utf-8")

@pytest.fixture
def wire(monkeypatch):
    calls, responses = [], []
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, method, url, **kwargs):
            calls.append({"method": method, "url": url, **kwargs})
            logging.getLogger("httpx").info("private %s %s", url, kwargs)
            response = responses.pop(0); return response if isinstance(response, Response) else Response(response)
    def client(**kwargs):
        assert kwargs == {"timeout": 20.0, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(fn, "guarded_async_client", client)
    return SimpleNamespace(calls=calls, responses=responses)

def witness(wire, body=None):
    wire.responses.extend([{"sites": [SITE]}, SITE])
    if body is not None: wire.responses.append(body)

async def run(op, args=None, *, credential_data=None, **context):
    return await run_node_operation(node_type=fn.NODE_TYPE, operation=op, arguments=args or {}, credential_data=credential_data or CREDS, user_id="actor", **context)

def test_actual_factory_schema_and_original_saved_family():
    node = NodeFactory.create_node(node_id="native", node_type=fn.NODE_TYPE, user_id="actor", node_data={"config": {"operation": "get_hits_counts", **RANGE, "limit": "20"}, "credentials": {**CREDS, "site_id": "7"}})
    assert node.config.config.limit == 20 and node.config.credentials.site_id == SITE_ID
    defs = fn.GoatCounterNode.get_config_schema()["$defs"]
    assert sorted(d["properties"]["operation"]["const"] for d in defs.values() if "operation" in d.get("properties", {})) == sorted(OPS)
    assert defs["GoatCounterHitsConfig"]["properties"]["include_paths"]["ui:widget"] == "list"
    assert defs["GoatCounterSiteConfig"]["properties"]["site_id"]["x-resource-type"] == "goatcounter_site"
    for family in (None, "http_bearer", "goatcounter_oauth"):
        data = {"credential_id": "saved", "config": {"operation": "test_connection"}, "credentials": {**CREDS, "credential_type": family}}
        assert fn.GoatCounterNode.validate_config(data)["valid"] is False
        with pytest.raises(ValueError, match="family"): fn.GoatCounterNode.parse_config(data)

@pytest.mark.parametrize("origin", ["http://selected.goatcounter.com", "https://selected.goatcounter.com/api/v0", "https://token@selected.goatcounter.com", "https://127.0.0.1", "https://localhost", "https://stats.local", "https://www.goatcounter.com", "https://selected.goatcounter.com:444", "https://selected.goatcounter.com?token=x"])
def test_strict_single_public_https_origin(origin):
    with pytest.raises(ValueError): fn.GoatCounterNode.parse_config({"config": {"operation": "test_connection"}, "credentials": {**CREDS, "site_origin": origin}})

@pytest.mark.parametrize("change", [{"limit": True}, {"limit": "1.2"}, {"limit": 101}, {"start": "yesterday"}, {"start": "2026-10-06T00:30:00Z"}, {"end": "2026-10-06T00:00:00Z"}, {"end": "2026-12-07T00:00:00Z"}, {"include_paths": "/path"}, {"include_paths": [13]}, {"include_paths": ["13,14"]}, {"include_paths": ["../path"]}, {"include_paths": ["13", "13"]}, {"include_paths": ["13"], "exclude_paths": ["13"]}, {"group": "day"}, {"daily": True}, {"path_by_name": True}, {"url": "https://else.invalid"}])
def test_actual_closed_range_form_and_opaque_filters(change):
    with pytest.raises(ValueError): fn.GoatCounterNode.parse_config({"config": {"operation": "get_hits_counts", **RANGE, **change}, "credentials": CREDS})

@pytest.mark.asyncio
async def test_actual_connect_catalog_only_bearer_and_logging_privacy(wire, caplog):
    wire.responses.append({"sites": [SITE]})
    with caplog.at_level(logging.DEBUG): result = await run("test_connection")
    assert wire.calls == [{"method": "GET", "url": CREDS["site_origin"] + "/api/v0/sites", "params": None, "headers": {"Authorization": "Bearer " + CREDS["api_token"], "Content-Type": "application/json", "Accept": "application/json"}}]
    proof = result["data"]
    assert proof["proves"] == "reachability" and proof["origin_site_witness_verified"] is True
    assert proof["account_identity_verified"] is False and proof["user_identity_verified"] is False and proof["ownership_verified"] is False
    assert "code" not in proof["results"][0] and '"omit"' not in json.dumps(result) and "link_domain" not in json.dumps(result)
    assert CREDS["api_token"] not in caplog.text and fn._PRIVATE_REQUEST.get() is False
    logging.getLogger("httpx").warning("unrelated context"); assert "unrelated context" in caplog.text

@pytest.mark.asyncio
@pytest.mark.parametrize("sites", [[], [dict(SITE, id=8)], [dict(SITE, code="other")], [SITE, dict(SITE, id=8)], [SITE, SITE], [dict(SITE, cname="https://selected.goatcounter.com")], [dict(SITE, id=True)]])
async def test_catalog_must_uniquely_witness_selected_current_origin(wire, sites):
    wire.responses.append({"sites": sites})
    with pytest.raises(fn.GoatCounterAPIError): await run("test_connection")
    assert len(wire.calls) == 1

@pytest.mark.asyncio
async def test_custom_host_witness_fixed_credential_origin_detail_and_projection(wire):
    custom = {**CREDS, "site_origin": "https://stats.example.invalid"}; site = {**SITE, "code": "", "cname": "stats.example.invalid"}
    wire.responses.extend([{"sites": [site]}, site])
    result = await run("get_site", {"site_id": "7", "include_names": True}, credential_data=custom)
    assert result["data"]["site"]["cname"] == "stats.example.invalid" and result["data"]["returned_hosts_followed"] is False
    assert [c["url"] for c in wire.calls] == [custom["site_origin"] + "/api/v0/sites", custom["site_origin"] + "/api/v0/sites/7"]
    before = len(wire.calls)
    with pytest.raises(fn.GoatCounterAPIError, match="scope"): await run("get_site", {"site_id": 8})
    assert len(wire.calls) == before
    wire.responses.extend([{"sites": [SITE]}, {**SITE, "code": "elsewhere"}])
    with pytest.raises(fn.GoatCounterAPIError, match="detail"): await run("get_site", {"site_id": SITE_ID})

@pytest.mark.asyncio
async def test_actual_totals_wire_exact_counts_no_site_query_or_inferred_parity(wire):
    witness(wire, TOTALS); result = await run("get_total_counts", {**RANGE, "include_paths": ["13", "14"]})
    assert wire.calls[-1]["params"] == {"start": RANGE["start"], "end": RANGE["end"], "path_by_name": "false", "include_paths": "13,14"}
    assert [c["url"] for c in wire.calls] == [CREDS["site_origin"] + p for p in ["/api/v0/sites", "/api/v0/sites/7", "/api/v0/stats/total"]]
    assert result["data"]["totals"] == {"stats": [{k: DAY[k] for k in ("day", "daily", "hourly", "weekly", "monthly")}], "total": 4, "total_events": 1, "total_utc": 3}
    assert '"omit"' not in json.dumps(result) and "pageview" not in json.dumps(result)
    witness(wire, {"stats": [], "total": 0, "total_events": 0, "total_utc": 0}); assert (await run("get_total_counts", RANGE))["data"]["totals"]["stats"] == []

@pytest.mark.asyncio
async def test_hits_exact_more_exclude_paging_optin_and_empty_contract(wire):
    witness(wire, HITS); first = await run("get_hits_counts", {**RANGE, "limit": "20"})
    hit = first["data"]["hits"]
    assert hit["more"] is True and hit["total"] == 4 and hit["returned_count"] == 1 and hit["next_exclude_paths"] == ["13"]
    assert hit["global_completion_verified"] is False and "path" not in hit["hits"][0] and "ref_scheme" not in hit["hits"][0]
    witness(wire, {"hits": [{**HIT, "path_id": 14}], "more": False, "total": 4}); final = await run("get_hits_counts", {**RANGE, "exclude_paths": hit["next_exclude_paths"], "include_path_details": True})
    assert wire.calls[-1]["params"]["exclude_paths"] == "13" and final["data"]["hits"]["more"] is False and final["data"]["hits"]["hits"][0]["path"] == HIT["path"]
    witness(wire, {"hits": [], "more": False, "total": 0}); empty = await run("get_hits_counts", RANGE); assert empty["data"]["hits"]["hits"] == []

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"hits": [], "more": True, "total": 0}, {"hits": [HIT, HIT], "more": False, "total": 4}, {"hits": [dict(HIT, event=1)], "more": False, "total": 4}, {"hits": [HIT], "more": "true", "total": 4}, {"hits": [HIT], "more": False, "total": True}, {"error": "private"}, {**HITS, "status": "rejected"}])
async def test_hits_envelope_malformed_or_refused_never_success(wire, body):
    witness(wire, body)
    with pytest.raises(fn.GoatCounterAPIError): await run("get_hits_counts", RANGE)
    assert len(wire.calls) == 3

@pytest.mark.asyncio
async def test_returned_filter_ancestry_and_explicit_local_filter_cap(wire, monkeypatch):
    witness(wire, HITS)
    with pytest.raises(fn.GoatCounterAPIError): await run("get_hits_counts", {**RANGE, "exclude_paths": ["13"]})
    witness(wire, HITS)
    with pytest.raises(fn.GoatCounterAPIError): await run("get_hits_counts", {**RANGE, "include_paths": ["14"]})
    monkeypatch.setattr(fn, "MAX_FILTER_IDS", 0); witness(wire, HITS)
    result = await run("get_hits_counts", RANGE)
    assert result["data"]["hits"]["more"] is True and result["data"]["hits"]["local_filter_bound_reached"] is True and "next_exclude_paths" not in result["data"]["hits"]

@pytest.mark.asyncio
async def test_picker_only_current_selected_id_no_host_names_or_continuation(wire):
    wire.responses.append({"sites": [SITE]}); selected = await fn.GoatCounterNode.load_field_options("site_id", CREDS, context={"_user_id": "actor"}, search="7")
    assert selected == {"options": [{"value": "7", "label": "7"}], "next_page_token": None}
    before = len(wire.calls)
    for kwargs in ({"page_token": "opaque"}, {"search": "selected"}):
        with pytest.raises(ValueError): await fn.GoatCounterNode.load_field_options("site_id", CREDS, **kwargs)
    assert len(wire.calls) == before

@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["403", "429", "redirect", "mime", "utf8", "duplicate", "nan", "deep", "size"])
async def test_response_bounds_safe_errors_and_no_replay(wire, monkeypatch, case):
    bodies = {"403": Response(status=403, raw=b"private", mime="text/html"), "429": Response(status=429), "redirect": Response(status=302), "mime": Response({"sites": [SITE]}, mime="text/plain"), "utf8": Response(raw=b"\xff"), "duplicate": Response(raw=b'{"sites":[],"sites":[]}'), "nan": Response(raw=b'{"sites":[],"x":1e309}'), "deep": Response(raw=b'{"sites":[],"x":'+b'['*40+b'0'+b']'*40+b'}'), "size": Response(raw=b"x"*20)}
    if case == "size": monkeypatch.setattr(fn, "MAX_BYTES", 10)
    wire.responses.append(bodies[case])
    with pytest.raises(fn.GoatCounterAPIError) as error: await run("test_connection")
    assert CREDS["api_token"] not in str(error.value) and len(wire.calls) == 1

@pytest.mark.asyncio
async def test_saved_credential_uses_staging_resolver_and_binds_picker_actor(monkeypatch, wire):
    from utils import credentials
    resolver = AsyncMock(return_value=CREDS)
    monkeypatch.setattr(credentials, "resolve_credential_with_owner_fallback", resolver)
    pool = object()
    fresh = await fn._current_data(CREDS, pool=pool, user_id="actor", credential_id="saved", organization_id="org", workflow_id="wf")
    resolver.assert_awaited_once_with("saved", "actor", pool, org_id="org", workflow_id="wf")
    context = fn._context(fresh, {"_user_id": "actor"})
    assert context["_approval_pool"] is pool and context["_credential_id"] == "saved"
    with pytest.raises(ValueError, match="actor"):
        fn._context(fresh, {"_user_id": "other"})
    wire.responses.append({"sites": [SITE]})
    result = await fn.GoatCounterNode.load_field_options("site_id", fresh, context={"_user_id": "actor"})
    assert result["options"] == [{"value": "7", "label": "7"}]
    assert resolver.await_count > 1

@pytest.mark.asyncio
@pytest.mark.parametrize("resolved", [None, {**CREDS, "credential_type": "http_bearer"}])
async def test_saved_credential_unavailable_or_wrong_family_before_transport(monkeypatch, wire, resolved):
    from utils import credentials
    monkeypatch.setattr(credentials, "resolve_credential_with_owner_fallback", AsyncMock(return_value=resolved))
    with pytest.raises(ValueError, match="unavailable"):
        await fn._current_data(CREDS, pool=object(), user_id="actor", credential_id="saved", organization_id="org")
    assert wire.calls == []

@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"api_token": "changed-key"}, {"site_origin": "https://other.goatcounter.com"}, {"site_id": 8}])
async def test_saved_execute_rejects_changed_binding_before_transport(monkeypatch, wire, change):
    monkeypatch.setattr(fn, "_current_data", AsyncMock(return_value=fn._shape({**CREDS, **change})))
    node = NodeFactory.create_node(node_id="native", node_type=fn.NODE_TYPE, user_id="actor", node_data={"config": {"operation": "test_connection"}, "credentials": CREDS, "credential_id": "saved", "_approval_pool": object()})
    with pytest.raises(fn.GoatCounterAPIError, match="binding changed"):
        await node.execute({})
    assert wire.calls == []

@pytest.mark.asyncio
async def test_credential_change_during_response_prevents_success(monkeypatch, wire):
    state = {"data": CREDS}
    async def current(data, **context): return fn._shape(state["data"])
    monkeypatch.setattr(fn, "_current_data", current)
    wire.responses.append(Response({"sites": [SITE]}, after=lambda: state.update(data={**CREDS, "api_token": "rotated-key"})))
    with pytest.raises(fn.GoatCounterAPIError, match="changed"):
        await run("test_connection")
    assert len(wire.calls) == 1

@pytest.mark.asyncio
async def test_staging_postconnect_validation_and_connection_evidence(wire):
    from nodes.core.connection_evidence import EvidenceSample, collect_evidence
    wire.responses.append({"sites": [SITE]})
    assert await fn.GoatCounterNode.validate_credential_access(CREDS) == {"valid": True, "proves": "reachability", "account_identity_verified": False}
    wire.responses.append({"sites": []})
    assert (await fn.GoatCounterNode.validate_credential_access(CREDS))["valid"] is None
    wire.responses.append(Response(status=403))
    assert (await fn.GoatCounterNode.validate_credential_access(CREDS))["valid"] is None
    wire.responses.append({"sites": [SITE]})
    evidence = await collect_evidence(node_type=fn.NODE_TYPE, credential_data=CREDS, user_id="actor")
    assert evidence.reachable is True
    assert fn.GoatCounterNode.connection_evidence.proves == "reachability"
    assert evidence.samples == [EvidenceSample(label="7")]
