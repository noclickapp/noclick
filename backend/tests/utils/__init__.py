"""Testing utilities for Socket.IO mock framework."""

from .mock_socketio import MockSocketIO, EventSpy, EmittedEvent, MockSession
from .proxy_utils import (
    create_test_proxy,
    create_fast_test_proxy,
    cleanup_test_proxy,
    SelectiveSocketIOProxy,
    StubHandler
)
from .test_helpers import (
    send_and_wait_response,
    batch_send_events,
    assert_event_sequence,
    simulate_rate_limited_requests,
    assert_error_response,
    validate_pydantic_event,
    create_mock_handler,
    register_handler_with_models
)
from .base_handler_test import BaseHandlerTest

__all__ = [
    # Mock server
    'MockSocketIO',
    'EventSpy', 
    'EmittedEvent',
    'MockSession',
    
    # Proxy utilities
    'create_test_proxy',
    'create_fast_test_proxy',
    'cleanup_test_proxy',
    'SelectiveSocketIOProxy',
    'StubHandler',
    
    # Test helpers
    'send_and_wait_response',
    'batch_send_events',
    'assert_event_sequence',
    'simulate_rate_limited_requests',
    'assert_error_response',
    'validate_pydantic_event',
    'create_mock_handler',
    'register_handler_with_models',
    
    # Base classes
    'BaseHandlerTest'
]