"""Prisma Postgres Management API v1, using a workspace service token.

Contract: https://api.prisma.io/v1/doc
Token setup: https://docs.prisma.io/docs/rest-api/authentication
Each operation makes one request; pagination is returned for explicit continuation.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


class PrismaServiceTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Prisma Service Token",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://console.prisma.io",
            "x-credential-instructions": "In Prisma Console, select your workspace, open Settings → Service Tokens, create a token and paste it here. Use a workspace service token, not a database connection string.",
        },
    )
    credential_type: Literal["prisma_service_token"] = Field(
        "prisma_service_token", json_schema_extra={"ui:hidden": True}
    )
    service_token: str = Field(
        ...,
        min_length=1,
        title="Service Token",
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetCurrentPrincipal(_Operation):
    operation: Literal["get_current_principal"] = Field(
        "get_current_principal",
        title="Get Current Principal",
        description="",
        json_schema_extra={"ui:hidden": True},
    )


class ListProjects(_Operation):
    operation: Literal["list_projects"] = Field(
        "list_projects",
        title="List Projects",
        description="Returns one page; use the returned pagination to continue.",
        json_schema_extra={"ui:hidden": True},
    )
    cursor: str | None = Field(
        None,
        title="Cursor",
        description="Continue with pagination.nextCursor from the previous response.",
    )
    limit: int = Field(100, ge=1, le=100, title="Page Size")


class CreateProject(_Operation):
    operation: Literal["create_project"] = Field(
        "create_project",
        title="Create Project",
        description="Creates a project and optionally its initial database.",
        json_schema_extra={"ui:hidden": True},
    )
    name: str = Field(..., min_length=1, max_length=256, title="Name")
    region: Literal[
        "us-east-1",
        "us-west-1",
        "eu-west-3",
        "eu-central-1",
        "ap-northeast-1",
        "ap-southeast-1",
    ] = Field("us-east-1", title="Region")
    workspace_id: str = Field(
        ..., title="Workspace ID", pattern=r"^(wksp_)?([cC][^\s-]{8,}|[a-z0-9]+)$"
    )
    create_database: bool = Field(True, title="Create Initial Database")


class GetProject(_Operation):
    operation: Literal["get_project"] = Field(
        "get_project",
        title="Get Project",
        description="",
        json_schema_extra={"ui:hidden": True},
    )
    project_id: str = Field(
        ..., title="Project ID", pattern=r"^(proj_)?([cC][^\s-]{8,}|[a-z0-9]+)$"
    )


class UpdateProject(_Operation):
    operation: Literal["update_project"] = Field(
        "update_project",
        title="Update Project",
        description="",
        json_schema_extra={"ui:hidden": True},
    )
    project_id: str = Field(
        ..., title="Project ID", pattern=r"^(proj_)?([cC][^\s-]{8,}|[a-z0-9]+)$"
    )
    name: str = Field(..., min_length=1, max_length=256, title="Name")


class DeleteProject(_Operation):
    operation: Literal["delete_project"] = Field(
        "delete_project",
        title="Delete Project",
        description="Permanently deletes this resource.",
        json_schema_extra={"ui:hidden": True},
    )
    project_id: str = Field(
        ..., title="Project ID", pattern=r"^(proj_)?([cC][^\s-]{8,}|[a-z0-9]+)$"
    )


class ListProjectDatabases(_Operation):
    operation: Literal["list_project_databases"] = Field(
        "list_project_databases",
        title="List Project Databases",
        description="Returns one page; use the returned pagination to continue.",
        json_schema_extra={"ui:hidden": True},
    )
    cursor: str | None = Field(
        None,
        title="Cursor",
        description="Continue with pagination.nextCursor from the previous response.",
    )
    limit: int = Field(100, ge=1, le=100, title="Page Size")
    project_id: str = Field(
        ..., title="Project ID", pattern=r"^(proj_)?([cC][^\s-]{8,}|[a-z0-9]+)$"
    )


class CreateDatabase(_Operation):
    operation: Literal["create_database"] = Field(
        "create_database",
        title="Create Database",
        description="",
        json_schema_extra={"ui:hidden": True},
    )
    project_id: str = Field(
        ..., title="Project ID", pattern=r"^(proj_)?([cC][^\s-]{8,}|[a-z0-9]+)$"
    )
    name: str = Field(..., min_length=1, max_length=256, title="Name")
    region: Literal[
        "us-east-1",
        "us-west-1",
        "eu-west-3",
        "eu-central-1",
        "ap-northeast-1",
        "ap-southeast-1",
    ] = Field("us-east-1", title="Region")


class GetDatabase(_Operation):
    operation: Literal["get_database"] = Field(
        "get_database",
        title="Get Database",
        description="",
        json_schema_extra={"ui:hidden": True},
    )
    database_id: str = Field(
        ..., title="Database ID", pattern=r"^(db_)?([cC][^\s-]{8,}|[a-z0-9]+)$"
    )


class UpdateDatabase(_Operation):
    operation: Literal["update_database"] = Field(
        "update_database",
        title="Update Database",
        description="",
        json_schema_extra={"ui:hidden": True},
    )
    database_id: str = Field(
        ..., title="Database ID", pattern=r"^(db_)?([cC][^\s-]{8,}|[a-z0-9]+)$"
    )
    name: str = Field(..., min_length=1, max_length=256, title="Name")


class DeleteDatabase(_Operation):
    operation: Literal["delete_database"] = Field(
        "delete_database",
        title="Delete Database",
        description="Permanently deletes this resource.",
        json_schema_extra={"ui:hidden": True},
    )
    database_id: str = Field(
        ..., title="Database ID", pattern=r"^(db_)?([cC][^\s-]{8,}|[a-z0-9]+)$"
    )


class ListConnections(_Operation):
    operation: Literal["list_connections"] = Field(
        "list_connections",
        title="List Connections",
        description="Returns one page; use the returned pagination to continue.",
        json_schema_extra={"ui:hidden": True},
    )
    cursor: str | None = Field(
        None,
        title="Cursor",
        description="Continue with pagination.nextCursor from the previous response.",
    )
    limit: int = Field(100, ge=1, le=100, title="Page Size")
    database_id: str | None = Field(
        None, title="Database ID", pattern=r"^(db_)?([cC][^\s-]{8,}|[a-z0-9]+)$"
    )


class CreateConnection(_Operation):
    operation: Literal["create_connection"] = Field(
        "create_connection",
        title="Create Connection",
        description="",
        json_schema_extra={"ui:hidden": True},
    )
    database_id: str = Field(
        ..., title="Database ID", pattern=r"^(db_)?([cC][^\s-]{8,}|[a-z0-9]+)$"
    )
    name: str = Field(..., min_length=3, max_length=65, title="Connection Name")


class GetConnection(_Operation):
    operation: Literal["get_connection"] = Field(
        "get_connection",
        title="Get Connection",
        description="",
        json_schema_extra={"ui:hidden": True},
    )
    connection_id: str = Field(
        ..., title="Connection ID", pattern=r"^(con_)?([cC][^\s-]{8,}|[a-z0-9]+)$"
    )


class DeleteConnection(_Operation):
    operation: Literal["delete_connection"] = Field(
        "delete_connection",
        title="Delete Connection",
        description="Permanently deletes this resource.",
        json_schema_extra={"ui:hidden": True},
    )
    connection_id: str = Field(
        ..., title="Connection ID", pattern=r"^(con_)?([cC][^\s-]{8,}|[a-z0-9]+)$"
    )


class RotateConnection(_Operation):
    operation: Literal["rotate_connection"] = Field(
        "rotate_connection",
        title="Rotate Connection",
        description="Generates replacement credentials; revocation of previous credentials is best-effort.",
        json_schema_extra={"ui:hidden": True},
    )
    connection_id: str = Field(
        ..., title="Connection ID", pattern=r"^(con_)?([cC][^\s-]{8,}|[a-z0-9]+)$"
    )


class ListDatabaseBackups(_Operation):
    operation: Literal["list_database_backups"] = Field(
        "list_database_backups",
        title="List Database Backups",
        description="Returns the most recent backups up to Page Size, with retention metadata and hasMore.",
        json_schema_extra={"ui:hidden": True},
    )
    database_id: str = Field(
        ..., title="Database ID", pattern=r"^(db_)?([cC][^\s-]{8,}|[a-z0-9]+)$"
    )
    limit: int = Field(25, ge=1, le=100, title="Page Size")


class GetDatabaseUsage(_Operation):
    operation: Literal["get_database_usage"] = Field(
        "get_database_usage",
        title="Get Database Usage",
        description="",
        json_schema_extra={"ui:hidden": True},
    )
    database_id: str = Field(
        ..., title="Database ID", pattern=r"^(db_)?([cC][^\s-]{8,}|[a-z0-9]+)$"
    )
    start_date: AwareDatetime | None = Field(None, title="Start Date")
    end_date: AwareDatetime | None = Field(None, title="End Date")


class ListWorkspaces(_Operation):
    operation: Literal["list_workspaces"] = Field(
        "list_workspaces",
        title="List Workspaces",
        description="Returns one page; use the returned pagination to continue.",
        json_schema_extra={"ui:hidden": True},
    )
    cursor: str | None = Field(
        None,
        title="Cursor",
        description="Continue with pagination.nextCursor from the previous response.",
    )
    limit: int = Field(100, ge=1, le=100, title="Page Size")


class GetWorkspace(_Operation):
    operation: Literal["get_workspace"] = Field(
        "get_workspace",
        title="Get Workspace",
        description="",
        json_schema_extra={"ui:hidden": True},
    )
    workspace_id: str = Field(
        ..., title="Workspace ID", pattern=r"^(wksp_)?([cC][^\s-]{8,}|[a-z0-9]+)$"
    )


class ListPostgresRegions(_Operation):
    operation: Literal["list_postgres_regions"] = Field(
        "list_postgres_regions",
        title="List Postgres Regions",
        description="Returns the available Prisma Postgres regions.",
        json_schema_extra={"ui:hidden": True},
    )


# Prisma's own MCP server: agents get its tools through a person's Prisma sign-in.
PrismaMcpCredential = mcp_credential("prisma", "https://mcp.prisma.io/mcp", app="Prisma")
PrismaCredential = Union[PrismaServiceTokenCredential, PrismaMcpCredential]


Operation = Annotated[
    Union[
        GetCurrentPrincipal,
        ListProjects,
        CreateProject,
        GetProject,
        UpdateProject,
        DeleteProject,
        ListProjectDatabases,
        CreateDatabase,
        GetDatabase,
        UpdateDatabase,
        DeleteDatabase,
        ListConnections,
        CreateConnection,
        GetConnection,
        DeleteConnection,
        RotateConnection,
        ListDatabaseBackups,
        GetDatabaseUsage,
        ListWorkspaces,
        GetWorkspace,
        ListPostgresRegions,
    ],
    Field(discriminator="operation"),
]


class PrismaNodeConfig(NodeConfig[Operation, PrismaCredential]):
    pass


ROUTES = {
    "get_current_principal": ("GET", "/v1/me", (), ()),
    "list_projects": ("GET", "/v1/projects", ("cursor", "limit"), ()),
    "create_project": (
        "POST",
        "/v1/projects",
        (),
        ("name", "region", "workspace_id", "create_database"),
    ),
    "get_project": ("GET", "/v1/projects/{project_id}", (), ()),
    "update_project": ("PATCH", "/v1/projects/{project_id}", (), ("name",)),
    "delete_project": ("DELETE", "/v1/projects/{project_id}", (), ()),
    "list_project_databases": (
        "GET",
        "/v1/projects/{project_id}/databases",
        ("cursor", "limit"),
        (),
    ),
    "create_database": ("POST", "/v1/databases", (), ("project_id", "name", "region")),
    "get_database": ("GET", "/v1/databases/{database_id}", (), ()),
    "update_database": ("PATCH", "/v1/databases/{database_id}", (), ("name",)),
    "delete_database": ("DELETE", "/v1/databases/{database_id}", (), ()),
    "list_connections": (
        "GET",
        "/v1/connections",
        ("cursor", "limit", "database_id"),
        (),
    ),
    "create_connection": ("POST", "/v1/connections", (), ("database_id", "name")),
    "get_connection": ("GET", "/v1/connections/{connection_id}", (), ()),
    "delete_connection": ("DELETE", "/v1/connections/{connection_id}", (), ()),
    "rotate_connection": ("POST", "/v1/connections/{connection_id}/rotate", (), ()),
    "list_database_backups": (
        "GET",
        "/v1/databases/{database_id}/backups",
        ("limit",),
        (),
    ),
    "get_database_usage": (
        "GET",
        "/v1/databases/{database_id}/usage",
        ("start_date", "end_date"),
        (),
    ),
    "list_workspaces": ("GET", "/v1/workspaces", ("cursor", "limit"), ()),
    "get_workspace": ("GET", "/v1/workspaces/{workspace_id}", (), ()),
    "list_postgres_regions": ("GET", "/v1/regions/postgres", (), ()),
}
WIRE_NAMES = {
    "workspace_id": "workspaceId",
    "project_id": "projectId",
    "database_id": "databaseId",
    "create_database": "createDatabase",
    "start_date": "startDate",
    "end_date": "endDate",
}


class PrismaNode(WorkflowNode):
    integration_type = "automation-prisma"
    credential_provider_labels = {"prisma": "Prisma Account"}
    connection_evidence = ConnectionEvidence(
        noun="Prisma projects", operation="list_projects"
    )

    @classmethod
    def get_config_model(cls):
        return PrismaNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Prisma service token")
        config = self.config.config
        token = self.config.credentials.service_token
        method, template, query_fields, body_fields = ROUTES[config.operation]
        values = config.model_dump(mode="json")
        path = template.format(**{k: quote(str(v), safe="") for k, v in values.items()})
        params = {
            WIRE_NAMES.get(k, k): values[k]
            for k in query_fields
            if values[k] is not None
        }
        body = {WIRE_NAMES.get(k, k): values[k] for k in body_fields}
        expected = (
            204
            if method == "DELETE"
            else 201
            if config.operation
            in {"create_project", "create_database", "create_connection"}
            else 200
        )
        async with guarded_async_client(
            timeout=30, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.request(
                method,
                "https://api.prisma.io" + path,
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/json",
                },
                params=params,
                **({"json": body} if body_fields else {}),
            )
        if response.status_code != expected:
            # Preserve provider rejection details for the connect seam without echoing the token.
            message = response.text.replace(token, "[redacted]")[:2000]
            raise ValueError(f"Prisma HTTP {response.status_code}: {message}")
        if expected == 204:
            return {"status": "success", "deleted": True}
        result = response.json()
        required = (
            {"period", "metrics", "generatedAt"}
            if config.operation == "get_database_usage"
            else {"data"}
        )
        if (
            not isinstance(result, dict)
            or not required <= result.keys()
            or "error" in result
            or "errors" in result
        ):
            raise ValueError("Prisma returned an unexpected response envelope")
        return {**result, "status": "success"}
