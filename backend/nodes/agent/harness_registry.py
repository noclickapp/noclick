"""Registry mapping CLI-harness model types to their turn runner.

``AgentNode.execute()`` dispatches every ``model_type`` in
``WRAPPER_ID_BY_MODEL_TYPE`` through the runner registered here and falls
through to the SDK agent path when the type has no runner claim. An edition can register another runner before first lookup; otherwise
the local-process runner is selected.
"""

import logging
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

# async (node, config, env_overrides, user_id, tool_configs,
#        filesystem_configs, *, model_type) -> node output dict
CliTurnRunner = Callable[..., Awaitable[Dict[str, Any]]]

_runners: Dict[str, CliTurnRunner] = {}
_initialized = False


def register_cli_turn_runner(model_types: Iterable[str], runner: CliTurnRunner) -> None:
    for model_type in model_types:
        _runners[model_type] = runner
    logger.debug(f"[HarnessRegistry] Registered runner for {list(model_types)}")


def get_cli_turn_runner(model_type: str) -> Optional[CliTurnRunner]:
    """The runner claiming this model type, or None (→ SDK path)."""
    _ensure_initialized()
    return _runners.get(model_type)


def _ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True
    if _runners:
        # An edition-specific runner was registered at start-up.
        return

    # Run harness turns as local subprocesses using the operator's own
    # installed CLIs (claude/codex/opencode).
    from nodes.agent.local_harness import LOCAL_HARNESS_MODEL_TYPES, run_local_harness_turn

    register_cli_turn_runner(LOCAL_HARNESS_MODEL_TYPES, run_local_harness_turn)


def clear() -> None:
    """Reset registration state (tests)."""
    global _initialized
    _runners.clear()
    _initialized = False
