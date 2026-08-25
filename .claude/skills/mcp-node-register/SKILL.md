---
name: MCP Node Register
description: Register MCP-generated workflow nodes in frontend and backend. Use when the user has run the MCP generator script and needs to complete manual registration steps, or asks about adding generated nodes to registries, schema imports, or mentions MCP node registration.
---

# MCP Node Registration

Steps to complete after running the MCP Node Generator (`scripts/generate_node_from_mcp.py`).

## Generated Files

The generator creates three files that need manual registration:

```
backend/nodes/{name}_node.py          → Backend Registry
frontend/app/schemas/nodes/{name}.json → Schema Imports
frontend/app/components/workflow/nodes/{ClassName}Node.tsx → Frontend Registry
```

## Step 1: Backend Registry

**File:** `backend/nodes/core/registry.py`

```python
# Add import at top
from nodes.{name}_node import {ClassName}Node

# Add to NODE_REGISTRY dict
NODE_REGISTRY: Dict[str, Type[WorkflowNode]] = {
    # ... existing nodes ...
    'automation-{name-with-dashes}': {ClassName}Node,
}
```

**Example:** For `stripe` node:
```python
from nodes.stripe_node import StripeNode

NODE_REGISTRY: Dict[str, Type[WorkflowNode]] = {
    # ...
    'automation-stripe': StripeNode,
}
```

## Step 2: Frontend Node Registry

**File:** `frontend/app/components/workflow/nodes/nodeRegistry.ts`

```typescript
// Add import
import { {ClassName}Node } from './{ClassName}Node';

// Add to AVAILABLE_NODES array
export const AVAILABLE_NODES: NodeDefinition[] = [
    // ... existing nodes ...
    {ClassName}Node,
];
```

## Step 3: Schema Import (1 file)

MCP-generated nodes use API key credentials by default (not OAuth), so registration is simpler.

### 3a. nodeSchemas.ts (centralized schema registry)

**File:** `frontend/app/utils/nodeSchemas.ts`

```typescript
// Add import at top with other schema imports
import {name}Schema from '~/schemas/nodes/{name}.json';

// Add to NODE_SCHEMAS object (this is the SINGLE SOURCE OF TRUTH)
export const NODE_SCHEMAS: Record<string, any> = {
    // ... existing schemas ...
    'automation-{name-with-dashes}': {name}Schema,
};
```

This is the only file that needs the schema import. `NodeConfig.tsx` and execution logic both import from `nodeSchemas.ts`.

## Registration Checklist

### Backend
- [ ] Import node class in `backend/nodes/core/registry.py`
- [ ] Add to `NODE_REGISTRY` dict with correct type key

### Frontend
- [ ] Import component in `nodeRegistry.ts`
- [ ] Add to `AVAILABLE_NODES` array
- [ ] Add schema import to `NodeCredentials.tsx`
- [ ] Add to `NODE_SCHEMAS` in `NodeCredentials.tsx`
- [ ] Add schema import to `NodeConfig.tsx`
- [ ] Add to `SCHEMAS` in `NodeConfig.tsx`
- [ ] Add dynamic import to `FlowCanvas.tsx` SCHEMAS

## Code Review Checklist

Before committing generated code, verify:

1. **Auth Header** - Correct API key header name (e.g., `Authorization: Bearer`, `X-API-Key`)
2. **MCP Endpoint** - URL is correct and accessible
3. **Tool Names** - All tool names map correctly to action discriminators
4. **Field Types** - Complex types (arrays, objects) handled appropriately
5. **Required Fields** - Match the actual MCP tool requirements
6. **Icon** - Appropriate icon from react-icons (check `react-icons/si` for brand icons)

## OAuth Nodes (Non-Standard)

If the MCP server uses OAuth instead of API key:

1. Run generator with `--auth-type oauth`
2. Additional registration in `NodeCredentials.tsx`:
   ```typescript
   const CREDENTIAL_TYPE_MAP = {
       '{ClassName}OAuthCredential': '{name}_oauth',
   };
   ```
3. Add OAuth handler or scope mapping in `backend/wss/handlers/`

## Quick Reference

| Name Pattern | Example |
|--------------|---------|
| `{name}` | `stripe`, `github`, `google_sheets` |
| `{name-with-dashes}` | `stripe`, `github`, `google-sheets` |
| `{ClassName}` | `Stripe`, `Github`, `GoogleSheets` |
| Node type | `automation-stripe` |

## Troubleshooting

**Node not appearing in sidebar:**
→ Missing from `AVAILABLE_NODES` in `nodeRegistry.ts`

**Config form not rendering:**
→ Missing schema in `NodeConfig.tsx` SCHEMAS

**Credentials not showing:**
→ Missing schema in `NodeCredentials.tsx` NODE_SCHEMAS

**"Unknown node type" error:**
→ Missing from backend `NODE_REGISTRY`

## Related

- Generator script: `scripts/generate_node_from_mcp.py`
- Generator docs: `docs/plans/MCP_NODE_GENERATOR_PLAN.md`
- Full node creation (from scratch): See `workflow-node-creator` skill
