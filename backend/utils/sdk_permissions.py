"""
SDK permission enforcement for API key-authenticated connections.

Maps socket events to required permissions (read, execute, write).
Browser connections (cookie auth) bypass this check entirely.
"""

import logging
import uuid
from typing import AbstractSet, Any, Optional, Set

logger = logging.getLogger(__name__)

# Marker on the key a published app inlines in its PUBLIC page: every visitor
# holds it, so it may use only the events the SDK itself sends.
PUBLISHED_APP = "published_app"

# The events sdk/typescript/src/transports/websocket.ts emits (pinned to that
# file by tests/test_sdk_permissions.py).
_PUBLISHED_APP_EVENTS = frozenset({
    "workflow:get",
    "workflow:get_node_outputs",
    "workflow:node:get_config",
    "workflow:node:set_config",
    "workflow:execute",
    "workflow:stop",
    "workflow:state:get",
    "workflow:state:set",
    "workflow:state:keys",
    "credential:list",
    "credential:create",
    "resource:list",
    "resource:create",
    "resource:upload_url",
    "resource:download_url",
    "resource:delete",
    "resource:dataset:rows",
    "resource:dataset:append",
    "resource:dataset:update_row",
    "resource:dataset:delete_rows",
})

# Stands in for the workflow of a resource that does not exist; matches no key.
_UNKNOWN_WORKFLOW = "<unknown>"

# Account-level events a workflow-scoped key may send without naming its
# workflow (the SDK's auth.hasCredential / createCredential). The list carries
# no secrets; every other workflow-less event is refused to a scoped key.
_SCOPED_ACCOUNT_EVENTS = frozenset({"credential:list", "credential:create"})

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
    request_workflow_ids: AbstractSet[str] = frozenset(),
) -> Optional[str]:
    """
    Check if an SDK client has permission to perform an event.

    Args:
        event: Socket event name
        sdk_permissions: List of permissions from the API key (e.g. ['read', 'execute', 'write'])
        sdk_workflow_id: Workflow ID the key is scoped to (None = all workflows)
        request_workflow_ids: Every workflow the request names
            (``resolve_request_workflow_ids``)

    Returns:
        None if allowed, or an error message string if denied.
    """
    # No sdk_permissions means this is a browser session — always allowed
    if sdk_permissions is None:
        return None

    if PUBLISHED_APP in sdk_permissions and event not in _PUBLISHED_APP_EVENTS:
        return f"Event '{event}' is not available to a published app"

    # Always-allowed events
    if event in _ALWAYS_ALLOWED:
        return None

    # A scoped key reaches only its own workflow, so a request that names none
    # is refused — otherwise it acts on the whole account (e.g. credential:get).
    if sdk_workflow_id:
        if not request_workflow_ids:
            if event not in _SCOPED_ACCOUNT_EVENTS:
                return f"API key is scoped to workflow {sdk_workflow_id[:8]}..., and '{event}' names no workflow"
        for workflow_id in request_workflow_ids:
            if workflow_id != sdk_workflow_id:
                return f"API key is scoped to workflow {sdk_workflow_id[:8]}..., cannot access workflow {workflow_id[:8]}..."

    # Check event permission
    required = _EVENT_PERMISSIONS.get(event)
    if required is None:
        # Unknown event — deny by default for SDK clients (browser clients bypass this)
        logger.warning(f"[SDK Permissions] Unknown event '{event}' from SDK client — denying")
        return f"Event '{event}' not allowed for SDK clients"

    if required not in sdk_permissions:
        return f"API key missing '{required}' permission (has: {', '.join(sdk_permissions)})"

    return None


def _payload_field(data: Any, name: str) -> Optional[Any]:
    if isinstance(data, dict):
        return data.get(name)
    return getattr(data, name, None)


async def resolve_request_workflow_ids(data: Any) -> Set[str]:
    """Every workflow a request names: its ``workflow_id`` and the workflow
    owning its ``resource_id``. A resource that does not exist names an
    unknown workflow, so a scoped key's check refuses it."""
    workflow_ids = set()
    workflow_id = _payload_field(data, "workflow_id")
    if workflow_id:
        workflow_ids.add(str(workflow_id))
    resource_id = _payload_field(data, "resource_id")
    if resource_id:
        workflow_ids.add(await _resource_workflow_id(str(resource_id)))
    return workflow_ids


async def _resource_workflow_id(resource_id: str) -> str:
    try:
        resource_id = str(uuid.UUID(resource_id))
    except ValueError:
        return _UNKNOWN_WORKFLOW
    from repositories.resources import ResourceRepo
    from utils.database_pool import get_native_pool

    resource = await ResourceRepo(get_native_pool()).get_resource(resource_id)
    return str(resource["workflow_id"]) if resource else _UNKNOWN_WORKFLOW
