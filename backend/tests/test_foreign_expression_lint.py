"""Foreign template-dialect lint.

`{{ $('node').item.json.x }}` and friends parse fine at write time and fail at
runtime (`$('id')` returns the output directly — no .item/.json wrapper, and
$input/$node[...] do not exist here). Pinned: the hard lint in validate_node_config (all AI
write paths + validate_workflow) and the soft reference_warnings mirror.
"""

import pytest

from coder.workflow.workflow_ops import (
    find_foreign_expression_tokens,
    foreign_expression_error,
)
from coder.workflow.workflow_schema import validate_references


class TestFinder:
    def test_flags_the_item_json_wrapper(self):
        config = {"message": "Reply to {{ $('whatsapp_x').item.json.body }} nicely"}
        hits = find_foreign_expression_tokens(config)
        assert len(hits) == 1
        path, snippet = hits[0]
        assert path == "message"
        assert ".item" in snippet

    @pytest.mark.parametrize("expr", [
        "{{ $node['Webhook'].json.body }}",
        "{{ $input.first().json.name }}",
        "{{ $items('node')[0] }}",
        "{{ $('a').all().itemMatching(0) }}",
        "{{ $prevNode.name }}",
        "{{ $execution.id }}",
        "{{ $workflow.id }}",
        "{{ $binary.data }}",
    ])
    def test_flags_foreign_accessors(self, expr):
        assert find_foreign_expression_tokens({"f": expr})

    @pytest.mark.parametrize("expr", [
        "{{ $('whatsapp_x').body }}",           # correct direct access
        "{{ $('whatsapp x').payload.from }}",   # label form
        "{{ $('x') }}",                          # whole output
        "{{ $json.field }}",
        "{{ $vars.api_base }}",
        "{{ $if($('x').ok, 'yes', 'no') }}",
        "{{ $ifEmpty($('x').name, 'friend') }}",
        "{{ $now }}",
        "{{ node_id.path.to.field }}",           # legacy path form
        "plain prose mentioning $input outside an expression block",
        "code: const item = $('x').items — no moustache, not scanned",
    ])
    def test_valid_forms_pass(self, expr):
        assert find_foreign_expression_tokens({"f": expr}) == []

    def test_walks_nested_and_respects_skip_fields(self):
        config = {
            "nested": {"deep": ["{{ $input.x }}"]},
            "code_field": "{{ $input.x }}",
        }
        hits = find_foreign_expression_tokens(config, frozenset({"code_field"}))
        assert [p for p, _ in hits] == ["nested.deep[0]"]

    def test_error_message_teaches_the_correct_form(self):
        msg = foreign_expression_error("message", "$('x').item")
        assert "$('node_id').field" in msg
        assert "no .item/.json wrapper" in msg


class TestValidateNodeConfigIntegration:
    def test_hard_lint_fires_through_validate_node_config(self):
        from coder.workflow.operation_catalog import validate_node_config

        err = validate_node_config(
            "automation-whatsapp", "send_text_message",
            {
                "operation": "send_text_message",
                "to": "123@c.us",
                "body": "{{ $('whatsapp_trigger').item.json.body }}",
            },
        )
        assert err is not None
        assert ".item" in err and "$('node_id').field" in err

    def test_correct_expression_passes(self):
        from coder.workflow.operation_catalog import validate_node_config

        assert validate_node_config(
            "automation-whatsapp", "send_text_message",
            {
                "operation": "send_text_message",
                "to": "123@c.us",
                "body": "{{ $('whatsapp_trigger').payload.body }}",
            },
        ) is None


class TestReferenceWarningsMirror:
    def test_soft_warning_rides_reference_warnings(self):
        warnings = validate_references(
            {"body": "{{ $('trigger').item.json.text }}"},
            upstream_ids={"trigger"},
            all_node_ids={"trigger", "me"},
        )
        assert any(".item" in w["warning"] for w in warnings)

    def test_clean_expression_yields_no_dialect_warning(self):
        warnings = validate_references(
            {"body": "{{ $('trigger').text }}"},
            upstream_ids={"trigger"},
            all_node_ids={"trigger", "me"},
        )
        assert warnings == []
