"""Native factory requests replay the provider's verbatim saved Postman examples."""
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import virtuous_crm_node as provider
from nodes.core.run_op import run_node_operation
from utils import ssrf

FIXTURE = json.loads((Path(__file__).parent / "fixtures/virtuous-crm/postman.json").read_text())
AUTH = {"credential_type": "virtuous_crm_api_key", "api_key": "test-virtuous-not-a-live-key"}
NODE = "automation-virtuous-crm"
NOTE = {"note_type": "Call", "note": "Discussed the annual fund", "note_date_time": "2026-11-09T10:00:00Z", "important": False, "private": True, "time_spent": 10}
CONFIGS = {
    "get_current_organization": {},
    "get_contact": {"contact_id": 11},
    "find_contact": {"email": "donor@example.com"},
    "search_contacts": {"search": "Weyland", "skip": 10, "take": 10},
    "import_contact": {"contact_type": "Household", "name": "Test Household", "first_name": "Test", "last_name": "Donor", "email": "donor@example.com", "reference_source": "External", "reference_id": "donor-1"},
    "archive_contact": {"contact_id": 11, "archive_reason": "Extremely lapsed giver"},
    "unarchive_contact": {"contact_id": 11},
    "list_individuals": {"contact_id": 11},
    "get_individual": {"individual_id": 12},
    "list_notes": {"contact_id": 11, "sort_by": "NoteDate", "descending": False},
    "get_note": {"note_id": 13},
    "create_note": {"contact_id": 11, **NOTE},
    "update_note": {"note_id": 13, **NOTE},
    "delete_note": {"note_id": 13},
    "list_tags": {"contact_id": 11},
    "add_tag": {"contact_id": 11, "tag_id": 14},
    "remove_tag": {"contact_tag_id": 15},
    "get_gift": {"gift_id": 16},
    "list_gifts": {"contact_id": 11},
    "get_project": {"project_id": 17},
    "search_projects": {"search": "annual fund"},
    "list_events": {},
    "get_event": {"event_id": 18},
}
CASES = [(op, i) for op, item in FIXTURE["items"].items() for i in range(len(item["response"]))]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.virtuoussoftware.com"
        assert request.headers["authorization"] == "Bearer " + AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        code, content, headers = replies.pop(0)
        return httpx.Response(code, content=content, headers=headers, request=request)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(provider, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type=NODE, operation=operation,
        arguments=CONFIGS[operation] if arguments is None else arguments,
        credential_data=AUTH, user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,example_index", CASES)
async def test_all_saved_postman_responses(transport, operation, example_index):
    requests, replies = transport
    item = FIXTURE["items"][operation]
    example = item["response"][example_index]
    replies.append((example["code"], example.get("body") or "", [(h["key"], h["value"]) for h in example.get("header", [])]))
    result = await run(operation)
    assert len(requests) == 1  # Writes never retry or add hidden readbacks.
    request = requests[0]
    expected = item["request"]["url"]
    expected = expected["raw"] if isinstance(expected, dict) else expected
    expected = expected.replace("{{baseUrl}}", provider.BASE).split("?")[0]
    ids = {"contactId": "contact_id", "contactIndividualId": "individual_id", "noteId": "note_id", "contactTagId": "contact_tag_id", "giftId": "gift_id", "projectId": "project_id", "eventId": "event_id"}
    expected = re.sub(r":([A-Za-z]+)", lambda m: str(CONFIGS[operation][ids[m[1]]]), expected)
    assert str(request.url).split("?")[0] == expected
    assert request.method == item["request"]["method"]
    assert result["http_status"] == example["code"]
    if example["code"] >= 300:
        assert result["status"] == "error"
        assert result["error"]
    else:
        assert result["status"] == "success"
        assert result["data"] == (json.loads(example["body"]) if example.get("body") else None)
        if operation == "import_contact":
            assert result["import_submitted"] is True
            assert result["contact_created"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,expected", [
    ("search_contacts", {"search": "Weyland"}),
    ("search_projects", {"search": "annual fund"}),
    ("archive_contact", {"archiveReason": "Extremely lapsed giver"}),
    ("add_tag", {"tagId": 14, "contactId": 11}),
    ("import_contact", {"contactType": "Household", "name": "Test Household", "firstName": "Test", "lastName": "Donor", "email": "donor@example.com", "referenceSource": "External", "referenceId": "donor-1"}),
    ("create_note", {"contactId": 11, "type": "Call", "note": NOTE["note"], "noteDateTime": NOTE["note_date_time"], "important": False, "private": True, "timeSpent": 10}),
    ("update_note", {"type": "Call", "note": NOTE["note"], "noteDateTime": NOTE["note_date_time"], "important": False, "private": True, "timeSpent": 10}),
])
async def test_write_wire_fields(transport, operation, expected):
    requests, replies = transport
    example = FIXTURE["items"][operation]["response"][0]
    replies.append((example["code"], example.get("body") or "", [(h["key"], h["value"]) for h in example.get("header", [])]))
    await run(operation)
    assert json.loads(requests[0].content) == expected


@pytest.mark.asyncio
async def test_false_sort_parameter(transport):
    requests, replies = transport
    example = FIXTURE["items"]["list_notes"]["response"][0]
    replies.append((example["code"], example["body"], [(h["key"], h["value"]) for h in example.get("header", [])]))
    await run("list_notes", {**CONFIGS["list_notes"], "skip": 1, "take": 1})
    assert dict(requests[0].url.params) == {"skip": "1", "take": "1", "sortBy": "NoteDate", "descending": "false"}


@pytest.mark.asyncio
async def test_completed_page_uses_published_total(transport):
    requests, replies = transport
    example = FIXTURE["items"]["search_contacts"]["response"][0]
    replies.append((example["code"], example["body"], [(h["key"], h["value"]) for h in example.get("header", [])]))
    result = await run("search_contacts", {"search": "Weyland", "skip": 0, "take": 2})
    assert dict(requests[0].url.params) == {"skip": "0", "take": "2"}
    assert result["next_skip"] is None and result["has_more"] is False


@pytest.mark.parametrize("field,value", [("note", None), ("private", None), ("time_spent", None), ("note_date_time", "yesterday")])
def test_note_replacement_requires_complete_model(field, value):
    with pytest.raises(ValidationError):
        provider.UpdateNote(note_id=1, **{**NOTE, field: value})


@pytest.mark.parametrize("key", ["Bearer token", "https://example.test/token", "<token>", "bad\r\nheader", "clé"])
def test_reject_bad_keys(key):
    with pytest.raises(ValidationError):
        provider.VirtuousCRMAPIKeyCredential(api_key=key)


@pytest.mark.parametrize("identifier", [0, -1, "../Current", "1?secret=true"])
def test_no_path_injection(identifier):
    with pytest.raises(ValidationError):
        provider.GetContact(contact_id=identifier)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_errors_are_redacted_and_not_retried(transport, status):
    requests, replies = transport
    replies.append((status, "Rejected " + AUTH["api_key"], {"Content-Type": "text/plain"}))
    result = await run("get_current_organization")
    assert result["status"] == "error" and result["http_status"] == status
    assert AUTH["api_key"] not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("content,headers", [(b"", {}), (b"<html>login</html>", {"Content-Type": "text/html"}), (b"{}", {"Content-Type": "application/json"})])
async def test_connection_read_rejects_unrecognizable_account(transport, content, headers):
    _, replies = transport
    replies.append((200, content, headers))
    with pytest.raises(ValueError):
        await run("get_current_organization")


@pytest.mark.asyncio
async def test_manual_connection_names_current_organization(transport):
    from nodes.core.connection_evidence import collect_evidence
    _, replies = transport
    example = FIXTURE["items"]["get_current_organization"]["response"][0]
    replies.append((example["code"], example["body"], [(h["key"], h["value"]) for h in example.get("header", [])]))
    result = await collect_evidence(node_type=NODE, credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001")
    assert result.reachable is True
    assert result.account_label == "The Human Fund"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_connection_rejection_retains_http_status(transport, status):
    # Adversarial error text checks the shared verifier's status classification;
    # it is deliberately not attributed to the provider as a published example.
    from nodes.core.connection_evidence import collect_evidence
    _, replies = transport
    replies.append((status, "No access", {"Content-Type": "text/plain"}))
    result = await collect_evidence(node_type=NODE, credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001")
    assert result.reachable is False
