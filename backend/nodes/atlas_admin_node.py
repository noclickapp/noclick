"""
MongoDB Atlas Admin API automation node.

Provides workflow integration with the MongoDB Atlas Administration API v2 for:
- Clusters: list, get, create, update, delete, pause, resume, failover, advanced config
- Serverless Instances: list, get, create, update, delete
- Flex Clusters: list, get, create, update, delete
- Cloud Backups: schedules, snapshots, restore jobs, export buckets/jobs
- Projects: list, get, create, delete, settings, IP access lists, peering, etc.
- Organizations: list, get, settings, teams, members, invitations
- Database Users: list, get, create, update, delete
- Network / Private Endpoints: peering containers, private endpoints
- Alerts & Alert Configurations: list, get, acknowledge, CRUD configs
- Monitoring & Logs: process metrics, database metrics, disk metrics, log downloads
- Search Indexes: list, get, create, update, delete
- Data Federation: federated database instances
- Auditing, Encryption at Rest, X.509 Auth, LDAP, and more

Authentication: OAuth 2.0 client_credentials using a Service Account (the method
recommended by MongoDB; Programmatic API Keys are the legacy alternative).
Create a Service Account under Access Manager → Service Accounts, assign it
org/project roles, and copy the Client ID and Client Secret.
Tokens are cached in-process and refreshed 5 minutes before expiry.

API Base URL: https://cloud.mongodb.com/api/atlas/v2
Documentation: https://www.mongodb.com/docs/atlas/reference/api-resources-spec/v2/
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any, Dict, List, Literal, Optional, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from nodes.core.poll_trigger import ScheduledPollTriggerMixin, PollTriggerConfigBase
from utils.oauth_token_cache import (
    OAuthTokenCache,
    oauth_authority_digest,
    token_expiry_input,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

ATLAS_BASE_URL = "https://cloud.mongodb.com/api/atlas/v2"
ATLAS_TOKEN_URL = "https://cloud.mongodb.com/api/oauth/token"
ATLAS_API_VERSION = "2023-02-01"

# Newer Atlas endpoints require specific API versions introduced after 2023-02-01.
# Each entry maps an operation name to the minimum version it requires.
OP_VERSION_OVERRIDES: Dict[str, str] = {
    # Flex clusters: GA'd in 2024-11-13
    "list_flex_clusters": "2024-11-13",
    "get_flex_cluster": "2024-11-13",
    "create_flex_cluster": "2024-11-13",
    "update_flex_cluster": "2024-11-13",
    "delete_flex_cluster": "2024-11-13",
    # Atlas Search indexes: moved to dedicated versioned path in 2024-05-30
    "list_search_indexes": "2024-05-30",
    "get_search_index": "2024-05-30",
    "create_search_index": "2024-05-30",
    "update_search_index": "2024-05-30",
    "delete_search_index": "2024-05-30",
    "list_search_index_by_name": "2024-05-30",
    # Service accounts, resource policies, performance advisor: 2024-08-05
    "list_org_service_accounts": "2024-08-05",
    "create_org_service_account": "2024-08-05",
    "get_org_service_account": "2024-08-05",
    "update_org_service_account": "2024-08-05",
    "delete_org_service_account": "2024-08-05",
    "create_service_account_secret": "2024-08-05",
    "delete_service_account_secret": "2024-08-05",
    "list_project_service_accounts": "2024-08-05",
    "add_project_service_account": "2024-08-05",
    "remove_project_service_account": "2024-08-05",
    "list_resource_policies": "2024-08-05",
    "get_resource_policy": "2024-08-05",
    "create_resource_policy": "2024-08-05",
    "update_resource_policy": "2024-08-05",
    "delete_resource_policy": "2024-08-05",
    "validate_resource_policy": "2024-08-05",
    "list_noncompliant_resources": "2024-08-05",
    "list_suggested_indexes": "2024-08-05",
    "list_performance_namespaces": "2024-08-05",
    "get_schema_advice": "2024-08-05",
}

# Event type sets for each decomposed poll trigger operation.
_POLL_EVENT_MAP: Dict[str, set] = {
    "on_cluster_event": {
        "CLUSTER_CREATED", "CLUSTER_DELETED", "CLUSTER_READY",
        "CLUSTER_PAUSED", "CLUSTER_RESUMED", "CLUSTER_MONGOS_IS_MISSING",
    },
    "on_backup_event": {
        "BACKUP_SNAPSHOT_CREATED", "BACKUP_RESTORE_SUCCEEDED",
        "BACKUP_RESTORE_STARTED", "BACKUP_SNAPSHOT_STARTED",
        "BACKUP_AGENT_DOWN", "BACKUP_AGENT_UP",
    },
    "on_maintenance_event": {
        "NDS_MAINTENANCE_START", "NDS_MAINTENANCE_END", "NDS_MAINTENANCE_IN_PROGRESS",
    },
    "on_user_event": {
        "DATABASE_USER_CREATED", "DATABASE_USER_UPDATED", "DATABASE_USER_DELETED",
    },
    "on_alert_event": {
        "ALERT_OPENED", "ALERT_CLOSED", "ALERT_ACKNOWLEDGED",
    },
}

# Refresh 5 minutes before expiry to stay within Atlas token-issuance rate limits.
_TOKEN_REFRESH_SKEW_SECONDS = 300


# =============================================================================
# Token cache: SHA-256(all credential authority) → token with bounded expiry
# =============================================================================

_TOKEN_CACHE = OAuthTokenCache(
    refresh_skew_seconds=_TOKEN_REFRESH_SKEW_SECONDS
)


def _atlas_token_cache_key(client_id: str, client_secret: str) -> str:
    return oauth_authority_digest(
        provider="mongodb-atlas-admin",
        token_url=ATLAS_TOKEN_URL,
        grant_type="client_credentials",
        client_id=client_id,
        client_secret=client_secret,
    )


async def _get_atlas_token(client_id: str, client_secret: str) -> str:
    """Exchange Atlas service-account credentials for a short-lived Bearer token.

    Caches in-process and reuses until the safe pre-expiry refresh boundary.
    Raises RuntimeError on any failure so callers surface a structured error.
    """
    cache_key = _atlas_token_cache_key(client_id, client_secret)
    cached = _TOKEN_CACHE.get(cache_key, now=time.monotonic())
    if cached:
        return cached

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            ATLAS_TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {basic}",
            },
        )

    if response.status_code >= 400:
        try:
            err = response.json()
            message = err.get("error_description") or err.get("error") or str(err)
        except Exception:
            message = response.text
        raise RuntimeError(f"Atlas token request failed ({response.status_code}): {message}")

    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("Atlas token response did not include an access_token")
    _TOKEN_CACHE.put(
        cache_key,
        token,
        expires_in=token_expiry_input(payload),
        now=time.monotonic(),
    )
    return token


# =============================================================================
# Core HTTP helper
# =============================================================================

async def _atlas_request(
    token: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    action_name: str = "request",
    api_version: str = ATLAS_API_VERSION,
) -> Dict[str, Any]:
    """Make an authenticated Atlas v2 request and return a structured result.

    The versioned media type is sent in both Accept and Content-Type so Atlas
    returns the correct resource representation and accepts the request body.
    204 responses and empty bodies are normalised to {"success": True}.
    """
    url = f"{ATLAS_BASE_URL}{endpoint}"
    versioned_type = f"application/vnd.atlas.{api_version}+json"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": versioned_type,
        "Content-Type": versioned_type,
    }

    if isinstance(json_body, dict):
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)

            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = (
                        err.get("detail")
                        or err.get("error")
                        or err.get("errorCode")
                        or str(err)
                    )
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[AtlasAdminNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }

            if response.status_code == 204 or not response.content:
                data: Any = {"success": True}
            else:
                try:
                    data = response.json()
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
            logger.error(f"[AtlasAdminNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# =============================================================================
# Dynamic-options field helpers
# =============================================================================

# Inline "Create new <resource>" builder affordances. Atlas keys projects as
# "groups" (the id the picker stores == the create response id) and clusters by
# name (echoed in the create response).
_FIELD_RESOURCE_TYPE: Dict[str, str] = {
    "cluster_name": "atlas_cluster",
    "project_id": "atlas_project",
    "group_id": "atlas_project",
}


def _dyn(field_name: str, label: str, depends_on: Optional[str] = None) -> Dict[str, Any]:
    """Build an x-dynamic-options block (searchable dropdown + custom paste)."""
    opts: Dict[str, Any] = {
        "field_name": field_name,
        "placeholder": f"Select {label}...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": f"Or paste a {label}",
    }
    if depends_on:
        opts["depends_on"] = depends_on
    extra: Dict[str, Any] = {"x-dynamic-options": opts}
    rt = _FIELD_RESOURCE_TYPE.get(field_name)
    if rt:
        extra["x-resource-type"] = rt
    return extra


def _project_id_field(description: str) -> Any:
    """Standard project_id field with a searchable dynamic-options dropdown."""
    return Field(
        ...,
        title="Project",
        description=description,
        json_schema_extra=_dyn("project_id", "project ID"),
    )


def _org_id_field(description: str) -> Any:
    """Standard org_id field with a searchable dynamic-options dropdown."""
    return Field(
        ...,
        title="Organization",
        description=description,
        json_schema_extra=_dyn("org_id", "organization ID"),
    )


def _cluster_name_field(description: str) -> Any:
    """Cluster name dropdown that depends on a previously selected project_id."""
    return Field(
        ...,
        title="Cluster",
        description=description,
        json_schema_extra=_dyn("cluster_name", "cluster name", depends_on="project_id"),
    )


# =============================================================================
# Credential schema
# =============================================================================

class AtlasAdminCredential(BaseModel):
    """Atlas Service Account credentials (OAuth 2.0 client_credentials — recommended by MongoDB)."""

    credential_type: Literal["atlas_admin_oauth2"] = Field(
        "atlas_admin_oauth2",
        json_schema_extra={"ui:hidden": True},
    )
    client_id: str = Field(
        ...,
        title="Client ID",
        description="Service Account Client ID from Atlas Access Manager → Service Accounts",
    )
    client_secret: str = Field(
        ...,
        title="Client Secret",
        description="Service Account Client Secret (shown once at creation)",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://www.mongodb.com/docs/atlas/configure-api-access/",
            "x-credential-instructions": (
                "Go to Atlas → Access Manager → Service Accounts, create a new service account, "
                "assign it the required org/project roles, then copy the Client ID and the "
                "Client Secret shown at creation time."
            ),
        }
    )


# =============================================================================
# CATEGORY: Clusters
# =============================================================================

class AtlasListClustersConfig(BaseModel):
    """List all clusters in a project."""

    operation: Literal["list_clusters"] = Field(
        "list_clusters",
        json_schema_extra={
            "const": "list_clusters",
            "ui:hidden": True,
            "x-category": "Clusters",
            "x-is-trigger": False,
            "x-display-name": "List Clusters",
        },
        title="List Clusters",
    )
    project_id: str = _project_id_field("The project whose clusters to list")
    page_num: Optional[str] = Field(
        None, title="Page Number", description="1-based page number for pagination"
    )
    items_per_page: Optional[str] = Field(
        None, title="Items Per Page", description="Number of results per page (default 100, max 500)"
    )


class AtlasGetClusterConfig(BaseModel):
    """Get a single cluster by name."""

    operation: Literal["get_cluster"] = Field(
        "get_cluster",
        json_schema_extra={
            "const": "get_cluster",
            "ui:hidden": True,
            "x-category": "Clusters",
            "x-is-trigger": False,
            "x-display-name": "Get Cluster",
        },
        title="Get Cluster",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster to retrieve")


class AtlasCreateClusterConfig(BaseModel):
    """Create a new dedicated cluster."""

    operation: Literal["create_cluster"] = Field(
        "create_cluster",
        json_schema_extra={
            "const": "create_cluster",
            "x-creates-resource": True,
            "x-resource-type": "atlas_cluster",
            "x-resource-id-path": "data.name",
            "ui:hidden": True,
            "x-category": "Clusters",
            "x-is-trigger": False,
            "x-display-name": "Create Cluster",
        },
        title="Create Cluster",
    )
    project_id: str = _project_id_field("The project to create the cluster in")
    cluster_name: str = Field(..., title="Cluster Name", description="Unique name for the new cluster")
    provider: str = Field(
        ...,
        title="Cloud Provider",
        description="Cloud provider to host the cluster",
        json_schema_extra={
            "enum": ["AWS", "GCP", "AZURE"],
            "enumNames": ["Amazon Web Services", "Google Cloud Platform", "Microsoft Azure"],
            "x-enum-searchable": True,
        },
    )
    region_name: str = Field(
        ...,
        title="Region",
        description="Provider region name (e.g. US_EAST_1 for AWS, US_CENTRAL1 for GCP, EASTUS for Azure)",
    )
    instance_size: str = Field(
        "M10",
        title="Instance Size",
        description="Atlas cluster tier",
        json_schema_extra={
            "enum": ["M10", "M20", "M30", "M40", "M50", "M60", "M80", "M140", "M200", "M300", "M400", "M700"],
            "enumNames": ["M10", "M20", "M30", "M40", "M50", "M60", "M80", "M140", "M200", "M300", "M400", "M700"],
            "x-enum-searchable": True,
        },
    )
    mongo_db_major_version: str = Field(
        "8.0",
        title="MongoDB Major Version",
        description="MongoDB major version for the cluster (e.g. 7.0, 8.0)",
    )
    disk_size_gb: Optional[str] = Field(
        None, title="Disk Size (GB)", description="Storage capacity in GB (leave blank to use tier default)"
    )
    backup_enabled: str = Field(
        "false",
        title="Backup Enabled",
        description="Whether to enable continuous cloud backups",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    cluster_type: str = Field(
        "REPLICASET",
        title="Cluster Type",
        description="Cluster topology",
        json_schema_extra={
            "enum": ["REPLICASET", "SHARDED", "GEOSHARDED"],
            "enumNames": ["Replica Set", "Sharded Cluster", "Global Write (Geo-Sharded)"],
            "x-enum-searchable": True,
        },
    )
    replication_factor: str = Field(
        "3",
        title="Replication Factor",
        description="Number of replica set members (3, 5, or 7)",
        json_schema_extra={
            "enum": ["3", "5", "7"],
            "enumNames": ["3 nodes", "5 nodes", "7 nodes"],
            "x-enum-searchable": True,
        },
    )
    termination_protection: str = Field(
        "false",
        title="Termination Protection",
        description="Prevent accidental cluster deletion",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Enabled", "Disabled"],
            "x-enum-searchable": True,
        },
    )


class AtlasUpdateClusterConfig(BaseModel):
    """Update an existing cluster's configuration."""

    operation: Literal["update_cluster"] = Field(
        "update_cluster",
        json_schema_extra={
            "const": "update_cluster",
            "ui:hidden": True,
            "x-category": "Clusters",
            "x-is-trigger": False,
            "x-display-name": "Update Cluster",
        },
        title="Update Cluster",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster to update")
    body_json: str = Field(
        ...,
        title="Update Body (JSON)",
        description="JSON object of cluster fields to update (e.g. {\"diskSizeGB\": 100})",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class AtlasDeleteClusterConfig(BaseModel):
    """Delete a cluster (irreversible)."""

    operation: Literal["delete_cluster"] = Field(
        "delete_cluster",
        json_schema_extra={
            "const": "delete_cluster",
            "ui:hidden": True,
            "x-category": "Clusters",
            "x-is-trigger": False,
            "x-display-name": "Delete Cluster",
        },
        title="Delete Cluster",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster to delete")


class AtlasPauseClusterConfig(BaseModel):
    """Pause a running cluster (stops billing for compute)."""

    operation: Literal["pause_cluster"] = Field(
        "pause_cluster",
        json_schema_extra={
            "const": "pause_cluster",
            "ui:hidden": True,
            "x-category": "Clusters",
            "x-is-trigger": False,
            "x-display-name": "Pause Cluster",
        },
        title="Pause Cluster",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster to pause")


class AtlasResumeClusterConfig(BaseModel):
    """Resume a paused cluster."""

    operation: Literal["resume_cluster"] = Field(
        "resume_cluster",
        json_schema_extra={
            "const": "resume_cluster",
            "ui:hidden": True,
            "x-category": "Clusters",
            "x-is-trigger": False,
            "x-display-name": "Resume Cluster",
        },
        title="Resume Cluster",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster to resume")


class AtlasTestFailoverConfig(BaseModel):
    """Trigger a test failover for a replica-set cluster."""

    operation: Literal["test_failover"] = Field(
        "test_failover",
        json_schema_extra={
            "const": "test_failover",
            "ui:hidden": True,
            "x-category": "Clusters",
            "x-is-trigger": False,
            "x-display-name": "Test Failover",
        },
        title="Test Failover",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster to test failover on")


class AtlasGetClusterAdvancedConfigConfig(BaseModel):
    """Get the advanced configuration options for a cluster."""

    operation: Literal["get_cluster_advanced_config"] = Field(
        "get_cluster_advanced_config",
        json_schema_extra={
            "const": "get_cluster_advanced_config",
            "ui:hidden": True,
            "x-category": "Clusters",
            "x-is-trigger": False,
            "x-display-name": "Get Cluster Advanced Configuration",
        },
        title="Get Cluster Advanced Configuration",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster whose advanced config to retrieve")


class AtlasUpdateClusterAdvancedConfigConfig(BaseModel):
    """Update advanced configuration options for a cluster."""

    operation: Literal["update_cluster_advanced_config"] = Field(
        "update_cluster_advanced_config",
        json_schema_extra={
            "const": "update_cluster_advanced_config",
            "ui:hidden": True,
            "x-category": "Clusters",
            "x-is-trigger": False,
            "x-display-name": "Update Cluster Advanced Configuration",
        },
        title="Update Cluster Advanced Configuration",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster to update")
    body_json: str = Field(
        ...,
        title="Advanced Config Body (JSON)",
        description=(
            "JSON object of advanced configuration fields to set "
            "(e.g. {\"oplogSizeMB\": 2048, \"javascriptEnabled\": false})"
        ),
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


# =============================================================================
# CATEGORY: Serverless Instances
# =============================================================================

class AtlasListServerlessConfig(BaseModel):
    """List all serverless instances in a project."""

    operation: Literal["list_serverless"] = Field(
        "list_serverless",
        json_schema_extra={
            "const": "list_serverless",
            "ui:hidden": True,
            "x-category": "Serverless Instances",
            "x-is-trigger": False,
            "x-display-name": "List Serverless Instances",
        },
        title="List Serverless Instances",
    )
    project_id: str = _project_id_field("The project whose serverless instances to list")


class AtlasGetServerlessConfig(BaseModel):
    """Get a single serverless instance by name."""

    operation: Literal["get_serverless"] = Field(
        "get_serverless",
        json_schema_extra={
            "const": "get_serverless",
            "ui:hidden": True,
            "x-category": "Serverless Instances",
            "x-is-trigger": False,
            "x-display-name": "Get Serverless Instance",
        },
        title="Get Serverless Instance",
    )
    project_id: str = _project_id_field("The project containing the serverless instance")
    serverless_name: str = Field(
        ...,
        title="Instance Name",
        description="Name of the serverless instance",
        json_schema_extra=_dyn("serverless_name", "instance name", depends_on="project_id"),
    )


class AtlasCreateServerlessConfig(BaseModel):
    """Create a new serverless instance."""

    operation: Literal["create_serverless"] = Field(
        "create_serverless",
        json_schema_extra={
            "const": "create_serverless",
            "ui:hidden": True,
            "x-category": "Serverless Instances",
            "x-is-trigger": False,
            "x-display-name": "Create Serverless Instance",
        },
        title="Create Serverless Instance",
    )
    project_id: str = _project_id_field("The project to create the serverless instance in")
    serverless_name: str = Field(..., title="Instance Name", description="Unique name for the new serverless instance")
    provider: str = Field(
        ...,
        title="Cloud Provider",
        description="Cloud provider to host the serverless instance",
        json_schema_extra={
            "enum": ["AWS", "GCP", "AZURE"],
            "enumNames": ["Amazon Web Services", "Google Cloud Platform", "Microsoft Azure"],
            "x-enum-searchable": True,
        },
    )
    region_name: str = Field(
        ...,
        title="Region",
        description="Provider region name (e.g. US_EAST_1 for AWS)",
    )
    backup_enabled: str = Field(
        "false",
        title="Backup Enabled",
        description="Whether to enable serverless continuous backups",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class AtlasUpdateServerlessConfig(BaseModel):
    """Update a serverless instance."""

    operation: Literal["update_serverless"] = Field(
        "update_serverless",
        json_schema_extra={
            "const": "update_serverless",
            "ui:hidden": True,
            "x-category": "Serverless Instances",
            "x-is-trigger": False,
            "x-display-name": "Update Serverless Instance",
        },
        title="Update Serverless Instance",
    )
    project_id: str = _project_id_field("The project containing the serverless instance")
    serverless_name: str = Field(
        ...,
        title="Instance Name",
        description="Name of the serverless instance to update",
        json_schema_extra=_dyn("serverless_name", "instance name", depends_on="project_id"),
    )
    termination_protection: str = Field(
        "false",
        title="Termination Protection",
        description="Prevent accidental instance deletion",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Enabled", "Disabled"],
            "x-enum-searchable": True,
        },
    )
    backup_enabled: str = Field(
        "false",
        title="Backup Enabled",
        description="Whether to enable serverless continuous backups",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class AtlasDeleteServerlessConfig(BaseModel):
    """Delete a serverless instance (irreversible)."""

    operation: Literal["delete_serverless"] = Field(
        "delete_serverless",
        json_schema_extra={
            "const": "delete_serverless",
            "ui:hidden": True,
            "x-category": "Serverless Instances",
            "x-is-trigger": False,
            "x-display-name": "Delete Serverless Instance",
        },
        title="Delete Serverless Instance",
    )
    project_id: str = _project_id_field("The project containing the serverless instance")
    serverless_name: str = Field(
        ...,
        title="Instance Name",
        description="Name of the serverless instance to delete",
        json_schema_extra=_dyn("serverless_name", "instance name", depends_on="project_id"),
    )


# =============================================================================
# CATEGORY: Flex Clusters
# =============================================================================

class AtlasListFlexClustersConfig(BaseModel):
    """List all flex clusters in a project."""

    operation: Literal["list_flex_clusters"] = Field(
        "list_flex_clusters",
        json_schema_extra={
            "const": "list_flex_clusters",
            "ui:hidden": True,
            "x-category": "Flex Clusters",
            "x-is-trigger": False,
            "x-display-name": "List Flex Clusters",
        },
        title="List Flex Clusters",
    )
    project_id: str = _project_id_field("The project whose flex clusters to list")


class AtlasGetFlexClusterConfig(BaseModel):
    """Get a single flex cluster by name."""

    operation: Literal["get_flex_cluster"] = Field(
        "get_flex_cluster",
        json_schema_extra={
            "const": "get_flex_cluster",
            "ui:hidden": True,
            "x-category": "Flex Clusters",
            "x-is-trigger": False,
            "x-display-name": "Get Flex Cluster",
        },
        title="Get Flex Cluster",
    )
    project_id: str = _project_id_field("The project containing the flex cluster")
    cluster_name: str = _cluster_name_field("The flex cluster to retrieve")


class AtlasCreateFlexClusterConfig(BaseModel):
    """Create a new flex cluster."""

    operation: Literal["create_flex_cluster"] = Field(
        "create_flex_cluster",
        json_schema_extra={
            "const": "create_flex_cluster",
            "ui:hidden": True,
            "x-category": "Flex Clusters",
            "x-is-trigger": False,
            "x-display-name": "Create Flex Cluster",
        },
        title="Create Flex Cluster",
    )
    project_id: str = _project_id_field("The project to create the flex cluster in")
    cluster_name: str = Field(..., title="Cluster Name", description="Unique name for the new flex cluster")
    provider: str = Field(
        ...,
        title="Cloud Provider",
        description="Cloud provider for the flex cluster",
        json_schema_extra={
            "enum": ["AWS", "GCP", "AZURE"],
            "enumNames": ["Amazon Web Services", "Google Cloud Platform", "Microsoft Azure"],
            "x-enum-searchable": True,
        },
    )
    region_name: str = Field(
        ...,
        title="Region",
        description="Provider region name (e.g. US_EAST_1 for AWS)",
    )
    backing_provider: str = Field(
        ...,
        title="Backing Provider",
        description="Underlying cloud provider that hosts the flex cluster hardware",
        json_schema_extra={
            "enum": ["AWS", "GCP", "AZURE"],
            "enumNames": ["Amazon Web Services", "Google Cloud Platform", "Microsoft Azure"],
            "x-enum-searchable": True,
        },
    )


class AtlasUpdateFlexClusterConfig(BaseModel):
    """Update a flex cluster's configuration."""

    operation: Literal["update_flex_cluster"] = Field(
        "update_flex_cluster",
        json_schema_extra={
            "const": "update_flex_cluster",
            "ui:hidden": True,
            "x-category": "Flex Clusters",
            "x-is-trigger": False,
            "x-display-name": "Update Flex Cluster",
        },
        title="Update Flex Cluster",
    )
    project_id: str = _project_id_field("The project containing the flex cluster")
    cluster_name: str = _cluster_name_field("The flex cluster to update")
    body_json: str = Field(
        ...,
        title="Update Body (JSON)",
        description="JSON object of flex cluster fields to update",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class AtlasDeleteFlexClusterConfig(BaseModel):
    """Delete a flex cluster (irreversible)."""

    operation: Literal["delete_flex_cluster"] = Field(
        "delete_flex_cluster",
        json_schema_extra={
            "const": "delete_flex_cluster",
            "ui:hidden": True,
            "x-category": "Flex Clusters",
            "x-is-trigger": False,
            "x-display-name": "Delete Flex Cluster",
        },
        title="Delete Flex Cluster",
    )
    project_id: str = _project_id_field("The project containing the flex cluster")
    cluster_name: str = _cluster_name_field("The flex cluster to delete")


# =============================================================================
# CATEGORY: Cloud Backups
# =============================================================================

class AtlasGetBackupScheduleConfig(BaseModel):
    """Get the cloud backup schedule for a cluster."""

    operation: Literal["get_backup_schedule"] = Field(
        "get_backup_schedule",
        json_schema_extra={
            "const": "get_backup_schedule",
            "ui:hidden": True,
            "x-category": "Cloud Backups",
            "x-is-trigger": False,
            "x-display-name": "Get Backup Schedule",
        },
        title="Get Backup Schedule",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster whose backup schedule to retrieve")


class AtlasUpdateBackupScheduleConfig(BaseModel):
    """Update the cloud backup schedule for a cluster."""

    operation: Literal["update_backup_schedule"] = Field(
        "update_backup_schedule",
        json_schema_extra={
            "const": "update_backup_schedule",
            "ui:hidden": True,
            "x-category": "Cloud Backups",
            "x-is-trigger": False,
            "x-display-name": "Update Backup Schedule",
        },
        title="Update Backup Schedule",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster whose backup schedule to update")
    frequency_type: str = Field(
        ...,
        title="Frequency Type",
        description="Backup frequency period",
        json_schema_extra={
            "enum": ["HOURLY", "DAILY", "WEEKLY", "MONTHLY"],
            "enumNames": ["Hourly", "Daily", "Weekly", "Monthly"],
            "x-enum-searchable": True,
        },
    )
    frequency_interval: str = Field(
        ...,
        title="Frequency Interval",
        description="How often within the frequency type (e.g. 6 for every 6 hours)",
    )
    retention_value: str = Field(
        ...,
        title="Retention Value",
        description="Number of retention units to keep backups",
    )
    retention_unit: str = Field(
        ...,
        title="Retention Unit",
        description="Unit of time for the retention value",
        json_schema_extra={
            "enum": ["DAYS", "WEEKS", "MONTHS"],
            "enumNames": ["Days", "Weeks", "Months"],
            "x-enum-searchable": True,
        },
    )
    reference_hour_of_day: Optional[str] = Field(
        None,
        title="Reference Hour of Day",
        description="UTC hour (0–23) when Atlas takes a snapshot (required for WEEKLY/MONTHLY)",
    )
    reference_minute_of_hour: Optional[str] = Field(
        None,
        title="Reference Minute of Hour",
        description="UTC minute (0–59) when Atlas takes a snapshot",
    )


class AtlasListSnapshotsConfig(BaseModel):
    """List cloud backup snapshots for a cluster."""

    operation: Literal["list_snapshots"] = Field(
        "list_snapshots",
        json_schema_extra={
            "const": "list_snapshots",
            "ui:hidden": True,
            "x-category": "Cloud Backups",
            "x-is-trigger": False,
            "x-display-name": "List Snapshots",
        },
        title="List Snapshots",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster whose snapshots to list")
    page_num: Optional[str] = Field(None, title="Page Number", description="1-based page number")
    items_per_page: Optional[str] = Field(None, title="Items Per Page", description="Results per page (default 100)")


class AtlasGetSnapshotConfig(BaseModel):
    """Get a single cloud backup snapshot."""

    operation: Literal["get_snapshot"] = Field(
        "get_snapshot",
        json_schema_extra={
            "const": "get_snapshot",
            "ui:hidden": True,
            "x-category": "Cloud Backups",
            "x-is-trigger": False,
            "x-display-name": "Get Snapshot",
        },
        title="Get Snapshot",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster the snapshot belongs to")
    snapshot_id: str = Field(..., title="Snapshot ID", description="Unique identifier of the snapshot")


class AtlasTakeSnapshotConfig(BaseModel):
    """Take an on-demand cloud backup snapshot."""

    operation: Literal["take_snapshot"] = Field(
        "take_snapshot",
        json_schema_extra={
            "const": "take_snapshot",
            "ui:hidden": True,
            "x-category": "Cloud Backups",
            "x-is-trigger": False,
            "x-display-name": "Take On-Demand Snapshot",
        },
        title="Take On-Demand Snapshot",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster to snapshot")
    description: str = Field(..., title="Description", description="Human-readable description of the snapshot")
    retention_in_days: str = Field(
        ...,
        title="Retention (Days)",
        description="Number of days to retain this on-demand snapshot",
    )


class AtlasDeleteSnapshotConfig(BaseModel):
    """Delete a cloud backup snapshot."""

    operation: Literal["delete_snapshot"] = Field(
        "delete_snapshot",
        json_schema_extra={
            "const": "delete_snapshot",
            "ui:hidden": True,
            "x-category": "Cloud Backups",
            "x-is-trigger": False,
            "x-display-name": "Delete Snapshot",
        },
        title="Delete Snapshot",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster the snapshot belongs to")
    snapshot_id: str = Field(..., title="Snapshot ID", description="Unique identifier of the snapshot to delete")


class AtlasListRestoreJobsConfig(BaseModel):
    """List cloud backup restore jobs for a cluster."""

    operation: Literal["list_restore_jobs"] = Field(
        "list_restore_jobs",
        json_schema_extra={
            "const": "list_restore_jobs",
            "ui:hidden": True,
            "x-category": "Cloud Backups",
            "x-is-trigger": False,
            "x-display-name": "List Restore Jobs",
        },
        title="List Restore Jobs",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster whose restore jobs to list")


class AtlasGetRestoreJobConfig(BaseModel):
    """Get a single cloud backup restore job."""

    operation: Literal["get_restore_job"] = Field(
        "get_restore_job",
        json_schema_extra={
            "const": "get_restore_job",
            "ui:hidden": True,
            "x-category": "Cloud Backups",
            "x-is-trigger": False,
            "x-display-name": "Get Restore Job",
        },
        title="Get Restore Job",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster the restore job targets")
    restore_job_id: str = Field(..., title="Restore Job ID", description="Unique identifier of the restore job")


class AtlasCreateRestoreJobConfig(BaseModel):
    """Create a cloud backup restore job."""

    operation: Literal["create_restore_job"] = Field(
        "create_restore_job",
        json_schema_extra={
            "const": "create_restore_job",
            "ui:hidden": True,
            "x-category": "Cloud Backups",
            "x-is-trigger": False,
            "x-display-name": "Create Restore Job",
        },
        title="Create Restore Job",
    )
    project_id: str = _project_id_field("The project containing the source cluster")
    cluster_name: str = _cluster_name_field("The source cluster to restore from")
    delivery_type: str = Field(
        ...,
        title="Delivery Type",
        description="How to deliver the restored data",
        json_schema_extra={
            "enum": ["AUTOMATED", "DOWNLOAD", "POINT_IN_TIME"],
            "enumNames": ["Automated (restore to cluster)", "Download (generate link)", "Point in Time"],
            "x-enum-searchable": True,
        },
    )
    target_cluster_name: Optional[str] = Field(
        None,
        title="Target Cluster Name",
        description="Name of the cluster to restore into (required for AUTOMATED delivery)",
    )
    target_project_id: Optional[str] = Field(
        None,
        title="Target Project ID",
        description="Project ID containing the target cluster (defaults to source project)",
    )
    oplog_ts: Optional[str] = Field(
        None,
        title="Oplog Timestamp",
        description="BSON timestamp for oplog-based point-in-time restore (Unix seconds as string)",
    )
    point_in_time_utc_seconds: Optional[str] = Field(
        None,
        title="Point-in-Time (UTC seconds)",
        description="Unix epoch seconds for POINT_IN_TIME delivery type",
    )
    snapshot_id: Optional[str] = Field(
        None,
        title="Snapshot ID",
        description="ID of the snapshot to restore (required for AUTOMATED/DOWNLOAD from a specific snapshot)",
    )


class AtlasCancelRestoreJobConfig(BaseModel):
    """Cancel an in-progress cloud backup restore job."""

    operation: Literal["cancel_restore_job"] = Field(
        "cancel_restore_job",
        json_schema_extra={
            "const": "cancel_restore_job",
            "ui:hidden": True,
            "x-category": "Cloud Backups",
            "x-is-trigger": False,
            "x-display-name": "Cancel Restore Job",
        },
        title="Cancel Restore Job",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster the restore job targets")
    restore_job_id: str = Field(..., title="Restore Job ID", description="Unique identifier of the restore job to cancel")


class AtlasListExportBucketsConfig(BaseModel):
    """List export buckets associated with a project."""

    operation: Literal["list_export_buckets"] = Field(
        "list_export_buckets",
        json_schema_extra={
            "const": "list_export_buckets",
            "ui:hidden": True,
            "x-category": "Cloud Backups",
            "x-is-trigger": False,
            "x-display-name": "List Export Buckets",
        },
        title="List Export Buckets",
    )
    project_id: str = _project_id_field("The project whose export buckets to list")


class AtlasCreateExportJobConfig(BaseModel):
    """Create a cloud backup snapshot export job to an S3 bucket."""

    operation: Literal["create_export_job"] = Field(
        "create_export_job",
        json_schema_extra={
            "const": "create_export_job",
            "ui:hidden": True,
            "x-category": "Cloud Backups",
            "x-is-trigger": False,
            "x-display-name": "Create Export Job",
        },
        title="Create Export Job",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster whose snapshot to export")
    export_bucket_id: str = Field(
        ...,
        title="Export Bucket ID",
        description="ID of the registered export bucket to export the snapshot into",
        json_schema_extra=_dyn("export_bucket_id", "export bucket ID", depends_on="project_id"),
    )
    custom_data: Optional[str] = Field(
        None,
        title="Custom Data (JSON)",
        description=(
            "Optional JSON array of key/value pairs attached to the export "
            "(e.g. [{\"key\": \"env\", \"value\": \"prod\"}])"
        ),
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


# =============================================================================
# Shared body/param helpers for execute()
# =============================================================================

def _pj(value: Any) -> Any:
    """Parse a JSON-string config field into a Python object.

    Returns None for empty, the parsed value for valid JSON, or the raw string
    if it isn't JSON (so a plain value still round-trips).
    """
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _pg(c: Any) -> Dict[str, Any]:
    """Build Atlas pagination query params from a config's page fields."""
    params: Dict[str, Any] = {}
    pn = getattr(c, "page_num", None)
    ipp = getattr(c, "items_per_page", None)
    if pn:
        params["pageNum"] = pn
    if ipp:
        params["itemsPerPage"] = ipp
    return params


def _tf(value: Any) -> bool:
    """Coerce the string-enum ("true"/"false") boolean convention to bool."""
    return value == "true" or value is True


# =============================================================================
# CATEGORY: Database Users (Section A)
# =============================================================================

class AtlasListDbUsersConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_db_users"] = Field("list_db_users", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    auth_db_name: Optional[str] = Field(None, title="Auth Database", json_schema_extra={"enum": ["admin", "$external", "default"], "x-enum-searchable": True})
    page_num: int = Field(1, title="Page", description="Page number (1-indexed)")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasGetDbUserConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_db_user"] = Field("get_db_user", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    database_name: str = Field("", title="Database Name")
    username: str = Field("", title="Username")


class AtlasCreateDbUserConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_db_user"] = Field("create_db_user", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    username: str = Field("", title="Username")
    password: str = Field("", title="Password")
    database_name: str = Field("admin", title="Database Name")
    aws_iam_type: Optional[str] = Field(None, title="AWS IAM Type", json_schema_extra={"enum": ["NONE", "USER", "ROLE"], "x-enum-searchable": True})
    x509_type: Optional[str] = Field(None, title="X.509 Type", json_schema_extra={"enum": ["NONE", "CUSTOMER", "MANAGED"], "x-enum-searchable": True})
    ldap_auth_type: Optional[str] = Field(None, title="LDAP Auth Type", json_schema_extra={"enum": ["NONE", "USER", "GROUP"], "x-enum-searchable": True})
    roles: Optional[str] = Field(None, title="Roles", description="JSON array of role objects e.g. [{\"roleName\":\"readWrite\",\"databaseName\":\"mydb\"}]", json_schema_extra={"ui:widget": "code_editor"})
    scopes: Optional[str] = Field(None, title="Scopes", description="JSON array of scope objects e.g. [{\"name\":\"myCluster\",\"type\":\"CLUSTER\"}]", json_schema_extra={"ui:widget": "code_editor"})
    labels: Optional[str] = Field(None, title="Labels", description="JSON array of label objects e.g. [{\"key\":\"env\",\"value\":\"prod\"}]", json_schema_extra={"ui:widget": "code_editor"})


class AtlasUpdateDbUserConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["update_db_user"] = Field("update_db_user", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    database_name: str = Field("", title="Database Name")
    username: str = Field("", title="Username")
    password: Optional[str] = Field(None, title="Password")
    roles: Optional[str] = Field(None, title="Roles", description="JSON array of role objects e.g. [{\"roleName\":\"readWrite\",\"databaseName\":\"mydb\"}]", json_schema_extra={"ui:widget": "code_editor"})
    scopes: Optional[str] = Field(None, title="Scopes", description="JSON array of scope objects e.g. [{\"name\":\"myCluster\",\"type\":\"CLUSTER\"}]", json_schema_extra={"ui:widget": "code_editor"})


class AtlasDeleteDbUserConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_db_user"] = Field("delete_db_user", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    database_name: str = Field("", title="Database Name")
    username: str = Field("", title="Username")


class AtlasListDbUserCertsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_db_user_certs"] = Field("list_db_user_certs", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    username: str = Field("", title="Username")


class AtlasCreateDbUserCertConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_db_user_cert"] = Field("create_db_user_cert", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    username: str = Field("", title="Username")
    months_until_expiration: int = Field(12, title="Months Until Expiration")


# =============================================================================
# CATEGORY: IP Access List (Section A)
# =============================================================================

class AtlasListAccessListConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_access_list"] = Field("list_access_list", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    page_num: int = Field(1, title="Page", description="Page number (1-indexed)")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasAddAccessListConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["add_access_list"] = Field("add_access_list", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    entries: str = Field("", title="Entries", description='JSON array of access list entries e.g. [{"ipAddress":"1.2.3.4","comment":"desc"} or {"cidrBlock":"1.2.3.0/24"} or {"awsSecurityGroup":"sg-xxx"}]', json_schema_extra={"ui:widget": "code_editor"})


class AtlasGetAccessListEntryConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_access_list_entry"] = Field("get_access_list_entry", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    entry_value: str = Field("", title="Entry Value", description="IP address, CIDR block, or AWS security group ID")


class AtlasDeleteAccessListEntryConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_access_list_entry"] = Field("delete_access_list_entry", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    entry_value: str = Field("", title="Entry Value", description="IP address, CIDR block, or AWS security group ID")


# =============================================================================
# CATEGORY: Network Peering (Section A)
# =============================================================================

class AtlasListPeeringContainersConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_peering_containers"] = Field("list_peering_containers", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    provider_name: Optional[str] = Field(None, title="Cloud Provider", json_schema_extra={"enum": ["AWS", "AZURE", "GCP"], "x-enum-searchable": True})
    page_num: int = Field(1, title="Page", description="Page number (1-indexed)")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasGetPeeringContainerConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_peering_container"] = Field("get_peering_container", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    container_id: str = Field("", title="Container ID", json_schema_extra=_dyn("container_id", "peering container", depends_on="group_id"))


class AtlasCreatePeeringContainerConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_peering_container"] = Field("create_peering_container", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    provider_name: str = Field("", title="Cloud Provider", json_schema_extra={"enum": ["AWS", "AZURE", "GCP"], "x-enum-searchable": True})
    atlas_cidr_block: str = Field("", title="Atlas CIDR Block")
    region_name: str = Field("", title="Region Name")


class AtlasUpdatePeeringContainerConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["update_peering_container"] = Field("update_peering_container", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    container_id: str = Field("", title="Container ID", json_schema_extra=_dyn("container_id", "peering container", depends_on="group_id"))
    atlas_cidr_block: str = Field("", title="Atlas CIDR Block")


class AtlasDeletePeeringContainerConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_peering_container"] = Field("delete_peering_container", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    container_id: str = Field("", title="Container ID", json_schema_extra=_dyn("container_id", "peering container", depends_on="group_id"))


class AtlasListPeeringConnectionsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_peering_connections"] = Field("list_peering_connections", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    provider_name: Optional[str] = Field(None, title="Cloud Provider", json_schema_extra={"enum": ["AWS", "AZURE", "GCP"], "x-enum-searchable": True})
    page_num: int = Field(1, title="Page", description="Page number (1-indexed)")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasGetPeeringConnectionConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_peering_connection"] = Field("get_peering_connection", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    peer_id: str = Field("", title="Peer ID")


class AtlasCreatePeeringConnectionConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_peering_connection"] = Field("create_peering_connection", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    provider_name: str = Field("", title="Cloud Provider", json_schema_extra={"enum": ["AWS", "AZURE", "GCP"], "x-enum-searchable": True})
    container_id: str = Field("", title="Container ID", json_schema_extra=_dyn("container_id", "peering container", depends_on="group_id"))
    peering_body: str = Field("", title="Peering Connection Body", description='Full peering connection body JSON. For AWS: {"vpcId","awsAccountId","routeTableCidrBlock"}. For Azure: {"vnetName","azureSubscriptionId","resourceGroupName","adTenantId"}. For GCP: {"networkName","gcpProjectId"}', json_schema_extra={"ui:widget": "code_editor"})


class AtlasUpdatePeeringConnectionConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["update_peering_connection"] = Field("update_peering_connection", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    peer_id: str = Field("", title="Peer ID")
    route_table_cidr_block: str = Field("", title="Route Table CIDR Block")


class AtlasDeletePeeringConnectionConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_peering_connection"] = Field("delete_peering_connection", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    peer_id: str = Field("", title="Peer ID")


# =============================================================================
# CATEGORY: Private Endpoints (Section A)
# =============================================================================

class AtlasListPrivateEndpointServicesConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_private_endpoint_services"] = Field("list_private_endpoint_services", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cloud_provider: str = Field("", title="Cloud Provider", json_schema_extra={"enum": ["AWS", "AZURE", "GCP"], "x-enum-searchable": True})
    page_num: int = Field(1, title="Page", description="Page number (1-indexed)")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasCreatePrivateEndpointServiceConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_private_endpoint_service"] = Field("create_private_endpoint_service", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cloud_provider: str = Field("", title="Cloud Provider", json_schema_extra={"enum": ["AWS", "AZURE", "GCP"], "x-enum-searchable": True})
    region: str = Field("", title="Region")


class AtlasGetPrivateEndpointServiceConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_private_endpoint_service"] = Field("get_private_endpoint_service", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cloud_provider: str = Field("", title="Cloud Provider", json_schema_extra={"enum": ["AWS", "AZURE", "GCP"], "x-enum-searchable": True})
    endpoint_service_id: str = Field("", title="Endpoint Service ID")


class AtlasDeletePrivateEndpointServiceConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_private_endpoint_service"] = Field("delete_private_endpoint_service", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cloud_provider: str = Field("", title="Cloud Provider", json_schema_extra={"enum": ["AWS", "AZURE", "GCP"], "x-enum-searchable": True})
    endpoint_service_id: str = Field("", title="Endpoint Service ID")


class AtlasListPrivateEndpointsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_private_endpoints"] = Field("list_private_endpoints", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cloud_provider: str = Field("", title="Cloud Provider", json_schema_extra={"enum": ["AWS", "AZURE", "GCP"], "x-enum-searchable": True})
    endpoint_service_id: str = Field("", title="Endpoint Service ID")


class AtlasCreatePrivateEndpointConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_private_endpoint"] = Field("create_private_endpoint", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cloud_provider: str = Field("", title="Cloud Provider", json_schema_extra={"enum": ["AWS", "AZURE", "GCP"], "x-enum-searchable": True})
    endpoint_service_id: str = Field("", title="Endpoint Service ID")
    endpoint_body: str = Field("", title="Endpoint Body", description='AWS: {"id": "VPC endpoint ID"}, Azure: {"privateEndpointIPAddress": "..."}', json_schema_extra={"ui:widget": "code_editor"})


class AtlasGetPrivateEndpointConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_private_endpoint"] = Field("get_private_endpoint", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cloud_provider: str = Field("", title="Cloud Provider", json_schema_extra={"enum": ["AWS", "AZURE", "GCP"], "x-enum-searchable": True})
    endpoint_service_id: str = Field("", title="Endpoint Service ID")
    endpoint_id: str = Field("", title="Endpoint ID")


class AtlasDeletePrivateEndpointConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_private_endpoint"] = Field("delete_private_endpoint", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cloud_provider: str = Field("", title="Cloud Provider", json_schema_extra={"enum": ["AWS", "AZURE", "GCP"], "x-enum-searchable": True})
    endpoint_service_id: str = Field("", title="Endpoint Service ID")
    endpoint_id: str = Field("", title="Endpoint ID")


class AtlasGetRegionalizedPrivateEndpointConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_regionalized_private_endpoint"] = Field("get_regionalized_private_endpoint", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))


class AtlasToggleRegionalizedPrivateEndpointConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["toggle_regionalized_private_endpoint"] = Field("toggle_regionalized_private_endpoint", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field("", title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    enabled: str = Field("", title="Enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


# =============================================================================
# SECTION B: Search / Online Archive / Streams / Data Federation
# =============================================================================
# =============================================================================
# CATEGORY: Search Indexes
# =============================================================================

class AtlasListSearchIndexesConfig(BaseModel):
    """List all Atlas Search indexes for a collection."""

    operation: Literal["list_search_indexes"] = Field(
        "list_search_indexes",
        json_schema_extra={
            "const": "list_search_indexes",
            "ui:hidden": True,
            "x-category": "Search Indexes",
            "x-is-trigger": False,
            "x-display-name": "List Search Indexes",
        },
        title="List Search Indexes",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster containing the collection")
    database_name: str = Field(..., title="Database Name", description="Name of the database")
    collection_name: str = Field(..., title="Collection Name", description="Name of the collection")
    index_type: Optional[str] = Field(
        None,
        title="Index Type",
        description="Filter by index type",
        json_schema_extra={
            "enum": ["search", "vectorSearch"],
            "enumNames": ["Search", "Vector Search"],
            "x-enum-searchable": True,
        },
    )


class AtlasGetSearchIndexConfig(BaseModel):
    """Get a single Atlas Search index by ID."""

    operation: Literal["get_search_index"] = Field(
        "get_search_index",
        json_schema_extra={
            "const": "get_search_index",
            "ui:hidden": True,
            "x-category": "Search Indexes",
            "x-is-trigger": False,
            "x-display-name": "Get Search Index",
        },
        title="Get Search Index",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster containing the index")
    index_id: str = Field(..., title="Index ID", description="Unique identifier of the search index")


class AtlasCreateSearchIndexConfig(BaseModel):
    """Create a new Atlas Search or Vector Search index."""

    operation: Literal["create_search_index"] = Field(
        "create_search_index",
        json_schema_extra={
            "const": "create_search_index",
            "ui:hidden": True,
            "x-category": "Search Indexes",
            "x-is-trigger": False,
            "x-display-name": "Create Search Index",
        },
        title="Create Search Index",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster to create the index on")
    index_definition: str = Field(
        ...,
        title="Index Definition (JSON)",
        description="Full search index definition JSON including name, database, collectionName, mappings/type etc.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class AtlasUpdateSearchIndexConfig(BaseModel):
    """Update an existing Atlas Search index."""

    operation: Literal["update_search_index"] = Field(
        "update_search_index",
        json_schema_extra={
            "const": "update_search_index",
            "ui:hidden": True,
            "x-category": "Search Indexes",
            "x-is-trigger": False,
            "x-display-name": "Update Search Index",
        },
        title="Update Search Index",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster containing the index")
    index_id: str = Field(..., title="Index ID", description="Unique identifier of the search index to update")
    index_definition: str = Field(
        ...,
        title="Index Definition (JSON)",
        description="Updated search index definition JSON",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class AtlasDeleteSearchIndexConfig(BaseModel):
    """Delete an Atlas Search index by ID."""

    operation: Literal["delete_search_index"] = Field(
        "delete_search_index",
        json_schema_extra={
            "const": "delete_search_index",
            "ui:hidden": True,
            "x-category": "Search Indexes",
            "x-is-trigger": False,
            "x-display-name": "Delete Search Index",
        },
        title="Delete Search Index",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster containing the index")
    index_id: str = Field(..., title="Index ID", description="Unique identifier of the search index to delete")


class AtlasListSearchIndexByNameConfig(BaseModel):
    """Get an Atlas Search index by collection and index name."""

    operation: Literal["list_search_index_by_name"] = Field(
        "list_search_index_by_name",
        json_schema_extra={
            "const": "list_search_index_by_name",
            "ui:hidden": True,
            "x-category": "Search Indexes",
            "x-is-trigger": False,
            "x-display-name": "Get Search Index by Name",
        },
        title="Get Search Index by Name",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster containing the collection")
    database_name: str = Field(..., title="Database Name", description="Name of the database")
    collection_name: str = Field(..., title="Collection Name", description="Name of the collection")
    index_name: str = Field(..., title="Index Name", description="Name of the search index")


class AtlasGetSearchDeploymentConfig(BaseModel):
    """Get the Atlas Search deployment configuration for a cluster."""

    operation: Literal["get_search_deployment"] = Field(
        "get_search_deployment",
        json_schema_extra={
            "const": "get_search_deployment",
            "ui:hidden": True,
            "x-category": "Search Indexes",
            "x-is-trigger": False,
            "x-display-name": "Get Search Deployment",
        },
        title="Get Search Deployment",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster whose search deployment to retrieve")


class AtlasCreateSearchDeploymentConfig(BaseModel):
    """Create a dedicated Atlas Search deployment for a cluster."""

    operation: Literal["create_search_deployment"] = Field(
        "create_search_deployment",
        json_schema_extra={
            "const": "create_search_deployment",
            "ui:hidden": True,
            "x-category": "Search Indexes",
            "x-is-trigger": False,
            "x-display-name": "Create Search Deployment",
        },
        title="Create Search Deployment",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster to create the search deployment for")
    specs: str = Field(
        ...,
        title="Specs (JSON Array)",
        description="Array of {instanceSize, nodeCount} objects",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class AtlasUpdateSearchDeploymentConfig(BaseModel):
    """Update the dedicated Atlas Search deployment for a cluster."""

    operation: Literal["update_search_deployment"] = Field(
        "update_search_deployment",
        json_schema_extra={
            "const": "update_search_deployment",
            "ui:hidden": True,
            "x-category": "Search Indexes",
            "x-is-trigger": False,
            "x-display-name": "Update Search Deployment",
        },
        title="Update Search Deployment",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster whose search deployment to update")
    specs: str = Field(
        ...,
        title="Specs (JSON Array)",
        description="Updated array of {instanceSize, nodeCount} objects",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class AtlasDeleteSearchDeploymentConfig(BaseModel):
    """Delete the dedicated Atlas Search deployment for a cluster."""

    operation: Literal["delete_search_deployment"] = Field(
        "delete_search_deployment",
        json_schema_extra={
            "const": "delete_search_deployment",
            "ui:hidden": True,
            "x-category": "Search Indexes",
            "x-is-trigger": False,
            "x-display-name": "Delete Search Deployment",
        },
        title="Delete Search Deployment",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster whose search deployment to delete")


class AtlasListSearchAnalyzersConfig(BaseModel):
    """List all custom Atlas Search analyzers for a cluster."""

    operation: Literal["list_search_analyzers"] = Field(
        "list_search_analyzers",
        json_schema_extra={
            "const": "list_search_analyzers",
            "ui:hidden": True,
            "x-category": "Search Indexes",
            "x-is-trigger": False,
            "x-display-name": "List Search Analyzers",
        },
        title="List Search Analyzers",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster whose search analyzers to list")


# =============================================================================
# CATEGORY: Online Archive
# =============================================================================

class AtlasListOnlineArchivesConfig(BaseModel):
    """List all online archives for a cluster."""

    operation: Literal["list_online_archives"] = Field(
        "list_online_archives",
        json_schema_extra={
            "const": "list_online_archives",
            "ui:hidden": True,
            "x-category": "Online Archive",
            "x-is-trigger": False,
            "x-display-name": "List Online Archives",
        },
        title="List Online Archives",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster whose online archives to list")
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field(
        "false",
        title="Fetch All Pages",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class AtlasGetOnlineArchiveConfig(BaseModel):
    """Get a single online archive by ID."""

    operation: Literal["get_online_archive"] = Field(
        "get_online_archive",
        json_schema_extra={
            "const": "get_online_archive",
            "ui:hidden": True,
            "x-category": "Online Archive",
            "x-is-trigger": False,
            "x-display-name": "Get Online Archive",
        },
        title="Get Online Archive",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster containing the online archive")
    archive_id: str = Field(..., title="Archive ID", description="Unique identifier of the online archive")


class AtlasCreateOnlineArchiveConfig(BaseModel):
    """Create an online archive rule for a collection."""

    operation: Literal["create_online_archive"] = Field(
        "create_online_archive",
        json_schema_extra={
            "const": "create_online_archive",
            "ui:hidden": True,
            "x-category": "Online Archive",
            "x-is-trigger": False,
            "x-display-name": "Create Online Archive",
        },
        title="Create Online Archive",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster to create the online archive for")
    db_name: str = Field(..., title="Database Name", description="Name of the database containing the collection to archive")
    coll_name: str = Field(..., title="Collection Name", description="Name of the collection to archive")
    date_field: str = Field(..., title="Date Field", description="Name of the date field to use for archiving")
    date_format: Optional[str] = Field(
        None,
        title="Date Format",
        description="Format of the date field value",
        json_schema_extra={
            "enum": ["ISODATE", "EPOCH_SECONDS", "EPOCH_MILLIS", "EPOCH_NANOSECONDS"],
            "x-enum-searchable": True,
        },
    )
    expire_after_days: int = Field(..., title="Expire After Days", description="Days after which data is archived")
    partition_fields: Optional[str] = Field(
        None,
        title="Partition Fields (JSON Array)",
        description="Array of partition field objects [{fieldName, fieldType, order}]",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class AtlasUpdateOnlineArchiveConfig(BaseModel):
    """Update an existing online archive's expiry setting."""

    operation: Literal["update_online_archive"] = Field(
        "update_online_archive",
        json_schema_extra={
            "const": "update_online_archive",
            "ui:hidden": True,
            "x-category": "Online Archive",
            "x-is-trigger": False,
            "x-display-name": "Update Online Archive",
        },
        title="Update Online Archive",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster containing the online archive")
    archive_id: str = Field(..., title="Archive ID", description="Unique identifier of the online archive to update")
    expire_after_days: int = Field(..., title="Expire After Days", description="Updated number of days after which data is archived")


class AtlasDeleteOnlineArchiveConfig(BaseModel):
    """Delete an online archive rule."""

    operation: Literal["delete_online_archive"] = Field(
        "delete_online_archive",
        json_schema_extra={
            "const": "delete_online_archive",
            "ui:hidden": True,
            "x-category": "Online Archive",
            "x-is-trigger": False,
            "x-display-name": "Delete Online Archive",
        },
        title="Delete Online Archive",
    )
    project_id: str = _project_id_field("The project containing the cluster")
    cluster_name: str = _cluster_name_field("The cluster containing the online archive")
    archive_id: str = Field(..., title="Archive ID", description="Unique identifier of the online archive to delete")


# =============================================================================
# CATEGORY: Atlas Streams
# =============================================================================

class AtlasListStreamInstancesConfig(BaseModel):
    """List all Atlas Stream Processing instances in a project."""

    operation: Literal["list_stream_instances"] = Field(
        "list_stream_instances",
        json_schema_extra={
            "const": "list_stream_instances",
            "ui:hidden": True,
            "x-category": "Atlas Streams",
            "x-is-trigger": False,
            "x-display-name": "List Stream Instances",
        },
        title="List Stream Instances",
    )
    project_id: str = _project_id_field("The project whose stream instances to list")
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field(
        "false",
        title="Fetch All Pages",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class AtlasGetStreamInstanceConfig(BaseModel):
    """Get a single Atlas Stream Processing instance by name."""

    operation: Literal["get_stream_instance"] = Field(
        "get_stream_instance",
        json_schema_extra={
            "const": "get_stream_instance",
            "ui:hidden": True,
            "x-category": "Atlas Streams",
            "x-is-trigger": False,
            "x-display-name": "Get Stream Instance",
        },
        title="Get Stream Instance",
    )
    project_id: str = _project_id_field("The project containing the stream instance")
    tenant_name: str = Field(
        ...,
        title="Stream Instance",
        description="Name of the stream processing instance",
        json_schema_extra=_dyn("tenant_name", "stream instance", depends_on="project_id"),
    )


class AtlasCreateStreamInstanceConfig(BaseModel):
    """Create a new Atlas Stream Processing instance."""

    operation: Literal["create_stream_instance"] = Field(
        "create_stream_instance",
        json_schema_extra={
            "const": "create_stream_instance",
            "ui:hidden": True,
            "x-category": "Atlas Streams",
            "x-is-trigger": False,
            "x-display-name": "Create Stream Instance",
        },
        title="Create Stream Instance",
    )
    project_id: str = _project_id_field("The project to create the stream instance in")
    name: str = Field(..., title="Instance Name", description="Unique name for the new stream processing instance")
    data_process_region: str = Field(
        ...,
        title="Data Process Region (JSON)",
        description='Processing region e.g. {"cloudProvider":"AWS","region":"US_EAST_1"}',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    stream_config: Optional[str] = Field(
        None,
        title="Stream Config (JSON)",
        description='Optional tier config e.g. {"tier":"SP10"}',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class AtlasUpdateStreamInstanceConfig(BaseModel):
    """Update an existing Atlas Stream Processing instance."""

    operation: Literal["update_stream_instance"] = Field(
        "update_stream_instance",
        json_schema_extra={
            "const": "update_stream_instance",
            "ui:hidden": True,
            "x-category": "Atlas Streams",
            "x-is-trigger": False,
            "x-display-name": "Update Stream Instance",
        },
        title="Update Stream Instance",
    )
    project_id: str = _project_id_field("The project containing the stream instance")
    tenant_name: str = Field(
        ...,
        title="Stream Instance",
        description="Name of the stream processing instance to update",
        json_schema_extra=_dyn("tenant_name", "stream instance", depends_on="project_id"),
    )
    data_process_region: Optional[str] = Field(
        None,
        title="Data Process Region (JSON)",
        description='Updated processing region e.g. {"cloudProvider":"AWS","region":"US_EAST_1"}',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    stream_config: Optional[str] = Field(
        None,
        title="Stream Config (JSON)",
        description='Updated tier config e.g. {"tier":"SP10"}',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class AtlasDeleteStreamInstanceConfig(BaseModel):
    """Delete an Atlas Stream Processing instance."""

    operation: Literal["delete_stream_instance"] = Field(
        "delete_stream_instance",
        json_schema_extra={
            "const": "delete_stream_instance",
            "ui:hidden": True,
            "x-category": "Atlas Streams",
            "x-is-trigger": False,
            "x-display-name": "Delete Stream Instance",
        },
        title="Delete Stream Instance",
    )
    project_id: str = _project_id_field("The project containing the stream instance")
    tenant_name: str = Field(
        ...,
        title="Stream Instance",
        description="Name of the stream processing instance to delete",
        json_schema_extra=_dyn("tenant_name", "stream instance", depends_on="project_id"),
    )


class AtlasDownloadStreamAuditLogsConfig(BaseModel):
    """Download audit logs for an Atlas Stream Processing instance."""

    operation: Literal["download_stream_audit_logs"] = Field(
        "download_stream_audit_logs",
        json_schema_extra={
            "const": "download_stream_audit_logs",
            "ui:hidden": True,
            "x-category": "Atlas Streams",
            "x-is-trigger": False,
            "x-display-name": "Download Stream Audit Logs",
        },
        title="Download Stream Audit Logs",
    )
    project_id: str = _project_id_field("The project containing the stream instance")
    tenant_name: str = Field(
        ...,
        title="Stream Instance",
        description="Name of the stream processing instance",
        json_schema_extra=_dyn("tenant_name", "stream instance", depends_on="project_id"),
    )
    start_date: Optional[str] = Field(None, title="Start Date", description="ISO 8601 start date")
    end_date: Optional[str] = Field(None, title="End Date", description="ISO 8601 end date")


class AtlasListStreamConnectionsConfig(BaseModel):
    """List all connections for an Atlas Stream Processing instance."""

    operation: Literal["list_stream_connections"] = Field(
        "list_stream_connections",
        json_schema_extra={
            "const": "list_stream_connections",
            "ui:hidden": True,
            "x-category": "Atlas Streams",
            "x-is-trigger": False,
            "x-display-name": "List Stream Connections",
        },
        title="List Stream Connections",
    )
    project_id: str = _project_id_field("The project containing the stream instance")
    tenant_name: str = Field(
        ...,
        title="Stream Instance",
        description="Name of the stream processing instance",
        json_schema_extra=_dyn("tenant_name", "stream instance", depends_on="project_id"),
    )
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field(
        "false",
        title="Fetch All Pages",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class AtlasGetStreamConnectionConfig(BaseModel):
    """Get a single stream connection by name."""

    operation: Literal["get_stream_connection"] = Field(
        "get_stream_connection",
        json_schema_extra={
            "const": "get_stream_connection",
            "ui:hidden": True,
            "x-category": "Atlas Streams",
            "x-is-trigger": False,
            "x-display-name": "Get Stream Connection",
        },
        title="Get Stream Connection",
    )
    project_id: str = _project_id_field("The project containing the stream instance")
    tenant_name: str = Field(
        ...,
        title="Stream Instance",
        description="Name of the stream processing instance",
        json_schema_extra=_dyn("tenant_name", "stream instance", depends_on="project_id"),
    )
    connection_name: str = Field(..., title="Connection Name", description="Name of the stream connection")


class AtlasCreateStreamConnectionConfig(BaseModel):
    """Create a new connection for an Atlas Stream Processing instance."""

    operation: Literal["create_stream_connection"] = Field(
        "create_stream_connection",
        json_schema_extra={
            "const": "create_stream_connection",
            "ui:hidden": True,
            "x-category": "Atlas Streams",
            "x-is-trigger": False,
            "x-display-name": "Create Stream Connection",
        },
        title="Create Stream Connection",
    )
    project_id: str = _project_id_field("The project containing the stream instance")
    tenant_name: str = Field(
        ...,
        title="Stream Instance",
        description="Name of the stream processing instance",
        json_schema_extra=_dyn("tenant_name", "stream instance", depends_on="project_id"),
    )
    connection_definition: str = Field(
        ...,
        title="Connection Definition (JSON)",
        description="Connection definition JSON: {name, type: Cluster|Kafka|Sample, clusterName or bootstrapServers+security+authentication}",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class AtlasUpdateStreamConnectionConfig(BaseModel):
    """Update an existing stream connection."""

    operation: Literal["update_stream_connection"] = Field(
        "update_stream_connection",
        json_schema_extra={
            "const": "update_stream_connection",
            "ui:hidden": True,
            "x-category": "Atlas Streams",
            "x-is-trigger": False,
            "x-display-name": "Update Stream Connection",
        },
        title="Update Stream Connection",
    )
    project_id: str = _project_id_field("The project containing the stream instance")
    tenant_name: str = Field(
        ...,
        title="Stream Instance",
        description="Name of the stream processing instance",
        json_schema_extra=_dyn("tenant_name", "stream instance", depends_on="project_id"),
    )
    connection_name: str = Field(..., title="Connection Name", description="Name of the stream connection to update")
    connection_definition: str = Field(
        ...,
        title="Connection Definition (JSON)",
        description="Updated connection definition JSON",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class AtlasDeleteStreamConnectionConfig(BaseModel):
    """Delete a stream connection."""

    operation: Literal["delete_stream_connection"] = Field(
        "delete_stream_connection",
        json_schema_extra={
            "const": "delete_stream_connection",
            "ui:hidden": True,
            "x-category": "Atlas Streams",
            "x-is-trigger": False,
            "x-display-name": "Delete Stream Connection",
        },
        title="Delete Stream Connection",
    )
    project_id: str = _project_id_field("The project containing the stream instance")
    tenant_name: str = Field(
        ...,
        title="Stream Instance",
        description="Name of the stream processing instance",
        json_schema_extra=_dyn("tenant_name", "stream instance", depends_on="project_id"),
    )
    connection_name: str = Field(..., title="Connection Name", description="Name of the stream connection to delete")


class AtlasListStreamProcessorsConfig(BaseModel):
    """List all processors for an Atlas Stream Processing instance."""

    operation: Literal["list_stream_processors"] = Field(
        "list_stream_processors",
        json_schema_extra={
            "const": "list_stream_processors",
            "ui:hidden": True,
            "x-category": "Atlas Streams",
            "x-is-trigger": False,
            "x-display-name": "List Stream Processors",
        },
        title="List Stream Processors",
    )
    project_id: str = _project_id_field("The project containing the stream instance")
    tenant_name: str = Field(
        ...,
        title="Stream Instance",
        description="Name of the stream processing instance",
        json_schema_extra=_dyn("tenant_name", "stream instance", depends_on="project_id"),
    )
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field(
        "false",
        title="Fetch All Pages",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class AtlasGetStreamProcessorConfig(BaseModel):
    """Get a single stream processor by name."""

    operation: Literal["get_stream_processor"] = Field(
        "get_stream_processor",
        json_schema_extra={
            "const": "get_stream_processor",
            "ui:hidden": True,
            "x-category": "Atlas Streams",
            "x-is-trigger": False,
            "x-display-name": "Get Stream Processor",
        },
        title="Get Stream Processor",
    )
    project_id: str = _project_id_field("The project containing the stream instance")
    tenant_name: str = Field(
        ...,
        title="Stream Instance",
        description="Name of the stream processing instance",
        json_schema_extra=_dyn("tenant_name", "stream instance", depends_on="project_id"),
    )
    processor_name: str = Field(..., title="Processor Name", description="Name of the stream processor")


class AtlasCreateStreamProcessorConfig(BaseModel):
    """Create a new stream processor."""

    operation: Literal["create_stream_processor"] = Field(
        "create_stream_processor",
        json_schema_extra={
            "const": "create_stream_processor",
            "ui:hidden": True,
            "x-category": "Atlas Streams",
            "x-is-trigger": False,
            "x-display-name": "Create Stream Processor",
        },
        title="Create Stream Processor",
    )
    project_id: str = _project_id_field("The project containing the stream instance")
    tenant_name: str = Field(
        ...,
        title="Stream Instance",
        description="Name of the stream processing instance",
        json_schema_extra=_dyn("tenant_name", "stream instance", depends_on="project_id"),
    )
    processor_definition: str = Field(
        ...,
        title="Processor Definition (JSON)",
        description="Processor definition: {name, pipeline: [...stages], options: {...}}",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class AtlasStartStreamProcessorConfig(BaseModel):
    """Start a stopped stream processor."""

    operation: Literal["start_stream_processor"] = Field(
        "start_stream_processor",
        json_schema_extra={
            "const": "start_stream_processor",
            "ui:hidden": True,
            "x-category": "Atlas Streams",
            "x-is-trigger": False,
            "x-display-name": "Start Stream Processor",
        },
        title="Start Stream Processor",
    )
    project_id: str = _project_id_field("The project containing the stream instance")
    tenant_name: str = Field(
        ...,
        title="Stream Instance",
        description="Name of the stream processing instance",
        json_schema_extra=_dyn("tenant_name", "stream instance", depends_on="project_id"),
    )
    processor_name: str = Field(..., title="Processor Name", description="Name of the stream processor to start")


class AtlasStopStreamProcessorConfig(BaseModel):
    """Stop a running stream processor."""

    operation: Literal["stop_stream_processor"] = Field(
        "stop_stream_processor",
        json_schema_extra={
            "const": "stop_stream_processor",
            "ui:hidden": True,
            "x-category": "Atlas Streams",
            "x-is-trigger": False,
            "x-display-name": "Stop Stream Processor",
        },
        title="Stop Stream Processor",
    )
    project_id: str = _project_id_field("The project containing the stream instance")
    tenant_name: str = Field(
        ...,
        title="Stream Instance",
        description="Name of the stream processing instance",
        json_schema_extra=_dyn("tenant_name", "stream instance", depends_on="project_id"),
    )
    processor_name: str = Field(..., title="Processor Name", description="Name of the stream processor to stop")


class AtlasDeleteStreamProcessorConfig(BaseModel):
    """Delete a stream processor."""

    operation: Literal["delete_stream_processor"] = Field(
        "delete_stream_processor",
        json_schema_extra={
            "const": "delete_stream_processor",
            "ui:hidden": True,
            "x-category": "Atlas Streams",
            "x-is-trigger": False,
            "x-display-name": "Delete Stream Processor",
        },
        title="Delete Stream Processor",
    )
    project_id: str = _project_id_field("The project containing the stream instance")
    tenant_name: str = Field(
        ...,
        title="Stream Instance",
        description="Name of the stream processing instance",
        json_schema_extra=_dyn("tenant_name", "stream instance", depends_on="project_id"),
    )
    processor_name: str = Field(..., title="Processor Name", description="Name of the stream processor to delete")


# =============================================================================
# CATEGORY: Data Federation
# =============================================================================

class AtlasListDataFederationConfig(BaseModel):
    """List all federated database instances in a project."""

    operation: Literal["list_data_federation"] = Field(
        "list_data_federation",
        json_schema_extra={
            "const": "list_data_federation",
            "ui:hidden": True,
            "x-category": "Data Federation",
            "x-is-trigger": False,
            "x-display-name": "List Federated Database Instances",
        },
        title="List Federated Database Instances",
    )
    project_id: str = _project_id_field("The project whose federated database instances to list")
    fed_type: Optional[str] = Field(
        None,
        title="Type",
        description="Filter by federated database instance type",
        json_schema_extra={
            "enum": ["USER", "SERVICE"],
            "x-enum-searchable": True,
        },
    )
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field(
        "false",
        title="Fetch All Pages",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class AtlasGetDataFederationConfig(BaseModel):
    """Get a single federated database instance by name."""

    operation: Literal["get_data_federation"] = Field(
        "get_data_federation",
        json_schema_extra={
            "const": "get_data_federation",
            "ui:hidden": True,
            "x-category": "Data Federation",
            "x-is-trigger": False,
            "x-display-name": "Get Federated Database Instance",
        },
        title="Get Federated Database Instance",
    )
    project_id: str = _project_id_field("The project containing the federated database instance")
    tenant_name: str = Field(
        ...,
        title="Federated Database Tenant",
        description="Name of the federated database instance",
        json_schema_extra=_dyn("tenant_name", "federated database tenant", depends_on="project_id"),
    )


class AtlasCreateDataFederationConfig(BaseModel):
    """Create a new federated database instance."""

    operation: Literal["create_data_federation"] = Field(
        "create_data_federation",
        json_schema_extra={
            "const": "create_data_federation",
            "ui:hidden": True,
            "x-category": "Data Federation",
            "x-is-trigger": False,
            "x-display-name": "Create Federated Database Instance",
        },
        title="Create Federated Database Instance",
    )
    project_id: str = _project_id_field("The project to create the federated database instance in")
    tenant_definition: str = Field(
        ...,
        title="Instance Definition (JSON)",
        description="Federated database instance definition JSON including name, cloudProviderConfig, dataProcessRegion, storage",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class AtlasUpdateDataFederationConfig(BaseModel):
    """Update an existing federated database instance."""

    operation: Literal["update_data_federation"] = Field(
        "update_data_federation",
        json_schema_extra={
            "const": "update_data_federation",
            "ui:hidden": True,
            "x-category": "Data Federation",
            "x-is-trigger": False,
            "x-display-name": "Update Federated Database Instance",
        },
        title="Update Federated Database Instance",
    )
    project_id: str = _project_id_field("The project containing the federated database instance")
    tenant_name: str = Field(
        ...,
        title="Federated Database Tenant",
        description="Name of the federated database instance to update",
        json_schema_extra=_dyn("tenant_name", "federated database tenant", depends_on="project_id"),
    )
    tenant_definition: str = Field(
        ...,
        title="Instance Definition (JSON)",
        description="Updated federated database instance definition JSON",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class AtlasDeleteDataFederationConfig(BaseModel):
    """Delete a federated database instance."""

    operation: Literal["delete_data_federation"] = Field(
        "delete_data_federation",
        json_schema_extra={
            "const": "delete_data_federation",
            "ui:hidden": True,
            "x-category": "Data Federation",
            "x-is-trigger": False,
            "x-display-name": "Delete Federated Database Instance",
        },
        title="Delete Federated Database Instance",
    )
    project_id: str = _project_id_field("The project containing the federated database instance")
    tenant_name: str = Field(
        ...,
        title="Federated Database Tenant",
        description="Name of the federated database instance to delete",
        json_schema_extra=_dyn("tenant_name", "federated database tenant", depends_on="project_id"),
    )


class AtlasCreateDataFederationQueryLimitConfig(BaseModel):
    """Create or update a query limit for a federated database instance."""

    operation: Literal["create_data_federation_query_limit"] = Field(
        "create_data_federation_query_limit",
        json_schema_extra={
            "const": "create_data_federation_query_limit",
            "ui:hidden": True,
            "x-category": "Data Federation",
            "x-is-trigger": False,
            "x-display-name": "Set Data Federation Query Limit",
        },
        title="Set Data Federation Query Limit",
    )
    project_id: str = _project_id_field("The project containing the federated database instance")
    tenant_name: str = Field(
        ...,
        title="Federated Database Tenant",
        description="Name of the federated database instance",
        json_schema_extra=_dyn("tenant_name", "federated database tenant", depends_on="project_id"),
    )
    limit_name: str = Field(
        ...,
        title="Limit Name",
        description="The query limit to set",
        json_schema_extra={
            "enum": [
                "bytesProcessed.query",
                "bytesProcessed.daily",
                "bytesProcessed.weekly",
                "bytesProcessed.monthly",
            ],
            "x-enum-searchable": True,
        },
    )
    limit_value: int = Field(..., title="Limit Value", description="Maximum bytes allowed")


class AtlasListDataFederationQueryLimitsConfig(BaseModel):
    """List all query limits for a federated database instance."""

    operation: Literal["list_data_federation_query_limits"] = Field(
        "list_data_federation_query_limits",
        json_schema_extra={
            "const": "list_data_federation_query_limits",
            "ui:hidden": True,
            "x-category": "Data Federation",
            "x-is-trigger": False,
            "x-display-name": "List Data Federation Query Limits",
        },
        title="List Data Federation Query Limits",
    )
    project_id: str = _project_id_field("The project containing the federated database instance")
    tenant_name: str = Field(
        ...,
        title="Federated Database Tenant",
        description="Name of the federated database instance",
        json_schema_extra=_dyn("tenant_name", "federated database tenant", depends_on="project_id"),
    )


class AtlasDeleteDataFederationQueryLimitConfig(BaseModel):
    """Delete a query limit from a federated database instance."""

    operation: Literal["delete_data_federation_query_limit"] = Field(
        "delete_data_federation_query_limit",
        json_schema_extra={
            "const": "delete_data_federation_query_limit",
            "ui:hidden": True,
            "x-category": "Data Federation",
            "x-is-trigger": False,
            "x-display-name": "Delete Data Federation Query Limit",
        },
        title="Delete Data Federation Query Limit",
    )
    project_id: str = _project_id_field("The project containing the federated database instance")
    tenant_name: str = Field(
        ...,
        title="Federated Database Tenant",
        description="Name of the federated database instance",
        json_schema_extra=_dyn("tenant_name", "federated database tenant", depends_on="project_id"),
    )
    limit_name: str = Field(..., title="Limit Name", description="Name of the query limit to delete")


# =============================================================================
# SECTION C: Organizations / Projects / Teams
# =============================================================================

# ── ORGANIZATIONS ─────────────────────────────────────────────────────────────

class AtlasListOrgsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_orgs"] = Field("list_orgs", title="Operation", json_schema_extra={"ui:hidden": True})
    name: Optional[str] = Field(None, title="Name", description="Filter by org name")
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasGetOrgConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_org"] = Field("get_org", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))


class AtlasRenameOrgConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["rename_org"] = Field("rename_org", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    name: str = Field(..., title="New Name")


class AtlasDeleteOrgConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_org"] = Field("delete_org", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))


class AtlasGetOrgSettingsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_org_settings"] = Field("get_org_settings", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))


class AtlasUpdateOrgSettingsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["update_org_settings"] = Field("update_org_settings", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    api_access_list_required: Optional[str] = Field(None, title="API Access List Required", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    multi_factor_auth_required: Optional[str] = Field(None, title="Multi-Factor Auth Required", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    restrict_employee_access: Optional[str] = Field(None, title="Restrict Employee Access", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasListOrgUsersConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_org_users"] = Field("list_org_users", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasListOrgInvitationsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_org_invitations"] = Field("list_org_invitations", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    username: Optional[str] = Field(None, title="Username", description="Filter by email/username")


class AtlasInviteToOrgConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["invite_to_org"] = Field("invite_to_org", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    username: str = Field(..., title="Username")
    roles: str = Field(..., title="Roles", description='Array of org role strings e.g. ["ORG_OWNER","ORG_MEMBER"]', json_schema_extra={"ui:widget": "code_editor"})
    team_ids: Optional[str] = Field(None, title="Team IDs", description="Optional array of team IDs to add user to", json_schema_extra={"ui:widget": "code_editor"})


class AtlasDeleteOrgInvitationConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_org_invitation"] = Field("delete_org_invitation", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    invitation_id: str = Field(..., title="Invitation ID")


class AtlasListOrgApiKeysConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_org_api_keys"] = Field("list_org_api_keys", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasCreateOrgApiKeyConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_org_api_key"] = Field("create_org_api_key", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    description: str = Field(..., title="Description")
    roles: str = Field(..., title="Roles", description='Array of org role strings e.g. ["ORG_OWNER"]', json_schema_extra={"ui:widget": "code_editor"})


class AtlasDeleteOrgApiKeyConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_org_api_key"] = Field("delete_org_api_key", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    api_user_id: str = Field(..., title="API Key", json_schema_extra=_dyn("api_user_id", "API key", depends_on="org_id"))


# ── PROJECTS ──────────────────────────────────────────────────────────────────

class AtlasListProjectsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_projects"] = Field("list_projects", title="Operation", json_schema_extra={"ui:hidden": True})
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasGetProjectConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_project"] = Field("get_project", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project", json_schema_extra=_dyn("group_id", "project"))


class AtlasGetProjectByNameConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_project_by_name"] = Field("get_project_by_name", title="Operation", json_schema_extra={"ui:hidden": True})
    group_name: str = Field(..., title="Project Name")


class AtlasCreateProjectConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_project"] = Field("create_project", title="Operation", json_schema_extra={"ui:hidden": True, "x-creates-resource": True, "x-resource-type": "atlas_project", "x-resource-id-path": "data.id"})
    name: str = Field(..., title="Project Name")
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    with_default_alerts_settings: Optional[str] = Field(None, title="Default Alert Settings", description="Create with default alert settings", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasDeleteProjectConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_project"] = Field("delete_project", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project", json_schema_extra=_dyn("group_id", "project"))


class AtlasGetProjectSettingsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_project_settings"] = Field("get_project_settings", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project", json_schema_extra=_dyn("group_id", "project"))


class AtlasUpdateProjectSettingsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["update_project_settings"] = Field("update_project_settings", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project", json_schema_extra=_dyn("group_id", "project"))
    is_performance_advisor_enabled: Optional[str] = Field(None, title="Performance Advisor Enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    is_schema_advisor_enabled: Optional[str] = Field(None, title="Schema Advisor Enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    is_realtime_performance_panel_enabled: Optional[str] = Field(None, title="Real-Time Performance Panel Enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    is_data_explorer_enabled: Optional[str] = Field(None, title="Data Explorer Enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    is_extended_storage_sizes_enabled: Optional[str] = Field(None, title="Extended Storage Sizes Enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasListProjectUsersConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_project_users"] = Field("list_project_users", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project", json_schema_extra=_dyn("group_id", "project"))
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasAddProjectUserConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["add_project_user"] = Field("add_project_user", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project", json_schema_extra=_dyn("group_id", "project"))
    username: str = Field(..., title="Username")
    roles: str = Field(..., title="Roles", description='Array of project role strings e.g. ["GROUP_READ_ONLY","GROUP_DATA_ACCESS_READ_WRITE"]', json_schema_extra={"ui:widget": "code_editor"})


class AtlasRemoveProjectUserConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["remove_project_user"] = Field("remove_project_user", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project", json_schema_extra=_dyn("group_id", "project"))
    user_id: str = Field(..., title="User ID")


class AtlasListProjectInvitationsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_project_invitations"] = Field("list_project_invitations", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project", json_schema_extra=_dyn("group_id", "project"))


class AtlasInviteToProjectConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["invite_to_project"] = Field("invite_to_project", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project", json_schema_extra=_dyn("group_id", "project"))
    username: str = Field(..., title="Username")
    roles: str = Field(..., title="Roles", description="Array of project role strings", json_schema_extra={"ui:widget": "code_editor"})


class AtlasDeleteProjectInvitationConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_project_invitation"] = Field("delete_project_invitation", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project", json_schema_extra=_dyn("group_id", "project"))
    invitation_id: str = Field(..., title="Invitation ID")


class AtlasGetProjectClusterCountConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_project_cluster_count"] = Field("get_project_cluster_count", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project", json_schema_extra=_dyn("group_id", "project"))


class AtlasListProjectApiKeysConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_project_api_keys"] = Field("list_project_api_keys", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project", json_schema_extra=_dyn("group_id", "project"))
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasCreateProjectApiKeyConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_project_api_key"] = Field("create_project_api_key", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project", json_schema_extra=_dyn("group_id", "project"))
    description: str = Field(..., title="Description")
    roles: str = Field(..., title="Roles", description="Array of project role strings", json_schema_extra={"ui:widget": "code_editor"})


class AtlasAssignApiKeyToProjectConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["assign_api_key_to_project"] = Field("assign_api_key_to_project", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project", json_schema_extra=_dyn("group_id", "project"))
    api_user_id: str = Field(..., title="API Key ID")
    roles: str = Field(..., title="Roles", json_schema_extra={"ui:widget": "code_editor"})


# ── TEAMS ─────────────────────────────────────────────────────────────────────

class AtlasListOrgTeamsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_org_teams"] = Field("list_org_teams", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasGetOrgTeamConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_org_team"] = Field("get_org_team", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    team_id: str = Field(..., title="Team", json_schema_extra=_dyn("team_id", "team", depends_on="org_id"))


class AtlasGetTeamByNameConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_team_by_name"] = Field("get_team_by_name", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    team_name: str = Field(..., title="Team Name")


class AtlasCreateOrgTeamConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_org_team"] = Field("create_org_team", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    name: str = Field(..., title="Team Name")
    usernames: str = Field(..., title="Usernames", description="Array of username strings", json_schema_extra={"ui:widget": "code_editor"})


class AtlasRenameOrgTeamConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["rename_org_team"] = Field("rename_org_team", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    team_id: str = Field(..., title="Team", json_schema_extra=_dyn("team_id", "team", depends_on="org_id"))
    name: str = Field(..., title="New Name")


class AtlasDeleteOrgTeamConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_org_team"] = Field("delete_org_team", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    team_id: str = Field(..., title="Team", json_schema_extra=_dyn("team_id", "team", depends_on="org_id"))


class AtlasListTeamUsersConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_team_users"] = Field("list_team_users", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    team_id: str = Field(..., title="Team", json_schema_extra=_dyn("team_id", "team", depends_on="org_id"))


class AtlasAddTeamUsersConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["add_team_users"] = Field("add_team_users", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    team_id: str = Field(..., title="Team", json_schema_extra=_dyn("team_id", "team", depends_on="org_id"))
    usernames: str = Field(..., title="Usernames", description="Array of username strings", json_schema_extra={"ui:widget": "code_editor"})


class AtlasRemoveTeamUserConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["remove_team_user"] = Field("remove_team_user", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization", json_schema_extra=_dyn("org_id", "organization"))
    team_id: str = Field(..., title="Team", json_schema_extra=_dyn("team_id", "team", depends_on="org_id"))
    user_id: str = Field(..., title="User ID")


class AtlasListProjectTeamsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_project_teams"] = Field("list_project_teams", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project", json_schema_extra=_dyn("group_id", "project"))
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasAddTeamsToProjectConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["add_teams_to_project"] = Field("add_teams_to_project", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project", json_schema_extra=_dyn("group_id", "project"))
    teams: str = Field(..., title="Teams", description="Array of {teamId, roleNames:[...]} objects", json_schema_extra={"ui:widget": "code_editor"})


class AtlasUpdateProjectTeamConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["update_project_team"] = Field("update_project_team", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project", json_schema_extra=_dyn("group_id", "project"))
    team_id: str = Field(..., title="Team ID")
    roles: str = Field(..., title="Roles", description="Array of project role strings", json_schema_extra={"ui:widget": "code_editor"})


class AtlasRemoveProjectTeamConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["remove_project_team"] = Field("remove_project_team", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project", json_schema_extra=_dyn("group_id", "project"))
    team_id: str = Field(..., title="Team ID")


# =============================================================================
# SECTION D: Maintenance / Auditing / Encryption / LDAP / X509 / Cloud Provider / Global Zones
# =============================================================================

# =============================================================================
# MAINTENANCE WINDOWS (5 ops)
# =============================================================================

class AtlasGetMaintenanceWindowConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_maintenance_window"] = Field("get_maintenance_window", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))


class AtlasUpdateMaintenanceWindowConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["update_maintenance_window"] = Field("update_maintenance_window", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    day_of_week: int = Field(..., title="Day of Week", ge=1, le=7, description="1=Sunday 7=Saturday")
    hour_of_day: int = Field(..., title="Hour of Day", ge=0, le=23)
    start_asap: Optional[str] = Field(None, title="Start ASAP", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasDeferMaintenanceWindowConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["defer_maintenance_window"] = Field("defer_maintenance_window", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))


class AtlasAutoDeferMaintenanceWindowConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["auto_defer_maintenance_window"] = Field("auto_defer_maintenance_window", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))


class AtlasResetMaintenanceWindowConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["reset_maintenance_window"] = Field("reset_maintenance_window", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))


# =============================================================================
# AUDITING (3 ops)
# =============================================================================

class AtlasGetAuditingConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_auditing"] = Field("get_auditing", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))


class AtlasUpdateAuditingConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["update_auditing"] = Field("update_auditing", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    enabled: str = Field(..., title="Enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    audit_filter: Optional[str] = Field(None, title="Audit Filter", description='MongoDB query filter for audit events e.g. {"atype":{"$in":["createCollection"]}}', json_schema_extra={"ui:widget": "code_editor"})
    audit_authorization_success: Optional[str] = Field(None, title="Audit Authorization Success", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasGetOrgAuditingConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_org_auditing"] = Field("get_org_auditing", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))


# =============================================================================
# ENCRYPTION AT REST (3 ops)
# =============================================================================

class AtlasGetEncryptionAtRestConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_encryption_at_rest"] = Field("get_encryption_at_rest", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))


class AtlasUpdateEncryptionAtRestConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["update_encryption_at_rest"] = Field("update_encryption_at_rest", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    aws_kms: Optional[str] = Field(None, title="AWS KMS Config", description="AWS KMS config: {enabled,accessKeyID,secretAccessKey,customerMasterKeyID,region}", json_schema_extra={"ui:widget": "code_editor"})
    azure_key_vault: Optional[str] = Field(None, title="Azure Key Vault Config", description="Azure Key Vault config: {enabled,clientID,azureEnvironment,subscriptionID,resourceGroupName,keyVaultName,keyIdentifier,tenantID}", json_schema_extra={"ui:widget": "code_editor"})
    google_cloud_kms: Optional[str] = Field(None, title="Google Cloud KMS Config", description="GCP KMS config: {enabled,serviceAccountKey,keyVersionResourceID}", json_schema_extra={"ui:widget": "code_editor"})


class AtlasGetEncryptionAtRestPrivateEndpointConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_encryption_at_rest_private_endpoint"] = Field("get_encryption_at_rest_private_endpoint", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cloud_provider: str = Field(..., title="Cloud Provider", json_schema_extra={"enum": ["AWS", "AZURE", "GCP"], "x-enum-searchable": True})


# =============================================================================
# LDAP (3 ops)
# =============================================================================

class AtlasGetLdapConfigConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_ldap_config"] = Field("get_ldap_config", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))


class AtlasSaveLdapConfigConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["save_ldap_config"] = Field("save_ldap_config", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    authentication_enabled: str = Field(..., title="Authentication Enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    authorization_enabled: str = Field(..., title="Authorization Enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    hostname: str = Field(..., title="Hostname")
    port: int = Field(636, title="Port")
    bind_username: str = Field(..., title="Bind Username")
    bind_password: str = Field(..., title="Bind Password")
    ca_certificate: Optional[str] = Field(None, title="CA Certificate", description="PEM CA cert")
    user_to_dn_mapping: Optional[str] = Field(None, title="User to DN Mapping", description="Array of {match, ldapQuery, substitution} objects", json_schema_extra={"ui:widget": "code_editor"})


class AtlasVerifyLdapConfigConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["verify_ldap_config"] = Field("verify_ldap_config", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    hostname: str = Field(..., title="Hostname")
    port: int = Field(636, title="Port")
    bind_username: str = Field(..., title="Bind Username")
    bind_password: str = Field(..., title="Bind Password")
    ca_certificate: Optional[str] = Field(None, title="CA Certificate")


# =============================================================================
# X.509 AUTH (3 ops)
# =============================================================================

class AtlasGetX509ConfigConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_x509_config"] = Field("get_x509_config", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))


class AtlasSaveX509ConfigConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["save_x509_config"] = Field("save_x509_config", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cas: str = Field(..., title="Certificate Authority Chain", description="PEM-encoded certificate authority chain")


class AtlasDisableX509ConfigConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["disable_x509_config"] = Field("disable_x509_config", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))


# =============================================================================
# CLOUD PROVIDER ACCESS (4 ops)
# =============================================================================

class AtlasListCloudProviderAccessConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_cloud_provider_access"] = Field("list_cloud_provider_access", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))


class AtlasCreateCloudProviderAccessConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_cloud_provider_access"] = Field("create_cloud_provider_access", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    provider_name: str = Field(..., title="Provider Name", json_schema_extra={"enum": ["AWS", "AZURE", "GCP"], "x-enum-searchable": True})


class AtlasAuthorizeCloudProviderAccessConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["authorize_cloud_provider_access"] = Field("authorize_cloud_provider_access", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    role_id: str = Field(..., title="Role ID")
    iam_assumed_role_arn: str = Field(..., title="IAM Assumed Role ARN", description="AWS IAM ARN to authorize e.g. arn:aws:iam::123456789:role/MyRole")


class AtlasDeauthorizeCloudProviderAccessConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["deauthorize_cloud_provider_access"] = Field("deauthorize_cloud_provider_access", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cloud_provider: str = Field(..., title="Cloud Provider", json_schema_extra={"enum": ["AWS", "AZURE", "GCP"], "x-enum-searchable": True})
    role_id: str = Field(..., title="Role ID")


# =============================================================================
# GLOBAL CLUSTER ZONE MAPPING (6 ops)
# =============================================================================

class AtlasGetManagedNamespacesConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_managed_namespaces"] = Field("get_managed_namespaces", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cluster_name: str = Field(..., title="Cluster Name", json_schema_extra=_dyn("cluster_name", "cluster", depends_on="group_id"))


class AtlasAddManagedNamespaceConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["add_managed_namespace"] = Field("add_managed_namespace", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cluster_name: str = Field(..., title="Cluster Name", json_schema_extra=_dyn("cluster_name", "cluster", depends_on="group_id"))
    db: str = Field(..., title="Database")
    collection: str = Field(..., title="Collection")
    custom_zone_name: str = Field(..., title="Custom Zone Name")
    is_custom_shard_key_hashed: Optional[str] = Field(None, title="Is Custom Shard Key Hashed", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    is_shard_key_unique: Optional[str] = Field(None, title="Is Shard Key Unique", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    num_initial_chunks: Optional[int] = Field(None, title="Number of Initial Chunks")


class AtlasDeleteManagedNamespaceConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_managed_namespace"] = Field("delete_managed_namespace", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cluster_name: str = Field(..., title="Cluster Name", json_schema_extra=_dyn("cluster_name", "cluster", depends_on="group_id"))
    db: str = Field(..., title="Database")
    collection: str = Field(..., title="Collection")


class AtlasGetCustomZoneMappingConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_custom_zone_mapping"] = Field("get_custom_zone_mapping", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cluster_name: str = Field(..., title="Cluster Name", json_schema_extra=_dyn("cluster_name", "cluster", depends_on="group_id"))


class AtlasAddCustomZoneMappingConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["add_custom_zone_mapping"] = Field("add_custom_zone_mapping", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cluster_name: str = Field(..., title="Cluster Name", json_schema_extra=_dyn("cluster_name", "cluster", depends_on="group_id"))
    custom_zone_mapping: str = Field(..., title="Custom Zone Mapping", description='Map of locationCode to zoneName e.g. {"US":"US_EAST","EU":"EU_WEST"}', json_schema_extra={"ui:widget": "code_editor"})


class AtlasDeleteCustomZoneMappingConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_custom_zone_mapping"] = Field("delete_custom_zone_mapping", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cluster_name: str = Field(..., title="Cluster Name", json_schema_extra=_dyn("cluster_name", "cluster", depends_on="group_id"))


# =============================================================================
# SECTION E: Service Accounts / API Keys / Events / Policies / Integrations / Log Export / Users / Federation
# =============================================================================
# =============================================================================
# SERVICE ACCOUNTS
# =============================================================================

class AtlasListOrgServiceAccountsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_org_service_accounts"] = Field("list_org_service_accounts", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasCreateOrgServiceAccountConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_org_service_account"] = Field("create_org_service_account", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    name: str = Field(..., title="Name")
    description: str = Field(..., title="Description")
    roles: Optional[str] = Field(None, title="Roles", description='Array of org role strings e.g. ["ORG_OWNER"]', json_schema_extra={"ui:widget": "code_editor"})


class AtlasGetOrgServiceAccountConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_org_service_account"] = Field("get_org_service_account", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    client_id: str = Field(..., title="Client ID", json_schema_extra=_dyn("client_id", "service account", depends_on="org_id"))


class AtlasUpdateOrgServiceAccountConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["update_org_service_account"] = Field("update_org_service_account", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    client_id: str = Field(..., title="Client ID", json_schema_extra=_dyn("client_id", "service account", depends_on="org_id"))
    name: str = Field(..., title="Name")
    description: str = Field(..., title="Description")
    roles: Optional[str] = Field(None, title="Roles", description='Array of org role strings e.g. ["ORG_OWNER"]', json_schema_extra={"ui:widget": "code_editor"})


class AtlasDeleteOrgServiceAccountConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_org_service_account"] = Field("delete_org_service_account", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    client_id: str = Field(..., title="Client ID", json_schema_extra=_dyn("client_id", "service account", depends_on="org_id"))


class AtlasCreateServiceAccountSecretConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_service_account_secret"] = Field("create_service_account_secret", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    client_id: str = Field(..., title="Client ID", json_schema_extra=_dyn("client_id", "service account", depends_on="org_id"))
    secret_expiration_hours: int = Field(8760, title="Secret Expiration Hours", description="Hours until secret expires (default 8760 = 1 year)")


class AtlasDeleteServiceAccountSecretConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_service_account_secret"] = Field("delete_service_account_secret", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    client_id: str = Field(..., title="Client ID", json_schema_extra=_dyn("client_id", "service account", depends_on="org_id"))
    secret_id: str = Field(..., title="Secret ID")


class AtlasListProjectServiceAccountsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_project_service_accounts"] = Field("list_project_service_accounts", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasAddProjectServiceAccountConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["add_project_service_account"] = Field("add_project_service_account", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    client_id: str = Field(..., title="Client ID")
    roles: Optional[str] = Field(None, title="Roles", description='Array of project role strings e.g. ["GROUP_READ_ONLY"]', json_schema_extra={"ui:widget": "code_editor"})


class AtlasRemoveProjectServiceAccountConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["remove_project_service_account"] = Field("remove_project_service_account", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    client_id: str = Field(..., title="Client ID", json_schema_extra=_dyn("client_id", "service account", depends_on="org_id"))


# =============================================================================
# PROGRAMMATIC API KEYS
# =============================================================================

class AtlasGetOrgApiKeyConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_org_api_key"] = Field("get_org_api_key", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    api_user_id: str = Field(..., title="API User ID")


class AtlasUpdateOrgApiKeyConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["update_org_api_key"] = Field("update_org_api_key", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    api_user_id: str = Field(..., title="API User ID")
    description: Optional[str] = Field(None, title="Description")
    roles: Optional[str] = Field(None, title="Roles", description="Array of role strings", json_schema_extra={"ui:widget": "code_editor"})


class AtlasGetApiKeyAccessListConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_api_key_access_list"] = Field("get_api_key_access_list", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    api_user_id: str = Field(..., title="API User ID")


class AtlasAddApiKeyAccessListConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["add_api_key_access_list"] = Field("add_api_key_access_list", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    api_user_id: str = Field(..., title="API User ID")
    access_list: str = Field(..., title="Access List", description="Array of [{cidrBlock or ipAddress, comment}] objects", json_schema_extra={"ui:widget": "code_editor"})


class AtlasDeleteApiKeyAccessListEntryConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_api_key_access_list_entry"] = Field("delete_api_key_access_list_entry", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    api_user_id: str = Field(..., title="API User ID")
    ip_address: str = Field(..., title="IP Address", description="IP address or CIDR block to remove")


class AtlasGetProjectApiKeyDetailConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_project_api_key_detail"] = Field("get_project_api_key_detail", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    api_user_id: str = Field(..., title="API User ID")


class AtlasRemoveProjectApiKeyConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["remove_project_api_key"] = Field("remove_project_api_key", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    api_user_id: str = Field(..., title="API User ID")


# =============================================================================
# EVENTS
# =============================================================================

_EVENT_TYPE_ENUM = [
    "CLUSTER_CREATED", "CLUSTER_DELETED", "USER_CREATED", "USER_DELETED",
    "ALERT_OPENED", "ALERT_CLOSED", "BACKUP_SNAPSHOT_CREATED", "NDS_MAINTENANCE_START",
]


class AtlasListOrgEventsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_org_events"] = Field("list_org_events", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    event_type: Optional[str] = Field(None, title="Event Type", json_schema_extra={"enum": _EVENT_TYPE_ENUM, "x-enum-searchable": True})
    min_date: Optional[str] = Field(None, title="Min Date", description="ISO 8601 min date")
    max_date: Optional[str] = Field(None, title="Max Date", description="ISO 8601 max date")
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasGetOrgEventConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_org_event"] = Field("get_org_event", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    event_id: str = Field(..., title="Event ID")


class AtlasListProjectEventsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_project_events"] = Field("list_project_events", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    event_type: Optional[str] = Field(None, title="Event Type", json_schema_extra={"enum": _EVENT_TYPE_ENUM, "x-enum-searchable": True})
    min_date: Optional[str] = Field(None, title="Min Date", description="ISO 8601 min date")
    max_date: Optional[str] = Field(None, title="Max Date", description="ISO 8601 max date")
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasGetProjectEventConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_project_event"] = Field("get_project_event", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    event_id: str = Field(..., title="Event ID")


# =============================================================================
# ACCESS TRACKING
# =============================================================================

class AtlasGetDbAccessHistoryConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_db_access_history"] = Field("get_db_access_history", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cluster_name: str = Field(..., title="Cluster Name", json_schema_extra=_dyn("cluster_name", "cluster", depends_on="group_id"))
    start: Optional[str] = Field(None, title="Start Time", description="ISO 8601 start time")
    end: Optional[str] = Field(None, title="End Time", description="ISO 8601 end time")
    ip_address: Optional[str] = Field(None, title="IP Address", description="Filter by IP address")
    auth_result: Optional[str] = Field(None, title="Auth Result", json_schema_extra={"enum": ["SUCCESS", "FAIL"], "x-enum-searchable": True})
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


# =============================================================================
# RESOURCE POLICIES
# =============================================================================

class AtlasListResourcePoliciesConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_resource_policies"] = Field("list_resource_policies", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasGetResourcePolicyConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_resource_policy"] = Field("get_resource_policy", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    resource_policy_id: str = Field(..., title="Resource Policy ID", json_schema_extra=_dyn("resource_policy_id", "resource policy", depends_on="org_id"))


class AtlasCreateResourcePolicyConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_resource_policy"] = Field("create_resource_policy", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    name: str = Field(..., title="Name")
    description: Optional[str] = Field(None, title="Description")
    policies: str = Field(..., title="Policies", description='Array of policy objects e.g. [{"body":"forbid(...)"}]', json_schema_extra={"ui:widget": "code_editor"})


class AtlasUpdateResourcePolicyConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["update_resource_policy"] = Field("update_resource_policy", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    resource_policy_id: str = Field(..., title="Resource Policy ID", json_schema_extra=_dyn("resource_policy_id", "resource policy", depends_on="org_id"))
    name: Optional[str] = Field(None, title="Name")
    policies: Optional[str] = Field(None, title="Policies", description="Array of policy objects", json_schema_extra={"ui:widget": "code_editor"})


class AtlasDeleteResourcePolicyConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_resource_policy"] = Field("delete_resource_policy", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    resource_policy_id: str = Field(..., title="Resource Policy ID", json_schema_extra=_dyn("resource_policy_id", "resource policy", depends_on="org_id"))


class AtlasValidateResourcePolicyConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["validate_resource_policy"] = Field("validate_resource_policy", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    name: str = Field(..., title="Name")
    policies: str = Field(..., title="Policies", description="Array of policy objects", json_schema_extra={"ui:widget": "code_editor"})


class AtlasListNoncompliantResourcesConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_noncompliant_resources"] = Field("list_noncompliant_resources", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))


# =============================================================================
# THIRD-PARTY INTEGRATIONS
# =============================================================================

_INTEGRATION_TYPE_ENUM = [
    "PAGER_DUTY", "SLACK", "DATADOG", "NEW_RELIC", "OPS_GENIE",
    "VICTOR_OPS", "WEBHOOK", "PROMETHEUS", "MICROSOFT_TEAMS",
]


class AtlasListIntegrationsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_integrations"] = Field("list_integrations", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))


class AtlasGetIntegrationConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_integration"] = Field("get_integration", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    integration_id: str = Field(..., title="Integration ID", json_schema_extra=_dyn("integration_id", "integration", depends_on="group_id"))


class AtlasCreateIntegrationConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_integration"] = Field("create_integration", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    integration_type: str = Field(..., title="Integration Type", json_schema_extra={"enum": _INTEGRATION_TYPE_ENUM, "x-enum-searchable": True})
    url: Optional[str] = Field(None, title="URL", description="Webhook URL or endpoint")
    secret: Optional[str] = Field(None, title="Secret", description="HMAC secret for webhook")
    service_key: Optional[str] = Field(None, title="Service Key", description="PagerDuty service key")
    api_key: Optional[str] = Field(None, title="API Key", description="API key for Datadog/New Relic")
    region: Optional[str] = Field(None, title="Region", description="Region for OpsGenie/Datadog")
    routing_key: Optional[str] = Field(None, title="Routing Key", description="VictorOps routing key")
    channel_name: Optional[str] = Field(None, title="Channel Name", description="Slack channel name")


class AtlasUpdateIntegrationConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["update_integration"] = Field("update_integration", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    integration_id: str = Field(..., title="Integration ID", json_schema_extra=_dyn("integration_id", "integration", depends_on="group_id"))
    integration_type: str = Field(..., title="Integration Type", json_schema_extra={"enum": _INTEGRATION_TYPE_ENUM, "x-enum-searchable": True})
    url: Optional[str] = Field(None, title="URL", description="Webhook URL or endpoint")
    secret: Optional[str] = Field(None, title="Secret", description="HMAC secret for webhook")


class AtlasDeleteIntegrationConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_integration"] = Field("delete_integration", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    integration_id: str = Field(..., title="Integration ID", json_schema_extra=_dyn("integration_id", "integration", depends_on="group_id"))


# =============================================================================
# PUSH-BASED LOG EXPORT
# =============================================================================

class AtlasGetLogExportConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_log_export"] = Field("get_log_export", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))


class AtlasCreateLogExportConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_log_export"] = Field("create_log_export", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    aws_s3_bucket_name: str = Field(..., title="AWS S3 Bucket Name")
    iam_role_arn: str = Field(..., title="IAM Role ARN")
    prefix: Optional[str] = Field(None, title="Prefix")


class AtlasUpdateLogExportConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["update_log_export"] = Field("update_log_export", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    aws_s3_bucket_name: Optional[str] = Field(None, title="AWS S3 Bucket Name")
    iam_role_arn: Optional[str] = Field(None, title="IAM Role ARN")
    prefix: Optional[str] = Field(None, title="Prefix")


class AtlasDeleteLogExportConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_log_export"] = Field("delete_log_export", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))


# =============================================================================
# ATLAS USERS
# =============================================================================

class AtlasCreateAtlasUserConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_atlas_user"] = Field("create_atlas_user", title="Operation", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., title="Username", description="Email address for the user")
    password: str = Field(..., title="Password")
    first_name: str = Field(..., title="First Name")
    last_name: str = Field(..., title="Last Name")
    country: str = Field(..., title="Country", description="Two-letter country code e.g. US")
    roles: str = Field(..., title="Roles", description="Array of role objects [{orgId, orgRoles:[]} or {groupId, groupRoles:[]}]", json_schema_extra={"ui:widget": "code_editor"})


class AtlasGetAtlasUserConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_atlas_user"] = Field("get_atlas_user", title="Operation", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., title="User ID")


class AtlasGetAtlasUserByNameConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_atlas_user_by_name"] = Field("get_atlas_user_by_name", title="Operation", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., title="Username")


# =============================================================================
# FEDERATED AUTHENTICATION
# =============================================================================

class AtlasGetFederationSettingsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_federation_settings"] = Field("get_federation_settings", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))


class AtlasListIdentityProvidersConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_identity_providers"] = Field("list_identity_providers", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    federation_settings_id: str = Field(..., title="Federation Settings ID", json_schema_extra=_dyn("federation_settings_id", "federation settings", depends_on="org_id"))
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasCreateIdentityProviderConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_identity_provider"] = Field("create_identity_provider", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    federation_settings_id: str = Field(..., title="Federation Settings ID", json_schema_extra=_dyn("federation_settings_id", "federation settings", depends_on="org_id"))
    display_name: str = Field(..., title="Display Name")
    protocol: str = Field(..., title="Protocol", json_schema_extra={"enum": ["SAML", "OIDC"], "x-enum-searchable": True})
    idp_type: str = Field(..., title="IDP Type", json_schema_extra={"enum": ["WORKFORCE", "WORKLOAD"], "x-enum-searchable": True})
    issuer_uri: Optional[str] = Field(None, title="Issuer URI")
    client_id: Optional[str] = Field(None, title="Client ID")
    requested_scopes: Optional[str] = Field(None, title="Requested Scopes", json_schema_extra={"ui:widget": "code_editor"})
    associated_domains: Optional[str] = Field(None, title="Associated Domains", description="Array of domain strings", json_schema_extra={"ui:widget": "code_editor"})
    sso_url: Optional[str] = Field(None, title="SSO URL")


class AtlasGetIdentityProviderConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_identity_provider"] = Field("get_identity_provider", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    federation_settings_id: str = Field(..., title="Federation Settings ID", json_schema_extra=_dyn("federation_settings_id", "federation settings", depends_on="org_id"))
    idp_id: str = Field(..., title="IDP ID", json_schema_extra=_dyn("idp_id", "identity provider", depends_on="federation_settings_id"))


class AtlasUpdateIdentityProviderConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["update_identity_provider"] = Field("update_identity_provider", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    federation_settings_id: str = Field(..., title="Federation Settings ID", json_schema_extra=_dyn("federation_settings_id", "federation settings", depends_on="org_id"))
    idp_id: str = Field(..., title="IDP ID", json_schema_extra=_dyn("idp_id", "identity provider", depends_on="federation_settings_id"))
    display_name: Optional[str] = Field(None, title="Display Name")
    sso_url: Optional[str] = Field(None, title="SSO URL")
    issuer_uri: Optional[str] = Field(None, title="Issuer URI")
    associated_domains: Optional[str] = Field(None, title="Associated Domains", description="Array of domain strings", json_schema_extra={"ui:widget": "code_editor"})


class AtlasDeleteIdentityProviderConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_identity_provider"] = Field("delete_identity_provider", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    federation_settings_id: str = Field(..., title="Federation Settings ID", json_schema_extra=_dyn("federation_settings_id", "federation settings", depends_on="org_id"))
    idp_id: str = Field(..., title="IDP ID", json_schema_extra=_dyn("idp_id", "identity provider", depends_on="federation_settings_id"))


class AtlasListConnectedOrgConfigsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_connected_org_configs"] = Field("list_connected_org_configs", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    federation_settings_id: str = Field(..., title="Federation Settings ID", json_schema_extra=_dyn("federation_settings_id", "federation settings", depends_on="org_id"))
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasUpdateConnectedOrgConfigConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["update_connected_org_config"] = Field("update_connected_org_config", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    federation_settings_id: str = Field(..., title="Federation Settings ID", json_schema_extra=_dyn("federation_settings_id", "federation settings", depends_on="org_id"))
    connected_org_config_id: str = Field(..., title="Connected Org Config ID", json_schema_extra=_dyn("connected_org_config_id", "connected org config", depends_on="federation_settings_id"))
    identity_provider_id: Optional[str] = Field(None, title="Identity Provider ID")
    domain_restriction_enabled: Optional[str] = Field(None, title="Domain Restriction Enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    domain_allow_list: Optional[str] = Field(None, title="Domain Allow List", json_schema_extra={"ui:widget": "code_editor"})


class AtlasListRoleMappingsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_role_mappings"] = Field("list_role_mappings", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    federation_settings_id: str = Field(..., title="Federation Settings ID", json_schema_extra=_dyn("federation_settings_id", "federation settings", depends_on="org_id"))
    connected_org_config_id: str = Field(..., title="Connected Org Config ID", json_schema_extra=_dyn("connected_org_config_id", "connected org config", depends_on="federation_settings_id"))


class AtlasCreateRoleMappingConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_role_mapping"] = Field("create_role_mapping", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    federation_settings_id: str = Field(..., title="Federation Settings ID", json_schema_extra=_dyn("federation_settings_id", "federation settings", depends_on="org_id"))
    connected_org_config_id: str = Field(..., title="Connected Org Config ID", json_schema_extra=_dyn("connected_org_config_id", "connected org config", depends_on="federation_settings_id"))
    external_group_name: str = Field(..., title="External Group Name")
    role_assignments: str = Field(..., title="Role Assignments", description="Array of role assignment objects [{orgId,role} or {groupId,role}]", json_schema_extra={"ui:widget": "code_editor"})


class AtlasDeleteRoleMappingConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_role_mapping"] = Field("delete_role_mapping", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    federation_settings_id: str = Field(..., title="Federation Settings ID", json_schema_extra=_dyn("federation_settings_id", "federation settings", depends_on="org_id"))
    connected_org_config_id: str = Field(..., title="Connected Org Config ID", json_schema_extra=_dyn("connected_org_config_id", "connected org config", depends_on="federation_settings_id"))
    role_mapping_id: str = Field(..., title="Role Mapping ID")


# =============================================================================
# SECTION F: Monitoring / Billing / Performance Advisor / Alerts / Custom Roles
# =============================================================================

# ─────────────────────────────────────────────
# MONITORING (8 ops)
# ─────────────────────────────────────────────

class AtlasListProcessesConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_processes"] = Field("list_processes", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasGetProcessConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_process"] = Field("get_process", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    process_id: str = Field(..., title="Process ID", description="Process ID in format hostname:port e.g. atlas-abc123-shard-00-00.mongodb.net:27017")


class AtlasGetProcessMeasurementsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_process_measurements"] = Field("get_process_measurements", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    process_id: str = Field(..., title="Process ID", description="Process ID in format hostname:port e.g. atlas-abc123-shard-00-00.mongodb.net:27017")
    granularity: str = Field(..., title="Granularity", json_schema_extra={"enum": ["PT1M", "PT5M", "PT1H", "P1D"], "x-enum-searchable": True})
    period: Optional[str] = Field(None, title="Period", description="ISO 8601 duration e.g. PT8H P1D P7D. Use period OR start+end")
    start_date: Optional[str] = Field(None, title="Start Date", description="ISO 8601 start datetime")
    end_date: Optional[str] = Field(None, title="End Date", description="ISO 8601 end datetime")
    metrics: Optional[str] = Field(None, title="Metrics", description="Comma-separated metric names e.g. CONNECTIONS,OPCOUNTER_CMD. Leave empty for all metrics")


class AtlasGetDatabaseMeasurementsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_database_measurements"] = Field("get_database_measurements", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    process_id: str = Field(..., title="Process ID", description="Process ID in format hostname:port e.g. atlas-abc123-shard-00-00.mongodb.net:27017")
    database_name: str = Field(..., title="Database Name")
    granularity: str = Field(..., title="Granularity", json_schema_extra={"enum": ["PT1M", "PT5M", "PT1H", "P1D"], "x-enum-searchable": True})
    period: Optional[str] = Field(None, title="Period", description="ISO 8601 duration e.g. PT8H P1D P7D. Use period OR start+end")
    start_date: Optional[str] = Field(None, title="Start Date", description="ISO 8601 start datetime")
    end_date: Optional[str] = Field(None, title="End Date", description="ISO 8601 end datetime")
    metrics: Optional[str] = Field(None, title="Metrics", description="Comma-separated: DATABASE_DATA_SIZE,DATABASE_STORAGE_SIZE,DATABASE_INDEX_SIZE,DATABASE_COLLECTION_COUNT,DATABASE_OBJECT_COUNT")


class AtlasGetDiskMeasurementsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_disk_measurements"] = Field("get_disk_measurements", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    process_id: str = Field(..., title="Process ID", description="Process ID in format hostname:port e.g. atlas-abc123-shard-00-00.mongodb.net:27017")
    partition_name: str = Field(..., title="Partition Name", description="Disk partition name e.g. data")
    granularity: str = Field(..., title="Granularity", json_schema_extra={"enum": ["PT1M", "PT5M", "PT1H", "P1D"], "x-enum-searchable": True})
    period: Optional[str] = Field(None, title="Period", description="ISO 8601 duration e.g. PT8H P1D P7D. Use period OR start+end")
    start_date: Optional[str] = Field(None, title="Start Date", description="ISO 8601 start datetime")
    end_date: Optional[str] = Field(None, title="End Date", description="ISO 8601 end datetime")
    metrics: Optional[str] = Field(None, title="Metrics", description="Comma-separated: DISK_PARTITION_IOPS_READ,DISK_PARTITION_IOPS_WRITE,DISK_PARTITION_UTILIZATION,DISK_PARTITION_SPACE_USED,DISK_PARTITION_SPACE_FREE")


class AtlasDownloadClusterLogConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["download_cluster_log"] = Field("download_cluster_log", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    host_name: str = Field(..., title="Host Name", description="Cluster host FQDN e.g. atlas-abc123-shard-00-00.mongodb.net")
    log_name: str = Field(..., title="Log Name", json_schema_extra={"enum": ["mongodb", "mongos", "mongodb-audit-log", "mongos-audit-log"], "x-enum-searchable": True})
    start_date: Optional[int] = Field(None, title="Start Date", description="Unix epoch seconds start")
    end_date: Optional[int] = Field(None, title="End Date", description="Unix epoch seconds end")


class AtlasListProcessesDatabasesConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_processes_databases"] = Field("list_processes_databases", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    process_id: str = Field(..., title="Process ID", description="Process ID in format hostname:port e.g. atlas-abc123-shard-00-00.mongodb.net:27017")
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasListProcessDisksConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_process_disks"] = Field("list_process_disks", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    process_id: str = Field(..., title="Process ID", description="Process ID in format hostname:port e.g. atlas-abc123-shard-00-00.mongodb.net:27017")
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


# ─────────────────────────────────────────────
# BILLING (3 ops)
# ─────────────────────────────────────────────

class AtlasListInvoicesConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_invoices"] = Field("list_invoices", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    status_names: Optional[str] = Field(None, title="Status", description="Filter by invoice status", json_schema_extra={"enum": ["PENDING", "CLOSED", "FORGIVEN", "FAILED", "PAID", "FREE", "PREPAID", "INVOICED"], "x-enum-searchable": True})
    from_date: Optional[str] = Field(None, title="From Date", description="Return invoices with startDate >= this date YYYY-MM-DD")
    to_date: Optional[str] = Field(None, title="To Date", description="Return invoices with endDate <= this date YYYY-MM-DD")
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasGetPendingInvoicesConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_pending_invoices"] = Field("get_pending_invoices", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))


class AtlasGetInvoiceConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_invoice"] = Field("get_invoice", title="Operation", json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", json_schema_extra=_dyn("org_id", "organization"))
    invoice_id: str = Field(..., title="Invoice ID")


# ─────────────────────────────────────────────
# PERFORMANCE ADVISOR (7 ops)
# ─────────────────────────────────────────────

class AtlasListSuggestedIndexesConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_suggested_indexes"] = Field("list_suggested_indexes", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cluster_name: str = Field(..., title="Cluster Name", json_schema_extra=_dyn("cluster_name", "cluster", depends_on="group_id"))
    since: Optional[int] = Field(None, title="Since", description="Start time in milliseconds since epoch")
    until: Optional[int] = Field(None, title="Until", description="End time in milliseconds since epoch")
    namespaces: Optional[str] = Field(None, title="Namespaces", description="Comma-separated namespace filters e.g. mydb.mycollection")


class AtlasListSlowQueryLogsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_slow_query_logs"] = Field("list_slow_query_logs", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    process_id: str = Field(..., title="Process ID", description="Process ID in format hostname:port e.g. atlas-abc123-shard-00-00.mongodb.net:27017")
    since: Optional[int] = Field(None, title="Since", description="Unix epoch milliseconds start")
    duration: Optional[int] = Field(None, title="Duration", description="Window in milliseconds")
    namespaces: Optional[str] = Field(None, title="Namespaces", description="Comma-separated namespace filters")
    n_logs: Optional[int] = Field(20000, title="Max Entries", description="Max entries to return, max 20000")


class AtlasListPerformanceNamespacesConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_performance_namespaces"] = Field("list_performance_namespaces", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cluster_name: str = Field(..., title="Cluster Name", json_schema_extra=_dyn("cluster_name", "cluster", depends_on="group_id"))
    since: Optional[int] = Field(None, title="Since", description="Start time in milliseconds since epoch")
    duration: Optional[int] = Field(None, title="Duration", description="Window in milliseconds")


class AtlasGetSchemaAdviceConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_schema_advice"] = Field("get_schema_advice", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    cluster_name: str = Field(..., title="Cluster Name", json_schema_extra=_dyn("cluster_name", "cluster", depends_on="group_id"))


class AtlasEnableManagedSlowMsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["enable_managed_slow_ms"] = Field("enable_managed_slow_ms", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))


class AtlasDisableManagedSlowMsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["disable_managed_slow_ms"] = Field("disable_managed_slow_ms", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))


class AtlasGetManagedSlowMsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_managed_slow_ms"] = Field("get_managed_slow_ms", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))


# ─────────────────────────────────────────────
# ALERT CONFIGURATIONS (8 ops)
# ─────────────────────────────────────────────

class AtlasListAlertConfigsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_alert_configs"] = Field("list_alert_configs", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasGetAlertConfigConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_alert_config"] = Field("get_alert_config", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    alert_config_id: str = Field(..., title="Alert Config ID")


class AtlasCreateAlertConfigConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_alert_config"] = Field("create_alert_config", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    event_type_name: str = Field(..., title="Event Type Name", description="Event type e.g. REPLICATION_OPLOG_WINDOW_RUNNING_OUT CLUSTER_MONGOS_IS_MISSING NDS_SYSTEM_ALERT")
    enabled: str = Field(..., title="Enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    notifications: str = Field(..., title="Notifications", description="Array of notification objects with typeName: SLACK|DATADOG|PAGER_DUTY|OPS_GENIE|WEBHOOK|EMAIL|GROUP|USER", json_schema_extra={"ui:widget": "code_editor"})
    matchers: Optional[str] = Field(None, title="Matchers", description="Array of {fieldName,operator,value} objects. fieldName: CLUSTER_NAME|REPLICA_SET_NAME|HOSTNAME. operator: EQUALS|CONTAINS|STARTS_WITH|ENDS_WITH", json_schema_extra={"ui:widget": "code_editor"})
    metric_threshold: Optional[str] = Field(None, title="Metric Threshold", description="For metric alerts: {metricName,operator,threshold,units,mode}", json_schema_extra={"ui:widget": "code_editor"})
    threshold: Optional[str] = Field(None, title="Threshold", description="For non-metric alerts: {operator,units,value}", json_schema_extra={"ui:widget": "code_editor"})


class AtlasUpdateAlertConfigConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["update_alert_config"] = Field("update_alert_config", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    alert_config_id: str = Field(..., title="Alert Config ID")
    event_type_name: str = Field(..., title="Event Type Name")
    enabled: str = Field(..., title="Enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    notifications: str = Field(..., title="Notifications", description="Array of notification objects with typeName: SLACK|DATADOG|PAGER_DUTY|OPS_GENIE|WEBHOOK|EMAIL|GROUP|USER", json_schema_extra={"ui:widget": "code_editor"})
    matchers: Optional[str] = Field(None, title="Matchers", description="Array of {fieldName,operator,value} objects. fieldName: CLUSTER_NAME|REPLICA_SET_NAME|HOSTNAME. operator: EQUALS|CONTAINS|STARTS_WITH|ENDS_WITH", json_schema_extra={"ui:widget": "code_editor"})
    metric_threshold: Optional[str] = Field(None, title="Metric Threshold", description="For metric alerts: {metricName,operator,threshold,units,mode}", json_schema_extra={"ui:widget": "code_editor"})
    threshold: Optional[str] = Field(None, title="Threshold", description="For non-metric alerts: {operator,units,value}", json_schema_extra={"ui:widget": "code_editor"})


class AtlasToggleAlertConfigConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["toggle_alert_config"] = Field("toggle_alert_config", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    alert_config_id: str = Field(..., title="Alert Config ID")
    enabled: str = Field(..., title="Enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasDeleteAlertConfigConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_alert_config"] = Field("delete_alert_config", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    alert_config_id: str = Field(..., title="Alert Config ID")


class AtlasGetAlertConfigMatchersConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_alert_config_matchers"] = Field("get_alert_config_matchers", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))


class AtlasListAlertsForConfigConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_alerts_for_config"] = Field("list_alerts_for_config", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    alert_config_id: str = Field(..., title="Alert Config ID")
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


# ─────────────────────────────────────────────
# ALERTS (3 ops)
# ─────────────────────────────────────────────

class AtlasListAlertsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_alerts"] = Field("list_alerts", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    status: Optional[str] = Field(None, title="Status", json_schema_extra={"enum": ["OPEN", "TRACKING", "CLOSED"], "x-enum-searchable": True})
    page_num: int = Field(1, title="Page")
    items_per_page: int = Field(100, title="Per Page", ge=1, le=500)
    fetch_all_pages: str = Field("false", title="Fetch All Pages", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


class AtlasGetAlertConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_alert"] = Field("get_alert", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    alert_id: str = Field(..., title="Alert ID")


class AtlasAcknowledgeAlertConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["acknowledge_alert"] = Field("acknowledge_alert", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    alert_id: str = Field(..., title="Alert ID")
    acknowledged_until: str = Field(..., title="Acknowledged Until", description="ISO 8601 datetime until alert is acknowledged. Set far future to permanently ack")
    acknowledgement_comment: Optional[str] = Field(None, title="Acknowledgement Comment", description="Max 200 chars")
    unacknowledge_alert: Optional[str] = Field(None, title="Unacknowledge Alert", description="Set true to undo acknowledgement", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


# ─────────────────────────────────────────────
# CUSTOM DATABASE ROLES (5 ops)
# ─────────────────────────────────────────────

class AtlasListCustomRolesConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["list_custom_roles"] = Field("list_custom_roles", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))


class AtlasGetCustomRoleConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["get_custom_role"] = Field("get_custom_role", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    role_name: str = Field(..., title="Role Name")


class AtlasCreateCustomRoleConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["create_custom_role"] = Field("create_custom_role", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    role_name: str = Field(..., title="Role Name")
    actions: str = Field(..., title="Actions", description="Array of {action,resources:[{cluster:bool,db,collection}]} objects. Actions: FIND INSERT UPDATE REMOVE CREATE_INDEX DROP_INDEX", json_schema_extra={"ui:widget": "code_editor"})
    inherited_roles: Optional[str] = Field(None, title="Inherited Roles", description='Array of {db,role} objects e.g. [{"db":"admin","role":"readWrite"}]', json_schema_extra={"ui:widget": "code_editor"})


class AtlasUpdateCustomRoleConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["update_custom_role"] = Field("update_custom_role", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    role_name: str = Field(..., title="Role Name")
    actions: Optional[str] = Field(None, title="Actions", json_schema_extra={"ui:widget": "code_editor"})
    inherited_roles: Optional[str] = Field(None, title="Inherited Roles", json_schema_extra={"ui:widget": "code_editor"})


class AtlasDeleteCustomRoleConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["delete_custom_role"] = Field("delete_custom_role", title="Operation", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., title="Project ID", json_schema_extra=_dyn("group_id", "project"))
    role_name: str = Field(..., title="Role Name")


# =============================================================================
# CATEGORY: Triggers
# =============================================================================

class AtlasOnAlertConfig(BaseModel):
    """Webhook push trigger: fires whenever Atlas sends an alert to the registered webhook."""
    model_config = ConfigDict(populate_by_name=True, json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_alert"] = Field(
        "on_alert", title="Operation",
        json_schema_extra={"const": "on_alert", "ui:hidden": True, "x-category": "Triggers",
                           "x-is-trigger": True, "x-display-name": "On Alert"},
    )
    trigger_group_id: str = Field(
        "", title="Project",
        description="Atlas project to register the alert webhook on",
        json_schema_extra=_dyn("trigger_group_id", "project"),
    )
    webhook_url: Optional[str] = Field(
        None, json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True},
    )
    webhook_id: Optional[str] = Field(None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[Union[str, int]] = Field(None, json_schema_extra={"ui:hidden": True})
    signing_secret: Optional[str] = Field(None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(None, json_schema_extra={"ui:hidden": True})


class AtlasOnClusterEventConfig(PollTriggerConfigBase):
    """Poll trigger: fires on cluster lifecycle events (create, delete, pause, ready)."""
    operation: Literal["on_cluster_event"] = Field(
        "on_cluster_event",
        json_schema_extra={"const": "on_cluster_event", "ui:hidden": True, "x-category": "Triggers",
                           "x-is-trigger": True, "x-display-name": "On Cluster Event"},
    )
    trigger_group_id: str = Field(
        "", title="Project",
        description="Atlas project to poll for cluster events",
        json_schema_extra=_dyn("trigger_group_id", "project"),
    )


class AtlasOnBackupEventConfig(PollTriggerConfigBase):
    """Poll trigger: fires on backup and snapshot events."""
    operation: Literal["on_backup_event"] = Field(
        "on_backup_event",
        json_schema_extra={"const": "on_backup_event", "ui:hidden": True, "x-category": "Triggers",
                           "x-is-trigger": True, "x-display-name": "On Backup Event"},
    )
    trigger_group_id: str = Field(
        "", title="Project",
        description="Atlas project to poll for backup and snapshot events",
        json_schema_extra=_dyn("trigger_group_id", "project"),
    )


class AtlasOnMaintenanceEventConfig(PollTriggerConfigBase):
    """Poll trigger: fires when Atlas starts or ends a maintenance window."""
    operation: Literal["on_maintenance_event"] = Field(
        "on_maintenance_event",
        json_schema_extra={"const": "on_maintenance_event", "ui:hidden": True, "x-category": "Triggers",
                           "x-is-trigger": True, "x-display-name": "On Maintenance Event"},
    )
    trigger_group_id: str = Field(
        "", title="Project",
        description="Atlas project to poll for maintenance window events",
        json_schema_extra=_dyn("trigger_group_id", "project"),
    )


class AtlasOnUserEventConfig(PollTriggerConfigBase):
    """Poll trigger: fires when database users are created, updated, or deleted."""
    operation: Literal["on_user_event"] = Field(
        "on_user_event",
        json_schema_extra={"const": "on_user_event", "ui:hidden": True, "x-category": "Triggers",
                           "x-is-trigger": True, "x-display-name": "On Database User Event"},
    )
    trigger_group_id: str = Field(
        "", title="Project",
        description="Atlas project to poll for database user events",
        json_schema_extra=_dyn("trigger_group_id", "project"),
    )


class AtlasOnAlertEventConfig(PollTriggerConfigBase):
    """Poll trigger: fires when Atlas alerts are opened, closed, or acknowledged."""
    operation: Literal["on_alert_event"] = Field(
        "on_alert_event",
        json_schema_extra={"const": "on_alert_event", "ui:hidden": True, "x-category": "Triggers",
                           "x-is-trigger": True, "x-display-name": "On Alert Event"},
    )
    trigger_group_id: str = Field(
        "", title="Project",
        description="Atlas project to poll for alert opened/closed/acknowledged events",
        json_schema_extra=_dyn("trigger_group_id", "project"),
    )


# =============================================================================
# Discriminated union of every Atlas operation config
# =============================================================================

AtlasConfig = Annotated[
    Union[
        # Triggers
        AtlasOnAlertConfig,
        AtlasOnClusterEventConfig,
        AtlasOnBackupEventConfig,
        AtlasOnMaintenanceEventConfig,
        AtlasOnUserEventConfig,
        AtlasOnAlertEventConfig,
        # Clusters
        AtlasListClustersConfig,
        AtlasGetClusterConfig,
        AtlasCreateClusterConfig,
        AtlasUpdateClusterConfig,
        AtlasDeleteClusterConfig,
        AtlasPauseClusterConfig,
        AtlasResumeClusterConfig,
        AtlasTestFailoverConfig,
        AtlasGetClusterAdvancedConfigConfig,
        AtlasUpdateClusterAdvancedConfigConfig,
        # Serverless
        AtlasListServerlessConfig,
        AtlasGetServerlessConfig,
        AtlasCreateServerlessConfig,
        AtlasUpdateServerlessConfig,
        AtlasDeleteServerlessConfig,
        # Flex
        AtlasListFlexClustersConfig,
        AtlasGetFlexClusterConfig,
        AtlasCreateFlexClusterConfig,
        AtlasUpdateFlexClusterConfig,
        AtlasDeleteFlexClusterConfig,
        # Backups
        AtlasGetBackupScheduleConfig,
        AtlasUpdateBackupScheduleConfig,
        AtlasListSnapshotsConfig,
        AtlasGetSnapshotConfig,
        AtlasTakeSnapshotConfig,
        AtlasDeleteSnapshotConfig,
        AtlasListRestoreJobsConfig,
        AtlasGetRestoreJobConfig,
        AtlasCreateRestoreJobConfig,
        AtlasCancelRestoreJobConfig,
        AtlasListExportBucketsConfig,
        AtlasCreateExportJobConfig,
        # Section A: DB Users
        AtlasListDbUsersConfig,
        AtlasGetDbUserConfig,
        AtlasCreateDbUserConfig,
        AtlasUpdateDbUserConfig,
        AtlasDeleteDbUserConfig,
        AtlasListDbUserCertsConfig,
        AtlasCreateDbUserCertConfig,
        # Section A: Access List
        AtlasListAccessListConfig,
        AtlasAddAccessListConfig,
        AtlasGetAccessListEntryConfig,
        AtlasDeleteAccessListEntryConfig,
        # Section A: Peering
        AtlasListPeeringContainersConfig,
        AtlasGetPeeringContainerConfig,
        AtlasCreatePeeringContainerConfig,
        AtlasUpdatePeeringContainerConfig,
        AtlasDeletePeeringContainerConfig,
        AtlasListPeeringConnectionsConfig,
        AtlasGetPeeringConnectionConfig,
        AtlasCreatePeeringConnectionConfig,
        AtlasUpdatePeeringConnectionConfig,
        AtlasDeletePeeringConnectionConfig,
        # Section A: Private Endpoints
        AtlasListPrivateEndpointServicesConfig,
        AtlasCreatePrivateEndpointServiceConfig,
        AtlasGetPrivateEndpointServiceConfig,
        AtlasDeletePrivateEndpointServiceConfig,
        AtlasListPrivateEndpointsConfig,
        AtlasCreatePrivateEndpointConfig,
        AtlasGetPrivateEndpointConfig,
        AtlasDeletePrivateEndpointConfig,
        AtlasGetRegionalizedPrivateEndpointConfig,
        AtlasToggleRegionalizedPrivateEndpointConfig,
        # Section B: Search Indexes
        AtlasListSearchIndexesConfig,
        AtlasGetSearchIndexConfig,
        AtlasCreateSearchIndexConfig,
        AtlasUpdateSearchIndexConfig,
        AtlasDeleteSearchIndexConfig,
        AtlasListSearchIndexByNameConfig,
        AtlasGetSearchDeploymentConfig,
        AtlasCreateSearchDeploymentConfig,
        AtlasUpdateSearchDeploymentConfig,
        AtlasDeleteSearchDeploymentConfig,
        AtlasListSearchAnalyzersConfig,
        # Section B: Online Archive
        AtlasListOnlineArchivesConfig,
        AtlasGetOnlineArchiveConfig,
        AtlasCreateOnlineArchiveConfig,
        AtlasUpdateOnlineArchiveConfig,
        AtlasDeleteOnlineArchiveConfig,
        # Section B: Streams
        AtlasListStreamInstancesConfig,
        AtlasGetStreamInstanceConfig,
        AtlasCreateStreamInstanceConfig,
        AtlasUpdateStreamInstanceConfig,
        AtlasDeleteStreamInstanceConfig,
        AtlasDownloadStreamAuditLogsConfig,
        AtlasListStreamConnectionsConfig,
        AtlasGetStreamConnectionConfig,
        AtlasCreateStreamConnectionConfig,
        AtlasUpdateStreamConnectionConfig,
        AtlasDeleteStreamConnectionConfig,
        AtlasListStreamProcessorsConfig,
        AtlasGetStreamProcessorConfig,
        AtlasCreateStreamProcessorConfig,
        AtlasStartStreamProcessorConfig,
        AtlasStopStreamProcessorConfig,
        AtlasDeleteStreamProcessorConfig,
        # Section B: Data Federation
        AtlasListDataFederationConfig,
        AtlasGetDataFederationConfig,
        AtlasCreateDataFederationConfig,
        AtlasUpdateDataFederationConfig,
        AtlasDeleteDataFederationConfig,
        AtlasCreateDataFederationQueryLimitConfig,
        AtlasListDataFederationQueryLimitsConfig,
        AtlasDeleteDataFederationQueryLimitConfig,
        # Section C: Organizations
        AtlasListOrgsConfig,
        AtlasGetOrgConfig,
        AtlasRenameOrgConfig,
        AtlasDeleteOrgConfig,
        AtlasGetOrgSettingsConfig,
        AtlasUpdateOrgSettingsConfig,
        AtlasListOrgUsersConfig,
        AtlasListOrgInvitationsConfig,
        AtlasInviteToOrgConfig,
        AtlasDeleteOrgInvitationConfig,
        AtlasListOrgApiKeysConfig,
        AtlasCreateOrgApiKeyConfig,
        AtlasDeleteOrgApiKeyConfig,
        # Section C: Projects
        AtlasListProjectsConfig,
        AtlasGetProjectConfig,
        AtlasGetProjectByNameConfig,
        AtlasCreateProjectConfig,
        AtlasDeleteProjectConfig,
        AtlasGetProjectSettingsConfig,
        AtlasUpdateProjectSettingsConfig,
        AtlasListProjectUsersConfig,
        AtlasAddProjectUserConfig,
        AtlasRemoveProjectUserConfig,
        AtlasListProjectInvitationsConfig,
        AtlasInviteToProjectConfig,
        AtlasDeleteProjectInvitationConfig,
        AtlasGetProjectClusterCountConfig,
        AtlasListProjectApiKeysConfig,
        AtlasCreateProjectApiKeyConfig,
        AtlasAssignApiKeyToProjectConfig,
        # Section C: Teams
        AtlasListOrgTeamsConfig,
        AtlasGetOrgTeamConfig,
        AtlasGetTeamByNameConfig,
        AtlasCreateOrgTeamConfig,
        AtlasRenameOrgTeamConfig,
        AtlasDeleteOrgTeamConfig,
        AtlasListTeamUsersConfig,
        AtlasAddTeamUsersConfig,
        AtlasRemoveTeamUserConfig,
        AtlasListProjectTeamsConfig,
        AtlasAddTeamsToProjectConfig,
        AtlasUpdateProjectTeamConfig,
        AtlasRemoveProjectTeamConfig,
        # Section D: Maintenance
        AtlasGetMaintenanceWindowConfig,
        AtlasUpdateMaintenanceWindowConfig,
        AtlasDeferMaintenanceWindowConfig,
        AtlasAutoDeferMaintenanceWindowConfig,
        AtlasResetMaintenanceWindowConfig,
        # Section D: Auditing
        AtlasGetAuditingConfig,
        AtlasUpdateAuditingConfig,
        AtlasGetOrgAuditingConfig,
        # Section D: Encryption
        AtlasGetEncryptionAtRestConfig,
        AtlasUpdateEncryptionAtRestConfig,
        AtlasGetEncryptionAtRestPrivateEndpointConfig,
        # Section D: LDAP
        AtlasGetLdapConfigConfig,
        AtlasSaveLdapConfigConfig,
        AtlasVerifyLdapConfigConfig,
        # Section D: X.509
        AtlasGetX509ConfigConfig,
        AtlasSaveX509ConfigConfig,
        AtlasDisableX509ConfigConfig,
        # Section D: Cloud Provider Access
        AtlasListCloudProviderAccessConfig,
        AtlasCreateCloudProviderAccessConfig,
        AtlasAuthorizeCloudProviderAccessConfig,
        AtlasDeauthorizeCloudProviderAccessConfig,
        # Section D: Global Zones
        AtlasGetManagedNamespacesConfig,
        AtlasAddManagedNamespaceConfig,
        AtlasDeleteManagedNamespaceConfig,
        AtlasGetCustomZoneMappingConfig,
        AtlasAddCustomZoneMappingConfig,
        AtlasDeleteCustomZoneMappingConfig,
        # Section E: Service Accounts
        AtlasListOrgServiceAccountsConfig,
        AtlasCreateOrgServiceAccountConfig,
        AtlasGetOrgServiceAccountConfig,
        AtlasUpdateOrgServiceAccountConfig,
        AtlasDeleteOrgServiceAccountConfig,
        AtlasCreateServiceAccountSecretConfig,
        AtlasDeleteServiceAccountSecretConfig,
        AtlasListProjectServiceAccountsConfig,
        AtlasAddProjectServiceAccountConfig,
        AtlasRemoveProjectServiceAccountConfig,
        # Section E: API Keys
        AtlasGetOrgApiKeyConfig,
        AtlasUpdateOrgApiKeyConfig,
        AtlasGetApiKeyAccessListConfig,
        AtlasAddApiKeyAccessListConfig,
        AtlasDeleteApiKeyAccessListEntryConfig,
        AtlasGetProjectApiKeyDetailConfig,
        AtlasRemoveProjectApiKeyConfig,
        # Section E: Events
        AtlasListOrgEventsConfig,
        AtlasGetOrgEventConfig,
        AtlasListProjectEventsConfig,
        AtlasGetProjectEventConfig,
        # Section E: Access Tracking
        AtlasGetDbAccessHistoryConfig,
        # Section E: Resource Policies
        AtlasListResourcePoliciesConfig,
        AtlasGetResourcePolicyConfig,
        AtlasCreateResourcePolicyConfig,
        AtlasUpdateResourcePolicyConfig,
        AtlasDeleteResourcePolicyConfig,
        AtlasValidateResourcePolicyConfig,
        AtlasListNoncompliantResourcesConfig,
        # Section E: Integrations
        AtlasListIntegrationsConfig,
        AtlasGetIntegrationConfig,
        AtlasCreateIntegrationConfig,
        AtlasUpdateIntegrationConfig,
        AtlasDeleteIntegrationConfig,
        # Section E: Log Export
        AtlasGetLogExportConfig,
        AtlasCreateLogExportConfig,
        AtlasUpdateLogExportConfig,
        AtlasDeleteLogExportConfig,
        # Section E: Atlas Users
        AtlasCreateAtlasUserConfig,
        AtlasGetAtlasUserConfig,
        AtlasGetAtlasUserByNameConfig,
        # Section E: Federated Auth
        AtlasGetFederationSettingsConfig,
        AtlasListIdentityProvidersConfig,
        AtlasCreateIdentityProviderConfig,
        AtlasGetIdentityProviderConfig,
        AtlasUpdateIdentityProviderConfig,
        AtlasDeleteIdentityProviderConfig,
        AtlasListConnectedOrgConfigsConfig,
        AtlasUpdateConnectedOrgConfigConfig,
        AtlasListRoleMappingsConfig,
        AtlasCreateRoleMappingConfig,
        AtlasDeleteRoleMappingConfig,
        # Section F: Monitoring
        AtlasListProcessesConfig,
        AtlasGetProcessConfig,
        AtlasGetProcessMeasurementsConfig,
        AtlasGetDatabaseMeasurementsConfig,
        AtlasGetDiskMeasurementsConfig,
        AtlasDownloadClusterLogConfig,
        AtlasListProcessesDatabasesConfig,
        AtlasListProcessDisksConfig,
        # Section F: Billing
        AtlasListInvoicesConfig,
        AtlasGetPendingInvoicesConfig,
        AtlasGetInvoiceConfig,
        # Section F: Performance Advisor
        AtlasListSuggestedIndexesConfig,
        AtlasListSlowQueryLogsConfig,
        AtlasListPerformanceNamespacesConfig,
        AtlasGetSchemaAdviceConfig,
        AtlasEnableManagedSlowMsConfig,
        AtlasDisableManagedSlowMsConfig,
        AtlasGetManagedSlowMsConfig,
        # Section F: Alert Configs
        AtlasListAlertConfigsConfig,
        AtlasGetAlertConfigConfig,
        AtlasCreateAlertConfigConfig,
        AtlasUpdateAlertConfigConfig,
        AtlasToggleAlertConfigConfig,
        AtlasDeleteAlertConfigConfig,
        AtlasGetAlertConfigMatchersConfig,
        AtlasListAlertsForConfigConfig,
        # Section F: Alerts
        AtlasListAlertsConfig,
        AtlasGetAlertConfig,
        AtlasAcknowledgeAlertConfig,
        # Section F: Custom Roles
        AtlasListCustomRolesConfig,
        AtlasGetCustomRoleConfig,
        AtlasCreateCustomRoleConfig,
        AtlasUpdateCustomRoleConfig,
        AtlasDeleteCustomRoleConfig,
    ],
    Discriminator("operation"),
]


class AtlasNodeConfig(NodeConfig[AtlasConfig, AtlasAdminCredential]):
    """Full configuration for the Atlas Admin node including credentials."""

    pass


# =============================================================================
# Node implementation
# =============================================================================

class AtlasAdminNode(ExternalWebhookTriggerMixin, ScheduledPollTriggerMixin, WorkflowNode):
    """MongoDB Atlas Administration API automation node.

    Full coverage of the Atlas Admin API v2: clusters, serverless/flex, backups,
    database users, network access, search, streams, data federation, orgs,
    projects, teams, security, billing, monitoring, alerts and more — plus an
    alert-webhook push trigger and an events poll trigger.
    """

    type = "automation-atlas-admin"
    credential_model = AtlasAdminCredential
    config_model = AtlasConfig

    TRIGGER_OPERATIONS = {
        "on_alert",
        "on_cluster_event", "on_backup_event", "on_maintenance_event",
        "on_user_event", "on_alert_event",
    }

    edit_examples = [
        "List all clusters in my Atlas project",
        "Pause the production cluster every night",
        "Create a database user with readWrite on the app database",
        "Take an on-demand backup snapshot of a cluster",
        "Trigger a workflow when an Atlas alert opens",
    ]

    @classmethod
    def get_config_model(cls):
        return AtlasNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (projects, orgs, clusters)
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
        cred = credential_data or {}
        client_id = cred.get("client_id")
        client_secret = cred.get("client_secret")
        if not (client_id and client_secret):
            return {"options": []}
        try:
            token = await _get_atlas_token(client_id, client_secret)
        except Exception:
            return {"options": []}

        ctx = context or {}

        if field_name in ("project_id", "group_id", "trigger_group_id"):
            res = await _atlas_request(
                token, "GET", "/groups", params={"itemsPerPage": 500}, action_name="load_projects"
            )
            items = (res.get("data") or {}).get("results") or []
            return {"options": [
                {"label": i.get("name") or i.get("id"), "value": i.get("id")}
                for i in items if i.get("id")
            ]}

        if field_name == "org_id":
            res = await _atlas_request(
                token, "GET", "/orgs", params={"itemsPerPage": 500}, action_name="load_orgs"
            )
            items = (res.get("data") or {}).get("results") or []
            return {"options": [
                {"label": i.get("name") or i.get("id"), "value": i.get("id")}
                for i in items if i.get("id")
            ]}

        if field_name in ("cluster_name",):
            gid = ctx.get("project_id") or ctx.get("group_id")
            if not gid:
                return {"options": []}
            res = await _atlas_request(
                token, "GET", f"/groups/{gid}/clusters", params={"itemsPerPage": 500},
                action_name="load_clusters",
            )
            items = (res.get("data") or {}).get("results") or []
            return {"options": [
                {"label": i.get("name"), "value": i.get("name")}
                for i in items if i.get("name")
            ]}

        return {"options": []}

    # ------------------------------------------------------------------
    # Webhook trigger (alert integration webhook)
    # ------------------------------------------------------------------
    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "trigger_group_id": (config or {}).get("trigger_group_id"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        gid = (config or {}).get("trigger_group_id") or ""
        if not gid:
            raise ValueError("Select an Atlas project for the alert trigger")
        token = await _get_atlas_token(credential["client_id"], credential["client_secret"])
        secret = secrets.token_hex(24)
        res = await _atlas_request(
            token, "POST", f"/groups/{gid}/integrations/WEBHOOK",
            json_body={"type": "WEBHOOK", "url": webhook_url, "secret": secret},
            action_name="register_alert_webhook",
        )
        if res.get("status") != "success":
            raise ValueError(f"Atlas alert webhook registration failed: {res.get('error')}")
        return {"external_webhook_id": "WEBHOOK", "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        if not credential:
            return
        gid = (config or {}).get("trigger_group_id") or ""
        if not gid:
            return
        token = await _get_atlas_token(credential["client_id"], credential["client_secret"])
        await _atlas_request(
            token, "DELETE", f"/groups/{gid}/integrations/WEBHOOK",
            action_name="unregister_alert_webhook",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        secret = (config or {}).get("signing_secret")
        if not secret:
            # No secret stored — security is the unguessable per-node webhook URL.
            return True
        provided = headers.get("X-MMS-Signature") or headers.get("x-mms-signature")
        if not provided:
            return True
        expected = hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
        return hmac.compare_digest(expected, provided)

    # ------------------------------------------------------------------
    # Trigger payload routing
    # ------------------------------------------------------------------
    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        """Return None for poll triggers (execute() does the API fetch).
        Pass through the payload for the on_alert webhook trigger."""
        op = (config or {}).get("operation", "")
        if op in _POLL_EVENT_MAP:
            return None
        return payload

    # ------------------------------------------------------------------
    # Poll trigger: fetch and deduplicate Atlas events
    # ------------------------------------------------------------------
    async def _poll_atlas_events(
        self, token: str, gid: str, event_types: set, op: str
    ) -> Dict[str, Any]:
        """Fetch the 100 most recent project events, filter by type, return only unseen."""
        result = await _atlas_request(
            token, "GET", f"/groups/{gid}/events",
            params={"itemsPerPage": 100},
            action_name=op,
        )
        if result.get("status") != "success":
            return result
        all_events = (result.get("data") or {}).get("results") or []
        filtered = [e for e in all_events if e.get("eventTypeName") in event_types]
        fresh = await self._filter_unseen(filtered, lambda e: e.get("id"))
        self._poll_emitted_count = len(fresh)
        return {
            "status": "success",
            "action": op,
            "events": fresh,
            "count": len(fresh),
            "timing_ms": result.get("timing_ms", {}),
        }

    # ------------------------------------------------------------------
    # Pagination helper
    # ------------------------------------------------------------------
    async def _paginate(
        self, token: str, endpoint: str, params: Optional[Dict[str, Any]], action_name: str,
        api_version: str = ATLAS_API_VERSION,
    ) -> Dict[str, Any]:
        """Follow Atlas ``pageNum`` pagination and aggregate ``results``."""
        params = dict(params or {})
        params.pop("fetch_all_pages", None)
        per_page = params.get("itemsPerPage") or 100
        params["itemsPerPage"] = per_page
        page = 1
        aggregated: List[Any] = []
        last: Optional[Dict[str, Any]] = None
        while True:
            params["pageNum"] = page
            res = await _atlas_request(token, "GET", endpoint, params=params, action_name=action_name, api_version=api_version)
            if res.get("status") != "success":
                return res
            last = res
            data = res.get("data") or {}
            batch = data.get("results") if isinstance(data, dict) else None
            if not batch:
                break
            aggregated.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
            if page > 100:
                break
        return {
            "status": "success",
            "action": action_name,
            "data": {"results": aggregated, "totalCount": len(aggregated)},
            "status_code": 200,
            "timing_ms": (last or {}).get("timing_ms", {}),
        }

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        cfg = self.config
        if not cfg or not isinstance(cfg, AtlasNodeConfig):
            raise ValueError("Valid configuration is required")
        c = cfg.config
        op = c.operation

        # on_alert (webhook trigger): payload is passed through by resolve_trigger_payload;
        # execute() is only reached on a manual run (no real webhook payload).
        if op == "on_alert":
            return {
                "status": "success",
                "action": op,
                "data": {**inputs},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        # Poll triggers: authenticate and call the Atlas Events API.
        if op in _POLL_EVENT_MAP:
            creds = cfg.credentials
            if not creds:
                raise ValueError(
                    "Credentials are required. Add your Atlas Service Account Client ID and Secret."
                )
            token = await _get_atlas_token(creds.client_id, creds.client_secret)
            gid = getattr(c, "trigger_group_id", "") or ""
            if not gid:
                raise ValueError("Select an Atlas project for the trigger")
            result = await self._poll_atlas_events(token, gid, _POLL_EVENT_MAP[op], op)
            result.setdefault("timing_ms", {})["total"] = round((time.time() - start_time) * 1000, 2)
            return result

        creds = cfg.credentials
        if not creds:
            raise ValueError(
                "Credentials are required. Add your Atlas Service Account Client ID and Secret."
            )
        token = await _get_atlas_token(creds.client_id, creds.client_secret)

        gid = getattr(c, "group_id", "") or getattr(c, "project_id", "") or ""
        org = getattr(c, "org_id", "") or ""
        cluster = getattr(c, "cluster_name", "") or ""

        method, endpoint, params, body = self._build_request(c, op, gid, org, cluster)
        api_version = OP_VERSION_OVERRIDES.get(op, ATLAS_API_VERSION)

        if method == "GET" and _tf(getattr(c, "fetch_all_pages", "false")):
            result = await self._paginate(token, endpoint, params, op, api_version=api_version)
        else:
            result = await _atlas_request(
                token, method, endpoint, params=params, json_body=body, action_name=op,
                api_version=api_version,
            )

        result.setdefault("timing_ms", {})["total"] = round((time.time() - start_time) * 1000, 2)
        return result

    def _build_request(self, c: Any, op: str, gid: str, org: str, cluster: str):
        """Resolve an operation to (method, endpoint, params, json_body).

        Every non-trigger operation has an explicit branch here.
        """
        p = _pg(c)

        # ---- CLUSTERS ----
        if op == "list_clusters":
            return "GET", f"/groups/{gid}/clusters", p, None
        if op == "get_cluster":
            return "GET", f"/groups/{gid}/clusters/{cluster}", None, None
        if op == "create_cluster":
            body = {
                "name": c.cluster_name,
                "clusterType": c.cluster_type,
                "mongoDBMajorVersion": c.mongo_db_major_version,
                "terminationProtectionEnabled": _tf(c.termination_protection),
                "backupEnabled": _tf(c.backup_enabled),
                "replicationSpecs": [{
                    "regionConfigs": [{
                        "providerName": c.provider,
                        "regionName": c.region_name,
                        "priority": 7,
                        "electableSpecs": {
                            "instanceSize": c.instance_size,
                            "nodeCount": int(c.replication_factor),
                        },
                    }],
                }],
            }
            if c.disk_size_gb:
                body["diskSizeGB"] = float(c.disk_size_gb)
            return "POST", f"/groups/{gid}/clusters", None, body
        if op == "update_cluster":
            return "PATCH", f"/groups/{gid}/clusters/{cluster}", None, _pj(c.body_json)
        if op == "delete_cluster":
            return "DELETE", f"/groups/{gid}/clusters/{cluster}", None, None
        if op == "pause_cluster":
            return "PATCH", f"/groups/{gid}/clusters/{cluster}", None, {"paused": True}
        if op == "resume_cluster":
            return "PATCH", f"/groups/{gid}/clusters/{cluster}", None, {"paused": False}
        if op == "test_failover":
            return "POST", f"/groups/{gid}/clusters/{cluster}/restartPrimaries", None, None
        if op == "get_cluster_advanced_config":
            return "GET", f"/groups/{gid}/clusters/{cluster}/processArgs", None, None
        if op == "update_cluster_advanced_config":
            return "PATCH", f"/groups/{gid}/clusters/{cluster}/processArgs", None, _pj(c.body_json)

        # ---- SERVERLESS ----
        if op == "list_serverless":
            return "GET", f"/groups/{gid}/serverless", None, None
        if op == "get_serverless":
            return "GET", f"/groups/{gid}/serverless/{c.serverless_name}", None, None
        if op == "create_serverless":
            return "POST", f"/groups/{gid}/serverless", None, {
                "name": c.serverless_name,
                "providerSettings": {
                    "providerName": "SERVERLESS",
                    "backingProviderName": c.provider,
                    "regionName": c.region_name,
                },
                "serverlessBackupOptions": {"serverlessContinuousBackupEnabled": _tf(c.backup_enabled)},
            }
        if op == "update_serverless":
            return "PATCH", f"/groups/{gid}/serverless/{c.serverless_name}", None, {
                "terminationProtectionEnabled": _tf(c.termination_protection),
                "serverlessBackupOptions": {"serverlessContinuousBackupEnabled": _tf(c.backup_enabled)},
            }
        if op == "delete_serverless":
            return "DELETE", f"/groups/{gid}/serverless/{c.serverless_name}", None, None

        # ---- FLEX ----
        if op == "list_flex_clusters":
            return "GET", f"/groups/{gid}/flexClusters", None, None
        if op == "get_flex_cluster":
            return "GET", f"/groups/{gid}/flexClusters/{cluster}", None, None
        if op == "create_flex_cluster":
            return "POST", f"/groups/{gid}/flexClusters", None, {
                "name": c.cluster_name,
                "providerSettings": {
                    "backingProviderName": c.backing_provider,
                    "regionName": c.region_name,
                },
            }
        if op == "update_flex_cluster":
            return "PATCH", f"/groups/{gid}/flexClusters/{cluster}", None, _pj(c.body_json)
        if op == "delete_flex_cluster":
            return "DELETE", f"/groups/{gid}/flexClusters/{cluster}", None, None

        # ---- BACKUPS ----
        if op == "get_backup_schedule":
            return "GET", f"/groups/{gid}/clusters/{cluster}/backup/schedule", None, None
        if op == "update_backup_schedule":
            body: Dict[str, Any] = {
                "policies": [{
                    "policyItems": [{
                        "frequencyType": c.frequency_type,
                        "frequencyInterval": int(c.frequency_interval),
                        "retentionValue": int(c.retention_value),
                        "retentionUnit": c.retention_unit,
                    }],
                }],
            }
            if c.reference_hour_of_day is not None and c.reference_hour_of_day != "":
                body["referenceHourOfDay"] = int(c.reference_hour_of_day)
            if c.reference_minute_of_hour is not None and c.reference_minute_of_hour != "":
                body["referenceMinuteOfHour"] = int(c.reference_minute_of_hour)
            return "PATCH", f"/groups/{gid}/clusters/{cluster}/backup/schedule", None, body
        if op == "list_snapshots":
            return "GET", f"/groups/{gid}/clusters/{cluster}/backup/snapshots", p, None
        if op == "get_snapshot":
            return "GET", f"/groups/{gid}/clusters/{cluster}/backup/snapshots/{c.snapshot_id}", None, None
        if op == "take_snapshot":
            return "POST", f"/groups/{gid}/clusters/{cluster}/backup/snapshots", None, {
                "description": c.description,
                "retentionInDays": int(c.retention_in_days),
            }
        if op == "delete_snapshot":
            return "DELETE", f"/groups/{gid}/clusters/{cluster}/backup/snapshots/{c.snapshot_id}", None, None
        if op == "list_restore_jobs":
            return "GET", f"/groups/{gid}/clusters/{cluster}/backup/restoreJobs", None, None
        if op == "get_restore_job":
            return "GET", f"/groups/{gid}/clusters/{cluster}/backup/restoreJobs/{c.restore_job_id}", None, None
        if op == "create_restore_job":
            body = {"deliveryType": c.delivery_type}
            if c.target_cluster_name:
                body["targetClusterName"] = c.target_cluster_name
            if c.target_project_id:
                body["targetGroupId"] = c.target_project_id
            if c.snapshot_id:
                body["snapshotId"] = c.snapshot_id
            if c.oplog_ts:
                body["oplogTs"] = int(c.oplog_ts)
            if c.point_in_time_utc_seconds:
                body["pointInTimeUTCSeconds"] = int(c.point_in_time_utc_seconds)
            return "POST", f"/groups/{gid}/clusters/{cluster}/backup/restoreJobs", None, body
        if op == "cancel_restore_job":
            return "DELETE", f"/groups/{gid}/clusters/{cluster}/backup/restoreJobs/{c.restore_job_id}", None, None
        if op == "list_export_buckets":
            return "GET", f"/groups/{gid}/backup/exportBuckets", None, None
        if op == "create_export_job":
            body = {"exportBucketId": c.export_bucket_id}
            if c.custom_data:
                body["customData"] = _pj(c.custom_data)
            return "POST", f"/groups/{gid}/clusters/{cluster}/backup/exports", None, body

        # ---- DB USERS ----
        if op == "list_db_users":
            return "GET", f"/groups/{gid}/databaseUsers", p, None
        if op == "get_db_user":
            return "GET", f"/groups/{gid}/databaseUsers/{c.database_name}/{c.username}", None, None
        if op == "create_db_user":
            body = {
                "groupId": gid,
                "username": c.username,
                "databaseName": c.database_name,
                "roles": _pj(c.roles) or [],
            }
            if c.password:
                body["password"] = c.password
            if c.aws_iam_type:
                body["awsIAMType"] = c.aws_iam_type
            if c.x509_type:
                body["x509Type"] = c.x509_type
            if c.ldap_auth_type:
                body["ldapAuthType"] = c.ldap_auth_type
            if c.scopes:
                body["scopes"] = _pj(c.scopes)
            if c.labels:
                body["labels"] = _pj(c.labels)
            return "POST", f"/groups/{gid}/databaseUsers", None, body
        if op == "update_db_user":
            body = {}
            if c.password:
                body["password"] = c.password
            if c.roles:
                body["roles"] = _pj(c.roles)
            if c.scopes:
                body["scopes"] = _pj(c.scopes)
            return "PATCH", f"/groups/{gid}/databaseUsers/{c.database_name}/{c.username}", None, body
        if op == "delete_db_user":
            return "DELETE", f"/groups/{gid}/databaseUsers/{c.database_name}/{c.username}", None, None
        if op == "list_db_user_certs":
            return "GET", f"/groups/{gid}/databaseUsers/{c.username}/certs", None, None
        if op == "create_db_user_cert":
            return "POST", f"/groups/{gid}/databaseUsers/{c.username}/certs", None, {
                "monthsUntilExpiration": c.months_until_expiration,
            }

        # ---- ACCESS LIST ----
        if op == "list_access_list":
            return "GET", f"/groups/{gid}/accessList", p, None
        if op == "add_access_list":
            return "POST", f"/groups/{gid}/accessList", None, _pj(c.entries)
        if op == "get_access_list_entry":
            return "GET", f"/groups/{gid}/accessList/{c.entry_value}", None, None
        if op == "delete_access_list_entry":
            return "DELETE", f"/groups/{gid}/accessList/{c.entry_value}", None, None

        # ---- PEERING ----
        if op == "list_peering_containers":
            params = {**p}
            if c.provider_name:
                params["providerName"] = c.provider_name
            return "GET", f"/groups/{gid}/containers", params, None
        if op == "get_peering_container":
            return "GET", f"/groups/{gid}/containers/{c.container_id}", None, None
        if op == "create_peering_container":
            return "POST", f"/groups/{gid}/containers", None, {
                "providerName": c.provider_name,
                "atlasCidrBlock": c.atlas_cidr_block,
                "regionName": c.region_name,
            }
        if op == "update_peering_container":
            return "PATCH", f"/groups/{gid}/containers/{c.container_id}", None, {
                "atlasCidrBlock": c.atlas_cidr_block,
            }
        if op == "delete_peering_container":
            return "DELETE", f"/groups/{gid}/containers/{c.container_id}", None, None
        if op == "list_peering_connections":
            params = {**p}
            if c.provider_name:
                params["providerName"] = c.provider_name
            return "GET", f"/groups/{gid}/peers", params, None
        if op == "get_peering_connection":
            return "GET", f"/groups/{gid}/peers/{c.peer_id}", None, None
        if op == "create_peering_connection":
            body = {"providerName": c.provider_name, "containerId": c.container_id}
            extra = _pj(c.peering_body)
            if isinstance(extra, dict):
                body.update(extra)
            return "POST", f"/groups/{gid}/peers", None, body
        if op == "update_peering_connection":
            return "PATCH", f"/groups/{gid}/peers/{c.peer_id}", None, {
                "routeTableCidrBlock": c.route_table_cidr_block,
            }
        if op == "delete_peering_connection":
            return "DELETE", f"/groups/{gid}/peers/{c.peer_id}", None, None

        # ---- PRIVATE ENDPOINTS ----
        if op == "list_private_endpoint_services":
            return "GET", f"/groups/{gid}/privateEndpoint/{c.cloud_provider}/endpointService", None, None
        if op == "create_private_endpoint_service":
            return "POST", f"/groups/{gid}/privateEndpoint/endpointService", None, {
                "providerName": c.cloud_provider,
                "region": c.region,
            }
        if op == "get_private_endpoint_service":
            return "GET", f"/groups/{gid}/privateEndpoint/{c.cloud_provider}/endpointService/{c.endpoint_service_id}", None, None
        if op == "delete_private_endpoint_service":
            return "DELETE", f"/groups/{gid}/privateEndpoint/{c.cloud_provider}/endpointService/{c.endpoint_service_id}", None, None
        if op == "list_private_endpoints":
            return "GET", f"/groups/{gid}/privateEndpoint/{c.cloud_provider}/endpointService/{c.endpoint_service_id}/endpoint", None, None
        if op == "create_private_endpoint":
            return "POST", f"/groups/{gid}/privateEndpoint/{c.cloud_provider}/endpointService/{c.endpoint_service_id}/endpoint", None, _pj(c.endpoint_body)
        if op == "get_private_endpoint":
            return "GET", f"/groups/{gid}/privateEndpoint/{c.cloud_provider}/endpointService/{c.endpoint_service_id}/endpoint/{c.endpoint_id}", None, None
        if op == "delete_private_endpoint":
            return "DELETE", f"/groups/{gid}/privateEndpoint/{c.cloud_provider}/endpointService/{c.endpoint_service_id}/endpoint/{c.endpoint_id}", None, None
        if op == "get_regionalized_private_endpoint":
            return "GET", f"/groups/{gid}/privateEndpoint/regionalMode", None, None
        if op == "toggle_regionalized_private_endpoint":
            return "PATCH", f"/groups/{gid}/privateEndpoint/regionalMode", None, {"enabled": _tf(c.enabled)}

        # ---- SEARCH INDEXES ----
        if op == "list_search_indexes":
            return "GET", f"/groups/{gid}/clusters/{cluster}/search/indexes/{c.database_name}/{c.collection_name}", None, None
        if op == "get_search_index":
            return "GET", f"/groups/{gid}/clusters/{cluster}/search/indexes/{c.index_id}", None, None
        if op == "create_search_index":
            return "POST", f"/groups/{gid}/clusters/{cluster}/search/indexes", None, _pj(c.index_definition)
        if op == "update_search_index":
            return "PATCH", f"/groups/{gid}/clusters/{cluster}/search/indexes/{c.index_id}", None, _pj(c.index_definition)
        if op == "delete_search_index":
            return "DELETE", f"/groups/{gid}/clusters/{cluster}/search/indexes/{c.index_id}", None, None
        if op == "list_search_index_by_name":
            return "GET", f"/groups/{gid}/clusters/{cluster}/search/indexes/{c.database_name}/{c.collection_name}/{c.index_name}", None, None
        if op == "get_search_deployment":
            return "GET", f"/groups/{gid}/clusters/{cluster}/search/deployment", None, None
        if op == "create_search_deployment":
            return "POST", f"/groups/{gid}/clusters/{cluster}/search/deployment", None, {"specs": _pj(c.specs)}
        if op == "update_search_deployment":
            return "PATCH", f"/groups/{gid}/clusters/{cluster}/search/deployment", None, {"specs": _pj(c.specs)}
        if op == "delete_search_deployment":
            return "DELETE", f"/groups/{gid}/clusters/{cluster}/search/deployment", None, None
        if op == "list_search_analyzers":
            return "GET", f"/groups/{gid}/clusters/{cluster}/search/analyzers", None, None

        # ---- ONLINE ARCHIVE ----
        if op == "list_online_archives":
            return "GET", f"/groups/{gid}/clusters/{cluster}/onlineArchives", p, None
        if op == "get_online_archive":
            return "GET", f"/groups/{gid}/clusters/{cluster}/onlineArchives/{c.archive_id}", None, None
        if op == "create_online_archive":
            criteria = {"type": "DATE", "dateField": c.date_field, "expireAfterDays": c.expire_after_days}
            if c.date_format:
                criteria["dateFormat"] = c.date_format
            body = {"dbName": c.db_name, "collName": c.coll_name, "criteria": criteria}
            if c.partition_fields:
                body["partitionFields"] = _pj(c.partition_fields)
            return "POST", f"/groups/{gid}/clusters/{cluster}/onlineArchives", None, body
        if op == "update_online_archive":
            return "PATCH", f"/groups/{gid}/clusters/{cluster}/onlineArchives/{c.archive_id}", None, {
                "criteria": {"type": "DATE", "expireAfterDays": c.expire_after_days},
            }
        if op == "delete_online_archive":
            return "DELETE", f"/groups/{gid}/clusters/{cluster}/onlineArchives/{c.archive_id}", None, None

        # ---- STREAMS ----
        if op == "list_stream_instances":
            return "GET", f"/groups/{gid}/streams", p, None
        if op == "get_stream_instance":
            return "GET", f"/groups/{gid}/streams/{c.tenant_name}", None, None
        if op == "create_stream_instance":
            body = {"name": c.name, "dataProcessRegion": _pj(c.data_process_region)}
            if c.stream_config:
                body["streamConfig"] = _pj(c.stream_config)
            return "POST", f"/groups/{gid}/streams", None, body
        if op == "update_stream_instance":
            body = {}
            if c.data_process_region:
                body["dataProcessRegion"] = _pj(c.data_process_region)
            if c.stream_config:
                body["streamConfig"] = _pj(c.stream_config)
            return "PATCH", f"/groups/{gid}/streams/{c.tenant_name}", None, body
        if op == "delete_stream_instance":
            return "DELETE", f"/groups/{gid}/streams/{c.tenant_name}", None, None
        if op == "download_stream_audit_logs":
            params = {}
            if c.start_date:
                params["startDate"] = c.start_date
            if c.end_date:
                params["endDate"] = c.end_date
            return "GET", f"/groups/{gid}/streams/{c.tenant_name}/auditLogs", params, None
        if op == "list_stream_connections":
            return "GET", f"/groups/{gid}/streams/{c.tenant_name}/connections", p, None
        if op == "get_stream_connection":
            return "GET", f"/groups/{gid}/streams/{c.tenant_name}/connections/{c.connection_name}", None, None
        if op == "create_stream_connection":
            return "POST", f"/groups/{gid}/streams/{c.tenant_name}/connections", None, _pj(c.connection_definition)
        if op == "update_stream_connection":
            return "PATCH", f"/groups/{gid}/streams/{c.tenant_name}/connections/{c.connection_name}", None, _pj(c.connection_definition)
        if op == "delete_stream_connection":
            return "DELETE", f"/groups/{gid}/streams/{c.tenant_name}/connections/{c.connection_name}", None, None
        if op == "list_stream_processors":
            return "GET", f"/groups/{gid}/streams/{c.tenant_name}/processor", p, None
        if op == "get_stream_processor":
            return "GET", f"/groups/{gid}/streams/{c.tenant_name}/processor/{c.processor_name}", None, None
        if op == "create_stream_processor":
            return "POST", f"/groups/{gid}/streams/{c.tenant_name}/processor", None, _pj(c.processor_definition)
        if op == "start_stream_processor":
            return "POST", f"/groups/{gid}/streams/{c.tenant_name}/processor/{c.processor_name}:start", None, None
        if op == "stop_stream_processor":
            return "POST", f"/groups/{gid}/streams/{c.tenant_name}/processor/{c.processor_name}:stop", None, None
        if op == "delete_stream_processor":
            return "DELETE", f"/groups/{gid}/streams/{c.tenant_name}/processor/{c.processor_name}", None, None

        # ---- DATA FEDERATION ----
        if op == "list_data_federation":
            params = {}
            if c.fed_type:
                params["type"] = c.fed_type
            return "GET", f"/groups/{gid}/dataFederation", params, None
        if op == "get_data_federation":
            return "GET", f"/groups/{gid}/dataFederation/{c.tenant_name}", None, None
        if op == "create_data_federation":
            return "POST", f"/groups/{gid}/dataFederation", None, _pj(c.tenant_definition)
        if op == "update_data_federation":
            return "PATCH", f"/groups/{gid}/dataFederation/{c.tenant_name}", None, _pj(c.tenant_definition)
        if op == "delete_data_federation":
            return "DELETE", f"/groups/{gid}/dataFederation/{c.tenant_name}", None, None
        if op == "create_data_federation_query_limit":
            return "PATCH", f"/groups/{gid}/dataFederation/{c.tenant_name}/limits/{c.limit_name}", None, {
                "overrunPolicy": "BLOCK",
                "value": c.limit_value,
            }
        if op == "list_data_federation_query_limits":
            return "GET", f"/groups/{gid}/dataFederation/{c.tenant_name}/limits", None, None
        if op == "delete_data_federation_query_limit":
            return "DELETE", f"/groups/{gid}/dataFederation/{c.tenant_name}/limits/{c.limit_name}", None, None

        # ---- ORGANIZATIONS ----
        if op == "list_orgs":
            params = {**p}
            if c.name:
                params["name"] = c.name
            return "GET", "/orgs", params, None
        if op == "get_org":
            return "GET", f"/orgs/{org}", None, None
        if op == "rename_org":
            return "PATCH", f"/orgs/{org}", None, {"name": c.name}
        if op == "delete_org":
            return "DELETE", f"/orgs/{org}", None, None
        if op == "get_org_settings":
            return "GET", f"/orgs/{org}/settings", None, None
        if op == "update_org_settings":
            body = {}
            if c.api_access_list_required is not None:
                body["apiAccessListRequired"] = _tf(c.api_access_list_required)
            if c.multi_factor_auth_required is not None:
                body["multiFactorAuthRequired"] = _tf(c.multi_factor_auth_required)
            if c.restrict_employee_access is not None:
                body["restrictEmployeeAccess"] = _tf(c.restrict_employee_access)
            return "PATCH", f"/orgs/{org}/settings", None, body
        if op == "list_org_users":
            return "GET", f"/orgs/{org}/users", p, None
        if op == "list_org_invitations":
            params = {}
            if c.username:
                params["username"] = c.username
            return "GET", f"/orgs/{org}/invites", params, None
        if op == "invite_to_org":
            body = {"username": c.username, "roles": _pj(c.roles)}
            if c.team_ids:
                body["teamIds"] = _pj(c.team_ids)
            return "POST", f"/orgs/{org}/invites", None, body
        if op == "delete_org_invitation":
            return "DELETE", f"/orgs/{org}/invites/{c.invitation_id}", None, None
        if op == "list_org_api_keys":
            return "GET", f"/orgs/{org}/apiKeys", p, None
        if op == "create_org_api_key":
            return "POST", f"/orgs/{org}/apiKeys", None, {"desc": c.description, "roles": _pj(c.roles)}
        if op == "delete_org_api_key":
            return "DELETE", f"/orgs/{org}/apiKeys/{c.api_user_id}", None, None

        # ---- PROJECTS ----
        if op == "list_projects":
            return "GET", "/groups", p, None
        if op == "get_project":
            return "GET", f"/groups/{gid}", None, None
        if op == "get_project_by_name":
            return "GET", f"/groups/byName/{c.group_name}", None, None
        if op == "create_project":
            params = {}
            body = {"name": c.name, "orgId": c.org_id}
            if c.with_default_alerts_settings is not None:
                body["withDefaultAlertsSettings"] = _tf(c.with_default_alerts_settings)
            return "POST", "/groups", params, body
        if op == "delete_project":
            return "DELETE", f"/groups/{gid}", None, None
        if op == "get_project_settings":
            return "GET", f"/groups/{gid}/settings", None, None
        if op == "update_project_settings":
            body = {}
            for cfg_field, api_field in [
                ("is_performance_advisor_enabled", "isPerformanceAdvisorEnabled"),
                ("is_schema_advisor_enabled", "isSchemaAdvisorEnabled"),
                ("is_realtime_performance_panel_enabled", "isRealtimePerformancePanelEnabled"),
                ("is_data_explorer_enabled", "isDataExplorerEnabled"),
                ("is_extended_storage_sizes_enabled", "isExtendedStorageSizesEnabled"),
            ]:
                val = getattr(c, cfg_field)
                if val is not None:
                    body[api_field] = _tf(val)
            return "PATCH", f"/groups/{gid}/settings", None, body
        if op == "list_project_users":
            return "GET", f"/groups/{gid}/users", p, None
        if op == "add_project_user":
            return "POST", f"/groups/{gid}/invites", None, {"username": c.username, "roles": _pj(c.roles)}
        if op == "remove_project_user":
            return "DELETE", f"/groups/{gid}/users/{c.user_id}", None, None
        if op == "list_project_invitations":
            return "GET", f"/groups/{gid}/invites", None, None
        if op == "invite_to_project":
            return "POST", f"/groups/{gid}/invites", None, {"username": c.username, "roles": _pj(c.roles)}
        if op == "delete_project_invitation":
            return "DELETE", f"/groups/{gid}/invites/{c.invitation_id}", None, None
        if op == "get_project_cluster_count":
            return "GET", f"/groups/{gid}", None, None
        if op == "list_project_api_keys":
            return "GET", f"/groups/{gid}/apiKeys", p, None
        if op == "create_project_api_key":
            return "POST", f"/groups/{gid}/apiKeys", None, {"desc": c.description, "roles": _pj(c.roles)}
        if op == "assign_api_key_to_project":
            return "POST", f"/groups/{gid}/apiKeys/{c.api_user_id}", None, _pj(c.roles)

        # ---- TEAMS ----
        if op == "list_org_teams":
            return "GET", f"/orgs/{org}/teams", p, None
        if op == "get_org_team":
            return "GET", f"/orgs/{org}/teams/{c.team_id}", None, None
        if op == "get_team_by_name":
            return "GET", f"/orgs/{org}/teams/byName/{c.team_name}", None, None
        if op == "create_org_team":
            return "POST", f"/orgs/{org}/teams", None, {"name": c.name, "usernames": _pj(c.usernames)}
        if op == "rename_org_team":
            return "PATCH", f"/orgs/{org}/teams/{c.team_id}", None, {"name": c.name}
        if op == "delete_org_team":
            return "DELETE", f"/orgs/{org}/teams/{c.team_id}", None, None
        if op == "list_team_users":
            return "GET", f"/orgs/{org}/teams/{c.team_id}/users", None, None
        if op == "add_team_users":
            return "POST", f"/orgs/{org}/teams/{c.team_id}/users", None, _pj(c.usernames)
        if op == "remove_team_user":
            return "DELETE", f"/orgs/{org}/teams/{c.team_id}/users/{c.user_id}", None, None
        if op == "list_project_teams":
            return "GET", f"/groups/{gid}/teams", p, None
        if op == "add_teams_to_project":
            return "POST", f"/groups/{gid}/teams", None, _pj(c.teams)
        if op == "update_project_team":
            return "PATCH", f"/groups/{gid}/teams/{c.team_id}", None, {"roleNames": _pj(c.roles)}
        if op == "remove_project_team":
            return "DELETE", f"/groups/{gid}/teams/{c.team_id}", None, None

        # ---- MAINTENANCE ----
        if op == "get_maintenance_window":
            return "GET", f"/groups/{gid}/maintenanceWindow", None, None
        if op == "update_maintenance_window":
            body = {"dayOfWeek": c.day_of_week, "hourOfDay": c.hour_of_day}
            if c.start_asap is not None:
                body["startASAP"] = _tf(c.start_asap)
            return "PATCH", f"/groups/{gid}/maintenanceWindow", None, body
        if op == "defer_maintenance_window":
            return "POST", f"/groups/{gid}/maintenanceWindow/defer", None, None
        if op == "auto_defer_maintenance_window":
            return "POST", f"/groups/{gid}/maintenanceWindow/autoDefer", None, None
        if op == "reset_maintenance_window":
            return "DELETE", f"/groups/{gid}/maintenanceWindow", None, None

        # ---- AUDITING ----
        if op == "get_auditing":
            return "GET", f"/groups/{gid}/auditLog", None, None
        if op == "update_auditing":
            body = {"enabled": _tf(c.enabled)}
            if c.audit_filter:
                body["auditFilter"] = c.audit_filter
            if c.audit_authorization_success is not None:
                body["auditAuthorizationSuccess"] = _tf(c.audit_authorization_success)
            return "PATCH", f"/groups/{gid}/auditLog", None, body
        if op == "get_org_auditing":
            return "GET", f"/orgs/{org}/settings", None, None

        # ---- ENCRYPTION AT REST ----
        if op == "get_encryption_at_rest":
            return "GET", f"/groups/{gid}/encryptionAtRest", None, None
        if op == "update_encryption_at_rest":
            body = {}
            if c.aws_kms:
                body["awsKms"] = _pj(c.aws_kms)
            if c.azure_key_vault:
                body["azureKeyVault"] = _pj(c.azure_key_vault)
            if c.google_cloud_kms:
                body["googleCloudKms"] = _pj(c.google_cloud_kms)
            return "PATCH", f"/groups/{gid}/encryptionAtRest", None, body
        if op == "get_encryption_at_rest_private_endpoint":
            return "GET", f"/groups/{gid}/encryptionAtRest/{c.cloud_provider}/privateEndpoints", None, None

        # ---- LDAP ----
        if op == "get_ldap_config":
            return "GET", f"/groups/{gid}/userSecurity", None, None
        if op == "save_ldap_config":
            ldap = {
                "authenticationEnabled": _tf(c.authentication_enabled),
                "authorizationEnabled": _tf(c.authorization_enabled),
                "hostname": c.hostname,
                "port": c.port,
                "bindUsername": c.bind_username,
                "bindPassword": c.bind_password,
            }
            if c.ca_certificate:
                ldap["caCertificate"] = c.ca_certificate
            if c.user_to_dn_mapping:
                ldap["userToDNMapping"] = _pj(c.user_to_dn_mapping)
            return "PATCH", f"/groups/{gid}/userSecurity", None, {"ldap": ldap}
        if op == "verify_ldap_config":
            body = {
                "hostname": c.hostname,
                "port": c.port,
                "bindUsername": c.bind_username,
                "bindPassword": c.bind_password,
            }
            if c.ca_certificate:
                body["caCertificate"] = c.ca_certificate
            return "POST", f"/groups/{gid}/userSecurity/ldap/verify", None, body

        # ---- X.509 ----
        if op == "get_x509_config":
            return "GET", f"/groups/{gid}/userSecurity", None, None
        if op == "save_x509_config":
            return "PATCH", f"/groups/{gid}/userSecurity", None, {"customerX509": {"cas": c.cas}}
        if op == "disable_x509_config":
            return "DELETE", f"/groups/{gid}/userSecurity/customerX509", None, None

        # ---- CLOUD PROVIDER ACCESS ----
        if op == "list_cloud_provider_access":
            return "GET", f"/groups/{gid}/cloudProviderAccess", None, None
        if op == "create_cloud_provider_access":
            return "POST", f"/groups/{gid}/cloudProviderAccess", None, {"providerName": c.provider_name}
        if op == "authorize_cloud_provider_access":
            return "PATCH", f"/groups/{gid}/cloudProviderAccess/{c.role_id}", None, {
                "providerName": "AWS",
                "aws": {"iamAssumedRoleArn": c.iam_assumed_role_arn},
            }
        if op == "deauthorize_cloud_provider_access":
            return "DELETE", f"/groups/{gid}/cloudProviderAccess/{c.cloud_provider}/{c.role_id}", None, None

        # ---- GLOBAL ZONES ----
        if op == "get_managed_namespaces":
            return "GET", f"/groups/{gid}/clusters/{cluster}/globalWrites/managedNamespaces", None, None
        if op == "add_managed_namespace":
            body = {
                "db": c.db,
                "collection": c.collection,
                "customShardKey": c.custom_zone_name,
                "customZoneName": c.custom_zone_name,
            }
            if c.is_custom_shard_key_hashed is not None:
                body["isCustomShardKeyHashed"] = _tf(c.is_custom_shard_key_hashed)
            if c.is_shard_key_unique is not None:
                body["isShardKeyUnique"] = _tf(c.is_shard_key_unique)
            if c.num_initial_chunks is not None:
                body["numInitialChunks"] = c.num_initial_chunks
            return "POST", f"/groups/{gid}/clusters/{cluster}/globalWrites/managedNamespaces", None, body
        if op == "delete_managed_namespace":
            return "DELETE", f"/groups/{gid}/clusters/{cluster}/globalWrites/managedNamespaces", {
                "db": c.db, "collection": c.collection,
            }, None
        if op == "get_custom_zone_mapping":
            return "GET", f"/groups/{gid}/clusters/{cluster}/globalWrites/customZoneMapping", None, None
        if op == "add_custom_zone_mapping":
            mapping = _pj(c.custom_zone_mapping)
            zone_mappings = (
                [{"location": k, "zone": v} for k, v in mapping.items()]
                if isinstance(mapping, dict) else mapping
            )
            return "POST", f"/groups/{gid}/clusters/{cluster}/globalWrites/customZoneMapping", None, {
                "customZoneMappings": zone_mappings,
            }
        if op == "delete_custom_zone_mapping":
            return "DELETE", f"/groups/{gid}/clusters/{cluster}/globalWrites/customZoneMapping", None, None

        # ---- SERVICE ACCOUNTS ----
        if op == "list_org_service_accounts":
            return "GET", f"/orgs/{org}/serviceAccounts", p, None
        if op == "create_org_service_account":
            body = {"name": c.name, "description": c.description}
            if c.roles:
                body["roles"] = _pj(c.roles)
            return "POST", f"/orgs/{org}/serviceAccounts", None, body
        if op == "get_org_service_account":
            return "GET", f"/orgs/{org}/serviceAccounts/{c.client_id}", None, None
        if op == "update_org_service_account":
            body = {"name": c.name, "description": c.description}
            if c.roles:
                body["roles"] = _pj(c.roles)
            return "PATCH", f"/orgs/{org}/serviceAccounts/{c.client_id}", None, body
        if op == "delete_org_service_account":
            return "DELETE", f"/orgs/{org}/serviceAccounts/{c.client_id}", None, None
        if op == "create_service_account_secret":
            return "POST", f"/orgs/{org}/serviceAccounts/{c.client_id}/secrets", None, {
                "secretExpiresAfterHours": c.secret_expiration_hours,
            }
        if op == "delete_service_account_secret":
            return "DELETE", f"/orgs/{org}/serviceAccounts/{c.client_id}/secrets/{c.secret_id}", None, None
        if op == "list_project_service_accounts":
            return "GET", f"/groups/{gid}/serviceAccounts", p, None
        if op == "add_project_service_account":
            body = {"clientId": c.client_id}
            if c.roles:
                body["roles"] = _pj(c.roles)
            return "POST", f"/groups/{gid}/serviceAccounts", None, body
        if op == "remove_project_service_account":
            return "DELETE", f"/groups/{gid}/serviceAccounts/{c.client_id}", None, None

        # ---- API KEYS ----
        if op == "get_org_api_key":
            return "GET", f"/orgs/{org}/apiKeys/{c.api_user_id}", None, None
        if op == "update_org_api_key":
            body = {}
            if c.description is not None:
                body["desc"] = c.description
            if c.roles:
                body["roles"] = _pj(c.roles)
            return "PATCH", f"/orgs/{org}/apiKeys/{c.api_user_id}", None, body
        if op == "get_api_key_access_list":
            return "GET", f"/orgs/{org}/apiKeys/{c.api_user_id}/accessList", None, None
        if op == "add_api_key_access_list":
            return "POST", f"/orgs/{org}/apiKeys/{c.api_user_id}/accessList", None, _pj(c.access_list)
        if op == "delete_api_key_access_list_entry":
            return "DELETE", f"/orgs/{org}/apiKeys/{c.api_user_id}/accessList/{c.ip_address}", None, None
        if op == "get_project_api_key_detail":
            return "GET", f"/groups/{gid}/apiKeys", None, None
        if op == "remove_project_api_key":
            return "DELETE", f"/groups/{gid}/apiKeys/{c.api_user_id}", None, None

        # ---- EVENTS ----
        if op == "list_org_events":
            params = {**p}
            if c.event_type:
                params["eventType"] = c.event_type
            if c.min_date:
                params["minDate"] = c.min_date
            if c.max_date:
                params["maxDate"] = c.max_date
            return "GET", f"/orgs/{org}/events", params, None
        if op == "get_org_event":
            return "GET", f"/orgs/{org}/events/{c.event_id}", None, None
        if op == "list_project_events":
            params = {**p}
            if c.event_type:
                params["eventType"] = c.event_type
            if c.min_date:
                params["minDate"] = c.min_date
            if c.max_date:
                params["maxDate"] = c.max_date
            return "GET", f"/groups/{gid}/events", params, None
        if op == "get_project_event":
            return "GET", f"/groups/{gid}/events/{c.event_id}", None, None

        # ---- ACCESS TRACKING ----
        if op == "get_db_access_history":
            params = {**p}
            if c.start:
                params["start"] = c.start
            if c.end:
                params["end"] = c.end
            if c.ip_address:
                params["ipAddress"] = c.ip_address
            if c.auth_result:
                params["authResult"] = c.auth_result
            return "GET", f"/groups/{gid}/dbAccessHistory/clusters/{cluster}", params, None

        # ---- RESOURCE POLICIES ----
        if op == "list_resource_policies":
            return "GET", f"/orgs/{org}/resourcePolicies", p, None
        if op == "get_resource_policy":
            return "GET", f"/orgs/{org}/resourcePolicies/{c.resource_policy_id}", None, None
        if op == "create_resource_policy":
            body = {"name": c.name, "policies": _pj(c.policies)}
            if c.description:
                body["description"] = c.description
            return "POST", f"/orgs/{org}/resourcePolicies", None, body
        if op == "update_resource_policy":
            body = {}
            if c.name is not None:
                body["name"] = c.name
            if c.policies:
                body["policies"] = _pj(c.policies)
            return "PATCH", f"/orgs/{org}/resourcePolicies/{c.resource_policy_id}", None, body
        if op == "delete_resource_policy":
            return "DELETE", f"/orgs/{org}/resourcePolicies/{c.resource_policy_id}", None, None
        if op == "validate_resource_policy":
            return "POST", f"/orgs/{org}/resourcePolicies:validate", None, {
                "name": c.name, "policies": _pj(c.policies),
            }
        if op == "list_noncompliant_resources":
            return "GET", f"/orgs/{org}/nonCompliantResources", None, None

        # ---- INTEGRATIONS ----
        if op == "list_integrations":
            return "GET", f"/groups/{gid}/integrations", None, None
        if op == "get_integration":
            return "GET", f"/groups/{gid}/integrations/{c.integration_id}", None, None
        if op == "create_integration":
            body = {"type": c.integration_type}
            for cfg_field, api_field in [
                ("url", "url"), ("secret", "secret"), ("service_key", "serviceKey"),
                ("api_key", "apiKey"), ("region", "region"),
                ("routing_key", "routingKey"), ("channel_name", "channelName"),
            ]:
                val = getattr(c, cfg_field, None)
                if val:
                    body[api_field] = val
            return "POST", f"/groups/{gid}/integrations/{c.integration_type}", None, body
        if op == "update_integration":
            body = {"type": c.integration_type}
            if c.url:
                body["url"] = c.url
            if c.secret:
                body["secret"] = c.secret
            return "PUT", f"/groups/{gid}/integrations/{c.integration_type}", None, body
        if op == "delete_integration":
            return "DELETE", f"/groups/{gid}/integrations/{c.integration_id}", None, None

        # ---- LOG EXPORT ----
        if op == "get_log_export":
            return "GET", f"/groups/{gid}/pushBasedLogExport", None, None
        if op == "create_log_export":
            body = {"bucketName": c.aws_s3_bucket_name, "iamRoleId": c.iam_role_arn}
            if c.prefix:
                body["prefixPath"] = c.prefix
            return "POST", f"/groups/{gid}/pushBasedLogExport", None, body
        if op == "update_log_export":
            body = {}
            if c.aws_s3_bucket_name:
                body["bucketName"] = c.aws_s3_bucket_name
            if c.iam_role_arn:
                body["iamRoleId"] = c.iam_role_arn
            if c.prefix:
                body["prefixPath"] = c.prefix
            return "PATCH", f"/groups/{gid}/pushBasedLogExport", None, body
        if op == "delete_log_export":
            return "DELETE", f"/groups/{gid}/pushBasedLogExport", None, None

        # ---- ATLAS USERS ----
        if op == "create_atlas_user":
            return "POST", "/users", None, {
                "username": c.username,
                "password": c.password,
                "firstName": c.first_name,
                "lastName": c.last_name,
                "country": c.country,
                "roles": _pj(c.roles),
            }
        if op == "get_atlas_user":
            return "GET", f"/users/{c.user_id}", None, None
        if op == "get_atlas_user_by_name":
            return "GET", f"/users/byName/{c.username}", None, None

        # ---- FEDERATED AUTH ----
        if op == "get_federation_settings":
            return "GET", f"/orgs/{org}/federationSettings", None, None
        if op == "list_identity_providers":
            return "GET", f"/orgs/{org}/federationSettings/{c.federation_settings_id}/identityProviders", p, None
        if op == "create_identity_provider":
            body = {
                "displayName": c.display_name,
                "protocol": c.protocol,
                "idpType": c.idp_type,
            }
            for cfg_field, api_field in [
                ("issuer_uri", "issuerUri"), ("client_id", "clientId"), ("sso_url", "ssoUrl"),
            ]:
                val = getattr(c, cfg_field, None)
                if val:
                    body[api_field] = val
            if c.requested_scopes:
                body["requestedScopes"] = _pj(c.requested_scopes)
            if c.associated_domains:
                body["associatedDomains"] = _pj(c.associated_domains)
            return "POST", f"/orgs/{org}/federationSettings/{c.federation_settings_id}/identityProviders", None, body
        if op == "get_identity_provider":
            return "GET", f"/orgs/{org}/federationSettings/{c.federation_settings_id}/identityProviders/{c.idp_id}", None, None
        if op == "update_identity_provider":
            body = {}
            for cfg_field, api_field in [
                ("display_name", "displayName"), ("sso_url", "ssoUrl"), ("issuer_uri", "issuerUri"),
            ]:
                val = getattr(c, cfg_field, None)
                if val:
                    body[api_field] = val
            if c.associated_domains:
                body["associatedDomains"] = _pj(c.associated_domains)
            return "PATCH", f"/orgs/{org}/federationSettings/{c.federation_settings_id}/identityProviders/{c.idp_id}", None, body
        if op == "delete_identity_provider":
            return "DELETE", f"/orgs/{org}/federationSettings/{c.federation_settings_id}/identityProviders/{c.idp_id}", None, None
        if op == "list_connected_org_configs":
            return "GET", f"/orgs/{org}/federationSettings/{c.federation_settings_id}/connectedOrgConfigs", p, None
        if op == "update_connected_org_config":
            body = {}
            if c.identity_provider_id is not None:
                body["identityProviderId"] = c.identity_provider_id
            if c.domain_restriction_enabled is not None:
                body["domainRestrictionEnabled"] = _tf(c.domain_restriction_enabled)
            if c.domain_allow_list:
                body["domainAllowList"] = _pj(c.domain_allow_list)
            return "PATCH", f"/orgs/{org}/federationSettings/{c.federation_settings_id}/connectedOrgConfigs/{c.connected_org_config_id}", None, body
        if op == "list_role_mappings":
            return "GET", f"/orgs/{org}/federationSettings/{c.federation_settings_id}/connectedOrgConfigs/{c.connected_org_config_id}/roleMappings", None, None
        if op == "create_role_mapping":
            return "POST", f"/orgs/{org}/federationSettings/{c.federation_settings_id}/connectedOrgConfigs/{c.connected_org_config_id}/roleMappings", None, {
                "externalGroupName": c.external_group_name,
                "roleAssignments": _pj(c.role_assignments),
            }
        if op == "delete_role_mapping":
            return "DELETE", f"/orgs/{org}/federationSettings/{c.federation_settings_id}/connectedOrgConfigs/{c.connected_org_config_id}/roleMappings/{c.role_mapping_id}", None, None

        # ---- MONITORING ----
        if op == "list_processes":
            return "GET", f"/groups/{gid}/processes", p, None
        if op == "get_process":
            return "GET", f"/groups/{gid}/processes/{c.process_id}", None, None
        if op == "get_process_measurements":
            return "GET", f"/groups/{gid}/processes/{c.process_id}/measurements", self._measurement_params(c), None
        if op == "get_database_measurements":
            return "GET", f"/groups/{gid}/processes/{c.process_id}/databases/{c.database_name}/measurements", self._measurement_params(c), None
        if op == "get_disk_measurements":
            return "GET", f"/groups/{gid}/processes/{c.process_id}/disks/{c.partition_name}/measurements", self._measurement_params(c), None
        if op == "download_cluster_log":
            params = {}
            if c.start_date is not None:
                params["startDate"] = c.start_date
            if c.end_date is not None:
                params["endDate"] = c.end_date
            return "GET", f"/groups/{gid}/clusters/{c.host_name}/logs/{c.log_name}.gz", params, None
        if op == "list_processes_databases":
            return "GET", f"/groups/{gid}/processes/{c.process_id}/databases", p, None
        if op == "list_process_disks":
            return "GET", f"/groups/{gid}/processes/{c.process_id}/disks", p, None

        # ---- BILLING ----
        if op == "list_invoices":
            params = {**p}
            if c.status_names:
                params["statusNames"] = c.status_names
            if c.from_date:
                params["fromDate"] = c.from_date
            if c.to_date:
                params["toDate"] = c.to_date
            return "GET", f"/orgs/{org}/invoices", params, None
        if op == "get_pending_invoices":
            return "GET", f"/orgs/{org}/invoices/pending", None, None
        if op == "get_invoice":
            return "GET", f"/orgs/{org}/invoices/{c.invoice_id}", None, None

        # ---- PERFORMANCE ADVISOR ----
        if op == "list_suggested_indexes":
            params = {}
            if c.since is not None:
                params["since"] = c.since
            if c.until is not None:
                params["until"] = c.until
            if c.namespaces:
                params["namespaces"] = c.namespaces
            return "GET", f"/groups/{gid}/clusters/{cluster}/performanceAdvisor/suggestedIndexes", params, None
        if op == "list_slow_query_logs":
            params = {}
            if c.since is not None:
                params["since"] = c.since
            if c.duration is not None:
                params["duration"] = c.duration
            if c.namespaces:
                params["namespaces"] = c.namespaces
            if c.n_logs is not None:
                params["nLogs"] = c.n_logs
            return "GET", f"/groups/{gid}/processes/{c.process_id}/performanceAdvisor/slowQueryLogs", params, None
        if op == "list_performance_namespaces":
            params = {}
            if c.since is not None:
                params["since"] = c.since
            if c.duration is not None:
                params["duration"] = c.duration
            return "GET", f"/groups/{gid}/clusters/{cluster}/performanceAdvisor/namespaces", params, None
        if op == "get_schema_advice":
            return "GET", f"/groups/{gid}/clusters/{cluster}/performanceAdvisor/schemaAdvice", None, None
        if op == "enable_managed_slow_ms":
            return "POST", f"/groups/{gid}/managedSlowMs/enable", None, None
        if op == "disable_managed_slow_ms":
            return "DELETE", f"/groups/{gid}/managedSlowMs/disable", None, None
        if op == "get_managed_slow_ms":
            return "GET", f"/groups/{gid}/managedSlowMs", None, None

        # ---- ALERT CONFIGS ----
        if op == "list_alert_configs":
            return "GET", f"/groups/{gid}/alertConfigs", p, None
        if op == "get_alert_config":
            return "GET", f"/groups/{gid}/alertConfigs/{c.alert_config_id}", None, None
        if op == "create_alert_config":
            return "POST", f"/groups/{gid}/alertConfigs", None, self._alert_config_body(c)
        if op == "update_alert_config":
            return "PUT", f"/groups/{gid}/alertConfigs/{c.alert_config_id}", None, self._alert_config_body(c)
        if op == "toggle_alert_config":
            return "PATCH", f"/groups/{gid}/alertConfigs/{c.alert_config_id}", None, {"enabled": _tf(c.enabled)}
        if op == "delete_alert_config":
            return "DELETE", f"/groups/{gid}/alertConfigs/{c.alert_config_id}", None, None
        if op == "get_alert_config_matchers":
            return "GET", "/alertConfigs/matchers/fieldNames", None, None
        if op == "list_alerts_for_config":
            return "GET", f"/groups/{gid}/alertConfigs/{c.alert_config_id}/alerts", p, None

        # ---- ALERTS ----
        if op == "list_alerts":
            params = {**p}
            if c.status:
                params["status"] = c.status
            return "GET", f"/groups/{gid}/alerts", params, None
        if op == "get_alert":
            return "GET", f"/groups/{gid}/alerts/{c.alert_id}", None, None
        if op == "acknowledge_alert":
            body = {"acknowledgedUntil": c.acknowledged_until}
            if c.acknowledgement_comment:
                body["acknowledgementComment"] = c.acknowledgement_comment
            if _tf(c.unacknowledge_alert):
                body["acknowledgedUntil"] = None
            return "PATCH", f"/groups/{gid}/alerts/{c.alert_id}", None, body

        # ---- CUSTOM DB ROLES ----
        if op == "list_custom_roles":
            return "GET", f"/groups/{gid}/customDBRoles/roles", None, None
        if op == "get_custom_role":
            return "GET", f"/groups/{gid}/customDBRoles/roles/{c.role_name}", None, None
        if op == "create_custom_role":
            body = {"roleName": c.role_name, "actions": _pj(c.actions)}
            if c.inherited_roles:
                body["inheritedRoles"] = _pj(c.inherited_roles)
            return "POST", f"/groups/{gid}/customDBRoles/roles", None, body
        if op == "update_custom_role":
            body = {}
            if c.actions:
                body["actions"] = _pj(c.actions)
            if c.inherited_roles:
                body["inheritedRoles"] = _pj(c.inherited_roles)
            return "PATCH", f"/groups/{gid}/customDBRoles/roles/{c.role_name}", None, body
        if op == "delete_custom_role":
            return "DELETE", f"/groups/{gid}/customDBRoles/roles/{c.role_name}", None, None

        raise ValueError(f"Unsupported Atlas operation: {op}")

    @staticmethod
    def _measurement_params(c: Any) -> Dict[str, Any]:
        params: Dict[str, Any] = {"granularity": c.granularity}
        if c.period:
            params["period"] = c.period
        if c.start_date:
            params["start"] = c.start_date
        if c.end_date:
            params["end"] = c.end_date
        if c.metrics:
            params["m"] = [m.strip() for m in c.metrics.split(",") if m.strip()]
        return params

    @staticmethod
    def _alert_config_body(c: Any) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "eventTypeName": c.event_type_name,
            "enabled": _tf(c.enabled),
            "notifications": _pj(c.notifications),
        }
        if c.matchers:
            body["matchers"] = _pj(c.matchers)
        if c.metric_threshold:
            body["metricThreshold"] = _pj(c.metric_threshold)
        if c.threshold:
            body["threshold"] = _pj(c.threshold)
        return body
