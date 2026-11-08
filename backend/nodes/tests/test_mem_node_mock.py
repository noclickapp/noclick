"""Mem v2 wire regressions using the provider's published response examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import mem_node as native
from nodes.core.registry import NodeFactory

TOKEN = "mem-synthetic-key-42"
NOTE = "5e29c8a2-c73b-476b-9311-e2579712d4b1"
COLLECTION = "01961d40-7c70-7ed8-8cd4-bd99203de422"
OTHER = "018f8d0d-5a3c-7afc-8321-2f6f6e0fefab"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/mem/contract_examples.json").read_text())
CONFIGS = {
    "list_notes": {"limit": 20, "include_note_content": True, "page": "opaque-cursor", "collection_id": COLLECTION},
    "create_note": {"content": "# Meeting with Product Team\n\nDiscussion Topics:\n- Roadmap updates", "collection_ids": [COLLECTION]},
    "get_note": {"note_id": NOTE},
    "update_note": {"note_id": NOTE, "content": "# Updated Meeting Notes\n\n- Sprint planning", "version": 2},
    "delete_note": {"note_id": NOTE}, "trash_note": {"note_id": NOTE}, "restore_note": {"note_id": NOTE},
    "set_note_created_at": {"note_id": NOTE, "created_at": "2020-01-07T00:00:00Z"},
    "find_related_notes": {"note_id": NOTE, "limit": 5},
    "search_notes": {"query": "Project Phoenix", "limit": 10, "offset": 20, "snapshot_id": OTHER, "filter_by_collection_ids": [COLLECTION]},
    "list_collections": {"limit": 20, "page": "opaque-cursor", "order_by": "created_at"},
    "create_collection": {"title": "Acme Corp", "description": "Anything related to Acme Corp"},
    "get_collection": {"collection_id": COLLECTION},
    "update_collection": {"collection_id": COLLECTION, "title": "Acme Corp - 2026"},
    "delete_collection": {"collection_id": COLLECTION},
    "add_note_to_collection": {"collection_id": COLLECTION, "note_id": NOTE},
    "remove_note_from_collection": {"collection_id": COLLECTION, "note_id": NOTE},
    "move_note": {"source_collection_id": COLLECTION, "note_id": NOTE, "target_collection_id": OTHER},
    "search_collections": {"query": "Acme Corp"},
    "mem_it": {"input": "Check out Atomic Habits by James Clear - recommended by Sarah", "instructions": "Add to my reading list"},
}


def node(config):
    return NodeFactory.create_node(node_id="mem-fixture", node_type="automation-mem", node_data={
        "config": config, "credentials": {"credential_type": "mem_api_key", "api_key": TOKEN},
    })


def mock(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={"Location": "https://example.test/"})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONFIGS)
async def test_each_operation_matches_published_method_path_and_response(monkeypatch, operation):
    fixture = EXAMPLES[operation]
    assert isinstance(fixture["body"], dict), operation
    requests = mock(monkeypatch, fixture["body"])
    config = {"operation": operation, **CONFIGS[operation]}
    output = await node(config).execute({})
    request, = requests
    assert request.method == fixture["method"]
    expected_path = fixture["path"]
    for key, value in config.items():
        expected_path = expected_path.replace("{" + key + "}", str(value))
    assert request.url.path == expected_path and request.url.host == "api.mem.ai"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert all(output[key] == value for key, value in fixture["body"].items())
    assert TOKEN not in str(output)
    # Path IDs and NoClick's discriminator must never leak into the JSON body.
    body = json.loads(request.content) if request.content else {}
    assert not {"operation", "note_id", "collection_id", "source_collection_id"} & body.keys()
    if operation == "update_note":
        assert body == {"content": config["content"], "version": 2}
    elif operation == "move_note":
        assert body == {"target_collection_id": OTHER}
    elif operation == "search_notes":
        assert dict(request.url.params) == {"limit": "10", "offset": "20", "snapshot_id": OTHER}
        assert body == {"query": "Project Phoenix", "filter_by_collection_ids": [COLLECTION],
            "filter_by_contains_files": False, "filter_by_contains_images": False,
            "filter_by_contains_open_tasks": False, "filter_by_contains_tasks": False}
    elif operation == "list_notes":
        assert request.url.params["page"] == "opaque-cursor"
        assert request.url.params["include_note_content"] == "true"
        assert request.url.params["collection_id"] == COLLECTION
    elif operation == "set_note_created_at":
        assert body == {"created_at": "2020-01-07T00:00:00Z"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 409, 429, 500])
async def test_provider_failures_do_not_become_success_or_retry(monkeypatch, status):
    requests = mock(monkeypatch, {"error": "key rejected " + TOKEN}, status)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_collections"}).execute({})
    assert TOKEN not in str(exc.value) and str(status) in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{}, [], {"request_id": "fixture", "results": {}}, {"request_id": "fixture", "error": "rejected"}])
async def test_malformed_response_fails(monkeypatch, response):
    mock(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({"operation": "list_notes"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "update_note", "note_id": NOTE, "content": "changed"},
    {"operation": "update_note", "note_id": NOTE, "content": "changed", "version": True},
    {"operation": "get_note", "note_id": "../notes"},
    {"operation": "list_notes", "limit": 101},
    {"operation": "search_notes", "query": "  "},
    {"operation": "search_notes", "query": "Project Phoenix", "offset": 20},
    {"operation": "update_collection", "collection_id": COLLECTION},
    {"operation": "set_note_created_at", "note_id": NOTE, "created_at": "2020-01-07T00:00:00"},
    {"operation": "create_note", "content": "é" * 100001},
])
def test_invalid_mutations_pagination_and_ids_fail_before_http(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_connection_evidence_is_account_specific_read():
    assert native.MemNode.connection_evidence.operation == "list_collections"
    assert native.MemNode.connection_evidence.proves == "account"
    assert len(native.ROUTES) == 20


@pytest.mark.asyncio
async def test_clear_description_sends_empty_string_through_runtime_config(monkeypatch):
    requests = mock(monkeypatch, EXAMPLES["update_collection"]["body"])
    await node({"operation": "update_collection", "collection_id": COLLECTION, "clear_description": True}).execute({})
    assert json.loads(requests[0].content) == {"description": ""}


@pytest.mark.parametrize("key", ["Bearer secret", "https://mem.ai/key", "<token>", "secret\nvalue", "secret\x00value", 123])
def test_bad_pasted_key_is_refused(key):
    with pytest.raises(ValueError):
        native.MemAPIKeyCredential(api_key=key)
