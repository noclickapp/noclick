"""Shared schema utilities for workflow nodes and public builder tools."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from .workflow_xml import escape_xml_attr
from utils.expression_evaluator import is_js_expression, extract_expression_node_ids


# ---------------------------------------------------------------------------
# Schema resolution
# ---------------------------------------------------------------------------

def inline_schema_refs(fragment: Any, defs: Dict[str, Any]) -> Any:
    """Recursively inline ``$ref`` pointers against ``defs``, merging any
    sibling keys (``title``, ``description``, etc.) over the resolved target.

    Cycle-safe: a definition reached again along the same resolution path
    keeps its remaining keys instead of recursing forever. Use directly for
    schema fragments (e.g. one union member's properties, which ship
    standalone into agent tool definitions); ``resolve_schema_refs`` wraps it
    for whole schemas.
    """
    def _resolve(obj: Any, seen: frozenset) -> Any:
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref_name = obj["$ref"].rsplit("/", 1)[-1]
                if ref_name in seen:
                    return {k: _resolve(v, seen) for k, v in obj.items() if k != "$ref"}
                if ref_name in defs:
                    merged = dict(defs[ref_name])
                    for k, v in obj.items():
                        if k != "$ref":
                            merged[k] = v
                    return _resolve(merged, seen | {ref_name})
            return {k: _resolve(v, seen) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_resolve(item, seen) for item in obj]
        return obj

    return _resolve(fragment, frozenset())


def resolve_schema_refs(schema: dict) -> dict:
    """Inline ``$ref`` pointers from ``$defs`` in a JSON Schema.

    Delegates to ``inline_schema_refs`` (single inliner definition, shared
    with the agent node_op tool builder). The ``$defs`` key is removed from
    the result. Returns the original schema unchanged if there are no
    ``$defs``.
    """
    defs = schema.get("$defs", {})
    if not defs:
        return schema

    result = inline_schema_refs(schema, defs)
    result.pop("$defs", None)
    return result


# ---------------------------------------------------------------------------
# Compact schema for LLM consumption
# ---------------------------------------------------------------------------

def compact_schema(properties: dict, required: list) -> str:
    """Convert JSON Schema properties into compact XML for LLM consumption.

    Format::

        <field name="x" type="string" required="true" desc="..." />

    Features:

    - Hidden fields (``ui:hidden``) are omitted.
    - Nested object fields become child ``<field>`` elements.
    - Enum values shown as ``values="a|b|c"``.
    - ~60 % fewer tokens than raw JSON Schema.
    """

    def _parse_inner(prop: dict) -> tuple:
        """Extract the non-null variant, nullable flag, and nested props."""
        nullable = False
        inner = prop
        if "anyOf" in prop:
            variants = [v for v in prop["anyOf"] if v.get("type") != "null"]
            nullable = len(variants) < len(prop["anyOf"])
            inner = variants[0] if variants else prop
        nested = None
        if inner.get("type") == "object" and "properties" in inner:
            nested = inner["properties"]
        elif inner.get("type") == "array":
            items = inner.get("items", {})
            if items.get("type") == "object" and "properties" in items:
                nested = items["properties"]
        return inner, nullable, nested

    def _type_str(inner: dict) -> str:
        t = inner.get("type", "any")
        if "enum" in inner:
            return "enum"
        if t == "integer":
            return "int"
        if t == "array":
            return f"{inner.get('items', {}).get('type', 'any')}[]"
        return t

    def _field_xml(name: str, prop: dict, indent: int = 0) -> list:
        if prop.get("ui:hidden"):
            return []

        inner, nullable, nested = _parse_inner(prop)
        prefix = "  " * indent
        attrs = [f'name="{escape_xml_attr(name)}"']
        attrs.append(f'type="{_type_str(inner)}"')

        if name in required:
            attrs.append('required="true"')
        if nullable:
            attrs.append('optional="true"')
        if "enum" in inner:
            attrs.append(f'values="{"|".join(str(v) for v in inner["enum"])}"')
        if "minimum" in inner or "maximum" in inner:
            lo = inner.get("minimum", "")
            hi = inner.get("maximum", "")
            attrs.append(f'range="{lo}-{hi}"')
        default = prop.get("default")
        # Hide the schema default for queryable fields entirely. Small schema-
        # filler models pattern-match `default=` and copy it verbatim, ignoring
        # the queryable instruction in the system prompt. Removing the attribute
        # forces them to read the goal / user description for the value.
        is_queryable = bool(prop.get("x-queryable-enum"))
        if default is not None and not is_queryable:
            if isinstance(default, dict):
                attrs.append(f'default="{escape_xml_attr(json.dumps(default, separators=(",", ":")))}"')
            elif isinstance(default, str):
                attrs.append(f'default="{escape_xml_attr(default)}"')
            else:
                attrs.append(f'default="{default}"')
        placeholder = prop.get("placeholder")
        if placeholder and default is None:
            attrs.append(f'placeholder="{escape_xml_attr(placeholder)}"')
        desc = prop.get("description")
        if desc:
            attrs.append(f'desc="{escape_xml_attr(desc)}"')
        # Surface x-queryable-enum so node drafter (and any other consumer) knows the
        # field accepts fuzzy values which the field-write resolver canonicalizes.
        # Letting node drafter see this is what makes it copy the user's wording into
        # the value instead of falling back to the schema default.
        queryable = prop.get("x-queryable-enum")
        if queryable:
            attrs.append(f'queryable="{escape_xml_attr(queryable)}"')
        hint = prop.get("x-enum-hint")
        if hint:
            attrs.append(f'hint="{escape_xml_attr(hint)}"')

        lines = []
        if nested:
            lines.append(f'{prefix}<field {" ".join(attrs)}>')
            for sub_name, sub_prop in nested.items():
                lines.extend(_field_xml(sub_name, sub_prop, indent + 1))
            lines.append(f'{prefix}</field>')
        else:
            lines.append(f'{prefix}<field {" ".join(attrs)} />')
        return lines

    result: list = []
    for name, prop in properties.items():
        result.extend(_field_xml(name, prop))
    return "\n".join(result)


# ---------------------------------------------------------------------------
# Field classification
# ---------------------------------------------------------------------------

def is_account_dynamic_field(prop: Any) -> bool:
    """Whether a property schema is an x-dynamic-options field whose options
    load from the user's connected account (sheet/channel/document pickers).

    Queryable-enum fields (e.g. agent.model) also carry x-dynamic-options for
    the frontend picker, but their values are canonicalized server-side by the
    option registry — node drafter fills are trustworthy and no user input is needed
    during build, so they are excluded.
    """
    return (
        isinstance(prop, dict)
        and isinstance(prop.get("x-dynamic-options"), dict)
        and not prop.get("x-queryable-enum")
    )


# ---------------------------------------------------------------------------
# Output path extraction
# ---------------------------------------------------------------------------

def extract_output_paths(
    output_data: dict,
    max_keys: int = 15,
    max_subkeys: int = 8,
) -> List[str]:
    """Extract concrete reference paths from node output data or schema.

    Works on both actual output dicts (from execution) and type-descriptor
    dicts from the ``workflow_node_output_schemas`` table.

    Returns paths like ``["rows", "rows[].id", "rows[].name", "status"]``.
    """
    paths: List[str] = []
    for k, v in list(output_data.items())[:max_keys]:
        if isinstance(v, list) and v and isinstance(v[0], dict):
            for sk in list(v[0].keys())[:max_subkeys]:
                paths.append(f"{k}[].{sk}")
        else:
            paths.append(k)
    return paths


def all_schema_paths(schema: Any, max_depth: int = 10) -> Set[str]:
    """Walk a type-descriptor schema and emit every reachable reference path.

    Non-capped sibling of :func:`extract_output_paths` used to validate
    LLM-curated suggestions against the schema. Arrays of objects expand
    via ``[]`` (``rows[].id``); arrays of primitives keep their parent key.

    Accepts schemas from ``workflow_node_output_schemas.output_schema``
    (type descriptors like ``{"rows": [{"id": "integer"}]}``) and raw
    output dicts alike.
    """
    paths: Set[str] = set()

    def _walk(node: Any, prefix: str, depth: int) -> None:
        if depth <= 0:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                p = f"{prefix}.{k}" if prefix else k
                paths.add(p)
                _walk(v, p, depth - 1)
        elif isinstance(node, list) and node:
            first = node[0]
            if isinstance(first, dict):
                _walk(first, f"{prefix}[]", depth - 1)

    if isinstance(schema, dict):
        _walk(schema, "", max_depth)
    return paths


# ---------------------------------------------------------------------------
# Discriminator detection & stripping
# ---------------------------------------------------------------------------

def get_discriminator_field(node_type: str) -> str:
    """Return the discriminator field name for a node type.

    All nodes use ``operation`` as the discriminator field.
    """
    return "operation"


def strip_discriminator(
    schema: dict,
    node_type: str,
) -> Tuple[dict, list]:
    """Remove the discriminator field from schema properties and required.

    The discriminator (``operation``) is set separately, so including it in
    the schema shown to the LLM is confusing.

    Returns ``(properties, required)`` with the discriminator removed.
    """
    props = dict(schema.get("properties", {}))
    required = list(schema.get("required", []))
    disc_field = get_discriminator_field(node_type)
    props.pop(disc_field, None)
    if disc_field in required:
        required.remove(disc_field)
    return props, required


# ---------------------------------------------------------------------------
# Reference validation (structural)
# ---------------------------------------------------------------------------

_REFERENCE_PATTERN = re.compile(r"\{\{([^}]+)\}\}")


def validate_references(
    config: Dict[str, Any],
    upstream_ids: Set[str],
    all_node_ids: Set[str],
) -> List[Dict[str, str]]:
    """Validate node references in config values — both legacy ``{{nodeId.path}}``
    and ``$()`` expressions like ``{{ $('nodeId').field.split(',') }}``.

    Performs *structural* validation only:

    1. Referenced node exists in the workflow.
    2. Referenced node is upstream of the current node.

    For a ``$()`` expression, only its ``$('id')`` data sources are checked (the JS
    property chain isn't a navigable path). Does **not** validate path correctness
    (no execution output available during generation).  The MCP server's
    ``_validate_references`` performs full path-through-output validation when
    actual outputs are available.

    Returns a list of warning dicts with ``field``, ``reference``, ``warning``
    keys (empty list if all references are valid).
    """
    warnings: List[Dict[str, str]] = []

    def _check_value(field: str, value: Any) -> None:
        if isinstance(value, str):
            for match in _REFERENCE_PATTERN.finditer(value):
                ref_path = match.group(1)
                # A `$()` JS expression: only its `$('id')` data sources are
                # graph-validatable (the property chain is JavaScript). A legacy
                # `{{nodeId.path}}` reference validates its leading node id.
                if is_js_expression(ref_path):
                    from coder.workflow.workflow_ops import (
                        _FOREIGN_ACCESSOR_RE, foreign_expression_error,
                    )
                    foreign = _FOREIGN_ACCESSOR_RE.search(ref_path)
                    if foreign:
                        warnings.append({
                            "field": field,
                            "reference": f"{{{{{ref_path}}}}}",
                            "warning": foreign_expression_error(field, foreign.group(0).strip()),
                        })
                    ref_node_ids = extract_expression_node_ids(ref_path)
                else:
                    ref_node_ids = [ref_path.strip().split(".")[0]]

                for ref_node_id in ref_node_ids:
                    if ref_node_id not in all_node_ids:
                        warnings.append({
                            "field": field,
                            "reference": f"{{{{{ref_path}}}}}",
                            "warning": f"Referenced node '{ref_node_id}' not found in workflow",
                        })
                    elif ref_node_id not in upstream_ids:
                        warnings.append({
                            "field": field,
                            "reference": f"{{{{{ref_path}}}}}",
                            "warning": f"Referenced node '{ref_node_id}' is not upstream",
                        })
        elif isinstance(value, dict):
            for k, v in value.items():
                _check_value(f"{field}.{k}", v)

    for field, value in config.items():
        _check_value(field, value)

    return warnings
