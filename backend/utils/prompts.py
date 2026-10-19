"""The text the engine sends models, kept apart from the code that sends it.

Each prompt the engine writes lives in a pack: a module of named parts (strings, or
functions that build text) with short defaults that work. A deployment may register
its own pack under the same name, and the engine reads whichever is registered at the
moment it builds a prompt, never at import, so a pack registered at start-up wins:

    # engine
    PROMPTS = PromptPack("coordinator")
    instructions = PROMPTS.INSTRUCTIONS

    # a deployment, at start-up
    register_prompts("coordinator", tuned_module)

A registered pack offers every part its default lists in ``__all__`` (``missing_parts``),
so a renamed part fails a test instead of the engine quietly sending the default.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, List

# Every pack the engine reads, and the module holding its defaults.
PACKS: Dict[str, str] = {
    "builder": "coder.workflow.agentic.prompts_default",
    "coordinator": "coder.coordinator.prompts",
    "coordinator_tools": "coder.coordinator.tool_prompts",
    "compaction": "coder.openai_agent.compaction_prompts",
    "agent_platform_tools": "nodes.agent.platform_tool_prompts",
    "rehearsal": "nodes.agent.rehearsal_prompts",
}

_REGISTERED: Dict[str, Any] = {}


def register_prompts(name: str, pack: Any) -> None:
    PACKS[name]  # a typo is a KeyError, never a pack nothing reads
    _REGISTERED[name] = pack


def registered_prompts() -> Dict[str, Any]:
    return dict(_REGISTERED)


def default_pack(name: str) -> Any:
    return importlib.import_module(PACKS[name])


def missing_parts(name: str) -> List[str]:
    """The parts of ``name``'s default that its registered pack doesn't offer."""
    pack = _REGISTERED.get(name)
    if pack is None:
        return []
    return [part for part in default_pack(name).__all__ if not hasattr(pack, part)]


class PromptPack:
    """A pack's parts as attributes: the registered pack's, else the default's."""

    def __init__(self, name: str):
        PACKS[name]
        self._name = name

    def __getattr__(self, part: str) -> Any:
        pack = _REGISTERED.get(self._name)
        return getattr(pack if pack is not None else default_pack(self._name), part)
