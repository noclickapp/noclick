"""Tests for inline expression evaluation in config fields.

Covers the three-way classification (legacy path / JS expression / literal
passthrough), the `$`-accessors, type-preservation, injection safety, error
surfacing, and the backward-compat guarantee that a config with no `$`-expression
triggers zero JS evaluation.
"""

import pytest
from unittest.mock import AsyncMock, patch

from utils.expression_evaluator import (
    ExpressionEvaluationError,
    evaluate_expressions,
    evaluate_single_expression,
    format_preview,
    is_legacy_path_reference,
)


NODE_OUTPUTS = {
    "node-1": {"csv": "alpha,beta,gamma", "count": 3, "tags": ["x", "y"]},
    "sheet": {"rows": [{"email": "a@x.com"}, {"email": "b@x.com"}]},
    "vars": {"threshold": 10, "name": "Ada"},
}


# --- classification -------------------------------------------------------

def test_is_legacy_path_reference():
    assert is_legacy_path_reference("node-1.csv", NODE_OUTPUTS)
    assert is_legacy_path_reference("node-1.tags[0]", NODE_OUTPUTS)
    assert is_legacy_path_reference("sheet.rows[].email", NODE_OUTPUTS)
    assert is_legacy_path_reference("vars.name", NODE_OUTPUTS)
    # Not legacy: unknown node, $-accessor, method call, arbitrary text.
    assert not is_legacy_path_reference("unknown.field", NODE_OUTPUTS)
    assert not is_legacy_path_reference("$('node-1').csv", NODE_OUTPUTS)
    assert not is_legacy_path_reference("node-1.csv.split(',')", NODE_OUTPUTS)
    assert not is_legacy_path_reference("name", NODE_OUTPUTS)


# --- expression evaluation ------------------------------------------------

async def test_string_method_split():
    out = await evaluate_expressions("{{ $('node-1').csv.split(',')[0] }}", NODE_OUTPUTS)
    assert out == "alpha"


async def test_arithmetic_preserves_number_type():
    out = await evaluate_expressions("{{ $('node-1').count * 2 + 1 }}", NODE_OUTPUTS)
    assert out == 7
    assert isinstance(out, int)


async def test_ternary():
    out = await evaluate_expressions("{{ $('node-1').count > 5 ? 'big' : 'small' }}", NODE_OUTPUTS)
    assert out == "small"


async def test_map_returns_list():
    out = await evaluate_expressions("{{ $('sheet').rows.map(r => r.email) }}", NODE_OUTPUTS)
    assert out == ["a@x.com", "b@x.com"]


async def test_vars_accessor():
    out = await evaluate_expressions("{{ $vars.threshold * 2 }}", NODE_OUTPUTS)
    assert out == 20


async def test_json_primary_input():
    out = await evaluate_expressions(
        "{{ $json.title.toUpperCase() }}", NODE_OUTPUTS, primary_input={"title": "hi"}
    )
    assert out == "HI"


async def test_label_accessor():
    workflow_nodes = [{"id": "node-1", "data": {"label": "My CSV"}}]
    out = await evaluate_expressions(
        "{{ $('My CSV').csv.split(',').length }}", NODE_OUTPUTS, workflow_nodes=workflow_nodes
    )
    assert out == 3


async def test_ifempty_on_missing_field():
    # $ifEmpty handles an empty/missing FIELD of a CONNECTED node.
    out = await evaluate_expressions("{{ $ifEmpty($('node-1').missing_field, 'fallback') }}", NODE_OUTPUTS)
    assert out == "fallback"


async def test_unknown_node_raises_clear_error():
    # A reference to a node that isn't connected/run fails with an actionable message
    # (the standard node-error pattern), not a cryptic downstream "undefined" error.
    with pytest.raises(ExpressionEvaluationError) as exc:
        await evaluate_expressions("{{ $('ghost').x }}", NODE_OUTPUTS)
    assert "ghost" in str(exc.value)
    assert "No data for node" in str(exc.value)


# --- type rules -----------------------------------------------------------

async def test_full_match_preserves_object():
    out = await evaluate_expressions("{{ $('node-1') }}", NODE_OUTPUTS)
    assert out == NODE_OUTPUTS["node-1"]
    assert isinstance(out, dict)


async def test_partial_match_stringifies():
    out = await evaluate_expressions("first={{ $('node-1').csv.split(',')[0] }}!", NODE_OUTPUTS)
    assert out == "first=alpha!"


async def test_partial_match_stringifies_array_as_json():
    out = await evaluate_expressions("tags: {{ $('node-1').tags }}", NODE_OUTPUTS)
    assert out == 'tags: ["x", "y"]'


async def test_multiple_expressions_in_one_string():
    out = await evaluate_expressions(
        "{{ $('node-1').count }} of {{ $('sheet').rows.length }}", NODE_OUTPUTS
    )
    assert out == "3 of 2"


# --- injection safety -----------------------------------------------------

async def test_embedded_data_cannot_break_out():
    # A node value containing JS-delimiter-ish characters must stay inert data.
    outputs = {"node-1": {"payload": '"}} ; while(true){} ; `${x}` //'}}
    out = await evaluate_expressions("{{ $('node-1').payload }}", outputs)
    assert out == '"}} ; while(true){} ; `${x}` //'


# --- errors ---------------------------------------------------------------

async def test_js_error_raises():
    with pytest.raises(ExpressionEvaluationError) as exc:
        await evaluate_expressions("{{ $('node-1').csv.nope() }}", NODE_OUTPUTS)
    assert "{{ $('node-1').csv.nope() }}" in str(exc.value)


async def test_timeout_raises():
    with pytest.raises(ExpressionEvaluationError):
        await evaluate_expressions("{{ $if(true, (function(){ while(true){} })(), 1) }}", NODE_OUTPUTS)


# --- recursion / batching -------------------------------------------------

async def test_nested_config_evaluated():
    cfg = {
        "subject": "Hello {{ $vars.name }}",
        "items": ["{{ $('node-1').count + 1 }}", "static"],
        "nested": {"first": "{{ $('node-1').csv.split(',')[0] }}"},
    }
    out = await evaluate_expressions(cfg, NODE_OUTPUTS)
    assert out["subject"] == "Hello Ada"
    assert out["items"] == [4, "static"]  # full-match block preserves the number type
    assert out["nested"]["first"] == "alpha"


# --- backward compatibility -----------------------------------------------

async def test_legacy_and_literal_untouched_with_zero_js_calls():
    cfg = {
        "ref": "{{node-1.csv}}",              # legacy path -> left for sync resolver
        "template": "Hello {{name}}!",          # literal passthrough (downstream templating)
        "mixed": "Count: {{node-1.count}}",     # legacy partial -> left for sync resolver
        "plain": "no braces here",
    }
    with patch(
        "utils.expression_evaluator.execute_js_async", new=AsyncMock()
    ) as mock_js:
        out = await evaluate_expressions(cfg, NODE_OUTPUTS)
    mock_js.assert_not_awaited()
    assert out == cfg  # byte-for-byte unchanged


async def test_literal_template_with_dollar_amount_passthrough():
    # `$5` is not a `$`-accessor -> stays a literal passthrough, not evaluated.
    out = await evaluate_expressions("{{ price is $5 }}", NODE_OUTPUTS)
    assert out == "{{ price is $5 }}"


# --- auto-upgrade: bare `{{node.field.method()}}` -> `$('node')...` -----------

async def test_bare_node_transform_is_upgraded_and_evaluated():
    # Appending JS to the legacy `{{node.field}}` form (instead of `$('node')`) is the
    # common mistake; it must still evaluate, not pass through as a literal.
    out = await evaluate_expressions("{{ node-1.csv.split(',')[0].toUpperCase() }}", NODE_OUTPUTS)
    assert out == "ALPHA"


async def test_bare_node_arithmetic_is_upgraded():
    out = await evaluate_expressions("{{ node-1.count * 2 }}", NODE_OUTPUTS)
    assert out == 6


async def test_bare_node_transform_partial_match_stringifies():
    out = await evaluate_expressions("first={{ node-1.csv.split(',')[0] }}!", NODE_OUTPUTS)
    assert out == "first=alpha!"


async def test_plain_legacy_path_not_upgraded():
    # A clean legacy path stays for the sync resolver — no JS eval, byte-identical out.
    with patch("utils.expression_evaluator.execute_js_async", new=AsyncMock()) as mock_js:
        out = await evaluate_expressions("{{node-1.csv}}", NODE_OUTPUTS)
    mock_js.assert_not_awaited()
    assert out == "{{node-1.csv}}"


async def test_unknown_node_prefix_not_upgraded():
    # A `{{foo.bar.baz()}}` whose leading id isn't a connected node stays a literal.
    with patch("utils.expression_evaluator.execute_js_async", new=AsyncMock()) as mock_js:
        out = await evaluate_expressions("{{ ghost.x.toUpperCase() }}", NODE_OUTPUTS)
    mock_js.assert_not_awaited()
    assert out == "{{ ghost.x.toUpperCase() }}"


# --- live-preview single-expression path ----------------------------------

async def test_evaluate_single_expression_value():
    out = await evaluate_single_expression("$('node-1').csv.split(',').length", NODE_OUTPUTS)
    assert out == 3


async def test_evaluate_single_expression_empty_is_none():
    assert await evaluate_single_expression("   ", NODE_OUTPUTS) is None


async def test_evaluate_single_expression_error_raises():
    with pytest.raises(ExpressionEvaluationError):
        await evaluate_single_expression("$('node-1').nope.bad()", NODE_OUTPUTS)


def test_format_preview_keeps_array_count_visible():
    out = format_preview([{"id": i} for i in range(100)])
    assert out.startswith("100 items:")
    assert "+98 more" in out


def test_format_preview_scalars_and_strings():
    assert format_preview(42) == "42"
    assert format_preview("alpha") == "alpha"
    assert format_preview("x" * 300).endswith("…")
    assert len(format_preview("x" * 300)) <= 121
    assert format_preview([]) == "[] (empty list)"
    assert format_preview([{"a": 1}]).startswith("1 item:")


def test_format_preview_nested_array_count():
    out = format_preview({"rows": [{"id": 1}] * 50})
    assert "rows: 50 items:" in out


async def test_evaluate_single_expression_no_accessor_constant():
    # The preview always evaluates, even without a `$`-accessor (unlike inline fields).
    out = await evaluate_single_expression("'a,b,c'.split(',')[1]", NODE_OUTPUTS)
    assert out == "b"
