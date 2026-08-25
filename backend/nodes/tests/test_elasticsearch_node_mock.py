"""
Mock tests for the Elasticsearch node.

These verify the node's request shaping across the implemented operation
surface without hitting a live Elasticsearch cluster.
"""

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

from nodes.elasticsearch_node import (
    ESAliasExistsConfig,
    ElasticsearchCredential,
    ElasticsearchNode,
    ElasticsearchNodeConfig,
    ESBulkIndexConfig,
    ESBulkWriteConfig,
    ESCountConfig,
    ESCreateDocConfig,
    ESCreateIndexConfig,
    ESDeleteByQueryConfig,
    ESDeleteDocConfig,
    ESDeleteIndexConfig,
    ESDocumentExistsConfig,
    ESGetDocConfig,
    ESGetDocSourceConfig,
    ESGetIndexConfig,
    ESGetIndexStatsConfig,
    ESGetMappingConfig,
    ESGetSettingsConfig,
    ESIndexExistsConfig,
    ESIndexDocConfig,
    ESListAliasesConfig,
    ESListIndicesConfig,
    ESMultiSearchConfig,
    ESMultiGetConfig,
    ESReindexConfig,
    ESRefreshIndexConfig,
    ESSearchConfig,
    ESUpdateAliasesConfig,
    ESUpdateByQueryConfig,
    ESUpdateDocConfig,
    ESUpdateMappingConfig,
    ESUpdateSettingsConfig,
    ESUploadIndexConfig,
)

BASE = "https://es.example.com"


@pytest.fixture
def credentials():
    return ElasticsearchCredential(url=BASE, api_key="encoded_key")


def create_node(config):
    return ElasticsearchNode(
        node_id="test-es-node",
        node_type="automation-elasticsearch",
        node_data={},
        config=config,
    )


def create_mock_response(status_code=200, json_data=None, text=None):
    response = Mock()
    response.status_code = status_code
    response.json = Mock(return_value=json_data if json_data is not None else {})
    response.text = text if text is not None else ("" if json_data is None else json.dumps(json_data))
    response.content = response.text.encode()
    return response


def create_capturing_client(status_code=200, json_data=None, text=None):
    response = create_mock_response(status_code, json_data, text)
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

    async def aexit(self, *args):
        return None

    client.__aenter__ = aenter
    client.__aexit__ = aexit
    return client, calls


def test_auth_header_api_key(credentials):
    assert ElasticsearchNode._auth_header(credentials)["Authorization"] == "ApiKey encoded_key"


@pytest.mark.asyncio
async def test_search_knn(credentials):
    config = ElasticsearchNodeConfig(
        config=ESSearchConfig(
            index="docs",
            field="vec",
            query_vector="[0.1, 0.2]",
            k=5,
            num_candidates=50,
            similarity=0.42,
            filter='{"term": {"category": "x"}}',
            source="title,content",
            routing="route-1",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"hits": {"hits": []}})
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    sent = calls[-1]
    assert sent["url"] == f"{BASE}/docs/_search"
    assert sent["json"]["knn"]["query_vector"] == [0.1, 0.2]
    assert sent["json"]["knn"]["similarity"] == 0.42
    assert sent["json"]["_source"] == ["title", "content"]
    assert sent["params"] == {"routing": "route-1"}


@pytest.mark.asyncio
async def test_search_query_vector_builder(credentials):
    config = ElasticsearchNodeConfig(
        config=ESSearchConfig(
            index="docs",
            field="vec",
            query_vector_builder='{"text_embedding": {"model_id": "m1", "model_text": "hello"}}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"hits": {"hits": []}})
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        await node.execute({})
    assert calls[-1]["json"]["knn"]["query_vector_builder"]["text_embedding"]["model_id"] == "m1"


def test_search_requires_exactly_one_query_source(credentials):
    with pytest.raises(ValueError, match="exactly one"):
        ElasticsearchNodeConfig(
            config=ESSearchConfig(index="docs", field="vec", query_vector="[0.1]", query_vector_builder='{"lookup": {}}'),
            credentials=credentials,
        )


@pytest.mark.asyncio
async def test_count_with_query(credentials):
    config = ElasticsearchNodeConfig(
        config=ESCountConfig(index="docs", query='{"term": {"tag": "a"}}', routing="route-1"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"count": 1})
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/docs/_count"
    assert calls[-1]["json"] == {"query": {"term": {"tag": "a"}}}
    assert calls[-1]["params"] == {"routing": "route-1"}


@pytest.mark.asyncio
async def test_multi_search(credentials):
    config = ElasticsearchNodeConfig(
        config=ESMultiSearchConfig(
            index="docs",
            searches='[{"body": {"query": {"match_all": {}}}}, {"header": {"index": "other"}, "body": {"query": {"term": {"tag": "a"}}}}]',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"responses": []})
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    sent = calls[-1]
    assert sent["url"] == f"{BASE}/docs/_msearch"
    lines = sent["content"].strip().split("\n")
    assert json.loads(lines[0]) == {}
    assert json.loads(lines[1]) == {"query": {"match_all": {}}}
    assert json.loads(lines[2]) == {"index": "other"}
    assert json.loads(lines[3]) == {"query": {"term": {"tag": "a"}}}


@pytest.mark.asyncio
async def test_index_document(credentials):
    config = ElasticsearchNodeConfig(
        config=ESIndexDocConfig(
            index="docs",
            document='{"content": "a"}',
            id="1",
            pipeline="pipe-1",
            routing="route-1",
            refresh="wait_for",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(201, {"result": "created"})
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["method"] == "PUT"
    assert calls[-1]["url"] == f"{BASE}/docs/_doc/1"
    assert calls[-1]["params"] == {"pipeline": "pipe-1", "routing": "route-1", "refresh": "wait_for"}


@pytest.mark.asyncio
async def test_create_document(credentials):
    config = ElasticsearchNodeConfig(
        config=ESCreateDocConfig(
            index="docs",
            id="1",
            document='{"content": "a"}',
            pipeline="pipe-1",
            routing="route-1",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(201, {"result": "created"})
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["method"] == "PUT"
    assert calls[-1]["url"] == f"{BASE}/docs/_create/1"
    assert calls[-1]["params"] == {"pipeline": "pipe-1", "routing": "route-1", "refresh": "wait_for"}


@pytest.mark.asyncio
async def test_bulk_index(credentials):
    config = ElasticsearchNodeConfig(
        config=ESBulkIndexConfig(
            index="docs",
            documents='[{"_id": "1", "content": "a"}, {"content": "b"}]',
            pipeline="pipe-1",
            routing="route-1",
            refresh="true",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"errors": False, "items": []})
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        await node.execute({})
    sent = calls[-1]
    lines = sent["content"].strip().split("\n")
    assert sent["url"] == f"{BASE}/_bulk"
    assert json.loads(lines[0]) == {"index": {"_index": "docs", "_id": "1"}}
    assert json.loads(lines[1]) == {"content": "a"}
    assert sent["params"] == {"pipeline": "pipe-1", "routing": "route-1", "refresh": "true"}


@pytest.mark.asyncio
async def test_bulk_write(credentials):
    config = ElasticsearchNodeConfig(
        config=ESBulkWriteConfig(
            index="docs",
            actions='[{"action":"index","_id":"1","document":{"content":"a"}},{"action":"create","_id":"2","document":{"content":"b"}},{"action":"update","_id":"1","document":{"content":"aa"},"upsert":{"content":"aa"}},{"action":"delete","_id":"2"}]',
            refresh="true",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"errors": False, "items": []})
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        await node.execute({})
    sent = calls[-1]
    assert sent["url"] == f"{BASE}/docs/_bulk"
    lines = sent["content"].strip().split("\n")
    assert json.loads(lines[0]) == {"index": {"_id": "1"}}
    assert json.loads(lines[1]) == {"content": "a"}
    assert json.loads(lines[2]) == {"create": {"_id": "2"}}
    assert json.loads(lines[3]) == {"content": "b"}
    assert json.loads(lines[4]) == {"update": {"_id": "1"}}
    assert json.loads(lines[5]) == {"doc": {"content": "aa"}, "upsert": {"content": "aa"}}
    assert json.loads(lines[6]) == {"delete": {"_id": "2"}}
    assert sent["params"] == {"refresh": "true"}


@pytest.mark.asyncio
async def test_get_document(credentials):
    config = ElasticsearchNodeConfig(config=ESGetDocConfig(index="docs", id="1", routing="route-1"), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, {"_id": "1"})
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        await node.execute({})
    assert calls[-1]["url"] == f"{BASE}/docs/_doc/1"
    assert calls[-1]["params"] == {"routing": "route-1"}


@pytest.mark.asyncio
async def test_get_document_source(credentials):
    config = ElasticsearchNodeConfig(config=ESGetDocSourceConfig(index="docs", id="1"), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, {"content": "a"})
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        await node.execute({})
    assert calls[-1]["url"] == f"{BASE}/docs/_source/1"


@pytest.mark.asyncio
async def test_document_exists_true_and_false(credentials):
    config = ElasticsearchNodeConfig(config=ESDocumentExistsConfig(index="docs", id="1"), credentials=credentials)
    node = create_node(config)

    ok_client, _ = create_capturing_client(200, None, "")
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=ok_client):
        result = await node.execute({})
    assert result["data"]["exists"] is True

    missing_client, _ = create_capturing_client(404, None, "")
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=missing_client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["exists"] is False


@pytest.mark.asyncio
async def test_multi_get_with_default_index(credentials):
    config = ElasticsearchNodeConfig(config=ESMultiGetConfig(index="docs", items='["1","2"]'), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, {"docs": []})
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        await node.execute({})
    assert calls[-1]["url"] == f"{BASE}/docs/_mget"
    assert calls[-1]["json"] == {"ids": ["1", "2"]}


@pytest.mark.asyncio
async def test_multi_get_with_explicit_docs(credentials):
    config = ElasticsearchNodeConfig(
        config=ESMultiGetConfig(items='[{"_index": "docs", "_id": "1"}]'),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"docs": []})
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        await node.execute({})
    assert calls[-1]["url"] == f"{BASE}/_mget"
    assert calls[-1]["json"] == {"docs": [{"_index": "docs", "_id": "1"}]}


@pytest.mark.asyncio
async def test_update_document(credentials):
    config = ElasticsearchNodeConfig(
        config=ESUpdateDocConfig(
            index="docs",
            id="1",
            document='{"status": "done"}',
            upsert='{"status": "new"}',
            refresh="wait_for",
            retry_on_conflict=2,
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"result": "updated"})
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        await node.execute({})
    assert calls[-1]["url"] == f"{BASE}/docs/_update/1"
    assert calls[-1]["json"]["doc"] == {"status": "done"}
    assert calls[-1]["json"]["upsert"] == {"status": "new"}
    assert calls[-1]["params"] == {"refresh": "wait_for", "retry_on_conflict": 2}


def test_update_document_requires_doc_or_script(credentials):
    with pytest.raises(ValueError, match="Partial Document or Script"):
        ElasticsearchNodeConfig(config=ESUpdateDocConfig(index="docs", id="1"), credentials=credentials)


@pytest.mark.asyncio
async def test_delete_document(credentials):
    config = ElasticsearchNodeConfig(config=ESDeleteDocConfig(index="docs", id="1", routing="route-1"), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, {"result": "deleted"})
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        await node.execute({})
    assert calls[-1]["url"] == f"{BASE}/docs/_doc/1"
    assert calls[-1]["params"] == {"routing": "route-1", "refresh": "wait_for"}


@pytest.mark.asyncio
async def test_delete_by_query(credentials):
    config = ElasticsearchNodeConfig(
        config=ESDeleteByQueryConfig(index="docs", query='{"term": {"tag": "a"}}', wait_for_completion=False),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"task": "1"})
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        await node.execute({})
    assert calls[-1]["url"] == f"{BASE}/docs/_delete_by_query"
    assert calls[-1]["json"] == {"query": {"term": {"tag": "a"}}}
    assert calls[-1]["params"] == {"conflicts": "proceed", "refresh": "true", "wait_for_completion": "false"}


@pytest.mark.asyncio
async def test_update_by_query(credentials):
    config = ElasticsearchNodeConfig(
        config=ESUpdateByQueryConfig(
            index="docs",
            query='{"match_all": {}}',
            script='{"source": "ctx._source.flag = true"}',
            requests_per_second=10.5,
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"updated": 2})
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        await node.execute({})
    assert calls[-1]["url"] == f"{BASE}/docs/_update_by_query"
    assert calls[-1]["json"]["script"] == {"source": "ctx._source.flag = true"}
    assert calls[-1]["params"]["requests_per_second"] == 10.5


@pytest.mark.asyncio
async def test_reindex_documents(credentials):
    config = ElasticsearchNodeConfig(
        config=ESReindexConfig(
            source_index="docs-src",
            dest_index="docs-dst",
            query='{"match_all": {}}',
            script='{"source": "ctx._source.copied = true"}',
            max_docs=10,
            dest_pipeline="pipe-1",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"created": 10})
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        await node.execute({})
    assert calls[-1]["url"] == f"{BASE}/_reindex"
    assert calls[-1]["json"]["source"]["index"] == "docs-src"
    assert calls[-1]["json"]["dest"] == {"index": "docs-dst", "pipeline": "pipe-1"}
    assert calls[-1]["json"]["conflicts"] == "proceed"
    assert calls[-1]["params"] == {"refresh": "true", "wait_for_completion": "true"}


@pytest.mark.asyncio
async def test_list_indices(credentials):
    config = ElasticsearchNodeConfig(config=ESListIndicesConfig(), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(
        200,
        {"indices": [{"name": "docs", "attributes": ["open"]}, {"name": ".kibana", "attributes": ["open"]}]},
    )
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert calls[-1]["url"] == f"{BASE}/_resolve/index/*"
    assert result["data"] == [{"name": "docs", "attributes": ["open"], "aliases": [], "data_stream": None, "mode": None}]


@pytest.mark.asyncio
async def test_index_and_alias_exists(credentials):
    index_node = create_node(ElasticsearchNodeConfig(config=ESIndexExistsConfig(index="docs"), credentials=credentials))
    alias_node = create_node(ElasticsearchNodeConfig(config=ESAliasExistsConfig(index="docs", name="docs-live"), credentials=credentials))

    ok_client, _ = create_capturing_client(200, None, "")
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=ok_client):
        result = await index_node.execute({})
    assert result["status"] == "success"
    assert result["data"]["exists"] is True

    missing_client, _ = create_capturing_client(404, None, "")
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=missing_client):
        result = await alias_node.execute({})
    assert result["status"] == "success"
    assert result["data"]["exists"] is False


@pytest.mark.asyncio
async def test_load_field_options_hides_system_indices():
    client, _ = create_capturing_client(
        200,
        {"indices": [{"name": "docs"}, {"name": ".kibana"}, {"name": "images"}]},
    )
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        options = await ElasticsearchNode.load_field_options("index", {"url": BASE, "api_key": "k"})
    assert {o["value"] for o in options} == {"docs", "images"}


@pytest.mark.asyncio
async def test_index_metadata_operations(credentials):
    operations = [
        (ESIndexExistsConfig(index="docs"), "HEAD", f"{BASE}/docs", None),
        (ESGetIndexConfig(index="docs", include_defaults=True, flat_settings=True), "GET", f"{BASE}/docs", {"include_defaults": "true", "flat_settings": "true"}),
        (ESDeleteIndexConfig(index="docs"), "DELETE", f"{BASE}/docs", None),
        (ESRefreshIndexConfig(index="docs"), "POST", f"{BASE}/docs/_refresh", None),
        (ESGetMappingConfig(index="docs"), "GET", f"{BASE}/docs/_mapping", None),
        (ESGetSettingsConfig(index="docs", include_defaults=True), "GET", f"{BASE}/docs/_settings", {"include_defaults": "true", "flat_settings": "false"}),
        (ESListAliasesConfig(index="docs", name="live"), "GET", f"{BASE}/docs/_alias/live", None),
        (ESAliasExistsConfig(index="docs", name="live"), "HEAD", f"{BASE}/docs/_alias/live", None),
        (ESGetIndexStatsConfig(index="docs", metrics="docs,store"), "GET", f"{BASE}/docs/_stats/docs,store", None),
    ]
    for op_config, method, url, params in operations:
        node = create_node(ElasticsearchNodeConfig(config=op_config, credentials=credentials))
        client, calls = create_capturing_client(200, {})
        with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert calls[-1]["method"] == method
        assert calls[-1]["url"] == url
        if params is None:
            assert calls[-1].get("params") in (None, {})
        else:
            assert calls[-1]["params"] == params


@pytest.mark.asyncio
async def test_create_update_index_operations(credentials):
    operations = [
        (
            ESCreateIndexConfig(index="docs", mappings='{"properties": {"vec": {"type": "dense_vector", "dims": 3}}}', settings='{"number_of_shards": 1}'),
            f"{BASE}/docs",
            {"mappings": {"properties": {"vec": {"type": "dense_vector", "dims": 3}}}, "settings": {"number_of_shards": 1}},
            None,
        ),
        (
            ESUpdateMappingConfig(index="docs", mappings='{"properties": {"tag": {"type": "keyword"}}}'),
            f"{BASE}/docs/_mapping",
            {"properties": {"tag": {"type": "keyword"}}},
            None,
        ),
        (
            ESUpdateSettingsConfig(index="docs", settings='{"index.refresh_interval": "1s"}', preserve_existing=True),
            f"{BASE}/docs/_settings",
            {"index.refresh_interval": "1s"},
            {"preserve_existing": "true"},
        ),
        (
            ESUpdateAliasesConfig(actions='[{"add": {"index": "docs", "alias": "docs-live"}}]'),
            f"{BASE}/_aliases",
            {"actions": [{"add": {"index": "docs", "alias": "docs-live"}}]},
            None,
        ),
    ]
    for op_config, url, expected_body, expected_params in operations:
        node = create_node(ElasticsearchNodeConfig(config=op_config, credentials=credentials))
        client, calls = create_capturing_client(200, {"acknowledged": True})
        with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
            await node.execute({})
        assert calls[-1]["url"] == url
        assert calls[-1]["json"] == expected_body
        assert calls[-1].get("params") == expected_params


@pytest.mark.asyncio
async def test_upload_and_index(credentials):
    config = ElasticsearchNodeConfig(
        config=ESUploadIndexConfig(index="docs", document="res-id", vector_field="vec", text_field="text", pipeline="pipe-1", refresh="true"),
        credentials=credentials,
    )
    node = create_node(config)
    fake_records = [{"id": "u0", "values": [0.1], "metadata": {"text": "a", "source": "f.pdf", "chunk_index": 0}}]
    client, calls = create_capturing_client(200, {"errors": False, "items": []})
    with patch("nodes.elasticsearch_node.ingest_document", new=AsyncMock(return_value=(fake_records, {"filename": "f.pdf"}))), \
         patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["chunks_indexed"] == 1
    sent = calls[-1]
    assert sent["url"] == f"{BASE}/_bulk"
    assert sent["params"] == {"pipeline": "pipe-1", "refresh": "true"}


@pytest.mark.asyncio
async def test_missing_credentials_raises():
    config = ElasticsearchNodeConfig(config=ESListIndicesConfig(), credentials=None)
    node = create_node(config)
    with pytest.raises(ValueError, match="[Cc]redentials"):
        await node.execute({})


@pytest.mark.asyncio
async def test_api_error_surfaced(credentials):
    config = ElasticsearchNodeConfig(config=ESSearchConfig(index="docs", field="vec", query_vector="[0.1]"), credentials=credentials)
    node = create_node(config)
    client, _ = create_capturing_client(
        404,
        {"error": {"type": "index_not_found_exception", "reason": "no such index [docs]"}, "status": 404},
    )
    with patch("nodes.elasticsearch_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 404
    assert "no such index" in result["error"].lower()
