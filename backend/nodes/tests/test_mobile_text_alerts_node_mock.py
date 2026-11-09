"""Exercise Mobile Text Alerts with every verbatim published saved response.

Transport assertions cover auth, route and body boundaries without an account.
Negative cases mutate these fixtures to check fail-closed error handling.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import mobile_text_alerts_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/mobile-text-alerts/saved_examples.json").read_text())
TOKEN = "mta-local-test-key-abc123"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="mta-test", node_type=native.NODE_TYPE,
        node_data={"config": config, "credentials": {"api_key": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [(op, index) for op, fixture in EXAMPLES.items() for index in range(len(fixture["responses"]))]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,index", CASES)
async def test_saved_response_and_request_contract(monkeypatch, operation, index):
    fixture = EXAMPLES[operation]
    example = fixture["responses"][index]
    requests = transport(monkeypatch, httpx.Response(example["status"], content=example["body"], headers={"Content-Type": "application/json"}))
    result = await node(fixture["config"]).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "api.mobile-text-alerts.com"
    assert request.url.path.startswith("/v3/")
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(result)
    assert result["http_status"] == example["status"]
    assert result["status"] == ("error" if example["status"] >= 400 else "success")
    if request.content:
        body = json.loads(request.content)
        assert not {"operation", "idOrNumber", "groupId", "templateId", "scheduledMessageId", "request_id"}.intersection(body)
    if operation == "delete_group_member":
        assert request.method == "DELETE" and request.url.path == "/v3/groups/1111/subscribers/1234"
        assert not request.content
    if operation == "get_message_cost":
        assert json.loads(request.content)["from"] == "+11005555555"
        assert "from_number" not in json.loads(request.content)
    if operation.startswith("list_"):
        assert not request.url.query
        assert result["data"] == json.loads(example["body"])["data"]


@pytest.mark.asyncio
async def test_evidence_reads_groups_without_arguments(monkeypatch):
    fixture = EXAMPLES["list_groups"]["responses"][0]
    requests = transport(monkeypatch, httpx.Response(200, content=fixture["body"]))
    from nodes.core.connection_evidence import collect_evidence
    result = await collect_evidence(node_type=native.NODE_TYPE, credential_data={"api_key": TOKEN}, user_id="mta-test", pool=None)
    assert result.reachable is True and result.samples
    assert requests[0].method == "GET" and requests[0].url.path == "/v3/groups"


@pytest.mark.asyncio
async def test_request_id_and_scheduling(monkeypatch):
    fixture = EXAMPLES["send_message"]
    requests = transport(monkeypatch, httpx.Response(200, content=fixture["responses"][1]["body"]))
    await node({**fixture["config"], "request_id": "abc123", "scheduledDate": "20230302T173000-0500"}).execute({})
    assert requests[0].headers["X-Request-Id"] == "abc123"
    body = json.loads(requests[0].content)
    assert body["scheduledDate"] == "20230302T173000-0500" and "request_id" not in body


@pytest.mark.parametrize("config", [
    {"operation": "create_subscriber"},
    {"operation": "update_subscriber", "idOrNumber": "100"},
    {"operation": "update_group", "groupId": 123},
    {"operation": "send_message", "message": "hello"},
    {"operation": "send_message", "message": "hello", "allSubscribers": True, "subscribers": [123]},
    {"operation": "get_subscriber", "idOrNumber": "../groups"},
    {"operation": "list_groups", "url": "https://example.com"},
])
def test_invalid_configs(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


@pytest.mark.asyncio
async def test_invalid_list_does_not_prove_connection(monkeypatch):
    body = json.loads(EXAMPLES["list_groups"]["responses"][0]["body"])
    body["data"]["rows"] = "invalid"
    transport(monkeypatch, httpx.Response(200, json=body))
    with pytest.raises(ValueError, match="list envelope"):
        await node({"operation": "list_groups"}).execute({})


@pytest.mark.asyncio
async def test_rejected_key_is_redacted(monkeypatch):
    body = json.loads(EXAMPLES["send_message"]["responses"][2]["body"])
    body["message"] = "Unauthorized: " + TOKEN
    transport(monkeypatch, httpx.Response(401, json=body))
    result = await node({"operation": "list_groups"}).execute({})
    assert result["status"] == "error" and result["http_status"] == 401
    assert TOKEN not in str(result) and "Unauthorized" in result["error"]["message"]


def test_credential_default_and_cleaning():
    credential = native.MobileTextAlertsAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.credential_type == native.CREDENTIAL_TYPE and credential.api_key == TOKEN
    with pytest.raises(ValidationError):
        native.MobileTextAlertsAPIKeyCredential(api_key="Bearer " + TOKEN)
