"""
Mock tests for the Qdrant vector database node.

Verifies the actual request shaping (endpoints, bodies, params), point-ID
coercion, config parsing, dynamic options, and error paths — no live API.
"""

import json

import pytest
from unittest.mock import Mock, AsyncMock, patch

from nodes.qdrant_node import (
    QdrantNode,
    QdrantNodeConfig,
    QdrantCredential,
    QdrantQueryConfig,
    QdrantUpsertConfig,
    QdrantRetrieveConfig,
    QdrantDeleteConfig,
    QdrantScrollConfig,
    QdrantCountConfig,
    QdrantRecommendConfig,
    QdrantListCollectionsConfig,
    QdrantGetCollectionConfig,
    QdrantCreateCollectionConfig,
    QdrantUpdateCollectionConfig,
    QdrantDeleteCollectionConfig,
    QdrantSetPayloadConfig,
    QdrantDeletePayloadConfig,
    QdrantClearPayloadConfig,
    QdrantCreatePayloadIndexConfig,
    QdrantDeletePayloadIndexConfig,
    QdrantUploadIndexConfig,
    _parse_json_list,
    _parse_json_obj,
    _coerce_point_ids,
)

BASE = "https://test.qdrant.io:6333"


@pytest.fixture
def credentials():
    return QdrantCredential(url=BASE, api_key="qk_test")


def create_qdrant_node(config):
    return QdrantNode(
        node_id="test-qdrant-node",
        node_type="automation-qdrant",
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


def test_parse_helpers():
    assert _parse_json_list("[1,2]") == [1, 2]
    assert _parse_json_list("nope") is None
    assert _parse_json_obj('{"a":1}') == {"a": 1}
    assert _parse_json_obj("[1]") is None


def test_coerce_point_ids():
    assert _coerce_point_ids("1, 2, 3") == [1, 2, 3]
    assert _coerce_point_ids("a1b2-uuid, 5") == ["a1b2-uuid", 5]
    assert _coerce_point_ids("") == []
    assert _coerce_point_ids(None) == []


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query(credentials):
    config = QdrantNodeConfig(
        config=QdrantQueryConfig(
            collection="docs", vector="[0.1, 0.2]", limit=5,
            filter='{"must": [{"key": "k", "match": {"value": "v"}}]}',
        ),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": {"points": [{"id": 1, "score": 0.9}]}})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    sent = calls[-1]
    assert sent["url"] == f"{BASE}/collections/docs/points/query"
    assert sent["json"]["query"] == [0.1, 0.2]
    assert sent["json"]["limit"] == 5
    assert sent["json"]["with_payload"] is True
    assert sent["json"]["filter"]["must"][0]["key"] == "k"


@pytest.mark.asyncio
async def test_query_malformed_vector(credentials):
    config = QdrantNodeConfig(
        config=QdrantQueryConfig(collection="docs", vector="oops"), credentials=credentials
    )
    node = create_qdrant_node(config)
    result = await node.execute({})
    assert result["status"] == "error"
    assert "json array" in result["error"].lower()


# ---------------------------------------------------------------------------
# Upsert / Retrieve / Delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_passes_wait(credentials):
    points = '[{"id": 1, "vector": [0.1, 0.2], "payload": {"src": "doc"}}]'
    config = QdrantNodeConfig(
        config=QdrantUpsertConfig(collection="docs", points=points), credentials=credentials
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": {"status": "completed"}})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/collections/docs/points"
    assert calls[-1]["method"] == "PUT"
    assert calls[-1]["params"] == {"wait": "true"}
    assert calls[-1]["json"]["points"][0]["id"] == 1


@pytest.mark.asyncio
async def test_retrieve(credentials):
    config = QdrantNodeConfig(
        config=QdrantRetrieveConfig(collection="docs", ids="1, 2"), credentials=credentials
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": []})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/collections/docs/points"
    assert calls[-1]["json"]["ids"] == [1, 2]


@pytest.mark.asyncio
async def test_delete_by_ids(credentials):
    config = QdrantNodeConfig(
        config=QdrantDeleteConfig(collection="docs", ids="1,2"), credentials=credentials
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": {"status": "completed"}})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/collections/docs/points/delete"
    assert calls[-1]["json"]["points"] == [1, 2]


@pytest.mark.asyncio
async def test_delete_by_filter(credentials):
    config = QdrantNodeConfig(
        config=QdrantDeleteConfig(collection="docs", filter='{"must": []}'),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": {}})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert "filter" in calls[-1]["json"]


@pytest.mark.asyncio
async def test_delete_requires_target(credentials):
    config = QdrantNodeConfig(
        config=QdrantDeleteConfig(collection="docs"), credentials=credentials
    )
    node = create_qdrant_node(config)
    result = await node.execute({})
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Collection management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_collections(credentials):
    config = QdrantNodeConfig(config=QdrantListCollectionsConfig(), credentials=credentials)
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": {"collections": [{"name": "docs"}]}})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/collections"


@pytest.mark.asyncio
async def test_create_collection(credentials):
    config = QdrantNodeConfig(
        config=QdrantCreateCollectionConfig(name="docs", size=1536, distance="Cosine"),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": True})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/collections/docs"
    assert calls[-1]["json"]["vectors"] == {"size": 1536, "distance": "Cosine"}


# ---------------------------------------------------------------------------
# Auth header + credentials + dynamic options
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_key_header_sent(credentials):
    config = QdrantNodeConfig(config=QdrantListCollectionsConfig(), credentials=credentials)
    node = create_qdrant_node(config)
    headers = node._headers(credentials)
    assert headers["api-key"] == "qk_test"


def test_api_key_always_in_header():
    cred = QdrantCredential(url=BASE, api_key="another-key")
    headers = QdrantNode._headers(cred)
    assert headers["api-key"] == "another-key"


@pytest.mark.asyncio
async def test_missing_credentials_raises():
    config = QdrantNodeConfig(config=QdrantListCollectionsConfig(), credentials=None)
    node = create_qdrant_node(config)
    with pytest.raises(ValueError, match="[Cc]redentials"):
        await node.execute({})


@pytest.mark.asyncio
async def test_load_field_options_lists_collections():
    client, _ = create_capturing_client(
        200, {"result": {"collections": [{"name": "docs"}, {"name": "images"}]}}
    )
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        options = await QdrantNode.load_field_options(
            field_name="collection", credential_data={"url": BASE, "api_key": "k"}
        )
    assert {o["value"] for o in options} == {"docs", "images"}


@pytest.mark.asyncio
async def test_upload_and_index(credentials):
    config = QdrantNodeConfig(
        config=QdrantUploadIndexConfig(collection="docs", document="res-id"), credentials=credentials
    )
    node = create_qdrant_node(config)
    fake_records = [
        {"id": "u0", "values": [0.1, 0.2], "metadata": {"text": "a", "source": "f.pdf", "chunk_index": 0}},
    ]
    client, calls = create_capturing_client(200, {"result": {"status": "completed"}})
    with patch("nodes.qdrant_node.ingest_document", new=AsyncMock(return_value=(fake_records, {"filename": "f.pdf"}))), \
         patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["chunks_indexed"] == 1
    assert calls[-1]["url"] == f"{BASE}/collections/docs/points"
    assert calls[-1]["params"] == {"wait": "true"}
    assert calls[-1]["json"]["points"][0] == {"id": "u0", "vector": [0.1, 0.2], "payload": {"text": "a", "source": "f.pdf", "chunk_index": 0}}


@pytest.mark.asyncio
async def test_api_error_surfaced(credentials):
    config = QdrantNodeConfig(
        config=QdrantQueryConfig(collection="docs", vector="[0.1]"), credentials=credentials
    )
    node = create_qdrant_node(config)
    client, _ = create_capturing_client(404, {"status": {"error": "Not found"}})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 404
    assert "not found" in result["error"].lower()


# ---------------------------------------------------------------------------
# Scroll
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scroll_basic(credentials):
    config = QdrantNodeConfig(
        config=QdrantScrollConfig(collection="docs", limit=5),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": {"points": [], "next_page_offset": None}})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/collections/docs/points/scroll"
    assert calls[-1]["json"]["limit"] == 5
    assert calls[-1]["json"]["with_payload"] is True
    assert calls[-1]["json"]["with_vector"] is False


@pytest.mark.asyncio
async def test_scroll_with_filter_and_offset(credentials):
    config = QdrantNodeConfig(
        config=QdrantScrollConfig(
            collection="docs", limit=10, offset="42",
            filter='{"must": [{"key": "status", "match": {"value": "ok"}}]}',
            order_by="created_at",
        ),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": {"points": []}})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert body["offset"] == 42  # numeric string coerced to int
    assert "filter" in body
    assert body["order_by"] == "created_at"


# ---------------------------------------------------------------------------
# Count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_all(credentials):
    config = QdrantNodeConfig(
        config=QdrantCountConfig(collection="docs"),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": {"count": 100}})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/collections/docs/points/count"
    assert calls[-1]["json"]["exact"] is True


@pytest.mark.asyncio
async def test_count_with_filter(credentials):
    config = QdrantNodeConfig(
        config=QdrantCountConfig(collection="docs", filter='{"must": []}', exact="false"),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": {"count": 5}})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"]["exact"] is False
    assert "filter" in calls[-1]["json"]


# ---------------------------------------------------------------------------
# Recommend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend(credentials):
    config = QdrantNodeConfig(
        config=QdrantRecommendConfig(
            collection="docs", positive="[1, 2]", negative="[3]", limit=5,
            strategy="best_score",
        ),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": [{"id": 10, "score": 0.8}]})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/collections/docs/points/recommend"
    body = calls[-1]["json"]
    assert body["positive"] == [1, 2]
    assert body["negative"] == [3]
    assert body["limit"] == 5
    assert body["strategy"] == "best_score"


@pytest.mark.asyncio
async def test_recommend_malformed_positive(credentials):
    config = QdrantNodeConfig(
        config=QdrantRecommendConfig(collection="docs", positive="oops"),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    result = await node.execute({})
    assert result["status"] == "error"
    assert "positive" in result["error"].lower()


# ---------------------------------------------------------------------------
# Collection CRUD — get / update / delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_collection(credentials):
    config = QdrantNodeConfig(
        config=QdrantGetCollectionConfig(collection="docs"),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": {"status": "green"}})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/collections/docs"
    assert calls[-1]["method"] == "GET"


@pytest.mark.asyncio
async def test_update_collection(credentials):
    config = QdrantNodeConfig(
        config=QdrantUpdateCollectionConfig(
            collection="docs",
            optimizers_config='{"indexing_threshold": 20000}',
        ),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": True})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/collections/docs"
    assert calls[-1]["method"] == "PATCH"
    assert calls[-1]["json"]["optimizers_config"] == {"indexing_threshold": 20000}


@pytest.mark.asyncio
async def test_update_collection_requires_at_least_one_field(credentials):
    config = QdrantNodeConfig(
        config=QdrantUpdateCollectionConfig(collection="docs"),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    result = await node.execute({})
    assert result["status"] == "error"
    assert "setting" in result["error"].lower()


@pytest.mark.asyncio
async def test_delete_collection(credentials):
    config = QdrantNodeConfig(
        config=QdrantDeleteCollectionConfig(collection="old-col"),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": True})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/collections/old-col"
    assert calls[-1]["method"] == "DELETE"


# ---------------------------------------------------------------------------
# Payload ops
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_payload_by_ids(credentials):
    config = QdrantNodeConfig(
        config=QdrantSetPayloadConfig(
            collection="docs", payload='{"status": "done"}', ids="1,2",
        ),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": {"status": "completed"}})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/collections/docs/points/payload"
    assert calls[-1]["method"] == "POST"
    assert calls[-1]["json"]["payload"] == {"status": "done"}
    assert calls[-1]["json"]["points"] == [1, 2]
    assert calls[-1]["params"] == {"wait": "true"}


@pytest.mark.asyncio
async def test_set_payload_by_filter(credentials):
    config = QdrantNodeConfig(
        config=QdrantSetPayloadConfig(
            collection="docs", payload='{"flagged": true}',
            filter='{"must": [{"key": "type", "match": {"value": "draft"}}]}',
        ),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": {"status": "completed"}})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert "filter" in calls[-1]["json"]
    assert "points" not in calls[-1]["json"]


@pytest.mark.asyncio
async def test_set_payload_requires_target(credentials):
    config = QdrantNodeConfig(
        config=QdrantSetPayloadConfig(collection="docs", payload='{"a": 1}'),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    result = await node.execute({})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_delete_payload_keys(credentials):
    config = QdrantNodeConfig(
        config=QdrantDeletePayloadConfig(collection="docs", keys="tmp, old_field", ids="1"),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": {"status": "completed"}})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/collections/docs/points/payload/delete"
    assert calls[-1]["json"]["keys"] == ["tmp", "old_field"]
    assert calls[-1]["json"]["points"] == [1]


@pytest.mark.asyncio
async def test_clear_payload_by_filter(credentials):
    config = QdrantNodeConfig(
        config=QdrantClearPayloadConfig(
            collection="docs",
            filter='{"must": [{"key": "stale", "match": {"value": true}}]}',
        ),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": {"status": "completed"}})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/collections/docs/points/payload/clear"
    assert "filter" in calls[-1]["json"]


@pytest.mark.asyncio
async def test_clear_payload_requires_target(credentials):
    config = QdrantNodeConfig(
        config=QdrantClearPayloadConfig(collection="docs"),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    result = await node.execute({})
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Payload index ops
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_payload_index(credentials):
    config = QdrantNodeConfig(
        config=QdrantCreatePayloadIndexConfig(
            collection="docs", field_name="category", field_schema="keyword",
        ),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": {"operation_id": 1, "status": "completed"}})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/collections/docs/index"
    assert calls[-1]["method"] == "PUT"
    assert calls[-1]["json"] == {"field_name": "category", "field_schema": "keyword"}
    assert calls[-1]["params"] == {"wait": "true"}


@pytest.mark.asyncio
async def test_delete_payload_index(credentials):
    config = QdrantNodeConfig(
        config=QdrantDeletePayloadIndexConfig(collection="docs", field_name="category"),
        credentials=credentials,
    )
    node = create_qdrant_node(config)
    client, calls = create_capturing_client(200, {"result": {"operation_id": 2, "status": "completed"}})
    with patch("nodes.qdrant_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/collections/docs/index/category"
    assert calls[-1]["method"] == "DELETE"
    assert calls[-1]["params"] == {"wait": "true"}
