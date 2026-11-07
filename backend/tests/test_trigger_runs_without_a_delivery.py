"""A trigger that runs with no delivery (a manual or test run) has no event to show or teach.

Its ``execute`` gets the run's other outputs as ``inputs``, keyed by step, and about fifty node types copied them into
the output as if they were the event. The output's shape was then learned, and read back to other accounts. So nothing
reaches a trigger through ``WorkflowNode.run``, and a run with no event teaches ``node_schema_tracker`` nothing.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from nodes.agent.node_op_tools import _iter_operation_defs, is_trigger
from nodes.core.registry import NODE_REGISTRY
from nodes.exa_node import ExaMonitorTriggerConfig, ExaNode, ExaNodeConfig
from nodes.posthog_node import PostHogNode
from nodes.webhook_trigger_node import WebhookTriggerNode
from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler
from tests.utils.sweep import check_each

OTHER_STEPS = {"another_step": {"its_field": "its value"}, "vars": {"a_variable": 1}}


class _Op:
    """A parsed config as ``run`` reads it: its operation, nothing a test of what ``execute`` receives needs more of."""

    def __init__(self, operation):
        self.config = MagicMock(operation=operation)


def _bare(node_cls, node_type, operation):
    node = object.__new__(node_cls)
    node.node_id, node.node_type, node.node_data = "n1", node_type, {}
    node.workflow_id, node.user_id, node.organization_id = "wf", "u1", None
    node._config = _Op(operation)
    return node


TRIGGERS = sorted(t for t, c in NODE_REGISTRY.items() if t.startswith("trigger-") or _iter_operation_defs(c, triggers=True))


async def _no_trigger_of_any_node_type_is_handed_the_runs_other_outputs(node_type, monkeypatch):
    node_cls = NODE_REGISTRY[node_type]
    received = []

    async def execute(self, inputs):
        received.append(inputs)
        return {"status": "success"}

    monkeypatch.setattr(node_cls, "execute", execute)
    operations = [o["operation"] for o in _iter_operation_defs(node_cls, triggers=True)] or [None]
    for operation in operations:
        await _bare(node_cls, node_type, operation).run(dict(OTHER_STEPS))
    assert received == [{}] * len(operations)


@pytest.mark.asyncio
async def test_no_trigger_of_any_node_type_is_handed_the_runs_other_outputs():
    async def one(node_type):
        # Each case patches what it needs afresh, undone before the next, as its own test once did.
        with pytest.MonkeyPatch.context() as monkeypatch:
            await _no_trigger_of_any_node_type_is_handed_the_runs_other_outputs(node_type, monkeypatch)

    await check_each(TRIGGERS, one)


async def test_a_step_that_isnt_a_trigger_still_reads_what_came_before(monkeypatch):
    received = []

    async def execute(self, inputs):
        received.append(inputs)
        return {"status": "success"}

    monkeypatch.setattr(ExaNode, "execute", execute)
    await _bare(ExaNode, "automation-exa", "search").run(dict(OTHER_STEPS))
    assert received == [OTHER_STEPS]


@pytest.mark.parametrize("build", [
    pytest.param(lambda: ExaNode(
        node_id="n1", node_type="automation-exa", node_data={}, sio=AsyncMock(), sid="s", workflow_id="wf", user_id="u1",
        config=ExaNodeConfig(config=ExaMonitorTriggerConfig(monitor_query="q", webhook_url="https://a.hooks.example.test"))),
                 id="exa"),
    pytest.param(lambda: PostHogNode(
        node_id="n1", node_type="automation-posthog", node_data={}, sio=AsyncMock(), sid="s", workflow_id="wf",
        user_id="u1", config=PostHogNode.get_config_model().model_validate({"config": {"operation": "on_pageview"}})),
                 id="posthog"),
    pytest.param(lambda: WebhookTriggerNode(
        node_id="n1", node_type="trigger-webhook", node_data={}, sio=AsyncMock(), sid="s", workflow_id="wf",
        user_id="u1", config=WebhookTriggerNode.get_config_model().model_validate({"config": {}})), id="webhook"),
])
async def test_a_manual_runs_output_holds_nothing_of_the_runs_other_steps(build):
    output = await build().run(dict(OTHER_STEPS))
    for held in ("another_step", "its_field", "its value", "a_variable"):
        assert held not in str(output)


def test_is_trigger_names_a_trigger_node_or_a_trigger_operation():
    assert is_trigger("trigger-webhook", None) and is_trigger("trigger-cron", "default")
    assert is_trigger("automation-exa", "on_monitor_results")
    assert not is_trigger("automation-exa", "search") and not is_trigger("automation-exa", None)


# ── what a run of it teaches ────────────────────────────────────────────────


def _trigger_node(output):
    node = _bare(ExaNode, "automation-exa", "on_monitor_results")
    node.run = AsyncMock(return_value=output)
    node.set_workflow_context = MagicMock()
    return node


async def _run(monkeypatch, node, node_type, config):
    """A real pass through the executor with the node's own run replaced, and what it asked to be learned."""
    taught = AsyncMock()
    monkeypatch.setattr("wss.handlers.workflow_execution_handler.track_node_schema", taught)
    handler = WorkflowExecutionHandler(AsyncMock())
    monkeypatch.setattr(handler, "_resolve_credentials", AsyncMock(return_value={}))
    monkeypatch.setattr("wss.handlers.workflow_execution_handler.NodeFactory.create_node", lambda *a, **k: node)
    _, error, outputs = await handler._execute_nodes_concurrent(
        [{"id": "n1", "type": node_type, "config": config}], [], "sid", "user", "wf",
    )
    assert error is None
    return taught, outputs


async def test_a_push_triggers_manual_run_teaches_nothing(monkeypatch):
    node = _trigger_node({"status": "success", "action": "on_monitor_results", "data": {"webhook_url": "https://a"}})
    taught, _ = await _run(monkeypatch, node, "automation-exa", {"operation": "on_monitor_results"})
    taught.assert_not_awaited()


async def test_a_delivery_teaches_as_a_delivery(monkeypatch):
    payload = {"type": "monitor.run.completed", "data": {"status": "completed"}, "_webhook": {"id": "w"}}
    taught, outputs = await _run(monkeypatch, _trigger_node({}), "automation-exa",
                                 {"operation": "on_monitor_results", "_triggerPayload": payload})
    assert outputs["n1"] == payload
    taught.assert_awaited_once()
    assert taught.await_args.kwargs["output"] == payload and taught.await_args.kwargs["delivered"] is True
    assert taught.await_args.kwargs["workflow_id"] == "wf"  # whose owner keeps the shape as their own


class _Poll(ExaNode):
    """A poll trigger, as the executor sees one: execute() is what finds out what arrived."""

    emitted = 0

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return None

    def trigger_produced_no_event(self, output):
        return self.emitted == 0

    def trigger_emitted_event(self, output):
        return self.emitted > 0


def _poll_node(emitted):
    node = _bare(_Poll, "automation-exa", "on_monitor_results")
    node.emitted = emitted
    node.run = AsyncMock(return_value={"rows": [{"id": 1}]} if emitted else {"rows": []})
    node.set_workflow_context = MagicMock()
    return node


@pytest.mark.parametrize("config, emitted, teaches", [
    pytest.param({}, 1, True, id="by hand, found something"),
    pytest.param({}, 0, False, id="by hand, found nothing"),
    pytest.param({"_triggerPayload": {"tick": 1}}, 0, False, id="its tick, found nothing"),
    pytest.param({"_triggerPayload": {"tick": 1}}, 1, True, id="its tick, found something"),
])
async def test_a_poll_teaches_what_it_found_never_as_a_delivery(monkeypatch, config, emitted, teaches):
    monkeypatch.setitem(NODE_REGISTRY, "automation-exa", _Poll)
    taught, _ = await _run(monkeypatch, _poll_node(emitted), "automation-exa",
                           {"operation": "on_monitor_results", **config})
    assert taught.await_count == (1 if teaches else 0)
    if teaches:
        assert taught.await_args.kwargs["output"] == {"rows": [{"id": 1}]}
        assert not taught.await_args.kwargs.get("delivered")


async def test_a_step_that_isnt_a_trigger_still_teaches(monkeypatch):
    node = _bare(ExaNode, "automation-exa", "search")
    node.run = AsyncMock(return_value={"status": "success", "results": []})
    node.set_workflow_context = MagicMock()
    taught, _ = await _run(monkeypatch, node, "automation-exa", {"operation": "search"})
    taught.assert_awaited_once()
    assert not taught.await_args.kwargs.get("delivered")
    assert taught.await_args.kwargs["workflow_id"] == "wf"


def test_only_a_trigger_ran_with_no_event():
    trigger = _bare(WebhookTriggerNode, "trigger-webhook", None)
    assert trigger.trigger_produced_no_event({"status": "no_event"}) is True
    assert trigger.trigger_produced_no_event({"status": "success"}) is False
    # An action's status of that name is its data.
    assert _bare(ExaNode, "automation-exa", "search").trigger_produced_no_event({"status": "no_event"}) is False
