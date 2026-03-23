"""
SDK permission enforcement for API key-authenticated connections.

Maps socket events to required permissions (read, execute, write).
Browser connections (cookie auth) bypass this check entirely.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Events that require no special permission (always allowed for authenticated SDK clients)
_ALWAYS_ALLOWED = frozenset({
    "yjs:sync",
})

# Map socket events to required permission level
_EVENT_PERMISSIONS = {
    # Read operations
    "workflow:get": "read",
    "workflow:list": "read",
    "workflow:get_node_outputs": "read",
    "workflow:get_node_output_history": "read",
    "workflow:node:load_options": "read",
    "workflow:node:get_config_schema": "read",
    "workflow:load_node_state": "read",
    "credential:list": "read",
    "credential:get": "read",
    "resource:list": "read",
    "resource:get": "read",
    "resource:download_url": "read",
    "resource:dataset:rows": "read",
    "workflow:list_executions": "read",

    # Execute operations
    "workflow:execute": "execute",
    "workflow:stop": "execute",

    # Write operations
    "workflow:node:set_config": "write",
    "workflow:node:get_config": "read",
    "workflow:state:get": "read",
    "workflow:state:set": "write",
    "workflow:state:keys": "read",
    "workflow:update": "write",
    "workflow:create": "write",
    "workflow:delete": "write",
    "workflow:save_node_state": "write",
    "workflow:clear_node_state": "write",
    "credential:create": "write",
    "credential:update": "write",
    "credential:delete": "write",
    "resource:create": "write",
    "resource:delete": "write",
    "resource:upload_url": "write",
    "resource:dataset:append": "write",
    "resource:dataset:update_row": "write",
    "resource:dataset:delete_rows": "write",
    "resource:fork": "write",
}


def check_sdk_permission(
    event: str,
    sdk_permissions: Optional[list],
    sdk_workflow_id: Optional[str] = None,
    request_workflow_id: Optional[str] = None,
) -> Optional[str]:
    """
    Check if an SDK client has permission to perform an event.

    Args:
        event: Socket event name
        sdk_permissions: List of permissions from the API key (e.g. ['read', 'execute', 'write'])
        sdk_workflow_id: Workflow ID the key is scoped to (None = all workflows)
        request_workflow_id: Workflow ID from the request payload (if applicable)

    Returns:
        None if allowed, or an error message string if denied.
    """
    # No sdk_permissions means this is a browser session — always allowed
    if sdk_permissions is None:
        return None

    # Always-allowed events
    if event in _ALWAYS_ALLOWED:
        return None

    # Check workflow scope
    if sdk_workflow_id and request_workflow_id and request_workflow_id != sdk_workflow_id:
        return f"API key is scoped to workflow {sdk_workflow_id[:8]}..., cannot access workflow {request_workflow_id[:8]}..."

    # Check event permission
    required = _EVENT_PERMISSIONS.get(event)
    if required is None:
        # Unknown event — deny by default for SDK clients (browser clients bypass this)
        logger.warning(f"[SDK Permissions] Unknown event '{event}' from SDK client — denying")
        return f"Event '{event}' not allowed for SDK clients"

    if required not in sdk_permissions:
        return f"API key missing '{required}' permission (has: {', '.join(sdk_permissions)})"

    return None
