"""Tests for the shared schema processing utilities (workflow_schema.py)."""

import pytest

from coder.workflow.workflow_schema import (
    all_schema_paths,
    resolve_schema_refs,
    compact_schema,
    extract_output_paths,
    get_discriminator_field,
    is_account_dynamic_field,
    strip_discriminator,
    validate_references,
)


class TestAllSchemaPaths:
    def test_flat_dict(self):
        assert all_schema_paths({"name": "string", "age": "integer"}) == {"name", "age"}

    def test_array_of_objects_expands(self):
        # `rows[].id` style is what the LLM must use for validation.
        paths = all_schema_paths({"rows": [{"id": "integer", "name": "string"}]})
        assert paths == {"rows", "rows[].id", "rows[].name"}

    def test_nested_objects(self):
        paths = all_schema_paths({"user": {"name": "string", "address": {"city": "string"}}})
        assert paths == {"user", "user.name", "user.address", "user.address.city"}

    def test_primitive_array_keeps_parent_only(self):
        # Primitive arrays don't expand — there's nothing to drill into.
        assert all_schema_paths({"tags": ["string"]}) == {"tags"}

    def test_non_dict_input_returns_empty(self):
        assert all_schema_paths("string") == set()
        assert all_schema_paths([]) == set()
        assert all_schema_paths(None) == set()

    def test_empty_dict(self):
        assert all_schema_paths({}) == set()


# ---------------------------------------------------------------------------
# resolve_schema_refs
# ---------------------------------------------------------------------------

class TestResolveSchemaRefs:
    def test_no_defs_returns_unchanged(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        result = resolve_schema_refs(schema)
        assert result == schema

    def test_resolves_simple_ref(self):
        schema = {
            "$defs": {"Foo": {"type": "object", "properties": {"x": {"type": "int"}}}},
            "properties": {"bar": {"$ref": "#/$defs/Foo"}},
        }
        result = resolve_schema_refs(schema)
        assert "$defs" not in result
        assert result["properties"]["bar"]["type"] == "object"
        assert "x" in result["properties"]["bar"]["properties"]

    def test_preserves_sibling_keys(self):
        schema = {
            "$defs": {"Foo": {"type": "string"}},
            "properties": {
                "bar": {"$ref": "#/$defs/Foo", "description": "A bar field"},
            },
        }
        result = resolve_schema_refs(schema)
        bar = result["properties"]["bar"]
        assert bar["type"] == "string"
        assert bar["description"] == "A bar field"

    def test_nested_refs(self):
        schema = {
            "$defs": {
                "Inner": {"type": "number"},
                "Outer": {"type": "object", "properties": {"val": {"$ref": "#/$defs/Inner"}}},
            },
            "properties": {"top": {"$ref": "#/$defs/Outer"}},
        }
        result = resolve_schema_refs(schema)
        assert result["properties"]["top"]["properties"]["val"]["type"] == "number"
        assert "$defs" not in result

    def test_removes_defs_key(self):
        schema = {
            "$defs": {"A": {"type": "string"}},
            "properties": {"x": {"$ref": "#/$defs/A"}},
        }
        result = resolve_schema_refs(schema)
        assert "$defs" not in result

    def test_unknown_ref_preserved(self):
        schema = {
            "$defs": {},
            "properties": {"x": {"$ref": "#/$defs/Missing"}},
        }
        result = resolve_schema_refs(schema)
        # Unknown ref should stay as-is
        assert result["properties"]["x"]["$ref"] == "#/$defs/Missing"

    def test_does_not_mutate_original(self):
        schema = {
            "$defs": {"A": {"type": "string"}},
            "properties": {"x": {"$ref": "#/$defs/A"}},
        }
        original_props = dict(schema["properties"])
        resolve_schema_refs(schema)
        assert schema["properties"] == original_props


# ---------------------------------------------------------------------------
# compact_schema
# ---------------------------------------------------------------------------

class TestCompactSchema:
    def test_simple_string_field(self):
        result = compact_schema({"name": {"type": "string"}}, [])
        assert 'name="name"' in result
        assert 'type="string"' in result

    def test_required_field(self):
        result = compact_schema({"name": {"type": "string"}}, ["name"])
        assert 'required="true"' in result

    def test_not_required_field(self):
        result = compact_schema({"name": {"type": "string"}}, [])
        assert "required" not in result

    def test_enum_field(self):
        result = compact_schema(
            {"color": {"type": "string", "enum": ["red", "green", "blue"]}},
            [],
        )
        assert 'type="enum"' in result
        assert 'values="red|green|blue"' in result

    def test_hidden_field_excluded(self):
        result = compact_schema(
            {
                "visible": {"type": "string"},
                "hidden": {"type": "string", "ui:hidden": True},
            },
            [],
        )
        assert "visible" in result
        assert "hidden" not in result

    def test_nested_object(self):
        result = compact_schema(
            {
                "options": {
                    "type": "object",
                    "properties": {
                        "timeout": {"type": "integer"},
                    },
                },
            },
            [],
        )
        assert 'name="options"' in result
        assert 'name="timeout"' in result
        assert "</field>" in result  # closing tag for nested object

    def test_nullable_field(self):
        result = compact_schema(
            {"val": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
            [],
        )
        assert 'optional="true"' in result
        assert 'type="string"' in result

    def test_integer_becomes_int(self):
        result = compact_schema({"count": {"type": "integer"}}, [])
        assert 'type="int"' in result

    def test_array_type(self):
        result = compact_schema(
            {"items": {"type": "array", "items": {"type": "string"}}},
            [],
        )
        assert 'type="string[]"' in result

    def test_field_with_default(self):
        result = compact_schema(
            {"port": {"type": "integer", "default": 8080}},
            [],
        )
        assert 'default="8080"' in result

    def test_field_with_string_default(self):
        result = compact_schema(
            {"mode": {"type": "string", "default": "auto"}},
            [],
        )
        assert 'default="auto"' in result

    def test_field_with_description(self):
        result = compact_schema(
            {"url": {"type": "string", "description": "The API endpoint"}},
            [],
        )
        assert 'desc="The API endpoint"' in result

    def test_field_with_range(self):
        result = compact_schema(
            {"temp": {"type": "number", "minimum": 0, "maximum": 100}},
            [],
        )
        assert 'range="0-100"' in result

    def test_field_with_placeholder(self):
        result = compact_schema(
            {"url": {"type": "string", "placeholder": "https://..."}},
            [],
        )
        assert 'placeholder="https://..."' in result

    def test_placeholder_hidden_when_default_exists(self):
        result = compact_schema(
            {"url": {"type": "string", "default": "http://localhost", "placeholder": "https://..."}},
            [],
        )
        assert "placeholder" not in result

    def test_empty_properties(self):
        result = compact_schema({}, [])
        assert result == ""

    def test_dict_default(self):
        result = compact_schema(
            {"opts": {"type": "object", "default": {"a": 1}}},
            [],
        )
        assert 'default=' in result


# ---------------------------------------------------------------------------
# extract_output_paths
# ---------------------------------------------------------------------------

class TestExtractOutputPaths:
    def test_simple_dict(self):
        paths = extract_output_paths({"name": "John", "age": 30})
        assert paths == ["name", "age"]

    def test_array_of_objects(self):
        paths = extract_output_paths({"rows": [{"id": 1, "name": "x"}]})
        assert paths == ["rows[].id", "rows[].name"]

    def test_mixed_types(self):
        paths = extract_output_paths({
            "status": 200,
            "rows": [{"id": 1, "name": "x"}],
            "count": 5,
        })
        assert "status" in paths
        assert "rows[].id" in paths
        assert "rows[].name" in paths
        assert "count" in paths

    def test_empty_dict(self):
        assert extract_output_paths({}) == []

    def test_respects_max_keys(self):
        data = {f"key_{i}": i for i in range(20)}
        paths = extract_output_paths(data, max_keys=3)
        assert len(paths) == 3

    def test_respects_max_subkeys(self):
        data = {"rows": [{"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}]}
        paths = extract_output_paths(data, max_subkeys=2)
        assert len(paths) == 2

    def test_empty_array(self):
        paths = extract_output_paths({"items": []})
        assert paths == ["items"]

    def test_array_of_non_objects(self):
        paths = extract_output_paths({"tags": ["a", "b", "c"]})
        assert paths == ["tags"]

    def test_type_descriptor_dict(self):
        """Works with schema tracker format where values are type strings."""
        paths = extract_output_paths({"rows": [{"id": "integer", "name": "string"}]})
        assert paths == ["rows[].id", "rows[].name"]


# ---------------------------------------------------------------------------
# get_discriminator_field
# ---------------------------------------------------------------------------

class TestGetDiscriminatorField:
    def test_default_is_operation(self):
        # Unknown node type should default to "operation"
        assert get_discriminator_field("nonexistent-node-type") == "operation"

    def test_known_operation_node(self):
        # automation-slack uses "operation" discriminator
        result = get_discriminator_field("automation-slack")
        assert result in ("operation", "action")

    def test_returns_string(self):
        result = get_discriminator_field("automation-gmail")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# strip_discriminator
# ---------------------------------------------------------------------------

class TestStripDiscriminator:
    def test_strips_operation_field(self):
        schema = {
            "properties": {
                "operation": {"type": "string"},
                "channel": {"type": "string"},
            },
            "required": ["operation", "channel"],
        }
        props, required = strip_discriminator(schema, "nonexistent-type")
        assert "operation" not in props
        assert "operation" not in required
        assert "channel" in props
        assert "channel" in required

    def test_preserves_other_fields(self):
        schema = {
            "properties": {
                "operation": {"type": "string"},
                "url": {"type": "string"},
                "method": {"type": "string"},
            },
            "required": ["operation", "url"],
        }
        props, required = strip_discriminator(schema, "nonexistent-type")
        assert "url" in props
        assert "method" in props
        assert "url" in required

    def test_does_not_mutate_original(self):
        schema = {
            "properties": {"operation": {"type": "string"}, "x": {"type": "string"}},
            "required": ["operation"],
        }
        original_props = dict(schema["properties"])
        strip_discriminator(schema, "nonexistent-type")
        assert schema["properties"] == original_props

    def test_handles_missing_properties(self):
        props, required = strip_discriminator({}, "nonexistent-type")
        assert props == {}
        assert required == []


# ---------------------------------------------------------------------------
# is_account_dynamic_field
# ---------------------------------------------------------------------------

class TestIsAccountDynamicField:
    """node drafter coerces fills on account-loaded dynamic fields to user_input
    (the builder then asks the user). Queryable-enum fields like agent.model
    must NOT classify as account-loaded — they're registry-resolved, so the
    builder fills them silently instead of asking which model to use."""

    def test_account_picker_field_is_dynamic(self):
        prop = {"type": "string", "x-dynamic-options": {"field_name": "spreadsheet_id"}}
        assert is_account_dynamic_field(prop)

    def test_queryable_enum_field_is_not(self):
        prop = {
            "type": "string",
            "x-queryable-enum": "models",
            "x-dynamic-options": {"field_name": "model"},
        }
        assert not is_account_dynamic_field(prop)

    def test_plain_field_is_not(self):
        assert not is_account_dynamic_field({"type": "string"})
        assert not is_account_dynamic_field(None)

    def test_agent_model_field_classifies_as_registry_resolved(self):
        # Against the real schema, the same way fill_schema builds its
        # dynamic-field set — pins that agent.model never triggers an ask.
        from coder.workflow.operation_catalog import get_operation_schema

        schema = resolve_schema_refs(get_operation_schema("agent", "default"))
        props, _ = strip_discriminator(schema, "agent")
        assert "model" in props
        assert not is_account_dynamic_field(props["model"])


# ---------------------------------------------------------------------------
# validate_references
# ---------------------------------------------------------------------------

class TestValidateReferences:
    def test_valid_reference(self):
        config = {"message": "Hello {{upstream.name}}"}
        warnings = validate_references(
            config,
            upstream_ids={"upstream"},
            all_node_ids={"upstream", "current"},
        )
        assert warnings == []

    def test_node_not_found(self):
        config = {"message": "{{nonexistent.data}}"}
        warnings = validate_references(
            config,
            upstream_ids={"upstream"},
            all_node_ids={"upstream", "current"},
        )
        assert len(warnings) == 1
        assert "not found" in warnings[0]["warning"]

    def test_node_not_upstream(self):
        config = {"message": "{{downstream.data}}"}
        warnings = validate_references(
            config,
            upstream_ids={"upstream"},
            all_node_ids={"upstream", "downstream", "current"},
        )
        assert len(warnings) == 1
        assert "not upstream" in warnings[0]["warning"]

    def test_nested_config_values(self):
        config = {"opts": {"text": "{{nonexistent.data}}"}}
        warnings = validate_references(
            config,
            upstream_ids=set(),
            all_node_ids={"current"},
        )
        assert len(warnings) == 1
        assert warnings[0]["field"] == "opts.text"

    def test_no_references(self):
        config = {"message": "Hello world", "count": 5}
        warnings = validate_references(
            config,
            upstream_ids=set(),
            all_node_ids={"current"},
        )
        assert warnings == []

    def test_multiple_references_in_one_value(self):
        config = {"text": "{{a.name}} from {{b.city}}"}
        warnings = validate_references(
            config,
            upstream_ids={"a", "b"},
            all_node_ids={"a", "b", "current"},
        )
        assert warnings == []

    def test_multiple_references_mixed_validity(self):
        config = {"text": "{{a.name}} from {{missing.city}}"}
        warnings = validate_references(
            config,
            upstream_ids={"a"},
            all_node_ids={"a", "current"},
        )
        assert len(warnings) == 1
        assert "missing" in warnings[0]["warning"]

    # --- $() JS expressions (regression: the property chain is JS, not a path) ---

    def test_js_expression_valid_node_no_warning(self):
        # `.length`/`.split()` are JavaScript on a valid node — must NOT warn.
        config = {"x": "{{ $('upstream').spreadsheet_id.length }}"}
        warnings = validate_references(
            config, upstream_ids={"upstream"}, all_node_ids={"upstream", "current"}
        )
        assert warnings == []

    def test_js_expression_missing_node_warns(self):
        config = {"x": "{{ $('ghost').field.split(',') }}"}
        warnings = validate_references(
            config, upstream_ids={"upstream"}, all_node_ids={"upstream", "current"}
        )
        assert len(warnings) == 1
        assert "ghost" in warnings[0]["warning"]

    def test_js_expression_multi_ref_flags_only_bad_one(self):
        config = {"x": "{{ $('a').y + $('downstream').z.toUpperCase() }}"}
        warnings = validate_references(
            config, upstream_ids={"a"}, all_node_ids={"a", "downstream", "current"}
        )
        assert len(warnings) == 1
        assert "downstream" in warnings[0]["warning"]
        assert "not upstream" in warnings[0]["warning"]

    def test_js_expression_vars_and_json_never_warn(self):
        # `$vars` / `$json` are not nodes — they have no graph reference to validate.
        config = {"x": "{{ $vars.threshold * 2 }}", "y": "{{ $json.title }}"}
        warnings = validate_references(
            config, upstream_ids=set(), all_node_ids={"current"}
        )
        assert warnings == []

    def test_empty_config(self):
        assert validate_references({}, set(), set()) == []
