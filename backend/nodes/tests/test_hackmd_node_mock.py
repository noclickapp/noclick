"""Native operation runner exercised at the HTTP boundary, without a live account."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import hackmd_node as node
from nodes.core.run_op import run_node_operation
from utils import ssrf

FIXTURES = json.loads((Path(__file__).parent / "fixtures/hackmd/responses.json").read_text())
TOKEN = "hackmd-fixture-token"
AUTH = {"credential_type": "hackmd_api_token", "api_token": TOKEN}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.hackmd.io"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        status, body = replies.pop(0)
        return httpx.Response(status, content=b"" if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    native = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-hackmd", operation=operation,
        arguments=arguments or {}, credential_data=AUTH.copy(), user_id="00000000-0000-4000-8000-000000000001")


CASES = [
    ("get_me", {}, "GET", "/me", 200, FIXTURES["user"]),
    ("list_notes", {}, "GET", "/notes", 200, [FIXTURES["note"]]),
    ("get_note", {"note_id": "note_1"}, "GET", "/notes/note_1", 200, FIXTURES["note"]),
    ("create_note", {"content": "# Notes", "read_permission": "owner"}, "POST", "/notes", 201, FIXTURES["note"]),
    ("update_note", {"note_id": "note_1", "content": "# Changed", "tags": []}, "PATCH", "/notes/note_1", 202, None),
    ("delete_note", {"note_id": "note_1"}, "DELETE", "/notes/note_1", 204, None),
    ("list_teams", {}, "GET", "/teams", 200, [FIXTURES["team"]]),
    ("list_team_notes", {"team_path": "example-team"}, "GET", "/teams/example-team/notes", 200, [FIXTURES["note"]]),
    ("get_team_note", {"team_path": "example-team", "note_id": "note_1"}, "GET", "/teams/example-team/notes/note_1", 200, FIXTURES["note"]),
    ("create_team_note", {"team_path": "example-team", "title": "Notes"}, "POST", "/teams/example-team/notes", 201, FIXTURES["note"]),
    ("update_team_note", {"team_path": "example-team", "note_id": "note_1", "title": "Changed"}, "PATCH", "/teams/example-team/notes/note_1", 202, None),
    ("delete_team_note", {"team_path": "example-team", "note_id": "note_1"}, "DELETE", "/teams/example-team/notes/note_1", 204, None),
    ("get_history", {"limit": 25}, "GET", "/history", 200, [FIXTURES["note"]]),
    ("list_folders", {}, "GET", "/folders", 200, [FIXTURES["folder"]]),
    ("get_folder", {"folder_id": "folder_1"}, "GET", "/folders/folder_1", 200, FIXTURES["folder"]),
    ("create_folder", {"name": "Engineering", "color": "#FF6B6B"}, "POST", "/folders", 201, FIXTURES["folder"]),
    ("update_folder", {"folder_id": "folder_1", "name": "Changed"}, "PATCH", "/folders/folder_1", 202, None),
    ("delete_folder", {"folder_id": "folder_1"}, "DELETE", "/folders/folder_1", 204, None),
    ("list_trash", {}, "GET", "/trash", 200, [FIXTURES["trash"]]),
    ("restore_note", {"note_id": "note_1"}, "PUT", "/trash/note_1/restore", 204, None),
]


@pytest.mark.parametrize("operation,arguments,method,path,status,body", CASES)
@pytest.mark.asyncio
async def test_hackmd_native_operations(transport, operation, arguments, method, path, status, body):
    requests, replies = transport
    replies.append((status, body))
    result = await run(operation, arguments)
    assert result["success"] is True, result
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert (request.method, request.url.path) == (method, "/v1" + path)
    assert result["http_status"] == status
    if status == 202:
        assert result["accepted"] and not result["acknowledged"]
    elif status == 204:
        assert result["acknowledged"] and not result["accepted"]
    else:
        assert result["data"] == body
    if method in {"POST", "PATCH"}:
        expected = {k: v for k, v in arguments.items() if k not in {"note_id", "team_path", "folder_id"}}
        if "read_permission" in expected:
            expected["readPermission"] = expected.pop("read_permission")
        assert json.loads(request.content) == expected
    elif operation == "get_history":
        assert dict(request.url.params) == {"limit": "25"}
    else:
        assert not request.content and not request.url.query


@pytest.mark.asyncio
async def test_hackmd_body_names_and_omitted_fields(transport):
    requests, replies = transport
    replies.append((202, None))
    await run("update_note", {"note_id": "note_1", "read_permission": "guest", "write_permission": "signed_in", "parent_folder_id": "folder_1"})
    assert json.loads(requests[0].content) == {"readPermission": "guest", "writePermission": "signed_in", "parentFolderId": "folder_1"}


@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
@pytest.mark.asyncio
async def test_hackmd_provider_failure_is_not_success_and_never_retried(transport, status):
    requests, replies = transport
    replies.append((status, {"message": "Rejected " + TOKEN}))
    result = await run("create_note", {"title": "Notes"})
    assert result["success"] is False and result["http_status"] == status
    assert TOKEN not in json.dumps(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_hackmd_partial_creation_is_preserved_without_success_or_retry(transport):
    requests, replies = transport
    body = {"note": FIXTURES["note"], "error": "Some metadata was not applied"}
    replies.append((207, body))
    result = await run("create_note", {"title": "Notes"})
    assert result["success"] is False and result["status"] == "partial"
    assert result["data"] == body and len(requests) == 1


@pytest.mark.parametrize("body", [[], {}, {"id": None}])
@pytest.mark.asyncio
async def test_hackmd_bad_profile_does_not_prove_connection(transport, body):
    transport[1].append((200, body))
    with pytest.raises(ValueError):
        await run("get_me")


@pytest.mark.parametrize("identifier", ["../notes", "https://hackmd.io/note", "note?query=1", "note#fragment", "a/b"])
def test_hackmd_identifiers_cannot_change_route(identifier):
    with pytest.raises(ValidationError):
        node.GetNote(note_id=identifier)


def test_hackmd_manual_credential_has_default_and_only_one_required_input():
    credential = node.HackMDTokenCredential(api_token=TOKEN)
    assert credential.credential_type == "hackmd_api_token"
    assert {k for k, v in node.HackMDTokenCredential.model_fields.items() if v.is_required()} == {"api_token"}


@pytest.mark.parametrize("token", ["Bearer token", "https://example.com/token", "<token>", "line\nbreak"])
def test_hackmd_refuses_token_placeholders_and_headers(token):
    with pytest.raises(ValidationError):
        node.HackMDTokenCredential(api_token=token)
