"""The builder made and run with the SDK, against a mocked API answering as ``/v1`` does: it's made once from the
definition, a build is one message in the workflow's conversation, and what the build came to is read from the
workflow, sent back when a run would refuse it."""

import json

import httpx
import pytest
import respx

import noclick as nc
from noclick import _client as client_module
from noclick_builder import agent, definition

BASE = "https://api.test"
WF = "wf_1"
AGENT = {"object": "agent", "id": "ag_b", "name": "builder", "model": "openrouter/x", "harness": "sdk",
         "instructions": "x", "tools": [], "user_id": None, "workflow_id": "wf_agent", "parent_id": None,
         "created_at": "2026-11-22T10:00:00Z"}
INVALID = {"code": "invalid_config", "step": "send", "message": "to: field required"}


def body(request):
    return json.loads(request.content) if request.content else None


def operation(op_id, status, result=None):
    return {"object": "operation", "id": op_id, "kind": "agent.message", "status": status, "result": result,
            "error": None, "created_at": "2026-11-22T10:00:00Z", "updated_at": "2026-11-22T10:00:00Z"}


STEP = {"id": "send", "name": "Send it", "type": "automation-send-email", "operation": "send", "enabled": True,
        "settings": {}, "connection": None, "trigger": None}


def workflow(version=3, issues=(), steps=(STEP,)):
    return {"object": "workflow", "id": WF, "name": "Morning brief", "description": "", "version": version,
            "access": "owner", "steps": list(steps),
            "readiness": {"status": "needs_setup" if issues else "configured", "meaning": "", "issues": list(issues),
                          "warnings": [], "unverified": []}}


def graph(version):
    return {"object": "workflow_graph", "workflow_id": WF, "version": version, "name": "Morning brief",
            "description": "", "settings": {}, "graph": {"nodes": [], "edges": []}}


def versions(*each):
    """The graph's version at each read, in order; the last one from then on."""
    reads = iter(each)
    last = [each[-1]]

    def answer(request):
        last[0] = next(reads, last[0])
        return httpx.Response(200, json=graph(last[0]))

    return answer


def replies(api, *texts):
    """The builder's reply to each message sent it, in order."""
    sent = api.post("/v1/agents/ag_b/messages").mock(side_effect=[
        httpx.Response(202, json=operation(f"op_{n}", "running")) for n in range(len(texts))])
    for n, text in enumerate(texts):
        api.get(f"/v1/operations/op_{n}/wait").respond(json=operation(
            f"op_{n}", "succeeded", {"text": text, "conversation": f"build:{WF}", "tool_calls": []}))
    return sent


@pytest.fixture
def api(monkeypatch):
    client = nc.Client(api_key="nk_live_test", base_url=BASE, max_retries=0)
    monkeypatch.setattr(client_module, "_default", client)
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


def test_the_builder_is_made_from_the_definition(api):
    made = api.post("/v1/agents").respond(201, json=AGENT)
    builder = agent.ensure()
    sent = body(made.calls.last.request)
    assert builder.id == "ag_b"
    assert sent["name"] == definition.NAME and sent["instructions"] == definition.instructions()
    assert sent["tools"] == definition.wire_tools() and sent["shell"] is True


def test_a_builder_that_exists_is_the_one_used(api):
    api.post("/v1/agents").respond(409, json={"error": {"type": "conflict", "message": "It already exists.",
                                                         "existing_id": "ag_b"}})
    api.get("/v1/agents/ag_b").respond(json=AGENT)
    assert agent.ensure().id == "ag_b"


def test_a_build_is_one_message_in_the_workflows_conversation(api):
    api.post("/v1/agents").respond(201, json=AGENT)
    api.get(f"/v1/workflows/{WF}").respond(json=workflow(version=5))
    api.get(f"/v1/workflows/{WF}/graph").mock(side_effect=versions(3, 5))
    sent = replies(api, "Built: a schedule, then an email.")

    built = agent.build(WF, "Every weekday at 8, email me today's calendar.")

    message = body(sent.calls.last.request)
    assert message["conversation"] == f"build:{WF}"
    assert message["text"] == definition.request(WF, "Every weekday at 8, email me today's calendar.",
                                                 name="Morning brief")
    assert built.summary == "Built: a schedule, then an email."
    assert (built.built, built.version, built.sent_back) == (True, 5, [])
    assert built.readiness["status"] == "configured"


def test_a_build_a_run_would_refuse_is_sent_back_with_what_fails(api):
    api.post("/v1/agents").respond(201, json=AGENT)
    api.get(f"/v1/workflows/{WF}").mock(side_effect=[
        httpx.Response(200, json=workflow()),                       # the workflow, loaded
        httpx.Response(200, json=workflow(issues=[INVALID])),       # after the first reply: a step would fail
        httpx.Response(200, json=workflow(version=6)),              # after the second: ready
    ])
    api.get(f"/v1/workflows/{WF}/graph").mock(side_effect=versions(3, 4, 6))
    sent = replies(api, "Done.", "Fixed the recipient.")

    built = agent.build(WF, "Email me my calendar.")

    assert sent.call_count == 2
    again = body(sent.calls.last.request)
    assert again["conversation"] == f"build:{WF}" and again["text"] == definition.sent_back([INVALID])
    assert (built.summary, built.sent_back, built.version) == ("Fixed the recipient.", ["rejected"], 6)
    assert built.readiness["issues"] == []


def test_a_build_still_refused_after_two_send_backs_says_so_in_its_facts(api):
    api.post("/v1/agents").respond(201, json=AGENT)
    api.get(f"/v1/workflows/{WF}").respond(json=workflow(issues=[INVALID]))
    api.get(f"/v1/workflows/{WF}/graph").mock(side_effect=versions(3, 4))
    sent = replies(api, "Done.", "Done again.", "It can't be fixed: the address is unknown.")

    built = agent.build(WF, "Email me my calendar.")

    assert sent.call_count == 1 + definition.SEND_BACKS and built.sent_back == ["rejected", "rejected"]
    assert built.readiness["issues"] == [INVALID] and built.built is True


def test_a_build_that_built_nothing_is_sent_back_once(api):
    api.post("/v1/agents").respond(201, json=AGENT)
    api.get(f"/v1/workflows/{WF}").respond(json=workflow(steps=()))
    api.get(f"/v1/workflows/{WF}/graph").mock(side_effect=versions(3))
    sent = replies(api, "I built the workflow.", "The request needs no steps.")

    built = agent.build(WF, "Email me my calendar.")

    assert sent.call_count == 2 and body(sent.calls.last.request)["text"] == definition.NOTHING_BUILT
    assert (built.built, built.sent_back, built.summary) == (False, ["nothing"], "The request needs no steps.")
