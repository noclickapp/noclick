"""Dashboard handler — the one aggregate behind the Dashboard tab.

``dashboard:overview`` assembles everything the tab shows in one round trip:
what needs the user (approvals, builder questions, agent proposals, bridge
links, credential requests, dead credentials, broken triggers), runs, agents,
files, credentials, triggers, upcoming runs and notifications. Sections are
gathered concurrently and isolated — one failing query empties its section and
reports under ``errors`` instead of blanking the whole tab. SQL lives in
``repositories/dashboard.py``; this file is composition only. The payload is
camelCase on purpose: it IS the frontend's ``DashboardData`` contract
(``frontend/app/components/dashboard/types.ts``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid as uuid_module
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from nodes.agent.config.providers import WRAPPER_ID_BY_MODEL_TYPE
from repositories.conversation import ConversationRepo
from repositories.credentials import CredentialsRepo
from repositories.dashboard import DashboardRepo
from repositories.feed import FeedRepo
from utils.database_pool import DatabasePoolMixin
from utils.graph_nodes import (
    BUILTIN_TRIGGER_TYPES,
    agent_mark,
    graph_nodes,
    is_trigger_node,
    node_config,
    node_credential_ids,
    node_label,
    node_meta_map,
    node_model,
    node_operation,
    node_type,
    workflow_marks,
)
from wss.receiver.client_events import DashboardNotificationsReadRequest, DashboardOverviewRequest
from wss.schema import SocketIOHandler
from wss.sender import ResponseEvent, send_event

logger = logging.getLogger(__name__)

_DECISION_KINDS = ("approval", "builder_ask", "builder_prompt")
# The node-config `next_run` mirror is written by the reconciler, not on every
# fire, so a value in the past is stale, never "overdue".
_STALE_NEXT_RUN_GRACE_S = 10 * 60
_ARGS_PREVIEW_CHARS = 6000


def _future_iso(value: Any) -> Optional[str]:
    """``value`` as an ISO string when it parses and is not in the past."""
    if not isinstance(value, str) or not value:
        return None
    ts = _ts(value)
    if not ts or ts < datetime.now(timezone.utc).timestamp() - _STALE_NEXT_RUN_GRACE_S:
        return None
    return value
_MAX_TURNS = 20
_MAX_ALARM_WORKFLOWS = 5
_ALARM_FANOUT_TIMEOUT_S = 2.5


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value) if value else None


def _parse_json(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return default
    return value if value is not None else default


class _Workflows:
    """Scoped workflows + their graphs, with the lookups every section needs."""

    def __init__(self, rows: List[Dict[str, Any]]):
        self.rows = rows
        self.by_id: Dict[str, Dict[str, Any]] = {str(r["id"]): r for r in rows}
        self._meta: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._marks: Dict[str, List[str]] = {}

    def add(self, workflow_id: str, name: Optional[str], graph: Any) -> None:
        if workflow_id not in self.by_id:
            self.by_id[workflow_id] = {"id": workflow_id, "name": name, "workflow": graph}

    def ref(self, workflow_id: Any, fallback_name: Optional[str] = None) -> Dict[str, Any]:
        wf_id = str(workflow_id) if workflow_id else ""
        row = self.by_id.get(wf_id)
        if wf_id and wf_id not in self._marks:
            self._marks[wf_id] = workflow_marks(row["workflow"]) if row else []
        return {
            "id": wf_id,
            "name": (row.get("name") if row else None) or fallback_name or "Untitled workflow",
            "marks": self._marks.get(wf_id, []),
        }

    def meta(self, workflow_id: Any) -> Dict[str, Dict[str, Any]]:
        wf_id = str(workflow_id) if workflow_id else ""
        if wf_id not in self._meta:
            row = self.by_id.get(wf_id)
            self._meta[wf_id] = node_meta_map(row["workflow"]) if row else {}
        return self._meta[wf_id]

    def agent_ref(self, workflow_id: Any, node_id: Optional[str], model_hint: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not node_id:
            return None
        m = self.meta(workflow_id).get(str(node_id), {})
        model = model_hint or m.get("model") or ""
        return {"nodeId": str(node_id), "label": m.get("label") or "Agent", "model": model}


class DashboardHandler(DatabasePoolMixin, SocketIOHandler):
    """Composes the Dashboard tab's overview from the existing repositories."""

    def __init__(self, sio):
        super().__init__(sio)

    def get_events(self) -> Dict[str, Callable]:
        return {
            "dashboard:overview": self.handle_overview,
            "dashboard:notifications:read": self.handle_notifications_read,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def _user_and_pool(self, sid: str) -> Tuple[Optional[str], Any]:
        session = await self.sio.get_session(sid)
        user_id = session.get("user_id") if session else None
        pool = await self.get_pool() if user_id else None
        return user_id, pool

    # ------------------------------------------------------------------
    # dashboard:overview
    # ------------------------------------------------------------------

    async def handle_overview(self, sid: str, request: DashboardOverviewRequest) -> None:
        try:
            user_id, pool = await self._user_and_pool(sid)
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id, data=None, error="User not authenticated"))
                return
            if pool is None:
                await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id, data=None, error="Database connection not available"))
                return
            payload = await build_overview(pool, user_id, days=request.days)
            await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id, data=payload))
        except Exception as e:
            logger.error(f"[DashboardHandler] overview failed: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id, data=None, error=str(e)))

    # ------------------------------------------------------------------
    # dashboard:notifications:read
    # ------------------------------------------------------------------

    async def handle_notifications_read(self, sid: str, request: DashboardNotificationsReadRequest) -> None:
        try:
            user_id, pool = await self._user_and_pool(sid)
            if not user_id or pool is None:
                await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id, data=None, error="User not authenticated"))
                return
            updated = await DashboardRepo(pool).mark_notifications_read(user_id, request.ids)
            await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id, data={"updated": updated}))
        except Exception as e:
            logger.error(f"[DashboardHandler] notifications read failed: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id, data=None, error=str(e)))


# ----------------------------------------------------------------------
# Composition — a module-level function so tests can drive it without sockets.
# ----------------------------------------------------------------------

async def build_overview(pool, user_id: str, *, days: int = 14) -> Dict[str, Any]:
    repo = DashboardRepo(pool)
    feed = FeedRepo(pool)
    org_id = await feed.get_primary_org_id(user_id)
    org_uuid = uuid_module.UUID(org_id) if org_id else None

    identity, wf_rows = await asyncio.gather(
        repo.workspace_identity(user_id, org_uuid),
        repo.list_workflows(user_id, org_uuid),
    )
    workflows = _Workflows(wf_rows)
    errors: Dict[str, str] = {}

    async def section(name: str, coro):
        try:
            return await coro
        except Exception as e:  # one bad query must not blank the tab
            logger.warning(f"[DashboardHandler] section {name} failed: {e}", exc_info=True)
            errors[name] = str(e)
            return None

    # Scope is resolved once, in list_workflows; the per-workflow queries take
    # the ids so each stays on its own table's (workflow_id, …) index.
    wf_ids = [str(r["id"]) for r in wf_rows]
    (
        approvals, asks, prompts, bridge_links, cred_requests, credentials,
        runs_window, recent, delayed, webhook_rows, subscription_rows,
        tool_calls, sandboxes, resources, conversations, notifications,
    ) = await asyncio.gather(
        section("approvals", feed.list_approvals(user_id=user_id, org_uuid=org_uuid)),
        section("builder_asks", ConversationRepo(pool).list_pending_asks(user_id, None, limit=50)),
        section("builder_prompts", repo.unanswered_builder_prompts(user_id)),
        section("bridge_links", repo.pending_bridge_links(user_id)),
        section("credential_requests", CredentialsRepo(pool).list_credential_requests(user_id)),
        section("credentials", CredentialsRepo(pool).list_accessible(user_id, org_id)),
        section("runs", repo.runs_window(wf_ids, days=days)),
        section("recent_runs", repo.recent_runs(wf_ids, days=days)),
        section("awaiting_delay", repo.awaiting_delay(wf_ids)),
        section("webhooks", repo.webhook_rows(wf_ids)),
        section("subscriptions", repo.subscription_rows(wf_ids)),
        section("tool_calls", feed.list_tool_calls(user_id=user_id, org_uuid=org_uuid, limit=120)),
        section("sandboxes", _list_sandboxes(user_id)),
        section("resources", repo.resources(wf_ids)),
        section("conversations", repo.agent_conversations(user_id, wf_ids)),
        section("notifications", repo.notifications(user_id)),
    )
    run_days = runs_window["by_day"] if runs_window else None
    by_workflow = runs_window["by_workflow"] if runs_window else None

    # Graphs for workflows referenced by rows but outside the scoped list
    # (shared workflows, since-moved ones) so their marks and labels resolve.
    referenced = set()
    for coll, key in ((recent or [], "workflow_id"), (delayed or [], "workflow_id"), (conversations or [], "workflow_id"), (resources or [], "workflow_id")):
        for row in coll:
            if row.get(key):
                referenced.add(str(row[key]))
    for row in (approvals[0] + approvals[1]) if approvals else []:
        referenced.add(str(row.workflow_id))
    if tool_calls:
        for wf_id, graph in tool_calls[1].items():
            workflows.add(str(wf_id), None, graph)
    missing = [w for w in referenced if w not in workflows.by_id]
    if missing:
        for wf_id, entry in (await section("graphs", repo.workflow_graphs(missing)) or {}).items():
            workflows.add(wf_id, entry["name"], entry["workflow"])
    if tool_calls:
        # list_tool_calls returns graphs without names; name them from the rows.
        for row in tool_calls[0]:
            wf = workflows.by_id.get(str(row.workflow_id) if row.workflow_id else "")
            if wf is not None and not wf.get("name") and row.workflow_name:
                wf["name"] = row.workflow_name

    health = await section("credential_health", _credential_health(pool, credentials or []))
    upcoming_alarms = await section("alarms", _alarm_fanout(workflows))

    triggers, broken_triggers = _compose_triggers(workflows, webhook_rows or [], subscription_rows or [])
    attention = _compose_attention(
        workflows,
        approvals[0] if approvals else [],
        asks or [],
        prompts or [],
        bridge_links or [],
        cred_requests or [],
        credentials or [],
        health or {},
        broken_triggers,
    )
    turns = await _compose_turns(pool, workflows, tool_calls) if tool_calls else []

    return {
        "workspace": {
            "name": "Personal" if identity.get("isPersonal", True) else (identity.get("orgName") or "Workspace"),
            "kind": "personal" if identity.get("isPersonal", True) else "org",
            "userName": identity.get("userName") or "there",
        },
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "attention": attention,
        "resolvedApprovals": [_resolved_approval(workflows, r) for r in (approvals[1] if approvals else [])],
        "runs": {
            "days": run_days or [],
            "byWorkflow": [
                {
                    "workflow": workflows.ref(s["workflow_id"]),
                    "runs": s["runs"],
                    "failed": s["failed"],
                    "lastRunAt": _iso(s["last_run_at"]),
                    "lastStatus": _run_status_bucket(s["last_status"]),
                    "days": s["days"],
                }
                for s in (by_workflow or [])
            ],
            "recent": [_run_row(workflows, r) for r in (recent or [])],
        },
        "agents": {
            "running": _compose_running(workflows, sandboxes or [], conversations or []),
            "turns": turns,
        },
        "files": _compose_files(workflows, resources or []),
        "workspaces": _compose_workspaces(workflows, conversations or []),
        "credentials": _compose_credentials(workflows, credentials or [], health or {}),
        "triggers": triggers,
        "upcoming": _compose_upcoming(workflows, delayed or [], upcoming_alarms or []),
        "notifications": _compose_notifications(workflows, notifications[0] if notifications else []),
        "unreadNotifications": notifications[1] if notifications else 0,
        "errors": errors,
    }


# ----------------------------------------------------------------------
# section helpers
# ----------------------------------------------------------------------

async def _list_sandboxes(user_id: str) -> List[Dict[str, Any]]:
    from utils.capabilities import WARM_SANDBOX_LIST, capability

    lister = capability(WARM_SANDBOX_LIST)
    if lister is None:
        return []
    return list(await lister(user_id=user_id))


async def _credential_health(pool, credentials: List[Any]) -> Dict[str, Any]:
    """Live provider verdicts for connection-backed credentials, bounded so a
    slow provider cannot hold the whole overview. Unknown is never dead."""
    from utils.credential_health import get_credential_health, health_relevant_credential_ids  # noqa: F401

    try:
        return await asyncio.wait_for(get_credential_health(credentials), timeout=3.0)
    except asyncio.TimeoutError:
        return {}


async def _alarm_fanout(workflows: _Workflows) -> List[Dict[str, Any]]:
    """Agent-set alarms live only in the cron scheduler, per workflow. Ask for
    the few workflows that have an alarm node, bounded in count and time."""
    targets: List[Tuple[str, Dict[str, Any]]] = []
    for wf_id, row in workflows.by_id.items():
        nodes = graph_nodes(row.get("workflow"))
        alarm_nodes = [n for n in nodes if node_type(n) == "alarm"]
        if alarm_nodes:
            targets.append((wf_id, {"alarm_ids": {n.get("id") for n in alarm_nodes}, "row": row}))
        if len(targets) >= _MAX_ALARM_WORKFLOWS:
            break
    if not targets:
        return []
    from utils.cron_scheduler_client import list_schedules

    async def one(wf_id: str) -> List[Dict[str, Any]]:
        try:
            schedules = await list_schedules(wf_id, timeout=_ALARM_FANOUT_TIMEOUT_S)
        except Exception:
            return []
        out = []
        for s in schedules or []:
            payload = s.get("payload") if isinstance(s, dict) else None
            payload = _parse_json(payload, {}) if payload is not None else {}
            if not isinstance(payload, dict) or payload.get("source") != "alarm":
                continue
            if not s.get("enabled", True):
                continue
            out.append({
                "workflow_id": wf_id,
                "schedule_id": s.get("id"),
                "agent_node_id": payload.get("agent_node_id"),
                "alarm_node_id": payload.get("alarm_node_id"),
                "message": payload.get("message") or "Alarm",
                "next_run": s.get("next_run_at"),
                "recurring": s.get("cron_expression") not in (None, "__run_at__"),
                "cron_expression": s.get("cron_expression"),
            })
        return out

    try:
        results = await asyncio.wait_for(asyncio.gather(*[one(wf_id) for wf_id, _ in targets]), timeout=_ALARM_FANOUT_TIMEOUT_S + 0.5)
    except asyncio.TimeoutError:
        return []
    return [item for group in results for item in group]


def _run_status_bucket(status: Optional[str]) -> str:
    if status == "error":
        return "failed"
    if status == "running":
        return "running"
    return "ok"


def _run_row(workflows: _Workflows, r: Dict[str, Any]) -> Dict[str, Any]:
    started = r.get("started_at")
    finished = r.get("finished_at")
    duration_ms = None
    if isinstance(started, datetime) and isinstance(finished, datetime):
        duration_ms = int((finished - started).total_seconds() * 1000)
    return {
        "id": str(r["id"]),
        "workflow": workflows.ref(r["workflow_id"]),
        "status": r.get("status") or "completed",
        "startedAt": _iso(started),
        "durationMs": duration_ms,
        "trigger": r.get("trigger_source") or "manual",
        "nodesExecuted": int(r.get("nodes_executed") or 0),
        "error": r.get("error") or None,
    }


def _field_type(raw: Any) -> str:
    return raw if raw in ("string", "number", "boolean", "select", "list", "text") else "string"


def _approval_fields(row: Any) -> List[Dict[str, Any]]:
    content = _parse_json(row.content, {}) or {}
    values = content.get("values") or {}
    fields = []
    for f in content.get("fields") or []:
        if not isinstance(f, dict) or not f.get("name"):
            continue
        fields.append({
            "name": f["name"],
            "type": _field_type(f.get("type")),
            "label": f.get("label") or f["name"],
            "description": f.get("description"),
            "options": f.get("options"),
            "value": values.get(f["name"], f.get("default")),
        })
    return fields


def _resolved_approval(workflows: _Workflows, row: Any) -> Dict[str, Any]:
    return {
        "id": str(row.id),
        "title": row.title or "Approval",
        "workflow": workflows.ref(row.workflow_id, row.workflow_name),
        "status": row.status,
        "decidedAt": _iso(row.decided_at),
        "decidedByEmail": row.decided_by_email,
        "createdAt": _iso(row.created_at),
    }


def _compose_attention(
    workflows: _Workflows,
    pending_approvals: List[Any],
    asks: List[Dict[str, Any]],
    prompts: List[Dict[str, Any]],
    bridge_links: List[Dict[str, Any]],
    cred_requests: List[Any],
    credentials: List[Any],
    health: Dict[str, Any],
    broken_triggers: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    for row in pending_approvals:
        items.append({
            "id": f"approval:{row.id}",
            "kind": "approval",
            "title": row.title or "Approval required",
            "workflow": workflows.ref(row.workflow_id, row.workflow_name),
            "createdAt": _iso(row.created_at),
            "fields": _approval_fields(row),
            "meta": {"approvalId": str(row.id), "executionId": str(row.execution_id), "nodeId": row.node_id},
        })

    for ask in asks:
        pending = _parse_json(ask.get("pending_ask"), {}) or {}
        inputs = [i for i in (pending.get("inputs") or []) if isinstance(i, dict)]
        first = inputs[0] if inputs else {}
        choices = None
        fields = None
        if len(inputs) == 1 and isinstance(first.get("options"), list) and first["options"]:
            choices = [str(o) for o in first["options"]]
        else:
            fields = [
                {
                    "name": str(i.get("id") or i.get("fieldKey") or idx),
                    "type": "select" if isinstance(i.get("options"), list) and i["options"] else _field_type(i.get("type")),
                    "label": i.get("label") or "Answer",
                    "description": i.get("description"),
                    "options": i.get("options"),
                    "value": i.get("defaultValue"),
                }
                for idx, i in enumerate(inputs)
            ]
        cred_inputs = [i for i in inputs if i.get("type") == "credential"]
        items.append({
            "id": f"ask:{ask['conversation_id']}",
            "kind": "builder_ask",
            "title": pending.get("title") or first.get("label") or "The builder has a question",
            "detail": first.get("description") if len(inputs) == 1 else None,
            "workflow": workflows.ref(ask.get("workflow_id")),
            "createdAt": _iso(ask.get("last_activity")),
            "choices": choices,
            "fields": fields,
            # A credential ask shows the provider it wants connected.
            "credentialType": (cred_inputs[0].get("credentialType") or cred_inputs[0].get("credential_type")) if cred_inputs else None,
            "provider": cred_inputs[0].get("nodeType") if cred_inputs else None,
            # The builder's own input requests, verbatim — the product answers
            # them with the same wizard the builder chat uses.
            "inputs": inputs,
            "meta": {"conversationId": ask["conversation_id"], "askId": pending.get("ask_id"), "workflowId": ask.get("workflow_id")},
        })

    for p in prompts:
        wf_id = p.get("workflow_id")
        prompt = (p.get("prompt") or "").strip()
        items.append({
            "id": f"proposal:{p['conversation_id']}:{p['proposal_id']}",
            "kind": "builder_prompt",
            "title": prompt[:140] if prompt else "Agent proposed a change",
            "detail": prompt if len(prompt) > 140 else None,
            "workflow": workflows.ref(wf_id),
            "from": workflows.agent_ref(wf_id, p.get("node_id")),
            "createdAt": p.get("created_at") or _iso(p.get("last_activity")),
            "meta": {
                "conversationId": p["conversation_id"],
                "proposalId": p["proposal_id"],
                "nodeId": p.get("prompt_node_id") or p.get("node_id"),
                "anchoredPrompt": p.get("anchored_prompt") or prompt,
            },
        })

    for link in bridge_links:
        inputs = [i for i in (_parse_json(link.get("inputs"), []) or []) if isinstance(i, dict)]
        cred_inputs = [i for i in inputs if i.get("type") == "credential"]
        labels = [i.get("label") for i in (cred_inputs or inputs) if i.get("label")]
        title = labels[0] if len(labels) == 1 else ("Connect " + ", ".join(l.replace("Connect ", "") for l in labels) if labels else "Finish setting up")
        items.append({
            "id": f"bridge:{link['id']}",
            "kind": "bridge_link",
            "title": title,
            "detail": "Only a human can connect the account — anyone with the link can, no account needed." if cred_inputs else "The builder needs answers before it can finish.",
            "workflow": workflows.ref(link.get("workflow_id"), link.get("workflow_name")),
            "from": workflows.agent_ref(link.get("workflow_id"), link.get("agent_node_id")),
            "link": f"/b/{link['id']}",
            "credentialType": (cred_inputs[0].get("credential_type") or cred_inputs[0].get("credentialType")) if cred_inputs else None,
            "createdAt": _iso(link.get("created_at")),
            "meta": {"linkId": str(link["id"]), "expiresAt": _iso(link.get("expires_at"))},
        })

    now = datetime.now(timezone.utc)
    for req in cred_requests:
        if req.status != "pending" or (req.expires_at and req.expires_at.replace(tzinfo=req.expires_at.tzinfo or timezone.utc) < now):
            continue
        items.append({
            "id": f"credreq:{req.id}",
            "kind": "credential_request",
            "title": f"Credential requested from {req.target_email}",
            "detail": req.message or None,
            "workflow": {"id": "", "name": "Credentials", "marks": []},
            "credentialType": req.credential_type,
            "createdAt": _iso(req.created_at),
            "meta": {"requestId": str(req.id), "expiresAt": _iso(req.expires_at)},
        })

    used_by = _credential_usage(workflows)
    for c in credentials:
        verdict = health.get(str(c.id))
        dead_status = verdict.status if verdict is not None and not verdict.healthy else None
        if not c.revoked_at and not dead_status:
            continue
        wf_refs = used_by.get(str(c.id), [])
        items.append({
            "id": f"cred:{c.id}",
            "kind": "credential_dead",
            "title": f"{c.name} {'was revoked' if c.revoked_at else 'is disconnected'}",
            "detail": (verdict.hint if verdict is not None and verdict.hint else None) or ("Refreshing the token was rejected by the provider — reconnect to restore it." if c.revoked_at else "The session is no longer connected."),
            "workflow": wf_refs[0] if wf_refs else {"id": "", "name": "Credentials", "marks": []},
            "credentialType": c.credential_type,
            "createdAt": _iso(c.revoked_at or c.updated_at),
            "meta": {"credentialId": str(c.id), "status": dead_status or "revoked", "usedBy": wf_refs},
        })

    items.extend(broken_triggers)

    def sort_key(item: Dict[str, Any]):
        return (0 if item["kind"] in _DECISION_KINDS else 1, -(_ts(item.get("createdAt"))))

    items.sort(key=sort_key)
    return items


def _ts(iso: Optional[str]) -> float:
    if not iso:
        return 0.0
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _credential_usage(workflows: _Workflows) -> Dict[str, List[Dict[str, Any]]]:
    used: Dict[str, List[Dict[str, Any]]] = {}
    for wf_id, row in workflows.by_id.items():
        seen = set()
        for node in graph_nodes(row.get("workflow")):
            for cred_id in node_credential_ids(node):
                if cred_id in seen:
                    continue
                seen.add(cred_id)
                used.setdefault(cred_id, []).append(workflows.ref(wf_id))
    return used


def _compose_credentials(workflows: _Workflows, credentials: List[Any], health: Dict[str, Any]) -> List[Dict[str, Any]]:
    used_by = _credential_usage(workflows)
    out = []
    for c in credentials:
        verdict = health.get(str(c.id))
        if c.revoked_at:
            state, detail = "revoked", "Refresh rejected — reconnect"
        elif verdict is not None and not verdict.healthy:
            state, detail = "disconnected", verdict.hint or verdict.status
        else:
            state, detail = "ok", None
        out.append({
            "id": str(c.id),
            "name": c.name,
            "credentialType": c.credential_type,
            "access": c.access_type,
            "health": state,
            "healthDetail": detail,
            "createdAt": _iso(c.created_at),
            "usedBy": used_by.get(str(c.id), []),
        })
    dead_first = sorted(out, key=lambda x: (0 if x["health"] != "ok" else 1, x["name"].lower()))
    return dead_first


def _trigger_kind(ntype: str, operation: Optional[str]) -> Optional[str]:
    if ntype == "trigger-cron":
        return "schedule"
    if ntype == "trigger-webhook":
        return "webhook"
    if ntype == "trigger-email":
        return "email"
    if ntype in ("interface-form", "trigger-form-input", "interface-config-form"):
        return "form"
    if ntype == "trigger-run" or ntype in BUILTIN_TRIGGER_TYPES:
        return None
    if not operation:
        return None
    from nodes.agent.node_op_tools import is_trigger_operation

    if not is_trigger_operation(ntype, operation):
        return None
    try:
        from nodes.core.registry import NODE_REGISTRY
        from nodes.core.schedule_registration import CronScheduleTriggerMixin
        from nodes.core.webhook_subscriptions import AppEventTriggerMixin

        cls = NODE_REGISTRY.get(ntype)
        if isinstance(cls, type):
            if issubclass(cls, AppEventTriggerMixin):
                return "app_event"
            if issubclass(cls, CronScheduleTriggerMixin):
                return "poll"
    except Exception:
        pass
    return "webhook"


def _compose_triggers(workflows: _Workflows, webhook_rows: List[Dict[str, Any]], subscription_rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    hooks = {(str(r["workflow_id"]), str(r["node_id"])): r for r in webhook_rows}
    subs: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for r in subscription_rows:
        subs.setdefault((str(r["workflow_id"]), str(r["node_id"])), []).append(r)

    triggers: List[Dict[str, Any]] = []
    broken: List[Dict[str, Any]] = []
    for wf_id, row in workflows.by_id.items():
        if wf_id not in {str(r["id"]) for r in workflows.rows}:
            continue  # only the scoped list, not graphs pulled in for labels
        for node in graph_nodes(row.get("workflow")):
            ntype = node_type(node)
            op = node_operation(node)
            kind = _trigger_kind(ntype, op)
            if not kind:
                continue
            cfg = node_config(node)
            if cfg.get("disabled") is True:
                continue
            node_id = str(node.get("id") or "")
            hook = hooks.get((wf_id, node_id))
            node_subs = subs.get((wf_id, node_id), [])
            mirror_registered = cfg.get("trigger_registered")
            mirror_error = cfg.get("trigger_error") or None
            if kind in ("schedule", "poll"):
                armed = bool(mirror_registered) or bool(cfg.get("next_run"))
                error = mirror_error if not armed else None
            elif kind == "app_event":
                armed = bool(node_subs)
                error = mirror_error if not armed else None
            elif kind in ("form", "email"):
                armed = True
                error = None
            else:  # webhook (built-in or provider)
                armed = bool(hook and hook.get("is_active"))
                error = mirror_error if not armed else ("Registration was torn down" if hook and hook.get("registered_operation") and not hook.get("is_active") else None)
            label = node_label(node) or (op.replace("_", " ") if op else kind.title())
            entry = {
                "id": f"{wf_id}:{node_id}",
                "workflow": workflows.ref(wf_id),
                "nodeType": ntype,
                "nodeId": node_id,
                "label": label,
                "kind": kind,
                "armed": armed,
                "error": error,
                "schedule": None,
                "nextRunAt": _future_iso(cfg.get("next_run")) if kind in ("schedule", "poll") else None,
                "lastFiredAt": _iso(hook.get("last_triggered_at")) if hook else None,
                "fireCount": int(hook.get("trigger_count") or 0) if hook else 0,
            }
            triggers.append(entry)
            if not armed and error:
                broken.append({
                    "id": f"trigger:{wf_id}:{node_id}",
                    "kind": "trigger_broken",
                    "title": f"{label} is not registered",
                    "detail": error,
                    "workflow": workflows.ref(wf_id),
                    "provider": ntype,
                    "createdAt": _iso(row.get("updated_at")),
                    "meta": {"nodeId": node_id},
                })
    triggers.sort(key=lambda t: (t["armed"], t["workflow"]["name"].lower()))
    return triggers, broken


def _compose_upcoming(workflows: _Workflows, delayed: List[Dict[str, Any]], alarms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    scoped_ids = {str(r["id"]) for r in workflows.rows}
    for wf_id in scoped_ids:
        row = workflows.by_id[wf_id]
        meta = workflows.meta(wf_id)
        agent_ref = None
        for node in graph_nodes(row.get("workflow")):
            if node_type(node) == "agent":
                agent_ref = workflows.agent_ref(wf_id, node.get("id"))
                break
        for node in graph_nodes(row.get("workflow")):
            ntype = node_type(node)
            kind = _trigger_kind(ntype, node_operation(node))
            if kind not in ("schedule", "poll"):
                continue
            cfg = node_config(node)
            if cfg.get("disabled") is True:
                continue
            next_run = _future_iso(cfg.get("next_run"))
            error = cfg.get("trigger_error") or None
            if not next_run and not error:
                continue
            out.append({
                "id": f"schedule:{wf_id}:{node.get('id')}",
                "kind": "schedule",
                "at": next_run,
                "workflow": workflows.ref(wf_id),
                "label": node_label(node) or row.get("name") or "Schedule",
                "agent": agent_ref,
                "nodeType": ntype,
                "recurrence": None,
                "error": error if not next_run else None,
            })
        _ = meta
    for a in alarms:
        wf_id = a["workflow_id"]
        out.append({
            "id": f"alarm:{a.get('schedule_id')}",
            "kind": "alarm",
            "at": a.get("next_run"),
            "workflow": workflows.ref(wf_id),
            "label": a.get("message") or "Alarm",
            "agent": workflows.agent_ref(wf_id, a.get("agent_node_id")),
            "nodeType": "alarm",
            "recurrence": a.get("cron_expression") if a.get("recurring") else None,
        })
    for d in delayed:
        wf_id = str(d["workflow_id"])
        target = workflows.meta(wf_id).get(str(d.get("resume_node_id") or ""), {})
        out.append({
            "id": f"resume:{d['id']}",
            "kind": "resume",
            "at": _iso(d.get("wake_at")),
            "workflow": workflows.ref(wf_id),
            "label": f"Resumes at {target.get('label') or 'the next step'}",
            "nodeType": target.get("type") or "trigger-cron",
            "recurrence": None,
        })
    out.sort(key=lambda u: (_ts(u.get("at")) if u.get("at") else float("inf")))
    return out


def _compose_running(workflows: _Workflows, sandboxes: List[Dict[str, Any]], conversations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    latest_title: Dict[Tuple[str, str], str] = {}
    for c in conversations:
        key = (str(c.get("workflow_id") or ""), str(c.get("node_id") or ""))
        latest_title.setdefault(key, c.get("title") or "")
    out = []
    for s in sandboxes:
        wf_id = str(s.get("workflow_id") or "")
        node_id = str(s.get("node_id") or "")
        slug = WRAPPER_ID_BY_MODEL_TYPE.get(str(s.get("model_type") or ""), str(s.get("model_type") or ""))
        agent = workflows.agent_ref(wf_id, node_id, model_hint=slug) or {"nodeId": node_id, "label": "Agent", "model": slug}
        out.append({
            "workflow": workflows.ref(wf_id),
            "agent": agent,
            "conversationTitle": latest_title.get((wf_id, node_id), ""),
            "busy": bool(s.get("busy", False)),
            "since": _iso(datetime.now(timezone.utc)) if not s.get("uptime") else _iso(datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - float(s["uptime"]), tz=timezone.utc)),
        })
    return out


def _humanize_tool(tool_name: Optional[str]) -> str:
    return (tool_name or "tool").replace("__", " · ").replace("_", " ")


def _provider_type_from_tool(tool_name: Optional[str]) -> Optional[str]:
    """`whatsapp__send_text_message` → `automation-whatsapp`, when the provider
    node is gone from the graph (renamed/deleted since the call was recorded)."""
    if not tool_name or "__" not in tool_name:
        return None
    slug = tool_name.split("__", 1)[0]
    slug = slug.rsplit("_", 1)[0] if slug.rsplit("_", 1)[-1].isdigit() else slug  # dedup suffix
    try:
        from nodes.core.registry import NODE_REGISTRY
    except Exception:
        return None
    for candidate in (f"automation-{slug}", f"automation-{slug.replace('_', '-')}"):
        if candidate in NODE_REGISTRY:
            return candidate
    return None


def _args_for_wire(arguments: Any) -> Any:
    """Tool arguments for the inspector, bounded so one giant payload can't
    bloat the overview."""
    args = _parse_json(arguments, None)
    if args is None:
        return None
    try:
        text = json.dumps(args)
    except (TypeError, ValueError):
        return None
    if len(text) <= _ARGS_PREVIEW_CHARS:
        return args
    return {"_truncated": True, "preview": text[:_ARGS_PREVIEW_CHARS]}


async def _compose_turns(pool, workflows: _Workflows, tool_calls: Tuple[List[Any], Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows, _graphs = tool_calls
    groups: Dict[str, List[Any]] = {}
    order: List[str] = []
    for row in rows:
        key = str(row.execution_id or row.conversation_id or row.id)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    order = order[:_MAX_TURNS]

    # The agent's closing words per run come from the CAS, keyed (execution, agent node).
    responses: Dict[str, str] = {}
    keys = []
    for key in order:
        head = groups[key][0]
        if head.execution_id and head.agent_node_id:
            keys.append((key, str(head.execution_id), head.agent_node_id, str(head.workflow_id) if head.workflow_id else None))
    if keys:
        from utils.cas import store as cas_store

        async def resolve(key, ex_id, node_id, wf_id):
            try:
                out = await cas_store.read_node_output(pool, execution_id=ex_id, node_id=node_id, workflow_id=wf_id)
            except Exception:
                return None
            if isinstance(out, dict):
                text = out.get("response")
                if isinstance(text, str) and text.strip():
                    return key, text.strip()[:2000]
            return None

        for resolved in await asyncio.gather(*[resolve(*k) for k in keys]):
            if resolved:
                responses[resolved[0]] = resolved[1]

    turns = []
    for key in order:
        calls = sorted(groups[key], key=lambda r: r.created_at)
        head = calls[0]
        wf_id = str(head.workflow_id) if head.workflow_id else ""
        meta = workflows.meta(wf_id).get(head.agent_node_id or "", {})
        started = calls[0].created_at
        ended = calls[-1].created_at
        failed = any(c.result_status == "error" for c in calls)
        turns.append({
            "id": key,
            "executionId": str(head.execution_id) if head.execution_id else None,
            "conversationId": head.conversation_id,
            "workflow": workflows.ref(wf_id, head.workflow_name),
            "agent": {"nodeId": head.agent_node_id or "", "label": meta.get("label") or "Agent", "model": head.model or meta.get("model") or ""},
            "conversationTitle": "",
            "startedAt": _iso(started),
            "durationMs": int((ended - started).total_seconds() * 1000) + int(calls[-1].duration_ms or 0),
            "trigger": "agent_turn",
            "toolCalls": [
                {
                    "tool": c.tool_name or "",
                    "providerType": (
                        workflows.meta(wf_id).get(c.provider_node_id or "", {}).get("type")
                        or _provider_type_from_tool(c.tool_name)
                        or agent_mark(head.model or "")
                    ),
                    "operation": c.operation or "",
                    "status": "error" if c.result_status == "error" else "success",
                    "durationMs": int(c.duration_ms or 0),
                    "detail": _call_detail(c.arguments),
                    "error": c.error or None,
                    "arguments": _args_for_wire(c.arguments),
                    "result": (c.result_preview or None),
                    "at": _iso(c.created_at),
                }
                for c in calls
            ],
            "response": responses.get(key, ""),
            "status": "error" if failed else "ok",
        })
    return turns


def _call_detail(arguments: Any) -> Optional[str]:
    args = _parse_json(arguments, None)
    if not isinstance(args, dict):
        return None
    for key in ("channel", "to", "recipient", "chat_id", "chatId", "repo", "title", "query", "name", "path", "command"):
        val = args.get(key)
        if isinstance(val, (str, int)) and str(val).strip():
            return str(val)[:80]
    return None


def _file_kind(mime: Optional[str], resource_type: Optional[str], name: str) -> str:
    mime = (mime or "").lower()
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if mime.startswith("image/") or resource_type == "image" or ext in ("png", "jpg", "jpeg", "gif", "webp", "svg"):
        return "image"
    if resource_type == "dataset" or ext in ("csv", "tsv", "xlsx", "json", "parquet"):
        return "data"
    if ext in ("py", "js", "ts", "tsx", "sh", "sql", "yaml", "yml", "toml"):
        return "code"
    if ext in ("zip", "tar", "gz", "7z"):
        return "archive"
    if resource_type == "document" or mime.startswith("text/") or ext in ("pdf", "md", "txt", "doc", "docx"):
        return "doc"
    return "other"


def _resource_url(storage_ref: Optional[str]) -> Optional[str]:
    if not storage_ref:
        return None
    try:
        from utils.r2_cloudflare import get_public_download_url

        return get_public_download_url(storage_ref)
    except Exception:
        return None


def _compose_files(workflows: _Workflows, resources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_wf: Dict[str, List[Dict[str, Any]]] = {}
    for r in resources:
        by_wf.setdefault(str(r["workflow_id"]), []).append(r)
    out = []
    for wf_id, rows in by_wf.items():
        ref = workflows.ref(wf_id)
        out.append({
            "id": f"resources:{wf_id}",
            "kind": "resources",
            # Uploads and deletes go through the resource events, which gate on
            # workflow access themselves.
            "writable": True,
            "label": ref["name"],
            "sublabel": "Uploads & outputs",
            "workflow": ref,
            "files": [
                {
                    "path": r.get("name") or "file",
                    "size": int(r.get("size_bytes") or 0),
                    "mtime": _iso(r.get("updated_at") or r.get("created_at")),
                    "kind": _file_kind(r.get("mime_type"), r.get("resource_type"), r.get("name") or ""),
                    "resourceId": str(r["id"]),
                    "resourceType": r.get("resource_type"),
                    "mime": r.get("mime_type"),
                    "url": _resource_url(r.get("storage_ref")),
                    "rows": (_parse_json(r.get("metadata"), {}) or {}).get("row_count") if r.get("resource_type") == "dataset" else None,
                }
                for r in rows
            ],
        })
    return out


def _compose_workspaces(workflows: _Workflows, conversations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Agent conversations whose durable /workspace volume the Files view can
    list lazily (each listing is a Modal call, so the overview only names them)."""
    out = []
    for c in conversations:
        conv_id = str(c.get("conversation_id") or "")
        wf_id = str(c.get("workflow_id") or "")
        node_id = str(c.get("node_id") or "")
        ck = None
        if conv_id.startswith("ck:"):
            parts = conv_id.split(":", 3)
            if len(parts) == 4:
                wf_id = wf_id or parts[1]
                node_id = node_id or parts[2]
                ck = parts[3]
        if not wf_id or not node_id or not ck or ck.startswith("share:"):
            continue
        out.append({
            "id": f"workspace:{conv_id}",
            "workflow": workflows.ref(wf_id),
            "agent": workflows.agent_ref(wf_id, node_id, model_hint=c.get("agent_model")) or {"nodeId": node_id, "label": "Agent", "model": c.get("agent_model") or ""},
            "conversationKey": ck,
            "conversationTitle": (c.get("title") or "")[:60].rstrip() + ("…" if len(c.get("title") or "") > 60 else ""),
            "lastActivity": _iso(c.get("last_activity")),
        })
    return out


def _compose_notifications(workflows: _Workflows, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        meta = _parse_json(r.get("metadata"), {}) or {}
        wf_id = meta.get("workflow_id") if isinstance(meta, dict) else None
        out.append({
            "id": str(r["id"]),
            "category": r.get("category") or "run_failure",
            "title": r.get("title") or "",
            "body": r.get("body") or "",
            "createdAt": _iso(r.get("created_at")),
            "readAt": _iso(r.get("read_at")),
            "suppressedCount": int(r.get("suppressed_count") or 0),
            "workflow": workflows.ref(wf_id) if wf_id else None,
            "ctaUrl": r.get("cta_url"),
        })
    return out


__all__ = ["DashboardHandler", "build_overview"]
