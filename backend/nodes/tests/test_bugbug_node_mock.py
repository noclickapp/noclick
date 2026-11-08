"""Exercise the actual operation factory with HTTP intercepted at transport."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import bugbug_node as native
from nodes.core.run_op import run_node_operation
from utils import ssrf

TOKEN = "synthetic-bugbug-test-token"
AUTH = {"credential_type": "bugbug_api_token", "api_token": TOKEN}
ID = "8f0c2a4e-1b7d-4c5e-9a3f-2d6b1e0c7a91"
CASES = json.loads((Path(__file__).parent / "fixtures/bugbug/wire.json").read_text())["cases"]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.bugbug.io"
        assert request.headers["Authorization"] == "Token " + TOKEN
        assert TOKEN not in str(request.url)
        status, body = replies.pop(0)
        return httpx.Response(status, content=b"") if status == 204 else httpx.Response(status, json=body)
    client = ssrf.guarded_async_client
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(op, arguments=None):
    return await run_node_operation(node_type="automation-bugbug", operation=op,
        arguments=arguments or {}, credential_data=AUTH.copy(), user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_every_operation_has_exactly_one_contract_request(transport, case):
    requests, replies = transport
    replies.append((case["status"], case["response"]))
    result = await run(case["operation"], case["config"])
    assert result["success"] is True and result["data"] == case["response"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"] and request.url.path == case["path"]
    assert dict(request.url.params) == case["query"]
    assert (json.loads(request.content) if request.content else None) == case["body"]


@pytest.mark.asyncio
async def test_false_empty_tags_overrides_and_profile_are_preserved(transport):
    requests, replies = transport
    replies.append((200, {"id": ID}))
    await run("update_suite", {"suite_id": ID, "auto_retry": 0, "run_in_parallel": False, "tests": [], "tags": []})
    assert json.loads(requests[-1].content) == {"autoRetry": 0, "runInParallel": False, "tests": [], "tags": []}
    replies.append((200, {"id": ID, "status": "queued"}))
    await run("run_suite", {"suite_id": ID, "run_profile_id": ID, "variables": [{"key": "email", "value": "qa@example.test"}], "tags": ["ci"]})
    assert json.loads(requests[-1].content) == {"suiteId": ID, "runProfileId": ID, "variables": [{"key": "email", "value": "qa@example.test"}], "tags": ["ci"]}


@pytest.mark.asyncio
async def test_pagination_filters_and_no_following_provider_links(transport):
    requests, replies = transport
    body = {"count": 40, "next": "https://untrusted.example/page/3", "previous": None, "results": [{"id": ID}]}
    replies.append((200, body))
    result = await run("list_tests", {"page": 2, "page_size": 20, "folder_id": ID, "latest_run": False, "no_folder": True, "query": "login", "ordering": "-name"})
    assert len(requests) == 1 and result["data"] == body
    assert dict(requests[0].url.params) == {"page": "2", "page_size": "20", "folderId": ID, "latestRun": "false", "noFolder": "true", "query": "login", "ordering": "-name"}


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 302, 400, 401, 402, 403, 404, 429, 500])
async def test_provider_errors_are_failures_redacted_and_never_retried(transport, code):
    requests, replies = transport
    replies.append((code, {"message": "Rejected " + TOKEN}))
    result = await run("run_test", {"test_id": ID})
    assert result["success"] is False and result["http_status"] == code
    assert TOKEN not in str(result) and len(requests) == 1
    assert "Rejected" in result["message"]


@pytest.mark.parametrize("config", [
    {"operation": "get_test", "test_id": "../escape"},
    {"operation": "create_suite"},
    {"operation": "create_variable", "key": "email", "type": "wrong"},
    {"operation": "run_test", "test_id": ID, "tags": ["x" * 65]},
    {"operation": "list_tests", "page": 0},
    {"operation": "list_tests", "page_size": 101},
    {"operation": "list_tests", "unknown": True},
])
def test_invalid_configuration_rejected(config):
    with pytest.raises((ValueError, ValidationError)):
        native.BugbugNode.parse_config({"config": config, "credentials": AUTH})


def test_manual_credential_default_and_secret_shape():
    assert native.BugbugTokenCredential(api_token=TOKEN).credential_type == "bugbug_api_token"
    for bad in ["Token abc", "https://example.test/token", "abc\r\nInjected: yes"]:
        with pytest.raises(ValueError):
            native.BugbugTokenCredential(api_token=bad)
