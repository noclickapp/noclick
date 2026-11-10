"""Real node execution through an intercepted HTTP transport, no live credentials."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import dust_node as dust
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

AUTH = {"credential_type": "dust_api_key", "api_key": "dust-test-secret", "workspace_id": "workspace", "region": "us"}
SOURCE = {"space_id": "space", "data_source_id": "knowledge"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    native = httpx.AsyncClient
    async def send(request):
        requests.append(request)
        code, body = replies.pop(0)
        return httpx.Response(code, json=body)
    monkeypatch.setattr(dust.httpx, "AsyncClient", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


def node(operation, config=None, auth=None):
    return NodeFactory.create_node(node_id="dust-test", node_type="automation-dust", node_data={
        "config": {"operation": operation, **(config or {})}, "credentials": deepcopy(auth or AUTH)})


CASES = [
    ("list_agents", {}, "GET", "/assistant/agent_configurations", None),
    ("get_agent", {"agent_id": "agent"}, "GET", "/assistant/agent_configurations/agent", None),
    ("update_agent", {"agent_id": "agent", "instructions": "Be helpful"}, "PATCH", "/assistant/agent_configurations/agent", {"instructions": "Be helpful"}),
    ("archive_agent", {"agent_id": "agent"}, "DELETE", "/assistant/agent_configurations/agent", None),
    ("list_spaces", {}, "GET", "/spaces", None),
    ("list_data_sources", {"space_id": "space"}, "GET", "/spaces/space/data_sources", None),
    ("list_documents", SOURCE, "GET", "/spaces/space/data_sources/knowledge/documents", None),
    ("get_document", {**SOURCE, "document_id": "doc"}, "GET", "/spaces/space/data_sources/knowledge/documents/doc", None),
    ("upsert_document", {**SOURCE, "document_id": "doc", "title": "FAQ", "text": "Answer", "tags_json": '["faq"]', "timestamp": 1736365559000}, "POST", "/spaces/space/data_sources/knowledge/documents/doc", {"title": "FAQ", "text": "Answer", "tags": ["faq"], "timestamp": 1736365559000}),
    ("delete_document", {**SOURCE, "document_id": "doc"}, "DELETE", "/spaces/space/data_sources/knowledge/documents/doc", None),
    ("search_documents", {**SOURCE, "query": "FAQ"}, "GET", "/spaces/space/data_sources/knowledge/search", None),
    ("list_tables", SOURCE, "GET", "/spaces/space/data_sources/knowledge/tables", None),
    ("get_table", {**SOURCE, "table_id": "table"}, "GET", "/spaces/space/data_sources/knowledge/tables/table", None),
    ("upsert_table", {**SOURCE, "table_id": "table", "name": "customers", "title": "Customers"}, "POST", "/spaces/space/data_sources/knowledge/tables", {"table_id": "table", "name": "customers", "title": "Customers"}),
    ("delete_table", {**SOURCE, "table_id": "table"}, "DELETE", "/spaces/space/data_sources/knowledge/tables/table", None),
    ("list_rows", {**SOURCE, "table_id": "table"}, "GET", "/spaces/space/data_sources/knowledge/tables/table/rows", None),
    ("get_row", {**SOURCE, "table_id": "table", "row_id": "row"}, "GET", "/spaces/space/data_sources/knowledge/tables/table/rows/row", None),
    ("upsert_rows", {**SOURCE, "table_id": "table", "rows_json": '[{"row_id":"row","value":{"active":true}}]'}, "POST", "/spaces/space/data_sources/knowledge/tables/table/rows", {"rows": [{"row_id": "row", "value": {"active": True}}]}),
    ("delete_row", {**SOURCE, "table_id": "table", "row_id": "row"}, "DELETE", "/spaces/space/data_sources/knowledge/tables/table/rows/row", None),
    ("create_conversation", {"agent_id": "agent", "content": "Hello"}, "POST", "/assistant/conversations", {"blocking": False, "message": {"content": "Hello", "mentions": [{"configurationId": "agent"}]}}),
    ("get_conversation", {"conversation_id": "conv"}, "GET", "/assistant/conversations/conv", None),
    ("rename_conversation", {"conversation_id": "conv", "title": "New title"}, "PATCH", "/assistant/conversations/conv", {"title": "New title"}),
    ("create_message", {"conversation_id": "conv", "agent_id": "agent", "content": "Hello"}, "POST", "/assistant/conversations/conv/messages", {"content": "Hello", "mentions": [{"configurationId": "agent"}]}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body", CASES)
async def test_wire_contract(transport, operation, config, method, path, body):
    requests, replies = transport
    replies.append((200, {"ok": True}))
    result = await node(operation, config).execute({})
    assert result["data"] == {"ok": True}
    request, = requests
    assert request.method == method
    assert request.url.path == "/api/v1/w/workspace" + path
    assert request.url.host == "dust.tt"
    assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
    assert AUTH["api_key"] not in str(request.url)
    assert (json.loads(request.content) if request.content else None) == body
    if operation in {"list_documents", "list_rows"}:
        assert dict(request.url.params) == {"limit": "100", "offset": "0"}
    if operation == "search_documents":
        assert dict(request.url.params) == {"query": "FAQ", "top_k": "100", "full_text": "true"}


@pytest.mark.asyncio
async def test_region_and_path_encoding(transport):
    requests, replies = transport
    replies.append((200, {}))
    await node("get_agent", {"agent_id": "folder/agent?x#y"}, {**AUTH, "region": "eu"}).execute({})
    assert requests[0].url.host == "eu.dust.tt"
    assert requests[0].url.raw_path.endswith(b"folder%2Fagent%3Fx%23y")
    assert not requests[0].url.query


@pytest.mark.parametrize("key,value", [("api_key", "https://dust.tt"), ("workspace_id", ".."), ("region", "https://evil.test"), ("api_key", "Bearer key")])
def test_manual_credential_validation(key, value):
    with pytest.raises(ValueError):
        dust.DustAPIKeyCredential.model_validate({**AUTH, key: value})
    assert dust.DustAPIKeyCredential.model_validate({k: v for k, v in AUTH.items() if k != "credential_type"}).credential_type == "dust_api_key"


@pytest.mark.asyncio
@pytest.mark.parametrize("code,body", [(401, {"error": {"message": "invalid key"}}), (200, {"error": {"message": "invalid key"}}), (302, {"location": "https://evil.test"})])
async def test_refusal_and_redirect_not_success(transport, code, body):
    _, replies = transport
    replies.append((code, body))
    with pytest.raises(ValueError):
        await node("list_spaces").execute({})


@pytest.mark.parametrize("value", ['{}', '[null]', '[{"row_id":"r","value":{"a":null}}]', '[{"row_id":"r","value":{"a":NaN}}]'])
def test_invalid_row_writes(value):
    with pytest.raises(ValueError):
        dust.json_field(value, "rows_json")


def document():
    # Values copied from the provider's Document examples; search fields are
    # constrained by its separate search response schema in the same fixture.
    fixture = json.loads((Path(__file__).parent / "fixtures/dust/provider_examples.json").read_text())
    properties = fixture["document_schema"]["properties"]
    return {"id": properties["document_id"]["example"], "title": properties["title"]["example"],
            "content": properties["text"]["example"], "timestamp": properties["timestamp"]["example"]}


@pytest.mark.asyncio
async def test_poll_baseline_dedup_update_and_agent_turn(transport):
    requests, replies = transport
    cfg = {**SOURCE, "query": "customer support", "since_timestamp": 0}
    n = node("on_new_or_updated_document", cfg)
    state = {}
    async def update(mutator, **kwargs):
        changed, result = mutator(deepcopy(state))
        if changed is not None:
            state.clear()
            state.update(changed)
        return result
    n._update_node_state = update
    row = document()
    async def poll(rows):
        replies.append((200, {"documents": rows}))
        return await n.execute({})
    assert (await poll([row]))["new_document_count"] == 0
    assert (await poll([row]))["new_document_count"] == 0
    updated = {**row, "timestamp": row["timestamp"] + 1}
    out = await poll([updated])
    assert out["documents"] == [updated]
    assert dust.DustNode.should_propagate_output(out, {"operation": "on_new_or_updated_document"})
    event = dust.DustNode.resolve_agent_event(out)
    for value in [updated["id"], updated["title"], updated["content"], "space", "knowledge"]:
        assert value in event["text"]
    assert (await poll([updated]))["new_document_count"] == 0
    assert requests[-1].url.params["timestamp_gt"] == "0.0"
    base = {"operation": "on_new_or_updated_document", **cfg}
    assert poll_scope(dust.DustNode, base) == poll_scope(dust.DustNode, {**base, "goal": "cosmetic edit"})
    assert poll_scope(dust.DustNode, base) != poll_scope(dust.DustNode, {**base, "data_source_id": "other"})


@pytest.mark.asyncio
async def test_poll_full_or_malformed_result_does_not_consume(transport):
    _, replies = transport
    for rows, bound in [([document()], 1), ([{"id": "x"}], 100)]:
        n = node("on_new_or_updated_document", {**SOURCE, "query": "FAQ", "top_k": bound})
        n._filter_unseen = AsyncMock()
        replies.append((200, {"documents": rows}))
        with pytest.raises(ValueError):
            await n.execute({})
        n._filter_unseen.assert_not_awaited()
