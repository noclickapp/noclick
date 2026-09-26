"""Owner alert tool contract, shared by hosted and exported agent runtimes."""
from unittest.mock import AsyncMock, MagicMock, patch

from nodes.agent.platform_tools import build_platform_tools, execute_platform_tool_from_ctx


async def test_both_agent_runtimes_preserve_owner_alert_arguments():
    from types import SimpleNamespace
    from nodes.agent.platform_tools import execute_message_coordinator

    pool = MagicMock()
    args = {"message": "An invoice needs attention", "purpose": "owner_alert", "channel": "whatsapp"}
    node = SimpleNamespace(user_id="u1", workflow_id="w1", node_id="n1", conversation_id="c1")
    with patch("utils.database_pool.get_native_pool", return_value=pool), patch(
        "coder.coordinator.signals.record_agent_message", new=AsyncMock(return_value={"success": True}),
    ) as record:
        await execute_message_coordinator(node, args)
        sdk_args = record.call_args
        await execute_platform_tool_from_ctx({"tool_type": "message_coordinator", "user_id": "u1",
            "workflow_id": "w1", "agent_node_id": "n1", "conversation_id": "c1"}, args, pool)
        assert record.call_args == sdk_args
    assert sdk_args.kwargs["purpose"] == "owner_alert"
    assert sdk_args.kwargs["channel"] == "whatsapp"
    # CLI discovery uses the same schema as SDK tools, not an empty wrapper.
    param, config = next(pair for pair in build_platform_tools(False)
                         if pair[0]["function"]["name"] == "message_coordinator")
    assert "owner_alert" in config["_parameters"]["properties"]["purpose"]["enum"]
    assert config["_parameters"] == param["function"]["parameters"]
