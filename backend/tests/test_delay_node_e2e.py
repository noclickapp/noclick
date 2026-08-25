"""End-to-end tests for the delay node through the real workflow execution engine.

Drives real workflows through WorkflowExecutionHandler against a real Postgres
(the postgres fixture applies all migrations). Short delays run in-process;
long delays suspend the run ('awaiting_delay') and resume via the generic
suspend/resume core. Only the external Cloudflare scheduler HTTP call and the
resume-webhook plumbing are stubbed — the engine, DB, DelayExecutionStrategy,
output persistence, and the resume path are all exercised for real.
"""
import asyncio
import uuid
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler
from tests.utils.base_handler_test import BaseHandlerTest
from tests.fixtures.real_db_fixture import real_database
from wss.receiver.client_events import WorkflowExecuteRequest
from wss.sender import send_event

USER_ID = "00000000-0000-4000-8000-000000000003"
TELEGRAM_TOKEN = "test-telegram-token-12345678:ABCdefGHIjklMNOpqrsTUVwxyz"


class TestDelayNodeE2E(BaseHandlerTest):
    """Full-stack delay node behavior: short in-process delays + long durable delays.

    CAS persist resolves its pool via utils.database_pool.get_native_pool() at
    call time, and the real_database fixture points that pool at the
    testcontainer — so the persist path lands on the test DB structurally,
    with no per-test patching.
    """

    def get_session_data(self, sid: str):
        return {"sid": sid, "user_id": USER_ID, "email": "delay-e2e@example.com"}

    # -- helpers -------------------------------------------------------------

    async def _create_user(self, db) -> None:
        await db.execute(
            "INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
            USER_ID, "delay-e2e@example.com",
        )

    async def _create_workflow(self, db, workflow_id: str, nodes: List[dict], edges: List[dict]) -> None:
        """Store the full workflow JSON — the resume path reads nodes/edges from here."""
        await db.execute(
            """INSERT INTO workflows (id, owner_id, name, description, workflow, permissions,
                                      created_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())""",
            workflow_id, USER_ID, "Delay E2E", "", {"nodes": nodes, "edges": edges}, {},
        )

    def _delay_node(self, node_id: str, amount: int, unit: str) -> Dict[str, Any]:
        # Flat config — matches the real exported workflow format.
        return {
            "id": node_id,
            "type": "delay",
            "position": {"x": 0, "y": 0},
            "config": {"delay_amount": amount, "delay_unit": unit, "credentialIds": {}},
        }

    def _telegram_node(self, node_id: str) -> Dict[str, Any]:
        return {
            "id": node_id,
            "type": "automation-telegram",
            "position": {"x": 200, "y": 0},
            "config": {
                "config": {"message": "downstream ran", "chatId": "123456"},
                "credentials": {"token": TELEGRAM_TOKEN},
            },
        }

    def _node_states(self, state: str) -> set:
        return {
            e[1]["node_id"]
            for e in self.get_main_api_emitted_events("workflow:node:state")
            if e[1].get("state") == state
        }

    # -- tests ---------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_short_delay_runs_in_process(self, real_database, frontend_sio, sid):
        """A short delay (<= 15 min) sleeps in-process; downstream then runs."""
        workflow_id = str(uuid.uuid4())
        await self._create_user(real_database)
        nodes = [self._delay_node("delay-1", 1, "seconds"), self._telegram_node("tg-1")]
        edges = [{"id": "e1", "source": "delay-1", "target": "tg-1"}]
        await self._create_workflow(real_database, workflow_id, nodes, edges)

        request = WorkflowExecuteRequest(
            event_name="workflow:execute", request_id="short-delay",
            workflow_id=workflow_id, nodes=nodes, edges=edges,
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(2.5)  # 1s in-process delay + engine overhead

        assert "delay-1" in self._node_states("completed")
        # Downstream executed — the short delay did NOT suspend the run.
        assert "tg-1" in self._node_states("running")

    @pytest.mark.asyncio
    async def test_long_delay_suspends_then_resumes(self, real_database, frontend_sio, sid):
        """A long delay suspends the run; a wake-up resumes the downstream subgraph."""
        workflow_id = str(uuid.uuid4())
        await self._create_user(real_database)
        nodes = [self._delay_node("delay-1", 2, "weeks"), self._telegram_node("tg-1")]
        edges = [{"id": "e1", "source": "delay-1", "target": "tg-1"}]
        await self._create_workflow(real_database, workflow_id, nodes, edges)

        request = WorkflowExecuteRequest(
            event_name="workflow:execute", request_id="long-delay",
            workflow_id=workflow_id, nodes=nodes, edges=edges,
        )

        create_alarm = AsyncMock(return_value={"id": "sched-e2e-1"})
        with patch("utils.cron_scheduler_client.create_alarm", create_alarm), \
             patch("utils.cron_scheduler_client.is_cron_scheduler_enabled", return_value=True), \
             patch("utils.webhook_manager.WebhookManager.get_or_create_webhook",
                   AsyncMock(return_value={"webhook_url": "https://test.webhook/delay"})):
            await send_event(frontend_sio, sid, request)
            await asyncio.sleep(1.0)

        # --- the run suspended on the delay node ---
        assert "delay-1" in self._node_states("completed")
        assert "tg-1" in self._node_states("skipped"), "downstream must be skipped while suspended"
        create_alarm.assert_awaited_once()

        rows = await real_database.fetch(
            """SELECT id, status, wake_at, resume_node_id, external_schedule_id
               FROM workflow_executions WHERE workflow_id = $1""",
            workflow_id,
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == "awaiting_delay"
        assert row["wake_at"] is not None
        assert row["resume_node_id"] == "delay-1"
        assert row["external_schedule_id"] == "sched-e2e-1"
        execution_id = str(row["id"])

        # Upstream outputs were persisted to the CAS so the resume can restore them.
        outputs = await real_database.fetch(
            "SELECT node_id FROM cas_manifests WHERE execution_id = $1",
            execution_id,
        )
        assert any(o["node_id"] == "delay-1" for o in outputs)

        # --- the wake-up resumes the run ---
        handler = WorkflowExecutionHandler(frontend_sio)
        await handler.handle_resume(
            sid="",
            caller_user_id=USER_ID,
            data={
                "execution_id": execution_id,
                "workflow_id": workflow_id,
                "resume_node_id": "delay-1",
                "from_status": "awaiting_delay",
                "decision": None,
            },
        )
        await asyncio.sleep(1.0)

        # Downstream ran on resume.
        assert "tg-1" in self._node_states("running")

        # The original execution is no longer suspended.
        final = await real_database.fetch(
            "SELECT status FROM workflow_executions WHERE id = $1", execution_id
        )
        assert final[0]["status"] in ("completed", "error")

        # The resume reused the original execution row — one logical run is one
        # execution record, not a fresh row per resume.
        all_rows = await real_database.fetch(
            "SELECT id FROM workflow_executions WHERE workflow_id = $1", workflow_id
        )
        assert len(all_rows) == 1, "resume must reuse the original row, not create a new one"
