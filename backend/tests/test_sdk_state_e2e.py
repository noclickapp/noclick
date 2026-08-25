"""Real-stack test for the SDK state store after the dual-store fix.

The SDK's state.get/set/delete/keys now route (on BOTH transports) through the
backend workflow:state:* handlers, which persist in workflow_node_state — the same
store state-manager node execution uses. This exercises those real handlers against
a real Postgres + codec pool, including the new delete-on-null behavior that makes
state.delete actually remove the key (a plain merge left a {key: null} tombstone).
"""

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

from tests.fixtures.cas_fixtures import codec_pool, TEST_USER_ID  # noqa: F401
from tests.utils.base_handler_test import BaseHandlerTest
from wss.sender import send_event
from wss.receiver.event_routing import Handler
from wss.receiver.client_events import (
    WorkflowStateGetRequest,
    WorkflowStateSetRequest,
    WorkflowStateKeysRequest,
)


@pytest.mark.asyncio
class TestSdkStateE2E(BaseHandlerTest):
    async def _make_workflow(self, pool) -> uuid.UUID:
        wid = uuid.uuid4()
        async with pool.acquire() as c:
            await c.execute(
                "INSERT INTO workflows (id, owner_id, name, workflow) VALUES ($1,$2,'s',$3)",
                wid, TEST_USER_ID,
                {"nodes": [{"id": "sm-1", "type": "state-manager"}], "edges": []},
            )
        return wid

    def _wire(self, pool):
        handler = self.handlers.get(Handler.WORKFLOW)
        handler.get_pool = AsyncMock(return_value=pool)
        self.main_api_sio.get_session = AsyncMock(return_value={'user_id': str(TEST_USER_ID)})

    async def _latest_response(self):
        await asyncio.sleep(0.1)
        return self.get_main_api_emitted_events("response")[-1][1]

    async def test_set_get_keys_roundtrip_then_delete_removes_key(self, frontend_sio, sid, codec_pool):
        wid = await self._make_workflow(codec_pool)
        self._wire(codec_pool)

        await send_event(frontend_sio, sid, WorkflowStateSetRequest(
            request_id="s1", workflow_id=str(wid), key="count", value=7))
        r = await self._latest_response()
        assert r.get("error") is None and r["data"].get("success") is True

        await send_event(frontend_sio, sid, WorkflowStateGetRequest(
            request_id="g1", workflow_id=str(wid), key="count"))
        assert (await self._latest_response())["data"]["value"] == 7

        await send_event(frontend_sio, sid, WorkflowStateKeysRequest(
            request_id="k1", workflow_id=str(wid)))
        assert (await self._latest_response())["data"]["keys"] == ["count"]

        # delete via null value — must REMOVE the key, not leave {count: null}
        await send_event(frontend_sio, sid, WorkflowStateSetRequest(
            request_id="d1", workflow_id=str(wid), key="count", value=None))
        await self._latest_response()

        await send_event(frontend_sio, sid, WorkflowStateKeysRequest(
            request_id="k2", workflow_id=str(wid)))
        assert (await self._latest_response())["data"]["keys"] == []

        await send_event(frontend_sio, sid, WorkflowStateGetRequest(
            request_id="g2", workflow_id=str(wid), key="count"))
        assert (await self._latest_response())["data"]["value"] is None

    async def test_set_requires_edit_access(self, frontend_sio, sid, codec_pool):
        wid = await self._make_workflow(codec_pool)
        self._wire(codec_pool)
        self.main_api_sio.get_session = AsyncMock(return_value={'user_id': str(uuid.uuid4())})  # not owner

        await send_event(frontend_sio, sid, WorkflowStateSetRequest(
            request_id="s-deny", workflow_id=str(wid), key="x", value=1))
        r = await self._latest_response()
        assert r.get("error")  # access denied, not a silent success
