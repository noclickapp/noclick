"""``Workflow.setup`` and ``Workflow.request_setup``: what a workflow needs from its person, as data, and sent to them
as one request, against the mocked transport: what each call sends and how its answer reads."""

import json

import noclick as nc

ITEMS = [
    {"key": "connect:slack", "kind": "connect", "app": "slack", "label": "Slack", "reconnect": False,
     "credential_types": ["slack_oauth"], "steps": [{"step_id": "ops", "step_name": "Tell ops"},
                                                   {"step_id": "sales", "step_name": "Tell sales"}]},
    {"key": "setting:text:to_number", "kind": "setting", "step": {"step_id": "text", "step_name": "Text me"},
     "setting": "to_number", "label": "To Number", "type": "string", "description": None, "options": None},
]
SETUP = {"object": "workflow_setup", "workflow_id": "wf_1", "ready": False, "items": ITEMS, "request": None}


def test_the_setup_reads_as_data(api, client):
    route = api.get("/v1/workflows/wf_1/setup").respond(json=SETUP)
    read = nc.Workflow.from_id("wf_1").setup()
    assert route.called and isinstance(read, nc.WorkflowSetup)
    assert (read.workflow_id, read.ready, read.request, read.sent) == ("wf_1", False, None, None)
    assert [i["label"] for i in read.items] == ["Slack", "To Number"]


def test_requesting_it_sends_one_request_how_it_was_asked(api, client):
    sent = {"id": "op_1", "status": "awaiting_human", "request": {"id": "hr_1", "kind": "setup",
                                                                  "delivered_via": ["email"]}}
    route = api.post("/v1/workflows/wf_1/setup/request").respond(json={
        **SETUP, "request": {"id": "hr_1", "operation_id": "op_1", "parts": []}, "sent": sent})
    done = nc.Workflow.from_id("wf_1").request_setup(via=["email"])
    assert json.loads(route.calls.last.request.content) == {"via": ["email"]}
    assert done.sent["request"]["kind"] == "setup" and done.request["id"] == "hr_1"
    nc.Workflow.from_id("wf_1").request_setup()
    assert json.loads(route.calls.last.request.content) == {"via": "auto"}


def test_a_ready_workflow_reads_ready_with_nothing_sent(api, client):
    api.post("/v1/workflows/wf_1/setup/request").respond(json={**SETUP, "ready": True, "items": [], "sent": None})
    done = nc.Workflow.from_id("wf_1").request_setup()
    assert done.ready and done.items == [] and done.sent is None
