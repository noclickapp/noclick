"""End-to-end coverage for the per-request instrumentation pipeline.

A single user prompt traverses: browser send → socket receiver →
worker dispatch → worker boot/import → AgenticBuilder → skill selection → brain
stream → agent op execution → result. This PR closes the remaining
blind spots so a stuck request can be diagnosed phase-by-phase. Each
test pins one phase's signal:

  * PR-A — `_stamp_correlation_ids`: socket span gets conversation_id,
    generation_id, workflow_id, request_id, ask_id as attributes so
    Honeycomb queries by conversation_id work.
  * PR-B — `_stamp_wire_latency`: FE-stamped `_client_sent_at_ms` becomes
    `socket.wire_latency_ms` on the span; receiver strips the key
    before the handler sees it.
  * PR-C — `agent.op` spans wrap each per-op dispatch with kind/tag
    attributes so dashboards can pivot by op type.
"""
from __future__ import annotations

import time
from typing import List
from unittest.mock import MagicMock

import pytest

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)


# ─── Shared fixtures ─────────────────────────────────────────────────


@pytest.fixture
def memory_exporter(monkeypatch):
    """Swap the module-level tracer in receiver.py / commands.py for one
    bound to an InMemorySpanExporter."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    test_tracer = provider.get_tracer("test")
    from wss.receiver import receiver as receiver_module
    from coder.workflow.agentic import commands as commands_module
    monkeypatch.setattr(receiver_module, "_tracer", test_tracer)
    monkeypatch.setattr(commands_module, "_tracer", test_tracer)
    return exporter


def _spans_by_name(exporter, name: str):
    return [s for s in exporter.get_finished_spans() if s.name == name]


# ─── PR-A: correlation IDs on socket span ────────────────────────────


class TestCorrelationIdStamping:
    """The receiver must stamp known IDs as span attributes so Honeycomb
    queries by `conversation_id` work without grep-by-time."""

    def test_stamp_correlation_ids_sets_known_keys(self):
        from wss.receiver.receiver import SocketIOProxy
        proxy = SocketIOProxy(MagicMock())
        span = MagicMock()
        proxy._stamp_correlation_ids(span, {
            "conversation_id": "conv-abc",
            "generation_id": "gen-xyz",
            "workflow_id": "wf-123",
            "request_id": "req-456",
            "ask_id": "ask-789",
            "unrelated_field": "should-not-leak",
        })
        attr_calls = {c.args[0]: c.args[1] for c in span.set_attribute.call_args_list}
        assert attr_calls == {
            "conversation_id": "conv-abc",
            "generation_id": "gen-xyz",
            "workflow_id": "wf-123",
            "request_id": "req-456",
            "ask_id": "ask-789",
        }

    def test_stamp_correlation_ids_skips_unknown_keys(self):
        """Random keys in the payload must NOT become span attributes —
        the receiver applies to EVERY socket event, so unrestricted
        attribute writes would explode Honeycomb column cardinality."""
        from wss.receiver.receiver import SocketIOProxy
        proxy = SocketIOProxy(MagicMock())
        span = MagicMock()
        proxy._stamp_correlation_ids(span, {"some_random_key": "value"})
        assert span.set_attribute.call_count == 0

    def test_stamp_correlation_ids_tolerates_non_dict(self):
        """Some events carry primitive payloads or none at all — the helper
        must no-op rather than raise."""
        from wss.receiver.receiver import SocketIOProxy
        proxy = SocketIOProxy(MagicMock())
        span = MagicMock()
        proxy._stamp_correlation_ids(span, None)
        proxy._stamp_correlation_ids(span, "string")
        proxy._stamp_correlation_ids(span, 42)
        assert span.set_attribute.call_count == 0


# ─── PR-B: wire latency stamping ─────────────────────────────────────


class TestWireLatencyStamping:
    """FE-stamped `_client_sent_at_ms` round-trips to a span attribute,
    and the key is stripped from the payload before the handler runs."""

    def test_wire_latency_computed_and_payload_stripped(self):
        from wss.receiver.receiver import SocketIOProxy
        proxy = SocketIOProxy(MagicMock())
        span = MagicMock()
        # Simulate a payload sent 100ms ago (in server's frame of reference)
        data = {
            "conversation_id": "c1",
            "_client_sent_at_ms": int(time.time() * 1000) - 100,
        }
        proxy._stamp_wire_latency(span, data)
        # Key MUST be popped — handlers shouldn't see transport metadata
        assert "_client_sent_at_ms" not in data
        # Wire latency should be approximately 100ms (small tolerance for
        # the time elapsed between data dict creation and helper call)
        attr_call = next(
            c for c in span.set_attribute.call_args_list
            if c.args[0] == "socket.wire_latency_ms"
        )
        assert 50 <= attr_call.args[1] <= 5000, (
            f"wire_latency_ms={attr_call.args[1]} not in plausible range"
        )

    def test_wire_latency_missing_stamp_is_silent_noop(self):
        from wss.receiver.receiver import SocketIOProxy
        proxy = SocketIOProxy(MagicMock())
        span = MagicMock()
        proxy._stamp_wire_latency(span, {"conversation_id": "c1"})
        assert span.set_attribute.call_count == 0

    def test_wire_latency_malformed_stamp_doesnt_raise(self):
        from wss.receiver.receiver import SocketIOProxy
        proxy = SocketIOProxy(MagicMock())
        span = MagicMock()
        # Non-numeric — must be silently ignored, not crash the receiver
        proxy._stamp_wire_latency(span, {"_client_sent_at_ms": "not-a-number"})
        assert span.set_attribute.call_count == 0


# ─── PR-C: per-op agent.op spans ─────────────────────────────────────


class TestAgentOpSpans:
    """Each platform op (`run_node`, `list_workflows`, …) gets its own
    `agent.op` span with kind + tag + duration."""

    @pytest.mark.asyncio
    async def test_execute_platform_ops_emits_one_span_per_op(self, memory_exporter):
        from coder.workflow.agentic.commands import execute_platform_ops
        from coder.workflow.workflow_xml import XmlOp

        class _FakePlatform:
            async def list_workflows(self, query, limit):
                return [{"id": "wf1", "name": "X", "description": ""}]
            async def open_workflow(self, wid):
                return {"success": True}

        ops = [
            XmlOp(tag="list_workflows", attrs={"query": "demo"}, body=""),
            XmlOp(tag="open_workflow", attrs={"id": "wf1"}, body=""),
        ]
        await execute_platform_ops(ops, _FakePlatform())

        agent_spans = _spans_by_name(memory_exporter, "agent.op")
        assert len(agent_spans) == 2, (
            f"expected 2 agent.op spans, got {len(agent_spans)} "
            f"(all: {[s.name for s in memory_exporter.get_finished_spans()]})"
        )
        kinds = {dict(s.attributes).get("agent.op.kind") for s in agent_spans}
        tags = {dict(s.attributes).get("agent.op.tag") for s in agent_spans}
        assert kinds == {"platform_op"}
        assert tags == {"list_workflows", "open_workflow"}
        # Every span has duration recorded
        for s in agent_spans:
            attrs = dict(s.attributes)
            assert "agent.op.duration_ms" in attrs
            assert attrs["agent.op.duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_execute_node_ops_emits_span_with_node_attr(self, memory_exporter):
        from coder.workflow.agentic.commands import execute_node_ops
        from coder.workflow.graph_state import GraphState
        from coder.workflow.workflow_xml import XmlOp

        class _FakePlatform:
            async def run_node(self, node_id, include_downstream=False):
                return {"output": {"foo": 1}}
            async def get_node_output(self, node_id):
                return None

        graph = GraphState()
        graph.add_node("slack", "automation-slack", "Slack")
        ops = [
            XmlOp(tag="run_node", attrs={"node": "slack"}, body=""),
        ]
        await execute_node_ops(ops, _FakePlatform(), graph)

        agent_spans = _spans_by_name(memory_exporter, "agent.op")
        assert len(agent_spans) == 1
        attrs = dict(agent_spans[0].attributes)
        assert attrs["agent.op.tag"] == "run_node"
        assert attrs["agent.op.kind"] == "node_op"
        assert attrs["agent.op.node"] == "slack"

    @pytest.mark.asyncio
    async def test_run_node_error_attaches_to_span(self, memory_exporter):
        from coder.workflow.agentic.commands import execute_node_ops
        from coder.workflow.graph_state import GraphState
        from coder.workflow.workflow_xml import XmlOp

        class _FakePlatform:
            async def run_node(self, node_id, include_downstream=False):
                return {"error": "Credentials are required."}
            async def get_node_output(self, node_id):
                return None

        graph = GraphState()
        graph.add_node("slack", "automation-slack", "Slack")
        await execute_node_ops(
            [XmlOp(tag="run_node", attrs={"node": "slack"}, body="")],
            _FakePlatform(), graph,
        )
        attrs = dict(_spans_by_name(memory_exporter, "agent.op")[0].attributes)
        assert "Credentials are required" in attrs["agent.op.error"]


