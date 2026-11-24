"""A run from one of a workflow's steps (``Workflow.run(from_step=, only=)``, ``Step.run``): the body each call sends,
against the mocked transport."""

import noclick as nc
from platform_helpers import body, operation

RUN = {"object": "workflow_run", "id": "run_1", "workflow_id": "wf_1", "status": "succeeded", "inputs": {},
       "outputs": {"Summary": {"message": "Order o_9 received"}}, "error": None, "source": "api", "user_id": None,
       "operation_id": "op_r", "started_at": "2026-11-21T10:00:00Z", "finished_at": "2026-11-21T10:00:02Z"}


def test_a_run_from_a_step_names_it_and_alone_says_so(api, client):
    runs = api.post("/v1/workflows/wf_1/runs").respond(
        status_code=202, json=operation(op_id="op_r", kind="workflow.run", status="queued"))
    intake = nc.Workflow.from_id("wf_1")
    intake.run(from_step="note")
    assert body(runs.calls.last.request) == {"inputs": {}, "from_step": "note"}
    intake.run(from_step=intake.step("note"), only=True, idempotency_key="note-again")
    assert body(runs.calls.last.request) == {"inputs": {}, "from_step": "note", "only": True}
    assert runs.calls.last.request.headers["Idempotency-Key"] == "note-again"
    # A run from its trigger sends what it always did.
    intake.run({"order_id": "o_1"})
    assert body(runs.calls.last.request) == {"inputs": {"order_id": "o_1"}}


def test_a_step_runs_the_workflow_from_itself(api, client):
    runs = api.post("/v1/workflows/wf_1/runs").respond(
        status_code=202, json=operation(op_id="op_r", kind="workflow.run", status="succeeded", result=RUN))
    op = nc.Workflow.from_id("wf_1").step("note").run(only=True)
    assert body(runs.calls.last.request) == {"inputs": {}, "from_step": "note", "only": True}
    assert op.wait().outputs == {"Summary": {"message": "Order o_9 received"}}
    nc.Workflow.from_id("wf_1").step("note").run()
    assert body(runs.calls.last.request) == {"inputs": {}, "from_step": "note"}


def test_a_manual_run_sends_what_the_apps_run_sends(api, client):
    runs = api.post("/v1/workflows/wf_1/runs").respond(
        status_code=202, json=operation(op_id="op_r", kind="workflow.run", status="queued"))
    intake = nc.Workflow.from_id("wf_1")
    intake.run(manual={})
    assert body(runs.calls.last.request) == {"inputs": {}, "manual": {}}
    intake.run(from_step="note", manual={"steps": ["hook", "note"], "outputs_from": {"hook": "run_0"}})
    assert body(runs.calls.last.request) == {"inputs": {}, "from_step": "note",
                                             "manual": {"steps": ["hook", "note"], "outputs_from": {"hook": "run_0"}}}
