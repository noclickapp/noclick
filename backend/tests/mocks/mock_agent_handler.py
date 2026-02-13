"""
Mock AgentHandler for testing.

This mock handler extends the real AgentHandler but patches litellm
to avoid actual LLM API calls while keeping all other logic intact.
"""

# Import mocks BEFORE importing modules that use them
from .mock_stripe import mock_stripe  # Prevents Stripe API calls

# Apply litellm patch BEFORE importing AgentHandler
# This ensures litellm is mocked before any module can import it
from .mock_litellm import patch_litellm_components
patch_litellm_components()

from wss.handlers.agent_handler import AgentHandler
import logging

logger = logging.getLogger(__name__)


class MockAgentHandler(AgentHandler):
    """
    Mock version of AgentHandler that patches litellm completion.
    
    This allows testing the full agent flow without real LLM API calls,
    while keeping all other logic (session management, event handling,
    workspace setup, etc.) intact.
    """
    
    def __init__(self, sio, rclone_handler=None, proxy=None):
        """Initialize MockAgentHandler."""
        super().__init__(sio, rclone_handler, proxy)
        logger.debug("MockAgentHandler initialized with pre-patched litellm")
