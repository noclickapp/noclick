"""The builder's definition: what the agent is, with no dependency, and that the SDK says the same thing."""

import asyncio
import re

import pytest

from noclick_builder import agent, definition


def test_the_wire_tools_are_what_the_sdk_objects_serialize_to():
    refs = []
    for tool in agent.sdk_tools():
        refs.extend([tool] if isinstance(tool, str) else asyncio.run(tool._tool_refs(None)))
    assert refs == definition.wire_tools()


def test_it_builds_and_asks_and_never_spends():
    tools = definition.wire_tools()
    assert "noclick.build" in tools and "noclick.workflows" in tools
    assert "noclick.spend" not in tools and "noclick" not in tools
    assert {"human": {"owner": True}, "tools": ["notify", "ask"]} in tools


def test_a_workflows_builds_share_one_conversation():
    assert definition.conversation("wf_1") == "build:wf_1"
    assert definition.conversation("wf_1") != definition.conversation("wf_2")


def test_a_request_names_the_workflow_and_what_to_do():
    text = definition.request("wf_1", "  Email me my calendar at 8.  ", name="Morning brief")
    assert text.startswith('Build request for workflow "Morning brief" (id wf_1).')
    assert "Email me my calendar at 8." in text and "Ask nothing" not in text


def test_a_request_can_say_to_ask_nothing_and_to_publish():
    text = definition.request("wf_1", "A sign-up form", questions=definition.ASSUME,
                              publish={"subdomain": "signup"})
    assert "Ask nothing in this build" in text and "what you assumed" in text
    assert "publish its interface at the subdomain signup" in text


@pytest.mark.parametrize("bad", [{"questions": "maybe"}, {"instructions": "   "}])
def test_a_request_that_cant_be_made_is_refused(bad):
    with pytest.raises(ValueError):
        definition.request("wf_1", bad.get("instructions", "Build it"), questions=bad.get("questions", "ask"))


def test_a_build_sent_back_hears_each_step_and_why():
    text = definition.sent_back([{"step": "send", "message": "to: field required"},
                                 {"step": "post", "message": "channel: field required"}])
    assert "- send: to: field required" in text and "- post: channel: field required" in text


def test_a_build_sent_back_leaves_what_only_the_person_knows_for_them():
    """A value only the person knows isn't the builder's to make up, nor a reason to ask again what was skipped:
    it's left for them with the edit that says so, and that settles it."""
    issue = [{"step": "check", "message": "url is required"}]
    text = definition.sent_back(issue)
    assert "left_for_user" in text and "isn't yours to fix or make up" in text
    assert "asking only where" not in text
    assert "don't ask for anything now" not in text
    assert "don't ask for anything now" in definition.sent_back(issue, skipped=True)


def test_the_instructions_name_only_calls_the_builder_can_make():
    text = definition.instructions()
    # The operations it's told to call, each one a /v1 operation in an area its tools reach.
    named = set(re.findall(r"`((?:workflows|step_types|connections|workflow_examples|operations)_[a-z_]+)", text))
    assert named == {
        "workflows_graph", "workflows_edits_create", "workflows_drafts_create", "workflows_get",
        "workflows_runs_create", "workflows_steps_outputs_get", "workflows_steps_outputs_list",
        "workflows_rehearsals_create", "workflows_steps_publish", "step_types_list", "step_types_get",
        "connections_list", "operations_wait",
    }
    for tool in ("noclick__api_call", "noclick__api_describe", "noclick__search", "noclick__fetch", "human__ask"):
        assert tool in text


def test_the_instructions_give_each_routine_call_its_exact_arguments():
    """The calls every build makes are written out with their arguments, so a build makes them without looking
    them up: an edit is a list of objects each naming its ``op``, and a draft or a run is waited for in the turn."""
    text = definition.instructions()
    assert "## The calls, exactly" in text
    for shape in ('{op: "add_step", type, id, name}', '{op: "connect", from, to}',
                  'left_for_user: [names]', "`operations_wait {operation_id, timeout_s: 60}`",
                  "`connections_list {integration}`",
                  "`workflows_steps_outputs_get {workflow_id, step_id, run_id, full}`"):
        assert shape in text, shape


def test_a_value_only_the_person_knows_is_left_for_them_never_made_up():
    text = definition.instructions()
    assert '`update_step {id, left_for_user: ["url"]}`' in text
    assert "never store a made-up value in its place" in text
    # A conditional's edge names its branch, and an app's own event starts from the app.
    assert "a `conditional` has `true` and `false`" in text
    assert "An event in an app starts from that app" in text
    assert "An app with no trigger for the event is watched on a schedule" in text
    assert "comes first in your reply" in text


def test_a_test_run_is_of_one_step_alone():
    """A run from a step goes on through every step after it unless it's asked for alone: the builder tests a step
    with ``only``, so reading what a fetch returned never sends the email after it."""
    text = definition.instructions()
    assert "`workflows_runs_create {workflow_id, from_step, only: true}`" in text
    assert "Always pass `only: true` to test a step" in text
    assert "Never run a step that sends, writes, pays or deletes unless the request asks for a real test" in text


def test_a_build_goes_back_for_what_a_run_would_refuse_twice_and_for_nothing_built_once():
    issue = [{"step": "send", "message": "to: field required"}]
    assert definition.send_back(built=True, empty=False, rejected=issue, sent=[]) == definition.REJECTED
    assert definition.send_back(built=True, empty=False, rejected=issue, sent=["rejected"]) == definition.REJECTED
    assert definition.send_back(built=True, empty=False, rejected=issue, sent=["rejected", "rejected"]) is None
    assert definition.send_back(built=False, empty=True, rejected=[], sent=[]) == definition.NOTHING
    assert definition.send_back(built=False, empty=True, rejected=[], sent=["nothing"]) is None
    # What couldn't be read is never taken for nothing built.
    assert definition.send_back(built=None, empty=True, rejected=[], sent=[]) is None
    assert definition.send_back(built=True, empty=False, rejected=[], sent=[]) is None


READ = {"step": "log_text", "field": "rows[0].zen_text", "source": "fetch_zen", "key": "body",
        "known_keys": ["status_code", "response"],
        "message": "Log zen text (`log_text`): `rows[0].zen_text` reads `body` from Fetch GitHub Zen (`fetch_zen`), "
                   "whose output has no `body` (it has status_code, response): a run reads nothing there."}


def test_a_read_that_gets_no_value_goes_back_on_the_same_budget_as_what_a_run_would_refuse():
    """A read of a key the step's output lacks fails nothing: the run succeeds and the setting is empty. So the
    build goes back for it as for settings a run would refuse, twice at most counting both."""
    assert definition.send_back(built=True, empty=False, rejected=[], unresolved=[READ], sent=[]) == definition.REJECTED
    assert definition.send_back(built=True, empty=False, rejected=[], unresolved=[READ],
                                sent=["rejected"]) == definition.REJECTED
    assert definition.send_back(built=True, empty=False, rejected=[], unresolved=[READ],
                                sent=["rejected", "rejected"]) is None


def test_a_build_sent_back_for_a_read_hears_what_it_reads_and_what_the_step_has():
    text = definition.sent_back([], unresolved=[READ])
    assert f"- {READ['message']}" in text and "reads nothing" in text and "the run still succeeds" in text
    assert "will fail exactly as listed" not in text
    both = definition.sent_back([{"step": "send", "message": "to: field required"}], unresolved=[READ])
    assert "- send: to: field required" in both and f"- {READ['message']}" in both


def test_the_instructions_say_a_run_that_succeeded_doesnt_show_a_read_got_a_value():
    assert ("A test run that succeeded doesn't show that a read got a value: a `{{ $('step').key }}` whose key the "
            "step's output doesn't have reads nothing and the run still succeeds, so check the step's output has "
            "each key the next step reads.") in definition.instructions()
