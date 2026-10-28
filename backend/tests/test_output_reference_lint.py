"""References to keys a node's output does not have are caught at write time.

The AI builder drafted `to={{ $('whatsapp_62d5').chat_id }}` for a WhatsApp
reply while the trigger's stored output carried `payload.from`; the value
resolved to nothing and the send went to nobody (2026-09-10). Known output
keys — this workflow's latest stored output, else the shape learned across
runs — ride GraphState._output_keys, and both the <field> write path and the
done-gate judge `$('node').key` reads against them. An unknown shape is
never judged.
"""

import copy

import pytest

from coder.workflow.agentic.commands import execute_field_ops
from coder.workflow.graph_state import GraphState
from coder.workflow.workflow_ops import (
    PROVIDER_TARGET_HANDLE,
    declares_output_keys,
    find_output_references_to,
    find_unknown_output_references,
    known_output_keys,
    output_top_level_keys,
    unknown_output_reference_error,
)
from coder.workflow.workflow_xml import parse_xml
from nodes.http_request_node import HttpRequestNode
from nodes.serverless_function_node import ServerlessFunctionNode

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


# ============================================================================
# Shapes a node's code fixes, declared from its config
# ============================================================================
#
# A first build had no stored output, and the shape learned across every
# account's HTTP GETs (status, headers, `response`) was the full-response one:
# the drafter read `$('fetch').response` from a fetch set to return the body
# only, `{data}`, and every hourly run failed on null (2026-10-28).

# The most common learned shape for send_http_get_request (full response on).
LEARNED_HTTP_KEYS = ["url", "type", "method", "status", "is_file", "response", "is_base64", "timestamp",
                     "elapsed_ms", "status_code", "response_headers"]
FETCH = {"operation": "send_http_get_request", "url": "https://example.com",
         "full_response": "false", "response_format": "text"}
EXTRACT = {"operation": "run_javascript_function",
           "function_inputs": [{"name": "html", "value": "{{ $('fetch').response }}"}],
           "function_body": "return { title: html.match(/<title>(.*)<\\/title>/)[1] };"}


def test_http_request_declares_its_output_from_its_config():
    full = HttpRequestNode.declared_output_keys({"operation": "send_http_get_request"})
    assert {"status_code", "response", "response_headers"} <= set(full)  # full response is the default
    assert HttpRequestNode.declared_output_keys(FETCH) == ["data"]
    # A body-only JSON object is returned as is: its keys are the API's, which only a run shows.
    assert HttpRequestNode.declared_output_keys({**FETCH, "response_format": "auto"}) is None
    assert HttpRequestNode.declared_output_keys({**FETCH, "response_format": "json"}) is None
    # Kept as data, an error comes back in the full shape beside a body-only success.
    assert set(HttpRequestNode.declared_output_keys({**FETCH, "never_error": "true"})) >= {"data", "error", "status"}
    assert HttpRequestNode.declared_output_keys({**FETCH, "full_response": "{{ $vars.full }}"}) is None


def test_serverless_function_declares_its_envelope():
    js = ServerlessFunctionNode.declared_output_keys(EXTRACT)
    assert {"result", "stdout", "error", "exit_code"} <= set(js) and "title" not in js
    py = ServerlessFunctionNode.declared_output_keys({"operation": "run_python_function"})
    assert "result" in py and "hardware" in py
    assert ServerlessFunctionNode.declared_output_keys({}) is None


def test_only_nodes_that_declare_say_so():
    assert declares_output_keys("automation-http-request")
    assert declares_output_keys("automation-serverless-function")
    assert not declares_output_keys("automation-whatsapp")
    assert not declares_output_keys("no-such-node")


def _first_build():
    g = GraphState()
    g.add_node("hourly", "trigger-cron", "Every hour")
    g.add_node("fetch", "automation-http-request", "Fetch example.com")
    g.add_node("extract", "automation-serverless-function", "Extract snapshot fields")
    g.add_edge("hourly", "fetch")
    g.add_edge("fetch", "extract")
    g.get_node("fetch").operation, g.get_node("fetch").config = "send_http_get_request", copy.deepcopy(FETCH)
    g.get_node("extract").operation, g.get_node("extract").config = "run_javascript_function", copy.deepcopy(EXTRACT)
    return g


def test_a_declared_shape_wins_over_the_learned_one():
    g = _first_build()
    known = known_output_keys(g.nodes.values(), {"fetch": LEARNED_HTTP_KEYS, "hourly": ["timestamp"]})
    assert known["fetch"] == ["data"]
    assert known["hourly"] == ["timestamp"]  # no declaration: what was observed stands
    hits = find_unknown_output_references(g.get_node("extract").config, known)
    assert hits == [("function_inputs[0].value", "fetch", "response", ["data"])]
    g.get_node("extract").config["function_inputs"][0]["value"] = "{{ $('fetch').data }}"
    assert find_unknown_output_references(g.get_node("extract").config, known) == []


def test_a_first_build_is_judged_with_nothing_observed():
    g = _first_build()
    known = known_output_keys(g.nodes.values(), {})
    assert "hourly" not in known  # an undeclared shape stays unknown, never "no keys"
    assert find_unknown_output_references(g.get_node("extract").config, known)[0][2] == "response"


def test_references_to_named_nodes_are_found_with_their_paths():
    config = {"a": "{{ $('fetch').data }} and {{ $('trig').payload.x }}", "b": ["{{ $('fetch').toString() }}"]}
    assert find_output_references_to(config, {"fetch"}) == [("a", "fetch", "data")]
    assert find_output_references_to(config, set()) == []
