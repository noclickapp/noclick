"""Wire-contract regressions for Slite's published v1 API; no live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import slite_node as native
from nodes.core.registry import NodeFactory

TOKEN = "slite-synthetic-key"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/slite/responses.json").read_text())
CASES = [
    ({"operation": "get_me"}, "GET", "/me", {}, None),
    ({"operation": "list_notes", "cursor": "next+page", "ownerId": "owner"}, "GET", "/notes", {"cursor": "next+page", "ownerId": "owner"}, None),
    ({"operation": "get_note", "noteId": "noteId", "format": "sliteml", "compact": True}, "GET", "/notes/noteId", {"format": "sliteml", "compact": "true"}, None),
    ({"operation": "create_note", "title": "Note title", "markdown": "# Content in markdown", "parentNoteId": "parentNoteId"}, "POST", "/notes", {}, {"title": "Note title", "markdown": "# Content in markdown", "parentNoteId": "parentNoteId"}),
    ({"operation": "update_note", "noteId": "noteId", "title": "New title", "attributes": [None, ""]}, "PUT", "/notes/noteId", {}, {"title": "New title", "attributes": [None, ""]}),
    ({"operation": "delete_note", "noteId": "noteId"}, "DELETE", "/notes/noteId", {}, None),
    ({"operation": "list_children", "noteId": "noteId", "includeDescendants": False}, "GET", "/notes/noteId/children", {"includeDescendants": "false"}, None),
    ({"operation": "verify_note", "noteId": "noteId", "until": None}, "PUT", "/notes/noteId/verify", {}, {"until": None}),
    ({"operation": "flag_outdated", "noteId": "noteId", "reason": "Information are incorrect"}, "PUT", "/notes/noteId/flag-as-outdated", {}, {"reason": "Information are incorrect"}),
    ({"operation": "set_archived", "noteId": "noteId", "archived": False}, "PUT", "/notes/noteId/archived", {}, {"archived": False}),
    ({"operation": "set_owner", "noteId": "noteId", "groupId": "groupId"}, "PUT", "/notes/noteId/owner", {}, {"groupId": "groupId"}),
    ({"operation": "search_notes", "query": "Slite public api", "page": 1}, "GET", "/search-notes", {"query": "Slite public api", "page": "1", "hitsPerPage": "20"}, None),
    ({"operation": "get_user", "userId": "userId123"}, "GET", "/users/userId123", {}, None),
    ({"operation": "search_users", "query": "john", "includeArchived": False}, "GET", "/users", {"query": "john", "includeArchived": "false"}, None),
    ({"operation": "get_group", "groupId": "groupId123"}, "GET", "/groups/groupId123", {}, None),
    ({"operation": "search_groups", "query": "Developers"}, "GET", "/groups", {"query": "Developers"}, None),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="slite-test", node_type="automation-slite", node_data={"config": config, "credentials": {"credential_type": "slite_api_key", "api_key": TOKEN}})


def transport(monkeypatch, respond):
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.host == "api.slite.com"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        return respond(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body", CASES)
async def test_documented_requests_and_responses(monkeypatch, config, method, path, query, body):
    payload = FIXTURES[config["operation"]]
    requests = transport(monkeypatch, lambda r: httpx.Response(204) if method == "DELETE" else httpx.Response(200, json=payload))
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/v1" + path
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body
    if method != "DELETE":
        assert result["data"] == payload
    else:
        assert result["deletion_acknowledged"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_rejections_no_retry_and_no_token_leak(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, text="Rejected " + TOKEN))
    result = await node({"operation": "get_me"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, [], {"error": "invalid"}])
async def test_malformed_identity_cannot_prove_connection(monkeypatch, payload):
    transport(monkeypatch, lambda r: httpx.Response(200, json=payload))
    with pytest.raises(ValueError, match="unexpected response"):
        await node({"operation": "get_me"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_note", "noteId": "../other"},
    {"operation": "create_note", "title": "x", "html": "x", "markdown": "x"},
    {"operation": "update_note", "noteId": "noteId"},
    {"operation": "set_owner", "noteId": "noteId", "userId": "a", "groupId": "b"},
    {"operation": "search_notes", "hitsPerPage": 101},
    {"operation": "create_note", "title": "x", "listPosition": -1},
])
def test_invalid_config_fails_before_request(config):
    with pytest.raises(ValueError):
        node(config)
