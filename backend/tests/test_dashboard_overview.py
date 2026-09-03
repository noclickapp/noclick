"""Dashboard tab aggregate: the repository's SQL against a real Postgres and the
handler's composition (marks, attention ordering, per-section error isolation).

Run: ``pytest tests/test_dashboard_overview.py`` (DB tests need Docker for the
testcontainers Postgres, like every ``real_database`` test).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from tests.fixtures.real_db_fixture import real_database  # noqa: F401 — fixture
from utils.graph_nodes import node_meta_map, workflow_marks
from wss.handlers import dashboard_handler as dh
from repositories.dashboard import DashboardRepo

def _fresh_user() -> str:
    """Each DB test gets its own user: the Postgres container is session-scoped,
    so rows from earlier tests are still there."""
    return str(uuid.uuid4())


USER = "6b2f4c8e-1d3a-4f7b-9c2e-5a8d7e6f4b21"  # composition tests only (no DB)


# ----------------------------------------------------------------------
# graph_nodes — both stored shapes
# ----------------------------------------------------------------------

SAVE_SHAPE = {
    "nodes": [
        {"id": "cron", "type": "trigger-cron", "config": {"label": "Daily", "next_run": "2030-01-01T02:30:00Z", "trigger_registered": True}},
        {"id": "agent1", "type": "agent", "config": {"label": "Enricher", "model": "codex", "credentialIds": {"openai": "cred-openai"}}},
        {"id": "hub", "type": "automation-hubspot", "config": {"label": "HubSpot", "operation": "list_contacts", "credentialIds": {"hubspot_oauth": "cred-hub"}}},
        {"id": "note", "type": "sticky-note", "config": {}},
    ]
}
CANVAS_SHAPE = {
    "nodes": [
        {"id": "wa", "type": "automation-whatsapp", "data": {"label": "WhatsApp", "operation": "on_message", "config": {}}},
        {"id": "agent2", "type": "agent", "data": {"label": "Sales Agent", "config": {"model": "claude-code"}}},
    ]
}


def test_marks_put_triggers_then_agents_with_harness_first_and_skip_notes():
    assert workflow_marks(SAVE_SHAPE) == ["trigger-cron", "agent:codex", "automation-hubspot"]


def test_marks_and_meta_read_the_canvas_shape_too():
    marks = workflow_marks(CANVAS_SHAPE)
    assert "agent:claude-code" in marks and "automation-whatsapp" in marks
    meta = node_meta_map(CANVAS_SHAPE)
    assert meta["agent2"]["label"] == "Sales Agent" and meta["agent2"]["model"] == "claude-code"
    assert meta["wa"]["operation"] == "on_message"


def test_marks_tolerate_string_and_empty_blobs():
    assert workflow_marks(json.dumps(SAVE_SHAPE))[0] == "trigger-cron"
    assert workflow_marks({}) == [] and workflow_marks("not json") == []


# ----------------------------------------------------------------------
# repository — real Postgres
# ----------------------------------------------------------------------

async def _seed(db, user):
    """A user, their (auto-created) personal-workspace org, one workflow with
    runs / a delayed run / a webhook row / two notifications. Returns
    (workflow_id, org_uuid) — the org is what production scopes on."""
    await db.execute("INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING", user, f"dash-{user[:8]}@example.com")
    org_id = await db.fetchval("SELECT organization_id FROM organization_members WHERE user_id = $1 AND is_primary = true", uuid.UUID(user))
    wf = await db.fetchrow(
        "INSERT INTO workflows (owner_id, name, workflow, organization_id) VALUES ($1, $2, ($3::text)::jsonb, $4) RETURNING id",
        user, "Lead enrichment", json.dumps(SAVE_SHAPE), org_id,
    )
    wf_id = wf["id"]
    USER = user  # noqa: N806 — the seed rows below key on this user
    now = datetime.now(timezone.utc)
    for offset_days, status in ((0, "completed"), (0, "error"), (1, "completed"), (13, "completed"), (20, "completed")):
        await db.execute(
            "INSERT INTO workflow_executions (workflow_id, user_id, status, started_at, finished_at, trigger_source) VALUES ($1, $2, $3, $4, $5, 'cron')",
            wf_id, USER, status, now - timedelta(days=offset_days, minutes=5), now - timedelta(days=offset_days, minutes=4),
        )
    await db.execute(
        "INSERT INTO workflow_executions (workflow_id, user_id, status, started_at, wake_at, resume_node_id) VALUES ($1, $2, 'awaiting_delay', $3, $4, 'hub')",
        wf_id, USER, now - timedelta(hours=1), now + timedelta(hours=6),
    )
    await db.execute(
        "INSERT INTO webhooks (user_id, workflow_id, node_id, is_active, registered_operation, trigger_count, last_triggered_at) VALUES ($1, $2, 'hub', true, 'list_contacts', 7, $3)",
        USER, wf_id, now - timedelta(hours=2),
    )
    for i, read in enumerate((None, now)):
        await db.execute(
            "INSERT INTO user_notifications (user_id, category, title, body, read_at, metadata) VALUES ($1, 'run_failure', $2, 'x', $3, ($4::text)::jsonb)",
            USER, f"Failure {i}", read, json.dumps({"workflow_id": str(wf_id)}),
        )
    return str(wf_id), org_id


@pytest.mark.asyncio
async def test_repo_runs_are_zero_filled_and_scoped(real_database):
    user = _fresh_user()
    wf_id, org = await _seed(real_database, user)
    repo = DashboardRepo(real_database.pool)

    window = await repo.runs_window([wf_id], days=14)
    days = window["by_day"]
    assert len(days) == 14
    # 3 completed + the parked (awaiting_delay) run count as non-failures; the 20-day-old run is outside the window.
    assert sum(d["ok"] for d in days) == 4 and sum(d["failed"] for d in days) == 1
    assert days[-1]["failed"] == 1 and days[-1]["ok"] == 2

    by_wf = window["by_workflow"]
    assert [s["workflow_id"] for s in by_wf] == [wf_id]
    assert by_wf[0]["runs"] == 5 and by_wf[0]["failed"] == 1 and len(by_wf[0]["days"]) == 14

    # Recent runs are the window's runs (the chart and the list agree), so the
    # 20-day-old run is not listed.
    recent = await repo.recent_runs([wf_id], days=14, limit=10)
    assert {r["status"] for r in recent[:3]} == {"completed", "error", "awaiting_delay"}, "newest first"
    assert all(str(r["workflow_id"]) == wf_id for r in recent) and len(recent) == 5

    delayed = await repo.awaiting_delay([wf_id])
    assert len(delayed) == 1 and delayed[0]["resume_node_id"] == "hub"

    # No workflows in scope → an empty, zero-filled window and no rows.
    assert (await repo.runs_window([], days=14))["by_day"] == [{"date": d["date"], "ok": 0, "failed": 0} for d in days]
    assert await repo.recent_runs([]) == [] and await repo.webhook_rows([]) == []


@pytest.mark.asyncio
async def test_repo_webhooks_notifications_and_mark_read(real_database):
    user = _fresh_user()
    wf_id, org = await _seed(real_database, user)
    repo = DashboardRepo(real_database.pool)

    hooks = await repo.webhook_rows([wf_id])
    assert [(str(h["workflow_id"]), h["node_id"], h["trigger_count"]) for h in hooks] == [(wf_id, "hub", 7)]

    rows, unread = await repo.notifications(user)
    assert len(rows) == 2 and unread == 1
    updated = await repo.mark_notifications_read(user, None)
    assert updated == 1
    _, unread_after = await repo.notifications(user)
    assert unread_after == 0

    # Another user's ids are not marked through this user's session.
    assert await repo.mark_notifications_read(str(uuid.uuid4()), [rows[0]["id"]]) == 0


@pytest.mark.asyncio
async def test_repo_list_workflows_and_identity(real_database):
    user = _fresh_user()
    wf_id, org = await _seed(real_database, user)
    repo = DashboardRepo(real_database.pool)
    rows = await repo.list_workflows(user, org)
    assert [str(r["id"]) for r in rows] == [wf_id]
    identity = await repo.workspace_identity(user, org)
    assert identity["userName"] == f"dash-{user[:8]}"
    # A personal-workspace org (auto-created on signup) still reads as personal.
    assert identity["isPersonal"] is (org is not None) or identity["isPersonal"] is True


@pytest.mark.asyncio
async def test_build_overview_end_to_end(real_database):
    """The full composition over a seeded database: sections present, the
    schedule mirror becomes an upcoming run, the delayed run resumes, the
    webhook row arms the HubSpot trigger, notifications count unread."""
    user = _fresh_user()
    wf_id, _org = await _seed(real_database, user)
    payload = await dh.build_overview(real_database.pool, user, days=14)

    assert payload["workspace"]["userName"] == f"dash-{user[:8]}" and payload["workspace"]["kind"] == "personal"
    assert payload["errors"] == {}, payload["errors"]

    runs = payload["runs"]
    assert len(runs["days"]) == 14 and runs["days"][-1]["failed"] == 1
    assert runs["byWorkflow"][0]["workflow"] == {"id": wf_id, "name": "Lead enrichment", "marks": ["trigger-cron", "agent:codex", "automation-hubspot"]}
    assert {r["status"] for r in runs["recent"][:3]} == {"completed", "error", "awaiting_delay"}

    kinds = {u["kind"] for u in payload["upcoming"]}
    assert kinds == {"schedule", "resume"}
    schedule = next(u for u in payload["upcoming"] if u["kind"] == "schedule")
    assert schedule["at"] == "2030-01-01T02:30:00Z" and schedule["agent"]["model"] == "codex"
    resume = next(u for u in payload["upcoming"] if u["kind"] == "resume")
    assert resume["label"] == "Resumes at HubSpot"

    triggers = {t["nodeId"]: t for t in payload["triggers"]}
    assert triggers["cron"]["armed"] is True and triggers["cron"]["kind"] == "schedule"
    assert "hub" not in triggers, "a plain action operation (list_contacts) is not a trigger, webhook row or not"

    assert payload["unreadNotifications"] == 1 and len(payload["notifications"]) == 2
    assert payload["attention"] == []


# ----------------------------------------------------------------------
# handler composition — no database
# ----------------------------------------------------------------------

def _wf(wf_id="wf-1", name="Lead enrichment", graph=SAVE_SHAPE):
    return dh._Workflows([{"id": wf_id, "name": name, "workflow": graph, "updated_at": datetime(2026, 9, 2, tzinfo=timezone.utc)}])


def test_attention_orders_decisions_before_fixes_and_shapes_each_kind():
    workflows = _wf()
    approval = SimpleNamespace(
        id="ap1", workflow_id="wf-1", execution_id="ex1", node_id="approve", title="Send outreach",
        content=json.dumps({"fields": [{"name": "subject", "type": "string", "label": "Subject"}], "values": {"subject": "Hi"}}),
        created_at=datetime(2026, 9, 2, 5, tzinfo=timezone.utc), workflow_name="Lead enrichment",
    )
    ask = {"conversation_id": "conv-1", "workflow_id": "wf-1", "last_activity": datetime(2026, 9, 2, 4, tzinfo=timezone.utc),
           "pending_ask": {"ask_id": "a1", "title": None, "inputs": [{"id": "dest", "label": "Where should escalations go?", "options": ["#a", "#b"]}]}}
    prompt = {"conversation_id": "conv-2", "workflow_id": "wf-1", "node_id": "agent1", "proposal_id": "p1", "prompt": "Add a Linear tool", "prompt_node_id": "agent1", "created_at": "2026-09-02T03:00:00+00:00", "last_activity": None}
    link = {"id": "link-1", "workflow_id": "wf-1", "workflow_name": "Lead enrichment", "agent_node_id": "agent1", "created_at": datetime(2026, 9, 2, 2, tzinfo=timezone.utc), "expires_at": None,
            "inputs": [{"id": "c", "type": "credential", "label": "Connect Google Sheets", "credential_type": "google_sheets_oauth"}]}
    dead = SimpleNamespace(id="cred-hub", name="HubSpot", credential_type="hubspot_oauth", revoked_at=datetime(2026, 9, 2, 1, tzinfo=timezone.utc), updated_at=None)
    broken = [{"id": "trigger:wf-1:cron", "kind": "trigger_broken", "title": "Daily is not registered", "detail": "tz", "workflow": workflows.ref("wf-1"), "provider": "trigger-cron", "createdAt": "2026-09-02T00:00:00+00:00", "meta": {}}]

    items = dh._compose_attention(workflows, [approval], [ask], [prompt], [link], [], [dead], {}, broken)
    assert [i["kind"] for i in items] == ["approval", "builder_ask", "builder_prompt", "bridge_link", "credential_dead", "trigger_broken"]
    assert items[0]["fields"] == [{"name": "subject", "type": "string", "label": "Subject", "description": None, "options": None, "value": "Hi"}]
    assert items[1]["choices"] == ["#a", "#b"] and items[1]["meta"]["askId"] == "a1"
    # The builder's own input requests ride along verbatim, so the product can
    # answer with the builder's wizard; a credential ask names its provider.
    assert items[1]["inputs"] == ask["pending_ask"]["inputs"]
    cred_ask = {**ask, "conversation_id": "conv-2", "pending_ask": {"ask_id": "a2", "title": "Which Slack workspace?", "inputs": [
        {"id": "s", "type": "credential", "label": "Which Slack workspace?", "credentialType": "slack", "nodeType": "automation-slack", "nodeId": "slack-1", "required": True}]}}
    cred_item = dh._compose_attention(workflows, [], [cred_ask], [], [], [], [], {}, [])[0]
    assert cred_item["credentialType"] == "slack" and cred_item["provider"] == "automation-slack"
    assert cred_item["inputs"][0]["nodeType"] == "automation-slack"
    assert items[2]["from"] == {"nodeId": "agent1", "label": "Enricher", "model": "codex"}
    assert items[3]["link"] == "/b/link-1" and items[3]["credentialType"] == "google_sheets_oauth"
    assert items[4]["meta"]["usedBy"] == [workflows.ref("wf-1")]


def test_resource_places_are_writable():
    workflows = dh._Workflows([{"id": "wf-1", "name": "Sales", "workflow": {"nodes": [], "edges": []}}])
    row = {"id": "r1", "workflow_id": "wf-1", "name": "leads.csv", "mime_type": "text/csv", "resource_type": "file",
           "size_bytes": 10, "created_at": datetime(2026, 9, 2, tzinfo=timezone.utc), "storage_ref": None, "metadata": {}}
    places = dh._compose_files(workflows, [row])
    assert places[0]["kind"] == "resources" and places[0]["writable"] is True
    assert places[0]["files"][0]["resourceId"] == "r1"


def test_stale_next_run_mirror_is_not_upcoming():
    """A `next_run` in the past is a stale display mirror (the reconciler writes
    it; fires don't), so it neither schedules an upcoming run nor arms a date."""
    graph = {"nodes": [{"id": "cron", "type": "trigger-cron", "config": {"label": "Weekly", "trigger_registered": True, "next_run": "2020-02-26T11:12:00Z"}}]}
    workflows = _wf(graph=graph)
    assert dh._compose_upcoming(workflows, [], []) == []
    triggers, _ = dh._compose_triggers(workflows, [], [])
    assert triggers[0]["armed"] is True and triggers[0]["nextRunAt"] is None


def test_tool_call_provider_falls_back_to_the_tool_name():
    assert dh._provider_type_from_tool("whatsapp__send_text_message") == "automation-whatsapp"
    assert dh._provider_type_from_tool("google_sheets_2__append_row") == "automation-google-sheets"
    assert dh._provider_type_from_tool("execute_bash") is None


def test_triggers_read_mirror_and_rows():
    graph = {"nodes": [
        {"id": "cron", "type": "trigger-cron", "config": {"label": "Daily", "trigger_registered": False, "trigger_error": "Schedule not registered: timezone is required"}},
        {"id": "hook", "type": "trigger-webhook", "config": {"label": "Inbound"}},
    ]}
    workflows = _wf(graph=graph)
    triggers, broken = dh._compose_triggers(workflows, [{"workflow_id": "wf-1", "node_id": "hook", "is_active": False, "registered_operation": None, "registered_fingerprint": None, "last_triggered_at": None, "trigger_count": 0}], [])
    by_node = {t["nodeId"]: t for t in triggers}
    assert by_node["cron"]["armed"] is False and by_node["cron"]["error"].startswith("Schedule not registered")
    assert by_node["hook"]["armed"] is False and by_node["hook"]["error"] is None
    assert [b["kind"] for b in broken] == ["trigger_broken"] and "Daily" in broken[0]["title"]


@pytest.mark.asyncio
async def test_build_overview_isolates_a_failing_section():
    """One broken query empties its section and lands in `errors`; the rest renders."""
    pool = object()

    async def boom(*_a, **_k):
        raise RuntimeError("relation does not exist")

    async def ok(*_a, **_k):
        return []

    async def two(*_a, **_k):
        return [], 0

    patches = [
        patch.object(dh.FeedRepo, "get_primary_org_id", AsyncMock(return_value=None)),
        patch.object(dh.FeedRepo, "list_approvals", AsyncMock(return_value=([], []))),
        patch.object(dh.FeedRepo, "list_tool_calls", AsyncMock(return_value=([], {}))),
        patch.object(dh.ConversationRepo, "list_pending_asks", ok),
        patch.object(dh.CredentialsRepo, "list_credential_requests", ok),
        patch.object(dh.CredentialsRepo, "list_accessible", ok),
        patch.object(dh.DashboardRepo, "workspace_identity", AsyncMock(return_value={"userName": "Dhruv", "orgName": "Acme", "isPersonal": False})),
        patch.object(dh.DashboardRepo, "list_workflows", AsyncMock(return_value=[{"id": "wf-1", "name": "WF", "workflow": SAVE_SHAPE, "updated_at": None}])),
        patch.object(dh.DashboardRepo, "unanswered_builder_prompts", ok),
        patch.object(dh.DashboardRepo, "pending_bridge_links", ok),
        patch.object(dh.DashboardRepo, "runs_window", boom),
        patch.object(dh.DashboardRepo, "recent_runs", ok),
        patch.object(dh.DashboardRepo, "awaiting_delay", ok),
        patch.object(dh.DashboardRepo, "webhook_rows", ok),
        patch.object(dh.DashboardRepo, "subscription_rows", ok),
        patch.object(dh.DashboardRepo, "resources", ok),
        patch.object(dh.DashboardRepo, "agent_conversations", ok),
        patch.object(dh.DashboardRepo, "notifications", two),
        patch.object(dh, "_list_sandboxes", ok),
        patch.object(dh, "_alarm_fanout", ok),
        patch.object(dh, "_credential_health", AsyncMock(return_value={})),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        payload = await dh.build_overview(pool, USER)

    assert payload["errors"] == {"runs": "relation does not exist"}
    assert payload["runs"]["days"] == [] and payload["workspace"] == {"name": "Acme", "kind": "org", "userName": "Dhruv"}
    assert payload["upcoming"][0]["kind"] == "schedule" and payload["triggers"][0]["armed"] is True
