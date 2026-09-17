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
from repositories.workflow import WorkflowRepo
from utils.async_helpers import spawn
from utils.builder_bridge import bridge_url, create_bridge_link_for_ask
from utils.tool_call_log import record_tool_call

logger = logging.getLogger(__name__)

COORDINATOR_TOOL_TYPE = "coordinator"
# The audit's per-(node, conversation) turn boundary needs a node id; the
# coordinator is not a node, so it borrows the builder's sentinel convention.
COORDINATOR_NODE_ID = "__coordinator__"
BUILDER_CONVERSATION_PREFIX = "coordinator-builder:"

MAX_ITEMS = 10
MAX_CHARS = 280
_OVERVIEW_SECTIONS = ("attention", "runs", "agents", "credentials", "triggers", "upcoming", "notifications", "files")


def coordinator_tool_params() -> List[Dict[str, Any]]:
    """ChatCompletionToolParam dicts — the shape Agent.create's custom_tools takes."""
    def tool(name: str, description: str, properties: Dict[str, Any], required: Optional[List[str]] = None):
        return {"type": "function", "function": {
            "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False},
        }}
    return [
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
        tool("request_build",
             "Hand a build or edit to the AI builder, which runs in the background as the account owner. "
             "Give it a new workflow's name or an existing workflow_id, plus complete instructions. "
             "Returns immediately; check on it with build_status. If the builder needs something from the "
             "owner, they get a WhatsApp message with the link and it appears in this thread.",
             {"instructions": {"type": "string", "description": "What to build or change, in full."},
              "workflow_id": {"type": "string", "description": "Edit this existing workflow. Omit to create a new one."},
              "name": {"type": "string", "description": "Name for a new workflow."}},
             ["instructions"]),
        tool("build_status",
             "Where the builds you requested stand: finished, running, or waiting on the owner (with the questions "
             "and the link that answers them).",
             {"builder_conversation_id": {"type": "string", "description": "One build, else the latest few."}}),
    ]


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
    def __init__(self, *, pool, sio, user_id: str, organization_id: Optional[str], conversation_id: str):
        self.pool = pool
        self.sio = sio
        self.user_id = user_id
        self.organization_id = organization_id
        self.conversation_id = conversation_id
        self._tools: Dict[str, Callable[..., Awaitable[Dict[str, Any]]]] = {
            "account_overview": self.account_overview,
            "list_workflows": self.list_workflows,
            "describe_workflow": self.describe_workflow,
            "request_build": self.request_build,
            "build_status": self.build_status,
        }

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
        self, instructions: str, workflow_id: Optional[str] = None, name: Optional[str] = None,
    ) -> Dict[str, Any]:
        from wss.handlers.workflow_builder_handler import create_workflow_as_user
        from wss.receiver.client_events import WorkflowBuilderEditRequest

        instructions = (instructions or "").strip()
        if not instructions:
            return {"success": False, "error": "instructions are required"}
        if workflow_id:
            fetched = await self._accessible_graph(workflow_id)
            if fetched is None:
                return {"success": False, "error": "workflow not found"}
            nodes, edges = fetched[0], fetched[1]
            workflow_name = await self.pool.fetchval("SELECT name FROM workflows WHERE id = $1::uuid", workflow_id)
        else:
            created = await create_workflow_as_user(
                self.pool, self.user_id, name=(name or "New workflow").strip()[:120], description=instructions[:300],
            )
            if created.get("error"):
                return {"success": False, "error": created["error"]}
            workflow_id, workflow_name = created["workflow_id"], created["name"]
            nodes, edges = [], []
        builder_conversation_id = f"{BUILDER_CONVERSATION_PREFIX}{self.user_id}:{uuid.uuid4().hex[:8]}"
        request = WorkflowBuilderEditRequest(
            request_id=f"coordinator-{uuid.uuid4().hex[:8]}",
            current_graph={"nodes": nodes, "edges": edges},
            edit_prompt=instructions,
            conversation_id=builder_conversation_id,
            user_context={
                "workflow_id": workflow_id,
                "source": "coordinator",
                "coordinator_conversation_id": self.conversation_id,
            },
        )
        spawn(self._run_builder(request))
        return {
            "success": True, "status": "builder_started",
            "workflow_id": workflow_id, "workflow_name": workflow_name,
            "builder_conversation_id": builder_conversation_id,
            "note": "The builder runs in the background; build_status reports progress. If it needs something "
                    "from the owner, they receive a WhatsApp message with the link and it lands in this thread.",
        }

    async def _run_builder(self, request) -> None:
        from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

        try:
            await WorkflowBuilderHandler(self.sio).edit_workflow("", request, caller_user_id=self.user_id)
        except Exception:
            logger.error("coordinator builder run failed: %s", request.conversation_id, exc_info=True)

    async def build_status(self, builder_conversation_id: Optional[str] = None) -> Dict[str, Any]:
        repo = ConversationRepo(self.pool)
        rows = await repo.list_by_prefix(
            self.user_id, prefix=f"{BUILDER_CONVERSATION_PREFIX}{self.user_id}:", limit=20,
        )
        if builder_conversation_id:
            rows = [r for r in rows if r["conversation_id"] == builder_conversation_id]
        builds = []
        for row in rows[:5]:
            assistant = [e for e in (row.get("events") or []) if e.get("role") == "assistant"]
            entry: Dict[str, Any] = {
                "builder_conversation_id": row["conversation_id"],
                "workflow_id": row.get("workflow_id"),
                "state": row.get("agent_state") or "running",
                "last_activity": row["last_activity"].isoformat() if row.get("last_activity") else None,
                "latest": bounded((assistant[-1].get("message") if assistant else None), max_chars=800),
            }
            ask = row.get("pending_ask")
            if isinstance(ask, dict) and ask.get("ask_id"):
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
