"""Workflows (designed, not built yet) and user export (built).

Against the mocked transport: the routes, bodies and user headers each call
sends, and what it parses.
"""

import pytest

import noclick as nc
from platform_helpers import USER_ID, body, listing, operation, user_row


# --- workflows --------------------------------------------------------------------

WORKFLOW = {"object": "workflow", "id": "wf_1", "name": "order-intake", "description": "Checks a new order.",
            "inputs": {"type": "object", "properties": {"order_id": {"type": "string"}}},
            "app_url": "https://noclick.com/dashboard?tab=workflows&workflow=order-intake", "created_at": "2026-09-01T10:00:00Z",
            "updated_at": "2026-09-25T10:00:00Z"}
RUN = {"object": "workflow_run", "id": "run_1", "workflow_id": "wf_1", "status": "succeeded",
       "inputs": {"order_id": "o1"}, "outputs": {"summary": "Order o1 is in stock."}, "error": None,
       "source": "api", "user_id": USER_ID, "operation_id": "op_r",
       "started_at": "2026-09-25T10:00:00Z", "finished_at": "2026-09-25T10:00:09Z"}


def test_from_name_run_and_wait(api, client):
    lookup = api.get("/v1/workflows").respond(json=listing(WORKFLOW, {**WORKFLOW, "id": "wf_2", "name": "other"}))
    start = api.post("/v1/workflows/wf_1/runs").respond(json=operation(op_id="op_r", kind="workflow.run",
                                                                       status="running"))
    api.get("/v1/operations/op_r/wait").respond(json=operation(op_id="op_r", kind="workflow.run",
                                                               status="succeeded", result=RUN))
    intake = nc.Workflow.from_name("order-intake")
    assert lookup.call_count == 0  # lazy
    with nc.as_user("acme"):
        op = intake.run({"order_id": "o1"}, idempotency_key="order-o1")
    assert lookup.calls.last.request.url.params["name"] == "order-intake"
    assert "NoClick-User" not in lookup.calls.last.request.headers  # workflows are the account's
    assert body(start.calls.last.request) == {"inputs": {"order_id": "o1"}}
    assert start.calls.last.request.headers["NoClick-User"] == "acme"  # the run is the user's
    assert start.calls.last.request.headers["Idempotency-Key"] == "order-o1"
    run = op.wait()
    assert isinstance(run, nc.WorkflowRun)
    assert (run.status, run.outputs["summary"], run.source, run.finished_at.second) == (
        "succeeded", "Order o1 is in stock.", "api", 9)
    assert nc.Operation.from_id("op_r").wait().id == "run_1"  # resumable anywhere


def test_from_name_refuses_a_missing_or_ambiguous_name(api, client):
    api.get("/v1/workflows").respond(json=listing(WORKFLOW, {**WORKFLOW, "id": "wf_2"}))
    with pytest.raises(nc.Conflict, match="2 workflows are named") as info:
        nc.Workflow.from_name("order-intake").hydrate()
    assert info.value.ids == ["wf_1", "wf_2"]
    with pytest.raises(nc.NotFound, match="No workflow is named 'nope'"):
        nc.Workflow.from_name("nope").hydrate()


def test_a_failed_run_raises_its_error(api, client):
    api.post("/v1/workflows/wf_1/runs").respond(json=operation(op_id="op_r", kind="workflow.run", status="running"))
    api.get("/v1/operations/op_r/wait").respond(json=operation(
        op_id="op_r", kind="workflow.run", status="failed",
        error={"type": "needs_connection", "message": "The Slack step has no connected account."}))
    with pytest.raises(nc.NeedsConnection, match="Slack step"):
        nc.Workflow.from_id("wf_1").run().wait()


def test_runs_endpoint_and_list(api, client):
    runs = api.get("/v1/workflows/wf_1/runs").respond(json=listing(RUN, {**RUN, "id": "run_0", "status": "failed",
                                                                         "error": {"message": "Timed out"}}))
    endpoint = api.put("/v1/workflows/wf_1/endpoint").respond(json={
        "object": "workflow_endpoint", "url": "https://wf-1.example.com", "public": True, "method": "POST"})
    listed = api.get("/v1/workflows").respond(json=listing(WORKFLOW))

    intake = nc.Workflow.from_id("wf_1")
    latest, failed = intake.runs(status=["succeeded", "failed"], user_filter=nc.ALL_USERS)
    params = runs.calls.last.request.url.params
    assert (params["status"], params["user_id"], params["limit"]) == ("succeeded,failed", "all", "20")
    assert (latest.id, failed.status, failed.error) == ("run_1", "failed", "Timed out")

    public = intake.endpoint(public=True)
    assert body(endpoint.calls.last.request) == {"public": True}
    assert (public.url, public.public, public.method) == ("https://wf-1.example.com", True, "POST")
    intake.endpoint()
    assert body(endpoint.calls.last.request) == {}

    [workflow] = nc.Workflow.list(q="order", limit=5)
    assert listed.calls.last.request.url.params["q"] == "order"
    assert (workflow.name, workflow.inputs["type"]) == ("order-intake", "object")


# --- user export ----------------------------------------------------------------

BUNDLE = {"object": "export", "url": "https://exports.example.com/x/acme.zip", "expires_at": "2026-10-02T10:00:00Z",
          "size_bytes": 48213,
          "contents": [{"object": "export_item", "kind": "agent", "name": "concierge",
                        "detail": "agents/concierge.json: its definition (instructions, model, tools and triggers)."},
                       {"object": "export_item", "kind": "phone_number", "name": "+14155550123",
                        "detail": "Port it to another carrier: POST /v1/phone_numbers/pn_1/transfer_out."}],
          "remaining_dependencies": ["the agent runtime", "channels"]}


def test_export_returns_the_bundle(api, client):
    api.get(f"/v1/users/{USER_ID}").respond(json=user_row())
    start = api.post(f"/v1/users/{USER_ID}/export").respond(json=operation(op_id="op_x", kind="user.export",
                                                                               status="running"))
    api.get("/v1/operations/op_x/wait").respond(json=operation(op_id="op_x", kind="user.export",
                                                               status="succeeded", result=BUNDLE))
    bundle = nc.User.from_id(USER_ID).export().wait()
    assert body(start.calls.last.request) == {}
    assert "NoClick-User" not in start.calls.last.request.headers
    assert isinstance(bundle, nc.ExportBundle)
    assert bundle.url.endswith("acme.zip") and bundle.expires_at.day == 2
    assert [(i.kind, i.name) for i in bundle.contents] == [("agent", "concierge"), ("phone_number", "+14155550123")]
    assert bundle.remaining_dependencies == ["the agent runtime", "channels"] and bundle.size_bytes == 48213
    assert isinstance(nc.Operation.from_id("op_x").wait(), nc.ExportBundle)


def test_delete_with_export_exports_first(api, client):
    api.get(f"/v1/users/{USER_ID}").respond(json=user_row())
    start = api.post(f"/v1/users/{USER_ID}/export").respond(json=operation(op_id="op_x", kind="user.export",
                                                                               status="running"))
    delete = api.delete(f"/v1/users/{USER_ID}").respond(json=user_row(status="deleted"))
    op = nc.User.from_id(USER_ID).delete(export=True)
    assert isinstance(op, nc.Operation) and op.kind == "user.export"
    assert body(start.calls.last.request) == {"delete_after": True}
    assert delete.call_count == 0  # the server deletes once the export is ready

    user = nc.User.from_id(USER_ID)
    assert user.delete() is None and user.status == "deleted" and delete.call_count == 1
