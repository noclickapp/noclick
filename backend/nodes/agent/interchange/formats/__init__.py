"""The harness formats the interchange knows, by harness key.

Adding a harness: write ``formats/<harness>.py`` with one ``ThreadFormat``
subclass (its docstring IS the description ``inspect`` prints), and list it
here. ``pair_support`` on the NoClick side derives what can move from this
registry — nothing else needs to change.
"""

from __future__ import annotations

from typing import Dict, List

from .base import REASONS, InterchangeError, ThreadFormat, Written, db_ref, discard, pointer_text, split_db_ref, write_new_file
from .claude_code import ClaudeCodeFormat
from .codex import CodexFormat
from .hermes import HermesFormat
from .openclaw import OpenClawFormat
from .opencode import OpenCodeFormat

FORMATS: Dict[str, ThreadFormat] = {
    f.harness: f for f in (ClaudeCodeFormat(), CodexFormat(), OpenCodeFormat(), HermesFormat(), OpenClawFormat())
}


def format_for(harness: str) -> ThreadFormat:
    try:
        return FORMATS[harness]
    except KeyError:
        raise InterchangeError("no_adapter", f"{harness} has no thread format") from None


def describe_formats() -> List[dict]:
    return [f.describe() for f in FORMATS.values()]


__all__ = ["FORMATS", "REASONS", "InterchangeError", "ThreadFormat", "Written", "db_ref", "describe_formats", "discard", "format_for",
           "pointer_text", "split_db_ref", "write_new_file"]
