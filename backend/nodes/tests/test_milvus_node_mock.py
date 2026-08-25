"""
Mock tests for the Milvus / Zilliz Cloud node.

Verifies v2 endpoint/body shaping (POST-based), the code-in-body error
promotion + data unwrapping, config parsing, dynamic options, and error paths.
No live API.
"""

import json

import pytest
from unittest.mock import Mock, AsyncMock, patch

from nodes.milvus_node import (
    MilvusNode,
    MilvusNodeConfig,
    MilvusCredential,
    MilvusSearchConfig,
    MilvusHybridSearchConfig,
    MilvusGetConfig,
    MilvusInsertConfig,
    MilvusUpsertConfig,
    MilvusQueryConfig,
    MilvusDeleteConfig,
    MilvusUploadIndexConfig,
    MilvusListCollectionsConfig,
    MilvusCreateCollectionConfig,
    MilvusDescribeCollectionConfig,
    MilvusDropCollectionConfig,
    MilvusRenameCollectionConfig,
    MilvusLoadCollectionConfig,
    MilvusReleaseCollectionConfig,
    MilvusGetLoadStateConfig,
    MilvusGetCollectionStatsConfig,
    MilvusFlushConfig,
    MilvusCompactConfig,
    MilvusHasCollectionConfig,
    MilvusListIndexesConfig,
    MilvusCreateIndexConfig,
    MilvusDropIndexConfig,
    MilvusDescribeIndexConfig,
    MilvusListPartitionsConfig,
    MilvusCreatePartitionConfig,
    MilvusDropPartitionConfig,
    MilvusHasPartitionConfig,
    MilvusListAliasesConfig,
    MilvusCreateAliasConfig,
    MilvusDropAliasConfig,
    MilvusDescribeAliasConfig,
    MilvusAlterAliasConfig,
    MilvusListDatabasesConfig,
    MilvusCreateDatabaseConfig,
    MilvusDropDatabaseConfig,
    MilvusDescribeDatabaseConfig,
)

BASE = "https://in03-test.api.gcp-us-west1.zillizcloud.com"


@pytest.fixture
def credentials():
    return MilvusCredential(uri=BASE, token="tok_test")


def create_node(config):
    return MilvusNode(
        node_id="test-milvus-node",
        node_type="automation-milvus",
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

    async def post(url, *args, **kwargs):
        calls.append({"url": url, **kwargs})
        return response

    client.post = post

    async def aenter(self):
        return client

    async def aexit(self, *a):
        return None

    client.__aenter__ = aenter
    client.__aexit__ = aexit
    return client, calls


def ok(data=None):
    return {"code": 0, "data": data or {}}


# ---------------------------------------------------------------------------
# Entities — Search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search(credentials):
    config = MilvusNodeConfig(
        config=MilvusSearchConfig(
            collection="docs", vector="[0.1, 0.2]", anns_field="vector", limit=5,
            filter='color == "red"', output_fields="id,color",
            partition_names="part1,part2",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok([{"id": 1, "distance": 0.1}]))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"] == [{"id": 1, "distance": 0.1}]
    body = calls[-1]["json"]
    assert body["collectionName"] == "docs"
    assert body["data"] == [[0.1, 0.2]]
    assert body["annsField"] == "vector"
    assert body["limit"] == 5
    assert body["filter"] == 'color == "red"'
    assert body["outputFields"] == ["id", "color"]
    assert body["partitionNames"] == ["part1", "part2"]
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/entities/search"


@pytest.mark.asyncio
async def test_search_malformed_vector(credentials):
    config = MilvusNodeConfig(
        config=MilvusSearchConfig(collection="docs", vector="oops"), credentials=credentials
    )
    node = create_node(config)
    result = await node.execute({})
    assert result["status"] == "error"
    assert "json array" in result["error"].lower()


@pytest.mark.asyncio
async def test_search_with_db_name(credentials):
    config = MilvusNodeConfig(
        config=MilvusSearchConfig(collection="docs", vector="[0.1]", db_name="mydb"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok([]))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        await node.execute({})
    assert calls[-1]["json"]["dbName"] == "mydb"


# ---------------------------------------------------------------------------
# Entities — Hybrid Search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hybrid_search(credentials):
    requests_json = '[{"annsField": "vec1", "data": [[0.1]], "limit": 5}, {"annsField": "vec2", "data": [[0.2]], "limit": 5}]'
    rerank_json = '{"strategy": "rrf", "params": {"k": 60}}'
    config = MilvusNodeConfig(
        config=MilvusHybridSearchConfig(
            collection="docs", requests=requests_json, rerank=rerank_json, limit=10,
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok([{"id": 1}]))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert body["collectionName"] == "docs"
    assert len(body["search"]) == 2
    assert body["rerank"]["strategy"] == "rrf"
    assert body["limit"] == 10
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/entities/hybrid_search"


@pytest.mark.asyncio
async def test_hybrid_search_malformed_requests(credentials):
    config = MilvusNodeConfig(
        config=MilvusHybridSearchConfig(collection="docs", requests="bad json", rerank="{}"),
        credentials=credentials,
    )
    node = create_node(config)
    result = await node.execute({})
    assert result["status"] == "error"
    assert "json array" in result["error"].lower()


@pytest.mark.asyncio
async def test_hybrid_search_malformed_rerank(credentials):
    config = MilvusNodeConfig(
        config=MilvusHybridSearchConfig(collection="docs", requests="[]", rerank="not json"),
        credentials=credentials,
    )
    node = create_node(config)
    result = await node.execute({})
    assert result["status"] == "error"
    assert "json object" in result["error"].lower()


# ---------------------------------------------------------------------------
# Entities — Get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_numeric_ids(credentials):
    config = MilvusNodeConfig(
        config=MilvusGetConfig(collection="docs", ids="1,2,3", output_fields="id,vector"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok([{"id": 1}]))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert body["id"] == [1, 2, 3]
    assert body["outputFields"] == ["id", "vector"]
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/entities/get"


@pytest.mark.asyncio
async def test_get_string_ids(credentials):
    config = MilvusNodeConfig(
        config=MilvusGetConfig(collection="docs", ids="abc,def"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok([]))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        await node.execute({})
    assert calls[-1]["json"]["id"] == ["abc", "def"]


# ---------------------------------------------------------------------------
# Entities — Insert / Upsert / Query / Delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert(credentials):
    config = MilvusNodeConfig(
        config=MilvusInsertConfig(collection="docs", data='[{"id": 1, "vector": [0.1]}]',
                                  partition_name="mypart"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok({"insertCount": 1}))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert body["data"][0]["id"] == 1
    assert body["partitionName"] == "mypart"
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/entities/insert"


@pytest.mark.asyncio
async def test_upsert(credentials):
    config = MilvusNodeConfig(
        config=MilvusUpsertConfig(collection="docs", data='[{"id": 1, "vector": [0.1]}]'),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok({"upsertCount": 1}))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/entities/upsert"


@pytest.mark.asyncio
async def test_insert_malformed(credentials):
    config = MilvusNodeConfig(
        config=MilvusInsertConfig(collection="docs", data="nope"), credentials=credentials
    )
    node = create_node(config)
    result = await node.execute({})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_query(credentials):
    config = MilvusNodeConfig(
        config=MilvusQueryConfig(collection="docs", filter="id in [1,2]", output_fields="id",
                                 limit=10, offset=5, partition_names="p1"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok([{"id": 1}]))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert body["filter"] == "id in [1,2]"
    assert body["outputFields"] == ["id"]
    assert body["limit"] == 10
    assert body["offset"] == 5
    assert body["partitionNames"] == ["p1"]
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/entities/query"


@pytest.mark.asyncio
async def test_delete(credentials):
    config = MilvusNodeConfig(
        config=MilvusDeleteConfig(collection="docs", filter="id in [1]",
                                  partition_name="mypart"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok())
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert body == {"collectionName": "docs", "filter": "id in [1]", "partitionName": "mypart"}
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/entities/delete"


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_collections(credentials):
    config = MilvusNodeConfig(config=MilvusListCollectionsConfig(), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, ok(["docs", "images"]))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"] == ["docs", "images"]
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/collections/list"
    assert calls[-1]["json"] == {}


@pytest.mark.asyncio
async def test_create_collection(credentials):
    config = MilvusNodeConfig(
        config=MilvusCreateCollectionConfig(name="docs", dimension="1536", metric_type="COSINE"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok())
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"] == {"collectionName": "docs", "dimension": 1536, "metricType": "COSINE"}
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/collections/create"


@pytest.mark.asyncio
async def test_describe_collection(credentials):
    config = MilvusNodeConfig(
        config=MilvusDescribeCollectionConfig(collection="docs"),
        credentials=credentials,
    )
    node = create_node(config)
    schema_data = {"collectionName": "docs", "fields": []}
    client, calls = create_capturing_client(200, ok(schema_data))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"] == {"collectionName": "docs"}
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/collections/describe"


@pytest.mark.asyncio
async def test_drop_collection(credentials):
    config = MilvusNodeConfig(
        config=MilvusDropCollectionConfig(collection="docs"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok())
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"] == {"collectionName": "docs"}
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/collections/drop"


@pytest.mark.asyncio
async def test_rename_collection(credentials):
    config = MilvusNodeConfig(
        config=MilvusRenameCollectionConfig(collection="docs", new_name="docs_v2",
                                            new_db_name="archive_db"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok())
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert body["collectionName"] == "docs"
    assert body["newCollectionName"] == "docs_v2"
    assert body["newDbName"] == "archive_db"
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/collections/rename"


@pytest.mark.asyncio
async def test_load_collection(credentials):
    config = MilvusNodeConfig(
        config=MilvusLoadCollectionConfig(collection="docs"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok())
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/collections/load"


@pytest.mark.asyncio
async def test_release_collection(credentials):
    config = MilvusNodeConfig(
        config=MilvusReleaseCollectionConfig(collection="docs"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok())
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/collections/release"


@pytest.mark.asyncio
async def test_get_load_state(credentials):
    config = MilvusNodeConfig(
        config=MilvusGetLoadStateConfig(collection="docs"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok({"loadState": "LoadStateLoaded"}))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["loadState"] == "LoadStateLoaded"
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/collections/get_load_state"


@pytest.mark.asyncio
async def test_get_collection_stats(credentials):
    config = MilvusNodeConfig(
        config=MilvusGetCollectionStatsConfig(collection="docs"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok({"rowCount": 1000}))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["rowCount"] == 1000
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/collections/get_stats"


@pytest.mark.asyncio
async def test_flush(credentials):
    config = MilvusNodeConfig(
        config=MilvusFlushConfig(collection="docs"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok())
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/collections/flush"


@pytest.mark.asyncio
async def test_compact(credentials):
    config = MilvusNodeConfig(
        config=MilvusCompactConfig(collection="docs"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok({"compactionID": 123}))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/collections/compact"


@pytest.mark.asyncio
async def test_has_collection(credentials):
    config = MilvusNodeConfig(
        config=MilvusHasCollectionConfig(collection="docs"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok({"has": True}))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["has"] is True
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/collections/has"


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_indexes(credentials):
    config = MilvusNodeConfig(
        config=MilvusListIndexesConfig(collection="docs"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok([{"indexName": "vector_idx"}]))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/indexes/list"
    assert calls[-1]["json"]["collectionName"] == "docs"


@pytest.mark.asyncio
async def test_create_index(credentials):
    config = MilvusNodeConfig(
        config=MilvusCreateIndexConfig(
            collection="docs", field_name="vector", index_name="vec_idx",
            index_type="HNSW", metric_type="COSINE",
            params='{"M": 16, "efConstruction": 200}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok())
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    # Milvus REST v2: params are wrapped in an indexParams array
    assert body["collectionName"] == "docs"
    ip = body["indexParams"][0]
    assert ip["fieldName"] == "vector"
    assert ip["indexName"] == "vec_idx"
    assert ip["indexType"] == "HNSW"
    assert ip["params"]["M"] == 16
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/indexes/create"


@pytest.mark.asyncio
async def test_drop_index(credentials):
    config = MilvusNodeConfig(
        config=MilvusDropIndexConfig(collection="docs", index_name="vec_idx"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok())
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"] == {"collectionName": "docs", "indexName": "vec_idx"}
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/indexes/drop"


@pytest.mark.asyncio
async def test_describe_index(credentials):
    config = MilvusNodeConfig(
        config=MilvusDescribeIndexConfig(collection="docs", index_name="vec_idx"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok({"indexType": "HNSW"}))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/indexes/describe"


# ---------------------------------------------------------------------------
# Partitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_partitions(credentials):
    config = MilvusNodeConfig(
        config=MilvusListPartitionsConfig(collection="docs"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok(["_default", "part1"]))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/partitions/list"


@pytest.mark.asyncio
async def test_create_partition(credentials):
    config = MilvusNodeConfig(
        config=MilvusCreatePartitionConfig(collection="docs", partition_name="q1"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok())
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"] == {"collectionName": "docs", "partitionName": "q1"}
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/partitions/create"


@pytest.mark.asyncio
async def test_drop_partition(credentials):
    config = MilvusNodeConfig(
        config=MilvusDropPartitionConfig(collection="docs", partition_name="q1"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok())
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/partitions/drop"


@pytest.mark.asyncio
async def test_has_partition(credentials):
    config = MilvusNodeConfig(
        config=MilvusHasPartitionConfig(collection="docs", partition_name="q1"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok({"has": True}))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["has"] is True
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/partitions/has"


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_aliases(credentials):
    config = MilvusNodeConfig(
        config=MilvusListAliasesConfig(collection="docs"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok(["alias1", "alias2"]))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/aliases/list"


@pytest.mark.asyncio
async def test_create_alias(credentials):
    config = MilvusNodeConfig(
        config=MilvusCreateAliasConfig(collection="docs", alias_name="prod_docs"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok())
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"] == {"collectionName": "docs", "aliasName": "prod_docs"}
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/aliases/create"


@pytest.mark.asyncio
async def test_drop_alias(credentials):
    config = MilvusNodeConfig(
        config=MilvusDropAliasConfig(alias_name="prod_docs"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok())
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"] == {"aliasName": "prod_docs"}
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/aliases/drop"


@pytest.mark.asyncio
async def test_describe_alias(credentials):
    config = MilvusNodeConfig(
        config=MilvusDescribeAliasConfig(alias_name="prod_docs"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok({"aliasName": "prod_docs", "collectionName": "docs"}))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"] == {"aliasName": "prod_docs"}
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/aliases/describe"


@pytest.mark.asyncio
async def test_alter_alias(credentials):
    config = MilvusNodeConfig(
        config=MilvusAlterAliasConfig(collection="docs_v2", alias_name="prod_docs"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok())
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"] == {"collectionName": "docs_v2", "aliasName": "prod_docs"}
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/aliases/alter"


# ---------------------------------------------------------------------------
# Databases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_databases(credentials):
    config = MilvusNodeConfig(config=MilvusListDatabasesConfig(), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, ok(["default", "mydb"]))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/databases/list"
    assert calls[-1]["json"] == {}


@pytest.mark.asyncio
async def test_create_database(credentials):
    config = MilvusNodeConfig(
        config=MilvusCreateDatabaseConfig(db_name="mydb"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok())
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"] == {"dbName": "mydb"}
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/databases/create"


@pytest.mark.asyncio
async def test_drop_database(credentials):
    config = MilvusNodeConfig(
        config=MilvusDropDatabaseConfig(db_name="mydb"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok())
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"] == {"dbName": "mydb"}
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/databases/drop"


@pytest.mark.asyncio
async def test_describe_database(credentials):
    config = MilvusNodeConfig(
        config=MilvusDescribeDatabaseConfig(db_name="mydb"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, ok({"dbName": "mydb"}))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"] == {"dbName": "mydb"}
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/databases/describe"


# ---------------------------------------------------------------------------
# Upload & Index
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_and_index(credentials):
    config = MilvusNodeConfig(
        config=MilvusUploadIndexConfig(
            collection="docs", document="res-id",
            vector_field="vector", text_field="text",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    fake_records = [
        {"id": "abcdef12-3456-7890-abcd-ef1234567890", "values": [0.1],
         "metadata": {"text": "hello", "source": "f.pdf", "chunk_index": 0}},
    ]
    client, calls = create_capturing_client(200, ok({"upsertCount": 1}))
    with patch("nodes.milvus_node.ingest_document", new=AsyncMock(return_value=(fake_records, {"filename": "f.pdf"}))), \
         patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["chunks_indexed"] == 1
    assert result["data"]["source"] == "f.pdf"
    row = calls[-1]["json"]["data"][0]
    assert isinstance(row["id"], int)
    assert row["vector"] == [0.1]
    assert row["text"] == "hello"
    assert calls[-1]["url"] == f"{BASE}/v2/vectordb/entities/upsert"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nonzero_code_promoted_to_error(credentials):
    config = MilvusNodeConfig(
        config=MilvusSearchConfig(collection="docs", vector="[0.1]"), credentials=credentials
    )
    node = create_node(config)
    client, _ = create_capturing_client(200, {"code": 1100, "message": "collection not found"})
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "error"
    assert result["code"] == 1100
    assert "not found" in result["error"].lower()


@pytest.mark.asyncio
async def test_http_error_status(credentials):
    config = MilvusNodeConfig(
        config=MilvusListCollectionsConfig(), credentials=credentials
    )
    node = create_node(config)
    client, _ = create_capturing_client(401, {"code": 80001, "message": "auth failed"})
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 401


@pytest.mark.asyncio
async def test_missing_credentials_raises():
    config = MilvusNodeConfig(config=MilvusListCollectionsConfig(), credentials=None)
    node = create_node(config)
    with pytest.raises(ValueError, match="[Cc]redentials"):
        await node.execute({})


# ---------------------------------------------------------------------------
# Auth header + dynamic options
# ---------------------------------------------------------------------------


def test_auth_header(credentials):
    assert MilvusNode._headers(credentials)["Authorization"] == "Bearer tok_test"


@pytest.mark.asyncio
async def test_load_field_options():
    client, _ = create_capturing_client(200, ok(["docs", "images"]))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        options = await MilvusNode.load_field_options(
            field_name="collection", credential_data={"uri": BASE, "token": "k"}
        )
    assert {o["value"] for o in options} == {"docs", "images"}


@pytest.mark.asyncio
async def test_load_field_options_search_filter():
    client, _ = create_capturing_client(200, ok(["docs", "images"]))
    with patch("nodes.milvus_node.httpx.AsyncClient", return_value=client):
        options = await MilvusNode.load_field_options(
            field_name="collection",
            credential_data={"uri": BASE, "token": "k"},
            search="ima",
        )
    assert len(options) == 1
    assert options[0]["value"] == "images"
