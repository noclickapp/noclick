"""A run's steps as they ran (``get_run(id, detail="steps")``), what came in to a coding harness's reply
(``run_inputs``), and a step form's check (``check_step_settings``), against the mocked transport."""

import noclick as nc
from platform_helpers import body

WF = "2e3a9296-1bf5-4088-a20d-7c31937380c4"
RUN = "7c1f3e2a-5b4d-4e6f-8a9b-0c1d2e3f4a01"


def test_get_run_with_detail_reads_each_step_as_it_ran(api, client):
    route = api.get(f"/v1/workflows/{WF}/runs/{RUN}").respond(json={
        "object": "workflow_run", "id": RUN, "status": "failed", "graph": {"nodes": [{"id": "helper"}], "edges": []},
        "steps": [{"id": "helper", "name": "Helper", "status": "failed", "error": "x", "output": None, "withheld": [],
                   "type": "agent", "operation": None, "error_action": {"kind": "add_funds"},
                   "tool_calls": [{"tool_name": "slack.send"}]}]})
    run = nc.Workflow.from_id(WF).get_run(RUN, detail="steps")
    assert route.calls.last.request.url.params["detail"] == "steps"
    step = run.steps[0]
    assert (step.type, step.error_action, step.tool_calls[0]["tool_name"]) == ("agent", {"kind": "add_funds"},
                                                                               "slack.send")
    assert run.graph["nodes"] == [{"id": "helper"}]


def test_run_inputs_reads_each_delivery(api, client):
    api.get(f"/v1/workflows/{WF}/runs/{RUN}/inputs").respond(json={"object": "list", "next_cursor": None, "total": 3,
        "data": [{"run_id": "d1", "steps": [{"id": "hook", "status": "succeeded", "output": {"order_id": "o_9"}}]}]})
    came = nc.Workflow.from_id(WF).run_inputs(RUN)
    assert came.total == 3 and came.inputs[0]["run_id"] == "d1"
    assert came.inputs[0]["steps"][0].output == {"order_id": "o_9"}


def test_check_step_settings_posts_the_settings(api, client):
    route = api.post("/v1/step_types/log/check").respond(json={
        "object": "step_check", "step_type": "log", "valid": True, "errors": [], "satisfied_set": "default"})
    check = nc.check_step_settings("log", {"message": "Hi"})
    assert body(route.calls.last.request) == {"settings": {"message": "Hi"}}
    assert (check.valid, check.satisfied_set) == (True, "default")
