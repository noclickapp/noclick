"""Prepared UNRUN: StatusPal native factory/dispatcher, protected scope and authority."""
import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from nodes import statuspal_node as fn
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation, run_node_lookup
from repositories.credentials import CredentialValidationRow

CREDS = {"credential_type": "statuspal_api_key", "api_key": "synthetic+/=private-key", "region": "us", "organization_id": 7}
STAMP = datetime(2026, 10, 7, tzinfo=timezone.utc)
PAGE = {"organization_id": 7, "subdomain": "owned-page", "name": "Owned page", "time_zone": "Europe/Berlin", "inserted_at": "2026-10-07T00:00:00", "updated_at": "2026-10-07T00:00:00Z", "url": "omit URL", "support_email": "omit email", "domain_config": {"domain": "omit domain", "validation_records": {"certificate_txt_value": "omit validation"}, "error": "omit secret"}, "restricted_ips": "omit IP", "custom_js": "omit script", "notify_by_default": True, "theme_configs": {"secret": "omit secret"}}
SERVICE = {"id": 11, "name": "Owned service", "parent_id": 10, "children_ids": [12], "current_incident_type": "minor", "is_up": False, "description": "omit description", "private_description": "omit private", "notification_recipients": [{"email": "omit email"}], "monitoring_options": {"headers": [{"key": "Authorization", "value": "omit secret"}]}, "incoming_webhook_url": "omit webhook", "inbound_email_address": "omit inbound", "ping_url": "omit ping", "auto_notify": True, "private": True}
OPS = ["test_connection", "list_status_pages", "get_status_page", "list_services", "get_service"]

@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield

def page(*rows, key="status_pages", total=None, next_link=None, **changes):
    return {key: list(rows), "links": {"next": next_link, "prev": None}, "meta": {"total_count": len(rows) if total is None else total}, **changes}

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
            calls.append({"method": method, "url": url, **kwargs}); logging.getLogger("httpx").info("private %s %s", url, kwargs)
            response = responses.pop(0); return response if isinstance(response, Response) else Response(response)
    def client(**kwargs):
        assert kwargs == {"require_public": True, "timeout": 20.0, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(fn, "guarded_async_client", client)
    return SimpleNamespace(calls=calls, responses=responses)

def scoped(wire, body): wire.responses.extend([{"status_page": PAGE}, body, {"status_page": PAGE}])
async def run(op, args=None, *, credential_data=None, **context):
    return await run_node_operation(node_type=fn.NODE_TYPE, operation=op, arguments=args or {}, credential_data=credential_data or CREDS, user_id="actor", **context)

def test_actual_factory_five_operations_and_original_family_before_reconciliation():
    node = NodeFactory.create_node(node_id="native", node_type=fn.NODE_TYPE, user_id="actor", node_data={"config": {"operation": "get_service", "subdomain": "owned-page", "service_id": "11"}, "credentials": CREDS})
    assert node.config.config.service_id == 11 and node.config.credentials.organization_id == 7
    defs = fn.StatusPalNode.get_config_schema()["$defs"]
    assert sorted(d["properties"]["operation"]["const"] for d in defs.values() if "operation" in d.get("properties", {})) == sorted(OPS)
    for family in (None, "http_bearer", "statuspal_oauth"):
        data = {"credential_id": "saved", "config": {"operation": "test_connection"}, "credentials": {**CREDS, "credential_type": family}}
        assert fn.StatusPalNode.validate_config(data)["valid"] is False
        with pytest.raises(ValueError, match="family"): fn.StatusPalNode.parse_config(data)

@pytest.mark.parametrize("cfg", [{"operation": "list_services"}, {"operation": "get_service", "subdomain": "owned-page", "service_id": True}, {"operation": "get_status_page", "subdomain": "owned-page.statuspal.io"}, {"operation": "get_status_page", "subdomain": "../other"}, {"operation": "list_status_pages", "page": 2}, {"operation": "list_status_pages", "page_token": "opaque"}, {"operation": "test_connection", "url": "https://evil.test"}, {"operation": "list_services", "subdomain": "owned-page", "query": "secret"}, {"operation": "summary"}, {"operation": "create_incident"}, {"operation": "push_metric"}])
def test_closed_config_no_cursor_guess_or_public_control_fallback(cfg):
    with pytest.raises(ValueError): fn.StatusPalNode.parse_config({"config": cfg, "credentials": CREDS})

@pytest.mark.parametrize("change", [{"region": "https://evil.test"}, {"region": "other"}, {"organization_id": False}, {"organization_id": "7.5"}, {"api_key": "Bearer private key"}])
def test_closed_credential_region_organization_raw_key(change):
    with pytest.raises(ValueError): fn.StatusPalNode.parse_config({"config": {"operation": "test_connection"}, "credentials": {**CREDS, **change}})

@pytest.mark.asyncio
@pytest.mark.parametrize("region", ["us", "eu"])
async def test_exact_fixed_raw_authorization_header_region_no_query_or_public_hello(wire, caplog, region):
    wire.responses.append(page(PAGE))
    with caplog.at_level(logging.DEBUG): result = await run("test_connection", credential_data={**CREDS, "region": region})
    assert wire.calls == [{"method": "GET", "url": fn.BASES[region] + "/orgs/7/status_pages", "headers": {"Authorization": CREDS["api_key"], "Accept": "application/json", "Content-Type": "application/json"}}]
    proof = result["data"]; assert proof["proves"] == "reachability" and proof["account_identity_verified"] is False and proof["organization_ownership_verified"] is False
    assert proof["results"] == [{"organization_id": 7, "subdomain": "owned-page", "time_zone": "Europe/Berlin", "inserted_at": PAGE["inserted_at"], "updated_at": PAGE["updated_at"]}]
    assert proof["pagination"]["completion_verified"] is False and CREDS["api_key"] not in caplog.text and fn._PRIVATE_REQUEST.get() is False
    logging.getLogger("httpx").warning("unrelated context"); assert "unrelated context" in caplog.text

@pytest.mark.asyncio
async def test_real_dispatch_service_page_witness_privacy_and_exact_wrapper(wire):
    scoped(wire, page(SERVICE, key="services")); result = await run("list_services", {"subdomain": "owned-page"})
    assert [c["url"] for c in wire.calls] == [fn.BASES["us"] + "/orgs/7/status_pages/owned-page", fn.BASES["us"] + "/status_pages/owned-page/services", fn.BASES["us"] + "/orgs/7/status_pages/owned-page"]
    assert result["data"]["services"] == [{"id": 11, "parent_id": 10, "children_ids": [12], "current_incident_type": "minor", "is_up": False}]
    assert result["data"]["protected_page_scope_verified"] is True and result["data"]["service_page_id_returned"] is False
    scoped(wire, {"service": SERVICE}); detail = await run("get_service", {"subdomain": "owned-page", "service_id": "11", "include_names": True})
    assert detail["data"]["service"]["name"] == "Owned service" and wire.calls[4]["url"].endswith("/services/11")
    wire.responses.append({"status_page": PAGE}); named = await run("get_status_page", {"subdomain": "owned-page", "include_names": True})
    assert named["data"]["status_page"]["name"] == "Owned page"
    for value in ("omit domain", "domain_config", "omit validation", "omit email", "omit private", "omit secret", "omit webhook", "monitoring_options", "auto_notify", "private"):
        assert value not in json.dumps(detail["data"]["service"]) and value not in json.dumps(named["data"]["status_page"])

@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["before_org", "before_subdomain", "after_org", "service_id", "string_id", "bare_detail", "array_detail"])
async def test_returned_org_subdomain_and_service_identity_are_actual_not_requested(wire, case):
    before = {**PAGE, "organization_id": 8} if case == "before_org" else {**PAGE, "subdomain": "other-page"} if case == "before_subdomain" else PAGE
    after = {**PAGE, "organization_id": 8} if case == "after_org" else PAGE
    child = {**SERVICE, "id": 12} if case == "service_id" else {**SERVICE, "id": "11"} if case == "string_id" else SERVICE
    child_body = child if case == "bare_detail" else {"service": [child]} if case == "array_detail" else {"service": child}
    wire.responses.extend([{"status_page": before}, child_body, {"status_page": after}])
    with pytest.raises(fn.StatusPalAPIError): await run("get_service", {"subdomain": "owned-page", "service_id": 11})
    assert len(wire.calls) == (1 if case.startswith("before") else 3 if case == "after_org" else 2)

@pytest.mark.asyncio
async def test_bounded_first_page_unknown_completion_no_link_follow_or_guess(wire):
    wire.responses.append(page(PAGE, total=20, next_link="http://evil.test/?api_key=opaque")); result = await run("list_status_pages")
    assert result["data"]["pagination"]["provider_total_count"] == 20 and result["data"]["pagination"]["completion_verified"] is False
    assert result["data"]["pagination"]["continuation_supported"] is False and "evil.test" not in json.dumps(result) and len(wire.calls) == 1
    wire.responses.append(page(PAGE, total=20, next_link="https://statuspal.io/unknown?cursor=1"))
    with pytest.raises(fn.StatusPalAPIError, match="incomplete"): await fn.StatusPalNode.load_field_options("subdomain", CREDS, {"_user_id": "actor"})
    with pytest.raises(ValueError, match="continuation"): await fn.StatusPalNode.load_field_options("subdomain", CREDS, {"_user_id": "actor"}, page_token="remote")
    assert len(wire.calls) == 2

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [page(PAGE, status_pages={}), page(PAGE, meta={}), page(PAGE, links=[]), page(PAGE, PAGE), page(PAGE, total=0), page(total=True), {"status_page": PAGE}, {"error": "private"}, {"status": "rejected", **page(PAGE)}, {"status_pages": []}, page({**PAGE, "organization_id": "7"})])
async def test_http200_error_wrong_wrapper_meta_or_duplicate_never_success(wire, body):
    wire.responses.append(body)
    with pytest.raises(fn.StatusPalAPIError): await run("list_status_pages")
    assert len(wire.calls) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["401", "403", "429", "503", "204", "html", "empty", "duplicate", "nan", "deep", "oversize"])
async def test_nonjson_response_bounds_refusal_no_retry(wire, monkeypatch, case):
    response = Response(page())
    if case.isdigit(): response = Response(status=int(case), raw=b"private", mime="text/html")
    if case == "html": response.headers["Content-Type"] = "text/html"
    if case == "empty": response.raw = b""
    if case == "duplicate": response.raw = b'{"status_pages":[],"meta":{},"meta":{}}'
    if case == "nan": response.raw = b'{"status_pages":[],"opaque":1e309}'
    if case == "deep": response.raw = b'[' * 40 + b'0' + b']' * 40
    if case == "oversize": monkeypatch.setattr(fn, "MAX_BYTES", 32)
    wire.responses.append(response)
    with pytest.raises(fn.StatusPalAPIError) as error: await run("test_connection")
    assert error.value.authority_rejected is False and CREDS["api_key"] not in str(error.value) and len(wire.calls) == 1 and fn._PRIVATE_REQUEST.get() is False

@pytest.mark.asyncio
async def test_picker_scoped_id_labels_local_search_missing_parent_and_unknown_hierarchy(wire):
    scoped(wire, page(SERVICE, key="services")); result = await fn.StatusPalNode.load_field_options("service_id", CREDS, {"_user_id": "actor", "subdomain": "owned-page"}, search="11")
    assert result == {"options": [{"value": "11", "label": "11"}], "next_page_token": None}
    with pytest.raises(ValueError): await fn.StatusPalNode.load_field_options("service_id", CREDS, {"_user_id": "actor"})
    scoped(wire, {"service": {"id": 11, "name": "Owned", "parent_id": None}}); detail = await run("get_service", {"subdomain": "owned-page", "service_id": 11})
    assert detail["data"]["service"] == {"id": 11} and detail["data"]["service_page_id_returned"] is False
    with pytest.raises(fn.StatusPalAPIError): fn._service_metadata({**SERVICE, "children_ids": [12, 12]})
    with pytest.raises(fn.StatusPalAPIError): fn._service_metadata({**SERVICE, "parent_id": 11})

@pytest.mark.asyncio
async def test_mixed_encoded_key_echo_and_opaque_status_metadata(wire):
    wire.responses.append({"status_page": {**PAGE, "name": "synthetic%2b%2F%3dprivate-key"}, "status": {"opaque": True}})
    result = await run("get_status_page", {"subdomain": "owned-page", "include_names": True})
    assert result["data"]["status_page"]["name"] == "[redacted]" and fn._redact("https://statuspal.io/?access_token=opaque", CREDS["api_key"]) == "https://statuspal.io/[redacted]"

@pytest.mark.asyncio
async def test_current_raw_canonical_row_stored_picker_actor_binding_and_no_forged_blob_type(monkeypatch, wire):
    from nodes.core import run_op
    from repositories.credentials import CredentialsRepo
    from repositories.credential_approvals import CredentialApprovalRepo
    from utils import encryption
    pool = object(); row = CredentialValidationRow(fn.FAMILIES[0], "owner", 2, STAMP, 1, None, "sealed")
    authority = AsyncMock(return_value=row); monkeypatch.setattr(CredentialsRepo, "fetch_validation_authority", authority)
    monkeypatch.setattr(encryption, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda _: {**CREDS, "credential_type": "http_bearer", "owner_id": "forged"}))
    fresh = await fn.StatusPalNode.freshen_credential(CREDS, pool=pool, user_id="actor", credential_id="saved", organization_id="org", workflow_id="wf")
    assert fresh["credential_type"] == fn.FAMILIES[0] and fresh["owner_id"] == "owner" and fresh["token_version"] == 2 and fresh["approval_revision"] == 1
    context = fn._context(fresh, {"_user_id": "actor", "_approval_pool": "forged", "_credential_id": "forged"})
    assert context["_approval_pool"] is pool and context["_credential_id"] == "saved"
    with pytest.raises(ValueError, match="actor"): fn._context(fresh, {"_user_id": "other"})
    monkeypatch.setattr(run_op, "resolve_operation_credential", AsyncMock(return_value=CREDS)); monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    scoped(wire, page(SERVICE, key="services")); result = await run_node_lookup(node_type=fn.NODE_TYPE, field_name="service_id", credential_id="saved", user_id="actor", pool=pool, organization_id="org", workflow_id="wf", context={"subdomain": "owned-page"})
    assert result["options"] == [{"value": "11", "label": "11"}] and len(wire.calls) == 3 and all(call.args == ("saved", "actor", "org") for call in authority.call_args_list)

@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing", "revoked", "foreign"])
async def test_current_denial_before_decrypt_client(monkeypatch, wire, state):
    from repositories.credentials import CredentialsRepo
    from utils import encryption
    row = CredentialValidationRow(fn.FAMILIES[0], "owner", 2, STAMP, 1, None, "sealed")
    row = None if state == "missing" else replace(row, revoked_at=STAMP) if state == "revoked" else replace(row, credential_type="http_bearer")
    monkeypatch.setattr(CredentialsRepo, "fetch_validation_authority", AsyncMock(return_value=row)); monkeypatch.setattr(encryption, "get_encryption", lambda: (_ for _ in ()).throw(AssertionError("No decrypt")))
    with pytest.raises(ValueError): await fn.StatusPalNode.freshen_credential(CREDS, pool=object(), user_id="actor", credential_id="saved", organization_id="org")
    assert wire.calls == []

@pytest.mark.asyncio
async def test_raw_binding_changes_before_after_refusal_and_after_parser(monkeypatch, wire):
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    raw = {**CREDS, "owner_id": "owner", "token_version": 3, "approval_revision": 4, "updated_at": STAMP.isoformat()}; state = {"data": fn._shape(raw)}
    async def current(data, **context): return state["data"]
    monkeypatch.setattr(fn, "_current_data", current)
    wire.responses.append(page(PAGE)); await run("test_connection", credential_data=raw, credential_id="saved", pool=object())
    state["data"] = {**fn._shape(raw), "api_key": "changed-synthetic-key"}
    with pytest.raises(fn.StatusPalAPIError, match="binding changed"): await run("test_connection", credential_data=raw, credential_id="saved", pool=object())
    state["data"] = fn._shape(raw); wire.responses.append(Response(status=403, after=lambda: state.update(data={**fn._shape(raw), "approval_revision": 9})))
    with pytest.raises(fn.StatusPalAPIError, match="changed"): await run("test_connection", credential_data=raw, credential_id="saved", pool=object())
    state["data"] = fn._shape(raw); original = fn._page_metadata
    def metadata(*args, **kwargs):
        result = original(*args, **kwargs); state["data"] = {**fn._shape(raw), "token_version": 10}; return result
    monkeypatch.setattr(fn, "_page_metadata", metadata); wire.responses.append(page(PAGE))
    with pytest.raises(fn.StatusPalAPIError, match="changed"): await run("test_connection", credential_data=raw, credential_id="saved", pool=object())
    assert len(wire.calls) == 3

@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"region": "eu"}, {"organization_id": 8}, {"owner_id": "other-owner"}, {"token_version": 9}, {"approval_revision": 9}])
async def test_saved_execute_rejects_original_scope_and_policy_changes_before_client(monkeypatch, wire, change):
    raw = {**CREDS, "owner_id": "owner", "token_version": 3, "approval_revision": 4, "updated_at": STAMP.isoformat()}
    monkeypatch.setattr(fn, "_current_data", AsyncMock(return_value=fn._shape({**raw, **change})))
    node = NodeFactory.create_node(node_id="native", node_type=fn.NODE_TYPE, user_id="actor", node_data={"config": {"operation": "test_connection"}, "credentials": raw, "credential_id": "saved", "_approval_pool": object()})
    with pytest.raises(fn.StatusPalAPIError, match="binding changed"): await node.execute({})
    assert wire.calls == []

@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_actual_operation_and_stored_picker_admission_before_header_wire(monkeypatch, wire, status):
    from nodes.core import run_op
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(run_op, "resolve_operation_credential", AsyncMock(return_value=CREDS)); monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value={"status": status, "id": "approval", "new_request": False}))
    result = await run("test_connection", credential_id="saved", pool=object()); assert result["executed"] is False
    result = await run_node_lookup(node_type=fn.NODE_TYPE, field_name="service_id", credential_id="saved", user_id="actor", pool=object(), context={"subdomain": "owned-page"})
    assert result["status"] in ("pending_approval", "rejected") and wire.calls == []

@pytest.mark.asyncio
async def test_actual_postconnect_handler_empty_reachability_evidence_and_tristate(monkeypatch, wire):
    from cryptography.fernet import Fernet
    from utils import encryption
    from nodes.core import run_op
    from nodes.core.credential_validation import CredentialValidationContext, CredentialValidationUnavailable, CredentialValidationUnverified
    from nodes.core.connection_evidence import collect_evidence
    from repositories.credential_approvals import CredentialApprovalRepo
    from wss.handlers import credentials_handler as hm
    from wss.receiver.client_events import CredentialValidateAccessRequest
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    cipher = encryption.CredentialEncryption()
    monkeypatch.setattr(encryption, "get_encryption", lambda: cipher)
    monkeypatch.setattr(hm, "get_encryption", lambda: cipher)
    row = CredentialValidationRow(fn.FAMILIES[0], "owner", 2, STAMP, 0, None, cipher.encrypt_credential(CREDS)); context = CredentialValidationContext("saved", fn.NODE_TYPE, "actor", "org", object(), row)
    monkeypatch.setattr(CredentialValidationContext, "create", AsyncMock(return_value=context)); monkeypatch.setattr(CredentialValidationContext, "revalidate", AsyncMock(return_value=row)); monkeypatch.setattr(run_op, "resolve_operation_credential", AsyncMock(return_value=CREDS)); monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None)); monkeypatch.setattr(fn, "_current_data", AsyncMock(return_value=fn._shape(CREDS)))
    sent = []
    async def capture(_sio, sid, response): sent.append(response.model_dump()["data"])
    monkeypatch.setattr(hm, "send_event", capture); sio = AsyncMock(); sio.get_session.return_value = {"user_id": "actor"}
    handler = hm.CredentialsHandler(sio); handler.get_pool = AsyncMock(return_value=context.pool); request = CredentialValidateAccessRequest(request_id="fixture", credential_id="saved", node_type=fn.NODE_TYPE)
    wire.responses.append(page()); await handler.get_events()[request.event_name]("sid", request)
    assert sent[-1]["valid"] is True and sent[-1]["proves"] == "reachability" and sent[-1]["account_identity_verified"] is False
    wire.responses.append(page()); evidence = await collect_evidence(node_type=fn.NODE_TYPE, credential_data=CREDS, user_id="actor")
    assert evidence.reachable is True and evidence.proves == "reachability" and evidence.samples == []
    wire.responses.append(Response(status=403, raw=b"private", mime="text/html")); assert (await collect_evidence(node_type=fn.NODE_TYPE, credential_data=CREDS, user_id="actor")).reachable is None
    assert (await fn.StatusPalNode.validate_credential_access(CREDS))["valid"] is None
    for error, valid in [(CredentialValidationUnavailable("revoked"), False), (CredentialValidationUnverified("unknown"), None), (fn.StatusPalAPIError("Authority unavailable", authority_rejected=True), False), (fn.StatusPalAPIError("Request refused", http_status=403), None)]:
        monkeypatch.setattr(CredentialValidationContext, "run_operation", AsyncMock(side_effect=error)); assert (await fn.StatusPalNode.validate_credential_access(CREDS, validation_context=context))["valid"] is valid

@pytest.mark.asyncio
@pytest.mark.parametrize("grant", [False, True])
async def test_actor_first_owner_fallback_requires_positive_workflow_grant(monkeypatch, wire, grant):
    from repositories.credentials import CredentialsRepo
    from utils import credentials, encryption
    row = CredentialValidationRow(fn.FAMILIES[0], "owner", 2, STAMP, 1, None, "sealed")
    authority = AsyncMock(side_effect=[None, row] if grant else [None]); monkeypatch.setattr(CredentialsRepo, "fetch_validation_authority", authority); monkeypatch.setattr(credentials, "get_workflow_owner_id", AsyncMock(return_value="owner")); allowed = AsyncMock(return_value=grant); monkeypatch.setattr(credentials, "is_credential_authorized_for_workflow", allowed)
    monkeypatch.setattr(encryption, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda _: CREDS) if grant else (_ for _ in ()).throw(AssertionError("No decrypt")))
    if grant:
        fresh = await fn.StatusPalNode.freshen_credential(CREDS, pool=object(), user_id="actor", credential_id="saved", organization_id="org", workflow_id="wf"); assert fresh["owner_id"] == "owner" and fresh["_statuspal_authority"].user_id == "actor"
    else:
        with pytest.raises(ValueError, match="unavailable"): await fn.StatusPalNode.freshen_credential(CREDS, pool=object(), user_id="actor", credential_id="saved", organization_id="org", workflow_id="wf")
    assert [call.args[1] for call in authority.call_args_list] == (["actor", "owner"] if grant else ["actor"]) and allowed.call_args.args[1:] == ("wf", "saved") and wire.calls == []
