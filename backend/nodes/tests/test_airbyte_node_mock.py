"""Exercise Airbyte's real node against serialized HTTP and schema-shaped data.

These tests cover Basic auth, RPC payloads, secret removal, and poll lifecycle
without a live account or database.
"""
import base64
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import airbyte_node as airbyte
from utils import ssrf

ID = "00000000-0000-4000-8000-000000000001"
CREDENTIAL = {"credential_type": "airbyte_basic", "server_url": "https://airbyte.example.com",
    "username": "airbyte", "password": "test-only-airbyte-password"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    captured, replies = [], []
    client = httpx.AsyncClient
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    def send(request):
        captured.append(request)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(**{**kw, "transport": httpx.MockTransport(send)}))
    return captured, replies


def node(config):
    data = {"config": config, "credentials": CREDENTIAL}
    return airbyte.AirbyteNode("airbyte-test", "automation-airbyte", data,
        config=airbyte.AirbyteNode.parse_config(data))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(airbyte.OPERATIONS))
async def test_every_action_maps_to_one_post(operation, transport):
    requests, replies = transport
    path, fields = airbyte.OPERATIONS[operation]
    config = {"operation": operation}
    for key in fields:
        if key.endswith("_id"):
            config[key] = 42 if key == "job_id" else ID
        elif key == "connection_configuration_json":
            config[key] = '{"user":"charles"}'  # SourceConfiguration's published example.
        elif key == "name":
            config[key] = "Warehouse sync"
        elif key == "connection_status":
            config[key] = "active"
    payload = {airbyte.LIST_KEYS[operation]: []} if operation in airbyte.LIST_KEYS else {"connectionId": ID}
    replies.append((200, payload))
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://airbyte.example.com/api/v1" + path
    assert request.method == "POST" and not request.url.query
    assert request.headers["authorization"] == "Basic " + base64.b64encode(b"airbyte:test-only-airbyte-password").decode()
    body = json.loads(request.content)
    if operation == "list_jobs":
        assert body == {"configId": ID, "configTypes": ["sync"], "pagination": {"pageSize": 100, "rowOffset": 0}}
    else:
        expected = {airbyte.API_FIELDS[key]: value for key, value in config.items() if key in airbyte.API_FIELDS}
        if "connection_configuration_json" in config:
            expected["connectionConfiguration"] = {"user": "charles"}
        assert body == expected


@pytest.mark.asyncio
async def test_connector_secrets_are_not_emitted(transport):
    requests, replies = transport
    replies.append((200, {"sourceId": ID, "name": "Production", "connectionConfiguration": {"password": "connector-secret"}, "secretId": "provider-secret-reference"}))
    result = await node({"operation": "get_source", "source_id": ID}).execute({})
    assert result["data"] == {"sourceId": ID, "name": "Production"}
    assert "connector-secret" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 422, 500])
async def test_rejections_fail_without_echoing_credentials(status, transport):
    requests, replies = transport
    replies.append((status, {"message": CREDENTIAL["password"]}))
    result = await node({"operation": "list_workspaces"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert CREDENTIAL["password"] not in json.dumps(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_provider_rejection_message_is_preserved(transport):
    _, replies = transport
    replies.append((401, {"message": "Invalid username or password"}))
    result = await node({"operation": "list_workspaces"}).execute({})
    assert result["message"] == "Invalid username or password"


@pytest.mark.asyncio
async def test_write_diagnostic_redacts_connector_secrets(transport):
    _, replies = transport
    replies.append((422, {"message": "Rejected connector password secret-connector-value"}))
    result = await node({"operation": "update_source", "source_id": ID, "name": "Source",
        "connection_configuration_json": '{"password":"secret-connector-value"}'}).execute({})
    assert result["message"] == "Rejected connector password [redacted]"


@pytest.mark.asyncio
async def test_invalid_connector_configuration_makes_no_request(transport):
    requests, _ = transport
    for value in ["[1]", "invalid"]:
        with pytest.raises(ValueError, match="configuration"):
            await node({"operation": "update_source", "source_id": ID, "name": "Source", "connection_configuration_json": value}).execute({})
    assert not requests


@pytest.mark.asyncio
async def test_poll_baseline_dedup_agent_event_and_scope(transport, monkeypatch):
    requests, replies = transport
    state = {}
    poll = node({"operation": "on_new_sync_job", "connection_id": ID})

    async def update(mutator, **kwargs):
        nonlocal state
        replacement, result = mutator(deepcopy(state))
        if replacement is not None:
            state = replacement
        return result

    monkeypatch.setattr(poll, "_update_node_state", update)
    # JobRead/JobWithAttemptsRead fields from the pinned contract; synthetic IDs.
    job = {"id": 1, "configType": "sync", "configId": ID, "createdAt": 1700000000, "updatedAt": 1700000000, "status": "running"}
    def reply(jobs):
        replies.append((200, {"jobs": [{"job": item, "attempts": []} for item in jobs], "totalJobCount": len(jobs)}))
    reply([job])
    assert (await poll.execute({}))["jobs"] == []
    assert poll.trigger_produced_no_event({})
    new_job = {**job, "id": 2, "createdAt": 1700000300}
    reply([new_job, job])
    result = await poll.execute({})
    assert result["jobs"] == [new_job]
    assert poll.trigger_emitted_event(result)
    event = airbyte.AirbyteNode.resolve_agent_event(result)
    assert "sync job 2" in event["text"] and ID in event["text"] and "running" in event["text"]
    reply([new_job, job])
    assert (await poll.execute({}))["jobs"] == []
    assert airbyte.AirbyteNode.resolve_agent_event({"jobs": []}) is None
    assert json.loads(requests[0].content)["configTypes"] == ["sync"]
    original_scope = airbyte.AirbyteNode.schedule_poll_scope({"operation": "on_new_sync_job", "connection_id": ID})
    assert original_scope != airbyte.AirbyteNode.schedule_poll_scope({"operation": "on_new_sync_job", "connection_id": "00000000-0000-4000-8000-000000000002"})


def test_manual_credential_default_and_origin():
    credential = airbyte.AirbyteBasicCredential.model_validate({k: v for k, v in CREDENTIAL.items() if k != "credential_type"})
    assert credential.credential_type == "airbyte_basic"
    assert airbyte.AirbyteBasicCredential.model_validate({**CREDENTIAL, "server_url": "https://airbyte.example.com/api/v1"}).server_url == CREDENTIAL["server_url"]
    for url in ["", "https://airbyte:password@example.com", "file:///tmp/airbyte"]:
        with pytest.raises(ValueError):
            airbyte.AirbyteBasicCredential.model_validate({**CREDENTIAL, "server_url": url})


@pytest.mark.asyncio
async def test_private_origin_is_guarded(transport, monkeypatch):
    requests, replies = transport
    async def blocked(*args, **kwargs):
        raise ssrf.SSRFError("Refusing private address")
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", blocked)
    monkeypatch.delenv("OUTBOUND_ALLOW_PRIVATE_IPS", raising=False)
    monkeypatch.delenv("HTTP_NODE_ALLOW_PRIVATE_IPS", raising=False)
    with pytest.raises(ssrf.SSRFError):
        await node({"operation": "list_workspaces"}).execute({})
    assert not requests
