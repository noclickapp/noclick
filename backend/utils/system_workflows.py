"""Workflows NoClick runs itself: ``workflows.settings.system`` names what one
runs (e.g. "your NoClick assistant"), set by whatever made it. Its owner can
open and run it, but nobody edits, renames, moves, shares, trashes or deletes it
(``access_control`` caps every caller at view), and no list of a person's
workflows shows it."""

from typing import Any, Dict, Mapping, Optional

SYSTEM_KEY = "system"
# The settings only NoClick writes on a workflow (its own marks on what it runs): a client's write never sets them,
# and a copy never carries them. A deployment adds its own (``register_server_setting``).
_SERVER_SETTINGS = {SYSTEM_KEY}


def register_server_setting(key: str) -> None:
    _SERVER_SETTINGS.add(key)


def client_settings(settings: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """``settings`` as a client may write them, or a copy carry them: without NoClick's own marks."""
    return {k: v for k, v in (settings or {}).items() if k not in _SERVER_SETTINGS}


def not_system_sql(alias: str = "w") -> str:
    """A ``WHERE`` clause keeping system workflows out of a query over ``workflows`` (as ``alias``)."""
    column = f"{alias}.settings" if alias else "settings"
    return f"({column}->>'{SYSTEM_KEY}') IS NULL"


def system_of(settings: Optional[Mapping[str, Any]]) -> Optional[str]:
    value = (settings or {}).get(SYSTEM_KEY)
    return value if isinstance(value, str) and value else None


def refusal(what: str) -> str:
    return f"This automation runs {what}, so NoClick keeps it: it can't be edited, renamed or deleted."
