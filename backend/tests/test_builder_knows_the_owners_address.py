"""An edit tells the builder the user's own address, which a Send email step reaches with nothing to connect: told
"email me" without it, a build asked the owner which address to send to and left the email step out. Runs against
whichever builder the edition ships."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from coder.workflow.agentic.builder import AgenticBuilder

pytestmark = pytest.mark.asyncio


async def test_an_edit_tells_the_builder_the_users_own_address(monkeypatch):
    pool = MagicMock(fetchval=AsyncMock(return_value="owner@bakery.test"))
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    monkeypatch.setattr(AgenticBuilder, "_refresh_workflow_metadata", AsyncMock(), raising=False)
    builder = object.__new__(AgenticBuilder)
    builder.user_id, builder.platform_ops, builder.workflow_id = "user-1", None, None
    builder.session_log, builder.config, builder.generation_id = MagicMock(), MagicMock(), "gen"

    await builder.edit({"nodes": [], "edges": []}, "Every Monday email me the markets",
                       user_context={"workflow_id": "wf-1", "has_workflow": True, "source": "coordinator"})
    assert "owner@bakery.test" in builder.messages[0]["content"]
    assert pool.fetchval.await_args.args[1:] == ("user-1",)

    pool.fetchval.reset_mock()
    await builder.edit({"nodes": [], "edges": []}, "Every Monday email me the markets")
    assert "owner@bakery.test" not in builder.messages[0]["content"]
