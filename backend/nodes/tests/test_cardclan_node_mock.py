"""Exercise Cardclan's published integration routes with provider examples.

The transport is entirely mocked; sending tests never deliver real cards.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import cardclan_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-cardclan-integration-token"
CARD = "60f7b2b5b8f4a20015a4f5a5"
WORKSPACE = "60f7b2b5b8f4a20015a4f5a4"
USER = "60f7b2b5b8f4a20015a4f5a3"
CONFIG = "60f7b2b5b8f4a20015a4f5a7"
RECIPIENTS = [{"name": "John Doe", "email": "john@example.com", "company": "Acme Corp", "position": "Marketing Manager"}]
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/cardclan/contract_examples.json").read_text())["responses"]
CONFIGS = {
    "validate_authentication": {}, "list_workspaces": {},
    "list_cards": {"workspace_id": WORKSPACE}, "list_email_accounts": {},
    "send_card": {"card_id": CARD, "integration_id": CONFIG, "merge_tags": json.dumps(RECIPIENTS), "email_account": "CardClan"},
    "get_card_url": {"card_id": CARD, "integration_id": CONFIG, "merge_tags": json.dumps(RECIPIENTS)},
    "create_config": {"user_id": USER, "workspace_id": WORKSPACE, "card_id": CARD},
    "get_config": {"integration_id": CONFIG}, "get_config_by_card": {"card_id": CARD},
    "list_workflow_cards": {}, "get_card_details": {"card_id": CARD},
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **fields):
    return NodeFactory.create_node(node_id="cardclan-test", node_type="automation-cardclan",
        node_data={"config": {"operation": operation, **CONFIGS[operation], **fields},
            "credentials": {"credential_type": "cardclan_integration_key", "integration_key": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def handler(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONFIGS)
async def test_contract_routes_and_documented_responses(monkeypatch, operation):
    method, route, status = native.ROUTES[operation]
    requests = transport(monkeypatch, httpx.Response(status, json=EXAMPLES[operation]))
    result = await node(operation).execute({})
    assert result["status"] == "success"
    assert result["data"] == EXAMPLES[operation]
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method
    assert req.url.host == "app.cardclan.io"
    assert req.url.path == "/api" + route.replace("{cardId}", CARD)
    assert req.headers["authorization"] == "Bearer " + TOKEN
    expected_query = {"list_cards": {"workspace": WORKSPACE}, "get_config": {"integrationId": CONFIG}, "get_config_by_card": {"cardId": CARD}}.get(operation, {})
    assert dict(req.url.params) == expected_query
    if operation in {"send_card", "get_card_url"}:
        assert json.loads(req.content) == {"card": CARD, "integrationId": CONFIG, "mergeTags": RECIPIENTS, **({"emailAccount": "CardClan"} if operation == "send_card" else {})}
    elif operation == "create_config":
        assert json.loads(req.content) == {"userId": USER, "workspaceId": WORKSPACE, "cardId": CARD}
    else:
        assert req.content == b""


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 302])
async def test_provider_rejections_preserve_message_without_secrets_or_retry(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, json={"message": "Rejected " + TOKEN}))
    result = await node("validate_authentication").execute({})
    assert result == {"status": "error", "error": "Rejected [redacted]", "status_code": status, "http_status": status}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_send_failure_envelope_and_uncertain_send(monkeypatch):
    transport(monkeypatch, httpx.Response(201, json={"status": False, "message": "Card sending failed: Invalid email address"}))
    assert (await node("send_card").execute({}))["status"] == "error"
    for body in ({}, {"status": "true"}, []):
        transport(monkeypatch, httpx.Response(201, json=body))
        with pytest.raises(ValueError, match="did not confirm"):
            await node("send_card").execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"success": True}, {"success": True, "user_id": 123}])
async def test_identity_requires_a_real_user_id(monkeypatch, body):
    transport(monkeypatch, httpx.Response(200, json=body))
    with pytest.raises(ValueError, match="did not confirm"):
        await node("validate_authentication").execute({})


@pytest.mark.asyncio
async def test_default_sender_is_omitted(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(201, json=EXAMPLES["send_card"]))
    await node("send_card", email_account=None).execute({})
    assert "emailAccount" not in json.loads(requests[0].content)


@pytest.mark.asyncio
async def test_non_json_is_not_a_success(monkeypatch):
    transport(monkeypatch, httpx.Response(200, text="<html>Sign in</html>", headers={"content-type": "text/html"}))
    with pytest.raises(ValueError, match="unexpected response"):
        await node("list_workspaces").execute({})


@pytest.mark.parametrize("value", ["[]", "{}", "bad json", '[{"name":"John"}]', '[{"name":"John","email":"invalid"}]', '[{"name":"John","email":"john@example.com","age":3}]'])
def test_invalid_recipient_data_fails_before_network(value):
    with pytest.raises(ValueError):
        node("send_card", merge_tags=value)


def test_manual_credential_defaults_and_secret_validation():
    cred = native.CardclanIntegrationKeyCredential(integration_key="  " + TOKEN + "  ")
    assert cred.credential_type == "cardclan_integration_key"
    assert cred.integration_key == TOKEN
    for value in ("https://example.com/key", "Bearer abc", "abc\r\nInjected", "<token>"):
        with pytest.raises(ValidationError):
            native.CardclanIntegrationKeyCredential(integration_key=value)


@pytest.mark.parametrize("value", ["../other", "a/b", "https://evil.test", "id?x=y"])
def test_resource_ids_cannot_change_the_route(value):
    with pytest.raises(ValueError):
        node("get_card_details", card_id=value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401])
async def test_connection_evidence_names_the_account_and_reports_rejection(monkeypatch, status):
    from nodes.core import run_op
    from nodes.core.connection_evidence import collect_evidence

    transport(monkeypatch, httpx.Response(status, json=EXAMPLES["validate_authentication"] if status == 200 else {"message": "Invalid or missing authentication"}))
    async def run(**kwargs):
        assert kwargs["operation"] == "validate_authentication"
        assert kwargs["arguments"] == {}
        return await node(kwargs["operation"]).execute({})
    monkeypatch.setattr(run_op, "run_node_operation", run)
    result = await collect_evidence(node_type="automation-cardclan", user_id="test-user",
        credential_data={"credential_type": "cardclan_integration_key", "integration_key": TOKEN})
    assert result.reachable is (status == 200)
    if status == 200:
        assert result.account_label == USER
    else:
        assert result.error == "Invalid or missing authentication (HTTP 401)"


@pytest.mark.asyncio
async def test_list_shape_is_checked_and_empty_lists_are_valid(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(ValueError, match="list response"):
        await node("list_workspaces").execute({})
    transport(monkeypatch, httpx.Response(200, json=[]))
    assert (await node("list_workspaces").execute({}))["data"] == []
