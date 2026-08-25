# Workflow Node Templates

Copy-paste templates for common patterns.

## Minimal Node (API Key Credential)

```python
"""
My Node - Does X with Y service.
"""
from typing import Dict, Any, Optional, Type
from pydantic import BaseModel, Field
from nodes.base_node import WorkflowNode, NodeConfig


class MyAPICredential(BaseModel):
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})


class MyNodeConfigData(BaseModel):
    input_field: str = Field(..., title="Input", description="What to process")


class MyNodeConfig(NodeConfig[MyNodeConfigData, MyAPICredential]):
    pass


class MyNode(WorkflowNode):
    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return MyNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config = self.config
        if not config:
            raise ValueError("Config required")

        api_key = config.credentials.api_key if config.credentials else None
        if not api_key:
            raise ValueError("API key required")

        # Do work
        result = f"Processed: {config.config.input_field}"

        return {"status": "success", "result": result}
```

## OAuth Node with Dynamic Dropdown

```python
"""
OAuth Node - Integrates with OAuth service.
"""
from typing import Dict, Any, Optional, Type, List
from pydantic import BaseModel, Field
from nodes.base_node import WorkflowNode, NodeConfig
import httpx


class MyOAuthCredential(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: str
    email: str

    class Config:
        json_schema_extra = {
            "x-credential-type": "oauth",
            "x-oauth-provider": "my_provider",
            "x-oauth-scopes": ["https://api.example.com/read"]
        }


class MyNodeConfigData(BaseModel):
    resource_id: str = Field(
        ...,
        title="Resource",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "resource_id",
                "placeholder": "Select...",
                "searchable": True
            }
        }
    )


class MyNodeConfig(NodeConfig[MyNodeConfigData, MyOAuthCredential]):
    pass


class MyNode(WorkflowNode):
    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return MyNodeConfig

    @classmethod
    async def load_field_options(
        cls, field_name: str, credential_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        if field_name == "resource_id":
            token = credential_data.get("access_token")
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.example.com/resources",
                    headers={"Authorization": f"Bearer {token}"}
                )
                items = resp.json().get("items", [])
                return [{"value": i["id"], "label": i["name"]} for i in items]
        return []

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config = self.config
        if not config or not config.credentials:
            raise ValueError("OAuth credentials required")

        token = config.credentials.access_token
        # Make API call with token
        return {"status": "success"}
```

## Multi-Operation Node (Discriminated Union)

```python
from typing import Union

class ReadConfig(BaseModel):
    operation: str = Field("read", json_schema_extra={"const": "read", "ui:hidden": True})
    resource_id: str = Field(..., title="Resource")

class WriteConfig(BaseModel):
    operation: str = Field("write", json_schema_extra={"const": "write", "ui:hidden": True})
    resource_id: str = Field(..., title="Resource")
    data: str = Field(..., title="Data", json_schema_extra={"ui:widget": "textarea"})

class DeleteConfig(BaseModel):
    operation: str = Field("delete", json_schema_extra={"const": "delete", "ui:hidden": True})
    resource_id: str = Field(..., title="Resource")

MyNodeConfigData = Union[ReadConfig, WriteConfig, DeleteConfig]


class MyNodeConfig(NodeConfig[MyNodeConfigData, MyCredential]):
    pass


class MyNode(WorkflowNode):
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config = self.config.config

        if isinstance(config, ReadConfig):
            return await self._read(config)
        elif isinstance(config, WriteConfig):
            return await self._write(config)
        elif isinstance(config, DeleteConfig):
            return await self._delete(config)
```

## Frontend Registration

### FlowCanvas.tsx (in autoSelectCredential)
```typescript
const SCHEMAS: Record<string, any> = {
    'automation-my-service': (await import('~/schemas/nodes/my-node.json')).default,
};

const typeMap: Record<string, string> = {
    'MyOAuthCredential': 'my_service_oauth',
};
```

### nodeRegistry.ts
```typescript
{
    id: 'automation-my-service',
    type: 'automation-my-service',
    label: 'My Service',
    category: 'integrations',
    icon: CloudIcon,  // from lucide-react
    dimensions: { width: 200, height: 80, iconSize: 24 },
    description: 'Connect to My Service',
},
```

## Webhook Trigger Node

For nodes that receive external HTTP webhooks:

```python
"""
Webhook-enabled node - receives external HTTP calls.
"""
from typing import Dict, Any, Optional, Type, Union
from pydantic import BaseModel, Field, ConfigDict
from nodes.base_node import WorkflowNode, NodeConfig


class ReceiveWebhookConfig(BaseModel):
    """Config for webhook receive operation"""
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: str = Field(
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


class SendMessageConfig(BaseModel):
    """Config for non-webhook operation"""
    operation: str = Field(
        "send_message",
        json_schema_extra={"const": "send_message", "ui:hidden": True}
    )
    message: str = Field(..., title="Message")


# Webhooks auto-cleanup when switching between operations
MyNodeConfigData = Union[ReceiveWebhookConfig, SendMessageConfig]


class MyWebhookNodeConfig(NodeConfig[MyNodeConfigData, None]):
    """Full config (no credentials for this example)"""
    pass


class MyWebhookNode(WorkflowNode):
    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return MyWebhookNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config = self.config
        if not config:
            raise ValueError("Config required")

        op_config = config.config
        if isinstance(op_config, ReceiveWebhookConfig):
            # For webhook triggers, inputs contains the webhook payload
            webhook_meta = inputs.get("_webhook", {})
            return {
                "status": "triggered",
                "method": webhook_meta.get("method", "POST"),
                "headers": webhook_meta.get("headers", {}),
                "payload": {k: v for k, v in inputs.items() if k != "_webhook"},
            }
        elif isinstance(op_config, SendMessageConfig):
            return {"status": "sent", "message": op_config.message}

        raise ValueError(f"Unknown operation")
```

**Key Points:**
- `ui:widget="webhook"` tells WebhookManager to auto-generate URL
- `ui:loadValue` triggers backend to load value when field renders
- `x-requires-webhook: true` on operation config marks it as webhook-requiring
- Webhook cleanup happens automatically when operation changes or node is deleted

## Schema Generation Command

```bash
cd backend && python -c "
from nodes.my_node import MyNode
import json
schema = MyNode.get_config_schema()
with open('../frontend/app/schemas/nodes/my-node.json', 'w') as f:
    json.dump(schema, f, indent=2)
print('Schema generated')
"
```
