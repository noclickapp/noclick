"""
Mock tests for the Firecrawl REST API node.

Exercises the current Firecrawl v2 surface without live API calls:
- Scrape / batch / crawl / extract / agent status flows
- Research endpoints
- Interact session endpoints and scrape-bound interaction
- Team usage/activity endpoints
- Feedback and support endpoints
- Monitor lifecycle endpoints
- Webhook trigger filtering and signature verification
"""

import hashlib
import hmac
from unittest.mock import Mock, patch

import pytest

import nodes.firecrawl_node as firecrawl


@pytest.fixture
def api_key_credentials():
    return firecrawl.FirecrawlAPIKeyCredential(api_key="fc-test-key-12345")


def create_firecrawl_node(config):
    return firecrawl.FirecrawlNode(
        node_id="test-firecrawl-node",
        node_type="automation-firecrawl",
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


def create_mock_client(status_code=200, json_data=None, responses=None):
    response_queue = list(responses) if responses is not None else [create_mock_response(status_code, json_data)]
    mock_client = Mock()
    calls = []

    async def async_request(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return response_queue.pop(0)

    async def async_get(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs, "method": "GET"})
        return response_queue.pop(0)

    mock_client.request = async_request
    mock_client.get = async_get
    mock_client.calls = calls

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


def _envelope(data):
    return {"success": True, "data": data}


async def _run(config_obj, credentials, status_code=200, json_data=None, responses=None):
    node = create_firecrawl_node(
        firecrawl.FirecrawlNodeConfig(config=config_obj, credentials=credentials)
    )
    mock_client = create_mock_client(status_code, json_data, responses=responses)
    with patch("nodes.firecrawl_node.httpx.AsyncClient", return_value=mock_client):
        result = await node.execute({})
    return result, mock_client.calls


class TestFirecrawlScraping:
    @pytest.mark.asyncio
    async def test_scrape(self, api_key_credentials):
        result, _ = await _run(
            firecrawl.FirecrawlScrapeConfig(url="https://example.com", formats="markdown"),
            api_key_credentials,
            json_data=_envelope({"markdown": "# Hello"}),
        )
        assert result["status"] == "success"
        assert result["action"] == "scrape"
        assert result["data"]["markdown"] == "# Hello"

    @pytest.mark.asyncio
    async def test_get_scrape(self, api_key_credentials):
        result, calls = await _run(
            firecrawl.FirecrawlGetScrapeConfig(job_id="scrape_1"),
            api_key_credentials,
            json_data={"status": "completed"},
        )
        assert result["action"] == "get_scrape"
        assert calls[0]["kwargs"]["url"].endswith("/scrape/scrape_1")

    @pytest.mark.asyncio
    async def test_batch_scrape_family(self, api_key_credentials):
        cases = [
            (
                firecrawl.FirecrawlBatchScrapeConfig(urls="https://a.com,https://b.com"),
                "batch_scrape",
                "/batch/scrape",
                _envelope({"id": "batch_1"}),
            ),
            (
                firecrawl.FirecrawlGetBatchScrapeConfig(job_id="batch_1"),
                "get_batch_scrape",
                "/batch/scrape/batch_1",
                {"status": "completed"},
            ),
            (
                firecrawl.FirecrawlCancelBatchScrapeConfig(job_id="batch_1"),
                "cancel_batch_scrape",
                "/batch/scrape/batch_1",
                {"status": "cancelled"},
            ),
            (
                firecrawl.FirecrawlGetBatchScrapeErrorsConfig(job_id="batch_1"),
                "get_batch_scrape_errors",
                "/batch/scrape/batch_1/errors",
                {"errors": []},
            ),
        ]
        for config, action, suffix, payload in cases:
            result, calls = await _run(config, api_key_credentials, json_data=payload)
            assert result["action"] == action
            assert calls[0]["kwargs"]["url"].endswith(suffix)

    @pytest.mark.asyncio
    async def test_batch_scrape_includes_webhook_options(self, api_key_credentials):
        result, calls = await _run(
            firecrawl.FirecrawlBatchScrapeConfig(
                urls="https://a.com",
                webhook_url="https://example.com/hook",
                webhook_events="started,page",
                webhook_headers_json='{"X-Source":"noclick"}',
                webhook_metadata_json='{"workflow":"demo"}',
            ),
            api_key_credentials,
            json_data=_envelope({"id": "batch_1"}),
        )
        assert result["action"] == "batch_scrape"
        assert calls[0]["kwargs"]["json"]["webhook"] == {
            "url": "https://example.com/hook",
            "events": ["started", "page"],
            "headers": {"X-Source": "noclick"},
            "metadata": {"workflow": "demo"},
        }


class TestFirecrawlCrawling:
    @pytest.mark.asyncio
    async def test_crawl_family(self, api_key_credentials):
        cases = [
            (
                firecrawl.FirecrawlCrawlConfig(url="https://example.com", limit="50"),
                "crawl",
                "/crawl",
                _envelope({"id": "crawl_1"}),
            ),
            (
                firecrawl.FirecrawlGetCrawlConfig(job_id="crawl_1"),
                "get_crawl",
                "/crawl/crawl_1",
                {"status": "running"},
            ),
            (
                firecrawl.FirecrawlCancelCrawlConfig(job_id="crawl_1"),
                "cancel_crawl",
                "/crawl/crawl_1",
                {"status": "cancelled"},
            ),
            (
                firecrawl.FirecrawlGetCrawlErrorsConfig(job_id="crawl_1"),
                "get_crawl_errors",
                "/crawl/crawl_1/errors",
                {"errors": []},
            ),
            (
                firecrawl.FirecrawlListActiveCrawlsConfig(),
                "list_active_crawls",
                "/crawl/active",
                {"crawls": []},
            ),
        ]
        for config, action, suffix, payload in cases:
            result, calls = await _run(config, api_key_credentials, json_data=payload)
            assert result["action"] == action
            assert calls[0]["kwargs"]["url"].endswith(suffix)

    @pytest.mark.asyncio
    async def test_crawl_includes_webhook_options(self, api_key_credentials):
        result, calls = await _run(
            firecrawl.FirecrawlCrawlConfig(
                url="https://example.com",
                webhook_url="https://example.com/hook",
                webhook_events="completed,failed",
                webhook_headers_json='{"X-Source":"noclick"}',
                webhook_metadata_json='{"workflow":"demo"}',
            ),
            api_key_credentials,
            json_data=_envelope({"id": "crawl_1"}),
        )
        assert result["action"] == "crawl"
        assert calls[0]["kwargs"]["json"]["webhook"] == {
            "url": "https://example.com/hook",
            "events": ["completed", "failed"],
            "headers": {"X-Source": "noclick"},
            "metadata": {"workflow": "demo"},
        }

    @pytest.mark.asyncio
    async def test_crawl_params_preview(self, api_key_credentials):
        result, calls = await _run(
            firecrawl.FirecrawlCrawlParamsPreviewConfig(
                url="https://example.com", prompt="all blog posts"
            ),
            api_key_credentials,
            json_data=_envelope({"includePaths": ["/blog"]}),
        )
        assert result["action"] == "crawl_params_preview"
        assert calls[0]["kwargs"]["url"].endswith("/crawl/params-preview")


class TestFirecrawlDiscoveryAndResearch:
    @pytest.mark.asyncio
    async def test_map_and_search(self, api_key_credentials):
        result, _ = await _run(
            firecrawl.FirecrawlMapConfig(url="https://example.com"),
            api_key_credentials,
            json_data=_envelope({"links": ["https://example.com/a"]}),
        )
        assert result["action"] == "map"

        result, calls = await _run(
            firecrawl.FirecrawlSearchConfig(
                query="firecrawl docs", limit="5", scrape_content="true"
            ),
            api_key_credentials,
            json_data=_envelope({"web": [{"url": "https://docs.firecrawl.dev"}]}),
        )
        assert result["action"] == "search"
        assert calls[0]["kwargs"]["json"]["scrapeOptions"] == {"formats": ["markdown"]}

    @pytest.mark.asyncio
    async def test_research_endpoints(self, api_key_credentials):
        cases = [
            (
                firecrawl.FirecrawlSearchResearchGithubConfig(query="oauth", k="3"),
                "search_research_github",
                "/search/research/github",
            ),
            (
                firecrawl.FirecrawlSearchResearchPapersConfig(
                    query="agents", k="2", authors="Smith", categories="cs.AI"
                ),
                "search_research_papers",
                "/search/research/papers",
            ),
            (
                firecrawl.FirecrawlGetResearchPaperConfig(paper_id="paper_1", query="summary", k="1"),
                "get_research_paper",
                "/search/research/papers/paper_1",
            ),
            (
                firecrawl.FirecrawlGetSimilarResearchPapersConfig(
                    paper_id="paper_1", intent="find semantically related papers", mode="similar", rerank="true"
                ),
                "get_similar_research_papers",
                "/search/research/papers/paper_1/similar",
            ),
        ]
        for config, action, suffix in cases:
            result, calls = await _run(config, api_key_credentials, json_data={"items": []})
            assert result["action"] == action
            assert calls[0]["kwargs"]["url"].endswith(suffix)


class TestFirecrawlExtraction:
    @pytest.mark.asyncio
    async def test_extract_family(self, api_key_credentials):
        result, _ = await _run(
            firecrawl.FirecrawlExtractConfig(
                urls="https://example.com", output_schema='{"type":"object"}'
            ),
            api_key_credentials,
            json_data=_envelope({"id": "extract_1"}),
        )
        assert result["action"] == "extract"

        cases = [
            (
                firecrawl.FirecrawlGetExtractConfig(job_id="extract_1"),
                "get_extract",
                "/extract/extract_1",
            ),
            (
                firecrawl.FirecrawlAgentConfig(prompt="find the founders of OpenAI"),
                "agent",
                "/agent",
            ),
            (
                firecrawl.FirecrawlGetAgentConfig(job_id="agent_1"),
                "get_agent",
                "/agent/agent_1",
            ),
            (
                firecrawl.FirecrawlCancelAgentConfig(job_id="agent_1"),
                "cancel_agent",
                "/agent/agent_1",
            ),
        ]
        for config, action, suffix in cases:
            result, calls = await _run(config, api_key_credentials, json_data={"id": "agent_1"})
            assert result["action"] == action
            assert calls[0]["kwargs"]["url"].endswith(suffix)

    @pytest.mark.asyncio
    async def test_extract_includes_webhook_options(self, api_key_credentials):
        result, calls = await _run(
            firecrawl.FirecrawlExtractConfig(
                urls="https://example.com",
                output_schema='{"type":"object"}',
                webhook_url="https://example.com/hook",
                webhook_events="completed",
                webhook_headers_json='{"X-Source":"noclick"}',
                webhook_metadata_json='{"workflow":"demo"}',
            ),
            api_key_credentials,
            json_data=_envelope({"id": "extract_1"}),
        )
        assert result["action"] == "extract"
        assert calls[0]["kwargs"]["json"]["webhook"] == {
            "url": "https://example.com/hook",
            "events": ["completed"],
            "headers": {"X-Source": "noclick"},
            "metadata": {"workflow": "demo"},
        }

    @pytest.mark.asyncio
    async def test_agent_includes_webhook_options(self, api_key_credentials):
        result, calls = await _run(
            firecrawl.FirecrawlAgentConfig(
                prompt="find the founders of OpenAI",
                webhook_url="https://example.com/hook",
                webhook_events="started,completed",
                webhook_headers_json='{"X-Source":"noclick"}',
                webhook_metadata_json='{"workflow":"demo"}',
            ),
            api_key_credentials,
            json_data=_envelope({"id": "agent_1"}),
        )
        assert result["action"] == "agent"
        assert calls[0]["kwargs"]["json"]["webhook"] == {
            "url": "https://example.com/hook",
            "events": ["started", "completed"],
            "headers": {"X-Source": "noclick"},
            "metadata": {"workflow": "demo"},
        }

    @pytest.mark.asyncio
    async def test_extract_rejects_invalid_json_schema(self, api_key_credentials):
        node = create_firecrawl_node(
            firecrawl.FirecrawlNodeConfig(
                config=firecrawl.FirecrawlExtractConfig(
                    urls="https://example.com", output_schema="{not json"
                ),
                credentials=api_key_credentials,
            )
        )
        with pytest.raises(ValueError, match="Invalid JSON in JSON Schema"):
            await node.execute({})


class TestFirecrawlFilesAndInteract:
    @pytest.mark.asyncio
    async def test_parse(self, api_key_credentials):
        download_response = Mock()
        download_response.content = b"%PDF-1.4 mock"
        download_response.headers = {"content-type": "application/pdf"}
        download_response.raise_for_status = Mock()

        parse_response = create_mock_response(200, _envelope({"markdown": "parsed"}))
        result, calls = await _run(
            firecrawl.FirecrawlParseConfig(url="https://example.com/doc.pdf"),
            api_key_credentials,
            responses=[download_response, parse_response],
        )
        assert result["action"] == "parse"
        assert calls[0]["method"] == "GET"
        assert calls[0]["args"][0] == "https://example.com/doc.pdf"
        assert calls[1]["kwargs"]["url"].endswith("/parse")
        assert "files" in calls[1]["kwargs"]
        assert calls[1]["kwargs"]["files"]["file"][0] == "doc.pdf"

    @pytest.mark.asyncio
    async def test_interact_endpoints(self, api_key_credentials):
        create_result, create_calls = await _run(
            firecrawl.FirecrawlCreateInteractConfig(ttl="300", profile_name="demo"),
            api_key_credentials,
            json_data=_envelope({"id": "sess_1"}),
        )
        assert create_result["action"] == "create_interact_session"
        assert create_calls[0]["kwargs"]["url"].endswith("/interact")
        assert create_calls[0]["kwargs"]["json"]["profile"]["name"] == "demo"

        cases = [
            (
                firecrawl.FirecrawlListInteractConfig(status="active"),
                "list_interact_sessions",
                "/interact",
            ),
            (
                firecrawl.FirecrawlExecuteInteractConfig(
                    session_id="sess_1", code="console.log('hi')", language="node", timeout="30"
                ),
                "execute_interact_session",
                "/interact/sess_1/execute",
            ),
            (
                firecrawl.FirecrawlDeleteInteractConfig(session_id="sess_1"),
                "delete_interact_session",
                "/interact/sess_1",
            ),
            (
                firecrawl.FirecrawlScrapeInteractConfig(job_id="scrape_1", code="console.log('hi')"),
                "scrape_interact",
                "/scrape/scrape_1/interact",
            ),
            (
                firecrawl.FirecrawlStopScrapeInteractConfig(job_id="scrape_1"),
                "stop_scrape_interact",
                "/scrape/scrape_1/interact",
            ),
        ]
        for config, action, suffix in cases:
            result, calls = await _run(config, api_key_credentials, json_data={"ok": True})
            assert result["action"] == action
            assert calls[0]["kwargs"]["url"].endswith(suffix)


class TestFirecrawlUsageSupportAndMonitoring:
    @pytest.mark.asyncio
    async def test_usage_endpoints(self, api_key_credentials):
        cases = [
            (
                firecrawl.FirecrawlCreditUsageConfig(),
                "credit_usage",
                "/team/credit-usage",
            ),
            (
                firecrawl.FirecrawlTokenUsageConfig(),
                "token_usage",
                "/team/token-usage",
            ),
            (
                firecrawl.FirecrawlCreditUsageHistoricalConfig(by_api_key="true"),
                "credit_usage_historical",
                "/team/credit-usage/historical",
            ),
            (
                firecrawl.FirecrawlTokenUsageHistoricalConfig(by_api_key="true"),
                "token_usage_historical",
                "/team/token-usage/historical",
            ),
            (
                firecrawl.FirecrawlQueueStatusConfig(),
                "queue_status",
                "/team/queue-status",
            ),
            (
                firecrawl.FirecrawlTeamActivityConfig(endpoint="/crawl", limit="10"),
                "team_activity",
                "/team/activity",
            ),
        ]
        for config, action, suffix in cases:
            result, calls = await _run(config, api_key_credentials, json_data={"items": []})
            assert result["action"] == action
            assert calls[0]["kwargs"]["url"].endswith(suffix)

    @pytest.mark.asyncio
    async def test_feedback_and_support_endpoints(self, api_key_credentials):
        cases = [
            (
                firecrawl.FirecrawlEndpointFeedbackConfig(
                    endpoint="search",
                    job_id="job_1",
                    rating="good",
                    valuable_sources_json='[{"url":"https://example.com"}]',
                ),
                "submit_feedback",
                "/feedback",
            ),
            (
                firecrawl.FirecrawlSearchFeedbackConfig(
                    job_id="job_2",
                    rating="partial",
                    missing_content_json='[{"topic":"pricing"}]',
                ),
                "submit_search_feedback",
                "/search/job_2/feedback",
            ),
            (
                firecrawl.FirecrawlSupportAskConfig(question="Why did this crawl fail?"),
                "support_ask",
                "/support/ask",
            ),
            (
                firecrawl.FirecrawlSupportDocsSearchConfig(question="How do webhooks work?"),
                "support_docs_search",
                "/support/docs-search",
            ),
        ]
        for config, action, suffix in cases:
            result, calls = await _run(config, api_key_credentials, json_data={"success": True})
            assert result["action"] == action
            assert calls[0]["kwargs"]["url"].endswith(suffix)

    @pytest.mark.asyncio
    async def test_monitor_endpoints(self, api_key_credentials):
        cases = [
            (
                firecrawl.FirecrawlCreateMonitorConfig(
                    name="Docs monitor",
                    schedule_json='{"text":"every 30 minutes","timezone":"UTC"}',
                    targets_json='[{"type":"scrape","urls":["https://docs.firecrawl.dev"]}]',
                ),
                "create_monitor",
                "/monitor",
            ),
            (
                firecrawl.FirecrawlListMonitorsConfig(limit="10", offset="0"),
                "list_monitors",
                "/monitor",
            ),
            (
                firecrawl.FirecrawlGetMonitorConfig(monitor_id="mon_1"),
                "get_monitor",
                "/monitor/mon_1",
            ),
            (
                firecrawl.FirecrawlUpdateMonitorConfig(
                    monitor_id="mon_1", update_json='{"status":"paused"}'
                ),
                "update_monitor",
                "/monitor/mon_1",
            ),
            (
                firecrawl.FirecrawlDeleteMonitorConfig(monitor_id="mon_1"),
                "delete_monitor",
                "/monitor/mon_1",
            ),
            (
                firecrawl.FirecrawlListMonitorChecksConfig(monitor_id="mon_1", limit="5"),
                "list_monitor_checks",
                "/monitor/mon_1/checks",
            ),
            (
                firecrawl.FirecrawlGetMonitorCheckConfig(monitor_id="mon_1", check_id="check_1"),
                "get_monitor_check",
                "/monitor/mon_1/checks/check_1",
            ),
            (
                firecrawl.FirecrawlRunMonitorConfig(monitor_id="mon_1"),
                "run_monitor",
                "/monitor/mon_1/run",
            ),
        ]
        for config, action, suffix in cases:
            result, calls = await _run(config, api_key_credentials, json_data={"success": True})
            assert result["action"] == action
            assert calls[0]["kwargs"]["url"].endswith(suffix)


class TestFirecrawlTriggerAndErrors:
    @pytest.mark.asyncio
    async def test_receive_webhook_passthrough(self):
        node = create_firecrawl_node(
            firecrawl.FirecrawlNodeConfig(
                config=firecrawl.FirecrawlReceiveWebhookConfig(
                    webhook_url="https://abc.hooks.example.test"
                ),
                credentials=None,
            )
        )
        result = await node.execute({"type": "crawl.completed"})
        assert result["status"] == "success"
        assert result["action"] == "receive_webhook"
        assert result["event_type"] == "crawl.completed"

    @pytest.mark.asyncio
    async def test_receive_webhook_exact_event_filter_skips_non_matching(self):
        node = create_firecrawl_node(
            firecrawl.FirecrawlNodeConfig(
                config=firecrawl.FirecrawlReceiveWebhookConfig(
                    webhook_url="https://abc.hooks.example.test",
                    event_type="monitor.page",
                ),
                credentials=None,
            )
        )
        result = await node.execute({"type": "crawl.completed"})
        assert result["status"] == "skipped"
        assert result["action"] == "receive_webhook"

    @pytest.mark.asyncio
    async def test_family_triggers_filter_by_prefix(self):
        cases = [
            (
                firecrawl.FirecrawlOnCrawlEventConfig(webhook_url="https://abc.hooks.example.test"),
                {"type": "crawl.failed"},
                "success",
            ),
            (
                firecrawl.FirecrawlOnBatchScrapeEventConfig(webhook_url="https://abc.hooks.example.test"),
                {"type": "batch_scrape.page"},
                "success",
            ),
            (
                firecrawl.FirecrawlOnAgentEventConfig(webhook_url="https://abc.hooks.example.test"),
                {"type": "agent.completed"},
                "success",
            ),
            (
                firecrawl.FirecrawlOnMonitorEventConfig(webhook_url="https://abc.hooks.example.test"),
                {"type": "monitor.check.completed"},
                "success",
            ),
            (
                firecrawl.FirecrawlOnCrawlEventConfig(webhook_url="https://abc.hooks.example.test"),
                {"type": "batch_scrape.completed"},
                "skipped",
            ),
        ]
        for config, payload, expected_status in cases:
            node = create_firecrawl_node(
                firecrawl.FirecrawlNodeConfig(config=config, credentials=None)
            )
            result = await node.execute(payload)
            assert result["status"] == expected_status
            assert result["action"] == config.operation

    def test_resolve_trigger_payload_filters_by_operation_and_event(self):
        payload = {"type": "agent.failed"}
        assert firecrawl.FirecrawlNode.resolve_trigger_payload(
            payload,
            {"operation": "on_agent_event", "event_type": "*"},
        ) == payload
        assert firecrawl.FirecrawlNode.resolve_trigger_payload(
            payload,
            {"operation": "on_crawl_event", "event_type": "*"},
        ) is None
        assert firecrawl.FirecrawlNode.resolve_trigger_payload(
            payload,
            {"operation": "receive_webhook", "event_type": "agent.failed"},
        ) == payload
        assert firecrawl.FirecrawlNode.resolve_trigger_payload(
            payload,
            {"operation": "receive_webhook", "event_type": "agent.completed"},
        ) is None

    def test_verify_webhook_signature_uses_firecrawl_header(self):
        body = b'{"event":"crawl.completed"}'
        secret = "top-secret"
        signature = "sha256=" + hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()

        assert firecrawl.FirecrawlNode.verify_webhook_signature(
            body,
            {"x-firecrawl-signature": signature},
            {"signing_secret": secret},
        ) is True
        assert firecrawl.FirecrawlNode.verify_webhook_signature(
            body,
            {"x-firecrawl-signature": "sha256=bad"},
            {"signing_secret": secret},
        ) is False
        assert firecrawl.FirecrawlNode.verify_webhook_signature(
            body,
            {},
            {},
        ) is True

    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        result, _ = await _run(
            firecrawl.FirecrawlGetCrawlConfig(job_id="missing"),
            api_key_credentials,
            status_code=404,
            json_data={"error": "Not Found"},
        )
        assert result["status"] == "error"
        assert result["status_code"] == 404

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        node = create_firecrawl_node(
            firecrawl.FirecrawlNodeConfig(
                config=firecrawl.FirecrawlCreditUsageConfig(), credentials=None
            )
        )
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})
