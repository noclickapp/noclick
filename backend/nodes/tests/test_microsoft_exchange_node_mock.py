"""Graph wire requests and provider-authored Exchange response fixtures; no live account."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes.core.run_op import run_node_operation
from nodes.microsoft_exchange_node import CONFIG_MODELS, OPERATIONS, ExchangeOAuthCredential, MicrosoftExchangeNode
from nodes.scopes.microsoft_exchange import EXCHANGE_SCOPES

FIXTURES = Path(__file__).parent / "fixtures" / "microsoft-exchange"
AUTH = {"credential_type": "microsoft_outlook_oauth", "access_token": "fixture-access-token", "refresh_token": "fixture-refresh-token", "expires_at": "2099-01-01T00:00:00Z", "email": "adele@contoso.com"}
VALUES = {"message_id": "message=", "folder_id": "folder=", "event_id": "event=", "contact_id": "contact=", "destination_id": "archive", "subject": "Meeting", "body_text": "Hello", "to_email": "adele@contoso.com", "comment": "Thanks", "is_read": True, "display_name": "Project", "start_datetime": "2026-11-10T12:00:00", "end_datetime": "2026-11-10T13:00:00", "time_zone": "UTC", "given_name": "Adele", "surname": "Vance", "email_address": "adele@contoso.com"}
# Independent wire expectations, including exact Graph casing and encoded IDs.
CASES = [
    ("list_messages", "GET", "/me/messages", None),
    ("get_message", "GET", "/me/messages/message%3D", None),
    ("send_email", "POST", "/me/sendMail", {"message": {"subject": "Meeting", "body": {"contentType": "text", "content": "Hello"}, "toRecipients": [{"emailAddress": {"address": "adele@contoso.com"}}]}}),
    ("create_draft", "POST", "/me/messages", {"subject": "Meeting", "body": {"contentType": "text", "content": "Hello"}, "toRecipients": [{"emailAddress": {"address": "adele@contoso.com"}}]}),
    ("update_message", "PATCH", "/me/messages/message%3D", {"isRead": True}),
    ("delete_message", "DELETE", "/me/messages/message%3D", None),
    ("move_message", "POST", "/me/messages/message%3D/move", {"destinationId": "archive"}),
    ("reply_message", "POST", "/me/messages/message%3D/reply", {"comment": "Thanks"}),
    ("forward_message", "POST", "/me/messages/message%3D/forward", {"comment": "Thanks", "toRecipients": [{"emailAddress": {"address": "adele@contoso.com"}}]}),
    ("send_draft", "POST", "/me/messages/message%3D/send", None),
    ("list_mail_folders", "GET", "/me/mailFolders", None),
    ("get_mail_folder", "GET", "/me/mailFolders/folder%3D", None),
    ("create_mail_folder", "POST", "/me/mailFolders", {"displayName": "Project"}),
    ("list_calendars", "GET", "/me/calendars", None),
    ("list_events", "GET", "/me/events", None),
    ("get_event", "GET", "/me/events/event%3D", None),
    ("create_event", "POST", "/me/events", {"subject": "Meeting", "body": {"contentType": "text", "content": "Hello"}, "start": {"dateTime": "2026-11-10T12:00:00", "timeZone": "UTC"}, "end": {"dateTime": "2026-11-10T13:00:00", "timeZone": "UTC"}}),
    ("update_event", "PATCH", "/me/events/event%3D", {"subject": "Meeting"}),
    ("delete_event", "DELETE", "/me/events/event%3D", None),
    ("list_contacts", "GET", "/me/contacts", None),
    ("get_contact", "GET", "/me/contacts/contact%3D", None),
    ("create_contact", "POST", "/me/contacts", {"givenName": "Adele", "surname": "Vance", "emailAddresses": [{"address": "adele@contoso.com"}]}),
    ("update_contact", "PATCH", "/me/contacts/contact%3D", {"displayName": "Project"}),
    ("delete_contact", "DELETE", "/me/contacts/contact%3D", None),
    ("list_contact_folders", "GET", "/me/contactFolders", None),
]


def arguments(op):
    return {k: VALUES[k] for k in OPERATIONS[op].fields if k in VALUES}


async def run(op, **values):
    return await run_node_operation(node_type="automation-microsoft-exchange", operation=op, arguments={**arguments(op), **values}, credential_data=AUTH.copy(), user_id="00000000-0000-0000-0000-000000000001")


@pytest.fixture
def wire(monkeypatch):
    from nodes.core import oauth_refresh
    monkeypatch.setattr(oauth_refresh, "ensure_fresh_oauth_token", AsyncMock(return_value=AUTH["access_token"]))
    requests, responses = [], []
    real = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return responses.pop(0)
    monkeypatch.setattr("nodes.microsoft_exchange_node.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(respond), **kw))
    return requests, responses


@pytest.mark.asyncio
@pytest.mark.parametrize("op,method,path,body", CASES, ids=[f"automation-microsoft-exchange:{case[0]}" for case in CASES])
async def test_all_operations_through_factory(wire, op, method, path, body):
    requests, replies = wire
    fixture = FIXTURES / (op + ".json")
    if op in {"send_email", "reply_message", "forward_message", "send_draft"}:
        replies.append(httpx.Response(202))
    elif method == "DELETE": replies.append(httpx.Response(204))
    else:
        payload = json.loads(fixture.read_text()) if fixture.exists() else {"id": "item="}
        replies.append(httpx.Response(201 if method == "POST" else 200, json=payload))
    result = await run(op)
    assert len(requests) == 1 and replies == []
    request = requests[0]
    assert request.method == method
    assert request.url.host == "graph.microsoft.com"
    assert request.url.raw_path.decode().split("?")[0] == "/v1.0" + path
    assert request.headers["Authorization"] == "Bearer fixture-access-token"
    assert (json.loads(request.content) if request.content else None) == body
    if op.startswith("list_"):
        assert request.url.params["$top"] == "25" and request.url.params["$skip"] == "0"
        assert result["items"] == payload["value"]
    if result["http_status"] == 202:
        assert result["status"] == "accepted" and result["delivery_verified"] is False
    else: assert result["status"] == "success"


@pytest.mark.asyncio
async def test_list_filter_and_exact_provider_paging(wire):
    requests, replies = wire
    replies.append(httpx.Response(200, json={"value": [{"id": "m1"}], "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=35&$top=10"}))
    result = await run("list_messages", top=10, skip=25, filter="isRead eq false")
    assert dict(requests[0].url.params) == {"$top": "10", "$skip": "25", "$filter": "isRead eq false"}
    assert result["next_skip"] == 35 and result["has_more"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["https://attacker.test/me/messages", "https://graph.microsoft.com.evil.test/v1.0/me/messages", "https://graph.microsoft.com/v1.0/me/contacts", "http://graph.microsoft.com/v1.0/me/messages", "https://user@graph.microsoft.com/v1.0/me/messages"])
async def test_foreign_continuations_are_rejected(wire, url):
    wire[1].append(httpx.Response(200, json={"value": [], "@odata.nextLink": url}))
    with pytest.raises(ValueError, match="continuation"):
        await run("list_messages")
    assert len(wire[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(401,json={"error": {"message": "fixture-access-token denied"}}), httpx.Response(429,json={"error": {"message": "Throttled"}}), httpx.Response(302,headers={"Location":"https://attacker.test"}), httpx.Response(200,json={"error":{"message":"bad"}}), httpx.Response(200,json={}), httpx.Response(200,text="<html>login</html>")])
async def test_error_responses_do_not_pass(wire, response):
    wire[1].append(response)
    with pytest.raises(ValueError) as error:
        await run("list_messages")
    assert AUTH["access_token"] not in str(error.value)
    assert len(wire[0]) == 1


@pytest.mark.parametrize("value", ["../x", "https://attacker.test", "a?b", "a%2fb", "a\\nb", ".."])
def test_bad_ids_refused(value):
    with pytest.raises(ValidationError): CONFIG_MODELS["get_message"](message_id=value)


def test_event_order_email_and_extra_arguments_refused():
    with pytest.raises(ValidationError): CONFIG_MODELS["create_event"](**{**arguments("create_event"), "end_datetime": "2026-11-09T00:00:00"})
    with pytest.raises(ValidationError): CONFIG_MODELS["send_email"](**{**arguments("send_email"), "to_email": "invalid"})
    with pytest.raises(ValidationError): CONFIG_MODELS["get_message"](message_id="m", arbitrary_url="https://attacker.test")


def test_scopes_credential_and_evidence_contract():
    assert set(OPERATIONS) == set(EXCHANGE_SCOPES)
    assert ExchangeOAuthCredential(access_token="fixture-access-token").credential_type == "microsoft_outlook_oauth"
    assert ExchangeOAuthCredential.model_json_schema()["x-oauth-provider"] == "microsoft"
    assert MicrosoftExchangeNode.connection_evidence.operation == "list_messages"
    assert "subject" in MicrosoftExchangeNode.connection_evidence.label_keys


@pytest.mark.asyncio
async def test_connection_probe_shows_account_message_subjects(wire):
    from nodes.core.connection_evidence import collect_evidence
    payload = json.loads((FIXTURES / "list_messages.json").read_text())
    wire[1].append(httpx.Response(200, json=payload))
    evidence = await collect_evidence(node_type="automation-microsoft-exchange", user_id="00000000-0000-0000-0000-000000000001", credential_data=AUTH.copy())
    assert evidence.reachable is True and evidence.noun == "messages"
    assert [sample.label for sample in evidence.samples] == ["You have late tasks!"]
    assert len(wire[0]) == 1 and wire[0][0].method == "GET"
    assert wire[0][0].url.path == "/v1.0/me/messages"
