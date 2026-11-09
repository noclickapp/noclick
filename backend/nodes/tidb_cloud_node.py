"""TiDB Cloud Starter/Essential administration using the provider's v1beta1 API.

Each action makes one API operation; API key pairs use HTTP Digest authentication.
Lists return one page and the provider's nextPageToken for explicit continuation.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://serverless.tidbapi.com/v1beta1"
IAM = "https://iam.tidbapi.com/v1beta1"


class TiDBCloudAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Tidb Cloud API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://tidbcloud.com",
            "x-credential-instructions": "In TiDB Cloud, open Organization Settings > API Keys. Create a key with the role and resource scope needed for your workflows, then paste both keys. The private key is shown only once. NoClick verifies access by listing your projects.",
        })
    credential_type: Literal["tidb_cloud_api_key"] = Field("tidb_cloud_api_key", json_schema_extra={"ui:hidden": True})
    public_key: str = Field(..., title="Public key", min_length=1, json_schema_extra={"ui:widget": "password"})
    private_key: str = Field(..., title="Private key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("public_key", "private_key", mode="before")
    @classmethod
    def key(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste the key without whitespace or control characters")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _Page(_Input):
    page_size: int = Field(10, ge=1, le=100, title="Page size")
    page_token: str | None = Field(None, title="Page token", description="Use nextPageToken from the previous response. Keep the same filters.")


class _Cluster(_Input):
    cluster_id: str = Field(..., min_length=1, title="Cluster ID", description="The cluster ID, not its full resource name.")


class _ClusterPage(_Cluster, _Page):
    pass


class _Branch(_Cluster):
    branch_id: str = Field(..., min_length=1, title="Branch ID")


class _Backup(_Input):
    backup_id: str = Field(..., min_length=1, title="Backup ID")


class _Import(_Cluster):
    import_id: str = Field(..., min_length=1, title="Import ID")


class _Export(_Cluster):
    export_id: str = Field(..., min_length=1, title="Export ID")


class TiDBCloudListProjectsConfig(_Page):
    operation: Literal["list_projects"] = Field("list_projects", title="List Projects", json_schema_extra={"ui:hidden": True})

class TiDBCloudListClustersConfig(_Page):
    operation: Literal["list_clusters"] = Field("list_clusters", title="List Clusters", json_schema_extra={"ui:hidden": True})
    filter: str | None = Field(None, description='Google AIP filter, e.g. state="ACTIVE".')
    order_by: str | None = Field(None, title="Order by")

class TiDBCloudGetClusterConfig(_Cluster):
    operation: Literal["get_cluster"] = Field("get_cluster", title="Get Cluster", json_schema_extra={"ui:hidden": True})
    view: Literal["BASIC", "FULL"] = "FULL"

class TiDBCloudCreateClusterConfig(_Input):
    operation: Literal["create_cluster"] = Field("create_cluster", title="Create Cluster", json_schema_extra={"ui:hidden": True})
    display_name: str = Field(..., min_length=4, max_length=64, pattern=r"^[A-Za-z0-9][-A-Za-z0-9]{2,62}[A-Za-z0-9]$", title="Cluster name")
    region: str = Field(..., pattern=r"^regions/(aws|gcp|azure)-(.+)$", description="Region name, e.g. regions/aws-us-west-2. Use List Regions to find available locations.")
    root_password: str = Field(..., min_length=8, max_length=64, title="Root password", json_schema_extra={"ui:widget": "password"})

class TiDBCloudUpdateClusterConfig(_Cluster):
    operation: Literal["update_cluster"] = Field("update_cluster", title="Update Cluster", json_schema_extra={"ui:hidden": True})
    display_name: str = Field(..., min_length=4, max_length=64, pattern=r"^[A-Za-z0-9][-A-Za-z0-9]{2,62}[A-Za-z0-9]$", title="New cluster name", description="Renames the selected cluster using updateMask=displayName.")

class TiDBCloudDeleteClusterConfig(_Cluster):
    operation: Literal["delete_cluster"] = Field("delete_cluster", title="Delete Cluster", json_schema_extra={"ui:hidden": True})

class TiDBCloudChangeRootPasswordConfig(_Cluster):
    operation: Literal["change_root_password"] = Field("change_root_password", title="Change Root Password", json_schema_extra={"ui:hidden": True})
    password: str = Field(..., min_length=8, max_length=64, title="New root password", json_schema_extra={"ui:widget": "password"})

class TiDBCloudListRegionsConfig(_Input):
    operation: Literal["list_regions"] = Field("list_regions", title="List Regions", json_schema_extra={"ui:hidden": True})

class TiDBCloudListBranchesConfig(_ClusterPage):
    operation: Literal["list_branches"] = Field("list_branches", title="List Branches", json_schema_extra={"ui:hidden": True})

class TiDBCloudGetBranchConfig(_Branch):
    operation: Literal["get_branch"] = Field("get_branch", title="Get Branch", json_schema_extra={"ui:hidden": True})
    view: Literal["BASIC", "FULL"] = "FULL"

class TiDBCloudCreateBranchConfig(_Cluster):
    operation: Literal["create_branch"] = Field("create_branch", title="Create Branch", json_schema_extra={"ui:hidden": True})
    display_name: str = Field(..., min_length=1, title="Branch name")
    parent_id: str | None = Field(None, title="Parent branch ID")
    root_password: str | None = Field(None, min_length=8, max_length=64, title="Branch root password", json_schema_extra={"ui:widget": "password"})

class TiDBCloudDeleteBranchConfig(_Branch):
    operation: Literal["delete_branch"] = Field("delete_branch", title="Delete Branch", json_schema_extra={"ui:hidden": True})

class TiDBCloudResetBranchConfig(_Branch):
    operation: Literal["reset_branch"] = Field("reset_branch", title="Reset Branch", json_schema_extra={"ui:hidden": True})

class TiDBCloudListBackupsConfig(_ClusterPage):
    operation: Literal["list_backups"] = Field("list_backups", title="List Backups", json_schema_extra={"ui:hidden": True})

class TiDBCloudGetBackupConfig(_Backup):
    operation: Literal["get_backup"] = Field("get_backup", title="Get Backup", json_schema_extra={"ui:hidden": True})

class TiDBCloudDeleteBackupConfig(_Backup):
    operation: Literal["delete_backup"] = Field("delete_backup", title="Delete Backup", json_schema_extra={"ui:hidden": True})

class TiDBCloudListImportsConfig(_ClusterPage):
    operation: Literal["list_imports"] = Field("list_imports", title="List Imports", json_schema_extra={"ui:hidden": True})
    order_by: str | None = Field(None, title="Order by", description="For example, createTime desc.")

class TiDBCloudGetImportConfig(_Import):
    operation: Literal["get_import"] = Field("get_import", title="Get Import", json_schema_extra={"ui:hidden": True})

class TiDBCloudCancelImportConfig(_Import):
    operation: Literal["cancel_import"] = Field("cancel_import", title="Cancel Import", json_schema_extra={"ui:hidden": True})

class TiDBCloudListExportsConfig(_ClusterPage):
    operation: Literal["list_exports"] = Field("list_exports", title="List Exports", json_schema_extra={"ui:hidden": True})
    order_by: str | None = Field(None, title="Order by", description="For example, createTime desc.")

class TiDBCloudGetExportConfig(_Export):
    operation: Literal["get_export"] = Field("get_export", title="Get Export", json_schema_extra={"ui:hidden": True})

class TiDBCloudDeleteExportConfig(_Export):
    operation: Literal["delete_export"] = Field("delete_export", title="Delete Export", json_schema_extra={"ui:hidden": True})

class TiDBCloudCancelExportConfig(_Export):
    operation: Literal["cancel_export"] = Field("cancel_export", title="Cancel Export", json_schema_extra={"ui:hidden": True})


TiDBCloudConfig = Annotated[Union[
    TiDBCloudListProjectsConfig,
    TiDBCloudListClustersConfig,
    TiDBCloudGetClusterConfig,
    TiDBCloudCreateClusterConfig,
    TiDBCloudUpdateClusterConfig,
    TiDBCloudDeleteClusterConfig,
    TiDBCloudChangeRootPasswordConfig,
    TiDBCloudListRegionsConfig,
    TiDBCloudListBranchesConfig,
    TiDBCloudGetBranchConfig,
    TiDBCloudCreateBranchConfig,
    TiDBCloudDeleteBranchConfig,
    TiDBCloudResetBranchConfig,
    TiDBCloudListBackupsConfig,
    TiDBCloudGetBackupConfig,
    TiDBCloudDeleteBackupConfig,
    TiDBCloudListImportsConfig,
    TiDBCloudGetImportConfig,
    TiDBCloudCancelImportConfig,
    TiDBCloudListExportsConfig,
    TiDBCloudGetExportConfig,
    TiDBCloudDeleteExportConfig,
    TiDBCloudCancelExportConfig
], Field(discriminator="operation")]


class TiDBCloudFullConfig(NodeConfig[TiDBCloudConfig, TiDBCloudAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {'list_projects': ('GET', '/projects', 'iam', 'projects'),
 'list_clusters': ('GET', '/clusters', 'serverless', 'clusters'),
 'get_cluster': ('GET', '/clusters/{cluster_id}', 'serverless', None),
 'create_cluster': ('POST', '/clusters', 'serverless', None),
 'update_cluster': ('PATCH', '/clusters/{cluster_id}', 'serverless', None),
 'delete_cluster': ('DELETE', '/clusters/{cluster_id}', 'serverless', None),
 'change_root_password': ('PUT', '/clusters/{cluster_id}/password', 'serverless', None),
 'list_regions': ('GET', '/regions', 'serverless', 'regions'),
 'list_branches': ('GET', '/clusters/{cluster_id}/branches', 'serverless', 'branches'),
 'get_branch': ('GET', '/clusters/{cluster_id}/branches/{branch_id}', 'serverless', None),
 'create_branch': ('POST', '/clusters/{cluster_id}/branches', 'serverless', None),
 'delete_branch': ('DELETE', '/clusters/{cluster_id}/branches/{branch_id}', 'serverless', None),
 'reset_branch': ('POST', '/clusters/{cluster_id}/branches/{branch_id}:reset', 'serverless', None),
 'list_backups': ('GET', '/backups', 'serverless', 'backups'),
 'get_backup': ('GET', '/backups/{backup_id}', 'serverless', None),
 'delete_backup': ('DELETE', '/backups/{backup_id}', 'serverless', None),
 'list_imports': ('GET', '/clusters/{cluster_id}/imports', 'serverless', 'imports'),
 'get_import': ('GET', '/clusters/{cluster_id}/imports/{import_id}', 'serverless', None),
 'cancel_import': ('POST', '/clusters/{cluster_id}/imports/{import_id}:cancel', 'serverless', None),
 'list_exports': ('GET', '/clusters/{cluster_id}/exports', 'serverless', 'exports'),
 'get_export': ('GET', '/clusters/{cluster_id}/exports/{export_id}', 'serverless', None),
 'delete_export': ('DELETE', '/clusters/{cluster_id}/exports/{export_id}', 'serverless', None),
 'cancel_export': ('POST', '/clusters/{cluster_id}/exports/{export_id}:cancel', 'serverless', None)}


def _segment(value):
    if value in (".", "..") or any(c in value for c in "/\\?#") or any(ord(c) < 32 for c in value):
        raise ValueError("Use a single resource ID, not a path or URL")
    return quote(value, safe="")


def _redact(value, secrets):
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items()
                if k.lower() not in {"rootpassword", "password", "privatekey", "private_key"}}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
    return value


class TiDBCloudNode(WorkflowNode):
    integration_type = "automation-tidb-cloud"
    connection_evidence = ConnectionEvidence(operation="list_projects", noun="projects",
        label_keys=("displayName", "name", "id", "projectId"))

    @classmethod
    def get_config_model(cls):
        return TiDBCloudFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a TiDB Cloud API key")
        c = self.config.config
        credential = self.config.credentials
        method, template, host, collection = ROUTES[c.operation]
        values = c.model_dump(exclude_none=True)
        path = template.format(**{k: _segment(v) for k, v in values.items() if k.endswith("_id")})
        params = {}
        if isinstance(c, _Page):
            params["pageSize"] = c.page_size
            if c.page_token:
                params["pageToken"] = c.page_token
        for local, wire in (("filter", "filter"), ("order_by", "orderBy"), ("view", "view")):
            if local in values:
                params[wire] = values[local]
        if c.operation == "list_backups":
            params["clusterId"] = c.cluster_id
        body = None
        if c.operation == "create_cluster":
            body = {"displayName": c.display_name, "region": {"name": c.region}, "rootPassword": c.root_password}
        elif c.operation == "update_cluster":
            body = {"cluster": {"displayName": c.display_name}, "updateMask": "displayName"}
        elif c.operation == "change_root_password":
            body = {"password": c.password}
        elif c.operation == "create_branch":
            body = {"displayName": c.display_name}
            if c.parent_id:
                body["parentId"] = c.parent_id
            if c.root_password:
                body["rootPassword"] = c.root_password
        secrets = [credential.public_key, credential.private_key, values.get("password"), values.get("root_password")]
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, (IAM if host == "iam" else BASE) + path,
                params=params, **({"json": body} if body is not None else {}),
                headers={"Accept": "application/json"},
                auth=httpx.DigestAuth(credential.public_key, credential.private_key))
        if not 200 <= response.status_code < 300:
            try:
                error = response.json().get("message") or "TiDB Cloud request failed"
            except (ValueError, AttributeError):
                error = "TiDB Cloud returned a non-JSON error"
            return {"status": "error", "http_status": response.status_code, "error": _redact(str(error), secrets)}
        if not response.content:
            return {"status": "success", "data": {}}
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected a TiDB Cloud JSON object")
        if data.get("error") or (data.get("code") not in (None, 0, "0") and "message" in data):
            return {"status": "error", "error": _redact(str(data.get("message") or data["error"]), secrets)}
        data = _redact(data, secrets)
        result = {"status": "success", "data": data}
        if collection:
            items = data.get(collection, [])
            if not isinstance(items, list):
                raise ValueError("Expected a TiDB Cloud collection")
            result.update(items=items, next_page_token=data.get("nextPageToken"))
        return result
