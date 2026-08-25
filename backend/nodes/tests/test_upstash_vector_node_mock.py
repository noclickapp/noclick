"""
Mock tests for the Upstash Vector node.

Verifies endpoint/body shaping (incl. namespace path segments and the
text-in server-side-embedding ops), config parsing, and error paths. No live API.
"""

import json

import pytest
from unittest.mock import Mock, patch

from nodes.upstash_vector_node import (
    UpstashVectorNode,
    UpstashVectorNodeConfig,
    UpstashVectorCredential,
    UpstashQueryConfig,
    UpstashQueryTextConfig,
    UpstashUpsertConfig,
    UpstashUpsertTextConfig,
    UpstashFetchConfig,
    UpstashDeleteConfig,
    UpstashInfoConfig,
    UpstashResetConfig,
    UpstashRangeConfig,
    UpstashUpdateConfig,
    UpstashUploadIndexConfig,
    _parse_json_list,
    _split_csv,
)
from unittest.mock import AsyncMock

BASE = "https://test-12345-us1-vector.upstash.io"


@pytest.fixture
def credentials():
    return UpstashVectorCredential(url=BASE, token="tok_test")


def create_node(config):
    return UpstashVectorNode(
        node_id="test-upstash-node",
        node_type="automation-upstash-vector",
        node_data={},
        config=config,
    )


def create_mock_response(status_code=200, json_data=None):
    resp = Mock()
    resp.status_code = status_code
    resp.content = b"{}" if json_data is None else json.dumps(json_data).encode()
    resp.json = Mock(return_value=json_data if json_data is not None else {})
    resp.text = "" if json_data is None else json.dumps(json_data)
    return resp


def create_capturing_client(status_code=200, json_data=None):
    response = create_mock_response(status_code, json_data)
    calls = []
    client = Mock()

    async def request(*args, **kwargs):
        calls.append(kwargs)
        return response

    client.request = request

    async def aenter(self):
        return client

    async def aexit(self, *a):
        return None

    client.__aenter__ = aenter
    client.__aexit__ = aexit
    return client, calls


def test_helpers():
    assert _parse_json_list("[1,2]") == [1, 2]
    assert _parse_json_list("x") is None
    assert _split_csv("a, b") == ["a", "b"]


@pytest.mark.asyncio
async def test_query(credentials):
    config = UpstashVectorNodeConfig(
        config=UpstashQueryConfig(vector="[0.1, 0.2]", top_k=3, filter="country = 'US'"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"result": []})
    with patch("nodes.upstash_vector_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/query"
    body = calls[-1]["json"]
    assert body["vector"] == [0.1, 0.2]
    assert body["topK"] == 3
    assert body["includeMetadata"] is True
    assert body["filter"] == "country = 'US'"


@pytest.mark.asyncio
async def test_query_namespace_path(credentials):
    config = UpstashVectorNodeConfig(
        config=UpstashQueryConfig(vector="[0.1]", namespace="docs"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"result": []})
    with patch("nodes.upstash_vector_node.httpx.AsyncClient", return_value=client):
        await node.execute({})
    assert calls[-1]["url"] == f"{BASE}/query/docs"


@pytest.mark.asyncio
async def test_query_text_uses_query_data_endpoint(credentials):
    config = UpstashVectorNodeConfig(
        config=UpstashQueryTextConfig(data="what is rag?", top_k=5),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"result": []})
    with patch("nodes.upstash_vector_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/query-data"
    assert calls[-1]["json"]["data"] == "what is rag?"


@pytest.mark.asyncio
async def test_upsert_sends_array_body(credentials):
    vectors = '[{"id": "a", "vector": [0.1], "metadata": {"k": "v"}}]'
    config = UpstashVectorNodeConfig(
        config=UpstashUpsertConfig(vectors=vectors), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"result": "Success"})
    with patch("nodes.upstash_vector_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/upsert"
    # Body is the array itself, not wrapped in an object.
    assert isinstance(calls[-1]["json"], list)
    assert calls[-1]["json"][0]["id"] == "a"


@pytest.mark.asyncio
async def test_upsert_text_uses_upsert_data_endpoint(credentials):
    items = '[{"id": "a", "data": "hello world"}]'
    config = UpstashVectorNodeConfig(
        config=UpstashUpsertTextConfig(items=items), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"result": "Success"})
    with patch("nodes.upstash_vector_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/upsert-data"
    assert calls[-1]["json"][0]["data"] == "hello world"


@pytest.mark.asyncio
async def test_upsert_malformed(credentials):
    config = UpstashVectorNodeConfig(
        config=UpstashUpsertConfig(vectors="nope"), credentials=credentials
    )
    node = create_node(config)
    result = await node.execute({})
    assert result["status"] == "error"
    assert "json array" in result["error"].lower()


@pytest.mark.asyncio
async def test_fetch(credentials):
    config = UpstashVectorNodeConfig(
        config=UpstashFetchConfig(ids="a, b"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"result": []})
    with patch("nodes.upstash_vector_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/fetch"
    assert calls[-1]["json"]["ids"] == ["a", "b"]


@pytest.mark.asyncio
async def test_delete(credentials):
    config = UpstashVectorNodeConfig(
        config=UpstashDeleteConfig(ids="a,b", namespace="ns"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"result": {"deleted": 2}})
    with patch("nodes.upstash_vector_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/delete/ns"
    assert calls[-1]["method"] == "DELETE"
    assert calls[-1]["json"]["ids"] == ["a", "b"]


@pytest.mark.asyncio
async def test_info(credentials):
    config = UpstashVectorNodeConfig(config=UpstashInfoConfig(), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, {"result": {"vectorCount": 10}})
    with patch("nodes.upstash_vector_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/info"
    assert calls[-1]["method"] == "GET"


@pytest.mark.asyncio
async def test_auth_header(credentials):
    headers = UpstashVectorNode._headers(credentials)
    assert headers["Authorization"] == "Bearer tok_test"


@pytest.mark.asyncio
async def test_missing_credentials_raises():
    config = UpstashVectorNodeConfig(config=UpstashInfoConfig(), credentials=None)
    node = create_node(config)
    with pytest.raises(ValueError, match="[Cc]redentials"):
        await node.execute({})


@pytest.mark.asyncio
async def test_upload_and_index_uses_upsert_data(credentials):
    config = UpstashVectorNodeConfig(
        config=UpstashUploadIndexConfig(document="res-id", namespace="ns"), credentials=credentials
    )
    node = create_node(config)
    fake_records = [
        {"id": "c0", "text": "chunk a", "metadata": {"source": "f.pdf", "chunk_index": 0}},
        {"id": "c1", "text": "chunk b", "metadata": {"source": "f.pdf", "chunk_index": 1}},
    ]
    client, calls = create_capturing_client(200, {"result": "Success"})
    with patch("nodes.upstash_vector_node.ingest_document_text", new=AsyncMock(return_value=(fake_records, {"filename": "f.pdf"}))), \
         patch("nodes.upstash_vector_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["chunks_indexed"] == 2
    # Text-in path → server-side embedding endpoint, with namespace path segment.
    assert calls[-1]["url"] == f"{BASE}/upsert-data/ns"
    assert calls[-1]["json"][0] == {"id": "c0", "data": "chunk a", "metadata": {"source": "f.pdf", "chunk_index": 0}}


@pytest.mark.asyncio
async def test_api_error_surfaced(credentials):
    config = UpstashVectorNodeConfig(
        config=UpstashQueryConfig(vector="[0.1]"), credentials=credentials
    )
    node = create_node(config)
    client, _ = create_capturing_client(401, {"error": "Invalid token"})
    with patch("nodes.upstash_vector_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 401
    assert "invalid token" in result["error"].lower()


# ── Bug fix: empty-list guards ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_empty_vector_rejected(credentials):
    """_parse_json_list('[]') returns [], which must be caught as invalid."""
    config = UpstashVectorNodeConfig(
        config=UpstashQueryConfig(vector="[]"), credentials=credentials
    )
    result = await create_node(config).execute({})
    assert result["status"] == "error"
    assert "non-empty" in result["error"]


@pytest.mark.asyncio
async def test_upsert_empty_array_rejected(credentials):
    config = UpstashVectorNodeConfig(
        config=UpstashUpsertConfig(vectors="[]"), credentials=credentials
    )
    result = await create_node(config).execute({})
    assert result["status"] == "error"
    assert "non-empty" in result["error"]


@pytest.mark.asyncio
async def test_upsert_text_empty_array_rejected(credentials):
    config = UpstashVectorNodeConfig(
        config=UpstashUpsertTextConfig(items="[]"), credentials=credentials
    )
    result = await create_node(config).execute({})
    assert result["status"] == "error"
    assert "non-empty" in result["error"]


# ── Bug fix: query_text includeVectors ───────────────────────────────────────

@pytest.mark.asyncio
async def test_query_text_sends_include_vectors(credentials):
    config = UpstashVectorNodeConfig(
        config=UpstashQueryTextConfig(data="hello", include_vectors="true"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"result": []})
    with patch("nodes.upstash_vector_node.httpx.AsyncClient", return_value=client):
        await node.execute({})
    assert calls[-1]["json"]["includeVectors"] is True


# ── New operations ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reset_default_namespace(credentials):
    config = UpstashVectorNodeConfig(config=UpstashResetConfig(), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, {"result": "Success"})
    with patch("nodes.upstash_vector_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/reset"
    assert calls[-1]["method"] == "DELETE"


@pytest.mark.asyncio
async def test_reset_named_namespace(credentials):
    config = UpstashVectorNodeConfig(config=UpstashResetConfig(namespace="archive"), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, {"result": "Success"})
    with patch("nodes.upstash_vector_node.httpx.AsyncClient", return_value=client):
        await node.execute({})
    assert calls[-1]["url"] == f"{BASE}/reset/archive"


@pytest.mark.asyncio
async def test_range_cursor_and_limit(credentials):
    config = UpstashVectorNodeConfig(
        config=UpstashRangeConfig(cursor="abc", limit=50, namespace="ns"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"result": {"nextCursor": "xyz", "vectors": []}})
    with patch("nodes.upstash_vector_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/range/ns"
    assert calls[-1]["json"]["cursor"] == "abc"
    assert calls[-1]["json"]["limit"] == 50


@pytest.mark.asyncio
async def test_update_metadata(credentials):
    config = UpstashVectorNodeConfig(
        config=UpstashUpdateConfig(id="vec-1", metadata='{"status": "processed"}'),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"result": "Updated"})
    with patch("nodes.upstash_vector_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/update"
    assert calls[-1]["json"] == {"id": "vec-1", "metadata": {"status": "processed"}}


@pytest.mark.asyncio
async def test_update_no_fields_rejected(credentials):
    config = UpstashVectorNodeConfig(
        config=UpstashUpdateConfig(id="vec-1"), credentials=credentials
    )
    result = await create_node(config).execute({})
    assert result["status"] == "error"
    assert "at least one" in result["error"]


@pytest.mark.asyncio
async def test_update_invalid_metadata_json(credentials):
    config = UpstashVectorNodeConfig(
        config=UpstashUpdateConfig(id="vec-1", metadata="not-json"), credentials=credentials
    )
    result = await create_node(config).execute({})
    assert result["status"] == "error"
    assert "json" in result["error"].lower()
