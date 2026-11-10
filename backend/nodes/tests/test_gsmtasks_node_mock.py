import base64
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError
from nodes.gsmtasks_node import GSMTasksNode, GSMTasksNodeConfig, GSMTasksAPIKeyCredential

CREDS = {"credential_type": "gsmtasks_api_key", "api_key": "test-api-key"}
ID = "497f6eca-6276-4993-bfeb-53cbbbba6f08"
FIXTURE = json.loads((Path(__file__).parent / "fixtures/gsmtasks/create_task.json").read_text())


def node(config):
    return GSMTasksNode(node_id="test", node_type="automation-gsmtasks", node_data={},
        config=GSMTasksNodeConfig.model_validate({"config": config, "credentials": CREDS}), sio=Mock())


@pytest.mark.asyncio
async def test_create_task_uses_documented_body_and_version(monkeypatch):
    requests = []
    async def request(self, method, url, **kwargs):
        requests.append((method, url, kwargs))
        return httpx.Response(201, json=FIXTURE["response"])
    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    result = await node({"operation": "create_task", **FIXTURE["request"]}).execute({})
    method, url, kwargs = requests[0]
    assert (method, url) == ("POST", "https://api.gsmtasks.com/tasks/")
    assert kwargs["json"] == FIXTURE["request"]
    assert kwargs["headers"] == {"Authorization": "Token test-api-key", "Accept": "application/json; version=2.11.10"}
    assert result["data"] == FIXTURE["response"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path", [
    ("accept_task", "accept"), ("activate_task", "activate"), ("transit_task", "transit"),
    ("complete_task", "complete"), ("fail_task", "fail"), ("cancel_task", "cancel"), ("unassign_task", "unassign")])
async def test_state_actions_are_single_post(monkeypatch, operation, path):
    calls = []
    async def request(self, method, url, **kwargs):
        calls.append((method, url, kwargs["json"]))
        return httpx.Response(200, json=FIXTURE["response"])
    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    await node({"operation": operation, "task_id": ID, "notes": "Delivered"}).execute({})
    assert calls == [("POST", f"https://api.gsmtasks.com/tasks/{ID}/{path}/", {"notes": "Delivered"})]


@pytest.mark.asyncio
async def test_account_evidence_preserves_array_and_pagination(monkeypatch):
    async def request(self, method, url, **kwargs):
        assert method == "GET" and url == "https://api.gsmtasks.com/accounts/"
        assert kwargs["params"] == {"page_size": 100}
        return httpx.Response(200, json=[{"id": ID, "name": "Dispatch"}], headers={"Link": "<next-page>; rel=next"})
    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    result = await node({"operation": "list_accounts"}).execute({})
    assert result["data"][0]["name"] == "Dispatch"
    assert result["pagination_link"] == "<next-page>; rel=next"


@pytest.mark.asyncio
async def test_rejection_is_visible_without_echoed_key(monkeypatch):
    async def request(*args, **kwargs):
        return httpx.Response(401, text="Invalid test-api-key")
    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    with pytest.raises(ValueError, match="GSMTasks API error 401") as exc:
        await node({"operation": "list_accounts"}).execute({})
    assert "test-api-key" not in str(exc.value)


def test_signature_matches_provider_algorithm_and_rejects_tampering():
    # Algorithm in the provider's webhooks tag: HMAC-SHA256(raw body), base64.
    body = json.dumps(FIXTURE["response"]).encode()
    secret = "test-webhook-secret"
    signed = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    headers = {"X-GSMtasks-Hmac-SHA256": signed}
    config = {"signing_secret": secret}
    assert GSMTasksNode.verify_webhook_signature(body, headers, config)
    assert not GSMTasksNode.verify_webhook_signature(body + b" ", headers, config)
    assert not GSMTasksNode.verify_webhook_signature(body, {}, config)
    assert not GSMTasksNode.verify_webhook_signature(body, headers, {})


@pytest.mark.asyncio
async def test_webhook_registration_and_cleanup(monkeypatch):
    calls = []
    async def request(credential, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"data": {"id": ID, "shared_secret": "test-secret"}}
    monkeypatch.setattr(GSMTasksNode, "_request", request)
    account = "https://api.gsmtasks.com/accounts/" + ID + "/"
    state = await GSMTasksNode._register_external_webhook(webhook_url="https://example.com/events",
        credential=CREDS, config={"account": account}, node_id="test")
    assert state == {"external_webhook_id": ID, "signing_secret": "test-secret"}
    body = calls[0][2]["body"]
    assert body["target"] == "https://example.com/events"
    assert body["account"] == account and body["version"] == "2.11.10"
    assert body["task_events"] is True and body["document_events"] is False
    assert calls[1][:2] == ("POST", f"/webhooks/{ID}/active/")
    await GSMTasksNode._unregister_external_webhook(credential=CREDS, config=state, node_id="test")
    assert calls[-1][:2] == ("DELETE", f"/webhooks/{ID}/")


def test_credential_default_and_path_validation():
    assert GSMTasksAPIKeyCredential(api_key="test-key").credential_type == "gsmtasks_api_key"
    with pytest.raises(ValidationError):
        node({"operation": "get_task", "task_id": "../users"})
    with pytest.raises(ValidationError):
        GSMTasksAPIKeyCredential(api_key="Token test-key")


@pytest.mark.asyncio
async def test_failed_activation_removes_new_webhook(monkeypatch):
    calls = []
    async def request(credential, method, path, **kwargs):
        calls.append((method, path))
        if path.endswith("/active/"):
            raise ValueError("Activation refused")
        return {"data": {"id": ID, "shared_secret": "test-secret"}}
    monkeypatch.setattr(GSMTasksNode, "_request", request)
    with pytest.raises(ValueError, match="Activation refused"):
        await GSMTasksNode._register_external_webhook(webhook_url="https://example.com/events",
            credential=CREDS, config={"account": FIXTURE["request"]["account"]}, node_id="test")
    assert calls[-1] == ("DELETE", f"/webhooks/{ID}/")
