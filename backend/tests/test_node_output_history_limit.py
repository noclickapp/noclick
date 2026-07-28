"""Regression tests for the output-history limit clamp.

`workflow:get_node_output_history` is reachable by API-key SDK clients
(utils/sdk_permissions.py), so `request.limit` is untrusted. It is bound into
both the per-key LATERAL and the outer LIMIT in read_node_output_history and
drives one R2 object-graph reassembly per returned row, so an unbounded value
is a remote fan-out lever. These tests pin the clamp at the handler.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# The handler imports `output_history` at call time, so the module must be
# imported here for patch() to resolve the attribute.
import utils.node_outputs  # noqa: F401
from wss.handlers.workflow_mcp_handler import (
    MAX_OUTPUT_HISTORY_LIMIT,
    WorkflowMCPHandler,
)
from wss.receiver.client_events import WorkflowGetNodeOutputHistoryRequest

WORKFLOW_ID = "11111111-1111-1111-1111-111111111111"


def _pool():
    """Pool whose `async with pool.acquire()` yields a dummy connection."""
    conn = MagicMock()
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=conn)
    acquire.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire)
    return pool


async def _effective_limit(requested: int) -> int:
    """Run the handler with `requested` and return the limit it passed down."""
    handler = WorkflowMCPHandler(sio=AsyncMock())
    handler._get_user_id = AsyncMock(return_value="user-1")
    handler.get_pool = AsyncMock(return_value=_pool())

    request = WorkflowGetNodeOutputHistoryRequest(
        request_id="r1", workflow_id=WORKFLOW_ID, node_id="n1", limit=requested
    )

    history = AsyncMock(return_value=[])
    with patch("wss.handlers.workflow_mcp_handler.check_resource_access",
               new=AsyncMock(return_value=MagicMock(has_access=True))), \
         patch("utils.node_outputs.output_history", new=history), \
         patch("wss.handlers.workflow_mcp_handler.send_event", new=AsyncMock()):
        await handler.get_node_output_history("sid-1", request)

    history.assert_awaited_once()
    # positional: (pool, workflow_id, node_id, limit)
    return history.await_args.args[3]


@pytest.mark.asyncio
class TestOutputHistoryLimitClamp:
    async def test_oversized_limit_is_clamped(self):
        assert await _effective_limit(10_000) == MAX_OUTPUT_HISTORY_LIMIT

    async def test_limit_at_cap_is_preserved(self):
        assert await _effective_limit(MAX_OUTPUT_HISTORY_LIMIT) == MAX_OUTPUT_HISTORY_LIMIT

    async def test_negative_limit_floors_to_one(self):
        # LIMIT -1 is a hard Postgres error, so the floor matters as much as the cap.
        assert await _effective_limit(-1) == 1

    async def test_zero_limit_floors_to_one(self):
        assert await _effective_limit(0) == 1

    async def test_default_limit_passes_through_unchanged(self):
        # Every in-repo caller sends 20; the clamp must not perturb them.
        assert await _effective_limit(20) == 20
