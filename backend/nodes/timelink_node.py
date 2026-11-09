"""Timelink v1 clients, projects, services and time entries.

Contract: https://api.timelink.io/docs?api-docs.json (1.0.0).
Every action issues exactly one request; list actions return one provider page.
"""
from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.timelink.io/api/v1"


class TimelinkTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Timelink API Token",
        extra="ignore",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.timelink.io/api",
            "x-credential-instructions": "Create an API token under My Account > API Tokens in Timelink and paste it here. Grant access to the resources your workflow uses. NoClick sends it as a bearer token to api.timelink.io. Client reads verify the connection; other permissions depend on the token.",
        },
    )
    credential_type: Literal["timelink_api_token"] = Field(
        "timelink_api_token", json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(
        ...,
        title="API token",
        min_length=1,
        max_length=4096,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(
            c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value
        ):
            raise ValueError("Paste the token without the Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator(
        "started_at",
        "ended_at",
        "billed_at",
        "start",
        "end",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def dates(cls, value, info):
        if info.field_name in {
            "started_at",
            "ended_at",
            "billed_at",
            "start",
            "end",
        } and isinstance(value, str):
            # The published examples also use HTTP-date; normalize to RFC 3339.
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                try:
                    return parsedate_to_datetime(value)
                except (ValueError, TypeError):
                    raise ValueError(
                        "Use an ISO 8601 timestamp with timezone"
                    ) from None
        return value

    @model_validator(mode="after")
    def timestamps(self):
        for name in ("started_at", "ended_at", "billed_at", "start", "end"):
            value = getattr(self, name, None)
            if isinstance(value, datetime) and value.tzinfo is None:
                raise ValueError("Timestamps require a timezone")
        start, end = getattr(self, "started_at", None), getattr(self, "ended_at", None)
        if start is not None and end is not None and end < start:
            raise ValueError("End time must not precede start time")
        return self


class _Identified(_Input):
    id: str = Field(
        ..., min_length=1, max_length=200, description="Timelink resource ID."
    )

    @field_validator("id")
    @classmethod
    def resource_id(cls, value):
        if (
            not value.strip()
            or value in {".", ".."}
            or any(c in value for c in "/\\?#")
            or any(ord(c) < 33 for c in value)
        ):
            raise ValueError("Paste a single Timelink resource ID")
        return value


class GetTokenConfig(_Input):
    """Get details to your token.."""

    operation: Literal["get_token"] = Field(
        "get_token", json_schema_extra={"ui:hidden": True}
    )


class GetCompanyConfig(_Input):
    """Get all company details."""

    operation: Literal["get_company"] = Field(
        "get_company", json_schema_extra={"ui:hidden": True}
    )


class ListClientsConfig(_Input):
    """Get all clients."""

    operation: Literal["list_clients"] = Field(
        "list_clients", json_schema_extra={"ui:hidden": True}
    )
    limit: int | None = Field(None, ge=1, le=1000)
    search: str | None = Field(None, max_length=10000)
    active: StrictBool | None = Field(None)
    withLimitedPartOfProjects: StrictBool | None = Field(None)
    projectsLimit: int | None = Field(None, ge=1, le=1000)


class GetClientConfig(_Identified):
    """Get Client."""

    operation: Literal["get_client"] = Field(
        "get_client", json_schema_extra={"ui:hidden": True}
    )


class CreateClientConfig(_Input):
    """Create new client."""

    operation: Literal["create_client"] = Field(
        "create_client", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(..., min_length=1, max_length=10000)
    ext_tool_id: str | None = Field(None, max_length=10000)
    info: str | None = Field(None, max_length=10000)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$", max_length=10000)
    active: StrictBool | None = Field(None)
    billable: StrictBool | None = Field(None)
    acronym: str | None = Field(None, max_length=4)


class UpdateClientConfig(_Identified):
    """Update Client."""

    operation: Literal["update_client"] = Field(
        "update_client", json_schema_extra={"ui:hidden": True}
    )
    name: str | None = Field(None, min_length=1, max_length=10000)
    ext_tool_id: str | None = Field(None, max_length=10000)
    info: str | None = Field(None, max_length=10000)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$", max_length=10000)
    active: StrictBool | None = Field(None)
    billable: StrictBool | None = Field(None)
    acronym: str | None = Field(None, max_length=4)
    demo_flag: StrictBool | None = Field(None)

    @model_validator(mode="after")
    def nonnullable_fields(self):
        for name in ["name"]:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    @model_validator(mode="after")
    def changes_required(self):
        if not self.model_fields_set - {"operation", "id"}:
            raise ValueError("Supply at least one field to update")
        return self


class DeleteClientConfig(_Identified):
    """Delete a client."""

    operation: Literal["delete_client"] = Field(
        "delete_client", json_schema_extra={"ui:hidden": True}
    )


class ListProjectsConfig(_Input):
    """Get all projects."""

    operation: Literal["list_projects"] = Field(
        "list_projects", json_schema_extra={"ui:hidden": True}
    )
    limit: int | None = Field(None, ge=1, le=1000)
    search: str | None = Field(None, max_length=10000)
    active: StrictBool | None = Field(None)
    client_id: str | None = Field(None, max_length=10000)


class GetProjectConfig(_Identified):
    """Get a Project."""

    operation: Literal["get_project"] = Field(
        "get_project", json_schema_extra={"ui:hidden": True}
    )


class CreateProjectConfig(_Input):
    """Create a new project."""

    operation: Literal["create_project"] = Field(
        "create_project", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(..., min_length=1, max_length=10000)
    ext_tool_id: str | None = Field(None, max_length=10000)
    client_id: str | None = Field(None, max_length=10000)
    ext_client_id: str | None = Field(None, max_length=10000)
    info: str | None = Field(None, max_length=10000)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$", max_length=10000)
    active: StrictBool | None = Field(None)
    billable: StrictBool | None = Field(None)
    acronym: str | None = Field(None, max_length=4)
    budget_type: Literal["rate", "hours"] | None = Field(None)
    available_budget: float | None = Field(None)

    @model_validator(mode="after")
    def nonnullable_fields(self):
        for name in ["client_id"]:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class UpdateProjectConfig(_Identified):
    """Update Project."""

    operation: Literal["update_project"] = Field(
        "update_project", json_schema_extra={"ui:hidden": True}
    )
    name: str | None = Field(None, min_length=1, max_length=10000)
    ext_tool_id: str | None = Field(None, max_length=10000)
    client_id: str | None = Field(None, max_length=10000)
    ext_client_id: str | None = Field(None, max_length=10000)
    info: str | None = Field(None, max_length=10000)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$", max_length=10000)
    active: StrictBool | None = Field(None)
    billable: StrictBool | None = Field(None)
    acronym: str | None = Field(None, max_length=4)
    demo_flag: StrictBool | None = Field(None)
    budget_type: Literal["rate", "hours"] | None = Field(None)
    available_budget: float | None = Field(None)

    @model_validator(mode="after")
    def nonnullable_fields(self):
        for name in ["name", "client_id"]:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    @model_validator(mode="after")
    def changes_required(self):
        if not self.model_fields_set - {"operation", "id"}:
            raise ValueError("Supply at least one field to update")
        return self


class DeleteProjectConfig(_Identified):
    """Delete a project."""

    operation: Literal["delete_project"] = Field(
        "delete_project", json_schema_extra={"ui:hidden": True}
    )


class ListServicesConfig(_Input):
    """Get all services."""

    operation: Literal["list_services"] = Field(
        "list_services", json_schema_extra={"ui:hidden": True}
    )
    limit: int | None = Field(None, ge=1, le=1000)
    search: str | None = Field(None, max_length=10000)
    active: StrictBool | None = Field(None)


class GetServiceConfig(_Identified):
    """Get a Service."""

    operation: Literal["get_service"] = Field(
        "get_service", json_schema_extra={"ui:hidden": True}
    )


class CreateServiceConfig(_Input):
    """Create a new service."""

    operation: Literal["create_service"] = Field(
        "create_service", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(..., min_length=1, max_length=10000)
    info: str | None = Field(None, max_length=10000)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$", max_length=10000)
    active: StrictBool | None = Field(None)
    billable: StrictBool | None = Field(None)
    acronym: str | None = Field(None, max_length=4)
    ext_tool_id: str | None = Field(None, max_length=10000)
    default_time_entry_description: str | None = Field(None, max_length=10000)


class UpdateServiceConfig(_Identified):
    """Update Service."""

    operation: Literal["update_service"] = Field(
        "update_service", json_schema_extra={"ui:hidden": True}
    )
    name: str | None = Field(None, min_length=1, max_length=10000)
    info: str | None = Field(None, max_length=10000)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$", max_length=10000)
    active: StrictBool | None = Field(None)
    billable: StrictBool | None = Field(None)
    acronym: str | None = Field(None, max_length=4)
    ext_tool_id: str | None = Field(None, max_length=10000)
    default_time_entry_description: str | None = Field(None, max_length=10000)

    @model_validator(mode="after")
    def nonnullable_fields(self):
        for name in ["name"]:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    @model_validator(mode="after")
    def changes_required(self):
        if not self.model_fields_set - {"operation", "id"}:
            raise ValueError("Supply at least one field to update")
        return self


class DeleteServiceConfig(_Identified):
    """Delete a service."""

    operation: Literal["delete_service"] = Field(
        "delete_service", json_schema_extra={"ui:hidden": True}
    )


class ListTimeEntriesConfig(_Input):
    """Get all time entries."""

    operation: Literal["list_time_entries"] = Field(
        "list_time_entries", json_schema_extra={"ui:hidden": True}
    )
    limit: int | None = Field(None, ge=1, le=1000)
    search: str | None = Field(None, max_length=10000)
    withRelations: StrictBool | None = Field(None)
    start: datetime | None = Field(None)
    end: datetime | None = Field(None)
    onlyDeleted: StrictBool | None = Field(None)
    isInterrupt: StrictBool | None = Field(None)
    isBilled: StrictBool | None = Field(None)
    isBillable: StrictBool | None = Field(None)
    searchInDescription: str | None = Field(None, max_length=10000)
    clientId: str | None = Field(None, max_length=10000)
    projectId: str | None = Field(None, max_length=10000)
    serviceId: str | None = Field(None, max_length=10000)
    userId: str | None = Field(None, max_length=10000)
    extToolId: str | None = Field(None, max_length=10000)
    exact: StrictBool | None = Field(None)


class GetTimeEntryConfig(_Identified):
    """Get a Time Entry."""

    operation: Literal["get_time_entry"] = Field(
        "get_time_entry", json_schema_extra={"ui:hidden": True}
    )


class CreateTimeEntryConfig(_Input):
    """Create a new time entry."""

    operation: Literal["create_time_entry"] = Field(
        "create_time_entry", json_schema_extra={"ui:hidden": True}
    )
    user_id: str = Field(..., min_length=1, max_length=10000)
    client_id: str | None = Field(None, max_length=10000)
    project_id: str | None = Field(None, max_length=10000)
    service_id: str | None = Field(None, max_length=10000)
    description: str | None = Field(None, max_length=10000)
    started_at: datetime = Field(...)
    ended_at: datetime | None = Field(None)
    ext_tool_id: str | None = Field(None, max_length=10000)
    temp_id: str | None = Field(None, max_length=10000)
    billed_at: datetime | None = Field(None)
    is_interrupt: StrictBool | None = Field(None)
    billable: StrictBool | None = Field(None)
    temp_id_should_be_unique: StrictBool | None = Field(None)


class UpdateTimeEntryConfig(_Identified):
    """Update Time Entry."""

    operation: Literal["update_time_entry"] = Field(
        "update_time_entry", json_schema_extra={"ui:hidden": True}
    )
    user_id: str | None = Field(None, min_length=1, max_length=10000)
    client_id: str | None = Field(None, max_length=10000)
    project_id: str | None = Field(None, max_length=10000)
    service_id: str | None = Field(None, max_length=10000)
    description: str | None = Field(None, max_length=10000)
    started_at: datetime | None = Field(None)
    ended_at: datetime | None = Field(None)
    ext_tool_id: str | None = Field(None, max_length=10000)
    temp_id: str | None = Field(None, max_length=10000)
    billed_at: datetime | None = Field(None)
    billable: StrictBool | None = Field(None)
    is_interrupt: StrictBool | None = Field(None)

    @model_validator(mode="after")
    def nonnullable_fields(self):
        for name in ["user_id", "started_at"]:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    @model_validator(mode="after")
    def changes_required(self):
        if not self.model_fields_set - {"operation", "id"}:
            raise ValueError("Supply at least one field to update")
        return self


class DeleteTimeEntryConfig(_Identified):
    """Delete a time entry."""

    operation: Literal["delete_time_entry"] = Field(
        "delete_time_entry", json_schema_extra={"ui:hidden": True}
    )


class ListUsersConfig(_Input):
    """Get all users."""

    operation: Literal["list_users"] = Field(
        "list_users", json_schema_extra={"ui:hidden": True}
    )
    limit: int | None = Field(None, ge=1, le=1000)
    search: str | None = Field(None, max_length=10000)
    active: StrictBool | None = Field(None)


class GetUserConfig(_Identified):
    """Get a User."""

    operation: Literal["get_user"] = Field(
        "get_user", json_schema_extra={"ui:hidden": True}
    )


class ListActiveTimeEntriesConfig(_Input):
    """Get all active time entries.."""

    operation: Literal["list_active_time_entries"] = Field(
        "list_active_time_entries", json_schema_extra={"ui:hidden": True}
    )
    limit: int | None = Field(None, ge=1, le=1000)
    withRelations: StrictBool | None = Field(None)


TimelinkOperation = Annotated[
    Union[
        GetTokenConfig,
        GetCompanyConfig,
        ListClientsConfig,
        GetClientConfig,
        CreateClientConfig,
        UpdateClientConfig,
        DeleteClientConfig,
        ListProjectsConfig,
        GetProjectConfig,
        CreateProjectConfig,
        UpdateProjectConfig,
        DeleteProjectConfig,
        ListServicesConfig,
        GetServiceConfig,
        CreateServiceConfig,
        UpdateServiceConfig,
        DeleteServiceConfig,
        ListTimeEntriesConfig,
        GetTimeEntryConfig,
        CreateTimeEntryConfig,
        UpdateTimeEntryConfig,
        DeleteTimeEntryConfig,
        ListUsersConfig,
        GetUserConfig,
        ListActiveTimeEntriesConfig,
    ],
    Field(discriminator="operation"),
]


class TimelinkNodeConfig(NodeConfig[TimelinkOperation, TimelinkTokenCredential]):
    pass


ROUTES = {
    "get_token": ("GET", "/token"),
    "get_company": ("GET", "/company"),
    "list_clients": ("GET", "/clients"),
    "get_client": ("GET", "/clients/{id}"),
    "create_client": ("POST", "/clients"),
    "update_client": ("PATCH", "/clients/{id}"),
    "delete_client": ("DELETE", "/clients/{id}"),
    "list_projects": ("GET", "/projects"),
    "get_project": ("GET", "/projects/{id}"),
    "create_project": ("POST", "/projects"),
    "update_project": ("PATCH", "/projects/{id}"),
    "delete_project": ("DELETE", "/projects/{id}"),
    "list_services": ("GET", "/services"),
    "get_service": ("GET", "/services/{id}"),
    "create_service": ("POST", "/services"),
    "update_service": ("PATCH", "/services/{id}"),
    "delete_service": ("DELETE", "/services/{id}"),
    "list_time_entries": ("GET", "/timeEntries"),
    "get_time_entry": ("GET", "/timeEntries/{id}"),
    "create_time_entry": ("POST", "/timeEntries"),
    "update_time_entry": ("PATCH", "/timeEntries/{id}"),
    "delete_time_entry": ("DELETE", "/timeEntries/{id}"),
    "list_users": ("GET", "/users"),
    "get_user": ("GET", "/users/{id}"),
    "list_active_time_entries": ("GET", "/timeEntries/active"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact(item, token)
            for key, item in value.items()
            if key.lower()
            not in {"access_token", "refresh_token", "api_token", "password", "secret"}
        }
    return value


class TimelinkNode(WorkflowNode):
    integration_type = "automation-timelink"
    connection_evidence = ConnectionEvidence(
        operation="list_clients", noun="clients", label_keys=("name", "id")
    )

    @classmethod
    def get_config_model(cls):
        return TimelinkNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Timelink API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, path = ROUTES[config.operation]
        if "{id}" in path:
            path = path.replace("{id}", quote(config.id, safe=""))
        fields = config.model_dump(
            mode="json", exclude={"operation", "id"}, exclude_unset=True
        )
        # Absent optional query values are omitted; explicit nulls in PATCH bodies
        # are retained so nullable fields can be cleared.
        params = (
            {
                key: str(value).lower() if isinstance(value, bool) else value
                for key, value in fields.items()
                if value is not None
            }
            if method == "GET"
            else None
        )
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        try:
            async with guarded_async_client(
                timeout=30, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.request(
                    method,
                    BASE_URL + path,
                    headers=headers,
                    params=params,
                    **({"json": fields} if method in {"POST", "PATCH"} else {}),
                )
        except httpx.HTTPError:
            # No automatic write retries: a timeout may follow a completed write.
            raise ValueError(
                "Timelink request could not be confirmed; inspect writes before retrying"
            ) from None
        if not 200 <= response.status_code < 300:
            message = "Timelink rejected the request"
            try:
                data = response.json()
                if isinstance(data, dict) and isinstance(data.get("message"), str):
                    message = data["message"][:2000]
            except ValueError:
                pass
            return {
                "status": "error",
                "success": False,
                "http_status": response.status_code,
                "error": _redact(message, token),
            }
        if len(response.content) > 5_000_000 or "json" not in response.headers.get(
            "content-type", ""
        ):
            raise ValueError(
                "Timelink returned an unexpected response; inspect writes before retrying"
            )
        try:
            payload = response.json()
        except ValueError:
            raise ValueError(
                "Timelink returned invalid JSON; inspect writes before retrying"
            ) from None
        if (
            not isinstance(payload, dict)
            or "data" not in payload
            or payload.get("success") is False
            or payload.get("errors")
        ):
            raise ValueError("Timelink did not confirm the operation")
        if config.operation.startswith("list_"):
            if not isinstance(payload["data"], list):
                raise ValueError("Timelink returned an invalid list")
        elif not isinstance(payload["data"], dict):
            raise ValueError("Timelink returned an invalid resource")
        result = {**payload, "status": "success", "http_status": response.status_code}
        if config.operation.startswith("list_"):
            # The published contract exposes limit but no page/cursor input.
            result["single_page"] = True
        result = _redact(result, token)
        await self.emit(result)
        return result
