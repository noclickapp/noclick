"""What a canvas reads and does about a workflow's runs (``Workflow.stop_run``, ``run_counts``, ``latest_outputs``,
``Step.preview_expression``, ``Step.clear_state``, ``noclick.step_output_shape``): what each call sends and how it
reads the answer, against the mocked transport."""

import json

import httpx

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


def test_runs_narrow_by_how_a_run_started_what_started_it_whether_it_waits_and_its_errors_text(api, client):
    waits = {**RUN, "id": "run_2", "status": "running", "error": None, "source": "trigger", "trigger": "email",
             "waiting_on": "approval", "steps": []}
    route = api.get("/v1/workflows/wf_1/runs").mock(side_effect=[
        httpx.Response(200, json={"object": "list", "data": [waits], "next_cursor": None}),
        httpx.Response(200, json={"object": "list", "data": [RUN], "next_cursor": None})])
    [run] = nc.Workflow.from_id("wf_1").runs(status="running", source=["trigger", "schedule"], trigger="email",
                                             waiting=True, search="refused", limit=5)
    sent = route.calls.last.request.url.params
    assert [sent[name] for name in ("status", "source", "trigger", "waiting", "search")] == [
        "running", "trigger,schedule", "email", "true", "refused"]
    assert (run.status, run.waiting_on, run.source, run.trigger) == ("running", "approval", "trigger", "email")
    # A run from code names no trigger and, once it ended, waits on nothing; nothing asked narrows nothing.
    [ended] = nc.Workflow.from_id("wf_1").runs(waiting=False)
    sent = route.calls.last.request.url.params
    assert (ended.waiting_on, ended.trigger, sent["waiting"]) == (None, None, "false")
    assert not {"source", "trigger", "search", "status"} & set(sent.keys())


def test_run_counts_read_every_status_and_take_a_user_filter(api, client):
    route = api.get("/v1/workflows/wf_1/runs/counts").respond(json={
        "object": "run_counts", "workflow_id": "wf_1", "total": 3, "by_status": {"succeeded": 2, "failed": 1},
        "waiting": 1, "by_source": {"api": 2, "schedule": 1}, "by_trigger": {"email": 1}})
    counts = nc.Workflow.from_id("wf_1").run_counts()
    assert isinstance(counts, nc.WorkflowRunCounts)
    assert (counts.total, counts.by_status, counts.by_source) == (
        3, {"running": 0, "succeeded": 2, "failed": 1}, {"api": 2, "schedule": 1})
    assert (counts.waiting, counts.by_trigger) == (1, {"email": 1})
    assert "user_id" not in route.calls.last.request.url.params
    nc.Workflow.from_id("wf_1").run_counts(user_filter=nc.ALL_USERS)
    request = route.calls.last.request
    assert request.url.params["user_id"] == "all" and "NoClick-User" not in request.headers


def test_latest_outputs_name_what_they_left_out_and_how_each_steps_last_run_ended(api, client):
    route = api.get("/v1/workflows/wf_1/outputs").respond(json={
        "object": "step_outputs", "workflow_id": "wf_1", "outputs": {"hook": {"order_id": "o_9"}},
        "withheld": {"hook": ["_webhook.headers.Authorization"]}, "full": True, "truncated": [],
        "last_runs": {"hook": {"status": "succeeded", "finished_at": "2026-11-21T10:00:04+00:00", "error": None},
                      "note": {"status": "failed", "finished_at": None, "error": "the shop answered 500"}}})
    intake = nc.Workflow.from_id("wf_1")
    latest = intake.latest_outputs(steps=[intake.step("hook"), "note"], full=True)
    params = route.calls.last.request.url.params
    assert (params["steps"], params["full"]) == ("hook,note", "true")
    assert (latest.outputs, latest.withheld, latest.full, latest.truncated) == (
        {"hook": {"order_id": "o_9"}}, {"hook": ["_webhook.headers.Authorization"]}, True, [])
    assert latest.last_runs["note"] == nc.StepLastRun("failed", None, "the shop answered 500")
    hook = latest.last_runs["hook"]
    assert (hook.status, hook.finished_at.isoformat(), hook.error) == ("succeeded", "2026-11-21T10:00:04+00:00", None)
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


def test_a_step_types_choices_are_listed_for_no_step_through_the_named_connection(api, client):
    body = {"object": "step_type_options", "type": "automation-slack", "field": "channel",
            "options": [{"value": "C1", "label": "#general", "metadata": None}], "next_page_token": "2",
            "withheld": []}
    route = api.post("/v1/step_types/automation-slack/options").respond(json=body)
    page = nc.step_type_options("automation-slack", "channel", connection="credential:c1", workflow_id="wf_1")
    assert json.loads(route.calls.last.request.content) == {
        "field": "channel", "connection": "credential:c1", "workflow_id": "wf_1"}
    assert (page.field, [o["label"] for o in page.options], page.next_page_token) == ("channel", ["#general"], "2")


def test_readiness_evidence_a_step_read_alone_and_workflows_by_credential(api, client):
    api.get("/v1/workflows/wf_1/readiness").respond(json={
        "object": "workflow_readiness", "workflow_id": "wf_1", "status": "input_observed", "meaning": "Seen.",
        "issues": [], "warnings": [], "unverified": [], "registered_steps": ["hook"], "deadline_watches": [],
        "alarm_steps": [], "destinations": [],
        "observations": [{"step": "hook", "at": "2026-11-21T10:00:00Z", "trigger": "webhook", "run_status": "succeeded"}]})
    check = nc.Workflow.from_id("wf_1").check_readiness()
    assert (check.status, check.observations[0]["run_status"], check.registered_steps) == (
        "input_observed", "succeeded", ["hook"])
    api.get("/v1/workflows/wf_1/steps/hook").respond(json={
        "object": "workflow_step", "workflow_id": "wf_1", "version": 3,
        "step": {"id": "hook", "type": "trigger-webhook", "config": {"label": "Hook"}}, "withheld": ["secret"]})
    step = nc.Workflow.from_id("wf_1").get_step("hook")
    assert (step.type, step.withheld) == ("trigger-webhook", ["secret"])
    listed = api.get("/v1/workflows").respond(json={"object": "list", "data": [], "next_cursor": None})
    nc.Workflow.list(credential_id="cred_1")
    assert listed.calls.last.request.url.params["credential_id"] == "cred_1"


def test_warm_sandboxes_template_and_a_proposals_verdict_read_and_send_what_the_canvas_does(api, client):
    api.get("/v1/workflows/wf_1/sandboxes").respond(json={
        "object": "workflow_sandboxes", "workflow_id": "wf_1", "steps": {"helper": 2}})
    api.get("/v1/workflows/wf_1/template").respond(json={
        "object": "workflow_template", "workflow_id": "wf_1", "published": False, "template": None,
        "draft": {"title": "Order intake", "description": "Files each order."}})
    decide = api.post("/v1/workflows/wf_1/steps/helper/conversations/__interface_chat__/decisions").respond(json={
        "object": "step_proposal_decision", "conversation": "__interface_chat__", "proposal_id": "p1",
        "decision": "dismissed"})
    intake = nc.Workflow.from_id("wf_1")
    assert intake.warm_sandboxes() == {"helper": 2}
    listing = intake.template()
    assert isinstance(listing, nc.WorkflowTemplate)
    assert (listing.published, listing.public_url, listing.draft_title) == (False, None, "Order intake")
    intake.step("helper").decide_proposal("__interface_chat__", "p1", "dismissed")
    assert json.loads(decide.calls.last.request.content) == {"proposal_id": "p1", "decision": "dismissed"}
