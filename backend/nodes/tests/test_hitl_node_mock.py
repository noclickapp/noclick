"""Hitl HTTP-boundary regressions using published provider response examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import hitl_node as native
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NodeFactory

TOKEN = "hitl-test-secret-12345"
LOOP = "65f1234567890abcdef12345"
REQUEST = "65f1234567890abcdef12348"
USER = "65f1234567890abcdef12347"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/hitl/responses.json").read_text())
CONFIGS = {
    "list_loops": {}, "get_loop": {"loop_id": LOOP},
    "create_loop": {"name": "Content Moderation Review", "icon": "shield-check"},
    "update_loop": {"loop_id": LOOP, "description": "Updated moderation"},
    "delete_loop": {"loop_id": LOOP}, "list_loop_members": {"loop_id": LOOP},
    "remove_loop_member": {"loop_id": LOOP, "user_id": USER},
    "test_api_key": {}, "list_requests": {}, "get_request": {"request_id": REQUEST},
    "cancel_request": {"request_id": REQUEST},
    "add_feedback": {"request_id": REQUEST, "feedback": {"rating": 5}},
    "list_loop_requests": {"loop_id": LOOP},
    "create_request": {"loop_id": LOOP, "request_text": "Please review this content for approval",
        "response_type": "single_select", "response_config": {"options": ["Approve", "Reject"]},
        "default_response": "Reject", "timeout_seconds": 1800},
}
# Paths are pinned independently of the implementation's route table.
EXPECTED = {
    "list_loops": ("GET", "/v1/api/loops"),
    "get_loop": ("GET", f"/v1/api/loops/{LOOP}"),
    "create_loop": ("POST", "/v1/api/loops"),
    "update_loop": ("PUT", f"/v1/api/loops/{LOOP}"),
    "delete_loop": ("DELETE", f"/v1/api/loops/{LOOP}"),
    "list_loop_members": ("GET", f"/v1/api/loops/{LOOP}/members"),
    "remove_loop_member": ("DELETE", f"/v1/api/loops/{LOOP}/members/{USER}"),
    "test_api_key": ("GET", "/v1/test"),
    "list_requests": ("GET", "/v1/api/requests"),
    "get_request": ("GET", f"/v1/api/requests/{REQUEST}"),
    "cancel_request": ("DELETE", f"/v1/api/requests/{REQUEST}"),
    "add_feedback": ("POST", f"/v1/api/requests/{REQUEST}/feedback"),
    "list_loop_requests": ("GET", f"/v1/api/loops/{LOOP}/requests"),
    "create_request": ("POST", f"/v1/api/loops/{LOOP}/requests"),
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **config):
    return NodeFactory.create_node(node_id="hitl-fixture", node_type="automation-hitl",
        node_data={"config": {"operation": operation, **CONFIGS[operation], **config},
            "credentials": {"credential_type": "hitl_api_key", "api_key": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONFIGS)
async def test_published_routes_bodies_and_response_examples(monkeypatch, operation):
    # The loop-list request endpoint has no standalone full response example.
    body = FIXTURES[operation]["body"] if operation in FIXTURES else {
        "error": False, "msg": "Loop requests retrieved successfully",
        "data": {"loop_id": LOOP, "requests": [], "count": 0}}
    status = 201 if operation in {"create_loop", "create_request"} else 200
    requests = transport(monkeypatch, httpx.Response(status, json=body))
    output = await node(operation).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert (request.method, request.url.path) == EXPECTED[operation]
    assert request.url.host == "api.hitl.sh" and not request.url.query
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert output["status"] == "success" and output["http_status"] == status
    assert TOKEN not in str(output)
    if request.method in {"POST", "PUT"}:
        sent = json.loads(request.content)
        assert not {"operation", "loop_id", "request_id", "user_id"} & set(sent)
        if operation == "create_request":
            assert sent == {k: v for k, v in CONFIGS[operation].items() if k != "loop_id"} | {
                "processing_type": "time-sensitive", "type": "markdown", "priority": "medium", "platform": "api"}
        elif operation == "update_loop":
            assert sent == {"description": "Updated moderation"}
        elif operation == "add_feedback":
            assert sent == {"feedback": {"rating": 5}}
    else:
        assert not request.content
    if operation == "create_loop":
        assert "qr_code_base64" not in output["data"]
        assert output["data"]["qr_code_url"] == body["data"]["qr_code_url"]
    else:
        assert output["data"] == body["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_provider_rejections_redact_token_and_never_retry(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, json={"error": True, "msg": "Rejected " + TOKEN},
        headers={"Location": "https://example.test/collect"}))
    output = await node("test_api_key").execute({})
    assert output["status"] == "error" and output["http_status"] == status
    assert output["error"] == "Rejected [redacted]" and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"error": True, "msg": "Not accepted"}, {"error": False},
    {"error": False, "data": []}])
async def test_malformed_or_unsuccessful_envelope_is_never_success(monkeypatch, body):
    transport(monkeypatch, httpx.Response(200, json=body))
    with pytest.raises(ValueError, match="successful data envelope"):
        await node("test_api_key").execute({})


def test_schema_rejects_path_injection_and_required_dependencies():
    for config in [{"operation": "get_loop", "loop_id": "../test"},
        {"operation": "get_request", "request_id": "x"},
        {"operation": "update_loop", "loop_id": LOOP},
        {"operation": "create_request", **CONFIGS["create_request"], "timeout_seconds": None},
        {"operation": "create_request", **CONFIGS["create_request"], "type": "image"},
        {"operation": "create_loop", "name": "", "icon": "shield"}]:
        with pytest.raises(ConfigValidationError):
            native.HitlNode.parse_config({"config": config})


def test_manual_credential_default_and_secret_widget():
    credential = native.HitlAPIKeyCredential(api_key=" " + TOKEN + " ")
    assert credential.credential_type == "hitl_api_key" and credential.api_key == TOKEN
    assert native.HitlAPIKeyCredential.model_json_schema()["properties"]["api_key"]["ui:widget"] == "password"
    for value in ["Bearer " + TOKEN, "https://my.hitl.sh/key", "your_api_key_here", "key\nheader"]:
        with pytest.raises(ValidationError):
            native.HitlAPIKeyCredential(api_key=value)
