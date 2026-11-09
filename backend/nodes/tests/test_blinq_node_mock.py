"""Blinq request regressions using the provider's published response examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import blinq_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/blinq/contract_examples.json").read_text())
TOKEN = "blinq-synthetic-unit-test-key"
CONFIGS = {
    "list_notes": {"limit": 5, "order_by": "updated_at", "updated_at_gte": "2026-10-01T00:00:00Z"},
    "search_notes": {"query": "Pricing", "limit": 10},
    "query_notes": {"query": "What follow-up actions did we agree on?", "note_ids": ["note-id-1", "note-id-2"]},
    "get_note": {"id": "note-id"},
    "get_note_transcript": {"id": "note-id"},
    "get_current_user": {},
    "list_workspaces": {},
    "list_contacts": {"workspace_id": "workspace-id", "search": "Jane", "limit": 25},
    "get_contact": {"workspace_id": "workspace-id", "contact_id": "contact-id"},
    "list_cards": {"workspace_id": "workspace-id", "limit": 25},
    "get_card": {"workspace_id": "workspace-id", "card_id": "card-id"},
    "create_webhook": {"workspace_id": "workspace-id", "url": "https://example.com/webhooks/blinq", "events": ["contact.created"]},
    "list_webhooks": {"workspace_id": "workspace-id"},
    "delete_webhook": {"workspace_id": "workspace-id", "subscription_id": "subscription-id"},
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **overrides):
    return NodeFactory.create_node(node_id="blinq-test", node_type="automation-blinq", node_data={
        "credentials": {"credential_type": "blinq_api_key", "api_key": TOKEN},
        "config": {"operation": operation, **CONFIGS[operation], **overrides},
    })


def transport(monkeypatch, response):
    calls = []
    def respond(request):
        calls.append(request)
        return response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(CONFIGS))
async def test_published_contract_operations(monkeypatch, operation):
    example = EXAMPLES[operation]
    calls = transport(monkeypatch, httpx.Response(example["status"], json=example["body"]) if example["body"] is not None else httpx.Response(204))
    result = await node(operation).execute({})
    assert result["status"] == "success"
    assert result["http_status"] == example["status"]
    assert len(calls) == 1
    request = calls[0]
    assert request.method == example["method"]
    path = example["path"]
    for key, value in CONFIGS[operation].items():
        path = path.replace("{" + key + "}", str(value))
    assert request.url.path == path
    assert request.url.host == "api.blinq.me"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if operation == "query_notes":
        assert json.loads(request.content) == CONFIGS[operation]
    if operation == "create_webhook":
        assert json.loads(request.content) == {k: v for k, v in CONFIGS[operation].items() if k != "workspace_id"}
        assert result["data"]["signing_secret"] == "whsec_example"
    if operation == "delete_webhook":
        assert result["deleted_id"] == "subscription-id"
    elif operation != "create_webhook":
        assert result["data"] == example["body"]
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_explicit_cursor_and_filters(monkeypatch):
    body = {"contacts": [], "has_more": False, "next_cursor": None, "total_count": None}
    calls = transport(monkeypatch, httpx.Response(200, json=body))
    result = await node("list_contacts", cursor="opaque-page-2", updated_at_gte="2026-10-01T00:00:00Z").execute({})
    assert dict(calls[0].url.params) == {"cursor": "opaque-page-2", "search": "Jane", "limit": "25", "updated_at_gte": "2026-10-01T00:00:00Z"}
    assert result["data"]["has_more"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_provider_errors_preserve_message_without_token_or_retry(monkeypatch, status):
    calls = transport(monkeypatch, httpx.Response(status, json={"message": "Rejected " + TOKEN}))
    result = await node("create_webhook").execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["status_code"] == status
    assert result["message"] == "Rejected [redacted]" and len(calls) == 1
    if status == 500:
        assert "unknown" in result["write_outcome"]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"workspaces": "bad"}])
async def test_malformed_response_is_not_connection_evidence(monkeypatch, body):
    transport(monkeypatch, httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node("list_workspaces").execute({})


@pytest.mark.asyncio
async def test_nonadvancing_pagination_is_rejected(monkeypatch):
    body = {"contacts": [], "has_more": True, "next_cursor": "same", "total_count": None}
    transport(monkeypatch, httpx.Response(200, json=body))
    with pytest.raises(ValueError, match="nonadvancing"):
        await node("list_contacts", cursor="same").execute({})


@pytest.mark.parametrize("operation,changes", [
    ("list_notes", {"limit": 51}), ("search_notes", {"query": ""}),
    ("query_notes", {"note_ids": []}), ("create_webhook", {"events": []}),
    ("create_webhook", {"url": "http://example.com"}),
    ("create_webhook", {"url": "https://user:pass@example.com/hook"}),
    ("list_notes", {"updated_at_gte": "yesterday"}),
    ("get_note", {"id": ".."}),
])
def test_invalid_configuration_is_rejected(operation, changes):
    with pytest.raises((ValueError, ValidationError)):
        node(operation, **changes)


def test_manual_credential_default_and_evidence():
    credential = native.BlinqAPIKeyCredential.model_validate({"api_key": TOKEN})
    assert credential.credential_type == "blinq_api_key"
    assert native.BlinqNode.connection_evidence.identity_operation == "get_current_user"
    from nodes.core.registry import NODE_REGISTRY
    assert NODE_REGISTRY["automation-blinq"] is native.BlinqNode
    with pytest.raises(ValidationError):
        native.BlinqAPIKeyCredential(api_key="Bearer key")


@pytest.mark.asyncio
@pytest.mark.parametrize("status,text,retry", [
    ("available", "", None), ("processing", None, 5), ("not_applicable", None, None),
])
async def test_documented_transcript_states_are_preserved(monkeypatch, status, text, retry):
    body = {"status": status, "text": text, "retry_after": retry}
    calls = transport(monkeypatch, httpx.Response(200, json=body))
    result = await node("get_note_transcript").execute({})
    assert result["data"] == body and len(calls) == 1
