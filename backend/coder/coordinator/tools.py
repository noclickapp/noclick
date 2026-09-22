"""The coordinator's tools: the account's existing read and write seams handed
to one SDK agent. Nothing new sits underneath — the Dashboard aggregate is the
read, the headless builder is the write, and every call is audited the way a
workflow agent's tool calls are."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from repositories.builder_bridge import BuilderBridgeRepo
from repositories.conversation import ConversationRepo
from repositories.coordinator_memories import CoordinatorMemoryRepo
from repositories.builder_requests import BuilderRequestRepo
from repositories.workflow import WorkflowRepo
from utils.coordinator_memory import CoordinatorMemoryWrite
from utils.builder_request import PublicationOptions
from utils.builder_bridge import bridge_url, create_bridge_link_for_ask
from utils.capabilities import INTERFACE_PUBLISH, OWNER_MESSAGE, capability
from utils.tool_call_log import record_tool_call

logger = logging.getLogger(__name__)

COORDINATOR_TOOL_TYPE = "coordinator"
# The audit's per-(node, conversation) turn boundary needs a node id; the
# coordinator is not a node, so it borrows the builder's sentinel convention.
COORDINATOR_NODE_ID = "__coordinator__"

MAX_ITEMS = 10
MAX_CHARS = 280
_OVERVIEW_SECTIONS = ("attention", "runs", "agents", "credentials", "triggers", "upcoming", "notifications", "files")


def coordinator_tool_params(*, include_owner_message: bool = False, include_publishing: bool = False) -> List[Dict[str, Any]]:
    """ChatCompletionToolParam dicts — the shape Agent.create's custom_tools takes.
    ``message_owner`` is advertised only where the instance can deliver one."""
    def tool(name: str, description: str, properties: Dict[str, Any], required: Optional[List[str]] = None):
        return {"type": "function", "function": {
            "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False},
        }}
    params = [
        tool("search_memories", "Find durable memories by keywords, or list their retrieval headers. "
             "Search includes full bodies but returns only descriptions; read_memory loads the content.",
             {"query": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}}),
        tool("read_memory", "Read one memory's complete Markdown body and current version before using or updating it.",
             {"memory_id": {"type": "string"}}, ["memory_id"]),
        tool("save_memory", "Remember a durable fact or correction. Write a semantic description of what this "
             "memory contains and when to retrieve it, separately from the full Markdown content. Never derive "
             "the description by truncating the body. Search first to avoid duplicates. To update, read the "
             "existing entry and pass memory_id and expected_version; omit both for a new memory.",
             CoordinatorMemoryWrite.model_json_schema()["properties"],
             CoordinatorMemoryWrite.model_json_schema()["required"]),
        tool("forget_memory", "Forget a memory at the user's request. Requires its current version; "
             "deleted memories must not be recreated from old conversations.",
             {"memory_id": {"type": "string"}, "expected_version": {"type": "integer", "minimum": 1}},
             ["memory_id", "expected_version"]),
        tool("search_history", "Find older messages in this account's coordinator conversation, across channels. "
             "Use concise keywords; returns excerpts with positions. Pass next_before as before for older matches.",
             {"query": {"type": "string"}, "before": {"type": "integer", "minimum": 1}}, ["query"]),
        tool("account_overview",
             "What is going on in this account right now: items needing the owner, recent and upcoming runs, "
             "running agents, credential health, unread notifications. Same data as the Dashboard.",
             {"section": {"type": "string", "enum": ["all", *_OVERVIEW_SECTIONS],
                          "description": "One section, or 'all' for a bounded summary of every section."}}),
        tool("list_workflows", "The account's workflows (agents and automations) with ids, names and descriptions.",
             {"query": {"type": "string", "description": "Optional name/description filter."}}),
        tool("describe_workflow",
             "A workflow's full structure: nodes, wiring, triggers, credentials with health, readiness and public endpoints. "
             "Free; use it before proposing or requesting a change.",
             {"workflow_id": {"type": "string"},
              "focus": {"type": "string", "description": "Optional node id to anchor the notes on."}},
             ["workflow_id"]),
        tool("find_agents", "Find existing agents by their name, workflow or purpose. Returns workflow_id and node_id for message_agent.",
             {"query": {"type": "string", "description": "Optional name or purpose to search for."}}),
        tool("message_agent", "Send work to an existing agent. Returns a durable task immediately; its reply arrives "
             "in this conversation when ready. The agent uses its configured tools and may run downstream workflow actions. "
             "For a follow-up, pass reply_to_task_id to preserve that agent's conversation; otherwise start a new conversation.",
             {"workflow_id": {"type": "string"}, "node_id": {"type": "string"},
              "message": {"type": "string", "description": "Complete instructions and relevant context for the agent."},
              "reply_to_task_id": {"type": "string", "description": "A prior task to this agent whose conversation to continue."}},
             ["workflow_id", "node_id", "message"]),
        tool("agent_tasks", "Read your agent requests, their status and their actual replies. Pass task_id for one "
             "specific request; otherwise lists active tasks first, then recent results.",
             {"task_id": {"type": "string"}}),
        tool("request_build",
             "Ask the builder to create or edit an interface, agent, or workflow, with optional publication. "
             "The builder owns all phases and questions; check build_status using the returned request_id. "
             "To publish an existing saved interface without rebuilding, pass workflow_id and publish, and omit instructions. "
             "Publication makes the interface public and its visitors can invoke the workflow; only request it when authorized.",
             {"instructions": {"type": "string", "description": "What to build or change. Required unless publishing an existing interface."},
              "workflow_id": {"type": "string", "description": "Existing workflow, or omit to create one."},
              "name": {"type": "string", "description": "Name for a new workflow."},
              "send_to_phone": {"type": "boolean", "description": "Send the result to the owner's phone when requested."},
              **({"publish": {**PublicationOptions.model_json_schema(),
                  "description": "Publish the interface when building finishes. Omit node_id only if there is one interface."}}
                 if include_publishing else {})}),
        tool("build_status", "Read builder requests: status, current phase, questions and answer links, results, "
             "published URLs, and separate delivery outcomes.",
             {"request_id": {"type": "string"}, "builder_conversation_id": {"type": "string"}}),
        tool("cancel_build", "Cancel a builder request before publishing starts. A build already running may finish, "
             "but no later steps will run.", {"request_id": {"type": "string"}}, ["request_id"]),
        tool("trash_workflow",
             "Move a workflow the owner owns to the trash: it stops running, its schedules and webhooks are removed, "
             "and it can be restored for 30 days before it is deleted for good. Confirm with the owner first.",
             {"workflow_id": {"type": "string"}}, ["workflow_id"]),
        tool("restore_workflow", "Bring a trashed workflow back, with its schedules and webhooks.",
             {"workflow_id": {"type": "string"}}, ["workflow_id"]),
    ]
    if include_owner_message:
        params.append(tool(
            "message_owner",
            "Send the owner a WhatsApp message on their linked phone: a link, a summary, anything they asked to have "
            "sent there. Not needed when you are already replying over WhatsApp text.",
            {"text": {"type": "string", "description": "The message, short and plain."},
             "link": {"type": "string", "description": "Optional URL, sent on its own line."}},
            ["text"],
        ))
    return params


def bounded(value: Any, *, max_items: int = MAX_ITEMS, max_chars: int = MAX_CHARS, depth: int = 8) -> Any:
    """A model-sized projection of a payload: lists capped, strings clipped,
    nesting limited. Keys are kept so ids stay usable by the other tools."""
    if depth <= 0:
        return "…"
    if isinstance(value, dict):
        return {str(k): bounded(v, max_items=max_items, max_chars=max_chars, depth=depth - 1) for k, v in value.items()}
    if isinstance(value, list):
        clipped = [bounded(v, max_items=max_items, max_chars=max_chars, depth=depth - 1) for v in value[:max_items]]
        if len(value) > max_items:
            clipped.append(f"… {len(value) - max_items} more")
        return clipped
    if isinstance(value, str) and len(value) > max_chars:
        return value[: max_chars - 1] + "…"
    return value


class CoordinatorTools:
    def __init__(self, *, pool, sio, user_id: str, organization_id: Optional[str], conversation_id: str,
                 reply_channel: str = "web"):
        self.pool = pool
        self.sio = sio
        self.user_id = user_id
        self.organization_id = organization_id
        self.conversation_id = conversation_id
        self.reply_channel = reply_channel
        self._tools: Dict[str, Callable[..., Awaitable[Dict[str, Any]]]] = {
            "search_memories": self.search_memories,
            "read_memory": self.read_memory,
            "save_memory": self.save_memory,
            "forget_memory": self.forget_memory,
            "search_history": self.search_history,
            "account_overview": self.account_overview,
            "list_workflows": self.list_workflows,
            "describe_workflow": self.describe_workflow,
            "find_agents": self.find_agents,
            "message_agent": self.message_agent,
            "agent_tasks": self.agent_tasks,
            "request_build": self.request_build,
            "build_status": self.build_status,
            "cancel_build": self.cancel_build,
            "trash_workflow": self.trash_workflow,
            "restore_workflow": self.restore_workflow,
        }
        if capability(OWNER_MESSAGE) is not None:
            self._tools["message_owner"] = self.message_owner

    @property
    def can_message_owner(self) -> bool:
        return "message_owner" in self._tools

    def tool_params(self) -> List[Dict[str, Any]]:
        return coordinator_tool_params(include_owner_message=self.can_message_owner,
                                       include_publishing=capability(INTERFACE_PUBLISH) is not None)

    async def execute(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """The custom_tool_executor seam: dispatch, never raise, always audit."""
        started = time.monotonic()
        method = self._tools.get(name)
        try:
            if method is None:
                result: Dict[str, Any] = {"success": False, "error": f"unknown tool: {name}"}
            else:
                result = await method(**(arguments or {}))
        except TypeError as exc:
            result = {"success": False, "error": f"bad arguments for {name}: {exc}"}
        except Exception as exc:
            logger.error("coordinator tool %s failed", name, exc_info=True)
            result = {"success": False, "error": str(exc)}
        record_tool_call(
            user_id=self.user_id, tool_name=name, tool_type=COORDINATOR_TOOL_TYPE,
            result_status="success" if result.get("success", True) else "error",
            conversation_id=self.conversation_id, agent_node_id=COORDINATOR_NODE_ID,
            arguments=arguments, error=None if result.get("success", True) else str(result.get("error")),
            result_preview=json.dumps(result, default=str)[:500],
            duration_ms=(time.monotonic() - started) * 1000,
        )
        return result

    async def search_memories(self, query: str = "", offset: int = 0) -> Dict[str, Any]:
        return {"success": True, **await CoordinatorMemoryRepo(self.pool).list_headers(
            self.user_id, query=query, limit=20, offset=offset,
        )}

    async def read_memory(self, memory_id: str) -> Dict[str, Any]:
        return {"success": True, "memory": await CoordinatorMemoryRepo(self.pool).get(self.user_id, memory_id)}

    async def save_memory(self, **fields) -> Dict[str, Any]:
        memory = CoordinatorMemoryWrite.model_validate(fields)
        saved = await CoordinatorMemoryRepo(self.pool).save(
            self.user_id, memory, origin_conversation_id=self.conversation_id,
        )
        # The model just authored the body; echoing it spends context unnecessarily.
        return {"success": True, "memory": {k: v for k, v in saved.items() if k != "content"}}

    async def forget_memory(self, memory_id: str, expected_version: int) -> Dict[str, Any]:
        return {"success": True, **await CoordinatorMemoryRepo(self.pool).delete(self.user_id, memory_id, expected_version)}

    async def search_history(self, query: str, before: Optional[int] = None) -> Dict[str, Any]:
        return {"success": True, **await ConversationRepo(self.pool).search_messages(
            self.conversation_id, self.user_id, query, before=before,
        )}

    async def account_overview(self, section: str = "all") -> Dict[str, Any]:
        from wss.handlers.dashboard_handler import build_overview

        payload = await build_overview(self.pool, self.user_id)
        if section != "all":
            if section not in _OVERVIEW_SECTIONS:
                return {"success": False, "error": f"unknown section: {section}"}
            payload = {k: v for k, v in payload.items() if k in (section, "workspace", "generatedAt", "errors")}
        return {"success": True, "overview": bounded(payload)}

    async def list_workflows(self, query: Optional[str] = None) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            rows = await WorkflowRepo(self.pool).list_workflows_builder(
                conn, user_id=uuid.UUID(self.user_id),
                organization_id=uuid.UUID(self.organization_id) if self.organization_id else None,
                query=query or None, limit=40,
            )
        return {"success": True, "workflows": [
            {"id": str(r["id"]), "name": r.get("name"), "description": r.get("description"),
             "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None}
            for r in rows
        ]}

    async def _accessible_graph(self, workflow_id: str):
        """The saved graph, only if this user may see it — the node-side
        describe reads by id alone because it runs inside the workflow."""
        from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

        try:
            uuid.UUID(workflow_id)
        except (TypeError, ValueError):
            return None
        return await WorkflowExecutionHandler(self.sio)._fetch_workflow(workflow_id, self.user_id)

    async def find_agents(self, query: Optional[str] = None) -> Dict[str, Any]:
        from repositories.dashboard import DashboardRepo
        from utils.graph_nodes import graph_nodes, node_config, node_disabled, node_label, node_model

        rows = await DashboardRepo(self.pool).list_workflows(
            self.user_id, uuid.UUID(self.organization_id) if self.organization_id else None,
        )
        found = []
        wanted = (query or "").casefold().strip()
        for row in rows:
            for node in graph_nodes(row["workflow"]):
                if node.get("type") != "agent":
                    continue
                goal = str(node_config(node).get("goal") or (node.get("data") or {}).get("goal") or "")
                name = node_label(node) or "Agent"
                if wanted and wanted not in f"{row['name']} {name} {goal}".casefold():
                    continue
                found.append({"workflow_id": str(row["id"]), "workflow_name": row["name"],
                              "node_id": node["id"], "name": name, "purpose": goal[:500],
                              "model": node_model(node), "disabled": node_disabled(node)})
        return {"success": True, "agents": found[:40], "has_more": len(found) > 40}

    async def message_agent(self, workflow_id: str, node_id: str, message: str,
                            reply_to_task_id: Optional[str] = None) -> Dict[str, Any]:
        from coder.coordinator.tasks import request_agent_message

        return await request_agent_message(
            self.pool, self.sio, user_id=self.user_id, workflow_id=workflow_id, node_id=node_id,
            message=message, channel=self.reply_channel, reply_to_task_id=reply_to_task_id,
        )

    async def agent_tasks(self, task_id: Optional[str] = None) -> Dict[str, Any]:
        from coder.coordinator.tasks import task_view
        from repositories.coordinator_tasks import CoordinatorTaskRepo

        if task_id:
            uuid.UUID(task_id)
        rows = await CoordinatorTaskRepo(self.pool).list_for_user(self.user_id, task_id)
        return {"success": True, "tasks": [task_view(row) for row in rows]}

    async def describe_workflow(self, workflow_id: str, focus: Optional[str] = None) -> Dict[str, Any]:
        from nodes.agent.platform_tools import describe_workflow_impl

        if await self._accessible_graph(workflow_id) is None:
            return {"success": False, "error": "workflow not found"}
        result = await describe_workflow_impl(
            self.pool, user_id=self.user_id, workflow_id=workflow_id, node_id=None, focus=focus,
        )
        result.pop("your_node_id", None)
        return result

    async def request_build(
        self, instructions: Optional[str] = None, workflow_id: Optional[str] = None, name: Optional[str] = None,
        publish: Optional[Dict[str, Any]] = None, send_to_phone: bool = False,
    ) -> Dict[str, Any]:
        from coder.workflow.requests import request_view, submit_request

        request = await submit_request(
            self.pool, user_id=self.user_id, workflow_id=workflow_id, instructions=instructions, name=name, publish=publish,
            origin={"source": "coordinator", "coordinator_conversation_id": self.conversation_id},
            reply_conversation_id=self.conversation_id, reply_node_id=COORDINATOR_NODE_ID,
            send_to_phone=send_to_phone or self.reply_channel != "web",
        )
        return {"success": True, **request_view(request),
                "note": "The builder owns this request through completion. build_status shows its phase and questions; "
                        "the result will arrive here when finished."}

    async def cancel_build(self, request_id: str) -> Dict[str, Any]:
        from coder.workflow.requests import request_view

        uuid.UUID(request_id)
        request = await BuilderRequestRepo(self.pool).cancel(self.user_id, request_id)
        return {"success": True, **request_view(request)}

    async def build_status(self, builder_conversation_id: Optional[str] = None, request_id: Optional[str] = None) -> Dict[str, Any]:
        from coder.workflow.requests import request_view

        if request_id:
            uuid.UUID(request_id)
        rows = await BuilderRequestRepo(self.pool).list_for_user(
            self.user_id, request_id=request_id, conversation_id=builder_conversation_id,
        )
        builds = []
        for row in rows:
            entry = request_view(row)
            ask = row["pending_ask"]
            if row["status"] == "waiting_for_input" and ask:
                entry["waiting_for"] = await self._ask_link(row, ask)
            builds.append(entry)
        return {"success": True, "builds": builds}

    async def _ask_link(self, row: Dict[str, Any], ask: Dict[str, Any]) -> Dict[str, Any]:
        """The question the builder parked on and the one link that answers
        it — reused when it already exists, minted otherwise."""
        inputs = ask.get("inputs") or []
        link_id = await BuilderBridgeRepo(self.pool).find_pending_for_ask(row["conversation_id"], ask["ask_id"])
        if link_id:
            return {"questions": [i.get("label") for i in inputs if i.get("label")], "answer_url": bridge_url(link_id)}
        minted = await create_bridge_link_for_ask(
            self.pool, user_id=self.user_id, workflow_id=row.get("workflow_id"),
            builder_conversation_id=row["conversation_id"], ask_id=ask["ask_id"], inputs=inputs,
            agent_conversation_id=None, agent_node_id=None, workflow_name=None,
        )
        if not minted:
            return {"questions": [i.get("label") for i in inputs if i.get("label")], "answer_url": None}
        return {"questions": minted["questions"], "answer_url": minted["url"]}

    async def trash_workflow(self, workflow_id: str) -> Dict[str, Any]:
        from wss.handlers.workflow_handler import trash_workflow_as_owner

        return await trash_workflow_as_owner(self.pool, workflow_id, self.user_id)

    async def restore_workflow(self, workflow_id: str) -> Dict[str, Any]:
        from wss.handlers.workflow_handler import restore_workflow_as_owner

        return await restore_workflow_as_owner(self.pool, workflow_id, self.user_id)

    async def message_owner(self, text: str, link: Optional[str] = None) -> Dict[str, Any]:
        send = capability(OWNER_MESSAGE)
        if send is None:
            return {"success": False, "error": "this instance has no channel to message the owner on"}
        text = (text or "").strip()
        if not text:
            return {"success": False, "error": "text is required"}
        return await send(self.pool, self.user_id, text, link=(link or "").strip() or None)
