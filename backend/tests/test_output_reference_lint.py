"""References to keys a node's output does not have are caught at write time.

The AI builder drafted `to={{ $('whatsapp_62d5').chat_id }}` for a WhatsApp
reply while the trigger's stored output carried `payload.from`; the value
resolved to nothing and the send went to nobody (2026-09-10). Known output
keys — this workflow's latest stored output, else the shape learned across
runs — ride GraphState._output_keys, and both the <field> write path and the
done-gate judge `$('node').key` reads against them. An unknown shape is
never judged.
"""

import pytest

from coder.workflow.agentic.commands import execute_field_ops
from coder.workflow.graph_state import GraphState
from coder.workflow.workflow_ops import (
    PROVIDER_TARGET_HANDLE,
    find_unknown_output_references,
    output_top_level_keys,
    unknown_output_reference_error,
)
from coder.workflow.workflow_xml import parse_xml

TRIGGER_KEYS = ["id", "event", "payload", "me"]
KNOWN = {"trig": TRIGGER_KEYS, "agent": ["response", "status"]}


# ============================================================================
# Pure helpers
# ============================================================================


def test_output_keys_come_from_objects_only():
    assert output_top_level_keys({"id": 1, "payload": {}}) == ["id", "payload"]
    assert output_top_level_keys({"status": "no_event", "data": {}}) is None  # a placeholder, not a shape
    assert output_top_level_keys([1, 2]) is None
    assert output_top_level_keys(None) is None


def test_unknown_first_key_is_flagged_with_the_real_keys():
    hits = find_unknown_output_references({"to": "{{ $('trig').chat_id }}"}, KNOWN)
    assert hits == [("to", "trig", "chat_id", TRIGGER_KEYS)]


@pytest.mark.parametrize("value", [
    "{{ $('trig').payload.senderPhone }}",   # judged on the first key only
    "{{ $('trig')['payload'].from }}",
    "{{ $('trig').toString() }}",            # a method call, not a field
    "{{ $('unknown').anything }}",           # shape unknown → never judged
    "{{ $('trig') }}",                       # the whole output
    "plain text without expressions",
])
def test_references_that_are_not_wrong_pass(value):
    assert find_unknown_output_references({"f": value}, KNOWN) == []


def test_nested_fields_bracket_keys_and_skip_fields():
    config = {
        "headers": [{"key": "X", "value": "{{ $('trig')['chatId'] }}"}],
        "code": "{{ $('trig').nope }}",
    }
    hits = find_unknown_output_references(config, KNOWN, skip_fields=frozenset({"code"}))
    assert hits == [("headers[0].value", "trig", "chatId", TRIGGER_KEYS)]


def test_error_message_names_the_fix():
    msg = unknown_output_reference_error("to", "trig", "chat_id", TRIGGER_KEYS)
    assert msg == (
        "Field 'to' reads $('trig').chat_id, but that node's output has no key 'chat_id' — it "
        "resolves to nothing at run time. Its keys are: id, event, payload, me. Reference one of "
        "those, or <get_output node=\"trig\" /> to see the stored output."
    )
    assert unknown_output_reference_error("f", "n", "k", [f"k{i}" for i in range(20)]).count(", …") == 1


# ============================================================================
# The <field> write path
# ============================================================================


def _graph(output_keys=None):
    g = GraphState()
    g.add_node("trig", "automation-whatsapp", "Incoming")
    g.add_node("wa", "automation-whatsapp", "Reply")
    g.add_edge("trig", "wa")
    g.get_node("trig").operation = "receive_message"
    g.get_node("wa").operation = "send_text_message"
    g._output_keys = output_keys if output_keys is not None else {"trig": TRIGGER_KEYS}
    return g


def test_field_write_reports_an_unknown_key_and_keeps_the_value():
    g = _graph()
    results = execute_field_ops(parse_xml('<field name="to" node="wa">{{ $(\'trig\').chat_id }}</field>'), g)
    assert any(r.startswith("REFERENCE ERROR for wa.to: Field 'to' reads $('trig').chat_id") for r in results)
    assert g.get_node("wa").config["to"] == "{{ $('trig').chat_id }}"  # advisory: the brain rewrites it


def test_field_write_with_a_known_key_or_unknown_shape_is_quiet():
    for g in (_graph(), _graph(output_keys={})):
        results = execute_field_ops(parse_xml('<field name="to" node="wa">{{ $(\'trig\').payload }}</field>'), g)
        assert not any("REFERENCE ERROR" in r for r in results)
