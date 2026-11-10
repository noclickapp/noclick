"""Wire behavior against the provider's pinned Public API 1.10.1 contract."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes.core.registry import NodeFactory
from nodes.mentortools_node import MentortoolsAPIKeyCredential, MentortoolsNode, ROUTES

KEY = "unit-test-private-mentortools-key"
RESULTS = json.loads((Path(__file__).parent / "fixtures/mentortools/success-results.json").read_text())["results"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **fields):
    return NodeFactory.create_node(node_id="mentortools-test", node_type="automation-mentortools",
        node_data={"config": {"operation": operation, **fields}, "credentials": {"api_key": KEY}})


def mock_api(monkeypatch, body, status=200):
    calls = []
    async def handle(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as api:
            yield api
    monkeypatch.setattr("nodes.mentortools_node.guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fields,method,path,body", [
    ("list_courses", {"archived": True, "limit": 25, "offset": 50}, "GET", "/courses/v1/", None),
    ("create_course", {"title": "Onboarding"}, "POST", "/courses/v1/", {"title": "Onboarding", "is_active": False, "is_secret": False, "is_archived": False, "is_displayed_in_app": False, "is_offline_downloadable": False}),
    ("update_course", {"course_id": 42, "is_active": False}, "PATCH", "/courses/v1/42", {"is_active": False}),
    ("create_module", {"course_id": 42, "title": "Getting started", "available_at": 7}, "POST", "/courses/v1/42/modules", {"title": "Getting started", "available_at": 7, "mandatory": False, "is_published": False, "is_active": False}),
    ("update_lesson", {"lesson_id": 80, "module_id": 23, "order": 2}, "PATCH", "/courses/v1/lessons/80", {"module_id": 23, "order": 2}),
    ("delete_lesson", {"lesson_id": 80}, "DELETE", "/courses/v1/lessons/80", None),
    ("list_files", {"parent_folder_id": 10, "file_type": "video"}, "GET", "/mediastorage/v1/files", None),
    ("create_folder", {"name": "Teaching", "parent_folder_id": 10}, "POST", "/mediastorage/v1/folders", {"name": "Teaching", "parent_folder_id": 10}),
    ("record_payment", {"id": "order-101", "marketplace_buyer": {"email": "student@example.com"}, "course_ids": [42], "transaction": {"id": "pay-101", "amount": 10.0}}, "POST", "/orders/v1/ipn/payment", {"id": "order-101", "marketplace_buyer": {"email": "student@example.com"}, "course_ids": [42], "transaction": {"id": "pay-101", "amount": 10.0}, "send_email": False, "billing_type": "single_payment"}),
    ("record_refund", {"id": "order-101", "transaction": {"id": "refund-101", "amount": 10.0}}, "POST", "/orders/v1/ipn/refund", {"id": "order-101", "transaction": {"id": "refund-101", "amount": 10.0}}),
])
async def test_wire(monkeypatch, operation, fields, method, path, body):
    result = RESULTS[operation]
    calls = mock_api(monkeypatch, {"done": True, "result": result, "error": None})
    output = await node(operation, **fields).execute({})
    assert output["data"] == result
    assert len(calls) == 1
    req = calls[0]
    assert req.method == method
    assert req.url.host == "app.mentortools.com"
    assert req.url.path == "/public_api" + path
    assert req.headers["Authorization"] == "Bearer " + KEY
    if body is not None:
        assert json.loads(req.content) == body
    else:
        assert req.content == b""
    if operation == "list_courses":
        assert dict(req.url.params) == {"archived": "true", "limit": "25", "offset": "50"}
    if operation == "list_files":
        assert dict(req.url.params) == {"parent_folder_id": "10", "file_type": "video", "limit": "15", "offset": "0"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 403, 422, 500])
async def test_provider_rejection(monkeypatch, status):
    mock_api(monkeypatch, {"done": False, "result": None, "error": "Permission denied " + KEY}, status)
    output = await node("list_courses").execute({})
    assert output["status"] == "error"
    assert output["error"] == "Permission denied [redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"done": "true", "result": []}, {"done": True}, {"done": True, "result": [], "error": "bad"}, {"done": True, "result": {}}])
async def test_unconfirmed_response(monkeypatch, body):
    mock_api(monkeypatch, body)
    with pytest.raises(ValueError):
        await node("list_courses").execute({})


@pytest.mark.asyncio
async def test_identity_omits_key_metadata(monkeypatch):
    mock_api(monkeypatch, {"done": True, "result": {"api_key": {"name": KEY}, "portal": {"id": 7, "domain": "academy.example.com", "secret": KEY}, "owner": {"id": 9, "email": "teacher@example.com"}}})
    result = await node("get_account").execute({})
    assert result["data"] == {"portal": {"id": 7, "domain": "academy.example.com"}, "owner": {"id": 9, "email": "teacher@example.com"}}
    assert KEY not in json.dumps(result)


@pytest.mark.parametrize("operation,fields", [
    ("list_courses", {"limit": 101}), ("list_courses", {"offset": -1}),
    ("update_course", {"course_id": 4}), ("update_module", {"module_id": 3}),
    ("update_lesson", {"lesson_id": 2}),
    ("create_module", {"course_id": 4, "title": "M", "available_at": 36501}),
    ("record_payment", {"id": "x", "course_ids": [1], "marketplace_buyer": {"email": "a@example.com"}, "billing_type": "subscription"}),
])
def test_invalid_config(operation, fields):
    assert MentortoolsNode.validate_config({"config": {"operation": operation, **fields}, "credentials": {"api_key": KEY}})["valid"] is False


def test_manual_credential_default():
    cred = MentortoolsAPIKeyCredential(api_key=KEY)
    assert cred.credential_type == "mentortools_api_key"
    assert len(ROUTES) == 25


@pytest.mark.parametrize("key", ["https://example.com/key", "Bearer secret", "key\nheader"])
def test_secret_validation(key):
    with pytest.raises(ValidationError):
        MentortoolsAPIKeyCredential(api_key=key)
