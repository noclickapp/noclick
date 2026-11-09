"""Reteno routing, authentication, mutation boundaries and documented response tests."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import reteno_node as native
from nodes.core.registry import NodeFactory

TOKEN = "reteno-synthetic-api-key"
FIXTURES = Path(__file__).parent / "fixtures" / "reteno"
CONTACT = {"first_name": "John", "last_name": "Smith", "channels": [{"type": "email", "value": "john@example.com"}], "external_customer_id": "TV12790", "language_code": "en", "time_zone": "Europe/London"}
EMAIL = {"name": "Welcome", "sender": '"John Smith" <John.Smith@example.com>', "subject": "Thanks for signing up", "html_text": "<p>Welcome</p>"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="reteno-fixture", node_type="automation-reteno", node_data={"config": config, "credentials": {"credential_type": "reteno_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body=None, status=200, headers=None, *, text=None):
    requests = []
    def respond(request):
        requests.append(request)
        if text is not None:
            return httpx.Response(status, text=text, headers=headers)
        return httpx.Response(status, json=body, headers=headers)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "get_account_info"}, "GET", "/api/v1/account/info", {}, None, {"orgId": 123, "organisationName": "Example", "userEmail": "api-user"}),
    ({"operation": "search_contacts", "external_customer_id": "TV12790", "maxrows": 50, "startindex": 2}, "GET", "/api/v1/contacts", {"externalCustomerId": "TV12790", "maxrows": "50", "startindex": "2"}, None, []),
    ({"operation": "get_contact", "contact_id": 12345678}, "GET", "/api/v1/contact/12345678", {}, None, {"id": 12345678}),
    ({"operation": "upsert_contact", "contact": CONTACT}, "POST", "/api/v1/contact", {}, {"firstName": "John", "lastName": "Smith", "channels": CONTACT["channels"], "externalCustomerId": "TV12790", "languageCode": "en", "timeZone": "Europe/London"}, {"id": 12345678}),
    ({"operation": "update_contact", "contact_id": 12345678, "contact": {"channels": CONTACT["channels"]}}, "PUT", "/api/v1/contact/12345678", {}, {"channels": CONTACT["channels"]}, "OK"),
    ({"operation": "delete_contact", "contact_id": 12345678}, "DELETE", "/api/v1/contact/12345678", {"erase": "false"}, None, "OK"),
    ({"operation": "list_segments", "name": "Summer + café"}, "GET", "/api/v1/groups", {"name": "Summer + café", "startindex": "1", "maxrows": "100"}, None, [{"id": 200400, "name": "Summer + café", "type": "Static"}]),
    ({"operation": "list_segment_contacts", "segment_id": 200400}, "GET", "/api/v1/group/200400/contacts", {"startindex": "1", "maxrows": "100", "orderByTs": "false", "asc": "true"}, None, []),
    ({"operation": "attach_contacts", "segment_id": 200400, "contact_ids": [12345678]}, "POST", "/api/v1/group/200400/contacts/attach", {}, {"contactIds": [12345678]}, "OK"),
    ({"operation": "detach_contacts", "segment_id": 200400, "external_customer_ids": ["TV12790"]}, "POST", "/api/v1/group/200400/contacts/detach", {}, {"externalCustomerIds": ["TV12790"]}, "OK"),
    ({"operation": "list_workflows", "name": "Welcome"}, "GET", "/api/v1/workflows", {"startindex": "1", "maxrows": "100", "name": "Welcome"}, None, []),
    ({"operation": "list_email_messages", "search": "promo"}, "GET", "/api/v1/messages/email", {"startindex": "1", "maxrows": "100", "search": "promo"}, None, []),
    ({"operation": "get_email_message", "message_id": 2345678}, "GET", "/api/v1/messages/email/2345678", {}, None, {"name": "Welcome", "from": EMAIL["sender"], "subject": EMAIL["subject"], "htmlText": EMAIL["html_text"]}),
    ({"operation": "create_email_message", "message": EMAIL}, "POST", "/api/v1/messages/email", {}, {"name": EMAIL["name"], "from": EMAIL["sender"], "subject": EMAIL["subject"], "htmlText": EMAIL["html_text"], "template": False}, {"id": 2345678}),
    ({"operation": "update_email_message", "message_id": 2345678, "message": EMAIL}, "PUT", "/api/v1/messages/email/2345678", {}, {"name": EMAIL["name"], "from": EMAIL["sender"], "subject": EMAIL["subject"], "htmlText": EMAIL["html_text"], "template": False}, "OK"),
    ({"operation": "delete_email_message", "message_id": 2345678}, "DELETE", "/api/v1/messages/email/2345678", {}, None, "OK"),
    ({"operation": "send_prepared_message", "message_id": 2345678, "recipients": [{"contact_id": 449790707}], "email": False}, "POST", "/api/v1/message/2345678/smartsend", {}, {"recipients": [{"contactId": 449790707}], "email": False}, {"id": 0, "results": [{"id": 0, "status": "OK", "requestId": "8b2e65d9-060b-4c61-bbd7-73c6796fa504"}]}),
    ({"operation": "generate_event", "event_type_key": "create_contact", "params": {"phone": "380501234567", "externalCustomerId": "AV13760"}}, "POST", "/api/v3/event", {}, {"eventTypeKey": "create_contact", "params": {"phone": "380501234567", "externalCustomerId": "AV13760"}}, None),
    ({"operation": "list_subscription_categories"}, "GET", "/api/v1/subscriptions", {}, None, []),
    ({"operation": "get_contact_subscriptions", "contact_id": 12345678}, "GET", "/api/v1/contact/12345678/subscriptions", {}, None, {"id": 1, "key": "news"}),
    ({"operation": "update_contact_subscriptions", "contact_id": 12345678, "subscriptions": ["news"]}, "PUT", "/api/v1/contact/12345678/subscriptions", {}, {"subscriptions": ["news"]}, "OK"),
    ({"operation": "get_additional_fields"}, "GET", "/api/v1/additionalfields", {}, None, {"addressBooks": []}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body,response", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_reteno_exact_contract_request(monkeypatch, config, method, path, query, body, response):
    requests = transport(monkeypatch, response)
    out = await node(config).execute({})
    assert out["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "api.reteno.com" and request.url.scheme == "https"
    assert request.method == method and request.url.path == path
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body
    assert base64.b64decode(request.headers["Authorization"].split()[1]).decode() == "noclick:" + TOKEN
    assert TOKEN not in json.dumps(out)
    if method != "GET":
        assert out["acknowledged"]
    if config["operation"] in {"send_prepared_message", "generate_event"}:
        assert out["processing_verified"] is False


@pytest.mark.asyncio
async def test_reteno_totalcount_and_full_page_without_total_are_honest(monkeypatch):
    transport(monkeypatch, [{"id": 200400}], headers={"TotalCount": "3"})
    result = await node({"operation": "list_segments", "maxrows": 1}).execute({})
    assert result["total_count"] == 3 and result["has_more"] and result["next_startindex"] == 2
    transport(monkeypatch, [{"id": 200400}])
    result = await node({"operation": "list_segments", "maxrows": 1}).execute({})
    assert result["has_more"] is None and result["next_startindex"] == 2
    transport(monkeypatch, [])
    result = await node({"operation": "list_segments"}).execute({})
    assert result["has_more"] is False and result["next_startindex"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_reteno_rejection_no_redirect_retry_and_secret_redaction(monkeypatch, status):
    encoded = base64.b64encode(("noclick:" + TOKEN).encode()).decode()
    requests = transport(monkeypatch, {"message": TOKEN + " Basic " + encoded}, status=status, headers={"Location": "https://example.com"})
    result = await node({"operation": "get_account_info"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and encoded not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_reteno_documented_send_response_and_recipient_errors(monkeypatch):
    documented = json.loads((FIXTURES / "prepared_response.json").read_text())
    requests = transport(monkeypatch, documented)
    result = await node({"operation": "send_prepared_message", "message_id": 2345678, "recipients": [{"contact_id": 449790707}], "email": False}).execute({})
    assert result["data"] == documented and result["recipient_errors"] is False and len(requests) == 1
    documented["results"][0].update(status="ERROR", message="Recipient cannot receive this message")
    transport(monkeypatch, documented)
    result = await node({"operation": "send_prepared_message", "message_id": 2345678, "recipients": [{"contact_id": 449790707}], "email": False}).execute({})
    assert result["status"] == "error" and result["recipient_errors"] and not result["processing_verified"]


@pytest.mark.parametrize("config", [
    {"operation": "detach_contacts", "segment_id": 200400},
    {"operation": "attach_contacts", "segment_id": 200400, "contact_ids": []},
    {"operation": "get_contact", "contact_id": -1},
    {"operation": "get_contact", "contact_id": "1/contacts"},
    {"operation": "list_segments", "maxrows": 501},
    {"operation": "generate_event", "event_type_key": "create_contact", "params": {}},
    {"operation": "generate_event", "event_type_key": "create_contact", "params": {"phone": "380501234567", "large": "x" * 20000}},
    {"operation": "send_prepared_message", "message_id": 2345678, "recipients": [{"contact_id": 123, "locator": "john@example.com"}]},
    {"operation": "upsert_contact", "contact": {"channels": []}},
])
def test_reteno_invalid_inputs_refused(config):
    with pytest.raises((ValueError, ValidationError)):
        native.RetenoNode.parse_config({"config": config})


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["text", None, 123])
async def test_reteno_malformed_read_is_not_evidence(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError, match="unexpected"):
        await node({"operation": "get_account_info"}).execute({})


def test_reteno_manual_credential_default_and_evidence_require_no_extra_input():
    credential = native.RetenoAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "reteno_api_key"
    assert native.RetenoNode.connection_evidence.operation == "list_segments"
    assert native.RetenoNode.connection_evidence.identity_operation == "get_account_info"
