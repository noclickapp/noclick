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
from unittest.mock import Mock, patch

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
        assert result["data"]["citations"] == ["https://example.com/a"]

    @pytest.mark.asyncio
    async def test_create_async_completion(self, api_key_credentials):
        config = PerplexityNodeConfig(
            config=PerplexityCreateAsyncCompletionConfig(
                model="sonar-deep-research", prompt="Write a deep report"
            ),
            credentials=api_key_credentials,
        )
        node = create_perplexity_node(config)
        mock_client = create_mock_client(200, {"request_id": "req_1", "status": "CREATED"})
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_async_completion"
        assert result["data"]["request_id"] == "req_1"

    @pytest.mark.asyncio
    async def test_list_async_completions(self, api_key_credentials):
        config = PerplexityNodeConfig(
            config=PerplexityListAsyncCompletionsConfig(),
            credentials=api_key_credentials,
        )
        node = create_perplexity_node(config)
        mock_client = create_mock_client(200, {"requests": [{"request_id": "req_1"}]})
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_async_completions"

    @pytest.mark.asyncio
    async def test_get_async_completion(self, api_key_credentials):
        config = PerplexityNodeConfig(
            config=PerplexityGetAsyncCompletionConfig(request_id="req_1"),
            credentials=api_key_credentials,
        )
        node = create_perplexity_node(config)
        mock_client = create_mock_client(200, {"request_id": "req_1", "status": "COMPLETED"})
        with patch("nodes.perplexity_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_async_completion"
        assert result["data"]["status"] == "COMPLETED"

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
