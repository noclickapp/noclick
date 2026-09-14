"""Execution readiness shared by activation, setup and agent introspection.

Configuration proves executability; only persisted run provenance proves input
was received. Neither one proves an alert was delivered to its recipient.
"""
from typing import Any, Dict, Optional
from contextlib import contextmanager
from contextvars import ContextVar

from utils.graph_nodes import (
    graph_nodes,
    graph_edges,
    node_config,
    is_trigger_node,
    parse_graph,
)


class WorkflowNotReadyError(ValueError):
    pass


_activation_graph = ContextVar("activation_graph", default=None)


@contextmanager
def activation_graph_scope(workflow_id, graph):
    token = _activation_graph.set((str(workflow_id), graph))
    try:
        yield
    finally:
        _activation_graph.reset(token)


def activation_issues(graph: dict, trigger_id: Optional[str] = None) -> list[dict]:
    from nodes.core.registry import NODE_REGISTRY
    from nodes.agent.node_op_tools import (
        is_node_op_provider,
        allowlist_requires_credentials,
    )
    from coder.workflow.operation_catalog import node_requires_credentials
    from coder.workflow.workflow_ops import agent_message_error, agent_trigger_fed
    from utils.credentials import extract_credential_ids

    nodes = [{**n, "config": node_config(n)} for n in graph_nodes(graph)]
    edges = [
        {
            **e,
            "source": e.get("source") or e.get("sourceId"),
            "target": e.get("target") or e.get("targetId"),
        }
        for e in graph_edges(graph)
    ]
    by_id = {n["id"]: n for n in nodes if n.get("id")}
    enabled = {
        nid
        for nid, n in by_id.items()
        if n["config"].get("disabled") not in (True, "true")
    }
    scope = enabled.copy() if trigger_id is None else {trigger_id} & enabled
    if trigger_id is not None:
        while True:
            expanded = scope | {
                e["target"]
                for e in edges
                if e["source"] in scope
                and (
                    e.get("targetHandle") != "bottom"
                    or by_id.get(e["source"], {}).get("type") == "alarm"
                )
                and e["target"] in enabled
            }
            if expanded == scope:
                break
            scope = expanded
        scope |= {
            e["source"]
            for e in edges
            if e["target"] in scope
            and e.get("targetHandle") == "bottom"
            and e["source"] in enabled
        }
    issues = []
    if trigger_id is not None and trigger_id not in enabled:
        return [
            {
                "node_id": trigger_id,
                "code": "disabled",
                "message": "Enable the trigger before activating it.",
            }
        ]
    for nid in sorted(scope):
        n = by_id[nid]
        kind, cfg = n.get("type", ""), n["config"]
        node_cls = NODE_REGISTRY.get(kind)
        if node_cls is None:
            if kind not in ("sticky-note", "sticky_note", "stickyNote", "note"):
                issues.append(
                    {
                        "node_id": nid,
                        "code": "unknown_node",
                        "message": f"{nid}: unknown node type {kind}",
                    }
                )
            continue
        provider = is_node_op_provider(nid, kind, nodes, edges)
        operation = cfg.get("operation") or "default"
        needs_credential = (
            allowlist_requires_credentials(kind, cfg.get("agent_tool_operations") or [])
            if provider
            else node_requires_credentials(kind, operation, cfg)
        )
        if needs_credential and not extract_credential_ids(cfg):
            issues.append(
                {
                    "node_id": nid,
                    "code": "missing_credentials",
                    "message": f"{cfg.get('label') or nid}: connect an account",
                }
            )
        if not provider:
            result = node_cls.validate_config({"config": cfg})
            errors = list(result.get("errors") or [])
            if kind == "agent":
                message_error = agent_message_error(
                    cfg,
                    trigger_fed=agent_trigger_fed(
                        nid, [by_id[source] for source in enabled], edges,
                    ),
                )
                if message_error:
                    errors.append(message_error)
            for error in errors:
                issues.append(
                    {
                        "node_id": nid,
                        "code": "invalid_config",
                        "message": f"{cfg.get('label') or nid}: {error}",
                    }
                )
    return issues


async def require_activation_ready(pool, workflow_id, node_id):
    from repositories.workflow import WorkflowRepo

    current = _activation_graph.get()
    if current and current[0] == str(workflow_id) and current[1] is not None:
        graph = current[1]
    else:
        async with pool.acquire() as conn:
            row = await WorkflowRepo(pool).get_workflow_data(conn, workflow_id)
        if not row:
            raise WorkflowNotReadyError(
                "Save the workflow before activating its trigger."
            )
        graph = parse_graph(row["workflow"])
    if node_id not in {n.get("id") for n in graph_nodes(graph)}:
        raise WorkflowNotReadyError("Save the trigger before activating it.")
    issues = activation_issues(graph, node_id)
    if issues:
        raise WorkflowNotReadyError(
            "Finish setup before activation: " + "; ".join(i["message"] for i in issues)
        )


async def readiness_report(
    pool, workflow_id, graph: Dict[str, Any], *, conn=None, credential_health=None
) -> dict:
    from nodes.agent.node_op_tools import effective_provider_operations
    from repositories.workflow import WorkflowRepo

    nodes = graph_nodes(graph)
    triggers = [
        n
        for n in nodes
        if is_trigger_node(n)
        and node_config(n).get("disabled") not in (True, "true")
        and n.get("type") != "trigger-run"
    ]
    issues = activation_issues(graph)
    for trigger in triggers:
        error = node_config(trigger).get("trigger_error")
        if error:
            issues.append(
                {
                    "node_id": trigger["id"],
                    "code": "registration_failed",
                    "message": str(error),
                }
            )
    alarm_ids = [
        n["id"]
        for n in nodes
        if n.get("type") == "alarm"
        and node_config(n).get("disabled") not in (True, "true")
    ]
    repo = WorkflowRepo(pool)

    async def evidence(connection):
        ids = [n["id"] for n in triggers]
        return (
            await repo.get_trigger_observations(connection, workflow_id, ids),
            await repo.get_registered_trigger_ids(connection, workflow_id, ids),
            await repo.get_deadline_watches(connection, workflow_id, alarm_ids),
        )

    if conn is not None:
        observations, registered, watches = await evidence(conn)
    else:
        async with pool.acquire() as connection:
            observations, registered, watches = await evidence(connection)
    # A definitive dead connection blocks readiness; unavailable health data
    # remains unknown and cannot establish a successful live connection.
    from utils.credentials import extract_credential_ids

    if credential_health is None:
        from utils.credential_health import (
            fetch_credential_health_for_ids,
            health_relevant_credential_ids,
        )

        credential_health = await fetch_credential_health_for_ids(
            pool,
            list(
                {
                    cid
                    for n in nodes
                    for cid in health_relevant_credential_ids(node_config(n))
                }
            ),
        )
    for n in nodes:
        for cid in extract_credential_ids(node_config(n)).values():
            health = credential_health.get(cid)
            if (
                health
                and not health.healthy
                and node_config(n).get("disabled") not in (True, "true")
            ):
                issues.append(
                    {
                        "node_id": n["id"],
                        "code": "connection_unhealthy",
                        "message": health.hint,
                    }
                )
    destinations = []
    for n in nodes:
        cfg = node_config(n)
        if cfg.get("disabled") in (True, "true") or not cfg.get(
            "agent_tool_operations"
        ):
            continue
        for op in effective_provider_operations(n.get("type", ""), cfg):
            if isinstance(op, dict) and op.get("field_scopes", {}).get("to"):
                destinations.append(
                    {
                        "node_id": n["id"],
                        "operation": op["operation"],
                        "recipients": op["field_scopes"]["to"],
                    }
                )
    if issues:
        status = "needs_setup"
    elif observations:
        status = "input_observed"
    elif any(w["status"] == "armed" for w in watches):
        status = "deadline_armed"
    elif triggers and len(registered) == len(triggers):
        status = "waiting_for_input"
    elif triggers or alarm_ids:
        status = "configured"
    else:
        status = "manual_only"
    return {
        "status": status,
        "registered_trigger_ids": registered,
        "deadline_watches": watches,
        "alarm_node_ids": alarm_ids,
        "issues": issues,
        "observations": observations,
        "destinations": destinations,
        "explanation": "Observed input is historical evidence. Rehearsals and manual empty runs do not verify live monitoring; provider acceptance does not establish delivery.",
    }
