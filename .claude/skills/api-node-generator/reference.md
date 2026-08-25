# API Node Generator Reference

Detailed reference for common patterns, authentication types, and API conventions.

## Authentication Patterns

### Pattern 1: API Key (Header)

Most common pattern. API key sent in header.

```python
class ServiceApiKeyCredential(BaseModel):
    """API Key credential"""
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your API key from {url}",
        json_schema_extra={"ui:widget": "password"}
    )

    class Config:
        json_schema_extra = {
            "x-credential-url": "https://service.com/settings/api"
        }

# In request
headers = {
    "Authorization": f"Bearer {credentials.api_key}",
    # OR
    "X-API-Key": credentials.api_key,
    # OR
    "Api-Key": credentials.api_key,
}
```

### Pattern 2: Basic Auth

Username/password combination.

```python
class ServiceBasicCredential(BaseModel):
    """Basic auth credential"""
    username: str = Field(..., title="Username")
    password: str = Field(
        ...,
        title="Password",
        json_schema_extra={"ui:widget": "password"}
    )

# In request
import base64
auth_string = base64.b64encode(f"{credentials.username}:{credentials.password}".encode()).decode()
headers = {"Authorization": f"Basic {auth_string}"}
```

### Pattern 3: OAuth 2.0

For services requiring OAuth flow.

```python
class ServiceOAuthCredential(BaseModel):
    """OAuth 2.0 credential"""
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: str = Field(..., title="Token Expiry")  # ISO 8601
    email: Optional[str] = Field(None, title="Account Email")

    class Config:
        json_schema_extra = {
            "x-credential-type": "oauth",
            "x-oauth-provider": "service_name",
            "x-oauth-scopes": [
                "read",
                "write"
            ]
        }

# Token refresh logic
async def _ensure_fresh_token(self, credentials) -> str:
    from datetime import datetime
    expires = datetime.fromisoformat(credentials.expires_at.replace('Z', '+00:00'))
    if datetime.now(expires.tzinfo) >= expires:
        # Refresh the token
        new_tokens = await self._refresh_token(credentials.refresh_token)
        return new_tokens.access_token
    return credentials.access_token
```

### Pattern 4: Custom Token

Service-specific token patterns.

```python
class ServiceTokenCredential(BaseModel):
    """Custom token credential"""
    token: str = Field(
        ...,
        title="Access Token",
        json_schema_extra={"ui:widget": "password"}
    )
    workspace_id: str = Field(..., title="Workspace ID")

# In request
headers = {
    "Authorization": f"Token {credentials.token}",
    "X-Workspace-Id": credentials.workspace_id
}
```

## Common API Patterns

### Pagination

```python
# Offset-based
class ListConfig(BaseModel):
    page: Optional[int] = Field(1, title="Page", ge=1)
    per_page: Optional[int] = Field(20, title="Per Page", ge=1, le=100)

# Cursor-based
class ListConfig(BaseModel):
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor from previous response")
    limit: Optional[int] = Field(20, title="Limit", ge=1, le=100)

# In response handling
result = {
    "data": items,
    "pagination": {
        "has_more": len(items) == config.limit,
        "next_cursor": response_data.get("next_cursor")
    }
}
```

### Filtering

```python
class ListConfig(BaseModel):
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Filter by status",
        json_schema_extra={"enum": ["active", "inactive", "pending"]}
    )
    created_after: Optional[str] = Field(
        None,
        title="Created After",
        description="ISO 8601 datetime"
    )
    tags: Optional[List[str]] = Field(
        None,
        title="Tags",
        description="Filter by tags"
    )
```

### Sorting

```python
class ListConfig(BaseModel):
    sort_by: Optional[str] = Field(
        "created_at",
        title="Sort By",
        json_schema_extra={"enum": ["created_at", "updated_at", "name"]}
    )
    sort_order: Optional[str] = Field(
        "desc",
        title="Sort Order",
        json_schema_extra={"enum": ["asc", "desc"]}
    )
```

## Field UI Widgets

### Password (for secrets)
```python
Field(..., json_schema_extra={"ui:widget": "password"})
```

### Textarea (for long text)
```python
Field(..., json_schema_extra={"ui:widget": "textarea"})
```

### Hidden (for discriminators)
```python
Field(..., json_schema_extra={"const": "value", "ui:hidden": True})
```

### Enum/Select
```python
Field(..., json_schema_extra={"enum": ["option1", "option2"]})
```

### Dynamic Dropdown
```python
Field(
    ...,
    json_schema_extra={
        "x-dynamic-options": {
            "field_name": "resource_id",
            "placeholder": "Select resource...",
            "searchable": True
        }
    }
)
```

## HTTP Client Patterns

### Standard Request with Error Handling

```python
async def _make_request(
    self,
    method: str,
    endpoint: str,
    credentials,
    params: Optional[Dict] = None,
    json_body: Optional[Dict] = None,
    action_name: str = "request"
) -> Dict[str, Any]:
    url = f"{API_BASE}{endpoint}"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {credentials.api_key}"
    }

    # Clean None values from params
    if params:
        params = {k: v for k, v in params.items() if v is not None}

    start_time = time.time()

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_body
            )

            api_time = (time.time() - start_time) * 1000

            # Handle errors
            if response.status_code >= 400:
                error_text = response.text
                try:
                    error_data = response.json()
                    error_msg = error_data.get("message") or error_data.get("error") or error_text
                except:
                    error_msg = error_text

                return {
                    "status": "error",
                    "action": action_name,
                    "error": error_msg,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)}
                }

            # Handle empty responses
            if response.status_code == 204:
                data = {"success": True}
            else:
                data = response.json()

            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": round(api_time, 2)}
            }

        except httpx.TimeoutException:
            return {"status": "error", "action": action_name, "error": "Request timeout", "status_code": 408}
        except Exception as e:
            return {"status": "error", "action": action_name, "error": str(e), "status_code": 500}
```

### Handling Rate Limits

```python
async def _make_request_with_retry(self, ...):
    max_retries = 3
    retry_delay = 1.0

    for attempt in range(max_retries):
        result = await self._make_request(...)

        if result["status_code"] == 429:  # Rate limited
            retry_after = int(result.get("headers", {}).get("Retry-After", retry_delay))
            logger.warning(f"Rate limited, waiting {retry_after}s")
            await asyncio.sleep(retry_after)
            retry_delay *= 2  # Exponential backoff
            continue

        return result

    return result  # Return last result after all retries
```

## Common Service Patterns

### Slack API
- Base URL: `https://slack.com/api/`
- Auth: Bearer token or OAuth
- Response format: `{"ok": true/false, "data": ..., "error": "..."}`

### Notion API
- Base URL: `https://api.notion.com/v1/`
- Auth: Bearer token (Integration token)
- Header: `Notion-Version: 2022-06-28`

### Stripe API
- Base URL: `https://api.stripe.com/v1/`
- Auth: Basic auth with API key as username

### Twilio API
- Base URL: `https://api.twilio.com/2010-04-01/`
- Auth: Basic auth (Account SID + Auth Token)

### Airtable API
- Base URL: `https://api.airtable.com/v0/`
- Auth: Bearer token (PAT)

### HubSpot API
- Base URL: `https://api.hubapi.com/`
- Auth: Bearer token (Private app token)

## Testing Patterns

### Read-Only Tests (Safe)
```python
async def test_list_items(self):
    """Safe: Lists items without modifications"""
    config = ListItemsConfig(per_page=5)
    result = await self.create_node(config).execute({})
    assert result["status"] == "success"
```

### Create-Cleanup Tests
```python
async def test_create_item(self):
    """Creates item and tracks for cleanup"""
    config = CreateItemConfig(name=f"Test {int(time.time())}")
    result = await self.create_node(config).execute({})

    if result["status"] == "success" and result["data"].get("id"):
        self.created_resources.append(("item", result["data"]["id"]))

    assert result["status"] == "success"
```

### Error Case Tests
```python
async def test_not_found(self):
    """Tests 404 handling"""
    config = GetItemConfig(item_id="nonexistent-id-12345")
    result = await self.create_node(config).execute({})

    assert result["status"] == "error"
    assert result["status_code"] == 404
```

## Naming Conventions

### Actions (snake_case)
- `list_items` - List multiple resources
- `get_item` - Get single resource
- `create_item` - Create resource
- `update_item` - Update resource
- `delete_item` - Delete resource
- `search_items` - Search with query

### Config Classes (PascalCase)
- `ServiceListItemsConfig`
- `ServiceGetItemConfig`
- `ServiceCreateItemConfig`

### Node Classes
- `ServiceNode` (e.g., `SlackNode`, `NotionNode`)

### File Names (kebab-case)
- Backend: `backend/nodes/service_name_node.py`
- Frontend: `frontend/app/schemas/nodes/service-name.json`
- Tests: `backend/scripts/test_service_name_integration.py`

## Checklist for New Service

### Research Phase
- [ ] Official API documentation URL
- [ ] API base URL and version
- [ ] Authentication method(s)
- [ ] Rate limits
- [ ] List all endpoints by category
- [ ] Note request/response formats
- [ ] Find credential setup URL

### Implementation Phase
- [ ] Credential model with setup URL
- [ ] Config model for each operation
- [ ] Discriminated union
- [ ] Full node config class
- [ ] Node class with execute()
- [ ] _make_request() helper
- [ ] Handler for each operation

### Schema Phase
- [ ] JSON schema for all configs
- [ ] Credential schema with x-credential-url
- [ ] Proper field descriptions
- [ ] UI widgets where needed

### Testing Phase
- [ ] Tests for each operation
- [ ] Error handling tests
- [ ] Timing tests
- [ ] Cleanup logic

### Registration Phase
- [ ] backend/nodes/core/registry.py
- [ ] FlowCanvas.tsx SCHEMAS
- [ ] NodeConfig.tsx SCHEMAS
- [ ] NodeCredentials.tsx NODE_SCHEMAS
- [ ] ServiceNode.tsx component
- [ ] nodeRegistry.ts AVAILABLE_NODES
