"""A required field whose expression resolves to nothing fails the node.

``{{ $('trigger').chat_id }}`` on a trigger that emits ``payload.from`` used
to evaluate to JS undefined, arrive at the config parse as None, be coerced
to "" for a str field, and reach the provider as an empty recipient — four
"successful" WhatsApp replies went to nobody (2026-09-10). The evaluator now
reports whole-field expressions that produced no value, and the execution
handler fails the node when such a field is REQUIRED, naming the missing key
and the keys the referenced output actually has.
"""

from unittest.mock import AsyncMock

import pytest

from nodes.core.base import ConfigValidationError, required_config_fields
from nodes.whatsapp_node import WhatsAppNode
from utils.expression_evaluator import (
    UnresolvedReference,
    describe_unresolved_reference,
    evaluate_expressions,
    evaluate_single_expression,
    unresolved_required_field_error,
)
from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

TRIGGER_OUTPUT = {
    "id": "evt_1",
    "event": "message",
    "payload": {"id": "false_12025550102@lid_3A95", "from": "12025550102@lid", "body": "Habari"},
}
NO_EVENT = {"status": "no_event", "action": "receive_message", "data": {}, "message": "No live event"}


# ============================================================================
# Evaluator: whole-field expressions that produce nothing are reported
# ============================================================================


async def test_missing_key_is_reported_and_the_field_comes_back_empty():
    unresolved = []
    out = await evaluate_expressions(
        {"to": "{{ $('t').chat_id }}", "body": "{{ $('t').payload.body }}"},
        {"t": TRIGGER_OUTPUT}, unresolved=unresolved,
    )
    assert out == {"to": None, "body": "Habari"}
    assert unresolved == [UnresolvedReference("to", "$('t').chat_id", "undefined")]


async def test_null_value_is_reported_with_its_own_reason():
    unresolved = []
    out = await evaluate_expressions({"to": "{{ $('t').phone }}"}, {"t": {"phone": None}}, unresolved=unresolved)
    assert out == {"to": None}
    assert unresolved == [UnresolvedReference("to", "$('t').phone", "null")]


@pytest.mark.parametrize("value", [0, False, "", [], {}])
async def test_falsy_but_present_values_are_not_unresolved(value):
    unresolved = []
    out = await evaluate_expressions({"f": "{{ $('t').v }}"}, {"t": {"v": value}}, unresolved=unresolved)
    assert out == {"f": value}
    assert unresolved == []


async def test_partial_interpolation_stays_lenient():
    unresolved = []
    out = await evaluate_expressions({"greeting": "Hi {{ $('t').name }}!"}, {"t": {}}, unresolved=unresolved)
    assert out == {"greeting": "Hi !"}
    assert unresolved == []


async def test_nested_paths_are_named():
    unresolved = []
    await evaluate_expressions(
        {"headers": [{"key": "X", "value": "{{ $('t').token }}"}], "meta": {"id": "{{ $('t').nope }}"}},
        {"t": {}}, unresolved=unresolved,
    )
    assert [r.path for r in unresolved] == ["headers[0].value", "meta.id"]


async def test_callers_that_pass_no_channel_are_unchanged():
    assert await evaluate_expressions({"to": "{{ $('t').chat_id }}"}, {"t": TRIGGER_OUTPUT}) == {"to": None}
    assert await evaluate_single_expression("$('t').chat_id", {"t": TRIGGER_OUTPUT}) is None


async def test_trailing_line_comment_in_an_expression_still_evaluates():
    out = await evaluate_expressions({"f": "{{ $('t').payload.body // the text }}"}, {"t": TRIGGER_OUTPUT})
    assert out == {"f": "Habari"}


# ============================================================================
# The message names the missing key and what exists instead
# ============================================================================


def test_describe_names_the_missing_key_and_the_real_keys():
    msg = describe_unresolved_reference(
        UnresolvedReference("to", "$('t').chat_id", "undefined"), {"t": TRIGGER_OUTPUT}
    )
    assert msg == (
        "{{ $('t').chat_id }} resolved to nothing: node 't' output has no key 'chat_id' "
        "(its top-level keys are: id, event, payload)"
    )


def test_describe_bracket_access_and_null():
    assert "has no key 'chat id'" in describe_unresolved_reference(
        UnresolvedReference("to", "$('t')['chat id']", "undefined"), {"t": TRIGGER_OUTPUT}
    )
    assert describe_unresolved_reference(
        UnresolvedReference("to", "$('t').phone", "null"), {"t": {"phone": None}}
    ) == "{{ $('t').phone }} resolved to nothing: in node 't' output 'phone' is null"


def test_describe_explains_a_manual_runs_no_event_placeholder():
    msg = describe_unresolved_reference(
        UnresolvedReference("to", "$('t').payload.senderPhone", "undefined"), {"t": NO_EVENT}
    )
    assert "has no live event in this run" in msg and "real message/webhook" in msg


def test_describe_clips_long_key_lists_and_handles_non_objects():
    wide = {f"k{i}": i for i in range(20)}
    msg = describe_unresolved_reference(UnresolvedReference("f", "$('t').zz", "undefined"), {"t": wide})
    assert "k11, … (+8 more)" in msg
    msg = describe_unresolved_reference(UnresolvedReference("f", "$('t').zz", "undefined"), {"t": [1, 2]})
    assert "it is a list of 2 items" in msg


def test_only_required_fields_fail():
    refs = [
        UnresolvedReference("to", "$('t').chat_id", "undefined"),
        UnresolvedReference("reply_to_message_id", "$('t').message_id", "undefined"),
    ]
    outputs = {"t": TRIGGER_OUTPUT}
    assert unresolved_required_field_error(refs, {"reply_to_message_id"}, outputs) == (
        "Required field 'reply_to_message_id' is empty — {{ $('t').message_id }} resolved to nothing: "
        "node 't' output has no key 'message_id' (its top-level keys are: id, event, payload)"
    )
    assert unresolved_required_field_error(refs, {"body"}, outputs) is None
    assert unresolved_required_field_error([], {"to"}, outputs) is None


# ============================================================================
# Required fields come from the node's own model, per operation
# ============================================================================


def test_required_fields_follow_the_selected_operation():
    send = WhatsAppNode.required_config_fields({"operation": "send_text_message", "to": "x"})
    assert {"to", "body"} <= send and "preview_url" not in send and "reply_to_message_id" not in send
    receive = WhatsAppNode.required_config_fields({"operation": "receive_message"})
    assert "to" not in receive


def test_required_fields_without_a_model_is_empty():
    class Modelless:
        @classmethod
        def get_config_model(cls):
            return None

    from nodes.core.base import WorkflowNode

    assert WorkflowNode.required_config_fields.__func__(Modelless, {"x": 1}) == frozenset()
    assert required_config_fields({"operation": "send_text_message"}, None) == frozenset()


# ============================================================================
# The execution handler fails the node before anything else runs
# ============================================================================


def _send_node(**config):
    return {
        "id": "wa_send",
        "type": "automation-whatsapp",
        "config": {"operation": "send_text_message", "body": "{{ $('trig').payload.body }}", **config},
    }


WORKFLOW_NODES = [{"id": "trig", "type": "automation-whatsapp"}, _send_node(to="{{ $('trig').chat_id }}")]
WORKFLOW_EDGES = [{"source": "trig", "target": "wa_send"}]


async def test_execute_node_fails_a_required_field_that_resolved_to_nothing():
    handler = WorkflowExecutionHandler(sio=AsyncMock())
    with pytest.raises(ConfigValidationError) as exc:
        await handler._execute_node(
            _send_node(to="{{ $('trig').chat_id }}"), {"trig": TRIGGER_OUTPUT},
            sid="sid", user_id="u", workflow_id="wf",
            workflow_nodes=WORKFLOW_NODES, workflow_edges=WORKFLOW_EDGES,
        )
    msg = str(exc.value)
    assert msg.startswith("Required field 'to' is empty")
    assert "has no key 'chat_id'" in msg and "payload" in msg


def test_optional_field_resolving_to_nothing_is_not_an_error():
    WorkflowExecutionHandler._raise_on_unresolved_required_refs(
        "wa_send", "automation-whatsapp", _send_node(to="12025550102@lid")["config"],
        [UnresolvedReference("reply_to_message_id", "$('trig').message_id", "undefined")],
        {"trig": TRIGGER_OUTPUT}, WORKFLOW_NODES, WORKFLOW_EDGES,
    )


def test_tool_provider_nodes_are_exempt():
    provider_edges = [{"source": "wa_send", "target": "agent", "sourceHandle": "top", "targetHandle": "bottom"}]
    nodes = [_send_node(to="{{ $('trig').chat_id }}"), {"id": "agent", "type": "agent"}]
    WorkflowExecutionHandler._raise_on_unresolved_required_refs(
        "wa_send", "automation-whatsapp", nodes[0]["config"],
        [UnresolvedReference("to", "$('trig').chat_id", "undefined")],
        {"trig": TRIGGER_OUTPUT}, nodes, provider_edges,
    )
