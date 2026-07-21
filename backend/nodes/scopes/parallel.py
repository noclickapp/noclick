"""Parallel operation → OAuth scope requirements.

Parallel has NO per-operation scopes. Its "OAuth" flow is a key-vending flow:
``platform.parallel.ai/getKeys/authorize`` returns the user's permanent Parallel
API key as the ``access_token`` (no refresh, no expiry), and every subsequent
call authenticates with that key in the ``x-api-key`` header — not a bearer
token. The single scope Parallel defines, ``key:read``, authorizes the key
handover itself; nothing an operation does consumes a scope.

So every operation declares an empty requirement (authenticated, unscoped), and
``key:read`` is an ``extra_scopes`` entry: the app must request it at connect,
but no endpoint implies it.

Docs: https://docs.parallel.ai/resources/oauth-provider
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

#: Every Parallel operation: authenticated by the API key, gated by no scope.
_UNSCOPED = ScopeRequirement()

_OPERATIONS = (
    # Search
    "search",
    "entity_search",
    # Task runs
    "create_task_run",
    "get_task_run",
    "get_task_run_input",
    "get_task_run_result",
    "get_task_run_events",
    # Task groups
    "create_task_group",
    "get_task_group",
    "get_task_group_run",
    "add_runs_to_group",
    "get_group_runs",
    "get_group_events",
    # FindAll
    "create_findall_spec",
    "create_findall_run",
    "get_findall_run",
    "get_findall_result",
    "extend_findall",
    "enrich_findall",
    "cancel_findall",
    # Monitors
    "create_monitor",
    "get_monitor",
    "list_monitors",
    "update_monitor",
    "cancel_monitor",
    "trigger_monitor",
    "simulate_monitor_event",
    "list_monitor_events",
    # Chat / extract
    "chat_completions",
    "extract",
    # Trigger
    "receive_webhook",
)

_REQUIREMENTS = {operation: _UNSCOPED for operation in _OPERATIONS}

PARALLEL_SCOPES = ScopeRegistry(
    provider="parallel",
    requirements=_REQUIREMENTS,
    # Authorizes the key handover at connect; no operation requires it.
    extra_scopes={"default": ("key:read",)},
)
