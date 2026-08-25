"""
ClickHouse Cloud management automation node.

Provides workflow integration with the ClickHouse Cloud control-plane API
(https://api.clickhouse.cloud/v1) for operations including:
- Organizations: list, get, update, list activities, get usage cost
- Services: list, get, create, update, delete, change state, update scaling, update password
- Query Endpoints: get, upsert, delete
- Backups: list, get single, get/update backup configuration
- ClickPipes: list, create, get, update state, delete (org-level path)
- API Keys: list, create, delete
- Members & Invitations: list/get/update members, remove member, list/create/get/delete invitations
- Metrics: get Prometheus metrics

Authentication: API key (Key ID + Key Secret) via HTTP Basic auth.
API Base URL: https://api.clickhouse.cloud/v1
Documentation: https://clickhouse.com/docs/cloud/manage/api/api-overview

This node targets the ClickHouse Cloud management/control-plane API (manage
orgs, services, keys, ClickPipes, backups). It is separate from the ClickHouse
database HTTP query interface (port 8443) which runs SQL.
"""

import base64
import logging
import time
import uuid as uuid_module
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.poll_trigger import bounded_seen_ids
from nodes.cron_trigger_node import (
    ScheduleConfig,
    schedule_to_cron,
    schedule_to_interval_ms,
)

logger = logging.getLogger(__name__)

CLICKHOUSE_API_BASE = "https://api.clickhouse.cloud/v1"

# Bound the per-node seen-activity-id set so it cannot grow without limit.
_MAX_SEEN_ACTIVITY_IDS = 10000


# ============================================================================
# Credential Schema
# ============================================================================


class ClickHouseApiKeyCredential(BaseModel):
    """API key credential (Key ID + Key Secret) for the ClickHouse Cloud API."""

    credential_type: Literal["clickhouse_api_key"] = Field(
        "clickhouse_api_key", json_schema_extra={"ui:hidden": True}
    )
    key_id: str = Field(
        ...,
        title="Key ID",
        description="ClickHouse Cloud API Key ID (used as the HTTP Basic username)",
        json_schema_extra={"ui:widget": "password"},
    )
    key_secret: str = Field(
        ...,
        title="Key Secret",
        description="ClickHouse Cloud API Key Secret (shown only once at creation; used as the HTTP Basic password)",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://console.clickhouse.cloud/",
            "x-credential-instructions": (
                "Create an API key in the ClickHouse Cloud console under "
                "Settings -> API Keys -> New API Key. Choose a role (developer = "
                "read-only, admin = read/write). Copy the Key ID and Key Secret "
                "(the secret is shown only once)."
            ),
        }
    )


ClickHouseCredential = ClickHouseApiKeyCredential


# ============================================================================
# Operation Configs
# ============================================================================


class ClickHouseListOrganizationsConfig(BaseModel):
    """List organizations the API key can access."""

    operation: Literal["list_organizations"] = Field(
        "list_organizations",
        json_schema_extra={
            "const": "list_organizations",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "List Organizations",
        },
        title="List Organizations",
    )


class ClickHouseGetOrganizationConfig(BaseModel):
    """Get details of a single organization."""

    operation: Literal["get_organization"] = Field(
        "get_organization",
        json_schema_extra={
            "const": "get_organization",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Get Organization",
        },
        title="Get Organization",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization to retrieve",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )


class ClickHouseUpdateOrganizationConfig(BaseModel):
    """Update organization settings (e.g. name)."""

    operation: Literal["update_organization"] = Field(
        "update_organization",
        json_schema_extra={
            "const": "update_organization",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Update Organization",
        },
        title="Update Organization",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    name: str = Field(..., title="Name", description="New organization name")


class ClickHouseListActivitiesConfig(BaseModel):
    """List the audit log of organization activities."""

    operation: Literal["list_activities"] = Field(
        "list_activities",
        json_schema_extra={
            "const": "list_activities",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "List Activities",
        },
        title="List Activities",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization whose activity log to read",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    from_date: Optional[str] = Field(
        None, title="From Date", description="ISO 8601 lower bound for activities (optional)"
    )
    to_date: Optional[str] = Field(
        None, title="To Date", description="ISO 8601 upper bound for activities (optional)"
    )


class ClickHouseGetUsageCostConfig(BaseModel):
    """Retrieve usage/cost data for a date range."""

    operation: Literal["get_usage_cost"] = Field(
        "get_usage_cost",
        json_schema_extra={
            "const": "get_usage_cost",
            "ui:hidden": True,
            "x-category": "Organizations",
            "x-is-trigger": False,
            "x-display-name": "Get Usage Cost",
        },
        title="Get Usage Cost",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization to read usage cost for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    from_date: str = Field(
        ..., title="From Date", description="Start of the usage window (YYYY-MM-DD)"
    )
    to_date: str = Field(
        ..., title="To Date", description="End of the usage window (YYYY-MM-DD)"
    )


class ClickHouseListServicesConfig(BaseModel):
    """List all ClickHouse services in an organization."""

    operation: Literal["list_services"] = Field(
        "list_services",
        json_schema_extra={
            "const": "list_services",
            "ui:hidden": True,
            "x-category": "Services",
            "x-is-trigger": False,
            "x-display-name": "List Services",
        },
        title="List Services",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization whose services to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )


class ClickHouseCreateServiceConfig(BaseModel):
    """Provision a new ClickHouse service."""

    operation: Literal["create_service"] = Field(
        "create_service",
        json_schema_extra={
            "const": "create_service",
            "ui:hidden": True,
            "x-category": "Services",
            "x-is-trigger": False,
            "x-display-name": "Create Service",
        },
        title="Create Service",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization to create the service in",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    name: str = Field(..., title="Name", description="Name for the new service")
    provider: str = Field(
        "aws",
        title="Cloud Provider",
        description="Cloud provider to host the service on",
        json_schema_extra={
            "enum": ["aws", "gcp", "azure"],
            "enumNames": ["AWS", "Google Cloud", "Azure"],
            "x-enum-searchable": True,
        },
    )
    region: str = Field(
        ..., title="Region", description="Cloud region (e.g. us-east-1, eu-west-1)"
    )


class ClickHouseGetServiceConfig(BaseModel):
    """Get details of a single service."""

    operation: Literal["get_service"] = Field(
        "get_service",
        json_schema_extra={
            "const": "get_service",
            "ui:hidden": True,
            "x-category": "Services",
            "x-is-trigger": False,
            "x-display-name": "Get Service",
        },
        title="Get Service",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization the service belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    service_id: str = Field(..., title="Service ID", description="The service to retrieve")


class ClickHouseUpdateServiceConfig(BaseModel):
    """Update service basics (name, etc.)."""

    operation: Literal["update_service"] = Field(
        "update_service",
        json_schema_extra={
            "const": "update_service",
            "ui:hidden": True,
            "x-category": "Services",
            "x-is-trigger": False,
            "x-display-name": "Update Service",
        },
        title="Update Service",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization the service belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    service_id: str = Field(..., title="Service ID", description="The service to update")
    name: str = Field(..., title="Name", description="New service name")


class ClickHouseDeleteServiceConfig(BaseModel):
    """Delete a service."""

    operation: Literal["delete_service"] = Field(
        "delete_service",
        json_schema_extra={
            "const": "delete_service",
            "ui:hidden": True,
            "x-category": "Services",
            "x-is-trigger": False,
            "x-display-name": "Delete Service",
        },
        title="Delete Service",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization the service belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    service_id: str = Field(..., title="Service ID", description="The service to delete")


class ClickHouseUpdateServiceStateConfig(BaseModel):
    """Start or stop a service."""

    operation: Literal["update_service_state"] = Field(
        "update_service_state",
        json_schema_extra={
            "const": "update_service_state",
            "ui:hidden": True,
            "x-category": "Services",
            "x-is-trigger": False,
            "x-display-name": "Start / Stop Service",
        },
        title="Start / Stop Service",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization the service belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    service_id: str = Field(..., title="Service ID", description="The service to change state")
    command: str = Field(
        "start",
        title="Command",
        description="Whether to start or stop the service",
        json_schema_extra={
            "enum": ["start", "stop"],
            "enumNames": ["Start", "Stop"],
            "x-enum-searchable": True,
        },
    )


class ClickHouseUpdateServiceScalingConfig(BaseModel):
    """Update service autoscaling min/max replica memory."""

    operation: Literal["update_service_scaling"] = Field(
        "update_service_scaling",
        json_schema_extra={
            "const": "update_service_scaling",
            "ui:hidden": True,
            "x-category": "Services",
            "x-is-trigger": False,
            "x-display-name": "Update Service Scaling",
        },
        title="Update Service Scaling",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization the service belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    service_id: str = Field(..., title="Service ID", description="The service to rescale")
    min_total_memory_gb: Optional[str] = Field(
        None,
        title="Min Total Memory (GB)",
        description="Minimum total cluster memory in GB (e.g. 48, 96, 192)",
    )
    max_total_memory_gb: Optional[str] = Field(
        None,
        title="Max Total Memory (GB)",
        description="Maximum total cluster memory in GB (e.g. 96, 192, 360)",
    )


class ClickHouseUpdateServiceReplicaScalingConfig(BaseModel):
    """Update service autoscaling — new endpoint replacing the deprecated /scaling path."""

    operation: Literal["update_service_replica_scaling"] = Field("update_service_replica_scaling", json_schema_extra={"const": "update_service_replica_scaling", "ui:hidden": True, "x-category": "Services", "x-is-trigger": False, "x-display-name": "Update Service Replica Scaling"}, title="Update Service Replica Scaling")
    organization_id: str = Field(..., title="Organization", json_schema_extra={"x-dynamic-options": {"field_name": "organization_id", "placeholder": "Select an organization...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste organization ID"}})
    service_id: str = Field(..., title="Service ID", description="The service to rescale")
    min_replica_memory_gb: Optional[str] = Field(None, title="Min Memory per Replica (GB)", description="Minimum memory per replica (e.g. 8, 16, 32)")
    max_replica_memory_gb: Optional[str] = Field(None, title="Max Memory per Replica (GB)", description="Maximum memory per replica (e.g. 8, 16, 32, 64, 120, 236)")
    num_replicas: Optional[str] = Field(None, title="Number of Replicas", description="Fixed number of replicas (overrides autoscaling)")


class ClickHouseUpdateServicePasswordConfig(BaseModel):
    """Reset the service's default database user password."""

    operation: Literal["update_service_password"] = Field(
        "update_service_password",
        json_schema_extra={
            "const": "update_service_password",
            "ui:hidden": True,
            "x-category": "Services",
            "x-is-trigger": False,
            "x-display-name": "Update Service Password",
        },
        title="Update Service Password",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization the service belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    service_id: str = Field(..., title="Service ID", description="The service to update")
    new_password_hash: Optional[str] = Field(
        None,
        title="New Password Hash",
        description="Optional sha256 hex hash of the new password. Omit to have ClickHouse generate one.",
    )


class ClickHouseGetPrivateEndpointConfigConfig(BaseModel):
    """Get the private endpoint configuration info needed to connect via VPC."""

    operation: Literal["get_private_endpoint_config"] = Field("get_private_endpoint_config", json_schema_extra={"const": "get_private_endpoint_config", "ui:hidden": True, "x-category": "Services", "x-is-trigger": False, "x-display-name": "Get Private Endpoint Config"}, title="Get Private Endpoint Config")
    organization_id: str = Field(..., title="Organization", json_schema_extra={"x-dynamic-options": {"field_name": "organization_id", "placeholder": "Select an organization...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste organization ID"}})
    service_id: str = Field(..., title="Service ID", description="The service to get private endpoint config for")


class ClickHouseGetQueryEndpointConfig(BaseModel):
    """Get the SQL query endpoint config for a service."""

    operation: Literal["get_query_endpoint"] = Field(
        "get_query_endpoint",
        json_schema_extra={
            "const": "get_query_endpoint",
            "ui:hidden": True,
            "x-category": "Query Endpoints",
            "x-is-trigger": False,
            "x-display-name": "Get Query Endpoint",
        },
        title="Get Query Endpoint",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization the service belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    service_id: str = Field(..., title="Service ID", description="The service to read the endpoint for")


class ClickHouseUpsertQueryEndpointConfig(BaseModel):
    """Create or update a query endpoint to run SQL against the service over HTTPS."""

    operation: Literal["upsert_query_endpoint"] = Field(
        "upsert_query_endpoint",
        json_schema_extra={
            "const": "upsert_query_endpoint",
            "ui:hidden": True,
            "x-category": "Query Endpoints",
            "x-is-trigger": False,
            "x-display-name": "Create / Update Query Endpoint",
        },
        title="Create / Update Query Endpoint",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization the service belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    service_id: str = Field(..., title="Service ID", description="The service to attach the endpoint to")
    open_api_keys: Optional[str] = Field(
        None,
        title="Allowed Roles",
        description="Comma-separated API key roles allowed (e.g. sql_console_admin, sql_console_read_only)",
    )
    allowed_origins: Optional[str] = Field(
        None, title="Allowed Origins", description="Comma-separated allowed CORS origins"
    )


class ClickHouseDeleteQueryEndpointConfig(BaseModel):
    """Delete the service's query endpoint."""

    operation: Literal["delete_query_endpoint"] = Field(
        "delete_query_endpoint",
        json_schema_extra={
            "const": "delete_query_endpoint",
            "ui:hidden": True,
            "x-category": "Query Endpoints",
            "x-is-trigger": False,
            "x-display-name": "Delete Query Endpoint",
        },
        title="Delete Query Endpoint",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization the service belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    service_id: str = Field(..., title="Service ID", description="The service whose endpoint to delete")


class ClickHouseListBackupsConfig(BaseModel):
    """List backups for a service."""

    operation: Literal["list_backups"] = Field(
        "list_backups",
        json_schema_extra={
            "const": "list_backups",
            "ui:hidden": True,
            "x-category": "Backups",
            "x-is-trigger": False,
            "x-display-name": "List Backups",
        },
        title="List Backups",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization the service belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    service_id: str = Field(..., title="Service ID", description="The service whose backups to list")


class ClickHouseGetBackupConfigurationConfig(BaseModel):
    """Read the backup schedule/retention configuration for a service."""

    operation: Literal["get_backup_configuration"] = Field(
        "get_backup_configuration",
        json_schema_extra={
            "const": "get_backup_configuration",
            "ui:hidden": True,
            "x-category": "Backups",
            "x-is-trigger": False,
            "x-display-name": "Get Backup Configuration",
        },
        title="Get Backup Configuration",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization the service belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    service_id: str = Field(..., title="Service ID", description="The service whose backup config to read")


class ClickHouseGetBackupConfig(BaseModel):
    """Get details of a single backup."""

    operation: Literal["get_backup"] = Field("get_backup", json_schema_extra={"const": "get_backup", "ui:hidden": True, "x-category": "Backups", "x-is-trigger": False, "x-display-name": "Get Backup"}, title="Get Backup")
    organization_id: str = Field(..., title="Organization", json_schema_extra={"x-dynamic-options": {"field_name": "organization_id", "placeholder": "Select an organization...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste organization ID"}})
    service_id: str = Field(..., title="Service ID", description="The service the backup belongs to")
    backup_id: str = Field(..., title="Backup ID", description="The backup to retrieve")


class ClickHouseUpdateBackupConfigurationConfig(BaseModel):
    """Update a service's backup schedule and retention settings."""

    operation: Literal["update_backup_configuration"] = Field("update_backup_configuration", json_schema_extra={"const": "update_backup_configuration", "ui:hidden": True, "x-category": "Backups", "x-is-trigger": False, "x-display-name": "Update Backup Configuration"}, title="Update Backup Configuration")
    organization_id: str = Field(..., title="Organization", json_schema_extra={"x-dynamic-options": {"field_name": "organization_id", "placeholder": "Select an organization...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste organization ID"}})
    service_id: str = Field(..., title="Service ID", description="The service whose backup configuration to update")
    backup_period_in_hours: Optional[int] = Field(None, title="Backup Period (hours)", description="How often to create backups (24 = daily)")
    backup_retention_period_in_hours: Optional[int] = Field(None, title="Retention Period (hours)", description="How long to keep backups (e.g. 168 = 7 days)")


class ClickHouseListClickPipesConfig(BaseModel):
    """List ingestion pipelines (ClickPipes) for an organization."""

    operation: Literal["list_clickpipes"] = Field(
        "list_clickpipes",
        json_schema_extra={
            "const": "list_clickpipes",
            "ui:hidden": True,
            "x-category": "ClickPipes",
            "x-is-trigger": False,
            "x-display-name": "List ClickPipes",
        },
        title="List ClickPipes",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization whose ClickPipes to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )


class ClickHouseCreateClickPipeConfig(BaseModel):
    """Create a ClickPipe data-ingestion pipeline."""

    operation: Literal["create_clickpipe"] = Field(
        "create_clickpipe",
        json_schema_extra={
            "const": "create_clickpipe",
            "ui:hidden": True,
            "x-category": "ClickPipes",
            "x-is-trigger": False,
            "x-display-name": "Create ClickPipe",
        },
        title="Create ClickPipe",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization to create the ClickPipe in",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    definition: str = Field(
        ...,
        title="ClickPipe Definition (JSON)",
        description="JSON object describing the ClickPipe (name, source, destination, etc.)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ClickHouseUpdateClickPipeStateConfig(BaseModel):
    """Start, stop, or pause a ClickPipe."""

    operation: Literal["update_clickpipe_state"] = Field(
        "update_clickpipe_state",
        json_schema_extra={
            "const": "update_clickpipe_state",
            "ui:hidden": True,
            "x-category": "ClickPipes",
            "x-is-trigger": False,
            "x-display-name": "Update ClickPipe State",
        },
        title="Update ClickPipe State",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization the ClickPipe belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    clickpipe_id: str = Field(..., title="ClickPipe ID", description="The ClickPipe to change state")
    command: str = Field(
        "start",
        title="Command",
        description="State change to apply",
        json_schema_extra={
            "enum": ["start", "stop", "pause", "resume"],
            "enumNames": ["Start", "Stop", "Pause", "Resume"],
            "x-enum-searchable": True,
        },
    )


class ClickHouseGetClickPipeConfig(BaseModel):
    """Get details of a single ClickPipe."""

    operation: Literal["get_clickpipe"] = Field("get_clickpipe", json_schema_extra={"const": "get_clickpipe", "ui:hidden": True, "x-category": "ClickPipes", "x-is-trigger": False, "x-display-name": "Get ClickPipe"}, title="Get ClickPipe")
    organization_id: str = Field(..., title="Organization", description="The organization the ClickPipe belongs to", json_schema_extra={"x-dynamic-options": {"field_name": "organization_id", "placeholder": "Select an organization...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste organization ID"}})
    clickpipe_id: str = Field(..., title="ClickPipe ID", description="The ClickPipe to retrieve")


class ClickHouseDeleteClickPipeConfig(BaseModel):
    """Delete a ClickPipe."""

    operation: Literal["delete_clickpipe"] = Field("delete_clickpipe", json_schema_extra={"const": "delete_clickpipe", "ui:hidden": True, "x-category": "ClickPipes", "x-is-trigger": False, "x-display-name": "Delete ClickPipe"}, title="Delete ClickPipe")
    organization_id: str = Field(..., title="Organization", description="The organization the ClickPipe belongs to", json_schema_extra={"x-dynamic-options": {"field_name": "organization_id", "placeholder": "Select an organization...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste organization ID"}})
    clickpipe_id: str = Field(..., title="ClickPipe ID", description="The ClickPipe to delete")


class ClickHouseListRolesConfig(BaseModel):
    """List custom roles defined in the organization (for orgs that have migrated to Custom Roles)."""

    operation: Literal["list_roles"] = Field("list_roles", json_schema_extra={"const": "list_roles", "ui:hidden": True, "x-category": "Members", "x-is-trigger": False, "x-display-name": "List Roles"}, title="List Roles")
    organization_id: str = Field(..., title="Organization", description="The organization whose roles to list", json_schema_extra={"x-dynamic-options": {"field_name": "organization_id", "placeholder": "Select an organization...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste organization ID"}})


class ClickHouseListKeysConfig(BaseModel):
    """List organization API keys."""

    operation: Literal["list_keys"] = Field(
        "list_keys",
        json_schema_extra={
            "const": "list_keys",
            "ui:hidden": True,
            "x-category": "API Keys",
            "x-is-trigger": False,
            "x-display-name": "List API Keys",
        },
        title="List API Keys",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization whose API keys to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )


class ClickHouseCreateKeyConfig(BaseModel):
    """Create a new organization API key (returns Key ID + Secret)."""

    operation: Literal["create_key"] = Field(
        "create_key",
        json_schema_extra={
            "const": "create_key",
            "ui:hidden": True,
            "x-category": "API Keys",
            "x-is-trigger": False,
            "x-display-name": "Create API Key",
        },
        title="Create API Key",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization to create the API key in",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    name: str = Field(..., title="Name", description="Name for the new API key")
    role: str = Field(
        "developer",
        title="Role",
        description="Permission role for the key (used for standard roles; ignored when role_ids is set)",
        json_schema_extra={
            "enum": ["developer", "admin"],
            "enumNames": ["Developer (read-only)", "Admin (read/write)"],
            "x-enum-searchable": True,
        },
    )
    role_ids: Optional[str] = Field(
        None,
        title="Custom Role IDs",
        description="Comma-separated custom role IDs for orgs that have migrated to Custom Roles (overrides Role)",
        json_schema_extra={"ui:placeholder": "role-uuid-1, role-uuid-2"},
    )


class ClickHouseDeleteKeyConfig(BaseModel):
    """Delete/revoke an organization API key."""

    operation: Literal["delete_key"] = Field(
        "delete_key",
        json_schema_extra={
            "const": "delete_key",
            "ui:hidden": True,
            "x-category": "API Keys",
            "x-is-trigger": False,
            "x-display-name": "Delete API Key",
        },
        title="Delete API Key",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization the key belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    key_id: str = Field(..., title="Key ID", description="The API key to delete")


class ClickHouseListMembersConfig(BaseModel):
    """List organization members."""

    operation: Literal["list_members"] = Field(
        "list_members",
        json_schema_extra={
            "const": "list_members",
            "ui:hidden": True,
            "x-category": "Members",
            "x-is-trigger": False,
            "x-display-name": "List Members",
        },
        title="List Members",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization whose members to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )


class ClickHouseRemoveMemberConfig(BaseModel):
    """Remove a member from the organization."""

    operation: Literal["remove_member"] = Field(
        "remove_member",
        json_schema_extra={
            "const": "remove_member",
            "ui:hidden": True,
            "x-category": "Members",
            "x-is-trigger": False,
            "x-display-name": "Remove Member",
        },
        title="Remove Member",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization the member belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    user_id: str = Field(..., title="User ID", description="The user to remove from the organization")


class ClickHouseGetMemberConfig(BaseModel):
    """Get a single organization member."""

    operation: Literal["get_member"] = Field("get_member", json_schema_extra={"const": "get_member", "ui:hidden": True, "x-category": "Members", "x-is-trigger": False, "x-display-name": "Get Member"}, title="Get Member")
    organization_id: str = Field(..., title="Organization", json_schema_extra={"x-dynamic-options": {"field_name": "organization_id", "placeholder": "Select an organization...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste organization ID"}})
    user_id: str = Field(..., title="User ID", description="The member's user ID")


class ClickHouseUpdateMemberConfig(BaseModel):
    """Update a member's role in the organization."""

    operation: Literal["update_member"] = Field("update_member", json_schema_extra={"const": "update_member", "ui:hidden": True, "x-category": "Members", "x-is-trigger": False, "x-display-name": "Update Member Role"}, title="Update Member Role")
    organization_id: str = Field(..., title="Organization", json_schema_extra={"x-dynamic-options": {"field_name": "organization_id", "placeholder": "Select an organization...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste organization ID"}})
    user_id: str = Field(..., title="User ID", description="The member to update")
    role: str = Field(..., title="Role", description="New role for the member (used for standard roles; ignored when role_ids is set)", json_schema_extra={"enum": ["developer", "admin"], "enumNames": ["Developer", "Admin"], "x-enum-searchable": True})
    role_ids: Optional[str] = Field(None, title="Custom Role IDs", description="Comma-separated custom role IDs for orgs that have migrated to Custom Roles (overrides Role)", json_schema_extra={"ui:placeholder": "role-uuid-1, role-uuid-2"})


class ClickHouseListInvitationsConfig(BaseModel):
    """List pending organization invitations."""

    operation: Literal["list_invitations"] = Field(
        "list_invitations",
        json_schema_extra={
            "const": "list_invitations",
            "ui:hidden": True,
            "x-category": "Invitations",
            "x-is-trigger": False,
            "x-display-name": "List Invitations",
        },
        title="List Invitations",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization whose invitations to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )


class ClickHouseCreateInvitationConfig(BaseModel):
    """Invite a user to the organization."""

    operation: Literal["create_invitation"] = Field(
        "create_invitation",
        json_schema_extra={
            "const": "create_invitation",
            "ui:hidden": True,
            "x-category": "Invitations",
            "x-is-trigger": False,
            "x-display-name": "Create Invitation",
        },
        title="Create Invitation",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization to invite the user into",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    email: str = Field(..., title="Email", description="Email address to invite")
    role: str = Field(
        "developer",
        title="Role",
        description="Organization role to grant (used for standard roles; ignored when role_ids is set)",
        json_schema_extra={
            "enum": ["developer", "admin"],
            "enumNames": ["Developer", "Admin"],
            "x-enum-searchable": True,
        },
    )
    role_ids: Optional[str] = Field(
        None,
        title="Custom Role IDs",
        description="Comma-separated custom role IDs for orgs that have migrated to Custom Roles (overrides Role)",
        json_schema_extra={"ui:placeholder": "role-uuid-1, role-uuid-2"},
    )


class ClickHouseDeleteInvitationConfig(BaseModel):
    """Revoke a pending invitation."""

    operation: Literal["delete_invitation"] = Field(
        "delete_invitation",
        json_schema_extra={
            "const": "delete_invitation",
            "ui:hidden": True,
            "x-category": "Invitations",
            "x-is-trigger": False,
            "x-display-name": "Delete Invitation",
        },
        title="Delete Invitation",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization the invitation belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    invitation_id: str = Field(..., title="Invitation ID", description="The invitation to revoke")


class ClickHouseGetInvitationConfig(BaseModel):
    """Get a single pending invitation."""

    operation: Literal["get_invitation"] = Field("get_invitation", json_schema_extra={"const": "get_invitation", "ui:hidden": True, "x-category": "Members", "x-is-trigger": False, "x-display-name": "Get Invitation"}, title="Get Invitation")
    organization_id: str = Field(..., title="Organization", json_schema_extra={"x-dynamic-options": {"field_name": "organization_id", "placeholder": "Select an organization...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste organization ID"}})
    invitation_id: str = Field(..., title="Invitation ID", description="The invitation to retrieve")


class ClickHouseGetPrometheusMetricsConfig(BaseModel):
    """Scrape service metrics in Prometheus exposition format."""

    operation: Literal["get_prometheus_metrics"] = Field(
        "get_prometheus_metrics",
        json_schema_extra={
            "const": "get_prometheus_metrics",
            "ui:hidden": True,
            "x-category": "Metrics",
            "x-is-trigger": False,
            "x-display-name": "Get Prometheus Metrics",
        },
        title="Get Prometheus Metrics",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization the service belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    service_id: str = Field(..., title="Service ID", description="The service to scrape metrics from")


# ============================================================================
# Trigger Config
# ============================================================================


class ClickHouseOnQueryResultsConfig(BaseModel):
    """Poll-based trigger: runs on a schedule, fetches the organization activity
    audit log, and emits NEW activities since the last poll.

    ClickHouse Cloud's management API has no outbound webhooks, so this trigger
    polls the time-ordered `/activities` audit log and dedupes on the activity
    `id` cursor — each activity is emitted at most once across polls.
    """

    operation: Literal["on_query_results"] = Field(
        "on_query_results",
        json_schema_extra={
            "const": "on_query_results",
            "ui:hidden": True,
            "x-category": "Triggers",
            "x-is-trigger": True,
            "x-display-name": "On Scheduled Query Results",
        },
        title="On Scheduled Query Results",
    )
    organization_id: str = Field(
        ...,
        title="Organization",
        description="The organization whose activity audit log to poll",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "organization_id",
                "placeholder": "Select an organization...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste organization ID",
            }
        },
    )
    activity_type: Optional[str] = Field(
        None,
        title="Activity Type Filter",
        description="Only emit activities whose type matches this value (e.g. 'service.create'). Leave blank to emit all.",
        json_schema_extra={"placeholder": "service.create"},
    )
    schedule: Optional[ScheduleConfig] = Field(
        default=ScheduleConfig(frequency="minutes", interval=5),
        title="Check Frequency",
        description="How often to poll for new activities",
        json_schema_extra={
            "ui:widget": "schedule",
            "x-exclude-frequencies": ["seconds"],
        },
    )
    max_results: int = Field(
        50,
        title="Max Activities",
        description="Maximum number of activities to fetch per poll (1-100)",
        ge=1,
        le=100,
        json_schema_extra={"ui:hidden": True},
    )
    # Hidden cursor: highest activity id emitted so far (dedupe across polls)
    last_seen_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    # Hidden webhook/schedule management fields
    webhook_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True, "ui:loadValue": True, "ui:copyable": True},
    )
    schedule_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    next_run: Optional[str] = Field(
        default=None,
        title="Next Check",
        json_schema_extra={"ui:widget": "nextRun"},
    )
    interval_ms: Optional[int] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    is_active: Optional[bool] = Field(default=True, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})


# ============================================================================
# Discriminated Union
# ============================================================================


ClickHouseConfig = Annotated[
    Union[
        ClickHouseListOrganizationsConfig,
        ClickHouseGetOrganizationConfig,
        ClickHouseUpdateOrganizationConfig,
        ClickHouseListActivitiesConfig,
        ClickHouseGetUsageCostConfig,
        ClickHouseListServicesConfig,
        ClickHouseCreateServiceConfig,
        ClickHouseGetServiceConfig,
        ClickHouseUpdateServiceConfig,
        ClickHouseDeleteServiceConfig,
        ClickHouseUpdateServiceStateConfig,
        ClickHouseUpdateServiceScalingConfig,
        ClickHouseUpdateServiceReplicaScalingConfig,
        ClickHouseUpdateServicePasswordConfig,
        ClickHouseGetPrivateEndpointConfigConfig,
        ClickHouseGetQueryEndpointConfig,
        ClickHouseUpsertQueryEndpointConfig,
        ClickHouseDeleteQueryEndpointConfig,
        ClickHouseListBackupsConfig,
        ClickHouseGetBackupConfigurationConfig,
        ClickHouseGetBackupConfig,
        ClickHouseUpdateBackupConfigurationConfig,
        ClickHouseListClickPipesConfig,
        ClickHouseCreateClickPipeConfig,
        ClickHouseUpdateClickPipeStateConfig,
        ClickHouseGetClickPipeConfig,
        ClickHouseDeleteClickPipeConfig,
        ClickHouseListRolesConfig,
        ClickHouseListKeysConfig,
        ClickHouseCreateKeyConfig,
        ClickHouseDeleteKeyConfig,
        ClickHouseListMembersConfig,
        ClickHouseRemoveMemberConfig,
        ClickHouseGetMemberConfig,
        ClickHouseUpdateMemberConfig,
        ClickHouseListInvitationsConfig,
        ClickHouseCreateInvitationConfig,
        ClickHouseDeleteInvitationConfig,
        ClickHouseGetInvitationConfig,
        ClickHouseGetPrometheusMetricsConfig,
        # Trigger
        ClickHouseOnQueryResultsConfig,
    ],
    Discriminator("operation"),
]


class ClickHouseNodeConfig(NodeConfig[ClickHouseConfig, ClickHouseCredential]):
    """Full configuration for the ClickHouse node including credentials."""

    pass


# ============================================================================
# HTTP Request Helper
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[list]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


async def _clickhouse_request(
    key_id: str,
    key_secret: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
    expect_text: bool = False,
) -> Dict[str, Any]:
    """Make an authenticated ClickHouse Cloud API request and return a structured result.

    Auth is HTTP Basic with the Key ID as username and Key Secret as password.
    """
    url = f"{CLICKHOUSE_API_BASE}{endpoint}"
    basic = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/json",
    }
    if json_body:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    if isinstance(err, dict):
                        message = err.get("error") or err.get("message") or str(err)
                    else:
                        message = str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[ClickHouseNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                data: Any = {"success": True}
            elif expect_text:
                data = {"metrics": response.text}
            else:
                try:
                    payload = response.json()
                    # ClickHouse management API wraps results in {result, status}
                    data = (
                        payload.get("result", payload)
                        if isinstance(payload, dict)
                        else payload
                    )
                except Exception:
                    data = {"raw": response.text}
            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[ClickHouseNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ============================================================================
# Node Implementation
# ============================================================================


class ClickHouseNode(WorkflowNode):
    """ClickHouse Cloud management automation node."""

    edit_examples = [
        "List all ClickHouse services in my organization",
        "Stop a ClickHouse service overnight to save cost",
        "Get usage cost for the last billing period",
        "Create a developer API key for a new teammate",
        "List the audit activities for my organization",
    ]

    @classmethod
    def get_config_model(cls):
        return ClickHouseNodeConfig

    @classmethod
    def resolve_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """The ClickHouse trigger is poll-based: the webhook is a wake-up signal,
        not data. Return None so execute() runs and polls the activity log."""
        if config.get("operation") == "on_query_results":
            return None
        return payload

    def trigger_produced_no_event(self, output: Dict[str, Any]) -> bool:
        """Return True when the poll found no new activities — suppresses downstream execution."""
        return output.get("new_count", -1) == 0

    @classmethod
    async def cleanup_external_webhook(
        cls, pool, workflow_id: str, node_id: str,
        config: Dict[str, Any], credentials: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Clean up the cron schedule when the workflow is deleted or trigger deactivated."""
        from utils.cron_scheduler_client import delete_schedule, is_cron_scheduler_enabled
        schedule_id = (config or {}).get("schedule_id")
        if schedule_id and is_cron_scheduler_enabled():
            try:
                await delete_schedule(schedule_id=schedule_id)
            except Exception as e:
                logger.warning(f"[ClickHouseNode] Failed to delete schedule {schedule_id}: {e}")

    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id: uuid_module.UUID,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Provision the webhook + polling schedule for the trigger (same pattern
        as Gmail/CronTriggerNode)."""
        from utils.webhook_manager import WebhookManager
        from utils.cron_scheduler_client import (
            create_schedule,
            update_schedule,
            is_cron_scheduler_enabled,
        )

        if field_name == "webhook_url":
            webhook_data = await WebhookManager.get_or_create_webhook(
                pool=pool,
                user_id=user_id,
                workflow_id=workflow_id,
                node_id=node_id,
            )
            webhook_id = webhook_data.get("webhook_id")
            webhook_url = webhook_data.get("webhook_url")

            schedule = {"frequency": "minutes", "interval": 5}
            if context and "schedule" in context and context["schedule"]:
                schedule = context["schedule"]
            cron_expression = schedule_to_cron(schedule)
            logger.info(
                f"[ClickHouseNode] Trigger schedule {schedule} -> cron: {cron_expression}"
            )

            existing_schedule_id = context.get("schedule_id") if context else None
            schedule_id = existing_schedule_id
            next_run = None

            if is_cron_scheduler_enabled() and webhook_url:
                if existing_schedule_id:
                    result = await update_schedule(
                        schedule_id=existing_schedule_id,
                        cron_expression=cron_expression,
                    )
                    if result.get("success"):
                        next_run = result.get("next_run")
                    elif "error" in result:
                        logger.warning(f"Failed to update schedule: {result['error']}")
                        existing_schedule_id = None

                if not existing_schedule_id:
                    result = await create_schedule(
                        user_id=user_id,
                        workflow_id=str(workflow_id),
                        node_id=node_id,
                        cron_expression=cron_expression,
                        webhook_url=webhook_url,
                        payload={"source": "clickhouse_trigger", "node_id": node_id},
                    )
                    if "id" in result:
                        schedule_id = result["id"]
                        next_run = result.get("next_run")
                    elif "error" in result:
                        logger.warning(f"Failed to create schedule: {result['error']}")

            interval_ms = schedule_to_interval_ms(schedule)

            return {
                "values": {
                    "webhook_id": webhook_id,
                    "webhook_url": webhook_url,
                    "schedule_id": schedule_id,
                    "next_run": next_run,
                    "interval_ms": interval_ms,
                }
            }

        return {"value": None}

    # ------------------------------------------------------------------
    # Dynamic options (organizations)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name != "organization_id":
            return {"options": []}
        key_id = (credential_data or {}).get("key_id")
        key_secret = (credential_data or {}).get("key_secret")
        if not key_id or not key_secret:
            return {"options": []}
        result = await _clickhouse_request(
            key_id, key_secret, "GET", "/organizations", action_name="list_organizations"
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or []
        orgs = data if isinstance(data, list) else []
        options = []
        for org in orgs:
            if not isinstance(org, dict):
                continue
            org_id = org.get("id")
            name = org.get("name") or org_id
            if org_id is not None:
                options.append({"label": str(name), "value": str(org_id)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, ClickHouseNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your ClickHouse API key (Key ID + Secret).")
        key_id = credentials.key_id
        key_secret = credentials.key_secret

        handlers = {
            "list_organizations": self._list_organizations,
            "get_organization": self._get_organization,
            "update_organization": self._update_organization,
            "list_activities": self._list_activities,
            "get_usage_cost": self._get_usage_cost,
            "list_services": self._list_services,
            "create_service": self._create_service,
            "get_service": self._get_service,
            "update_service": self._update_service,
            "delete_service": self._delete_service,
            "update_service_state": self._update_service_state,
            "update_service_scaling": self._update_service_scaling,
            "update_service_replica_scaling": self._update_service_replica_scaling,
            "update_service_password": self._update_service_password,
            "get_private_endpoint_config": self._get_private_endpoint_config,
            "get_query_endpoint": self._get_query_endpoint,
            "upsert_query_endpoint": self._upsert_query_endpoint,
            "delete_query_endpoint": self._delete_query_endpoint,
            "list_backups": self._list_backups,
            "get_backup_configuration": self._get_backup_configuration,
            "get_backup": self._get_backup,
            "update_backup_configuration": self._update_backup_configuration,
            "list_clickpipes": self._list_clickpipes,
            "create_clickpipe": self._create_clickpipe,
            "update_clickpipe_state": self._update_clickpipe_state,
            "get_clickpipe": self._get_clickpipe,
            "delete_clickpipe": self._delete_clickpipe,
            "list_roles": self._list_roles,
            "list_keys": self._list_keys,
            "create_key": self._create_key,
            "delete_key": self._delete_key,
            "list_members": self._list_members,
            "remove_member": self._remove_member,
            "get_member": self._get_member,
            "update_member": self._update_member,
            "list_invitations": self._list_invitations,
            "create_invitation": self._create_invitation,
            "delete_invitation": self._delete_invitation,
            "get_invitation": self._get_invitation,
            "get_prometheus_metrics": self._get_prometheus_metrics,
            "on_query_results": self._poll_activities,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, key_id, key_secret)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Handlers — Organizations
    # ------------------------------------------------------------------
    async def _list_organizations(self, c, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET", "/organizations", action_name="list_organizations"
        )

    async def _get_organization(self, c: ClickHouseGetOrganizationConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET", f"/organizations/{c.organization_id}",
            action_name="get_organization",
        )

    async def _update_organization(self, c: ClickHouseUpdateOrganizationConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "PATCH", f"/organizations/{c.organization_id}",
            json_body={"name": c.name}, action_name="update_organization",
        )

    async def _list_activities(self, c: ClickHouseListActivitiesConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET", f"/organizations/{c.organization_id}/activities",
            params={"from_date": c.from_date, "to_date": c.to_date},
            action_name="list_activities",
        )

    async def _get_usage_cost(self, c: ClickHouseGetUsageCostConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET", f"/organizations/{c.organization_id}/usageCost",
            params={"from_date": c.from_date, "to_date": c.to_date},
            action_name="get_usage_cost",
        )

    # ------------------------------------------------------------------
    # Handlers — Trigger (poll-based)
    # ------------------------------------------------------------------
    async def _poll_activities(
        self, c: ClickHouseOnQueryResultsConfig, key_id, key_secret
    ) -> Dict[str, Any]:
        """Poll the organization activity audit log and emit only NEW activities.

        The first poll after the trigger is enabled BASELINES: it records every
        current activity id as seen and emits nothing, so activation never floods
        the workflow with the entire existing audit log — the trigger only fires
        for activities that appear on later polls. The seen-id set lives in node
        state and is written under compare-and-swap (`_update_node_state`), so an
        overlapping poll on another container can't double-fire the same activity.
        """
        result = await _clickhouse_request(
            key_id, key_secret, "GET",
            f"/organizations/{c.organization_id}/activities",
            action_name="on_query_results",
        )
        if result.get("status") != "success":
            return result

        data = result.get("data") or []
        activities: List[Dict[str, Any]] = data if isinstance(data, list) else []
        if c.activity_type:
            activities = [a for a in activities if isinstance(a, dict) and a.get("type") == c.activity_type]

        timing_ms = result.get("timing_ms", {})

        def mutator(state):
            seen_list = state.get("seen_activity_ids", [])
            is_first_poll = "seen_activity_ids" not in state
            seen = set(seen_list)
            # Optional config cursor seed — only meaningful on the first poll.
            if is_first_poll and c.last_seen_id:
                seen.add(str(c.last_seen_id))

            current_ids: List[str] = []
            new_items: List[Dict[str, Any]] = []
            for activity in activities:
                if not isinstance(activity, dict):
                    continue
                activity_id = activity.get("id")
                if activity_id is None:
                    continue
                activity_id = str(activity_id)
                current_ids.append(activity_id)
                if not is_first_poll and activity_id not in seen:
                    new_items.append(activity)

            if is_first_poll:
                baseline = bounded_seen_ids(list(seen), current_ids, _MAX_SEEN_ACTIVITY_IDS)
                return {"seen_activity_ids": baseline}, ([], True)
            if new_items:
                all_seen = bounded_seen_ids(seen_list, current_ids, _MAX_SEEN_ACTIVITY_IDS)
                return {"seen_activity_ids": all_seen}, (new_items, False)
            return None, ([], False)  # nothing new → no write

        # skip_result: on a transient state blip / lost contention, emit nothing
        # this tick (state untouched) instead of failing the scheduled run.
        new_items, is_first_poll = await self._update_node_state(
            mutator, skip_result=([], False)
        )
        self._poll_emitted_count = 0 if is_first_poll else len(new_items)

        logger.info(
            f"[ClickHouseNode] Trigger poll: {len(new_items)} new activities "
            f"(from {len(activities)} total, first_poll={is_first_poll})"
        )

        last_seen_id = new_items[-1].get("id") if new_items else c.last_seen_id
        return {
            "status": "success",
            "operation": "on_query_results",
            "items": new_items,
            "new_count": len(new_items),
            "total_in_window": len(activities),
            "last_seen_id": last_seen_id,
            "timing_ms": timing_ms,
        }

    # ------------------------------------------------------------------
    # Handlers — Services
    # ------------------------------------------------------------------
    async def _list_services(self, c: ClickHouseListServicesConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET", f"/organizations/{c.organization_id}/services",
            action_name="list_services",
        )

    async def _create_service(self, c: ClickHouseCreateServiceConfig, key_id, key_secret) -> Dict[str, Any]:
        body = {"name": c.name, "provider": c.provider, "region": c.region}
        return await _clickhouse_request(
            key_id, key_secret, "POST", f"/organizations/{c.organization_id}/services",
            json_body=body, action_name="create_service",
        )

    async def _get_service(self, c: ClickHouseGetServiceConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET",
            f"/organizations/{c.organization_id}/services/{c.service_id}",
            action_name="get_service",
        )

    async def _update_service(self, c: ClickHouseUpdateServiceConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "PATCH",
            f"/organizations/{c.organization_id}/services/{c.service_id}",
            json_body={"name": c.name}, action_name="update_service",
        )

    async def _delete_service(self, c: ClickHouseDeleteServiceConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "DELETE",
            f"/organizations/{c.organization_id}/services/{c.service_id}",
            action_name="delete_service",
        )

    async def _update_service_state(self, c: ClickHouseUpdateServiceStateConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "PATCH",
            f"/organizations/{c.organization_id}/services/{c.service_id}/state",
            json_body={"command": c.command}, action_name="update_service_state",
        )

    async def _update_service_scaling(self, c: ClickHouseUpdateServiceScalingConfig, key_id, key_secret) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if c.min_total_memory_gb:
            body["minTotalMemoryGb"] = int(c.min_total_memory_gb)
        if c.max_total_memory_gb:
            body["maxTotalMemoryGb"] = int(c.max_total_memory_gb)
        return await _clickhouse_request(
            key_id, key_secret, "PATCH",
            f"/organizations/{c.organization_id}/services/{c.service_id}/scaling",
            json_body=body, action_name="update_service_scaling",
        )

    async def _update_service_password(self, c: ClickHouseUpdateServicePasswordConfig, key_id, key_secret) -> Dict[str, Any]:
        body = {"newPasswordHash": c.new_password_hash} if c.new_password_hash else {}
        return await _clickhouse_request(
            key_id, key_secret, "PATCH",
            f"/organizations/{c.organization_id}/services/{c.service_id}/password",
            json_body=body, action_name="update_service_password",
        )

    async def _get_private_endpoint_config(self, c: ClickHouseGetPrivateEndpointConfigConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET",
            f"/organizations/{c.organization_id}/services/{c.service_id}/privateEndpointConfig",
            action_name="get_private_endpoint_config",
        )

    async def _update_service_replica_scaling(self, c: ClickHouseUpdateServiceReplicaScalingConfig, key_id, key_secret) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if c.min_replica_memory_gb:
            body["minReplicaMemoryGb"] = int(c.min_replica_memory_gb)
        if c.max_replica_memory_gb:
            body["maxReplicaMemoryGb"] = int(c.max_replica_memory_gb)
        if c.num_replicas:
            body["numReplicas"] = int(c.num_replicas)
        return await _clickhouse_request(
            key_id, key_secret, "PATCH",
            f"/organizations/{c.organization_id}/services/{c.service_id}/replicaScaling",
            json_body=body, action_name="update_service_replica_scaling",
        )

    # ------------------------------------------------------------------
    # Handlers — Query Endpoints
    # ------------------------------------------------------------------
    async def _get_query_endpoint(self, c: ClickHouseGetQueryEndpointConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET",
            f"/organizations/{c.organization_id}/services/{c.service_id}/serviceQueryEndpoint",
            action_name="get_query_endpoint",
        )

    async def _upsert_query_endpoint(self, c: ClickHouseUpsertQueryEndpointConfig, key_id, key_secret) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if c.open_api_keys:
            body["openApiKeys"] = _comma_list(c.open_api_keys)
        if c.allowed_origins:
            body["allowedOrigins"] = _comma_list(c.allowed_origins)
        return await _clickhouse_request(
            key_id, key_secret, "POST",
            f"/organizations/{c.organization_id}/services/{c.service_id}/serviceQueryEndpoint",
            json_body=body, action_name="upsert_query_endpoint",
        )

    async def _delete_query_endpoint(self, c: ClickHouseDeleteQueryEndpointConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "DELETE",
            f"/organizations/{c.organization_id}/services/{c.service_id}/serviceQueryEndpoint",
            action_name="delete_query_endpoint",
        )

    # ------------------------------------------------------------------
    # Handlers — Backups
    # ------------------------------------------------------------------
    async def _list_backups(self, c: ClickHouseListBackupsConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET",
            f"/organizations/{c.organization_id}/services/{c.service_id}/backups",
            action_name="list_backups",
        )

    async def _get_backup_configuration(self, c: ClickHouseGetBackupConfigurationConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET",
            f"/organizations/{c.organization_id}/services/{c.service_id}/backupConfiguration",
            action_name="get_backup_configuration",
        )

    async def _get_backup(self, c: ClickHouseGetBackupConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET",
            f"/organizations/{c.organization_id}/services/{c.service_id}/backups/{c.backup_id}",
            action_name="get_backup",
        )

    async def _update_backup_configuration(self, c: ClickHouseUpdateBackupConfigurationConfig, key_id, key_secret) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "backupPeriodInHours": c.backup_period_in_hours,
            "backupRetentionPeriodInHours": c.backup_retention_period_in_hours,
        }
        return await _clickhouse_request(
            key_id, key_secret, "PATCH",
            f"/organizations/{c.organization_id}/services/{c.service_id}/backupConfiguration",
            json_body=body, action_name="update_backup_configuration",
        )

    # ------------------------------------------------------------------
    # Handlers — ClickPipes
    # ------------------------------------------------------------------
    async def _list_clickpipes(self, c: ClickHouseListClickPipesConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET",
            f"/organizations/{c.organization_id}/clickpipes",
            action_name="list_clickpipes",
        )

    async def _create_clickpipe(self, c: ClickHouseCreateClickPipeConfig, key_id, key_secret) -> Dict[str, Any]:
        import json as _json

        try:
            definition = _json.loads(c.definition)
        except Exception as e:
            return {
                "status": "error",
                "action": "create_clickpipe",
                "error": f"Invalid ClickPipe definition JSON: {e}",
                "status_code": 400,
            }
        return await _clickhouse_request(
            key_id, key_secret, "POST",
            f"/organizations/{c.organization_id}/clickpipes",
            json_body=definition, action_name="create_clickpipe",
        )

    async def _update_clickpipe_state(self, c: ClickHouseUpdateClickPipeStateConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "PATCH",
            f"/organizations/{c.organization_id}/clickpipes/{c.clickpipe_id}/state",
            json_body={"command": c.command}, action_name="update_clickpipe_state",
        )

    async def _get_clickpipe(self, c: ClickHouseGetClickPipeConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET",
            f"/organizations/{c.organization_id}/clickpipes/{c.clickpipe_id}",
            action_name="get_clickpipe",
        )

    async def _delete_clickpipe(self, c: ClickHouseDeleteClickPipeConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "DELETE",
            f"/organizations/{c.organization_id}/clickpipes/{c.clickpipe_id}",
            action_name="delete_clickpipe",
        )

    # ------------------------------------------------------------------
    # Handlers — API Keys
    # ------------------------------------------------------------------
    async def _list_roles(self, c: ClickHouseListRolesConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET", f"/organizations/{c.organization_id}/roles",
            action_name="list_roles",
        )

    async def _list_keys(self, c: ClickHouseListKeysConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET", f"/organizations/{c.organization_id}/keys",
            action_name="list_keys",
        )

    async def _create_key(self, c: ClickHouseCreateKeyConfig, key_id, key_secret) -> Dict[str, Any]:
        if c.role_ids:
            body: Dict[str, Any] = {"name": c.name, "assignedRoleIds": _comma_list(c.role_ids)}
        else:
            body = {"name": c.name, "roles": [c.role]}
        return await _clickhouse_request(
            key_id, key_secret, "POST", f"/organizations/{c.organization_id}/keys",
            json_body=body, action_name="create_key",
        )

    async def _delete_key(self, c: ClickHouseDeleteKeyConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "DELETE",
            f"/organizations/{c.organization_id}/keys/{c.key_id}",
            action_name="delete_key",
        )

    # ------------------------------------------------------------------
    # Handlers — Members & Invitations
    # ------------------------------------------------------------------
    async def _list_members(self, c: ClickHouseListMembersConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET", f"/organizations/{c.organization_id}/members",
            action_name="list_members",
        )

    async def _remove_member(self, c: ClickHouseRemoveMemberConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "DELETE",
            f"/organizations/{c.organization_id}/members/{c.user_id}",
            action_name="remove_member",
        )

    async def _get_member(self, c: ClickHouseGetMemberConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET",
            f"/organizations/{c.organization_id}/members/{c.user_id}",
            action_name="get_member",
        )

    async def _update_member(self, c: ClickHouseUpdateMemberConfig, key_id, key_secret) -> Dict[str, Any]:
        if c.role_ids:
            body: Dict[str, Any] = {"assignedRoleIds": _comma_list(c.role_ids)}
        else:
            body = {"role": c.role}
        return await _clickhouse_request(
            key_id, key_secret, "PATCH",
            f"/organizations/{c.organization_id}/members/{c.user_id}",
            json_body=body, action_name="update_member",
        )

    async def _list_invitations(self, c: ClickHouseListInvitationsConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET", f"/organizations/{c.organization_id}/invitations",
            action_name="list_invitations",
        )

    async def _create_invitation(self, c: ClickHouseCreateInvitationConfig, key_id, key_secret) -> Dict[str, Any]:
        if c.role_ids:
            body: Dict[str, Any] = {"email": c.email, "assignedRoleIds": _comma_list(c.role_ids)}
        else:
            body = {"email": c.email, "role": c.role}
        return await _clickhouse_request(
            key_id, key_secret, "POST", f"/organizations/{c.organization_id}/invitations",
            json_body=body, action_name="create_invitation",
        )

    async def _delete_invitation(self, c: ClickHouseDeleteInvitationConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "DELETE",
            f"/organizations/{c.organization_id}/invitations/{c.invitation_id}",
            action_name="delete_invitation",
        )

    async def _get_invitation(self, c: ClickHouseGetInvitationConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET",
            f"/organizations/{c.organization_id}/invitations/{c.invitation_id}",
            action_name="get_invitation",
        )

    # ------------------------------------------------------------------
    # Handlers — Metrics
    # ------------------------------------------------------------------
    async def _get_prometheus_metrics(self, c: ClickHouseGetPrometheusMetricsConfig, key_id, key_secret) -> Dict[str, Any]:
        return await _clickhouse_request(
            key_id, key_secret, "GET",
            f"/organizations/{c.organization_id}/services/{c.service_id}/prometheus",
            action_name="get_prometheus_metrics", expect_text=True,
        )
