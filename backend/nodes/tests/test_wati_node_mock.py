"""WATI operations through staging dispatch and guarded transport; synthetic data only."""
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from nodes import wati_node as wn
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation

CREDS = {"credential_type": wn.FAMILIES[0], "api_token": "wati_synthetic+/=private-key"}
CONTACT = {"id": "contact42", "wa_id": "919876543210", "name": "Private name", "phone": "private", "photo": "https://private.test/?token=private", "custom_params": [{"name": "private", "value": "private"}], "created": "2026-10-01T00:00:00Z", "contact_status": "Active", "channel_id": "channel42", "opted_in": True, "allow_broadcast": True, "teams": ["private"]}
OPS = ["test_connection", "list_contacts", "get_contact", "get_contact_count", "create_contact", "update_contact_attributes", "soft_delete_contact", "list_channels", "list_templates", "get_template", "list_campaigns", "get_campaign", "list_segments", "get_segment", "list_message_metadata"]

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

class Response:
    def __init__(self, payload=None, *, status=200, raw=None, content_type="application/json"):
        self.status_code, self.headers = status, {"content-type": content_type}
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
            logging.getLogger("httpx").info("private %s", kwargs["headers"]["Authorization"])
            logging.getLogger("httpcore.http2").debug("private %s", kwargs)
            item = responses.pop(0)
            return item if isinstance(item, Response) else Response(item)
    def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(wn, "guarded_async_client", client)
    return SimpleNamespace(calls=calls, responses=responses)

async def run(op, args=None, **context):
    return await run_node_operation(node_type=wn.NODE_TYPE, operation=op, arguments=args or {}, credential_data=CREDS, user_id="actor", **context)

def contacts(rows, page=1, size=20):
    return {"contact_list": rows, "page_number": page, "page_size": size}

def test_actual_factory_closed_operation_set_family_and_numeric_forms():
    node = NodeFactory.create_node(node_id="native", node_type=wn.NODE_TYPE, user_id="actor", node_data={"config": {"operation": "list_segments", "page_number": "2", "page_size": "20", "source": "1", "sort_field": "2"}, "credentials": CREDS})
    assert node.config.config.page_number == 2 and node.config.config.source == 1 and node.config.config.sort_field == 2
    defs = wn.WATINode.get_config_schema()["$defs"]
    assert sorted(d["properties"]["operation"]["const"] for d in defs.values() if "operation" in d.get("properties", {})) == sorted(OPS)
    for family in (None, "http_bearer", "wati_legacy_jwt"):
        bad = {"credential_id": "saved", "config": {"operation": "test_connection"}, "credentials": {**CREDS, "credential_type": family}}
        assert wn.WATINode.validate_config(bad)["valid"] is False
        with pytest.raises(ValueError, match="family"): wn.WATINode.parse_config(bad)
    for cfg in [{"operation": "send_message"}, {"operation": "list_contacts", "tenant_id": "tenant"}, {"operation": "get_contact", "contact_id": "channel:phone"}, {"operation": "list_contacts", "page_size": 101}, {"operation": "list_contacts", "page_number": True}, {"operation": "list_segments", "source": "3"}, {"operation": "update_contact_attributes", "contact_id": "contact42", "custom_params_json": '{"clear":null}'}]:
        with pytest.raises(ValueError): wn.WATINode.parse_config({"config": cfg, "credentials": CREDS})

@pytest.mark.asyncio
async def test_fixed_v3_bearer_no_tenant_closed_output_and_private_logs(wire, caplog):
    wire.responses.append(contacts([CONTACT], size=10))
    with caplog.at_level(logging.DEBUG): result = await run("test_connection")
    call = wire.calls[0]
    assert call["url"] == "https://live-mt-server.wati.io/api/ext/v3/contacts" and call["params"] == {"page_number": 1, "page_size": 10}
    assert call["headers"] == {"Authorization": "Bearer " + CREDS["api_token"], "Accept": "application/json", "Content-Type": "application/json"}
    proof = result["data"]
    assert proof["protected_read_completed"] is True and proof["account_identity_verified"] is False and proof["write_permissions_verified"] is False
    assert proof["results"][0] == {"id": "contact42", "created": CONTACT["created"], "contact_status": "Active", "channel_id": "channel42"}
    assert "Private name" not in json.dumps(result) and CREDS["api_token"] not in caplog.text
    assert wn._PRIVATE_REQUEST.get() is False
    logging.getLogger("httpx").warning("unrelated outside private context")
    assert "unrelated outside private context" in caplog.text

@pytest.mark.asyncio
async def test_nullable_empty_short_and_unknown_extra_total_are_distinct(wire):
    wire.responses.extend([contacts(None), contacts([]), {**contacts([CONTACT]), "total": 1}])
    null = (await run("list_contacts"))["data"]
    empty = (await run("list_contacts"))["data"]
    short = (await run("list_contacts"))["data"]
    assert null["results"] is None and null["collection_exhausted"] is None and null["next_page_number"] is None
    assert empty["collection_exhausted"] is True and empty["next_page_number"] is None
    assert short["collection_exhausted"] is None and short["next_page_number"] == 2 and "total" not in short

@pytest.mark.asyncio
async def test_empty_evidence_is_only_reachability(monkeypatch, wire):
    wire.responses.append(contacts([], size=10)); result = await run("test_connection")
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core import run_op
    probe = AsyncMock(return_value=result); monkeypatch.setattr(run_op, "run_node_operation", probe)
    evidence = await collect_evidence(node_type=wn.NODE_TYPE, credential_data=CREDS, user_id="actor")
    assert evidence.reachable is True and wn.WATINode.connection_evidence.proves == "reachability" and evidence.samples == [] and evidence.account_label is None and probe.await_count == 1

@pytest.mark.asyncio
async def test_real_dispatcher_contact_wire_receipts_and_separate_readback(wire):
    wire.responses.extend([CONTACT, CONTACT, {"contact_list": [CONTACT]}, CONTACT, {"contactId": "contact42", "deleted": False, "cleanupCompleted": True}, CONTACT])
    created = await run("create_contact", {"name": "Private name", "whatsapp_number": "919876543210", "custom_params_json": '{"internal_label":"owned"}', "confirm_changes": True})
    updated = await run("update_contact_attributes", {"contact_id": "contact42", "custom_params_json": '{"internal_label":"changed"}', "confirm_changes": True})
    deleted = await run("soft_delete_contact", {"contact_id": "contact42", "confirm_changes": True})
    readback = await run("get_contact", {"contact_id": "contact42"})
    assert [c["method"] for c in wire.calls] == ["POST", "GET", "PUT", "GET", "DELETE", "GET"]
    assert wire.calls[0]["json"] == {"name": "Private name", "whatsapp_number": "919876543210", "custom_params": [{"name": "internal_label", "value": "owned"}]}
    assert wire.calls[2]["json"] == {"contacts": [{"target": "contact42", "customParams": [{"name": "internal_label", "value": "changed"}]}]}
    for result in (created, updated, deleted):
        assert result["data"]["acknowledged"] is True and result["data"]["independent_readback_verified"] is False and result["data"]["notification_absence_verified"] is False
    assert created["data"]["atomic_new_creation_verified"] is False
    assert deleted["data"]["provider_reported_deleted"] is False and deleted["data"]["provider_reported_cleanup_completed"] is True and deleted["data"]["physical_erasure_verified"] is False
    assert readback["data"]["independent_get_completed"] is True and readback["data"]["physical_erasure_verified"] is False

@pytest.mark.asyncio
async def test_write_confirmation_target_and_receipt_errors_stop_without_replay(wire):
    for op, args in [("create_contact", {"name": "Name", "whatsapp_number": "919876543210"}), ("soft_delete_contact", {"contact_id": "contact42"}), ("update_contact_attributes", {"contact_id": "contact42", "custom_params_json": '{"x":"v"}'})]:
        with pytest.raises(ValueError, match="Confirm"): await run(op, args)
    assert wire.calls == []
    wire.responses.append({**CONTACT, "id": "other"})
    with pytest.raises(wn.WATIAPIError, match="another resource"): await run("soft_delete_contact", {"contact_id": "contact42", "confirm_changes": True})
    wire.responses.extend([CONTACT, {"contactId": "other", "deleted": True, "cleanupCompleted": True}])
    with pytest.raises(wn.WATIAPIError, match="may have applied"): await run("soft_delete_contact", {"contact_id": "contact42", "confirm_changes": True})
    wire.responses.extend([CONTACT, {"contact_list": None}])
    with pytest.raises(wn.WATIAPIError, match="may have applied"): await run("update_contact_attributes", {"contact_id": "contact42", "custom_params_json": '{"x":"v"}', "confirm_changes": True})
    assert [c["method"] for c in wire.calls] == ["GET", "GET", "DELETE", "GET", "PUT"]

@pytest.mark.asyncio
async def test_channel_id_is_resolved_to_actual_name_and_campaign_parent_verified(wire):
    wire.responses.extend([{"channels": [{"id": "channel42", "name": "Owned channel", "channel": "whatsapp", "platform_id": "private"}]}, {"broadcasts": [{"id": "campaign42", "channel_id": "channel42", "status": "Scheduled", "fallback_templates": [{"private": True}]}], "page_number": 1, "page_size": 20, "total": 1}])
    result = await run("list_campaigns", {"channel_id": "channel42"})
    assert wire.calls[1]["params"]["channel"] == "Owned channel"
    assert result["data"]["collection_exhausted"] is True and result["data"]["results"] == [{"id": "campaign42", "channel_id": "channel42", "status": "Scheduled"}]
    wire.responses.extend([{"channels": [{"id": "channel42", "name": "Owned channel"}]}, {"broadcasts": [{"id": "campaign42", "channel_id": "other"}], "page_number": 1, "page_size": 20, "total": 1}])
    with pytest.raises(wn.WATIAPIError, match="outside"): await run("list_campaigns", {"channel_id": "channel42"})
    wire.responses.append({"channels": []})
    with pytest.raises(ValueError, match="default channel"): await run("list_templates", {"channel_id": "missing"})
    assert wire.calls[-1]["url"].endswith("/channels")

@pytest.mark.asyncio
async def test_segments_camel_paging_channel_no_echo_and_closed_detail_fields(wire):
    wire.responses.extend([{"segments": [{"id": "seg42", "name": "Segment", "status": 1, "groups": [{"private": True}]}], "pageNumber": 2, "pageSize": 20, "total": 21}, {"channels": [{"id": "channel42", "name": "private", "channel": "whatsapp"}]}, {"id": "campaign42", "status": "Completed", "statistics": {"total_read": 3, "raw": "private"}}, {"id": "seg42", "totalContactCount": 3, "hitCountPercentage": None, "deletedAt": "2026-10-01T00:00:00Z", "groups": ["private"]}])
    segment = await run("list_segments", {"page_number": "2", "source": "1", "sort_field": "2"})
    assert wire.calls[0]["params"] == {"page_number": 2, "page_size": 20, "source": 1, "sort_field": 2}
    assert segment["data"]["collection_exhausted"] is True and "groups" not in segment["data"]["results"][0]
    channel = await run("list_channels")
    assert channel["data"]["page_scope_source"] == "request_only" and channel["data"]["results"] == [{"id": "channel42", "channel": "whatsapp"}]
    campaign = await run("get_campaign", {"campaign_id": "campaign42"}); detail = await run("get_segment", {"segment_id": "seg42"})
    assert campaign["data"]["statistics"] == {"total_read": 3} and detail["data"]["hitCountPercentage"] is None and "deletedAt" not in detail["data"] and "groups" not in detail["data"]

@pytest.mark.asyncio
async def test_message_only_schema_fields_and_returned_conversation_witness(wire):
    event = {"id": "event42", "conversation_id": "conv42", "event_type": "message", "text": "private", "status": "READ", "media": "https://private.test/?token=private", "operator": "private"}
    wire.responses.extend([{"message_list": [event], "page_number": 1, "page_size": 20}, {"message_list": [], "page_number": 1, "page_size": 20}, {"message_list": [{**event, "conversation_id": "other"}], "page_number": 1, "page_size": 20}])
    first = await run("list_message_metadata", {"conversation_id": "conv42"})
    assert first["data"]["results"] == [{"id": "event42", "conversation_id": "conv42", "event_type": "message"}] and first["data"]["returned_conversation_scope_verified"] is True
    empty = await run("list_message_metadata", {"conversation_id": "conv42"})
    assert empty["data"]["returned_conversation_scope_verified"] is False
    with pytest.raises(wn.WATIAPIError, match="outside"): await run("list_message_metadata", {"conversation_id": "conv42"})
    assert all(c["method"] == "GET" and c["url"].endswith("/conversations/conv42/messages") for c in wire.calls)

@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["http401", "http403", "http429", "http201", "http204", "html", "nan", "overflow", "deep", "wrong_id", "error"])
async def test_safe_errors_nonjson403_no_token_echo_or_replay(wire, case):
    response = Response(CONTACT)
    if case.startswith("http"): response = Response(None, status=int(case[4:]), raw=b"private nonJSON", content_type="text/plain")
    if case == "html": response.headers["content-type"] = "text/html"
    if case == "nan": response.raw = b'{"id":"contact42","extra":NaN}'
    if case == "overflow": response.raw = b'{"id":"contact42","extra":1e309}'
    if case == "deep": response.raw = b'['*40+b'0'+b']'*40
    if case == "wrong_id": response.payload = {**CONTACT, "id": "other"}
    if case == "error": response.payload = {"ok": False, "error": {"message": CREDS["api_token"]}}
    wire.responses.append(response)
    with pytest.raises(wn.WATIAPIError) as error: await run("get_contact", {"contact_id": "contact42"})
    assert error.value.authority_rejected is (case in ("http401", "http403")) and CREDS["api_token"] not in str(error.value)
    assert len(wire.calls) == 1 and wn._PRIVATE_REQUEST.get() is False

@pytest.mark.asyncio
async def test_redaction_and_response_cap(monkeypatch, wire):
    wire.responses.append({**CONTACT, "name": "wati_synthetic%2b%2F%3dprivate-key"})
    result = await run("get_contact", {"contact_id": "contact42", "include_names": True})
    assert result["data"]["contact"]["name"] == "[redacted]"
    wire.responses.append(CONTACT); monkeypatch.setattr(wn, "MAX_BYTES", 10)
    with pytest.raises(wn.WATIAPIError, match="byte bound"): await run("get_contact", {"contact_id": "contact42"})
    assert len(wire.calls) == 2

@pytest.mark.asyncio
async def test_picker_binding_nullable_and_bounded_search_are_honest(wire):
    wire.responses.append(contacts([CONTACT]))
    first = await wn.WATINode.load_field_options("contact_id", CREDS, context={"_user_id": "actor"})
    assert first["options"] == [{"value": "contact42", "label": "contact42"}] and first["next_page_token"]
    with pytest.raises(ValueError, match="another current"):
        await wn.WATINode.load_field_options("channel_id", CREDS, context={"_user_id": "actor"}, page_token=first["next_page_token"])
    wire.responses.append(contacts([], page=2))
    last = await wn.WATINode.load_field_options("contact_id", CREDS, context={"_user_id": "actor"}, page_token=first["next_page_token"])
    assert last == {"options": [], "next_page_token": None}
    wire.responses.append(contacts(None))
    with pytest.raises(wn.WATIAPIError, match="nullable"): await wn.WATINode.load_field_options("contact_id", CREDS, context={"_user_id": "actor"})
    for page in range(1, 6): wire.responses.append(contacts([{**CONTACT, "id": "c" + str(page)}], page=page))
    with pytest.raises(wn.WATIAPIError, match="bound before exhaustion"):
        await wn.WATINode.load_field_options("contact_id", CREDS, context={"_user_id": "actor"}, search="unmatched")

@pytest.mark.asyncio
async def test_saved_credentials_use_staging_resolver(monkeypatch, wire):
    from nodes.core import run_op
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    current = {**CREDS, "api_token": "wati_current-synthetic-token"}
    resolve = AsyncMock(return_value=current)
    monkeypatch.setattr(run_op, "resolve_operation_credential", resolve)
    wire.responses.append(contacts([], size=10))
    await run_node_operation(node_type=wn.NODE_TYPE, operation="test_connection",
        arguments={}, credential_id="saved", user_id="actor", pool=object())
    assert resolve.await_count == 1
    assert wire.calls[0]["headers"]["Authorization"] == "Bearer " + current["api_token"]

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {**CONTACT, "wa_id": "other"}])
async def test_create_requires_documented_target_response_without_replay(wire, body):
    wire.responses.append(body)
    with pytest.raises(wn.WATIAPIError): await run("create_contact", {"name": "Name", "whatsapp_number": "919876543210", "custom_params_json": "  ", "confirm_changes": True})
    assert len(wire.calls) == 1 and wire.calls[0]["json"] == {"name": "Name", "whatsapp_number": "919876543210"}

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"contact_list": [], "page_number": 2, "page_size": 20}, {"contact_list": [{"id": None}], "page_number": 1, "page_size": 20}])
async def test_malformed_page_scope_or_nullable_id_is_unverified(wire, body):
    wire.responses.append(body)
    with pytest.raises(wn.WATIAPIError): await run("list_contacts")
    assert len(wire.calls) == 1
