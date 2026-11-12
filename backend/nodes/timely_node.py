"""Timely bearer-token operations pinned to the published V1 contract."""
from typing import Annotated, Literal, Union
from datetime import date
import httpx
from pydantic import BaseModel, ConfigDict, Field
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.timely import TIMELY_SCOPES
from utils.ssrf import guarded_async_client

class TimelyTokenCredential(BaseModel):
    model_config = ConfigDict(title="Timely Access Token", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://developer.timely.com/", "x-credential-instructions": "Copy a bearer token from the Timely API docs login and your workspace ID from the Timely app URL. Tokens expire; replace an expired token here."})
    credential_type: Literal["timely_token"] = "timely_token"
    access_token: str = Field(..., min_length=1, repr=False, title="Access Token", json_schema_extra={"ui:widget": "password"})
    account_id: int = Field(..., gt=0, title="Workspace ID", description="Numeric workspace ID from your Timely app URL.")

class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

class _Page(_Config):
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)

class _TimePage(_Config):
    per_page: int = Field(50, ge=1, le=200)
    page: int = Field(1, ge=1)
    day: date | None = None
    project_id: int | None = Field(None, gt=0)
    user_id: int | None = Field(None, gt=0)

class _ClientWrite(_Config):
    name: str = Field(..., min_length=1, max_length=255)
    active: bool | None = None
    color: str | None = Field(None, pattern=r"^([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")

class _ProjectWrite(_Config):
    name: str = Field(..., min_length=1)
    rate_type: Literal["project", "user", "non-billable"]
    company_id: int | None = Field(None, gt=0)
    hour_rate: float | None = Field(None, ge=0)
    budget: float | None = Field(None, ge=0)
    budget_type: Literal["H", "M"] | None = None
    active: bool | None = None
    external_id: str | None = None
    description: str | None = None

class _TimeWrite(_Config):
    project_id: int = Field(..., gt=0)
    day: date
    hours: int = Field(0, ge=0)
    minutes: int = Field(0, ge=0, le=59)
    seconds: int = Field(0, ge=0, le=59)
    note: str | None = None
    user_id: int | None = Field(None, gt=0)
    external_id: str | None = None
    billable: bool | None = None

class TimelyListClientsConfig(_Page):
    """List clients."""
    operation: Literal["list_clients"] = "list_clients"

class TimelyGetClientConfig(_Config):
    """Get client."""
    operation: Literal["get_client"] = "get_client"
    client_id: int = Field(..., gt=0)

class TimelyCreateClientConfig(_ClientWrite):
    """Create client."""
    operation: Literal["create_client"] = "create_client"

class TimelyUpdateClientConfig(_ClientWrite):
    """Update client."""
    operation: Literal["update_client"] = "update_client"
    client_id: int = Field(..., gt=0)

class TimelyListProjectsConfig(_Page):
    """List projects."""
    operation: Literal["list_projects"] = "list_projects"

class TimelyGetProjectConfig(_Config):
    """Get project."""
    operation: Literal["get_project"] = "get_project"
    project_id: int = Field(..., gt=0)

class TimelyCreateProjectConfig(_ProjectWrite):
    """Create project."""
    operation: Literal["create_project"] = "create_project"

class TimelyUpdateProjectConfig(_ProjectWrite):
    """Update project."""
    operation: Literal["update_project"] = "update_project"
    project_id: int = Field(..., gt=0)

class TimelyDeleteProjectConfig(_Config):
    """Delete project."""
    operation: Literal["delete_project"] = "delete_project"
    project_id: int = Field(..., gt=0)

class TimelyListTimeEntriesConfig(_TimePage):
    """List time entries."""
    operation: Literal["list_time_entries"] = "list_time_entries"

class TimelyGetTimeEntryConfig(_Config):
    """Get time entry."""
    operation: Literal["get_time_entry"] = "get_time_entry"
    time_entry_id: int = Field(..., gt=0)

class TimelyCreateTimeEntryConfig(_TimeWrite):
    """Create time entry."""
    operation: Literal["create_time_entry"] = "create_time_entry"

class TimelyUpdateTimeEntryConfig(_TimeWrite):
    """Update time entry."""
    operation: Literal["update_time_entry"] = "update_time_entry"
    time_entry_id: int = Field(..., gt=0)

class TimelyDeleteTimeEntryConfig(_Config):
    """Delete time entry."""
    operation: Literal["delete_time_entry"] = "delete_time_entry"
    time_entry_id: int = Field(..., gt=0)

class TimelyStartTimerConfig(_Config):
    """Start timer."""
    operation: Literal["start_timer"] = "start_timer"
    time_entry_id: int = Field(..., gt=0)

class TimelyStopTimerConfig(_Config):
    """Stop timer."""
    operation: Literal["stop_timer"] = "stop_timer"
    time_entry_id: int = Field(..., gt=0)

class TimelyGetCurrentUserConfig(_Config):
    """Get current user."""
    operation: Literal["get_current_user"] = "get_current_user"

class TimelyListUsersConfig(_Config):
    """List users."""
    operation: Literal["list_users"] = "list_users"

# Timely's own MCP server: agents get its tools through a person's Timely sign-in.
TimelyMcpCredential = mcp_credential("timely", "https://api.timelyapp.com/mcp", app="Timely")
TimelyCredential = Union[TimelyTokenCredential, TimelyMcpCredential]


TimelyConfig = Annotated[Union[TimelyListClientsConfig, TimelyGetClientConfig, TimelyCreateClientConfig, TimelyUpdateClientConfig, TimelyListProjectsConfig, TimelyGetProjectConfig, TimelyCreateProjectConfig, TimelyUpdateProjectConfig, TimelyDeleteProjectConfig, TimelyListTimeEntriesConfig, TimelyGetTimeEntryConfig, TimelyCreateTimeEntryConfig, TimelyUpdateTimeEntryConfig, TimelyDeleteTimeEntryConfig, TimelyStartTimerConfig, TimelyStopTimerConfig, TimelyGetCurrentUserConfig, TimelyListUsersConfig], Field(discriminator="operation")]

class TimelyFullConfig(NodeConfig[TimelyConfig, TimelyCredential]):
    pass

ROUTES = {'list_clients': ('GET', 'clients', 'client'), 'get_client': ('GET', 'clients/{id}', 'client'), 'create_client': ('POST', 'clients', 'client'), 'update_client': ('PUT', 'clients/{id}', 'client'), 'list_projects': ('GET', 'projects', 'project'), 'get_project': ('GET', 'projects/{id}', 'project'), 'create_project': ('POST', 'projects', 'project'), 'update_project': ('PUT', 'projects/{id}', 'project'), 'delete_project': ('DELETE', 'projects/{id}', 'project'), 'list_time_entries': ('GET', 'hours', 'time_entry'), 'get_time_entry': ('GET', 'hours/{id}', 'time_entry'), 'create_time_entry': ('POST', 'hours', 'time_entry'), 'update_time_entry': ('PUT', 'hours/{id}', 'time_entry'), 'delete_time_entry': ('DELETE', 'hours/{id}', 'time_entry'), 'start_timer': ('PUT', 'hours/{id}/start', 'time_entry'), 'stop_timer': ('PUT', 'hours/{id}/stop', 'time_entry'), 'get_current_user': ('GET', 'users/current', 'user'), 'list_users': ('GET', 'users', 'user')}

class TimelyNode(WorkflowNode):
    integration_type = "automation-timely"
    credential_provider_labels = {"timely": "Timely Account"}
    scope_registry = TIMELY_SCOPES
    connection_evidence = ConnectionEvidence(noun="Timely user", identity_operation="get_current_user")

    @classmethod
    def get_config_model(cls):
        return TimelyFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Timely access token")
        method, path, singular = ROUTES[config.operation]
        data = config.model_dump(mode="json", exclude_none=True)
        data.pop("operation")
        if "{id}" in path:
            path = path.replace("{id}", str(data.pop(singular + "_id")))
        body = None
        params = None
        if method == "GET":
            params = data
        elif config.operation.startswith(("create_", "update_")):
            body = {{"client": "client", "project": "project", "time_entry": "event"}[singular]: data}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, f"https://api.timelyapp.com/1.1/{credential.account_id}/{path}",
                headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"}, params=params, json=body)
        if not 200 <= response.status_code < 300:
            return {"status": "error", "http_status": response.status_code, "error": response.text[:2000].replace(credential.access_token, "[redacted]")}
        if response.status_code == 204:
            return {"status": "success", "deleted": True}
        result = response.json()
        if not isinstance(result, (dict, list)) or (isinstance(result, dict) and ("error" in result or "errors" in result)):
            raise ValueError("Timely returned an unexpected response")
        output = {"status": "success", "data": result}
        if config.operation.startswith("list_") and hasattr(config, "limit"):
            output.update(offset=config.offset, next_offset=config.offset + len(result) if len(result) == config.limit else None)
        if config.operation == "list_time_entries":
            output["next_page"] = config.page + 1 if len(result) == config.per_page else None
        return output
