"""Exercise Smoove through the native factory using fixture-only HTTP.

These regressions pin published paths, write bodies, identifiers, pagination,
and credential rejections without using a provider account.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import smoove_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-smoove-key"
AUTH = {"credential_type": "smoove_api_key", "api_key": TOKEN}
CONTRACT = json.loads((Path(__file__).parent / "fixtures/smoove/operations.json").read_text())
CASES = {
    "list_contacts": ({}, {"id": 846, "email": "jhon@domain.com"}),
    "create_contact": ({"email": "jhon@domain.com", "lists_ToSubscribe": [283184], "customFields": {"i2": 905, "i3": True}}, {"id": 846}),
    "get_contact": ({"id": "jhon+tag@domain.com", "by": "Email"}, {"id": 846}),
    "update_contact": ({"id": "846", "firstName": "Updated", "canReceiveEmails": False, "lists_ToUnsubscribe": [999]}, {"id": 846, "firstName": "Updated"}),
    "contact_exists": ({"id": "846", "by": "ContactId"}, True),
    "unsubscribe_contact": ({"id": "846", "by": "ContactId", "reason": "To much mails"}, "Ok"),
    "get_contact_status": ({"id": "846"}, {"id": 846, "status": "Active"}),
    "list_unsubscribed_contacts": ({}, []),
    "list_contact_fields": ({}, [{"key": "i1", "label": "Favorite pets", "custom": True}]),
    "list_lists": ({}, [{"id": 173584, "name": "My subscribers list"}]),
    "create_list": ({"name": "My subscribers list", "permissions": {"isPublic": False}}, {"id": 173584}),
    "get_list": ({"id": 173584}, {"id": 173584, "name": "My subscribers list"}),
    "list_list_contacts": ({"id": 173584}, [{"id": 846}]),
    "list_landing_pages": ({"type": "LandingPage"}, [{"formId": 12345, "formTitle": "My landing page"}]),
    "get_landing_page": ({"id": 12345}, {"formId": 12345}),
    "list_landing_page_recipients": ({"id": 12345}, [{"id": 112121, "contactId": 585694}]),
    "list_campaign_templates": ({}, [{"id": "123456", "name": "ApiTemplate"}]),
    "get_campaign_statistics": ({"id": "5142684"}, {"howManyWasSent": 3500, "clicked": 1100}),
    "list_campaign_recipients": ({"id": "5142684"}, [{"contactId": 123587, "campaignId": 5142684}]),
    "create_communication": ({"contact": "jhon@domain.com", "by": "Email", "communicator": "admin@domain.com", "initiator": "You", "date": "28/10/2024", "time": "13:00", "type": "Meeting", "content": "Discussed plan"}, {"id": 123456}),
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, config=None):
    return NodeFactory.create_node(node_id="smoove-fixture", node_type="automation-smoove",
        node_data={"config": {"operation": operation, **(config or {})}, "credentials": AUTH})


def transport(monkeypatch, body, status=200, mime="application/json"):
    calls = []
    def respond(request):
        calls.append(request)
        assert request.url.host == "rest.smoove.io"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        return httpx.Response(status, json=body, headers={"Content-Type": mime})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", CONTRACT, ids=lambda e: e["operation"])
async def test_smoove_published_routes_and_responses(monkeypatch, endpoint):
    op = endpoint["operation"]
    config, body = CASES[op]
    calls = transport(monkeypatch, body)
    result = await node(op, config).execute({})
    assert result["status"] == "success" and result["data"] == body
    assert len(calls) == 1 and calls[0].method == endpoint["method"]
    assert calls[0].url.path == endpoint["path"].replace("{id}", str(config.get("id", "")))
    if op.startswith("list_"):
        assert result["items"] == (body if isinstance(body, list) else [body])
    if endpoint["method"] in {"PUT", "POST"}:
        payload = json.loads(calls[0].content)
        assert not {"operation", "id", "by"} & payload.keys()
    if op == "create_contact":
        assert payload["customFields"] == {"i2": 905, "i3": True}
        assert payload["lists_ToSubscribe"] == [283184]
        assert dict(calls[0].url.params) == {"updateIfExists": "false", "restoreIfDeleted": "false", "restoreIfUnsubscribed": "false", "overrideNullableValue": "false"}
    if op == "update_contact":
        assert payload == {"firstName": "Updated", "canReceiveEmails": False, "lists_ToUnsubscribe": [999]}
    if op in {"contact_exists", "unsubscribe_contact"}:
        assert calls[0].url.params["by"] == "ContactId"
    if op == "get_contact":
        assert "%2B" in str(calls[0].url) and "%40" in str(calls[0].url)
        assert calls[0].url.params["by"] == "Email"
    if op == "create_communication":
        assert payload["date"] == "28/10/2024" and calls[0].url.params["by"] == "Email"


@pytest.mark.asyncio
async def test_smoove_pagination_is_one_page(monkeypatch):
    calls = transport(monkeypatch, [{"id": 1}, {"id": 2}])
    out = await node("list_contacts", {"page": 3, "itemsPerPage": 2, "includeCustomFields": True}).execute({})
    assert len(calls) == 1 and calls[0].url.params["page"] == "3"
    assert calls[0].url.params["itemsPerPage"] == "2" and calls[0].url.params["includeCustomFields"] == "true"
    assert out["page"] == 3 and out["next_page_hint"] == 4
    transport(monkeypatch, [])
    assert (await node("list_contacts").execute({}))["next_page_hint"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 429, 500, 302])
async def test_smoove_http_failures_preserve_rejection_without_key(monkeypatch, status):
    calls = transport(monkeypatch, "API key rejected " + TOKEN, status=status)
    out = await node("list_lists").execute({})
    assert out["status"] == "error" and out["http_status"] == status
    assert out["error"] == "API key rejected [redacted]"
    assert len(calls) == 1 and "items" not in out


@pytest.mark.asyncio
@pytest.mark.parametrize("op,config,body,mime", [
    ("list_lists", {}, "bad collection", "application/json"),
    ("list_lists", {}, ["bad record"], "application/json"),
    ("list_lists", {}, {}, "application/json"),
    ("list_lists", {}, [{}], "application/json"),
    ("list_lists", {}, {"errors": ["denied"]}, "application/json"),
    ("get_contact", {"id": "846"}, [], "application/json"),
    ("contact_exists", {"id": "846", "by": "ContactId"}, {}, "application/json"),
    ("unsubscribe_contact", {"id": "846", "by": "ContactId"}, {}, "application/json"),
    ("list_lists", {}, {}, "text/html"),
])
async def test_smoove_malformed_success_is_not_evidence(monkeypatch, op, config, body, mime):
    transport(monkeypatch, body, mime=mime)
    with pytest.raises(ValueError):
        await node(op, config).execute({})


def test_smoove_manual_credential_and_schema_contract():
    from nodes.core.credential_connect import shape_credential
    shaped, errors, resolved = shape_credential("smoove_api_key", {"api_key": "  " + TOKEN + "  "})
    assert not errors and shaped["api_key"] == TOKEN
    assert resolved == ("automation-smoove", native.SmooveAPIKeyCredential)
    assert native.SmooveAPIKeyCredential.model_validate(shaped).credential_type == "smoove_api_key"
    assert native.SmooveNode.connection_evidence.operation == "list_lists"
    assert not native.SmooveNode.required_config_fields({"operation": "list_lists"})
    assert native.SmooveAPIKeyCredential.model_fields["credential_type"].default == "smoove_api_key"
    assert not native.SmooveNode.validate_config({"config": {"operation": "list_contacts", "itemsPerPage": 101}, "credentials": AUTH})["valid"]
    for key in ["https://example.com/key", "Bearer key", "line\nbreak"]:
        with pytest.raises(ValidationError):
            native.SmooveAPIKeyCredential(api_key=key)
    for identifier in [".", "..", "invalid\nidentifier"]:
        assert not native.SmooveNode.validate_saved_config({"operation": "get_contact", "id": identifier})["valid"]
