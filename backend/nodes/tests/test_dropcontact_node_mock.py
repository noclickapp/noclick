"""Dropcontact factory, dispatch, parser and staging credential-contract fixtures."""
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from nodes import dropcontact_node as dn
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation

CREDS = {"credential_type": dn.FAMILIES[0], "access_token": "synthetic+/=private-key"}
CONTACT = {"first_name": "Owned", "last_name": "Fixture", "company": "Owned Company"}
ACK = {"error": False, "success": True, "request_id": "req-42", "credits_left": 12}
ROW = {**CONTACT, "email": [{"email": "private@example.test", "qualification": "nominative@pro"}], "custom_fields": {"owned_ref": "fixture"}, "warnings": {"empty_field": ["phone", "private_field"], "only_organization_data": False}, "private_extra": "omit"}
OPS = ["test_connection", "get_credits", "enrich_contact", "enrich_batch", "get_status", "get_results"]

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
        assert kwargs == {"timeout": 20.0, "follow_redirects": False, "trust_env": False}
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
    monkeypatch.setattr(dn, "_current_data", AsyncMock(side_effect=[shaped, shaped, {**shaped, "access_token": "changed-private-token"}]))
    wire.responses.append(ACK)
    with pytest.raises(dn.DropcontactAPIError, match="changed"): await run("get_credits")
    assert len(wire.calls) == 2

@pytest.mark.asyncio
async def test_actual_dispatch_rechecks_authority_after_native_result_parser(monkeypatch, wire):
    shaped = dn._shape(CREDS)
    monkeypatch.setattr(dn, "_current_data", AsyncMock(side_effect=[shaped, shaped, shaped, {**shaped, "access_token": "changed-private-token"}]))
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
async def test_saved_credential_reload_uses_staging_access_policy(monkeypatch):
    from utils import credentials
    loader = AsyncMock(return_value=CREDS)
    monkeypatch.setattr(credentials, "resolve_credential_with_owner_fallback", loader)
    pool = object()
    current = await dn.DropcontactNode.freshen_credential(
        CREDS, pool=pool, user_id="actor", credential_id="saved", organization_id="org", workflow_id="workflow",
    )
    loader.assert_awaited_once_with("saved", "actor", pool, org_id="org", workflow_id="workflow")
    assert dn._binding(current) == dn._binding(CREDS)
    assert dn._context(current, {"_user_id": "actor"})["_credential_id"] == "saved"
    for value in (None, {**CREDS, "credential_type": "http_bearer"}):
        loader.return_value = value
        with pytest.raises(ValueError):
            await dn.DropcontactNode.freshen_credential(CREDS, pool=pool, user_id="actor", credential_id="saved", organization_id="org")

@pytest.mark.asyncio
@pytest.mark.parametrize("status,valid", [(200, True), (401, False), (403, False), (429, None), (500, None)])
async def test_staging_validation_hook_uses_free_probe_and_honest_result(wire, status, valid):
    wire.responses.append(Response(ACK, status=status))
    result = await dn.DropcontactNode.validate_credential_access(CREDS)
    assert result["valid"] is valid
    assert len(wire.calls) == 1 and json.loads(wire.calls[0]["content"]) == {"data": [{}]}
    if valid:
        assert result["proves"] == "reachability" and result["account_identity_verified"] is False
