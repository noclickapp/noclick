"""Exercise Apptoto's native factory with synthetic credentials and HTTP.

These tests pin action routing, provider payloads, connection reads and failures
without signing in to an Apptoto account or sending messages.
"""
import base64
import json
from urllib.parse import parse_qs
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import apptoto_node as native
from nodes.core.registry import NodeFactory

CREDENTIAL = {"credential_type": "apptoto_api_key", "username": "fixture@example.test", "api_key": "synthetic-apptoto-api-key"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=CREDENTIAL):
    return NodeFactory.create_node(node_id="apptoto-test", node_type="automation-apptoto",
        node_data={"config": config, "credentials": credentials})


def transport(monkeypatch, payload=None, status=200, headers=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload if payload is not None else {}, headers=headers)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "get_user_info"}, "GET", "/v1/userinfo", {}),
    ({"operation": "list_calendars"}, "GET", "/v1/calendars", {}),
    ({"operation": "list_events", "begin": "2026-11-01", "q": "phone=+16505551212"}, "GET", "/v1/events", {"begin": "2026-11-01", "q": "phone=+16505551212"}),
    ({"operation": "get_event", "id": 123}, "GET", "/v1/event", {"id": "123"}),
    ({"operation": "create_event", "calendar_id": 123, "title": "Consultation", "start_time": "2026-11-10T10:00:00Z", "end_time": "2026-11-10T11:00:00Z", "participants": [{"name": "Fixture", "email": "fixture@example.test"}]}, "POST", "/v1/events", None),
    ({"operation": "update_event", "id": 123, "title": "Changed"}, "PUT", "/v1/events", None),
    ({"operation": "delete_event", "id": 123}, "DELETE", "/v1/events", {"id": "123"}),
    ({"operation": "tag_event", "id": "123", "tag": "qualified", "remove": "true"}, "POST", "/v1/event/tag", {"id": "123", "tag": "qualified", "remove": "true"}),
    ({"operation": "list_participants", "event_id": 123}, "GET", "/v1/participants", {"event_id": "123", "include_conversations": "false"}),
    ({"operation": "add_participant", "event_id": 123, "contact_id": 456}, "POST", "/v1/participants", {"event_id": "123", "contact_id": "456"}),
    ({"operation": "update_participant", "id": 789, "state": "confirmed"}, "PUT", "/v1/participants", {"id": "789", "state": "confirmed"}),
    ({"operation": "delete_participant", "id": 789}, "DELETE", "/v1/participants", {"id": "789"}),
    ({"operation": "list_address_books"}, "GET", "/v1/address_books", {}),
    ({"operation": "list_contacts", "page": 2, "address_book_id": 123}, "GET", "/v1/contacts", {"page": "2", "page_size": "30", "address_book_id": "123"}),
    ({"operation": "get_contact", "id": 456}, "GET", "/v1/contact", {"id": "456"}),
    ({"operation": "create_contact", "address_book_id": 123, "name": "Fixture", "phone": "+16505551212"}, "POST", "/v1/contacts", None),
    ({"operation": "update_contact", "id": 456, "email": "updated@example.test"}, "PUT", "/v1/contacts", None),
    ({"operation": "delete_contact", "id": 456}, "DELETE", "/v1/contacts", {"id": "456"}),
    ({"operation": "tag_contact", "id": "456", "tag": "prospect"}, "POST", "/v1/contacts/tag", {"id": "456", "tag": "prospect", "remove": "false"}),
    ({"operation": "list_booking_pages"}, "GET", "/v1/booking_pages", {"page": "1", "page_size": "30"}),
    ({"operation": "book_appointment", "booking_page": "bookwithfred", "time": "2025-06-21T08:00:00", "field_data": {"zip": "97701"}, "opted_into_text_messaging": False}, "POST", "/v1/book_now", None),
    ({"operation": "list_conversations", "folder": "outbox"}, "GET", "/v1/conversations", {"folder": "outbox", "page": "1", "page_size": "30"}),
    ({"operation": "list_conversation_messages", "conversation_id": 123}, "GET", "/v1/conversation_messages", {"conversation_id": "123"}),
    ({"operation": "list_conversation_templates"}, "GET", "/v1/conversation_templates", {}),
    ({"operation": "reply_to_conversation", "conversation_id": 123, "message": "New time?", "and_archive": True}, "POST", "/v1/conversation_reply", {"conversation_id": "123", "message": "New time?", "and_archive": "true", "allow_number_change": "false"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,expected", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_native_operations(monkeypatch, config, method, path, expected):
    payload = {"calendars": [{"id": 123, "name": "Apptoto Calendar"}]} if config["operation"] == "list_calendars" else {"id": 123}
    requests = transport(monkeypatch, payload)
    result = await node(config).execute({})
    assert result == {"status": "success", "data": payload}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.apptoto.com" and request.url.scheme == "https"
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"fixture@example.test:synthetic-apptoto-api-key").decode()
    if expected is not None:
        fields = dict(request.url.params) if method in {"GET", "DELETE"} else {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        assert expected.items() <= fields.items()
    else:
        assert request.headers["content-type"] == "application/json"
        body = json.loads(request.content)
        if config["operation"] in {"create_event", "update_event"}:
            assert body["prevent_calendar_creation"] is True
            assert len(body["events"]) == 1 and body["events"][0]["title"] == config["title"]
            assert "operation" not in body["events"][0]
        elif config["operation"] in {"create_contact", "update_contact"}:
            assert body == {"contacts": [{k: v for k, v in config.items() if k != "operation"}]}
        else:
            assert body["field_data"] == {"zip": "97701"}
            assert body["opted_into_text_messaging"] is False
    assert CREDENTIAL["api_key"] not in str(result)


@pytest.mark.parametrize("config", [
    {"operation": "create_event", "calendar_id": 1, "title": "x", "start_time": "2026-11-10T11:00:00Z", "end_time": "2026-11-10T10:00:00Z"},
    {"operation": "create_event", "calendar_id": 1, "title": "x", "start_time": "2026-11-10T10:00:00", "end_time": "2026-11-10T11:00:00"},
    {"operation": "add_participant", "event_id": 123},
    {"operation": "update_event", "id": 123},
    {"operation": "update_contact", "id": 123},
    {"operation": "get_event", "id": 0},
    {"operation": "list_contacts", "page": 0},
    {"operation": "update_participant", "id": 123, "state": "made-up"},
    {"operation": "list_conversations", "folder": "all"},
])
def test_reject_invalid_inputs(config):
    assert native.ApptotoNode.validate_config({"config": config, "credentials": CREDENTIAL})["valid"] is False


@pytest.mark.parametrize("changes", [{"username": "bad:user"}, {"username": " "}, {"api_key": "https://example.test/key"}, {"api_key": "with spaces"}])
def test_manual_credential_validation(changes):
    with pytest.raises(ValidationError):
        native.ApptotoAPIKeyCredential.model_validate({**CREDENTIAL, **changes})


def test_manual_type_default():
    credential = native.ApptotoAPIKeyCredential.model_validate({k: v for k, v in CREDENTIAL.items() if k != "credential_type"})
    assert credential.credential_type == "apptoto_api_key"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_preserve_provider_rejection_without_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"error": "Provider's exact rejection"}, status)
    result = await node({"operation": "list_calendars"}).execute({})
    assert result == {"status": "error", "status_code": status, "error": "Provider's exact rejection"}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_success_error_envelope_and_empty_delete(monkeypatch):
    transport(monkeypatch, {"success": False, "error": "Not saved"})
    assert (await node({"operation": "delete_event", "id": 123}).execute({}))["status"] == "error"
    transport(monkeypatch, status=204)
    assert (await node({"operation": "delete_event", "id": 123}).execute({})) == {"status": "success", "data": None}


@pytest.mark.asyncio
async def test_missing_credentials_makes_no_request(monkeypatch):
    requests = transport(monkeypatch)
    with pytest.raises(ValueError, match="Connect"):
        await node({"operation": "list_calendars"}, credentials=None).execute({})
    assert not requests


@pytest.mark.asyncio
async def test_whole_documented_responses(monkeypatch):
    examples = json.loads((Path(__file__).parent / "fixtures/apptoto/provider_examples.json").read_text())
    for config, method, path, _ in CASES:
        example = examples.get(method + " " + path)
        if example is None:
            continue
        transport(monkeypatch, example["body"])
        result = await node(config).execute({})
        assert result == {"status": "success", "data": example["body"]}, config["operation"]


@pytest.mark.asyncio
async def test_connection_evidence_uses_account_calendars(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    requests = transport(monkeypatch, {"calendars": [{"id": 123, "name": "Apptoto Calendar"}]})
    evidence = await collect_evidence(node_type="automation-apptoto", credential_data=CREDENTIAL, user_id="00000000-0000-4000-8000-000000000001")
    assert evidence.reachable is True
    assert "Apptoto Calendar" in str(evidence)
    assert len(requests) == 1 and requests[0].url.path == "/v1/calendars"
