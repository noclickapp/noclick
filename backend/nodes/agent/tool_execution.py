"""
Tool execution — dispatches tool calls from the agent to the appropriate handler.

Handles: MCP tools, workflow tools, alarm tools, filesystem tools, node-op
tools, and the locked email-reply tool.
All functions take `node` (AgentNode instance) as first arg for access to
workflow_id, user_id, sio, sid, etc.
"""

import asyncio
import logging

from nodes.agent.rehearsal import (
    REHEARSAL_PASSTHROUGH_TOOL_TYPES,
    is_rehearsing,
)
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from nodes.core.base import WorkflowNode

logger = logging.getLogger(__name__)


# ============================================================================
# Main dispatcher
# ============================================================================


def _conversation_id_for(node) -> Optional[str]:
    """The conversation a tool call belongs to.

    Interface chats can have a bare ``conversation_id`` of ``None``, so fall
    back to ``chat_routing_id()``. Audit records and the rehearsal gate must
    use the same value.
    """
    routing = getattr(node, "chat_routing_id", None)
    return getattr(node, "conversation_id", None) or (
        routing() if callable(routing) else None
    )


async def execute_tool(
    node: "WorkflowNode",
    tool_name: str,
    arguments: Dict[str, Any],
    tool_configs: Dict[str, Dict],
) -> Dict[str, Any]:
    """
    Execute a custom tool based on its type.

    Routes execution based on tool_type:
    - 'workflow': Execute downstream nodes of the ToolNode
    - 'mcp': Execute via MCP protocol to external server
    - 'alarm': Schedule/list/cancel/update alarms
    - 'filesystem': Upload files to R2
    - 'node_op': Run a single integration-node operation standalone
    - 'node_op_lookup': List valid options for a node's dynamic ID fields
    - 'email_reply': Locked reply to the inbound email that triggered the run
    """
    if tool_name not in tool_configs:
        return {"success": False, "error": f"Tool '{tool_name}' not found in workflow"}

    tool_info = tool_configs[tool_name]
    tool_type = tool_info.get("tool_type", "workflow")
    dispatch_arguments = arguments
    if tool_info.get("node_type") == "automation-shopify":
        from utils.tool_call_log import mark_protected_tool_arguments

        # Rebind only the audit copy; every execution path keeps the untouched
        # provider arguments with no internal bookkeeping key.
        arguments = mark_protected_tool_arguments(arguments)
    logged_arguments = (
        "[protected Shopify payload]"
        if dispatch_arguments is not arguments
        else arguments
    )
    logger.info(
        f"[ToolExec] Executing {tool_type} tool '{tool_name}' with args: "
        f"{logged_arguments}"
    )

    # Observability: this is the ONE choke point every tool call passes
    # through (SDK FunctionTools and CLI runners, all tool types), so a
    # single span + durable record here covers every harness. The record is
    # fire-and-forget — logging must never fail a tool call.
    import time

    from utils.otel import get_tracer
    from utils.tool_call_log import record_tool_call

    start = time.monotonic()
    error: str = ""
    result: Dict[str, Any] = {}
    with get_tracer("noclick.agent_tools").start_as_current_span("agent.tool_call") as span:
        span.set_attribute("tool.name", tool_name)
        span.set_attribute("tool.type", tool_type)
        if tool_info.get("node_id"):
            span.set_attribute("tool.provider_node_id", str(tool_info["node_id"]))
        if tool_info.get("operation"):
            span.set_attribute("tool.operation", str(tool_info["operation"]))
        if getattr(node, "workflow_id", None):
            span.set_attribute("workflow.id", str(node.workflow_id))
        if getattr(node, "execution_id", None):
            span.set_attribute("execution.id", str(node.execution_id))

        try:
            # A rehearsal fabricates every outward effect. Checked here, at the
            # one choke point all tool types pass through, so a tool added later
            # is covered without anyone remembering to cover it.
            rehearsal_conversation = _conversation_id_for(node)
            if tool_type not in REHEARSAL_PASSTHROUGH_TOOL_TYPES and await is_rehearsing(
                rehearsal_conversation
            ):
                span.set_attribute("tool.rehearsed", True)
                result = await _rehearse_tool(
                    rehearsal_conversation,
                    tool_name,
                    tool_type,
                    dispatch_arguments,
                    tool_info,
                )
            elif tool_type == "mcp":
                result = await _execute_mcp_tool(
                    node, tool_name, dispatch_arguments, tool_info
                )
            elif tool_type == "alarm":
                result = await _execute_alarm_tool(
                    node, tool_name, dispatch_arguments, tool_info
                )
            elif tool_type == "filesystem":
                result = await _execute_filesystem_tool(
                    node, tool_name, dispatch_arguments, tool_info
                )
            elif tool_type == "node_op":
                result = await _execute_node_op_tool(
                    node, tool_name, dispatch_arguments, tool_info, tool_configs,
                )
            elif tool_type == "node_op_lookup":
                result = await _execute_node_op_lookup(
                    node, tool_name, dispatch_arguments, tool_info
                )
            elif tool_type == "email_reply":
                from nodes.agent.email_reply import execute_email_reply

                result = await execute_email_reply(node, dispatch_arguments, tool_info)
            elif tool_type == "submit_feedback":
                from nodes.agent.platform_tools import execute_submit_feedback

                result = await execute_submit_feedback(node, dispatch_arguments)
            elif tool_type == "prompt_builder":
                from nodes.agent.platform_tools import execute_prompt_builder

                result = await execute_prompt_builder(node, dispatch_arguments)
            elif tool_type == "builder_respond":
                from nodes.agent.platform_tools import execute_builder_respond

                result = await execute_builder_respond(node, dispatch_arguments)
            elif tool_type == "describe_workflow":
                from nodes.agent.platform_tools import execute_describe_workflow

                result = await execute_describe_workflow(node, dispatch_arguments)
            elif tool_type == "email_user":
                from nodes.agent.platform_tools import execute_email_user

                result = await execute_email_user(node, dispatch_arguments)
            else:
                result = await _execute_workflow_tool(
                    node, tool_name, dispatch_arguments, tool_info
                )
        except Exception as e:
            logger.error(f"[ToolExec] Error executing tool {tool_name}: {e}", exc_info=True)
            error = str(e)
            result = {"success": False, "error": error}

        # Soft failures (handlers return {success: False} instead of raising)
        # count as errors for the span and the durable record.
        if not error and isinstance(result, dict) and result.get("success") is False:
            error = str(result.get("error") or "tool returned success=False")
        if error:
            span.set_attribute("error", True)
            span.set_attribute("tool.error", error[:500])

    # Use the same conversation-id derivation as the rehearsal gate. A bare
    # conversation_id is None for interface chats and would leave audit rows
    # invisible to per-conversation reads.
    record_tool_call(
        user_id=getattr(node, "user_id", None),
        tool_name=tool_name,
        tool_type=tool_type,
        result_status="error" if error else "success",
        workflow_id=str(node.workflow_id) if getattr(node, "workflow_id", None) else None,
        execution_id=getattr(node, "execution_id", None),
        conversation_id=_conversation_id_for(node),
        agent_node_id=getattr(node, "node_id", None),
        provider_node_id=tool_info.get("node_id"),
        operation=tool_info.get("operation"),
        credential_id=tool_info.get("credential_id"),
        arguments=arguments,
        error=error or None,
        result_preview=None if error else str(result)[:500],
        duration_ms=(time.monotonic() - start) * 1000,
        model=getattr(node, "_effective_model", None),
    )
    return result


# ============================================================================
# MCP tools
# ============================================================================


async def _execute_mcp_tool(node, tool_name, arguments, tool_info) -> Dict[str, Any]:
    """Execute an MCP tool by calling the external MCP server."""
    from coder.openai_agent.mcp import call_tool as mcp_call_tool

    mcp_config = tool_info.get("mcp_server_config")
    if not mcp_config:
        return {
            "success": False,
            "error": f"Tool '{tool_name}' has no MCP server configuration",
        }

    original_name = tool_info.get("original_tool_name", tool_name)

    # The helper expects a single auth-source view. mcp_server_config can
    # carry either an api_key OR (auth_type='oauth' + access_token); pass
    # both fields through and let _build_headers decide precedence.
    server_config = {
        "url": mcp_config["url"],
        "transport_type": mcp_config.get("transport_type", "shttp"),
        "api_key": mcp_config.get("api_key"),
        "access_token": mcp_config.get("access_token")
            if mcp_config.get("auth_type") == "oauth" else None,
        "custom_headers": mcp_config.get("custom_headers"),
    }

    result = await mcp_call_tool(server_config, original_name, arguments)
    if result.get("success"):
        logger.info(
            f"[ToolExec] MCP tool '{original_name}' returned: {str(result.get('result'))[:500]}..."
        )
    return result


# ============================================================================
# Workflow tools
# ============================================================================


async def _execute_workflow_tool(
    node, tool_name, arguments, tool_info
) -> Dict[str, Any]:
    """Execute a workflow tool by running its downstream nodes."""
    tool_node_id = tool_info.get("node_id")

    if not node._execute_downstream_callback:
        logger.warning(f"[ToolExec] No workflow context set for tool '{tool_name}'")
        return {
            "success": False,
            "error": "Workflow context not available for tool execution",
        }

    logger.info(
        f"[ToolExec] Executing downstream nodes for tool '{tool_name}' (node_id={tool_node_id})"
    )
    return await node._execute_downstream_callback(
        tool_node_id, arguments, node.node_id
    )


# ============================================================================
# Node-operation tools
# ============================================================================



async def _rehearse_tool(
    conversation_id: str,
    tool_name: str,
    tool_type: str,
    arguments: Dict[str, Any],
    tool_info: Dict[str, Any],
) -> Dict[str, Any]:
    """Answer a tool call from the fabricated world instead of the real one.

    The result carries no "this was rehearsed" marker: the model should behave
    exactly as it would on a real run, and telling it otherwise changes the
    behaviour we are trying to show. Labelling is the UI's job, and it already
    knows — the whole run is a rehearsal.
    """
    from nodes.agent.rehearsal import RehearsalUnavailable, mock_tool_call

    try:
        simulated = await mock_tool_call(
            conversation_id=conversation_id,
            tool_name=tool_name,
            arguments=arguments or {},
            description=tool_info.get("_description") or tool_info.get("description"),
            node_type=tool_info.get("node_type"),
            operation=tool_info.get("operation"),
        )
    except RehearsalUnavailable as e:
        # Surfaced to the model as a tool failure rather than silently returning
        # nothing, so the trace shows a broken rehearsal instead of an agent
        # confidently reasoning over an empty response.
        return {"success": False, "error": f"rehearsal could not simulate this call: {e}"}

    return simulated if isinstance(simulated, dict) else {"success": True, "data": simulated}


async def _execute_node_op_tool(
    node, tool_name, arguments, tool_info, tool_configs,
) -> Dict[str, Any]:
    """Run a single integration-node operation standalone (node action tool).

    tool_info carries node_type/operation/credential_id from
    node_op_tools.build_node_op_tools; runner identity and billing context
    come from the live agent node. Errors propagate to execute_tool's
    catch-all and return to the model as {success: False, error}.
    """
    from nodes.core.run_op import run_node_operation

    node_type = tool_info.get("node_type")
    operation = tool_info.get("operation")
    if not node_type or not operation:
        return {
            "success": False,
            "error": f"Tool '{tool_name}' is missing node_type/operation config",
        }

    # Resource-scope gate (defense in depth — the JSON-schema enum on the
    # parameter already blocks off-list IDs at the wire layer; this catches
    # any caller bypassing the SDK validator.
    scope_error = _enforce_field_scopes(arguments or {}, tool_info)
    if scope_error:
        return {"success": False, "error": scope_error}

    try:
        result = await run_node_operation(
            node_type=node_type,
            operation=operation,
            arguments=arguments or {},
            user_id=node.user_id,
            credential_id=tool_info.get("credential_id"),
            organization_id=node.organization_id,
            workflow_id=node.workflow_id,
            conversation_id=getattr(node, "conversation_id", None),
        )
    except Exception as e:
        e = _with_missing_credential_hint(e, tool_info)
        if tool_info.get("lookup_tool"):
            raise RuntimeError(
                _append_lookup_hint(str(e), tool_info, arguments)
            ) from e
        raise e
    # Soft failures (node returns {success: False} instead of raising) get the
    # same nudge so the agent can self-correct a bad ID either way.
    if isinstance(result, dict) and result.get("success") is False and result.get("error"):
        result["error"] = _append_lookup_hint(str(result["error"]), tool_info, arguments)
        return result

    # Resource auto-extend: a successful creator op for a scopable resource
    # type adds the newly minted ID to every matching field_scopes on this
    # provider's allowlist — persists to the workflows row AND mutates the
    # live tool_configs so the SAME session can immediately read/edit it.
    await _maybe_autoextend_field_scopes(node, tool_info, result, tool_configs)
    return result


async def _maybe_autoextend_field_scopes(
    node, tool_info: Dict, result: Any, tool_configs: Dict[str, Dict],
) -> None:
    """Append any newly created resource IDs to the provider node's
    field_scopes (DB + broadcast + live tool_configs). Pure side effect —
    failures are logged, never re-raised; a broken writeback must not fail
    the tool call that just succeeded."""
    if not isinstance(result, dict):
        return
    node_type = tool_info.get("node_type")
    operation = tool_info.get("operation")
    provider_node_id = tool_info.get("node_id")
    workflow_id = getattr(node, "workflow_id", None)
    if not (node_type and operation and provider_node_id and workflow_id):
        return

    from nodes.agent.node_op_tools import (
        extract_resource_id_from_output,
        resource_creators,
    )

    new_ids: Dict[str, str] = {}
    for creator_op, resource_type, id_path in resource_creators(node_type):
        if creator_op != operation:
            continue
        new_id = extract_resource_id_from_output(result, id_path)
        if new_id:
            new_ids[resource_type] = new_id
    if not new_ids:
        return

    from utils.database_pool import get_native_pool
    from utils.workflow_node_writeback import (
        apply_new_id_to_live_tool_configs,
        extend_node_field_scopes,
    )

    try:
        await extend_node_field_scopes(
            workflow_id=str(workflow_id),
            provider_node_id=str(provider_node_id),
            new_resource_ids_by_type=new_ids,
        )
    except Exception as e:
        logger.warning(
            f"[ToolExec] auto-extend field_scopes failed for "
            f"{provider_node_id}: {e}"
        )
        return

    # In-process mirror — so the SAME agent turn can immediately read/edit
    # the just-created resource without re-collecting tools. Idempotent.
    try:
        apply_new_id_to_live_tool_configs(
            tool_configs, str(provider_node_id), node_type, new_ids,
        )
    except Exception as e:
        logger.warning(
            f"[ToolExec] live tool_configs mirror failed for {provider_node_id}: {e}"
        )


def _enforce_field_scopes(
    arguments: Dict[str, Any], tool_info: Dict
) -> Optional[str]:
    """Return an error message if any scoped field's value isn't in its
    allowlist, else None. ``field_scopes`` is stamped onto the op's tool_info
    by build_node_op_tools when the user pinned that op to specific resource
    IDs."""
    scopes = tool_info.get("field_scopes") or {}
    if not isinstance(scopes, dict):
        return None
    for field, allowed in scopes.items():
        if not isinstance(allowed, list) or not allowed:
            continue
        value = arguments.get(field)
        # Unset scoped fields slip past here — the node's own required-field
        # check fails the call with a clear schema error. Avoid double-failing.
        if value is None or value == "":
            continue
        if value not in allowed:
            return (
                f"'{field}' is restricted to a specific set of resources for this "
                f"tool. Allowed values: {sorted(allowed)}. Got: {value!r}."
            )
    return None


def _with_missing_credential_hint(error: Exception, tool_info: Dict) -> Exception:
    """Node errors with no credential bound are usually cryptic (each node
    fails its own way on missing auth) — tell the agent the actionable cause."""
    if tool_info.get("credential_id"):
        return error
    return RuntimeError(
        f"{error} — note: no credentials are connected to this tool's provider "
        f"node; if this action requires auth, connect credentials on the node "
        f"and re-run."
    )


def _append_lookup_hint(message: str, tool_info: Dict, arguments: Dict) -> str:
    """When a node_op action fails and its provider exposes a lookup tool for
    its ID fields, nudge the agent to resolve the value — a frequent cause is
    the agent passing a human-readable name where an ID is required. Hedged so
    it stays harmless when the failure was unrelated to an ID."""
    lookup_tool = tool_info.get("lookup_tool")
    fields = tool_info.get("lookup_fields") or []
    if not lookup_tool or not fields:
        return message
    supplied = [f for f in fields if isinstance(arguments, dict) and f in arguments]
    target = supplied or fields
    fields_str = ", ".join(repr(f) for f in target)
    return (
        f"{message} — if this failed because a value for {fields_str} could not "
        f"be found, it may be a name rather than an ID. Call {lookup_tool} with "
        f'field="{target[0]}" (and an optional search) to find the correct '
        f"value, then retry."
    )


async def _execute_node_op_lookup(node, tool_name, arguments, tool_info) -> Dict[str, Any]:
    """List valid options for a provider's dynamic ID field (the
    {provider}__lookup_options tool). tool_info['fields'] maps the agent-facing
    config key to the loader's field_name; the field arg is validated against
    it so the loader only ever sees fields this provider exposes."""
    from nodes.core.run_op import run_node_lookup

    node_type = tool_info.get("node_type")
    fields = tool_info.get("fields") or {}
    field = (arguments or {}).get("field")
    if not node_type or field not in fields:
        return {
            "success": False,
            "error": f"Unknown field '{field}'. Valid fields: {sorted(fields)}",
        }

    context = (arguments or {}).get("context")
    scopes = tool_info.get("field_scopes") or {}
    scope_for_field = scopes.get(field) if isinstance(scopes, dict) else None
    try:
        return await run_node_lookup(
            node_type=node_type,
            field_name=fields[field],
            user_id=node.user_id,
            credential_id=tool_info.get("credential_id"),
            context=context if isinstance(context, dict) else None,
            page_token=(arguments or {}).get("page_token"),
            search=(arguments or {}).get("search"),
            organization_id=node.organization_id,
            workflow_id=node.workflow_id,
            allowed_values=scope_for_field if isinstance(scope_for_field, list) else None,
        )
    except Exception as e:
        raise _with_missing_credential_hint(e, tool_info)


# ============================================================================
# Alarm tools
# ============================================================================


async def _execute_alarm_tool(node, tool_name, arguments, tool_info) -> Dict[str, Any]:
    """Dispatch alarm tool calls."""
    if tool_name == "schedule_alarm":
        return await _execute_schedule_alarm(node, arguments, tool_info)
    elif tool_name == "list_alarms":
        return await _execute_list_alarms(node)
    elif tool_name == "cancel_alarm":
        return await _execute_cancel_alarm(node, arguments)
    elif tool_name == "update_alarm":
        return await _execute_update_alarm(node, arguments)
    else:
        return {"success": False, "error": f"Unknown alarm tool: {tool_name}"}


def compute_alarm_upstream_snapshot(
    agent_node_id: str,
    wf_nodes: Optional[List[Dict[str, Any]]],
    wf_edges: Optional[List[Dict[str, Any]]],
    exec_inputs: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Snapshot the upstream node outputs referenced by the agent's alarm subgraph.

    At alarm-schedule time we bake the outputs of upstream nodes referenced by
    ``{{ $('trigger')... }}`` expressions in the subgraph configs, so a future alarm
    fire can restore them (``webhook_routes._restore_upstream_context``). The subgraph
    is the agent + its bottom-handle providers + everything downstream; referenced
    upstream nodes outside it get their live output captured.

    Returns ``{}`` when there is no live graph context or nothing is referenced.
    """
    if not (wf_nodes and wf_edges):
        return {}
    from nodes.agent_node import _extract_referenced_node_ids

    subgraph_ids = {agent_node_id}
    for edge in wf_edges:
        if (
            edge.get("target") == agent_node_id
            and edge.get("targetHandle") == "bottom"
        ):
            subgraph_ids.add(edge.get("source"))
    queue = [agent_node_id]
    visited = {agent_node_id}
    while queue:
        current = queue.pop(0)
        for edge in wf_edges:
            if edge.get("source") == current:
                target = edge.get("target")
                if target and target not in visited:
                    visited.add(target)
                    queue.append(target)
                    subgraph_ids.add(target)

    referenced_ids = set()
    for wf_node in wf_nodes:
        if wf_node.get("id") in subgraph_ids:
            referenced_ids |= _extract_referenced_node_ids(
                wf_node.get("config", {}), workflow_nodes=wf_nodes
            )
    upstream_ids = referenced_ids - subgraph_ids

    return {
        nid: output
        for nid, output in (exec_inputs or {}).items()
        if nid in upstream_ids and isinstance(output, dict)
    }


async def _execute_schedule_alarm(node, arguments, tool_info) -> Dict[str, Any]:
    """Create a one-time alarm or recurring cron schedule."""
    from utils.webhook_manager import WebhookManager
    from utils.cron_scheduler_client import (
        create_alarm,
        create_schedule,
        parse_countdown_to_timestamp,
    )
    from utils.database_pool import get_native_pool

    alarm_type = arguments.get("alarm_type", "countdown")
    delay_or_time = arguments.get("delay_or_time", "")
    message = arguments.get("message", "")
    alarm_node_id = tool_info.get("node_id")

    if not delay_or_time:
        return {"success": False, "error": "delay_or_time is required"}
    if not message:
        return {"success": False, "error": "message is required"}

    pool = get_native_pool()
    webhook_data = await WebhookManager.get_or_create_webhook(
        pool=pool,
        user_id=node.user_id,
        workflow_id=node.workflow_id,
        node_id=alarm_node_id,
    )
    webhook_url = webhook_data.get("webhook_url")
    if not webhook_url:
        return {"success": False, "error": "Failed to create webhook for alarm node"}

    # Snapshot the referenced upstream outputs so a future alarm fire can restore
    # the {{ $('trigger')... }} refs (webhook_routes._restore_upstream_context).
    wf_nodes = getattr(node, "_workflow_nodes", None)
    wf_edges = getattr(node, "_workflow_edges", None)
    if wf_nodes and wf_edges:
        upstream_outputs = compute_alarm_upstream_snapshot(
            node.node_id, wf_nodes, wf_edges, getattr(node, "_execution_inputs", {})
        )
    else:
        # A tool call served over MCP (CLI harnesses) runs with no live execution
        # inputs in this process, so the snapshot was captured at tool injection
        # time and stashed under the per-turn executor_key. Use it here so
        # schedule_alarm still bakes a non-empty upstream_node_outputs.
        upstream_outputs = getattr(node, "_prefetched_upstream_outputs", None) or {}

    alarm_payload = {
        "source": "alarm",
        "alarm_node_id": alarm_node_id,
        "agent_node_id": node.node_id,
        "message": message,
        "conversation_key": getattr(node, "_conversation_key", None),
        "upstream_node_outputs": upstream_outputs,
    }

    try:
        if alarm_type == "countdown":
            run_at = parse_countdown_to_timestamp(delay_or_time)
            result = await create_alarm(
                user_id=node.user_id,
                workflow_id=str(node.workflow_id),
                node_id=alarm_node_id,
                run_at=run_at,
                webhook_url=webhook_url,
                payload=alarm_payload,
            )
        elif alarm_type == "datetime":
            result = await create_alarm(
                user_id=node.user_id,
                workflow_id=str(node.workflow_id),
                node_id=alarm_node_id,
                run_at=delay_or_time,
                webhook_url=webhook_url,
                payload=alarm_payload,
            )
        elif alarm_type == "cron":
            result = await create_schedule(
                user_id=node.user_id,
                workflow_id=str(node.workflow_id),
                node_id=alarm_node_id,
                cron_expression=delay_or_time,
                webhook_url=webhook_url,
                payload=alarm_payload,
            )
        else:
            return {
                "success": False,
                "error": f"Unknown alarm_type: {alarm_type}. Use countdown, datetime, or cron.",
            }
    except ValueError as e:
        return {"success": False, "error": str(e)}

    if "error" in result:
        return {"success": False, "error": result["error"]}

    logger.info(
        f"[ToolExec] Alarm scheduled: type={alarm_type}, schedule_id={result.get('id')}"
    )
    return {
        "success": True,
        "schedule_id": result.get("id"),
        "next_run": result.get("next_run"),
        "alarm_type": alarm_type,
        "message": f"Alarm scheduled ({alarm_type}: {delay_or_time}). You will be woken up with your message.",
    }


async def _execute_list_alarms(node) -> Dict[str, Any]:
    """List all active alarms for this workflow."""
    from utils.cron_scheduler_client import list_schedules

    result = await list_schedules(workflow_id=str(node.workflow_id))
    if isinstance(result, dict) and "error" in result:
        return {"success": False, "error": result["error"]}

    conversation_key = getattr(node, "_conversation_key", None)
    alarms = []
    for schedule in result:
        payload = schedule.get("payload") or {}
        if payload.get("source") != "alarm":
            continue
        if conversation_key and payload.get("conversation_key") != conversation_key:
            continue
        alarms.append(
            {
                "schedule_id": schedule.get("id"),
                "type": "one-time"
                if schedule.get("cron_expression") == "__run_at__"
                else "cron",
                "enabled": bool(schedule.get("enabled", 1)),
                "next_run": schedule.get("next_run_at"),
                "created_at": schedule.get("created_at"),
                "message": payload.get("message", ""),
                "cron_expression": schedule.get("cron_expression"),
                "node_id": schedule.get("node_id"),
                "conversation_key": payload.get("conversation_key"),
            }
        )

    return {"success": True, "alarm_count": len(alarms), "alarms": alarms}


async def _execute_cancel_alarm(node, arguments) -> Dict[str, Any]:
    """Cancel (delete) an alarm by schedule_id."""
    from utils.cron_scheduler_client import delete_schedule

    schedule_id = arguments.get("schedule_id")
    if not schedule_id:
        return {"success": False, "error": "schedule_id is required"}

    result = await delete_schedule(schedule_id=schedule_id)
    if "error" in result:
        return {"success": False, "error": result["error"]}

    logger.info(f"[ToolExec] Alarm cancelled: schedule_id={schedule_id}")
    return {"success": True, "message": f"Alarm {schedule_id} has been cancelled."}


async def _execute_update_alarm(node, arguments) -> Dict[str, Any]:
    """Update an alarm's enabled status or message."""
    from utils.cron_scheduler_client import update_schedule, get_schedule

    schedule_id = arguments.get("schedule_id")
    if not schedule_id:
        return {"success": False, "error": "schedule_id is required"}

    enabled_str = arguments.get("enabled")
    new_message = arguments.get("message")

    if enabled_str is None and new_message is None:
        return {"success": False, "error": "Provide at least one of: enabled, message"}

    kwargs: Dict[str, Any] = {}
    if enabled_str is not None:
        # Tolerate either a string "true"/"false" (schema-specified) or a native
        # JSON boolean (some LLMs emit booleans despite the string schema).
        if isinstance(enabled_str, bool):
            kwargs["enabled"] = enabled_str
        else:
            kwargs["enabled"] = str(enabled_str).lower() == "true"

    if new_message is not None:
        current = await get_schedule(schedule_id)
        if "error" in current:
            return {"success": False, "error": current["error"]}
        existing_payload = current.get("payload") or {}
        existing_payload["message"] = new_message
        kwargs["payload"] = existing_payload

    result = await update_schedule(schedule_id=schedule_id, **kwargs)
    if "error" in result:
        return {"success": False, "error": result["error"]}

    logger.info(f"[ToolExec] Alarm updated: schedule_id={schedule_id}")
    return {
        "success": True,
        "next_run": result.get("next_run"),
        "message": f"Alarm {schedule_id} updated successfully.",
    }


# ============================================================================
# Filesystem tools
# ============================================================================


async def _execute_filesystem_tool(
    node, tool_name, arguments, tool_info
) -> Dict[str, Any]:
    """Execute filesystem tools (upload_file)."""
    if tool_name != "upload_file":
        return {"success": False, "error": f"Unknown filesystem tool: {tool_name}"}

    import os
    import uuid as _uuid
    import mimetypes
    import httpx
    from utils.r2_cloudflare import (
        generate_presigned_upload_url,
        get_public_download_url,
    )
    from utils.database_pool import get_native_pool

    file_path = arguments.get("file_path", "")
    display_name = arguments.get("name", "")
    if not file_path:
        return {"success": False, "error": "file_path is required"}

    if not display_name:
        display_name = os.path.basename(file_path)
    mime_type, _ = mimetypes.guess_type(file_path)
    mime_type = mime_type or "application/octet-stream"

    resource_type = (
        "image"
        if mime_type.startswith("image/")
        else "video"
        if mime_type.startswith("video/")
        else "audio"
        if mime_type.startswith("audio/")
        else "file"
    )

    # Read file from the sandbox via the runtime's uniform read surface.
    file_content = None
    agent = getattr(node, "_active_agent", None)
    runtime = getattr(agent, "_runtime", None) if agent else None
    if runtime is not None:
        file_content = await runtime.read_file(file_path)

    if file_content is None:
        return {"success": False, "error": f"Could not read file: {file_path}"}

    try:
        from utils.resource_store import create_resource_from_bytes

        wf_row = await get_native_pool().fetchrow(
            "SELECT organization_id FROM workflows WHERE id = $1", node.workflow_id
        )
        org_id = wf_row["organization_id"] if wf_row else None

        ref = await create_resource_from_bytes(
            user_id=node.user_id,
            workflow_id=node.workflow_id,
            node_id=node.node_id,
            organization_id=org_id,
            body=file_content,
            content_type=mime_type,
            filename=display_name,
            resource_type=resource_type,
        )
        logger.info(
            f"[ToolExec] Uploaded {file_path} → {ref['download_url']} ({ref['size_bytes']} bytes)"
        )

        return {
            "success": True,
            "url": ref["download_url"],
            "resource_id": ref["resource_id"],
            "name": ref["name"],
            "size_bytes": ref["size_bytes"],
            "mime_type": ref["mime_type"],
            "message": f"File uploaded successfully. Public URL: {ref['download_url']}",
        }

    except Exception as e:
        logger.error(f"[ToolExec] Failed to upload file: {e}", exc_info=True)
        return {"success": False, "error": f"Upload failed: {e}"}
