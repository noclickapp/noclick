"""Where an agent's sandboxes run, and the named volumes they mount.

An edition that places agents sets the runtime config key ``_sandboxRegion``
on the agent node (the sandbox provider's own region name); both sandbox
runtimes read it when they boot. Unset, the provider places them anywhere.
``_sandboxVolumes`` is ``{mount path: volume name}`` (the volume backend's
names): both runtimes mount each one read-write beside the workspace.
``_noShell`` (true) takes the in-process agent's shell away: no sandbox and no
``execute_bash``. ``_sandboxNetwork`` is the hosts its sandboxes' code may
reach (``*.d`` covers ``d`` and the names under it; none: no network beyond
what the agent itself needs, which the runtime adds); unset, anywhere. A
runtime that can't enforce it never takes it. ``_sandboxSkills`` is the
skills a coding harness finds where it reads skills (``[{skill_id,
account_user_id, version, name, digest, files}]``, ``files`` each version's
``[{path, size, sha256}]``), written at its sandbox's cold start.
``_sessionGeneration`` is which of its conversation's harness session stores a
coding harness resumes (a revert starts the next one); unset, the first.
``_agentScope`` is the agent's own place, whichever conversation a turn runs in
(a platform agent's: one per agent and scope): its warm sandbox, its
``/workspace``, its presence and its lost-turn markers key on it, while its
conversation key keeps only its history. Unset (a canvas agent, a test run),
they key on the conversation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

SANDBOX_REGION_KEY = "_sandboxRegion"
SANDBOX_VOLUMES_KEY = "_sandboxVolumes"
NO_SHELL_KEY = "_noShell"
SANDBOX_NETWORK_KEY = "_sandboxNetwork"
SANDBOX_SKILLS_KEY = "_sandboxSkills"
SESSION_GENERATION_KEY = "_sessionGeneration"
AGENT_SCOPE_KEY = "_agentScope"


def _runtime_value(node: Any, key: str) -> Any:
    data = getattr(node, "node_data", None) or {}
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    return config.get(key) or data.get(key)


def sandbox_region_of(node: Any) -> Optional[str]:
    region = _runtime_value(node, SANDBOX_REGION_KEY)
    return region if isinstance(region, str) and region else None


def sandbox_volumes_of(node: Any) -> Dict[str, str]:
    volumes = _runtime_value(node, SANDBOX_VOLUMES_KEY)
    if not isinstance(volumes, dict):
        return {}
    return {str(path): str(name) for path, name in sorted(volumes.items()) if path and name}


def sandbox_skills_of(node: Any) -> List[Dict[str, Any]]:
    skills = _runtime_value(node, SANDBOX_SKILLS_KEY)
    return [s for s in skills if isinstance(s, dict) and s.get("name")] if isinstance(skills, list) else []


def shell_of(node: Any) -> bool:
    """Whether the in-process agent has its shell (``execute_bash``)."""
    return _runtime_value(node, NO_SHELL_KEY) is not True


def sandbox_network_of(node: Any) -> Optional[Tuple[str, ...]]:
    """The hosts its sandboxes may reach, or None (anywhere). An empty list is
    a limit too, so it isn't read through ``_runtime_value``'s truthiness."""
    data = getattr(node, "node_data", None) or {}
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    network = config.get(SANDBOX_NETWORK_KEY, data.get(SANDBOX_NETWORK_KEY))
    return tuple(str(host) for host in network) if isinstance(network, list) else None


def session_generation_of(node: Any) -> int:
    generation = _runtime_value(node, SESSION_GENERATION_KEY)
    return generation if isinstance(generation, int) and generation > 0 else 0


def session_key(conversation_key: str, generation: int) -> str:
    """The key a conversation's harness session store is named by: its own, then one per generation after it."""
    return f"{conversation_key}~s{generation}" if generation else conversation_key


def agent_scope_of(node: Any) -> Optional[str]:
    scope = _runtime_value(node, AGENT_SCOPE_KEY)
    return scope if isinstance(scope, str) and scope else None


def place_key_of(node: Any) -> Optional[str]:
    """What the agent's place (its warm sandbox, ``/workspace``, presence, markers) goes by: its scope, else the
    conversation the run is in (``AgentNode._conversation_key``); None for a one-off run."""
    return agent_scope_of(node) or getattr(node, "_conversation_key", None)
