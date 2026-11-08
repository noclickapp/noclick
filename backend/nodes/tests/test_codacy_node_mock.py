"""Codacy transport tests; synthetic credentials, no provider account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import codacy_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads(
    (Path(__file__).parent / "fixtures/codacy/operations.json").read_text()
)
TOKEN = "synthetic-codacy-account-token-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="codacy-test",
        node_type="automation-codacy",
        node_data={
            "config": config,
            "credentials": {"credential_type": "codacy_api_token", "api_token": TOKEN},
        },
    )


def mock_client(monkeypatch, reply):
    requests = []

    def respond(request):
        requests.append(request)
        return reply(request)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_contract_routes_auth_and_one_request(monkeypatch, operation):
    case = CASES[operation]
    no_content = operation in {
        "unfollow_repository",
        "reanalyze_commit",
        "update_file_state",
        "update_issue_state",
    }
    response = {
        "data": [{"id": 12, "name": "Codacy"}],
        "pagination": {"cursor": "next+/==", "limit": 100},
    }
    if not operation.startswith("list_"):
        response["data"] = {"id": 12, "name": "Codacy"}
    if operation == "follow_repository":
        response["data"] = "Following"
    if operation == "get_pull_request":
        response = {"isAnalysing": False, "meta": {}, "pullRequest": {"number": 1}}
    if operation == "get_commit":
        response = {"commit": {"id": "123"}, "meta": {}}
    if operation == "list_ignored_files":
        response["hasCodacyConfigurationFile"] = False
    if operation == "list_pull_request_issues":
        response["analyzed"] = True
    requests = mock_client(
        monkeypatch,
        lambda req: httpx.Response(204)
        if no_content
        else httpx.Response(200, json=response),
    )
    out = await node(case["config"]).execute({})
    assert out["status"] == "success"
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case["method"]
    assert req.url.host == "api.codacy.com"
    assert req.headers["api-token"] == TOKEN
    assert "authorization" not in req.headers
    substitutions = {
        "provider": "provider",
        "remoteOrganizationName": "organization",
        "repositoryName": "repository",
        "pullRequestNumber": "pull_request_number",
        "commitUuid": "commit_uuid",
        "issueId": "issue_id",
    }
    path = case["path"]
    for key, attr in substitutions.items():
        if "{" + key + "}" in path:
            path = path.replace("{" + key + "}", str(case["config"][attr]))
    assert req.url.path == "/api/v3" + path
    if no_content:
        assert out["acknowledged"] is True and out["http_status"] == 204
    else:
        assert {key: out[key] for key in response} == response
    expected_bodies = {
        "reanalyze_commit": {
            "commitUuid": "2957025d42e8daadf937d4044516f991d21deea4",
            "cleanCache": False,
        },
        "update_file_state": {
            "filepath": "src/main/scala/main/Main.scala",
            "ignored": True,
        },
        "update_issue_state": {"ignored": True},
    }
    if operation in expected_bodies:
        assert json.loads(req.content) == expected_bodies[operation]
    else:
        assert req.content == b""


@pytest.mark.asyncio
async def test_cursor_encoded_once_without_automatic_page_fetch(monkeypatch):
    requests = mock_client(
        monkeypatch,
        lambda req: httpx.Response(
            200, json={"data": [], "pagination": {"cursor": "second=="}}
        ),
    )
    out = await node(
        {
            "operation": "list_repositories",
            "provider": "bb",
            "organization": "my org",
            "cursor": "Yms+/==",
            "limit": 20,
            "search": "backend",
        }
    ).execute({})
    assert len(requests) == 1
    assert dict(requests[0].url.params) == {
        "cursor": "Yms+/==",
        "limit": "20",
        "search": "backend",
    }
    assert out["pagination"]["cursor"] == "second=="
    assert "my%20org" in str(requests[0].url)


@pytest.mark.asyncio
async def test_optional_write_fields_and_false_preserved(monkeypatch):
    requests = mock_client(monkeypatch, lambda req: httpx.Response(204))
    await node(
        {
            "operation": "update_issue_state",
            "provider": "gh",
            "organization": "codacy",
            "repository": "awesome-repo",
            "issue_id": "123",
            "ignored": False,
            "reason": "FalsePositive",
            "comment": "Reviewed",
        }
    ).execute({})
    assert json.loads(requests[0].content) == {
        "ignored": False,
        "reason": "FalsePositive",
        "comment": "Reviewed",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 422, 429, 500])
async def test_failure_not_success_not_retried_and_redacted(monkeypatch, status):
    requests = mock_client(
        monkeypatch,
        lambda req: httpx.Response(
            status,
            text="Token rejected " + TOKEN,
            headers={"Location": "https://other.example/"},
        ),
    )
    result = await node({"operation": "get_user"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Token rejected" in result["error"] and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_timeout_does_not_leak_request_or_retry_write(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("secret " + TOKEN, request=request)

    requests = mock_client(monkeypatch, fail)
    result = await node(CASES["reanalyze_commit"]["config"]).execute({})
    assert result["status"] == "error" and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        b"<html>bad</html>",
        b"null",
        b"42",
        b"{}",
        b'{"error":"not found"}',
        b'{"data":null}',
    ],
)
async def test_malformed_success_not_evidence(monkeypatch, body):
    mock_client(monkeypatch, lambda req: httpx.Response(200, content=body))
    assert (await node({"operation": "get_user"}).execute({}))["status"] == "error"


def test_manual_credential_default_and_token_validation():
    assert (
        native.CodacyAPITokenCredential(api_token=TOKEN).credential_type
        == "codacy_api_token"
    )
    assert not native.CodacyAPITokenCredential.model_fields[
        "credential_type"
    ].is_required()
    for bad in ["https://example.com/key", "your_api_key", "Bearer token value", ""]:
        with pytest.raises(ValidationError):
            native.CodacyAPITokenCredential(api_token=bad)


@pytest.mark.parametrize(
    "config",
    [
        {
            "operation": "get_repository",
            "provider": "gh",
            "organization": ".",
            "repository": "repo",
        },
        {"operation": "list_organizations", "limit": 101},
        {
            "operation": "get_pull_request",
            "provider": "gh",
            "organization": "org",
            "repository": "repo",
            "pull_request_number": 0,
        },
        {
            "operation": "update_file_state",
            "provider": "gh",
            "organization": "org",
            "repository": "repo",
            "filepath": "file",
        },
    ],
)
def test_invalid_requests_fail_before_http(config):
    with pytest.raises(ValueError):
        node(config)
