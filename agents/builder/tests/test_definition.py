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


def test_the_instructions_name_only_calls_the_builder_can_make():
    text = definition.instructions()
    # The operations it's told to call, each one a /v1 operation in an area its tools reach.
    named = set(re.findall(r"`((?:workflows|step_types|connections|workflow_examples)_[a-z_]+)", text))
    assert named == {
        "workflows_graph", "workflows_edits_create", "workflows_drafts_create", "workflows_get",
        "workflows_runs_create", "workflows_steps_outputs_get", "workflows_rehearsals_create",
        "workflows_steps_publish", "step_types_list", "step_types_get", "connections_list",
    }
    for tool in ("noclick__api_call", "noclick__api_describe", "noclick__search", "noclick__fetch", "human__ask"):
        assert tool in text
