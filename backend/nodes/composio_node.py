"""Composio project automation against the published Platform API v3.1 contract.

Each operation makes one fixed API call; account/auth reads omit credential payloads.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://backend.composio.dev/api/v3.1"


class ComposioAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Composio API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://dashboard.composio.dev/~/project/settings/api-keys",
        "x-credential-instructions": "Paste a project API key from Composio project settings. Grant read access to connected accounts for the connection check, and permissions for the operations you use.",
    })
    credential_type: Literal["composio_api_key"] = Field("composio_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, repr=False, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the Composio project API key")
        return value


Identifier = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=1000)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(Input):
    limit: int = Field(50, ge=1, le=1000, description="Maximum results in this page; follow next_cursor explicitly.")
    cursor: str | None = Field(None, max_length=8192, description="Opaque next_cursor from the preceding page with the same filters.")


class ListTools(Page):
    """Discover tools and their schemas by toolkit or search query."""
    operation: Literal["list_tools"] = "list_tools"
    toolkit_slug: Identifier | None = None
    query: Text | None = None
    important: Literal["true", "false"] | None = None
    include_deprecated: bool = False


class GetTool(Input):
    """Read a tool's argument schema before executing it."""
    operation: Literal["get_tool"] = "get_tool"
    tool_slug: Identifier
    version: Identifier | None = None


class ExecuteTool(Input):
    """Execute one tool as an explicit connected account and user."""
    operation: Literal["execute_tool"] = "execute_tool"
    tool_slug: Identifier
    connected_account_id: Identifier
    user_id: Text
    arguments: dict[str, Any] = Field(default_factory=dict, description="Arguments matching the schema returned by get_tool.")
    version: str = Field("latest", max_length=256, pattern=r"^[A-Za-z0-9_-]+$", description="Use a fixed published version for repeatable workflows.")


class ListToolkits(Page):
    """Find toolkits available to the project."""
    operation: Literal["list_toolkits"] = "list_toolkits"
    search: Text | None = None
    category: Identifier | None = None
    sort_by: Literal["usage", "alphabetically"] | None = None


class GetToolkit(Input):
    """Read toolkit authentication requirements and metadata."""
    operation: Literal["get_toolkit"] = "get_toolkit"
    slug: Identifier
    version: str = Field("latest", max_length=256, pattern=r"^[A-Za-z0-9_-]+$")


class ListToolkitCategories(Input):
    """List toolkit categories for discovery filters."""
    operation: Literal["list_toolkit_categories"] = "list_toolkit_categories"


class ListAuthConfigs(Page):
    """List project authentication configurations without their secrets."""
    operation: Literal["list_auth_configs"] = "list_auth_configs"
    toolkit_slug: Identifier | None = None
    search: Text | None = None
    show_disabled: bool = False


class GetAuthConfig(Input):
    """Read an authentication configuration's non-secret metadata."""
    operation: Literal["get_auth_config"] = "get_auth_config"
    auth_config_id: Identifier


class CreateAuthConfig(Input):
    """Create a Composio-managed auth configuration for a toolkit."""
    operation: Literal["create_auth_config"] = "create_auth_config"
    toolkit_slug: Identifier
    name: str = Field(..., min_length=1, max_length=255)
    scopes: list[str] = Field(default_factory=list, max_length=100)


class DeleteAuthConfig(Input):
    """Delete one auth configuration; does not request upstream revocation."""
    operation: Literal["delete_auth_config"] = "delete_auth_config"
    auth_config_id: Identifier


class ListConnectedAccounts(Page):
    """Read the project's own connected account metadata as connection evidence."""
    operation: Literal["list_connected_accounts"] = "list_connected_accounts"
    user_ids: list[str] | None = Field(None, max_length=100)
    toolkit_slugs: list[str] | None = Field(None, max_length=100)
    statuses: list[Literal["INITIALIZING", "INITIATED", "ACTIVE", "FAILED", "EXPIRED", "INACTIVE", "REVOKED"]] | None = Field(None, max_length=7)


class GetConnectedAccount(Input):
    """Read one connected account, omitting connection state and credential data."""
    operation: Literal["get_connected_account"] = "get_connected_account"
    connected_account_id: Identifier


class DeleteConnectedAccount(Input):
    """Delete a connected account; does not request upstream revocation."""
    operation: Literal["delete_connected_account"] = "delete_connected_account"
    connected_account_id: Identifier


class ListTriggerTypes(Page):
    """Discover trigger types and their configuration schemas."""
    operation: Literal["list_trigger_types"] = "list_trigger_types"
    toolkit_slugs: list[str] | None = Field(None, max_length=100)


class GetTriggerType(Input):
    """Read the configuration and payload schemas of one trigger type."""
    operation: Literal["get_trigger_type"] = "get_trigger_type"
    slug: Identifier


class ListActiveTriggers(Page):
    """List project trigger instances with explicit pagination."""
    operation: Literal["list_active_triggers"] = "list_active_triggers"
    user_ids: list[str] | None = Field(None, max_length=100)
    show_disabled: bool = False


class UpsertTrigger(Input):
    """Create or update a trigger using an existing connected account."""
    operation: Literal["upsert_trigger"] = "upsert_trigger"
    slug: Identifier
    connected_account_id: Identifier
    user_id: Text
    trigger_config: dict[str, Any] = Field(default_factory=dict)
    type: Literal["poll", "webhook"] | None = None
    polling_interval: int | None = Field(None, ge=1, le=10080)


class UpdateTrigger(Input):
    """Enable or disable a trigger as the acting user."""
    operation: Literal["update_trigger"] = "update_trigger"
    trigger_id: Identifier
    user_id: Text
    status: Literal["enable", "disable"]


class DeleteTrigger(Input):
    """Delete one trigger instance."""
    operation: Literal["delete_trigger"] = "delete_trigger"
    trigger_id: Identifier


ComposioConfig = Annotated[Union[ListTools, GetTool, ExecuteTool, ListToolkits, GetToolkit,
    ListToolkitCategories, ListAuthConfigs, GetAuthConfig, CreateAuthConfig, DeleteAuthConfig,
    ListConnectedAccounts, GetConnectedAccount, DeleteConnectedAccount, ListTriggerTypes,
    GetTriggerType, ListActiveTriggers, UpsertTrigger, UpdateTrigger, DeleteTrigger], Field(discriminator="operation")]


class ComposioFullConfig(NodeConfig[ComposioConfig, ComposioAPIKeyCredential]):
    pass


# Fixed routes keep user inputs out of the origin and method. Each entry is one
# published OpenAPI operation, with only its named query/body fields admitted.
ROUTES = {
    "list_tools": ("GET", "/tools", None),
    "get_tool": ("GET", "/tools/{tool_slug}", "tool_slug"),
    "execute_tool": ("POST", "/tools/execute/{tool_slug}", "tool_slug"),
    "list_toolkits": ("GET", "/toolkits", None),
    "get_toolkit": ("GET", "/toolkits/{slug}", "slug"),
    "list_toolkit_categories": ("GET", "/toolkits/categories", None),
    "list_auth_configs": ("GET", "/auth_configs", None),
    "get_auth_config": ("GET", "/auth_configs/{auth_config_id}", "auth_config_id"),
    "create_auth_config": ("POST", "/auth_configs", None),
    "delete_auth_config": ("DELETE", "/auth_configs/{auth_config_id}", "auth_config_id"),
    "list_connected_accounts": ("GET", "/connected_accounts", None),
    "get_connected_account": ("GET", "/connected_accounts/{connected_account_id}", "connected_account_id"),
    "delete_connected_account": ("DELETE", "/connected_accounts/{connected_account_id}", "connected_account_id"),
    "list_trigger_types": ("GET", "/triggers_types", None),
    "get_trigger_type": ("GET", "/triggers_types/{slug}", "slug"),
    "list_active_triggers": ("GET", "/trigger_instances/active", None),
    "upsert_trigger": ("POST", "/trigger_instances/{slug}/upsert", "slug"),
    "update_trigger": ("PATCH", "/trigger_instances/manage/{trigger_id}", "trigger_id"),
    "delete_trigger": ("DELETE", "/trigger_instances/manage/{trigger_id}", "trigger_id"),
}
ACCOUNT_FIELDS = frozenset({"id", "word_id", "alias", "user_id", "status", "created_at", "updated_at", "toolkit", "auth_config", "is_disabled"})
AUTH_FIELDS = frozenset({"id", "uuid", "type", "toolkit", "name", "auth_scheme", "is_composio_managed", "status", "created_at", "last_updated_at", "no_of_connections", "is_enabled_for_tool_router"})
SECRET_FIELDS = frozenset({"api_key", "access_token", "refresh_token", "client_secret", "password", "private_key", "credentials", "shared_credentials", "shared_connection_fields", "connectionData", "state", "params"})


def _safe(value, key):
    if isinstance(value, dict):
        return {k: _safe(v, key) for k, v in value.items() if k not in SECRET_FIELDS}
    if isinstance(value, list):
        return [_safe(v, key) for v in value]
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    return value


def _metadata(row, fields):
    if not isinstance(row, dict):
        raise ValueError("Composio returned invalid resource metadata")
    return {k: v for k, v in row.items() if k in fields}


class ComposioNode(WorkflowNode):
    integration_type = "automation-composio"
    connection_evidence = ConnectionEvidence(noun="Composio connected accounts", operation="list_connected_accounts")

    @classmethod
    def get_config_model(cls):
        return ComposioFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Composio project API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, path, path_field = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        if path_field:
            path = path.replace("{" + path_field + "}", quote(values.pop(path_field), safe=""))
        params, body = {}, None
        if method == "GET":
            params = values
        elif config.operation == "create_auth_config":
            body = {"toolkit": {"slug": config.toolkit_slug}, "auth_config": {
                "type": "use_composio_managed_auth", "name": config.name,
                "credentials": {"scopes": config.scopes},
            }}
        elif method in {"POST", "PATCH"}:
            body = values
        # No retries: tool execution and writes may have effects even if a
        # response is lost. Redirects are refused to keep the key on this origin.
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"x-api-key": key, "Accept": "application/json"}, params=params,
                **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            message = f"Composio returned HTTP {response.status_code}"
            try:
                error = response.json()
                detail = error.get("message") or error.get("error")
                if isinstance(detail, str):
                    message = detail[:2000].replace(key, "[redacted]")
            except (ValueError, AttributeError):
                pass
            raise ValueError(f"{message} (HTTP {response.status_code})")
        if response.status_code == 204:
            return {"status": "success", "http_status": 204, "data": None}
        if len(response.content) > 10_000_000:
            raise ValueError("Composio response exceeds the size limit")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Composio returned invalid JSON") from None
        if not isinstance(data, dict):
            raise ValueError("Composio returned an unexpected response envelope")
        if data.get("successful") is False or data.get("success") is False:
            detail = data.get("error") or data.get("message") or "Composio reported an unsuccessful operation"
            raise ValueError(str(_safe(detail, key))[:2000])
        if config.operation.startswith("list_"):
            if not isinstance(data.get("items"), list):
                raise ValueError("Composio returned an invalid list envelope")
            fields = ACCOUNT_FIELDS if config.operation == "list_connected_accounts" else AUTH_FIELDS if config.operation == "list_auth_configs" else None
            if fields:
                data["items"] = [_metadata(row, fields) for row in data["items"]]
            data["has_more"] = bool(data.get("next_cursor"))
        elif config.operation == "get_connected_account":
            data = _metadata(data, ACCOUNT_FIELDS)
        elif config.operation == "get_auth_config":
            data = _metadata(data, AUTH_FIELDS)
        safe = _safe(data, key)
        return {"status": "success", "http_status": response.status_code, "data": safe,
            **({"items": safe["items"], "next_cursor": safe.get("next_cursor"), "has_more": safe["has_more"]} if config.operation.startswith("list_") else {})}
