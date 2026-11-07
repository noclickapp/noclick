"""Exercise native factory, connect/admission, row, request and parent seams."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import httpx
import pytest
from nodes import homebase_node as hb
from nodes.core import connection_evidence as ce, credential_connect as cc, run_op
from nodes.core.registry import NodeFactory
from nodes import homebase_node as store
from repositories.credential_approvals import CredentialApprovalRepo
from utils import credentials, ssrf

TYPE, FAMILY = "automation-homebase", "homebase_api_key"
ID, USER = "00000000-0000-4000-8000-000000000042", "00000000-0000-4000-8000-000000000001"
LOC, OTHER = ID, "00000000-0000-4000-8000-000000000043"
CREDS = {"api_key": "synthetic-homebase-private-api-canary", "expected_company_name": "Fixture Company", "expected_company_owner_id": 7, "allowed_location_uuids": [LOC]}
ME = {"name": "Fixture Company", "owner": {"id": 7, "email": "private-owner-email-marker", "job": {"pin": "private-clock-marker", "wage_rate": 20}}, "capabilities": ["private-capability-marker"]}
LOCATION = {"uuid": LOC, "name": "Fixture Location", "time_zone": "America/New_York", "city": "Fixture City", "website": "private-link-marker", "phone": "private-phone-marker"}
EMPLOYEE = {"id": 42, "first_name": "Fixture", "last_name": "Employee", "email": "private-employee-email-marker", "phone": "private-phone-marker", "job": {"location_uuid": LOC, "pin": "private-clock-marker", "wage_rate": 25, "payroll_id": "private-payroll-marker", "roles": [{"wage_rate": 30}]}, "capabilities": ["private-capability-marker"]}
ARGS = {"location_uuid": LOC, "employee_id": 42}


@pytest.fixture
def ensure_native_db_pool():
    yield


def factory(op, args=None, credential=None, current=None):
    data = {"config": {"operation": op, **(args or {})}, "credentials": deepcopy(CREDS if credential is None else credential)}
    if current:
        data.update(credential_id=ID, _approval_pool=current.pool)
    return NodeFactory.create_node(node_id="homebase-fixture", node_type=TYPE, node_data=data, user_id=USER)


@pytest.fixture
async def wire(monkeypatch):
    state = SimpleNamespace(calls=[], override=None, me=deepcopy(ME), address="8.8.8.8")
    async def respond(request):
        state.calls.append(request)
        assert request.method == "GET" and request.url.scheme == "https" and request.url.host == "api.joinhomebase.com"
        assert not request.url.params and not request.url.username and request.content == b""
        assert request.headers["Authorization"] == "Bearer " + CREDS["api_key"]
        assert request.headers["Accept"] == "application/vnd.homebase-v1+json"
        if state.override:
            value = state.override(request)
            if value is not None:
                return value
        if request.url.path == "/company":
            return httpx.Response(200, json=state.me)
        if request.url.path == f"/locations/{LOC}":
            return httpx.Response(200, json=LOCATION)
        assert request.url.path == f"/locations/{LOC}/employees/42"
        return httpx.Response(200, json=EMPLOYEE)
    async def dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (state.address, 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    original = ssrf.guarded_async_client
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(hb, "guarded_async_client", client)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args", [("get_company", {}), ("list_configured_locations", {}), ("get_location", {"location_uuid": LOC}), ("get_employee", ARGS)])
async def test_actual_factory_run_four_closed_reads_and_projection(wire, op, args):
    node = factory(op, args)
    assert isinstance(node, hb.HomebaseNode)
    result = await node.run({})
    assert wire.calls[0].url.path == "/company" and result["http_status"] == 200
    for marker in (CREDS["api_key"], "private-owner", "private-employee", "private-clock", "private-payroll", "private-capability", "private-phone", "private-link"):
        assert marker not in json.dumps(result)
    if op == "get_company":
        assert result["identity_verified"] is False and result["company_identity_verified"] is False and result["reachable"] is True
    elif op == "list_configured_locations":
        assert result["configured_scope_only"] is True and result["total"] == 1 and result["next_page_token"] is None
    elif op == "get_employee":
        assert result["data"] == {"id": 42, "location_uuid": LOC, "first_name": "Fixture", "last_name": "Employee"}
        assert [r.url.path for r in wire.calls] == ["/company", f"/locations/{LOC}", f"/locations/{LOC}/employees/42"]


def test_actual_three_value_shape_config_and_native_password_schema():
    blob, errors, resolved = cc.shape_credential(FAMILY, CREDS)
    assert not errors and "credential_type" not in blob and resolved == (TYPE, hb.HomebaseApiKeyCredential)
    schema = hb.HomebaseNodeConfig.model_json_schema()
    assert len(schema["properties"]["config"]["discriminator"]["mapping"]) == 4
    assert schema["$defs"]["HomebaseApiKeyCredential"]["properties"]["api_key"]["ui:widget"] == "password"
    assert schema["$defs"]["GetEmployee"]["properties"]["location_uuid"]["x-resource-type"] == "homebase_location"
    assert schema["$defs"]["GetEmployee"]["properties"]["employee_id"]["x-resource-type"] == "homebase_employee"
    assert schema["$defs"]["GetEmployee"]["properties"]["location_uuid"]["format"] == "uuid"


@pytest.mark.parametrize("tag", [None, 42, [], {}, "foreign_api_key"])
def test_original_family_guard_before_factory_parse(tag):
    with pytest.raises(ValueError, match="native Homebase"):
        factory("get_company", credential={**CREDS, "credential_type": tag})
    assert hb.HomebaseNode.validate_config({"config": {"operation": "get_company"}, "credentials": {**CREDS, "credential_type": tag}})["valid"] is False


@pytest.mark.parametrize("args", [{"endpoint": "https://foreign.example.test"}, {"headers": {"Authorization": "foreign"}}, {"method": "POST"}, {"body": {"clock_in": True}}, {"with_note": True}, {"query": {"api_key": "foreign"}}])
def test_unknown_sidecars_cannot_change_native_read_transport(args):
    with pytest.raises(ValueError, match="configuration is invalid"):
        factory("get_company", args)


@pytest.mark.asyncio
async def test_scope_preflight_and_failed_company_stop_all_descendant_reads(wire):
    with pytest.raises(ValueError, match="explicit scope"):
        await factory("get_employee", {**ARGS, "location_uuid": OTHER}).run({})
    assert wire.calls == []
    wire.me["owner"]["id"] = 8
    with pytest.raises(ValueError, match="configured witness"):
        await factory("get_employee", ARGS).run({})
    assert len(wire.calls) == 1 and wire.calls[0].url.path == "/company"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"id": 43}, {"job": {"location_uuid": OTHER}}, {"job": None}])
async def test_employee_id_and_exact_location_response_ancestry(wire, change):
    wire.override = lambda r: httpx.Response(200, json={**EMPLOYEE, **change}) if r.url.path.endswith("/employees/42") else None
    with pytest.raises(ValueError, match="selected ID or location"):
        await factory("get_employee", ARGS).run({})


@pytest.mark.asyncio
async def test_wrong_location_stops_employee_fetch(wire):
    wire.override = lambda r: httpx.Response(200, json={**LOCATION, "uuid": OTHER}) if r.url.path == f"/locations/{LOC}" else None
    with pytest.raises(ValueError, match="selected parent"):
        await factory("get_employee", ARGS).run({})
    assert not any(r.url.path.endswith("/employees/42") for r in wire.calls)


def test_rfc5988_reduces_only_valid_current_context_to_bounded_page():
    route = f"/locations/{LOC}/employees"
    link = f'<https://api.joinhomebase.com{route}?per_page=25&with_archived=false&page=2>; rel="next", <https://api.joinhomebase.com{route}?per_page=25&with_archived=false&page=1>; rel="prev"'
    assert hb._next_page(link, route, {"per_page": "25", "with_archived": "false"}, 1) == 2
    for value in (link.replace("api.joinhomebase.com", "app.joinhomebase.com"), link.replace("https:", "http:"), link.replace(LOC, OTHER), link.replace("page=2", "page=1"), link.replace("per_page=25", "per_page=50"), link.replace("page=2", "page=2&page=3"), link.replace("page=2", "page=101"), link.replace("page=2", "page=2&api_key=private"), link.replace("api.joinhomebase.com", "api.joinhomebase.com@127.0.0.1")):
        with pytest.raises(ValueError):
            hb._next_page(value, route, {"per_page": "25", "with_archived": "false"}, 1)


@pytest.mark.asyncio
async def test_individual_resource_never_follows_next_or_guesses_collection(wire):
    wire.override = lambda r: httpx.Response(200, json=ME, headers={"Link": '<https://api.joinhomebase.com/company?page=2>; rel="next"'})
    with pytest.raises(ValueError, match="unexpectedly advertised"):
        await factory("get_company").run({})
    assert len(wire.calls) == 1
    for operation in ("list_employees", "list_shifts", "get_shift", "clock_in", "publish_shift"):
        with pytest.raises(ValueError, match="configuration is invalid"):
            factory(operation)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 202, 204, 302, 400, 401, 403, 404, 429, 500])
async def test_status_errors_no_retry_or_absence_proof(wire, status):
    wire.override = lambda r: httpx.Response(status, json={"error": "private " + CREDS["api_key"]}, headers={"location": "https://foreign.example.test/private"})
    with pytest.raises(hb.HomebaseRequestError) as error:
        await factory("get_company").run({})
    assert error.value.status == status and CREDS["api_key"] not in str(error.value)
    assert len(wire.calls) == 1 and hb.PRIVATE_REQUEST.get() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [None, [], {"error": "private-provider-marker"}, {"name": "https://private.example.test", "owner": {"id": 7}}, {"name": "Fixture Company", "owner": None}])
async def test_malformed_or_private_response_has_no_public_raw_payload(wire, body):
    wire.override = lambda r: httpx.Response(200, json=body)
    with pytest.raises(ValueError) as error:
        await factory("get_company").run({})
    assert "private-provider-marker" not in str(error.value)


@pytest.mark.asyncio
async def test_private_dns_and_freshen_does_no_provider_io(wire, monkeypatch):
    assert (await hb.HomebaseNode.freshen_credential(CREDS)).authority
    assert (await hb.HomebaseNode.validate_credential_access(CREDS))["valid"] is None and wire.calls == []
    monkeypatch.setattr(ssrf, "allow_private_hosts", lambda: False)
    wire.address = "169.254.169.254"
    with pytest.raises(ssrf.SSRFError, match="non-public address"):
        await factory("get_company").run({})
    assert wire.calls == []
class Pool:
    def __init__(self, row):
        self.row, self.calls = row, []
    def acquire(self):
        return self
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        return False
    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        return None if sql == hb.PRIMARY_ORG_SQL else self.row


@pytest.fixture
def current(monkeypatch):
    row = {"credential_type": FAMILY, "credential": "synthetic-encrypted", "revoked_at": None, "owner_id": USER, "token_version": 7, "updated_at": datetime(2026, 10, 6, tzinfo=timezone.utc), "metadata": {}, "approval_operations": [], "approval_revision": 1}
    crypto = MagicMock()
    crypto.decrypt_credential.return_value = deepcopy(CREDS)
    crypto.decrypt_credential.side_effect = lambda _: deepcopy(crypto.decrypt_credential.return_value)
    monkeypatch.setattr(store, "get_encryption", lambda: crypto)
    monkeypatch.setattr(credentials, "get_encryption", lambda: crypto)
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: crypto)
    return SimpleNamespace(row=row, pool=Pool(row), crypto=crypto)



@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"credential_type": "foreign"}, {"revoked_at": "revoked"}, {"token_version": None}, {"token_version": True}, {"approval_revision": "1"}, {"owner_id": None}, {"updated_at": None}, {"approval_operations": None}])
async def test_current_row_invalid_before_decrypt(wire, current, change):
    current.row.update(change)
    if change.get("revoked_at"):
        assert await store.load_homebase_credential(ID, USER, current.pool) is None
    else:
        with pytest.raises(ValueError):
            await store.load_homebase_credential(ID, USER, current.pool)
    current.crypto.decrypt_credential.assert_not_called()
    assert wire.calls == []


@pytest.mark.asyncio
async def test_saved_positive_binding_and_after_admission_authority_fence(wire, current, monkeypatch):
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    assert (await factory("get_company", current=current).run({}))["reachable"] is True
    wire.calls.clear()
    for change in ({"api_key": "synthetic-another-key"}, {"expected_company_owner_id": 8}, {"allowed_location_uuids": [OTHER]}):
        current.crypto.decrypt_credential.return_value = {**CREDS, **change}
        with pytest.raises(ValueError, match="binding changed"):
            await factory("get_company", current=current).run({})
    current.crypto.decrypt_credential.return_value = deepcopy(CREDS)
    async def admission(**kwargs):
        current.row["approval_revision"] += 1
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(side_effect=admission))
    with pytest.raises(ValueError, match="authority changed"):
        await factory("get_company", current=current).run({})
    assert wire.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_real_operation_admission(wire, current, monkeypatch, status):
    from utils import credential_approval
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value={"id": ID, "status": status, "new_request": False}))
    monkeypatch.setattr(credential_approval, "get_frontend_url", lambda: "https://fixture.example.test")
    result = await run_op.run_node_operation(node_type=TYPE, operation="get_company", arguments={}, user_id=USER, credential_id=ID, pool=current.pool)
    assert result["executed"] is False and wire.calls == []


@pytest.mark.asyncio
async def test_actual_connect_evidence_and_current_allowed_location_picker(wire, current, monkeypatch):
    monkeypatch.setattr(cc, "_collect_evidence", ce.collect_evidence)
    verdict = await cc.validate_for_connect(credential_type=FAMILY, credential_data=CREDS, user_id=USER, pool=current.pool)
    assert not verdict.field_errors and verdict.evidence.reachable is True
    assert verdict.evidence.account_label is None
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    result = await run_op.run_node_lookup(node_type=TYPE, field_name="location_uuid", search="Fixture", user_id=USER, credential_id=ID, pool=current.pool)
    assert result["options"] == [{"label": "Fixture Location", "value": LOC}]


@pytest.mark.asyncio
async def test_actual_socket_picker_uses_current_credential(wire, current, monkeypatch):
    from wss.handlers import workflow_handler as wh
    from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest
    from utils import credential_approval
    monkeypatch.setattr(wh, "get_encryption", lambda: current.crypto)
    monkeypatch.setattr(wh.WorkflowHandler, "get_pool", AsyncMock(return_value=current.pool))
    monkeypatch.setattr(wh, "get_user_org_context", AsyncMock(return_value=None))
    monkeypatch.setattr(credential_approval, "get_frontend_url", lambda: "https://fixture.example.test")
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    sent = AsyncMock()
    monkeypatch.setattr(wh, "send_event", sent)
    handler = wh.WorkflowHandler.__new__(wh.WorkflowHandler)
    handler.sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    await handler.load_node_options("fixture-sid", WorkflowNodeLoadOptionsRequest(request_id="homebase-fixture", node_type=TYPE, field_name="location_uuid", context={}, credential_id=ID))
    data = sent.call_args.args[2].data
    assert data["success"] is True, data
    assert data["options"][0]["value"] == LOC


@pytest.mark.asyncio
@pytest.mark.parametrize("tag", [None, 42, [], {}, "foreign"])
async def test_saved_original_kind_freshen_and_picker_reject_before_http(wire, current, tag):
    current.crypto.decrypt_credential.return_value = {**CREDS, "credential_type": tag}
    with pytest.raises(ValueError, match="current credential is invalid"):
        await store.load_homebase_credential(ID, USER, current.pool)
    for method in (hb.HomebaseNode.freshen_credential, hb.HomebaseNode.validate_credential_access):
        with pytest.raises(ValueError, match="native Homebase"):
            await method({**CREDS, "credential_type": tag})
    with pytest.raises(ValueError, match="native Homebase"):
        await hb.HomebaseNode.load_field_options("location_uuid", {**CREDS, "credential_type": tag})
    assert wire.calls == []


def test_malformed_link_query_never_echoes_private_capability():
    secret = CREDS["api_key"]
    with pytest.raises(ValueError) as error:
        hb._next_page(f'<https://api.joinhomebase.com/company?{secret}>; rel="next"', "/company", {}, 1)
    assert secret not in str(error.value) and error.value.__suppress_context__


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", ["owner", "lender", "denied"])
async def test_local_snapshot_uses_shared_workflow_authority(wire, current, monkeypatch, fallback):
    principal = "00000000-0000-4000-8000-000000000099"
    workflow = "00000000-0000-4000-8000-000000000098"
    current.row["owner_id"] = principal
    current.pool.fetchrow = AsyncMock(side_effect=lambda sql, *args: current.row if sql != hb.PRIMARY_ORG_SQL and args[1] == principal else None)
    owner = AsyncMock(return_value=principal)
    authorized = AsyncMock(return_value=fallback == "owner")
    lender = AsyncMock(return_value=principal if fallback == "lender" else None)
    resolver = AsyncMock(return_value={**CREDS, "credential_type": FAMILY})
    monkeypatch.setattr(hb, "get_workflow_owner_id", owner)
    monkeypatch.setattr(hb, "is_credential_authorized_for_workflow", authorized)
    monkeypatch.setattr(hb, "credential_lender", lender)
    monkeypatch.setattr(hb, "resolve_credential_with_owner_fallback", resolver)
    result = await hb.load_homebase_credential(ID, USER, current.pool, workflow_id=workflow)
    if fallback == "denied":
        assert result is None
        resolver.assert_not_awaited()
        current.crypto.decrypt_credential.assert_not_called()
    else:
        assert result.anchor[0] == principal
        resolver.assert_awaited_once_with(ID, USER, current.pool, org_id=None, workflow_id=workflow)
    assert wire.calls == []
