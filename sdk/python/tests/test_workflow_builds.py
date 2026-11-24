"""Building workflows from code, against the mocked transport: the routes and
bodies each call sends, and what it parses (the build's question, its result)."""

import pytest

import noclick as nc
from noclick import workflow as workflow_module
from platform_helpers import body, operation

WORKFLOW = {"object": "workflow", "id": "wf_1", "name": "Morning brief", "description": None, "inputs": {},
            "app_url": "https://noclick.com/dashboard?tab=workflows&workflow=wf_1", "created_at": "2026-10-12T10:00:00Z",
            "updated_at": "2026-10-12T10:00:00Z", "steps": []}
STEPS = [{"id": "daily", "name": "Every morning", "type": "trigger-cron", "operation": None},
         {"id": "mail", "name": "Email the brief", "type": "automation-gmail", "operation": "send_email"}]
RESULT = {"object": "workflow_build", "workflow_id": "wf_1", "summary": "It emails you every morning at 8.",
          "steps": STEPS, "app_url": "https://noclick.com/dashboard?tab=workflows&workflow=wf_1"}
QUESTION = {"id": "ask-1", "title": "A few details", "answer_url": "https://noclick.com/b/l1",
            "answerable_from_code": True,
            "inputs": [{"id": "channel", "label": "Which channel?", "type": "text", "description": "", "required": True}]}


def building(status="running", **extra):
    return operation(op_id="op_b", kind="workflow.build", status=status, workflow_id="wf_1",
                     **{"step": "building", **extra})


def test_create_with_instructions_builds_it_and_wait_gives_its_steps(api, client):
    made = api.post("/v1/workflows").respond(status_code=201, json={**WORKFLOW, "build": building()})
    api.get("/v1/operations/op_b/wait").respond(json=building("succeeded", result=RESULT))
    brief = nc.Workflow.create("Morning brief", instructions="Every day at 8, email me my calendar")
    assert body(made.calls.last.request) == {"name": "Morning brief",
                                             "instructions": "Every day at 8, email me my calendar"}
    assert "NoClick-User" not in made.calls.last.request.headers  # workflows are the account's
    build = brief.latest_build
    assert isinstance(build, nc.WorkflowBuild) and build.workflow_id == "wf_1" and build.step == "building"
    result = build.wait()
    assert isinstance(result, nc.WorkflowBuildResult)
    assert result.summary == "It emails you every morning at 8."
    assert [(s.name, s.operation) for s in result.steps] == [("Every morning", None), ("Email the brief", "send_email")]


def test_a_workflow_created_without_instructions_has_no_build(api, client):
    api.post("/v1/workflows").respond(status_code=201, json=WORKFLOW)
    assert nc.Workflow.create("Morning brief").latest_build is None


def test_a_build_that_asks_is_answered_from_code(api, client, monkeypatch):
    monkeypatch.setattr(workflow_module, "_QUESTION_POLL_S", 0)
    api.get("/v1/workflows/wf_1").respond(json={**WORKFLOW, "steps": STEPS})
    started = api.post("/v1/workflows/wf_1/builds").respond(status_code=202, json=building())
    reads = api.get("/v1/operations/op_b").mock(side_effect=[
        _json(building()), _json(building("awaiting_human", step="asking", question=QUESTION)),
        _json(building("succeeded", result=RESULT))])
    answered = api.post("/v1/workflows/wf_1/builds/op_b/answer").respond(json=building())

    brief = nc.Workflow.from_id("wf_1")
    build = brief.build("Also post it to Slack")
    assert body(started.calls.last.request) == {"instructions": "Also post it to Slack"}
    assert brief.latest_build is build
    question = build.next_question()
    assert isinstance(question, nc.BuildQuestion) and question.answerable_from_code
    assert question.inputs[0]["id"] == "channel" and question.answer_url == "https://noclick.com/b/l1"
    assert build.answer({"channel": "#team"}, message="Keep it short") is build
    assert body(answered.calls.last.request) == {"values": {"channel": "#team"}, "message": "Keep it short"}
    assert build.next_question() is None  # done
    assert reads.call_count == 3


def test_wait_stops_at_a_question_and_then_waits_for_its_answer(api, client):
    """The guide's first example, wait() straight after create(), blocked its whole timeout on a question nobody
    was shown (2026-10-28): wait() raises the question, and once it has, waits through it for the answer."""
    api.post("/v1/workflows/wf_1/builds").respond(status_code=202, json=building())
    asking = building("awaiting_human", step="asking", question=QUESTION)
    waits = api.get("/v1/operations/op_b/wait").mock(side_effect=[
        _json(building()), _json(asking), _json(asking), _json(building("succeeded", result=RESULT))])
    build = nc.Workflow.from_id("wf_1").build("Also post it to Slack")
    with pytest.raises(nc.AnswerRequired) as asked:
        build.wait(timeout=900)
    question = asked.value.question
    assert isinstance(question, nc.BuildQuestion) and question.inputs[0]["id"] == "channel"
    assert question.answer_url == "https://noclick.com/b/l1"
    assert asked.value.details["operation_id"] == "op_b" and "build.answer(" in asked.value.next_step
    assert str(asked.value).startswith("The build is waiting on an answer: A few details")
    # A person answers at answer_url while this waits: the question it raised doesn't raise again.
    assert build.wait(timeout=900).summary == "It emails you every morning at 8."
    assert waits.call_count == 4
    # Each read waits on the server only briefly, so a question surfaces in seconds, not a long poll.
    assert {c.request.url.params["timeout_s"] for c in waits.calls} == {str(workflow_module._QUESTION_WAIT_S)}


def test_a_new_question_raises_and_one_already_returned_does_not(api, client):
    api.post("/v1/workflows/wf_1/builds").respond(status_code=202, json=building())
    second = {**QUESTION, "id": "ask-2", "title": None, "inputs": [{"id": "time", "label": "What time?", "type": "text"}]}
    api.get("/v1/operations/op_b").respond(json=building("awaiting_human", step="asking", question=QUESTION))
    api.get("/v1/operations/op_b/wait").mock(side_effect=[
        _json(building("awaiting_human", step="asking", question=QUESTION)),
        _json(building("awaiting_human", step="asking", question=second)),
        _json(building("succeeded", result=RESULT))])
    build = nc.Workflow.from_id("wf_1").build("Also post it to Slack")
    assert build.next_question().id == "ask-1"  # seen: wait() goes on through it
    with pytest.raises(nc.AnswerRequired) as asked:
        build.wait()
    assert asked.value.question.id == "ask-2" and "waiting on an answer: What time?" in str(asked.value)
    assert build.wait().steps[0].id == "daily"


def test_a_finished_build_carries_facts_beside_the_builders_words(api, client):
    readiness = {"status": "needs_setup", "meaning": "Something is in the way.", "warnings": [], "unverified": [],
                 "issues": [{"step": "mail", "code": "invalid_config", "message": "Email the brief: to is required"}]}
    read = {"step": "mail", "field": "body", "source": "daily", "key": "text", "known_keys": ["fired_at"],
            "message": "Email the brief (`mail`): `body` reads `text` from Daily (`daily`), whose output has no `text` "
                       "(it has fired_at): a run reads nothing there."}
    facts = {**RESULT, "built": True, "version": 7, "readiness": readiness, "sent_back": 2, "unread": [],
             "references": [read],
             "verdicts": {"daily": {"config_valid": True},
                          "mail": {"config_valid": False, "missing_required": ["to"]}}}
    api.post("/v1/workflows/wf_1/builds").respond(status_code=202, json=building())
    api.get("/v1/operations/op_b/wait").mock(side_effect=[_json(building("succeeded", result=facts)),
                                                          _json(building("succeeded", result=RESULT))])
    result = nc.Workflow.from_id("wf_1").build("Email it to the team too").wait()
    assert (result.built, result.version, result.sent_back, result.unread) == (True, 7, 2, [])
    assert result.readiness["status"] == "needs_setup" and result.readiness["issues"][0]["step"] == "mail"
    assert result.verdicts["mail"] == {"config_valid": False, "missing_required": ["to"]}
    # The reads that get no value, said: a run that succeeded wouldn't show them.
    assert result.references == [read]
    # A result from before facts were carried, or whose facts weren't read, says none of them.
    older = nc.Workflow.from_id("wf_1").build("Again").wait()
    assert (older.built, older.version, older.readiness, older.verdicts, older.references, older.sent_back,
            older.unread) == (None, None, None, None, None, 0, [])


def test_facts_that_werent_read_are_none_and_named(api, client):
    unread = {**RESULT, "built": None, "version": None, "readiness": None, "verdicts": None, "sent_back": 0,
              "unread": ["built", "version", "readiness", "verdicts"]}
    api.post("/v1/workflows/wf_1/builds").respond(status_code=202, json=building())
    api.get("/v1/operations/op_b/wait").respond(json=building("succeeded", result=unread))
    result = nc.Workflow.from_id("wf_1").build("Email it to the team too").wait()
    assert result.readiness is None and result.unread == ["built", "version", "readiness", "verdicts"]


def test_a_build_asks_through_human_requests_and_code_answers_accounts_and_secrets(api, client):
    asked = {**QUESTION, "sent_to": ["email", "web"], "inputs": [
        {"id": "slack", "label": "Connect Slack", "type": "credential", "credential_type": "slack_oauth",
         "request_id": "hr_1"},
        {"id": "env", "label": "Its token", "type": "env", "env_keys": [{"name": "WAREHOUSE_TOKEN"}],
         "request_id": "hr_2"}]}
    started = api.post("/v1/workflows/wf_1/builds").respond(
        status_code=202, json=building("awaiting_human", step="asking", question=asked))
    answered = api.post("/v1/workflows/wf_1/builds/op_b/answer").respond(json=building())
    build = nc.Workflow.from_id("wf_1").build("Post it to Slack")
    assert body(started.calls.last.request) == {"instructions": "Post it to Slack"}
    question = build.question
    assert question.sent_to == ["email", "web"] and [i["request_id"] for i in question.inputs] == ["hr_1", "hr_2"]
    build.answer({"slack": "credential:c1"}, secret_values={"env": {"WAREHOUSE_TOKEN": "t0k"}})
    assert body(answered.calls.last.request) == {"values": {"slack": "credential:c1"},
                                                 "secret_values": {"env": {"WAREHOUSE_TOKEN": "t0k"}}}


def test_a_build_or_a_new_workflow_can_ask_nothing(api, client):
    made = api.post("/v1/workflows").respond(status_code=201, json={**WORKFLOW, "build": building()})
    started = api.post("/v1/workflows/wf_1/builds").respond(status_code=202, json=building())
    nc.Workflow.create("Morning brief", instructions="Email me at 8", questions="assume")
    nc.Workflow.from_id("wf_1").build("Text me too", questions="assume")
    assert body(made.calls.last.request) == {"name": "Morning brief", "instructions": "Email me at 8",
                                             "questions": "assume"}
    assert body(started.calls.last.request) == {"instructions": "Text me too", "questions": "assume"}


def test_skip_goes_on_without_an_answer(api, client):
    api.post("/v1/workflows/wf_1/builds").respond(status_code=202, json=building())
    answered = api.post("/v1/workflows/wf_1/builds/op_b/answer").respond(json=building())
    nc.Workflow.from_id("wf_1").build("Text me too").answer(skip=True)
    assert body(answered.calls.last.request) == {"values": {}, "skip": True}


def test_steps_come_with_one_workflow_and_delete_trashes_it(api, client):
    api.get("/v1/workflows/wf_1").respond(json={**WORKFLOW, "steps": STEPS})
    gone = api.delete("/v1/workflows/wf_1").respond(json={"object": "workflow", "id": "wf_1", "deleted": True})
    brief = nc.Workflow.get("wf_1")
    assert [s.id for s in brief.steps] == ["daily", "mail"]
    brief.delete()
    assert gone.call_count == 1


def test_a_build_in_progress_is_a_conflict(api, client):
    api.post("/v1/workflows/wf_1/builds").respond(status_code=409, json={"error": {
        "type": "conflict", "message": "A build is already pending for this workflow."}})
    with pytest.raises(nc.Conflict):
        nc.Workflow.from_id("wf_1").build("Text me too")


def _json(payload):
    import httpx

    return httpx.Response(200, json=payload)
