"""The secrets in a step's settings: what no read of a workflow shows, and what a write that never saw them keeps.

A setting is a secret when its schema marks it (``writeOnly``, a password format or widget) or its name does
(``looks_like_secret_field``), at any depth: a step's own fields, a nested object's, a list's items'; never a yes or
no (a form field's ``secret: true``). An entry of a free-form map (a ``Dict[str, str]``) and the value of a
name/value row (an HTTP step's headers, query parameters and form fields) are secrets when the name is
``Authorization``, ``Cookie`` or ``Proxy-Authorization`` or holds ``key``, ``token`` or ``secret``; so is an entry
of any object kept under a name holding ``header`` whose schema isn't known. Of a workflow's own settings (``kind``
None), every variable's value is withheld, whatever its name.

``withhold`` gives a step's settings without them and the path of each (``headers[0].value``, ``auth.password``);
``keep_withheld`` puts the stored ones back into settings a write sends without them: a row is matched by its
name and any other list item by its ``id``, never by its place (a removed item's secret would land in the next
one), and a value the write does send replaces the stored one.
"""

from __future__ import annotations

import copy
from functools import lru_cache
from typing import Any, Dict, Iterator, List, Optional, Tuple

SECRET_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})
SECRET_WORDS = ("key", "token", "secret")
# A step's connections are by reference, never a secret.
CONNECTIONS = "credentialIds"
# A workflow's variables (its settings'), whose values are withheld whatever their names, as its public template
# page shows them: a field bound to ``{{vars.x}}`` takes its value, a key as often as not.
VARIABLES = "variable_definitions"


@lru_cache(maxsize=1024)
def settings_schema(kind: str, operation: Optional[str]) -> Optional[Dict[str, Any]]:
    """The JSON schema of a step's settings (with its ``$defs``); None when it isn't known."""
    from pydantic import TypeAdapter

    from .operation_catalog import get_operation_config_class

    found = get_operation_config_class(kind, operation or "default") if kind else None
    if found is None:
        return None
    try:
        return TypeAdapter(found).json_schema()
    except Exception:  # a schema the adapter can't render: judge secrets by name alone
        return None


def is_secret_field(name: str, prop: Optional[Dict[str, Any]]) -> bool:
    """A field no read shows: its name or its schema marks it as a secret."""
    from nodes.core.credential_fields import looks_like_secret_field

    prop = prop or {}
    return (looks_like_secret_field(name) or prop.get("writeOnly") is True or prop.get("format") == "password"
            or prop.get("ui:widget") == "password")


def is_secret_name(name: Any) -> bool:
    """A header, map entry or name/value row that holds a secret, by its name."""
    lowered = str(name or "").strip().lower()
    return lowered in SECRET_HEADERS or any(word in lowered for word in SECRET_WORDS)


def _flag(value: Any) -> bool:
    """A yes or no holds no secret, whatever its name (a form field's ``secret: true``)."""
    return isinstance(value, bool)


def _row_name(row: Any) -> Optional[str]:
    """A name/value row's name (``{key|name, value}``), else None."""
    name = row.get("key", row.get("name")) if isinstance(row, dict) else None
    return name if isinstance(name, str) else None


def _alternatives(schema: Any, defs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A schema's alternatives with ``$ref``s resolved (``Optional[X]`` is X or null)."""
    if not isinstance(schema, dict):
        return []
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        rest = {k: v for k, v in schema.items() if k != "$ref"}
        return _alternatives({**(defs.get(ref[len("#/$defs/"):]) or {}), **rest}, defs)
    for key in ("anyOf", "oneOf", "allOf"):
        if isinstance(schema.get(key), list):
            rest = {k: v for k, v in schema.items() if k != key}
            return [alt for member in schema[key] for alt in _alternatives({**rest, **member}, defs)]
    return [schema]


def _shape(schema: Any, defs: Dict[str, Any], value: Any) -> Optional[Dict[str, Any]]:
    """The alternative of ``schema`` that fits ``value``'s kind: an object (a model, or a map when it names no
    properties) or a list."""
    for alt in _alternatives(schema, defs):
        if isinstance(value, dict) and (alt.get("type") == "object" or "properties" in alt
                                        or "additionalProperties" in alt):
            return alt
        if isinstance(value, list) and isinstance(alt.get("items"), dict):
            return alt
    return None


# A place in settings: a key, a row by its name (``("row", name)``), a list item by its id (``("id", id)``) or,
# for one with neither, by its place (withheld, never put back).
Step = Any


def _item_id(item: Any) -> Any:
    """A list item's own id, else None."""
    found = item.get("id") if isinstance(item, dict) else None
    return found if isinstance(found, (str, int)) and not isinstance(found, bool) else None


def _secrets(value: Any, schema: Any, defs: Dict[str, Any], shown: str,
             at: Tuple[Step, ...]) -> Iterator[Tuple[str, Tuple[Step, ...]]]:
    """Each secret inside ``value``: its path as shown and as matched."""
    if isinstance(value, list):
        shape = _shape(schema, defs, value)
        items = shape.get("items") if shape else None
        for i, row in enumerate(value):
            name = _row_name(row)
            if name is not None and "value" in row:
                if is_secret_name(name) and not _flag(row["value"]):
                    yield f"{shown}[{i}].value", (*at, ("row", name.strip().lower()), "value")
                continue
            own = _item_id(row)
            yield from _secrets(row, items, defs, f"{shown}[{i}]", (*at, i if own is None else ("id", own)))
        return
    if not isinstance(value, dict):
        return
    shape = _shape(schema, defs, value)
    headers = shape is None and bool(at) and isinstance(at[-1], str) and "header" in at[-1].lower()
    if headers or (shape is not None and not isinstance(shape.get("properties"), dict)):  # a map of named entries
        entries = (shape or {}).get("additionalProperties")
        for key, inner in value.items():
            if is_secret_name(key) and not _flag(inner):
                yield f"{shown}.{key}", (*at, key)
            else:
                yield from _secrets(inner, entries, defs, f"{shown}.{key}", (*at, key))
        return
    props = (shape or {}).get("properties") or {}  # an object, judged by its fields' names where its schema is unknown
    for key, inner in value.items():
        if is_secret_field(key, props.get(key)) and not _flag(inner):
            yield f"{shown}.{key}", (*at, key)
        else:
            yield from _secrets(inner, props.get(key), defs, f"{shown}.{key}", (*at, key))

def _found(settings: Dict[str, Any], kind: Optional[str],
           operation: Optional[str]) -> List[Tuple[str, Tuple[Step, ...]]]:
    schema = settings_schema(kind, operation) or {}
    defs = schema.get("$defs") or {}
    props = schema.get("properties") or {}
    found: List[Tuple[str, Tuple[Step, ...]]] = []
    for key, value in settings.items():
        if key == CONNECTIONS:
            continue
        if kind is None and key == VARIABLES and isinstance(value, list):
            found.extend((f"{key}[{i}].value", (key, ("row", _row_name(row).strip().lower()), "value"))
                         for i, row in enumerate(value) if _row_name(row) is not None and "value" in row)
        elif is_secret_field(key, props.get(key)) and not _flag(value):
            found.append((key, (key,)))
        else:
            found.extend(_secrets(value, props.get(key), defs, key, (key,)))
    return found


def _parent(root: Any, at: Tuple[Step, ...]) -> Tuple[Any, Step]:
    """The container holding the place ``at`` names and its last step; (None, None) when it isn't there."""
    node = root
    for step in at[:-1]:
        if isinstance(step, tuple):
            node = next((r for r in node if _matches(r, step)), None) if isinstance(node, list) else None
        elif isinstance(step, int):
            node = node[step] if isinstance(node, list) and step < len(node) else None
        else:
            node = node.get(step) if isinstance(node, dict) else None
        if node is None:
            return None, None
    return node, at[-1]


def _matches(item: Any, step: Tuple[str, Any]) -> bool:
    kind, value = step
    return _item_id(item) == value if kind == "id" else (_row_name(item) or "").strip().lower() == value


def withhold(settings: Dict[str, Any], kind: Optional[str],
             operation: Optional[str]) -> Tuple[Dict[str, Any], List[str]]:
    """A step's settings without their secrets, and the path of each left out (``kind`` None: settings whose schema
    isn't known, such as the workflow's own, judged by name)."""
    found = _found(settings, kind, operation)
    if not found:
        return settings, []
    shown = copy.deepcopy(settings)
    for _, at in found:
        parent, last = _parent(shown, at)
        if isinstance(parent, dict):
            parent.pop(last, None)
    return shown, sorted(path for path, _ in found)


def keep_withheld(stored: Dict[str, Any], written: Dict[str, Any], kind: Optional[str],
                  operation: Optional[str]) -> Dict[str, Any]:
    """``written`` with each of ``stored``'s secrets it leaves out put back (in place), where its place still is:
    never into a list item known only by its place."""
    for _, at in _found(stored, kind, operation):
        if any(isinstance(step, int) for step in at):
            continue
        parent, last = _parent(written, at)
        if isinstance(parent, dict) and last not in parent:
            source, _ = _parent(stored, at)
            parent[last] = copy.deepcopy(source[last])
    return written
