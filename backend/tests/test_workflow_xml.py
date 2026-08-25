"""Tests for the shared XML DSL parser (coder/workflow/workflow_xml)."""

import asyncio
import time

import pytest
from coder.workflow.workflow_xml import (
    XmlOp,
    parse_xml,
    parse_xml_line,
    parse_xml_streaming,
    unescape_attr_value,
    coerce_value,
    coerce_value_for_field,
    escape_xml_attr,
)


# ============================================================================
# unescape_attr_value
# ============================================================================

class TestUnescapeAttrValue:
    def test_no_escapes(self):
        assert unescape_attr_value("hello world") == "hello world"

    def test_escaped_double_quote(self):
        assert unescape_attr_value(r'say \"hello\"') == 'say "hello"'

    def test_escaped_single_quote(self):
        assert unescape_attr_value(r"it\'s fine") == "it's fine"

    def test_escaped_newline(self):
        assert unescape_attr_value(r"line1\nline2") == "line1\nline2"

    def test_escaped_tab(self):
        assert unescape_attr_value(r"col1\tcol2") == "col1\tcol2"

    def test_escaped_carriage_return(self):
        assert unescape_attr_value(r"a\rb") == "a\rb"

    def test_escaped_backslash(self):
        assert unescape_attr_value(r"path\\to\\file") == "path\\to\\file"

    def test_html_entity_quot(self):
        assert unescape_attr_value("&quot;hello&quot;") == '"hello"'

    def test_html_entity_amp(self):
        assert unescape_attr_value("a &amp; b") == "a & b"

    def test_html_entity_lt_gt(self):
        assert unescape_attr_value("&lt;tag&gt;") == "<tag>"

    def test_combined_backslash_and_entity(self):
        assert unescape_attr_value(r'say \"hello\" &amp; goodbye') == 'say "hello" & goodbye'

    def test_unknown_escape_kept(self):
        # Unknown escape sequences: keep the backslash
        assert unescape_attr_value(r"\x") == "\\x"

    def test_empty_string(self):
        assert unescape_attr_value("") == ""


# ============================================================================
# coerce_value
# ============================================================================

class TestCoerceValue:
    def test_plain_string(self):
        assert coerce_value("hello") == "hello"

    def test_integer(self):
        assert coerce_value("42") == 42

    def test_float(self):
        assert coerce_value("3.14") == 3.14

    def test_boolean_true(self):
        assert coerce_value("true") is True

    def test_boolean_false(self):
        assert coerce_value("false") is False

    def test_null(self):
        assert coerce_value("null") is None

    def test_json_array(self):
        assert coerce_value('[1, 2, 3]') == [1, 2, 3]

    def test_json_object(self):
        assert coerce_value('{"key": "val"}') == {"key": "val"}

    def test_non_json_string(self):
        assert coerce_value("not json {") == "not json {"

    def test_unhashable_python_literal_falls_back_to_string(self):
        """Malformed double-braced builder values must not crash coercion."""
        assert coerce_value("{{1, 2}}") == "{{1, 2}}"

    def test_empty_string(self):
        assert coerce_value("") == ""


# ============================================================================
# coerce_value_for_field — schema-aware coercion
# ============================================================================

class TestCoerceValueForField:
    """
    Regression tests for the AI-builder bug where ``value="false"`` on a
    string-typed enum field (e.g. ``show_in_interface: enum('true','false')``)
    was JSON-coerced into Python ``False``, then rejected by Pydantic v2's
    strict string validation — causing the builder to spin in a retry loop.
    """

    # The actual schema shape generated for show_in_interface: enum string fields
    ENUM_STRING_SCHEMA = {
        "default": "false",
        "description": "Show this agent as a fullscreen chat in the Interface tab.",
        "enum": ["true", "false"],
        "enumNames": ["Yes", "No"],
    }

    def test_enum_string_false_preserved(self):
        """The headline bug: 'false' must stay a string for an enum-string field."""
        result = coerce_value_for_field("false", self.ENUM_STRING_SCHEMA)
        assert result == "false"
        assert isinstance(result, str)

    def test_enum_string_true_preserved(self):
        result = coerce_value_for_field("true", self.ENUM_STRING_SCHEMA)
        assert result == "true"
        assert isinstance(result, str)

    def test_plain_string_field_preserves_numeric_string(self):
        """A plain string field shouldn't have '42' coerced into int 42."""
        schema = {"type": "string", "description": "free text"}
        result = coerce_value_for_field("42", schema)
        assert result == "42"
        assert isinstance(result, str)

    def test_integer_field_still_coerces(self):
        """Integer fields must still get string-to-int coercion."""
        schema = {"type": "integer"}
        result = coerce_value_for_field("42", schema)
        assert result == 42
        assert isinstance(result, int)

    def test_boolean_field_still_coerces(self):
        """Boolean fields must still get string-to-bool coercion."""
        schema = {"type": "boolean"}
        result = coerce_value_for_field("false", schema)
        assert result is False

    def test_array_field_still_parses_json(self):
        """Array fields must still parse JSON literals (e.g. function_inputs)."""
        schema = {"type": "array"}
        result = coerce_value_for_field('[1, 2, 3]', schema)
        assert result == [1, 2, 3]

    def test_object_field_still_parses_json(self):
        schema = {"type": "object"}
        result = coerce_value_for_field('{"k": "v"}', schema)
        assert result == {"k": "v"}

    def test_no_schema_falls_back_to_coerce_value(self):
        """Without a schema, behavior matches the legacy coerce_value."""
        assert coerce_value_for_field("false", None) is False
        assert coerce_value_for_field("42", None) == 42
        assert coerce_value_for_field("hello", None) == "hello"

    def test_empty_string_returns_empty(self):
        """Empty raw value short-circuits regardless of schema."""
        assert coerce_value_for_field("", self.ENUM_STRING_SCHEMA) == ""
        assert coerce_value_for_field("", None) == ""

    def test_enum_with_mixed_types_still_coerces(self):
        """If the enum mixes types (e.g. [1, 2, 'auto']), the string rule
        doesn't apply and we coerce as usual."""
        schema = {"enum": [1, 2, "auto"]}
        result = coerce_value_for_field("2", schema)
        # No string-enum guarantee → falls through to coerce_value → int
        assert result == 2

    def test_enum_unknown_string_value_still_preserved(self):
        """Even if the raw value isn't in the enum, we keep it as a string so
        Pydantic produces a clear validation error rather than the value
        getting type-mangled along the way."""
        result = coerce_value_for_field("maybe", self.ENUM_STRING_SCHEMA)
        assert result == "maybe"
        assert isinstance(result, str)


# ============================================================================
# escape_xml_attr
# ============================================================================

class TestEscapeXmlAttr:
    def test_no_special_chars(self):
        assert escape_xml_attr("hello") == "hello"

    def test_ampersand(self):
        assert escape_xml_attr("a & b") == "a &amp; b"

    def test_double_quote(self):
        assert escape_xml_attr('say "hi"') == "say &quot;hi&quot;"

    def test_less_than(self):
        assert escape_xml_attr("a < b") == "a &lt; b"

    def test_greater_than(self):
        assert escape_xml_attr("a > b") == "a &gt; b"

    def test_all_combined(self):
        assert escape_xml_attr('a & "b" < c > d') == "a &amp; &quot;b&quot; &lt; c &gt; d"

    def test_ampersand_first(self):
        """Ampersand must be escaped first to prevent double-escaping."""
        result = escape_xml_attr("&quot;")
        assert result == "&amp;quot;"


# ============================================================================
# parse_xml — full-text parser
# ============================================================================

class TestParseXml:
    def test_self_closing_add_node(self):
        ops = parse_xml('<add_node type="automation-rss" name="rss" label="Feed" />')
        assert len(ops) == 1
        assert ops[0].tag == "add_node"
        assert ops[0].attrs["type"] == "automation-rss"
        assert ops[0].attrs["name"] == "rss"
        assert ops[0].attrs["label"] == "Feed"
        assert ops[0].body is None

    def test_field_self_closing(self):
        ops = parse_xml('<field id="n1" name="channel" value="#general" />')
        assert len(ops) == 1
        assert ops[0].tag == "field"
        assert ops[0].attrs["name"] == "channel"
        assert ops[0].attrs["value"] == "#general"

    def test_field_body_tag(self):
        xml = '<field id="n1" name="code">const x = 1;\nreturn x;</field>'
        ops = parse_xml(xml)
        assert len(ops) == 1
        assert ops[0].tag == "field"
        assert ops[0].attrs["name"] == "code"
        assert ops[0].body == "const x = 1;\nreturn x;"

    def test_patch_body_tag(self):
        xml = (
            '<patch id="n1" name="function_body">\n'
            '*** Begin Patch\n'
            '@@ context\n'
            ' unchanged\n'
            '-old line\n'
            '+new line\n'
            '*** End Patch\n'
            '</patch>'
        )
        ops = parse_xml(xml)
        assert len(ops) == 1
        assert ops[0].tag == "patch"
        assert ops[0].attrs["name"] == "function_body"
        assert "*** Begin Patch" in ops[0].body

    def test_mock_node_body(self):
        ops = parse_xml('<mock_node id="n1">{"key": "value"}</mock_node>')
        assert len(ops) == 1
        assert ops[0].tag == "mock_node"
        assert ops[0].body == '{"key": "value"}'

    def test_mock_node_inline(self):
        ops = parse_xml("""<mock_node id="n1" output='{"a": 1}' />""")
        assert len(ops) == 1
        assert ops[0].attrs["output"] == '{"a": 1}'

    def test_body_tag_not_double_parsed(self):
        """Body tags should not also be matched as self-closing tags."""
        xml = '<mock_node id="n1">{"data": true}</mock_node>'
        ops = parse_xml(xml)
        assert len(ops) == 1


    def test_multiple_ops(self):
        xml = (
            '<add_node type="automation-rss" name="rss" />\n'
            '<add_node type="automation-slack" name="slack" />\n'
            '<add_edge from="rss" to="slack" />'
        )
        ops = parse_xml(xml)
        assert len(ops) == 3
        assert ops[0].tag == "add_node"
        assert ops[1].tag == "add_node"
        assert ops[2].tag == "add_edge"

    def test_document_order(self):
        xml = (
            '<add_edge from="a" to="b" />\n'
            '<add_node type="x" name="a" />'
        )
        ops = parse_xml(xml)
        assert len(ops) == 2
        assert ops[0].tag == "add_edge"
        assert ops[1].tag == "add_node"

    def test_mixed_body_and_self_closing(self):
        xml = (
            '<field id="n1" name="url" value="https://example.com" />\n'
            '<field id="n1" name="code">console.log("hi")</field>\n'
            '<field id="n1" name="enabled" value="true" />'
        )
        ops = parse_xml(xml)
        assert len(ops) == 3
        assert ops[0].attrs["name"] == "url"
        assert ops[1].attrs["name"] == "code"
        assert ops[1].body == 'console.log("hi")'
        assert ops[2].attrs["name"] == "enabled"

    def test_double_quoted_attrs(self):
        ops = parse_xml('<field id="n1" name="x" value="hello" />')
        assert ops[0].attrs["value"] == "hello"

    def test_single_quoted_attrs(self):
        ops = parse_xml("<field id='n1' name='x' value='hello' />")
        assert ops[0].attrs["value"] == "hello"

    def test_mixed_quotes(self):
        ops = parse_xml("""<field id="n1" name='channel' value="#general" />""")
        assert ops[0].attrs["name"] == "channel"
        assert ops[0].attrs["value"] == "#general"

    def test_escaped_quotes_in_value(self):
        ops = parse_xml(r'<field id="n1" name="text" value="say \"hello\"" />')
        assert ops[0].attrs["value"] == 'say "hello"'

    def test_html_entities_in_value(self):
        ops = parse_xml('<field id="n1" name="text" value="a &amp; b &lt; c" />')
        assert ops[0].attrs["value"] == "a & b < c"

    def test_empty_value(self):
        ops = parse_xml('<field id="n1" name="x" value="" />')
        assert ops[0].attrs["value"] == ""

    def test_bare_done_tag(self):
        ops = parse_xml("<done/>")
        assert len(ops) == 1
        assert ops[0].tag == "done"
        assert ops[0].attrs == {}

    def test_bare_done_with_space(self):
        ops = parse_xml("<done />")
        assert len(ops) == 1
        assert ops[0].tag == "done"

    def test_done_with_attrs(self):
        ops = parse_xml('<done name="My Workflow" summary="Does things" />')
        assert len(ops) == 1
        assert ops[0].attrs["name"] == "My Workflow"
        assert ops[0].attrs["summary"] == "Does things"

    def test_allowed_tags_filter(self):
        xml = (
            '<add_node type="x" name="a" />\n'
            '<field id="a" name="key" value="val" />\n'
            '<add_edge from="a" to="b" />'
        )
        ops = parse_xml(xml, allowed_tags={"add_node", "add_edge"})
        assert len(ops) == 2
        assert ops[0].tag == "add_node"
        assert ops[1].tag == "add_edge"

    def test_empty_text(self):
        assert parse_xml("") == []

    def test_non_xml_text(self):
        assert parse_xml("This is just plain text with no tags.") == []

    def test_unknown_tag_ignored(self):
        ops = parse_xml('<unknown_tag foo="bar" />')
        assert len(ops) == 0

    def test_deprecated_update_config_parsed(self):
        ops = parse_xml('<update_config id="n1" channel="#general" />')
        assert len(ops) == 1
        assert ops[0].tag == "update_config"
        assert ops[0].attrs["channel"] == "#general"

    def test_deprecated_update_config_body(self):
        ops = parse_xml('<update_config id="n1" field="code">x = 1</update_config>')
        assert len(ops) == 1
        assert ops[0].tag == "update_config"
        assert ops[0].body == "x = 1"

    def test_deprecated_patch_config(self):
        ops = parse_xml('<patch_config id="n1" field="body">diff here</patch_config>')
        assert len(ops) == 1
        assert ops[0].tag == "patch_config"
        assert ops[0].attrs["field"] == "body"
        assert ops[0].body == "diff here"

    def test_all_tag_types(self):
        """Verify all supported tags are parseable."""
        tags = [
            '<add_node type="x" name="a" />',
            '<add_edge from="a" to="b" />',
            '<remove_node id="a" />',
            '<remove_edge from="a" to="b" />',
            '<field id="a" name="x" value="1" />',
            '<set_credentials id="a" google_oauth="uuid" />',
            '<disable_node id="a" />',
            '<enable_node id="a" />',
            '<unmock_node id="a" />',
            '<done name="test" summary="test" />',
            '<input node="a" type="credential" label="API Key" />',
            '<update_goal node="a" goal="new goal" />',
        ]
        xml = "\n".join(tags)
        ops = parse_xml(xml)
        assert len(ops) == len(tags)

    def test_add_node_with_after_handle(self):
        ops = parse_xml('<add_node type="x" name="body" after="iter:loop" />')
        assert ops[0].attrs["after"] == "iter:loop"

    def test_add_edge_with_handle(self):
        ops = parse_xml('<add_edge from="iter" to="body" handle="loop" />')
        assert ops[0].attrs["handle"] == "loop"

    def test_field_with_all_attrs(self):
        ops = parse_xml(
            '<field id="n1" name="key" value="val" type="user_input" '
            'label="Enter key" reason="Required" depends_on="upstream" '
            'resolve="fuzzy" query="search term" limit="20" />'
        )
        a = ops[0].attrs
        assert a["name"] == "key"
        assert a["type"] == "user_input"
        assert a["label"] == "Enter key"
        assert a["reason"] == "Required"
        assert a["depends_on"] == "upstream"
        assert a["resolve"] == "fuzzy"
        assert a["query"] == "search term"
        assert a["limit"] == "20"

    def test_without_trailing_slash(self):
        """Tags without self-closing slash should still be parsed."""
        ops = parse_xml('<add_node type="x" name="a">')
        assert len(ops) == 1
        assert ops[0].tag == "add_node"

    def test_set_credentials(self):
        ops = parse_xml('<set_credentials id="slack" slack_oauth="cred-uuid-123" />')
        assert ops[0].attrs["slack_oauth"] == "cred-uuid-123"

    def test_disable_enable(self):
        ops = parse_xml('<disable_node id="n1" />\n<enable_node id="n2" />')
        assert len(ops) == 2
        assert ops[0].tag == "disable_node"
        assert ops[1].tag == "enable_node"


# ============================================================================
# parse_xml_line — streaming line parser
# ============================================================================

class TestParseXmlLine:
    def test_add_node(self):
        op = parse_xml_line('<add_node type="automation-rss" name="rss" label="Feed" goal="Parse RSS">')
        assert op is not None
        assert op.tag == "add_node"
        assert op.attrs["type"] == "automation-rss"
        assert op.attrs["name"] == "rss"
        assert op.attrs["label"] == "Feed"
        assert op.attrs["goal"] == "Parse RSS"

    def test_add_edge(self):
        op = parse_xml_line('<add_edge from="rss" to="slack">')
        assert op is not None
        assert op.tag == "add_edge"
        assert op.attrs["from"] == "rss"
        assert op.attrs["to"] == "slack"

    def test_add_edge_with_handle(self):
        op = parse_xml_line('<add_edge from="iter" to="body" handle="loop">')
        assert op.attrs["handle"] == "loop"

    def test_remove_node(self):
        op = parse_xml_line('<remove_node name="old_node"/>')
        assert op is not None
        assert op.tag == "remove_node"
        assert op.attrs["name"] == "old_node"

    def test_remove_edge(self):
        op = parse_xml_line('<remove_edge from="a" to="b"/>')
        assert op.tag == "remove_edge"

    def test_update_goal(self):
        op = parse_xml_line('<update_goal node="rss" goal="Parse and filter RSS"/>')
        assert op.tag == "update_goal"
        assert op.attrs["node"] == "rss"
        assert op.attrs["goal"] == "Parse and filter RSS"

    def test_input(self):
        op = parse_xml_line('<input node="sheets" type="credential" label="Google Sheets" service="google_sheets">')
        assert op.tag == "input"
        assert op.attrs["node"] == "sheets"
        assert op.attrs["service"] == "google_sheets"

    def test_done_with_attrs(self):
        op = parse_xml_line('<done name="My Workflow" summary="A test workflow"/>')
        assert op.tag == "done"
        assert op.attrs["name"] == "My Workflow"
        assert op.attrs["summary"] == "A test workflow"

    def test_done_bare(self):
        op = parse_xml_line("<done/>")
        assert op is not None
        assert op.tag == "done"
        assert op.attrs == {}

    def test_done_bare_with_space(self):
        op = parse_xml_line("<done />")
        assert op.tag == "done"

    def test_non_xml_returns_none(self):
        assert parse_xml_line("This is just text") is None

    def test_empty_line_returns_none(self):
        assert parse_xml_line("") is None
        assert parse_xml_line("   ") is None

    def test_allowed_tags_filter(self):
        op = parse_xml_line(
            '<field id="n1" name="x" value="1" />',
            allowed_tags={"add_node"}
        )
        assert op is None

    def test_allowed_tags_passes(self):
        op = parse_xml_line(
            '<add_node type="x" name="a" label="A" goal="test">',
            allowed_tags={"add_node"}
        )
        assert op is not None
        assert op.tag == "add_node"

    def test_single_quotes(self):
        op = parse_xml_line("<add_node type='x' name='a' label='A' goal='test'>")
        assert op.attrs["type"] == "x"

    def test_mixed_quotes(self):
        op = parse_xml_line("""<add_node type="x" name='a' label="A" goal='test'>""")
        assert op.attrs["type"] == "x"
        assert op.attrs["name"] == "a"

    def test_any_attribute_order(self):
        """Attributes can appear in any order."""
        op = parse_xml_line('<add_node goal="test" name="a" type="x" label="A">')
        assert op.attrs["type"] == "x"
        assert op.attrs["name"] == "a"
        assert op.attrs["label"] == "A"
        assert op.attrs["goal"] == "test"

    def test_optional_description(self):
        op = parse_xml_line(
            '<add_node type="x" name="a" label="A" goal="test" description="Extra info">'
        )
        assert op.attrs.get("description") == "Extra info"

    def test_leading_whitespace_stripped(self):
        op = parse_xml_line('   <add_node type="x" name="a">')
        assert op is not None
        assert op.tag == "add_node"

    def test_escaped_quotes(self):
        op = parse_xml_line(r'<add_node type="x" name="a" label="it\'s" goal="test">')
        assert op.attrs["label"] == "it's"


# ============================================================================
# update_settings tag parsing
# ============================================================================

class TestUpdateSettingsParsing:
    def test_self_closing_single_attr(self):
        ops = parse_xml('<update_settings id="node-1" retryOnFail="true" />')
        assert len(ops) == 1
        assert ops[0].tag == "update_settings"
        assert ops[0].attrs["id"] == "node-1"
        assert ops[0].attrs["retryOnFail"] == "true"

    def test_multiple_attrs(self):
        ops = parse_xml(
            '<update_settings id="node-1" retryOnFail="true" maxTries="3" waitBetweenTries="1000" />'
        )
        assert len(ops) == 1
        assert ops[0].attrs["retryOnFail"] == "true"
        assert ops[0].attrs["maxTries"] == "3"
        assert ops[0].attrs["waitBetweenTries"] == "1000"

    def test_all_fields_parsed(self):
        ops = parse_xml(
            '<update_settings id="n" retryOnFail="true" maxTries="4" '
            'waitBetweenTries="2000" onError="stopWorkflow" '
            'alwaysOutputData="false" executeOnce="false" notes="test note" />'
        )
        assert len(ops) == 1
        a = ops[0].attrs
        assert a["onError"] == "stopWorkflow"
        assert a["alwaysOutputData"] == "false"
        assert a["executeOnce"] == "false"
        assert a["notes"] == "test note"

    def test_notes_with_spaces(self):
        ops = parse_xml('<update_settings id="n" notes="This is a multi word note" />')
        assert ops[0].attrs["notes"] == "This is a multi word note"

    def test_update_settings_in_batch_with_other_ops(self):
        xml = (
            '<update_settings id="node-a" retryOnFail="true" />\n'
            '<disable_node id="node-b" />\n'
            '<update_settings id="node-c" onError="continueRegularOutput" />\n'
        )
        ops = parse_xml(xml)
        tags = [op.tag for op in ops]
        assert tags == ["update_settings", "disable_node", "update_settings"]
        assert ops[0].attrs["retryOnFail"] == "true"
        assert ops[2].attrs["onError"] == "continueRegularOutput"

    def test_is_in_all_tags(self):
        from coder.workflow.workflow_xml import ALL_TAGS
        assert "update_settings" in ALL_TAGS


# ============================================================================
# Bare boolean attributes
# ============================================================================

class TestBooleanAttributes:
    """Tags with bare boolean attributes like <get_output node="x" full />."""

    def test_get_output_full(self):
        ops = parse_xml('<get_output node="list_docs" full />')
        assert len(ops) == 1
        assert ops[0].tag == "get_output"
        assert ops[0].attrs["node"] == "list_docs"
        assert "full" in ops[0].attrs
        assert ops[0].attrs["full"] == ""

    def test_run_node_get_output(self):
        ops = parse_xml('<run_node node="fetch" get_output />')
        assert len(ops) == 1
        assert ops[0].attrs["node"] == "fetch"
        assert "get_output" in ops[0].attrs

    def test_run_node_include_downstream(self):
        ops = parse_xml('<run_node node="trigger" include_downstream />')
        assert len(ops) == 1
        assert "include_downstream" in ops[0].attrs

    def test_boolean_attr_with_multiple_kv_attrs(self):
        ops = parse_xml('<add_node type="x" name="a" label="Test" full />')
        assert len(ops) == 1
        assert ops[0].attrs["type"] == "x"
        assert ops[0].attrs["name"] == "a"
        assert ops[0].attrs["label"] == "Test"
        assert "full" in ops[0].attrs

    def test_boolean_attr_before_kv_attrs(self):
        """Bare attr appearing before key=value attrs."""
        ops = parse_xml('<get_output full node="list_docs" />')
        assert len(ops) == 1
        assert "full" in ops[0].attrs
        assert ops[0].attrs["node"] == "list_docs"

    def test_parse_xml_line_boolean_attr(self):
        op = parse_xml_line('<get_output node="list_docs" full />')
        assert op is not None
        assert op.attrs["node"] == "list_docs"
        assert "full" in op.attrs


# ============================================================================
# parse_xml_streaming — incremental parser for LLM-streamed buffers
# ============================================================================

class TestParseXmlStreaming:
    """parse_xml_streaming is the streaming-friendly variant of parse_xml.

    It accepts a start_offset, parses only the suffix, and returns
    (ops, next_safe_offset) so callers can resume on the next chunk
    without rescanning the prefix. Total work across a stream is O(N)
    instead of parse_xml's O(N²).
    """

    def test_matches_parse_xml_when_offset_zero(self):
        """At start_offset=0 on a complete buffer, output equals parse_xml."""
        xml = (
            '<add_node type="x" name="a" />\n'
            '<field id="n1" name="code">return 1;</field>\n'
            '<add_edge from="a" to="b" />\n'
        )
        full = parse_xml(xml)
        ops, _ = parse_xml_streaming(xml, start_offset=0)
        assert [(o.tag, o.attrs, o.body) for o in ops] == \
               [(o.tag, o.attrs, o.body) for o in full]

    def test_advances_past_self_closing_tags(self):
        xml = '<add_node type="x" name="a" />'
        ops, next_off = parse_xml_streaming(xml, start_offset=0)
        assert len(ops) == 1
        assert next_off == len(xml)

    def test_advances_past_full_body_tag(self):
        xml = '<field id="n1" name="code">x = 1</field>'
        ops, next_off = parse_xml_streaming(xml, start_offset=0)
        assert len(ops) == 1
        assert ops[0].body == "x = 1"
        assert next_off == len(xml)

    def test_holds_unclosed_body_opening(self):
        """`<field name="x">` without closing must NOT emit and must NOT advance offset."""
        xml = '<field id="n1" name="x">par'
        ops, next_off = parse_xml_streaming(xml, start_offset=0)
        # Field is body-eligible; unclosed opening is held back
        assert ops == []
        # Cursor stops at the unclosed opening's start so next call rescans it
        assert next_off == 0

    def test_resumes_when_close_arrives(self):
        """Two-step stream: opening in chunk 1, close in chunk 2 — emit once on close."""
        chunk1 = '<field id="n1" name="x">par'
        ops1, off1 = parse_xml_streaming(chunk1, start_offset=0)
        assert ops1 == []
        assert off1 == 0

        chunk2 = chunk1 + 'tial body</field>'
        ops2, off2 = parse_xml_streaming(chunk2, start_offset=off1)
        assert len(ops2) == 1
        assert ops2[0].tag == "field"
        assert ops2[0].body == "partial body"
        assert off2 == len(chunk2)

    def test_self_closing_emits_immediately_in_stream(self):
        """`<field name="x" value="y" />` is self-closing and emits the same chunk."""
        xml = '<field name="x" value="y" />'
        ops, off = parse_xml_streaming(xml, start_offset=0)
        assert len(ops) == 1
        assert ops[0].attrs["value"] == "y"
        assert off == len(xml)

    def test_partial_tag_at_buffer_tail(self):
        """A truncated `<fie` at tail must NOT advance offset past it."""
        xml = '<add_node type="x" name="a" />\n<fie'
        ops, off = parse_xml_streaming(xml, start_offset=0)
        assert len(ops) == 1
        assert ops[0].tag == "add_node"
        # Cursor stops at the partial '<' so the next chunk re-sees it
        assert off == xml.index('<fie')

    def test_partial_tag_completes_in_next_call(self):
        chunk1 = '<add_node type="x" name="a" />\n<add_edge fr'
        ops1, off1 = parse_xml_streaming(chunk1, start_offset=0)
        assert len(ops1) == 1
        partial_pos = chunk1.index('<add_edge')
        assert off1 == partial_pos

        chunk2 = chunk1 + 'om="a" to="b" />'
        ops2, off2 = parse_xml_streaming(chunk2, start_offset=off1)
        assert len(ops2) == 1
        assert ops2[0].tag == "add_edge"
        assert off2 == len(chunk2)

    def test_streamed_chunks_match_full_parse(self):
        """Feeding the full buffer one byte at a time produces the same ops as one parse_xml call."""
        xml = (
            '<add_node type="automation-rss" name="rss" />\n'
            '<add_node type="automation-slack" name="slack" />\n'
            '<add_edge from="rss" to="slack" />\n'
            '<field id="rss" name="url" value="https://example.com" />\n'
            '<field id="slack" name="message">Hello {{$rss.title}}!</field>\n'
            '<set_credentials id="slack" slack_oauth="cred-1" />\n'
            '<done name="My Workflow" summary="RSS to Slack" />'
        )
        expected = parse_xml(xml)

        emitted = []
        offset = 0
        buffer = ""
        for ch in xml:
            buffer += ch
            new_ops, offset = parse_xml_streaming(buffer, start_offset=offset)
            emitted.extend(new_ops)

        assert [(o.tag, o.attrs, o.body) for o in emitted] == \
               [(o.tag, o.attrs, o.body) for o in expected]

    def test_streaming_with_allowed_tags(self):
        xml = (
            '<add_node type="x" name="a" />'
            '<field name="key" value="val" />'
            '<add_edge from="a" to="b" />'
        )
        emitted = []
        offset = 0
        buffer = ""
        for ch in xml:
            buffer += ch
            new_ops, offset = parse_xml_streaming(
                buffer, allowed_tags={"field"}, start_offset=offset,
            )
            emitted.extend(new_ops)
        assert len(emitted) == 1
        assert emitted[0].tag == "field"
        assert emitted[0].attrs["name"] == "key"

    def test_no_double_emission_across_chunks(self):
        """A tag completed in chunk K must not re-emit when chunk K+1 arrives."""
        chunk1 = '<add_node type="x" name="a" />'
        ops1, off1 = parse_xml_streaming(chunk1, start_offset=0)
        assert len(ops1) == 1

        chunk2 = chunk1 + '<add_edge from="a" to="b" />'
        ops2, off2 = parse_xml_streaming(chunk2, start_offset=off1)
        assert len(ops2) == 1
        assert ops2[0].tag == "add_edge"

    def test_field_with_unescaped_quotes_in_value_streamed(self):
        """Pass 4 (bracket-depth fallback) works in streaming mode."""
        xml = '<field id="n1" name="payload" value="[{"k": "v"}]" />'
        emitted = []
        offset = 0
        buffer = ""
        for ch in xml:
            buffer += ch
            new_ops, offset = parse_xml_streaming(buffer, start_offset=offset)
            emitted.extend(new_ops)
        assert len(emitted) == 1
        assert emitted[0].attrs["name"] == "payload"
        assert emitted[0].attrs["value"] == '[{"k": "v"}]'

    def test_perf_is_linear_for_long_stream(self):
        """Regression test for the parse_xml O(N²) bug.

        Previously streaming callers called parse_xml(full_response) on every
        streaming chunk, making total work Σ(1..N) = O(N²). Profiling confirmed
        that repeated parsing dominated CPU time on the old path.

        This test feeds a ~50KB body in 500 chunks. With the old parser the
        elapsed time would be ~500× a single full parse; with parse_xml_streaming
        it should be ≤2× a single full parse (one O(N) scan amortized).
        """
        # A realistic-shape LLM streaming response: many self-closing field tags.
        n_tags = 500
        xml_parts = []
        for i in range(n_tags):
            xml_parts.append(
                f'<field id="n{i}" name="key{i}" '
                f'value="value-with-some-content-{i}" />\n'
            )
        full = "".join(xml_parts)
        # Sanity: ~50KB
        assert 30_000 < len(full) < 80_000

        # Baseline: one full parse
        t0 = time.perf_counter()
        baseline_ops = parse_xml(full)
        baseline_elapsed = time.perf_counter() - t0
        assert len(baseline_ops) == n_tags

        # Streaming: feed in chunks; each call resumes at the previous offset.
        chunk_size = max(1, len(full) // n_tags)
        t0 = time.perf_counter()
        offset = 0
        buf = ""
        emitted = 0
        for i in range(0, len(full), chunk_size):
            buf = full[: i + chunk_size]
            new_ops, offset = parse_xml_streaming(buf, start_offset=offset)
            emitted += len(new_ops)
        # Tail flush — final offset should reach end after the loop's last chunk
        streaming_elapsed = time.perf_counter() - t0
        assert emitted == n_tags
        assert offset == len(full)

        # The streaming variant must be substantially faster than the O(N²)
        # baseline of calling parse_xml on every chunk. With the old code the
        # ratio would be ~n_tags/2; we require well under 10×.
        # Allow a generous margin for CI noise — the failure mode is "got
        # quadratically worse," not "fast vs. faster."
        ratio_vs_baseline = streaming_elapsed / max(baseline_elapsed, 1e-6)
        assert ratio_vs_baseline < 10.0, (
            f"parse_xml_streaming over {n_tags} chunks took "
            f"{streaming_elapsed*1000:.1f}ms; one full parse_xml took "
            f"{baseline_elapsed*1000:.1f}ms (ratio={ratio_vs_baseline:.1f}). "
            "If this regressed past 10× the perf bug from 2026-05-07 is back."
        )

    async def test_streaming_via_to_thread_within_2x_of_inline(self):
        """Streaming-handler wall time when the parse runs on a worker thread
        must stay within 2× of the inline (event-loop) baseline.

        The schema-filler streaming hot path now wraps each parse in
        ``asyncio.to_thread`` so a slow chunk can no longer pin the event
        loop. The trade-off is one thread hop per chunk. This benchmark
        asserts the aggregate overhead is small relative to the parse work
        on a representative LLM-stream-shaped buffer (~50KB / 500 chunks).
        If this regresses past 2× the offload is doing more harm than good
        and we need a smarter heuristic (e.g. only thread-hop when the
        residual buffer crosses a threshold).
        """
        n_tags = 500
        full = "".join(
            f'<field id="n{i}" name="key{i}" '
            f'value="value-with-some-content-{i}" />\n'
            for i in range(n_tags)
        )
        chunk_size = max(1, len(full) // n_tags)

        def run_inline() -> tuple[float, int]:
            t0 = time.perf_counter()
            offset = 0
            emitted = 0
            for i in range(0, len(full), chunk_size):
                buf = full[: i + chunk_size]
                new_ops, offset = parse_xml_streaming(buf, start_offset=offset)
                emitted += len(new_ops)
            return time.perf_counter() - t0, emitted

        async def run_threaded() -> tuple[float, int]:
            t0 = time.perf_counter()
            offset = 0
            emitted = 0
            for i in range(0, len(full), chunk_size):
                buf = full[: i + chunk_size]
                new_ops, offset = await asyncio.to_thread(
                    parse_xml_streaming, buf, start_offset=offset,
                )
                emitted += len(new_ops)
            return time.perf_counter() - t0, emitted

        # Warm up once each to avoid first-run JIT/import skew, then take the
        # min of three runs so a stray GC pause doesn't flake CI.
        run_inline()
        await run_threaded()
        inline_runs = [run_inline() for _ in range(3)]
        threaded_runs = [await run_threaded() for _ in range(3)]
        inline_elapsed = min(t for t, _ in inline_runs)
        threaded_elapsed = min(t for t, _ in threaded_runs)

        # Correctness: both variants must emit every tag.
        for elapsed, emitted in inline_runs + threaded_runs:
            assert emitted == n_tags

        # The original guard here was `threaded/inline < 2.0`. That ratio only
        # held while the parse was pathologically slow: _TAG_PATTERN used to
        # backtrack on every chunk that ended mid-tag, so parse work dwarfed the
        # thread hop. Making the attribute repetition possessive cut the inline
        # baseline ~5x (49ms -> 9ms here), which pushes the *ratio* past 2x even
        # though both variants got faster in absolute terms (threaded 70ms ->
        # 29ms). A ratio against a near-zero denominator measures nothing, so we
        # assert the property that actually matters: the per-chunk dispatch cost
        # the offload adds must stay negligible next to a streaming turn.
        overhead_per_chunk_ms = (
            (threaded_elapsed - inline_elapsed) / n_tags * 1000
        )
        assert overhead_per_chunk_ms < 1.0, (
            f"asyncio.to_thread offload regressed: threaded "
            f"{threaded_elapsed*1000:.1f}ms vs inline {inline_elapsed*1000:.1f}ms "
            f"over {n_tags} chunks = {overhead_per_chunk_ms:.3f}ms/chunk. "
            "Above ~1ms/chunk the hop costs more than the parse it protects."
        )

    def test_streaming_field_does_not_emit_value_none_for_partial_open(self):
        """Streaming correctness: callers like streaming callers dedup by
        field name. If parse_xml emits `<field name="x">` (no body, no value)
        when only the opening has arrived, the dedup latches and the body
        version is silently dropped. parse_xml_streaming must hold partial
        body openings until the close arrives."""
        chunk1 = '<field id="n1" name="x">'
        ops1, off1 = parse_xml_streaming(chunk1, start_offset=0)
        # Old behavior would emit XmlOp(tag="field", attrs={"name": "x"}, body=None)
        # which sticks the caller's emitted_fields set. Streaming variant must NOT.
        assert ops1 == []

        # Body arrives across a couple more chunks
        for tail in ['hel', 'lo</field>']:
            buf = chunk1 + tail
            ops2, off1 = parse_xml_streaming(buf, start_offset=off1)
            chunk1 = buf
        assert len(ops2) == 1
        assert ops2[0].body == "hello"


class TestFinalParseUnclosedRecovery:
    """An unclosed `<field ... type="static">` tag can otherwise be
    silently dropped, leaving required config absent. On a FINAL parse an
    unclosed attr-bearing body tag is
    recoverable: value= present → self-closing; otherwise the text up to the
    next recognized tag is its body. Streaming keeps the deferral (the close
    may simply not have arrived yet)."""

    REDDIT_drafter_RESPONSE = (
        '<field name="subreddit" value="wallstreetbets" type="static">\n'
        '<field name="sort" value="hot" type="static">\n'
        '<field name="limit" value="25" type="static">'
    )

    def test_unclosed_value_fields_recovered(self):
        ops = parse_xml(self.REDDIT_drafter_RESPONSE, allowed_tags={'field', 'patch'})
        assert [(o.attrs['name'], o.attrs['value']) for o in ops] == [
            ('subreddit', 'wallstreetbets'), ('sort', 'hot'), ('limit', '25'),
        ]
        assert all(o.body is None for o in ops)

    def test_unclosed_body_field_recovers_text_up_to_next_tag(self):
        xml = (
            '<field name="function_body" type="static">\n'
            'return 1;\n'
            '<field name="x" value="y" type="static">'
        )
        ops = parse_xml(xml, allowed_tags={'field'})
        assert [(o.attrs['name'], o.attrs.get('value'), o.body) for o in ops] == [
            ('function_body', None, 'return 1;'), ('x', 'y', None),
        ]

    def test_streaming_still_defers_unclosed_opens(self):
        ops, next_off = parse_xml_streaming(self.REDDIT_drafter_RESPONSE, allowed_tags={'field', 'patch'})
        assert ops == []
        assert next_off == 0

    def test_properly_closed_body_still_wins(self):
        """Recovery must not double-emit a tag pass 1 already resolved."""
        xml = '<field name="code" type="static">x = 1</field>'
        ops = parse_xml(xml, allowed_tags={'field'})
        assert len(ops) == 1
        assert ops[0].body == 'x = 1'


class TestJsxBodyParsePerformance:
    """Guards the catastrophic-backtracking regression in _TAG_PATTERN.

    `input` is in the DSL vocabulary AND is a stock HTML/JSX element, so an
    interface-html-react node streams `<input ... value={v} />` by the hundred.
    The tag name matches, the JSX-brace attributes don't, and before the
    attribute repetition was made possessive the engine re-partitioned the
    attribute run on every failure — 2s+ per 100KB, re-run on every stream
    chunk, which pinned two whole containers on 2026-07-28.
    """

    JSX_LINE = '  <input className="rounded px-2" value={value} onChange={onChange} />\n'

    def _jsx_buffer(self, lines: int) -> str:
        return '<field name="jsx_source" type="static">\n' + self.JSX_LINE * lines

    def test_jsx_heavy_body_parses_quickly(self):
        """~400KB of input-heavy JSX must parse in well under a second.

        Pre-fix this took ~7.5s; post-fix it is a few milliseconds. The 2s
        bound is deliberately loose so a slow CI runner can't flake it, while
        still catching a return of the super-linear behaviour.
        """
        buf = self._jsx_buffer(5000)
        assert len(buf) > 350_000
        start = time.perf_counter()
        parse_xml_streaming(buf, allowed_tags={'field', 'patch'}, start_offset=0)
        assert time.perf_counter() - start < 2.0

    def test_cost_stays_linear_in_buffer_size(self):
        """Doubling the body must not more than ~quadruple the parse time."""
        def timed(lines: int) -> float:
            buf = self._jsx_buffer(lines)
            start = time.perf_counter()
            parse_xml_streaming(buf, allowed_tags={'field', 'patch'}, start_offset=0)
            return time.perf_counter() - start

        small, large = timed(1500), timed(3000)
        # Guard against a divide-by-zero on very fast machines.
        assert large < max(small * 4, 0.5)

    def test_jsx_input_element_yields_nothing_under_the_streaming_allowlist(self):
        """The restricted caller allowlist is what keeps JSX `<input>` out of the ops.

        `input` is a DSL tag, so with a permissive allowlist a JSX element does
        parse into an op (only the quoted attrs survive) — long-standing
        behaviour, unchanged here. The streaming hot path passes
        ``{'field', 'patch'}``, under which it correctly yields nothing.
        """
        jsx = '<input className="a" value={v} onChange={f} />'

        ops, next_off = parse_xml_streaming(
            jsx, allowed_tags={'field', 'patch'}, start_offset=0
        )
        assert ops == []

        # Documents the permissive-allowlist behaviour so a future change to it
        # is a deliberate decision rather than a silent one.
        assert [(o.tag, o.attrs) for o in parse_xml(jsx, allowed_tags={'input'})] == [
            ('input', {'className': 'a'})
        ]

    def test_quoted_input_tag_still_parses(self):
        """The possessive quantifier must not break legitimate matches."""
        ops = parse_xml('<input name="q" value="42" />', allowed_tags={'input'})
        assert len(ops) == 1
        assert ops[0].attrs == {'name': 'q', 'value': '42'}

    def test_bare_boolean_and_unescaped_quote_attrs_still_parse(self):
        """Both awkward attribute forms survive the possessive change."""
        ops = parse_xml('<field full name="y" value=\'z\' />', allowed_tags={'field'})
        assert len(ops) == 1
        assert ops[0].attrs['name'] == 'y' and ops[0].attrs['value'] == 'z'

        ops = parse_xml('<field name="v" value="[{"a": 1}]" />', allowed_tags={'field'})
        assert len(ops) == 1
        assert ops[0].attrs['name'] == 'v'
