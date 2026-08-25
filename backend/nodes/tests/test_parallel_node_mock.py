"""
Mock tests for the Parallel REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Search:   search, extract
- Tasks:    create / get / get-result (with timeout) / get-input run; create group, add runs,
            get group runs, get group, get task group run
- FindAll:  create / get / get-result / enrich / extend / cancel run, entity search,
            create findall spec
- Monitors: create / list / get / update / list-events / trigger / cancel
- Chat:     chat completions (with model enum)
- Trigger:  receive_webhook passthrough, signature verification
- Error handling: API errors, missing credentials
"""

import base64
import hashlib
import hmac

import pytest
from unittest.mock import Mock, patch

from nodes.parallel_node import (
    ParallelNode,
    ParallelNodeConfig,
    ParallelApiKeyCredential,
    ParallelSearchConfig,
    ParallelExtractConfig,
    ParallelCreateTaskRunConfig,
    ParallelGetTaskRunConfig,
    ParallelGetTaskRunResultConfig,
    ParallelGetTaskRunInputConfig,
    ParallelCreateTaskGroupConfig,
    ParallelAddRunsToGroupConfig,
    ParallelGetGroupRunsConfig,
    ParallelGetTaskGroupConfig,
    ParallelGetTaskGroupRunConfig,
    ParallelCreateFindAllConfig,
    ParallelCreateFindAllSpecConfig,
    ParallelGetFindAllConfig,
    ParallelGetFindAllResultConfig,
    ParallelEnrichFindAllConfig,
    ParallelExtendFindAllConfig,
    ParallelCancelFindAllConfig,
    ParallelEntitySearchConfig,
    ParallelCreateMonitorConfig,
    ParallelListMonitorsConfig,
    ParallelGetMonitorConfig,
    ParallelUpdateMonitorConfig,
    ParallelListMonitorEventsConfig,
    ParallelTriggerMonitorConfig,
    ParallelCancelMonitorConfig,
    ParallelChatCompletionsConfig,
    ParallelReceiveWebhookConfig,
)


@pytest.fixture
def api_key_credentials():
    return ParallelApiKeyCredential(api_key="pk_test_key_12345")


def create_parallel_node(config):
    return ParallelNode(
        node_id="test-parallel-node",
        node_type="automation-parallel",
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


async def _run(config_obj, credentials, status_code=200, json_data=None):
    config = ParallelNodeConfig(config=config_obj, credentials=credentials)
    node = create_parallel_node(config)
    mock_client = create_mock_client(status_code, json_data)
    with patch("nodes.parallel_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


# ============================================================================
# Search
# ============================================================================


class TestParallelSearchMock:
    @pytest.mark.asyncio
    async def test_search(self, api_key_credentials):
        result = await _run(
            ParallelSearchConfig(
                search_queries="AI funding 2025\nAI startups 2025",
                objective="latest AI funding rounds",
            ),
            api_key_credentials,
            200,
            {"results": [{"url": "https://example.com"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "search"
        assert result["data"]["results"][0]["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_extract(self, api_key_credentials):
        result = await _run(
            ParallelExtractConfig(urls="https://example.com\nhttps://foo.com"),
            api_key_credentials,
            200,
            {"results": [{"markdown": "# Hello"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "extract"


# ============================================================================
# Tasks
# ============================================================================


class TestParallelTasksMock:
    @pytest.mark.asyncio
    async def test_create_task_run(self, api_key_credentials):
        result = await _run(
            ParallelCreateTaskRunConfig(
                input="Research Acme Corp", processor="core",
                output_schema='{"type": "object"}',
                webhook_url="https://abc.hooks.example.test",
            ),
            api_key_credentials,
            200,
            {"run_id": "run_1", "status": "queued"},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_task_run"
        assert result["data"]["run_id"] == "run_1"

    @pytest.mark.asyncio
    async def test_get_task_run(self, api_key_credentials):
        result = await _run(
            ParallelGetTaskRunConfig(run_id="run_1"),
            api_key_credentials,
            200,
            {"run_id": "run_1", "status": "running"},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_task_run"

    @pytest.mark.asyncio
    async def test_get_task_run_result(self, api_key_credentials):
        result = await _run(
            ParallelGetTaskRunResultConfig(run_id="run_1"),
            api_key_credentials,
            200,
            {"output": {"answer": "42"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_task_run_result"

    @pytest.mark.asyncio
    async def test_get_task_run_result_custom_timeout(self, api_key_credentials):
        """Custom timeout_seconds is passed as a query param and raises httpx timeout to 630s."""
        result = await _run(
            ParallelGetTaskRunResultConfig(run_id="run_1", timeout_seconds="300"),
            api_key_credentials,
            200,
            {"output": {"answer": "42"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_task_run_result"

    @pytest.mark.asyncio
    async def test_get_task_run_input(self, api_key_credentials):
        result = await _run(
            ParallelGetTaskRunInputConfig(run_id="run_1"),
            api_key_credentials,
            200,
            {"input": "Research Acme Corp"},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_task_run_input"

    @pytest.mark.asyncio
    async def test_create_task_group(self, api_key_credentials):
        result = await _run(
            ParallelCreateTaskGroupConfig(metadata='{"campaign": "q3"}'),
            api_key_credentials,
            200,
            {"taskgroup_id": "tg_1"},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_task_group"
        assert result["data"]["taskgroup_id"] == "tg_1"

    @pytest.mark.asyncio
    async def test_add_runs_to_group(self, api_key_credentials):
        result = await _run(
            ParallelAddRunsToGroupConfig(
                taskgroup_id="tg_1", inputs="Acme\nBeta\nGamma", processor="core"
            ),
            api_key_credentials,
            200,
            {"added": 3},
        )
        assert result["status"] == "success"
        assert result["action"] == "add_runs_to_group"

    @pytest.mark.asyncio
    async def test_get_group_runs(self, api_key_credentials):
        # get_group_runs returns SSE (text/event-stream); mock the raw SSE response.
        sse_body = (
            'event: task_run.state\n'
            'id: run_1\n'
            'data: {"type":"task_run.state","run":{"run_id":"run_1","status":"completed"}}\n\n'
            'event: task_run.state\n'
            'id: run_2\n'
            'data: {"type":"task_run.state","run":{"run_id":"run_2","status":"running"}}\n\n'
        )
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = sse_body
        mock_client = Mock()
        async def async_get(*args, **kwargs):
            return mock_response
        mock_client.get = async_get
        async def aenter(self): return mock_client
        async def aexit(self, *a): return None
        mock_client.__aenter__ = aenter
        mock_client.__aexit__ = aexit

        cfg = ParallelNodeConfig(
            config=ParallelGetGroupRunsConfig(taskgroup_id="tg_1", include_input="true"),
            credentials=api_key_credentials,
        )
        node = create_parallel_node(cfg)
        with patch("nodes.parallel_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_group_runs"
        assert result["data"]["count"] == 2
        assert result["data"]["runs"][0]["run_id"] == "run_1"

    @pytest.mark.asyncio
    async def test_get_task_group(self, api_key_credentials):
        result = await _run(
            ParallelGetTaskGroupConfig(taskgroup_id="tg_1"),
            api_key_credentials,
            200,
            {"taskgroup_id": "tg_1", "status": "running"},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_task_group"

    @pytest.mark.asyncio
    async def test_get_task_group_run(self, api_key_credentials):
        result = await _run(
            ParallelGetTaskGroupRunConfig(taskgroup_id="tg_1", run_id="run_1"),
            api_key_credentials,
            200,
            {"run_id": "run_1", "status": "complete"},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_task_group_run"


# ============================================================================
# FindAll
# ============================================================================


class TestParallelFindAllMock:
    @pytest.mark.asyncio
    async def test_create_findall_run(self, api_key_credentials):
        result = await _run(
            ParallelCreateFindAllConfig(
                objective="Series B SaaS companies",
                entity_type="company",
                generator="base",
                match_conditions='[{"name": "hiring_ml", "description": "Company is hiring for ML roles"}, {"name": "us_based", "description": "Company is based in the US"}]',
                match_limit="50",
                webhook_url="https://abc.hooks.example.test",
            ),
            api_key_credentials,
            200,
            {"findall_id": "fa_1", "status": "queued"},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_findall_run"
        assert result["data"]["findall_id"] == "fa_1"

    @pytest.mark.asyncio
    async def test_get_findall_run(self, api_key_credentials):
        result = await _run(
            ParallelGetFindAllConfig(findall_id="fa_1"),
            api_key_credentials,
            200,
            {"findall_id": "fa_1", "status": "running"},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_findall_run"

    @pytest.mark.asyncio
    async def test_get_findall_result(self, api_key_credentials):
        result = await _run(
            ParallelGetFindAllResultConfig(findall_id="fa_1"),
            api_key_credentials,
            200,
            {"entities": [{"name": "Acme"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_findall_result"

    @pytest.mark.asyncio
    async def test_enrich_findall(self, api_key_credentials):
        result = await _run(
            ParallelEnrichFindAllConfig(
                findall_id="fa_1", enrichments="CEO name\nEmployee count"
            ),
            api_key_credentials,
            200,
            {"enriched": True},
        )
        assert result["status"] == "success"
        assert result["action"] == "enrich_findall"

    @pytest.mark.asyncio
    async def test_extend_findall(self, api_key_credentials):
        result = await _run(
            ParallelExtendFindAllConfig(findall_id="fa_1", match_limit="25"),
            api_key_credentials,
            200,
            {"extended": True},
        )
        assert result["status"] == "success"
        assert result["action"] == "extend_findall"

    @pytest.mark.asyncio
    async def test_cancel_findall(self, api_key_credentials):
        result = await _run(
            ParallelCancelFindAllConfig(findall_id="fa_1"),
            api_key_credentials,
            200,
            {"findall_id": "fa_1", "status": "cancelled"},
        )
        assert result["status"] == "success"
        assert result["action"] == "cancel_findall"

    @pytest.mark.asyncio
    async def test_entity_search(self, api_key_credentials):
        result = await _run(
            ParallelEntitySearchConfig(
                query="CTO of Stripe",
                entity_type="people",
                objective="Find the Chief Technology Officer at Stripe",
            ),
            api_key_credentials,
            200,
            {"entities": [{"name": "David Singleton"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "entity_search"

    @pytest.mark.asyncio
    async def test_create_findall_spec(self, api_key_credentials):
        result = await _run(
            ParallelCreateFindAllSpecConfig(objective="Series B SaaS companies in Europe"),
            api_key_credentials,
            200,
            {"objective": "Series B SaaS companies in Europe", "entity_type": "company"},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_findall_spec"


# ============================================================================
# Monitors
# ============================================================================


class TestParallelMonitorsMock:
    @pytest.mark.asyncio
    async def test_create_monitor(self, api_key_credentials):
        result = await _run(
            ParallelCreateMonitorConfig(
                type="event_stream",
                frequency="1d",
                settings='{"query": "competitor pricing changes", "objective": "Track pricing updates"}',
                webhook_url="https://abc.hooks.example.test",
            ),
            api_key_credentials,
            200,
            {"monitor_id": "mon_1"},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_monitor"
        assert result["data"]["monitor_id"] == "mon_1"

    @pytest.mark.asyncio
    async def test_list_monitors(self, api_key_credentials):
        result = await _run(
            ParallelListMonitorsConfig(status="active", limit="10"),
            api_key_credentials,
            200,
            {"monitors": [{"monitor_id": "mon_1"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_monitors"

    @pytest.mark.asyncio
    async def test_get_monitor(self, api_key_credentials):
        result = await _run(
            ParallelGetMonitorConfig(monitor_id="mon_1"),
            api_key_credentials,
            200,
            {"monitor_id": "mon_1", "status": "active"},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_monitor"

    @pytest.mark.asyncio
    async def test_update_monitor(self, api_key_credentials):
        result = await _run(
            ParallelUpdateMonitorConfig(
                monitor_id="mon_1",
                frequency="2d",
                type="event_stream",
                settings='{"query": "AI news 2025"}',
            ),
            api_key_credentials,
            200,
            {"monitor_id": "mon_1", "updated": True},
        )
        assert result["status"] == "success"
        assert result["action"] == "update_monitor"

    @pytest.mark.asyncio
    async def test_list_monitor_events(self, api_key_credentials):
        result = await _run(
            ParallelListMonitorEventsConfig(monitor_id="mon_1"),
            api_key_credentials,
            200,
            {"events": [{"id": "ev_1"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_monitor_events"

    @pytest.mark.asyncio
    async def test_trigger_monitor(self, api_key_credentials):
        result = await _run(
            ParallelTriggerMonitorConfig(monitor_id="mon_1"),
            api_key_credentials,
            200,
            {"monitor_id": "mon_1", "triggered": True},
        )
        assert result["status"] == "success"
        assert result["action"] == "trigger_monitor"

    @pytest.mark.asyncio
    async def test_cancel_monitor(self, api_key_credentials):
        result = await _run(
            ParallelCancelMonitorConfig(monitor_id="mon_1"),
            api_key_credentials,
            200,
            {"monitor_id": "mon_1", "status": "cancelled"},
        )
        assert result["status"] == "success"
        assert result["action"] == "cancel_monitor"


# ============================================================================
# Chat
# ============================================================================


class TestParallelChatMock:
    @pytest.mark.asyncio
    async def test_chat_completions(self, api_key_credentials):
        result = await _run(
            ParallelChatCompletionsConfig(
                prompt="What is the capital of France?",
                model="speed",
                system_prompt="Be concise.",
            ),
            api_key_credentials,
            200,
            {"choices": [{"message": {"content": "Paris"}}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "chat_completions"
        assert result["data"]["choices"][0]["message"]["content"] == "Paris"

    @pytest.mark.asyncio
    async def test_chat_completions_research_model(self, api_key_credentials):
        """Research models (lite/base/core) are valid enum values."""
        for model in ("lite", "base", "core"):
            result = await _run(
                ParallelChatCompletionsConfig(prompt="Summarize AI trends", model=model),
                api_key_credentials,
                200,
                {"choices": [{"message": {"content": "AI is evolving rapidly"}}]},
            )
            assert result["status"] == "success"
            assert result["action"] == "chat_completions"


# ============================================================================
# Trigger
# ============================================================================


class TestParallelTriggerMock:
    @pytest.mark.asyncio
    async def test_receive_webhook_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = ParallelNodeConfig(
            config=ParallelReceiveWebhookConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_parallel_node(config)
        payload = {"type": "task_run.status", "data": {"run_id": "run_x"}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "receive_webhook"
        assert result["data"]["type"] == "task_run.status"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    def test_verify_webhook_signature(self):
        """Parallel signs "{webhook-id}.{webhook-timestamp}.{body}" and sends
        "v1,<base64_hmac_sha256>" in the `webhook-signature` header."""
        secret = "topsecret"
        webhook_id = "msg_abc123"
        webhook_ts = "1700000000"
        body = b'{"type":"task_run.status"}'
        signed_payload = f"{webhook_id}.{webhook_ts}.".encode() + body
        good_sig = base64.b64encode(
            hmac.new(secret.encode(), signed_payload, hashlib.sha256).digest()
        ).decode()

        headers = {
            "webhook-id": webhook_id,
            "webhook-timestamp": webhook_ts,
            "webhook-signature": f"v1,{good_sig}",
        }
        assert ParallelNode.verify_webhook_signature(body, headers, {"signing_secret": secret})

        # Multiple sigs — first is wrong, second is correct
        headers_multi = {**headers, "webhook-signature": f"v1,badsig== v1,{good_sig}"}
        assert ParallelNode.verify_webhook_signature(body, headers_multi, {"signing_secret": secret})

        # Wrong signature
        headers_bad = {**headers, "webhook-signature": "v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}
        assert not ParallelNode.verify_webhook_signature(body, headers_bad, {"signing_secret": secret})

        # Missing webhook-id / webhook-timestamp → reject even with valid sig
        assert not ParallelNode.verify_webhook_signature(
            body, {"webhook-signature": f"v1,{good_sig}"}, {"signing_secret": secret}
        )

        # No secret stored yet → accept (trigger not armed)
        assert ParallelNode.verify_webhook_signature(body, {}, {})


# ============================================================================
# Error handling
# ============================================================================


class TestParallelErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        result = await _run(
            ParallelGetTaskRunConfig(run_id="missing"),
            api_key_credentials,
            404,
            {"error": {"message": "Run not found"}},
        )
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = ParallelNodeConfig(
            config=ParallelSearchConfig(search_queries="test query", objective="x"),
            credentials=None,
        )
        node = create_parallel_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})
