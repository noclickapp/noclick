---
name: Workflow Node Creator
description: Create new workflow automation nodes with Pydantic models, OAuth/API credentials, and dynamic field loading. Use when user asks to add a workflow node, create an automation node, add integration, implement a new node type, or mentions workflow nodes, automation integrations, or node credentials.
---

# Workflow Node Creator

Complete guide for implementing workflow automation nodes with credentials and dynamic fields.

## Architecture

```
Backend                                    Frontend
───────                                    ────────
nodes/my_node.py                          schemas/nodes/my-node.json
  - Pydantic models (config, creds)         - Generated JSON Schema
  - Node class with execute()
  - load_field_options() for dropdowns    utils/
                                            - nodeSchemas.ts (NODE_SCHEMAS registry + filterConfigForExecution)
nodes/node_registry.py                    components/workflow/
  - NODE_REGISTRY entry                     - FlowCanvas.tsx (typeMap for auto-select)
                                            - NodeCredentials.tsx (CREDENTIAL_TYPE_MAP)

nodes/oauth/                              hooks/oauth/
  - google_oauth.py                         - useGoogleOAuth.ts
  - airtable_oauth.py                       - useAirtableOAuth.ts
  - github_oauth.py                         - useGithubOAuth.ts
  (Token utils: exchange, refresh, etc.)    (OAuth flow, popup, postMessage)

wss/handlers/oauth/                       nodes/
  - google_oauth_handler.py                 - MyServiceNode.tsx (component + definition)
  - airtable_oauth_handler.py               - nodeRegistry.ts (AVAILABLE_NODES)
  - github_oauth_handler.py
wss/handlers/
  - workflow_handler.py (field options)
  - workflow_execution_handler.py
```

**Key Frontend Registrations** (easy to miss):
- `utils/nodeSchemas.ts`: NODE_SCHEMAS (centralized schema registry for config form + execution filtering)
- `FlowCanvas.tsx`: typeMap (for credential auto-select on drag)
- `NodeCredentials.tsx`: **CREDENTIAL_TYPE_MAP** (for OAuth credential display)

## Step 1: Create Backend Node

### File: `backend/nodes/my_node.py`

```python
"""
My Node - Brief description of what this node does.
"""
import logging
from typing import Dict, Any, Optional, Union, Type, List
from pydantic import BaseModel, Field
from nodes.base_node import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


# ============================================================================
# Credential Schema
# ============================================================================
#
# IMPORTANT: Implement ALL auth methods the service supports!
# Frontend auto-sorts credentials by priority: OAuth > API Key > PAT > Others
# This provides best UX as OAuth is typically easiest for users.
#
# Use Union[...] to combine multiple credential types (see Pattern C below).

# Pattern A: PAT credential (Personal Access Token)
class MyPATCredential(BaseModel):
    """Personal Access Token credential for My Service.

    Get your PAT at: https://myservice.com/tokens
    """
    personal_access_token: str = Field(
        ...,
        title="Personal Access Token",
        description="Your Personal Access Token (PAT)",
        json_schema_extra={"ui:widget": "password"}
    )

    class Config:
        json_schema_extra = {
            "x-credential-url": "https://myservice.com/tokens"  # Shows "Get credentials here" link
        }


# Pattern B: OAuth credential (tokens from OAuth flow)
class MyOAuthCredential(BaseModel):
    """OAuth 2.0 credential for My Service.
    Tokens are obtained via OAuth flow, not entered manually.

    Register OAuth app at: https://myservice.com/oauth
    """
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: str = Field(..., title="Token Expiry")  # ISO 8601
    email: Optional[str] = Field(None, title="Account Email")

    class Config:
        json_schema_extra = {
            "x-credential-type": "oauth",
            "x-oauth-provider": "my_service",  # airtable, google, microsoft, linear, etc.
            "x-oauth-scopes": [
                "data:read",
                "data:write",
            ]
        }

# ⚠️ IMPORTANT: OAuth Scopes
#
# When defining x-oauth-scopes, include ALL scopes needed for EVERY operation
# the node supports. Common mistake: Adding new operations but forgetting to
# add their required scopes.
#
# Example - YouTube node needs scopes for multiple APIs:
#   "x-oauth-scopes": [
#       "https://www.googleapis.com/auth/youtube.force-ssl",     # Data API
#       "https://www.googleapis.com/auth/youtube.upload",        # Video uploads
#       "https://www.googleapis.com/auth/yt-analytics.readonly", # Analytics API
#       "https://www.googleapis.com/auth/yt-analytics-monetary.readonly", # Revenue
#       "https://www.googleapis.com/auth/youtube.channel-memberships.creator", # Members
#   ]
#
# After adding new scopes:
# 1. Regenerate the JSON schema (frontend reads scopes from schema)
# 2. Users must RECONNECT their account to grant new scopes
# 3. Enable the required APIs in cloud provider console (e.g., Google Cloud)


# Pattern C: Multiple auth methods (RECOMMENDED for services supporting both)
# Use Union type - frontend will show all options, OAuth first
MyCredential = Union[MyOAuthCredential, MyPATCredential]  # OAuth shown first!


# ============================================================================
# Operation Configs (use discriminated union for multiple operations)
# ============================================================================

class MyNodeReadConfig(BaseModel):
    """Config for read operation"""
    operation: str = Field(
        "read",
        json_schema_extra={"const": "read", "ui:hidden": True}  # discriminator
    )
    # Static field
    some_option: str = Field(..., title="Option", description="...")

    # Dynamic dropdown field (populated at runtime)
    resource_id: str = Field(
        ...,
        title="Resource",
        description="Select a resource",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "resource_id",
                "placeholder": "Select a resource...",
                "searchable": True,
                "allow_custom": True,  # Allow manual ID entry
                "custom_placeholder": "Or paste resource ID"
            }
        }
    )


class MyNodeWriteConfig(BaseModel):
    """Config for write operation"""
    operation: str = Field(
        "write",
        json_schema_extra={"const": "write", "ui:hidden": True}
    )
    resource_id: str = Field(...)
    data: str = Field(
        ...,
        title="Data",
        json_schema_extra={"ui:widget": "textarea"}
    )


# Union type creates anyOf/oneOf in JSON Schema
MyNodeConfig = Union[MyNodeReadConfig, MyNodeWriteConfig]


# ============================================================================
# Full Node Config (wraps config + credentials)
# ============================================================================

class MyNodeFullConfig(NodeConfig[MyNodeConfig, MyCredential]):
    """Complete node configuration - uses Union credential type"""
    pass


# ============================================================================
# Node Implementation
# ============================================================================

class MyNode(WorkflowNode):
    """My workflow node implementation"""

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return MyNodeFullConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Load dynamic options for dropdown fields.
        Called when frontend needs to populate a dynamic select.

        Returns: [{"value": "id", "label": "Name", "metadata": {...}}, ...]
        """
        if field_name == "resource_id":
            return await cls._list_resources(credential_data)
        return []

    @classmethod
    async def _list_resources(cls, credential_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch resources from API"""
        access_token = credential_data.get('access_token')
        # Make API call, return list of options
        return [
            {"value": "res-1", "label": "Resource 1", "metadata": {}},
            {"value": "res-2", "label": "Resource 2", "metadata": {}},
        ]

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the node"""
        config = self.config
        if not config or not isinstance(config, MyNodeFullConfig):
            raise ValueError("Configuration required")

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials required. Connect an account in the credentials tab.")

        # Get fresh token if OAuth
        access_token = await self._ensure_fresh_token(credentials)

        # Execute based on operation type
        op_config = config.config
        if isinstance(op_config, MyNodeReadConfig):
            return await self._read(op_config, access_token)
        elif isinstance(op_config, MyNodeWriteConfig):
            return await self._write(op_config, access_token, inputs)

        raise ValueError(f"Unknown operation: {type(op_config)}")

    async def _ensure_fresh_token(self, credentials) -> str:
        """Refresh OAuth token if expired"""
        from nodes.oauth.google_oauth import is_token_expired, refresh_access_token

        if not is_token_expired(credentials.expires_at):
            return credentials.access_token

        new_tokens = await refresh_access_token(credentials.refresh_token)
        return new_tokens.access_token

    async def _read(self, config, token) -> Dict[str, Any]:
        # Implementation
        return {"status": "success", "data": [...]}

    async def _write(self, config, token, inputs) -> Dict[str, Any]:
        # Implementation
        return {"status": "success", "written": True}
```

## Step 2: Register Node in Backend

### File: `backend/nodes/node_registry.py`

```python
from nodes.my_node import MyNode

NODE_REGISTRY: Dict[str, Type[WorkflowNode]] = {
    # ... existing nodes ...
    'automation-my-service': MyNode,
}
```

## Step 3: Generate JSON Schema

```bash
cd backend
python -c "
from nodes.my_node import MyNode
import json
schema = MyNode.get_config_schema()
print(json.dumps(schema, indent=2))
" > ../frontend/app/schemas/nodes/my-node.json
```

## Step 4: Register Schema in Frontend (2 files)

**IMPORTANT**: Schema must be added to TWO files. Missing any will cause bugs.

```typescript
// ============ utils/nodeSchemas.ts (centralized schema registry) ============
// This is the SINGLE SOURCE OF TRUTH for node schemas.
// Used by NodeConfig for rendering forms and by execution logic for filtering configs.
import myServiceSchema from '~/schemas/nodes/my-service.json';

export const NODE_SCHEMAS: Record<string, any> = {
    // ... existing schemas ...
    'automation-my-service': myServiceSchema,
};

// ============ NodeCredentials.tsx ============
// Only needs CREDENTIAL_TYPE_MAP (imports NODE_SCHEMAS from nodeSchemas.ts)
const CREDENTIAL_TYPE_MAP = {
    // Add ALL credential types from Union! Frontend auto-sorts: OAuth first, PAT second
    'MyOAuthCredential': 'my_service_oauth',  // ⚠️ REQUIRED for OAuth credentials to appear!
    'MyPATCredential': 'my_service_pat',       // Also add PAT if using Union type
};

// ============ FlowCanvas.tsx (only for credential auto-select) ============
// Only needed if you want automatic credential selection when dragging node onto canvas
const typeMap = {
    'MyOAuthCredential': 'my_service_oauth',  // schema title → DB credential_type
};
```

> **Common Bug**: Credentials don't appear after OAuth? → Missing `CREDENTIAL_TYPE_MAP` entry.

## Step 5: Create Node Component

### File: `frontend/app/components/workflow/nodes/MyServiceNode.tsx`

```typescript
import { memo, SVGProps } from 'react';
import { NodeProps } from 'reactflow';
import { SiMyService } from 'react-icons/si';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Option A: react-icons (single color)
export const MyServiceNode: NodeDefinition = {
    type: 'automation-my-service',
    label: 'My Service',
    description: 'Read and write data',
    Icon: SiMyService,
    iconColor: 'text-blue-500',
    dimensions: DIMENSIONS,
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={SiMyService} iconColor="text-blue-500" />
    )),
};

// Option B: Custom SVG (multi-colored) - use iconColor="" and cast Icon as any
const CustomIcon = ({ className, style, ...props }: SVGProps<SVGSVGElement>) => (
    <svg viewBox="0 0 48 48" className={className} style={style} {...props}>
        <path fill="#4caf50" d="..."/><path fill="#1e88e5" d="..."/>
    </svg>
);
```

### File: `frontend/app/components/workflow/nodes/nodeRegistry.ts`

```typescript
import { MyServiceNode } from './MyServiceNode';
export const AVAILABLE_NODES: NodeDefinition[] = [..., MyServiceNode];
```

## Step 6: OAuth Handler (if using OAuth)

### OAuth Directory Structure

```
backend/
├── nodes/oauth/                    # OAuth token utilities
│   ├── __init__.py                 # Exports all OAuth utilities
│   ├── google_oauth.py             # Google: exchange, refresh, validate
│   ├── airtable_oauth.py           # Airtable: PKCE flow support
│   └── github_oauth.py             # GitHub: standard OAuth
│
├── wss/handlers/oauth/             # OAuth WebSocket handlers
│   ├── __init__.py                 # Exports all handlers
│   ├── google_oauth_handler.py     # Google OAuth events
│   ├── airtable_oauth_handler.py   # Airtable OAuth events
│   └── github_oauth_handler.py     # GitHub OAuth events

frontend/app/hooks/oauth/           # Frontend OAuth hooks
├── index.ts                        # Exports all hooks
├── useGoogleOAuth.ts               # Google popup + postMessage
├── useAirtableOAuth.ts             # Airtable popup + PKCE
└── useGithubOAuth.ts               # GitHub popup + postMessage
```

### Adding a New OAuth Provider

1. **Create token utilities**: `backend/nodes/oauth/myservice_oauth.py`
2. **Create WebSocket handler**: `backend/wss/handlers/oauth/myservice_oauth_handler.py`
3. **Create frontend hook**: `frontend/app/hooks/oauth/useMyServiceOAuth.ts`
4. **Add frontend routes**: `frontend/app/routes/api/auth/myservice.*.tsx`

### File: `backend/wss/handlers/oauth/google_oauth_handler.py`

Add credential type mapping for Google scopes:

```python
def _get_credential_type_from_scopes(self, scopes: list[str]) -> str:
    scope_set = set(scopes)

    if 'https://api.myservice.com/scope' in scope_set:
        return 'my_service_oauth'
    # ... existing mappings ...
```

For new OAuth providers, create a dedicated handler following the existing OAuth handler pattern in `wss/handlers/oauth/`.

## Key Patterns

### Discriminated Unions (Multiple Operations)

Use `const` field for operation discrimination:

```python
class ReadConfig(BaseModel):
    operation: str = Field("read", json_schema_extra={"const": "read"})

class WriteConfig(BaseModel):
    operation: str = Field("write", json_schema_extra={"const": "write"})

Config = Union[ReadConfig, WriteConfig]
```

Frontend `NodeConfig.tsx` detects discriminator and renders operation selector buttons.
The `utils/nodeSchemas.ts` module also uses discriminator detection to filter configs before execution.

### Dynamic Dropdowns

1. Add `x-dynamic-options` to field schema
2. Implement `load_field_options()` class method
3. Frontend calls `workflow:node:load_options` event
4. Handler in `workflow_handler.py` routes to node's method

### Credential Types

**Priority Order** (frontend auto-sorts): OAuth > API Key > PAT > Others

| Type | UI | Schema Extra | Priority |
|------|----|--------------|----------|
| OAuth | Connect button | `"x-credential-type": "oauth"`, `"x-oauth-provider": "..."` | 1st |
| API Key | Password input | `"ui:widget": "password"` | 2nd |
| PAT | Password input | `"ui:widget": "password"`, `"x-credential-url": "..."` | 3rd |
| Other | Text input | varies | 4th |

**Best Practice**: If a service supports multiple auth methods, implement ALL of them using `Union[OAuthCred, PATCred]`. Users prefer OAuth for ease of use, but power users may want PAT for automation.

### Field UI Widgets

```python
# Password field
Field(..., json_schema_extra={"ui:widget": "password"})

# Textarea
Field(..., json_schema_extra={"ui:widget": "textarea"})

# Hidden field
Field(..., json_schema_extra={"ui:hidden": True})

# Placeholder
Field(..., json_schema_extra={"placeholder": "Enter value..."})

# Webhook URL field (auto-generated, see Webhook Support section)
Field(..., json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})
```

### Webhook Support

For nodes that receive external HTTP webhooks (e.g., trigger nodes, service integrations):

#### Schema Markers

Use `ui:widget="webhook"` to mark a field as a webhook URL. The system automatically:
1. Creates a webhook record when the field is loaded
2. Generates a URL under the installation's configured `WEBHOOK_URL_BASE`:
   `{WEBHOOK_URL_BASE}/{webhook_id}`
3. Handles cleanup when the node is deleted

```python
class MyTriggerConfig(BaseModel):
    """Config for webhook trigger operation"""
    operation: str = Field(
        "receive_webhook",
        json_schema_extra={"const": "receive_webhook", "ui:hidden": True}
    )
    webhook_id: Optional[str] = Field(
        default=None,
        title="Webhook ID",
        json_schema_extra={"ui:hidden": True}  # Internal tracking
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Send webhooks to this URL",
        json_schema_extra={
            "ui:widget": "webhook",    # Triggers WebhookManager
            "ui:copyable": True,       # Adds copy button
            "ui:loadValue": True       # Auto-loads value on render
        }
    )
    secret: Optional[str] = Field(
        default=None,
        title="Secret (Optional)",
        description="For HMAC-SHA256 signature verification",
        json_schema_extra={"ui:widget": "password"}
    )
```

#### Operation-Level Webhook Requirement

For multi-operation nodes where only some operations need webhooks:

```python
from pydantic import ConfigDict

class ReceiveMessageConfig(BaseModel):
    """Webhook operation that receives messages"""
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: str = Field("receive_message", json_schema_extra={"const": "receive_message", "ui:hidden": True})
    webhook_url: Optional[str] = Field(
        None,
        title="Webhook URL",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True}
    )

class SendMessageConfig(BaseModel):
    """Non-webhook operation"""
    operation: str = Field("send_message", json_schema_extra={"const": "send_message", "ui:hidden": True})
    message: str = Field(..., title="Message")

# Union type - webhooks auto-cleanup when switching operations
MyNodeConfig = Union[ReceiveMessageConfig, SendMessageConfig]
```

#### How It Works

1. **Field Load**: When frontend renders a field with `ui:widget="webhook"`, it triggers `workflow:node:load_value`
2. **WebhookManager**: Backend's `workflow_handler.py` detects the webhook field and calls `WebhookManager.get_or_create_webhook()`
3. **URL Generation**: Webhook URL is returned under the configured
   `WEBHOOK_URL_BASE`
4. **Cleanup**: When node is deleted or operation changes to non-webhook, `WebhookManager.delete_webhook()` is called

#### Workflow Execution with Webhooks

When a webhook is received:
1. HTTP request hits the webhook URL
2. `webhook_routes.py` looks up the webhook config from database
3. Webhook payload is injected as `mockedOutput` on the trigger node
4. Workflow executes starting from the trigger node (single starting node selection)
5. Events are relayed to user's connected frontends via Event Relay

## Checklist

### Backend
- [ ] `nodes/my_node.py` - Pydantic models + execute()
- [ ] `node_registry.py` - NODE_REGISTRY entry
- [ ] `wss/handlers/oauth/` - OAuth handler (if new OAuth provider)
- [ ] **OAuth scopes** - Include ALL scopes in `x-oauth-scopes` for every API the node uses

### Frontend
- [ ] Generate schema to `schemas/nodes/my-node.json`
- [ ] `utils/nodeSchemas.ts` - NODE_SCHEMAS (centralized schema registry)
- [ ] `NodeCredentials.tsx` - **CREDENTIAL_TYPE_MAP**
- [ ] `FlowCanvas.tsx` - typeMap (for credential auto-select)
- [ ] `nodes/MyServiceNode.tsx` - NodeDefinition
- [ ] `nodeRegistry.ts` - AVAILABLE_NODES

### Test Files (IMPORTANT)
- [ ] **Location**: ALL test files MUST be in `backend/nodes/tests/` directory
- [ ] **File limit**: Maximum 2 test files per node
- [ ] **Naming convention**:
  - Main test file: `test_NODENAME_node_integration.py` (e.g., `test_redis_node_integration.py`)
  - Mock tests (optional): `test_NODENAME_node_mock.py`
- [ ] **Integration tests**: Must pass or have mocks for unavailable APIs
- [ ] **Test quality**: Ensure tests verify actual functionality, not just mock behavior

### Manual Test
- [ ] Node in sidebar, OAuth works, credential appears after connection
- [ ] Config form renders, dynamic dropdowns populate, execution succeeds

### Webhook Support (if applicable)
- [ ] Add `ui:widget="webhook"` to webhook URL field in config model
- [ ] Add `ui:copyable` and `ui:loadValue` to webhook URL field
- [ ] Add optional `secret` field for HMAC verification if needed
- [ ] For multi-operation nodes: Add `x-requires-webhook: true` to webhook operations
- [ ] Test: Webhook URL auto-generates when config loads
- [ ] Test: Webhook triggers workflow execution correctly

### When Adding New Operations to Existing Node
- [ ] Check if new operations require additional OAuth scopes
- [ ] Update `x-oauth-scopes` in credential class Config
- [ ] Regenerate JSON schema after scope changes
- [ ] Note: Users must **reconnect** their account to get new scopes

## Post-Generation: Testing Instructions

After generating a node, **always provide testing instructions** for all supported auth methods:

### Example Testing Instructions (output this after node creation):

```markdown
## Testing [ServiceName] Node

### OAuth Authentication
1. **Register OAuth App**: https://service.com/oauth/apps
   - Redirect URI: `http://localhost:5174/api/auth/[service]/callback`
   - Required scopes: `data:read`, `data:write`, etc.

2. **Environment Variables** (add to `frontend/.env`):
   ```
   [SERVICE]_CLIENT_ID=your-client-id
   [SERVICE]_REDIRECT_URI=http://localhost:5174/api/auth/[service]/callback
   ```

3. **Backend Environment** (add to `backend/.env` if token refresh needed):
   ```
   [SERVICE]_CLIENT_ID=your-client-id
   [SERVICE]_CLIENT_SECRET=your-client-secret
   ```

4. **Test Flow**:
   - Restart frontend dev server
   - Add node to workflow
   - Go to Credentials tab
   - Click "Connect [Service] Account"
   - Complete OAuth consent flow
   - Verify credential appears in dropdown

### PAT/API Key Authentication
1. **Get Token**: https://service.com/tokens (or /api-keys)
   - Create token with required permissions

2. **Test Flow**:
   - Add node to workflow
   - Go to Credentials tab
   - Click "Create new" under PAT section
   - Enter your token
   - Verify credential is saved and selectable

### Verify Node Execution
1. Configure node with test data
2. Run workflow
3. Check Output tab for results
```

**IMPORTANT**: Always include this testing section after generating a new node!

## Reference Implementation

- **OAuth + PAT (multiple auth)**: `backend/nodes/airtable_node.py` - Union credential type with OAuth first, PAT second
- **OAuth + PAT (multiple auth)**: `backend/nodes/github_rest_node.py` - Union credential type with OAuth first, PAT second
- **OAuth only**: `backend/nodes/google_sheets_node.py` - OAuth, discriminated unions, dynamic dropdowns, token refresh
