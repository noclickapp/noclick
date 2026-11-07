"""
Mock tests for the Perplexity REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Chat: completion, streaming, async create/list/get, academic, sec, structured
- Search: web search
- Agent: agent response
- Embeddings: standard, contextualized
- Models: list models
- Auth Tokens: generate, revoke
- Analytics: usage
- Error handling: API errors, missing credentials, invalid structured-output schema
- Dynamic options: model dropdown
"""

import pytest
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from nodes.perplexity_node import (
    PerplexityNode,
    PerplexityNodeConfig,
    PerplexityApiKeyCredential,
    PerplexityChatCompletionConfig,
    PerplexityCreateAsyncCompletionConfig,
    PerplexityListAsyncCompletionsConfig,
    PerplexityGetAsyncCompletionConfig,
    PerplexitySearchConfig,
    PerplexityAgentResponseConfig,
    PerplexityCreateEmbeddingsConfig,
    PerplexityCreateContextualizedEmbeddingsConfig,
    PerplexityListModelsConfig,
    PerplexityGenerateAuthTokenConfig,
    PerplexityRevokeAuthTokenConfig,
    PerplexityUsageAnalyticsConfig,
    PerplexityAcademicSearchConfig,
    PerplexitySecSearchConfig,
    PerplexityStructuredOutputConfig,
)


@pytest.fixture
def api_key_credentials():
    return PerplexityApiKeyCredential(api_key="pplx-test-key-12345")


def create_perplexity_node(config):
    return PerplexityNode(
        node_id="test-perplexity-node",
        node_type="automation-perplexity",
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

    mock_client.request = AsyncMock(return_value=mock_response)

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


# Exact provider-authored Response object, also used as a harness witness.
AGENT_RESPONSE = json.loads(
    (Path(__file__).parent / "fixtures/perplexity_agent_response.json").read_text()
)["body"]


CHAT_RESPONSE = {
    "id": "cmpl-1",
    "choices": [{"message": {"role": "assistant", "content": "The answer."}}],
    "citations": ["https://example.com/a"],
}


class TestPerplexityChatMock:
    @pytest.mark.asyncio
    async def test_chat_completion(self, api_key_credentials):
        config = PerplexityNodeConfig(
            config=PerplexityChatCompletionConfig(
                model="sonar", prompt="What is the capital of France?"
            ),
            credentials=api_key_credentials,
        )
        node = create_perplexity_node(config)
        mock_client = create_mock_client(200, CHAT_RESPONSE)
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "chat_completion"
        mock_client.request.assert_awaited_once()
        request = mock_client.request.call_args.kwargs
        assert request["method"] == "POST"
        assert request["url"] == "https://api.perplexity.ai/v1/sonar"
        assert result["data"]["citations"] == ["https://example.com/a"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("model,effort", [
        ("sonar", "fast"), ("sonar-pro", "fast"),
        ("sonar-reasoning-pro", "low"), ("sonar-deep-research", "high"),
        ("openai/gpt-5.6-sol", None),
    ])
    async def test_create_async_completion(self, api_key_credentials, model, effort):
        node = create_perplexity_node(PerplexityNodeConfig(
            config=PerplexityCreateAsyncCompletionConfig(
                model=model, prompt="Write a deep report", system_prompt="Use sources"
            ), credentials=api_key_credentials,
        ))
        node._load_node_state = AsyncMock(return_value={"unrelated": True})
        node._save_node_state = AsyncMock()
        client = create_mock_client(200, AGENT_RESPONSE)
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_async_completion"
        client.request.assert_awaited_once()
        request = client.request.call_args.kwargs
        assert request["method"] == "POST"
        assert request["url"] == "https://api.perplexity.ai/v1/agent"
        assert request["json"]["background"] is True
        assert request["json"]["store"] is True
        assert request["json"]["input"] == "Write a deep report"
        assert request["json"]["instructions"] == "Use sources"
        assert "request" not in request["json"]
        if effort:
            assert request["json"]["effort"] == effort
            assert "model" not in request["json"]
        else:
            assert request["json"]["model"] == model
            assert request["json"]["tools"] == [{"type": "web_search"}]
            assert request["json"]["max_steps"] == 10
        assert result["data"]["request_id"] == AGENT_RESPONSE["id"]
        state = node._save_node_state.call_args.args[0]
        key = hashlib.sha256(api_key_credentials.api_key.encode()).hexdigest()
        assert state["perplexity_background_jobs"][key] == {AGENT_RESPONSE["id"]: model}
        assert state["unrelated"] is True
        assert api_key_credentials.api_key not in json.dumps(state)

    @pytest.mark.asyncio
    async def test_list_async_completions(self, api_key_credentials):
        node = create_perplexity_node(PerplexityNodeConfig(
            config=PerplexityListAsyncCompletionsConfig(), credentials=api_key_credentials,
        ))
        key = hashlib.sha256(api_key_credentials.api_key.encode()).hexdigest()
        state = {"perplexity_background_jobs": {key: {AGENT_RESPONSE["id"]: "sonar-deep-research"}}}
        pool = Mock(fetch=AsyncMock(return_value=[
            {"state": json.dumps(state)}, {"state": state},
            {"state": {"perplexity_background_jobs": {"another-key": {"private-id": "sonar"}}}},
        ]))
        client = create_mock_client(200, AGENT_RESPONSE)
        with patch("utils.database_pool.get_native_pool", return_value=pool), patch(
            "nodes.perplexity_node.httpx.AsyncClient", return_value=client
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_async_completions"
        pool.fetch.assert_awaited_once_with(
            "SELECT state FROM workflow_node_state WHERE workflow_id = $1", "test-workflow"
        )
        client.request.assert_awaited_once()
        request = client.request.call_args.kwargs
        assert request["method"] == "GET"
        assert request["url"] == "https://api.perplexity.ai/v1/agent/" + AGENT_RESPONSE["id"]
        assert result["timing_ms"]["api_request"] >= 0
        assert result["data"]["scope"] == "workflow"
        assert result["data"]["next_token"] is None
        assert len(result["data"]["requests"]) == 1
        assert result["data"]["requests"][0]["status"] == "COMPLETED"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status,legacy_status", [
        ("queued", "CREATED"), ("in_progress", "IN_PROGRESS"),
        ("cancelling", "IN_PROGRESS"), ("completed", "COMPLETED"),
        ("failed", "FAILED"), ("cancelled", "FAILED"), ("incomplete", "FAILED"),
    ])
    async def test_get_async_completion(self, api_key_credentials, status, legacy_status):
        node = create_perplexity_node(PerplexityNodeConfig(
            config=PerplexityGetAsyncCompletionConfig(request_id=AGENT_RESPONSE["id"]),
            credentials=api_key_credentials,
        ))
        node._update_node_state = AsyncMock()
        # Vary the documented status enum to verify every lifecycle transition.
        snapshot = copy.deepcopy(AGENT_RESPONSE)
        snapshot["status"] = status
        if status != "completed":
            snapshot["output"] = []
            snapshot.pop("completed_at", None)
        if status == "in_progress":
            snapshot["paused"] = {"reason": "token_limit"}
        if status == "failed":
            snapshot["error"] = {"message": "Run failed"}
        client = create_mock_client(200, snapshot)
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_async_completion"
        client.request.assert_awaited_once()
        request = client.request.call_args.kwargs
        assert request["method"] == "GET"
        assert request["url"] == "https://api.perplexity.ai/v1/agent/" + AGENT_RESPONSE["id"]
        data = result["data"]
        assert data["id"] == data["request_id"] == AGENT_RESPONSE["id"]
        assert data["status"] == legacy_status
        assert data["agent_status"] == status
        assert data["agent_response"] == snapshot
        assert data["started_at"] is None  # Don't invent missing timestamps.
        assert data["completed_at"] == snapshot.get("completed_at")
        assert data["failed_at"] is None
        if status == "completed":
            text = "".join(c["text"] for i in snapshot["output"] if i["type"] == "message"
                           for c in i["content"] if c["type"] == "output_text")
            assert data["response"]["choices"][0]["message"]["content"] == text
            assert data["response"]["usage"]["prompt_tokens"] == snapshot["usage"]["input_tokens"]
        else:
            assert data["response"] is None
        if status in ("failed", "cancelled", "incomplete"):
            assert data["error_message"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("operation", [
        "create_async_completion", "get_async_completion", "list_async_completions",
    ])
    async def test_background_cost_aliases_from_provider_fixture(self, api_key_credentials, operation):
        configs = {
            "create_async_completion": PerplexityCreateAsyncCompletionConfig(prompt="Research"),
            "get_async_completion": PerplexityGetAsyncCompletionConfig(request_id=AGENT_RESPONSE["id"]),
            "list_async_completions": PerplexityListAsyncCompletionsConfig(request_ids=AGENT_RESPONSE["id"]),
        }
        node = create_perplexity_node(PerplexityNodeConfig(
            config=configs[operation], credentials=api_key_credentials,
        ))
        node.workflow_id = None
        snapshot = copy.deepcopy(AGENT_RESPONSE)
        client = create_mock_client(200, snapshot)
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        data = result["data"]
        if operation == "list_async_completions":
            data = data["requests"][0]
        cost = data["response"]["usage"]["cost"]
        native_cost = AGENT_RESPONSE["usage"]["cost"]
        assert cost["input_tokens_cost"] == cost["input_cost"] == native_cost["input_cost"] == 0.01307
        assert cost["output_tokens_cost"] == cost["output_cost"] == native_cost["output_cost"] == 0.02632
        assert cost["total_cost"] == native_cost["total_cost"]
        assert data["agent_response"]["usage"]["cost"] == native_cost
        assert data["usage"]["cost"] == native_cost
        assert snapshot == AGENT_RESPONSE  # No aliases added to the native response.

    @pytest.mark.asyncio
    async def test_listing_explicit_ids_without_workflow(self, api_key_credentials):
        node = create_perplexity_node(PerplexityNodeConfig(
            config=PerplexityListAsyncCompletionsConfig(request_ids=AGENT_RESPONSE["id"]),
            credentials=api_key_credentials,
        ))
        node.workflow_id = None
        client = create_mock_client(200, AGENT_RESPONSE)
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["data"]["requests"][0]["request_id"] == AGENT_RESPONSE["id"]
        assert result["data"]["scope"] == "provided_ids"
        client.request.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_listing_does_not_hide_storage_failure(self, api_key_credentials):
        node = create_perplexity_node(PerplexityNodeConfig(
            config=PerplexityListAsyncCompletionsConfig(), credentials=api_key_credentials,
        ))
        pool = Mock(fetch=AsyncMock(side_effect=RuntimeError("DB unavailable")))
        with patch("utils.database_pool.get_native_pool", return_value=pool):
            with pytest.raises(RuntimeError, match="DB unavailable"):
                await node.execute({})

    @pytest.mark.asyncio
    async def test_listing_does_not_hide_provider_failure(self, api_key_credentials):
        node = create_perplexity_node(PerplexityNodeConfig(
            config=PerplexityListAsyncCompletionsConfig(), credentials=api_key_credentials,
        ))
        key = hashlib.sha256(api_key_credentials.api_key.encode()).hexdigest()
        pool = Mock(fetch=AsyncMock(return_value=[{"state": {
            "perplexity_background_jobs": {key: {AGENT_RESPONSE["id"]: "sonar"}}
        }}]))
        client = create_mock_client(403, {"error": {"message": "Forbidden"}})
        with patch("utils.database_pool.get_native_pool", return_value=pool), patch(
            "nodes.perplexity_node.httpx.AsyncClient", return_value=client
        ):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 403
        assert "data" not in result

    @pytest.mark.asyncio
    async def test_empty_workflow_listing_is_explicitly_scoped(self, api_key_credentials):
        node = create_perplexity_node(PerplexityNodeConfig(
            config=PerplexityListAsyncCompletionsConfig(), credentials=api_key_credentials,
        ))
        pool = Mock(fetch=AsyncMock(return_value=[]))
        with patch("utils.database_pool.get_native_pool", return_value=pool), patch(
            "nodes.perplexity_node.httpx.AsyncClient"
        ) as client:
            result = await node.execute({})
        assert result["data"] == {"requests": [], "next_token": None,
                                  "scope": "workflow", "includes_historical_sonar_jobs": False}
        assert result["timing_ms"]["api_request"] == 0
        client.assert_not_called()

    @pytest.mark.asyncio
    async def test_tracking_failure_preserves_created_job(self, api_key_credentials):
        node = create_perplexity_node(PerplexityNodeConfig(
            config=PerplexityCreateAsyncCompletionConfig(prompt="Research"),
            credentials=api_key_credentials,
        ))
        node._update_node_state = AsyncMock(side_effect=RuntimeError("DB unavailable"))
        client = create_mock_client(200, AGENT_RESPONSE)
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["data"]["request_id"] == AGENT_RESPONSE["id"]
        assert result["tracking_error"]
        client.request.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_historical_sonar_id_has_actionable_error(self, api_key_credentials):
        node = create_perplexity_node(PerplexityNodeConfig(
            config=PerplexityGetAsyncCompletionConfig(request_id="old/sonar?job"),
            credentials=api_key_credentials,
        ))
        client = create_mock_client(404, {"error": {"message": "Unknown response"}})
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert "Historical async Sonar jobs" in result["error"]
        assert client.request.call_args.kwargs["url"].endswith("/old%2Fsonar%3Fjob")

    @pytest.mark.asyncio
    async def test_academic_search(self, api_key_credentials):
        config = PerplexityNodeConfig(
            config=PerplexityAcademicSearchConfig(model="sonar", prompt="CRISPR advances"),
            credentials=api_key_credentials,
        )
        node = create_perplexity_node(config)
        mock_client = create_mock_client(200, CHAT_RESPONSE)
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "academic_search"
        mock_client.request.assert_awaited_once()
        request = mock_client.request.call_args.kwargs
        assert request["method"] == "POST"
        assert request["url"] == "https://api.perplexity.ai/v1/sonar"
        assert request["json"]["search_mode"] == "academic"

    @pytest.mark.asyncio
    async def test_sec_search(self, api_key_credentials):
        config = PerplexityNodeConfig(
            config=PerplexitySecSearchConfig(model="sonar", prompt="Apple latest 10-K"),
            credentials=api_key_credentials,
        )
        node = create_perplexity_node(config)
        mock_client = create_mock_client(200, CHAT_RESPONSE)
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "sec_search"
        mock_client.request.assert_awaited_once()
        request = mock_client.request.call_args.kwargs
        assert request["method"] == "POST"
        assert request["url"] == "https://api.perplexity.ai/v1/sonar"
        assert request["json"]["search_mode"] == "sec"

    @pytest.mark.asyncio
    async def test_structured_output(self, api_key_credentials):
        config = PerplexityNodeConfig(
            config=PerplexityStructuredOutputConfig(
                model="sonar",
                prompt="Give me the capital of France",
                output_schema='{"type": "object", "properties": {"capital": {"type": "string"}}}',
            ),
            credentials=api_key_credentials,
        )
        node = create_perplexity_node(config)
        mock_client = create_mock_client(200, CHAT_RESPONSE)
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "structured_output"
        mock_client.request.assert_awaited_once()
        request = mock_client.request.call_args.kwargs
        assert request["method"] == "POST"
        assert request["url"] == "https://api.perplexity.ai/v1/sonar"

    @pytest.mark.asyncio
    async def test_structured_output_invalid_schema(self, api_key_credentials):
        config = PerplexityNodeConfig(
            config=PerplexityStructuredOutputConfig(
                model="sonar", prompt="x", output_schema="{not valid json"
            ),
            credentials=api_key_credentials,
        )
        node = create_perplexity_node(config)
        result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 400
        assert "Invalid JSON schema" in result["error"]


class TestPerplexitySearchMock:
    @pytest.mark.asyncio
    async def test_search(self, api_key_credentials):
        config = PerplexityNodeConfig(
            config=PerplexitySearchConfig(
                query="latest AI news", max_results="5", search_recency_filter="day"
            ),
            credentials=api_key_credentials,
        )
        node = create_perplexity_node(config)
        mock_client = create_mock_client(
            200, {"results": [{"title": "T", "url": "https://x.com", "snippet": "S"}]}
        )
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "search"
        assert result["data"]["results"][0]["url"] == "https://x.com"


class TestPerplexityAgentMock:
    @pytest.mark.asyncio
    async def test_agent_response(self, api_key_credentials):
        config = PerplexityNodeConfig(
            config=PerplexityAgentResponseConfig(
                model="openai/gpt-5.5", prompt="Research the market"
            ),
            credentials=api_key_credentials,
        )
        node = create_perplexity_node(config)
        mock_client = create_mock_client(200, CHAT_RESPONSE)
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "agent_response"


class TestPerplexityEmbeddingsMock:
    @pytest.mark.asyncio
    async def test_create_embeddings(self, api_key_credentials):
        config = PerplexityNodeConfig(
            config=PerplexityCreateEmbeddingsConfig(
                model="text-embedding", input_text="hello world"
            ),
            credentials=api_key_credentials,
        )
        node = create_perplexity_node(config)
        mock_client = create_mock_client(
            200, {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
        )
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_embeddings"
        assert result["data"]["data"][0]["embedding"] == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_create_contextualized_embeddings(self, api_key_credentials):
        config = PerplexityNodeConfig(
            config=PerplexityCreateContextualizedEmbeddingsConfig(
                model="text-embedding", input_text="hello", context="greetings corpus"
            ),
            credentials=api_key_credentials,
        )
        node = create_perplexity_node(config)
        mock_client = create_mock_client(200, {"data": [{"embedding": [0.4]}]})
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_contextualized_embeddings"


class TestPerplexityModelsMock:
    @pytest.mark.asyncio
    async def test_list_models(self, api_key_credentials):
        config = PerplexityNodeConfig(
            config=PerplexityListModelsConfig(), credentials=api_key_credentials
        )
        node = create_perplexity_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "sonar"}, {"id": "sonar-pro"}]})
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_models"
        assert len(result["data"]["data"]) == 2


class TestPerplexityAuthTokensMock:
    @pytest.mark.asyncio
    async def test_generate_auth_token(self, api_key_credentials):
        config = PerplexityNodeConfig(
            config=PerplexityGenerateAuthTokenConfig(token_name="ci-key"),
            credentials=api_key_credentials,
        )
        node = create_perplexity_node(config)
        mock_client = create_mock_client(200, {"token": "pplx-new", "name": "ci-key"})
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "generate_auth_token"
        assert result["data"]["token"] == "pplx-new"

    @pytest.mark.asyncio
    async def test_revoke_auth_token(self, api_key_credentials):
        config = PerplexityNodeConfig(
            config=PerplexityRevokeAuthTokenConfig(token="pplx-old"),
            credentials=api_key_credentials,
        )
        node = create_perplexity_node(config)
        mock_client = create_mock_client(200, {"success": True})
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "revoke_auth_token"


class TestPerplexityAnalyticsMock:
    @pytest.mark.asyncio
    async def test_usage_analytics(self, api_key_credentials):
        config = PerplexityNodeConfig(
            config=PerplexityUsageAnalyticsConfig(dataset="credit_usage", start_time="1750000000"),
            credentials=api_key_credentials,
        )
        node = create_perplexity_node(config)
        mock_client = create_mock_client(200, {"usage": {"total_requests": 42}})
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "usage_analytics"
        assert result["data"]["usage"]["total_requests"] == 42


class TestPerplexityErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        config = PerplexityNodeConfig(
            config=PerplexityChatCompletionConfig(model="sonar", prompt="x"),
            credentials=api_key_credentials,
        )
        node = create_perplexity_node(config)
        mock_client = create_mock_client(
            401, {"error": {"message": "Invalid API key"}}
        )
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 401
        assert "invalid api key" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = PerplexityNodeConfig(
            config=PerplexityListModelsConfig(), credentials=None
        )
        node = create_perplexity_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


class TestPerplexityDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_model_options(self):
        async def fake_request(*args, **kwargs):
            return {"status": "success", "data": {"data": [{"id": "sonar"}, {"id": "sonar-pro"}]}}

        with patch("nodes.perplexity_node._perplexity_request", side_effect=fake_request):
            result = await PerplexityNode.load_field_options(
                "model", {"api_key": "pplx-test"}, context={}
            )
        assert "options" in result
        assert result["options"][0]["value"] == "sonar"
        assert result["options"][1]["value"] == "sonar-pro"

    @pytest.mark.asyncio
    async def test_load_model_options_no_credential(self):
        result = await PerplexityNode.load_field_options("model", {}, context={})
        assert "options" in result
        assert {"label": "sonar", "value": "sonar"} in result["options"]
