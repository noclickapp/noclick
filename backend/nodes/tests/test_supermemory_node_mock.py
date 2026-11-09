"""Native factory tests of Supermemory's v5 request and response boundaries."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import supermemory_node as native
from nodes.core.registry import NodeFactory

TOKEN = "sm_synthetic_supermemory_42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="supermemory-fixture", node_type="automation-supermemory",
        node_data={"config": config, "credentials": {"credential_type": "supermemory_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "add_document", "namespace": "user_alex", "content": "Project notes", "id": "notes", "metadata": {"team": "platform"}}, "POST", "/ns/user_alex/document", {}, {"content": "Project notes", "id": "notes", "metadata": {"team": "platform"}}, {"id": "notes", "status": "queued"}),
    ({"operation": "batch_add_documents", "namespace": "user_alex", "documents": [{"content": "Notes"}], "dreaming": "instant"}, "POST", "/ns/user_alex/document/batch", {}, {"documents": [{"content": "Notes"}], "dreaming": "instant"}, {"documents": [{"id": "notes", "status": "queued"}]}),
    ({"operation": "get_document", "namespace": "user_alex", "id": "note/a", "include": ["chunks", "memories"]}, "GET", "/ns/user_alex/document/note/a", {"include": "chunks,memories"}, None, {"id": "note/a", "status": "done"}),
    ({"operation": "update_document", "namespace": "user_alex", "id": "notes", "metadata": {"reviewed": True}}, "PATCH", "/ns/user_alex/document/notes", {}, {"metadata": {"reviewed": True}}, {"id": "notes", "status": "done"}),
    ({"operation": "delete_documents", "namespace": "user_alex", "ids": ["notes"]}, "DELETE", "/ns/user_alex/document", {}, {"ids": ["notes"]}, {"count": 1, "errors": []}),
    ({"operation": "search", "namespace": "user_alex", "query": "API limits"}, "POST", "/ns/user_alex/search", {}, {"query": "API limits", "searchMode": "hybrid", "limit": 10, "threshold": 0.3, "rerank": "none", "rewriteQuery": False}, {"results": []}),
    ({"operation": "get_profile", "namespace": "user_alex"}, "POST", "/ns/user_alex/profile", {}, {}, {"profile": {"static": [], "dynamic": [], "buckets": {}}}),
    ({"operation": "get_profile_buckets", "namespace": "user_alex"}, "GET", "/ns/user_alex/profile/buckets", {}, None, {"buckets": {}}),
    ({"operation": "upsert_profile_buckets", "namespace": "user_alex", "buckets": {"goals": "Current goals"}}, "PUT", "/ns/user_alex/profile/buckets", {}, {"buckets": {"goals": "Current goals"}}, {"buckets": {"goals": "Current goals"}}),
    ({"operation": "delete_profile_buckets", "namespace": "user_alex", "buckets": ["goals"]}, "DELETE", "/ns/user_alex/profile/buckets", {}, {"buckets": ["goals"]}, {"buckets": {}}),
    ({"operation": "forget_memories", "namespace": "user_alex", "ids": ["mem_123"]}, "DELETE", "/ns/user_alex/memories", {}, {"ids": ["mem_123"]}, {"count": 1, "errors": [], "matches": []}),
    ({"operation": "forget_memories_semantic", "namespace": "user_alex", "query": "Old plans"}, "DELETE", "/ns/user_alex/memories/semantic", {}, {"query": "Old plans", "dryRun": True}, {"count": 0, "errors": [], "matches": []}),
    ({"operation": "list_resources", "namespace": "user_alex", "type": "documents", "cursor": "opaque+cursor"}, "POST", "/ns/user_alex/list/documents", {"page": "1", "limit": "10", "cursor": "opaque+cursor", "sort": "createdAt", "order": "desc"}, {}, {"documents": [], "pagination": {"hasMore": True, "nextCursor": "next"}}),
    ({"operation": "list_connectors", "namespace": "user_alex"}, "GET", "/ns/user_alex/connectors", {"page": "1", "limit": "10"}, None, {"connectors": []}),
    ({"operation": "get_connector", "namespace": "user_alex", "id": "connector_1"}, "GET", "/ns/user_alex/connectors/connector_1", {}, None, {"id": "connector_1"}),
    ({"operation": "delete_connector", "namespace": "user_alex", "id": "connector_1"}, "DELETE", "/ns/user_alex/connectors/connector_1", {"deleteDocuments": "true"}, None, {"id": "connector_1", "deleted": True}),
    ({"operation": "sync_connector", "namespace": "user_alex", "id": "connector_1"}, "POST", "/ns/user_alex/connectors/connector_1/sync", {}, None, {"status": "queued"}),
    ({"operation": "list_namespaces"}, "GET", "/ns", {"page": "1", "limit": "10"}, None, {"namespaces": [], "pagination": {"currentPage": 1, "totalItems": 0, "totalPages": 0}}),
    ({"operation": "get_namespace", "namespace": "user_alex"}, "GET", "/ns/user_alex", {}, None, {"namespace": "user_alex", "supportingContext": None}),
    ({"operation": "update_namespace", "namespace": "user_alex", "supportingContext": None}, "PATCH", "/ns/user_alex", {}, {"supportingContext": None}, {"namespace": "user_alex", "supportingContext": None}),
    ({"operation": "get_organization"}, "GET", "/organization", {}, None, {"organizationalContext": None, "namespaceCount": 1}),
    ({"operation": "get_memory", "namespace": "user_alex", "id": "mem_123", "include": ["related", "documents"]}, "GET", "/ns/user_alex/memories/mem_123", {"include": "related,documents", "relatedLimit": "10"}, None, {"id": "mem_123", "memory": "Loves tea"}),
    ({"operation": "count_document_memories", "namespace": "user_alex", "ids": ["notes"]}, "POST", "/ns/user_alex/list/documents/memory-counts", {}, {"ids": ["notes"]}, {"counts": [{"id": "notes", "memoryCount": 2}]}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,params,body,response", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_each_operation_single_contract_request(monkeypatch, config, method, path, params, body, response):
    requests = transport(monkeypatch, response, status=202 if config["operation"] == "sync_connector" else 200)
    result = await node(config).execute({})
    assert result == response
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.supermemory.ai"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert dict(request.url.params) == params
    assert (json.loads(request.content) if request.content else None) == body
    if config["operation"] == "get_document":
        assert "note%2Fa" in str(request.url)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_rejections_do_not_echo_key_or_retry_writes(monkeypatch, status):
    requests = transport(monkeypatch, {"error": TOKEN}, status)
    with pytest.raises(ValueError, match=f"HTTP {status}") as exc:
        await node({"operation": "add_document", "namespace": "user_alex", "content": "Notes"}).execute({})
    assert TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {"error": "invalid_auth"}, {"errors": ["bad"]}])
async def test_error_envelopes_and_wrong_shapes_fail(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_namespaces"}).execute({})


@pytest.mark.parametrize("config", [
    { "operation": "get_namespace", "namespace": "../other"},
    {"operation": "get_document", "namespace": "user_alex", "id": ".."},
    {"operation": "list_resources", "namespace": "user_alex", "type": "documents", "sort": "position"},
    {"operation": "delete_documents", "namespace": "user_alex", "ids": []},
    {"operation": "search", "namespace": "user_alex", "query": "q", "limit": 101},
    {"operation": "list_namespaces", "base_url": "https://evil.example"},
    {"operation": "list_resources", "namespace": "user_alex", "type": "unknown"},
])
def test_invalid_requests_rejected_before_network(config):
    with pytest.raises(ValidationError):
        native.SupermemoryFullConfig.model_validate({"config": config})


def test_catalog_and_manual_credential_contract():
    assert {c[0]["operation"] for c in CASES} == set(native.ROUTES)
    cred = native.SupermemoryAPIKeyCredential(api_key=TOKEN)
    assert cred.credential_type == "supermemory_api_key"
    assert native.SupermemoryNode.connection_evidence.operation == "list_namespaces"
    assert native.SupermemoryAPIKeyCredential.model_json_schema()["required"] == ["api_key"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["delete_documents", "forget_memories", "forget_memories_semantic"])
async def test_documented_partial_failures_are_preserved(monkeypatch, operation):
    body = {"count": 1, "errors": [{"id": "missing", "error": "Not found"}]}
    if operation != "delete_documents":
        body["matches"] = [{"id": "mem_123", "memory": "Old context"}]
    transport(monkeypatch, body)
    config = {"operation": operation, "namespace": "user_alex"}
    config.update({"query": "Old context", "dryRun": False} if operation.endswith("semantic") else {"ids": ["notes", "missing"]})
    assert await node(config).execute({}) == body


@pytest.mark.asyncio
async def test_empty_success_envelope_cannot_prove_connection(monkeypatch):
    transport(monkeypatch, {})
    with pytest.raises(ValueError, match="namespace listing"):
        await node({"operation": "list_namespaces"}).execute({})
