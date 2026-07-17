"""Load the curated CLI harness model lists and version pins.

Everything lives in `_cli_models.json`, refreshed daily from the CLI binaries
by `.github/workflows/refresh-cli-models.yml`. See `scripts/refresh_cli_models.py`
for the extraction.

Three kinds of data per harness:
  • Model lists/aliases (codex, claude-code) — extracted from the binary, which
    bakes them as static literals; the dropdowns render from these.
  • Version pins (codex, claude-code, opencode, openclaw, hermes) — the version
    each harness's isolated runtime image installs. Embedding the pin in the
    image's install command means a bump (landed by the daily refresh PR)
    invalidates the cached layer, so the sandbox binary upgrades in lockstep
    instead of being frozen to whatever `latest` was at first build.
  • `default_model` — the preselected model for every harness, human-owned in
    the JSON (the refresh script carries it through and fails if a model-list
    refresh drops it). `harness_default_model()` is the ONE code path for
    harness defaults; config classes must not hardcode their own — a code-side
    heuristic (e.g. "latest -mini suffix") silently breaks when providers
    change naming schemes.
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


def _pin(harness: str, field: str = "version") -> str:
    """A required version/ref pin from _cli_models.json.

    Raises if absent — we never silently fall back to `latest`/HEAD (that
    unpinned drift is exactly what these pins exist to kill).
    """
    value = _load().get(harness, {}).get(field)
    if not value:
        raise RuntimeError(
            f"{harness}.{field} missing from _cli_models.json — run "
            "scripts/refresh_cli_models.py (the refresh-cli-models workflow "
            "regenerates it daily)."
        )
    return value


def harness_default_model(harness: str) -> str:
    """The preselected model for a CLI harness config.

    Evaluated at class-definition time in each config module, so the value
    lands in the generated JSON schema as `default` — that's what the FE
    preselects (a default_factory never serializes one, leaving the picker
    empty while the runtime silently falls back).
    """
    return _pin(harness, "default_model")


def codex_models() -> List[str]:
    """Servable codex model ids: the human-owned ``extra_models`` (codex-family
    ids the binary's embedded slug list omits — the ONLY models codex-rs
    exposes MCP servers to; see the JSON's ``_extra_models_note``) first, then
    the binary-extracted list."""
    block = _load()["codex"]
    extras = list(block.get("extra_models") or [])
    return extras + [m for m in block["models"] if m not in extras]


def codex_version() -> str:
    """Pinned @openai/codex version for the isolated runtime image."""
    return _pin("codex")


def claude_code_version() -> str:
    """Pinned @anthropic-ai/claude-code version for the isolated runtime image."""
    return _pin("claude_code")


def opencode_version() -> str:
    """Pinned opencode-ai version for the isolated runtime image."""
    return _pin("opencode")


def openclaw_version() -> str:
    """Pinned openclaw version for the isolated runtime image."""
    return _pin("openclaw")


def hermes_ref() -> str:
    """Pinned hermes-agent git tag for the isolated runtime image clone."""
    return _pin("hermes", "ref")


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
