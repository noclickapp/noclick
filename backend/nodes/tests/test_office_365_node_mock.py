"""Graph contract examples exercised through the real node and HTTP boundary."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import office_365_node as office
from nodes.core.registry import NodeFactory


@pytest.fixture
def ensure_native_db_pool():
    yield


AUTH = {"credential_type": "microsoft_outlook_oauth", "access_token": "fixture-access-token",
        "refresh_token": "fixture-refresh-token", "expires_at": "2099-01-01T00:00:00Z", "email": "qa@example.com"}
FIXTURES = json.loads((Path(__file__).parent / "fixtures/office-365/documented_responses.json").read_text())
MESSAGE = {"subject": "Lunch", "body_text": "Shall we meet?", "to_recipients": ["adele@contoso.com"]}
CONTACT = {"given_name": "Pavel", "surname": "Bansky", "email_address": "pavelb@contoso.com"}
EVENT = {"subject": "Lunch", "body_text": "Meet at noon", "start": "2017-04-15T12:00:00",
         "end": "2017-04-15T14:00:00", "time_zone": "Pacific Standard Time"}

# Independent route assertions: these are Graph v1.0 operation routes, not
# expectations read back from the node's own dispatch table.
CASES = [
    ("get_profile", {}, "GET", "/me", 200),
    ("list_messages", {}, "GET", "/me/messages", 200),
    ("get_message", {"message_id": "mail-one"}, "GET", "/me/messages/{message-id}", 200),
    ("send_mail", MESSAGE, "POST", "/me/sendMail", 202),
    ("create_draft", MESSAGE, "POST", "/me/messages", 201),
    ("update_message", {"message_id": "mail-one", "is_read": False}, "PATCH", "/me/messages/{message-id}", 200),
    ("delete_message", {"message_id": "mail-one"}, "DELETE", "/me/messages/{message-id}", 204),
    ("reply_message", {"message_id": "mail-one", "comment": "Thanks!"}, "POST", "/me/messages/{message-id}/reply", 202),
    ("move_message", {"message_id": "mail-one", "destination_id": "archive"}, "POST", "/me/messages/{message-id}/move", 201),
    ("list_mail_folders", {}, "GET", "/me/mailFolders", 200),
    ("list_calendars", {}, "GET", "/me/calendars", 200),
    ("list_events", {}, "GET", "/me/events", 200),
    ("get_event", {"event_id": "event-one"}, "GET", "/me/events/{event-id}", 200),
    ("create_event", EVENT, "POST", "/me/events", 201),
    ("update_event", {"event_id": "event-one", "subject": "Changed"}, "PATCH", "/me/events/{event-id}", 200),
    ("delete_event", {"event_id": "event-one"}, "DELETE", "/me/events/{event-id}", 204),
    ("list_contacts", {}, "GET", "/me/contacts", 200),
    ("get_contact", {"contact_id": "contact-one"}, "GET", "/me/contacts/{contact-id}", 200),
    ("create_contact", CONTACT, "POST", "/me/contacts", 201),
    ("update_contact", {"contact_id": "contact-one", "given_name": "Pavel", "surname": "Bansky"}, "PATCH", "/me/contacts/{contact-id}", 200),
    ("delete_contact", {"contact_id": "contact-one"}, "DELETE", "/me/contacts/{contact-id}", 204),
]


def make_node(operation, arguments=None, auth=None):
    return NodeFactory.create_node(
        node_id="office-test", node_type="automation-office-365",
        node_data={"config": {"operation": operation, **(arguments or {})}, "credentials": auth or AUTH},
    )


@pytest.fixture
def transport(monkeypatch):
    from nodes.core import oauth_refresh
    refresh = AsyncMock(return_value=AUTH["access_token"])
    monkeypatch.setattr(oauth_refresh, "ensure_fresh_oauth_token", refresh)
    requests, replies = [], []
    def send(request):
        requests.append(request)
        status, payload = replies.pop(0)
        return httpx.Response(status, json=payload, request=request) if payload is not None else httpx.Response(status, request=request)
    real_client = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return real_client(**kwargs, transport=httpx.MockTransport(send))
    monkeypatch.setattr(office.httpx, "AsyncClient", client)
    return requests, replies, refresh


@pytest.mark.parametrize("operation,arguments,method,path,status", CASES,
                         ids=["office-365-" + case[0] for case in CASES])
async def test_office_365_documented_operations(transport, operation, arguments, method, path, status):
    requests, replies, refresh = transport
    payload = FIXTURES.get(method + " " + path, {}).get("body")
    replies.append((status, payload))
    output = await make_node(operation, arguments).execute({})
    assert len(requests) == 1 and not replies
    request = requests[0]
    expected = path.replace("{message-id}", "mail-one").replace("{event-id}", "event-one").replace("{contact-id}", "contact-one")
    assert request.method == method
    assert request.url.path == "/v1.0" + expected
    assert request.url.host == "graph.microsoft.com"
    assert request.headers["authorization"] == "Bearer fixture-access-token"
    assert AUTH["access_token"] not in str(request.url)
    assert output["status"] == "success" and output["http_status"] == status
    assert refresh.await_args.kwargs["provider"] == "microsoft"
    if status == 202:
        assert output["accepted"] is True and output["delivery_verified"] is False
    elif status == 204:
        assert output["deleted"] is True
    elif operation.startswith("list_"):
        assert output["items"] == payload["value"]
    else:
        assert output["data"] == payload
    if method == "GET":
        assert not request.content
    if operation == "send_mail":
        assert json.loads(request.content) == {"message": {"subject": "Lunch", "body": {"contentType": "text", "content": "Shall we meet?"}, "toRecipients": [{"emailAddress": {"address": "adele@contoso.com"}}]}, "saveToSentItems": True}
    if operation == "reply_message":
        assert json.loads(request.content) == {"comment": "Thanks!"}
    if operation == "move_message":
        assert json.loads(request.content) == {"destinationId": "archive"}
    if operation == "update_message":
        assert json.loads(request.content) == {"isRead": False}
    if operation == "create_event":
        body = json.loads(request.content)
        assert body["start"] == {"dateTime": EVENT["start"], "timeZone": EVENT["time_zone"]}
        assert body["end"] == {"dateTime": EVENT["end"], "timeZone": EVENT["time_zone"]}
    if operation == "create_contact":
        assert json.loads(request.content) == {"givenName": "Pavel", "surname": "Bansky", "emailAddresses": [{"address": "pavelb@contoso.com"}]}


async def test_office_365_paging_preserves_graph_skiptoken(transport):
    requests, replies, _ = transport
    url = "https://graph.microsoft.com/v1.0/me/messages?$skiptoken=opaque%2Btoken&$top=2"
    replies.extend([(200, {"value": [{"id": "one"}], "@odata.nextLink": url}), (200, {"value": []})])
    first = await make_node("list_messages", {"top": 2, "filter": "isRead eq false"}).execute({})
    assert first["has_more"] is True and first["next_page_url"] == url
    assert requests[0].url.params["$filter"] == "isRead eq false"
    second = await make_node("list_messages", {"page_url": first["next_page_url"]}).execute({})
    assert str(requests[1].url) == url
    assert second["has_more"] is False and second["next_page_url"] is None


@pytest.mark.parametrize("operation,arguments,payload", [
    ("send_mail", MESSAGE, None),
    ("reply_message", {"message_id": "mail-one", "comment": "Thanks!"}, None),
    ("move_message", {"message_id": "mail-one", "destination_id": "archive"}, {"id": "moved-id"}),
])
async def test_office_365_accepts_published_contract_success_forms(transport, operation, arguments, payload):
    transport[1].append((200 if operation == "move_message" else 204, payload))
    result = await make_node(operation, arguments).execute({})
    assert result["status"] == "success"
    if operation == "move_message":
        assert result["data"] == payload
    else:
        assert result["accepted"] is True and result["delivery_verified"] is False


@pytest.mark.parametrize("url", [
    "https://evil.test/v1.0/me/messages?$skip=1",
    "https://graph.microsoft.com.evil.test/v1.0/me/messages?$skip=1",
    "http://graph.microsoft.com/v1.0/me/messages?$skip=1",
    "https://user@graph.microsoft.com/v1.0/me/messages?$skip=1",
    "https://graph.microsoft.com:443/v1.0/me/messages?$skip=1",
    "https://graph.microsoft.com/v1.0/users/other/messages?$skip=1",
    "https://graph.microsoft.com/v1.0/me/contacts?$skip=1",
    "https://graph.microsoft.com/v1.0/me/messages?$skip=1#fragment",
])
async def test_office_365_rejects_cross_resource_paging(transport, url):
    with pytest.raises(ValueError, match="exact collection"):
        await make_node("list_messages", {"page_url": url}).execute({})
    assert not transport[0]


async def test_office_365_ids_are_encoded_as_one_segment(transport):
    requests, replies, _ = transport
    replies.append((200, {"id": "id/with?query#fragment"}))
    await make_node("get_message", {"message_id": "id/with?query#fragment"}).execute({})
    assert requests[0].url.raw_path == b"/v1.0/me/messages/id%2Fwith%3Fquery%23fragment"


@pytest.mark.parametrize("status,payload", [(401, {"error": {"message": "Token fixture-access-token rejected"}}), (403, {"error": {"message": "Insufficient privileges"}}), (302, None)])
async def test_office_365_errors_and_redirects_never_report_success(transport, status, payload):
    transport[1].append((status, payload))
    with pytest.raises(ValueError) as error:
        await make_node("get_profile").execute({})
    assert str(status) in str(error.value) and AUTH["access_token"] not in str(error.value)


@pytest.mark.parametrize("operation,payload", [("list_contacts", {}), ("get_profile", {}), ("get_profile", [])])
async def test_office_365_malformed_success_is_rejected(transport, operation, payload):
    transport[1].append((200, payload))
    with pytest.raises(ValueError):
        await make_node(operation).execute({})


async def test_office_365_uses_shared_microsoft_refresh_hook(monkeypatch):
    from nodes.core import oauth_refresh
    hook = AsyncMock(return_value=AUTH)
    monkeypatch.setattr(oauth_refresh, "freshen_oauth_credential", hook)
    assert await office.Office365Node.freshen_credential(AUTH, credential_id="saved-id") == AUTH
    assert hook.await_args.kwargs["provider"] == "microsoft"
    assert hook.await_args.kwargs["credential_id"] == "saved-id"


def test_office_365_matches_existing_microsoft_sign_in_type():
    from wss.handlers.oauth.microsoft_oauth_handler import MicrosoftOAuthHandler
    scopes = office.OFFICE_365_SCOPES.declared_scopes()
    handler = MicrosoftOAuthHandler.__new__(MicrosoftOAuthHandler)
    resolved = handler._get_credential_type_from_name("Microsoft Office 365 OAuth", scopes)
    assert resolved == office.Office365OAuthCredential.model_fields["credential_type"].default
    assert set(office.OPERATIONS) | {"on_new_message", "on_outlook_change"} == set(office.OFFICE_365_SCOPES)


def test_office_365_manual_credential_has_default_type_and_normalized_token():
    credential = office.Office365OAuthCredential(access_token="  fixture-access-token  ")
    assert credential.credential_type == "microsoft_outlook_oauth"
    assert credential.access_token == "fixture-access-token"


@pytest.mark.parametrize("start,end", [("not-a-date", "2017-04-15T14:00:00"), ("2017-04-15T15:00:00", "2017-04-15T14:00:00"), ("2017-04-15T12:00:00Z", "2017-04-15T14:00:00Z")])
def test_office_365_validates_event_time_pair(start, end):
    with pytest.raises(ValueError, match="local ISO"):
        make_node("create_event", {**EVENT, "start": start, "end": end})


# Microsoft documents basic notification envelopes separately from resource GETs.
# These examples are pinned verbatim, including the clientState field we strip.
TRIGGER_EXAMPLES = json.loads((Path(__file__).parent / "fixtures/office-365/trigger_examples.json").read_text())


def notification():
    import copy
    return copy.deepcopy(TRIGGER_EXAMPLES["notification"]["body"])


@pytest.mark.parametrize("operation,config,resource,changes", [
    ("on_new_message", {}, "me/mailfolders('inbox')/messages", "created"),
    ("on_outlook_change", {}, "me/messages", "created,updated"),
    ("on_outlook_change", {"collection": "events", "change_type": "updated"}, "me/events", "updated"),
    ("on_outlook_change", {"collection": "contacts", "change_type": "deleted"}, "me/contacts", "deleted"),
])
@pytest.mark.parametrize("status", [200, 201])
async def test_office_365_subscription_registration(transport, operation, config, resource, changes, status):
    from datetime import datetime, timezone
    requests, replies, _ = transport
    replies.append((status, TRIGGER_EXAMPLES["registration"]["body"]))
    result = await office.Office365Node._register_external_webhook(
        webhook_url="https://example.com/webhook", credential=AUTH,
        config={"operation": operation, **config}, node_id="office-test")
    request = requests[0]
    body = json.loads(request.content)
    assert request.method == "POST" and request.url.path == "/v1.0/subscriptions"
    assert request.headers["authorization"] == "Bearer fixture-access-token"
    assert body["resource"] == resource and body["changeType"] == changes
    assert body["notificationUrl"] == "https://example.com/webhook"
    assert 3500 < (datetime.fromisoformat(body["expirationDateTime"]) - datetime.now(timezone.utc)).total_seconds() <= 3600
    assert result["external_webhook_id"] == TRIGGER_EXAMPLES["registration"]["body"]["id"]
    assert body["clientState"] == result["signing_secret"] and len(result["signing_secret"]) >= 32
    assert "includeResourceData" not in body


@pytest.mark.parametrize("status", [204, 404])
async def test_office_365_subscription_cleanup_is_idempotent(transport, status):
    requests, replies, _ = transport
    replies.append((status, None))
    await office.Office365Node._unregister_external_webhook(
        credential=AUTH, config={"external_webhook_id": "subscription/one"}, node_id="office-test")
    assert requests[0].method == "DELETE" and requests[0].url.raw_path == b"/v1.0/subscriptions/subscription%2Fone"


def test_office_365_client_state_verifies_every_notification():
    payload = notification()
    secret = payload["value"][0]["clientState"]
    verify = office.Office365Node.verify_webhook_signature
    assert verify(json.dumps(payload).encode(), {}, {"signing_secret": secret})
    assert not verify(json.dumps(payload).encode(), {}, {})
    assert not verify(json.dumps(payload).encode(), {}, {"signing_secret": "wrong"})
    for body in [b"[]", b"{}", b"{", b'{"value":[]}', b'{"value":[null]}']:
        assert not verify(body, {}, {"signing_secret": secret})
    payload["value"].append({**payload["value"][0], "clientState": "wrong"})
    assert not verify(json.dumps(payload).encode(), {}, {"signing_secret": secret})


@pytest.mark.parametrize("operation", ["on_new_message", "on_outlook_change"])
async def test_office_365_documented_notification_to_agent(operation):
    payload = notification()
    config = {"operation": operation}
    assert office.Office365Node.filter_trigger_payload(payload, config)
    transformed = await office.Office365Node.transform_trigger_payload(
        {**payload, "_office365_enrichment": {"changes": [{"data": "untrusted"}]}}, config,
        pool=None, workflow_id=None, node_id="office-test")
    output = office.Office365Node.resolve_trigger_payload(transformed, config)
    assert len(output["changes"]) == 1 and output["changes"][0]["id"] == payload["value"][0]["resourceData"]["id"]
    assert "clientState" not in json.dumps(output) and "untrusted" not in json.dumps(output)
    assert payload["value"][0]["clientState"] not in json.dumps(output)
    event = office.Office365Node.resolve_agent_event(output)
    assert "created in Outlook" in event["text"] and "get_message" in event["text"]
    assert output["changes"][0]["id"] in event["text"]
    manual = await make_node(operation).execute({"value": payload["value"]})
    assert manual["status"] == "no_event"


def test_office_365_subscription_filters_changes_and_collections():
    payload = notification()
    assert not office.Office365Node.filter_trigger_payload(payload, {"operation": "on_outlook_change", "change_type": "updated"})
    assert not office.Office365Node.filter_trigger_payload(payload, {"operation": "on_outlook_change", "collection": "events"})
    assert not office.Office365Node.filter_trigger_payload({"value": [None, {}, {"changeType": "created"}]}, {"operation": "on_new_message"})


def test_office_365_renewal_uses_existing_reconciler(monkeypatch):
    from utils.webhook_manager import registration_fingerprint
    cls = office.Office365Node
    config = {"operation": "on_outlook_change"}
    monkeypatch.setattr(office.time, "time", lambda: 1801)
    first = registration_fingerprint(cls, "on_outlook_change", "credential", config)
    assert first == registration_fingerprint(cls, "on_outlook_change", "credential", config)
    assert first != registration_fingerprint(cls, "on_outlook_change", "credential", {**config, "collection": "contacts"})
    monkeypatch.setattr(office.time, "time", lambda: 3601)
    assert first != registration_fingerprint(cls, "on_outlook_change", "credential", config)
    assert cls.webhook_replace_stale_endpoint
    assert cls.registration_fingerprint_fields({"operation": "get_profile"}) == {}


async def test_office_365_enriches_agent_email_from_documented_get(transport, monkeypatch):
    from utils import inbound_media
    payload = notification()
    message = FIXTURES["GET /me/messages/{message-id}"]["body"]
    monkeypatch.setattr(inbound_media, "resolve_delivery_credential", AsyncMock(return_value=(AUTH, "owner")))
    monkeypatch.setattr(office.Office365Node, "freshen_credential", AsyncMock(return_value=AUTH))
    transport[1].append((200, message))
    transformed = await office.Office365Node.transform_trigger_payload(
        payload, {"operation": "on_new_message"}, pool=object(), workflow_id="workflow", node_id="office-test")
    output = office.Office365Node.resolve_trigger_payload(transformed, {"operation": "on_new_message"})
    assert output["changes"][0]["data"] == message
    text = office.Office365Node.resolve_agent_event(output)["text"]
    assert message["subject"] in text
    assert message["from"]["emailAddress"]["name"] in text
    assert message["bodyPreview"] in text
    assert transport[0][0].url.host == "graph.microsoft.com"
    assert transport[0][0].url.path.endswith("/me/messages/" + payload["value"][0]["resourceData"]["id"])


async def test_office_365_enrichment_failure_preserves_actionable_event(transport, monkeypatch):
    from utils import inbound_media
    monkeypatch.setattr(inbound_media, "resolve_delivery_credential", AsyncMock(return_value=(AUTH, "owner")))
    monkeypatch.setattr(office.Office365Node, "freshen_credential", AsyncMock(return_value=AUTH))
    transport[1].append((404, {"error": {"message": "gone"}}))
    payload = await office.Office365Node.transform_trigger_payload(
        notification(), {"operation": "on_new_message"}, pool=object(), workflow_id="workflow", node_id="office-test")
    output = office.Office365Node.resolve_trigger_payload(payload, {"operation": "on_new_message"})
    assert office.Office365Node.resolve_agent_event(output)["text"]
    assert "data" not in output["changes"][0]
