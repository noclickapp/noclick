"""Native factory and real guarded HTTP tests; all accounts and tokens are synthetic."""
import asyncio
import json
import socket
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import gitea_node as native
from nodes.core.registry import NodeFactory
from utils import ssrf

TOKEN = "synthetic-gitea-personal-token-42"
AUTH = {"credential_type": "gitea_token", "instance_url": "https://gitea.example.com", "access_token": TOKEN}
RESOLVE = ssrf._resolve_host_addresses
REPO = {"owner": "octocat", "repo": "hello-world"}
ITEM = {"id": 7, "name": "hello-world", "title": "Automation", "login": "octocat"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    def send(request):
        requests.append(request)
        assert request.url.host == "gitea.example.com"
        assert request.headers["Authorization"] == "token " + TOKEN
        assert request.headers["Accept"] == "application/json"
        assert TOKEN not in str(request.url)
        return replies.pop(0)
    original = ssrf.guarded_async_client
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(**kwargs, transport=httpx.MockTransport(send))
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests, replies


def node(operation, arguments=None, auth=None):
    return NodeFactory.create_node(node_id="gitea-fixture", node_type="automation-gitea", node_data={
        "config": {"operation": operation, **(arguments or {})}, "credentials": AUTH if auth is None else auth})


# Independent expectations pin the provider's method, path and body contract.
CASES = [
    ("get_current_user", {}, "GET", "/user", None, False),
    ("list_repositories", {}, "GET", "/user/repos", None, True),
    ("get_repository", REPO, "GET", "/repos/octocat/hello-world", None, False),
    ("create_repository", {"name": "new-repo"}, "POST", "/user/repos", {"name": "new-repo", "private": True, "auto_init": False}, False),
    ("list_issues", REPO, "GET", "/repos/octocat/hello-world/issues", None, True),
    ("get_issue", {**REPO, "index": 12}, "GET", "/repos/octocat/hello-world/issues/12", None, False),
    ("create_issue", {**REPO, "title": "Automation"}, "POST", "/repos/octocat/hello-world/issues", {"title": "Automation"}, False),
    ("update_issue", {**REPO, "index": 12, "state": "closed"}, "PATCH", "/repos/octocat/hello-world/issues/12", {"state": "closed"}, False),
    ("list_issue_comments", {**REPO, "index": 12}, "GET", "/repos/octocat/hello-world/issues/12/comments", None, True),
    ("create_issue_comment", {**REPO, "index": 12, "body": "Thanks"}, "POST", "/repos/octocat/hello-world/issues/12/comments", {"body": "Thanks"}, False),
    ("list_pull_requests", REPO, "GET", "/repos/octocat/hello-world/pulls", None, True),
    ("get_pull_request", {**REPO, "index": 12}, "GET", "/repos/octocat/hello-world/pulls/12", None, False),
    ("create_pull_request", {**REPO, "title": "Automation", "head": "feature/work", "base": "main"}, "POST", "/repos/octocat/hello-world/pulls", {"title": "Automation", "head": "feature/work", "base": "main"}, False),
    ("update_pull_request", {**REPO, "index": 12, "body": ""}, "PATCH", "/repos/octocat/hello-world/pulls/12", {"body": ""}, False),
    ("list_branches", REPO, "GET", "/repos/octocat/hello-world/branches", None, True),
    ("create_branch", {**REPO, "new_branch_name": "feature/work", "old_branch_name": "main"}, "POST", "/repos/octocat/hello-world/branches", {"new_branch_name": "feature/work", "old_branch_name": "main"}, False),
    ("list_releases", REPO, "GET", "/repos/octocat/hello-world/releases", None, True),
    ("get_release", {**REPO, "release_id": 7}, "GET", "/repos/octocat/hello-world/releases/7", None, False),
    ("create_release", {**REPO, "tag_name": "v1.0"}, "POST", "/repos/octocat/hello-world/releases", {"tag_name": "v1.0", "draft": True, "prerelease": False}, False),
    ("update_release", {**REPO, "release_id": 7, "draft": False}, "PATCH", "/repos/octocat/hello-world/releases/7", {"draft": False}, False),
    ("list_labels", REPO, "GET", "/repos/octocat/hello-world/labels", None, True),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,body,is_list", CASES)
async def test_gitea_each_operation_makes_one_published_request(transport, operation, arguments, method, path, body, is_list):
    requests, replies = transport
    data = [ITEM] if is_list else ITEM
    code = 201 if method == "POST" or operation in {"update_issue", "update_pull_request"} else 200
    replies.append(httpx.Response(code, json=data))
    result = await node(operation, arguments).execute({})
    assert result["status"] == "success" and result["data"] == data
    assert len(requests) == 1 and replies == []
    request = requests[0]
    assert request.method == method and request.url.path == "/api/v1" + path
    assert (json.loads(request.content) if request.content else None) == body
    assert TOKEN not in json.dumps(result)
    expected_query = {"page": "1", "limit": "50"} if operation in {
        "list_repositories", "list_issues", "list_pull_requests", "list_branches", "list_releases", "list_labels"} else {}
    if operation in {"list_issues", "list_pull_requests"}: expected_query["state"] = "open"
    if operation == "list_issues": expected_query["type"] = "issues"
    assert dict(request.url.params) == expected_query


@pytest.mark.asyncio
async def test_gitea_optional_fields_preserve_false_empty_body_and_empty_assignment(transport):
    requests, replies = transport
    replies.append(httpx.Response(201, json=ITEM))
    await node("update_issue", {**REPO, "index": 12, "body": "", "assignees": [], "milestone": 0}).execute({})
    assert json.loads(requests[0].content) == {"body": "", "assignees": [], "milestone": 0}


@pytest.mark.asyncio
async def test_gitea_pagination_stays_on_selected_host_and_manual_page(transport):
    requests, replies = transport
    replies.append(httpx.Response(200, json=[ITEM], headers={"Link": '<https://evil.example/steal>; rel="next"'}))
    result = await node("list_issues", {**REPO, "page": 3, "limit": 1, "q": "space + café"}).execute({})
    assert result["has_more"] is True and result["next_page"] == 4
    assert len(requests) == 1 and dict(requests[0].url.params)["q"] == "space + café"
    replies.append(httpx.Response(200, json=[]))
    result = await node("list_issues", {**REPO, "page": 4, "limit": 1}).execute({})
    assert result["has_more"] is False and result["next_page"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [202, 203, 206, 301, 302, 401, 403, 404, 422, 429, 500])
async def test_gitea_rejection_is_not_success_or_retried_and_token_is_redacted(transport, code):
    requests, replies = transport
    replies.append(httpx.Response(code, json={"message": "Rejected " + TOKEN}, headers={"Location": "https://evil.example/"}))
    result = await node("get_current_user").execute({})
    assert result["status"] == "error" and result["http_status"] == code
    assert TOKEN not in json.dumps(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="login", headers={"Content-Type": "text/html"}),
    httpx.Response(200, content=b"not json", headers={"Content-Type": "application/json"}),
    httpx.Response(200, json=[]), httpx.Response(200, json={"error": "refused"}),
    httpx.Response(204), httpx.Response(200, content=b"x" * (8 * 1024 * 1024 + 1), headers={"Content-Type": "application/json"})])
async def test_gitea_invalid_success_payload_is_an_error(transport, response):
    transport[1].append(response)
    assert (await node("get_current_user").execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_gitea_echoed_token_cannot_escape_success(transport):
    transport[1].append(httpx.Response(200, json={"id": 7, "login": TOKEN, "nested": [TOKEN]}))
    result = await node("get_current_user").execute({})
    assert TOKEN not in json.dumps(result)


@pytest.mark.parametrize("field,bad", [("owner", "../other"), ("repo", "x/y"), ("repo", "x%2Fy"), ("owner", "https://other.test")])
def test_gitea_route_injection_refused(field, bad):
    with pytest.raises(ValueError):
        node("get_repository", {**REPO, field: bad})


@pytest.mark.parametrize("origin", ["http://gitea.example.com", "https://user:pass@gitea.example.com", "https://gitea.example.com/api/v1", "https://gitea.example.com?token=x", "https://gitea.example.com#frag"])
def test_gitea_credential_destination_boundary(origin):
    with pytest.raises(ValueError):
        native.GiteaTokenCredential.model_validate({**AUTH, "instance_url": origin})


@pytest.mark.asyncio
async def test_gitea_guard_blocks_private_dns_before_transport(transport, monkeypatch):
    monkeypatch.setenv("OUTBOUND_ALLOW_PRIVATE_IPS", "false")
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", RESOLVE)
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]))
    assert (await node("get_current_user").execute({}))["status"] == "error"
    assert transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args", [("update_issue", {**REPO, "index": 12}), ("update_pull_request", {**REPO, "index": 12}), ("update_release", {**REPO, "release_id": 7})])
async def test_gitea_empty_update_refused_without_http(transport, operation, args):
    with pytest.raises(ValueError, match="at least one"):
        await node(operation, args).execute({})
    assert transport[0] == []


def test_gitea_hand_connect_default_type_and_normalized_origin():
    auth = native.GiteaTokenCredential(instance_url="https://GITEA.example.com/", access_token=TOKEN)
    assert auth.credential_type == "gitea_token" and auth.instance_url == AUTH["instance_url"]
    assert "credential_type" not in native.GiteaTokenCredential.model_json_schema()["required"]
    with pytest.raises(ValueError):
        node("get_current_user", auth={**AUTH, "credential_type": "forgejo_pat"})
