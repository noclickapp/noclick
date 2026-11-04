"""
Live check of the Slack Web API node against Slack itself, with no credential:
an invalid token must come back as Slack's own auth error.

The operations against a real workspace live in test_slack_node_integration.py
(SLACK_TEST_BOT_TOKEN); the mocked ones in test_slack_node_mock.py.
"""

import pytest

from nodes.slack_node import (
    SlackNode,
    SlackNodeConfig,
    SlackBotTokenCredential,
    SlackListConversationsConfig,
)


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_invalid_token(self):
        """Test handling of invalid token."""
        config = SlackListConversationsConfig()
        credentials = SlackBotTokenCredential(bot_token="xoxb-invalid-token")
        node_config = SlackNodeConfig(config=config, credentials=credentials)
        node = SlackNode(
            node_id="test-node",
            node_type="automation-slack",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["error"] in ["invalid_auth", "not_authed"]
