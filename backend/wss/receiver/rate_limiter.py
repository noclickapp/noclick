import time
from collections import defaultdict, deque
from typing import Dict, Optional, Tuple
import asyncio
from wss.schema import SocketIORateLimit, SocketIORateLimitConfig


class RateLimiter:
    """
    Sliding window rate limiter for SocketIO events.
    Tracks requests per user (sid) per event with configurable time windows.
    
    Rate limiting behavior:
    - Per-event limits: Applied to each specific event type individually
    """
    
    def __init__(self, config: SocketIORateLimitConfig):
        self.config = config
        # Structure: {sid: {event: deque(timestamps)}}
        self.requests: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(deque))
        # Lock for thread-safe operations
        self.lock = asyncio.Lock()
    
    async def check_rate_limit(self, sid: str, event: str) -> Tuple[bool, Optional[str]]:
        """
        Check if a request is allowed based on rate limits.
        Returns (allowed, error_message)
        """
        async with self.lock:
            current_time = time.time()
            
            # Get or create request queue for this sid/event
            event_queue = self.requests[sid][event]
            
            # Clean up old requests outside the minute window
            minute_ago = current_time - 60
            while event_queue and event_queue[0] < minute_ago:
                event_queue.popleft()
            
            # Get rate limit for this event
            event_limit = self.config.per_event_rate_limits.get(event)
            
            # Check event-specific rate limit
            if event_limit:
                if not self._check_limit(event_queue, current_time, event_limit):
                    return False, f"Rate limit exceeded for event '{event}': max {event_limit.second}/sec or {event_limit.minute}/min"
            
            # Request is allowed, add timestamp
            event_queue.append(current_time)
            return True, None
    
    def _check_limit(self, queue: deque, current_time: float, limit: SocketIORateLimit) -> bool:
        """Check if adding a new request would exceed the rate limit."""
        # Count requests in the last second
        second_ago = current_time - 1
        second_count = sum(1 for ts in queue if ts >= second_ago)
        
        if second_count >= limit.second:
            return False
        
        # Count requests in the last minute
        minute_count = len(queue)  # Already filtered to last minute
        
        if minute_count >= limit.minute:
            return False
        
        return True
    
    async def cleanup_user(self, sid: str):
        """Remove all tracking data for a disconnected user."""
        async with self.lock:
            if sid in self.requests:
                del self.requests[sid]
    
    async def get_usage_stats(self, sid: str) -> Dict[str, Dict[str, int]]:
        """Get current usage statistics for a user."""
        async with self.lock:
            current_time = time.time()
            stats = {}
            
            if sid not in self.requests:
                return stats
            
            for event, queue in self.requests[sid].items():
                # Clean up old entries
                minute_ago = current_time - 60
                while queue and queue[0] < minute_ago:
                    queue.popleft()
                
                second_ago = current_time - 1
                second_count = sum(1 for ts in queue if ts >= second_ago)
                minute_count = len(queue)
                
                stats[event] = {
                    "per_second": second_count,
                    "per_minute": minute_count
                }
            
            return stats