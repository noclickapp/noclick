"""Exercise native discovery and wire serialization without live credentials."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import manus_node as manus
from nodes.core.connection_evidence import collect_evidence
from nodes.core.run_op import run_node_operation

AUTH = {"credential_type": "manus_api_key", "api_key": "synthetic-manus-key"}
USER = "00000000-0000-4000-8000-000000000001"
CASES = json.loads((Path(__file__).parent / "fixtures/manus/requests.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    native = httpx.AsyncClient

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.manus.ai"
        assert request.headers["x-manus-api-key"] == AUTH["api_key"]
        assert "authorization" not in request.headers
        assert AUTH["api_key"] not in str(request.url)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(
        manus.httpx,
        "AsyncClient",
        lambda **kw: native(**kw, transport=httpx.MockTransport(send)),
    )
    return requests, replies


async def run(operation, arguments):
    return await run_node_operation(
        node_type="automation-manus",
        operation=operation,
        arguments=arguments,
        credential_data=AUTH.copy(),
        user_id=USER,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["operation"])
async def test_each_operation_has_one_exact_request(transport, case):
    requests, replies = transport
    response = {
        "ok": True,
        "request_id": "req-1",
        "user_id": "user-1",
        "has_more": True,
        "next_cursor": "opaque-next",
        "tasks": [],
    }
    replies.append((200, response))
    result = await run(case["operation"], case["config"])
    assert result == response
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == case["method"] and request.url.path == case["path"]
    if request.method == "GET":
        assert dict(request.url.params) == {
            k: str(v).lower() if isinstance(v, bool) else str(v)
            for k, v in case["config"].items()
        }
        assert request.content == b""
    else:
        assert json.loads(request.content) == case.get("body", case["config"])


@pytest.mark.asyncio
async def test_account_evidence_uses_read_only_user_identity(transport):
    requests, replies = transport
    replies.append((200, {"ok": True, "user_id": "user-1", "name": "Fixture Account"}))
    result = await collect_evidence(
        node_type="automation-manus", user_id=USER, credential_data=AUTH.copy()
    )
    assert result.reachable is True and result.account_label == "Fixture Account"
    assert [(r.method, r.url.path) for r in requests] == [("GET", "/v2/user.me")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body",
    [
        (
            401,
            {
                "ok": False,
                "error": {"code": "unauthenticated", "message": "Invalid API key"},
            },
        ),
        (
            200,
            {
                "ok": False,
                "error": {"code": "invalid_argument", "message": "Wrong task"},
            },
        ),
        (302, {"location": "https://example.com"}),
        (200, []),
        (200, {}),
    ],
)
async def test_provider_errors_and_redirects_fail_without_retry(
    transport, status, body
):
    requests, replies = transport
    replies.append((status, body))
    with pytest.raises((ValueError, httpx.HTTPStatusError)):
        await run("get_task", {"task_id": "task-1"})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_http_error_redacts_key_but_preserves_rejection(transport):
    _, replies = transport
    replies.append((401, {"error": {"message": "Rejected " + AUTH["api_key"]}}))
    with pytest.raises(httpx.HTTPStatusError) as exc:
        await run("get_current_user", {})
    assert AUTH["api_key"] not in str(exc.value) and "Rejected" in str(exc.value)


@pytest.mark.parametrize(
    "model,config",
    [
        (manus.ManusListTasksConfig, {"scope": "project"}),
        (manus.ManusListTasksConfig, {"scope": "agent_subtask"}),
        (manus.ManusListTasksConfig, {"oauth_client_id": "app", "api_key_id": "key"}),
        (
            manus.ManusListMessagesConfig,
            {"task_id": "task-1", "cursor": "next", "start_event_id": "event-1"},
        ),
        (
            manus.ManusCreateTaskConfig,
            {
                "message": {"content": "hello", "connectors": ["c1"]},
                "clear_connectors": True,
            },
        ),
        (manus.ManusCreateTaskConfig, {"message": {"content": " "}}),
        (manus.ManusGetTaskConfig, {"task_id": ""}),
        (manus.ManusListTasksConfig, {"limit": 101}),
        (manus.ManusCreateTaskConfig, {"message": {"content": "hello"}, "website": {}}),
        (
            manus.ManusCreateTaskConfig,
            {"message": {"content": "hello"}, "agent_profile": "unknown"},
        ),
    ],
)
def test_invalid_inputs_fail_before_http(model, config):
    with pytest.raises(ValidationError):
        model.model_validate(config)
