"""Synthetic fixtures for actual Eloqua factory/run/admission/transport seams."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from nodes import eloqua_node as el
from nodes.core import connection_evidence as ce, credential_connect as cc, run_op
from nodes.core.registry import NodeFactory
from repositories.credential_approvals import CredentialApprovalRepo
from utils import credentials, ssrf

TYPE, FAMILY = "automation-eloqua", "eloqua_basic"
ID, USER = "00000000-0000-4000-8000-000000000042", "00000000-0000-4000-8000-000000000001"
CREDS = {"company": "FixtureCo", "username": "fixtureuser", "password": "synthetic-eloqua-password-canary", "expected_site_id": "42", "expected_user_id": "7"}
BEARER = {"credential_type": "eloqua_bearer_token", "access_token": "synthetic-eloqua-bearer-canary", "expires_at": "2099-01-01T00:00:00Z", "expected_site_id": "42", "expected_user_id": "7"}
ORIGIN = "https://secure.p03.eloqua.com"
DISCOVERY = {"site": {"id": 42, "name": "FixtureCo"}, "user": {"id": 7, "username": "fixtureuser", "displayName": "Fixture User", "emailAddress": "private@example.test"},
    "urls": {"base": ORIGIN, "apis": {"rest": {"standard": ORIGIN + "/API/REST/{version}/", "bulk": ORIGIN + "/API/Bulk/{version}/"}, "soap": {"private": "unexported"}}}}
COMMON = {"createdBy": "7", "createdAt": "1234567890", "updatedBy": "7", "updatedAt": "1234567891", "depth": "complete"}
ROWS = {
    "contact": {**COMMON, "type": "Contact", "id": "10", "firstName": "Fixture", "lastName": "Contact", "emailAddress": "private@example.test", "isSubscribed": "false", "fieldValues": [{"type": "FieldValue", "id": "100", "value": "private-contact-value"}]},
    "account": {**COMMON, "type": "Account", "id": "20", "name": "Fixture Account", "businessPhone": "private-phone", "fieldValues": []},
    "custom_object": {**COMMON, "type": "CustomObject", "id": "30", "name": "Fixture Object", "deleteLinkedCustomObjectData": "false", "fields": [{"type": "CustomObjectField", "id": "101", "name": "Fixture Text", "dataType": "text", "displayType": "text", "defaultValue": "private-default-value", "permissions": []}]},
    "custom_object_record": {**COMMON, "type": "CustomObjectData", "id": "40", "isMapped": "false", "fieldValues": [{"type": "FieldValue", "id": "101", "value": "private-record-value"}]},
}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture(autouse=True)
def isolated_discovery(monkeypatch):
    monkeypatch.setattr(el, "_DISCOVERY", {})
    monkeypatch.setattr(el, "_DISCOVERY_LOCK", asyncio.Lock())


def factory(op, args=None, credential=None, current=None):
    data = {"config": {"operation": op, **(args or {})}, "credentials": deepcopy(CREDS if credential is None else credential)}
    if current:
        data.update(credential_id=ID, _approval_pool=current.pool)
    return NodeFactory.create_node(node_id="eloqua-fixture", node_type=TYPE, node_data=data, user_id=USER)


@pytest.fixture
async def wire(monkeypatch):
    state = SimpleNamespace(calls=[], override=None, discovery=deepcopy(DISCOVERY), address="8.8.8.8", rows=deepcopy(ROWS), empty_object=False)
    def respond(request):
        state.calls.append(request)
        assert request.url.scheme == "https" and request.url.host in {"login.eloqua.com", "secure.p03.eloqua.com"}
        assert not request.url.username and "apiKey" not in request.url.params
        assert request.headers["Authorization"] in {el._authorization(el._credential(CREDS)), el._authorization(el._credential(BEARER))}
        if state.override:
            result = state.override(request)
            if result is not None:
                return result
        path = request.url.path
        if path == "/id":
            return httpx.Response(200, json=state.discovery)
        for kind in ROWS:
            client = el._Client(el._Authority(CREDS))
            single = client.route(kind, parent="30" if kind == "custom_object_record" else None)
            plural = client.route(kind, collection=True, parent="30" if kind == "custom_object_record" else None)
            if path == plural and request.method == "GET":
                rows = [] if kind == "custom_object_record" and state.empty_object else [state.rows[kind]]
                return httpx.Response(200, json={"type": "QueryResult", "elements": rows, "total": len(rows), "page": int(request.url.params["page"]), "pageSize": int(request.url.params["count"])})
            if path == single and request.method == "POST":
                state.rows[kind].update(json.loads(request.content))
                if kind == "custom_object":
                    state.rows[kind]["fields"][0].update(type="CustomObjectField", id="101")
                return httpx.Response(201, json=state.rows[kind])
            if path == single + "/" + state.rows[kind]["id"]:
                if request.method == "GET":
                    return httpx.Response(200, json=state.rows[kind])
                if request.method == "PUT":
                    state.rows[kind] = json.loads(request.content)
                    return httpx.Response(200, json=state.rows[kind])
                if request.method == "DELETE":
                    return httpx.Response(204 if kind in {"contact", "account"} else 200)
        return httpx.Response(404, json={"privateError": CREDS["password"]})
    async def dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (state.address, 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    original = ssrf.guarded_async_client
    def client(**kwargs):
        assert "require_public" not in kwargs and kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(el, "guarded_async_client", client)
    return state


CASES = [("get_identity", {}, "/id", "GET")]
for kind, plural, target, create, update, parent in [
    ("contact", "contacts", "10", {"first_name": "Fixture", "last_name": "Contact", "email_address": "private@example.test"}, {"first_name": "Renamed", "last_name": "Contact"}, {}),
    ("account", "accounts", "20", {"name": "Fixture Account"}, {"name": "Renamed Account"}, {}),
    ("custom_object", "custom_objects", "30", {"name": "Fixture Object", "text_field_name": "Fixture Text"}, {"name": "Renamed Object"}, {}),
    ("custom_object_record", "custom_object_records", "40", {"custom_object_id": "30", "field_values": [{"field_id": "101", "value": "Fixture Value"}]}, {"custom_object_id": "30", "field_values": [{"field_id": "101", "value": "Renamed Value"}]}, {"custom_object_id": "30"}),
]:
    key = "record_id" if kind == "custom_object_record" else kind + "_id"
    route = "/API/REST/2.0/data/customObject/30/instance" if parent else "/API/REST/" + ("1.0/data/" + kind if kind in {"contact", "account"} else "2.0/assets/customObject")
    collection = route + "s"
    CASES.extend([("list_" + plural, parent, collection, "GET"), ("get_" + kind, {**parent, key: target}, route + "/" + target, "GET"),
        ("create_" + kind, create, route, "POST"), ("update_" + kind, {**update, key: target}, route + "/" + target, "PUT"),
        ("delete_" + kind, {**parent, key: target}, route + "/" + target, "DELETE")])


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args,path,method", CASES)
async def test_real_factory_run_all_21_native_operations_and_wire_contract(wire, op, args, path, method):
    wire.empty_object = op == "delete_custom_object"
    node = factory(op, args)
    assert isinstance(node, el.EloquaNode)
    result = await node.run({})
    assert result["site_id"] == "42" and result["user_id"] == "7"
    assert any(r.url.path == path and r.method == method for r in wire.calls)
    for private in (CREDS["password"], "private@example.test", "private-phone", "private-contact-value", "private-record-value", "private-default-value", ORIGIN):
        assert private not in json.dumps(result)
    if op.startswith(("create_", "update_")):
        assert result["acknowledged"] is True and wire.calls[-1].method == "GET"
        write, = [r for r in wire.calls if r.method == method]
        body = json.loads(write.content)
        if op == "update_contact":
            assert body["emailAddress"] == ROWS["contact"]["emailAddress"]
            assert body["isSubscribed"] == "false" and body["fieldValues"] == ROWS["contact"]["fieldValues"]
        if op == "update_custom_object":
            assert body["fields"] == ROWS["custom_object"]["fields"] and body["deleteLinkedCustomObjectData"] == "false"
        if op == "create_custom_object_record":
            assert set(body) == {"fieldValues"} and body["fieldValues"] == [{"id": "101", "value": "Fixture Value"}]
    if op.startswith("delete_"):
        assert result["http_status"] == (204 if op in {"delete_contact", "delete_account"} else 200)
        assert result["acknowledged"] is True and "deleted" not in result


def test_actual_three_value_shape_omitted_defaults_and_schema():
    for family, data, cls in [(FAMILY, {k: CREDS[k] for k in ("company", "username", "password")}, el.EloquaBasicCredential), ("eloqua_bearer_token", {k: BEARER[k] for k in ("access_token", "expires_at")}, el.EloquaBearerTokenCredential)]:
        blob, errors, resolved = cc.shape_credential(family, data)
        assert not errors and "credential_type" not in blob and "expected_site_id" not in blob
        assert resolved == (TYPE, cls)
    schema = el.EloquaNodeConfig.model_json_schema()
    assert len(schema["properties"]["config"]["discriminator"]["mapping"]) == 21
    for model, name in [("GetContact", "contact_id"), ("GetAccount", "account_id"), ("GetCustomObject", "custom_object_id")]:
        assert schema["$defs"][model]["properties"][name]["x-dynamic-options"]["field_name"] == name
    assert schema["$defs"]["EloquaBasicCredential"]["properties"]["password"]["ui:widget"] == "password"
    assert "expires_at" in schema["$defs"]["EloquaBearerTokenCredential"]["required"]


@pytest.mark.parametrize("tag", [None, 42, [], {}, "foreign_api_key"])
def test_original_kind_rejected_before_factory_parse(tag):
    with pytest.raises(ValueError, match="native Eloqua"):
        factory("get_identity", credential={**CREDS, "credential_type": tag})
    assert el.EloquaNode.validate_config({"config": {"operation": "get_identity"}, "credentials": {**CREDS, "credential_type": tag}})["valid"] is False


@pytest.mark.parametrize("sidecar", [{"endpoint": "https://foreign.example.test"}, {"headers": {"Authorization": "foreign"}}, {"deploy_email": True}, {"currentStatus": "Active"}, {"fieldValues": []}, {"send": True}])
def test_unknown_sidecars_cannot_change_read_into_transport_or_marketing_write(sidecar):
    with pytest.raises(ValueError, match="configuration is invalid"):
        factory("list_contacts", sidecar)


@pytest.mark.asyncio
async def test_basic_and_bearer_discovery_cache_and_actual_expiry(wire):
    assert (await factory("get_identity").run({}))["user_id"] == "7"
    await factory("get_contact", {"contact_id": "10"}).run({})
    assert len([r for r in wire.calls if r.url.path == "/id"]) == 1
    await factory("get_identity", credential=BEARER).run({})
    assert len([r for r in wire.calls if r.url.path == "/id"]) == 2
    with pytest.raises(ValueError, match="configuration is invalid"):
        factory("get_identity", credential={**BEARER, "expires_at": "2020-01-01T00:00:00Z"})
    with pytest.raises(ValueError, match="configuration is invalid"):
        factory("get_identity", credential={**BEARER, "expires_at": "2099-01-01T00:00:00"})


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["https://secure.p05.eloqua.com", "https://secure.p03.eloqua.com.evil.example", "http://secure.p03.eloqua.com", "https://secure.p03.eloqua.com:443", "https://secure.p03.eloqua.com/path", "https://127.0.0.1", "https://user@secure.p03.eloqua.com"])
async def test_discovery_cannot_redirect_credentials_to_undocumented_origin(wire, origin):
    wire.discovery["urls"]["base"] = origin
    wire.discovery["urls"]["apis"]["rest"]["standard"] = origin + "/API/REST/{version}/"
    with pytest.raises(ValueError, match="documented matching"):
        await factory("list_contacts").run({})
    assert [r.url.path for r in wire.calls] == ["/id"]


@pytest.mark.asyncio
async def test_http_200_not_authenticated_and_mismatched_rest_template_fail_closed(wire):
    wire.override = lambda r: httpx.Response(200, json="Not authenticated.")
    with pytest.raises(el.EloquaRequestError, match="did not authenticate"):
        await factory("get_identity").run({})
    wire.override, wire.calls = None, []
    wire.discovery["urls"]["apis"]["rest"]["standard"] = "https://secure.p02.eloqua.com/API/REST/{version}/"
    with pytest.raises(ValueError, match="matching HTTPS pod"):
        await factory("get_identity").run({})
    assert len(wire.calls) == 1


@pytest.mark.asyncio
async def test_principal_creator_parent_text_schema_mapping_and_nonempty_delete_gates(wire):
    wire.discovery["user"]["id"] = 9
    with pytest.raises(ValueError, match="another site or user"):
        await factory("create_account", {"name": "Fixture"}).run({})
    wire.discovery, wire.calls = deepcopy(DISCOVERY), []
    wire.rows["contact"]["createdBy"] = "9"
    with pytest.raises(ValueError, match="created by"):
        await factory("delete_contact", {"contact_id": "10"}).run({})
    with pytest.raises(el.EloquaRequestError) as error:
        await factory("create_custom_object_record", {"custom_object_id": "31", "field_values": [{"field_id": "101", "value": "Fixture"}]}).run({})
    assert error.value.status == 404
    with pytest.raises(ValueError, match="belonging"):
        await factory("create_custom_object_record", {"custom_object_id": "30", "field_values": [{"field_id": "999", "value": "Fixture"}]}).run({})
    wire.rows["custom_object_record"]["contactId"] = "10"
    with pytest.raises(ValueError, match="unlinked"):
        await factory("delete_custom_object_record", {"custom_object_id": "30", "record_id": "40"}).run({})
    with pytest.raises(ValueError, match="empty"):
        await factory("delete_custom_object", {"custom_object_id": "30"}).run({})
    assert all(r.method == "GET" for r in wire.calls)


@pytest.mark.asyncio
async def test_put_preserves_complete_record_values_and_rejects_unknown_properties(wire):
    wire.rows["custom_object_record"]["fieldValues"].append({"id": "102", "type": "FieldValue", "value": "private-preserved-text"})
    await factory("update_custom_object_record", {"custom_object_id": "30", "record_id": "40", "field_values": [{"field_id": "101", "value": "Fixture"}]}).run({})
    write, = [r for r in wire.calls if r.method == "PUT"]
    assert json.loads(write.content)["fieldValues"][1]["value"] == "private-preserved-text"
    wire.calls.clear()
    wire.rows["account"]["unknownProperty"] = "must-not-drop"
    with pytest.raises(ValueError, match="complete, known"):
        await factory("update_account", {"account_id": "20", "name": "New Name"}).run({})
    assert all(r.method == "GET" for r in wire.calls)


@pytest.mark.asyncio
async def test_signed_paging_exact_parent_size_principal_cycle_and_204(wire):
    def pages(request):
        if request.url.path.endswith("/contacts"):
            page = int(request.url.params["page"])
            row = {**ROWS["contact"], "id": str(page * 10)}
            return httpx.Response(200, json={"type": "QueryResult", "elements": [row], "total": 3, "pageSize": 1, "page": page})
    wire.override = pages
    first = await factory("list_contacts", {"count": 1}).run({})
    second = await factory("list_contacts", {"count": 1, "page_token": first["next_page_token"]}).run({})
    assert [first["data"][0]["id"], second["data"][0]["id"]] == ["10", "20"]
    for op, args in [("list_accounts", {"count": 1}), ("list_contacts", {"count": 2})]:
        with pytest.raises(ValueError, match="continuation belongs"):
            await factory(op, {**args, "page_token": first["next_page_token"]}).run({})
    wire.override = lambda r: httpx.Response(204) if r.url.path.endswith("/contacts") else None
    result = await factory("list_contacts").run({})
    assert result["http_status"] == 204 and result["data"] == [] and result["next_page_token"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 202, 204, 302, 400, 401, 403, 404, 409, 429, 500])
async def test_status_errors_are_sanitized_and_never_retried(wire, status):
    wire.override = lambda r: httpx.Response(status, json={"error": CREDS["password"]})
    with pytest.raises(el.EloquaRequestError) as error:
        await factory("get_identity").run({})
    assert CREDS["password"] not in str(error.value) and len(wire.calls) == 1


@pytest.mark.asyncio
async def test_guarded_transport_rejects_private_dns(wire, monkeypatch):
    monkeypatch.setattr(ssrf, "allow_private_hosts", lambda: False)
    wire.address = "169.254.169.254"
    with pytest.raises(ssrf.SSRFError, match="resolves to non-public address"):
        await factory("get_identity").run({})
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
        return self.row if "FROM credentials c" in sql else None


@pytest.fixture
def current(monkeypatch):
    row = {"credential_type": FAMILY, "credential": "synthetic-encrypted", "revoked_at": None, "owner_id": USER,
        "token_version": 7, "updated_at": datetime(2026, 10, 6, tzinfo=timezone.utc), "metadata": {}, "approval_operations": [], "approval_revision": 1}
    crypto = MagicMock()
    crypto.decrypt_credential.return_value = deepcopy(CREDS)
    crypto.decrypt_credential.side_effect = lambda _: deepcopy(crypto.decrypt_credential.return_value)
    monkeypatch.setattr(credentials, "get_encryption", lambda: crypto)
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: crypto)
    return SimpleNamespace(row=row, pool=Pool(row), crypto=crypto)


@pytest.mark.asyncio
async def test_authoritative_saved_positive_and_freshen_row_metadata(wire, current, monkeypatch):
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    assert (await factory("get_identity", current=current).run({}))["user_id"] == "7"
    refreshed = await el.EloquaNode.freshen_credential({**CREDS, "token_version": 7, "updated_at": current.row["updated_at"]})
    assert "token_version" not in refreshed and "updated_at" not in refreshed


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_real_operation_lookup_and_identity_evidence_admission(wire, current, monkeypatch, status):
    from utils import credential_approval
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value={"id": ID, "status": status, "new_request": False}))
    monkeypatch.setattr(credential_approval, "get_frontend_url", lambda: "https://fixture.example.test")
    result = await run_op.run_node_operation(node_type=TYPE, operation="get_identity", arguments={}, user_id=USER, credential_id=ID, pool=current.pool)
    lookup = await run_op.run_node_lookup(node_type=TYPE, field_name="custom_object_id", user_id=USER, credential_id=ID, pool=current.pool)
    evidence = await ce.collect_evidence(node_type=TYPE, user_id=USER, credential_id=ID, pool=current.pool)
    assert result["executed"] is False and lookup["executed"] is False and evidence.reachable is None
    assert wire.calls == []


@pytest.mark.asyncio
async def test_actual_connect_and_admitted_picker(wire, current, monkeypatch):
    monkeypatch.setattr(cc, "_collect_evidence", ce.collect_evidence)
    verdict = await cc.validate_for_connect(credential_type=FAMILY, credential_data=CREDS, user_id=USER, pool=current.pool)
    assert not verdict.field_errors and verdict.evidence.reachable is True
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    result = await run_op.run_node_lookup(node_type=TYPE, field_name="contact_id", user_id=USER, credential_id=ID, pool=current.pool)
    assert result["options"] == [{"label": "Fixture Contact", "value": "10"}]


@pytest.mark.asyncio
async def test_actual_socket_picker_success(wire, current, monkeypatch):
    from wss.handlers import workflow_handler as wh
    from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest
    from utils import credential_approval
    monkeypatch.setattr(wh, "get_user_org_context", AsyncMock(return_value=None))
    monkeypatch.setattr(wh, "get_encryption", lambda: current.crypto)
    monkeypatch.setattr(credential_approval, "get_frontend_url", lambda: "https://fixture.example.test")
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    sent = AsyncMock()
    monkeypatch.setattr(wh, "send_event", sent)
    handler = wh.WorkflowHandler.__new__(wh.WorkflowHandler)
    handler.get_pool = AsyncMock(return_value=current.pool)
    handler.sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    await handler.load_node_options("fixture-sid", WorkflowNodeLoadOptionsRequest(request_id="eloqua-fixture", node_type=TYPE, field_name="custom_object_id", credential_id=ID))
    data = sent.call_args.args[2].data
    assert data["success"] is True
    assert data["options"][0]["value"] == "30"


@pytest.mark.asyncio
@pytest.mark.parametrize("tag", [None, 42, [], {}, "foreign"])
async def test_saved_original_bad_tag_and_freshen_lookup_before_provider(wire, current, tag):
    current.crypto.decrypt_credential.return_value = {**CREDS, "credential_type": tag}
    for method in (el.EloquaNode.freshen_credential, el.EloquaNode.validate_credential_access):
        with pytest.raises(ValueError, match="native Eloqua"):
            await method({**CREDS, "credential_type": tag})
    with pytest.raises(ValueError, match="native Eloqua"):
        await el.EloquaNode.load_field_options("contact_id", {**CREDS, "credential_type": tag})
    assert wire.calls == []


@pytest.mark.asyncio
async def test_actual_request_rejects_unknown_routes_query_payload_and_http200_delete_string(wire):
    client = el._Client(el._Authority(CREDS))
    await client.identity()
    before = len(wire.calls)
    for method, kind, kwargs in [("POST", "email_deployment", {"body": {"name": "send"}}),
        ("GET", "contact", {"identifier": "10", "params": {"depth": "complete", "apiKey": "query-secret"}}),
        ("POST", "account", {"body": {"clientSecret": "foreign"}})]:
        with pytest.raises(ValueError):
            await client.request(method, kind, **kwargs)
    assert len(wire.calls) == before
    wire.override = lambda r: httpx.Response(200, json="Not authenticated.") if r.method == "DELETE" else None
    with pytest.raises(el.EloquaRequestError, match="did not authenticate"):
        await factory("delete_custom_object_record", {"custom_object_id": "30", "record_id": "40"}).run({})
    assert len([r for r in wire.calls if r.method == "DELETE"]) == 1


@pytest.mark.asyncio
async def test_cached_discovery_cannot_hide_current_row_change_or_revocation(wire, current, monkeypatch):
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    await factory("get_identity", current=current).run({})
    wire.calls.clear()
    current.crypto.decrypt_credential.return_value = {**CREDS, "password": "synthetic-replacement-canary"}
    with pytest.raises(ValueError, match="binding changed"):
        await factory("get_identity", current=current).run({})
    current.crypto.decrypt_credential.return_value = deepcopy(CREDS)
    current.row["revoked_at"] = "revoked"
    with pytest.raises(ValueError, match="unavailable or revoked"):
        await factory("get_identity", current=current).run({})
    assert wire.calls == []


@pytest.mark.asyncio
async def test_expired_cache_rediscovery_principal_drift_is_rejected(wire):
    client = el._Client(el._Authority(BEARER))
    await client.identity()
    key = client.authority.key()
    el._DISCOVERY[key] = (0, el._DISCOVERY[key][1])
    wire.discovery["user"]["id"] = 9
    with pytest.raises(ValueError, match="rediscovery changed"):
        await client.identity()
    assert len(wire.calls) == 2 and key not in el._DISCOVERY


@pytest.mark.asyncio
async def test_nested_selected_field_canary_and_write_timeout_never_export_or_retry(wire):
    wire.rows["custom_object"]["fields"][0]["name"] = CREDS["password"]
    with pytest.raises(ValueError, match="protected credential"):
        await factory("get_custom_object", {"custom_object_id": "30"}).run({})
    wire.rows = deepcopy(ROWS)
    wire.calls.clear()
    def timeout(request):
        if request.method == "POST":
            raise httpx.ReadTimeout("private " + CREDS["password"], request=request)
    wire.override = timeout
    with pytest.raises(el.EloquaRequestError, match="outcome is unknown") as error:
        await factory("create_account", {"name": "Fixture"}).run({})
    assert CREDS["password"] not in str(error.value)
    assert len([r for r in wire.calls if r.method == "POST"]) == 1
