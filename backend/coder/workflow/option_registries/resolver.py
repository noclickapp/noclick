"""
Field-write resolver for queryable-enum schema fields.

When a field declares ``x-queryable-enum: "<registry>"`` in its JSON schema,
``resolve_field_value`` looks the value up in the named registry, returns the
canonical id (overwriting whatever the brain or node drafting wrote), and produces
a Resolution record for the next-turn execution summary. Inputs that look
like reference expressions (``{{node.field}}`` or ``{{ $('node').field }}``)
are passed through untouched since they're runtime expressions, not literal ids.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from . import get_registry
from .base import Resolution


def _is_reference_expression(value: str) -> bool:
    """True for any ``{{ ... }}`` reference/expression (legacy or `$()`) — never resolve those."""
    if not isinstance(value, str):
        return False
    return "{{" in value and "}}" in value


def _resolve_property_schema(
    schema: Dict[str, Any], field_name: str,
) -> Optional[Dict[str, Any]]:
    """Find the property schema for *field_name* inside a (possibly union'd)
    operation schema.

    Walks ``properties`` directly first, then dives into ``oneOf``/``anyOf``
    branches (for discriminated unions like AgentConfig). Returns the first
    match — within a single union the per-branch schemas for shared fields
    carry identical x-queryable-enum metadata.
    """
    if not schema:
        return None
    props = schema.get("properties") or {}
    if field_name in props:
        return props[field_name]
    for branch in (schema.get("oneOf") or []) + (schema.get("anyOf") or []):
        if not isinstance(branch, dict):
            continue
        nested = _resolve_property_schema(branch, field_name)
        if nested:
            return nested
    return None


def get_queryable_registry_name(
    schema: Optional[Dict[str, Any]], field_name: str,
) -> Optional[str]:
    """Return the registry name declared on *field_name*, or None."""
    prop = _resolve_property_schema(schema or {}, field_name)
    if not prop:
        return None
    return prop.get("x-queryable-enum")


def resolve_field_value(
    schema: Optional[Dict[str, Any]],
    field_name: str,
    value: Any,
) -> Tuple[Any, Optional[Resolution]]:
    """Resolve *value* against the field's queryable-enum registry, if any.

    Returns ``(resolved_value, Resolution or None)``. The resolved value is
    the canonical id when matched; otherwise the original value is preserved
    so the brain still sees what it wrote (alongside the alternatives in the
    Resolution record).

    Non-string values, references (`{{...}}`), and fields without the
    ``x-queryable-enum`` annotation are passed through with no Resolution.
    """
    if not isinstance(value, str) or not value.strip():
        return value, None
    if _is_reference_expression(value):
        return value, None

    registry_name = get_queryable_registry_name(schema, field_name)
    if not registry_name:
        return value, None

    registry = get_registry(registry_name)
    if registry is None:
        return value, None

    resolution = registry.match(value)
    resolution.field_name = field_name

    # Exact-id matches don't need to surface alternatives.
    if resolution.exact:
        return resolution.matched_id, resolution

    if resolution.matched_id and resolution.matched_id != value:
        return resolution.matched_id, resolution

    # Either a weak match (matched_id is None) or a confident match that
    # happened to equal the input string. In both cases keep the original
    # value; the Resolution still carries alternatives the brain can use.
    return value, resolution


def resolve_config_dict(
    schema: Optional[Dict[str, Any]],
    config: Dict[str, Any],
) -> list[Resolution]:
    """Resolve every queryable-enum field in *config* in place.

    Walks the keys of *config*, looks each up in the schema, and rewrites the
    value to the canonical id when a match is found. Returns the Resolutions
    for non-exact matches so the caller can attach them to the node's
    ``pending_resolutions``.
    """
    if not config or not schema:
        return []
    resolutions: list[Resolution] = []
    for field_name, value in list(config.items()):
        stored, resolution = resolve_field_value(schema, field_name, value)
        if resolution is None:
            continue
        if stored != value:
            config[field_name] = stored
        if not resolution.exact:
            resolutions.append(resolution)
    return resolutions


def format_resolution_block(resolution: Resolution) -> list[str]:
    """Format a Resolution record as lines for the execution summary.

    Returns an empty list for exact matches (nothing surprising to surface).
    """
    if resolution.exact or resolution.matched_id is None and not resolution.alternatives:
        return []

    lines: list[str] = []
    if resolution.matched_id and resolution.matched_id != resolution.original:
        head = (
            f"    {resolution.field_name}: matched {resolution.matched_id!r} "
            f"from {resolution.original!r}"
        )
        if resolution.matched_label:
            head += f" — {resolution.matched_label}"
        lines.append(head)
    elif resolution.matched_id is None:
        lines.append(
            f"    {resolution.field_name}: [unresolved] {resolution.original!r} "
            f"did not match any registered option"
        )

    if resolution.alternatives:
        lines.append("      alternatives:")
        for alt in resolution.alternatives:
            desc = f" — {alt.description}" if alt.description else ""
            lines.append(f"        {alt.id}{desc}")
        lines.append(
            "      → To switch, emit "
            f"<field name=\"{resolution.field_name}\" node=\"<id>\" value=\"<canonical-id>\" />"
        )
    return lines
