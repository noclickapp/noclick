"""Prepared UNRUN Dropcontact factory/dispatch/parser/authority fixtures."""
import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from nodes import dropcontact_node as dn
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation, run_node_lookup
from repositories.credentials import CredentialValidationRow

CREDS = {"credential_type": dn.FAMILIES[0], "access_token": "synthetic+/=private-key"}
STAMP = datetime(2026, 10, 7, tzinfo=timezone.utc)
CONTACT = {"first_name": "Owned", "last_name": "Fixture", "company": "Owned Company"}
ACK = {"error": False, "success": True, "request_id": "req-42", "credits_left": 12}
ROW = {**CONTACT, "email": [{"email": "private@example.test", "qualification": "nominative@pro"}], "custom_fields": {"owned_ref": "fixture"}, "warnings": {"empty_field": ["phone", "private_field"], "only_organization_data": False}, "private_extra": "omit"}
OPS = ["test_connection", "get_credits", "enrich_contact", "enrich_batch", "get_status", "get_results"]

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

class Response:
    def __init__(self, payload=None, *, status=200, raw=None, content_type="application/json"):
        self.status_code, self.headers = status, {"Content-Type": content_type}
        self.payload, self.raw = payload, raw
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def aiter_bytes(self, chunk_size):
        assert chunk_size == 65536
        yield self.raw if self.raw is not None else json.dumps(self.payload).encode()

@pytest.fixture
def wire(monkeypatch):
    calls, responses = [], []
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, method, url, **kwargs):
            calls.append({"method": method, "url": url, **kwargs})
            logging.getLogger("httpx").info("private %s", kwargs)
            item = responses.pop(0)
            return item if isinstance(item, Response) else Response(item)
    def client(**kwargs):
        assert kwargs == {"require_public": True, "timeout": 20.0, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(dn, "guarded_async_client", client)
    return SimpleNamespace(calls=calls, responses=responses)

async def run(op, args=None, *, credential_data=None, **context):
    return await run_node_operation(node_type=dn.NODE_TYPE, operation=op, arguments=args or {}, credential_data=credential_data or CREDS, user_id="actor", **context)

def completed(rows, **values): return {"error": False, "success": True, "data": rows, **values}

def test_actual_factory_closed_operation_set_original_family_and_numeric_form():
    node = NodeFactory.create_node(node_id="native", node_type=dn.NODE_TYPE, user_id="actor", node_data={"config": {"operation": "get_results", "request_id": "req-42", "expected_contact_count": "2"}, "credentials": CREDS})
    assert node.config.config.expected_contact_count == 2
    defs = dn.DropcontactNode.get_config_schema()["$defs"]
    assert sorted(d["properties"]["operation"]["const"] for d in defs.values() if "operation" in d.get("properties", {})) == sorted(OPS)
    for family in (None, "http_bearer", "dropcontact_oauth"):
        bad = {"credential_id": "saved", "config": {"operation": "test_connection"}, "credentials": {**CREDS, "credential_type": family}}
        assert dn.DropcontactNode.validate_config(bad)["valid"] is False
        with pytest.raises(ValueError, match="family"): dn.DropcontactNode.parse_config(bad)
    for cfg in [{"operation": "mcp_enrich"}, {"operation": "test_connection", "url": "https://evil.test"}, {"operation": "get_results", "request_id": "../other"}, {"operation": "get_results", "request_id": "req-42", "forceResults": True}, {"operation": "get_results", "request_id": "req-42", "expected_contact_count": True}, {"operation": "enrich_contact", **CONTACT, "custom_callback_url": "https://evil.test"}]:
        with pytest.raises(ValueError): dn.DropcontactNode.parse_config({"config": cfg, "credentials": CREDS})

@pytest.mark.parametrize("contact", [{}, {"email": "private@example.test"}, {"linkedin": "https://www.linkedin.com/in/owned"}, {"company": "Owned"}, {**CONTACT, "headquarter": "unknown"}, {**CONTACT, "phone": None}, {**CONTACT, "job": 7}, {**CONTACT, "custom_fields": {"nested": {"x": "v"}}}])
def test_current_company_context_unknown_fields_and_exact_string_contract(contact):
    with pytest.raises(ValueError): dn._contacts_json(json.dumps([contact]))

@pytest.mark.parametrize("contact", [CONTACT, {"full_name": "Owned Fixture", "website": "owned.example.test"}, {"email": "private@example.test", "company_linkedin": "https://www.linkedin.com/company/owned"}, {"linkedin": "https://www.linkedin.com/in/owned", "num_siren": "500500500"}])
def test_supported_identity_company_combinations(contact):
    assert dn._contacts_json(json.dumps([contact])) == [contact]

@pytest.mark.parametrize("text", ['{}', '[]', '[null]', '[{"company":"Owned","company":"Other","email":"private@example.test"}]', '[{"company":"Owned","email":"private@example.test","x":NaN}]', '[{"company":"Owned","email":"private@example.test","x":1e309}]', '['*40+'0'+']'*40])
def test_closed_batch_json_ambiguity_finiteness_depth_and_array(text):
    with pytest.raises(ValueError): dn._contacts_json(text)

def test_exact_utf8_contact_limit_and_batch250_boundary():
    base = {**CONTACT, "custom_fields": {"a": "x"*4096, "b": "x"*4096, "c": "x"*4096, "d": ""}}
    remaining = dn.MAX_CONTACT_BYTES - 1 - len(dn._json(base))
    assert 0 < remaining < 4096
    base["custom_fields"]["d"] = "x"*remaining
    assert len(dn._json(dn._contact(base))) == dn.MAX_CONTACT_BYTES - 1
    base["custom_fields"]["d"] += "x"
    with pytest.raises(ValueError, match="UTF8"): dn._contact(base)
    with pytest.raises(ValueError, match="UTF8"): dn._contact({"first_name": "€"*4000, "last_name": "Owned", "company": "€"*1000})
    assert len(dn._contacts_json(json.dumps([CONTACT]*250))) == 250
    with pytest.raises(ValueError): dn._contacts_json(json.dumps([CONTACT]*251))

@pytest.mark.asyncio
async def test_actual_free_probe_exact_body_header_no_identity_and_private_logs(wire, caplog):
    wire.responses.append(ACK)
    with caplog.at_level(logging.DEBUG): result = await run("test_connection")
    call = wire.calls[0]
    assert call["method"] == "POST" and call["url"] == "https://api.dropcontact.com/v1/enrich/all" and json.loads(call["content"]) == {"data": [{}]}
    assert call["headers"] == {"X-Access-Token": CREDS["access_token"], "Accept": "application/json", "Content-Type": "application/json"}
    assert result["data"]["credits_left"] == 12 and result["data"]["protected_read_completed"] is True and result["data"]["account_identity_verified"] is False and result["data"]["enrichment_permissions_verified"] is False
    assert CREDS["access_token"] not in caplog.text and dn._PRIVATE_REQUEST.get() is False
    logging.getLogger("httpx").warning("unrelated outside private context")
    assert "unrelated outside private context" in caplog.text

@pytest.mark.asyncio
async def test_actual_dispatch_single_and_batch_sparse_custom_fields_language_and_ack(wire):
    wire.responses.extend([ACK, {**ACK, "data": [{**CONTACT, "index": 0, "errors": {"only_contact_data": False}, "warnings": {"only_organization_data": False}}]}])
    single = await run("enrich_contact", {**CONTACT, "custom_fields_json": "  ", "language": "fr", "confirm_existing_credits": True})
    batch = await run("enrich_batch", {"contacts_json": json.dumps([{**CONTACT, "custom_fields": {"owned_ref": "one"}}, {"full_name": "Owned Second", "website": "owned.example.test"}]), "siren": True, "confirm_existing_credits": True})
    assert json.loads(wire.calls[0]["content"]) == {"data": [CONTACT], "siren": False}
    sent = json.loads(wire.calls[1]["content"])
    assert sent["language"] == "en" and sent["siren"] is True and sent["data"][0]["custom_fields"] == {"owned_ref": "one"}
    assert single["data"]["state"] == "accepted" and single["data"]["data"] is None and single["data"]["submitted_contact_count"] == 1
    assert batch["data"]["missing_response_row_count"] == 1 and batch["data"]["complete_record_coverage_verified"] is False and batch["data"]["original_input_order_verified"] is False
    assert len(wire.calls) == 2 and all(c["method"] == "POST" for c in wire.calls)

@pytest.mark.asyncio
async def test_confirmation_and_invalid_factory_payload_before_any_transport(wire):
    for op, args in [("enrich_contact", CONTACT), ("enrich_batch", {"contacts_json": json.dumps([CONTACT])})]:
        with pytest.raises(ValueError, match="Confirm"): await run(op, args)
    with pytest.raises(ValueError): await run("enrich_batch", {"contacts_json": '[{}]', "confirm_existing_credits": True})
    assert wire.calls == []

@pytest.mark.asyncio
async def test_processing_completed_empty_missing_credit_and_order_are_distinct(wire):
    wire.responses.extend([{"error": False, "success": False, "reason": dn.NOT_READY}, completed([]), completed([{**ROW, "index": 1}, {**ROW, "index": 0}], request_id="req-42", credits_left=9)])
    processing = await run("get_results", {"request_id": "req-42"}); empty = await run("get_results", {"request_id": "req-42"}); result = await run("get_results", {"request_id": "req-42", "expected_contact_count": "3"})
    assert processing["data"]["state"] == "processing" and processing["data"]["data"] is None and "credits_left" not in processing["data"]
    assert empty["data"]["state"] == "completed" and empty["data"]["data"] == [] and "credits_left" not in empty["data"]
    rows = result["data"]["data"]
    assert [row["provider_index"] for row in rows] == [1, 0] and [row["response_position"] for row in rows] == [0, 1]
    assert result["data"]["missing_response_row_count"] == 1 and result["data"]["expected_count_source"] == "caller_supplied_expectation" and result["data"]["submission_ancestry_verified"] is False
    assert "private@example.test" not in json.dumps(result) and "Owned Company" not in json.dumps(result) and "private_field" not in json.dumps(result)
    assert rows[0]["warnings"]["empty_field"] == {"count": 2, "supported_fields": ["phone"], "unknown_field_count": 1}
    assert len(wire.calls) == 3 and all(c["method"] == "GET" and c["url"].endswith("/req-42") for c in wire.calls)

@pytest.mark.asyncio
async def test_opt_in_private_output_and_original_email_string_not_new_verification(wire):
    wire.responses.extend([completed([ROW]), completed([{**ROW, "email": "original@example.test"}])])
    first = await run("get_results", {"request_id": "req-42", "include_contact_data": True, "include_custom_fields": True})
    second = await run("get_results", {"request_id": "req-42", "include_contact_data": True})
    assert first["data"]["data"][0]["email"] == ROW["email"] and first["data"]["data"][0]["custom_fields"] == {"owned_ref": "fixture"}
    assert "private_extra" not in first["data"]["data"][0] and second["data"]["data"][0]["email"] == "original@example.test"
    assert "newly_verified" not in json.dumps(second)

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"error": False, "success": True}, completed(None), completed([ROW], request_id="different"), {"error": False, "success": False, "reason": "private unknown"}, {"error": True, "success": True}, completed([ROW], status="rejected"), completed([{**ROW, "index": True}]), completed([{"custom_fields": {"bad": 7}}])])
async def test_response_contract_and_scope_malformed_no_replay(wire, body):
    wire.responses.append(body)
    with pytest.raises(dn.DropcontactAPIError): await run("get_results", {"request_id": "req-42"})
    assert len(wire.calls) == 1

@pytest.mark.asyncio
async def test_failed_flags_preserved_and_exact_picker_uses_one_route_not_history(wire):
    wire.responses.extend([{"error": True, "success": False, "reason": "private diagnostic", "credits_left": 7}, {"error": False, "success": False, "reason": dn.NOT_READY}])
    failed = await run("get_results", {"request_id": "req-42"})
    assert failed["status"] == "error" and failed["data"]["error"] is True and failed["data"]["success"] is False and failed["data"]["state"] == "failed" and "private diagnostic" not in json.dumps(failed)
    assert await dn.DropcontactNode.load_field_options("request_id", CREDS, context={"_user_id": "actor"}) == {"options": [], "next_page_token": None}
    option = await dn.DropcontactNode.load_field_options("request_id", CREDS, context={"_user_id": "actor"}, search="req-42")
    assert option == {"options": [{"value": "req-42", "label": "req-42"}], "next_page_token": None} and wire.calls[-1]["url"].endswith("/req-42")
    with pytest.raises(ValueError): await dn.DropcontactNode.load_field_options("request_id", CREDS, context={"_user_id": "actor"}, search="req-42", page_token="invented")
    assert len(wire.calls) == 2

@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["401", "403", "429", "500", "html", "empty", "duplicate", "nan", "deep"])
async def test_safe_http_json_errors_no_secret_or_retry(wire, case):
    response = Response(ACK)
    if case.isdigit(): response = Response(status=int(case), raw=b"private nonJSON", content_type="text/plain")
    if case == "html": response.headers["Content-Type"] = "text/html"
    if case == "empty": response.raw = b""
    if case == "duplicate": response.raw = b'{"error":false,"error":true,"success":true}'
    if case == "nan": response.raw = b'{"error":false,"success":true,"extra":NaN}'
    if case == "deep": response.raw = b'['*40+b'0'+b']'*40
    wire.responses.append(response)
    with pytest.raises(dn.DropcontactAPIError) as error: await run("get_credits")
    assert error.value.authority_rejected is (case in ("401", "403")) and CREDS["access_token"] not in str(error.value) and len(wire.calls) == 1

@pytest.mark.asyncio
async def test_redaction_bound_and_stale_authority_before_result_acceptance(monkeypatch, wire):
    wire.responses.append(completed([{**ROW, "company": "synthetic%2b%2F%3dprivate-key"}]))
    result = await run("get_results", {"request_id": "req-42", "include_contact_data": True})
    assert result["data"]["data"][0]["company"] == "[redacted]"
    shaped = dn._shape(CREDS)
    monkeypatch.setattr(dn, "_current_data", AsyncMock(side_effect=[shaped, shaped, {**shaped, "approval_revision": 2}]))
    wire.responses.append(ACK)
    with pytest.raises(dn.DropcontactAPIError, match="changed"): await run("get_credits")
    assert len(wire.calls) == 2

@pytest.mark.asyncio
async def test_actual_dispatch_rechecks_authority_after_native_result_parser(monkeypatch, wire):
    shaped = dn._shape(CREDS)
    monkeypatch.setattr(dn, "_current_data", AsyncMock(side_effect=[shaped, shaped, shaped, {**shaped, "token_version": 9}]))
    wire.responses.append(ACK)
    with pytest.raises(dn.DropcontactAPIError, match="changed"): await run("get_credits")
    assert len(wire.calls) == 1

@pytest.mark.asyncio
async def test_actual_request_serialization_and_stream_byte_caps(monkeypatch, wire):
    monkeypatch.setattr(dn, "MAX_BYTES", 80)
    with pytest.raises(ValueError, match="request byte bound"):
        await run("enrich_contact", {**CONTACT, "confirm_existing_credits": True})
    assert wire.calls == []
    wire.responses.append({**ACK, "unknown": "x"*100})
    with pytest.raises(dn.DropcontactAPIError, match="response exceeds"):
        await run("get_credits")
    assert len(wire.calls) == 1 and dn._PRIVATE_REQUEST.get() is False

@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing", "revoked", "foreign_family"])
async def test_invalid_current_row_before_decrypt_or_transport(monkeypatch, wire, state):
    from repositories.credentials import CredentialsRepo
    from utils import encryption
    row = CredentialValidationRow(dn.FAMILIES[0], "owner", 2, STAMP, 1, None, "sealed")
    if state == "missing": row = None
    if state == "revoked": row = replace(row, revoked_at=STAMP)
    if state == "foreign_family": row = replace(row, credential_type="http_bearer")
    monkeypatch.setattr(CredentialsRepo, "fetch_validation_authority", AsyncMock(return_value=row))
    monkeypatch.setattr(encryption, "get_encryption", lambda: (_ for _ in ()).throw(AssertionError("No decrypt")))
    with pytest.raises(ValueError): await dn.DropcontactNode.freshen_credential(CREDS, pool=object(), user_id="actor", credential_id="saved", organization_id="org")
    assert wire.calls == []

@pytest.mark.asyncio
async def test_actual_execute_raw_owner_version_grant_metadata_retained(monkeypatch, wire):
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    raw = {**CREDS, "owner_id": "owner", "token_version": 3, "approval_revision": 4, "updated_at": STAMP.isoformat()}
    loader = AsyncMock(return_value=dn._shape(raw)); monkeypatch.setattr(dn, "_current_data", loader)
    wire.responses.append(ACK)
    result = await run("test_connection", credential_data=raw, credential_id="saved", pool=object())
    assert result["data"]["credits_left"] == 12 and loader.call_args_list[0].args[0]["owner_id"] == "owner" and loader.call_args_list[0].args[0]["token_version"] == 3 and loader.call_args_list[0].args[0]["approval_revision"] == 4
    loader.return_value = {**dn._shape(raw), "token_version": 4}
    with pytest.raises(dn.DropcontactAPIError, match="changed"): await run("test_connection", credential_data=raw, credential_id="saved", pool=object())
    assert len(wire.calls) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_actual_admission_blocks_probe_submission_and_exact_lookup(monkeypatch, wire, status):
    from nodes.core import run_op
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(run_op, "resolve_operation_credential", AsyncMock(return_value=CREDS))
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value={"status": status, "id": "approval", "new_request": False}))
    for op, args in [("test_connection", {}), ("enrich_contact", {**CONTACT, "confirm_existing_credits": True})]:
        result = await run(op, args, credential_id="saved", pool=object()); assert result["executed"] is False
    result = await run_node_lookup(node_type=dn.NODE_TYPE, field_name="request_id", credential_id="saved", user_id="actor", pool=object(), search="req-42")
    assert result["status"] in ("pending_approval", "rejected") and wire.calls == []

@pytest.mark.asyncio
async def test_actual_post_connect_handler_trusted_context_tristate_and_evidence(monkeypatch, wire):
    from nodes.core import run_op
    from nodes.core.credential_validation import CredentialValidationContext, CredentialValidationUnavailable, CredentialValidationUnverified
    from nodes.core.connection_evidence import collect_evidence
    from repositories.credential_approvals import CredentialApprovalRepo
    from wss.handlers import credentials_handler as hm
    from wss.receiver.client_events import CredentialValidateAccessRequest
    from cryptography.fernet import Fernet
    from utils import encryption
    # The handler loads the current encrypted row before calling the node hook.
    # Keep the real decrypt path and give it a valid, test-only credential blob.
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(encryption, "_encryption_instance", encryption.CredentialEncryption())
    sealed = encryption.get_encryption().encrypt_credential(CREDS)
    row = CredentialValidationRow(dn.FAMILIES[0], "owner", 2, STAMP, 0, None, sealed)
    context = CredentialValidationContext("saved", dn.NODE_TYPE, "actor", "org", object(), row)
    monkeypatch.setattr(CredentialValidationContext, "create", AsyncMock(return_value=context)); monkeypatch.setattr(CredentialValidationContext, "revalidate", AsyncMock(return_value=row)); monkeypatch.setattr(run_op, "resolve_operation_credential", AsyncMock(return_value=CREDS)); monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None)); monkeypatch.setattr(dn, "_current_data", AsyncMock(return_value=dn._shape(CREDS)))
    sent = []
    async def capture(_sio, sid, response): sent.append(response.model_dump()["data"])
    monkeypatch.setattr(hm, "send_event", capture)
    sio = AsyncMock(); sio.get_session.return_value = {"user_id": "actor"}
    handler = hm.CredentialsHandler(sio); handler.get_pool = AsyncMock(return_value=context.pool)
    request = CredentialValidateAccessRequest(request_id="fixture", credential_id="saved", node_type=dn.NODE_TYPE)
    wire.responses.append(ACK); await handler.get_events()[request.event_name]("sid", request)
    assert sent[-1]["valid"] is True and sent[-1]["proves"] == "reachability" and sent[-1]["account_identity_verified"] is False
    wire.responses.append(ACK); evidence = await collect_evidence(node_type=dn.NODE_TYPE, credential_data=CREDS, user_id="actor")
    assert evidence.reachable is True and evidence.proves == "reachability" and [s.label for s in evidence.samples] == ["12"]
    assert (await dn.DropcontactNode.validate_credential_access(CREDS))["valid"] is None
    for error, valid in [(CredentialValidationUnavailable("revoked"), False), (CredentialValidationUnverified("unknown"), None), (dn.DropcontactAPIError("Quota refused", authority_rejected=True), False), (dn.DropcontactAPIError("Unknown"), None)]:
        monkeypatch.setattr(CredentialValidationContext, "run_operation", AsyncMock(side_effect=error))
        assert (await dn.DropcontactNode.validate_credential_access(CREDS, validation_context=context))["valid"] is valid
