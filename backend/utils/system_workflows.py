"""Workflows NoClick runs itself: ``workflows.settings.system`` names what one
runs (e.g. "your NoClick assistant"), set by whatever made it. Its owner can
open and run it, but nobody edits, renames, moves, shares, trashes or deletes it
(``access_control`` caps every caller at view), and no list of a person's
workflows shows it.

A deployment can keep more out of those lists (``register_unlisted``): the
workflows its own objects run on, such as an agent's own flow, which stay their
owner's to open and run but are never one of their automations."""

from typing import Any, Callable, Dict, List, Mapping, Optional

SYSTEM_KEY = "system"
# The settings only NoClick writes on a workflow (its own marks on what it runs): a client's write never sets them,
# and a copy never carries them. A deployment adds its own (``register_server_setting``).
_SERVER_SETTINGS = {SYSTEM_KEY}
# Each takes a ``workflows`` alias and returns SQL true for a workflow no list of a person's automations shows.
_UNLISTED: List[Callable[[str], str]] = []


def register_server_setting(key: str) -> None:
    _SERVER_SETTINGS.add(key)


def client_settings(settings: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """``settings`` as a client may write them, or a copy carry them: without NoClick's own marks."""
    return {k: v for k, v in (settings or {}).items() if k not in _SERVER_SETTINGS}


def not_system_sql(alias: str = "w") -> str:
    """A ``WHERE`` clause keeping system workflows out of a query over ``workflows`` (as ``alias``)."""
    column = f"{alias}.settings" if alias else "settings"
    return f"({column}->>'{SYSTEM_KEY}') IS NULL"


def register_unlisted(clause: Callable[[str], str]) -> None:
    """Keep the workflows ``clause(alias)`` is true for out of every list of a person's automations."""
    if clause not in _UNLISTED:
        _UNLISTED.append(clause)


def listed_sql(alias: str = "w") -> str:
    """A ``WHERE`` clause keeping a query over ``workflows`` (as ``alias``) to a person's automations: no system
    workflow, and none a deployment keeps out (``register_unlisted``)."""
    return " AND ".join([not_system_sql(alias), *(f"NOT {clause(alias)}" for clause in _UNLISTED)])


def system_of(settings: Optional[Mapping[str, Any]]) -> Optional[str]:
    value = (settings or {}).get(SYSTEM_KEY)
    return value if isinstance(value, str) and value else None


def refusal(what: str) -> str:
    return f"This automation runs {what}, so NoClick keeps it: it can't be edited, renamed or deleted."
