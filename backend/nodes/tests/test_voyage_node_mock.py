"""
Mock tests for the Voyage AI embedding and reranking node.

Exercises all operations with mocked HTTP calls (no live API):
- Credential model shape
- Config discriminator (embed / rerank)
- execute(): embed single string, embed array, rerank with top_k
- Error propagation from the API
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from nodes.voyage_node import (
    VoyageNode,
    VoyageNodeConfig,
    VoyageAPIKeyCredential,
    VoyageEmbedConfig,
    VoyageRerankConfig,
    _voyage_request,
    _voyage_upload_file,
)

FAKE_KEY = "pa-test-fake-key"
EMBED_VECTOR = [0.1] * 1024


def make_creds():
    return VoyageAPIKeyCredential(api_key=FAKE_KEY)


def make_node(op_config):
    return VoyageNode(
        node_id="test-voyage",
        node_type="automation-voyage",
        node_data={},
        config=VoyageNodeConfig(config=op_config, credentials=make_creds()),
        sio=Mock(),
        sid="sid",
        workflow_id="wf",
        user_id="user",
    )


def embed_api_response(count=1, dims=1024):
    return {
        "status": "success",
        "action": "embed",
        "data": {
            "object": "list",
            "data": [{"object": "embedding", "embedding": [0.1] * dims, "index": i} for i in range(count)],
            "model": "voyage-3-large",
            "usage": {"total_tokens": 10 * count},
        },
        "status_code": 200,
        "timing_ms": {"api": 120.0},
    }


def rerank_api_response(n_docs=3):
    return {
        "status": "success",
        "action": "rerank",
        "data": {
            "object": "list",
            "data": [
                {"relevance_score": 0.9 - i * 0.1, "index": i, "document": {"text": f"doc {i}"}}
                for i in range(n_docs)
            ],
            "model": "rerank-2",
            "usage": {"total_tokens": 50},
        },
        "status_code": 200,
        "timing_ms": {"api": 80.0},
    }


def _async_context(value):
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=value)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


# ---------------------------------------------------------------------------
# Credential & config model
# ---------------------------------------------------------------------------

class TestCredential:
    def test_credential_type(self):
        cred = make_creds()
        assert cred.credential_type == "voyage_api_key"
        assert cred.api_key == FAKE_KEY

    def test_embed_config_defaults(self):
        c = VoyageEmbedConfig(input="hello")
        assert c.operation == "embed"
        assert c.model == "voyage-4-large"
        assert c.output_dtype == "float"
        assert c.truncation == "true"
        assert c.input_type is None

    def test_rerank_config_defaults(self):
        c = VoyageRerankConfig(query="q", documents='["a","b"]')
        assert c.operation == "rerank"
        assert c.model == "rerank-2.5"
        assert c.return_documents == "true"
        assert c.top_k is None


@pytest.mark.asyncio
async def test_json_request_refuses_redirects():
    response = MagicMock(status=200)
    response.text = AsyncMock(return_value='{"ok": true}')
    session = MagicMock()
    session.request.return_value = _async_context(response)

    with patch(
        "nodes.voyage_node.aiohttp.ClientSession",
        return_value=_async_context(session),
    ):
        result = await _voyage_request(
            FAKE_KEY,
            "POST",
            "/embeddings",
            body={"input": ["hello"]},
        )

    assert result["status"] == "success"
    assert session.request.call_args.kwargs["allow_redirects"] is False


@pytest.mark.asyncio
async def test_file_upload_refuses_redirects():
    response = MagicMock(status=200)
    response.json = AsyncMock(return_value={"id": "file-1"})
    session = MagicMock()
    session.post.return_value = _async_context(response)

    with patch(
        "nodes.voyage_node.aiohttp.ClientSession",
        return_value=_async_context(session),
    ):
        result = await _voyage_upload_file(FAKE_KEY, '{"input":"hello"}\n', "batch.jsonl")

    assert result["status"] == "success"
    assert session.post.call_args.kwargs["allow_redirects"] is False


# ---------------------------------------------------------------------------
# execute(): embed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_embed_single_string():
    node = make_node(VoyageEmbedConfig(input="Hello world", model="voyage-3"))
    with patch("nodes.voyage_node._voyage_request", new=AsyncMock(return_value=embed_api_response(count=1))):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["count"] == 1
    assert result["data"]["dimensions"] == 1024
    assert len(result["data"]["embeddings"][0]) == 1024
    assert result["data"]["total_tokens"] == 10


@pytest.mark.asyncio
async def test_embed_json_array():
    node = make_node(VoyageEmbedConfig(input='["doc one", "doc two", "doc three"]'))
    with patch("nodes.voyage_node._voyage_request", new=AsyncMock(return_value=embed_api_response(count=3))):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["count"] == 3
    assert len(result["data"]["embeddings"]) == 3


@pytest.mark.asyncio
async def test_embed_with_input_type_and_dimension():
    node = make_node(VoyageEmbedConfig(
        input="query text",
        input_type="query",
        output_dimension=256,
        model="voyage-3-large",
    ))
    mock_resp = embed_api_response(count=1, dims=256)
    with patch("nodes.voyage_node._voyage_request", new=AsyncMock(return_value=mock_resp)) as m:
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["dimensions"] == 256
    # Verify body sent to API included input_type and output_dimension
    call_body = m.call_args.kwargs["body"]
    assert call_body["input_type"] == "query"
    assert call_body["output_dimension"] == 256


@pytest.mark.asyncio
async def test_embed_invalid_json_array_raises():
    node = make_node(VoyageEmbedConfig(input='[not valid json'))
    with pytest.raises(ValueError, match="not valid JSON"):
        await node.execute({})


@pytest.mark.asyncio
async def test_embed_api_error_propagated():
    node = make_node(VoyageEmbedConfig(input="hello"))
    error_resp = {
        "status": "error",
        "action": "embed",
        "error": "Voyage AI error (401): Unauthorized",
        "status_code": 401,
        "timing_ms": {"api": 50.0},
    }
    with patch("nodes.voyage_node._voyage_request", new=AsyncMock(return_value=error_resp)):
        result = await node.execute({})
    assert result["status"] == "error"
    assert "401" in result["error"]


# ---------------------------------------------------------------------------
# execute(): rerank
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rerank_basic():
    node = make_node(VoyageRerankConfig(
        query="What is AI?",
        documents='["AI is smart", "Paris is a city", "ML is AI subset"]',
    ))
    with patch("nodes.voyage_node._voyage_request", new=AsyncMock(return_value=rerank_api_response(n_docs=3))):
        result = await node.execute({})
    assert result["status"] == "success"
    assert len(result["data"]["results"]) == 3
    assert result["data"]["results"][0]["relevance_score"] == pytest.approx(0.9)
    assert result["data"]["total_tokens"] == 50


@pytest.mark.asyncio
async def test_rerank_top_k_sent_in_body():
    node = make_node(VoyageRerankConfig(
        query="capital of France",
        documents='["Paris", "Berlin", "London"]',
        top_k=2,
        return_documents="false",
    ))
    with patch("nodes.voyage_node._voyage_request", new=AsyncMock(return_value=rerank_api_response(n_docs=2))) as m:
        await node.execute({})
    call_body = m.call_args.kwargs["body"]
    assert call_body["top_k"] == 2
    assert call_body["return_documents"] is False


@pytest.mark.asyncio
async def test_rerank_invalid_json_raises():
    node = make_node(VoyageRerankConfig(
        query="q",
        documents="not a list",
    ))
    with pytest.raises(ValueError, match="not valid JSON"):
        await node.execute({})


# ---------------------------------------------------------------------------
# Missing credentials guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_credentials_raises():
    node = VoyageNode(
        node_id="test",
        node_type="automation-voyage",
        node_data={},
        config=VoyageNodeConfig(config=VoyageEmbedConfig(input="hi"), credentials=None),
        sio=Mock(), sid="sid", workflow_id="wf", user_id="user",
    )
    with pytest.raises(ValueError, match="Credentials are required"):
        await node.execute({})


# ---------------------------------------------------------------------------
# Schema smoke test
# ---------------------------------------------------------------------------

def test_schema_has_two_operations():
    schema = VoyageNode.get_config_schema()
    text = json.dumps(schema)
    assert '"embed"' in text
    assert '"rerank"' in text


def test_schema_has_model_enums():
    schema = VoyageNode.get_config_schema()
    text = json.dumps(schema)
    assert "voyage-3-large" in text
    assert "rerank-2" in text


def test_node_type():
    assert VoyageNode.get_config_model() is VoyageNodeConfig
