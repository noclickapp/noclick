"""Egnyte documented HTTP boundaries, identity, OAuth context and file output."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

import nodes.egnyte_node as egnyte
from nodes.core.binary_output import BinaryOutput
from nodes.core.oauth_refresh import RotatedRefreshTokenMissing
from nodes.oauth.egnyte_oauth import OAUTH_PROVIDER

AUTH = {"credential_type": "egnyte_oauth", "account_host": "apidemo.egnyte.com",
        "access_token": "synthetic-access", "refresh_token": "synthetic-refresh",
        "expires_at": "2099-01-01T00:00:00+00:00"}
PATH = "/Shared/Documents/form.docx"
COMMENT = "a7a809d3-1c2f-4dd0-8b65-3f2c78eac4c8"
# Expected methods/URLs/body are independent of the implementation catalog.
CASES = [
    ("get_user_info", {}, "GET", "/v1/userinfo", None),
    ("get_file_or_folder", {"path": PATH, "offset": 100}, "GET", "/v1/fs/Shared/Documents/form.docx", None),
    ("create_folder", {"path": "/Shared/test"}, "POST", "/v1/fs/Shared/test", {"action": "add_folder"}),
    ("move_item", {"path": PATH, "destination": "/Shared/toFolder/form.docx"}, "POST", "/v1/fs/Shared/Documents/form.docx", {"action": "move", "destination": "/Shared/toFolder/form.docx"}),
    ("copy_item", {"path": PATH, "destination": "/Shared/toFolder/form.docx", "permissions": "inherit_from_parent"}, "POST", "/v1/fs/Shared/Documents/form.docx", {"action": "copy", "destination": "/Shared/toFolder/form.docx", "permissions": "inherit_from_parent"}),
    ("lock_file", {"path": PATH, "lock_token": "my lock token", "lock_timeout": 7200}, "POST", "/v1/fs/Shared/Documents/form.docx", {"action": "lock", "lock_token": "my lock token", "lock_timeout": 7200}),
    ("unlock_file", {"path": PATH, "lock_token": "my lock token"}, "POST", "/v1/fs/Shared/Documents/form.docx", {"action": "unlock", "lock_token": "my lock token"}),
    ("delete_item", {"path": PATH, "entry_id": "version-1"}, "DELETE", "/v1/fs/Shared/Documents/form.docx", None),
    ("download_file", {"path": PATH, "entry_id": "version-1"}, "GET", "/v1/fs-content/Shared/Documents/form.docx", None),
    ("search_files", {"query": "contract", "folder": "/Shared", "offset": 20}, "GET", "/v1/search", None),
    ("list_links", {"path": PATH, "offset": 100}, "GET", "/v1/links", None),
    ("create_link", {"path": PATH, "type": "file"}, "POST", "/v1/links", {"path": PATH, "type": "file", "accessibility": "domain", "notify": False}),
    ("get_link", {"link_id": "owTMm8H8Sg"}, "GET", "/v1/links/owTMm8H8Sg", None),
    ("delete_link", {"link_id": "owTMm8H8Sg"}, "DELETE", "/v1/links/owTMm8H8Sg", None),
    ("add_comment", {"path": PATH, "body": "Test comment"}, "POST", "/v1/notes", {"path": PATH, "body": "Test comment"}),
    ("list_comments", {"file": PATH, "offset": 25}, "GET", "/v1/notes", None),
    ("get_comment", {"comment_id": COMMENT}, "GET", "/v1/notes/" + COMMENT, None),
    ("delete_comment", {"comment_id": COMMENT}, "DELETE", "/v1/notes/" + COMMENT, None),
    ("get_events_cursor", {}, "GET", "/v1/events/cursor", None),
    ("list_events", {"id": 16342, "suppress": "app"}, "GET", "/v1/events", None),
]


async def run(operation, config=None, credential=None):
    raw = {"config": {"operation": operation, **(config or {})}, "credentials": credential or AUTH}
    model = egnyte.EgnyteNode.parse_config(raw)
    return await egnyte.EgnyteNode("test", "automation-egnyte", raw, config=model).execute({})


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    def respond(request):
        calls.append(request)
        if responses:
            return responses.pop(0)
        if request.url.path.endswith("userinfo"):
            return httpx.Response(200, json={"id": 123, "username": "test", "first_name": "Test", "last_name": "User"})
        if "fs-content" in request.url.path:
            return httpx.Response(200, content=b"file bytes", headers={"Content-Type": "application/octet-stream"})
        return httpx.Response(200, json={"path": "/Shared/test", "folder_id": "4abfdc36-2a1b-44b4-8792-01bf43c0d0f9"})
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs) as c:
            yield c
    monkeypatch.setattr(egnyte, "guarded_async_client", client)
    return calls, responses


@pytest.mark.parametrize("operation,config,method,path,body", CASES, ids=[c[0] for c in CASES])
async def test_documented_requests(transport, operation, config, method, path, body):
    result = await run(operation, config)
    assert len(transport[0]) == 1
    request = transport[0][0]
    assert request.method == method
    assert request.url.path == "/pubapi" + path
    assert request.url.host == "apidemo.egnyte.com"
    assert request.headers["authorization"] == "Bearer synthetic-access"
    assert (json.loads(request.content) if request.content else None) == body
    if operation == "download_file":
        assert isinstance(result["file"], BinaryOutput)
        assert result["file"].data == b"file bytes"
        assert result["file"].filename == "form.docx"
    if operation in {"get_file_or_folder", "search_files", "list_links", "list_comments"}:
        assert request.url.params["offset"] == str(config["offset"])
    if operation in {"download_file", "delete_item"}:
        assert request.url.params["entry_id"] == "version-1"
    if operation == "list_events":
        assert request.url.params["id"] == "16342" and request.url.params["suppress"] == "app"


async def test_path_encodes_segments_once(transport):
    await run("get_file_or_folder", {"path": "/Shared/example?path/$file %.txt"})
    assert transport[0][0].url.raw_path.startswith(b"/pubapi/v1/fs/Shared/example%3Fpath/%24file%20%25.txt?")


@pytest.mark.parametrize("path", ["../Shared", "/Shared/../secret", "/Shared//x", "/Shared/", "/Shared/\nsecret", "Shared\\x"])
async def test_invalid_paths_never_send(transport, path):
    with pytest.raises(ValueError):
        await run("delete_item", {"path": path})
    assert not transport[0]


@pytest.mark.parametrize("host", ["http://apidemo.egnyte.com", "apidemo.egnyte.com.evil.test", "evil@apidemo.egnyte.com", "127.0.0.1", "apidemo.egnyte.com:443", "a.b.egnyte.com"])
async def test_invalid_hosts_never_send(transport, host):
    with pytest.raises((ValueError, ValidationError)):
        await run("get_user_info", credential={**AUTH, "account_host": host})
    assert not transport[0]


@pytest.mark.parametrize("payload", [{}, {"id": 1}, {"username": "test"}, {"id": 1, "username": ""}, {"error": "rejected"}])
async def test_malformed_identity_does_not_prove_connection(transport, payload):
    transport[1].append(httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await run("get_user_info")


@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_provider_refusals_are_errors_and_are_not_retried(transport, status):
    transport[1].append(httpx.Response(status, headers={"Location": "https://foreign.test"}, json={"message": "synthetic-access"}))
    with pytest.raises(httpx.HTTPStatusError) as error:
        await run("create_folder", {"path": "/Shared/test"})
    assert "synthetic-access" not in str(error.value)
    assert len(transport[0]) == 1


async def test_documented_empty_delete_and_event_response(transport):
    transport[1].extend([httpx.Response(200), httpx.Response(204)])
    assert await run("delete_comment", {"comment_id": COMMENT}) == {"status_code": 200, "data": None}
    assert await run("list_events", {"id": 16342}) == {"status_code": 204, "data": None}


async def test_page_metadata_and_documented_comment_response_survive(transport):
    fixture = json.loads((Path(__file__).parent / "fixtures/egnyte/comments.json").read_text())
    transport[1].append(httpx.Response(200, json=fixture["body"]))
    result = await run("list_comments", {"file": PATH})
    assert result["data"] == fixture["body"]


@pytest.mark.parametrize("config", [
    {"operation": "create_link", "path": PATH, "type": "file", "accessibility": "password"},
    {"operation": "create_link", "path": PATH, "type": "file", "accessibility": "recipients"},
    {"operation": "list_events", "id": 1, "suppress": "none"},
    {"operation": "search_files", "query": "ab"},
    {"operation": "unlock_file", "path": PATH},
    {"operation": "move_item", "path": PATH},
    {"operation": "create_folder", "path": PATH, "method": "DELETE"},
])
def test_invalid_operations(config):
    with pytest.raises(ValidationError):
        egnyte.EgnyteConfig.model_validate({"config": config, "credentials": AUTH})


async def test_oauth_declared_flow_exchange_identity_and_rotation(monkeypatch):
    for key in ["EGNYTE_CLIENT_ID", "EGNYTE_CLIENT_SECRET", "EGNYTE_REDIRECT_URI"]:
        monkeypatch.setenv(key, "https://app.example/api/auth/oauth/egnyte/callback" if key.endswith("URI") else "synthetic-client")
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.path == "/pubapi/v1/userinfo":
            return httpx.Response(200, json={"id": 123, "username": "test"})
        return httpx.Response(200, json={"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 2592000, "token_type": "bearer"})
    original = httpx.AsyncClient
    @asynccontextmanager
    async def client(template):
        async with original(transport=httpx.MockTransport(respond)) as c:
            yield c
    monkeypatch.setattr(type(OAUTH_PROVIDER), "_client", lambda self, template: client(template))
    tokens, name = await OAUTH_PROVIDER.exchange("synthetic-code", "https://app.example/api/auth/oauth/egnyte/callback", context={"account_host": "apidemo.egnyte.com"})
    assert name == "test" and tokens.account_host == "apidemo.egnyte.com"
    assert requests[0].url == "https://apidemo.egnyte.com/puboauth/token"
    assert parse_qs(requests[0].content.decode())["grant_type"] == ["authorization_code"]
    refreshed = await OAUTH_PROVIDER.bind_refresh(AUTH)("synthetic-refresh")
    assert refreshed.refresh_token == "new-refresh"
    assert parse_qs(requests[-1].content.decode())["grant_type"] == ["refresh_token"]
    assert OAUTH_PROVIDER.scopes == ["Egnyte.filesystem", "Egnyte.link"]
    with pytest.raises(RotatedRefreshTokenMissing):
        OAUTH_PROVIDER.parse_tokens(httpx.Response(200, json={"access_token": "new"}), context={"account_host": "apidemo.egnyte.com"})


async def test_empty_identity_cannot_verify_account(transport):
    transport[1].append(httpx.Response(200))
    with pytest.raises(ValueError, match="account identity"):
        await run("get_user_info")
    assert egnyte.EgnyteNode.connection_evidence.identity_keys == ("username",)
