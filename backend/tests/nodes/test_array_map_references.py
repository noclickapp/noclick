"""Tests for '[]' array-map reference resolution.

Implicit auto-iteration was removed: a '{{node.items[].field}}' reference no
longer loops. It now resolves to the MAPPED ARRAY value (a plain list). Looping
over items is done only by an explicit iteration node. These tests pin the
mapped-array semantics on both resolvers (the execution handler's and the shared
utils.reference_resolver).
"""

import pytest
from unittest.mock import AsyncMock

from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler
from utils.reference_resolver import resolve_single_reference


NODE_OUTPUTS = {
    "youtube_1": {
        "items": [
            {"snippet": {"title": "A"}},
            {"snippet": {"title": "B"}},
            {"snippet": {"title": "C"}},
        ],
    },
    "profile_1": {
        "groups": [
            {"members": [{"name": "a"}, {"name": "b"}]},
            {"members": [{"name": "c"}]},
        ],
    },
    "list_node": [{"x": 1}, {"x": 2}],
    "scalar_node": {"value": "hello"},
}


@pytest.fixture
def handler():
    return WorkflowExecutionHandler(sio=AsyncMock())


# --- handler resolver --------------------------------------------------------

class TestHandlerArrayMap:
    def test_maps_field_over_array(self, handler):
        assert handler._resolve_references(
            "{{youtube_1.items[].snippet.title}}", NODE_OUTPUTS
        ) == ["A", "B", "C"]

    def test_bare_bracket_returns_whole_array(self, handler):
        # items[] with no remainder == the array itself
        assert handler._resolve_references("{{youtube_1.items[]}}", NODE_OUTPUTS) == NODE_OUTPUTS["youtube_1"]["items"]

    def test_node_output_is_array(self, handler):
        assert handler._resolve_references("{{list_node[].x}}", NODE_OUTPUTS) == [1, 2]

    def test_nested_brackets_fan_out(self, handler):
        assert handler._resolve_references(
            "{{profile_1.groups[].members[].name}}", NODE_OUTPUTS
        ) == [["a", "b"], ["c"]]

    def test_missing_field_per_item_is_none(self, handler):
        assert handler._resolve_references("{{youtube_1.items[].missing}}", NODE_OUTPUTS) == [None, None, None]

    def test_bracket_on_non_array_preserves_original(self, handler):
        # Unresolvable [] (source isn't an array) → handler preserves the literal
        # reference (its existing "keep original if unresolvable" behavior),
        # which is the underlying resolver returning None.
        assert handler._resolve_references("{{scalar_node.value[].x}}", NODE_OUTPUTS) == "{{scalar_node.value[].x}}"
        assert handler._resolve_single_reference("scalar_node.value[].x", NODE_OUTPUTS) is None

    def test_does_not_loop_partial_match_stringifies_list(self, handler):
        # Embedded (partial) reference stringifies the mapped list — proof the
        # value is a list, not a per-item loop side effect.
        out = handler._resolve_references("titles: {{youtube_1.items[].snippet.title}}", NODE_OUTPUTS)
        assert out == "titles: ['A', 'B', 'C']"


# --- shared resolver (parity) ------------------------------------------------

class TestSharedResolverArrayMap:
    def test_maps_field_over_array(self):
        assert resolve_single_reference("youtube_1.items[].snippet.title", NODE_OUTPUTS) == ["A", "B", "C"]

    def test_nested_brackets_fan_out(self):
        assert resolve_single_reference("profile_1.groups[].members[].name", NODE_OUTPUTS) == [["a", "b"], ["c"]]

    def test_bracket_on_non_array_is_none(self):
        assert resolve_single_reference("scalar_node.value[].x", NODE_OUTPUTS) is None

    def test_numeric_index_still_works(self):
        assert resolve_single_reference("youtube_1.items[0].snippet.title", NODE_OUTPUTS) == "A"


def test_no_implicit_iteration_machinery():
    """The implicit-iteration symbols are gone — guards against reintroduction."""
    import wss.handlers.workflow_execution_handler as h
    assert not hasattr(h, "IterationGroup")
    assert not hasattr(WorkflowExecutionHandler, "_analyze_iteration_groups")
    assert not hasattr(WorkflowExecutionHandler, "_execute_iteration_group")
    assert not hasattr(WorkflowExecutionHandler, "_resolve_iteration_reference")
