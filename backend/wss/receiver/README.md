# SocketIO Proxy with Rate Limiting

This module provides a centralized proxy for handling incoming SocketIO events with built-in rate limiting functionality.

## Features

- **Event Routing**: Routes events to appropriate handlers based on environment (API, DATA_ENGINE)
- **Rate Limiting**: Sliding window rate limiter with per-second and per-minute limits
- **Per-Event Limits**: Configure specific limits for individual event types
- **User Isolation**: Rate limits are tracked per user session (sid)
- **Handler Selection**: Support for testing with limited handlers

## Usage

```python
from wss.receiver.receiver import SocketIOProxy

# Initialize the proxy with your SocketIO instance
proxy = SocketIOProxy(sio)

# The proxy automatically sets up:
# - Event routing based on SOCKET_PROXY_ENV
# - Rate limiting for all incoming events
# - Handler lifecycle management

# When user connects (called automatically on authentication)
await proxy.setup_user(sid)

# When user disconnects (called automatically)
await proxy.cleanup_user(sid)
```

## Configuration

Rate limits are configured in `proxy.py`'s `setup_config()` method:

```python
SocketIORateLimitConfig(
    per_event_rate_limits={
        "chat:message": SocketIORateLimit(second=5, minute=15),
        "chat:audio:chunk": SocketIORateLimit(second=100, minute=5000),
        # ... more event-specific limits
    }
)
```

## Rate Limiting Behavior



- Requests are tracked using a sliding window approach
- When limits are exceeded, an error event is emitted to the client
- Rate limit data is automatically cleaned up on user disconnect
- Both per-second and per-minute limits are enforced

### How Limits Work

**Per-Event Limits**: Each event type has its own counter. For example:
- `chat:message`: max 5/sec, 15/min
- `upload:chunk`: max 100/sec, 5000/min

Each event is tracked independently, and a request is blocked if it exceeds its specific event limit.

## Testing

Run the test suite:

```bash
pytest handlers/socketio/proxy/tests/test_rate_limiter.py -v
```

## Environment Variables

- `SOCKET_PROXY_ENV`: Determines which set of events/handlers to route (default: "API")