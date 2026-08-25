"""
Live integration tests for the Elasticsearch node.

Required environment variables (at least one pair):
- ELASTICSEARCH_URI + ELASTICSEARCH_API_KEY   (from backend/.env)
- ELASTICSEARCH_TEST_URL + ELASTICSEARCH_TEST_API_KEY  (alternative names)
"""

import os
import time
from typing import Any, Dict

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
)

# Accept either naming convention
TEST_URL = os.getenv("ELASTICSEARCH_URI") or os.getenv("ELASTICSEARCH_TEST_URL")
TEST_API_KEY = os.getenv("ELASTICSEARCH_API_KEY") or os.getenv("ELASTICSEARCH_TEST_API_KEY")

pytestmark = pytest.mark.skipif(
    not TEST_URL or not TEST_API_KEY,
    reason="Elasticsearch credentials not configured (set ELASTICSEARCH_URI + ELASTICSEARCH_API_KEY)",
)

TEST_STATE: Dict[str, Any] = {
    "source_index": f"noclick-es-it-src-{int(time.time())}",
    "dest_index": f"noclick-es-it-dst-{int(time.time())}",
    "alias": f"noclick-es-it-alias-{int(time.time())}",
}

VECTOR_MAPPINGS = (
    '{"properties": {"vec": {"type": "dense_vector", "dims": 3, "similarity": "cosine"}, '
    '"content": {"type": "text"}, "tag": {"type": "keyword"}, "flag": {"type": "boolean"}}}'
)


def make_credential() -> ElasticsearchCredential:
    return ElasticsearchCredential(url=TEST_URL, api_key=TEST_API_KEY)


def create_node(config, credential: ElasticsearchCredential | None = None) -> ElasticsearchNode:
    node_config = ElasticsearchNodeConfig(config=config, credentials=credential or make_credential())
    return ElasticsearchNode(
        node_id="test-es-node",
        node_type="automation-elasticsearch",
        node_data={},
        config=node_config,
        workflow_id="test-es-workflow",
    )


class TestElasticsearchNodeIntegration:
    @pytest.mark.asyncio
    async def test_01_create_index_and_read_metadata(self):
        node = create_node(
            ESCreateIndexConfig(
                index=TEST_STATE["source_index"],
                mappings=VECTOR_MAPPINGS,
                aliases=f'{{"{TEST_STATE["alias"]}": {{}}}}',
            )
        )
        created = await node.execute({})
        assert created["status"] == "success"

        exists = await create_node(ESIndexExistsConfig(index=TEST_STATE["source_index"])).execute({})
        assert exists["status"] == "success"
        assert exists["data"]["exists"] is True

        index_info = await create_node(ESGetIndexConfig(index=TEST_STATE["source_index"])).execute({})
        assert index_info["status"] == "success"
        assert TEST_STATE["source_index"] in index_info["data"]

        mapping = await create_node(ESGetMappingConfig(index=TEST_STATE["source_index"])).execute({})
        assert mapping["status"] == "success"
        props = mapping["data"][TEST_STATE["source_index"]]["mappings"]["properties"]
        assert props["vec"]["type"] == "dense_vector"

        settings = await create_node(ESGetSettingsConfig(index=TEST_STATE["source_index"])).execute({})
        assert settings["status"] == "success"
        assert isinstance(settings["data"], dict)

    @pytest.mark.asyncio
    async def test_02_update_mapping_settings_and_stats(self):
        updated_mapping = await create_node(
            ESUpdateMappingConfig(
                index=TEST_STATE["source_index"],
                mappings='{"properties": {"flag": {"type": "boolean"}}}',
            )
        ).execute({})
        assert updated_mapping["status"] == "success"

        updated_settings = await create_node(
            ESUpdateSettingsConfig(
                index=TEST_STATE["source_index"],
                settings='{"index.refresh_interval": "5s"}',
            )
        ).execute({})
        assert updated_settings["status"] == "success"

        stats = await create_node(ESGetIndexStatsConfig(index=TEST_STATE["source_index"], metrics="docs,store")).execute({})
        if stats["status"] == "success":
            assert "_all" in stats["data"]
        else:
            # Serverless Elasticsearch returns 410 for _stats
            assert stats["status_code"] == 410
            assert "serverless mode" in stats["error"].lower()

        indices = await create_node(ESListIndicesConfig()).execute({})
        assert indices["status"] == "success"
        names = {item["name"] for item in indices["data"]}
        assert TEST_STATE["source_index"] in names

    @pytest.mark.asyncio
    async def test_03_document_reads_search_and_count(self):
        indexed = await create_node(
            ESIndexDocConfig(
                index=TEST_STATE["source_index"],
                id="1",
                document='{"content": "alpha doc", "vec": [0.1, 0.2, 0.3], "tag": "a"}',
            )
        ).execute({})
        assert indexed["status"] == "success"

        exists = await create_node(ESDocumentExistsConfig(index=TEST_STATE["source_index"], id="1")).execute({})
        assert exists["status"] == "success"
        assert exists["data"]["exists"] is True

        got = await create_node(ESGetDocConfig(index=TEST_STATE["source_index"], id="1")).execute({})
        assert got["status"] == "success"
        assert got["data"]["_source"]["content"] == "alpha doc"

        source = await create_node(ESGetDocSourceConfig(index=TEST_STATE["source_index"], id="1")).execute({})
        assert source["status"] == "success"
        assert source["data"]["content"] == "alpha doc"

        mget = await create_node(ESMultiGetConfig(index=TEST_STATE["source_index"], items='["1"]')).execute({})
        assert mget["status"] == "success"
        assert len(mget["data"]["docs"]) == 1

        count = await create_node(
            ESCountConfig(index=TEST_STATE["source_index"], query='{"term": {"tag": "a"}}')
        ).execute({})
        assert count["status"] == "success"
        assert count["data"]["count"] == 1

        search = await create_node(
            ESSearchConfig(
                index=TEST_STATE["source_index"],
                field="vec",
                query_vector="[0.1, 0.2, 0.31]",
                k=1,
                num_candidates=10,
                source="content,tag",
            )
        ).execute({})
        assert search["status"] == "success"
        hits = search["data"]["hits"]["hits"]
        assert len(hits) == 1
        assert hits[0]["_id"] == "1"

    @pytest.mark.asyncio
    async def test_04_bulk_write_and_msearch(self):
        created = await create_node(
            ESCreateDocConfig(
                index=TEST_STATE["source_index"],
                id="2",
                document='{"content": "beta doc", "vec": [0.1, 0.2, 0.29], "tag": "b"}',
            )
        ).execute({})
        assert created["status"] == "success"

        bulk = await create_node(
            ESBulkWriteConfig(
                index=TEST_STATE["source_index"],
                actions='[{"action":"index","_id":"3","document":{"content":"gamma doc","vec":[0.9,0.1,0.1],"tag":"c"}},{"action":"update","_id":"1","document":{"tag":"updated"},"upsert":{"tag":"updated"}}]',
            )
        ).execute({})
        assert bulk["status"] == "success"
        assert bulk["data"]["errors"] is False

        refreshed = await create_node(ESRefreshIndexConfig(index=TEST_STATE["source_index"])).execute({})
        assert refreshed["status"] == "success"

        msearch = await create_node(
            ESMultiSearchConfig(
                index=TEST_STATE["source_index"],
                searches='[{"body":{"query":{"term":{"tag":"updated"}},"size":10}},{"body":{"query":{"term":{"tag":"b"}},"size":10}}]',
            )
        ).execute({})
        assert msearch["status"] == "success"
        assert len(msearch["data"]["responses"]) == 2

    @pytest.mark.asyncio
    async def test_05_update_by_query_delete_by_query_and_refresh(self):
        update_by_query = await create_node(
            ESUpdateByQueryConfig(
                index=TEST_STATE["source_index"],
                query='{"term": {"tag": "b"}}',
                script='{"source": "ctx._source.flag = true"}',
            )
        ).execute({})
        assert update_by_query["status"] == "success"
        assert update_by_query["data"]["updated"] >= 1

        refreshed = await create_node(ESRefreshIndexConfig(index=TEST_STATE["source_index"])).execute({})
        assert refreshed["status"] == "success"

        delete_by_query = await create_node(
            ESDeleteByQueryConfig(
                index=TEST_STATE["source_index"],
                query='{"term": {"tag": "c"}}',
            )
        ).execute({})
        assert delete_by_query["status"] == "success"
        assert delete_by_query["data"]["deleted"] >= 1

    @pytest.mark.asyncio
    async def test_06_aliases_and_reindex(self):
        aliases = await create_node(ESListAliasesConfig(index=TEST_STATE["source_index"], name=TEST_STATE["alias"])).execute({})
        assert aliases["status"] == "success"
        assert TEST_STATE["source_index"] in aliases["data"]

        alias_exists = await create_node(
            ESAliasExistsConfig(index=TEST_STATE["source_index"], name=TEST_STATE["alias"])
        ).execute({})
        assert alias_exists["status"] == "success"
        assert alias_exists["data"]["exists"] is True

        created_dest = await create_node(
            ESCreateIndexConfig(
                index=TEST_STATE["dest_index"],
                mappings=VECTOR_MAPPINGS,
            )
        ).execute({})
        assert created_dest["status"] == "success"

        reindexed = await create_node(
            ESReindexConfig(
                source_index=TEST_STATE["source_index"],
                dest_index=TEST_STATE["dest_index"],
                query='{"match_all": {}}',
            )
        ).execute({})
        assert reindexed["status"] == "success"
        assert reindexed["data"]["created"] >= 1

        dest_count = await create_node(ESCountConfig(index=TEST_STATE["dest_index"])).execute({})
        assert dest_count["status"] == "success"
        assert dest_count["data"]["count"] >= 1

    @pytest.mark.asyncio
    async def test_07_cleanup(self):
        deleted_doc = await create_node(ESDeleteDocConfig(index=TEST_STATE["source_index"], id="1")).execute({})
        assert deleted_doc["status"] == "success"

        deleted_source = await create_node(ESDeleteIndexConfig(index=TEST_STATE["source_index"])).execute({})
        assert deleted_source["status"] == "success"

        deleted_dest = await create_node(ESDeleteIndexConfig(index=TEST_STATE["dest_index"])).execute({})
        assert deleted_dest["status"] == "success"
