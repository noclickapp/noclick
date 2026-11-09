"""Check Heymarket's factory, signed requests, response parsing and manual connect.

The operation fixtures use synthetic account data and never contact the provider.
"""
import base64
import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from nodes import heymarket_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/heymarket/requests.json').read_text())
CREDENTIAL = {"credential_type": "heymarket_api_secret", "secret_id": "test-secret-id", "secret_key": "test-secret-key"}


def node(config, credential=None):
    return NodeFactory.create_node(node_id="heymarket-test", node_type="automation-heymarket",
        node_data={"config": config, "credentials": credential or CREDENTIAL})


def transport(monkeypatch, reply):
    calls = []
    def respond(request):
        calls.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_documented_operation_requests_and_responses(monkeypatch, case):
    def reply(request):
        if case.get("mime") == "text/plain":
            return httpx.Response(200, text=case["response"])
        return httpx.Response(200, json=case["response"])
    calls = transport(monkeypatch, reply)
    result = await node(case["config"]).execute({})
    assert result["status"] == "success" and result["data"] == case["response"]
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case["method"]
    assert request.url.host == "api.heymarket.com" and request.url.path == case["path"]
    assert dict(request.url.params) == case.get("query", {})
    assert (json.loads(request.content) if request.content else None) == case.get("body")
    assert CREDENTIAL["secret_key"] not in str(result)
    if case["config"]["operation"] == "send_message":
        assert result["acknowledged"] is True and result["delivery_verified"] is False


@pytest.mark.asyncio
async def test_jwt_signing_per_request_matches_published_contract(monkeypatch):
    clock = iter([1713225600, 1713225601])
    monkeypatch.setattr(native, "time", SimpleNamespace(time=lambda: next(clock)))
    calls = transport(monkeypatch, lambda _: httpx.Response(200, json=[]))
    for _ in range(2):
        await node({"operation": "list_inboxes"}).execute({})
    tokens = [r.headers["authorization"].removeprefix("Bearer ") for r in calls]
    assert tokens[0] != tokens[1]
    for i, token in enumerate(tokens):
        header, payload, signature = token.split(".")
        decode = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
        assert json.loads(decode(header)) == {"alg": "HS256", "typ": "JWT"}
        assert json.loads(decode(payload)) == {"iss": "test-secret-id", "iat": 1713225600 + i}
        assert decode(signature) == hmac.new(b"test-secret-id||test-secret-key", (header + "." + payload).encode(), hashlib.sha256).digest()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_rejection_preserves_provider_message_and_redacts_secrets_without_retry(monkeypatch, status):
    calls = transport(monkeypatch, lambda req: httpx.Response(status, text="Provider rejected " + CREDENTIAL["secret_key"] + " " + req.headers["authorization"]))
    result = await node(CASES[16]["config"]).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Provider rejected" in result["message"]
    assert CREDENTIAL["secret_id"] not in str(result) and CREDENTIAL["secret_key"] not in str(result)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_network_failure_is_ambiguous_for_send_and_never_retried(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("timeout", request=request)
    calls = transport(monkeypatch, fail)
    result = await node(CASES[16]["config"]).execute({})
    assert result["status"] == "error" and result["write_outcome"] == "unknown"
    assert "data" not in result and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"error": "invalid secret"}, {"errors": ["unavailable"]}, {"success": False}, "html error"])
async def test_error_envelope_and_wrong_shape_do_not_prove_connection(monkeypatch, body):
    transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    result = await node({"operation": "list_inboxes"}).execute({})
    assert result["status"] == "error" and "data" not in result


@pytest.mark.asyncio
async def test_empty_inbox_account_and_page_results_are_preserved(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, json=[]))
    assert (await node({"operation": "list_inboxes"}).execute({}))["data"] == []
    result = await node({"operation": "list_contacts", "page": 7, "limit": 10}).execute({})
    assert result["pagination"] == {"page": 7, "limit": 10, "single_page": True, "date": None}


def test_manual_credential_defaults_and_evidence_are_account_specific():
    from nodes.core.credential_connect import shape_credential
    shaped, errors, resolved = shape_credential("heymarket_api_secret", {"secret_id": " test-secret-id ", "secret_key": " test-secret-key "})
    assert not errors and shaped == {k: v for k, v in CREDENTIAL.items() if k != "credential_type"}
    assert resolved[1].model_validate(shaped).credential_type == "heymarket_api_secret"
    assert native.HeymarketNode.connection_evidence.operation == "list_inboxes"
    assert native.HeymarketNode.connection_evidence.proves == "account"


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "contact_id": "../team"},
    {"operation": "get_contact", "contact_id": 0},
    {"operation": "send_message", "phone_number": "+14155551234", "inbox_id": 42, "creator_id": 7, "text": "Hello"},
    {"operation": "create_contact"},
    {"operation": "close_conversation", "inbox_id": 42, "target": "14155551234"},
    {"operation": "list_contacts", "limit": 101},
    {"operation": "search_contacts", "contact_channels": []},
])
def test_invalid_inputs_fail_before_network(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)
