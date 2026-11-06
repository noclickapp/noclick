"""UNRUN native factory and exact Connect HTTP contract fixtures.
Synthetic metadata contains private configuration sentinels to prove projections
and safe error handling through the real typed execute and transport seams.
"""
from copy import deepcopy
from types import SimpleNamespace
import json
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import TypeAdapter
from nodes import openstatus_node as R

USER = "00000000-0000-4000-8000-000000000001"
AUTH = {"credential_type": R.FAMILY, "api_key": "synthetic-openstatus-key"}
PAGE, MONITOR, COMPONENT, REPORT, MAINT = "page-1", "monitor-1", "component-1", "report-1", "maintenance-1"
DATE = "2026-10-07T00:00:00Z"
PRIVATE = "do-not-return-private-content"
MON = {"id": MONITOR, "name": "Synthetic monitor", "status": "MONITOR_STATUS_ACTIVE", "active": True,
    "uri": "https://private.invalid/secret", "headers": {"authorization": PRIVATE}, "body": PRIVATE, "privateLocationIds": [PRIVATE]}
PG = {"id": PAGE, "title": "Synthetic page", "published": False, "createdAt": DATE, "updatedAt": DATE,
    "password": PRIVATE, "authEmailDomains": [PRIVATE], "contactUrl": "https://private.invalid/"}
COMP = {"id": COMPONENT, "pageId": PAGE, "name": "Synthetic component", "type": "PAGE_COMPONENT_TYPE_MONITOR", "description": PRIVATE}
REP = {"id": REPORT, "title": "Synthetic report", "status": "STATUS_REPORT_STATUS_INVESTIGATING",
    "pageComponentIds": [COMPONENT], "updates": [{"message": PRIVATE}], "createdAt": DATE}
MT = {"id": MAINT, "pageId": PAGE, "title": "Synthetic maintenance", "message": PRIVATE, "pageComponentIds": [COMPONENT],
    "from": DATE, "to": "2026-10-07T01:00:00Z"}


def args(op):
    value = {"operation": op}
    if op in {"get_monitor", "get_monitor_status", "get_monitor_summary"}: value["monitor_id"] = MONITOR
    if op in {"get_status_page", "get_page_components", "get_page_overall_status", "get_page_component", "list_maintenances", "get_maintenance"}: value["page_id"] = PAGE
    if op == "get_page_component": value["component_id"] = COMPONENT
    if op == "get_status_report": value["report_id"] = REPORT
    if op == "get_maintenance": value["maintenance_id"] = MAINT
    return value


@pytest.fixture
def world(monkeypatch):
    w = SimpleNamespace(calls=[], status=200, override=None, after_request=None, count=1)
    def handler(req):
        w.calls.append(req)
        assert req.method == "POST" and req.url.host == "api.openstatus.dev" and not req.url.query
        assert req.headers["x-openstatus-key"] == AUTH["api_key"]
        assert req.headers["connect-protocol-version"] == "1" and req.headers["content-type"] == "application/json"
        name = req.url.path.rsplit("/", 1)[1]
        assert name in R.SERVICES and req.url.path == "/rpc/openstatus." + R.SERVICES[name] + "/" + name
        body = json.loads(req.content)
        fixtures = {
            "ListMonitors": {"httpMonitors": [MON], "totalSize": 1},
            "GetMonitor": {"monitor": {"http": MON}},
            "GetMonitorStatus": {"id": MONITOR, "regions": [{"region": PRIVATE, "status": "MONITOR_STATUS_ACTIVE"}]},
            "GetMonitorSummary": {"id": MONITOR, "timeRange": body.get("timeRange"), "totalSuccessful": "9007199254740993", "p99": "12"},
            "ListStatusPages": {"statusPages": [PG], "totalSize": w.count},
            "GetStatusPage": {"statusPage": PG},
            "GetStatusPageOverview": {"statusPage": PG, "components": [COMP], "configuration": {"secret": PRIVATE}},
            "GetPageComponent": {"component": COMP},
            "GetOverallStatus": {"overallStatus": "OVERALL_STATUS_OPERATIONAL",
                "componentStatuses": [{"componentId": COMPONENT, "status": "OVERALL_STATUS_OPERATIONAL"}]},
            "ListStatusReports": {"statusReports": [REP], "totalSize": 1},
            "GetStatusReport": {"statusReport": REP},
            "ListMaintenances": {"maintenances": [MT], "totalSize": 1},
            "GetMaintenance": {"maintenance": MT},
        }
        if name == "ListMaintenances": assert body["pageId"] == PAGE
        if name == "ListStatusReports": assert "pageId" not in body
        payload = deepcopy(fixtures[name])
        if w.override: payload = w.override(name, body, payload)
        if w.after_request: w.after_request(req)
        return httpx.Response(w.status, json=payload, request=req)
    transport = httpx.MockTransport(handler)
    def client(**kw):
        assert kw.pop("require_public") is True and kw["follow_redirects"] is False and kw["trust_env"] is False
        return httpx.AsyncClient(transport=transport, **kw)
    monkeypatch.setattr(R, "guarded_async_client", client)
    return w


@pytest.mark.parametrize("op", R.OPS)
def test_all_real_discriminated_operations_have_schema(op):
    value = TypeAdapter(R.OpenStatusOperation).validate_python(args(op))
    assert value.operation == op and value.include_names is False
    assert R.OpenStatusNode.get_config_schema()["properties"]["config"]
    # The actual class-body registry must use the current constructor without
    # pretending that a supplied key's permission grant has been inspected.
    registry = R.OpenStatusNode.scope_registry
    assert registry.provider == "openstatus" and registry.declared_scopes() == []
    assert registry.require(op).credential_types == (R.FAMILY,)


@pytest.mark.asyncio
@pytest.mark.parametrize("op", R.OPS)
async def test_real_factory_execute_and_exact_closed_http(world, op, monkeypatch):
    from nodes.core import registry
    monkeypatch.setattr(registry, "NODE_REGISTRY", {R.NODE_TYPE: R.OpenStatusNode})
    node = registry.NodeFactory.create_node("node", R.NODE_TYPE, {"config": args(op), "credentials": deepcopy(AUTH)},
        sio=None, sid="sid", user_id=USER)
    assert node.config.config.operation == op
    result = await node.execute({"ignored": PRIVATE})
    assert result["read_completed"] is True and result["identity_verified"] is False
    encoded = json.dumps(result)
    assert PRIVATE not in encoded and "private.invalid" not in encoded and "Synthetic" not in encoded
    assert AUTH["api_key"] not in encoded
    assert world.calls
    if op == "get_monitor_summary": assert result["data"]["totalSuccessful"] == "9007199254740993"


@pytest.mark.asyncio
async def test_heartbeat_monitors_are_listed_and_read_without_ping_capability(world):
    # The pinned v2 OpenAPI declares heartbeatMonitors in ListMonitorsResponse
    # and heartbeat in MonitorConfig; pingUrl remains private configuration.
    heartbeat = {"id": MONITOR, "name": "Nightly backup", "active": True,
        "status": "MONITOR_STATUS_ACTIVE", "period": "3600", "grace": "300",
        "pingUrl": "https://api.openstatus.dev/heartbeat/" + PRIVATE}
    def response(name, body, raw):
        if name == "ListMonitors":
            return {"heartbeatMonitors": [heartbeat], "totalSize": 1}
        if name == "GetMonitor":
            return {"monitor": {"heartbeat": heartbeat}}
        return raw
    world.override = response
    listed = await R.records(AUTH, {"operation": "list_monitors"})
    assert listed["data"] == [{"id": MONITOR, "active": True,
        "status": "MONITOR_STATUS_ACTIVE", "type": "heartbeat"}]
    assert listed["total_count"] == 1 and listed["completion_known"]
    selected = await R.records(AUTH, args("get_monitor"))
    assert selected["data"] == listed["data"][0]
    assert PRIVATE not in json.dumps([listed, selected])
    assert all("/heartbeat/" not in str(req.url) for req in world.calls)


@pytest.mark.asyncio
async def test_explicit_names_and_actual_paging_are_local_sealed_offsets(world):
    world.count = 2
    result = await R.records(AUTH, {"operation": "list_status_pages", "limit": 1, "include_names": True})
    assert result["data"][0]["name"] == "Synthetic page" and result["has_more"]
    page = result["next_page_token"]
    assert R.unseal_page(AUTH, "page", None, 1, page) == 1
    for changed, kind, parent, limit in [({**AUTH, "api_key": "changed-synthetic-key"}, "page", None, 1),
            (AUTH, "monitor", None, 1), (AUTH, "page", "other", 1), (AUTH, "page", None, 2)]:
        with pytest.raises(ValueError): R.unseal_page(changed, kind, parent, limit, page)
    result = await R.records(AUTH, {"operation": "list_status_pages", "limit": 1, "page_token": page})
    assert json.loads(world.calls[-1].content)["offset"] == 1 and result["completion_known"]
    assert all("offset" not in req.url.params for req in world.calls)


@pytest.mark.asyncio
async def test_empty_proto_json_is_reachability_not_identity(world):
    world.override = lambda *_: {}
    result = await R.records(AUTH, {"operation": "list_status_pages"})
    assert result["data"] == [] and result["total_count"] == 0 and result["identity_verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code,exc", [(401,"unauthenticated",ValueError),(403,"permission_denied",ValueError),
    (404,"not_found",ValueError),(429,"resource_exhausted",RuntimeError),(503,"unavailable",RuntimeError),
    (200,"internal",RuntimeError),(200,"unknown",RuntimeError)])
async def test_connect_errors_are_safe_and_tristate(world, status, code, exc):
    world.status = status
    world.override = lambda *_: {"code": code, "message": PRIVATE, "details": [{"debug": {"token": AUTH["api_key"]}}]}
    with pytest.raises(exc) as caught: await R.records(AUTH, {"operation": "list_status_pages"})
    assert PRIVATE not in str(caught.value) and AUTH["api_key"] not in str(caught.value)


@pytest.mark.asyncio
async def test_foreign_component_or_maintenance_parent_refuses(world):
    world.override = lambda name, body, raw: ({**raw, "component": {**COMP, "pageId": "foreign"}} if name == "GetPageComponent" else raw)
    with pytest.raises(ValueError): await R.records(AUTH, args("get_page_component"))
    world.override = lambda name, body, raw: ({"maintenances": [{**MT, "pageId": "foreign"}], "totalSize": 1} if name == "ListMaintenances" else raw)
    with pytest.raises(ValueError): await R.records(AUTH, args("list_maintenances"))


@pytest.mark.asyncio
async def test_membership_bound_inconclusive_not_absence(world):
    world.override = lambda name, body, raw: ({"statusPages": [{**PG, "id": "other-" + str(body["offset"])}], "totalSize": 10000} if name == "ListStatusPages" else raw)
    with pytest.raises(RuntimeError): await R.records(AUTH, args("get_status_page"))
    assert len(world.calls) == R.MAX_WITNESS_PAGES


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [{"statusPages": "wrong"}, {"statusPages": [PG], "totalSize": True},
    {"statusPages": [PG], "totalSize": -1}, {"statusPages": [], "totalSize": 1},
    {"statusPages": [PG, PG], "totalSize": 2}])
async def test_malformed_paging_no_false_complete(world, raw):
    world.override = lambda *_: raw
    with pytest.raises(RuntimeError): await R.records(AUTH, {"operation": "list_status_pages"})


@pytest.mark.asyncio
async def test_real_picker_generic_labels_and_parent_scope(world):
    result = await R.OpenStatusNode.load_field_options("component_id", AUTH, {"page_id": PAGE})
    assert result["options"] == [{"value": COMPONENT, "label": "Resource 1", "metadata": {"proves": "reachability", "page_id": PAGE}}]
    count = len(world.calls)
    with pytest.raises(ValueError): await R.OpenStatusNode.load_field_options("component_id", AUTH, {})
    assert len(world.calls) == count
    with pytest.raises(ValueError): await R.request(AUTH, "TriggerMonitor", {"id": MONITOR})


@pytest.mark.parametrize("value", [{**AUTH, "credential_type": "slack_oauth"}, {**AUTH, "base_url": "https://foreign.invalid"},
    {**AUTH, "api_key": "Bearer synthetic-key"}, {**AUTH, "refresh_token": "private"}])
def test_raw_foreign_or_alternate_authority_rejected(value):
    with pytest.raises(ValueError): R.OpenStatusNode.parse_config({"config": {"operation": "list_monitors"}, "credentials": value})
