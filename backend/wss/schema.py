from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Callable, List, Any


class SocketIOHandler(ABC):
    """Abstract base class for all SocketIO handlers."""
    
    def __init__(self, sio):
        """Initialize handler with SocketIO instance."""
        self.sio = sio
    
    @abstractmethod
    def get_events(self) -> Dict[str, Callable]:
        """
        Set up relevant events for the handler. The method returns a dictionary of event names
        to their corresponding async handler methods.
        This method should register all event handlers using @self.sio.on() decorators.
        """
        pass
    
    async def setup_user(self, sid: str) -> None:
        """
        Initialize resources for user after auth is verified, this is only called
        when a client is authenticated.
        Override this method if your handler needs to perform setup on connection.
        """
        pass
    
    async def cleanup_user(self, sid: str) -> None:
        """
        Cleanup the resources for a user. This is only called when a client disconnects.
        Override this method if your handler needs to perform cleanup on disconnect.
        """
        pass


@dataclass
class SocketIORateLimit:
    """Rate limit configuration for time windows."""
    second: int # limit number of calls per second
    minute: int # limit number of calls per minute


@dataclass
class SocketIORateLimitConfig:
    """
    Configuration for rate limiting across different events.
    
    per_event_rate_limits: Applies to each specific event type individually
    """
    per_event_rate_limits: Dict[str, SocketIORateLimit] = field(default_factory=dict)


@dataclass
class SocketIOProxyConfig:
    """Configuration for the SocketIO proxy system."""
    rate_limits: Dict[str, Dict[str, int]] = field(default_factory=dict)
    # event_name: [handler_instance, handler_instance, ...]
    event_handlers: Dict[str, Dict[str, List[SocketIOHandler]]] = field(default_factory=dict)