"""Turso Platform API v1: one documented request per operation.

Platform tokens manage infrastructure; SQL-engine tokens are not accepted.
Responses acknowledge writes, without claiming subsequent propagation or readback.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE = "https://api.turso.tech"
TYPE = "turso_api_token"


class TursoAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Turso API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://docs.turso.tech/api-reference/authentication",
            "x-credential-instructions": "Paste a Turso Platform API token, not a database SQL token. Use the Turso CLI to mint a token scoped to your organization. Grant read for database reads, org:read for members and billing usage, and the write scopes your workflow needs. Group creation/deletion requires an organization-level token. NoClick sends it only to api.turso.tech using Bearer authentication."})
    credential_type: Literal["turso_api_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=8192, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Organization(_Input):
    organization_slug: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$",
        description="Organization slug, or your username for a personal organization.")


class _Database(_Organization):
    database_name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")


class _Group(_Organization):
    group_name: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ListOrganizations(_Input):
    """List organizations visible to the Platform API token."""
    operation: Literal["list_organizations"] = "list_organizations"


class GetOrganization(_Organization):
    operation: Literal["get_organization"] = "get_organization"


class ListLocations(_Input):
    operation: Literal["list_locations"] = "list_locations"


class ListDatabases(_Organization):
    operation: Literal["list_databases"] = "list_databases"
    group: str | None = Field(None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    parent: str | None = Field(None, min_length=1, max_length=128, description="Parent database ID to list branches.")


class CreateDatabase(_Organization):
    """Create an empty database in an existing group."""
    operation: Literal["create_database"] = "create_database"
    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    group: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    size_limit: str | None = Field(None, min_length=1, max_length=64, description="Bytes or a size such as 256mb.")


class GetDatabase(_Database):
    operation: Literal["get_database"] = "get_database"


class DeleteDatabase(_Database):
    """Delete this database. Turso's configured recovery policy applies."""
    operation: Literal["delete_database"] = "delete_database"


class GetDatabaseConfiguration(_Database):
    operation: Literal["get_database_configuration"] = "get_database_configuration"


class UpdateDatabaseConfiguration(_Database):
    operation: Literal["update_database_configuration"] = "update_database_configuration"
    size_limit: str | None = Field(None, min_length=1, max_length=64)
    block_reads: bool | None = None
    block_writes: bool | None = None
    delete_protection: bool | None = None

    @model_validator(mode="after")
    def changed(self):
        if all(getattr(self, k) is None for k in ("size_limit", "block_reads", "block_writes", "delete_protection")):
            raise ValueError("Choose at least one database configuration setting")
        return self


class ListDatabaseInstances(_Database):
    operation: Literal["list_database_instances"] = "list_database_instances"


class GetDatabaseUsage(_Database):
    operation: Literal["get_database_usage"] = "get_database_usage"
    from_time: str | None = Field(None, description="Inclusive ISO 8601 timestamp; omitted uses Turso's current calendar month.")
    to_time: str | None = Field(None, description="End ISO 8601 timestamp; omitted uses Turso's current calendar month.")

    @field_validator("from_time", "to_time")
    @classmethod
    def timestamp(cls, value):
        if value is None:
            return value
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError()
        except ValueError:
            raise ValueError("Use an ISO 8601 timestamp with a timezone") from None
        return value

    @model_validator(mode="after")
    def ordered(self):
        if self.from_time and self.to_time and datetime.fromisoformat(self.from_time.replace("Z", "+00:00")) >= datetime.fromisoformat(self.to_time.replace("Z", "+00:00")):
            raise ValueError("End must be after start")
        return self


class GetDatabaseStats(_Database):
    """Read query text and row counts; this does not execute SQL."""
    operation: Literal["get_database_stats"] = "get_database_stats"


class ListGroups(_Organization):
    operation: Literal["list_groups"] = "list_groups"


class CreateGroup(_Organization):
    operation: Literal["create_group"] = "create_group"
    name: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    location: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$",
        description="Location code from List Locations, for example aws-us-east-1.")


class GetGroup(_Group):
    operation: Literal["get_group"] = "get_group"


class DeleteGroup(_Group):
    """Delete a group and its databases; Turso's configured recovery policy applies."""
    operation: Literal["delete_group"] = "delete_group"


class GetGroupConfiguration(_Group):
    operation: Literal["get_group_configuration"] = "get_group_configuration"


class UpdateGroupConfiguration(_Group):
    operation: Literal["update_group_configuration"] = "update_group_configuration"
    delete_protection: bool = Field(..., description="Whether Turso prevents deleting this group and its databases.")


class ListOrganizationMembers(_Organization):
    operation: Literal["list_organization_members"] = "list_organization_members"


class GetOrganizationUsage(_Organization):
    operation: Literal["get_organization_usage"] = "get_organization_usage"


TursoConfig = Annotated[Union[ListOrganizations, GetOrganization, ListLocations, ListDatabases,
    CreateDatabase, GetDatabase, DeleteDatabase, GetDatabaseConfiguration, UpdateDatabaseConfiguration,
    ListDatabaseInstances, GetDatabaseUsage, GetDatabaseStats, ListGroups, CreateGroup, GetGroup,
    DeleteGroup, GetGroupConfiguration, UpdateGroupConfiguration, ListOrganizationMembers,
    GetOrganizationUsage], Field(discriminator="operation")]


class TursoFullConfig(NodeConfig[TursoConfig, TursoAPITokenCredential]):
    pass


# Each entry maps to exactly one operation in https://turso.tech/openapi.json.
# method, route suffix, response member, response member type
ROUTES = {
    "list_organizations": ("GET", "/v1/organizations", None, list),
    "list_locations": ("GET", "/v1/locations", "locations", dict),
    "get_organization": ("GET", "", "organization", dict),
    "list_databases": ("GET", "/databases", "databases", list),
    "create_database": ("POST", "/databases", "database", dict),
    "get_database": ("GET", "/databases/{database_name}", "database", dict),
    "delete_database": ("DELETE", "/databases/{database_name}", "database", str),
    "get_database_configuration": ("GET", "/databases/{database_name}/configuration", None, dict),
    "update_database_configuration": ("PATCH", "/databases/{database_name}/configuration", None, dict),
    "list_database_instances": ("GET", "/databases/{database_name}/instances", "instances", list),
    "get_database_usage": ("GET", "/databases/{database_name}/usage", "database", dict),
    "get_database_stats": ("GET", "/databases/{database_name}/stats", "top_queries", (list, type(None))),
    "list_groups": ("GET", "/groups", "groups", list),
    "create_group": ("POST", "/groups", "group", dict),
    "get_group": ("GET", "/groups/{group_name}", "group", dict),
    "delete_group": ("DELETE", "/groups/{group_name}", "group", dict),
    "get_group_configuration": ("GET", "/groups/{group_name}/configuration", None, dict),
    "update_group_configuration": ("PATCH", "/groups/{group_name}/configuration", None, dict),
    "list_organization_members": ("GET", "/members", "members", list),
    "get_organization_usage": ("GET", "/usage", "organization", dict),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class TursoNode(WorkflowNode):
    integration_type = "automation-turso"
    connection_evidence = ConnectionEvidence(operation="list_organizations", noun="organizations")

    @classmethod
    def get_config_model(cls):
        return TursoFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, TursoFullConfig) or not self.config.credentials:
            raise ValueError("Attach a Turso Platform API token")
        config, credential = self.config.config, self.config.credentials
        op = config.operation
        method, route, member, kind = ROUTES[op]
        values = config.model_dump(exclude_none=True)
        path = route.format(**{k: quote(str(v), safe="") for k, v in values.items()})
        if isinstance(config, _Organization):
            path = "/v1/organizations/" + quote(config.organization_slug, safe="") + path
        query, body = {}, None
        if isinstance(config, ListDatabases):
            query = {k: values[k] for k in ("group", "parent") if k in values}
        elif isinstance(config, GetDatabaseUsage):
            query = {target: values[key] for key, target in (("from_time", "from"), ("to_time", "to")) if key in values}
        elif method in {"POST", "PATCH"}:
            body = {k: v for k, v in values.items() if k not in {"operation", "organization_slug", "database_name", "group_name"}}
        url = BASE + path + ("?" + urlencode(query, quote_via=quote) if query else "")
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, url, headers={"Authorization": "Bearer " + credential.api_token,
                    "Accept": "application/json"}, **({"json": body} if body is not None else {}))
            if response.status_code != 200:
                message = "Turso did not confirm this request; check token permissions and resource names"
                # Preserve a definitive provider rejection for the shared connect verdict.
                # Never expose an arbitrary HTML page or an echoed credential.
                if len(response.content) <= 100_000:
                    try:
                        error_body = response.json()
                        error = error_body.get("error") if isinstance(error_body, dict) else None
                        if isinstance(error, str) and 0 < len(error) <= 1000 and not any(ord(c) < 32 for c in error):
                            message = _redact(error, credential.api_token)
                    except ValueError:
                        pass
                return {"status": "error", "operation": op, "http_status": response.status_code,
                    "error": message,
                    "write_outcome_unknown": method != "GET" and response.status_code >= 500}
            if len(response.content) > 8_000_000 or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError("Expected bounded JSON")
            payload = response.json()
            if isinstance(payload, dict) and any(key in payload for key in ("error", "errors")):
                raise ValueError("Provider error envelope")
            data = payload.get(member) if member and isinstance(payload, dict) else payload
            if not isinstance(data, kind) or (member and (not isinstance(payload, dict) or member not in payload)):
                raise ValueError("Unexpected response shape")
            if isinstance(data, list) and any(not isinstance(row, dict) for row in data):
                raise ValueError("Unexpected list item")
            return {"status": "success", "operation": op, "data": _redact(data, credential.api_token),
                "http_status": response.status_code, **({"write_acknowledged": True} if method != "GET" else {})}
        except (ValueError, httpx.HTTPError, SSRFError):
            return {"status": "error", "operation": op, "error": "Turso response could not be confirmed",
                "write_outcome_unknown": method != "GET"}
