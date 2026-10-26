"""A schedule the AI builder writes is judged where it is written, and a runnable one registers during the build.

Asked for "every morning at 8", the open edition's builder drafted ``frequency: "days"`` (a value the trigger can't
run) and then never registered the corrected schedule: provisioning judged readiness against the saved graph, which
lacks the nodes a build adds, so every turn answered "Save the trigger before activating it." Runs against whichever
builder the edition ships, with real PostgreSQL and the local scheduler."""
import json

import pytest

from coder.workflow.agentic.builder import EXEC_RESULT_MARKER, AgenticBuilder
from coder.workflow.agentic.commands import execute_field_ops
from coder.workflow.graph_state import GraphState, NodeState
from coder.workflow.workflow_xml import XmlOp
from tests.fixtures.local_scheduler import local_scheduler  # noqa: F401
from tests.test_builder_requests import USER, builder_request_db  # noqa: F401

DAILY_AT_8 = [{"frequency": "day", "hour": 8, "minute": 0}]
ALLOWED = "Input should be 'seconds', 'minutes', 'hours', 'day', 'week', 'weeks' or 'month'"


def _graph(schedules=None) -> GraphState:
    graph = GraphState()
    config = {"operation": "default", "timezone": "Europe/London"}
    if schedules is not None:
        config["schedules"] = schedules
    graph.nodes["daily"] = NodeState(
        id="daily", type="trigger-cron", label="Daily at 8", goal="Run every morning at 8", operation="default",
        config=config,
    )
    return graph


def _builder(graph: GraphState, workflow_id: str = "") -> AgenticBuilder:
    builder = object.__new__(AgenticBuilder)
    builder.messages = [{"role": "user", "content": f"{EXEC_RESULT_MARKER}\nadded nodes"}]
    builder.graph_state = graph
    builder.platform_ops, builder.user_id, builder.workflow_id = object(), USER, workflow_id
    return builder


def _write_schedules(graph: GraphState, schedules: list) -> list:
    return execute_field_ops(
        [XmlOp("field", {"node": "daily", "name": "schedules", "value": json.dumps(schedules)})], graph,
    )


def test_a_frequency_the_trigger_cannot_run_is_named_where_it_is_written():
    graph = _graph()
    results = "\n".join(_write_schedules(graph, [{"frequency": "days", "hour": 8, "minute": 0}]))
    assert "VALIDATION ERROR for daily" in results and ALLOWED in results
    nudge = _builder(graph)._config_done_nudge()
    assert nudge and "daily (trigger-cron:default)" in nudge and ALLOWED in nudge

    assert not any("ERROR" in line for line in _write_schedules(graph, DAILY_AT_8))
    assert _builder(graph)._config_done_nudge() is None


@pytest.fixture
async def provisioning(local_scheduler, monkeypatch):  # noqa: F811
    from utils import database_pool, webhook_delivery

    app, pool = local_scheduler
    workflow_id = await pool.fetchval("SELECT id::text FROM workflows WHERE owner_id=$1::uuid", USER)
    assert json.loads(await pool.fetchval("SELECT workflow::text FROM workflows WHERE id=$1::uuid", workflow_id)) == {
        "nodes": [], "edges": [],
    }  # saved before this build's nodes, as a build's first save is
    monkeypatch.setattr(database_pool, "get_native_pool", lambda: pool)
    monkeypatch.setattr(webhook_delivery, "_relay", None)
    monkeypatch.setenv("PUBLIC_WEBHOOK_URL", "http://scheduler.test")

    async def provision(graph: GraphState) -> list:
        results: list = []
        async for _ in _builder(graph, workflow_id)._provision_trigger_webhooks([], ["daily"], results):
            pass
        return results

    try:
        yield pool, workflow_id, provision
    finally:
        await pool.execute("DELETE FROM webhooks WHERE workflow_id=$1::uuid", workflow_id)


@pytest.mark.asyncio
async def test_a_schedule_added_in_a_build_registers_during_the_build(provisioning):
    pool, workflow_id, provision = provisioning
    graph = _graph(DAILY_AT_8)
    results = "\n".join(await provision(graph))
    assert "Save the trigger" not in results
    assert "Webhook provisioned for daily" in results, results
    config = graph.nodes["daily"].config
    assert config["trigger_registered"] is True and config["schedule_ids"], config
    rows = await pool.fetch(
        "SELECT cron_expression, timezone, webhook_url, enabled FROM local_cron_schedules "
        "WHERE workflow_id=$1 AND node_id='daily'", workflow_id,
    )
    assert [dict(r) for r in rows] == [{
        "cron_expression": "0 8 * * *", "timezone": "Europe/London", "webhook_url": config["webhook_url"],
        "enabled": True,
    }]


@pytest.mark.asyncio
async def test_a_schedule_it_cannot_run_is_refused_with_the_reason(provisioning):
    pool, workflow_id, provision = provisioning
    graph = _graph([{"frequency": "days", "hour": 8, "minute": 0}])
    results = "\n".join(await provision(graph))
    assert "Webhook provisioning failed for daily: Finish setup before activation" in results, results
    assert ALLOWED in results
    assert not graph.nodes["daily"].config.get("trigger_registered")
    assert await pool.fetchval("SELECT count(*) FROM local_cron_schedules WHERE workflow_id=$1", workflow_id) == 0


@pytest.mark.asyncio
async def test_a_schedule_held_back_by_another_step_registers_once_that_step_goes(provisioning):
    """A schedule refused because a step after it couldn't run yet (no account for it, or a key the instance lacks)
    used to stay off once the builder removed that step: only the turn's own nodes were tried again."""
    pool, workflow_id, provision = provisioning
    graph = _graph(DAILY_AT_8)
    graph.nodes["mail"] = NodeState(
        id="mail", type="automation-gmail", label="Email the digest", goal="Email it", operation="send_email_message",
        config={"operation": "send_email_message", "to": ["me@example.test"], "subject": "Digest", "body": "Hi"},
    )
    graph.add_edge("daily", "mail")
    held = "\n".join(await provision(graph))
    assert "Webhook provisioning failed for daily: Finish setup before activation" in held, held
    assert "Email the digest" in held and not graph.nodes["daily"].config.get("trigger_registered")

    graph.remove_node("mail")
    results: list = []
    async for _ in _builder(graph, workflow_id)._provision_trigger_webhooks(
            [XmlOp("remove_node", {"name": "mail"})], [], results):
        pass
    assert "Webhook provisioned for daily" in "\n".join(results), results
    assert graph.nodes["daily"].config["trigger_registered"] is True
    assert await pool.fetchval("SELECT count(*) FROM local_cron_schedules WHERE workflow_id=$1", workflow_id) == 1
