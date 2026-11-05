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
import time

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from unittest.mock import AsyncMock, Mock, patch

from nodes.core.connection_evidence import collect_evidence
from nodes.exa_node import (
    MONITOR_RESULTS_EVENT,
    monitor_period,
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
from utils.webhook_routes import _apply_trigger_node_hooks


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
    async def test_a_news_search_is_exas_auto_search_in_its_news_category(self, api_key_credentials):
        """A model asked how the market did sends "news" as the search type whatever the schema says, which Exa
        refuses ("expected one of neural, keyword, auto, ..."): the node sends it as Exa's news search, keeping a
        category the call names, and an agent's tool says it takes news."""
        from nodes.agent.node_op_tools import build_node_op_tools

        sent = []
        mock_client = create_mock_client(200, {"results": []})

        async def request(method, url, **kwargs):
            sent.append(kwargs["json"])
            return create_mock_response(200, {"results": []})

        mock_client.request = request
        for category in (None, "financial report"):
            config = ExaNodeConfig(config=ExaSearchConfig(query="US stock market today", search_type="news",
                                                          category=category), credentials=api_key_credentials)
            with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
                assert (await create_exa_node(config).execute({}))["status"] == "success"
        assert [(b["type"], b["category"]) for b in sent] == [("auto", "news"), ("auto", "financial report")]
        # Any other type goes to Exa as it is.
        config = ExaNodeConfig(config=ExaSearchConfig(query="ai agents", search_type="keyword"),
                               credentials=api_key_credentials)
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            await create_exa_node(config).execute({})
        assert (sent[-1]["type"], sent[-1].get("category")) == ("keyword", None)
        params, _ = build_node_op_tools("automation-exa", ["search"], node_id="web", slug="exa")
        [search] = [p["function"] for p in params if p["function"]["name"] == "exa__search"]
        assert "news" in search["parameters"]["properties"]["search_type"]["enum"]

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
        mock_client = create_mock_client(200, {"triggered": True})
        mock_client.request = AsyncMock(return_value=create_mock_response(200, {"triggered": True}))
        with patch("nodes.exa_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "trigger_monitor"
        # /runs only lists a monitor's runs; a POST there answers 404.
        request = mock_client.request.call_args.kwargs
        assert (request["method"], request["url"]) == ("POST", "https://api.exa.ai/monitors/mon_1/trigger")

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
        # A monitor with no trigger only ever runs by hand; with no events named, Exa also posts its lifecycle.
        assert mock_req.call_args.kwargs["json_body"] == {
            "search": {"query": "ai news"},
            "trigger": {"type": "interval", "period": "1d"},
            "webhook": {"url": "https://abc.hooks.example.test", "events": ["monitor.run.completed"]},
        }

    @pytest.mark.asyncio
    async def test_a_monitor_runs_at_the_cadence_it_was_given(self):
        with patch(
            "nodes.exa_node._exa_request",
            return_value={"status": "success", "data": {"id": "mon_99", "webhookSecret": "s"}},
        ) as mock_req:
            await ExaNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_key": "exa_test"},
                config={"monitor_query": "ai news", "cadence": "6h"},
                node_id="node-1",
            )
        assert mock_req.call_args.kwargs["json_body"]["trigger"] == {"type": "interval", "period": "6h"}

    @pytest.mark.asyncio
    async def test_a_cadence_exa_cant_run_refuses_the_registration(self):
        with patch("nodes.exa_node._exa_request") as mock_req, pytest.raises(ValueError, match="fixed interval"):
            await ExaNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_key": "exa_test"},
                config={"monitor_query": "ai news", "cadence": "0 9 * * 1-5"},
                node_id="node-1",
            )
        assert not mock_req.called

    @pytest.mark.parametrize("cadence, period", [
        ("1h", "1h"), ("6h", "6h"), ("1d", "1d"), ("7d", "7d"), (None, "1d"), ("", "1d"),
        # Cron expressions saved before the field asked for an interval, the old default among them.
        ("0 9 * * *", "1d"), ("15 * * * *", "1h"), ("0 */6 * * *", "6h"), ("30 8 * * 1", "7d"),
    ])
    def test_monitor_period(self, cadence, period):
        assert monitor_period(cadence) == period

    @pytest.mark.parametrize("cadence", [
        "0 9 * * 1-5",  # weekdays: an interval would run it at weekends too
        "0 9 1 * *",  # months differ in length
        "0 */5 * * *",  # its last gap of a day is shorter
        "*/30 * * * *",  # under Exa's hour
        "30m", "0h", "1w", "1d12h", "every day",
    ])
    def test_a_cadence_exa_cant_run_is_refused_by_name(self, cadence):
        with pytest.raises(ValueError, match="fixed interval"):
            monitor_period(cadence)
        # Where the builder, MCP and the canvas's writes meet it.
        with pytest.raises(ValidationError, match="fixed interval"):
            ExaMonitorTriggerConfig(monitor_query="q", cadence=cadence)

    def test_a_changed_cadence_registers_again(self):
        fields = ExaNode.registration_fingerprint_fields
        assert fields({"monitor_query": "q", "cadence": "1d"}) != fields({"monitor_query": "q", "cadence": "6h"})

    @pytest.mark.parametrize("event, fires", [
        (MONITOR_RESULTS_EVENT, True),
        ("monitor.created", False), ("monitor.updated", False), ("monitor.deleted", False),
        ("monitor.run.created", False),
    ])
    def test_only_a_finished_run_fires_the_trigger(self, event, fires):
        # Monitors registered before this asked for every event, and one torn down still says it was deleted.
        assert ExaNode.filter_trigger_payload({"type": event, "data": {}}, {}) is fires

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

    @staticmethod
    def _signed(secret: str, body: bytes, *, at: float = None, sign: bytes = None) -> dict:
        """The header Exa sends: ``t=<unix>,v1=<hmac of "<t>.<body>">``."""
        t = str(int(time.time() if at is None else at))
        v1 = hmac.new(secret.encode(), t.encode() + b"." + (body if sign is None else sign), hashlib.sha256).hexdigest()
        return {"exa-signature": f"t={t},v1={v1}"}

    def test_verify_webhook_signature(self):
        secret = "topsecret"
        body = b'{"type":"monitor.run.completed"}'
        config = {"signing_secret": secret}
        assert ExaNode.verify_webhook_signature(body, self._signed(secret, body), config)
        # Signed by someone else, or over another body.
        assert not ExaNode.verify_webhook_signature(body, self._signed("another", body), config)
        assert not ExaNode.verify_webhook_signature(body, self._signed(secret, body, sign=b"{}"), config)
        # The HMAC of the body alone was never what Exa signs.
        bare = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert not ExaNode.verify_webhook_signature(body, {"exa-signature": bare}, config)
        assert not ExaNode.verify_webhook_signature(body, {"exa-signature": f"t={int(time.time())},v1={bare}"}, config)
        assert not ExaNode.verify_webhook_signature(body, {}, config)

    def test_a_signature_older_or_newer_than_five_minutes_is_refused(self):
        secret, body = "topsecret", b"{}"
        config = {"signing_secret": secret}
        now = time.time()
        assert ExaNode.verify_webhook_signature(body, self._signed(secret, body, at=now - 280), config)
        assert not ExaNode.verify_webhook_signature(body, self._signed(secret, body, at=now - 320), config)
        assert not ExaNode.verify_webhook_signature(body, self._signed(secret, body, at=now + 320), config)

    @pytest.mark.parametrize("header", ["", "t=,v1=", "v1=abc", "t=123", "t=soon,v1=abc", "abc",
                                        "t=" + "9" * 400 + ",v1=abc", "t=" + "9" * 5000 + ",v1=abc"])
    def test_a_malformed_signature_is_refused_never_raised(self, header):
        assert not ExaNode.verify_webhook_signature(b"{}", {"exa-signature": header}, {"signing_secret": "s"})

    def test_a_signature_that_isnt_ascii_is_refused_never_raised(self):
        header = f"t={int(time.time())},v1=caf\u00e9"
        assert not ExaNode.verify_webhook_signature(b"{}", {"exa-signature": header}, {"signing_secret": "s"})

    @pytest.mark.asyncio
    async def test_no_secret_in_the_config_is_judged_by_the_rows_never_waved_through(self):
        """The config's secret lags the row's until the autosave lands: unsigned mail mustn't pass meanwhile."""
        secret, body = "row-secret", b'{"type":"monitor.run.completed"}'
        node = {"id": "n1", "type": "automation-exa", "config": {"operation": "on_monitor_results"}}
        signed = self._signed(secret, body)["exa-signature"]
        assert await _apply_trigger_node_hooks(node, body, {"Exa-Signature": signed}, webhook_secret=secret) is None
        for headers, row_secret in (({}, secret), (self._signed("another", body), secret), ({}, None)):
            with pytest.raises(HTTPException) as refused:
                await _apply_trigger_node_hooks(node, body, headers, webhook_secret=row_secret)
            assert refused.value.status_code == 401


class TestExaConnectionEvidence:
    """A key with no Websets access is still a good key: the probe mustn't need more than the key."""

    @staticmethod
    def _exa(monitors: httpx.Response):
        def answer(request: httpx.Request) -> httpx.Response:
            if request.url.path.startswith("/websets"):
                return httpx.Response(401, json={"error": "Unauthorized"})
            assert (request.method, request.url.path) == ("GET", "/monitors")
            return monitors

        transport = httpx.MockTransport(answer)
        real = httpx.AsyncClient
        return patch("nodes.exa_node.httpx.AsyncClient", lambda **kw: real(transport=transport, **kw))

    async def _probe(self, monitors: httpx.Response):
        with self._exa(monitors):
            return await collect_evidence(
                node_type="automation-exa", credential_data={"api_key": "exa-key"}, user_id="user-1"
            )

    @pytest.mark.asyncio
    async def test_a_key_without_websets_connects(self):
        result = await self._probe(httpx.Response(200, json={"data": [], "hasMore": False, "nextCursor": None}))
        assert (result.reachable, result.error, result.samples) == (True, None, [])

    @pytest.mark.asyncio
    async def test_the_teams_own_monitors_are_the_proof(self):
        result = await self._probe(httpx.Response(200, json={"data": [
            {"id": "mon_1", "name": "Competitor launches"}, {"id": "mon_2", "name": None},
        ], "hasMore": False, "nextCursor": None}))
        assert result.reachable is True and result.noun == "monitors"
        assert [s.label for s in result.samples] == ["Competitor launches", "mon_2"]

    @pytest.mark.asyncio
    async def test_a_key_exa_refuses_is_still_refused(self):
        result = await self._probe(httpx.Response(401, json={"error": "Unauthorized"}))
        assert result.reachable is False and "Unauthorized" in result.error


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
