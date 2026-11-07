"""Native Planday factory/connect/dispatcher/current-row/picker fixtures.

Synthetic records and explicit MockTransport; mocks do not prove DB ACL SQL.
"""
import logging
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import planday_node as native
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.credential_connect import validate_for_connect
NT = "automation-planday"
USER = "11111111-1111-4111-8111-111111111111"
CID = "22222222-2222-4222-8222-222222222222"
TOKEN = {"credential_type": native.TYPE, "client_id": "synthetic-client", "access_token": "synthetic-access"}
PORTAL = {"id": 7, "name": "Synthetic Portal", "companyName": "Synthetic Company"}
EMPLOYEE = {"id": 91, "departments": [4], "employeeGroups": [6], "employeeTypeId": 8, "firstName": "omit-name", "email": "omit-email", "bankAccount": {"accountNumber": "omit-bank"}, "birthDate": "omit-birth", "ssn": "omit-ssn", "custom_1": {"url": "omit-capability"}, "salaryIdentifier": "omit-pay", "securityGroups": [123]}
DEPARTMENT = {"id": 4, "name": "Operations", "number": "D-4"}
SHIFT = {"id": 31, "departmentId": 4, "employeeId": 91, "date": "2026-10-01", "status": "Assigned", "timeZone": "Europe/Copenhagen", "startDateTime": "2026-10-01T09:00:00Z", "endDateTime": "2026-10-01T17:00:00Z", "comment": "omit-private", "punchClockShiftId": 44, "cost": "omit-cost"}


def paged(rows, offset=0, limit=50, total=None):
    return {"data": rows, "paging": {"offset": offset, "limit": limit, "total": len(rows) if total is None else total}}


def node(operation="get_portal_info", raw=TOKEN, **args):
    return NodeFactory.create_node(node_id="planday-fixture", node_type=NT, node_data={"config": {"operation": operation, **args}, "credentials": deepcopy(raw)}, sio=None, sid=None, user_id=USER)


@pytest.fixture(autouse=True)
def admission(monkeypatch):
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=None))


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    async def receive(request):
        assert request.url.host == "openapi.planday.com" and request.url.scheme == "https"
        assert request.method == "GET" and request.content == b""
        assert request.headers["X-ClientId"] == TOKEN["client_id"]
        assert request.headers["Authorization"] == "Bearer " + TOKEN["access_token"]
        assert TOKEN["access_token"] not in str(request.url) and not request.url.username
        calls.append(request)
        value = responses.pop(0)
        if callable(value): value = value(request)
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as client:
            yield client
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls, responses


@pytest.mark.parametrize("args", [{"limit": "50"}, {"limit": "20x"}, {"limit": 20.5}, {"limit": True}, {"limit": 0}, {"limit": 51}, {"offset": -1}, {"offset": "0"}, {"offset": 2147483648}, {"special": ["Ssn"]}, {"host": "https://evil.example.test"}])
def test_actual_factory_rejects_wrong_types_bounds_special_and_host(transport, args):
    with pytest.raises(ValueError): node("list_employees", **args)
    assert transport[0] == []


@pytest.mark.parametrize("operation,args", [("get_employee", {"employee_id": True}), ("get_department", {"department_id": "4"}), ("get_shift", {"shift_id": 31}), ("list_shifts", {"department_id": 4, "date_from": "2026-10-02", "date_to": "2026-10-01"}), ("list_shifts", {"department_id": 4, "date_from": "2026-10-01", "date_to": "2026-11-01"})])
def test_parent_and_window_refusals_are_zero_io(transport, operation, args):
    with pytest.raises(ValueError): node(operation, **args)
    assert transport[0] == []


@pytest.mark.asyncio
async def test_visible_form_connect_and_protected_portal_witness(transport):
    transport[1].append({"data": {**PORTAL, "aliases": ["omit-url"]}})
    verdict = await validate_for_connect(credential_type=native.TYPE, credential_data={"client_id": TOKEN["client_id"], "access_token": TOKEN["access_token"], "expected_portal_id": "7"}, user_id=USER)
    assert verdict.ok and verdict.credential_data["credential_type"] == native.TYPE
    assert verdict.evidence.reachable is True and verdict.evidence.account_label == PORTAL["companyName"]
    assert transport[0][0].url.path == "/portal/v1.0/info"


@pytest.mark.asyncio
async def test_direct_credential_validation_reads_protected_portal(transport):
    transport[1].append({"data": PORTAL})
    assert await native.PlandayNode.validate_credential_access(TOKEN) == (True, None)
    assert [request.url.path for request in transport[0]] == ["/portal/v1.0/info"]


@pytest.mark.asyncio
async def test_original_foreign_tag_before_factory_reconciliation_and_preparsed_execution(transport):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="foreign", node_type=NT, node_data={"config": {"operation": "get_portal_info"}, "credentials": {**TOKEN, "credential_type": "foreign"}, "credentialIds": {native.TYPE: CID}}, sio=None, sid=None)
    instance = node(); instance.node_data["credentials"]["credential_type"] = "foreign"
    with pytest.raises(ValueError): await instance.execute({})
    assert transport[0] == []


@pytest.mark.asyncio
async def test_expired_supplied_token_is_refused_without_exchange_or_provider_io(transport):
    with pytest.raises(ValueError): await node(raw={**TOKEN, "expires_at": "2000-01-01T00:00:00Z"}).execute({})
    assert transport[0] == []


@pytest.mark.asyncio
async def test_actual_dispatch_exact_lowercase_path_offset_and_safe_projection(transport):
    transport[1].append(paged([EMPLOYEE], offset=2, limit=1, total=4))
    result = await run_node_operation(node_type=NT, operation="list_employees", arguments={"offset": 2, "limit": 1}, user_id=USER, credential_data=TOKEN)
    assert transport[0][0].url.path == "/hr/v1.0/employees"
    assert dict(transport[0][0].url.params) == {"offset": "2", "limit": "1"}
    assert result["data"]["data"] == [{"id": 91, "departments": [4], "employeeGroups": [6], "employeeTypeId": 8}]
    assert result["data"]["continuation"]["next_offset_candidate"] == 3 and "omit" not in repr(result)


@pytest.mark.asyncio
async def test_each_native_resource_shape_and_unpaged_parent_relation(transport):
    transport[1].extend([paged([DEPARTMENT]), {"data": DEPARTMENT}, paged([{"id": 6, "name": "Service"}]), {"data": {"id": 6, "name": "Service"}}, {"data": EMPLOYEE}, {"data": DEPARTMENT}, {"data": [{"employeeId": 91}]}])
    cases = [("list_departments", {}), ("get_department", {"department_id": 4}), ("list_employee_groups", {}), ("get_employee_group", {"employee_group_id": 6}), ("get_employee", {"employee_id": 91}), ("list_department_employees", {"department_id": 4})]
    for operation, args in cases:
        result = await node(operation, **args).execute({})
        assert "omit" not in repr(result)
    assert [r.url.path for r in transport[0]][-2:] == ["/hr/v1.0/departments/4", "/hr/v1.0/departments/4/employees"]
    assert not transport[0][-1].url.query


@pytest.mark.asyncio
async def test_shifts_validate_department_window_and_omit_comments_punchclock(transport):
    transport[1].extend([paged([SHIFT], limit=1), {"data": SHIFT}, paged([{**SHIFT, "departmentId": 5}], limit=1), {"data": {**SHIFT, "id": 32}}])
    result = await node("list_shifts", department_id=4, date_from="2026-10-01", date_to="2026-10-01", limit=1).execute({})
    assert dict(transport[0][0].url.params) == {"offset": "0", "limit": "1", "departmentId": "4", "from": "2026-10-01", "to": "2026-10-01"}
    assert "omit" not in repr(result) and "punchClockShiftId" not in repr(result)
    await node("get_shift", department_id=4, shift_id=31).execute({})
    with pytest.raises(native.OutcomeUnverified): await node("list_shifts", department_id=4, date_from="2026-10-01", date_to="2026-10-01", limit=1).execute({})
    with pytest.raises(native.OutcomeUnverified): await node("get_shift", department_id=4, shift_id=31).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": {"id": True, "name": "Missing company"}}, {"data": []}])
async def test_no_portal_identity_from_empty_or_malformed_data(transport, payload):
    transport[1].append(payload)
    assert (await native.PlandayNode.validate_credential_access(TOKEN))[0] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [paged([EMPLOYEE, EMPLOYEE]), {"data": [EMPLOYEE], "paging": {"offset": True, "limit": 50, "total": 1}}, {"data": [EMPLOYEE], "paging": {"offset": 0, "limit": 50, "total": 0}}, {"data": [None]}, {"data": [] ,"paging": {"offset": 1, "limit": 50, "total": 0}}])
async def test_malformed_page_or_contradictory_paging_is_unverified(transport, payload):
    transport[1].append(payload)
    with pytest.raises(native.OutcomeUnverified): await node("list_employees").execute({})


@pytest.mark.asyncio
async def test_nullable_paging_is_unknown_and_documented_plain_json_supported(transport):
    transport[1].append(httpx.Response(200, json={"data": [] ,"paging": None}, headers={"Content-Type": "text/plain"}))
    result = await node("list_departments").execute({})
    assert result["data"]["paging"] is None and result["data"]["continuation"]["more_results"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(401, False), (403, False), (429, None), (500, None), (302, None)])
async def test_error_body_is_redacted_no_retry(transport, status, expected):
    transport[1].append(httpx.Response(status, json={"error": TOKEN["access_token"] + "omit-private"}))
    verdict = await native.PlandayNode.validate_credential_access(TOKEN)
    assert verdict[0] is expected and TOKEN["access_token"] not in repr(verdict) and "omit" not in repr(verdict)
    assert len(transport[0]) == 1


@pytest.fixture
def stored(monkeypatch):
    state = {"credential": deepcopy(TOKEN), "accessible": True}

    async def resolve(identifier, principal, pool, *, org_id=None, workflow_id=None):
        assert identifier == CID and principal == USER and org_id is None
        return deepcopy(state["credential"]) if state["accessible"] else None

    monkeypatch.setattr(native, "resolve_credential_with_owner_fallback", resolve)
    monkeypatch.setattr(native.Authority, "current_organization", AsyncMock(return_value=None))
    return state


@pytest.mark.asyncio
async def test_saved_execute_missing_caller_denies_cached_key(stored, transport):
    instance = NodeFactory.create_node(node_id="saved", node_type=NT, node_data={"credential_id": CID, "config": {"operation": "get_portal_info"}, "credentials": deepcopy(TOKEN)}, sio=None, sid=None)
    with pytest.raises(ValueError):
        await instance.execute({})
    assert transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["access", "kind", "key", "client_id", "expiry", "expected_portal"])
async def test_actual_saved_execute_current_row_change_discards_response(stored, transport, change):
    instance = node()
    instance.node_data.update({"credential_id": CID, "_approval_pool": object()})

    def changed(request):
        if change == "access":
            stored["accessible"] = False
        else:
            delta = {"kind": {"credential_type": "foreign"}, "key": {"access_token": "replacement"}, "client_id": {"client_id": "replacement"}, "expiry": {"expires_at": "2000-01-01T00:00:00Z"}, "expected_portal": {"expected_portal_id": "8"}}[change]
            stored["credential"].update(delta)
        return {"data": PORTAL}

    transport[1].append(changed)
    with pytest.raises(ValueError):
        await instance.execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_current_malformed_key_is_redacted_and_freshening_uses_original_current_row(stored, transport):
    current = await native.PlandayNode.freshen_credential({**TOKEN, "access_token": "stale-key"}, pool=object(), user_id=USER, credential_id=CID)
    assert current["access_token"] == TOKEN["access_token"] and isinstance(current[native.AUTH_KEY], native.Authority)
    stored["credential"] = {**TOKEN, "access_token": {"private": TOKEN["access_token"]}}
    with pytest.raises(ValueError) as captured:
        await native.Authority.create(TOKEN, pool=object(), user_id=USER, credential_id=CID)
    assert TOKEN["access_token"] not in str(captured.value) and transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [None, "authorization", "owner"])
async def test_native_workflow_fallback_rechecks_trusted_owner_scope(monkeypatch, transport, change):
    owner = "33333333-3333-4333-8333-333333333333"
    workflow = "44444444-4444-4444-8444-444444444444"
    organization = "55555555-5555-4555-8555-555555555555"
    pool = object()
    state = {"owner": owner, "authorized": True}
    loads = []


    async def fetch(identifier, principal, actual_pool, org=None):
        assert identifier == CID and org == organization
        loads.append(principal)
        return deepcopy(TOKEN) if principal == owner else None

    async def get_owner(actual_pool, actual_workflow):
        assert actual_pool is pool and actual_workflow == workflow
        return state["owner"]

    async def allowed(actual_pool, actual_workflow, identifier):
        assert actual_pool is pool and actual_workflow == workflow and identifier == CID
        return state["authorized"]

    monkeypatch.setattr("utils.credentials.get_credential", fetch)
    monkeypatch.setattr("utils.credentials.credential_lender", AsyncMock(return_value=None))
    monkeypatch.setattr("utils.credentials.get_workflow_owner_id", get_owner)
    monkeypatch.setattr("utils.credentials.is_credential_authorized_for_workflow", allowed)
    instance = NodeFactory.create_node(node_id="fallback", node_type=NT, node_data={"config": {"operation": "get_portal_info"}, "credentials": deepcopy(TOKEN), "credential_id": CID, "_approval_pool": pool}, user_id=USER, organization_id=organization, workflow_id=workflow, sio=None, sid=None)

    def during_request(request):
        if change == "authorization":
            state["authorized"] = False
        elif change == "owner":
            state["owner"] = CID
        return {"data": PORTAL}

    transport[1].append(during_request)
    if change is None:
        assert (await instance.execute({}))["data"] == PORTAL
        assert loads[:2] == [USER, owner]
    else:
        with pytest.raises(ValueError):
            await instance.execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending_approval", "rejected"])
async def test_actual_run_admission_has_zero_provider_io(monkeypatch, transport, status):
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value={"status": status, "message": "Owner review is required"}))
    result = await node().run({})
    assert result["status"] == status and transport[0] == []


@pytest.mark.asyncio
async def test_request_local_diagnostics_hide_key_search_pii_and_response_bodies(transport, caplog):
    logger = logging.getLogger("httpx")

    def observe(request):
        logger.warning("%s %s %s", request.headers["authorization"], request.url, "omit-private")
        return paged([EMPLOYEE])

    transport[1].append(observe)
    with caplog.at_level(logging.WARNING):
        await node("list_employees").execute({})
        logger.warning("Ordinary unrelated message")
    assert "Planday transport activity" in caplog.text and "Ordinary unrelated message" in caplog.text
    assert TOKEN["access_token"] not in caplog.text and "omit-private" not in caplog.text

@pytest.mark.asyncio
async def test_actual_saved_picker_actor_token_and_current_row_gate(stored, transport):
    current = await native.PlandayNode.freshen_credential(TOKEN, pool=object(), user_id=USER, credential_id=CID)
    transport[1].append(paged([DEPARTMENT]))
    result = await native.PlandayNode.load_field_options(field_name="department_id", credential_data=current, context={"_user_id": USER})
    assert result == {"options": [{"value": 4, "label": "Operations"}], "next_page_token": None}
    for values in [{"context": {"_user_id": CID}}, {"page_token": "https://evil.example.test"}, {"field_name": "salary"}]:
        with pytest.raises(ValueError):
            await native.PlandayNode.load_field_options(**{"field_name": "department_id", "credential_data": current, "context": {"_user_id": USER}, **values})
    stored["accessible"] = False
    with pytest.raises(ValueError): await native.PlandayNode.load_field_options(field_name="department_id", credential_data=current, context={"_user_id": USER})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_browser_only_credential_cannot_forge_private_picker_authority(transport):
    with pytest.raises(ValueError): await native.PlandayNode.load_field_options(field_name="department_id", credential_data={**TOKEN, native.AUTH_KEY: {}}, context={"_user_id": USER})
    assert transport[0] == []
