"""A build keeps what a workflow says about itself true: its description and its steps' labels.

Replays a platform MCP session: ``workflows_save`` built a "weekday 8 AM" automation, a later
``workflows_save`` moved it to 9 AM America/Chicago, and ``fetch`` still read the description
"...at 8 AM..." over a trigger named "Weekday 8 AM". The builder brain writes both: it reads the
description in the workflow's snapshot, rewrites it with ``<set_description>``, and a write that
changes a trigger's settings under its old label says so.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from coder.workflow.agentic.commands import AGENTIC_TAGS, execute_description_ops, execute_field_ops
from coder.workflow.graph_state import GraphState, NodeState
from coder.workflow.workflow_xml import ALL_TAGS, _BODY_TAGS, parse_xml

TRIGGER = "weekday_8am"
DESCRIPTION = "Every weekday at 8 AM, email me today's calendar."
EIGHT = [{"frequency": "days", "hour": 8, "minute": 0, "daysOfWeek": [1, 2, 3, 4, 5]}]
NINE = '[{"frequency": "days", "hour": 9, "minute": 0, "daysOfWeek": [1, 2, 3, 4, 5]}]'


def _state(description=DESCRIPTION) -> GraphState:
    state = GraphState()
    state.nodes[TRIGGER] = NodeState(
        id=TRIGGER, type="trigger-cron", label="Weekday 8 AM", goal="Start every weekday at 8 AM",
        operation="default", config={"schedules": EIGHT, "timezone": "UTC"},
    )
    state.nodes["mail"] = NodeState(id="mail", type="log", label="Email the calendar", goal="Email it",
                                    operation="default", config={})
    state.workflow_description = description
    return state


def _move_to_nine(state, extra=""):
    return execute_field_ops(parse_xml(
        f"<field name=\"schedules\" node=\"{TRIGGER}\" value='{NINE}'/>"
        f'<field name="timezone" node="{TRIGGER}" value="America/Chicago"/>{extra}'
    ), state)


class TestTheBrainReadsAndWritesTheDescription:
    def test_the_tag_is_the_builders_alone(self):
        from mcp_server import _UPDATE_WORKFLOW_TAGS

        assert "set_description" in ALL_TAGS and "set_description" in _BODY_TAGS
        assert "set_description" in AGENTIC_TAGS
        # The workflow MCP server changes a description with its update_workflow_metadata tool.
        assert "set_description" not in _UPDATE_WORKFLOW_TAGS

    def test_the_snapshot_shows_the_description(self):
        state = _state('Weekdays at 8 AM, "the brief"')
        assert state.to_xml().splitlines()[0] == '<workflow description="Weekdays at 8 AM, &quot;the brief&quot;">'
        assert _state(None).to_xml().splitlines()[0] == "<workflow>"

    def test_set_description_rewrites_it_as_one_line(self):
        state = _state()
        results = execute_description_ops(parse_xml(
            "<set_description>Every weekday at 9 AM Central,\n emails me today's calendar.</set_description>"
        ), state)
        line = "Every weekday at 9 AM Central, emails me today's calendar."
        assert state.workflow_description == line and state.written_description == line
        assert results == [f"Set the workflow's description: {line!r}"]
        assert state.to_xml().splitlines()[0] == f'<workflow description="{line}">'

    @pytest.mark.parametrize("body", ["", "   ", "x" * 301])
    def test_an_empty_or_long_description_is_refused(self, body):
        state = _state()
        results = execute_description_ops(parse_xml(f"<set_description>{body}</set_description>"), state)
        assert results[0].startswith("ERROR: set_description")
        assert state.workflow_description == DESCRIPTION and state.written_description is None


class TestAStaleLabelIsNamed:
    def test_moving_the_schedule_names_the_label_it_left_behind(self):
        state = _state()
        results = _move_to_nine(state)
        notes = [r for r in results if "Weekday 8 AM" in r]
        assert len(notes) == 1
        assert f'<field name="label" node="{TRIGGER}">' in notes[0] and "<set_description>" in notes[0]

    def test_a_label_written_with_the_change_is_not_questioned(self):
        state = _state()
        results = _move_to_nine(state, f'<field name="label" node="{TRIGGER}" value="Weekday 9 AM"/>')
        assert state.nodes[TRIGGER].config["label"] == "Weekday 9 AM"
        assert not [r for r in results if "still labeled" in r]

    def test_steps_that_start_nothing_keep_their_labels_unquestioned(self):
        state = _state()
        state.nodes["mail"].config["message"] = "old"
        results = execute_field_ops(parse_xml('<field name="message" node="mail" value="new"/>'), state)
        assert not [r for r in results if "still labeled" in r]


def _persisting_handler():
    from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

    handler = WorkflowBuilderHandler(MagicMock())
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"workflow": {"nodes": [], "edges": []}, "name": "Morning brief"})
    pool = MagicMock(acquire=MagicMock(return_value=MagicMock(
        __aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=False),
    )))
    handler.get_pool = AsyncMock(return_value=pool)
    return handler, AsyncMock(return_value={"id": "wf"})


class TestTheBuildSavesIt:
    @pytest.mark.asyncio
    async def test_the_persist_writes_the_description_the_brain_wrote_once(self, monkeypatch):
        handler, save = _persisting_handler()
        monkeypatch.setattr("wss.handlers.workflow_builder_handler.WorkflowRepo",
                            lambda _pool: MagicMock(update_workflow_dynamic=save))
        state = _state()
        execute_description_ops(parse_xml("<set_description>Weekdays at 9 AM Central.</set_description>"), state)

        await handler._persist_builder_graph_for(str(uuid.uuid4()), SimpleNamespace(graph_state=state), "owner-1")
        assert save.await_args.kwargs["description"] == "Weekdays at 9 AM Central."
        assert state.written_description is None and state.workflow_description == "Weekdays at 9 AM Central."

        await handler._persist_builder_graph_for(str(uuid.uuid4()), SimpleNamespace(graph_state=state), "owner-1")
        assert save.await_args.kwargs["description"] is None


class TestThePromptSaysIt:
    def test_the_default_pack_teaches_the_command_and_the_rule(self):
        from coder.workflow.agentic import prompts_default

        stable, _ = prompts_default.build_system_prompt_parts()
        assert "<set_description>" in stable and "untrue" in stable
