"""Neo4j Aura v1 management API. Each operation makes one contract request.

Bearer-token authentication: https://neo4j.com/docs/aura/api/authentication/
Tokens expire after one hour; reconnect with a newly issued token when expired.
Async instance and snapshot changes return accepted, requiring a later status read.
"""
from __future__ import annotations

import re
from datetime import date as Date
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.neo4j.io/v1"


class Neo4jTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Neo4j Aura Access Token",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://neo4j.com/docs/aura/api/authentication/",
            "x-credential-instructions": "Paste an existing Aura API bearer access token, without the Bearer prefix. Obtain it from the documented token endpoint using your Aura Console client credentials. Access tokens expire after one hour: reconnect with a new token when expired. NoClick does not exchange or refresh client credentials. This manages Aura infrastructure; it does not run Cypher queries. Connection checks read your accessible Aura projects.",
        },
    )
    credential_type: Literal["neo4j_access_token"] = Field(
        "neo4j_access_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., min_length=1, max_length=8192, title="Access token", json_schema_extra={"ui:widget": "password"}
    )

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste the token without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def resource_ids(cls, value, info):
        if info.field_name == "name" and value != value.strip():
            raise ValueError("Aura names must not have leading or trailing whitespace")
        if (
            info.field_name
            in {
                "instance_id",
                "snapshot_id",
                "tenant_id",
                "customer_managed_key_id",
                "source_instance_id",
                "source_snapshot_id",
            }
            and value is not None
        ):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
                raise ValueError("Use a single Aura resource ID")
        return value


class ListInstances(_Input):
    operation: Literal["list_instances"] = Field(
        "list_instances",
        title="List Instances",
        description="Returns a list of instances",
        json_schema_extra={"ui:hidden": True},
    )
    tenant_id: str | None = Field(
        None,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="An optional project ID to filter instances in a project",
    )


class CreateInstance(_Input):
    operation: Literal["create_instance"] = Field(
        "create_instance",
        title="Create Instance",
        description="Creates a new instance Asynchronous: poll the resource afterward.",
        json_schema_extra={"ui:hidden": True},
    )
    version: str = Field(..., min_length=1, max_length=1024)
    region: str = Field(..., min_length=1, max_length=1024)
    memory: str = Field(..., min_length=1, max_length=1024)
    name: str = Field(
        ...,
        min_length=1,
        max_length=30,
        description="The name of the instance (any UTF-8 characters with no trailing or leading whitespace).",
    )
    type: Literal[
        "enterprise-db", "enterprise-ds", "business-critical", "professional-db", "professional-ds", "free-db"
    ] = Field(..., min_length=1, max_length=1024)
    tenant_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Project ID",
    )
    source_instance_id: str | None = Field(
        None,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="The ID of the source instance when cloning.",
    )
    source_snapshot_id: str | None = Field(
        None,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="An optional snapshot ID to create an instance from a specific snapshot. `source_instance_id` must also be provided. Note that the snapshot must be exportable in order to create a new instance with it.",
    )
    cloud_provider: Literal["gcp", "aws", "azure"] = Field(..., min_length=1, max_length=1024)
    customer_managed_key_id: str | None = Field(
        None,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="An optional customer managed key to be used for instance creation.",
    )
    vector_optimized: bool | None = Field(
        None, description="An optional vector optimization configuration to be set during instance creation."
    )
    graph_analytics_plugin: bool | None = Field(
        None,
        description="An optional graph analytics plugin configuration to be set during instance creation.",
    )

    @model_validator(mode="after")
    def clone_source(self):
        if self.source_snapshot_id and not self.source_instance_id:
            raise ValueError("A source snapshot also requires source_instance_id")
        return self


class EstimateInstanceSize(_Input):
    operation: Literal["estimate_instance_size"] = Field(
        "estimate_instance_size",
        title="Estimate Instance Size",
        description="Estimate the size of a new instance",
        json_schema_extra={"ui:hidden": True},
    )
    node_count: int = Field(..., ge=0, description="The number of nodes to be stored in the instance.")
    relationship_count: int = Field(
        ..., ge=0, description="The number of relationships to be stored in the instance."
    )
    instance_type: Literal["professional-ds", "enterprise-ds"] | None = Field(
        None, min_length=1, max_length=1024
    )
    algorithm_categories: list[str] | None = Field(
        None, description="The algorithm categories to be used in the instance."
    )


class GetInstance(_Input):
    operation: Literal["get_instance"] = Field(
        "get_instance",
        title="Get Instance",
        description="Returns instance details",
        json_schema_extra={"ui:hidden": True},
    )
    instance_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Instance ID",
    )


class DeleteInstance(_Input):
    operation: Literal["delete_instance"] = Field(
        "delete_instance",
        title="Delete Instance",
        description="Deletes an instance Asynchronous: poll the resource afterward.",
        json_schema_extra={"ui:hidden": True},
    )
    instance_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Instance ID",
    )


class UpdateInstance(_Input):
    operation: Literal["update_instance"] = Field(
        "update_instance",
        title="Update Instance",
        description="Edits the instance configuration Asynchronous: poll the resource afterward.",
        json_schema_extra={"ui:hidden": True},
    )
    instance_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Instance ID",
    )
    name: str | None = Field(
        None,
        min_length=1,
        max_length=30,
        description="Edit the instance name in the Aura Console.\n\nThe name may include any UTF-8 characters with no trailing or leading whitespace.",
    )
    memory: str | None = Field(None, min_length=1, max_length=1024)
    vector_optimized: bool | None = Field(None, description="Add or remove the instance vector optimization.")
    graph_analytics_plugin: bool | None = Field(
        None, description="Add or remove the instance graph analytics plugin."
    )
    storage: str | None = Field(None, min_length=1, max_length=1024)

    @model_validator(mode="after")
    def change_required(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "instance_id"}):
            raise ValueError("Supply at least one instance configuration change")
        return self


class OverwriteInstance(_Input):
    operation: Literal["overwrite_instance"] = Field(
        "overwrite_instance",
        title="Overwrite Instance",
        description="Overwrites an instance Asynchronous: poll the resource afterward.",
        json_schema_extra={"ui:hidden": True},
    )
    instance_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Instance ID",
    )
    source_instance_id: str = Field(
        ..., min_length=1, max_length=1024, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
    )
    source_snapshot_id: str | None = Field(
        None, min_length=1, max_length=1024, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
    )


class PauseInstance(_Input):
    operation: Literal["pause_instance"] = Field(
        "pause_instance",
        title="Pause Instance",
        description="Pauses an instance. Asynchronous: poll the resource afterward.",
        json_schema_extra={"ui:hidden": True},
    )
    instance_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Instance ID.",
    )


class ResumeInstance(_Input):
    operation: Literal["resume_instance"] = Field(
        "resume_instance",
        title="Resume Instance",
        description="Resumes an instance Asynchronous: poll the resource afterward.",
        json_schema_extra={"ui:hidden": True},
    )
    instance_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Instance ID.",
    )


class GetSnapshot(_Input):
    operation: Literal["get_snapshot"] = Field(
        "get_snapshot",
        title="Get Snapshot",
        description="Get details of a snapshot.",
        json_schema_extra={"ui:hidden": True},
    )
    instance_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Instance ID",
    )
    snapshot_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Snapshot ID.",
    )


class RestoreSnapshot(_Input):
    operation: Literal["restore_snapshot"] = Field(
        "restore_snapshot",
        title="Restore Snapshot",
        description="Restores an instance from a snapshot. Asynchronous: poll the resource afterward.",
        json_schema_extra={"ui:hidden": True},
    )
    instance_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Instance ID",
    )
    snapshot_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Snapshot ID.",
    )


class ListSnapshots(_Input):
    operation: Literal["list_snapshots"] = Field(
        "list_snapshots",
        title="List Snapshots",
        description="Returns a list of snapshots",
        json_schema_extra={"ui:hidden": True},
    )
    instance_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Instance ID",
    )
    date: Date | None = Field(
        None, description="An optional date parameter to list snapshots for a given day, defaults to today."
    )


class CreateSnapshot(_Input):
    operation: Literal["create_snapshot"] = Field(
        "create_snapshot",
        title="Create Snapshot",
        description="Takes an on-demand snapshot Asynchronous: poll the resource afterward.",
        json_schema_extra={"ui:hidden": True},
    )
    instance_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Instance ID",
    )


class UpgradeInstance(_Input):
    operation: Literal["upgrade_instance"] = Field(
        "upgrade_instance",
        title="Upgrade Instance",
        description="Upgrade an AuraDB Professional instance to an AuraDB Business Critical instance",
        json_schema_extra={"ui:hidden": True},
    )
    instance_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Instance ID",
    )
    memory: str | None = Field(None, min_length=1, max_length=1024)
    storage: str | None = Field(None, min_length=1, max_length=1024)

    @model_validator(mode="after")
    def paired_resize(self):
        if (self.memory is None) != (self.storage is None):
            raise ValueError("An upgrade resize requires both memory and storage")
        return self


class ListProjects(_Input):
    operation: Literal["list_projects"] = Field(
        "list_projects",
        title="List Projects",
        description="Returns a list of projects",
        json_schema_extra={"ui:hidden": True},
    )


class GetProject(_Input):
    operation: Literal["get_project"] = Field(
        "get_project",
        title="Get Project",
        description="Returns project details",
        json_schema_extra={"ui:hidden": True},
    )
    tenant_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Project ID",
    )


class ListCustomerManagedKeys(_Input):
    operation: Literal["list_customer_managed_keys"] = Field(
        "list_customer_managed_keys",
        title="List Customer Managed Keys",
        description="Returns a list of customer managed keys",
        json_schema_extra={"ui:hidden": True},
    )
    tenant_id: str | None = Field(
        None,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="An optional project ID to filter customer managed keys in a project",
    )


class CreateCustomerManagedKey(_Input):
    operation: Literal["create_customer_managed_key"] = Field(
        "create_customer_managed_key",
        title="Create Customer Managed Key",
        description="Creates a new customer managed key Asynchronous: poll the resource afterward.",
        json_schema_extra={"ui:hidden": True},
    )
    region: str = Field(..., min_length=1, max_length=1024)
    name: str = Field(
        ...,
        min_length=1,
        max_length=30,
        description="The name of the key (any UTF-8 characters with no trailing or leading whitespace).",
    )
    instance_type: Literal["enterprise-db", "enterprise-ds"] = Field(..., min_length=1, max_length=1024)
    tenant_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Project ID",
    )
    cloud_provider: Literal["gcp", "aws", "azure"] = Field(..., min_length=1, max_length=1024)
    key_id: str = Field(
        ..., min_length=1, max_length=1024, description="Cloud KMS key ID, such as an AWS key ARN"
    )


class GetCustomerManagedKey(_Input):
    operation: Literal["get_customer_managed_key"] = Field(
        "get_customer_managed_key",
        title="Get Customer Managed Key",
        description="Returns customer managed key details",
        json_schema_extra={"ui:hidden": True},
    )
    customer_managed_key_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Customer Managed Key ID",
    )


class DeleteCustomerManagedKey(_Input):
    operation: Literal["delete_customer_managed_key"] = Field(
        "delete_customer_managed_key",
        title="Delete Customer Managed Key",
        description="Deletes a customer managed key",
        json_schema_extra={"ui:hidden": True},
    )
    customer_managed_key_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Customer Managed Key ID",
    )


class GetProjectMetrics(_Input):
    operation: Literal["get_project_metrics"] = Field(
        "get_project_metrics",
        title="Get Project Metrics",
        description="Returns project metrics integration details",
        json_schema_extra={"ui:hidden": True},
    )
    tenant_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
        description="Project ID",
    )


Operation = Annotated[
    Union[
        ListInstances,
        CreateInstance,
        EstimateInstanceSize,
        GetInstance,
        DeleteInstance,
        UpdateInstance,
        OverwriteInstance,
        PauseInstance,
        ResumeInstance,
        GetSnapshot,
        RestoreSnapshot,
        ListSnapshots,
        CreateSnapshot,
        UpgradeInstance,
        ListProjects,
        GetProject,
        ListCustomerManagedKeys,
        CreateCustomerManagedKey,
        GetCustomerManagedKey,
        DeleteCustomerManagedKey,
        GetProjectMetrics,
    ],
    Field(discriminator="operation"),
]


class Neo4jConfig(NodeConfig[Operation, Neo4jTokenCredential]):
    pass


ROUTES = {
    "list_instances": ("GET", "/instances", {}, {"tenant_id": "tenantId"}, (200,), False),
    "create_instance": ("POST", "/instances", {}, {}, (202,), True),
    "estimate_instance_size": ("POST", "/instances/sizing", {}, {}, (200,), True),
    "get_instance": ("GET", "/instances/{instanceId}", {"instance_id": "instanceId"}, {}, (200,), False),
    "delete_instance": (
        "DELETE",
        "/instances/{instanceId}",
        {"instance_id": "instanceId"},
        {},
        (202,),
        False,
    ),
    "update_instance": (
        "PATCH",
        "/instances/{instanceId}",
        {"instance_id": "instanceId"},
        {},
        (200, 202),
        True,
    ),
    "overwrite_instance": (
        "POST",
        "/instances/{instanceId}/overwrite",
        {"instance_id": "instanceId"},
        {},
        (202,),
        True,
    ),
    "pause_instance": (
        "POST",
        "/instances/{instanceId}/pause",
        {"instance_id": "instanceId"},
        {},
        (202,),
        True,
    ),
    "resume_instance": (
        "POST",
        "/instances/{instanceId}/resume",
        {"instance_id": "instanceId"},
        {},
        (202,),
        True,
    ),
    "get_snapshot": (
        "GET",
        "/instances/{instanceId}/snapshots/{snapshotId}",
        {"instance_id": "instanceId", "snapshot_id": "snapshotId"},
        {},
        (200,),
        False,
    ),
    "restore_snapshot": (
        "POST",
        "/instances/{instanceId}/snapshots/{snapshotId}/restore",
        {"instance_id": "instanceId", "snapshot_id": "snapshotId"},
        {},
        (202,),
        True,
    ),
    "list_snapshots": (
        "GET",
        "/instances/{instanceId}/snapshots",
        {"instance_id": "instanceId"},
        {"date": "date"},
        (200,),
        False,
    ),
    "create_snapshot": (
        "POST",
        "/instances/{instanceId}/snapshots",
        {"instance_id": "instanceId"},
        {},
        (202,),
        True,
    ),
    "upgrade_instance": (
        "POST",
        "/instances/{instanceId}/upgrade",
        {"instance_id": "instanceId"},
        {},
        (200,),
        True,
    ),
    "list_projects": ("GET", "/tenants", {}, {}, (200,), False),
    "get_project": ("GET", "/tenants/{tenantId}", {"tenant_id": "tenantId"}, {}, (200,), False),
    "list_customer_managed_keys": (
        "GET",
        "/customer-managed-keys",
        {},
        {"tenant_id": "tenantId"},
        (200,),
        False,
    ),
    "create_customer_managed_key": ("POST", "/customer-managed-keys", {}, {}, (202,), True),
    "get_customer_managed_key": (
        "GET",
        "/customer-managed-keys/{customerManagedKeyId}",
        {"customer_managed_key_id": "customerManagedKeyId"},
        {},
        (200,),
        False,
    ),
    "delete_customer_managed_key": (
        "DELETE",
        "/customer-managed-keys/{customerManagedKeyId}",
        {"customer_managed_key_id": "customerManagedKeyId"},
        {},
        (204,),
        False,
    ),
    "get_project_metrics": (
        "GET",
        "/tenants/{tenantId}/metrics-integration",
        {"tenant_id": "tenantId"},
        {},
        (200,),
        False,
    ),
}


class Neo4jNode(WorkflowNode):
    integration_type = "automation-neo4j"
    connection_evidence = ConnectionEvidence(operation="list_projects", noun="Neo4j Aura projects")

    @classmethod
    def get_config_model(cls):
        return Neo4jConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Neo4j Aura access token")
        op = self.config.config
        method, route, path_keys, query_keys, expected, has_body = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for field, placeholder in path_keys.items():
            route = route.replace("{" + placeholder + "}", values.pop(field))
        params = {wire: values.pop(field) for field, wire in query_keys.items() if field in values}
        kwargs = {"params": params}
        if has_body:
            kwargs["json"] = values
        token = self.config.credentials.access_token
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(
                method,
                BASE + route,
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/json",
                },
                **kwargs,
            )
        if response.status_code not in expected:
            message = "Aura request was not accepted"
            try:
                body = response.json()
                if isinstance(body, dict):
                    if isinstance(body.get("errors"), list):
                        message = (
                            "; ".join(
                                e["message"]
                                for e in body["errors"]
                                if isinstance(e, dict) and isinstance(e.get("message"), str)
                            )
                            or message
                        )
                    elif isinstance(body.get("error"), str):
                        message = body["error"]
            except ValueError:
                pass
            raise ValueError(
                f"Neo4j Aura HTTP {response.status_code}: {message.replace(token, '[redacted]')}"
            )
        if response.status_code == 204:
            return {"status": "success", "http_status": 204, "data": None}
        if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise ValueError("Expected JSON from Neo4j Aura")
        body = response.json()
        if (
            not isinstance(body, dict)
            or "errors" in body
            or "error" in body
            or "data" not in body
            or not isinstance(body["data"], (dict, list))
        ):
            raise ValueError("Unexpected Neo4j Aura response envelope")
        if token in str(body):
            raise ValueError("Neo4j Aura unexpectedly returned the access credential")
        return {
            **body,
            "status": "accepted" if response.status_code == 202 else "success",
            "http_status": response.status_code,
        }
