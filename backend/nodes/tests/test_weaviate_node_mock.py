"""
Mock tests for the Weaviate vector database node.

Verifies GraphQL query assembly (nearVector / nearText / hybrid / generative /
aggregate), REST object + schema endpoints, GraphQL-error promotion, config
parsing, dynamic options, where-filter inline GQL, target_vector injection,
and all error/validation paths. No live API.
"""

import json

import pytest
from unittest.mock import Mock, patch, AsyncMock

from nodes.weaviate_node import (
    WeaviateNode,
    WeaviateNodeConfig,
    WeaviateCredential,
    WeaviateQueryConfig,
    WeaviateQueryTextConfig,
    WeaviateHybridSearchConfig,
    WeaviateGenerativeSearchConfig,
    WeaviateAggregateConfig,
    WeaviateInsertConfig,
    WeaviateGetConfig,
    WeaviateUpdateConfig,
    WeaviateDeleteConfig,
    WeaviateListCollectionsConfig,
    WeaviateCreateCollectionConfig,
    WeaviateDeleteCollectionConfig,
    WeaviateBatchDeleteConfig,
    WeaviateUploadIndexConfig,
    _build_get_query,
    _build_generative_query,
    _build_aggregate_query,
    _property_fields,
    _parse_where_filter,
)

BASE = "https://my-cluster.weaviate.network"


@pytest.fixture
def credentials():
    return WeaviateCredential(url=BASE, api_key="wk_test")


def create_node(config):
    return WeaviateNode(
        node_id="test-weaviate-node",
        node_type="automation-weaviate",
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
# GraphQL assembly helpers
# ---------------------------------------------------------------------------


def test_property_fields():
    assert _property_fields("title, content") == "title content"
    assert _property_fields(None) == ""
    assert _property_fields("") == ""


def test_build_get_query():
    q = _build_get_query("Doc", "nearVector: {vector: [0.1]}", "title", 5)
    assert "Get { Doc(nearVector: {vector: [0.1]}, limit: 5)" in q
    assert "title _additional { id distance }" in q


def test_build_generative_query_single():
    q = _build_generative_query("Doc", "nearVector: {vector: [0.1]}", "title", 3, single_prompt="Summarize: {title}")
    assert "generate(" in q
    assert "singleResult:" in q
    assert "Summarize: {title}" in q
    assert "groupedResult" in q  # field requested in _additional even if no groupedResult arg
    assert "_additional { id distance generate(" in q


def test_build_generative_query_grouped():
    q = _build_generative_query("Doc", "nearText: {concepts: [\"ai\"]}", "", 5, group_task="What do these share?")
    assert "groupedResult: { task:" in q
    assert "What do these share?" in q
    assert "singleResult" in q  # field in _additional block


def test_build_generative_query_both():
    q = _build_generative_query("Doc", "nearVector: {vector: [0.1]}", "body", 5,
                                 single_prompt="Summarize: {body}", group_task="Common themes?")
    assert "singleResult: { prompt:" in q
    assert "groupedResult: { task:" in q


def test_build_aggregate_query_count_only():
    q = _build_aggregate_query("Doc")
    assert "Aggregate { Doc" in q
    assert "meta { count }" in q
    assert "groupedBy" not in q


def test_build_aggregate_query_with_properties():
    q = _build_aggregate_query("Doc", properties_json='[{"name":"score","stats":["mean","maximum"]}]')
    assert "score { mean maximum }" in q
    assert "meta { count }" in q


def test_build_aggregate_query_top_occurrences():
    q = _build_aggregate_query("Doc", properties_json='[{"name":"category","topOccurrences":5}]')
    assert "category { topOccurrences(limit: 5) { value occurs } }" in q


def test_build_aggregate_query_with_where():
    q = _build_aggregate_query("Doc", where_gql='path: ["status"], operator: Equal, valueText: "published"')
    assert "where: {" in q


def test_build_aggregate_query_with_group_by():
    q = _build_aggregate_query("Doc", group_by="category", limit=10)
    assert 'groupBy: ["category"]' in q
    assert "limit: 10" in q
    assert "groupedBy { value path }" in q


# ---------------------------------------------------------------------------
# Search (GraphQL)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_near_vector(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateQueryConfig(
            collection="Doc", vector="[0.1, 0.2]", properties="title,content", limit=5
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"data": {"Get": {"Doc": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v1/graphql"
    gql = calls[-1]["json"]["query"]
    assert "nearVector: {vector: [0.1, 0.2]}" in gql
    assert "limit: 5" in gql
    assert "title content" in gql


@pytest.mark.asyncio
async def test_query_with_target_vector(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateQueryConfig(collection="Doc", vector="[0.1]", target_vector="title_vec"),
        credentials=credentials,
    )
    client, calls = create_capturing_client(200, {"data": {"Get": {"Doc": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await create_node(config).execute({})
    assert result["status"] == "success"
    gql = calls[-1]["json"]["query"]
    assert 'targetVectors: ["title_vec"]' in gql
    assert "nearVector: {vector: [0.1]" in gql


@pytest.mark.asyncio
async def test_query_text_near_text(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateQueryTextConfig(collection="Doc", text="what is rag?", limit=3),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"data": {"Get": {"Doc": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    gql = calls[-1]["json"]["query"]
    assert 'nearText: {concepts: ["what is rag?"]}' in gql


@pytest.mark.asyncio
async def test_query_text_with_target_vector(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateQueryTextConfig(collection="Doc", text="rag", target_vector="body_vec"),
        credentials=credentials,
    )
    client, calls = create_capturing_client(200, {"data": {"Get": {"Doc": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await create_node(config).execute({})
    assert result["status"] == "success"
    gql = calls[-1]["json"]["query"]
    assert 'targetVectors: ["body_vec"]' in gql
    assert 'nearText: {concepts: ["rag"]' in gql


@pytest.mark.asyncio
async def test_query_malformed_vector(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateQueryConfig(collection="Doc", vector="oops"), credentials=credentials
    )
    node = create_node(config)
    result = await node.execute({})
    assert result["status"] == "error"
    assert "json array" in result["error"].lower()


@pytest.mark.asyncio
async def test_graphql_errors_promoted(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateQueryConfig(collection="Doc", vector="[0.1]"), credentials=credentials
    )
    node = create_node(config)
    client, _ = create_capturing_client(200, {"errors": [{"message": "no such class"}]})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "error"
    assert result["error"][0]["message"] == "no such class"


# ---------------------------------------------------------------------------
# Objects (REST)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateInsertConfig(
            collection="Doc", properties='{"title": "T"}', vector="[0.1, 0.2]", id="uuid-1"
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"id": "uuid-1"})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v1/objects"
    body = calls[-1]["json"]
    assert body["class"] == "Doc"
    assert body["properties"] == {"title": "T"}
    assert body["vector"] == [0.1, 0.2]
    assert body["id"] == "uuid-1"


@pytest.mark.asyncio
async def test_insert_malformed_properties(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateInsertConfig(collection="Doc", properties="[]"), credentials=credentials
    )
    node = create_node(config)
    result = await node.execute({})
    assert result["status"] == "error"
    assert "json object" in result["error"].lower()


@pytest.mark.asyncio
async def test_insert_empty_vector_rejected(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateInsertConfig(collection="Doc", properties="{}", vector="[]"),
        credentials=credentials,
    )
    result = await create_node(config).execute({})
    assert result["status"] == "error"
    assert "non-empty" in result["error"].lower()


@pytest.mark.asyncio
async def test_get(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateGetConfig(collection="Doc", id="uuid-1"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"id": "uuid-1"})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v1/objects/Doc/uuid-1"
    assert calls[-1]["method"] == "GET"


@pytest.mark.asyncio
async def test_delete(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateDeleteConfig(collection="Doc", id="uuid-1"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(204, None)
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v1/objects/Doc/uuid-1"
    assert calls[-1]["method"] == "DELETE"


# ---------------------------------------------------------------------------
# Schema (REST)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_collections(credentials):
    config = WeaviateNodeConfig(config=WeaviateListCollectionsConfig(), credentials=credentials)
    node = create_node(config)
    client, calls = create_capturing_client(200, {"classes": [{"class": "Doc"}]})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v1/schema"


@pytest.mark.asyncio
async def test_create_collection(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateCreateCollectionConfig(
            name="Doc", vectorizer="text2vec-openai",
            properties='[{"name": "title", "dataType": ["text"]}]',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"class": "Doc"})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert body["class"] == "Doc"
    assert body["vectorizer"] == "text2vec-openai"
    assert body["properties"][0]["name"] == "title"


# ---------------------------------------------------------------------------
# Auth + credentials + dynamic options
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_and_index(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateUploadIndexConfig(collection="Doc", document="res-id"), credentials=credentials
    )
    node = create_node(config)
    fake_records = [
        {"id": "uuid-0", "values": [0.1], "metadata": {"text": "a", "source": "f.pdf", "chunk_index": 0}},
    ]
    client, calls = create_capturing_client(200, [{"result": {"status": "SUCCESS"}}])
    with patch("nodes.weaviate_node.ingest_document", new=AsyncMock(return_value=(fake_records, {"filename": "f.pdf"}))), \
         patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["chunks_indexed"] == 1
    assert calls[-1]["url"] == f"{BASE}/v1/batch/objects"
    obj = calls[-1]["json"]["objects"][0]
    assert obj["class"] == "Doc"
    assert obj["id"] == "uuid-0"
    assert obj["vector"] == [0.1]
    assert obj["properties"]["text"] == "a"


def test_auth_header():
    cred = WeaviateCredential(url=BASE, api_key="wk_test")
    assert WeaviateNode._headers(cred)["Authorization"] == "Bearer wk_test"


def test_no_auth_header_when_absent():
    cred = WeaviateCredential(url=BASE, api_key=None)
    assert "Authorization" not in WeaviateNode._headers(cred)


@pytest.mark.asyncio
async def test_missing_credentials_raises():
    config = WeaviateNodeConfig(config=WeaviateListCollectionsConfig(), credentials=None)
    node = create_node(config)
    with pytest.raises(ValueError, match="[Cc]redentials"):
        await node.execute({})


@pytest.mark.asyncio
async def test_load_field_options():
    client, _ = create_capturing_client(200, {"classes": [{"class": "Doc"}, {"class": "Image"}]})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        options = await WeaviateNode.load_field_options(
            field_name="collection", credential_data={"url": BASE, "api_key": "k"}
        )
    assert {o["value"] for o in options} == {"Doc", "Image"}


# ---------------------------------------------------------------------------
# Module API key headers (original + new providers)
# ---------------------------------------------------------------------------


def test_module_api_key_headers():
    cred = WeaviateCredential(url=BASE, api_key="wk", openai_api_key="oai", cohere_api_key="coh", huggingface_api_key="hf")
    h = WeaviateNode._headers(cred)
    assert h["Authorization"] == "Bearer wk"
    assert h["X-OpenAI-Api-Key"] == "oai"
    assert h["X-Cohere-Api-Key"] == "coh"
    assert h["X-HuggingFace-Api-Key"] == "hf"


def test_generative_provider_headers():
    cred = WeaviateCredential(
        url=BASE,
        anthropic_api_key="ant",
        google_api_key="goog",
        mistral_api_key="mist",
    )
    h = WeaviateNode._headers(cred)
    assert h["X-Anthropic-Api-Key"] == "ant"
    assert h["X-Google-Api-Key"] == "goog"
    assert h["X-Mistral-Api-Key"] == "mist"
    assert "X-OpenAI-Api-Key" not in h


def test_module_headers_absent_when_not_set():
    cred = WeaviateCredential(url=BASE)
    h = WeaviateNode._headers(cred)
    assert "X-OpenAI-Api-Key" not in h
    assert "X-Cohere-Api-Key" not in h
    assert "X-Anthropic-Api-Key" not in h
    assert "X-Google-Api-Key" not in h
    assert "X-Mistral-Api-Key" not in h
    assert "X-Weaviate-Api-Key" not in h
    assert "X-Weaviate-Cluster-Url" not in h


def test_weaviate_embedding_headers():
    cred = WeaviateCredential(url=BASE, weaviate_embedding_api_key="eng_testkey")
    h = WeaviateNode._headers(cred)
    assert h["X-Weaviate-Api-Key"] == "eng_testkey"
    assert h["X-Weaviate-Cluster-Url"] == BASE


# ---------------------------------------------------------------------------
# Bug fix: empty vector guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_empty_vector_rejected(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateQueryConfig(collection="Doc", vector="[]"), credentials=credentials
    )
    result = await create_node(config).execute({})
    assert result["status"] == "error"
    assert "non-empty" in result["error"]


# ---------------------------------------------------------------------------
# Where filter injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_with_where_inline_gql(credentials):
    where = '{"path":["category"],"operator":"Equal","valueText":"news"}'
    config = WeaviateNodeConfig(
        config=WeaviateQueryConfig(collection="Doc", vector="[0.1]", where=where),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"data": {"Get": {"Doc": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert "variables" not in body
    gql = body["query"]
    assert 'where: {path: ["category"], operator: Equal, valueText: "news"}' in gql


@pytest.mark.asyncio
async def test_query_with_bad_where_rejected(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateQueryConfig(collection="Doc", vector="[0.1]", where="not-json"),
        credentials=credentials,
    )
    result = await create_node(config).execute({})
    assert result["status"] == "error"
    assert "WhereFilter" in result["error"] or "where" in result["error"].lower()


def test_parse_where_filter_valid():
    obj, gql = _parse_where_filter('{"path":["x"],"operator":"Equal","valueText":"y"}')
    assert obj == {"path": ["x"], "operator": "Equal", "valueText": "y"}
    assert 'path: ["x"]' in gql
    assert "operator: Equal" in gql
    assert 'valueText: "y"' in gql


def test_parse_where_filter_empty():
    assert _parse_where_filter(None) == (None, None)
    assert _parse_where_filter("") == (None, None)


def test_parse_where_filter_bad_json():
    assert _parse_where_filter("oops") == (False, None)


# ---------------------------------------------------------------------------
# Update (PATCH)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_object(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateUpdateConfig(
            collection="Doc", id="uuid-1", properties='{"title": "Updated"}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(204, None)
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v1/objects/Doc/uuid-1"
    assert calls[-1]["method"] == "PATCH"
    assert calls[-1]["json"] == {"properties": {"title": "Updated"}}


@pytest.mark.asyncio
async def test_update_with_vector(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateUpdateConfig(collection="Doc", id="uuid-1", vector="[0.5, 0.6]"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(204, None)
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"] == {"vector": [0.5, 0.6]}


@pytest.mark.asyncio
async def test_update_no_fields_rejected(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateUpdateConfig(collection="Doc", id="uuid-1"), credentials=credentials
    )
    result = await create_node(config).execute({})
    assert result["status"] == "error"
    assert "at least one" in result["error"]


@pytest.mark.asyncio
async def test_update_malformed_properties(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateUpdateConfig(collection="Doc", id="uuid-1", properties="[]"),
        credentials=credentials,
    )
    result = await create_node(config).execute({})
    assert result["status"] == "error"
    assert "json object" in result["error"].lower()


# ---------------------------------------------------------------------------
# Hybrid search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hybrid_search(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateHybridSearchConfig(
            collection="Doc", query="machine learning", alpha=0.5, properties="title,content", limit=5
        ),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"data": {"Get": {"Doc": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    gql = body["query"]
    assert 'hybrid: {query: "machine learning", alpha: 0.5}' in gql
    assert "limit: 5" in gql
    assert "title content" in gql
    assert "_additional { id score }" in gql
    assert "variables" not in body  # no where filter


@pytest.mark.asyncio
async def test_hybrid_search_with_override_vector(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateHybridSearchConfig(collection="Doc", query="q", alpha=0.75, vector="[0.1, 0.2]"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"data": {"Get": {"Doc": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert "vector: [0.1, 0.2]" in calls[-1]["json"]["query"]


@pytest.mark.asyncio
async def test_hybrid_search_with_target_vector(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateHybridSearchConfig(collection="Doc", query="q", target_vector="body_vec"),
        credentials=credentials,
    )
    client, calls = create_capturing_client(200, {"data": {"Get": {"Doc": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await create_node(config).execute({})
    assert result["status"] == "success"
    gql = calls[-1]["json"]["query"]
    assert 'targetVectors: ["body_vec"]' in gql
    assert "hybrid: {" in gql


@pytest.mark.asyncio
async def test_hybrid_search_with_where(credentials):
    where = '{"path":["published"],"operator":"Equal","valueBoolean":true}'
    config = WeaviateNodeConfig(
        config=WeaviateHybridSearchConfig(collection="Doc", query="news", alpha=0.75, where=where),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"data": {"Get": {"Doc": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    body = calls[-1]["json"]
    assert "variables" not in body
    gql = body["query"]
    assert 'path: ["published"]' in gql
    assert "operator: Equal" in gql
    assert "valueBoolean: true" in gql


@pytest.mark.asyncio
async def test_hybrid_empty_vector_rejected(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateHybridSearchConfig(collection="Doc", query="q", vector="[]"),
        credentials=credentials,
    )
    result = await create_node(config).execute({})
    assert result["status"] == "error"
    assert "non-empty" in result["error"]


# ---------------------------------------------------------------------------
# Generative search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generative_search_nearvector_single_prompt(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateGenerativeSearchConfig(
            collection="Article",
            search_type="nearVector",
            vector="[0.1, 0.2]",
            properties="title,content",
            limit=3,
            single_prompt="Summarize this article: {content}",
        ),
        credentials=credentials,
    )
    client, calls = create_capturing_client(200, {"data": {"Get": {"Article": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await create_node(config).execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v1/graphql"
    gql = calls[-1]["json"]["query"]
    assert "nearVector: {vector: [0.1, 0.2]}" in gql
    assert "singleResult: { prompt:" in gql
    assert "Summarize this article: {content}" in gql
    assert "generate(" in gql
    assert "limit: 3" in gql
    assert "title content" in gql


@pytest.mark.asyncio
async def test_generative_search_neartext_mode(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateGenerativeSearchConfig(
            collection="Article",
            search_type="nearText",
            text="machine learning",
            single_prompt="In one sentence: {body}",
        ),
        credentials=credentials,
    )
    client, calls = create_capturing_client(200, {"data": {"Get": {"Article": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await create_node(config).execute({})
    assert result["status"] == "success"
    gql = calls[-1]["json"]["query"]
    assert 'nearText: {concepts: ["machine learning"]}' in gql
    assert "singleResult:" in gql


@pytest.mark.asyncio
async def test_generative_search_hybrid_mode(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateGenerativeSearchConfig(
            collection="Article",
            search_type="hybrid",
            text="neural networks",
            alpha=0.5,
            vector="[0.1, 0.2]",
            group_task="What do these articles have in common?",
        ),
        credentials=credentials,
    )
    client, calls = create_capturing_client(200, {"data": {"Get": {"Article": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await create_node(config).execute({})
    assert result["status"] == "success"
    gql = calls[-1]["json"]["query"]
    assert 'hybrid: {query: "neural networks"' in gql
    assert "alpha: 0.5" in gql
    assert "groupedResult: { task:" in gql
    assert "What do these articles have in common?" in gql


@pytest.mark.asyncio
async def test_generative_search_grouped_result_only(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateGenerativeSearchConfig(
            collection="Doc",
            search_type="nearVector",
            vector="[0.3]",
            group_task="Summarize all results together",
        ),
        credentials=credentials,
    )
    client, calls = create_capturing_client(200, {"data": {"Get": {"Doc": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await create_node(config).execute({})
    assert result["status"] == "success"
    gql = calls[-1]["json"]["query"]
    assert "groupedResult: { task:" in gql
    assert "singleResult" not in gql.split("generate(")[1].split(")")[0]  # not in generate() args


@pytest.mark.asyncio
async def test_generative_search_both_modes(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateGenerativeSearchConfig(
            collection="Doc",
            search_type="nearVector",
            vector="[0.1]",
            single_prompt="Explain: {text}",
            group_task="Common themes?",
        ),
        credentials=credentials,
    )
    client, calls = create_capturing_client(200, {"data": {"Get": {"Doc": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await create_node(config).execute({})
    assert result["status"] == "success"
    gql = calls[-1]["json"]["query"]
    assert "singleResult: { prompt:" in gql
    assert "groupedResult: { task:" in gql


@pytest.mark.asyncio
async def test_generative_search_no_prompt_rejected(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateGenerativeSearchConfig(
            collection="Doc", search_type="nearVector", vector="[0.1]"
        ),
        credentials=credentials,
    )
    result = await create_node(config).execute({})
    assert result["status"] == "error"
    assert "single_prompt" in result["error"] or "group_task" in result["error"]


@pytest.mark.asyncio
async def test_generative_search_nearvector_missing_vector_rejected(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateGenerativeSearchConfig(
            collection="Doc", search_type="nearVector", single_prompt="Summarize: {text}"
        ),
        credentials=credentials,
    )
    result = await create_node(config).execute({})
    assert result["status"] == "error"
    assert "vector" in result["error"].lower()


@pytest.mark.asyncio
async def test_generative_search_neartext_missing_text_rejected(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateGenerativeSearchConfig(
            collection="Doc", search_type="nearText", single_prompt="Summarize: {text}"
        ),
        credentials=credentials,
    )
    result = await create_node(config).execute({})
    assert result["status"] == "error"
    assert "text" in result["error"].lower()


@pytest.mark.asyncio
async def test_generative_search_with_where(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateGenerativeSearchConfig(
            collection="Doc",
            search_type="nearVector",
            vector="[0.1]",
            single_prompt="Summarize: {text}",
            where='{"path":["category"],"operator":"Equal","valueText":"ml"}',
        ),
        credentials=credentials,
    )
    client, calls = create_capturing_client(200, {"data": {"Get": {"Doc": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await create_node(config).execute({})
    assert result["status"] == "success"
    gql = calls[-1]["json"]["query"]
    assert 'where: {path: ["category"], operator: Equal, valueText: "ml"}' in gql


@pytest.mark.asyncio
async def test_generative_search_bad_where_rejected(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateGenerativeSearchConfig(
            collection="Doc", search_type="nearVector", vector="[0.1]",
            single_prompt="Summarize: {text}", where="not-json",
        ),
        credentials=credentials,
    )
    result = await create_node(config).execute({})
    assert result["status"] == "error"
    assert "where" in result["error"].lower()


@pytest.mark.asyncio
async def test_generative_search_unknown_search_type_rejected(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateGenerativeSearchConfig(
            collection="Doc", search_type="bm25only", single_prompt="Summarize: {text}", vector="[0.1]"
        ),
        credentials=credentials,
    )
    result = await create_node(config).execute({})
    assert result["status"] == "error"
    assert "search_type" in result["error"].lower() or "bm25only" in result["error"]


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aggregate_basic_count(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateAggregateConfig(collection="Doc"),
        credentials=credentials,
    )
    client, calls = create_capturing_client(200, {"data": {"Aggregate": {"Doc": [{"meta": {"count": 42}}]}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await create_node(config).execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v1/graphql"
    gql = calls[-1]["json"]["query"]
    assert "Aggregate { Doc" in gql
    assert "meta { count }" in gql
    assert "where" not in gql
    assert "groupBy" not in gql


@pytest.mark.asyncio
async def test_aggregate_with_numeric_stats(credentials):
    props = json.dumps([{"name": "score", "stats": ["mean", "maximum", "minimum"]}])
    config = WeaviateNodeConfig(
        config=WeaviateAggregateConfig(collection="Doc", properties=props),
        credentials=credentials,
    )
    client, calls = create_capturing_client(200, {"data": {"Aggregate": {"Doc": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await create_node(config).execute({})
    assert result["status"] == "success"
    gql = calls[-1]["json"]["query"]
    assert "score { mean maximum minimum }" in gql
    assert "meta { count }" in gql


@pytest.mark.asyncio
async def test_aggregate_with_top_occurrences(credentials):
    props = json.dumps([{"name": "category", "topOccurrences": 5}])
    config = WeaviateNodeConfig(
        config=WeaviateAggregateConfig(collection="Doc", properties=props),
        credentials=credentials,
    )
    client, calls = create_capturing_client(200, {"data": {"Aggregate": {"Doc": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await create_node(config).execute({})
    assert result["status"] == "success"
    gql = calls[-1]["json"]["query"]
    assert "category { topOccurrences(limit: 5) { value occurs } }" in gql


@pytest.mark.asyncio
async def test_aggregate_with_where_filter(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateAggregateConfig(
            collection="Doc",
            where='{"path":["category"],"operator":"Equal","valueText":"ml"}',
        ),
        credentials=credentials,
    )
    client, calls = create_capturing_client(200, {"data": {"Aggregate": {"Doc": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await create_node(config).execute({})
    assert result["status"] == "success"
    gql = calls[-1]["json"]["query"]
    assert 'where: {path: ["category"], operator: Equal, valueText: "ml"}' in gql


@pytest.mark.asyncio
async def test_aggregate_with_group_by(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateAggregateConfig(collection="Doc", group_by="category", limit=10),
        credentials=credentials,
    )
    client, calls = create_capturing_client(200, {"data": {"Aggregate": {"Doc": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await create_node(config).execute({})
    assert result["status"] == "success"
    gql = calls[-1]["json"]["query"]
    assert 'groupBy: ["category"]' in gql
    assert "limit: 10" in gql
    assert "groupedBy { value path }" in gql


@pytest.mark.asyncio
async def test_aggregate_bad_where_rejected(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateAggregateConfig(collection="Doc", where="not-json"),
        credentials=credentials,
    )
    result = await create_node(config).execute({})
    assert result["status"] == "error"
    assert "where" in result["error"].lower()


@pytest.mark.asyncio
async def test_aggregate_combined_stats_and_top_occurrences(credentials):
    props = json.dumps([
        {"name": "score", "stats": ["mean", "maximum", "sum"]},
        {"name": "category", "topOccurrences": 3},
    ])
    config = WeaviateNodeConfig(
        config=WeaviateAggregateConfig(collection="Doc", properties=props),
        credentials=credentials,
    )
    client, calls = create_capturing_client(200, {"data": {"Aggregate": {"Doc": []}}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await create_node(config).execute({})
    assert result["status"] == "success"
    gql = calls[-1]["json"]["query"]
    assert "score { mean maximum sum }" in gql
    assert "category { topOccurrences(limit: 3) { value occurs } }" in gql


# ---------------------------------------------------------------------------
# Delete collection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_collection(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateDeleteCollectionConfig(collection="OldClass"), credentials=credentials
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"result": "success"})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v1/schema/OldClass"
    assert calls[-1]["method"] == "DELETE"


# ---------------------------------------------------------------------------
# Batch delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_delete(credentials):
    where = '{"path":["category"],"operator":"Equal","valueText":"old"}'
    config = WeaviateNodeConfig(
        config=WeaviateBatchDeleteConfig(collection="Doc", where=where, dry_run="false"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"results": {"successful": 3, "failed": 0}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["url"] == f"{BASE}/v1/batch/objects"
    assert calls[-1]["method"] == "DELETE"
    body = calls[-1]["json"]
    assert body["match"]["class"] == "Doc"
    assert body["match"]["where"]["valueText"] == "old"
    assert body["dryRun"] is False
    assert body["output"] == "verbose"


@pytest.mark.asyncio
async def test_batch_delete_dry_run(credentials):
    where = '{"path":["status"],"operator":"Equal","valueText":"draft"}'
    config = WeaviateNodeConfig(
        config=WeaviateBatchDeleteConfig(collection="Doc", where=where, dry_run="true"),
        credentials=credentials,
    )
    node = create_node(config)
    client, calls = create_capturing_client(200, {"results": {"matches": 5}})
    with patch("nodes.weaviate_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert calls[-1]["json"]["dryRun"] is True


@pytest.mark.asyncio
async def test_batch_delete_bad_where_rejected(credentials):
    config = WeaviateNodeConfig(
        config=WeaviateBatchDeleteConfig(collection="Doc", where="not-json"),
        credentials=credentials,
    )
    result = await create_node(config).execute({})
    assert result["status"] == "error"
    assert "WhereFilter" in result["error"] or "where" in result["error"].lower()
