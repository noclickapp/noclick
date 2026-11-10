import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.microsoft_graph_security_node import OPERATIONS, MicrosoftGraphSecurityNode

FIXTURES = Path(__file__).parent / "fixtures/microsoft-graph-security"

def node(operation, **config):
    return NodeFactory.create_node(node_id="security-test", node_type="automation-microsoft-graph-security", node_data={"config": {"operation": operation, **config}, "credentials": {"credential_type": "microsoft_oauth", "access_token": "test-token"}})

@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(OPERATIONS))
async def test_operation_request(monkeypatch, operation):
    method, path, _ = OPERATIONS[operation]
    config = {}
    for part in path.split("/"):
        if part.startswith("{"): config[part[1:-1]] = "record/id"
    if method == "PATCH": config.update(status="resolved", assigned_to="analyst@example.com")
    n = node(operation, **config)
    monkeypatch.setattr(MicrosoftGraphSecurityNode, "_token", AsyncMock(return_value="test-token"))
    async def request(token, verb, url, **kwargs):
        assert token == "test-token"
        assert verb == method
        assert url == "https://graph.microsoft.com/v1.0/security" + path.format(**{k:"record%2Fid" for k in config if k.endswith("_id")})
        if method == "PATCH": assert kwargs["json"] == {"status":"resolved", "assignedTo":"analyst@example.com", "@odata.type":"#microsoft.graph.security." + ("alert" if operation == "update_alert" else "incident")}
        return {"value": []} if operation.startswith(("list_", "on_")) else {"id": "record/id"}
    monkeypatch.setattr(n, "_request", request)
    assert (await n.execute({}))["status"] == "success"

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["alerts", "incidents"])
async def test_documented_poll_payload(monkeypatch, kind):
    body = json.loads((FIXTURES / (kind + ".json")).read_text())
    op = "on_updated_alert" if kind == "alerts" else "on_updated_incident"
    n = node(op)
    monkeypatch.setattr(MicrosoftGraphSecurityNode, "_token", AsyncMock(return_value="test-token"))
    monkeypatch.setattr(n, "_request", AsyncMock(return_value=body))
    keys = []
    async def unseen(items, key):
        keys.extend(key(item) for item in items)
        return items
    monkeypatch.setattr(n, "_filter_unseen", unseen)
    output = await n.execute({})
    assert keys and all(":" in k for k in keys)
    assert n.resolve_agent_event(output)["text"].startswith("Microsoft Graph Security")
    assert n.should_propagate_output(output, {"operation":op})
    assert not n.should_propagate_output({"items":[]}, {"operation":op})

def test_continuation_rejects_other_origins():
    for url in ["https://evil.example/v1.0/security/incidents", "https://graph.microsoft.com/v1.0/me", "https://user@graph.microsoft.com/v1.0/security/incidents"]:
        with pytest.raises(ValueError): MicrosoftGraphSecurityNode._continuation(url, "/incidents")

@pytest.mark.asyncio
async def test_http_error_preserves_provider_rejection(monkeypatch):
    n = node("list_alerts")
    real = httpx.AsyncClient
    def client(**kwargs):
        return real(transport=httpx.MockTransport(lambda req: httpx.Response(403, json={"error":{"message":"Insufficient privileges"}})))
    monkeypatch.setattr("nodes.microsoft_graph_security_node.httpx.AsyncClient", client)
    with pytest.raises(ValueError, match="Insufficient privileges"):
        await n._request("token", "GET", "https://graph.microsoft.com/v1.0/security/alerts_v2")

@pytest.mark.asyncio
async def test_poll_drains_pages_before_baseline(monkeypatch):
    n = node("on_updated_incident")
    monkeypatch.setattr(MicrosoftGraphSecurityNode, "_token", AsyncMock(return_value="test-token"))
    request = AsyncMock(side_effect=[
        {"value":[{"id":"one","lastUpdateDateTime":"2026-01-01T00:00:00Z"}], "@odata.nextLink":"https://graph.microsoft.com/v1.0/security/incidents?$skip=1"},
        {"value":[{"id":"two","lastUpdateDateTime":"2026-01-02T00:00:00Z"}]},
    ])
    monkeypatch.setattr(n, "_request", request)
    async def unseen(items, key):
        assert request.await_count == 2
        assert [key(i) for i in items] == ["one:2026-01-01T00:00:00Z", "two:2026-01-02T00:00:00Z"]
        return items
    monkeypatch.setattr(n, "_filter_unseen", unseen)
    assert (await n.execute({}))["count"] == 2

@pytest.mark.asyncio
async def test_failed_page_does_not_advance_baseline(monkeypatch):
    n = node("on_updated_incident")
    monkeypatch.setattr(MicrosoftGraphSecurityNode, "_token", AsyncMock(return_value="test-token"))
    monkeypatch.setattr(n, "_request", AsyncMock(return_value={"value":[], "@odata.nextLink":"https://evil.example/incidents"}))
    unseen = AsyncMock()
    monkeypatch.setattr(n, "_filter_unseen", unseen)
    with pytest.raises(ValueError): await n.execute({})
    unseen.assert_not_awaited()
