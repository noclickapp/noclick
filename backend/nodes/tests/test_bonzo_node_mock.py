"""Execute the BONZO operations through the factory and inspect their HTTP contract."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import bonzo_node as native
from nodes.core.registry import NodeFactory

TOKEN = "bonzo-synthetic-fixture-secret"
CASES = json.loads((Path(__file__).parent / "fixtures/bonzo/operations.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="bonzo-test", node_type="automation-bonzo", node_data={
        "config": config, "credentials": {"credential_type": "bonzo_api_token", "api_token": TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_operation_http_contract(monkeypatch, operation):
    case = CASES[operation]
    config = case["config"]
    path = case["path"]
    for k, v in config.items():
        path = path.replace("{" + ("pipelineStage" if k == "pipeline_stage" else k) + "}", str(v))
    if operation in {"delete_prospect", "delete_note", "move_prospect"}:
        body = {"message": "Person has been successfully assigned."}
    else:
        identifier = config.get("note", config.get("prospect", config.get("task", config.get("pipeline", 1))))
        body = {"data": [{"id": identifier}] if operation.startswith("list_") else {"id": identifier}}
        if "page" in config:
            body["meta"] = {"current_page": 1, "last_page": 2}
    requests = transport(monkeypatch, body, 201 if operation == "create_note" else 200)
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert result.get("write_acknowledged", False) == (case["method"] != "GET")
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert str(request.url).split("?")[0] == native.BASE + path
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if "page" in config:
        assert dict(request.url.params) == {"page": "1", "per_page": "15"}
        assert result["next_page"] == 2 and result["has_more"] is True
    if operation in {"create_note", "update_note"}:
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {"content": "Example note content"}
    if operation in {"create_prospect", "update_prospect"}:
        assert json.loads(request.content) == {"first_name": "John"}
    if operation == "send_email":
        assert json.loads(request.content) == {"subject": "Email subject", "message": "Email message"}


@pytest.mark.asyncio
async def test_json_boolean_tag_and_message_serialization(monkeypatch):
    requests = transport(monkeypatch, {"data": {"id": 1}}, 201)
    await node({"operation": "create_note", "prospect": 1, "content": "A & B", "is_pinned": False, "include_in_conversation": True}).execute({})
    assert json.loads(requests[0].content) == {"content": "A & B", "is_pinned": False, "include_in_conversation": True}
    requests = transport(monkeypatch, {"data": {"id": 1}})
    await node({"operation": "update_prospect", "prospect": 1, "first_name": "Jane", "tags": "new lead"}).execute({})
    assert json.loads(requests[0].content) == {"first_name": "Jane", "tags": "new lead"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 422, 429, 500])
async def test_errors_are_redacted_and_never_retried(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    with pytest.raises(ValueError, match="Rejected \\[redacted\\]") as exc:
        await node({"operation": "get_current_user"}).execute({})
    assert TOKEN not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"data": []}, {"error": "denied"}, {"data": {"id": 2}}])
async def test_invalid_envelopes_and_different_resource_are_rejected(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "get_prospect", "prospect": 1}).execute({})


@pytest.mark.asyncio
async def test_empty_terminal_page_and_no_following_provider_links(monkeypatch):
    requests = transport(monkeypatch, {"data": [], "meta": {"current_page": 2, "last_page": 2}, "links": {"next": "https://evil.example"}})
    result = await node({"operation": "list_prospects", "page": 2, "search": "Jane"}).execute({})
    assert result["items"] == [] and result["next_page"] is None and not result["has_more"]
    assert dict(requests[0].url.params) == {"page": "2", "per_page": "15", "search": "Jane"}
    assert len(requests) == 1


@pytest.mark.parametrize("value", ["Bearer token", "https://evil.example/key", "<token>", "abc\r\nx: y"])
def test_invalid_tokens(value):
    with pytest.raises(ValidationError):
        native.BonzoAPITokenCredential(api_token=value)


@pytest.mark.parametrize("value", [0, -1, "../me", "1?foo=2"])
def test_path_injection_is_rejected(value):
    with pytest.raises(Exception):
        node({"operation": "get_prospect", "prospect": value})


@pytest.mark.asyncio
async def test_current_documented_note_success_status(monkeypatch):
    transport(monkeypatch, {"data": {"id": 1}}, 200)
    result = await node({"operation": "create_note", "prospect": 1, "content": "Note"}).execute({})
    assert result["write_acknowledged"] is True
