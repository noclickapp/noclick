"""A step's outputs (``Step.outputs``, ``Step.output``): what each call sends and how it reads the answer, against the
mocked transport."""

import httpx

import noclick as nc
from platform_helpers import USER_ID, listing

DELIVERY = {
    "object": "step_output", "workflow_id": "wf_1", "step_id": "hook", "iteration": None, "run_id": "run_9",
    "source": "trigger", "status": "succeeded", "error": None, "created_at": "2026-11-20T09:00:00Z",
    "no_event": False, "preview": 'order_id="o_9", items=[1 items]', "withheld": ["_webhook.headers.Authorization"],
}
PLACEHOLDER = {**DELIVERY, "run_id": "run_8", "source": "app", "no_event": True, "preview": 'status="no_event"',
               "withheld": []}


def test_outputs_read_newest_first_page_by_page(api, client):
    route = api.get("/v1/workflows/wf_1/steps/hook/outputs").mock(side_effect=[
        httpx.Response(200, json=listing(DELIVERY, next_cursor="run_9:hook")),
        httpx.Response(200, json=listing(PLACEHOLDER)),
    ])
    found = nc.Workflow.from_id("wf_1").step("hook").outputs(search="o_9", limit=None)
    first, second = (call.request for call in route.calls)
    assert (first.url.params["search"], "cursor" not in first.url.params) == ("o_9", True)
    assert second.url.params["cursor"] == "run_9:hook" and "NoClick-User" not in first.headers
    delivery, placeholder = found
    assert isinstance(delivery, nc.StepOutput)
    assert (delivery.run_id, delivery.source, delivery.status, delivery.no_event, delivery.iteration) == (
        "run_9", "trigger", "succeeded", False, None)
    assert delivery.preview.startswith('order_id="o_9"') and delivery.withheld == ["_webhook.headers.Authorization"]
    assert delivery.output is None and delivery.created_at.year == 2026
    assert (placeholder.no_event, placeholder.source) == (True, "app")


def test_outputs_take_ten_by_default_and_read_as_a_user_inside_as_user(api, client):
    route = api.get("/v1/workflows/wf_1/steps/hook/outputs").respond(json=listing(DELIVERY))
    with nc.as_user(USER_ID):
        nc.Workflow.from_id("wf_1").step("hook").outputs()
    request = route.calls.last.request
    assert request.url.params["limit"] == "10" and "search" not in request.url.params
    assert request.headers["NoClick-User"] == USER_ID


def test_one_output_reads_whole_or_a_part(api, client):
    route = api.get("/v1/workflows/wf_1/steps/note/outputs/run_9").respond(json={
        **DELIVERY, "step_id": "note", "iteration": 2, "preview": None, "output": "A1", "path": "items[0].sku",
        "full": True, "truncated": False})
    note = nc.Workflow.from_id("wf_1").step("note")
    read = note.output("run_9", path="items[0].sku", full=True, iteration=2)
    params = route.calls.last.request.url.params
    assert (params["path"], params["full"], params["iteration"]) == ("items[0].sku", "true", "2")
    assert (read.output, read.path, read.full, read.truncated, read.iteration) == ("A1", "items[0].sku", True, False, 2)
    # Left out, a choice isn't sent.
    note.output("run_9")
    assert dict(route.calls.last.request.url.params) == {}


def test_a_runs_step_names_the_secrets_left_out_of_it(api, client):
    api.get("/v1/workflows/wf_1/runs/run_1").respond(json={
        "object": "workflow_run", "id": "run_1", "workflow_id": "wf_1", "status": "succeeded", "inputs": {},
        "outputs": {}, "error": None, "source": "trigger", "user_id": None, "operation_id": None,
        "started_at": "2026-10-12T10:00:00Z", "finished_at": "2026-10-12T10:00:03Z",
        "steps": [{"id": "hook", "name": "Hook", "status": "succeeded", "error": None, "output": {"order_id": "o1"},
                   "withheld": ["_webhook.headers.Authorization"]}]})
    [hook] = nc.Workflow.from_id("wf_1").get_run("run_1").steps
    assert hook.withheld == ["_webhook.headers.Authorization"]


def test_a_hosted_mcp_links_status_reads_both_sides(api, client):
    route = api.get("/v1/workflows/wf_1/steps/mcp/hosted_mcp").respond(json={
        "object": "hosted_mcp", "exists": True, "is_active": True, "liveness_available": True,
        "client_name": "claude-code", "last_method": "tools/list", "tool_count": 3, "tools_ready": 3,
        "tools_sample": ["linear__create_issue"], "seconds_since_seen": 4.0, "first_tools_at": 1763629200})
    link = nc.Workflow.from_id("wf_1").step("mcp").hosted_mcp(tools=True)
    assert route.calls.last.request.url.params["tools"] == "true"
    assert (link.exists, link.client_name, link.tools_ready, link.tools_sample) == (
        True, "claude-code", 3, ["linear__create_issue"])
