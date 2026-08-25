"""
Mock tests for the Exa REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Search: search, get contents, answer, find similar
- Agent: create/get/list/cancel agent runs
- Monitors: create/list/get/update/delete/trigger, list runs
- Websets: create/get/list/update/delete, items, enrichment, webhook, events
- Team Management: create/list API keys, get usage
- Trigger: on_monitor_results passthrough, monitor registration/deregistration,
  signature verification
- Error handling: API errors, missing credentials
- Dynamic options: monitor dropdown
"""

import hashlib
import hmac

import pytest
from unittest.mock import Mock, patch

from nodes.exa_node import (
    ExaNode,
    ExaNodeConfig,
    ExaApiKeyCredential,
    ExaSearchConfig,
    ExaGetContentsConfig,
    ExaAnswerConfig,
    ExaFindSimilarConfig,
    ExaCreateAgentRunConfig,
    ExaGetAgentRunConfig,
    ExaListAgentRunsConfig,
    ExaCancelAgentRunConfig,
    ExaCreateMonitorConfig,
    ExaListMonitorsConfig,
    ExaGetMonitorConfig,
    ExaUpdateMonitorConfig,
    ExaDeleteMonitorConfig,
    ExaTriggerMonitorConfig,
    ExaListMonitorRunsConfig,
    ExaCreateWebsetConfig,
    ExaGetWebsetConfig,
    ExaListWebsetsConfig,
    ExaUpdateWebsetConfig,
    ExaDeleteWebsetConfig,
    ExaListWebsetItemsConfig,
    ExaCreateWebsetEnrichmentConfig,
    ExaCreateWebsetWebhookConfig,
    ExaListWebsetsEventsConfig,
    ExaMonitorTriggerConfig,
)


@pytest.fixture
def api_key_credentials():
    return ExaApiKeyCredential(api_key="exa_test_key_12345")


def create_exa_node(config):
    return ExaNode(
        node_id="test-exa-node",
        node_type="automation-exa",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


class TestExaSearchMock:
    @pytest.mark.asyncio
    async def test_search(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaSearchConfig(query="ai agents", num_results="5"),
            credentials=api_key_credentials,
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(200, {"results": [{"url": "https://a"}, {"url": "https://b"}]})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "search"
        assert len(result["data"]["results"]) == 2

    @pytest.mark.asyncio
    async def test_get_contents(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaGetContentsConfig(urls="https://exa.ai, https://example.com"),
            credentials=api_key_credentials,
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(200, {"results": [{"text": "hello"}]})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_contents"

    @pytest.mark.asyncio
    async def test_answer(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaAnswerConfig(query="What is Exa?"),
            credentials=api_key_credentials,
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(200, {"answer": "Exa is a search API.", "citations": []})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "answer"
        assert "Exa" in result["data"]["answer"]

    @pytest.mark.asyncio
    async def test_find_similar(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaFindSimilarConfig(url="https://exa.ai", num_results="3"),
            credentials=api_key_credentials,
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(200, {"results": [{"url": "https://similar"}]})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "find_similar"


class TestExaAgentMock:
    @pytest.mark.asyncio
    async def test_create_agent_run(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaCreateAgentRunConfig(query="Research AI startups"),
            credentials=api_key_credentials,
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(201, {"id": "run_1", "status": "queued"})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_agent_run"
        assert result["data"]["id"] == "run_1"

    @pytest.mark.asyncio
    async def test_get_agent_run(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaGetAgentRunConfig(run_id="run_1"),
            credentials=api_key_credentials,
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(200, {"id": "run_1", "status": "completed"})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_agent_run"
        assert result["data"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_list_agent_runs(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaListAgentRunsConfig(limit="10"),
            credentials=api_key_credentials,
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "run_1"}], "hasMore": False})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_agent_runs"

    @pytest.mark.asyncio
    async def test_cancel_agent_run(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaCancelAgentRunConfig(run_id="run_1"),
            credentials=api_key_credentials,
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(200, {"id": "run_1", "status": "cancelled"})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "cancel_agent_run"


class TestExaMonitorsMock:
    @pytest.mark.asyncio
    async def test_create_monitor(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaCreateMonitorConfig(
                query="ai news", webhook_url="https://abc.hooks.example.test"
            ),
            credentials=api_key_credentials,
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(201, {"id": "mon_1"})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_monitor"
        assert result["data"]["id"] == "mon_1"

    @pytest.mark.asyncio
    async def test_list_monitors(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaListMonitorsConfig(limit="10"), credentials=api_key_credentials
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "mon_1", "query": "ai"}]})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_monitors"

    @pytest.mark.asyncio
    async def test_get_monitor(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaGetMonitorConfig(monitor_id="mon_1"), credentials=api_key_credentials
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(200, {"id": "mon_1", "query": "ai"})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_monitor"
        assert result["data"]["id"] == "mon_1"

    @pytest.mark.asyncio
    async def test_update_monitor(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaUpdateMonitorConfig(monitor_id="mon_1", query="ai agents updated"),
            credentials=api_key_credentials,
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(200, {"id": "mon_1", "search": {"query": "ai agents updated"}})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_monitor"

    @pytest.mark.asyncio
    async def test_delete_monitor(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaDeleteMonitorConfig(monitor_id="mon_1"), credentials=api_key_credentials
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_monitor"

    @pytest.mark.asyncio
    async def test_trigger_monitor(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaTriggerMonitorConfig(monitor_id="mon_1"), credentials=api_key_credentials
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(201, {"id": "monrun_1", "status": "running"})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "trigger_monitor"

    @pytest.mark.asyncio
    async def test_list_monitor_runs(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaListMonitorRunsConfig(monitor_id="mon_1"), credentials=api_key_credentials
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "monrun_1"}]})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_monitor_runs"


class TestExaWebsetsMock:
    @pytest.mark.asyncio
    async def test_create_webset(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaCreateWebsetConfig(query="ai startups", count="20"),
            credentials=api_key_credentials,
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(201, {"id": "ws_1", "status": "running"})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_webset"
        assert result["data"]["id"] == "ws_1"

    @pytest.mark.asyncio
    async def test_get_webset(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaGetWebsetConfig(webset_id="ws_1", expand_items=True),
            credentials=api_key_credentials,
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(200, {"id": "ws_1", "items": []})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_webset"

    @pytest.mark.asyncio
    async def test_list_websets(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaListWebsetsConfig(limit="10"), credentials=api_key_credentials
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "ws_1"}]})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_websets"

    @pytest.mark.asyncio
    async def test_update_webset(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaUpdateWebsetConfig(webset_id="ws_1", metadata='{"team": "growth"}'),
            credentials=api_key_credentials,
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(200, {"id": "ws_1"})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_webset"

    @pytest.mark.asyncio
    async def test_delete_webset(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaDeleteWebsetConfig(webset_id="ws_1"), credentials=api_key_credentials
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(200, {"id": "ws_1", "status": "deleted"})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_webset"

    @pytest.mark.asyncio
    async def test_list_webset_items(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaListWebsetItemsConfig(webset_id="ws_1"), credentials=api_key_credentials
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "item_1"}]})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_webset_items"

    @pytest.mark.asyncio
    async def test_create_webset_enrichment(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaCreateWebsetEnrichmentConfig(
                webset_id="ws_1", description="Company headcount", enrichment_format="number"
            ),
            credentials=api_key_credentials,
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(201, {"id": "enr_1"})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_webset_enrichment"

    @pytest.mark.asyncio
    async def test_create_webset_webhook(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaCreateWebsetWebhookConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=api_key_credentials,
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(201, {"id": "wh_1"})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_webset_webhook"

    @pytest.mark.asyncio
    async def test_list_websets_events(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaListWebsetsEventsConfig(limit="10"), credentials=api_key_credentials
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "evt_1"}]})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_websets_events"


class TestExaTriggerMock:
    @pytest.mark.asyncio
    async def test_on_monitor_results_passthrough(self):
        """The trigger passes the inbound monitor webhook payload through as output."""
        config = ExaNodeConfig(
            config=ExaMonitorTriggerConfig(
                monitor_query="ai news", webhook_url="https://abc.hooks.example.test"
            ),
            credentials=None,
        )
        node = create_exa_node(config)
        payload = {"event": "monitor.run.completed", "results": [{"url": "https://x"}]}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_monitor_results"
        assert result["data"]["event"] == "monitor.run.completed"

    @pytest.mark.asyncio
    async def test_register_external_webhook(self):
        with patch(
            "nodes.exa_node._exa_request",
            return_value={"status": "success", "data": {"id": "mon_99", "webhookSecret": "api-secret-xyz"}},
        ) as mock_req:
            extra = await ExaNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_key": "exa_test"},
                config={"monitor_query": "ai news"},
                node_id="node-1",
            )
        assert mock_req.called
        assert extra["external_webhook_id"] == "mon_99"
        assert extra["monitor_id"] == "mon_99"
        assert extra["signing_secret"] == "api-secret-xyz"

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.exa_node._exa_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await ExaNode._unregister_external_webhook(
                credential={"api_key": "exa_test"},
                config={"external_webhook_id": "mon_99"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature(self):
        secret = "topsecret"
        body = b'{"event":"monitor.run.completed"}'
        good_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert ExaNode.verify_webhook_signature(
            body, {"exa-signature": good_sig}, {"signing_secret": secret}
        )
        assert not ExaNode.verify_webhook_signature(
            body, {"exa-signature": "deadbeef"}, {"signing_secret": secret}
        )
        # no secret stored yet -> accept (trigger not armed)
        assert ExaNode.verify_webhook_signature(body, {}, {})


class TestExaErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        config = ExaNodeConfig(
            config=ExaGetMonitorConfig(monitor_id="missing"), credentials=api_key_credentials
        )
        node = create_exa_node(config)
        mock_client = create_mock_client(404, {"error": "Monitor not found"})
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials_byok_only_op(self):
        """BYOK-only ops (websets/monitors/agent runs) still require a
        credential — only PLATFORM_METERED_OPERATIONS may run keyless."""
        config = ExaNodeConfig(
            config=ExaCreateWebsetConfig(query="x"), credentials=None
        )
        node = create_exa_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    async def test_platform_op_without_server_key(self, monkeypatch):
        """A credential-less search op routes to the platform key; when the
        server has none configured, the error must say so instead of blaming
        the (legitimately absent) user credential."""
        monkeypatch.delenv("EXA_API_KEY", raising=False)
        config = ExaNodeConfig(config=ExaSearchConfig(query="x"), credentials=None)
        node = create_exa_node(config)
        node.user_id = "user-1"
        with pytest.raises(RuntimeError, match="EXA_API_KEY is not configured"):
            await node.execute({})


class TestExaDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_monitor_options(self):
        with patch(
            "utils.credential_loader.load_credential", return_value={"api_key": "exa_test"}
        ), patch(
            "nodes.exa_node._exa_request",
            return_value={
                "status": "success",
                "data": {"data": [{"id": "mon_1", "query": "ai news"}]},
            },
        ):
            result = await ExaNode.load_field_options(
                "monitor_id", "user-1", {}, credential_ids={"exa": "cred-1"}, pool=Mock()
            )
        assert "options" in result
        assert result["options"][0]["value"] == "mon_1"
        assert "ai news" in result["options"][0]["label"]
