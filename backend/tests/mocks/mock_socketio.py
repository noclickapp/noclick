"""
Simplified Mock Socket.IO implementation for testing.

This module provides a lightweight mock of socketio.AsyncServer
for testing socket handlers with linked socket pairs.
"""

import asyncio
import re
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import logging
import inspect

logger = logging.getLogger(__name__)


class MockSocketIO:
    """
    Simplified mock implementation of socketio.AsyncServer for testing.
    
    Features:
    - Create linked socket pairs via create_socketio_connection()
    - Pattern matching for event handlers (exact match, wildcard "*", regex)
    - Simple event emission tracking
    - Basic session management
    """
    
    def __init__(self, role: str = 'server'):
        self.role = role  # 'client' or 'server' - determines handler calling convention
        self.handlers: Dict[str, List[Callable]] = defaultdict(list)
        self.partner: Optional['MockSocketIO'] = None  # Linked MockSocketIO instance
        self.emitted_events: List[Tuple[str, Any, Optional[str]]] = []  # (event, data, to)
        self.sessions: Dict[str, Dict[str, Any]] = {}  # sid -> session data
        
    # Core Methods
    
    async def emit(
        self,
        event: str,
        data: Any = None,
        to: Optional[str] = None,
        room: Optional[str] = None,
        **kwargs
    ) -> None:
        """
        Emit an event. If linked to a partner, trigger their handlers.

        Args:
            event: Event name
            data: Event data
            to: Target session ID (optional)
            room: Target room (treated same as 'to' for simplicity)
        """
        # Record the emission
        target = to or room
        self.emitted_events.append((event, data, target))

        logger.info(f"[MockSocketIO:{self.role}] Emitted event={event} to target={target or 'all'}, has_partner={self.partner is not None}")

        # Validate that sandbox-sid targets exist (to catch cross-container MCP bugs)
        # Real Socket.IO silently ignores emits to non-existent sids
        if target and target.startswith('sandbox-sid') and target not in self.sessions:
            logger.warning(f"[MockSocketIO:{self.role}] Cannot emit to sandbox {target} - session not found on this server. Available sessions: {list(self.sessions.keys())}")
            return

        # If we have a partner, trigger their handlers
        if self.partner:
            logger.info(f"[MockSocketIO:{self.role}] Forwarding {event} to partner ({self.partner.role})")
            await self.partner._handle_incoming_event(event, target or 'mock-sid', data)
        else:
            logger.warning(f"[MockSocketIO:{self.role}] No partner to forward {event} to!")
    
    async def _handle_incoming_event(self, event: str, sid: str, data: Any) -> None:
        """
        Handle an incoming event from the partner socket.

        Matches handlers based on:
        1. Exact event name match
        2. Wildcard "*" handlers
        3. Regex pattern matching

        Calls handlers based on socket role (client vs server):
        - Server handlers receive sid, client handlers don't
        - Wildcard handlers receive event name as first param
        """
        logger.info(f"[MockSocketIO:{self.role}] _handle_incoming_event called: event={event}, sid={sid}, registered_handlers={list(self.handlers.keys())}")

        # Collect all matching handlers with their event pattern
        handlers_to_call = []

        # Check exact match
        if event in self.handlers:
            logger.info(f"[MockSocketIO:{self.role}] Found {len(self.handlers[event])} exact match handlers for {event}")
            for handler in self.handlers[event]:
                handlers_to_call.append((handler, event))  # Store pattern with handler

        # Check wildcard handlers
        if '*' in self.handlers:
            logger.info(f"[MockSocketIO:{self.role}] Found {len(self.handlers['*'])} wildcard handlers")
            for handler in self.handlers['*']:
                handlers_to_call.append((handler, '*'))  # Mark as wildcard
        else:
            logger.warning(f"[MockSocketIO:{self.role}] No wildcard handlers registered!")

        # Check regex patterns (keys starting with 'regex:')
        for pattern_key, pattern_handlers in self.handlers.items():
            if pattern_key.startswith('regex:'):
                pattern = pattern_key[6:]  # Remove 'regex:' prefix
                if re.match(pattern, event):
                    for handler in pattern_handlers:
                        handlers_to_call.append((handler, pattern_key))  # Store pattern

        logger.info(f"[MockSocketIO:{self.role}] Found {len(handlers_to_call)} handlers to call for {event}")

        # Call all matching handlers with proper signature based on role
        for handler, pattern in handlers_to_call:
            logger.info(f"[MockSocketIO:{self.role}] Calling handler for pattern={pattern}")
            try:
                if self.role == 'client':
                    # Client handlers never receive sid
                    if pattern == '*':
                        # Wildcard: handler(event, *args) where args is typically just data
                        await handler(event, data)
                    else:
                        # Specific event: handler(data) or handler(*args)
                        # Try to inspect signature to handle both cases
                        sig = inspect.signature(handler)
                        params = list(sig.parameters.keys())
                        if len(params) == 2 and params[0] == 'sid':
                            # Legacy handler expecting (sid, data) - provide compatibility
                            await handler(sid, data)
                        else:
                            # Standard client handler expecting just data
                            await handler(data)
                else:  # role == 'server'
                    # Server handlers always receive sid
                    if pattern == '*':
                        # Wildcard: handler(event, sid, data)
                        await handler(event, sid, data)
                    else:
                        # Specific event: handler(sid, data)
                        await handler(sid, data)
            except Exception as e:
                import traceback
                logger.error(f"Error in handler for event '{event}': {e}")
                logger.error(f"Traceback:\n{traceback.format_exc()}")
                raise
    
    def on(self, event: str, handler: Optional[Callable] = None):
        """
        Register an event handler.
        
        Supports:
        - Exact event name matching
        - Wildcard "*" to match all events
        - Regex patterns with "regex:" prefix (e.g., "regex:user_.*")
        
        Can be used as a decorator or directly.
        """
        if handler is None:
            # Decorator usage
            def decorator(func):
                self.handlers[event].append(func)
                return func
            return decorator
        else:
            # Direct registration
            self.handlers[event].append(handler)
            return handler
    
    @classmethod
    def create_socketio_connection(cls) -> Tuple['MockSocketIO', 'MockSocketIO']:
        """
        Create a pair of linked MockSocketIO instances.
        
        When one emits an event, it triggers handlers on the other.
        This simulates a client-server socket connection.
        
        Returns:
            Tuple of (client_sio, server_sio) that are linked together
        """
        client_sio = cls(role='client')
        server_sio = cls(role='server')
        
        # Link them together
        client_sio.partner = server_sio
        server_sio.partner = client_sio
        
        logger.debug("[MockSocketIO] Created linked socket pair (client + server)")
        
        return client_sio, server_sio
    
    # Session Management (Simplified)
    
    async def save_session(self, sid: str, session_data: Dict[str, Any]):
        """Save session data for a client."""
        self.sessions[sid] = session_data
    
    async def get_session(self, sid: str) -> Optional[Dict[str, Any]]:
        """Get session data for a client."""
        return self.sessions.get(sid)
    
    def create_session(self, sid: str = "test-sid", **kwargs) -> str:
        """
        Create a simple session for testing.
        Returns the session ID.
        """
        self.sessions[sid] = kwargs
        return sid
    
    # Testing Helpers
    
    def get_emitted_events(self, event_name: str = None, to: str = None) -> List[Tuple[str, Any, Optional[str]]]:
        """Get emitted events matching the criteria."""
        events = self.emitted_events
        
        if event_name:
            events = [(e, d, t) for e, d, t in events if e == event_name]
        if to:
            events = [(e, d, t) for e, d, t in events if t == to]
            
        return events  # [(event_name, data, to)]
    
    def clear_emitted_events(self):
        """Clear all recorded emitted events."""
        self.emitted_events = []
    
    def assert_event_emitted(self, event_name: str, to: str = None):
        """Assert that an event was emitted."""
        events = self.get_emitted_events(event_name, to)
        assert events, f"No event '{event_name}' emitted to {to or 'any'}"
    
    def assert_no_event(self, event_name: str, to: str = None):
        """Assert that no event was emitted."""
        events = self.get_emitted_events(event_name, to)
        assert not events, f"Unexpected event '{event_name}' emitted to {to or 'any'}"
    
    # Compatibility methods for existing code
    async def send(self, data: Any, to: Optional[str] = None, **kwargs):
        """Send a message event (compatibility method)."""
        await self.emit('message', data, to=to, **kwargs)
    
    async def connect(self, url: str = None, **kwargs):
        """Mock connect method - immediately succeeds."""
        logger.debug(f"[MockSocketIO] Mock connect to {url}")
        return True
    
    async def disconnect(self):
        """Mock disconnect method."""
        logger.debug("[MockSocketIO] Mock disconnect")
        return True
    
    def start_background_task(self, target, *args, **kwargs):
        """
        Mock implementation of Socket.IO's start_background_task.

        In real Socket.IO, this schedules a background task. In tests, we
        schedule it as an asyncio task but don't wait for it (fire-and-forget).
        This prevents usage_tracker errors when it tries to send events in background.

        Args:
            target: Coroutine function or regular function to run
            *args: Positional arguments to pass to target
            **kwargs: Keyword arguments to pass to target

        Returns:
            The scheduled task (or None for sync functions)
        """
        import asyncio
        import inspect

        # Call the target with provided arguments
        result = target(*args, **kwargs)

        # If it's a coroutine, schedule it as a background task
        if inspect.iscoroutine(result):
            try:
                task = asyncio.create_task(result)
                logger.debug(f"[MockSocketIO] Scheduled background task: {target.__name__}")
                return task
            except RuntimeError:
                # No event loop running - just ignore
                logger.debug(f"[MockSocketIO] No event loop for background task: {target.__name__}")
                return None
        else:
            # Synchronous function - already executed
            logger.debug(f"[MockSocketIO] Executed sync background task: {target.__name__}")
            return None

    @property
    def connected(self):
        """Mock connected property - always True for testing."""
        return True