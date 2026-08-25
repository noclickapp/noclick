---
name: API Node Generator
description: Automatically generate workflow automation nodes from API documentation. Use when user asks to create a node for a service, generate an integration, add a provider, automate node creation, or mentions API node generation, service integration, or provider nodes. This skill researches API docs, generates Pydantic models, creates backend nodes, frontend schemas, and comprehensive tests.
---

# API Node Generator

Automated pipeline for creating workflow automation nodes from API documentation.

## Overview

This skill automates the complete process of creating a workflow node for any API service:

1. **Research Phase**: Search and analyze official API documentation
2. **Schema Design**: Define Pydantic models for configs and credentials
3. **Node Implementation**: Generate the backend node code
4. **Frontend Schema**: Create JSON schema for the UI
5. **Test Generation**: Create comprehensive integration tests
6. **Registration**: Update registries and provide setup instructions

## Usage

When the user asks to create a node for a service (e.g., "create a Slack node", "add Notion integration"):

### Step 1: Research API Documentation

Use WebSearch and WebFetch to gather comprehensive API information:

```
1. Search: "{service_name} REST API documentation"
2. Search: "{service_name} API authentication"
3. Search: "{service_name} API endpoints reference"
4. Fetch the official documentation pages
```

**Key Information to Extract:**
- Base API URL
- API version
- Authentication methods (API Key, OAuth, Bearer Token)
- Available endpoints/operations
- Request/response formats
- Rate limits
- Credential setup URLs (where users get API keys)
- **Webhook support** - Does the API support webhooks/callbacks? What events are available?

### Step 2: Analyze and Categorize Operations

Group the API operations into logical categories:
- **CRUD Operations**: Create, Read, Update, Delete for each resource
- **List Operations**: Pagination, filtering, sorting
- **Special Operations**: Service-specific actions
- **Webhook/Trigger Operations**: Receiving events from external services

For each operation, note:
- HTTP method (GET, POST, PUT, PATCH, DELETE)
- Endpoint path
- Required parameters
- Optional parameters
- Response format

### Step 3: Design Pydantic Models

Create models following these patterns:

**Credential Model:**
```python
# For API Key authentication
class {Service}ApiKeyCredential(BaseModel):
    """API key credential for {Service}"""
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your {Service} API key from {credential_url}",
        json_schema_extra={"ui:widget": "password"}
    )

# For OAuth authentication
class {Service}OAuthCredential(BaseModel):
    """OAuth credential for {Service}"""
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: str = Field(..., title="Token Expiry")

    class Config:
        json_schema_extra = {
            "x-credential-type": "oauth",
            "x-credential-url": "{oauth_setup_url}"
        }
```

**Operation Config Models:**
```python
class {Service}{Operation}Config(BaseModel):
    """Config for {operation_description}"""
    action: Literal["{action_name}"] = Field(
        "{action_name}",
        json_schema_extra={"const": "{action_name}", "ui:hidden": True}
    )
    # Required fields
    field_name: str = Field(..., title="Field Name", description="...")
    # Optional fields with defaults
    optional_field: Optional[str] = Field(None, title="Optional", description="...")
```

**Webhook Operation Config (for services with webhook support):**
```python
from pydantic import ConfigDict

class {Service}ReceiveWebhookConfig(BaseModel):
    """Config for receiving webhooks from {Service}"""
    # Mark this operation as requiring a webhook
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    action: Literal["receive_webhook"] = Field(
        "receive_webhook",
        json_schema_extra={"const": "receive_webhook", "ui:hidden": True}
    )
    webhook_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Register this URL with {Service} to receive events",
        json_schema_extra={
            "ui:widget": "webhook",    # Auto-generates webhook URL
            "ui:copyable": True,       # Adds copy button
            "ui:loadValue": True       # Loads value when field renders
        }
    )
    secret: Optional[str] = Field(
        default=None,
        title="Secret (Optional)",
        description="For webhook signature verification",
        json_schema_extra={"ui:widget": "password"}
    )
```

**Discriminated Union:**
```python
{Service}Config = Annotated[
    Union[
        {Service}{Operation1}Config,
        {Service}{Operation2}Config,
        # ... all operation configs
    ],
    Discriminator("operation")
]
```

### Step 4: Generate Node Code

Create the node file at `backend/nodes/{service_name}_node.py`:

```python
"""
{Service} REST API automation node.

Provides workflow integration for {Service} with operations for:
- {Category1}: {operations}
- {Category2}: {operations}
...
"""

import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

{SERVICE}_API_BASE = "{base_api_url}"

# ============================================================================
# Credential Schema
# ============================================================================

{credential_model}

# ============================================================================
# Operation Configs
# ============================================================================

{operation_configs}

# ============================================================================
# Discriminated Union
# ============================================================================

{Service}Config = Annotated[
    Union[{config_union}],
    Discriminator("operation")
]

class {Service}NodeConfig(NodeConfig[{Service}Config, {Service}Credential]):
    """Full configuration for {Service} node including credentials"""
    pass

# ============================================================================
# Node Implementation
# ============================================================================

class {Service}Node(WorkflowNode):
    """
    {Service} automation node.

    Executes {Service} operations via REST API.
    """

    @classmethod
    def get_config_model(cls):
        return {Service}NodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        {execute_method}

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: {Service}Credential,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request"
    ) -> Dict[str, Any]:
        {make_request_method}

    # Handler methods for each operation
    {handler_methods}
```

### Step 4.5: Response Schema Format for Table Parsing

**CRITICAL REQUIREMENT**: All handler methods MUST return data in a format that supports table parsing in the frontend UI.

#### Table Parsing Rules

The frontend TableView component automatically detects and renders array data in table format. It supports both arrays of objects and arrays of primitives:

**1. Prefer Arrays of Objects for Better Column Names**

```python
# ✅ PREFERRED - Array of objects with descriptive property names
schemas = [{"schema_name": row["schema_name"]} for row in rows]
sequences = [{"sequence_name": row["sequence_name"]} for row in rows]
tables = [{"name": row["table_name"], "type": row["table_type"]} for row in rows]

# ✓ ACCEPTABLE - Array of primitives (automatically shown with "value" column)
schemas = [row["schema_name"] for row in rows]  # Shows in table with "value" column
numbers = [1, 2, 3, 4, 5]  # Shows in table with "value" column
```

**2. Use Descriptive Property Names**

Property names become column headers in the table view:

```python
# ✅ GOOD - Clear, descriptive column names
{"schema_name": "public", "owner": "postgres", "size": "8192"}

# ❌ BAD - Generic names
{"name": "public", "val1": "postgres", "val2": "8192"}
```

**3. Consistent Data Structure**

Always wrap arrays in a `data` object with a descriptive property name:

```python
return {
    "status": "success",
    "action": "list_schemas",
    "data": {
        "schemas": schemas,  # Array of objects goes here
        "count": len(schemas)
    },
    "timing_ms": {...}
}
```

**4. Handle Row Data Properly**

For query results that return rows:

```python
# ✅ CORRECT - Convert asyncpg records to dicts
result_data = [dict(row) for row in rows]

return {
    "status": "success",
    "action": "query",
    "data": {
        "rows": result_data,  # Array of dicts with all columns
        "row_count": len(result_data)
    }
}

# ❌ INCORRECT - Array of arrays loses column names
result_data = [[row[col] for col in row.keys()] for row in rows]
```

**5. Nested Objects**

For nested or complex data, use JSON stringification (TableView handles this automatically):

```python
# ✅ OK - Nested objects/arrays will be stringified in table cells
users = [{
    "id": "123",
    "name": "John",
    "metadata": {"role": "admin", "active": True}  # Will show as JSON string in table
}]
```

#### Response Format Examples

**List Operations:**
```python
async def _handle_list_schemas(self, config, credentials) -> Dict[str, Any]:
    rows = await conn.fetch("SELECT schema_name FROM information_schema.schemata")

    # Convert to array of objects (not primitive strings)
    schemas = [{"schema_name": row["schema_name"]} for row in rows]

    return {
        "status": "success",
        "action": "list_schemas",
        "data": {
            "schemas": schemas,  # Frontend will show table with "schema_name" column
            "count": len(schemas)
        },
        "timing_ms": {"query": query_time}
    }
```

**Query Operations:**
```python
async def _handle_query(self, config, credentials) -> Dict[str, Any]:
    rows = await conn.fetch(config.query)

    # Convert asyncpg records to dictionaries
    result_data = [dict(row) for row in rows]

    return {
        "status": "success",
        "action": "query",
        "data": {
            "rows": result_data,  # Frontend will show table with all column names
            "row_count": len(result_data)
        },
        "timing_ms": {"query": query_time}
    }
```

**Single-Column Results:**
```python
async def _handle_explain_query(self, config, credentials) -> Dict[str, Any]:
    rows = await conn.fetch(f"EXPLAIN {config.query}")

    # Wrap single-column results in objects with descriptive property
    plan = [{"plan_line": row[0]} for row in rows]

    return {
        "status": "success",
        "action": "explain_query",
        "data": {
            "plan": plan,  # Frontend will show table with "plan_line" column
        },
        "timing_ms": {"query": query_time}
    }
```

#### Why This Matters

The frontend `IODataDisplay` component provides **JSON/TABLE toggle** for output data. When users view operation results:

- **JSON View**: Shows expandable tree with draggable fields
- **TABLE View**: Auto-detects arrays and renders them in a sortable, scrollable table

For TABLE view to work correctly:
1. `TableView` component searches for arrays in the response data
2. Extracts column names from the first object's keys
3. Renders data in a table with those column headers

If you return arrays of primitives, the component has no column names to extract, resulting in "undefined" values.

### Step 5: Generate Frontend Schema

Generate the JSON schema from the backend Pydantic models:

```bash
cd backend
python -c "
from nodes.{service_name}_node import {Service}Node
import json
schema = {Service}Node.get_config_schema()
print(json.dumps(schema, indent=2))
" > ../frontend/app/schemas/nodes/{service-name}.json
```

This generates the complete schema from Pydantic models automatically.

### Step 6: Generate COMPREHENSIVE Integration Tests

**CRITICAL REQUIREMENT**: Generate a test method for EVERY operation in the node.

For a node with N operations, you MUST create N+ test methods (one per operation plus error/performance tests).

See detailed guidance in [templates/test-generator-guide.md](templates/test-generator-guide.md).

#### Test Generation Rules:

1. **Import ALL config classes** - Every `{Service}{Operation}Config` must be imported
2. **One test per operation** - `test_{action_name}()` for EACH config class
3. **Organize by category** - Match the node's handler organization
4. **Track created resources** - Write operations must track for cleanup
5. **Cleanup in finally block** - Always clean up test data
6. **Include error tests** - Invalid IDs, missing auth, etc.
7. **Include performance tests** - Verify timing_ms in responses

#### Test File Structure:

```python
"""
Comprehensive integration tests for {Service} REST API node.

Tests ALL {N} operations organized by category.
Run: python scripts/test_{service_name}_integration.py <API_KEY>
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nodes.{service_name}_node import (
    {Service}Node,
    {Service}NodeConfig,
    {Service}Credential,
    # IMPORT EVERY CONFIG CLASS - ONE LINE PER OPERATION
    {Service}List{Resource1}Config,
    {Service}Get{Resource1}Config,
    {Service}Create{Resource1}Config,
    {Service}Update{Resource1}Config,
    {Service}Delete{Resource1}Config,
    {Service}List{Resource2}Config,
    # ... continue for ALL operations
)


class TestRunner:
    def __init__(self, api_key: str):
        self.credentials = {Service}Credential(api_key=api_key)
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.created_resources = []  # Track for cleanup

    def create_node(self, config):
        node_config = {Service}NodeConfig(config=config, credentials=self.credentials)
        return {Service}Node(
            node_id="test-node",
            node_type="automation-{service-name}",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow"
        )

    async def run_test(self, name: str, test_func):
        try:
            await test_func()
            print(f"  PASS: {name}")
            self.passed += 1
        except AssertionError as e:
            print(f"  FAIL: {name} - {e}")
            self.failed += 1
        except Exception as e:
            print(f"  ERROR: {name} - {type(e).__name__}: {e}")
            self.failed += 1

    async def cleanup(self):
        """Clean up ALL test-created resources."""
        print("\\n[Cleanup]")
        for resource_type, resource_id in reversed(self.created_resources):
            try:
                await self._delete_resource(resource_type, resource_id)
                print(f"  Deleted {resource_type}: {resource_id}")
            except Exception as e:
                print(f"  Warning: {e}")

    async def run_all_tests(self):
        print("\\n" + "=" * 70)
        print(f"{{Service}} Node Integration Tests - {{N}} Operations")
        print("=" * 70 + "\\n")

        try:
            # =====================================================
            # {Category1} Operations ({count} tests)
            # =====================================================
            print("\\n[{Category1} Operations]")
            await self.run_test("list_{resources1}", self.test_list_{resources1})
            await self.run_test("get_{resource1}", self.test_get_{resource1})
            await self.run_test("create_{resource1}", self.test_create_{resource1})
            await self.run_test("update_{resource1}", self.test_update_{resource1})
            await self.run_test("delete_{resource1}", self.test_delete_{resource1})

            # =====================================================
            # {Category2} Operations ({count} tests)
            # =====================================================
            print("\\n[{Category2} Operations]")
            await self.run_test("list_{resources2}", self.test_list_{resources2})
            # ... ALL operations for category 2

            # Continue for ALL categories until ALL operations are covered

            # =====================================================
            # Error Handling Tests
            # =====================================================
            print("\\n[Error Handling]")
            await self.run_test("invalid_id", self.test_invalid_id)
            await self.run_test("missing_credentials", self.test_missing_credentials)

            # =====================================================
            # Performance Tests
            # =====================================================
            print("\\n[Performance]")
            await self.run_test("timing_info", self.test_timing_info)

        finally:
            await self.cleanup()

        total = self.passed + self.failed + self.skipped
        print("\\n" + "=" * 70)
        print(f"Results: {self.passed}/{total} passed, {self.failed} failed, {self.skipped} skipped")
        print("=" * 70 + "\\n")

        return self.failed == 0

    # ===========================================================
    # {Category1} Test Methods - ONE PER OPERATION
    # ===========================================================

    async def test_list_{resources1}(self):
        """Test list_{resources1} operation."""
        config = {Service}List{Resource1}Config(per_page=5)
        result = await self.create_node(config).execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_{resources1}"

    async def test_get_{resource1}(self):
        """Test get_{resource1} operation."""
        # First get a valid ID
        list_config = {Service}List{Resource1}Config(per_page=1)
        list_result = await self.create_node(list_config).execute({})
        if list_result["status"] == "success" and list_result["data"]:
            id = list_result["data"][0]["id"]
            config = {Service}Get{Resource1}Config({resource1}_id=id)
            result = await self.create_node(config).execute({})
            assert result["status"] == "success"
            assert result["action"] == "get_{resource1}"

    async def test_create_{resource1}(self):
        """Test create_{resource1} operation."""
        config = {Service}Create{Resource1}Config(
            name=f"Test {int(time.time())}"
        )
        result = await self.create_node(config).execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_{resource1}"
        # Track for cleanup
        if result.get("data", {}).get("id"):
            self.created_resources.append(("{resource1}", result["data"]["id"]))

    async def test_update_{resource1}(self):
        """Test update_{resource1} operation."""
        # Create first
        create_config = {Service}Create{Resource1}Config(name=f"ToUpdate {int(time.time())}")
        create_result = await self.create_node(create_config).execute({})
        if create_result["status"] == "success":
            id = create_result["data"]["id"]
            self.created_resources.append(("{resource1}", id))
            # Then update
            config = {Service}Update{Resource1}Config({resource1}_id=id, name="Updated")
            result = await self.create_node(config).execute({})
            assert result["status"] == "success"

    async def test_delete_{resource1}(self):
        """Test delete_{resource1} operation."""
        # Create then delete
        create_config = {Service}Create{Resource1}Config(name=f"ToDelete {int(time.time())}")
        create_result = await self.create_node(create_config).execute({})
        if create_result["status"] == "success":
            id = create_result["data"]["id"]
            config = {Service}Delete{Resource1}Config({resource1}_id=id)
            result = await self.create_node(config).execute({})
            assert result["status"] == "success"

    # ===========================================================
    # {Category2} Test Methods - ONE PER OPERATION
    # ===========================================================

    # async def test_list_{resources2}(self): ...
    # ... CONTINUE FOR ALL OPERATIONS

    # ===========================================================
    # Error & Performance Tests
    # ===========================================================

    async def test_invalid_id(self):
        config = {Service}Get{Resource1}Config({resource1}_id="invalid-12345")
        result = await self.create_node(config).execute({})
        assert result["status"] == "error"
        assert result["status_code"] in [404, 400]

    async def test_timing_info(self):
        config = {Service}List{Resource1}Config(per_page=1)
        result = await self.create_node(config).execute({})
        assert "timing_ms" in result
        assert result["timing_ms"]["api_request"] > 0


async def main():
    api_key = os.environ.get("{SERVICE}_API_KEY", "")
    if len(sys.argv) > 1:
        api_key = sys.argv[1]

    if not api_key:
        print("ERROR: API key required.")
        sys.exit(1)

    runner = TestRunner(api_key)
    success = await runner.run_all_tests()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())
```

#### Verification Checklist

After generating tests, verify:

- [ ] Every `{Service}{Operation}Config` has a `test_{action}` method
- [ ] Test count matches operation count (+ error/perf tests)
- [ ] All write operations track resources for cleanup
- [ ] All categories from node are represented in tests

### Step 7: Complete Registration (Backend + Frontend)

After generating the node and schema files, perform ALL these registration steps:

#### Backend Registration

**1. `backend/nodes/core/registry.py`:**
```python
from nodes.{service_name}_node import {Service}Node

NODE_REGISTRY: Dict[str, Type[WorkflowNode]] = {
    # ... existing nodes
    'automation-{service-name}': {Service}Node,
}
```

#### Frontend Registration (ALL 5 FILES REQUIRED)

**2. `frontend/app/components/workflow/NodeConfig.tsx`:**
```typescript
// Add import at top with other schema imports
import {serviceName}Schema from '~/schemas/nodes/{service-name}.json';

// Add to SCHEMAS object
const SCHEMAS: Record<string, any> = {
    // ... existing schemas
    'automation-{service-name}': {serviceName}Schema,
};
```

**3. `frontend/app/components/workflow/NodeCredentials.tsx`:**
```typescript
// Add import at top with other schema imports
import {serviceName}Schema from '~/schemas/nodes/{service-name}.json';

// Add to NODE_SCHEMAS object
const NODE_SCHEMAS: Record<string, any> = {
    // ... existing schemas
    'automation-{service-name}': {serviceName}Schema,
};

// Add to CREDENTIAL_TYPE_MAP inside the useEffect function
const CREDENTIAL_TYPE_MAP: Record<string, string> = {
    // ... existing mappings
    '{Service}Credential': '{service_name}_pat',  // or _api_key, _oauth as appropriate
};
```

**4. `frontend/app/utils/credentialAutoSelect.ts`:**
```typescript
// Add import at top with other schema imports
import {serviceName}Schema from '~/schemas/nodes/{service-name}.json';

// Add to NODE_SCHEMAS object
const NODE_SCHEMAS: Record<string, any> = {
    // ... existing schemas
    'automation-{service-name}': {serviceName}Schema,
};

// Add to CREDENTIAL_TYPE_MAP object
const CREDENTIAL_TYPE_MAP: Record<string, string> = {
    // ... existing mappings
    '{Service}Credential': '{service_name}_pat',  // must match NodeCredentials.tsx
};
```

**5. Create `frontend/app/components/workflow/nodes/{Service}Node.tsx`:**
```typescript
// {Service} REST API automation node definition.
// Provides workflow integration for {service description}.

import { memo, forwardRef } from 'react';
import { NodeProps } from 'reactflow';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Option A: Use react-icons if available
// import { Si{Service} } from 'react-icons/si';
// export const {Service}Node: NodeDefinition = {
//     type: 'automation-{service-name}',
//     label: '{Service}',
//     description: '{Service} REST API',
//     Icon: Si{Service},
//     iconColor: 'text-blue-500',
//     dimensions: DIMENSIONS,
//     component: memo((props: NodeProps) => (
//         <AutomationNode {...props} Icon={Si{Service}} iconColor="text-blue-500" />
//     )),
// };

// Option B: Use SVG from /public/icons/{service}.svg
const {Service}Icon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/{service-name}.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
{Service}Icon.displayName = '{Service}Icon';

const {Service}NodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={{Service}Icon} iconColor="" />;
};

export const {Service}Node: NodeDefinition = {
    type: 'automation-{service-name}',
    label: '{Service}',
    description: '{Service description}',
    Icon: {Service}Icon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo({Service}NodeComponent),
};
```

**6. Update `frontend/app/components/workflow/nodes/nodeRegistry.ts`:**
```typescript
// Add import
import { {Service}Node } from './{Service}Node';

// Add to AVAILABLE_NODES array
export const AVAILABLE_NODES: NodeDefinition[] = [
    // ... existing nodes
    {Service}Node,
    // ... other nodes
];
```

**7. Remove from `frontend/app/components/workflow/nodes/DummyNodes.tsx` (if exists):**
If the service had a dummy placeholder node, remove it:
- Remove the icon creation line: `const {Service}Icon = createSvgIcon('{service}.svg');`
- Remove the node export: `export const {Service}Node = createDummyNode(...);`
- Remove from `DUMMY_NODES` array

## Template References

See supporting templates:
- [templates/node-template.py](templates/node-template.py) - Full node implementation template
- [templates/test-template.py](templates/test-template.py) - Test file template
- [templates/schema-template.json](templates/schema-template.json) - JSON schema template
- [reference.md](reference.md) - Detailed patterns and examples

## Checklist

When generating a node, ensure:

### Research
- [ ] Found official API documentation
- [ ] Identified ALL available endpoints (not just common ones)
- [ ] Documented authentication method
- [ ] Found credential setup URL
- [ ] Noted rate limits and constraints
- [ ] **Webhook support**: Does the API support webhooks? What events are available?

### Backend
- [ ] Created `backend/nodes/{service}_node.py`
- [ ] Implemented credential model with setup URL
- [ ] Created config models for ALL operations
- [ ] Implemented discriminated union with ALL configs
- [ ] Created node class with execute method
- [ ] Added handler method for EACH operation
- [ ] Proper error handling and timing
- [ ] **Response Format**: All handlers return arrays of OBJECTS (not primitives) for table parsing
- [ ] **Descriptive Properties**: Object properties have clear, descriptive names (e.g., "schema_name" not "name")
- [ ] **Consistent Structure**: Arrays wrapped in data object with descriptive property names

### Webhook Operations (if service supports webhooks)
- [ ] Created webhook config with `x-requires-webhook: true` in model_config
- [ ] Added `webhook_url` field with `ui:widget="webhook"`, `ui:copyable`, `ui:loadValue`
- [ ] Added optional `secret` field for HMAC verification
- [ ] Handler returns webhook payload from `inputs` parameter

### Frontend
- [ ] Generated `frontend/app/schemas/nodes/{service}.json`
- [ ] ALL operations in schema (not just common ones)
- [ ] Credential URL included (`x-credential-url`)
- [ ] Proper field descriptions and UI widgets

### Tests (COMPREHENSIVE COVERAGE REQUIRED)
- [ ] Created `backend/scripts/test_{service}_integration.py`
- [ ] **ONE test method per operation** (test count = operation count)
- [ ] Imported ALL config classes at top of file
- [ ] Tests organized by category matching node structure
- [ ] Write operations track created resources
- [ ] Cleanup runs in `finally` block
- [ ] Error handling tests (invalid IDs, missing auth)
- [ ] Performance tests (timing_ms verification)
- [ ] **VERIFIED**: Every config class has corresponding test

### Registration (7 files to update)
- [ ] `backend/nodes/core/registry.py` - Import node and add to NODE_REGISTRY
- [ ] `frontend/app/components/workflow/NodeConfig.tsx` - Import schema, add to SCHEMAS
- [ ] `frontend/app/components/workflow/NodeCredentials.tsx` - Import schema, add to NODE_SCHEMAS and CREDENTIAL_TYPE_MAP
- [ ] `frontend/app/utils/credentialAutoSelect.ts` - Import schema, add to NODE_SCHEMAS and CREDENTIAL_TYPE_MAP
- [ ] `frontend/app/components/workflow/nodes/{Service}Node.tsx` - Create node component
- [ ] `frontend/app/components/workflow/nodes/nodeRegistry.ts` - Import and add to AVAILABLE_NODES
- [ ] `frontend/app/components/workflow/nodes/DummyNodes.tsx` - Remove dummy if exists

## Example Services

This skill has been successfully used to generate nodes for:
- GitHub REST API (75 operations)
- Airtable REST API (24 operations)
- [Future: Slack, Notion, Stripe, Twilio, etc.]

## Best Practices

1. **Comprehensive Coverage**: Include ALL documented API operations, not just common ones
2. **Consistent Naming**: Use snake_case for actions, PascalCase for classes
3. **Clear Descriptions**: Every field should have a helpful description
4. **Credential Security**: Always use `ui:widget: password` for sensitive fields
5. **Error Handling**: Return structured errors with status codes
6. **Timing Information**: Include API request timing in responses
7. **Test Coverage**: Test every operation type, not just happy paths
8. **Database Connections**: For database nodes using asyncpg, ALWAYS set `statement_cache_size=0` to prevent prepared statement conflicts:
   ```python
   # ✅ CORRECT - Disables statement caching
   conn = await asyncpg.connect(dsn, statement_cache_size=0)

   # ❌ INCORRECT - Will cause "prepared statement already exists" errors
   conn = await asyncpg.connect(dsn)
   ```
   This prevents errors when connections are reused in workflows or when using PgBouncer with transaction/statement pooling modes.
