# Adding a Real-time MCP Event

This guide explains how to add a new MCP tool that triggers real-time frontend updates via the dual-delivery mechanism. The dual-delivery pattern sends responses to both the MCP client (Claude) and the connected frontend browser for instant UI updates.

## Overview

When an MCP tool modifies workflow state (adding nodes, edges, updating configs, etc.), the frontend needs to reflect these changes immediately. The dual-delivery mechanism accomplishes this by:

1. Backend processes the MCP request and saves to database
2. Backend sends response to MCP client (for Claude to see the result)
3. Backend simultaneously sends the same response to the frontend via Socket.IO
4. Frontend listener receives the event and updates React state

## Files to Modify

| File | Purpose |
|------|---------|
| `backend/wss/receiver/client_events.py` | Define request schema |
| `backend/wss/sender/responses.py` | Define response schema with dual-delivery config |
| `backend/wss/receiver/event_routing.py` | Route event to handler |
| `backend/wss/handlers/workflow_mcp_handler.py` | Implement handler logic |
| `backend/mcp_adapter/tools.py` | Define MCP tool interface |
| `frontend/app/lib/socket/config.ts` | Register frontend event listener |
| `frontend/app/types/socket-events.generated.ts` | Add TypeScript types |
| `frontend/app/hooks/useWorkflowMCPHandler.ts` | Handle event and update UI state |

---

## Step-by-Step Guide

### Step 1: Define the Request Event (Backend)

**File:** `backend/wss/receiver/client_events.py`

```python
class WorkflowMCPYourFeatureRequest(ClientEventBase):
    """Request to do something with the workflow."""
    event_name: ClassVar[str] = "workflow:mcp:your_feature"

    workflow_id: str = Field(..., description="UUID of the workflow")
    # Add your parameters here
    some_param: str = Field(..., description="Description of the parameter")
    optional_param: Optional[str] = Field(None, description="Optional parameter")
```

**Key points:**
- Extend `ClientEventBase`
- Use `ClassVar[str]` for `event_name` (naming convention: `workflow:mcp:snake_case`)
- Use Pydantic `Field` with descriptions for MCP tool documentation

---

### Step 2: Define the Response Model (Backend)

**File:** `backend/wss/sender/responses.py`

```python
class WorkflowMCPYourFeatureResponse(BaseModel):
    """Response for workflow:mcp:your_feature - dual-delivered to frontend"""

    # CRITICAL: This enables dual-delivery to frontend
    mcp_config: ClassVar[dict] = {
        "notify_frontend": True,
        "frontend_event_name": "mcp:workflow:your_feature:response"
    }

    success: bool = Field(..., description="Whether the operation succeeded")
    workflow_id: str = Field(..., description="ID of the modified workflow")
    # Add response data fields
    result_data: Optional[Dict[str, Any]] = Field(None, description="Result data")
    message: Optional[str] = Field(None, description="Status message or error")
```

**Key points:**
- The `mcp_config` with `notify_frontend: True` triggers dual-delivery
- `frontend_event_name` follows pattern: `mcp:workflow:feature_name:response`
- Always include `success`, `workflow_id`, and `message` fields
- Include any data the frontend needs to update its state

---

### Step 3: Add Event Routing (Backend)

**File:** `backend/wss/receiver/event_routing.py`

Add your event to the `EVENT_HANDLERS` dict:

```python
EVENT_HANDLERS: Dict[str, Handler] = {
    # ... existing handlers ...
    "workflow:mcp:your_feature": Handler.WORKFLOW_MCP,
}
```

---

### Step 4: Implement the Handler (Backend)

**File:** `backend/wss/handlers/workflow_mcp_handler.py`

```python
async def your_feature(
    self,
    request: WorkflowMCPYourFeatureRequest,
    sid: str,
) -> WorkflowMCPYourFeatureResponse:
    """Handle your_feature MCP request."""
    try:
        # 1. Load the workflow from database
        workflow = await self._load_workflow(request.workflow_id)
        if not workflow:
            return WorkflowMCPYourFeatureResponse(
                success=False,
                workflow_id=request.workflow_id,
                message=f"Workflow {request.workflow_id} not found"
            )

        # 2. Perform your operation
        result = do_something(workflow, request.some_param)

        # 3. Save to database
        await self._save_workflow(workflow)

        # 4. Return success response (will be dual-delivered)
        return WorkflowMCPYourFeatureResponse(
            success=True,
            workflow_id=request.workflow_id,
            result_data=result,
            message="Operation completed successfully"
        )

    except Exception as e:
        logger.error(f"Error in your_feature: {e}")
        return WorkflowMCPYourFeatureResponse(
            success=False,
            workflow_id=request.workflow_id,
            message=str(e)
        )
```

Also add the handler method dispatch in `handle_event`:

```python
async def handle_event(self, event_name: str, data: Dict[str, Any], sid: str):
    # ... existing code ...

    if event_name == "workflow:mcp:your_feature":
        request = WorkflowMCPYourFeatureRequest(**data)
        return await self.your_feature(request, sid)
```

---

### Step 5: Define the MCP Tool (Backend)

**File:** `backend/mcp_adapter/tools.py`

Add the tool definition to the `WORKFLOW_TOOLS` list:

```python
Tool(
    name="your_feature",
    description="Description of what this tool does. Be specific about inputs and outputs.",
    inputSchema={
        "type": "object",
        "properties": {
            "workflow_id": {
                "type": "string",
                "description": "UUID of the workflow"
            },
            "some_param": {
                "type": "string",
                "description": "Description of this parameter"
            },
            "optional_param": {
                "type": "string",
                "description": "Optional parameter description"
            }
        },
        "required": ["workflow_id", "some_param"]
    },
    annotations=ToolAnnotations(
        title="Your Feature Title",
        readOnlyHint=False,  # True if this doesn't modify state
        openWorldHint=False
    )
),
```

---

### Step 6: Register Frontend Event (Frontend)

**File:** `frontend/app/lib/socket/config.ts`

Add your event to the `events` array in the API config:

```typescript
events: [
    // ... existing events ...

    // Workflow MCP events
    'mcp:workflow:your_feature:response',  // Add this line
],
```

---

### Step 7: Add TypeScript Types (Frontend)

**File:** `frontend/app/types/socket-events.generated.ts`

#### 7a. Add the response interface (add near other WorkflowMCP interfaces):

```typescript
/**
 * Response for workflow:mcp:your_feature - dual-delivered to frontend
 */
export interface WorkflowMCPYourFeatureResponse {
  /**
   * Whether the operation succeeded
   */
  success: boolean;
  /**
   * ID of the modified workflow
   */
  workflow_id: string;
  /**
   * Result data from the operation
   */
  result_data?: {
    [k: string]: unknown;
  } | null;
  /**
   * Status message or error
   */
  message?: string | null;
}
```

#### 7b. Add to ServerToClientEvents interface:

```typescript
export interface ServerToClientEvents {
  // ... existing events ...

  'mcp:workflow:your_feature:response': (data: WorkflowMCPYourFeatureResponse) => void;  // MCP dual delivery
}
```

---

### Step 8: Add Frontend Event Handler (Frontend)

**File:** `frontend/app/hooks/useWorkflowMCPHandler.ts`

Add a useEffect to listen for the event and update React state:

```typescript
// Handle your_feature dual-delivery
useEffect(() => {
    const unsubscribe = onSocketEvent(
        'mcp:workflow:your_feature:response' as any,
        (response: {
            success: boolean;
            workflow_id: string;
            result_data?: Record<string, any>;
            message?: string;
        }) => {
            // Only process if this is for the currently open workflow
            if (response.workflow_id !== workflowId || !response.success) return;

            console.log('[WorkflowMCP] Dual-delivery: your_feature', response);

            // Update local React state based on the response
            // Example: updating nodes
            setNodes(curr => curr.map(n => {
                // Your state update logic here
                return n;
            }));

            // Or updating edges
            setEdges(curr => {
                // Your state update logic here
                return curr;
            });
        }
    );
    return unsubscribe;
}, [workflowId, setNodes, setEdges]);
```

**Key points:**
- Always check `workflow_id` matches the currently open workflow
- Check `success` before processing
- Use functional updates (`setNodes(curr => ...)`) to avoid stale state
- Add console.log for debugging

---

## Event Naming Conventions

| Location | Pattern | Example |
|----------|---------|---------|
| Backend request event | `workflow:mcp:snake_case` | `workflow:mcp:add_edge` |
| Backend response class | `WorkflowMCPPascalCaseResponse` | `WorkflowMCPAddEdgeResponse` |
| Frontend event name | `mcp:workflow:snake_case:response` | `mcp:workflow:add_edge:response` |
| MCP tool name | `snake_case` | `add_workflow_edge` |

---

## Checklist

Use this checklist when adding a new real-time MCP event:

- [ ] **Backend: client_events.py** - Added request class with `event_name`
- [ ] **Backend: responses.py** - Added response class with `mcp_config` dual-delivery
- [ ] **Backend: event_routing.py** - Added event → handler mapping
- [ ] **Backend: workflow_mcp_handler.py** - Implemented handler method
- [ ] **Backend: workflow_mcp_handler.py** - Added dispatch in `handle_event`
- [ ] **Backend: tools.py** - Added MCP tool definition
- [ ] **Frontend: socket/config.ts** - Added event to `events` array
- [ ] **Frontend: socket-events.generated.ts** - Added response interface
- [ ] **Frontend: socket-events.generated.ts** - Added to `ServerToClientEvents`
- [ ] **Frontend: useWorkflowMCPHandler.ts** - Added useEffect listener

---

## Debugging Tips

1. **Backend not sending to frontend?**
   - Check `mcp_config` has `notify_frontend: True`
   - Verify the response class is being returned from handler
   - Check logs for dual-delivery send confirmation

2. **Frontend not receiving?**
   - Check event is in `socket/config.ts` events array
   - Check event is in `ServerToClientEvents` interface
   - Look at browser Network tab → WS tab for incoming messages

3. **Frontend receiving but not updating UI?**
   - Add console.log in the useEffect handler
   - Check `workflow_id` matches
   - Check `success` is true
   - Verify state update logic is correct

4. **TypeScript errors?**
   - Run `npm run typecheck` in frontend
   - Ensure response interface matches backend exactly
   - Check event name strings match exactly

---

## Example: Complete Add Edge Implementation

For a complete working example, see the `add_edge` implementation:

- Request: `WorkflowMCPAddEdgeRequest` in `client_events.py`
- Response: `WorkflowMCPAddEdgeResponse` in `responses.py`
- Handler: `add_edge()` in `workflow_mcp_handler.py`
- Tool: `add_workflow_edge` in `tools.py`
- Frontend listener: `mcp:workflow:add_edge:response` handler in `useWorkflowMCPHandler.ts`
