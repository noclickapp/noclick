"""Builder field ops must not run on the event loop thread.

Regression guard for the perf finding where ``_execute_operations`` called the
sync ``execute_field_ops`` inline. Resolving a queryable-enum field (the model
pickers on the agent/image/video/kling nodes) rebuilds ``MODELS_REGISTRY`` once
its 600s TTL expires, which fetches the OpenRouter / models.dev / OpenCode Zen
catalogs over sync ``httpx``/``requests`` and then translates them — an SSL
round-trip plus seconds of pure-CPU catalog walking, all on the loop.
Production telemetry caught it as an ``event_loop.block`` span at
``ssl.py:1107`` whose stack ran through ``opencode_zen`` and httpx's *sync*
transport.

Mirrors tests/test_models_route_async.py, which guards the same bug class on
the /api/models route.
"""

import threading
from unittest.mock import patch

from coder.workflow.agentic import builder as builder_module
from coder.workflow.agentic.builder import AgenticBuilder
from coder.workflow.graph_state import GraphState
from coder.workflow.workflow_xml import XmlOp


class _StubBuilder:
    """Stand-in for AgenticBuilder.

    A field-only op list skips the graph/sticky/draft branches, so
    ``_execute_operations`` touches only these two members.
    """

    def __init__(self):
        self.graph_state = GraphState()
        self.self_heal_calls: list[tuple] = []
        self.platform_ops = None

    async def _self_heal_operation_changes(self, operation_changes, field_results):
        self.self_heal_calls.append((operation_changes, field_results))

    async def _provision_trigger_webhooks(self, ops, new_node_ids, field_results):
        return
        yield  # pragma: no cover - makes this an async generator


async def test_field_ops_run_off_the_loop_thread():
    seen: list[threading.Thread] = []

    def record(field_ops, state):
        seen.append(threading.current_thread())
        return ["ok"]

    ops = [XmlOp(tag="field", attrs={"node": "n1", "name": "model"}, body="gpt-4o")]
    stub = _StubBuilder()

    with patch.object(builder_module, "execute_field_ops", record):
        async for _ in AgenticBuilder._execute_operations(stub, ops):
            pass

    assert seen, "execute_field_ops never ran"
    assert seen[0] is not threading.main_thread(), (
        "execute_field_ops ran on the event loop thread — a MODELS_REGISTRY "
        "rebuild there blocks the loop on sync HTTP plus catalog translation"
    )


async def test_field_op_results_still_reach_self_heal():
    """The offload must not change what the caller observes."""

    def record(field_ops, state):
        return ["field n1.model = gpt-4o"]

    ops = [XmlOp(tag="field", attrs={"node": "n1", "name": "model"}, body="gpt-4o")]
    stub = _StubBuilder()

    with patch.object(builder_module, "execute_field_ops", record):
        async for _ in AgenticBuilder._execute_operations(stub, ops):
            pass

    assert stub.self_heal_calls, "_self_heal_operation_changes was never awaited"
    _, field_results = stub.self_heal_calls[0]
    assert field_results == ["field n1.model = gpt-4o"]
