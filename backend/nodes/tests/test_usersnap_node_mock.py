"""Exercise Usersnap through discovery and the real HTTP request builder.

Provider-published v0.1 responses pin the parser; failures and filter/body
assertions guard against silent authentication, submission and routing errors.
"""
import json
from pathlib import Path

import httpx
import pytest

from nodes import usersnap_node as native
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential

TOKEN = "synthetic-usersnap-token-42"
PROJECT = "03e7f4ec-7fa5-4783-b4b1-2da96ab2ba69"
KEY = "79baa410-b3dd-4e03-86e5-8849d841473e"
RESPONSES = json.loads((Path(__file__).parent / "fixtures/usersnap/responses.json").read_text())["responses"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="usersnap-test", node_type="automation-usersnap",
        node_data={"config": config, "credentials": {"credential_type": "usersnap_api_token", "api_token": TOKEN}})


def transport(monkeypatch, body, status=200):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,operation_id", [
    ({"operation": "list_projects"}, "GET", "/projects", "getProjects"),
    ({"operation": "get_project_metrics", "project_api_key": KEY}, "GET", f"/projects/{KEY}/metrics", "getProjectMetrics"),
    ({"operation": "list_project_assignees", "project_api_key": KEY}, "GET", f"/projects/{KEY}/assignees", "getProjectAssignees"),
    ({"operation": "submit_feedback", "project_api_key": KEY, "visitor": "customer@example.com", "comment": "I like the new feature", "rating": 9}, "POST", f"/projects/{KEY}/feedbacks", "submitFeedback"),
    ({"operation": "list_feedback", "project_id": PROJECT}, "GET", f"/projects/{PROJECT}/feedbacks", "getProjectFeedbacks"),
    ({"operation": "count_feedback", "project_id": PROJECT}, "GET", f"/projects/{PROJECT}/feedbacks/count", "getProjectFeedbacksCount"),
    ({"operation": "filter_feedback", "project_id": PROJECT, "query": [{"filter_type": "state", "operator": "eq", "value": "done"}]}, "POST", f"/projects/{PROJECT}/feedbacks/filter", "filterProjectFeedbacks"),
    ({"operation": "count_filtered_feedback", "project_id": PROJECT}, "POST", f"/projects/{PROJECT}/feedbacks/filter/count", "filterProjectFeedbacksCount"),
    ({"operation": "find_feedback_by_email", "project_id": PROJECT, "email": "someone@somewhere.com"}, "POST", f"/projects/{PROJECT}/feedbacks/filter", "filterProjectFeedbacks"),
    ({"operation": "find_feedback_by_state", "project_id": PROJECT, "state": "done"}, "POST", f"/projects/{PROJECT}/feedbacks/filter", "filterProjectFeedbacks"),
])
async def test_published_routes_and_response_examples(monkeypatch, config, method, path, operation_id):
    body = RESPONSES.get(operation_id, {"status": True, "data": {"users": [{"user_id": "fixture-user", "first_name": "Alex"}]}})
    calls = transport(monkeypatch, body, 201 if operation_id == "submitFeedback" else 200)
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert result["data"] == body["data"]
    assert len(calls) == 1
    assert calls[0].method == method and calls[0].url.path == "/v0.1" + path
    assert calls[0].url.host == "platform.usersnap.com" and not calls[0].url.query
    assert calls[0].headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(result)
    if method == "GET":
        assert not calls[0].content
    else:
        payload = json.loads(calls[0].content)
        assert "operation" not in payload and "project_id" not in payload and "project_api_key" not in payload
        if config["operation"] == "find_feedback_by_email":
            assert payload == {"query": [{"filter_type": "email", "operator": "eq", "value": "someone@somewhere.com"}]}
        if config["operation"] == "find_feedback_by_state":
            assert payload == {"query": [{"filter_type": "state", "operator": "eq", "value": "done"}]}


@pytest.mark.asyncio
async def test_submission_nested_data_and_explicit_unassignment(monkeypatch):
    cfg = {"operation": "submit_feedback", "project_api_key": KEY, "client": {"url": "https://example.com", "screen_width": 1920, "screen_height": 1080},
           "attachments": [{"content": "aGVsbG8=", "filename": "hello.txt", "mime_type": "text/plain"}]}
    calls = transport(monkeypatch, RESPONSES["submitFeedback"], 201)
    assert (await node(cfg).execute({}))["feedback_id"]
    body = json.loads(calls[0].content)
    assert body == {"client": cfg["client"], "attachments": cfg["attachments"]}
    # The endpoint description explicitly documents null as unassigned.
    calls = transport(monkeypatch, RESPONSES["submitFeedback"], 201)
    await node({**cfg, "assignee": None}).execute({})
    assert json.loads(calls[0].content)["assignee"] is None


@pytest.mark.asyncio
async def test_filters_and_sort_preserve_documented_types(monkeypatch):
    cfg = {"operation": "filter_feedback", "project_id": PROJECT,
           "query": [{"filter_type": "created_at", "operator": "gte", "value": "2023-03-22T00:00:00Z"}],
           "order_by": {"direction": "asc", "order_by_type": "created_at"}}
    calls = transport(monkeypatch, RESPONSES["filterProjectFeedbacks"])
    result = await node(cfg).execute({})
    assert result["status"] == "success"
    assert json.loads(calls[0].content) == {"query": cfg["query"], "order_by": cfg["order_by"]}
    assert result["next"] == RESPONSES["filterProjectFeedbacks"]["data"]["next"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 400, 401, 403, 429, 500])
async def test_provider_error_envelopes_are_rejected_verbatim(monkeypatch, status):
    calls = transport(monkeypatch, {"status": False, "msg": "Authorization failed " + TOKEN}, status)
    result = await node({"operation": "list_projects"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Authorization failed [redacted]" and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body,status", [({}, 200), ({"status": True, "data": {}}, 200),
    ({"status": True, "data": {"projects": None}}, 200), ({"status": True, "data": {"projects": []}}, 302)])
async def test_malformed_and_redirect_responses_do_not_prove_connection(monkeypatch, body, status):
    calls = transport(monkeypatch, body, status)
    assert (await node({"operation": "list_projects"}).execute({}))["status"] == "error"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_empty_projects_are_successful_and_more_pages_remain_visible(monkeypatch):
    transport(monkeypatch, {"status": True, "data": {"projects": [], "has_more": True, "count": 0}})
    result = await node({"operation": "list_projects"}).execute({})
    assert result["status"] == "success" and result["items"] == [] and result["has_more"] is True


def test_manual_connect_defaults_and_field_validation():
    shaped, errors, resolved = shape_credential("usersnap_api_token", {"api_token": TOKEN})
    assert resolved == ("automation-usersnap", native.UsersnapTokenCredential) and not errors
    assert shaped == {"api_token": TOKEN}
    assert native.UsersnapTokenCredential.model_validate(shaped).credential_type == "usersnap_api_token"
    for value in ["Bearer abc", "https://example.com/token", "abc\r\nHeader: value"]:
        with pytest.raises(ValueError):
            native.UsersnapTokenCredential(api_token=value)
    for config in [{"operation": "list_feedback", "project_id": "../projects"},
        {"operation": "get_project_metrics", "project_id": PROJECT},
        {"operation": "filter_feedback", "project_id": PROJECT, "query": [{"filter_type": "wrong", "operator": "eq", "value": "done"}]},
        {"operation": "submit_feedback", "project_api_key": KEY, "attachments": [{"content": "not base64!", "filename": "a", "mime_type": "text/plain"}]}]:
        with pytest.raises(ValueError):
            native.UsersnapNode.parse_config({"config": config, "credentials": {"api_token": TOKEN}})
