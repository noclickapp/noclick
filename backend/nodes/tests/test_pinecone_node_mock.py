"""
Mock tests for the Pinecone vector database node.

Exercises every operation with mocked HTTP (no live API calls), verifying the
ACTUAL request shaping the node produces — endpoints, bodies, params — plus
host resolution/caching, config parsing, dynamic options, and error paths.
"""

import json

import pytest
from unittest.mock import Mock, AsyncMock, patch

from nodes.pinecone_node import (
    PineconeNode,
    PineconeNodeConfig,
    PineconeAPIKeyCredential,
    PineconeQueryConfig,
    PineconeUpsertConfig,
    PineconeFetchConfig,
    PineconeDeleteConfig,
    PineconeUpdateVectorConfig,
    PineconeListVectorsConfig,
    PineconeDescribeIndexStatsConfig,
    PineconeListIndexesConfig,
    PineconeDescribeIndexConfig,
    PineconeCreateIndexConfig,
    PineconeConfigureIndexConfig,
    PineconeDeleteIndexConfig,
    PineconeCreateIndexForModelConfig,
    PineconeUpsertRecordsConfig,
    PineconeSearchRecordsConfig,
    PineconeGenerateEmbeddingsConfig,
    PineconeRerankConfig,
    PineconeStartImportConfig,
    PineconeListImportsConfig,
    PineconeDescribeImportConfig,
    PineconeCancelImportConfig,
    PineconeUploadIndexConfig,
    PINECONE_CONTROL_BASE,
    _parse_json_list,
    _parse_json_obj,
    _split_csv,
)


@pytest.fixture
def credentials():
    return PineconeAPIKeyCredential(api_key="pc_test_key")


def create_pinecone_node(config):
    return PineconeNode(
        node_id="test-pinecone-node",
        node_type="automation-pinecone",
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
    """A mocked httpx.AsyncClient that records every request's kwargs."""
    response = create_mock_response(status_code, json_data)
    calls = []
    client = Mock()

    async def request(*args, **kwargs):
        calls.append(kwargs)
        return response

    async def get(url, *args, **kwargs):
        calls.append({"method": "GET", "url": url, **kwargs})
        return response

    client.request = request
    client.get = get

    async def aenter(self):
        return client

    async def aexit(self, *a):
        return None

    client.__aenter__ = aenter
    client.__aexit__ = aexit
    return client, calls


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_parse_json_list_accepts_list_and_string():
    assert _parse_json_list([0.1, 0.2]) == [0.1, 0.2]
    assert _parse_json_list("[0.1, 0.2]") == [0.1, 0.2]
    assert _parse_json_list("") is None
    assert _parse_json_list(None) is None
    assert _parse_json_list("not json") is None
    assert _parse_json_list('{"a": 1}') is None  # object, not list


def test_parse_json_obj_accepts_dict_and_string():
    assert _parse_json_obj({"a": 1}) == {"a": 1}
    assert _parse_json_obj('{"a": 1}') == {"a": 1}
    assert _parse_json_obj("[1,2]") is None  # list, not object
    assert _parse_json_obj("") is None


def test_split_csv():
    assert _split_csv("a, b ,c") == ["a", "b", "c"]
    assert _split_csv("") == []
    assert _split_csv(None) == []


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_with_vector(credentials):
    config = PineconeNodeConfig(
        config=PineconeQueryConfig(
            index="docs", vector="[0.1, 0.2, 0.3]", top_k=5, namespace="ns1",
            filter='{"source": {"$eq": "a"}}',
        ),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="docs-abc.svc.pinecone.io")
    client, calls = create_capturing_client(200, {"matches": [{"id": "v1", "score": 0.9}]})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["data"]["matches"][0]["id"] == "v1"
    sent = calls[-1]
    assert sent["url"] == "https://docs-abc.svc.pinecone.io/query"
    body = sent["json"]
    assert body["vector"] == [0.1, 0.2, 0.3]
    assert body["topK"] == 5
    assert body["namespace"] == "ns1"
    assert body["includeMetadata"] is True
    assert body["filter"] == {"source": {"$eq": "a"}}


@pytest.mark.asyncio
async def test_query_by_id(credentials):
    config = PineconeNodeConfig(
        config=PineconeQueryConfig(index="docs", id="vec-42"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    client, calls = create_capturing_client(200, {"matches": []})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"]["id"] == "vec-42"
    assert "vector" not in calls[-1]["json"]


@pytest.mark.asyncio
async def test_query_requires_vector_or_id(credentials):
    config = PineconeNodeConfig(
        config=PineconeQueryConfig(index="docs"), credentials=credentials
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    result = await node.execute({})
    assert result["status"] == "error"
    assert "vector" in result["error"].lower()


@pytest.mark.asyncio
async def test_query_malformed_vector(credentials):
    config = PineconeNodeConfig(
        config=PineconeQueryConfig(index="docs", vector="not-a-json-array"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    result = await node.execute({})
    assert result["status"] == "error"
    assert "json array" in result["error"].lower()


# ---------------------------------------------------------------------------
# Upsert / Fetch / Delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert(credentials):
    vectors = '[{"id": "a", "values": [0.1, 0.2], "metadata": {"src": "doc"}}]'
    config = PineconeNodeConfig(
        config=PineconeUpsertConfig(index="docs", vectors=vectors, namespace="ns"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    client, calls = create_capturing_client(200, {"upsertedCount": 1})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == "https://h.pinecone.io/vectors/upsert"
    body = calls[-1]["json"]
    assert body["vectors"][0]["id"] == "a"
    assert body["namespace"] == "ns"


@pytest.mark.asyncio
async def test_upsert_malformed(credentials):
    config = PineconeNodeConfig(
        config=PineconeUpsertConfig(index="docs", vectors="oops"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    result = await node.execute({})
    assert result["status"] == "error"
    assert "json array" in result["error"].lower()


@pytest.mark.asyncio
async def test_fetch(credentials):
    config = PineconeNodeConfig(
        config=PineconeFetchConfig(index="docs", ids="a, b, c", namespace="ns"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    client, calls = create_capturing_client(200, {"vectors": {}})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == "https://h.pinecone.io/vectors/fetch"
    assert calls[-1]["params"]["ids"] == ["a", "b", "c"]
    assert calls[-1]["params"]["namespace"] == "ns"


@pytest.mark.asyncio
async def test_fetch_requires_ids(credentials):
    config = PineconeNodeConfig(
        config=PineconeFetchConfig(index="docs", ids=" , "), credentials=credentials
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    result = await node.execute({})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_delete_by_ids(credentials):
    config = PineconeNodeConfig(
        config=PineconeDeleteConfig(index="docs", ids="a,b"), credentials=credentials
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    client, calls = create_capturing_client(200, {})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"]["ids"] == ["a", "b"]


@pytest.mark.asyncio
async def test_delete_all(credentials):
    config = PineconeNodeConfig(
        config=PineconeDeleteConfig(index="docs", delete_all="true", namespace="ns"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    client, calls = create_capturing_client(200, {})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"]["deleteAll"] is True


@pytest.mark.asyncio
async def test_delete_requires_target(credentials):
    config = PineconeNodeConfig(
        config=PineconeDeleteConfig(index="docs"), credentials=credentials
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    result = await node.execute({})
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Index management (control plane)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_indexes(credentials):
    config = PineconeNodeConfig(
        config=PineconeListIndexesConfig(), credentials=credentials
    )
    node = create_pinecone_node(config)
    client, calls = create_capturing_client(200, {"indexes": [{"name": "docs"}]})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["indexes"][0]["name"] == "docs"
    assert calls[-1]["url"] == f"{PINECONE_CONTROL_BASE}/indexes"


@pytest.mark.asyncio
async def test_create_index(credentials):
    config = PineconeNodeConfig(
        config=PineconeCreateIndexConfig(
            name="docs", dimension=1536, metric="cosine", cloud="aws", region="us-east-1"
        ),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    client, calls = create_capturing_client(201, {"name": "docs"})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert body["name"] == "docs"
    assert body["dimension"] == 1536
    assert body["spec"]["serverless"] == {"cloud": "aws", "region": "us-east-1"}


# ---------------------------------------------------------------------------
# Host resolution + caching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_host_caches(credentials):
    config = PineconeNodeConfig(
        config=PineconeListIndexesConfig(), credentials=credentials
    )
    node = create_pinecone_node(config)
    client, calls = create_capturing_client(200, {"host": "docs-x.svc.pinecone.io"})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        host1 = await node._resolve_host("docs", "pc_test_key")
        host2 = await node._resolve_host("docs", "pc_test_key")
    assert host1 == host2 == "docs-x.svc.pinecone.io"
    # Second call served from cache — only one control-plane GET.
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_resolve_host_error_returns_error_dict(credentials):
    config = PineconeNodeConfig(
        config=PineconeQueryConfig(index="missing", vector="[0.1]"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    client, _ = create_capturing_client(404, {"error": "not found"})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 404


# ---------------------------------------------------------------------------
# Credentials + dynamic options
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_credentials_raises():
    config = PineconeNodeConfig(
        config=PineconeListIndexesConfig(), credentials=None
    )
    node = create_pinecone_node(config)
    with pytest.raises(ValueError, match="[Cc]redentials"):
        await node.execute({})


@pytest.mark.asyncio
async def test_load_field_options_lists_indexes():
    client, _ = create_capturing_client(
        200, {"indexes": [{"name": "docs", "host": "h", "dimension": 1536}, {"name": "other"}]}
    )
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        options = await PineconeNode.load_field_options(
            field_name="index", credential_data={"api_key": "pc_test_key"}
        )
    assert {o["value"] for o in options} == {"docs", "other"}
    docs = next(o for o in options if o["value"] == "docs")
    assert docs["metadata"]["dimension"] == 1536


@pytest.mark.asyncio
async def test_upload_and_index(credentials):
    config = PineconeNodeConfig(
        config=PineconeUploadIndexConfig(index="docs", document="res-id", namespace="ns"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="docs-abc.svc.pinecone.io")
    fake_records = [
        {"id": "c0", "values": [0.1, 0.2], "metadata": {"text": "chunk a", "source": "f.pdf", "chunk_index": 0}},
        {"id": "c1", "values": [0.3, 0.4], "metadata": {"text": "chunk b", "source": "f.pdf", "chunk_index": 1}},
    ]
    client, calls = create_capturing_client(200, {"upsertedCount": 2})
    with patch("nodes.pinecone_node.ingest_document", new=AsyncMock(return_value=(fake_records, {"filename": "f.pdf"}))), \
         patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["chunks_indexed"] == 2
    assert calls[-1]["url"] == "https://docs-abc.svc.pinecone.io/vectors/upsert"
    body = calls[-1]["json"]
    assert body["vectors"][0] == fake_records[0]
    assert body["namespace"] == "ns"


@pytest.mark.asyncio
async def test_upload_and_index_no_text(credentials):
    config = PineconeNodeConfig(
        config=PineconeUploadIndexConfig(index="docs", document="res-id"), credentials=credentials
    )
    node = create_pinecone_node(config)
    with patch("nodes.pinecone_node.ingest_document", new=AsyncMock(return_value=([], {"filename": "empty.txt"}))):
        result = await node.execute({})
    assert result["status"] == "error"
    assert "no text" in result["error"].lower()


@pytest.mark.asyncio
async def test_load_field_options_search_filter():
    client, _ = create_capturing_client(
        200, {"indexes": [{"name": "docs"}, {"name": "images"}]}
    )
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        options = await PineconeNode.load_field_options(
            field_name="index", credential_data={"api_key": "k"}, search="imag"
        )
    assert [o["value"] for o in options] == ["images"]


# ---------------------------------------------------------------------------
# Update Vector
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_vector_values(credentials):
    config = PineconeNodeConfig(
        config=PineconeUpdateVectorConfig(index="docs", id="v1", values="[0.9, 0.8]", namespace="ns"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    client, calls = create_capturing_client(200, {})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == "https://h.pinecone.io/vectors/update"
    body = calls[-1]["json"]
    assert body["id"] == "v1"
    assert body["values"] == [0.9, 0.8]
    assert body["namespace"] == "ns"


@pytest.mark.asyncio
async def test_update_vector_metadata(credentials):
    config = PineconeNodeConfig(
        config=PineconeUpdateVectorConfig(index="docs", id="v1", set_metadata='{"source": "v2"}'),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    client, calls = create_capturing_client(200, {})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"]["setMetadata"] == {"source": "v2"}


@pytest.mark.asyncio
async def test_update_vector_requires_at_least_one_field(credentials):
    config = PineconeNodeConfig(
        config=PineconeUpdateVectorConfig(index="docs", id="v1"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    result = await node.execute({})
    assert result["status"] == "error"
    assert "values" in result["error"].lower() or "metadata" in result["error"].lower()


# ---------------------------------------------------------------------------
# List Vectors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_vectors(credentials):
    config = PineconeNodeConfig(
        config=PineconeListVectorsConfig(index="docs", namespace="ns", prefix="chunk-", limit=50),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    client, calls = create_capturing_client(200, {"vectors": [{"id": "chunk-0"}]})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == "https://h.pinecone.io/vectors/list"
    assert calls[-1]["params"]["namespace"] == "ns"
    assert calls[-1]["params"]["prefix"] == "chunk-"
    assert calls[-1]["params"]["limit"] == 50


# ---------------------------------------------------------------------------
# Describe Index Stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_index_stats(credentials):
    config = PineconeNodeConfig(
        config=PineconeDescribeIndexStatsConfig(index="docs"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    client, calls = create_capturing_client(200, {"totalVectorCount": 42, "namespaces": {}})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["totalVectorCount"] == 42
    assert calls[-1]["url"] == "https://h.pinecone.io/describe_index_stats"


@pytest.mark.asyncio
async def test_describe_index_stats_with_filter(credentials):
    config = PineconeNodeConfig(
        config=PineconeDescribeIndexStatsConfig(index="docs", filter='{"source": {"$eq": "web"}}'),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    client, calls = create_capturing_client(200, {"totalVectorCount": 10})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"]["filter"] == {"source": {"$eq": "web"}}


# ---------------------------------------------------------------------------
# Describe / Configure / Delete Index
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_index(credentials):
    config = PineconeNodeConfig(
        config=PineconeDescribeIndexConfig(index="docs"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    client, calls = create_capturing_client(200, {"name": "docs", "host": "h.pinecone.io", "dimension": 1536})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["name"] == "docs"
    assert calls[-1]["url"] == f"{PINECONE_CONTROL_BASE}/indexes/docs"


@pytest.mark.asyncio
async def test_configure_index_deletion_protection(credentials):
    config = PineconeNodeConfig(
        config=PineconeConfigureIndexConfig(index="docs", deletion_protection="enabled"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    client, calls = create_capturing_client(200, {"name": "docs"})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{PINECONE_CONTROL_BASE}/indexes/docs"
    assert calls[-1]["json"]["deletion_protection"] == "enabled"


@pytest.mark.asyncio
async def test_configure_index_requires_at_least_one_change(credentials):
    config = PineconeNodeConfig(
        config=PineconeConfigureIndexConfig(index="docs"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    result = await node.execute({})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_delete_index(credentials):
    config = PineconeNodeConfig(
        config=PineconeDeleteIndexConfig(index="old-index"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    client, calls = create_capturing_client(202, None)
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{PINECONE_CONTROL_BASE}/indexes/old-index"


# ---------------------------------------------------------------------------
# Integrated inference (text-native)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_index_for_model(credentials):
    config = PineconeNodeConfig(
        config=PineconeCreateIndexForModelConfig(
            name="text-idx", embed_model="multilingual-e5-large",
            field_map_text="text", cloud="aws", region="us-east-1"
        ),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    client, calls = create_capturing_client(201, {"name": "text-idx"})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert body["name"] == "text-idx"
    assert body["cloud"] == "aws"
    assert body["region"] == "us-east-1"
    assert body["embed"]["model"] == "multilingual-e5-large"
    assert body["embed"]["field_map"]["text"] == "text"
    assert "spec" not in body
    assert calls[-1]["url"] == f"{PINECONE_CONTROL_BASE}/indexes/create-for-model"


@pytest.mark.asyncio
async def test_upsert_records(credentials):
    records = '[{"id": "r1", "text": "Hello world"}, {"id": "r2", "text": "Foo bar"}]'
    config = PineconeNodeConfig(
        config=PineconeUpsertRecordsConfig(index="text-idx", namespace="ns1", records=records),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    client, calls = create_capturing_client(200, {"upsertedCount": 2})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == "https://h.pinecone.io/records/namespaces/ns1/upsert"
    # Body is ndjson bytes
    ndjson = calls[-1]["content"].decode()
    lines = ndjson.strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["id"] == "r1"


@pytest.mark.asyncio
async def test_upsert_records_malformed(credentials):
    config = PineconeNodeConfig(
        config=PineconeUpsertRecordsConfig(index="text-idx", namespace="ns", records="not json"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    result = await node.execute({})
    assert result["status"] == "error"
    assert "json array" in result["error"].lower()


@pytest.mark.asyncio
async def test_search_records(credentials):
    config = PineconeNodeConfig(
        config=PineconeSearchRecordsConfig(
            index="text-idx", namespace="ns1", query_text="hello", top_k=5
        ),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    client, calls = create_capturing_client(200, {"result": {"hits": []}})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert body["query"]["inputs"]["text"] == "hello"
    assert body["query"]["top_k"] == 5
    assert calls[-1]["url"] == "https://h.pinecone.io/records/namespaces/ns1/search"


@pytest.mark.asyncio
async def test_search_records_with_rerank(credentials):
    config = PineconeNodeConfig(
        config=PineconeSearchRecordsConfig(
            index="text-idx", namespace="ns1", query_text="cats", top_k=10,
            rerank_model="bge-reranker-v2-m3", rerank_top_n=3
        ),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    client, calls = create_capturing_client(200, {"result": {"hits": []}})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert body["rerank"]["model"] == "bge-reranker-v2-m3"
    assert body["rerank"]["top_n"] == 3
    assert body["rerank"]["query"] == "cats"


# ---------------------------------------------------------------------------
# Inference API — embeddings + rerank
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_embeddings(credentials):
    config = PineconeNodeConfig(
        config=PineconeGenerateEmbeddingsConfig(
            model="multilingual-e5-large",
            inputs='["Hello world", "Foo bar"]',
            input_type="passage",
        ),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    client, calls = create_capturing_client(200, {"data": [{"values": [0.1, 0.2]}, {"values": [0.3, 0.4]}]})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert body["model"] == "multilingual-e5-large"
    assert body["inputs"] == [{"text": "Hello world"}, {"text": "Foo bar"}]
    assert body["parameters"]["input_type"] == "passage"
    assert calls[-1]["url"] == f"{PINECONE_CONTROL_BASE}/embed"


@pytest.mark.asyncio
async def test_generate_embeddings_malformed_inputs(credentials):
    config = PineconeNodeConfig(
        config=PineconeGenerateEmbeddingsConfig(model="multilingual-e5-large", inputs="not json"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    result = await node.execute({})
    assert result["status"] == "error"
    assert "json array" in result["error"].lower()


@pytest.mark.asyncio
async def test_rerank(credentials):
    docs = '["The cat sat on a mat", "Dogs are great pets"]'
    config = PineconeNodeConfig(
        config=PineconeRerankConfig(
            model="bge-reranker-v2-m3", query="cats at home",
            documents=docs, top_n=1,
        ),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    client, calls = create_capturing_client(200, {"data": [{"index": 0, "score": 0.9}]})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert body["model"] == "bge-reranker-v2-m3"
    assert body["query"] == "cats at home"
    assert body["documents"] == [{"text": "The cat sat on a mat"}, {"text": "Dogs are great pets"}]
    assert body["top_n"] == 1
    assert calls[-1]["url"] == f"{PINECONE_CONTROL_BASE}/rerank"


@pytest.mark.asyncio
async def test_rerank_with_rank_fields(credentials):
    docs = '[{"title": "Cat article", "body": "Cats are great"}, {"title": "Dog article", "body": "Dogs too"}]'
    config = PineconeNodeConfig(
        config=PineconeRerankConfig(
            model="bge-reranker-v2-m3", query="cats",
            documents=docs, rank_fields="title, body",
        ),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    client, calls = create_capturing_client(200, {"data": []})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"]["rank_fields"] == ["title", "body"]


# ---------------------------------------------------------------------------
# Bulk import
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_import(credentials):
    config = PineconeNodeConfig(
        config=PineconeStartImportConfig(index="docs", uri="s3://my-bucket/data.parquet", error_mode="continue"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    client, calls = create_capturing_client(200, {"id": "imp-123"})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == "https://h.pinecone.io/bulk/imports"
    body = calls[-1]["json"]
    assert body["uri"] == "s3://my-bucket/data.parquet"
    assert body["errorMode"] == {"onError": "continue"}


@pytest.mark.asyncio
async def test_list_imports(credentials):
    config = PineconeNodeConfig(
        config=PineconeListImportsConfig(index="docs", limit=5),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    client, calls = create_capturing_client(200, {"imports": []})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == "https://h.pinecone.io/bulk/imports"
    assert calls[-1]["params"]["limit"] == 5


@pytest.mark.asyncio
async def test_describe_import(credentials):
    config = PineconeNodeConfig(
        config=PineconeDescribeImportConfig(index="docs", import_id="imp-123"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    client, calls = create_capturing_client(200, {"id": "imp-123", "status": "Completed"})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == "https://h.pinecone.io/bulk/imports/imp-123"


@pytest.mark.asyncio
async def test_cancel_import(credentials):
    config = PineconeNodeConfig(
        config=PineconeCancelImportConfig(index="docs", import_id="imp-456"),
        credentials=credentials,
    )
    node = create_pinecone_node(config)
    node._resolve_host = AsyncMock(return_value="h.pinecone.io")
    client, calls = create_capturing_client(200, {})
    with patch("nodes.pinecone_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == "https://h.pinecone.io/bulk/imports/imp-456"
