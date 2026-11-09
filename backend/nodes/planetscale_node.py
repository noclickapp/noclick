"""PlanetScale v1 management API: databases, branches, backups and deploy requests.

Contract: https://api.planetscale.com/v1/openapi-spec (v1).
This API manages infrastructure; it does not run SQL or access database rows.
Each operation makes one fixed provider request. Creation and deployment can
finish asynchronously: use the corresponding get operation to inspect state.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.planetscale.com/v1"


class PlanetScaleServiceToken(BaseModel):
    model_config = ConfigDict(title="PlanetScale Service Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://planetscale.com/docs/api/service-tokens",
            "x-credential-instructions": "Create a service token in your PlanetScale organization settings and grant access for the databases and operations you use. Paste the token only, without Bearer. Use a current service token that supports Bearer authentication; legacy token-ID pairs are not supported. Connection verification lists your organizations. This is the management API, not a database connection password.",
        })
    credential_type: Literal["planetscale_service_token"] = Field("planetscale_service_token", json_schema_extra={"ui:hidden": True})
    service_token: str = Field(..., title="Service token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("service_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Service token")
        if any(c.isspace() for c in value) or ":" in value:
            raise ValueError("Paste a current service token without Bearer or a token ID")
        return value


Segment = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class ListOrganizations(_Input):
    """List organizations."""
    operation: Literal["list_organizations"] = Field("list_organizations", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description='If provided, specifies the page offset of returned results')
    per_page: int = Field(25, ge=1, le=100, description='If provided, specifies the number of returned results')

class GetOrganization(_Input):
    """Get an organization."""
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"ui:hidden": True})
    organization: Segment = Field(..., description='Organization name slug from `list_organizations`. Example: `acme`.')

class ListDatabases(_Input):
    """List databases."""
    operation: Literal["list_databases"] = Field("list_databases", json_schema_extra={"ui:hidden": True})
    organization: Segment = Field(..., description='Organization name slug from `list_organizations`. Example: `acme`.')
    page: int = Field(1, ge=1, description='If provided, specifies the page offset of returned results')
    per_page: int = Field(25, ge=1, le=100, description='If provided, specifies the number of returned results')

class CreateDatabase(_Input):
    """Create a database."""
    operation: Literal["create_database"] = Field("create_database", json_schema_extra={"ui:hidden": True})
    organization: Segment = Field(..., description='Organization name slug from `list_organizations`. Example: `acme`.')
    name: str = Field(..., min_length=1, max_length=255, description='Name of the database')
    region: Optional[str] = Field(None, min_length=1, max_length=255, description="The region the database will be deployed in. If left blank, defaults to the organization's default region.")
    cluster_size: str = Field(..., min_length=1, max_length=255, description="The database cluster size name (e.g., 'PS_10', 'PS_80'). Use the 'List available cluster sizes' endpoint to get available options for your organization. /v1/organizations/:organization/cluster-size-skus")
    replicas: Optional[int] = Field(None, ge=0, le=8, description='The number of replicas for the database. 0 for non-HA, 2+ for HA.')
    kind: Optional[Literal['mysql', 'postgresql', 'neki']] = Field(None, description='The kind of database to create.')
    major_version: Optional[str] = Field(None, min_length=1, max_length=255, description='For PostgreSQL and Neki databases, the PostgreSQL major version to use for the database. Defaults to the latest available major version.')

class GetDatabase(_Input):
    """Get a database."""
    operation: Literal["get_database"] = Field("get_database", json_schema_extra={"ui:hidden": True})
    organization: Segment = Field(..., description='Organization name slug from `list_organizations`. Example: `acme`.')
    database: Segment = Field(..., description='Database name slug from `list_databases`. Example: `app-db`.')

class DeleteDatabase(_Input):
    """Delete a database."""
    operation: Literal["delete_database"] = Field("delete_database", json_schema_extra={"ui:hidden": True})
    organization: Segment = Field(..., description='Organization name slug from `list_organizations`. Example: `acme`.')
    database: Segment = Field(..., description='Database name slug from `list_databases`. Example: `app-db`.')

class ListBranches(_Input):
    """List branches."""
    operation: Literal["list_branches"] = Field("list_branches", json_schema_extra={"ui:hidden": True})
    organization: Segment = Field(..., description='Organization name slug from `list_organizations`. Example: `acme`.')
    database: Segment = Field(..., description='Database name slug from `list_databases`. Example: `app-db`.')
    page: int = Field(1, ge=1, description='If provided, specifies the page offset of returned results')
    per_page: int = Field(25, ge=1, le=100, description='If provided, specifies the number of returned results')

class CreateBranch(_Input):
    """Create a branch."""
    operation: Literal["create_branch"] = Field("create_branch", json_schema_extra={"ui:hidden": True})
    organization: Segment = Field(..., description='The name of the organization the branch belongs to')
    database: Segment = Field(..., description='The name of the database the branch belongs to')
    name: str = Field(..., min_length=1, max_length=255, description='The name of the branch to create')
    deletion_protected: Optional[bool] = Field(None, description='Whether deletion protection is enabled for the branch')
    parent_branch: Optional[str] = Field(None, min_length=1, max_length=255, description="The name of the parent branch. Defaults to the database's default branch if not provided.")
    region: Optional[str] = Field(None, min_length=1, max_length=255, description='The region to create the branch in. If not provided, the branch will be created in the default region for its database.')

class GetBranch(_Input):
    """Get a branch."""
    operation: Literal["get_branch"] = Field("get_branch", json_schema_extra={"ui:hidden": True})
    organization: Segment = Field(..., description='Organization name slug from `list_organizations`. Example: `acme`.')
    database: Segment = Field(..., description='Database name slug from `list_databases`. Example: `app-db`.')
    branch: Segment = Field(..., description='Branch name from `list_branches`. Example: `main`.')

class DeleteBranch(_Input):
    """Delete a branch."""
    operation: Literal["delete_branch"] = Field("delete_branch", json_schema_extra={"ui:hidden": True})
    organization: Segment = Field(..., description='The name of the organization the branch belongs to')
    database: Segment = Field(..., description='The name of the database the branch belongs to')
    branch: Segment = Field(..., description='The name of the branch')
    delete_descendants: Optional[bool] = Field(None, description='If true, recursively delete all descendant branches along with this branch')

class ListBackups(_Input):
    """List backups."""
    operation: Literal["list_backups"] = Field("list_backups", json_schema_extra={"ui:hidden": True})
    organization: Segment = Field(..., description='The name of the organization the branch belongs to')
    database: Segment = Field(..., description='The name of the database the branch belongs to')
    branch: Segment = Field(..., description='The name of the branch')
    all: Optional[bool] = Field(None, description='Whether to include all backups, including deleted ones')
    state: Optional[Literal['pending', 'running', 'success', 'failed', 'canceled', 'ignored']] = Field(None, description='Filter backups by state')
    page: int = Field(1, ge=1, description='If provided, specifies the page offset of returned results')
    per_page: int = Field(25, ge=1, le=100, description='If provided, specifies the number of returned results')

class CreateBackup(_Input):
    """Create a backup."""
    operation: Literal["create_backup"] = Field("create_backup", json_schema_extra={"ui:hidden": True})
    organization: Segment = Field(..., description='The name of the organization the branch belongs to')
    database: Segment = Field(..., description='The name of the database the branch belongs to')
    branch: Segment = Field(..., description='The name of the branch')
    name: Optional[str] = Field(None, min_length=1, max_length=255, description='Name for the backup')
    retention_unit: Optional[Literal['hour', 'day', 'week', 'month', 'year']] = Field(None, description='Unit for the retention period of the backup')
    retention_value: Optional[int] = Field(None, ge=1, le=1000, description='Value between `1` and `1000` for the retention period of the backup (i.e retention_value `6` and retention_unit `hour` means 6 hours)')
    emergency: Optional[bool] = Field(None, description='Whether the backup is an immediate backup that may affect database performance. Emergency backups are only supported for PostgreSQL databases.')

class GetBackup(_Input):
    """Get a backup."""
    operation: Literal["get_backup"] = Field("get_backup", json_schema_extra={"ui:hidden": True})
    id: Segment = Field(..., description='The ID for the backup')
    organization: Segment = Field(..., description='The name of the organization the branch belongs to')
    database: Segment = Field(..., description='The name of the database the branch belongs to')
    branch: Segment = Field(..., description='The name of the branch')

class DeleteBackup(_Input):
    """Delete a backup."""
    operation: Literal["delete_backup"] = Field("delete_backup", json_schema_extra={"ui:hidden": True})
    id: Segment = Field(..., description='The ID of the backup')
    organization: Segment = Field(..., description='The name of the organization the branch belongs to')
    database: Segment = Field(..., description='The name of the database the branch belongs to')
    branch: Segment = Field(..., description='The name of the branch')

class GetBranchSchema(_Input):
    """Get a branch schema."""
    operation: Literal["get_branch_schema"] = Field("get_branch_schema", json_schema_extra={"ui:hidden": True})
    organization: Segment = Field(..., description='The name of the organization the branch belongs to')
    database: Segment = Field(..., description='The name of the database the branch belongs to')
    branch: Segment = Field(..., description='The name of the branch')
    keyspace: Optional[str] = Field(None, min_length=1, max_length=255, description='Return the schema for a single Vitess keyspace')
    namespace: Optional[str] = Field(None, min_length=1, max_length=255, description='Return the schema for a PostgreSQL catalog namespace in `<database>.<schema>` format (e.g. public.schema1)')

class ListDeployRequests(_Input):
    """List deploy requests."""
    operation: Literal["list_deploy_requests"] = Field("list_deploy_requests", json_schema_extra={"ui:hidden": True})
    organization: Segment = Field(..., description="The name of the deploy request's organization")
    database: Segment = Field(..., description="The name of the deploy request's database")
    state: Optional[str] = Field(None, min_length=1, max_length=255, description='Filter by state of the deploy request (open, closed, deployed)')
    branch: Optional[str] = Field(None, min_length=1, max_length=255, description='Filter by the name of the branch the deploy request is created from')
    into_branch: Optional[str] = Field(None, min_length=1, max_length=255, description='Filter by the name of the branch the deploy request will be merged into')
    page: int = Field(1, ge=1, description='If provided, specifies the page offset of returned results')
    per_page: int = Field(25, ge=1, le=100, description='If provided, specifies the number of returned results')

class CreateDeployRequest(_Input):
    """Create a deploy request."""
    operation: Literal["create_deploy_request"] = Field("create_deploy_request", json_schema_extra={"ui:hidden": True})
    organization: Segment = Field(..., description="The name of the deploy request's organization")
    database: Segment = Field(..., description="The name of the deploy request's database")
    branch: str = Field(..., min_length=1, max_length=255, description='The name of the branch the deploy request is created from')
    into_branch: str = Field(..., min_length=1, max_length=255, description='The name of the branch the deploy request will be merged into')
    notes: Optional[str] = Field(None, min_length=1, max_length=10000, description='Notes about the deploy request')
    auto_cutover: Optional[bool] = Field(None, description='Whether or not to enable auto_cutover for the deploy request. When enabled, will auto cutover to the new schema as soon as it is ready.')
    auto_delete_branch: Optional[bool] = Field(None, description='Whether or not to enable auto_delete_branch for the deploy request. When enabled, will delete the branch once the DR successfully completes.')

class GetDeployRequest(_Input):
    """Get a deploy request."""
    operation: Literal["get_deploy_request"] = Field("get_deploy_request", json_schema_extra={"ui:hidden": True})
    organization: Segment = Field(..., description="The name of the deploy request's organization")
    database: Segment = Field(..., description="The name of the deploy request's database")
    number: int = Field(..., ge=1, description='The number of the deploy request')

class CloseDeployRequest(_Input):
    """Close a deploy request."""
    operation: Literal["close_deploy_request"] = Field("close_deploy_request", json_schema_extra={"ui:hidden": True})
    organization: Segment = Field(..., description="The name of the deploy request's organization")
    database: Segment = Field(..., description="The name of the deploy request's database")
    number: int = Field(..., ge=1, description='The number of the deploy request')
    state: Literal['closed'] = Field("closed", description='The deploy request will be updated to this state')

class QueueDeployRequest(_Input):
    """Queue a deploy request."""
    operation: Literal["queue_deploy_request"] = Field("queue_deploy_request", json_schema_extra={"ui:hidden": True})
    organization: Segment = Field(..., description="The name of the deploy request's organization")
    database: Segment = Field(..., description="The name of the deploy request's database")
    number: int = Field(..., ge=1, description='The number of the deploy request')
    instant_ddl: Optional[bool] = Field(None, description='Whether or not to deploy the request with instant DDL. Defaults to false.')

PlanetScaleOperation = Annotated[Union[
    ListOrganizations, GetOrganization, ListDatabases, CreateDatabase, GetDatabase, DeleteDatabase, ListBranches, CreateBranch, GetBranch, DeleteBranch, ListBackups, CreateBackup, GetBackup, DeleteBackup, GetBranchSchema, ListDeployRequests, CreateDeployRequest, GetDeployRequest, CloseDeployRequest, QueueDeployRequest,
], Field(discriminator="operation")]


class PlanetScaleConfig(NodeConfig[PlanetScaleOperation, PlanetScaleServiceToken]):
    pass


# Fixed paths and explicit parameter locations from the pinned provider contract.
ROUTES = {
    'list_organizations': ('GET', '/organizations', [], ['page', 'per_page'], []),
    'get_organization': ('GET', '/organizations/{organization}', ['organization'], [], []),
    'list_databases': ('GET', '/organizations/{organization}/databases', ['organization'], ['page', 'per_page'], []),
    'create_database': ('POST', '/organizations/{organization}/databases', ['organization'], [], ['name', 'region', 'cluster_size', 'replicas', 'kind', 'major_version']),
    'get_database': ('GET', '/organizations/{organization}/databases/{database}', ['organization', 'database'], [], []),
    'delete_database': ('DELETE', '/organizations/{organization}/databases/{database}', ['organization', 'database'], [], []),
    'list_branches': ('GET', '/organizations/{organization}/databases/{database}/branches', ['organization', 'database'], ['page', 'per_page'], []),
    'create_branch': ('POST', '/organizations/{organization}/databases/{database}/branches', ['organization', 'database'], [], ['name', 'deletion_protected', 'parent_branch', 'region']),
    'get_branch': ('GET', '/organizations/{organization}/databases/{database}/branches/{branch}', ['organization', 'database', 'branch'], [], []),
    'delete_branch': ('DELETE', '/organizations/{organization}/databases/{database}/branches/{branch}', ['organization', 'database', 'branch'], ['delete_descendants'], []),
    'list_backups': ('GET', '/organizations/{organization}/databases/{database}/branches/{branch}/backups', ['organization', 'database', 'branch'], ['all', 'state', 'page', 'per_page'], []),
    'create_backup': ('POST', '/organizations/{organization}/databases/{database}/branches/{branch}/backups', ['organization', 'database', 'branch'], [], ['name', 'retention_unit', 'retention_value', 'emergency']),
    'get_backup': ('GET', '/organizations/{organization}/databases/{database}/branches/{branch}/backups/{id}', ['id', 'organization', 'database', 'branch'], [], []),
    'delete_backup': ('DELETE', '/organizations/{organization}/databases/{database}/branches/{branch}/backups/{id}', ['id', 'organization', 'database', 'branch'], [], []),
    'get_branch_schema': ('GET', '/organizations/{organization}/databases/{database}/branches/{branch}/schema', ['organization', 'database', 'branch'], ['keyspace', 'namespace'], []),
    'list_deploy_requests': ('GET', '/organizations/{organization}/databases/{database}/deploy-requests', ['organization', 'database'], ['state', 'branch', 'into_branch', 'page', 'per_page'], []),
    'create_deploy_request': ('POST', '/organizations/{organization}/databases/{database}/deploy-requests', ['organization', 'database'], [], ['branch', 'into_branch', 'notes', 'auto_cutover', 'auto_delete_branch']),
    'get_deploy_request': ('GET', '/organizations/{organization}/databases/{database}/deploy-requests/{number}', ['organization', 'database', 'number'], [], []),
    'close_deploy_request': ('PATCH', '/organizations/{organization}/databases/{database}/deploy-requests/{number}', ['organization', 'database', 'number'], [], ['state']),
    'queue_deploy_request': ('POST', '/organizations/{organization}/databases/{database}/deploy-requests/{number}/deploy', ['organization', 'database', 'number'], [], ['instant_ddl']),
}


class PlanetScaleNode(WorkflowNode):
    integration_type = "automation-planetscale"
    connection_evidence = ConnectionEvidence(operation="list_organizations", noun="organizations")

    @classmethod
    def get_config_model(cls):
        return PlanetScaleConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a PlanetScale service token")
        config = self.config.config
        method, template, path_keys, query_keys, body_keys = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        path = template.format(**{key: quote(str(values[key]), safe="") for key in path_keys})
        params = {key: str(values[key]).lower() if isinstance(values[key], bool) else values[key]
                  for key in query_keys if key in values}
        payload = {key: values[key] for key in body_keys if key in values}
        kwargs = {"params": params} if params else {}
        if body_keys:
            kwargs["json"] = payload
        token = credential.service_token
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, headers={
                    "Authorization": "Bearer " + token, "Accept": "application/json",
                }, **kwargs)
            status = response.status_code
            if len(response.content) > 10_000_000:
                raise ValueError("PlanetScale response is too large")
            if not 200 <= status < 300:
                try:
                    body = response.json()
                    message = body.get("message") or body.get("error") if isinstance(body, dict) else None
                except ValueError:
                    message = None
                return {"status": "error", "http_status": status,
                        "error": str(message or "PlanetScale rejected the request").replace(token, "[redacted]")}
            if status == 204:
                return {"status": "success", "operation": config.operation, "http_status": status,
                        "deletion_acknowledged": True}
            body = response.json()
            if not isinstance(body, (dict, list)):
                raise ValueError("Expected a PlanetScale JSON object or list")
            if isinstance(body, dict) and (body.get("error") or body.get("errors")):
                return {"status": "error", "http_status": status,
                        "error": str(body.get("message") or body.get("error") or body["errors"]).replace(token, "[redacted]")}
            # JSON preserves provider state, pagination and asynchronous readiness.
            # Never follow provider-supplied links or retry writes automatically.
            return {"status": "success", "operation": config.operation, "http_status": status,
                    "data": _redact(body, token)}
        except httpx.HTTPError:
            return {"status": "error", "error": "PlanetScale request did not complete; inspect the resource before retrying a write"}
        except ValueError:
            return {"status": "error", "error": "PlanetScale returned an invalid response; inspect the resource before retrying a write"}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()}
    return value
