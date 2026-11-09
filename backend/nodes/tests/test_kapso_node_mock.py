"""Exercise Kapso request construction and parsing through the real node factory."""
import json
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError
from nodes import kapso_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures/kapso"
CASES = json.loads((FIXTURES / "cases.json").read_text())
OPERATIONS = json.loads((FIXTURES / "operations.json").read_text())
TOKEN = "synthetic-kapso-api-key"
CREDENTIAL = {"credential_type": "kapso_api_key", "api_key": TOKEN, "business_account_id": "123456789012345"}


def node(config, credential=None):
    return NodeFactory.create_node(node_id="kapso-fixture", node_type="automation-kapso",
        node_data={"config": config, "credentials": CREDENTIAL if credential is None else credential})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_kapso_operation_routes_auth_and_documented_response(monkeypatch, operation):
    case = CASES[operation]
    requests = transport(monkeypatch, case["response"])
    result = await node(case["config"]).execute({})
    assert result == {"status": "success", "data": case["response"]}
    request, = requests
    route = OPERATIONS[operation]
    expected = route["path"]
    for key, value in {**case["config"], **CREDENTIAL}.items():
        expected = expected.replace("{" + key + "}", quote(str(value), safe=""))
    assert request.method == route["method"]
    assert request.url.raw_path.split(b"?", 1)[0].decode() == "/meta/whatsapp/v24.0" + expected
    assert request.url.host == "api.kapso.ai"
    assert request.headers["X-API-Key"] == TOKEN
    assert "authorization" not in request.headers
    if request.method == "GET":
        assert request.content == b""
    if operation == "get_flow":
        assert request.url.params["business_account_id"] == CREDENTIAL["business_account_id"]
        assert request.url.params["fields"] == case["config"]["fields"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation, expected", [
    ("send_text", {"messaging_product": "whatsapp", "to": "15551234567", "type": "text", "text": {"body": "Hello! Your order #12345 has been shipped."}}),
    ("send_template", {"messaging_product": "whatsapp", "to": "15551234567", "type": "template", "template": {"name": "order_update", "language": {"code": "en_US"}}}),
    ("block_users", {"block_users": [{"user": "15551234567"}]}),
    ("unblock_users", {"block_users": [{"user": "15551234567"}]}),
])
async def test_kapso_mutations_send_exact_documented_bodies(monkeypatch, operation, expected):
    requests = transport(monkeypatch, CASES[operation]["response"])
    await node(CASES[operation]["config"]).execute({})
    assert json.loads(requests[0].content) == expected


@pytest.mark.asyncio
async def test_kapso_profile_and_template_bodies(monkeypatch):
    for operation in ("update_business_profile", "create_template"):
        config = CASES[operation]["config"]
        requests = transport(monkeypatch, CASES[operation]["response"])
        await node(config).execute({})
        expected = {k: v for k, v in config.items() if k not in {"operation", "phone_number_id"}}
        if operation == "update_business_profile":
            expected["messaging_product"] = "whatsapp"
        assert json.loads(requests[0].content) == expected


@pytest.mark.asyncio
async def test_kapso_filters_and_cursor_preserved_without_following_links(monkeypatch):
    body = {"data": [{"id": "message-owned"}], "paging": {"cursors": {"after": "opaque+/="}, "next": "https://evil.example/"}}
    requests = transport(monkeypatch, body)
    result = await node({"operation": "list_messages", "phone_number_id": "110987654321", "after": "opaque+/=", "since": "2024-01-15T00:00:00Z", "direction": "inbound", "limit": 50}).execute({})
    assert result["data"] == body and len(requests) == 1
    assert dict(requests[0].url.params) == {"limit": "50", "after": "opaque+/=", "since": "2024-01-15T00:00:00Z", "direction": "inbound"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_kapso_error_statuses_and_secret_redaction(monkeypatch, status):
    requests = transport(monkeypatch, {"error": {"message": "Rejected " + TOKEN}}, status)
    result = await node({"operation": "list_phone_numbers"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and "Rejected" in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_kapso_error_envelope_cannot_prove_connection(monkeypatch):
    transport(monkeypatch, {"error": {"message": "Invalid API key"}})
    result = await node({"operation": "list_phone_numbers"}).execute({})
    assert result["status"] == "error"


def test_kapso_manual_credential_defaults_and_invalid_config():
    assert native.KapsoAPIKeyCredential.model_validate({"api_key": TOKEN, "business_account_id": "123456789012345"}).credential_type == "kapso_api_key"
    assert native.KapsoNode.connection_evidence.operation == "list_phone_numbers"
    for config in [
        {"operation": "get_message", "phone_number_id": "../other", "message_id": "message"},
        {"operation": "list_messages", "phone_number_id": "110987654321", "limit": 101},
        {"operation": "list_messages", "phone_number_id": "110987654321", "before": "a", "after": "b"},
        {"operation": "list_conversations", "phone_number_id": "110987654321", "unassigned": True, "assigned_user_id": "user"},
        {"operation": "send_text", "phone_number_id": "110987654321", "to": "15551234567", "text": ""},
    ]:
        with pytest.raises((ValidationError, ValueError)):
            native.KapsoNode.parse_config({"config": config, "credentials": CREDENTIAL})
