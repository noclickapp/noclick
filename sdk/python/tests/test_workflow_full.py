"""A workflow read in full, paused, resumed, restored and published, and one run with its steps, against the
mocked transport: the routes and bodies each call sends, and what it parses."""

import noclick as nc
from platform_helpers import body, operation

FULL = {
    "object": "workflow", "id": "wf_1", "name": "Order intake", "description": None, "access": "owner",
    "inputs": {"type": "object"}, "app_url": "https://noclick.com/dashboard?tab=workflows&workflow=wf_1",
    "step_types": ["trigger-webhook", "automation-linear"],
    "created_at": "2026-10-12T10:00:00Z", "updated_at": "2026-10-12T10:00:00Z",
    "steps": [
        {"id": "hook", "name": "Hook", "type": "trigger-webhook", "operation": None, "enabled": True,
         "settings": {"http_method": "POST"}, "connection": None,
         "trigger": {"error": None, "paused_reason": None, "next_run": None}},
        {"id": "ticket", "name": "Ticket", "type": "automation-linear", "operation": "create_issue", "enabled": True,
         "settings": {"title": "Order"}, "connection": {"attached": False, "healthy": None, "hint": None},
         "trigger": None},
    ],
    "edges": [{"from": "hook", "to": "ticket", "kind": "data"}], "paused": False,
    "readiness": {"status": "needs_setup",
                  "meaning": "Something is in the way of it running: each issue says what, and where.", "issues": [
                      {"step": "ticket", "code": "missing_credentials", "message": "Ticket: connect an account"}]},
    "urls": [{"kind": "endpoint", "url": "https://api.noclick.com/v1/workflows/wf_1/endpoint", "step": None,
              "public": False}],
}


def test_one_workflow_reads_in_full(api, client):
    api.get("/v1/workflows/wf_1").respond(json=FULL)
    workflow = nc.Workflow.get("wf_1")
    assert (workflow.access, workflow.paused, workflow.readiness["status"]) == ("owner", False, "needs_setup")
    assert workflow.step_types == ["trigger-webhook", "automation-linear"]
    assert workflow.readiness["meaning"] == FULL["readiness"]["meaning"]
    hook, ticket = workflow.steps
    assert (hook.enabled, hook.settings, hook.trigger["error"], hook.connection) == (
        True, {"http_method": "POST"}, None, None)
    assert (ticket.trigger, ticket.connection) == (None, {"attached": False, "healthy": None, "hint": None})
    assert workflow.edges == [{"from": "hook", "to": "ticket", "kind": "data"}]
    assert workflow.urls[0]["kind"] == "endpoint"


def test_pause_resume_and_restore_read_the_workflow_again(api, client):
    api.get("/v1/workflows/wf_1").respond(json=FULL)
    paused = api.post("/v1/workflows/wf_1/pause").respond(json={**FULL, "paused": True})
    resumed = api.post("/v1/workflows/wf_1/resume").respond(json=FULL)
    restored = api.post("/v1/workflows/wf_1/restore").respond(json=FULL)
    workflow = nc.Workflow.from_id("wf_1")
    assert workflow.pause("Too noisy").paused is True
    assert body(paused.calls.last.request) == {"reason": "Too noisy"}
    assert workflow.resume().paused is False and resumed.called
    assert workflow.restore().name == "Order intake" and restored.called


def test_publishing_is_a_build_with_publish(api, client):
    api.get("/v1/workflows/wf_1").respond(json=FULL)
    builds = api.post("/v1/workflows/wf_1/builds").respond(
        status_code=202, json=operation(op_id="op_b", kind="workflow.build", status="running", workflow_id="wf_1"))
    workflow = nc.Workflow.from_id("wf_1")
    workflow.publish(subdomain="morrow", title="Morrow")
    assert body(builds.calls.last.request) == {"publish": {"subdomain": "morrow", "title": "Morrow"}}
    workflow.unpublish()
    assert body(builds.calls.last.request) == {"publish": {"action": "unpublish"}}
    workflow.build("Add a contact form", publish=True)
    assert body(builds.calls.last.request) == {"instructions": "Add a contact form", "publish": {}}


def test_a_build_result_says_what_it_published(api, client):
    result = nc.WorkflowBuildResult._from({"workflow_id": "wf_1", "summary": None, "steps": [], "app_url": None,
                                           "published": {"state": "published", "url": "https://morrow.noclick.app"}})
    assert result.published == {"state": "published", "url": "https://morrow.noclick.app"}


def test_one_run_reads_with_its_steps(api, client):
    api.get("/v1/workflows/wf_1").respond(json=FULL)
    api.get("/v1/workflows/wf_1/runs/run_1").respond(json={
        "object": "workflow_run", "id": "run_1", "workflow_id": "wf_1", "status": "failed", "inputs": {},
        "outputs": {}, "error": {"type": "platform_error", "message": "Step 'Ticket' failed: no team"},
        "source": "trigger", "user_id": None, "operation_id": None, "started_at": "2026-10-12T10:00:00Z",
        "finished_at": "2026-10-12T10:00:03Z",
        "steps": [{"id": "hook", "name": "Hook", "status": "succeeded", "error": None, "output": {"order_id": "o1"}},
                  {"id": "ticket", "name": "Ticket", "status": "failed", "error": "no team", "output": None}]})
    run = nc.Workflow.from_id("wf_1").get_run("run_1")
    assert (run.status, run.error) == ("failed", "Step 'Ticket' failed: no team")
    assert [(s.name, s.status, s.error) for s in run.steps] == [("Hook", "succeeded", None),
                                                                 ("Ticket", "failed", "no team")]
    assert isinstance(run.steps[0], nc.RunStep) and run.steps[0].output == {"order_id": "o1"}
