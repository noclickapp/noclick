"""Offline Kenect contract and execution regression tests.

The provider's pinned schema validates every exposed request, while explicit
checks cover credentials, paging, acknowledgements and failure handling.
"""
import hashlib
import json
from pathlib import Path

import httpx
import pytest
import yaml
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from nodes.kenect_text_messaging_node import (
    KenectAPIKeyCredential, KenectFullConfig, KenectTextMessagingNode,
)

FIXTURES = Path(__file__).parent / "fixtures" / "kenect-text-messaging"
SPEC = yaml.safe_load((FIXTURES / "openapi.yaml").read_text())
CREDENTIAL = {"api_key": "test-kenect-key-12345", "api_secret": "test-kenect-secret-67890", "kenect_location_id": "24685"}

# Inputs use the published field names and example values. Response objects
# here are intentionally synthetic, not claimed as provider-authored examples.
CASES = [
    ({"operation": "list_locations", "organizationId": "123"}, "GET", "/api/v1/locations", [{"id": 24685, "locationName": "Main office"}]),
    ({"operation": "list_users", "filterByLocationId": True}, "GET", "/api/v1/users", [{"id": 123}]),
    ({"operation": "get_user", "userId": 123}, "GET", "/api/v1/users/123", {"id": 123}),
    ({"operation": "list_leads", "limit": 25, "offset": 50, "startDate": "2022-01-01T00:00:00Z"}, "GET", "/api/v1/lead", []),
    ({"operation": "list_broadcast_messages", "page": 2, "pageSize": 25}, "GET", "/api/v1/broadcast-messages", {"results": [], "currentPage": 2, "pageSize": 25, "totalPages": 2, "totalRecords": 25}),
    ({"operation": "list_conversations", "limit": 25, "offset": 50, "beginAt": "2022-01-01T00:00:00Z"}, "GET", "/api/v1/messages", []),
    ({"operation": "list_messages_by_phone", "phoneNumber": "+15555555555"}, "GET", "/api/v1/messages/by-phone-number", []),
    ({"operation": "get_conversation_by_phone", "phoneNumber": "+15555555555", "offset": 100}, "GET", "/api/v1/messages/conversations/by-phone-number", {"id": 0, "messages": []}),
    ({"operation": "list_conversations_by_contact", "contactExternalId": "123"}, "GET", "/api/v1/messages/conversations/by-contact-external-id", []),
    ({"operation": "get_attachment_info", "attachmentId": 123, "messageId": 123}, "GET", "/api/v1/messages/attachment-info", {}),
    ({"operation": "send_message", "contactPhone": "+15555555555", "messageBody": "Hello", "externalContactId": "123", "attachments": [{"name": "1-attachments/code/file-name.png"}]}, "POST", "/api/v1/messages", {"id": 123, "contactPhone": "+15555555555", "status": "SENDING"}),
    ({"operation": "send_review_request", "phoneNumber": "+15555555555", "messageBody": "Some text"}, "POST", "/api/v1/reviews/review-request", {"requestCreated": True, "reviewRequestId": 664849}),
    ({"operation": "create_lead", "partnerLeadId": "L-123", "firstName": "John", "lastName": "Doe", "phoneNumber": "+15555555555"}, "POST", "/api/v1/lead", {"leadId": 123}),
    ({"operation": "notify_event", "eventName": "CLOSED_SALE_EVENT", "phone": "+15555555555", "recordId": "123", "eventData": {"customerName": "John"}}, "POST", "/api/v1/events/notify", None),
    ({"operation": "sync_contacts", "contacts": [{"firstName": "John", "lastName": "Doe", "mobilePhone": "+15555555555", "externalId": "123", "birthday": 1640995200000}], "totalCount": 1}, "POST", "/api/v1/contact/batch", {}),
]


def node(config, credential=None):
    parsed = KenectFullConfig.model_validate({"config": config, "credentials": credential or CREDENTIAL})
    return KenectTextMessagingNode("kenect-test", "automation-kenect-text-messaging", {}, config=parsed)


@pytest.fixture
def mock_http(monkeypatch):
    original = httpx.AsyncClient
    def install(handler):
        def factory(**kwargs):
            assert kwargs["follow_redirects"] is False
            return original(transport=httpx.MockTransport(handler), **kwargs)
        monkeypatch.setattr("nodes.kenect_text_messaging_node.httpx.AsyncClient", factory)
    return install


def test_contract_pin():
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    assert hashlib.sha256((FIXTURES / manifest["file"]).read_bytes()).hexdigest() == manifest["sha256"]
    assert SPEC["info"]["version"] == manifest["version"] == "1.0.1"


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_contract_requests(mock_http, config, method, path, body):
    seen = []
    def handle(request):
        seen.append(request)
        assert request.method == method
        assert request.url.host == "integrations-api.kenect.com"
        assert request.url.path == path
        assert request.headers["X-Api-Key"] == CREDENTIAL["api_key"]
        assert request.headers["X-Api-Secret"] == CREDENTIAL["api_secret"]
        assert request.headers["X-Location-Id"] == "24685"
        template = path if config["operation"] != "get_user" else "/api/v1/users/{userId}"
        contract = SPEC["paths"][template][method.lower()]
        if method == "POST":
            sent = json.loads(request.content)
            assert sent == {k: v for k, v in config.items() if k != "operation"}
            schema = contract["requestBody"]["content"]["application/json"]["schema"]
            Draft202012Validator({**schema, "components": SPEC["components"]}).validate(sent)
        else:
            valid_params = {p["name"] for p in contract.get("parameters", []) if p["in"] == "query"}
            assert set(request.url.params) <= valid_params
            for k, v in config.items():
                if k not in {"operation", "userId"}:
                    assert request.url.params[k] == (str(v).lower() if isinstance(v, bool) else str(v))
        return httpx.Response(202 if config["operation"] == "notify_event" else 200,
                              **({"json": body} if body is not None else {}))
    mock_http(handle)
    result = await node(config).execute({})
    assert len(seen) == 1
    assert result["status"] == "success"
    assert result["data"] == body
    assert "delivered" not in result


@pytest.mark.parametrize("config", [
    {"operation": "send_message", "contactPhone": "+15555555555"},
    {"operation": "create_lead", "partnerLeadId": "L-123"},
    {"operation": "notify_event", "eventName": "CLOSED_SALE_EVENT", "phone": "+15555555555"},
    {"operation": "sync_contacts", "contacts": [], "totalCount": 1},
    {"operation": "get_user", "userId": "../locations"},
    {"operation": "list_conversations", "limit": 101},
])
def test_required_fields_and_bounds(config):
    with pytest.raises(ValidationError):
        node(config)


def test_manual_credential_shape():
    credential = KenectAPIKeyCredential.model_validate(CREDENTIAL)
    assert credential.credential_type == "kenect_text_messaging_api_key"
    for field in ("api_key", "api_secret", "kenect_location_id"):
        with pytest.raises(ValidationError):
            KenectAPIKeyCredential.model_validate({k: v for k, v in CREDENTIAL.items() if k != field})
    with pytest.raises(ValidationError):
        KenectAPIKeyCredential.model_validate({**CREDENTIAL, "api_key": "bad\r\nheader"})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 403, 429, 500, 302])
async def test_error_envelopes_and_redaction(mock_http, status):
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(status, json={"error": "Rejected " + CREDENTIAL["api_secret"]},
                              headers={"Location": "https://example.com/stolen"})
    mock_http(handle)
    result = await node({"operation": "list_locations"}).execute({})
    assert len(seen) == 1
    assert result["status"] == "error"
    assert CREDENTIAL["api_secret"] not in json.dumps(result)
    assert "Rejected" in json.dumps(result)


@pytest.mark.asyncio
async def test_timeout_is_not_retried(mock_http):
    seen = []
    def handle(request):
        seen.append(request)
        raise httpx.ReadTimeout("do not leak " + CREDENTIAL["api_secret"], request=request)
    mock_http(handle)
    with pytest.raises(ValueError, match="inspect Kenect") as error:
        await node({"operation": "send_message", "contactPhone": "+15555555555", "messageBody": "Hello"}).execute({})
    assert CREDENTIAL["api_secret"] not in str(error.value)
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["not JSON", {}])
async def test_invalid_list_does_not_prove_connection(mock_http, body):
    mock_http(lambda request: httpx.Response(200, **({"content": body} if isinstance(body, str) else {"json": body})))
    with pytest.raises(ValueError):
        await node({"operation": "list_locations"}).execute({})


@pytest.mark.asyncio
async def test_no_content_is_not_json(mock_http):
    mock_http(lambda request: httpx.Response(204))
    result = await node({"operation": "get_conversation_by_phone", "phoneNumber": "+15555555555"}).execute({})
    assert result["data"] is None
    assert result["http_status"] == 204
