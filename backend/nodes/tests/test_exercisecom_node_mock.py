"""Exercise the native node against synthetic Modern API responses; no live account."""
import json

import httpx
import pytest
from pydantic import ValidationError
from nodes import exercisecom_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-exercisecom-personal-token"


def node(config, **credential):
    return NodeFactory.create_node(node_id="exercisecom-test", node_type="automation-exercisecom",
        node_data={"config": config, "credentials": {
            "credential_type": "exercisecom_token", "api_token": TOKEN, **credential}})


def transport(monkeypatch, response):
    calls = []
    def reply(request):
        calls.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


# Independent expectations pin each public operation to one method and endpoint.
CASES = [
    ({"operation": "list_calendar", "start_date": "2026-05-20", "end_date": "2026-05-21"}, "GET", "/calendar", {"calendar_item": [], "meta": {"total": 0}}),
    ({"operation": "schedule_workout", "workout_id": 42, "date": "2026-05-20"}, "POST", "/calendar/workouts", {"type": "workout", "id": 43}),
    ({"operation": "move_workout", "id": 43, "date": "2026-05-21"}, "PATCH", "/calendar/workouts/43", {"type": "workout", "id": 43}),
    ({"operation": "remove_workout", "id": 43}, "DELETE", "/calendar/workouts/43", None),
    ({"operation": "list_packages"}, "GET", "/packages", {"package": []}),
    ({"operation": "list_user_packages"}, "GET", "/user_packages", {"user_package": []}),
    ({"operation": "list_invoices"}, "GET", "/invoices", {"invoice": []}),
    ({"operation": "list_visits"}, "GET", "/visits", {"visit": []}),
    ({"operation": "get_visit_summary", "start_date": "2026-05-20T00:00:00Z", "end_date": "2026-05-21T00:00:00Z"}, "GET", "/visit_summary", {"user_id": 7, "counts": []}),
    ({"operation": "get_visit_totals"}, "GET", "/visit_totals", {"user_id": 7, "this_week": 1, "this_month": 4, "all_time": 50}),
    ({"operation": "get_conversation_summary"}, "GET", "/conversations/summary", {"unread": 1, "messaging_available": True}),
    ({"operation": "get_user", "id": 7}, "GET", "/users/7", {"id": 7, "name": "Jane"}),
    ({"operation": "update_user", "id": 7, "first_name": "Jane"}, "PATCH", "/users/7", {"id": 7, "first_name": "Jane"}),
    ({"operation": "list_tasks"}, "GET", "/staff/tasks", {"task": [{"id": 8, "title": "Call member"}]}),
    ({"operation": "create_task", "title": "Call member", "due_at": "2026-05-21T10:00:00Z", "assigned_to_id": 9}, "POST", "/staff/tasks", {"id": 8, "title": "Call member"}),
    ({"operation": "get_task", "id": 8}, "GET", "/staff/tasks/8", {"id": 8, "title": "Call member"}),
    ({"operation": "update_task", "id": 8, "status": "complete"}, "PATCH", "/staff/tasks/8", {"id": 8, "status": "complete"}),
    ({"operation": "delete_task", "id": 8}, "DELETE", "/staff/tasks/8", {"id": 8, "status": "open"}),
    ({"operation": "list_assignees"}, "GET", "/staff/assignees", {"assignee": [{"id": 9, "name": "Trainer"}]}),
    ({"operation": "list_task_audit_logs"}, "GET", "/staff/task_audit_logs", {"task_audit_log": []}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_exercisecom_factory_one_published_operation(monkeypatch, config, method, path, body):
    calls = transport(monkeypatch, (lambda _: httpx.Response(204)) if body is None else body)
    out = await node(config).execute({})
    assert out["status"] == "success", out
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.exercise.com"
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert request.headers["x-api-version"] == "2026-05-20"
    assert TOKEN not in str(out)
    if method == "GET":
        assert not request.content
    elif config["operation"] == "create_task":
        assert json.loads(request.content) == {"task": {"title": "Call member", "due_at": "2026-05-21T10:00:00Z", "assigned_to_id": 9}}
    elif config["operation"] == "update_task":
        assert json.loads(request.content) == {"task": {"status": "complete"}}
    elif config["operation"] == "update_user":
        assert json.loads(request.content) == {"first_name": "Jane"}
    elif config["operation"] == "schedule_workout":
        assert json.loads(request.content) == {"workout_id": 42, "date": "2026-05-20"}
    elif config["operation"] == "move_workout":
        assert json.loads(request.content) == {"date": "2026-05-21"}


@pytest.mark.asyncio
async def test_exercisecom_pagination_filters_and_tenant_host(monkeypatch):
    pagination = {"limit": 10, "total_count": 20, "has_next_page": True,
                  "has_previous_page": False, "cursors": {"after": "opaque+/=cursor", "before": None}}
    calls = transport(monkeypatch, {"invoice": [], "meta": {"pagination": pagination}})
    out = await node({"operation": "list_invoices", "overdue": False, "user_id": 7, "limit": 10,
                      "after": "previous+/=cursor", "status": "paid,open"}, api_host="train.demoexercise.com").execute({})
    assert dict(calls[0].url.params) == {"overdue": "false", "user_id": "7", "limit": "10", "after": "previous+/=cursor", "status": "paid,open"}
    assert calls[0].url.host == "train.demoexercise.com" and len(calls) == 1
    assert out["pagination"] == pagination and out["next_after"] == "opaque+/=cursor"


@pytest.mark.asyncio
async def test_exercisecom_explicit_null_clears_only_supplied_profile_field(monkeypatch):
    calls = transport(monkeypatch, {"id": 7, "phone_number": None})
    await node({"operation": "update_user", "id": 7, "phone_number": None, "uses_metric": False}).execute({})
    assert json.loads(calls[0].content) == {"phone_number": None, "uses_metric": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429, 500])
async def test_exercisecom_provider_errors_preserve_words_and_redact(monkeypatch, status):
    calls = transport(monkeypatch, lambda _: httpx.Response(status, json={"success": False, "error": "invalid_access_token", "details": {"token": [TOKEN]}}))
    out = await node({"operation": "list_tasks"}).execute({})
    assert out["status"] == "error" and out["http_status"] == status
    assert out["error"] == "invalid_access_token" and TOKEN not in str(out) and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(302, headers={"Location": "https://evil.example"}),
    httpx.Response(200, text="<html>login</html>", headers={"content-type": "text/html"}),
    httpx.Response(200, json={"success": False, "error": "platform_not_authorized"}),
    httpx.Response(200, json={"task": {}}), httpx.Response(200, json=[]),
    httpx.Response(200, content='{"task":[{"id":NaN}]}', headers={"content-type": "application/json"})])
async def test_exercisecom_redirect_html_error_and_invalid_collections(monkeypatch, response):
    calls = transport(monkeypatch, lambda _: response)
    out = await node({"operation": "list_tasks"}).execute({})
    assert out["status"] == "error" and len(calls) == 1


@pytest.mark.asyncio
async def test_exercisecom_write_timeout_is_not_retried(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)
    calls = transport(monkeypatch, timeout)
    out = await node({"operation": "update_task", "id": 8, "status": "complete"}).execute({})
    assert out["status"] == "error" and out["outcome_unknown"] and len(calls) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_user", "id": "../sessions"},
    {"operation": "get_task", "id": 0},
    {"operation": "list_invoices", "after": "a", "before": "b"},
    {"operation": "list_tasks", "limit": 101},
    {"operation": "list_visits", "user_id": 7, "all_members": True},
    {"operation": "list_calendar", "start_date": "2026-05-21", "end_date": "2026-05-20"},
    {"operation": "list_calendar", "start_date": "2026-01-01", "end_date": "2026-12-31"},
    {"operation": "update_user", "id": 7, "email": "new@example.com"},
    {"operation": "update_task", "id": 8},
    {"operation": "update_task", "id": 8, "due_at": None},
    {"operation": "update_user", "id": 7, "privacy_level": None},
    {"operation": "create_task", "title": "Call member", "due_at": "2026-05-20", "assigned_to_id": 9},
])
def test_exercisecom_invalid_config_rejected_before_request(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


@pytest.mark.parametrize("changes", [{"api_host": "evil.example"}, {"api_host": "api.exercise.com.evil.example"},
    {"api_token": "Bearer secret"}, {"api_token": "https://example.com/token"}])
def test_exercisecom_manual_credential_shape(changes):
    with pytest.raises((ValueError, ValidationError)):
        native.ExercisecomTokenCredential(api_token=changes.get("api_token", TOKEN), **{k:v for k,v in changes.items() if k != "api_token"})


def test_exercisecom_manual_type_default_and_account_evidence():
    credential = native.ExercisecomTokenCredential(api_token=TOKEN)
    assert credential.credential_type == "exercisecom_token"
    evidence = native.ExercisecomNode.connection_evidence
    assert evidence.operation == "list_tasks" and evidence.proves == "account"
