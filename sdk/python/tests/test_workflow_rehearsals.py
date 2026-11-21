"""A workflow's test run (``Workflow.rehearse``): the body each call sends and how its result reads, against the
mocked transport."""

import noclick as nc
from platform_helpers import body, operation

CALL = {"tool": "slack__send_message_to_channel", "arguments": {"channel": "#support"}, "result": {"ok": True}}
REHEARSAL = {
    "workflow_id": "wf_1", "test_run": {"key": "refund-request", "name": "Refund request", "custom": True},
    "trigger": {"step_id": "mail", "type": "automation-gmail", "name": "Inbox"},
    "reply": "I've told the team.", "tool_calls": [CALL],
    "transcript": [{"role": "tool", **CALL}, {"role": "assistant", "text": "I've told the team."}],
    "scenario": "An ordinary working day.", "note": "What it did to act was simulated.", "cost_usd": 0.004,
}


def test_a_test_run_names_what_it_plays_and_reads_what_the_agent_did(api, client):
    route = api.post("/v1/workflows/wf_1/rehearsals").respond(
        status_code=202, json=operation(op_id="op_t", kind="workflow.rehearse", status="succeeded", result=REHEARSAL))
    test = nc.Workflow.from_id("wf_1").rehearse("Refund request", scenario="Order 1042 shipped late.")
    assert body(route.calls.last.request) == {"test_run": "Refund request", "scenario": "Order 1042 shipped late."}
    done = test.wait()
    assert isinstance(done, nc.WorkflowRehearsal)
    assert (done.reply, done.tool_calls, done.cost_usd, done.operation_id) == (
        "I've told the team.", [CALL], 0.004, "op_t")
    assert done.test_run["name"] == "Refund request" and done.trigger["step_id"] == "mail"
    assert done.note == "What it did to act was simulated." and done.transcript[-1]["role"] == "assistant"


def test_a_message_of_your_own_is_staged_on_a_trigger_step(api, client):
    route = api.post("/v1/workflows/wf_1/rehearsals").respond(
        status_code=202, json=operation(op_id="op_t", kind="workflow.rehearse", status="queued"))
    inbox = nc.Workflow.from_id("wf_1")
    inbox.rehearse(trigger=inbox.step("mail"), body="My order never came.", title="Order 1042", author="Ana",
                   handle="ana@example.com")
    assert body(route.calls.last.request) == {"trigger": "mail", "body": "My order never came.",
                                              "title": "Order 1042", "author": "Ana", "handle": "ana@example.com"}
    with nc.as_user("user_42"):
        inbox.rehearse(trigger="automation-gmail", body="Hello?")
    sent = route.calls.last.request
    assert body(sent) == {"trigger": "automation-gmail", "body": "Hello?"}
    assert sent.headers["NoClick-User"] == "user_42"
