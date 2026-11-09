"""HTTP boundary tests using SMTP2GO's published v3.0.4 examples."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import smtp2go_node as node
from nodes.core.run_op import run_node_operation
import utils.ssrf as ssrf

KEY = "api-synthetic-key-for-offline-tests"
AUTH = {"credential_type": "smtp2go_api_key", "api_key": KEY}
FIXTURES = json.loads((Path(__file__).parent / "fixtures/smtp2go/responses.json").read_text())
ARGUMENTS = {
    "send_email": {"sender": "John Smith <john@example.com>", "to": ["Jane Jones <jane@example.com>"], "subject": "My Test Email", "text_body": "Test"},
    "add_suppression": {"email_address": "temp@example.com"},
    "remove_suppression": {"email_address": "temp@test.com", "reasons": ["manual", "spam"]},
    "add_sender_domain": {"domain": "example.com"},
    "verify_sender_domain": {"domain": "example.com"},
    "remove_sender_domain": {"domain": "example.com"},
    "create_template": {"template_name": "Shiny new name", "id": "testid", "subject": "Shiny new Subject", "html_body": "Shiny HTML body. This is a {{ variable }}", "text_body": "Shiny Text body"},
    "update_template": {"id": "testid", "subject": "Shiny new Subject"},
    "delete_template": {"id": "example"},
    "get_template": {"id": "testid"},
    "remove_scheduled_email": {"schedule_id": "fe7d54d0-8f06-40c5-a675-d72f183e8ebf"},
}


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        calls.append(request)
        assert request.url.host == "api.smtp2go.com"
        assert request.headers["X-Smtp2go-Api-Key"] == KEY
        assert KEY not in str(request.url)
        return responses.pop(0)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return calls, responses


async def run(operation, args=None):
    return await run_node_operation(node_type="automation-smtp2go", operation=operation,
        arguments=args if args is not None else ARGUMENTS.get(operation, {}),
        credential_data=AUTH, user_id="00000000-0000-0000-0000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", FIXTURES)
async def test_published_responses_and_exact_request(transport, operation):
    calls, responses = transport
    responses.append(httpx.Response(200, json=FIXTURES[operation]["body"]))
    result = await run(operation)
    assert result["status"] == "success"
    assert len(calls) == 1
    assert calls[0].method == "POST"
    assert calls[0].url.path == "/v3" + node.ROUTES[operation]
    assert json.loads(calls[0].content) == ARGUMENTS.get(operation, {})
    assert result["data"] == FIXTURES[operation]["body"]["data"]
    if operation == "send_email":
        assert result["delivery_verified"] is False
    if operation == "list_sender_emails":
        assert result["items"][0]["email_address"] == "test@test.com"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [200, 401, 403, 429, 500])
async def test_provider_errors_never_succeed_or_leak_key(transport, code):
    transport[1].append(httpx.Response(code, json={"data": {"error": "Denied " + KEY, "error_code": "E_ApiKey"}}))
    result = await run("list_sender_emails")
    assert result["status"] == "error"
    assert result["http_status"] == code
    assert KEY not in json.dumps(result)
    assert result["error"] == "Denied [redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"Location": "https://example.org"}),
    httpx.Response(200, text="<html>Login</html>"),
    httpx.Response(200, json={}),
    httpx.Response(200, json={"data": {}}),
    httpx.Response(200, json={"data": {"senders": [None]}}),
])
async def test_incomplete_connection_read_is_not_success(transport, response):
    transport[1].append(response)
    with pytest.raises(ValueError):
        await run("list_sender_emails")
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_native_pagination_and_optional_fields_preserved(transport):
    transport[1].append(httpx.Response(200, json={"request_id": "request", "data": {"templates": [], "continue_token": "next-token", "total_count": 12}}))
    result = await run("list_templates", {"continue_token": "previous-token", "page_size": 5, "fuzzy_search": False})
    assert result["data"]["continue_token"] == "next-token"
    assert json.loads(transport[0][0].content) == {"continue_token": "previous-token", "page_size": 5, "fuzzy_search": False}


@pytest.mark.asyncio
async def test_partial_send_failure_is_an_error(transport):
    transport[1].append(httpx.Response(200, json={"data": {"email_id": "mail", "failed": 1, "failures": ["Recipient refused"]}}))
    result = await run("send_email")
    assert result["status"] == "error" and result["delivery_verified"] is False


@pytest.mark.parametrize("args", [{"sender": "a@example.com", "to": ["b@example.com"]},
    {"sender": "a@example.com", "to": [], "text_body": "Hi"},
    {"sender": "a@example.com", "to": ["b@example.com"] * 101, "text_body": "Hi"},
    {"sender": "a@example.com", "to": ["b@example.com"], "template_id": "t", "template_data": "[]"}])
def test_invalid_send_inputs(args):
    with pytest.raises(ValueError):
        node.Smtp2GoNode.parse_config({"config": {"operation": "send_email", **args}, "credentials": AUTH})


def test_manual_connect_defaults_type_and_closed_operation():
    assert node.Smtp2GoApiKeyCredential(api_key=KEY).credential_type == "smtp2go_api_key"
    with pytest.raises(ValueError):
        node.Smtp2GoNode.parse_config({"config": {"operation": "get_template", "id": "t", "url": "https://other.example"}, "credentials": AUTH})


@pytest.mark.asyncio
async def test_scheduled_cancellation_bodyless_contract(transport):
    transport[1].append(httpx.Response(200))
    result = await run("remove_scheduled_email")
    assert result["status"] == "success" and result["acknowledged"] is True
    assert result["removal_verified"] is False
    assert json.loads(transport[0][0].content) == ARGUMENTS["remove_scheduled_email"]
