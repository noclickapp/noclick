"""In-process execution relay used by the self-hosted edition."""

from __future__ import annotations

from utils.local_relay import LocalExecutionRelay


# Compatibility alias for callers and extensions that imported the original
# class name. The community edition has one backend process and therefore uses
# the local relay exclusively.
ExecutionRelay = LocalExecutionRelay


def create_execution_relay(
    workflow_id: str,
    execution_id: str,
    user_id: str,
    **kwargs,
) -> LocalExecutionRelay:
    # Construct through the public compatibility alias. Besides keeping this
    # extension seam honest, it lets test suites and downstream installations
    # substitute the relay without patching private implementation names.
    return ExecutionRelay(workflow_id, execution_id, user_id, **kwargs)
