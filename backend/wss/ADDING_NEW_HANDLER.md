# Adding a New Socket Handler

This guide walks through adding a new full-stack socket handler with bidirectional communication.

## 1. Backend: Define Event Models

### Client → Server Events (`wss/receiver/client_events.py`)
```python
class MyFeatureRequest(ClientEventBase):
    """Request from client to start my feature"""
    event_name: ClassVar[str] = "myfeature:start"
    
    user_input: str = Field(..., description="User's input")
    options: Dict[str, Any] = Field(default_factory=dict)
```

### Server → Client Events (`wss/sender/events.py`)
```python
class MyFeatureProgressEvent(BaseModel):
    """Progress update for my feature"""
    event_name: ClassVar[str] = "myfeature:progress"
    
    progress: int = Field(..., description="Progress percentage")
    status: str = Field(..., description="Current status")

class MyFeatureCompleteEvent(BaseModel):
    """Completion event for my feature"""
    event_name: ClassVar[str] = "myfeature:complete"
    
    result: str = Field(..., description="Final result")
```

## 2. Backend: Create Handler (`wss/handlers/myfeature_handler.py`)

```python
from typing import Dict, List
from wss.handlers.base_handler import Handler
from wss.sender import send_event, MyFeatureProgressEvent, MyFeatureCompleteEvent
from wss.receiver.client_events import MyFeatureRequest

class MyFeatureHandler(Handler):
    def __init__(self, sio):
        self.sio = sio

    def setup_user(self):
      """Called after user is authenticated"""
    
    def get_events(self) -> Dict[str, callable]:
        """Register which events this handler processes"""
        return {
            "myfeature:start": self.handle_start,
        }
    
    async def handle_start(self, sid: str, data: MyFeatureRequest) -> None:
        """Process the feature request"""
        # Send progress updates
        await send_event(self.sio, sid, MyFeatureProgressEvent(
            progress=50,
            status="Processing..."
        ))
        
        # Do work...
        result = f"Processed: {data.user_input}"
        
        # Send completion
        await send_event(self.sio, sid, MyFeatureCompleteEvent(
            result=result
        ))

    def cleanup_user(self):
      """Called after user disconnects"""
```

## 3. Backend: Register Handler (`wss/receiver/receiver.py`)

### Add to setup_config():
```python
def setup_config(self):
    # ... existing handlers ...
    myfeature_handler = MyFeatureHandler(self.sio)
    
    return SocketIOProxyConfig(
        event_handlers = {
            "API": {
                # ... existing events ...
                "myfeature:start": [myfeature_handler],  # Add your event
            },
        }
    )
```

### Add to event_models mapping:
```python
self.event_models: Dict[str, Type[BaseModel]] = {
    # ... existing events ...
    "myfeature:start": MyFeatureRequest,
}
```

### Add rate limits (optional):
```python
rate_limits=SocketIORateLimitConfig(
    per_event_rate_limits={
        # ... existing limits ...
        "myfeature:start": SocketIORateLimit(second=1, minute=10),
    }
)
```

## 4. Generate TypeScript Types

```bash
cd backend
python scripts/generate_socket_types.py
```

This generates:
- TypeScript interfaces for all events
- Companion objects with `.create()` methods
- EventRouting configuration

## 5. Frontend: Update Socket Listener Configuration

**Currently hardcoded in `frontend/app/lib/socket-receiver.ts`:**
```typescript
// Add your server->client events to the appropriate environment
API: {
  events: [
    // ... existing events ...
    'myfeature:progress',
    'myfeature:complete',
  ],
}
```

> ⚠️ **TODO**: This should be auto-generated from backend config

## 6. Frontend: Send Events

```typescript
import { sendEvent, MyFeatureRequest } from '~/lib/socket-sender';

// Send event to backend
const startMyFeature = (input: string) => {
  sendEvent(MyFeatureRequest.create({
    user_input: input,
    options: { advanced: true }
  }));
};
```

## 7. Frontend: Listen for Events

### React Hook Pattern
```typescript
import { useSocketEvent } from '~/hooks/useSocketEvent';

function MyComponent() {
  useSocketEvent('myfeature:progress', (data) => {
    console.log(`Progress: ${data.progress}% - ${data.status}`);
  });
  
  useSocketEvent('myfeature:complete', (data) => {
    console.log(`Complete: ${data.result}`);
  });
}
```

### Direct Subscription Pattern
```typescript
import { onSocketEvent } from '~/lib/socket-receiver';

const unsubscribe = onSocketEvent('myfeature:complete', (data) => {
  console.log(data.result);
});

// Later: unsubscribe();
```

## Environment Routing

Events are automatically routed based on where they're registered in `receiver.py`:
- Events in `"API"` block → API socket

## File Summary

### Backend Files to Modify:
1. `wss/receiver/client_events.py` - Define client→server events
2. `wss/sender/events.py` - Define server→client events  
3. `wss/handlers/your_handler.py` - Create handler (new file)
4. `wss/receiver/receiver.py` - Register handler & events
5. Run: `python scripts/generate_socket_types.py`

### Frontend Files to Modify:
1. `app/lib/socket-receiver.ts` - Add server events to config (temporary, should be generated)
2. Your components - Use `sendEvent()` and `useSocketEvent()`

## Testing

1. Check TypeScript compilation: `npm run typecheck`
2. Monitor backend logs for handler execution
3. Use browser DevTools Network tab to inspect WebSocket frames

## Common Patterns

### Request-Response with Progress
Perfect for long-running operations (file processing, AI generation, etc.)

### Streaming Updates
Send multiple events of the same type for real-time updates (chat, logs, etc.)

### Binary Data
Use `bytes` type in Python, will be `ArrayBuffer` in TypeScript:
```python
data: bytes = Field(..., description="Binary data")

# In get_typescript_type():
return "ArrayBuffer"
```

## Gotchas

1. **Event names must be unique** across all handlers
2. **Pydantic models need `event_name: ClassVar[str]`** for routing
3. **Rate limits are per-event**, not per-handler
4. **Binary data** needs special handling in client_events.py