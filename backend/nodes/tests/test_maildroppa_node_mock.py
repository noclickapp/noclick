"""Maildroppa transport tests; no provider account or network is used."""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import maildroppa_node as m

KEY = {"credential_type": "maildroppa_api_key", "api_key": "test-api-key-123"}
@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

ID = "c851b8a5-a7a4-42be-a2d4-710db3cdd981"

async def run(monkeypatch, config, body=None, status=200):
    client = AsyncMock()
    client.request.return_value = httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    @asynccontextmanager
    async def guarded(**kwargs):
        assert kwargs["follow_redirects"] is False
        yield client
    monkeypatch.setattr(m, "guarded_async_client", guarded)
    node = m.MaildroppaNode(node_id="test", node_type="automation-maildroppa", node_data={}, config=m.MaildroppaFullConfig.model_validate({"config": config, "credentials": KEY}))
    return await node.execute({}), client.request.call_args

@pytest.mark.asyncio
async def test_page_and_header(monkeypatch):
    result, call = await run(monkeypatch, {"operation": "list_subscribers", "pageNumber": 2, "pageSize": 10}, {"subscribers": [], "total": 10})
    assert call.args == ("GET", "https://api.maildroppa.com/subscribers")
    assert call.kwargs["params"] == {"pageNumber": 2, "pageSize": 10}
    assert call.kwargs["headers"]["X-API-Key"] == KEY["api_key"]
    assert result["data"]["total"] == 10

@pytest.mark.asyncio
async def test_clear_first_name(monkeypatch):
    result, call = await run(monkeypatch, {"operation": "update_subscriber_first_name", "subscriberId": ID, "firstName": None}, status=204)
    assert call.kwargs["json"] == {"firstName": None}
    assert result["status"] == "success"

@pytest.mark.asyncio
async def test_replace_topics_empty(monkeypatch):
    _, call = await run(monkeypatch, {"operation": "replace_subscriber_topics", "subscriberId": ID, "topicIds": []}, status=204)
    assert call.kwargs["json"] == {"topicIds": [], "overrideOptOuts": False}

@pytest.mark.asyncio
async def test_rejection_redacts_key(monkeypatch):
    result, _ = await run(monkeypatch, {"operation": "list_tags"}, {"message": KEY["api_key"]}, status=401)
    assert result["status"] == "error"
    assert KEY["api_key"] not in result["message"]

def test_manual_credential_and_invalid_id():
    assert m.MaildroppaAPIKeyCredential(api_key="test-api-key-123").credential_type == "maildroppa_api_key"
    with pytest.raises(ValueError):
        m.GetSubscriberConfig(subscriberId="../secrets")
