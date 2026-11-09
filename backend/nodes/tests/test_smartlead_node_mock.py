"""Native factory and HTTP regressions against Smartlead's published examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import smartlead_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "synthetic-smartlead-account-key"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/smartlead/responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def make_node(config, **credentials):
    return NodeFactory.create_node(node_id="smartlead-test", node_type="automation-smartlead",
        node_data={"config": config, "credentials": {"credential_type": "smartlead_api_key", "api_key": TOKEN, **credentials}})


def mock_http(monkeypatch, body, status=200, *, headers=None):
    requests = []
    def send(request):
        requests.append(request)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, **({"content": body} if isinstance(body, bytes) else {"json": body}), headers=headers)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        assert kwargs["timeout"] == 30
        return httpx.AsyncClient(transport=httpx.MockTransport(send), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(FIXTURES))
async def test_smartlead_exact_provider_route_query_json_and_documented_response(monkeypatch, operation):
    fixture = FIXTURES[operation]
    requests = mock_http(monkeypatch, fixture["response"])
    result = await make_node(fixture["config"]).execute({})
    assert result["status"] == "success", result
    assert result["data"] == fixture["response"]
    assert TOKEN not in str(result)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture["method"]
    assert request.url.host == "server.smartlead.ai" and request.url.scheme == "https"
    assert request.url.path == "/api" + fixture["path"].replace("{id}", str(fixture["config"].get("id")))
    query = dict(request.url.params)
    assert query.pop("api_key") == TOKEN
    config = {k: v for k, v in fixture["config"].items() if k not in {"operation", "id"}}
    if request.method == "GET":
        assert not request.content
        assert query == {k: str(v) for k, v in config.items()}
    else:
        if operation == "list_inbox_replies":
            assert query == {"fetch_message_history": "true"}
            config.pop("fetch_message_history")
        else:
            assert query == {}
        assert json.loads(request.content) == config


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,key", [("list_campaigns", "campaign_list"), ("list_clients", "client_list")])
async def test_smartlead_lists_support_current_provider_docs_and_empty_accounts(monkeypatch, operation, key):
    for rows in [[{"id":12345,"name":"Q1 Cold Outreach"}], []]:
        mock_http(monkeypatch, {"ok": True, "data": {key: rows}})
        result = await make_node({"operation": operation}).execute({})
        assert result["status"] == "success" and result["items"] == rows


@pytest.mark.asyncio
@pytest.mark.parametrize("body,status", [({"message":"Invalid API Key"},401), ({"ok":False,"message":"Permission denied"},200), ({"success":False,"error":"Invalid request"},200), ({"error":"Rate limit exceeded"},429), (b'<html>Unavailable</html>',502), ({"data":{}},200)])
async def test_smartlead_errors_and_malformed_lists_cannot_prove_connection(monkeypatch, body, status):
    requests = mock_http(monkeypatch, body, status)
    result = await make_node({"operation":"list_campaigns"}).execute({})
    assert result["status"] == "error" and len(requests) == 1
    assert TOKEN not in str(result)
    if status == 401:
        assert result["error"] == "Invalid API Key" and result["status_code"] == 401


@pytest.mark.asyncio
async def test_smartlead_key_echo_and_transport_errors_are_redacted_without_retry(monkeypatch):
    requests = mock_http(monkeypatch, {"ok":False,"message":f"Rejected {TOKEN}","api_key":TOKEN})
    result = await make_node(FIXTURES["create_lead_note"]["config"]).execute({})
    assert result["status"] == "error" and TOKEN not in str(result) and len(requests) == 1
    requests = mock_http(monkeypatch, httpx.ConnectError(f"https://server.smartlead.ai/?api_key={TOKEN}"))
    result = await make_node(FIXTURES["create_lead_note"]["config"]).execute({})
    assert result["status"] == "error" and TOKEN not in str(result) and len(requests) == 1


def test_smartlead_hand_connect_and_discovery():
    assert NODE_REGISTRY["automation-smartlead"] is native.SmartleadNode
    credential = native.SmartleadAPIKeyCredential(api_key="  abc123-real-key  ")
    assert credential.credential_type == "smartlead_api_key" and credential.api_key == "abc123-real-key"
    assert native.SmartleadNode.connection_evidence.operation == "list_campaigns"
    for key in ["", "https://example.com/key", "<token>", "Bearer abc"]:
        with pytest.raises(ValidationError):
            native.SmartleadAPIKeyCredential(api_key=key)


@pytest.mark.parametrize("config", [
    {"operation":"list_inbox_replies","limit":21},
    {"operation":"list_inbox_replies","offset":-1},
    {"operation":"get_inbox_lead","id":"../../other"},
    {"operation":"add_email_account_tags","email_account_ids":list(range(26)),"tag_ids":[1]},
    {"operation":"update_lead_revenue","email_lead_map_id":1,"revenue":float('nan')},
    {"operation":"get_campaign_performance","start_date":"2024-02-01","end_date":"2024-01-01","timezone":"UTC"},
    {"operation":"get_daily_stats","start_date":"2024-01-01","end_date":"2024-01-31","timezone":"invalid-zone"},
])
def test_smartlead_invalid_configs_fail_before_http(config):
    result = native.SmartleadNode.validate_config({"config":config,"credentials":{"api_key":TOKEN}})
    assert result["valid"] is False
