"""A workflow the owner picked on a public page (an /agents page, /mcp), finished in the coordinator's thread.

The page builds the workflow and the chat creates it, then asks for this: a note from NoClick naming it, which
the chat draws its setup card under (connect the apps, then add the link to your own agent or talk to the agent
NoClick runs). The card reads the workflow live, so the note never goes stale. The coordinator's own history
gets the same line with the ids it needs, so "now ask it to…" is understood. One note per workflow, however
often it's asked for."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from utils.graph_nodes import graph_edges, graph_nodes, node_config, node_label, parse_graph

logger = logging.getLogger(__name__)


def setup_kind(graph: Dict[str, Any]) -> Optional[str]:
    """``mcp`` for a hosted link (an mcp-server node serving the apps wired into it), ``agent`` for an agent."""
    nodes = graph_nodes(graph)
    hosted = {
        e.get("target") or e.get("targetId")
        for e in graph_edges(graph)
        if e.get("targetHandle") == "bottom"
    }
    if any(n.get("type") == "mcp-server" and n.get("id") in hosted and not node_config(n).get("server_url") for n in nodes):
        return "mcp"
    if any(n.get("type") == "agent" for n in nodes):
        return "agent"
    return None


def _context_line(kind: str, name: str, workflow_id: str, graph: Dict[str, Any]) -> str:
    nodes = graph_nodes(graph)
    apps = ", ".join(node_label(n) for n in nodes if n.get("type", "").startswith("automation-")) or "its apps"
    if kind == "mcp":
        return (f"(Picked on a public page: {name}, workflow_id={workflow_id}, a hosted MCP link serving {apps} "
                f"tools to the owner's own agent on their computer. Its card above connects {apps} and shows how to "
                "add the link; describe_workflow shows the link and what is connected.)")
    agent = next(n for n in nodes if n.get("type") == "agent")
    return (f"(Picked on a public page: {name}, workflow_id={workflow_id}, agent node_id={agent['id']}, an agent "
            f"NoClick runs with {apps} as tools. Its card above connects the agent's AI account and {apps}; once "
            "they're connected, send it work with message_agent.)")


async def post_arrival(pool, user_id: str, *, workflow_id: str, client: Optional[str]) -> Dict[str, Any]:
    from coder.coordinator.agent import conversation_id_for
    from coder.coordinator.tools import COORDINATOR_NODE_ID
    from repositories.conversation import ConversationRepo
    from repositories.workflow import WorkflowRepo
    from utils.access_control import Permission, check_resource_access
    from utils.async_helpers import spawn
    from utils.socket_singleton import get_sio
    from utils.task_notifications import emit_notification, notification_event

    async with pool.acquire() as conn:
        access = await check_resource_access(conn, user_id, "workflow", workflow_id)
        if access.permission != Permission.OWNER:
            raise ValueError("That automation isn't yours to set up.")
        row = await WorkflowRepo(pool).get_workflow_full(conn, workflow_id)
    graph = parse_graph(row["workflow"])
    kind = setup_kind(graph)
    if kind is None:
        raise ValueError("There's nothing to set up in that automation.")
    name = " ".join(str(row["name"] or "").split())[:120] or "your automation"
    text = f"Let’s finish setting up {name}."
    setup = {"kind": kind, "workflow_id": workflow_id, **({"client": client} if client else {})}
    event = notification_event(text, f"setup:{workflow_id}", setup=setup)
    conversation_id = conversation_id_for(user_id)
    added = await ConversationRepo(pool).append_chat_event_once(
        conversation_id=conversation_id, user_id=user_id, node_id=COORDINATOR_NODE_ID, event=event, label="Coordinator",
    )
    if added:
        await emit_notification(get_sio(), user_id, conversation_id, event)
        spawn(_remember(pool, user_id, conversation_id, f"{text} {_context_line(kind, name, workflow_id, graph)}"),
              name=f"coordinator-arrival:{workflow_id[:8]}")
    # The asking tab gets the note in the reply: it can land before that tab's relay is connected.
    return {"turn_id": event["turn_id"], "note": {"message": text, "turn_id": event["turn_id"], "setup": setup}}


async def _remember(pool, user_id: str, conversation_id: str, line: str) -> None:
    """Into the model's history between turns: under the turn lease, so it never lands inside a turn's tool pair."""
    from coder.openai_agent.session import PostgresSession
    from repositories.coordinator_lease import coordinator_lock

    try:
        async with coordinator_lock(pool, user_id):
            await PostgresSession(conversation_id, user_id=user_id).add_items([{"role": "assistant", "content": line}])
    except Exception:
        logger.error("coordinator arrival: could not add the setup to %s's history", user_id, exc_info=True)
