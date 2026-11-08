"""Hookdeck Admin API request contracts and response handling."""

import json
from unittest.mock import patch

import httpx
import pytest

from nodes.hookdeck_node import (
    API_BASE,
    HookdeckNode,
    HookdeckNodeConfig,
    HookdeckApiKeyCredential,
    _request_spec,
    CreateSource,
    CreateDestination,
    CreateConnection,
    UpdateSource,
    ListSources,
    GetSource,
    DeleteSource,
    PauseConnection,
    UnpauseConnection,
    RetryEvent,
    CancelEvent,
    ListEvents,
)


def test_mutation_contracts_and_path_escaping():
    assert _request_spec(CreateSource(name="from_checkout", description="Inbound")) == (
        "POST", "/sources", None, {"name": "from_checkout", "description": "Inbound"}
    )
    assert _request_spec(CreateDestination(name="test_sink", destination_type="HTTP", url="https://example.com/webhook")) == (
        "POST", "/destinations", None,
        {"name": "test_sink", "type": "HTTP", "config": {"url": "https://example.com/webhook"}},
    )
    assert _request_spec(CreateConnection(source_id="src_1", destination_id="des_1")) == (
        "POST", "/connections", None, {"source_id": "src_1", "destination_id": "des_1"}
    )
    assert _request_spec(UpdateSource(id="src_1", description="Changed")) == (
        "PUT", "/sources/src_1", None, {"description": "Changed"}
    )
    assert _request_spec(DeleteSource(id="src/1")) == ("DELETE", "/sources/src%2F1", None, None)
    assert _request_spec(PauseConnection(id="con_1")) == ("PUT", "/connections/con_1/pause", None, None)
    assert _request_spec(UnpauseConnection(id="con_1")) == ("PUT", "/connections/con_1/unpause", None, None)
    assert _request_spec(RetryEvent(id="evt_1")) == ("POST", "/events/evt_1/retry", None, None)
    assert _request_spec(CancelEvent(id="evt_1")) == ("PUT", "/events/evt_1/cancel", None, None)


def test_http_destination_requires_url_and_updates_need_fields():
    with pytest.raises(ValueError, match="require a URL"):
        _request_spec(CreateDestination(name="missing_url"))
    with pytest.raises(ValueError, match="at least one field"):
        _request_spec(UpdateSource(id="src_1"))


@pytest.mark.asyncio
async def test_node_sends_bearer_and_returns_table_friendly_list():
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={
            "pagination": {"next": "page_2", "limit": 2}, "count": 1,
            "models": [{"id": "src_1", "name": "checkout"}],
        })

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def make_client(*args, **kwargs):
        return real_client(*args, transport=transport, **kwargs)

    node = HookdeckNode(
        node_id="hookdeck-test", node_type="automation-hookdeck", node_data={},
        config=HookdeckNodeConfig(
            config=ListSources(limit=2),
            credentials=HookdeckApiKeyCredential(api_key="hd_secret"),
        ),
        sio=None, sid=None, workflow_id=None, user_id=None, conversation_id=None,
    )
    with patch("nodes.hookdeck_node.httpx.AsyncClient", side_effect=make_client):
        result = await node.execute({})
    assert captured[0].method == "GET"
    assert str(captured[0].url) == API_BASE + "/sources?limit=2"
    assert captured[0].headers["Authorization"] == "Bearer hd_secret"
    assert result["data"]["items"] == [{"id": "src_1", "name": "checkout"}]
    assert result["data"]["pagination"]["next"] == "page_2"
    assert "hd_secret" not in json.dumps(result)


@pytest.mark.asyncio
async def test_api_error_keeps_status_without_exposing_credential():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Source not found"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    node = HookdeckNode(
        node_id="hookdeck-test", node_type="automation-hookdeck", node_data={},
        config=HookdeckNodeConfig(config=GetSource(id="missing"),
                                  credentials=HookdeckApiKeyCredential(api_key="hd_secret")),
        sio=None, sid=None, workflow_id=None, user_id=None, conversation_id=None,
    )
    with patch("nodes.hookdeck_node.httpx.AsyncClient", side_effect=lambda *a, **kw: real_client(*a, transport=transport, **kw)):
        result = await node.execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 404
    assert result["error"] == "Source not found"
    assert "hd_secret" not in json.dumps(result)


def test_event_filters_become_query_params():
    method, path, params, body = _request_spec(ListEvents(limit=10, source_id="src_1", status="FAILED"))
    assert (method, path, body) == ("GET", "/events", None)
    assert params == {"limit": 10, "source_id": "src_1", "status": "FAILED"}
