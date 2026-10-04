"""Bound arguments: a tool's parameters fixed outside the model's reach.

A bound parameter leaves the tool's schema and is filled on every call, over
whatever the model passed, including the same key inside a free-form object
parameter (an ``extra_params`` pass-through), so a call's final arguments are
the model's with the binding on top, and what a guard judges is what runs.

A bound value may name the person the turn acts for: ``{{user.id}}``,
``{{user.email}}``, ``{{user.name}}`` or ``{{user.metadata.<key>}}``, filled
from what the turn's runtime config holds under ``TOOL_USER_KEY``. A tool
whose binding can't be filled (no such person, or a value they lack) isn't
offered for that turn.

Where it applies: an ``agent_tool_operations`` entry carries ``bind``
(``build_node_op_tools`` strips and fills it); any tool config carrying
``bound_arguments`` has them applied at dispatch (``execute_tool``, the CLI
shadow pool), so a tool type needs no binding code of its own.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, Optional

# An ``agent_tool_operations`` entry's bound arguments: {parameter: value}.
BIND_KEY = "bind"
# A tool config's filled bound arguments, applied to every call of it.
BOUND_ARGUMENTS_KEY = "bound_arguments"
# Runtime config key on an agent node: the person the turn acts for,
# ``{id, email, name, metadata}``, which ``{{user.*}}`` templates read.
TOOL_USER_KEY = "_toolUser"

_TEMPLATE = re.compile(r"\{\{(.*?)\}\}")
_USER_PATH = re.compile(r"\s*user\.(id|email|name|metadata\.[A-Za-z0-9_-]+)\s*")


def tool_user_of(node: Any) -> Optional[Dict[str, Any]]:
    """The person an agent node's turn acts for, when a platform says."""
    from nodes.agent.platform_tools import _runtime_spec

    return _runtime_spec(node, TOOL_USER_KEY)


class Unfillable(Exception):
    """A template names something the turn's person lacks."""


def template_error(value: Any) -> Optional[str]:
    """Why ``value`` (any JSON) holds a template that can't be filled, or None."""
    if isinstance(value, str):
        for template in _TEMPLATE.findall(value):
            if not _USER_PATH.fullmatch(template):
                return (f"{{{{{template}}}}} isn't something NoClick fills in; use {{{{user.id}}}}, "
                        "{{user.email}}, {{user.name}} or {{user.metadata.<key>}}.")
    elif isinstance(value, dict):
        return next((e for e in map(template_error, value.values()) if e), None)
    elif isinstance(value, (list, tuple)):
        return next((e for e in map(template_error, value) if e), None)
    return None


def has_template(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_TEMPLATE.search(value))
    if isinstance(value, dict):
        return any(has_template(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(has_template(v) for v in value)
    return False


def _user_value(path: str, user: Optional[Dict[str, Any]]) -> Any:
    if not isinstance(user, dict):
        raise Unfillable(path)
    field, _, key = path.partition(".")
    value = user.get(field)
    if key:
        value = value.get(key) if isinstance(value, dict) else None
    if value is None or value == "":
        raise Unfillable(path)
    return value


def _fill_value(value: Any, user: Optional[Dict[str, Any]]) -> Any:
    if isinstance(value, str):
        whole = _TEMPLATE.fullmatch(value.strip())
        if whole and _USER_PATH.fullmatch(whole.group(1)):
            return _user_value(whole.group(1).strip()[len("user."):], user)
        return _TEMPLATE.sub(lambda m: str(_user_value(m.group(1).strip()[len("user."):], user))
                             if _USER_PATH.fullmatch(m.group(1)) else m.group(0), value)
    if isinstance(value, dict):
        return {k: _fill_value(v, user) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill_value(v, user) for v in value]
    return value


def fill_text(text: str, user: Optional[Dict[str, Any]], *, encode: Callable[[str], str] = str) -> str:
    """``text`` with each ``{{user.*}}`` template filled from ``user``, the
    value passed through ``encode`` (a URL's percent-encoding, say). Raises
    ``Unfillable`` with the path ``user`` lacks."""
    return _TEMPLATE.sub(lambda m: encode(str(_user_value(m.group(1).strip()[len("user."):], user)))
                         if _USER_PATH.fullmatch(m.group(1)) else m.group(0), text)


def fill(bind: Optional[Dict[str, Any]], user: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """``bind`` with its ``{{user.*}}`` templates filled from ``user`` (a
    template that is a whole value keeps the value's type); None when one
    can't be filled. Empty ``bind`` fills to ``{}``."""
    try:
        return {name: _fill_value(value, user) for name, value in (bind or {}).items()}
    except Unfillable:
        return None


def strip(parameters: Optional[Dict[str, Any]], names: Iterable[str]) -> Dict[str, Any]:
    """A JSON-schema ``parameters`` object without the bound ``names``."""
    names = set(names)
    parameters = dict(parameters or {"type": "object", "properties": {}})
    parameters["properties"] = {k: v for k, v in (parameters.get("properties") or {}).items() if k not in names}
    if "required" in parameters:
        parameters["required"] = [r for r in parameters.get("required") or [] if r not in names]
    return parameters


def _free_form(schema: Any) -> bool:
    """A parameter whose value is an object the call passes through as is."""
    if not isinstance(schema, dict):
        return False
    variants = schema.get("anyOf") or schema.get("oneOf")
    if variants:
        return any(_free_form(v) for v in variants)
    return schema.get("type") == "object" and (not schema.get("properties") or bool(schema.get("additionalProperties")))


def apply(arguments: Optional[Dict[str, Any]], bound: Optional[Dict[str, Any]],
          parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The call's final arguments: the model's, with ``bound`` on top, and no
    bound key left inside a free-form object parameter of ``parameters``."""
    out = dict(arguments or {})
    if not bound:
        return out
    for name, schema in ((parameters or {}).get("properties") or {}).items():
        if isinstance(out.get(name), dict) and _free_form(schema):
            out[name] = {k: v for k, v in out[name].items() if k not in bound}
    out.update(bound)
    return out
