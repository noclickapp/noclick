"""
Testing utilities for selectively loading handlers in SocketIOProxy.

This module provides tools to test with the real SocketIOProxy infrastructure
while avoiding expensive handler imports that slow down tests.
"""

import asyncio
from typing import Dict, List, Optional, Callable, Any, Set
from unittest.mock import MagicMock, patch
import logging

from wss.schema import SocketIOHandler, SocketIOProxyConfig
from wss.receiver.event_routing import Handler
from wss.receiver.receiver import SocketIOProxy

logger = logging.getLogger(__name__)

class MockSocketIOProxy(SocketIOProxy):
    """
    Test-friendly SocketIOProxy that only loads specified handlers.
    
    This proxy allows selective handler initialization to avoid slow imports
    during testing while maintaining the real proxy infrastructure.
    """
    
    def __init__(self, sio, env: Optional[str] = None):
        """
        Initialize proxy with selective handler loading.

        Calls the parent's cheap constructor + manually runs the heavy
        setup synchronously here. The real proxy defers heavy init to an
        async setup() called from app_lifespan (after the forkserver
        warm-up); tests don't run a lifespan so we collapse the two phases.
        """
        super().__init__(sio, env)

        # Manually run what async setup() would do — tests don't have a
        # lifespan to await it from.
        from wss.schema import SocketIOProxyConfig, SocketIORateLimitConfig
        from wss.receiver.rate_limits import get_rate_limit_config
        from wss.receiver.rate_limiter import RateLimiter
        self.handler_instances = self._create_handler_instances()
        self.config = SocketIOProxyConfig(
            rate_limits=get_rate_limit_config(),
            event_handlers=self._build_event_handlers(self.handler_instances),
        )
        self.lifecycle_handlers = self._build_lifecycle_handlers(self.handler_instances)
        self.frontend_request_pydantic_models = self._build_frontend_request_pydantic_models()

        # Disable all rate limits for testing — overrides the get_rate_limit_config()
        # values just set above so per-event throttles don't fire under load tests.
        self.config.rate_limits = SocketIORateLimitConfig(
            per_event_rate_limits={}  # No per-event limits = unlimited
        )
        self.rate_limiter = RateLimiter(self.config.rate_limits)
    
    def _create_handler_instances(self):
        """
        Create partially mocked handler instances for the current environment.
        """
        from tests.mocks.mock_agent_handler import MockAgentHandler
        # Import the real workflow execution handler (doesn't need mocking)
        from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler
        from wss.handlers.workflow_handler import WorkflowHandler
        from wss.handlers.workflow_mcp_handler import WorkflowMCPHandler
        from wss.handlers.credentials_handler import CredentialsHandler
        from wss.handlers.share_handler import ShareHandler
        from wss.handlers.saved_output_handler import SavedOutputHandler
        from wss.handlers.resource_handler import ResourceHandler
        from wss.handlers.folder_handler import FolderHandler
        from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler
        from wss.handlers.agent_share_handler import AgentShareHandler

        agent_handler = MockAgentHandler(self.sio)
        workflow_execution_handler = WorkflowExecutionHandler(self.sio)
        workflow_handler = WorkflowHandler(self.sio)
        workflow_mcp_handler = WorkflowMCPHandler(self.sio)  # MCP handler for AI agent workflow manipulation
        credentials_handler = CredentialsHandler(self.sio)  # Real handler for credentials management
        share_handler = ShareHandler(self.sio)  # Real handler for resource sharing
        saved_output_handler = SavedOutputHandler(self.sio)  # Real handler for saved output management
        resource_handler = ResourceHandler(self.sio)  # Real handler for workflow resources
        folder_handler = FolderHandler(self.sio)  # Real handler for folder operations
        workflow_builder_handler = WorkflowBuilderHandler(self.sio)  # Real handler for AI builder + conversations
        agent_share_handler = AgentShareHandler(self.sio)  # Real handler for public agent share links

        return {
            Handler.AGENT: agent_handler,
            Handler.WORKFLOW_EXECUTION: workflow_execution_handler,
            Handler.WORKFLOW: workflow_handler,
            Handler.WORKFLOW_MCP: workflow_mcp_handler,
            Handler.CREDENTIALS: credentials_handler,
            Handler.SHARE: share_handler,
            Handler.SAVED_OUTPUT: saved_output_handler,
            Handler.RESOURCE: resource_handler,
            Handler.FOLDER: folder_handler,
            Handler.WORKFLOW_BUILDER: workflow_builder_handler,
            Handler.AGENT_SHARE: agent_share_handler,
        }
