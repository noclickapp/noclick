"""
Mock tests for the Chroma vector database node.

Covers: v2 endpoint shaping, all 36 operations (full API coverage), collection
name→UUID resolution (direct GET + caching), parallel-array record shape,
Basic auth headers, where_document / include / offset / pagination fields,
config validation and error paths. No live API.
"""

import json
import sys
import types

import pytest
from unittest.mock import Mock, AsyncMock, patch

from nodes.chroma_node import (
    ChromaNode,
    ChromaNodeConfig,
    ChromaCredential,
    ChromaQueryConfig,
    ChromaSearchConfig,
    ChromaAddConfig,
    ChromaUpsertConfig,
    ChromaUpdateConfig,
    ChromaGetConfig,
    ChromaCountConfig,
    ChromaDeleteConfig,
    ChromaUploadIndexConfig,
    ChromaListCollectionsConfig,
    ChromaGetCollectionConfig,
    ChromaCreateCollectionConfig,
    ChromaUpdateCollectionConfig,
    ChromaDeleteCollectionConfig,
    ChromaCountCollectionsConfig,
    ChromaIndexingStatusConfig,
    ChromaForkCollectionConfig,
    ChromaForkCountConfig,
    ChromaGetCollectionByIdConfig,
    ChromaGetCollectionByCrnConfig,
    ChromaAttachFunctionConfig,
    ChromaGetAttachedFunctionConfig,
    ChromaAddAttachedFunctionInputConfig,
    ChromaDetachFunctionConfig,
    ChromaGetTenantConfig,
    ChromaCreateTenantConfig,
    ChromaUpdateTenantConfig,
    ChromaListDatabasesConfig,
    ChromaCreateDatabaseConfig,
    ChromaGetDatabaseConfig,
    ChromaDeleteDatabaseConfig,
    ChromaHealthcheckConfig,
    ChromaHeartbeatConfig,
    ChromaVersionConfig,
    ChromaResetConfig,
    ChromaGetUserIdentityConfig,
    CHROMA_CLOUD_BASE,
)

COLBASE = f"{CHROMA_CLOUD_BASE}/api/v2/tenants/t/databases/d/collections"


@pytest.fixture
def credentials():
    return ChromaCredential(api_key="ck_test", tenant="t", database="d")


def create_node(config):
    return ChromaNode(
        node_id="test-chroma-node",
        node_type="automation-chroma",
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
    """Returns (client, calls) where calls is appended per HTTP call."""
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
# Credential + headers
# ---------------------------------------------------------------------------


def test_collections_base(credentials):
    assert ChromaNode._collections_base(credentials) == COLBASE


def test_token_headers(credentials):
    h = ChromaNode._headers(credentials)
    assert h["x-chroma-token"] == "ck_test"
    assert "Authorization" not in h


def test_basic_auth_headers():
    import base64
    cred = ChromaCredential(auth_type="basic", username="admin", password="s3cr3t", tenant="t", database="d")
    h = ChromaNode._headers(cred)
    assert "x-chroma-token" not in h
    expected = "Basic " + base64.b64encode(b"admin:s3cr3t").decode()
    assert h["Authorization"] == expected


def test_base_url_override():
    cred = ChromaCredential(api_key="k", tenant="t", database="d", base_url="http://localhost:8000")
    assert ChromaNode._collections_base(cred).startswith("http://localhost:8000/api/v2")


# ---------------------------------------------------------------------------
# Name→UUID resolution (direct GET, cached)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_collection_id_uses_direct_get(credentials):
    config = ChromaNodeConfig(config=ChromaListCollectionsConfig(), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, {"id": "abc-123", "name": "docs"})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        col_id = await node._resolve_collection_id("docs", credentials)
    assert col_id == "abc-123"
    assert len(calls) == 1
    assert calls[0]["url"] == f"{COLBASE}/docs"


@pytest.mark.asyncio
async def test_resolve_collection_id_caches(credentials):
    config = ChromaNodeConfig(config=ChromaListCollectionsConfig(), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, {"id": "abc", "name": "docs"})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        id1 = await node._resolve_collection_id("docs", credentials)
        id2 = await node._resolve_collection_id("docs", credentials)
    assert id1 == id2 == "abc"
    assert len(calls) == 1  # second call was served from cache


@pytest.mark.asyncio
async def test_resolve_collection_id_not_found(credentials):
    config = ChromaNodeConfig(
        config=ChromaQueryConfig(collection="missing", vector="[0.1]"), credentials=credentials
    )
    node = create_node(config)
    client, _ = create_capturing_client(404, {"error": "Collection not found"})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "error"
    assert "not found" in result["error"].lower()


# ---------------------------------------------------------------------------
# Records — query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query(credentials):
    config = ChromaNodeConfig(
        config=ChromaQueryConfig(collection="docs", vector="[0.1, 0.2]", n_results=5, where='{"src": "a"}'),
        credentials=credentials,
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"ids": [[]]})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{COLBASE}/col-uuid/query"
    body = calls[-1]["json"]
    assert body["query_embeddings"] == [[0.1, 0.2]]
    assert body["n_results"] == 5
    assert body["where"] == {"src": "a"}
    assert "distances" in body["include"]


@pytest.mark.asyncio
async def test_query_with_where_document_and_include(credentials):
    config = ChromaNodeConfig(
        config=ChromaQueryConfig(
            collection="docs",
            vector="[0.1]",
            where_document='{"$contains": "keyword"}',
            include='["documents", "distances"]',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"ids": [[]]})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert body["where_document"] == {"$contains": "keyword"}
    assert body["include"] == ["documents", "distances"]


@pytest.mark.asyncio
async def test_query_malformed_vector(credentials):
    config = ChromaNodeConfig(
        config=ChromaQueryConfig(collection="docs", vector="oops"), credentials=credentials
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    result = await node.execute({})
    assert result["status"] == "error"
    assert "json array" in result["error"].lower()


# ---------------------------------------------------------------------------
# Records — add / upsert / update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add(credentials):
    config = ChromaNodeConfig(
        config=ChromaAddConfig(
            collection="docs", ids="a,b", embeddings="[[0.1],[0.2]]",
            documents='["d1","d2"]', metadatas='[{"k":1},{"k":2}]',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(201, {"success": True})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{COLBASE}/col-uuid/add"
    body = calls[-1]["json"]
    assert body["ids"] == ["a", "b"]
    assert body["embeddings"] == [[0.1], [0.2]]


@pytest.mark.asyncio
async def test_add_malformed_embeddings(credentials):
    config = ChromaNodeConfig(
        config=ChromaAddConfig(collection="docs", ids="a", embeddings="nope"),
        credentials=credentials,
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    result = await node.execute({})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_upsert_hits_upsert_endpoint(credentials):
    config = ChromaNodeConfig(
        config=ChromaUpsertConfig(
            collection="docs", ids="a,b", embeddings="[[0.1],[0.2]]", documents='["d1","d2"]'
        ),
        credentials=credentials,
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"success": True})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{COLBASE}/col-uuid/upsert"
    body = calls[-1]["json"]
    assert body["ids"] == ["a", "b"]
    assert body["documents"] == ["d1", "d2"]


@pytest.mark.asyncio
async def test_update_sends_only_provided_fields(credentials):
    config = ChromaNodeConfig(
        config=ChromaUpdateConfig(collection="docs", ids="a", documents='["new text"]'),
        credentials=credentials,
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"success": True})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{COLBASE}/col-uuid/update"
    body = calls[-1]["json"]
    assert body["ids"] == ["a"]
    assert body["documents"] == ["new text"]
    assert "embeddings" not in body


# ---------------------------------------------------------------------------
# Records — get / count / delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get(credentials):
    config = ChromaNodeConfig(
        config=ChromaGetConfig(collection="docs", ids="a,b", limit=10), credentials=credentials
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"ids": ["a", "b"]})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{COLBASE}/col-uuid/get"
    assert calls[-1]["json"]["ids"] == ["a", "b"]
    assert calls[-1]["json"]["limit"] == 10


@pytest.mark.asyncio
async def test_get_with_offset_and_where_document(credentials):
    config = ChromaNodeConfig(
        config=ChromaGetConfig(
            collection="docs",
            where_document='{"$contains": "python"}',
            offset=20,
            include='["documents"]',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"ids": []})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert body["where_document"] == {"$contains": "python"}
    assert body["offset"] == 20
    assert body["include"] == ["documents"]


@pytest.mark.asyncio
async def test_count(credentials):
    config = ChromaNodeConfig(
        config=ChromaCountConfig(collection="docs"), credentials=credentials
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, 42)  # count returns a bare integer
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["count"] == 42
    assert calls[-1]["url"] == f"{COLBASE}/col-uuid/count"


@pytest.mark.asyncio
async def test_delete_by_ids(credentials):
    config = ChromaNodeConfig(
        config=ChromaDeleteConfig(collection="docs", ids="a"), credentials=credentials
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"success": True})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{COLBASE}/col-uuid/delete"
    assert calls[-1]["json"]["ids"] == ["a"]


@pytest.mark.asyncio
async def test_delete_with_where_document(credentials):
    config = ChromaNodeConfig(
        config=ChromaDeleteConfig(collection="docs", where_document='{"$contains": "stale"}'),
        credentials=credentials,
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"success": True})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"]["where_document"] == {"$contains": "stale"}


@pytest.mark.asyncio
async def test_delete_requires_target(credentials):
    config = ChromaNodeConfig(
        config=ChromaDeleteConfig(collection="docs"), credentials=credentials
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    result = await node.execute({})
    assert result["status"] == "error"
    assert "filter" in result["error"].lower() or "ids" in result["error"].lower()


# ---------------------------------------------------------------------------
# Collections — list / get / create / update / delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_collections(credentials):
    config = ChromaNodeConfig(config=ChromaListCollectionsConfig(), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, [{"id": "x", "name": "docs"}])
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == COLBASE


@pytest.mark.asyncio
async def test_list_collections_with_pagination(credentials):
    config = ChromaNodeConfig(
        config=ChromaListCollectionsConfig(limit=5, offset=10), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, [])
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["params"] == {"limit": 5, "offset": 10}


@pytest.mark.asyncio
async def test_get_collection(credentials):
    config = ChromaNodeConfig(
        config=ChromaGetCollectionConfig(collection="docs"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"id": "abc", "name": "docs", "metadata": {}})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{COLBASE}/docs"


@pytest.mark.asyncio
async def test_create_collection(credentials):
    config = ChromaNodeConfig(
        config=ChromaCreateCollectionConfig(name="docs", get_or_create="true"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"id": "x", "name": "docs"})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == COLBASE
    assert calls[-1]["json"] == {"name": "docs", "get_or_create": True}


@pytest.mark.asyncio
async def test_create_collection_with_metadata_and_distance(credentials):
    config = ChromaNodeConfig(
        config=ChromaCreateCollectionConfig(
            name="embeddings",
            get_or_create="false",
            distance_metric="cosine",
            metadata='{"owner": "team-a"}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"id": "y", "name": "embeddings"})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert body["get_or_create"] is False
    assert body["metadata"]["hnsw:space"] == "cosine"
    assert body["metadata"]["owner"] == "team-a"


@pytest.mark.asyncio
async def test_update_collection_rename(credentials):
    config = ChromaNodeConfig(
        config=ChromaUpdateCollectionConfig(collection="old-name", new_name="new-name"),
        credentials=credentials,
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"id": "col-uuid", "name": "new-name"})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{COLBASE}/col-uuid"
    assert calls[-1]["json"]["new_name"] == "new-name"


@pytest.mark.asyncio
async def test_delete_collection(credentials):
    # DELETE resolves by name (not UUID) — same as GET, unlike record operations.
    config = ChromaNodeConfig(
        config=ChromaDeleteCollectionConfig(collection="docs"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"success": True})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{COLBASE}/docs"
    assert calls[-1]["method"] == "DELETE"


# ---------------------------------------------------------------------------
# Upload & Index
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_and_index(credentials):
    config = ChromaNodeConfig(
        config=ChromaUploadIndexConfig(collection="docs", document="res-id"), credentials=credentials
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    fake_records = [
        {"id": "u0", "values": [0.1], "metadata": {"text": "a", "source": "f.pdf", "chunk_index": 0}},
        {"id": "u1", "values": [0.2], "metadata": {"text": "b", "source": "f.pdf", "chunk_index": 1}},
    ]
    client, calls = create_capturing_client(201, {"success": True})
    with patch("nodes.chroma_node.ingest_document", new=AsyncMock(return_value=(fake_records, {"filename": "f.pdf"}))), \
         patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["chunks_indexed"] == 2
    assert calls[-1]["url"] == f"{COLBASE}/col-uuid/add"
    body = calls[-1]["json"]
    assert body["ids"] == ["u0", "u1"]
    assert body["embeddings"] == [[0.1], [0.2]]
    assert body["documents"] == ["a", "b"]
    assert body["metadatas"][0] == {"source": "f.pdf", "chunk_index": 0}


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_credentials_raises():
    config = ChromaNodeConfig(config=ChromaListCollectionsConfig(), credentials=None)
    node = create_node(config)
    with pytest.raises(ValueError, match="[Cc]redentials"):
        await node.execute({})


@pytest.mark.asyncio
async def test_load_field_options():
    client, _ = create_capturing_client(200, [{"id": "1", "name": "docs"}, {"id": "2", "name": "img"}])
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        options = await ChromaNode.load_field_options(
            field_name="collection",
            credential_data={"api_key": "k", "tenant": "t", "database": "d"},
        )
    assert {o["value"] for o in options} == {"docs", "img"}


# ---------------------------------------------------------------------------
# Records — search (text, no vector)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_sends_query_text(credentials):
    config = ChromaNodeConfig(
        config=ChromaSearchConfig(collection="docs", query_text="machine learning", n_results=3),
        credentials=credentials,
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"ids": [[]]})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{COLBASE}/col-uuid/search"
    body = calls[-1]["json"]
    assert body["query"] == "machine learning"
    assert body["n_results"] == 3
    assert "distances" in body["include"]


@pytest.mark.asyncio
async def test_search_with_where_and_where_document(credentials):
    config = ChromaNodeConfig(
        config=ChromaSearchConfig(
            collection="docs",
            query_text="AI",
            where='{"topic": "ml"}',
            where_document='{"$contains": "neural"}',
            include='["documents"]',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"ids": [[]]})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert body["where"] == {"topic": "ml"}
    assert body["where_document"] == {"$contains": "neural"}
    assert body["include"] == ["documents"]


# ---------------------------------------------------------------------------
# Collection extras — count_collections, indexing_status, fork, by_id, by_crn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_collections(credentials):
    config = ChromaNodeConfig(config=ChromaCountCollectionsConfig(), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, 5)
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"].endswith("/collections_count")


@pytest.mark.asyncio
async def test_indexing_status(credentials):
    config = ChromaNodeConfig(
        config=ChromaIndexingStatusConfig(collection="docs"), credentials=credentials
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"total_records": 100, "indexed_records": 100})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{COLBASE}/col-uuid/indexing_status"


@pytest.mark.asyncio
async def test_fork_collection(credentials):
    config = ChromaNodeConfig(
        config=ChromaForkCollectionConfig(collection="docs", new_name="docs-fork"),
        credentials=credentials,
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"id": "fork-uuid", "name": "docs-fork"})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{COLBASE}/col-uuid/fork"
    assert calls[-1]["json"]["name"] == "docs-fork"


@pytest.mark.asyncio
async def test_fork_collection_with_destination_database(credentials):
    config = ChromaNodeConfig(
        config=ChromaForkCollectionConfig(
            collection="docs", new_name="docs-fork", destination_database="other-db"
        ),
        credentials=credentials,
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"id": "fork-uuid", "name": "docs-fork"})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"]["destination_database"] == "other-db"


@pytest.mark.asyncio
async def test_fork_count(credentials):
    config = ChromaNodeConfig(
        config=ChromaForkCountConfig(collection="docs"), credentials=credentials
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"count": 3})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{COLBASE}/col-uuid/fork_count"


@pytest.mark.asyncio
async def test_get_collection_by_id(credentials):
    config = ChromaNodeConfig(
        config=ChromaGetCollectionByIdConfig(collection_id="abc-123"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"id": "abc-123", "name": "docs"})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{COLBASE}/by-id/abc-123"


@pytest.mark.asyncio
async def test_get_collection_by_crn(credentials):
    config = ChromaNodeConfig(
        config=ChromaGetCollectionByCrnConfig(crn="crn:t:d:docs"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"id": "abc-123", "name": "docs"})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{CHROMA_CLOUD_BASE}/api/v2/collections/crn:t:d:docs"


# ---------------------------------------------------------------------------
# Attached functions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attach_function(credentials):
    config = ChromaNodeConfig(
        config=ChromaAttachFunctionConfig(
            collection="docs", function_name="openai", function_config='{"model": "ada"}'
        ),
        credentials=credentials,
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"name": "openai"})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{COLBASE}/col-uuid/functions/attach"
    assert calls[-1]["json"] == {"name": "openai", "config": {"model": "ada"}}


@pytest.mark.asyncio
async def test_get_attached_function(credentials):
    config = ChromaNodeConfig(
        config=ChromaGetAttachedFunctionConfig(collection="docs", function_name="openai"),
        credentials=credentials,
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"name": "openai", "config": {}})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{COLBASE}/col-uuid/functions/openai"


@pytest.mark.asyncio
async def test_add_attached_function_input(credentials):
    config = ChromaNodeConfig(
        config=ChromaAddAttachedFunctionInputConfig(
            collection="docs", function_name="openai", input='{"text": "hello"}'
        ),
        credentials=credentials,
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"success": True})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{COLBASE}/col-uuid/attached_functions/openai/add_input"
    assert calls[-1]["json"] == {"input": {"text": "hello"}}


@pytest.mark.asyncio
async def test_add_attached_function_input_invalid_json(credentials):
    config = ChromaNodeConfig(
        config=ChromaAddAttachedFunctionInputConfig(
            collection="docs", function_name="fn", input="not-json"
        ),
        credentials=credentials,
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    result = await node.execute({})
    assert result["status"] == "error"
    assert "json" in result["error"].lower()


@pytest.mark.asyncio
async def test_detach_function(credentials):
    config = ChromaNodeConfig(
        config=ChromaDetachFunctionConfig(collection="docs", function_name="openai"),
        credentials=credentials,
    )
    node = create_node(config)
    node._resolve_collection_id = AsyncMock(return_value="col-uuid")
    client, calls = create_capturing_client(200, {"success": True})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{COLBASE}/col-uuid/attached_functions/openai/detach"


# ---------------------------------------------------------------------------
# Tenant management
# ---------------------------------------------------------------------------

TENANT_BASE = f"{CHROMA_CLOUD_BASE}/api/v2/tenants"


@pytest.mark.asyncio
async def test_get_tenant_uses_credential_tenant_by_default(credentials):
    config = ChromaNodeConfig(config=ChromaGetTenantConfig(), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, {"name": "t"})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{TENANT_BASE}/t"


@pytest.mark.asyncio
async def test_get_tenant_override(credentials):
    config = ChromaNodeConfig(
        config=ChromaGetTenantConfig(tenant_name="other-tenant"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"name": "other-tenant"})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{TENANT_BASE}/other-tenant"


@pytest.mark.asyncio
async def test_create_tenant(credentials):
    config = ChromaNodeConfig(
        config=ChromaCreateTenantConfig(tenant_name="new-tenant"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"name": "new-tenant"})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == TENANT_BASE
    assert calls[-1]["json"] == {"name": "new-tenant"}


@pytest.mark.asyncio
async def test_update_tenant(credentials):
    config = ChromaNodeConfig(
        config=ChromaUpdateTenantConfig(config='{"key": "val"}'), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"name": "t"})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{TENANT_BASE}/t"
    assert calls[-1]["json"] == {"config": {"key": "val"}}


# ---------------------------------------------------------------------------
# Database management
# ---------------------------------------------------------------------------

DB_BASE = f"{CHROMA_CLOUD_BASE}/api/v2/tenants/t/databases"


@pytest.mark.asyncio
async def test_list_databases(credentials):
    config = ChromaNodeConfig(config=ChromaListDatabasesConfig(), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, [{"name": "d"}])
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == DB_BASE


@pytest.mark.asyncio
async def test_create_database(credentials):
    config = ChromaNodeConfig(
        config=ChromaCreateDatabaseConfig(database_name="new-db"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"name": "new-db"})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == DB_BASE
    assert calls[-1]["json"] == {"name": "new-db"}


@pytest.mark.asyncio
async def test_get_database_default(credentials):
    config = ChromaNodeConfig(config=ChromaGetDatabaseConfig(), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, {"name": "d"})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{DB_BASE}/d"


@pytest.mark.asyncio
async def test_delete_database(credentials):
    config = ChromaNodeConfig(
        config=ChromaDeleteDatabaseConfig(database_name="old-db"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"success": True})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{DB_BASE}/old-db"
    assert calls[-1]["method"] == "DELETE"


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_healthcheck(credentials):
    config = ChromaNodeConfig(config=ChromaHealthcheckConfig(), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, {"is_executor_ready": True})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{CHROMA_CLOUD_BASE}/api/v2/healthcheck"


@pytest.mark.asyncio
async def test_heartbeat(credentials):
    config = ChromaNodeConfig(config=ChromaHeartbeatConfig(), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, {"nanosecond heartbeat": 1234567890})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{CHROMA_CLOUD_BASE}/api/v2/heartbeat"


@pytest.mark.asyncio
async def test_version(credentials):
    config = ChromaNodeConfig(config=ChromaVersionConfig(), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, "0.6.0")
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{CHROMA_CLOUD_BASE}/api/v2/version"


@pytest.mark.asyncio
async def test_reset(credentials):
    config = ChromaNodeConfig(config=ChromaResetConfig(), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, True)
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{CHROMA_CLOUD_BASE}/api/v2/reset"
    assert calls[-1]["method"] == "POST"


@pytest.mark.asyncio
async def test_get_user_identity(credentials):
    config = ChromaNodeConfig(config=ChromaGetUserIdentityConfig(), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, {"user_id": "u1", "tenant": "t"})
    with patch("nodes.chroma_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{CHROMA_CLOUD_BASE}/api/v2/auth/identity"
