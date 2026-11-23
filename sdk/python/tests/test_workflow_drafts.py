"""Drafting a workflow's steps (``Workflow.draft``): the body it sends and the result its operation settles with,
against the mocked transport."""

import noclick as nc
from platform_helpers import body, operation

DRAFTED = {
    "object": "workflow_draft", "workflow_id": "wf_1", "mode": "full", "version": 7, "history_version": 3,
    "changed": True, "summary": "Changed 2 steps",
    "steps": {
        "fetch": {"drafted": True, "error": None, "operation": "list_messages", "settings": ["query"],
                  "unfilled": ["label_ids"], "config_valid": True, "references": []},
        "post": {"drafted": False, "error": "No operation fits", "operation": None, "settings": [], "unfilled": [],
                 "config_valid": False, "references": [{"field": "text", "step": "fetch", "key": "body",
                                                        "known_keys": ["messages"]}]},
    },
}


def test_a_draft_names_its_steps_their_goals_and_its_mode(api, client):
    drafts = api.post("/v1/workflows/wf_1/drafts").respond(
        status_code=202, json=operation(op_id="op_d", kind="workflow.draft", status="queued"))
    brief = nc.Workflow.from_id("wf_1")
    brief.draft([brief.step("fetch"), {"id": "post", "goal": "Post a summary to #team"}],
                instructions="Every morning, summarize my email")
    assert body(drafts.calls.last.request) == {
        "steps": [{"id": "fetch"}, {"id": "post", "goal": "Post a summary to #team"}], "mode": "full",
        "instructions": "Every morning, summarize my email"}
    brief.draft(["post"], mode="field", field="text")
    assert body(drafts.calls.last.request) == {"steps": [{"id": "post"}], "mode": "field", "field": "text"}


def test_a_drafts_result_is_each_steps_verdict(api, client):
    api.post("/v1/workflows/wf_1/drafts").respond(
        status_code=202, json=operation(op_id="op_d", kind="workflow.draft", status="succeeded", result=DRAFTED))
    op = nc.Workflow.from_id("wf_1").draft(["fetch", "post"])
    assert op.kind == "workflow.draft"
    result = op.wait()
    assert isinstance(result, nc.WorkflowDraftResult)
    assert (result.version, result.history_version, result.changed) == (7, 3, True)
    assert result.steps["fetch"]["unfilled"] == ["label_ids"]
    assert result.steps["post"]["error"] == "No operation fits"
    assert result.steps["post"]["references"][0]["known_keys"] == ["messages"]


PREVIEW = {
    "object": "workflow_draft", "workflow_id": "wf_1", "mode": "full", "written": False, "version": 7,
    "history_version": None, "changed": True, "summary": "Changed 1 step",
    "steps": {"post": {"drafted": True, "error": None, "operation": "send_message", "settings": ["text"],
                       "unfilled": [], "withheld": [], "config_valid": True, "references": []}},
    "edits": [{"op": "update_step", "id": "post", "operation": "send_message", "settings": {"text": "Hi"}}],
}


def test_a_draft_that_writes_nothing_asks_so_and_reads_the_edits_it_answers(api, client):
    drafts = api.post("/v1/workflows/wf_1/drafts").respond(
        status_code=202, json=operation(op_id="op_d", kind="workflow.draft", status="succeeded", result=PREVIEW))
    result = nc.Workflow.from_id("wf_1").draft(["post"], write=False).wait()
    assert body(drafts.calls.last.request) == {"steps": [{"id": "post"}], "mode": "full", "write": False}
    assert (result.written, result.version, result.history_version) == (False, 7, None)
    assert result.edits == PREVIEW["edits"]


def test_a_written_draft_reads_as_written(api, client):
    api.post("/v1/workflows/wf_1/drafts").respond(
        status_code=202, json=operation(op_id="op_d", kind="workflow.draft", status="succeeded", result=DRAFTED))
    result = nc.Workflow.from_id("wf_1").draft(["fetch"]).wait()
    assert (result.written, result.edits) == (True, [])
