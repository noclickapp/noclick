"""
Integration tests for the core data nodes — filter, merge, conditional,
iteration — executed through the real WorkflowExecutionHandler.

Each test builds a dummy workflow graph, sends a workflow:execute event, and
asserts on the workflow:node:output events the nodes emit. This exercises every
operation end to end, including config deserialization from the wire format —
which routes through each node's discriminated-union config.
"""

import pytest
import pytest_asyncio
import asyncio
import uuid
import json
from typing import List, Dict, Any
from unittest.mock import patch

from tests.utils.base_handler_test import BaseHandlerTest
from tests.fixtures.real_db_fixture import real_database
from wss.receiver.client_events import WorkflowExecuteRequest
from wss.sender import send_event
from nodes.dummy_node import DummyNode


USER_ID = '00000000-0000-4000-8000-000000000003'


class TestCoreNodeExecution(BaseHandlerTest):
    """Run the core data nodes through the workflow execution handler."""

    def get_session_data(self, sid: str) -> Dict[str, Any]:
        return {'sid': sid, 'user_id': USER_ID, 'email': 'core-node-test@example.com'}

    # ------------------------------------------------------------------ helpers
    async def _setup_db(self, real_database, workflow_id: str):
        await real_database.execute(
            "INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
            USER_ID, 'core-node-test@example.com',
        )
        await real_database.execute(
            "INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())",
            workflow_id, USER_ID, "Core Node Test", "", {}, {},
        )

    def _node(self, node_id: str, node_type: str, config: Dict[str, Any],
              x: int = 0, y: int = 0) -> Dict[str, Any]:
        """Build a node spec. Config is wrapped as NodeConfig expects ({"config": ...})."""
        return {
            "id": node_id,
            "type": node_type,
            "position": {"x": x, "y": y},
            "config": {"config": config},
        }

    async def _run(self, frontend_sio, sid, real_database,
                   nodes: List[Dict], edges: List[Dict]) -> Dict[str, Any]:
        """Execute a workflow and return {node_id: last emitted output}.

        Clears prior emitted events so a test can run several workflows and
        assert on each in isolation.
        """
        self.main_api_sio.emitted_events.clear()
        workflow_id = str(uuid.uuid4())
        await self._setup_db(real_database, workflow_id)
        request = WorkflowExecuteRequest(
            event_name="workflow:execute",
            request_id=f"req-{uuid.uuid4()}",
            workflow_id=workflow_id,
            nodes=nodes,
            edges=edges,
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.5)

        outputs: Dict[str, Any] = {}
        for event in self.get_main_api_emitted_events("workflow:node:output"):
            data = event[1]
            outputs[data['node_id']] = data['output']
        return outputs

    def _assert_workflow_succeeded(self):
        complete = self.get_main_api_emitted_events("workflow:complete")
        assert len(complete) == 1, "workflow should complete exactly once"
        assert complete[0][1]['success'] is True, \
            f"workflow failed: {complete[0][1].get('error')}"

    @pytest.mark.asyncio
    async def test_intermediate_emit_does_not_replace_canonical_output(
        self, real_database, frontend_sio, sid
    ):
        """Node-internal emit() metadata must not compete with final node output."""
        expected_output = {
            "maxResults": 50,
            "startAt": 0,
            "total": 2,
            "isLast": True,
            "values": [
                {"id": 1, "name": "Board 1"},
                {"id": 2, "name": "Board 2"},
            ],
        }

        async def fake_execute(self, inputs):
            await self.emit({"action": "list_boards", "count": 2})
            return expected_output

        nodes = [
            self._node("dummy-emit", "test-dummy", {"stringValue": "ok"}),
        ]

        with patch.object(DummyNode, "execute", new=fake_execute):
            out = await self._run(frontend_sio, sid, real_database, nodes, [])

        self._assert_workflow_succeeded()
        assert out["dummy-emit"] == expected_output

        output_events = [
            event[1]
            for event in self.get_main_api_emitted_events("workflow:node:output")
            if event[1].get("node_id") == "dummy-emit"
        ]
        progress_events = [
            event[1]
            for event in self.get_main_api_emitted_events("workflow:node:progress")
            if event[1].get("node_id") == "dummy-emit"
        ]

        assert len(output_events) == 1
        assert output_events[0]["output"] == expected_output
        # self.emit({...}) rides the unified progress event as a snapshot —
        # separate from the canonical output slot.
        assert len(progress_events) == 1
        assert progress_events[0].get("snapshot") == {"action": "list_boards", "count": 2}
        assert "append" not in progress_events[0]

    # ------------------------------------------------------------------- filter
    @pytest.mark.asyncio
    async def test_filter_operations(self, real_database, frontend_sio, sid):
        """All seven filter operations produce the expected output."""
        users = json.dumps([
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
            {"name": "Eve", "age": 40},
        ])
        nums = json.dumps([3, 1, 2, 2, 3])
        obj = json.dumps({"a": 1, "b": 2, "password": "secret"})
        records = json.dumps([
            {"type": "a", "v": 1}, {"type": "b", "v": 2}, {"type": "a", "v": 3},
        ])

        nodes = [
            self._node("f-array", "filter", {
                "operation": "filter_array", "input_data": users,
                "filter_field": "age", "operator": "greater_than", "filter_value": "28",
            }),
            self._node("f-dedup", "filter", {
                "operation": "remove_duplicates", "input_data": nums,
            }, y=120),
            self._node("f-limit", "filter", {
                "operation": "limit", "input_data": nums, "limit": 2,
            }, y=240),
            self._node("f-sort", "filter", {
                "operation": "sort", "input_data": nums, "sort_order": "ascending",
            }, y=360),
            self._node("f-obj", "filter", {
                "operation": "filter_object", "input_data": obj, "keep_keys": "a,b",
            }, y=480),
            self._node("f-group", "filter", {
                "operation": "group_by_field", "input_data": records,
                "group_by_field": "type",
            }, y=600),
            self._node("f-split", "filter", {
                "operation": "split_string", "input_data": "apple, banana , cherry",
                "delimiter": ",", "trim_whitespace": "true",
            }, y=720),
        ]

        out = await self._run(frontend_sio, sid, real_database, nodes, [])
        self._assert_workflow_succeeded()

        assert out["f-array"]["operation"] == "filter_array"
        assert out["f-array"]["count"] == 2  # Alice (30), Eve (40)
        assert {u["name"] for u in out["f-array"]["filtered"]} == {"Alice", "Eve"}

        assert out["f-dedup"]["operation"] == "remove_duplicates"
        assert sorted(out["f-dedup"]["filtered"]) == [1, 2, 3]

        assert out["f-limit"]["operation"] == "limit"
        assert out["f-limit"]["filtered"] == [3, 1]

        assert out["f-sort"]["operation"] == "sort"
        assert out["f-sort"]["filtered"] == [1, 2, 2, 3, 3]

        assert out["f-obj"]["operation"] == "filter_object"
        assert set(out["f-obj"]["filtered"].keys()) == {"a", "b"}

        # group_by_field — absorbed from the (now deleted) split node
        assert out["f-group"]["operation"] == "group_by_field"
        assert set(out["f-group"]["filtered"].keys()) == {"a", "b"}
        assert len(out["f-group"]["filtered"]["a"]) == 2

        # split_string — absorbed from the (now deleted) split node
        assert out["f-split"]["operation"] == "split_string"
        assert out["f-split"]["filtered"] == ["apple", "banana", "cherry"]

    # -------------------------------------------------------------- conditional
    @pytest.mark.asyncio
    async def test_conditional_operations(self, real_database, frontend_sio, sid):
        """The conditional node routes correctly across a range of operators."""
        nodes = [
            self._node("c-true", "conditional", {
                "input_data": json.dumps({"status": "active"}),
                "condition_field": "status", "condition_operator": "equals",
                "condition_value": "active",
            }),
            self._node("c-false", "conditional", {
                "input_data": json.dumps({"status": "inactive"}),
                "condition_field": "status", "condition_operator": "equals",
                "condition_value": "active",
            }, y=120),
            self._node("c-num", "conditional", {
                "input_data": json.dumps({"score": 80}),
                "condition_field": "score", "condition_operator": "greater_than",
                "condition_value": "50",
            }, y=240),
            self._node("c-case", "conditional", {
                "input_data": json.dumps({"name": "ALICE"}),
                "condition_field": "name", "condition_operator": "equals",
                "condition_value": "alice", "case_sensitive": "true",
            }, y=360),
            self._node("c-empty", "conditional", {
                "input_data": json.dumps({"notes": ""}),
                "condition_field": "notes", "condition_operator": "is_empty",
            }, y=480),
        ]

        out = await self._run(frontend_sio, sid, real_database, nodes, [])
        self._assert_workflow_succeeded()

        assert out["c-true"]["condition_result"] is True
        assert out["c-true"]["output_handle"] == "true"

        assert out["c-false"]["condition_result"] is False
        assert out["c-false"]["output_handle"] == "false"

        assert out["c-num"]["condition_result"] is True

        # case_sensitive="true" — "ALICE" must not equal "alice"
        assert out["c-case"]["condition_result"] is False

        assert out["c-empty"]["condition_result"] is True

    # -------------------------------------------------------------------- merge
    async def _run_merge(self, frontend_sio, sid, real_database,
                         operation: str, extra_cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Run an isolated workflow: two passthrough sources → one merge node.

        A merge node consumes every array it can see in its inputs, so each
        operation gets its own workflow to avoid cross-contamination.
        """
        array_a = json.dumps([{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}])
        array_b = json.dumps([{"id": 1, "email": "a@x.com"}, {"id": 3, "email": "c@x.com"}])

        def source(node_id, data, y):
            return self._node(node_id, "filter", {
                "operation": "limit", "input_data": data, "limit": 1000,
            }, y=y)

        nodes = [
            source("src-a", array_a, 0),
            source("src-b", array_b, 120),
            self._node("merge-node", "merge", {"operation": operation, **extra_cfg}, x=300),
        ]
        edges = [
            {"id": "e-a", "source": "src-a", "target": "merge-node"},
            {"id": "e-b", "source": "src-b", "target": "merge-node"},
        ]
        out = await self._run(frontend_sio, sid, real_database, nodes, edges)
        self._assert_workflow_succeeded()
        return out["merge-node"]

    @pytest.mark.asyncio
    async def test_merge_operations(self, real_database, frontend_sio, sid):
        """All five merge operations combine two upstream arrays correctly."""
        # append: all 4 items concatenated
        append = await self._run_merge(frontend_sio, sid, real_database, "append", {})
        assert append["operation"] == "append"
        assert append["count"] == 4

        # combine_by_position: zipped by index — 2 rows
        position = await self._run_merge(frontend_sio, sid, real_database,
                                         "combine_by_position", {})
        assert position["count"] == 2

        # combine_by_field on "id": id 1 (in both), id 2, id 3 → 3 rows
        field = await self._run_merge(frontend_sio, sid, real_database,
                                      "combine_by_field", {"match_field": "id"})
        assert field["count"] == 3
        joined = next(r for r in field["merged"] if r.get("id") == 1)
        assert joined.get("name") == "Alice" and joined.get("email") == "a@x.com"

        # keep_matches on "id": only id 1 exists in both inputs
        keep = await self._run_merge(frontend_sio, sid, real_database,
                                     "keep_matches", {"match_field": "id"})
        assert keep["count"] == 1
        assert keep["merged"][0]["id"] == 1

        # remove_duplicates: all 4 objects are distinct
        dedup = await self._run_merge(frontend_sio, sid, real_database,
                                      "remove_duplicates", {})
        assert dedup["count"] == 4

    # ---------------------------------------------------------------- iteration
    @pytest.mark.asyncio
    async def test_iteration_operations(self, real_database, frontend_sio, sid):
        """The iteration node resolves items with and without header-row mode."""
        nodes = [
            self._node("it-header", "iteration", {
                "items": json.dumps([["name", "age"], ["Alice", "30"], ["Bob", "25"]]),
                "header_row": "true",
            }),
            self._node("it-plain", "iteration", {
                "items": json.dumps(["x", "y", "z"]),
                "header_row": "false",
            }, y=120),
        ]

        out = await self._run(frontend_sio, sid, real_database, nodes, [])
        self._assert_workflow_succeeded()

        # header_row="true": first row becomes field names, 2 data rows remain
        assert out["it-header"]["total"] == 2
        assert out["it-header"]["items"][0] == {"name": "Alice", "age": "30"}

        # header_row="false": items pass through unchanged
        assert out["it-plain"]["total"] == 3
        assert out["it-plain"]["items"] == ["x", "y", "z"]
