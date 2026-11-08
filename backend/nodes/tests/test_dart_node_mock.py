"""Dart contract transports with synthetic account data; no live writes."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import dart_node as native
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NodeFactory

ID = "Ab12Cd34Ef56"
TOKEN = "synthetic-dart-token-42"
CASES = json.loads((Path(__file__).parent / "fixtures/dart/transport.json").read_text())["cases"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential():
    return {"credential_type": "dart_api_token", "api_token": TOKEN}


def node(config):
    return NodeFactory.create_node(node_id="dart-fixture", node_type="automation-dart",
        node_data={"config": config, "credentials": credential()})


def transport(monkeypatch, body, status=200):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body(request) if callable(body) else body)

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_dart_provider_method_route_body_and_parser(monkeypatch, case):
    requests = transport(monkeypatch, case["response"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert TOKEN not in str(result)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "app.dartai.com"
    assert request.url.path == case["path"]
    assert dict(request.url.params) == case["params"]
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN


@pytest.mark.asyncio
async def test_dart_pagination_and_picker_share_one_page(monkeypatch):
    requests = transport(monkeypatch, {"count": 200, "results": [{"id": ID, "title": "Launch"}],
        "next": native.BASE + "/tasks/list?offset=50&limit=50"})
    result = await node({"operation": "list_tasks", "no_defaults": True, "is_completed": False}).execute({})
    assert result["has_more"] is True and result["next_offset"] == 50
    assert len(requests) == 1
    assert requests[0].url.params["is_completed"] == "false"
    assert requests[0].url.params["no_defaults"] == "true"
    choices = await native.DartNode.load_field_options("task_id", credential(), page_token="0", search="Launch + café")
    assert choices == {"options": [{"value": ID, "label": "Launch"}], "next_page_token": "50"}
    assert len(requests) == 2 and requests[-1].url.params["title"] == "Launch + café"


@pytest.mark.asyncio
@pytest.mark.parametrize("link", ["https://evil.test/tasks?offset=50", native.BASE + "/docs/list?offset=50",
    native.BASE + "/tasks/list?offset=0", native.BASE + "/tasks/list?offset=x"])
async def test_dart_foreign_or_stalled_continuation_refused_without_following(monkeypatch, link):
    requests = transport(monkeypatch, {"count": 1, "results": [], "next": link})
    with pytest.raises(ValueError):
        await node({"operation": "list_tasks"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_dart_http_failures_keep_provider_message_and_redact_token(monkeypatch, status):
    requests = transport(monkeypatch, {"detail": "Not accepted " + TOKEN}, status)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_me"}).execute({})
    assert str(status) in str(exc.value) and "Not accepted" in str(exc.value)
    assert TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"item": []}, {"item": {"id": "other"}}, {"error": "bad"}])
async def test_dart_invalid_resource_or_error_is_not_success(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "get_task", "task_id": ID}).execute({})


@pytest.mark.asyncio
async def test_dart_update_omission_and_move_without_anchor_refused_locally(monkeypatch):
    requests = transport(monkeypatch, {"item": {"id": ID}})
    for config in [{"operation": "update_task", "task_id": ID},
        {"operation": "update_doc", "doc_id": ID},
        {"operation": "move_task", "task_id": ID, "position": "before"}]:
        with pytest.raises(ValueError):
            await node(config).execute({})
    assert requests == []


def test_dart_manual_credential_default_masking_and_strict_resource_ids():
    shaped = native.DartAPITokenCredential(api_token="  " + TOKEN + "\n")
    assert shaped.credential_type == "dart_api_token" and shaped.api_token == TOKEN
    for token in ["Bearer " + TOKEN, "https://app.dartai.com", "<token>"]:
        with pytest.raises(ValidationError):
            native.DartAPITokenCredential(api_token=token)
    for config in [{"operation": "get_task", "task_id": "../bad"},
        {"operation": "list_comments"}, {"operation": "create_doc"},
        {"operation": "list_tasks", "limit": 0}]:
        with pytest.raises(ConfigValidationError):
            native.DartNode.parse_config({"config": config})
