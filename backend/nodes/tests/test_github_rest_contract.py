"""Offline regressions for GitHub's documented routes and JSON request bodies.

Response fixtures are copied verbatim from GitHub's OpenAPI examples; each
fixture records its source and operation. No GitHub credentials are used.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes.github_rest_node import (
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


def test_update_gist_rejects_file_array():
    with pytest.raises(ValidationError):
        GithubUpdateGistConfig(gist_id="2decf6c462d9b4418f2", files=["README.md"])


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
