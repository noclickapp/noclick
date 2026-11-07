"""Offline regressions for GitHub's documented routes and JSON request bodies.

Response fixtures are copied verbatim from GitHub's OpenAPI examples; each
fixture records its source and operation. No GitHub credentials are used.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes.github_rest_node import (
    GithubGetRepositoryConfig,
    GithubRestNode,
    GithubRestNodeConfig,
    GithubUpdateGistConfig,
)


RESPONSES = json.loads(
    (Path(__file__).parent / "fixtures" / "github_rest_responses.json").read_text()
)
REPO = {"owner": "octocat", "repo": "Hello-World"}
SHA = "6dcb09b5b57875f334f61aebed695e2e4193db5e"


async def run_node(monkeypatch, config, fixtures):
    requests = []
    responses = iter(fixtures)

    def transport(request):
        requests.append(request)
        fixture = RESPONSES[next(responses)]
        return httpx.Response(fixture["status"], json=fixture["response"])

    original_client = httpx.AsyncClient

    def client(*args, **kwargs):
        return original_client(
            *args, **kwargs, transport=httpx.MockTransport(transport)
        )

    monkeypatch.setattr(httpx, "AsyncClient", client)
    node = GithubRestNode(
        node_id="github-contract",
        node_type="automation-github-rest",
        node_data={},
        config=GithubRestNodeConfig.model_validate(
            {
                "config": config,
                "credentials": {
                    "credential_type": "github_pat",
                    "personal_access_token": "conformance-fake-token",
                },
            }
        ),
        sio=None,
    )
    node.emit = AsyncMock()
    result = await node.execute({})
    assert result["status"] == "success", result
    assert len(requests) == len(fixtures)
    assert set(result) == {"type", "action", "status", "data", "timestamp", "timing_ms"}
    assert result["type"] == "github_rest"
    assert result["action"] == config["operation"]
    assert result["data"] == RESPONSES[fixtures[-1]]["response"]
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config,fixture,method,path,body",
    [
        (
            {
                "operation": "create_pull_request_review_comment",
                **REPO,
                "pull_number": 1,
                "body": "Great stuff!",
                "commit_id": SHA,
                "path": "file1.txt",
                "start_line": 1,
                "start_side": "RIGHT",
                "line": 2,
                "side": "RIGHT",
            },
            "review_comment",
            "POST",
            "/repos/octocat/Hello-World/pulls/1/comments",
            {
                "body": "Great stuff!",
                "commit_id": SHA,
                "path": "file1.txt",
                "start_line": 1,
                "start_side": "RIGHT",
                "line": 2,
                "side": "RIGHT",
            },
        ),
        (
            {
                "operation": "submit_pull_request_review",
                **REPO,
                "pull_number": 1,
                "review_id": 1,
                "event": "REQUEST_CHANGES",
                "body": "Here is the body for the review.",
            },
            "submit_review",
            "POST",
            "/repos/octocat/Hello-World/pulls/1/reviews/1/events",
            {"event": "REQUEST_CHANGES", "body": "Here is the body for the review."},
        ),
        (
            {
                "operation": "submit_pull_request_review",
                **REPO,
                "pull_number": 1,
                "review_id": 1,
                "event": "APPROVE",
            },
            "submit_review",
            "POST",
            "/repos/octocat/Hello-World/pulls/1/reviews/1/events",
            {"event": "APPROVE"},
        ),
        (
            {
                "operation": "update_pull_request_branch",
                **REPO,
                "pull_number": 1,
                "expected_head_sha": SHA,
            },
            "update_branch",
            "PUT",
            "/repos/octocat/Hello-World/pulls/1/update-branch",
            {"expected_head_sha": SHA},
        ),
        (
            {"operation": "update_pull_request_branch", **REPO, "pull_number": 1},
            "update_branch",
            "PUT",
            "/repos/octocat/Hello-World/pulls/1/update-branch",
            {},
        ),
        (
            {
                "operation": "update_repo_webhook",
                **REPO,
                "hook_id": 12345678,
                "config": {
                    "url": "https://example.com/webhook",
                    "content_type": "json",
                },
                "events": ["push", "pull_request"],
                "active": False,
            },
            "update_hook",
            "PATCH",
            "/repos/octocat/Hello-World/hooks/12345678",
            {
                "config": {
                    "url": "https://example.com/webhook",
                    "content_type": "json",
                },
                "events": ["push", "pull_request"],
                "active": False,
            },
        ),
        (
            {
                "operation": "create_org_webhook",
                "org": "octocat",
                "name": "web",
                "config": {"url": "http://example.com/webhook", "content_type": "json"},
                "events": ["push", "pull_request"],
                "active": False,
            },
            "create_org_hook",
            "POST",
            "/orgs/octocat/hooks",
            {
                "name": "web",
                "config": {"url": "http://example.com/webhook", "content_type": "json"},
                "events": ["push", "pull_request"],
                "active": False,
            },
        ),
    ],
)
async def test_documented_json_requests(
    monkeypatch, config, fixture, method, path, body
):
    (request,) = await run_node(monkeypatch, config, [fixture])
    assert (request.method, request.url.path) == (method, path)
    assert not request.url.query
    assert json.loads(request.content) == body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "update",
    [
        {
            "description": "An updated gist description",
            "files": {"README.md": {"content": "Hello World from GitHub"}},
        },
        {"files": {"hello.py": None}},
        {"files": {"hello.py": {"filename": "goodbye.py"}}},
        {"description": "An updated gist description"},
    ],
)
async def test_update_gist_file_map_and_description(monkeypatch, update):
    (request,) = await run_node(
        monkeypatch,
        {
            "operation": "update_gist",
            "gist_id": "2decf6c462d9b4418f2",
            **update,
        },
        ["update_gist"],
    )
    assert (request.method, request.url.path) == ("PATCH", "/gists/2decf6c462d9b4418f2")
    assert not request.url.query
    assert json.loads(request.content) == update


@pytest.mark.asyncio
@pytest.mark.parametrize("gist_id", [123456, "123456", "2decf6c462d9b4418f2"])
@pytest.mark.parametrize(
    "files,expected",
    [
        ([], {}),
        (
            {"README.md": {"content": "Hello World from GitHub"}},
            {"README.md": {"content": "Hello World from GitHub"}},
        ),
        (
            [{"filename": "README.md", "content": "Hello World from GitHub"}],
            {"README.md": {"content": "Hello World from GitHub"}},
        ),
        (
            [
                {"README.md": {"content": "Hello World from GitHub"}},
                {"hello.py": {"filename": "goodbye.py"}},
                {"old.py": None},
            ],
            {
                "README.md": {"content": "Hello World from GitHub"},
                "hello.py": {"filename": "goodbye.py"},
                "old.py": None,
            },
        ),
    ],
)
async def test_saved_gist_config_adapts_only_at_request_boundary(
    monkeypatch, gist_id, files, expected
):
    saved = {"operation": "update_gist", "gist_id": gist_id, "files": files}
    parsed = GithubUpdateGistConfig.model_validate(saved)
    assert parsed.model_dump()["gist_id"] == gist_id
    assert parsed.model_dump()["files"] == files
    (request,) = await run_node(monkeypatch, saved, ["update_gist"])
    assert request.url.path == f"/gists/{gist_id}"
    assert json.loads(request.content) == {"files": expected}
    assert parsed.model_dump()["files"] == files


@pytest.mark.parametrize(
    "files",
    [
        ["README.md"],
        [{"filename": "README.md"}],
        [{"README.md": {"content": "first"}}, {"README.md": {"content": "second"}}],
    ],
)
def test_unrecoverable_saved_arrays_load_without_guessing_file_deletions(files):
    parsed = GithubUpdateGistConfig(gist_id=123456, files=files)
    assert parsed.model_dump()["files"] == files
    with pytest.raises(ValueError, match="Legacy gist|Duplicate legacy gist"):
        parsed.request_files()


def test_gist_schema_still_accepts_saved_field_types():
    properties = GithubUpdateGistConfig.model_json_schema()["properties"]
    assert {s["type"] for s in properties["gist_id"]["anyOf"]} == {"integer", "string"}
    assert {s["type"] for s in properties["files"]["anyOf"]} == {
        "object",
        "array",
        "null",
    }


@pytest.mark.asyncio
async def test_create_branch_resolves_singular_ref_route(monkeypatch):
    requests = await run_node(
        monkeypatch,
        {
            "operation": "create_branch",
            **REPO,
            "branch_name": "feature-a",
            "source_branch": "main",
        },
        ["get_ref", "create_ref"],
    )
    assert (requests[0].method, requests[0].url.path) == (
        "GET",
        "/repos/octocat/Hello-World/git/ref/heads/main",
    )
    assert (requests[1].method, requests[1].url.path) == (
        "POST",
        "/repos/octocat/Hello-World/git/refs",
    )
    assert json.loads(requests[1].content) == {
        "ref": "refs/heads/feature-a",
        "sha": RESPONSES["get_ref"]["response"]["object"]["sha"],
    }


@pytest.mark.asyncio
async def test_workflow_run_usage_uses_timing_route(monkeypatch):
    (request,) = await run_node(
        monkeypatch,
        {
            "operation": "get_workflow_run_usage",
            **REPO,
            "run_id": 1,
        },
        ["run_usage"],
    )
    assert (request.method, request.url.path) == (
        "GET",
        "/repos/octocat/Hello-World/actions/runs/1/timing",
    )


# Moved from the live suite (test_github_rest_node.py), the one check there that needs no account.
@pytest.mark.asyncio
async def test_missing_credentials():
    """Test handling of missing credentials."""
    config = GithubGetRepositoryConfig(**REPO)
    node_config = GithubRestNodeConfig(config=config, credentials=None)
    node = GithubRestNode(
        node_id="test-node",
        node_type="automation-github-rest",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )

    with pytest.raises(ValueError, match="Credentials are required"):
        await node.execute({})
