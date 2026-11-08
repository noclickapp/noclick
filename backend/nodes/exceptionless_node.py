"""Exceptionless v2 account, project, event and stack automation.

Contract: https://api.exceptionless.io/docs/v2/openapi.json (v2).
User-scoped bearer tokens are described at
https://exceptionless.com/docs/api/api-getting-started/.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.exceptionless.io/api/v2"


class ExceptionlessUserTokenCredential(BaseModel):
    model_config = ConfigDict(title="Exceptionless User Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://exceptionless.com/docs/api/api-getting-started/",
            "x-credential-instructions": "Paste an existing user-scoped token, without Bearer. A project client token cannot manage projects or triage stacks. User tokens have full account access; keep them secret. NoClick sends this token only to api.exceptionless.io.",
        })
    credential_type: Literal["exceptionless_user_token"] = Field("exceptionless_user_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="User token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetCurrentUser(_Input):
    """Get current user."""
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})


class ListOrganizations(_Input):
    """List organizations."""
    operation: Literal["list_organizations"] = Field("list_organizations", json_schema_extra={"ui:hidden": True})
    filter: str | None = Field(None, max_length=2000)


class GetOrganization(_Input):
    """Get organization."""
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"ui:hidden": True})
    organization_id: str = Field(..., pattern=r"^[a-zA-Z0-9]{24,36}$")


class ListProjects(_Input):
    """List projects."""
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})
    filter: str | None = Field(None, max_length=2000)
    sort: str | None = Field(None, max_length=2000)
    page: int = Field(1, ge=1, le=1000000)
    limit: int = Field(10, ge=1, le=100)


class GetProject(_Input):
    """Get project."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})
    project_id: str = Field(..., pattern=r"^[a-zA-Z0-9]{24,36}$")


class CreateProject(_Input):
    """Create project."""
    operation: Literal["create_project"] = Field("create_project", json_schema_extra={"ui:hidden": True})
    organization_id: str = Field(..., pattern=r"^[a-fA-F0-9]{24}$")
    name: str = Field(..., min_length=1, max_length=1000)
    delete_bot_data_enabled: bool = Field(False)


class UpdateProject(_Input):
    """Update project."""
    operation: Literal["update_project"] = Field("update_project", json_schema_extra={"ui:hidden": True})
    project_id: str = Field(..., pattern=r"^[a-zA-Z0-9]{24,36}$")
    name: str = Field(..., min_length=1, max_length=1000)


class ListStacks(_Input):
    """List stacks."""
    operation: Literal["list_stacks"] = Field("list_stacks", json_schema_extra={"ui:hidden": True})
    filter: str | None = Field(None, max_length=2000)
    sort: str | None = Field(None, max_length=2000)
    time: str | None = Field(None, max_length=2000)
    page: int = Field(1, ge=1, le=1000000)
    limit: int = Field(10, ge=1, le=100)


class GetStack(_Input):
    """Get stack."""
    operation: Literal["get_stack"] = Field("get_stack", json_schema_extra={"ui:hidden": True})
    stack_id: str = Field(..., pattern=r"^[a-zA-Z0-9]{24,36}$")


class ListProjectStacks(_Input):
    """List project stacks."""
    operation: Literal["list_project_stacks"] = Field("list_project_stacks", json_schema_extra={"ui:hidden": True})
    project_id: str = Field(..., pattern=r"^[a-zA-Z0-9]{24,36}$")
    filter: str | None = Field(None, max_length=2000)
    sort: str | None = Field(None, max_length=2000)
    time: str | None = Field(None, max_length=2000)
    page: int = Field(1, ge=1, le=1000000)
    limit: int = Field(10, ge=1, le=100)


class MarkStacksFixed(_Input):
    """Mark stacks fixed."""
    operation: Literal["mark_stacks_fixed"] = Field("mark_stacks_fixed", json_schema_extra={"ui:hidden": True})
    stack_ids: str = Field(..., pattern=r"^[a-zA-Z0-9]{24,36}(,[a-zA-Z0-9]{24,36})*$", max_length=3699, description="Comma-separated stack IDs; at most 100.")
    version: str | None = Field(None, max_length=2000)


class SnoozeStacks(_Input):
    """Snooze stacks."""
    operation: Literal["snooze_stacks"] = Field("snooze_stacks", json_schema_extra={"ui:hidden": True})
    stack_ids: str = Field(..., pattern=r"^[a-zA-Z0-9]{24,36}(,[a-zA-Z0-9]{24,36})*$", max_length=3699, description="Comma-separated stack IDs; at most 100.")
    snooze_until_utc: str = Field(..., description="Timezone-aware ISO 8601 timestamp for snoozeUntilUtc.", json_schema_extra={"format": "date-time"})

    @field_validator("snooze_until_utc")
    @classmethod
    def timestamp(cls, value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Include the timestamp's UTC offset")
        return value


class MarkStacksCritical(_Input):
    """Mark stacks critical."""
    operation: Literal["mark_stacks_critical"] = Field("mark_stacks_critical", json_schema_extra={"ui:hidden": True})
    stack_ids: str = Field(..., pattern=r"^[a-zA-Z0-9]{24,36}(,[a-zA-Z0-9]{24,36})*$", max_length=3699, description="Comma-separated stack IDs; at most 100.")


class UnmarkStacksCritical(_Input):
    """Unmark stacks critical."""
    operation: Literal["unmark_stacks_critical"] = Field("unmark_stacks_critical", json_schema_extra={"ui:hidden": True})
    stack_ids: str = Field(..., pattern=r"^[a-zA-Z0-9]{24,36}(,[a-zA-Z0-9]{24,36})*$", max_length=3699, description="Comma-separated stack IDs; at most 100.")


class AddStackLink(_Input):
    """Add stack link."""
    operation: Literal["add_stack_link"] = Field("add_stack_link", json_schema_extra={"ui:hidden": True})
    stack_id: str = Field(..., pattern=r"^[a-zA-Z0-9]{24,36}$")
    link: str = Field(..., min_length=1, max_length=2048, pattern=r"^https?://[^\s]+$", description="Reference URL to add or remove.")


class RemoveStackLink(_Input):
    """Remove stack link."""
    operation: Literal["remove_stack_link"] = Field("remove_stack_link", json_schema_extra={"ui:hidden": True})
    stack_id: str = Field(..., pattern=r"^[a-zA-Z0-9]{24,36}$")
    link: str = Field(..., min_length=1, max_length=2048, pattern=r"^https?://[^\s]+$", description="Reference URL to add or remove.")


class ListEvents(_Input):
    """List events."""
    operation: Literal["list_events"] = Field("list_events", json_schema_extra={"ui:hidden": True})
    filter: str | None = Field(None, max_length=2000)
    sort: str | None = Field(None, max_length=2000)
    time: str | None = Field(None, max_length=2000)
    page: int = Field(1, ge=1, le=1000000)
    limit: int = Field(10, ge=1, le=100)


class GetEvent(_Input):
    """Get event."""
    operation: Literal["get_event"] = Field("get_event", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., pattern=r"^[a-zA-Z0-9]{24,36}$")


class CountEvents(_Input):
    """Count events."""
    operation: Literal["count_events"] = Field("count_events", json_schema_extra={"ui:hidden": True})
    filter: str | None = Field(None, max_length=2000)
    time: str | None = Field(None, max_length=2000)


class ListStackEvents(_Input):
    """List stack events."""
    operation: Literal["list_stack_events"] = Field("list_stack_events", json_schema_extra={"ui:hidden": True})
    stack_id: str = Field(..., pattern=r"^[a-zA-Z0-9]{24,36}$")
    filter: str | None = Field(None, max_length=2000)
    sort: str | None = Field(None, max_length=2000)
    time: str | None = Field(None, max_length=2000)
    page: int = Field(1, ge=1, le=1000000)
    limit: int = Field(10, ge=1, le=100)


ExceptionlessOperation = Annotated[Union[GetCurrentUser, ListOrganizations, GetOrganization, ListProjects, GetProject, CreateProject, UpdateProject, ListStacks, GetStack, ListProjectStacks, MarkStacksFixed, SnoozeStacks, MarkStacksCritical, UnmarkStacksCritical, AddStackLink, RemoveStackLink, ListEvents, GetEvent, CountEvents, ListStackEvents], Field(discriminator="operation")]


class ExceptionlessNodeConfig(NodeConfig[ExceptionlessOperation, ExceptionlessUserTokenCredential]):
    pass


ROUTES = {
    "get_current_user": ('GET', '/users/me', (), 200, 'object'),
    "list_organizations": ('GET', '/organizations', ('filter',), 200, 'array'),
    "get_organization": ('GET', '/organizations/{organization_id}', (), 200, 'object'),
    "list_projects": ('GET', '/projects', ('filter', 'sort', 'page', 'limit'), 200, 'array'),
    "get_project": ('GET', '/projects/{project_id}', (), 200, 'object'),
    "create_project": ('POST', '/projects', (), 201, 'object'),
    "update_project": ('PATCH', '/projects/{project_id}', (), 200, 'object'),
    "list_stacks": ('GET', '/stacks', ('filter', 'sort', 'time', 'page', 'limit'), 200, 'array'),
    "get_stack": ('GET', '/stacks/{stack_id}', (), 200, 'object'),
    "list_project_stacks": ('GET', '/projects/{project_id}/stacks', ('filter', 'sort', 'time', 'page', 'limit'), 200, 'array'),
    "mark_stacks_fixed": ('POST', '/stacks/{stack_ids}/mark-fixed', ('version',), 200, 'empty'),
    "snooze_stacks": ('POST', '/stacks/{stack_ids}/mark-snoozed', ('snooze_until_utc',), 200, 'empty'),
    "mark_stacks_critical": ('POST', '/stacks/{stack_ids}/mark-critical', (), 200, 'empty'),
    "unmark_stacks_critical": ('DELETE', '/stacks/{stack_ids}/mark-critical', (), 204, 'empty'),
    "add_stack_link": ('POST', '/stacks/{stack_id}/add-link', (), 200, 'empty'),
    "remove_stack_link": ('POST', '/stacks/{stack_id}/remove-link', (), 204, 'empty'),
    "list_events": ('GET', '/events', ('filter', 'sort', 'time', 'page', 'limit'), 200, 'array'),
    "get_event": ('GET', '/events/{event_id}', (), 200, 'object'),
    "count_events": ('GET', '/events/count', ('filter', 'time'), 200, 'object'),
    "list_stack_events": ('GET', '/stacks/{stack_id}/events', ('filter', 'sort', 'time', 'page', 'limit'), 200, 'array'),
}


class ExceptionlessNode(WorkflowNode):
    integration_type = "automation-exceptionless"
    connection_evidence = ConnectionEvidence(operation="list_organizations", noun="organizations")
    edit_examples = ["List Exceptionless events", "Mark stacks fixed after a deployment", "Create an Exceptionless project"]

    @classmethod
    def get_config_model(cls):
        return ExceptionlessNodeConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an Exceptionless user token")
        method, path, query_fields, expected_status, shape = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        for name, value in values.items():
            if "{" + name + "}" in path:
                path = path.replace("{" + name + "}", quote(str(value), safe="," if name == "stack_ids" else ""))
        params = {("snoozeUntilUtc" if name == "snooze_until_utc" else name): values[name]
                  for name in query_fields if name in values}
        body = None
        if config.operation == "create_project":
            body = {name: values[name] for name in ("organization_id", "name", "delete_bot_data_enabled")}
        elif config.operation == "update_project":
            body = {"name": config.name}
        elif config.operation in {"add_stack_link", "remove_stack_link"}:
            body = {"value": config.link}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, params=params,
                headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        if response.status_code != expected_status:
            message = response.text[:2000].replace(credential.api_token, "[redacted]")
            return {"status": "error", "http_status": response.status_code,
                    "error": "Exceptionless: " + message,
                    "write_outcome_unknown": method != "GET" and (response.status_code < 400 or response.status_code >= 500)}
        result = {"status": "success", "operation": config.operation, "http_status": response.status_code}
        if shape == "empty":
            return {**result, "acknowledged": True}
        if len(response.content) > 5_000_000:
            raise ValueError("Exceptionless response exceeds the supported size")
        media = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if media != "application/json" and not (media.startswith("application/") and media.endswith("+json")):
            raise ValueError("Expected Exceptionless JSON")
        data = response.json()
        if isinstance(data, dict) and (data.get("error") or data.get("errors")):
            raise ValueError("Exceptionless returned an error envelope")
        if shape == "array":
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError("Expected an Exceptionless resource list")
            # Return one requested page; no provider continuation URL is followed.
            return {**result, "items": data, **({"page": config.page, "limit": config.limit} if hasattr(config, "page") else {})}
        if not isinstance(data, dict):
            raise ValueError("Expected an Exceptionless resource object")
        return {**result, "data": data}
