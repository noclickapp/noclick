"""UNRUN real HetrixTools factory/connect/dispatcher/current-row/socket regressions.
Synthetic MockTransport and repository fixtures do not prove provider or database access.
"""
import logging
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import hetrixtools_node as native
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.credential_connect import validate_for_connect
from nodes.hetrixtools_node import HetrixToolsCredentialAuthority as CredentialValidationRow

NT = "automation-hetrixtools"
USER = "11111111-1111-4111-8111-111111111111"
CID = "22222222-2222-4222-8222-222222222222"
MID = "0123456789abcdef0123456789abcdef"
OTHER = "123456789abcdef0123456789abcdef0"
KEY = {"credential_type": native.TYPE, "api_key": "synthetic-issued-key"}
SCOPE = {"access": "restricted", "api_calls": ["v3 Uptime Monitors", "v3 Uptime Report"], "assets": {"type": "uptime_monitors", "ids": [MID]}}
MONITOR = {"id": MID, "type": "website", "uptime_status": "up", "monitor_status": "active", "created_at": 1700000000, "last_check": 1700000010, "name": "opt-in-name", "target": "omit-URL", "resolve_address": "omit-IP", "private_notes": "omit-note", "contact_lists": ["omit-contact"], "locations": {"omit": "diagnostic"}}
UPTIME = {"percentage": 99.9, "percentage_incl_maint": 99.8, "downtimes": 1, "downtimes_incl_maint": 2}
REPORT = {"timezone": "UTC+00:00", "data": {"2026-10-01": {"uptime": UPTIME, "response_time": {"omit": "diagnostic"}, "hourly_stats": {"omit": "private"}}}, "summary": {"uptime": UPTIME}, "history": {"2026-09": {"uptime": {"percentage": 99.0, "percentage_incl_maint": 98.0}}}}
MAINTENANCE = {"id": "windowA", "monitor_id": MID, "start": "2026-10-10 10:00", "end": "2026-10-10 12:00", "timezone": "UTC", "with_notifications": False, "recurring": False, "recurring_time": 0, "recurring_time_type": "", "private": "omit-note"}


def page(envelope="monitors", items=None, *, current=1, last=1, next_page=None):
    items = [MONITOR] if items is None else items
    return {envelope: deepcopy(items), "meta": {"total": max(len(items), 10 if next_page else 0), "total_filtered": max(len(items), 10 if next_page else 0), "returned": len(items), "pagination": {"current": current, "last": last, "previous": current - 1 if current > 1 else None, "next": next_page}}}


def node(operation="list_uptime_monitors", raw=KEY, **args):
    return NodeFactory.create_node(node_id="hetrixtools-fixture", node_type=NT, node_data={"config": {"operation": operation, **args}, "credentials": deepcopy(raw)}, sio=None, sid=None, user_id=USER)


@pytest.fixture(autouse=True)
def admission(monkeypatch):
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=None))


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    async def receive(request):
        assert request.url.host == "api.hetrixtools.com" and request.url.scheme == "https"
        assert request.method == "GET" and request.content == b""
        assert request.headers["Authorization"] == "Bearer " + KEY["api_key"]
        assert not request.url.username and not request.url.password and KEY["api_key"] not in str(request.url)
        calls.append(request)
        value = responses.pop(0)
        if callable(value):
            value = value(request)
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as client:
            yield client
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls, responses


@pytest.mark.parametrize("args", [{"page": "1"}, {"page": True}, {"page": 0}, {"page": 10001}, {"per_page": "20x"}, {"per_page": 20.5}, {"per_page": 201}, {"include_names": "false"}, {"host": "https://evil.example.test"}, {"target": "private"}, {"private_notes_search": "private"}, {"operation": "ping"}, {"operation": "create_monitor"}])
def test_actual_factory_types_closed_routes_and_bounds_are_zero_io(transport, args):
    operation = args.get("operation", "list_uptime_monitors")
    with pytest.raises(ValueError):
        node(operation, **{k: v for k, v in args.items() if k != "operation"})
    assert transport[0] == []


@pytest.mark.parametrize("model,args", [(native.ListStatusPages, {"per_page": 101}), (native.GetReport, {"monitor_id": MID, "days": 31}), (native.GetReport, {"monitor_id": MID, "month": "2026-13"}), (native.ListDowntimes, {"monitor_id": MID, "start_after": 20, "start_before": 10}), (native.GetMonitor, {"monitor_id": "../private"}), (native.ListMaintenance, {}), (native.ListMonitors, {"include_names": None})])
def test_direct_native_models_refuse_malformed_values(model, args):
    with pytest.raises(ValueError):
        model.model_validate(args)


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [SCOPE, {"access": "full", "api_calls": [], "assets": None}])
async def test_actual_visible_form_connect_scope_is_not_identity(transport, scope):
    transport[1].append(scope)
    verdict = await validate_for_connect(credential_type=native.TYPE, credential_data={"api_key": KEY["api_key"]}, user_id=USER)
    assert verdict.ok and verdict.credential_data["credential_type"] == native.TYPE
    assert native.HetrixToolsNode.connection_evidence.proves == "reachability"
    assert verdict.evidence.reachable and not verdict.evidence.account_label
    allowed_labels = set(scope["api_calls"]) | set((scope["assets"] or {}).get("ids", []))
    assert {sample.label for sample in verdict.evidence.samples} <= allowed_labels
    assert [r.url.path for r in transport[0]] == ["/v3/account/api/scope"]


@pytest.mark.asyncio
async def test_foreign_original_tag_cannot_be_reconciled_or_preparsed(transport):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="foreign", node_type=NT, node_data={"config": {"operation": "get_api_scope"}, "credentials": {**KEY, "credential_type": "foreign"}, "credentialIds": {native.TYPE: CID}}, sio=None, sid=None)
    instance = node(); instance.node_data["credentials"]["credential_type"] = "foreign"
    with pytest.raises(ValueError):
        await instance.execute({})
    assert transport[0] == []


@pytest.mark.asyncio
async def test_actual_dispatch_one_page_projection_and_exact_query(transport):
    transport[1].append(page(current=2, last=3, next_page=3))
    result = await run_node_operation(node_type=NT, operation="list_uptime_monitors", arguments={"page": 2, "per_page": 20, "uptime_status": "up"}, user_id=USER, credential_data=KEY)
    assert result["data"]["items"][0]["id"] == MID
    assert "omit" not in repr(result) and "name" not in result["data"]["items"][0]
    assert result["data"]["meta"]["pagination"]["next"] == 3
    assert dict(transport[0][0].url.params) == {"page": "2", "per_page": "20", "uptime_status": "up"}
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_report_parent_and_metadata_no_hourly_or_network_diagnostics(transport):
    transport[1].extend([page(), REPORT])
    result = await node("get_uptime_report", monitor_id=MID, month="2026-10").execute({})
    assert result["data"]["monitor"]["id"] == MID and result["data"]["report"]["data"]["2026-10-01"]["uptime"] == UPTIME
    assert "omit" not in repr(result)
    assert dict(transport[0][0].url.params) == {"id": MID, "page": "1", "per_page": "1"}
    assert transport[0][1].url.path == f"/v3/uptime-monitors/{MID}/report"
    assert dict(transport[0][1].url.params) == {"month": "2026-10", "timezone": "+00:00", "hourly_stats": "false"}


@pytest.mark.asyncio
async def test_remaining_read_contracts_and_names_opt_in(transport):
    transport[1].extend([page(), page(), page("downtimes", [{"id": OTHER, "start": 1, "end": 2, "maintenance": False}]), page("status_pages", [{"id": MID, "type": "uptime", "monitors": [MID], "name": "opt-in-page", "announcement_body": "omit-note", "twitter_user": "omit-user"}]), page(), page("scheduled_maintenances", [MAINTENANCE])])
    assert (await node("get_uptime_monitor", monitor_id=MID, include_names=True).execute({}))["data"]["name"] == MONITOR["name"]
    result = await node("list_downtimes", monitor_id=MID, start_after=0, start_before=2).execute({})
    assert result["data"]["items"][0]["maintenance"] is False
    result = await node("list_status_pages", include_names=True).execute({})
    assert result["data"]["items"] == [{"id": MID, "type": "uptime", "name": "opt-in-page", "monitor_count": 1}]
    result = await node("list_scheduled_maintenance", monitor_id=MID).execute({})
    assert result["data"]["items"][0]["monitor_id"] == MID and "omit" not in repr(result)
    assert dict(transport[0][-1].url.params)["monitor_id"] == MID


@pytest.mark.asyncio
async def test_wrong_parent_and_wrong_maintenance_parent_are_refused(transport):
    transport[1].append(page(items=[{**MONITOR, "id": OTHER}]))
    with pytest.raises(native.OutcomeUnverified):
        await node("get_uptime_report", monitor_id=MID).execute({})
    assert len(transport[0]) == 1
    transport[1].extend([page(), page("scheduled_maintenances", [{**MAINTENANCE, "monitor_id": OTHER}])])
    with pytest.raises(native.OutcomeUnverified):
        await node("list_scheduled_maintenance", monitor_id=MID).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["duplicate", "count", "loop", "id_type", "oversize"])
async def test_page_shape_no_partial_truncation_or_invented_continuation(transport, mutation):
    value = page()
    if mutation == "duplicate": value = page(items=[MONITOR, MONITOR])
    if mutation == "count": value["meta"]["returned"] = 0
    if mutation == "loop": value["meta"]["pagination"]["next"] = 1
    if mutation == "id_type": value["monitors"][0]["id"] = True
    if mutation == "oversize": value = page(items=[MONITOR, {**MONITOR, "id": OTHER}])
    transport[1].append(value)
    with pytest.raises(native.OutcomeUnverified):
        await node(per_page=1 if mutation == "oversize" else 20).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("status,verdict", [(401, False), (403, False), (429, None), (500, None), (302, None), (204, None)])
async def test_401_auth_403_permission_distinct_redacted_no_retry(transport, status, verdict):
    transport[1].append(httpx.Response(status, json={"message": KEY["api_key"] + "omit-private"}))
    result = await native.HetrixToolsNode.validate_credential_access(KEY)
    assert result[0] is verdict and str(status) in result[1]
    assert KEY["api_key"] not in repr(result) and "omit" not in repr(result) and len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b'{"access":"full","access":"restricted"}', b'{"percentage":NaN}', b"not-json"])
async def test_malformed_json_is_redacted(transport, body):
    transport[1].append(httpx.Response(200, content=body, headers={"Content-Type": "application/json"}))
    with pytest.raises(native.OutcomeUnverified):
        await node("get_api_scope").execute({})


@pytest.fixture
def stored(monkeypatch):
    state = {"row": CredentialValidationRow(native.TYPE, USER, 1, datetime(2026, 10, 1, tzinfo=timezone.utc), 1, None, deepcopy(KEY)), "accessible": True}
    async def get_credential(identifier, principal, pool, org_id=None):
        assert identifier == CID and principal == USER and org_id is None
        return deepcopy(state["row"].credential) if state["accessible"] else None
    async def fetch(pool, identifier):
        assert identifier == CID
        return state["row"]
    monkeypatch.setattr("utils.credentials.get_credential", get_credential)
    monkeypatch.setattr(native, "fetch_credential_authority", fetch)
    monkeypatch.setattr(native.Authority, "current_organization", AsyncMock(return_value=None))
    monkeypatch.setattr(native, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda raw: deepcopy(raw)))
    return state


@pytest.mark.asyncio
async def test_saved_missing_caller_and_stale_original_key_refuse_before_transport(stored, transport):
    instance = NodeFactory.create_node(node_id="saved", node_type=NT, node_data={"credential_id": CID, "config": {"operation": "get_api_scope"}, "credentials": KEY}, sio=None, sid=None)
    with pytest.raises(ValueError): await instance.execute({})
    with pytest.raises(ValueError): await native.Authority.create({**KEY, "api_key": "stale"}, pool=object(), user_id=USER, credential_id=CID, organization_id=None)
    assert transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["owner", "version", "approval", "revoked", "access", "kind", "original_kind", "key"])
async def test_actual_saved_execute_discards_racing_response(stored, transport, change):
    instance = node(); instance.node_data.update({"credential_id": CID, "_approval_pool": object()})
    def changed(request):
        if change == "access": stored["accessible"] = False
        else:
            delta = {"owner": {"owner_id": CID}, "version": {"token_version": 2}, "approval": {"approval_revision": 2}, "revoked": {"revoked_at": datetime.now(timezone.utc)}, "kind": {"credential_type": "foreign"}, "original_kind": {"credential": {**KEY, "credential_type": "foreign"}}, "key": {"credential": {**KEY, "api_key": "changed"}}}[change]
            stored["row"] = replace(stored["row"], **delta)
        return page()
    transport[1].append(changed)
    with pytest.raises(ValueError): await instance.execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_saved_actor_picker_one_page_and_current_access(stored, transport):
    fresh = await native.HetrixToolsNode.freshen_credential(KEY, pool=object(), user_id=USER, credential_id=CID)
    transport[1].append(page(current=2, last=3, next_page=3))
    result = await native.HetrixToolsNode.load_field_options(field_name="monitor_id", credential_data=fresh, context={"_user_id": USER}, page_token="2")
    assert result == {"options": [{"value": MID, "label": MID}], "next_page_token": "3"}
    for args in [{"context": {"_user_id": CID}}, {"page_token": "https://evil.example.test"}, {"credential_data": {**KEY, native.AUTH_KEY: {}}}]:
        with pytest.raises(ValueError): await native.HetrixToolsNode.load_field_options(**{"field_name": "monitor_id", "credential_data": fresh, "context": {"_user_id": USER}, **args})
    stored["accessible"] = False
    with pytest.raises(ValueError): await native.HetrixToolsNode.load_field_options(field_name="monitor_id", credential_data=fresh, context={"_user_id": USER})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_local_diagnostics_hide_key_but_unrelated_logs_survive(transport, caplog):
    logger = logging.getLogger("httpx")
    def observed(request):
        logger.warning("%s %s", request.headers["authorization"], "omit-private")
        return page()
    transport[1].append(observed)
    with caplog.at_level(logging.WARNING):
        await node().execute({}); logger.warning("Ordinary unrelated message")
    assert "HetrixTools transport activity" in caplog.text and "Ordinary unrelated message" in caplog.text
    assert KEY["api_key"] not in caplog.text and "omit-private" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [None, "authorization", "owner"])
async def test_execute_workflow_owner_fallback_revalidates_trusted_scope(monkeypatch, transport, change):
    owner = "33333333-3333-4333-8333-333333333333"
    workflow = "44444444-4444-4444-8444-444444444444"
    organization = "55555555-5555-4555-8555-555555555555"
    pool = object(); state = {"owner": owner, "authorized": True}; principals = []
    row = CredentialValidationRow(native.TYPE, owner, 1, datetime(2026, 10, 1, tzinfo=timezone.utc), 1, None, deepcopy(KEY))
    async def get_credential(identifier, principal, pool, org_id=None):
        assert identifier == CID and org_id == organization
        principals.append(principal)
        return deepcopy(row.credential) if principal == owner else None
    async def get_owner(actual_pool, actual_workflow):
        assert actual_pool is pool and actual_workflow == workflow
        return state["owner"]
    async def allowed(actual_pool, actual_workflow, identifier):
        assert actual_pool is pool and actual_workflow == workflow and identifier == CID
        return state["authorized"]
    monkeypatch.setattr("utils.credentials.get_credential", get_credential)
    monkeypatch.setattr(native, "fetch_credential_authority", AsyncMock(return_value=row))
    monkeypatch.setattr("utils.credentials.credential_lender", AsyncMock(return_value=None))
    monkeypatch.setattr(native, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda raw: deepcopy(raw)))
    monkeypatch.setattr("utils.credentials.get_workflow_owner_id", get_owner)
    monkeypatch.setattr("utils.credentials.is_credential_authorized_for_workflow", allowed)
    instance = NodeFactory.create_node(node_id="fallback", node_type=NT, node_data={"config": {"operation": "list_uptime_monitors"}, "credentials": deepcopy(KEY), "credential_id": CID, "_approval_pool": pool}, user_id=USER, organization_id=organization, workflow_id=workflow, sio=None, sid=None)
    def changed(request):
        if change == "authorization": state["authorized"] = False
        if change == "owner": state["owner"] = CID
        return page()
    transport[1].append(changed)
    if change is None:
        assert (await instance.execute({}))["data"]["items"][0]["id"] == MID
        assert principals[:2] == [USER, owner]
    else:
        with pytest.raises(ValueError): await instance.execute({})
    assert len(transport[0]) == 1
