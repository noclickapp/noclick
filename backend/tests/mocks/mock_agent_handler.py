"""
Mock AgentHandler for testing.

This mock handler extends the real AgentHandler but patches litellm
to avoid actual LLM API calls while keeping all other logic intact.
"""

from wss.handlers.agent_handler import AgentHandler
from .mock_litellm import patch_litellm_components
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
        """Initialize with litellm patching."""
        super().__init__(sio, rclone_handler, proxy)
        self._setup_patches()
    
    def _setup_patches(self):
        """Start patching litellm completion."""
        patch_litellm_components()
