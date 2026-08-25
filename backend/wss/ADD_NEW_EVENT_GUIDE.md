# Complete Guide to Adding a New Socket Event

This guide documents all the files that need to be modified when adding a new socket event in both backend and frontend, using the `cache_valtio:state` event as a complete example.

## Overview

When adding a new socket event, you need to modify files in both the backend and frontend to:
1. Define the event schema (backend)
2. Create/modify handlers (backend)
3. Register the event routing (backend)
4. Register the event listener (frontend)
5. Generate TypeScript types (frontend)
6. Set up event handlers (frontend)

## Backend Changes

### 1. Define the Event Schema
**File:** `backend/wss/sender/events.py`

Add your event class definition:
```python
class CacheValtioStateEvent(BaseModel):
    """Event description"""
    event_name: ClassVar[str] = "cache_valtio:state"
    state_update: List[int]  # Your event data fields
```

### 2. Export the Event
**File:** `backend/wss/sender/__init__.py`

Add your event to the imports and exports:
```python
from .events import CacheValtioStateEvent

__all__ = [
    # ... other events
    "CacheValtioStateEvent",
]
```

### 3. Create the Handler (if needed)
**File:** `backend/wss/handlers/your_handler.py`

Create a new handler that extends `SocketIOHandler`:
```python
from wss.schema import SocketIOHandler
from wss.sender import send_event, YourEvent

class YourHandler(SocketIOHandler):
    def get_events(self):
        return {
            "your:event": self.handle_your_event
        }
    
    async def setup_user(self, sid: str) -> None:
        # Called when user connects
        pass
    
    async def cleanup_user(self, sid: str) -> None:
        # Called when user disconnects
        pass
```

### 4. Register the Handler
**File:** `backend/wss/receiver/receiver.py`

#### For Event Handlers:
Import and initialize your handler in the `__init__` method:
```python
from wss.handlers.your_handler import YourHandler

# In __init__ method:
your_handler = YourHandler(self.sio)
```

Add to the handlers dictionary (around line 235-250):
```python
handlers = {
    "API": [
        # ... other handlers
        your_handler,
    ],
    # Other environments...
}
```

#### For Lifecycle-Only Handlers:
If your handler only needs lifecycle methods (setup_user/cleanup_user) but doesn't handle events directly:
```python
# In __init__ method:
your_handler = YourHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None

# Add to lifecycle_handlers (around line 293):
self.lifecycle_handlers = {
    "API": [sandbox_handler] + ([your_handler] if your_handler else []),
}
```

### 5. Update Event Routing (if needed)
**File:** `backend/wss/receiver/event_routing.py`

If your event needs special routing to a specific environment:
```python
EVENT_ROUTING = {
    # ... other events
    "your:event": "API",
}
```

## Frontend Changes

### 6. Add Event to Socket Receiver
**File:** `frontend/app/lib/socket-receiver.ts`

Add your event to the appropriate socket configuration (around lines 58-72):
```typescript
const config: SocketConfig = {
    API: {
        url: import.meta.env.VITE_API_URL,
        events: [
            // ... other events
            'cache_valtio:state',  // Add your event here
        ],
        // ... rest of config
    },
    // ... other environments
}
```

### 7. Generate TypeScript Types
After adding the backend event definition, run:
```bash
cd frontend
npm run generate:types
```

This will update `frontend/app/types/socket-events.generated.ts` with the new event types.

### 8. Add Event Listener
**File:** Your component or service file (e.g., `frontend/app/state.ts`)

Use the `onSocketEvent` helper to listen for the event:
```typescript
import { onSocketEvent } from './lib/socket-receiver';

// Set up listener (preferably at module initialization for timing-critical events)
const unsubscribe = onSocketEvent('cache_valtio:state', (data: number[]) => {
    console.log('Received event data:', data);
    // Handle the event
});

// Clean up when done (e.g., on component unmount)
unsubscribe();
```

## Frontend Integration Patterns

### Early Connection Events
For events sent immediately on connection:

```typescript
// ✅ GOOD - Set up listener at module initialization
const unsubscribe = onSocketEvent('cache_valtio:state', (data) => {
    // Handle early event
});

socketReceiver.subscribeConnection('API', (status) => {
    if (status) {
        // Connection established
    }
});
```

```typescript
// ❌ BAD - Might miss the event
socketReceiver.subscribeConnection('API', (status) => {
    if (status) {
        // Event might already be sent!
        onSocketEvent('cache_valtio:state', handler);
    }
});
```

### Request-Response Pattern
For correlated request-response:

```typescript
import { sendEventAsync } from '~/lib/socket-sender';

// Send request and await response
const response = await sendEventAsync({
    event_name: 'your:request',
    request_id: crypto.randomUUID(),
    data: requestData
});
```

### React Component Integration
In React components:

```typescript
function MyComponent() {
    useEffect(() => {
        const unsubscribe = onSocketEvent('your:event', (data) => {
            // Update component state
        });
        
        return () => {
            unsubscribe(); // Clean up on unmount
        };
    }, []);
}
```

### State Management Integration
With Valtio state:

```typescript
import { state, cachedb } from '~/state';

// For local-only state
onSocketEvent('your:event', (data) => {
    state.someValue = data.value;
});

// For cached/synced state
onSocketEvent('your:event', (data) => {
    cachedb.someValue = data.value;
});
```

## Important Considerations

### Thread Safety (Backend)
If working with YJS/YDoc objects in Python:
- **DO NOT** pass YDoc/YMap objects to async tasks or different threads
- **DO** encode the state immediately and pass bytes instead
- Example of the issue and fix:
```python
# ❌ WRONG - causes thread safety error
asyncio.create_task(self.process_later(synced_state))

# ✅ CORRECT - encode first, then pass bytes
state_bytes = Y.encode_state_as_update(synced_state.ydoc)
asyncio.create_task(self.process_later(state_bytes))
```

### Event Timing (Frontend)
For events sent immediately on connection (like cache restoration):
- Set up listeners **before** or **immediately after** socket initialization
- Don't set up listeners inside connection callbacks if you need to catch early events
- Example:
```typescript
// ✅ GOOD - listener ready before connection
const unsubscribe = onSocketEvent('cache_valtio:state', handler);

socketReceiver.subscribeConnection('API', (status) => {
    // Connection logic here
});

// ❌ BAD - might miss early events
socketReceiver.subscribeConnection('API', (status) => {
    if (status) {
        // Event might be sent before this runs!
        onSocketEvent('cache_valtio:state', handler);
    }
});
```

### Lifecycle Handlers
Handlers can implement lifecycle methods that are called on user connect/disconnect:
- `setup_user(sid)` - Called after authentication succeeds
- `cleanup_user(sid)` - Called on disconnect

These are useful for:
- Initializing user-specific state
- Cleaning up resources
- Sending initial data on connection

## Event Routing

Events are automatically routed based on backend configuration:
- `API` environment: Main application events

The routing is defined in:
- Backend: `wss/receiver/event_routing.py`
- Frontend: `EventRouting` in `types/socket-events.generated.ts`

## Common Issues & Solutions

### Event Not Received (Frontend)
1. Check event is in socket-receiver.ts events list
2. Verify backend is sending to correct socket environment
3. Check browser console for connection status
4. Ensure listener is set up before event is sent

### TypeScript Errors
1. Run `npm run generate:types` after backend changes
2. Check event name matches exactly (case-sensitive)
3. Verify import paths are correct

### Files Modified

#### Backend:
1. **`backend/wss/sender/events.py`** - Event definition
   ```python
   class CacheValtioStateEvent(BaseModel):
       event_name: ClassVar[str] = "cache_valtio:state"
       state_update: List[int]
   ```

2. **`backend/wss/sender/__init__.py`** - Event export
   ```python
   from .events import CacheValtioStateEvent
   ```

3. **`backend/wss/handlers/cache_valtio_handler.py`** - Handler implementation
   ```python
   class CacheValtioHandler(SocketIOHandler):
       async def setup_user(self, sid: str):
           # Restore cached state from Redis
           event = CacheValtioStateEvent(state_update=list(cached_state))
           await send_event(self.sio, sid, event)
   ```

4. **`backend/wss/handlers/ypy_handler.py`** - Helper methods for state access
   ```python
   async def cleanup_synced_state(self, sid: str):
       # Helper to clean up YJS state
   ```

5. **`backend/wss/receiver/receiver.py`** - Handler registration
   ```python
   cache_valtio_handler = CacheValtioHandler(self.sio, ypy_handler)
   self.lifecycle_handlers = {
       "API": [sandbox_handler] + ([cache_valtio_handler] if cache_valtio_handler else [])
   }
   ```

#### Frontend:
6. **`frontend/app/lib/socket-receiver.ts`** - Event registration
   ```typescript
   events: [
       'cache_valtio:state',
   ]
   ```

7. **`frontend/app/state.ts`** - Event listener
   ```typescript
   const unsubscribeCacheRestore = onSocketEvent('cache_valtio:state', (data: number[]) => {
       const update = new Uint8Array(data);
       Y.applyUpdate(ydoc, update);
   });
   ```

8. **`frontend/app/types/socket-events.generated.ts`** - Auto-generated types
   ```typescript
   export interface ServerToClientEvents {
       'cache_valtio:state': (data: number[]) => void;
   }
   ```

## Summary

Adding a new socket event requires coordination between backend and frontend:
1. Define event schema in backend
2. Create handler logic
3. Register handler and routing
4. Add event to frontend socket configuration
5. Generate TypeScript types
6. Implement frontend listener

Key pitfalls to avoid:
- Thread safety issues with YJS objects
- Missing event registration in socket-receiver.ts
- Timing issues with early connection events
- Forgetting to generate TypeScript types