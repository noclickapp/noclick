"""What a canvas reads and does about a workflow's runs (``Workflow.stop_run``, ``run_counts``, ``latest_outputs``,
``Step.preview_expression``, ``Step.clear_state``, ``noclick.step_output_shape``): what each call sends and how it
reads the answer, against the mocked transport."""

import json

import noclick as nc
from platform_helpers import USER_ID

RUN = {"object": "workflow_run", "id": "run_1", "workflow_id": "wf_1", "status": "failed", "inputs": {},
       "outputs": {}, "error": {"type": "canceled", "message": "The operation was canceled."}, "source": "api",
       "user_id": None, "operation_id": "op_1", "started_at": "2026-11-21T10:00:00Z",
       "finished_at": "2026-11-21T10:00:04Z", "steps": [
           {"id": "hook", "name": "Hook", "status": "succeeded", "error": None, "output": {"order_id": "o_1"},
            "withheld": []},
           {"id": "note", "name": "Summary", "status": "running", "error": None, "output": None, "withheld": []}]}


def test_stopping_a_run_answers_it_as_it_stands(api, client):
    route = api.post("/v1/workflows/wf_1/runs/run_1/stop").respond(json=RUN)
    stopped = nc.Workflow.from_id("wf_1").stop_run("run_1")
    assert route.called and route.calls.last.request.content in (b"", None)
    assert (stopped.status, stopped.error, stopped.operation_id) == ("failed", "The operation was canceled.", "op_1")
    assert [(s.id, s.status) for s in stopped.steps] == [("hook", "succeeded"), ("note", "running")]
    with nc.as_user(USER_ID):
        nc.Workflow.from_id("wf_1").stop_run("run_1")
    assert route.calls.last.request.headers["NoClick-User"] == USER_ID


def test_run_counts_read_every_status_and_take_a_user_filter(api, client):
    route = api.get("/v1/workflows/wf_1/runs/counts").respond(json={
        "object": "run_counts", "workflow_id": "wf_1", "total": 3, "by_status": {"succeeded": 2, "failed": 1},
        "by_source": {"api": 2, "schedule": 1}})
    counts = nc.Workflow.from_id("wf_1").run_counts()
    assert isinstance(counts, nc.WorkflowRunCounts)
    assert (counts.total, counts.by_status, counts.by_source) == (
        3, {"running": 0, "succeeded": 2, "failed": 1}, {"api": 2, "schedule": 1})
    assert "user_id" not in route.calls.last.request.url.params
    nc.Workflow.from_id("wf_1").run_counts(user_filter=nc.ALL_USERS)
    request = route.calls.last.request
    assert request.url.params["user_id"] == "all" and "NoClick-User" not in request.headers


def test_latest_outputs_name_what_they_left_out(api, client):
    route = api.get("/v1/workflows/wf_1/outputs").respond(json={
        "object": "step_outputs", "workflow_id": "wf_1", "outputs": {"hook": {"order_id": "o_9"}},
        "withheld": {"hook": ["_webhook.headers.Authorization"]}, "full": True, "truncated": []})
    intake = nc.Workflow.from_id("wf_1")
    latest = intake.latest_outputs(steps=[intake.step("hook"), "note"], full=True)
    params = route.calls.last.request.url.params
    assert (params["steps"], params["full"]) == ("hook,note", "true")
    assert (latest.outputs, latest.withheld, latest.full, latest.truncated) == (
        {"hook": {"order_id": "o_9"}}, {"hook": ["_webhook.headers.Authorization"]}, True, [])
    intake.latest_outputs()
    assert dict(route.calls.last.request.url.params) == {}


def test_an_expression_previews_against_what_was_stored_or_samples(api, client):
    route = api.post("/v1/workflows/wf_1/steps/note/expression").respond(json={
        "object": "expression_preview", "workflow_id": "wf_1", "step_id": "note", "ok": True, "kind": "string",
        "keys": None, "preview": "o_9", "preview_tokens": [{"t": "s", "v": "o_9"}]})
    note = nc.Workflow.from_id("wf_1").step("note")
    found = note.preview_expression("$json.order_id")
    assert json.loads(route.calls.last.request.content) == {"expression": "$json.order_id"}
    assert (found.ok, found.kind, found.keys, found.preview, found.error) == (True, "string", None, "o_9", None)
    note.preview_expression("$vars.region", samples={"vars": {"region": "eu"}})
    assert json.loads(route.calls.last.request.content) == {"expression": "$vars.region",
                                                            "samples": {"vars": {"region": "eu"}}}
    route.respond(json={"ok": False, "error": "Cannot read properties of undefined"})
    failed = note.preview_expression("$('hook').nope.deeper")
    assert (failed.ok, failed.error, failed.keys) == (False, "Cannot read properties of undefined", None)


def test_clearing_a_steps_state_acts_for_the_account(api, client):
    route = api.post("/v1/workflows/wf_1/steps/rss/clear_state").respond(json={
        "object": "step_state", "workflow_id": "wf_1", "step_id": "rss", "cleared": True, "state_rows_deleted": 1,
        "conversations_deleted": 0})
    with nc.as_user(USER_ID):
        cleared = nc.Workflow.from_id("wf_1").step("rss").clear_state()
    assert "NoClick-User" not in route.calls.last.request.headers
    assert (cleared.step_id, cleared.state_rows_deleted, cleared.conversations_deleted) == ("rss", 1, 0)


def test_a_step_types_output_shape_is_the_accounts_own(api, client):
    route = api.get("/v1/step_types/automation-hubspot/output_shape").respond(json={
        "object": "output_shape", "type": "automation-hubspot", "operation": "get_contact",
        "shape": {"id": "integer"}, "suggested_refs": None})
    found = nc.step_output_shape("automation-hubspot", operation="get_contact")
    assert route.calls.last.request.url.params["operation"] == "get_contact"
    assert (found.type, found.operation, found.shape, found.suggested_refs) == (
        "automation-hubspot", "get_contact", {"id": "integer"}, None)
    nc.step_output_shape("automation-hubspot")
    assert "operation" not in route.calls.last.request.url.params
