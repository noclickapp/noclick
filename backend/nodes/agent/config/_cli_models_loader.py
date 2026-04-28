"""Load the curated Codex / Claude Code model lists.

The lists live in `_cli_models.json`, refreshed daily from the CLI binaries
by `.github/workflows/refresh-cli-models.yml`. See
`scripts/refresh_cli_models.py` for the extraction.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

_DATA_PATH = Path(__file__).parent / "_cli_models.json"


@lru_cache(maxsize=1)
def _load() -> Dict[str, Any]:
    return json.loads(_DATA_PATH.read_text())


def codex_models() -> List[str]:
    return list(_load()["codex"]["models"])


def claude_code_aliases() -> Dict[str, str]:
    return dict(_load()["claude_code"]["aliases"])


def codex_options() -> List[Dict[str, str]]:
    """`{value, label}` entries for the Codex model dropdown."""
    return [{"value": m, "label": m} for m in codex_models()]


def claude_code_options() -> List[Dict[str, str]]:
    """`{value, label}` entries for the Claude Code alias dropdown."""
    aliases = claude_code_aliases()
    order = ["opus", "sonnet", "haiku"]
    return [
        {"value": alias, "label": f"{alias} ({aliases[alias]})"}
        for alias in order
        if alias in aliases
    ]
