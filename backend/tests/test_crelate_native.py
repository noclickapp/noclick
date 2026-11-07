"""Offline Crelate factory, saved-credential, admission and wire regressions.

Synthetic responses exercise staging's credential and request paths without
claiming provider-authored conformance evidence or making live API calls.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlencode

import httpx
import pytest
from nodes import crelate_node as cr
from nodes.core import connection_evidence as ce, credential_connect as cc, run_op
from nodes.core.registry import NodeFactory
from repositories.credential_approvals import CredentialApprovalRepo
from utils import credentials, ssrf

TYPE, FAMILY = "automation-crelate", "crelate_api_key"
ID, USER = "00000000-0000-4000-8000-000000000042", "00000000-0000-4000-8000-000000000001"
CURRENT_USER = "00000000-0000-4000-8000-000000000007"
CONTACT_ID, COMPANY_ID, JOB_ID, NOTE_ID, TASK_ID = [f"00000000-0000-4000-8000-{n:012}" for n in (10, 20, 30, 40, 50)]
CREDS = {"api_key": "synthetic-crelate-key-canary", "expected_organization_name": "fixture-org", "expected_user_id": CURRENT_USER}
PARENT = {"Id": CONTACT_ID, "EntityName": "FixtureContactEntity"}  # Supplied value, not a claim about provider naming.
COMMON = {"CreatedById": {"Id": CURRENT_USER, "Title": "private-creator-title"}, "Owners": [{"Id": CURRENT_USER, "IsPrimary": True, "Title": "private-owner-title"}]}
ROWS = {
    "contacts": {**COMMON, "Id": CONTACT_ID, "FirstName": "Fixture", "LastName": "Contact", "Name": "Fixture Contact", "EmailAddresses_Home": {"Value": "private@example.test"}, "BirthDate": "private-birth", "Compensation": "private-finance"},
    "companies": {**COMMON, "Id": COMPANY_ID, "Name": "Fixture Company", "Description": "private-company-description"},
    "jobs": {**COMMON, "Id": JOB_ID, "Name": "Fixture Job", "AccountId": {"Id": COMPANY_ID, "Title": "private-parent-title"}, "PayrollType": "private-payroll"},
    "notes": {**COMMON, "Id": NOTE_ID, "ParentId": PARENT, "Display": "private-note-content", "Announced": False},
    "tasks": {**COMMON, "Id": TASK_ID, "ParentId": PARENT, "Display": "private-task-content", "Announced": False, "When": "2026-10-08T12:00:00+00:00"},
}


@pytest.fixture
def ensure_native_db_pool():
    yield


def factory(op, args=None, credential=None, current=None):
    data = {"config": {"operation": op, **(args or {})}, "credentials": deepcopy(CREDS if credential is None else credential)}
    if current:
        data.update(credential_id=ID, _approval_pool=current.pool)
    return NodeFactory.create_node(node_id="crelate-fixture", node_type=TYPE, node_data=data, user_id=USER)


def envelope(data, *, metadata=None, errors=None, status=200):
    return httpx.Response(status, json={"Data": data, "Errors": errors or [], "Metadata": metadata or {"CorrelationId": ID, "TimeStamp": "2026-10-06T00:00:00Z", "Url": "private-response-url", "Verb": "GET", "Links": None, "MoreRecords": False}})


@pytest.fixture
async def wire(monkeypatch):
    state = SimpleNamespace(calls=[], override=None, user=CURRENT_USER, org="fixture-org", address="8.8.8.8", rows=deepcopy(ROWS))
    def respond(request):
        state.calls.append(request)
        assert request.url.host == "app.crelate.com" and request.url.scheme == "https"
        assert CREDS["api_key"] not in str(request.url)
        assert request.headers["X-Api-Key"] == CREDS["api_key"] and "Authorization" not in request.headers
        assert request.url.params["validation"] == "strict"
        if state.override:
            result = state.override(request)
            if result is not None:
                return result
        path = request.url.path
        if path == "/api3/users/self":
            return envelope({"Id": state.user, "FullName": "Fixture User", "Email": "private@example.test", "PayrollOnboardStatus": 7})
        if path == "/api3/organizations/self":
            return envelope({"Name": state.org, "DisplayName": "Fixture Organization", "TimezoneId": {"Id": ID}, "UndocumentedSecret": CREDS["api_key"]})
        kind = path.split("/")[2]
        if path.endswith("/info"):
            return envelope({"Fields": {name: {"DisplayName": name, "Type": "string", "IsEncrypted": False, "ValidFor": ["read", "create", "update", "sort"], "ValueMaskingMode": 0, "Values": [{"Id": ID, "Title": "private-picklist-value"}]} for name in set(cr.PUBLIC[kind]) | cr.WRITE[kind]}, "CustomFields": {"PrivateCustom": {"Values": [CREDS["api_key"]]}}})
        if request.method in {"POST", "PATCH"}:
            entity = json.loads(request.content)["entity"]
            state.rows[kind].update(entity)
            return envelope(state.rows[kind]["Id"] if request.method == "POST" else True)
        if request.method == "DELETE":
            return envelope(True)
        if path.count("/") == 3:
            return envelope(state.rows[kind])
        return envelope([state.rows[kind]])
    async def dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (state.address, 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    original = ssrf.guarded_async_client
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(cr, "guarded_async_client", client)
    return state


CONTACT_ARGS = {"first_name": "Fixture", "last_name": "Contact"}
COMPANY_ARGS = {"name": "Fixture Company"}
JOB_ARGS = {"company_id": COMPANY_ID, "name": "Fixture Job"}
PARENT_ARGS = {"contact_id": CONTACT_ID, "parent_entity_name": PARENT["EntityName"]}
NOTE_ARGS = {**PARENT_ARGS, "display": "Fixture Note"}
TASK_ARGS = {**PARENT_ARGS, "display": "Fixture Task", "when": "2026-10-08T12:00:00Z"}
CASES = [("get_self", {}, "/organizations/self", "GET"), ("get_organization", {}, "/organizations/self", "GET"),
    ("contact_info", {}, "/contacts/info", "GET"), ("company_info", {}, "/companies/info", "GET"), ("job_info", {}, "/jobs/info", "GET")]
for singular, kind, target, create, parent in [
    ("contact", "contacts", CONTACT_ID, CONTACT_ARGS, {}), ("company", "companies", COMPANY_ID, COMPANY_ARGS, {}),
    ("job", "jobs", JOB_ID, JOB_ARGS, {"company_id": COMPANY_ID}),
    ("note", "notes", NOTE_ID, NOTE_ARGS, PARENT_ARGS), ("task", "tasks", TASK_ID, TASK_ARGS, PARENT_ARGS)]:
    CASES.extend([("list_" + kind, parent, "/" + kind, "GET"),
        ("get_" + singular, {**parent, singular + "_id": target}, "/" + kind + "/" + target, "GET"),
        ("create_" + singular, create, "/" + kind, "POST"),
        ("update_" + singular, {**create, singular + "_id": target}, "/" + kind + "/" + target, "PATCH"),
        ("delete_" + singular, {**parent, singular + "_id": target}, "/" + kind + "/" + target, "DELETE")])


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args,path,method", CASES)
async def test_actual_factory_run_dispatch_transport_and_receipts(wire, op, args, path, method):
    node = factory(op, args)
    assert isinstance(node, cr.CrelateNode)
    result = await node.run({})
    assert result["organization_name"] == "fixture-org"
    assert any(r.url.path == "/api3" + path and r.method == method for r in wire.calls)
    for private in (CREDS["api_key"], "private@example.test", "private-birth", "private-finance", "private-creator-title", "private-owner-title", "private-parent-title", "private-note-content", "private-task-content", "private-company-description", "private-payroll", "private-picklist-value", "private-response-url"):
        assert private not in json.dumps(result)
    if op.startswith("create_") or op.startswith("update_"):
        write, = [r for r in wire.calls if r.method == method]
        body = json.loads(write.content)
        assert set(body) == {"entity"}
        assert set(body["entity"]) <= cr.WRITE[path.split("/")[1]]
        assert result["acknowledged"] is True and wire.calls[-1].method == "GET"
        if op == "create_note":
            assert body["entity"]["IsReachOut"] is False and body["entity"]["IsEngagement"] is False
        if op == "create_task":
            assert body["entity"]["Owners"] == [{"Id": CURRENT_USER, "IsPrimary": True}]
            assert "Completed" not in body["entity"]  # Current write schema has no completion field.
    if op.startswith("delete_"):
        assert result["deleted"] is True and result["id"] == path.split("/")[-1]
    if op.endswith("_info"):
        assert result["required_fields"] is None and result["custom_fields_supported_for_writes"] is False


def test_actual_shape_three_tuple_omitted_defaults_and_native_schema():
    blob, errors, resolved = cc.shape_credential(FAMILY, {"api_key": CREDS["api_key"]})
    assert errors == {} and blob == {"api_key": CREDS["api_key"]}
    assert resolved == (TYPE, cr.CrelateAPIKeyCredential)
    schema = cr.CrelateNodeConfig.model_json_schema()
    assert len(schema["properties"]["config"]["discriminator"]["mapping"]) == 30
    assert schema["$defs"]["CrelateAPIKeyCredential"]["properties"]["api_key"]["ui:widget"] == "password"


@pytest.mark.parametrize("tag", [None, 42, [], {}, "foreign_api_key"])
def test_original_family_guard_before_native_parse(tag):
    with pytest.raises(ValueError, match="native Crelate"):
        factory("get_self", credential={**CREDS, "credential_type": tag})
    assert cr.CrelateNode.validate_config({"config": {"operation": "get_self"}, "credentials": {**CREDS, "credential_type": tag}})["valid"] is False


@pytest.mark.parametrize("sidecar", [{"endpoint": "https://foreign.example.test"}, {"headers": {"Authorization": "foreign"}}, {"send_email": True}, {"payroll": {}}, {"CustomFields": {}}, {"api_key": "query-key"}])
def test_typed_factory_rejects_transport_employment_and_arbitrary_payload(sidecar):
    with pytest.raises(ValueError, match="configuration is invalid"):
        factory("list_contacts", sidecar)


@pytest.mark.asyncio
async def test_principal_parent_and_creator_denied_before_write(wire):
    wire.org = "other-org"
    with pytest.raises(ValueError, match="another user or organization"):
        await factory("create_contact", CONTACT_ARGS).run({})
    assert all(r.method == "GET" for r in wire.calls)
    wire.org, wire.calls = "fixture-org", []
    wire.rows["jobs"]["AccountId"] = {"Id": CONTACT_ID}
    with pytest.raises(ValueError, match="another parent"):
        await factory("delete_job", {"company_id": COMPANY_ID, "job_id": JOB_ID}).run({})
    wire.rows["notes"]["CreatedById"] = {"Id": ID}
    with pytest.raises(ValueError, match="created by the current"):
        await factory("delete_note", {**PARENT_ARGS, "note_id": NOTE_ID}).run({})
    assert all(r.method == "GET" for r in wire.calls)


@pytest.mark.asyncio
async def test_org_writable_metadata_and_required_field_failure_are_truthful(wire):
    wire.override = lambda r: envelope({"Fields": {"FirstName": {"DisplayName": "First", "Type": "string", "IsEncrypted": True, "ValidFor": ["create"], "ValueMaskingMode": 2}}}) if r.url.path.endswith("/info") else None
    with pytest.raises(ValueError, match="does not permit"):
        await factory("create_contact", CONTACT_ARGS).run({})
    assert all(r.method == "GET" for r in wire.calls)
    wire.calls.clear()
    wire.override = lambda r: envelope(None, errors=[{"Code": 400, "Type": "Validation", "Message": CREDS["api_key"]}], status=400) if r.method == "POST" else None
    with pytest.raises(cr.CrelateRequestError, match="organization field requirements") as error:
        await factory("create_contact", CONTACT_ARGS).run({})
    assert CREDS["api_key"] not in str(error.value)
    assert len([r for r in wire.calls if r.method == "POST"]) == 1


@pytest.mark.asyncio
async def test_documented_next_link_signing_scope_cycles_and_partial_contract(wire):
    client = cr._Client(cr._Authority(CREDS))
    await client.identity()
    params = {"limit": 1, "fields": ",".join(cr.PUBLIC["contacts"]), "unmask_values": "false", "total_count": "true", "sort_by": "ModifiedOn asc"}
    def reply(r):
        next_url = str(r.url.copy_set_param("offset", "1"))
        return envelope([ROWS["contacts"]], metadata={"Links": {"Next": {"Href": next_url}}, "MoreRecords": True, "TotalRecords": 2})
    wire.override = reply
    first = await client.page("contacts", params)
    assert first["total"] == 2 and CREDS["api_key"] not in first["next_page_token"]
    before = len(wire.calls)
    with pytest.raises(ValueError, match="another key"):
        await client.page("contacts", {**params, "limit": 2}, first["next_page_token"])
    assert len(wire.calls) == before
    with pytest.raises(ValueError, match="repeated a page"):
        await client.page("contacts", params, first["next_page_token"])
    wire.override = lambda r: envelope([ROWS["contacts"]], errors=[{"Code": 403, "Type": "Access", "Message": CREDS["api_key"]}], status=206)
    partial = await client.page("contacts", params)
    assert partial["outcome"] == "partial" and partial["errors"] == [{"code": 403, "type": "ProviderError"}]
    wire.override = lambda r: envelope([ROWS["contacts"]], errors=[{"Code": 200, "Type": "IgnoredField", "Message": CREDS["api_key"]}])
    assert (await client.page("contacts", params))["outcome"] == "success"


@pytest.mark.parametrize("href", ["https://foreign.example.test/api3/contacts?offset=1", "https://app.crelate.com/api3/tasks?offset=1", "https://app.crelate.com/api3/contacts?api_key=private&offset=1", "https://app.crelate.com:444/api3/contacts?offset=1", "https://user@app.crelate.com/api3/contacts?offset=1"])
def test_next_link_rejects_foreign_origin_route_query_and_auth(href):
    client = cr._Client(cr._Authority(CREDS))
    with pytest.raises(ValueError):
        client._next("contacts", {"limit": 1}, {"Links": {"Next": {"Href": href}}}, 0)


@pytest.mark.asyncio
async def test_rate_limit_flat_body_and_false_receipts(wire):
    wire.override = lambda r: httpx.Response(429, json={"retry_after_seconds": "60", "error": CREDS["api_key"]})
    with pytest.raises(cr.CrelateRequestError) as error:
        await factory("get_self").run({})
    assert error.value.retry_after == 60 and CREDS["api_key"] not in str(error.value) and len(wire.calls) == 1
    wire.calls.clear()
    wire.override = lambda r: envelope(False) if r.method == "DELETE" else None
    with pytest.raises(ValueError, match="receipt is not true"):
        await factory("delete_contact", {"contact_id": CONTACT_ID}).run({})
    assert len([r for r in wire.calls if r.method == "DELETE"]) == 1


@pytest.mark.asyncio
async def test_public_dns_rejects_private_target(wire, monkeypatch):
    monkeypatch.setattr(ssrf, "allow_private_hosts", lambda: False)
    wire.address = "169.254.169.254"
    with pytest.raises(ssrf.SSRFError, match="non-public address"):
        await factory("get_self").run({})
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
        return self.row if "FROM credentials" in sql else None


@pytest.fixture
def current(monkeypatch):
    row = {"credential_type": FAMILY, "credential": "synthetic-encrypted", "revoked_at": None, "owner_id": USER,
        "token_version": 7, "updated_at": datetime(2026, 10, 6, tzinfo=timezone.utc), "metadata": {}, "approval_operations": [], "approval_revision": 1}
    crypto = MagicMock()
    crypto.decrypt_credential.return_value = deepcopy(CREDS)
    crypto.decrypt_credential.side_effect = lambda *_: deepcopy(crypto.decrypt_credential.return_value)
    monkeypatch.setattr(credentials, "get_encryption", lambda: crypto)
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: crypto)
    return SimpleNamespace(row=row, pool=Pool(row), crypto=crypto)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"credential_type": "foreign"}, {"revoked_at": "revoked"}])
async def test_current_row_rejects_foreign_or_revoked_credential(wire, current, change):
    current.row.update(change)
    with pytest.raises(ValueError, match="native Crelate|unavailable or revoked"):
        await factory("get_self", current=current).run({})
    assert wire.calls == []


@pytest.mark.asyncio
async def test_actual_saved_row_positive(wire, current, monkeypatch):
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    assert (await factory("get_self", current=current).run({}))["organization_name"] == "fixture-org"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_actual_operation_lookup_identity_evidence_admission(wire, current, monkeypatch, status):
    from utils import credential_approval
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value={"id": ID, "status": status, "new_request": False}))
    monkeypatch.setattr(credential_approval, "get_frontend_url", lambda: "https://fixture.example.test")
    result = await run_op.run_node_operation(node_type=TYPE, operation="get_self", arguments={}, user_id=USER, credential_id=ID, pool=current.pool)
    lookup = await run_op.run_node_lookup(node_type=TYPE, field_name="contact_id", user_id=USER, credential_id=ID, pool=current.pool)
    evidence = await ce.collect_evidence(node_type=TYPE, user_id=USER, credential_id=ID, pool=current.pool)
    assert result["executed"] is False and lookup["executed"] is False and evidence.reachable is None
    assert wire.calls == []


@pytest.mark.asyncio
async def test_actual_connect_and_native_admitted_picker(wire, current, monkeypatch):
    monkeypatch.setattr(cc, "_collect_evidence", ce.collect_evidence)
    verdict = await cc.validate_for_connect(credential_type=FAMILY, credential_data=CREDS, user_id=USER, pool=current.pool)
    assert not verdict.field_errors and verdict.evidence.reachable is True
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    result = await run_op.run_node_lookup(node_type=TYPE, field_name="contact_id", user_id=USER, credential_id=ID, pool=current.pool)
    assert result["options"] == [{"label": "Fixture Contact", "value": CONTACT_ID}]


@pytest.mark.asyncio
async def test_actual_socket_picker_native_success(wire, current, monkeypatch):
    from wss.handlers import workflow_handler as wh
    from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest
    from utils import credential_approval
    monkeypatch.setattr(wh.WorkflowHandler, "get_pool", AsyncMock(return_value=current.pool))
    monkeypatch.setattr(wh, "get_user_org_context", AsyncMock(return_value=None))
    monkeypatch.setattr(wh, "get_encryption", lambda: current.crypto)
    monkeypatch.setattr(credential_approval, "get_frontend_url", lambda: "https://fixture.example.test")
    sent = AsyncMock()
    monkeypatch.setattr(wh, "send_event", sent)
    handler = wh.WorkflowHandler.__new__(wh.WorkflowHandler)
    handler.sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    request = WorkflowNodeLoadOptionsRequest(request_id="crelate-fixture", node_type=TYPE, field_name="contact_id", credential_id=ID)
    await handler.load_node_options("fixture-sid", request)
    data = sent.call_args.args[2].data
    assert data["success"] is True
    assert data["options"][0]["value"] == CONTACT_ID


@pytest.mark.asyncio
async def test_actual_stale_current_row_and_foreign_freshen_lookup(wire, current):
    current.crypto.decrypt_credential.return_value = {**CREDS, "api_key": "synthetic-replacement-key"}
    with pytest.raises(ValueError, match="binding changed"):
        await factory("get_self", current=current).run({})
    assert wire.calls == []
    for method in (cr.CrelateNode.freshen_credential, cr.CrelateNode.validate_credential_access):
        with pytest.raises(ValueError, match="native Crelate"):
            await method({**CREDS, "credential_type": None})
    with pytest.raises(ValueError, match="native Crelate"):
        await cr.CrelateNode.load_field_options("contact_id", {**CREDS, "credential_type": "foreign"})
    assert wire.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 202, 204, 302, 400, 401, 403, 404, 409, 500])
async def test_unexpected_or_rejected_status_has_no_raw_body_and_no_retry(wire, status):
    wire.override = lambda r: httpx.Response(status, json={"Message": CREDS["api_key"]})
    with pytest.raises(cr.CrelateRequestError) as error:
        await factory("get_self").run({})
    assert CREDS["api_key"] not in str(error.value) and len(wire.calls) == 1


@pytest.mark.asyncio
async def test_actual_request_seam_rejects_arbitrary_path_query_and_body(wire):
    client = cr._Client(cr._Authority(CREDS))
    with pytest.raises(ValueError, match="native route"):
        await client.request("POST", "/emails", body={"entity": {"Display": "send"}})
    with pytest.raises(ValueError, match="native query"):
        await client.request("GET", "/users/self", params={"apiKey": CREDS["api_key"]})
    await client.identity()
    before = len(wire.calls)
    with pytest.raises(ValueError, match="native payload"):
        await client.request("POST", "/contacts", body={"entity": {"Payroll": True}})
    assert len(wire.calls) == before


@pytest.mark.asyncio
async def test_nested_public_canary_and_note_parent_type_privacy(wire):
    wire.rows["contacts"]["Name"] = CREDS["api_key"]
    with pytest.raises(ValueError, match="protected credential data"):
        await factory("get_contact", {"contact_id": CONTACT_ID}).run({})
    wire.rows["contacts"] = deepcopy(ROWS["contacts"])
    wire.override = lambda r: envelope({**ROWS["notes"], "ParentId": {"Id": CONTACT_ID, "EntityName": "OtherEntity"}}) if r.method == "GET" and r.url.path.endswith("notes/" + NOTE_ID) else None
    with pytest.raises(ValueError, match="another parent"):
        await factory("create_note", NOTE_ARGS).run({})
    assert len([r for r in wire.calls if r.method == "POST"]) == 1
    # This is an uncertain readback after one create, never an automatic retry.
