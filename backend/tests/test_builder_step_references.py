"""A drafted read of a key a step's output doesn't have, or of a step that isn't there, is caught before a build
says done; and a build that added nothing doesn't finish as built.

A first build of an email digest wrote the email step's body as {{ $('select_and_explain').body }}: the agent answers
in `response`, and every scheduled run failed on an empty body. Nothing had run, so no shape was known to judge the
read by (an agent's output is fixed by its code; it now says so). A contact-form build wrote {{trigger.name}}: no step
is called `trigger`, so it went out as that literal text. A third build queried a few operations, added no step, and
said it had set up the digest and sent a test.

These run against whichever builder the tree ships (the hosted one here, the open edition's in its tree).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from coder.workflow.agentic.builder import EXEC_RESULT_MARKER, AgenticBuilder
from coder.workflow.agentic.commands import build_execution_summary, execute_field_ops
from coder.workflow.graph_state import GraphState
from coder.workflow.workflow_ops import (
    find_missing_node_references,
    find_unknown_output_references,
    known_output_keys,
    step_reference_errors,
)
from coder.workflow.workflow_xml import parse_xml
from nodes.agent_node import AgentNode

_WORKED = [{"role": "user", "content": f"{EXEC_RESULT_MARKER}\nqueried operations"}]


def _digest() -> GraphState:
    """The reported first build: schedule → agent → Send email, nothing run yet."""
    g = GraphState()
    g.add_node("weekday_8pm", "trigger-cron", "Weekdays at 8 PM")
    g.add_node("select_and_explain", "agent", "Select and explain the top five")
    g.add_node("email_roundup", "automation-send-email", "Email the roundup")
    g.add_edge("weekday_8pm", "select_and_explain")
    g.add_edge("select_and_explain", "email_roundup")
    g.get_node("weekday_8pm").operation = "default"
    agent = g.get_node("select_and_explain")
    agent.operation, agent.config = "default", {"operation": "default", "message": "Pick five stories."}
    email = g.get_node("email_roundup")
    email.operation = "send"
    email.config = {"operation": "send", "subject": "Today's top 5", "body": "{{ $('select_and_explain').body }}"}
    return g


# ── What an agent's output holds ─────────────────────────────────────────────


def test_an_agent_declares_its_output_for_a_model_it_runs_itself():
    keys = AgentNode.declared_output_keys({"model": "openrouter/openai/gpt-5.4-mini"})
    assert {"response", "status", "error"} <= set(keys) and "body" not in keys
    assert "images" in AgentNode.declared_output_keys({"model_type": "image", "model": "openai/gpt-image-1"})
    # A coding harness reports what its harness does: only a run shows it.
    assert AgentNode.declared_output_keys({"model": "codex"}) is None
    assert AgentNode.declared_output_keys({"model_type": "opencode"}) is None


def test_a_first_build_knows_the_agent_answers_in_response():
    g = _digest()
    known = known_output_keys(g.nodes.values(), {})
    hits = find_unknown_output_references(g.get_node("email_roundup").config, known)
    assert [(path, node, key) for path, node, key, _ in hits] == [("body", "select_and_explain", "body")]
    g.get_node("email_roundup").config["body"] = "{{ $('select_and_explain').response }}"
    assert find_unknown_output_references(g.get_node("email_roundup").config, known) == []


def test_a_path_read_is_judged_like_an_expression():
    known = {"select_and_explain": ["type", "status", "response"]}
    assert find_unknown_output_references({"body": "Top: {{select_and_explain.body}}"}, known)[0][2] == "body"
    assert find_unknown_output_references({"body": "{{select_and_explain.response.title}}"}, known) == []


# ── Reads of a step that isn't there ─────────────────────────────────────────


def test_reads_of_a_step_that_isnt_there_are_found():
    steps = {"contact_webhook", "email_owner"}
    config = {
        "body": "**Name:** {{trigger.name}}\n**Email:** {{ $('form').email }}",
        "subject": "From {{contact_webhook.name}} ({{ $('contact_webhook').email }})",
        "reply_to": "{{contact_webhok.email}} {{ $('Contact_Webhook').email }}",
    }
    assert find_missing_node_references(config, steps) == [
        ("body", "{{trigger.name}}", "trigger", None),             # a name drafters use for no step
        ("body", "{{ $('form').email }}", "form", None),           # $('…') of no step always fails the run
        ("reply_to", "{{contact_webhok.email}}", "contact_webhok", "contact_webhook"),  # a slip of a step id
        ("reply_to", "{{ $('Contact_Webhook').email }}", "Contact_Webhook", "contact_webhook"),
    ]


@pytest.mark.parametrize("value", [
    "{{vars.recipient}}",                  # the workflow's variables
    "{{ $vars.recipient }}",
    "Dear {{name}},",                      # a bare word may be another system's template
    "{{ $json.email }}",
    "{{ $now }}",
    "{{ background: '#fff' }}",            # an object literal, not a read
    "{{contact_webhook.name}}",
    "{{item.name}}", "{{ item.email }}",   # an iteration step's loop variables
    "{{index}} of {{total}}", "{{items[0].id}}", "{{row_number}}",
    "token: ${{ secrets.GITHUB_TOKEN }}",  # a CI system's, passed through as text
    "Hi {{ contact.FIRSTNAME }}",          # another system's template
    "Dear {{ customer.first_name }},",
])
def test_what_isnt_a_read_of_a_missing_step_passes(value):
    assert find_missing_node_references({"f": value}, {"contact_webhook"}) == []


def test_one_check_reports_both_and_names_the_steps_there_are():
    g = _digest()
    g.get_node("email_roundup").config["subject"] = "{{trigger.date}}"
    errors = dict(step_reference_errors(g.get_node("email_roundup"), set(g.nodes),
                                        known_output_keys(g.nodes.values(), {})))
    assert "has no key 'body'" in errors["body"]
    assert "no step 'trigger'" in errors["subject"] and "literal text" in errors["subject"]
    assert "email_roundup, select_and_explain, weekday_8pm" in errors["subject"]


# ── Where the builder judges them ────────────────────────────────────────────


def test_a_field_write_reports_both_on_a_first_build():
    g = _digest()
    results = execute_field_ops(parse_xml(
        '<field name="body" node="email_roundup">{{ $(\'select_and_explain\').body }}</field>'
        '<field name="subject" node="email_roundup">New message from {{trigger.name}}</field>'
    ), g)
    assert any(r.startswith("REFERENCE ERROR for email_roundup.body") and "no key 'body'" in r for r in results)
    assert any(r.startswith("REFERENCE ERROR for email_roundup.subject") and "no step 'trigger'" in r
               for r in results)


def test_what_drafting_wrote_is_judged_in_its_summary():
    g = _digest()
    summary = build_execution_summary(g, [], ["email_roundup"], [], [], ["email_roundup"])
    assert "[reference error:" in summary and "no key 'body'" in summary


def _builder(graph: GraphState, messages=None, must_build=False, written=None) -> AgenticBuilder:
    b = object.__new__(AgenticBuilder)
    b.messages = list(_WORKED if messages is None else messages)
    b.graph_state = graph
    b._must_build = must_build
    b._written_steps = set(graph.nodes) if written is None else set(written)
    return b


def test_done_waits_on_a_broken_read_this_build_wrote():
    nudge = _builder(_digest())._config_done_nudge()
    assert nudge and "email_roundup.body" in nudge and "no key 'body'" in nudge
    # Editing another step leaves a step it didn't touch alone: its reads are another build's, or the person's.
    assert _builder(_digest(), written={"select_and_explain"})._config_done_nudge() is None


def test_a_build_request_on_an_empty_workflow_that_adds_nothing_waits_once():
    from coder.workflow.requests import must_build

    empty = GraphState()
    empty.add_node("note", "stickyNote", "A note")  # a note isn't a step
    b = _builder(empty, must_build=True)
    assert b._gate_on_nothing_built("Done") is True
    assert b._NOTHING_BUILT_MARKER in b.messages[-1]["content"] and "no steps" in b.messages[-1]["content"]
    assert b._last_turn_result.next_action == "continue"
    assert b._gate_on_nothing_built("Done") is False  # once: then it may say why
    # Built something, or a question answered on a canvas (the person sees it): nothing to hold.
    assert _builder(_digest(), must_build=True)._gate_on_nothing_built("Done") is False
    assert _builder(GraphState())._gate_on_nothing_built("Done") is False
    # Only a build request on a workflow that began with no steps must build: emptying one is a build too, and a
    # request from before this was recorded is never judged.
    request = {"builder_request_id": "r1"}
    assert must_build({**request, "began_empty": True})
    assert not must_build({**request, "began_empty": False}) and not must_build(request)
    assert not must_build({"began_empty": True})


# ── What a finished build reports ────────────────────────────────────────────


def test_a_build_reports_its_steps_and_what_it_ran_by_step():
    from coder.workflow.requests import build_facts
    from wss.handlers.workflow_builder_handler import record_build_run

    ran = {}
    record_build_run(ran, "select_and_explain", {"success": True, "ran": {"email_roundup": "error"}})
    record_build_run(ran, "weekday_8pm", {"error": "Node weekday_8pm didn't run.", "failed_node": "other"})
    graph = _digest()
    graph.add_node("note", "stickyNote", "Why")
    facts = build_facts(graph.nodes.values(), ran)
    assert facts["steps"] == {"weekday_8pm": "Weekdays at 8 PM", "select_and_explain": "Select and explain the top five",
                              "email_roundup": "Email the roundup"}
    assert facts["ran"] == {"select_and_explain": "completed", "email_roundup": "failed"}


@pytest.mark.asyncio
async def test_a_build_that_added_nothing_is_not_a_success(monkeypatch):
    from coder.workflow import requests
    from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

    recorded = AsyncMock()
    monkeypatch.setattr(requests, "record_result", recorded)
    handler = object.__new__(WorkflowBuilderHandler)
    handler.get_pool = AsyncMock(return_value=object())
    claim = "The workflow is set up, and I sent a one-time test digest to your account."
    builder = SimpleNamespace(last_words=claim, graph_state=GraphState(), platform_ops=SimpleNamespace(ran={}))
    asked = {"builder_request_id": "r1", "builder_attempt_id": "a1"}
    request = SimpleNamespace(user_context={**asked, "began_empty": True}, current_graph={"nodes": [], "edges": []})

    await handler._maybe_notify_agent_result(request=request, user_id="u1", builder=builder, segments=[])
    kwargs = recorded.await_args.kwargs
    assert kwargs["success"] is False and kwargs["error"] == requests.NOTHING_BUILT
    assert claim not in kwargs["summary"] and kwargs["facts"] == {"steps": {}, "ran": {}}

    # Emptying a workflow that had steps is what was asked, though this attempt (resumed after an earlier one
    # emptied it) began with none: judged by how the request began, it finishes as asked.
    request.user_context = {**asked, "began_empty": False}
    await handler._maybe_notify_agent_result(request=request, user_id="u1", builder=builder, segments=[])
    assert recorded.await_args.kwargs["success"] is True
    request.user_context = asked  # a request from before the start was recorded
    await handler._maybe_notify_agent_result(request=request, user_id="u1", builder=builder, segments=[])
    assert recorded.await_args.kwargs["success"] is True
