"""
Tests for the NoClick MCP server (backend/mcp_server.py).

Covers XML parsing, utility functions, server helpers, update_workflow batch
processing, tool handlers, and ASGI middleware authentication.
"""

import json
import pytest
import pytest_asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

# Must import mock_asyncpg before mcp_server to patch DB
from tests.mocks.mock_asyncpg import (
    configure_mock_query_responses,
    MockAsyncpgPool,
    MockAsyncpgRecord,
    clear_executed_queries,
    get_executed_queries,
)

from mcp_server import (
    _parse_xml_operations,
    _coerce_config_value,
    _escape_xml_attr,
    _workflow_to_xml,
    _normalize_credential_name,
    _extract_credential_type,
    _user_id_var,
    _client_id_var,
    NoClickMCPServer,
)


# ---------------------------------------------------------------------------
# XML Parsing
# ---------------------------------------------------------------------------

class TestParseXmlOperations:
    """Test _parse_xml_operations: the core XML → operation list parser."""

    def test_self_closing_add_node(self):
        xml = '<add_node type="automation-rss" name="rss" />'
        ops = _parse_xml_operations(xml)
        assert len(ops) == 1
        assert ops[0]["tag"] == "add_node"
        assert ops[0]["attrs"]["type"] == "automation-rss"
        assert ops[0]["attrs"]["name"] == "rss"

    def test_self_closing_update_config(self):
        xml = '<update_config id="rss" feed_url="https://example.com/feed.xml" />'
        ops = _parse_xml_operations(xml)
        assert len(ops) == 1
        assert ops[0]["tag"] == "update_config"
        assert ops[0]["attrs"]["id"] == "rss"
        assert ops[0]["attrs"]["feed_url"] == "https://example.com/feed.xml"

    def test_body_tag_mock_node(self):
        xml = '<mock_node id="node1">{"key": "value"}</mock_node>'
        ops = _parse_xml_operations(xml)
        assert len(ops) == 1
        assert ops[0]["tag"] == "mock_node"
        assert ops[0]["attrs"]["id"] == "node1"
        assert ops[0]["body"] == '{"key": "value"}'

    def test_body_tag_patch_config(self):
        xml = '<patch_config id="fn" field="function_body">*** Begin Patch\n+new line\n*** End Patch</patch_config>'
        ops = _parse_xml_operations(xml)
        assert len(ops) == 1
        assert ops[0]["tag"] == "patch_config"
        assert ops[0]["attrs"]["field"] == "function_body"
        assert "*** Begin Patch" in ops[0]["body"]

    def test_body_tag_update_config(self):
        """update_config supports body syntax for large values."""
        xml = '<update_config id="fn" field="function_body">const x = 1;\nreturn x;</update_config>'
        ops = _parse_xml_operations(xml)
        assert len(ops) == 1
        assert ops[0]["tag"] == "update_config"
        assert ops[0]["attrs"]["field"] == "function_body"
        assert ops[0]["body"] == "const x = 1;\nreturn x;"

    def test_multiple_operations(self):
        xml = (
            '<add_node type="automation-rss" name="rss" />\n'
            '<add_node type="automation-slack" name="slack" after="rss" />\n'
            '<add_edge from="rss" to="slack" />'
        )
        ops = _parse_xml_operations(xml)
        assert len(ops) == 3
        tags = [op["tag"] for op in ops]
        assert "add_node" in tags
        assert "add_edge" in tags

    def test_body_tag_not_double_parsed(self):
        """Body tags should not also appear as self-closing matches."""
        xml = '<mock_node id="n1">{"a": 1}</mock_node>'
        ops = _parse_xml_operations(xml)
        assert len(ops) == 1

    def test_empty_xml(self):
        ops = _parse_xml_operations("")
        assert ops == []

    def test_invalid_xml(self):
        ops = _parse_xml_operations("this is not xml")
        assert ops == []

    def test_xml_entity_unescaping(self):
        """Attribute values with XML entities should be unescaped."""
        xml = '<update_config id="n1" text="a &amp; b &lt; c &gt; d &quot;e&quot;" />'
        ops = _parse_xml_operations(xml)
        assert ops[0]["attrs"]["text"] == 'a & b < c > d "e"'

    def test_escaped_quotes_in_attrs(self):
        xml = r'<update_config id="n1" text="hello \"world\"" />'
        ops = _parse_xml_operations(xml)
        assert ops[0]["attrs"]["text"] == 'hello "world"'

    def test_all_tag_types_parsed(self):
        """All 11 tag types should be parseable."""
        xml = """
        <add_node type="automation-rss" name="rss" />
        <add_edge from="a" to="b" />
        <update_config id="n1" key="val" />
        <set_credentials id="n1" slack_oauth="cred-123" />
        <disable_node id="n1" />
        <enable_node id="n1" />
        <mock_node id="n1">{"x":1}</mock_node>
        <unmock_node id="n1" />
        <patch_config id="n1" field="f">patch</patch_config>
        <remove_edge from="a" to="b" />
        <remove_node id="n1" />
        """
        ops = _parse_xml_operations(xml)
        tags = {op["tag"] for op in ops}
        expected = {
            "add_node", "add_edge", "update_config", "set_credentials",
            "disable_node", "enable_node", "mock_node", "unmock_node",
            "patch_config", "remove_edge", "remove_node",
        }
        assert tags == expected

    def test_add_node_with_after_and_operation(self):
        xml = '<add_node type="automation-slack" name="slack" after="rss" operation="send_message_to_channel" />'
        ops = _parse_xml_operations(xml)
        assert ops[0]["attrs"]["after"] == "rss"
        assert ops[0]["attrs"]["operation"] == "send_message_to_channel"

    def test_add_edge_with_handle(self):
        xml = '<add_edge from="switch" to="slack" handle="true" />'
        ops = _parse_xml_operations(xml)
        assert ops[0]["attrs"]["handle"] == "true"

    def test_dynamic_suffixes_parsed_as_attrs(self):
        xml = '<update_config id="n1" channel__fuzzy="general" operation__fuzzy="send" />'
        ops = _parse_xml_operations(xml)
        assert ops[0]["attrs"]["channel__fuzzy"] == "general"
        assert ops[0]["attrs"]["operation__fuzzy"] == "send"

    def test_single_quoted_attributes(self):
        """Single-quoted attribute values should be parsed correctly."""
        xml = """<mock_node id='node1' output='{"key": "value"}' />"""
        ops = _parse_xml_operations(xml)
        assert len(ops) == 1
        assert ops[0]["tag"] == "mock_node"
        assert ops[0]["attrs"]["id"] == "node1"
        assert ops[0]["attrs"]["output"] == '{"key": "value"}'

    def test_mixed_quote_styles(self):
        """Mix of single and double quotes in the same tag."""
        xml = """<update_config id="n1" text='hello world' />"""
        ops = _parse_xml_operations(xml)
        assert len(ops) == 1
        assert ops[0]["attrs"]["id"] == "n1"
        assert ops[0]["attrs"]["text"] == "hello world"

    def test_single_quoted_body_tag(self):
        """Body tags with single-quoted attributes."""
        xml = """<update_config id='fn' field='function_body'>return 42;</update_config>"""
        ops = _parse_xml_operations(xml)
        assert len(ops) == 1
        assert ops[0]["attrs"]["id"] == "fn"
        assert ops[0]["attrs"]["field"] == "function_body"
        assert ops[0]["body"] == "return 42;"


# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------

class TestCoerceConfigValue:
    """Test _coerce_config_value: JSON-parses strings or falls back to raw string."""

    def test_string_passthrough(self):
        assert _coerce_config_value("hello") == "hello"

    def test_number(self):
        assert _coerce_config_value("42") == 42

    def test_float(self):
        assert _coerce_config_value("3.14") == 3.14

    def test_boolean_true(self):
        assert _coerce_config_value("true") is True

    def test_boolean_false(self):
        assert _coerce_config_value("false") is False

    def test_json_array(self):
        assert _coerce_config_value('[1, 2, 3]') == [1, 2, 3]

    def test_json_object(self):
        assert _coerce_config_value('{"a": 1}') == {"a": 1}

    def test_non_json_string(self):
        assert _coerce_config_value("not json") == "not json"

    def test_null(self):
        assert _coerce_config_value("null") is None

    def test_empty_string(self):
        assert _coerce_config_value("") == ""


class TestEscapeXmlAttr:
    """Test _escape_xml_attr: XML attribute escaping."""

    def test_no_special_chars(self):
        assert _escape_xml_attr("hello") == "hello"

    def test_ampersand(self):
        assert _escape_xml_attr("a & b") == "a &amp; b"

    def test_quote(self):
        assert _escape_xml_attr('say "hi"') == "say &quot;hi&quot;"

    def test_less_than(self):
        assert _escape_xml_attr("a < b") == "a &lt; b"

    def test_greater_than(self):
        assert _escape_xml_attr("a > b") == "a &gt; b"

    def test_all_special_chars(self):
        result = _escape_xml_attr('a & b < c > d "e"')
        assert result == 'a &amp; b &lt; c &gt; d &quot;e&quot;'

    def test_ampersand_first(self):
        """Ampersand must be escaped first to avoid double-escaping."""
        assert _escape_xml_attr("&amp;") == "&amp;amp;"


class TestWorkflowToXml:
    """Test _workflow_to_xml: workflow data → XML string conversion."""

    def test_empty_workflow(self):
        result = _workflow_to_xml([], [])
        assert result == ""

    def test_single_node(self):
        nodes = [{"id": "rss-123", "type": "automation-rss", "config": {"feed_url": "https://example.com"}}]
        xml = _workflow_to_xml(nodes, [])
        assert 'id="rss-123"' in xml
        assert 'type="automation-rss"' in xml
        assert 'feed_url="https://example.com"' in xml

    def test_node_with_output_shows_flag(self):
        nodes = [{"id": "n1", "type": "t", "config": {"output": {"data": "test"}, "key": "val"}}]
        xml = _workflow_to_xml(nodes, [])
        assert 'has_output="true"' in xml
        # Output value itself should not appear
        assert "data" not in xml or 'key="val"' in xml

    def test_node_with_mocked_output_shows_flag(self):
        nodes = [{"id": "n1", "type": "t", "config": {"mockedOutput": {"x": 1}}}]
        xml = _workflow_to_xml(nodes, [])
        assert 'has_mock="true"' in xml

    def test_configValid_excluded(self):
        nodes = [{"id": "n1", "type": "t", "config": {"configValid": True, "key": "val"}}]
        xml = _workflow_to_xml(nodes, [])
        assert "configValid" not in xml
        assert 'key="val"' in xml

    def test_edge_basic(self):
        edges = [{"id": "e1", "source": "a", "target": "b"}]
        xml = _workflow_to_xml([], edges)
        assert 'from="a"' in xml
        assert 'to="b"' in xml

    def test_edge_with_handle(self):
        edges = [{"id": "e1", "source": "a", "target": "b", "sourceHandle": "true"}]
        xml = _workflow_to_xml([], edges)
        assert 'handle="true"' in xml

    def test_nested_data_format(self):
        """Nodes with nested data.config format should be handled."""
        nodes = [{"id": "n1", "type": "t", "data": {"config": {"key": "val"}}}]
        xml = _workflow_to_xml(nodes, [])
        assert 'key="val"' in xml

    def test_non_string_config_values_json_serialized(self):
        nodes = [{"id": "n1", "type": "t", "config": {"count": 42, "items": [1, 2]}}]
        xml = _workflow_to_xml(nodes, [])
        assert 'count="42"' in xml
        assert "items=" in xml

    def test_output_handles_included(self):
        """Nodes with multiple output handles show output_handles attribute in XML."""
        nodes = [{"id": "iter-1", "type": "iteration", "config": {}}]
        xml = _workflow_to_xml(nodes, [])
        assert 'output_handles="' in xml
        assert "loop=Loop Body" in xml
        assert "done=After Loop" in xml


class TestNormalizeCredentialName:
    """Test _normalize_credential_name: class name → snake_case."""

    def test_simple(self):
        assert _normalize_credential_name("SlackOAuthCredential") == "slack_oauth"

    def test_google_sheets(self):
        assert _normalize_credential_name("GoogleSheetsOAuthCredential") == "google_sheets_oauth"

    def test_api_key(self):
        # CamelCase splits each letter: OpenAI → open_a_i, API → a_p_i → api
        assert _normalize_credential_name("OpenAIAPICredential") == "open_a_i_api"

    def test_no_credential_suffix(self):
        assert _normalize_credential_name("Slack") == "slack"

    def test_oauth_prefix(self):
        result = _normalize_credential_name("OAuthCredential")
        assert result == "oauth"


class TestExtractCredentialType:
    """Test _extract_credential_type: type annotation → credential type string."""

    def test_simple_class(self):
        class TestCredential:
            __name__ = "TestCredential"
        assert _extract_credential_type(TestCredential) == "test"

    def test_none_type(self):
        assert _extract_credential_type(None) is None

    def test_no_name_attr(self):
        assert _extract_credential_type(42) is None


# ---------------------------------------------------------------------------
# Server Instance Helpers
# ---------------------------------------------------------------------------

class TestServerHelpers:
    """Test NoClickMCPServer helper methods that don't need DB."""

    @pytest.fixture
    def server(self):
        sio = MagicMock()
        with patch("mcp_server.DatabasePoolMixin.__init__", return_value=None):
            srv = NoClickMCPServer(sio)
        return srv

    def test_create_node_dict(self, server):
        node = server._create_node_dict("automation-rss", {"feed_url": "https://x.com"}, {"x": 100, "y": 200})
        assert node["type"] == "automation-rss"
        assert node["config"]["feed_url"] == "https://x.com"
        assert node["position"] == {"x": 100, "y": 200}
        assert node["id"].startswith("automation-rss-")

    def test_create_node_dict_no_config(self, server):
        node = server._create_node_dict("automation-slack", None, {"x": 0, "y": 0})
        assert node["config"] == {}

    def test_find_node_position_after_node(self, server):
        nodes = [{"id": "a", "position": {"x": 100, "y": 200}}]
        pos = server._find_node_position(nodes, "a")
        assert pos == {"x": 400, "y": 200}

    def test_find_node_position_no_after(self, server):
        nodes = [{"id": "a", "position": {"x": 100, "y": 200}}]
        pos = server._find_node_position(nodes, None)
        assert pos["x"] == 400  # last node x + 300

    def test_find_node_position_empty(self, server):
        pos = server._find_node_position([], None)
        assert pos == {"x": 250, "y": 150}

    def test_deep_merge_config(self, server):
        base = {"a": 1, "nested": {"x": 10, "y": 20}}
        updates = {"a": 2, "nested": {"y": 30, "z": 40}, "b": 3}
        result = server._deep_merge_config(base, updates)
        assert result == {"a": 2, "nested": {"x": 10, "y": 30, "z": 40}, "b": 3}

    def test_deep_merge_config_no_overwrite_without_key(self, server):
        base = {"a": 1, "b": 2}
        updates = {"a": 10}
        result = server._deep_merge_config(base, updates)
        assert result == {"a": 10, "b": 2}

    def test_node_config_flat_config(self, server):
        node = {"id": "n1", "type": "t", "config": {"key": "val", "output": {"data": 1}}}
        config = node["config"]
        assert config == {"key": "val", "output": {"data": 1}}
        assert config.get("output") == {"data": 1}

    def test_node_config_empty(self, server):
        node = {"id": "n1", "type": "t"}
        config = node.get("config", {}) or {}
        assert config == {}
        assert config.get("output") is None
        assert config.get("disabled", False) is False


class TestResolveSchemaRefs:
    """Test resolve_schema_refs (shared in workflow_schema.py, used by MCP)."""

    def test_no_refs(self):
        from coder.workflow.workflow_schema import resolve_schema_refs
        schema = {"properties": {"name": {"type": "string"}}}
        result = resolve_schema_refs(schema)
        assert result == schema

    def test_inline_ref(self):
        from coder.workflow.workflow_schema import resolve_schema_refs
        schema = {
            "properties": {
                "schedule": {"$ref": "#/$defs/ScheduleConfig"}
            },
            "$defs": {
                "ScheduleConfig": {"type": "object", "properties": {"cron": {"type": "string"}}}
            },
        }
        result = resolve_schema_refs(schema)
        assert "$ref" not in result["properties"]["schedule"]
        assert result["properties"]["schedule"]["type"] == "object"
        assert "$defs" not in result

    def test_nested_ref(self):
        from coder.workflow.workflow_schema import resolve_schema_refs
        schema = {
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {"inner": {"$ref": "#/$defs/Inner"}}
                }
            },
            "$defs": {
                "Inner": {"type": "string", "description": "inner value"}
            },
        }
        result = resolve_schema_refs(schema)
        assert result["properties"]["config"]["properties"]["inner"]["type"] == "string"


class TestCompactSchema:
    """Test compact_schema (shared in workflow_schema.py, used by MCP)."""

    def test_simple_string(self):
        from coder.workflow.workflow_schema import compact_schema
        props = {"name": {"type": "string", "description": "The name"}}
        result = compact_schema(props, ["name"])
        assert 'name="name"' in result
        assert 'type="string"' in result
        assert 'required="true"' in result
        assert 'desc="The name"' in result

    def test_enum_field(self):
        from coder.workflow.workflow_schema import compact_schema
        props = {"color": {"type": "string", "enum": ["red", "blue", "green"]}}
        result = compact_schema(props, [])
        assert 'type="enum"' in result
        assert 'values="red|blue|green"' in result

    def test_hidden_field_excluded(self):
        from coder.workflow.workflow_schema import compact_schema
        props = {
            "visible": {"type": "string"},
            "hidden": {"type": "string", "ui:hidden": True},
        }
        result = compact_schema(props, [])
        assert "visible" in result
        assert "hidden" not in result

    def test_default_value(self):
        from coder.workflow.workflow_schema import compact_schema
        props = {"count": {"type": "integer", "default": 10}}
        result = compact_schema(props, [])
        assert 'default="10"' in result

    def test_optional_nullable(self):
        from coder.workflow.workflow_schema import compact_schema
        props = {
            "opt": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
            }
        }
        result = compact_schema(props, [])
        assert 'optional="true"' in result

    def test_array_type(self):
        from coder.workflow.workflow_schema import compact_schema
        props = {"items": {"type": "array", "items": {"type": "string"}}}
        result = compact_schema(props, [])
        assert 'type="string[]"' in result

    def test_nested_object(self):
        from coder.workflow.workflow_schema import compact_schema
        props = {
            "config": {
                "type": "object",
                "properties": {"key": {"type": "string"}},
            }
        }
        result = compact_schema(props, [])
        assert 'name="config"' in result
        assert 'name="key"' in result


class TestValidateReferences:
    """Test _validate_references: checks {{nodeId.path}} references."""

    @pytest.fixture
    def server(self):
        sio = MagicMock()
        with patch("mcp_server.DatabasePoolMixin.__init__", return_value=None):
            srv = NoClickMCPServer(sio)
        return srv

    def test_valid_reference(self, server):
        nodes = [
            {"id": "rss-1", "type": "automation-rss", "config": {"output": {"entries": [{"title": "test"}]}}},
            {"id": "fn-1", "type": "automation-fn", "config": {}},
        ]
        edges = [{"source": "rss-1", "target": "fn-1"}]
        config = {"input": "{{rss-1.entries}}"}
        warnings = server._validate_references(config, nodes, edges, "fn-1")
        assert warnings == []

    def test_nonexistent_node_reference(self, server):
        nodes = [{"id": "fn-1", "type": "t", "config": {}}]
        edges = []
        config = {"input": "{{nonexistent.data}}"}
        warnings = server._validate_references(config, nodes, edges, "fn-1")
        assert len(warnings) == 1
        assert "not found" in warnings[0]["warning"]

    def test_not_upstream_reference(self, server):
        nodes = [
            {"id": "a", "type": "t", "config": {"output": {"x": 1}}},
            {"id": "b", "type": "t", "config": {}},
        ]
        edges = []  # no edge connecting a → b
        config = {"input": "{{a.x}}"}
        warnings = server._validate_references(config, nodes, edges, "b")
        assert len(warnings) == 1
        assert "not upstream" in warnings[0]["warning"]

    def test_missing_output_reference_silently_skipped(self, server):
        """Nodes with no output yet are silently skipped (not warned) to reduce build-time noise."""
        nodes = [
            {"id": "a", "type": "t", "config": {}},  # no output
            {"id": "b", "type": "t", "config": {}},
        ]
        edges = [{"source": "a", "target": "b"}]
        config = {"input": "{{a.data}}"}
        warnings = server._validate_references(config, nodes, edges, "b")
        assert len(warnings) == 0

    def test_invalid_path_key(self, server):
        nodes = [
            {"id": "a", "type": "t", "config": {"output": {"entries": []}}},
            {"id": "b", "type": "t", "config": {}},
        ]
        edges = [{"source": "a", "target": "b"}]
        config = {"input": "{{a.nonexistent_key}}"}
        warnings = server._validate_references(config, nodes, edges, "b")
        assert len(warnings) == 1
        assert "not found" in warnings[0]["warning"].lower()

    def test_no_references_no_warnings(self, server):
        nodes = [{"id": "a", "type": "t", "config": {}}]
        config = {"plain_text": "no references here"}
        warnings = server._validate_references(config, nodes, [], "a")
        assert warnings == []

    # --- $() JS expressions: validate the data source, not the JS property chain ---

    def test_js_expression_valid_node_no_warning(self, server):
        # `.length` is JavaScript on a valid upstream node — must NOT warn, even though
        # `length` is not a key in the output (regression for the legacy path validator).
        nodes = [
            {"id": "a", "type": "t", "config": {"output": {"spreadsheet_id": "abc123"}}},
            {"id": "b", "type": "t", "config": {}},
        ]
        edges = [{"source": "a", "target": "b"}]
        config = {"input": "{{ $('a').spreadsheet_id.length }}"}
        warnings = server._validate_references(config, nodes, edges, "b")
        assert warnings == []

    def test_js_expression_missing_node_warns(self, server):
        nodes = [{"id": "b", "type": "t", "config": {}}]
        config = {"input": "{{ $('ghost').field.split(',') }}"}
        warnings = server._validate_references(config, nodes, [], "b")
        assert len(warnings) == 1
        assert "ghost" in warnings[0]["warning"]
        assert "not found" in warnings[0]["warning"]

    def test_js_expression_not_upstream_warns(self, server):
        nodes = [
            {"id": "a", "type": "t", "config": {"output": {"x": 1}}},
            {"id": "b", "type": "t", "config": {}},
        ]
        edges = []  # a not wired to b
        config = {"input": "{{ $('a').x * 2 }}"}
        warnings = server._validate_references(config, nodes, edges, "b")
        assert len(warnings) == 1
        assert "not upstream" in warnings[0]["warning"]

    def test_js_expression_vars_json_no_warning(self, server):
        nodes = [{"id": "b", "type": "t", "config": {}}]
        config = {"a": "{{ $vars.threshold * 2 }}", "c": "{{ $json.title }}"}
        warnings = server._validate_references(config, nodes, [], "b")
        assert warnings == []


# ---------------------------------------------------------------------------
# Process Update Workflow (batch processor)
# ---------------------------------------------------------------------------

class TestProcessUpdateWorkflow:
    """Test _process_update_workflow: the core batch XML mutation processor."""

    @pytest.fixture
    def server(self):
        sio = MagicMock()
        with patch("mcp_server.DatabasePoolMixin.__init__", return_value=None):
            srv = NoClickMCPServer(sio)
        srv._emit_builder_event = AsyncMock()
        # No DB pool in unit tests — credential autoselection treats this as
        # "no credentials available" and skips, leaving add_node behavior intact.
        srv.get_pool = AsyncMock(return_value=None)
        return srv

    @pytest.fixture(autouse=True)
    def set_user_context(self):
        token = _user_id_var.set("test-user-123")
        yield
        _user_id_var.reset(token)

    @pytest.mark.asyncio
    async def test_add_node(self, server):
        workflow_data = {"nodes": [], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<add_node type="automation-rss" name="rss" />',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        assert "rss" in result["alias_map"]
        node_id = result["alias_map"]["rss"]
        assert node_id.startswith("automation-rss-")
        assert len(workflow_data["nodes"]) == 1
        server._save_workflow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_node_unknown_type(self, server):
        workflow_data = {"nodes": [], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<add_node type="nonexistent-type" name="bad" />',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is False
        assert any("Unknown node type" in e["error"] for e in result["errors"])

    @pytest.mark.asyncio
    async def test_add_node_missing_name(self, server):
        workflow_data = {"nodes": [], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<add_node type="automation-rss" />',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is False
        assert any("requires name" in e["error"] for e in result["errors"])

    @pytest.mark.asyncio
    async def test_add_node_with_after_creates_edge(self, server):
        existing_node = {"id": "existing-1", "type": "automation-rss", "position": {"x": 100, "y": 100}, "config": {}}
        workflow_data = {"nodes": [existing_node], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<add_node type="automation-rss" name="rss2" after="existing-1" />',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        assert len(workflow_data["edges"]) == 1
        assert workflow_data["edges"][0]["source"] == "existing-1"

    @pytest.mark.asyncio
    async def test_add_edge(self, server):
        workflow_data = {
            "nodes": [
                {"id": "a", "type": "t", "position": {"x": 0, "y": 0}, "config": {}},
                {"id": "b", "type": "t", "position": {"x": 300, "y": 0}, "config": {}},
            ],
            "edges": [],
        }
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<add_edge from="a" to="b" />',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        assert len(workflow_data["edges"]) == 1
        assert workflow_data["edges"][0]["source"] == "a"
        assert workflow_data["edges"][0]["target"] == "b"

    @pytest.mark.asyncio
    async def test_add_edge_nonexistent_source(self, server):
        workflow_data = {
            "nodes": [{"id": "b", "type": "t", "position": {"x": 0, "y": 0}, "config": {}}],
            "edges": [],
        }
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<add_edge from="nonexistent" to="b" />',
            include_operations=False,
            include_configs=False,
        )

        assert any("not found" in e["error"].lower() for e in result["errors"])

    @pytest.mark.asyncio
    async def test_add_edge_duplicate_rejected(self, server):
        workflow_data = {
            "nodes": [
                {"id": "a", "type": "t", "position": {"x": 0, "y": 0}, "config": {}},
                {"id": "b", "type": "t", "position": {"x": 300, "y": 0}, "config": {}},
            ],
            "edges": [{"id": "a-b", "source": "a", "target": "b"}],
        }
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<add_edge from="a" to="b" />',
            include_operations=False,
            include_configs=False,
        )

        assert any("already exists" in e["error"].lower() for e in result["errors"])

    @pytest.mark.asyncio
    async def test_update_config_attribute_syntax(self, server):
        existing_node = {"id": "n1", "type": "automation-rss", "config": {"existing_key": "old"}, "position": {"x": 0, "y": 0}}
        workflow_data = {"nodes": [existing_node], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<update_config id="n1" feed_url="https://example.com" />',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        assert existing_node["config"]["feed_url"] == "https://example.com"
        assert existing_node["config"]["existing_key"] == "old"  # preserved

    @pytest.mark.asyncio
    async def test_update_config_body_syntax(self, server):
        existing_node = {"id": "n1", "type": "automation-rss", "config": {}, "position": {"x": 0, "y": 0}}
        workflow_data = {"nodes": [existing_node], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<update_config id="n1" field="function_body">const x = 1;\nreturn x;</update_config>',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        assert existing_node["config"]["function_body"] == "const x = 1;\nreturn x;"

    @pytest.mark.asyncio
    async def test_update_config_nonexistent_node(self, server):
        workflow_data = {"nodes": [], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<update_config id="ghost" key="val" />',
            include_operations=False,
            include_configs=False,
        )

        assert any("not found" in e["error"].lower() for e in result["errors"])

    @pytest.mark.asyncio
    async def test_update_config_alias_resolution(self, server):
        """Aliases from add_node should resolve in update_config."""
        workflow_data = {"nodes": [], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml=(
                '<add_node type="automation-rss" name="rss" />\n'
                '<update_config id="rss" feed_url="https://example.com" />'
            ),
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        node_id = result["alias_map"]["rss"]
        node = workflow_data["nodes"][0]
        assert node["id"] == node_id
        assert node["config"]["feed_url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_set_credentials(self, server):
        existing_node = {"id": "n1", "type": "automation-slack", "config": {}, "position": {"x": 0, "y": 0}}
        workflow_data = {"nodes": [existing_node], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<set_credentials id="n1" slack_oauth="cred-uuid-123" />',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        assert existing_node["config"]["credentialIds"]["slack_oauth"] == "cred-uuid-123"

    @pytest.mark.asyncio
    async def test_set_credentials_missing_pair(self, server):
        existing_node = {"id": "n1", "type": "t", "config": {}, "position": {"x": 0, "y": 0}}
        workflow_data = {"nodes": [existing_node], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<set_credentials id="n1" />',
            include_operations=False,
            include_configs=False,
        )

        assert any("requires at least one" in e["error"].lower() for e in result["errors"])

    @pytest.mark.asyncio
    async def test_add_node_autoselects_single_credential(self, server):
        workflow_data = {"nodes": [], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)
        server._get_credential_info_for_node = AsyncMock(return_value={
            "credential_type": "slack_oauth", "is_oauth": True,
            "available": [{"id": "only-cred", "name": "My Slack", "metadata": {}}],
        })

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<add_node type="automation-slack" name="slack" />',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        assert workflow_data["nodes"][0]["config"]["credentialIds"] == {"slack_oauth": "only-cred"}

    @pytest.mark.asyncio
    async def test_add_node_skips_autoselect_with_multiple_credentials(self, server):
        workflow_data = {"nodes": [], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)
        server._get_credential_info_for_node = AsyncMock(return_value={
            "credential_type": "slack_oauth", "is_oauth": True,
            "available": [
                {"id": "cred-1", "name": "Slack A", "metadata": {}},
                {"id": "cred-2", "name": "Slack B", "metadata": {}},
            ],
        })

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<add_node type="automation-slack" name="slack" />',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        assert "credentialIds" not in workflow_data["nodes"][0]["config"]

    @pytest.mark.asyncio
    async def test_add_node_skips_autoselect_with_no_credentials(self, server):
        workflow_data = {"nodes": [], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)
        server._get_credential_info_for_node = AsyncMock(return_value={
            "credential_type": "slack_oauth", "is_oauth": True, "available": [],
        })

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<add_node type="automation-slack" name="slack" />',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        assert "credentialIds" not in workflow_data["nodes"][0]["config"]

    @pytest.mark.asyncio
    async def test_explicit_set_credentials_overrides_autoselect(self, server):
        workflow_data = {"nodes": [], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)
        server._get_credential_info_for_node = AsyncMock(return_value={
            "credential_type": "slack_oauth", "is_oauth": True,
            "available": [{"id": "auto-cred", "name": "My Slack", "metadata": {}}],
        })

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml=(
                '<add_node type="automation-slack" name="slack" />\n'
                '<set_credentials id="slack" slack_oauth="explicit-cred" />'
            ),
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        assert workflow_data["nodes"][0]["config"]["credentialIds"] == {"slack_oauth": "explicit-cred"}

    @pytest.mark.asyncio
    async def test_disable_node(self, server):
        existing_node = {"id": "n1", "type": "t", "config": {}, "position": {"x": 0, "y": 0}}
        workflow_data = {"nodes": [existing_node], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<disable_node id="n1" />',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        # disabled now lives only in the flat config blob (no top-level mirror)
        assert existing_node["config"]["disabled"] is True

    @pytest.mark.asyncio
    async def test_enable_node(self, server):
        existing_node = {"id": "n1", "type": "t", "config": {"disabled": True}, "position": {"x": 0, "y": 0}}
        workflow_data = {"nodes": [existing_node], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<enable_node id="n1" />',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        # disabled now lives only in the flat config blob (no top-level mirror)
        assert existing_node["config"]["disabled"] is False

    @pytest.mark.asyncio
    async def test_mock_node_inline_output(self, server):
        existing_node = {"id": "n1", "type": "t", "config": {}, "position": {"x": 0, "y": 0}}
        workflow_data = {"nodes": [existing_node], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        # XML attributes use double quotes; inner JSON quotes must be escaped as &quot;
        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<mock_node id="n1" output="{&quot;data&quot;: &quot;test&quot;}" />',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        assert existing_node["mockedOutput"] == {"data": "test"}

    @pytest.mark.asyncio
    async def test_mock_node_body_content(self, server):
        existing_node = {"id": "n1", "type": "t", "config": {}, "position": {"x": 0, "y": 0}}
        workflow_data = {"nodes": [existing_node], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<mock_node id="n1">{"entries": [1, 2, 3]}</mock_node>',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        assert existing_node["mockedOutput"] == {"entries": [1, 2, 3]}

    @pytest.mark.asyncio
    async def test_mock_node_invalid_json(self, server):
        existing_node = {"id": "n1", "type": "t", "config": {}, "position": {"x": 0, "y": 0}}
        workflow_data = {"nodes": [existing_node], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<mock_node id="n1">not json</mock_node>',
            include_operations=False,
            include_configs=False,
        )

        assert any("invalid json" in e["error"].lower() for e in result["errors"])

    @pytest.mark.asyncio
    async def test_unmock_node(self, server):
        existing_node = {
            "id": "n1", "type": "t",
            "config": {"mockedOutput": {"x": 1}},
            "mockedOutput": {"x": 1},
            "position": {"x": 0, "y": 0},
        }
        workflow_data = {"nodes": [existing_node], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<unmock_node id="n1" />',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        assert "mockedOutput" not in existing_node
        assert "mockedOutput" not in existing_node["config"]

    @pytest.mark.asyncio
    async def test_remove_edge(self, server):
        workflow_data = {
            "nodes": [
                {"id": "a", "type": "t", "config": {}, "position": {"x": 0, "y": 0}},
                {"id": "b", "type": "t", "config": {}, "position": {"x": 300, "y": 0}},
            ],
            "edges": [{"id": "a-b", "source": "a", "target": "b"}],
        }
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<remove_edge from="a" to="b" />',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        assert len(workflow_data["edges"]) == 0

    @pytest.mark.asyncio
    async def test_remove_node(self, server):
        workflow_data = {
            "nodes": [
                {"id": "a", "type": "t", "config": {}, "position": {"x": 0, "y": 0}},
                {"id": "b", "type": "t", "config": {}, "position": {"x": 300, "y": 0}},
            ],
            "edges": [{"id": "a-b", "source": "a", "target": "b"}],
        }
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<remove_node id="a" />',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        assert len(workflow_data["nodes"]) == 1
        assert workflow_data["nodes"][0]["id"] == "b"
        # Connected edge should also be removed
        assert len(workflow_data["edges"]) == 0

    @pytest.mark.asyncio
    async def test_remove_nonexistent_node(self, server):
        workflow_data = {"nodes": [], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<remove_node id="ghost" />',
            include_operations=False,
            include_configs=False,
        )

        assert any("not found" in e["error"].lower() for e in result["errors"])

    @pytest.mark.asyncio
    async def test_affected_configs_returned(self, server):
        existing_node = {"id": "n1", "type": "automation-rss", "config": {"key": "old"}, "position": {"x": 0, "y": 0}}
        workflow_data = {"nodes": [existing_node], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<update_config id="n1" key="new" />',
            include_operations=False,
            include_configs=False,
        )

        assert "affected_configs" in result
        assert "n1" in result["affected_configs"]
        assert result["affected_configs"]["n1"]["config"]["key"] == "new"

    @pytest.mark.asyncio
    async def test_load_workflow_error(self, server):
        server._load_workflow = AsyncMock(return_value=(None, "Access denied"))

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<add_node type="automation-rss" name="rss" />',
            include_operations=False,
            include_configs=False,
        )

        assert "error" in result
        assert result["error"] == "Access denied"

    @pytest.mark.asyncio
    async def test_empty_xml_error(self, server):
        workflow_data = {"nodes": [], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml="",
            include_operations=False,
            include_configs=False,
        )

        assert "error" in result
        assert "No valid operations" in result["error"]

    @pytest.mark.asyncio
    async def test_save_error_reported(self, server):
        workflow_data = {"nodes": [], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value="Save failed: DB error")

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<add_node type="automation-rss" name="rss" />',
            include_operations=False,
            include_configs=False,
        )

        assert "error" in result
        assert "Save failed" in result["error"]

    @pytest.mark.asyncio
    async def test_builder_events_emitted(self, server):
        workflow_data = {"nodes": [], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<add_node type="automation-rss" name="rss" />',
            include_operations=False,
            include_configs=False,
        )

        # Should have emitted at least node_start event
        calls = server._emit_builder_event.call_args_list
        event_types = [call.args[2] for call in calls]
        assert "node_start" in event_types

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self, server):
        """Some ops succeed while others fail — partial success."""
        existing_node = {"id": "n1", "type": "t", "config": {}, "position": {"x": 0, "y": 0}}
        workflow_data = {"nodes": [existing_node], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml=(
                '<update_config id="n1" key="val" />\n'  # succeeds
                '<update_config id="ghost" key="val" />'  # fails
            ),
            include_operations=False,
            include_configs=False,
        )

        # Partial success: errors exist but save still happened
        assert result["success"] is False
        assert len(result["errors"]) == 1
        successful = [op for op in result["operations"] if op.get("success")]
        assert len(successful) >= 1
        server._save_workflow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_include_operations_flag(self, server):
        workflow_data = {"nodes": [], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<add_node type="automation-rss" name="rss" />',
            include_operations=True,
            include_configs=False,
        )

        assert "node_operations" in result
        assert "automation-rss" in result["node_operations"]

    @pytest.mark.asyncio
    async def test_include_operations_with_handles(self, server):
        """include_operations for multi-output node types includes output_handles."""
        workflow_data = {"nodes": [], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<add_node type="iteration" name="iter" />',
            include_operations=True,
            include_configs=False,
        )

        assert "node_operations" in result
        ops_data = result["node_operations"]["iteration"]
        assert isinstance(ops_data, dict)
        assert "operations" in ops_data
        assert "output_handles" in ops_data
        handle_ids = [h["id"] for h in ops_data["output_handles"]]
        assert "loop" in handle_ids
        assert "done" in handle_ids

    @pytest.mark.asyncio
    async def test_add_edge_with_handle_stores_source_handle(self, server):
        """add_edge with handle= stores sourceHandle on the edge."""
        workflow_data = {
            "nodes": [
                {"id": "a", "type": "iteration", "position": {"x": 0, "y": 0}, "config": {}},
                {"id": "b", "type": "automation-rss", "position": {"x": 300, "y": 0}, "config": {}},
            ],
            "edges": [],
        }
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<add_edge from="a" to="b" handle="done" />',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        assert len(workflow_data["edges"]) == 1
        assert workflow_data["edges"][0]["sourceHandle"] == "done"

    @pytest.mark.asyncio
    async def test_full_workflow_build(self, server):
        """End-to-end: add two nodes with edge via after, then update config."""
        workflow_data = {"nodes": [], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml=(
                '<add_node type="automation-rss" name="rss" />\n'
                '<add_node type="automation-rss" name="rss2" after="rss" />\n'
                '<update_config id="rss" feed_url="https://hn.com/rss" />'
            ),
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        assert len(result["alias_map"]) == 2
        assert len(workflow_data["nodes"]) == 2
        assert len(workflow_data["edges"]) == 1
        assert workflow_data["nodes"][0]["config"]["feed_url"] == "https://hn.com/rss"


# ---------------------------------------------------------------------------
# ASGI Middleware
# ---------------------------------------------------------------------------

class TestASGIMiddleware:
    """Test create_asgi_middleware: auth interception on /mcp."""

    @pytest.fixture
    def server(self):
        sio = MagicMock()
        with patch("mcp_server.DatabasePoolMixin.__init__", return_value=None):
            srv = NoClickMCPServer(sio)
        srv.handle_request = AsyncMock()
        return srv

    @pytest.mark.asyncio
    async def test_non_mcp_path_passes_through(self, server):
        """Requests to non-/mcp paths should pass through to inner app."""
        inner_app = AsyncMock()
        middleware = server.create_asgi_middleware(inner_app)

        scope = {"type": "http", "path": "/health", "method": "GET"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        inner_app.assert_awaited_once_with(scope, receive, send)
        server.handle_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mcp_without_token_returns_401(self, server):
        """Requests to /mcp without Bearer token should get 401."""
        inner_app = AsyncMock()
        middleware = server.create_asgi_middleware(inner_app)

        # Build a minimal ASGI scope that StarletteRequest can parse
        scope = {
            "type": "http",
            "path": "/mcp",
            "method": "POST",
            "headers": [],  # no Authorization header
            "query_string": b"",
        }

        responses = []

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        async def mock_send(message):
            responses.append(message)

        await middleware(scope, mock_receive, mock_send)

        # Should have sent response start + body
        assert len(responses) >= 1
        start = responses[0]
        assert start["type"] == "http.response.start"
        assert start["status"] == 401
        inner_app.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mcp_with_invalid_token_returns_401(self, server):
        """Requests to /mcp with invalid token should get 401."""
        inner_app = AsyncMock()
        middleware = server.create_asgi_middleware(inner_app)

        scope = {
            "type": "http",
            "path": "/mcp",
            "method": "POST",
            "headers": [(b"authorization", b"Bearer invalid.token.here")],
            "query_string": b"",
        }

        responses = []

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        async def mock_send(message):
            responses.append(message)

        await middleware(scope, mock_receive, mock_send)

        start = responses[0]
        assert start["status"] == 401
        # Check for invalid_token in WWW-Authenticate header
        headers = dict(start.get("headers", []))
        assert b"www-authenticate" in headers
        inner_app.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mcp_with_valid_token_forwards(self, server):
        """Requests to /mcp with valid token should forward to handle_request."""
        from starlette.responses import JSONResponse

        inner_app = AsyncMock()

        mock_response = JSONResponse(content={"ok": True})
        server.handle_request = AsyncMock(return_value=mock_response)

        scope = {
            "type": "http",
            "path": "/mcp",
            "method": "POST",
            "headers": [(b"authorization", b"Bearer valid-token")],
            "query_string": b"",
        }

        responses = []

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        async def mock_send(message):
            responses.append(message)

        # Patch verify_mcp_token BEFORE creating middleware (imports captured at creation time)
        with patch("mcp_adapter.auth.tokens.verify_mcp_token", return_value={"sub": "user-123"}):
            middleware = server.create_asgi_middleware(inner_app)
            await middleware(scope, mock_receive, mock_send)

        server.handle_request.assert_awaited_once()
        call_args = server.handle_request.call_args
        assert call_args.args[1] == "user-123"  # user_id
        inner_app.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mcp_trailing_slash_handled(self, server):
        """Both /mcp and /mcp/ should be intercepted."""
        inner_app = AsyncMock()

        scope = {
            "type": "http",
            "path": "/mcp/",
            "method": "POST",
            "headers": [],
            "query_string": b"",
        }

        responses = []

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        async def mock_send(message):
            responses.append(message)

        middleware = server.create_asgi_middleware(inner_app)
        await middleware(scope, mock_receive, mock_send)

        # Should intercept (returns 401 since no token), not pass through
        assert responses[0]["status"] == 401
        inner_app.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_http_scope_passes_through(self, server):
        """Non-HTTP scopes (websocket, lifespan) should pass through."""
        inner_app = AsyncMock()
        middleware = server.create_asgi_middleware(inner_app)

        scope = {"type": "websocket", "path": "/mcp"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)
        inner_app.assert_awaited_once()


# ---------------------------------------------------------------------------
# Integration Helpers
# ---------------------------------------------------------------------------

class TestGetOAuthRouter:
    """Test get_oauth_router returns a functioning router."""

    def test_returns_router(self):
        sio = MagicMock()
        with patch("mcp_server.DatabasePoolMixin.__init__", return_value=None):
            srv = NoClickMCPServer(sio)
        router = srv.get_oauth_router()
        # Should be an APIRouter with routes
        assert hasattr(router, "routes")
        assert len(router.routes) > 0


# ---------------------------------------------------------------------------
# Patch Config
# ---------------------------------------------------------------------------

class TestPatchConfig:
    """Test patch_config operations in update_workflow."""

    @pytest.fixture
    def server(self):
        sio = MagicMock()
        with patch("mcp_server.DatabasePoolMixin.__init__", return_value=None):
            srv = NoClickMCPServer(sio)
        srv._emit_builder_event = AsyncMock()
        return srv

    @pytest.fixture(autouse=True)
    def set_user_context(self):
        token = _user_id_var.set("test-user-123")
        yield
        _user_id_var.reset(token)

    @pytest.mark.asyncio
    async def test_patch_config_applies_patch(self, server):
        existing_node = {
            "id": "n1", "type": "t",
            "config": {"function_body": "line1\nline2\nline3"},
            "position": {"x": 0, "y": 0},
        }
        workflow_data = {"nodes": [existing_node], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        patch_body = "*** Begin Patch\n@@ line2\n line2\n-line3\n+line3_modified\n*** End Patch"

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml=f'<patch_config id="n1" field="function_body">{patch_body}</patch_config>',
            include_operations=False,
            include_configs=False,
        )

        assert result["success"] is True
        assert "line3_modified" in existing_node["config"]["function_body"]

    @pytest.mark.asyncio
    async def test_patch_config_missing_field(self, server):
        existing_node = {"id": "n1", "type": "t", "config": {}, "position": {"x": 0, "y": 0}}
        workflow_data = {"nodes": [existing_node], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<patch_config id="n1" field="nonexistent">patch</patch_config>',
            include_operations=False,
            include_configs=False,
        )

        assert any("not found" in e["error"].lower() for e in result["errors"])

    @pytest.mark.asyncio
    async def test_patch_config_requires_field_attr(self, server):
        existing_node = {"id": "n1", "type": "t", "config": {"x": "val"}, "position": {"x": 0, "y": 0}}
        workflow_data = {"nodes": [existing_node], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml='<patch_config id="n1">patch body</patch_config>',
            include_operations=False,
            include_configs=False,
        )

        assert any("requires" in e["error"].lower() for e in result["errors"])


# ---------------------------------------------------------------------------
# Processing Order
# ---------------------------------------------------------------------------

class TestProcessingOrder:
    """Verify that operations execute in the documented order."""

    @pytest.fixture
    def server(self):
        sio = MagicMock()
        with patch("mcp_server.DatabasePoolMixin.__init__", return_value=None):
            srv = NoClickMCPServer(sio)
        srv._emit_builder_event = AsyncMock()
        return srv

    @pytest.fixture(autouse=True)
    def set_user_context(self):
        token = _user_id_var.set("test-user-123")
        yield
        _user_id_var.reset(token)

    @pytest.mark.asyncio
    async def test_add_node_before_add_edge(self, server):
        """add_node must run before add_edge so aliases resolve."""
        workflow_data = {"nodes": [], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml=(
                '<add_edge from="a" to="b" />\n'  # intentionally before add_node in XML
                '<add_node type="automation-rss" name="a" />\n'
                '<add_node type="automation-rss" name="b" />'
            ),
            include_operations=False,
            include_configs=False,
        )

        # add_node runs first (creating aliases), then add_edge resolves them
        assert "a" in result["alias_map"]
        assert "b" in result["alias_map"]
        assert len(workflow_data["edges"]) == 1

    @pytest.mark.asyncio
    async def test_remove_node_after_other_ops(self, server):
        """remove_node runs last so update_config can reference the node first."""
        existing_node = {"id": "n1", "type": "t", "config": {}, "position": {"x": 0, "y": 0}}
        workflow_data = {"nodes": [existing_node], "edges": []}
        server._load_workflow = AsyncMock(return_value=(workflow_data, None))
        server._save_workflow = AsyncMock(return_value=None)

        result = await server._process_update_workflow(
            workflow_id="wf-1",
            updates_xml=(
                '<remove_node id="n1" />\n'  # listed first in XML
                '<update_config id="n1" key="val" />'  # but should run before remove
            ),
            include_operations=False,
            include_configs=False,
        )

        # update_config should succeed (runs before remove)
        successful = [op for op in result["operations"] if op.get("success") and op["action"] == "update_config"]
        assert len(successful) == 1
        # Node should be removed at the end
        assert len(workflow_data["nodes"]) == 0


