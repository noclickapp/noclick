"""L5 real-stack smoke for the SDK's restored-output scenario.

The deterministic layers mock the store (L4 patches latest_outputs) or the backend
(L1/L2 use a fake/mock socket). This test wires the REAL chain end to end, in-process:

    background run --persist_outputs--> REAL CAS (Postgres + R2) --get_node_outputs handler--> restored output

It uses the committed `cas_pool` (a real asyncpg pool over the throwaway Postgres
container) plus an in-memory FakeR2, persists via the same `node_outputs.persist_outputs`
the executor calls, then drives the REAL `workflow:get_node_outputs` handler — with the
real pool injected and the real access gate running against a real workflow row. No
store mocks. This is the only layer that exercises the CAS read-after-write that the
SDK's nodes.getOutput() depends on when a component is opened after a (background) run.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

from tests.fixtures.cas_fixtures import cas_pool, make_workflow, make_execution, TEST_USER_ID  # noqa: F401
from tests.mocks.mock_r2 import FakeR2, patch_r2
from tests.utils.base_handler_test import BaseHandlerTest
from utils import node_outputs
from wss.sender import send_event
from wss.receiver.event_routing import Handler
from wss.receiver.client_events import WorkflowGetNodeOutputsRequest


@pytest.mark.asyncio
class TestSdkRestoredOutputE2E(BaseHandlerTest):
    """Real CAS + real handler, no store mocks."""

    def _wire_handler(self, cas_pool, user_id=TEST_USER_ID):
        """Point the real WORKFLOW_MCP handler at the real CAS pool + a session."""
        handler = self.handlers.get(Handler.WORKFLOW_MCP)
        handler.get_pool = AsyncMock(return_value=cas_pool)
        self.main_api_sio.get_session = AsyncMock(return_value={'user_id': str(user_id)})
        return handler

    async def test_latest_output_roundtrips_through_the_real_handler(self, frontend_sio, sid, cas_pool):
        """A background run's output is read back, unmocked, via workflow:get_node_outputs."""
        with patch_r2(FakeR2()):
            wid = await make_workflow(cas_pool)
            eid = await make_execution(cas_pool, wid)
            # The executor's real write path.
            await node_outputs.persist_outputs(
                cas_pool, workflow_id=wid, execution_id=eid,
                node_outputs={"data-1": {"rows": [1, 2, 3]}},
                node_statuses={"data-1": {"status": "completed"}},
            )

            self._wire_handler(cas_pool)
            await send_event(frontend_sio, sid, WorkflowGetNodeOutputsRequest(
                request_id="rs-latest", workflow_id=str(wid),
            ))
            await asyncio.sleep(0.1)

        resp = self.get_main_api_emitted_events("response")[0][1]
        assert resp.get("error") is None
        assert resp["data"]["outputs"] == {"data-1": {"rows": [1, 2, 3]}}

    async def test_large_output_chunks_to_r2_and_reassembles_via_handler(self, frontend_sio, sid, cas_pool):
        """An over-threshold output is chunked into R2 on write and fully reassembled
        on the handler read — the real CAS chunk round-trip behind getOutput."""
        big = {"blob": list(range(5000)), "label": "report"}  # > chunk threshold → R2 chunk(s)
        with patch_r2(FakeR2()):
            wid = await make_workflow(cas_pool)
            eid = await make_execution(cas_pool, wid)
            await node_outputs.persist_outputs(
                cas_pool, workflow_id=wid, execution_id=eid,
                node_outputs={"data-1": big},
                node_statuses={"data-1": {"status": "completed"}},
            )

            self._wire_handler(cas_pool)
            await send_event(frontend_sio, sid, WorkflowGetNodeOutputsRequest(
                request_id="rs-big", workflow_id=str(wid), execution_id=str(eid),
            ))
            await asyncio.sleep(0.1)

        resp = self.get_main_api_emitted_events("response")[0][1]
        assert resp.get("error") is None
        assert resp["data"]["outputs"] == {"data-1": big}

    async def test_access_gate_denies_a_non_owner(self, frontend_sio, sid, cas_pool):
        """The real access check runs against the real workflow row: a different user
        gets an error and no output, even though the output exists in the store."""
        with patch_r2(FakeR2()):
            wid = await make_workflow(cas_pool)
            eid = await make_execution(cas_pool, wid)
            await node_outputs.persist_outputs(
                cas_pool, workflow_id=wid, execution_id=eid,
                node_outputs={"data-1": {"secret": True}},
            )

            self._wire_handler(cas_pool, user_id=uuid.uuid4())  # not the owner, no shares
            await send_event(frontend_sio, sid, WorkflowGetNodeOutputsRequest(
                request_id="rs-deny", workflow_id=str(wid),
            ))
            await asyncio.sleep(0.1)

        resp = self.get_main_api_emitted_events("response")[0][1]
        assert resp.get("error") == "No access to workflow"
        assert resp.get("data") in (None, {}, {"outputs": {}})
