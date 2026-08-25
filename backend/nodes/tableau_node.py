"""
Tableau analytics & BI automation node.

Provides workflow integration with the Tableau REST API (v3.29) for operations
including:
- Projects: query, create, delete
- Workbooks: list, get, download, refresh extract, delete
- Views: list, render image, render PDF, export data (CSV)
- Data Sources: list, get, refresh extract, download, delete
- Users & Groups: list users, add user, list groups, add user to group
- Webhooks: list, create, test, delete
- Webhook Trigger: fire when a Tableau event (workbook/datasource/refresh) occurs

Authentication: Personal Access Token (PAT). The node POSTs the PAT to the Sign
In endpoint to exchange it for a short-lived `X-Tableau-Auth` credentials token
plus the site LUID, then sends that token on every subsequent request.

API Base URL: https://<server>/api/<api-version>  (e.g. https://10ax.online.tableau.com/api/3.29)
Documentation: https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api.htm
"""

import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator, create_model
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from utils.ssrf import guarded_async_client

logger = logging.getLogger(__name__)


# ==========================================================================
# Shared REST helpers (formerly tableau_common.py)
# ==========================================================================

TABLEAU_API_VERSION = "3.29"


def _base_url(server_url: str) -> str:
    """Build the versioned REST API base, e.g. https://10ax.online.tableau.com/api/3.29."""
    return f"{server_url.rstrip('/')}/api/{TABLEAU_API_VERSION}"


async def _tableau_signin(
    server_url: str,
    pat_name: str,
    pat_secret: str,
    site_content_url: str,
) -> Dict[str, Any]:
    """Exchange a PAT for an X-Tableau-Auth token + site LUID.

    Returns {"status": "success", "token": ..., "site_id": ...} or an error dict.
    """
    url = f"{_base_url(server_url)}/auth/signin"
    body = {
        "credentials": {
            "personalAccessTokenName": pat_name,
            "personalAccessTokenSecret": pat_secret,
            "site": {"contentUrl": site_content_url or ""},
        }
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    start = time.time()
    async with guarded_async_client(timeout=30.0) as client:
        response = await client.request("POST", url, headers=headers, json=body)
        api_ms = round((time.time() - start) * 1000, 2)
        if response.status_code >= 400:
            try:
                err = response.json()
                message = err.get("error", {}).get("detail", str(err))
            except Exception:
                message = response.text
            logger.error(f"[TableauNode] Sign in failed: {message}")
            return {
                "status": "error",
                "action": "signin",
                "error": message,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        payload = response.json()
        creds = (payload or {}).get("credentials", {})
        return {
            "status": "success",
            "token": creds.get("token"),
            "site_id": (creds.get("site") or {}).get("id"),
            "timing_ms": {"signin": api_ms},
        }


async def _tableau_request(
    server_url: str,
    token: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
    raw_response: bool = False,
    url_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Make an authenticated Tableau REST request and return a structured result.

    *endpoint* is appended to the versioned base (it starts with '/sites/...').
    Set *raw_response* for binary/CSV endpoints (image/pdf/data/content).
    Set *url_override* to a full URL for surfaces off the versioned base (e.g.
    Pulse under {server}/api/-/pulse/...).
    """
    url = url_override or f"{_base_url(server_url)}{endpoint}"
    headers = {
        "X-Tableau-Auth": token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if json_body:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with guarded_async_client(timeout=60.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = err.get("error", {}).get("detail", str(err))
                except Exception:
                    message = response.text
                logger.error(f"[TableauNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                data: Any = {"success": True}
            elif raw_response:
                data = {
                    "content_type": response.headers.get("content-type"),
                    "content_length": len(response.content),
                }
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
            logger.error(f"[TableauNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ==========================================================================
# Operation registry: config classes + handlers for the full REST API surface
# (formerly tableau_operations.py). OPERATION_CONFIGS is merged into the
# discriminated union below; OPERATION_HANDLERS into execute().
# ==========================================================================

# Inline "Create new <resource>" builder affordances.
_FIELD_RESOURCE_TYPE: Dict[str, str] = {
    "project_id": "tableau_project",
    "group_id": "tableau_group",
}


def _dyn(field_name: str, label: str) -> Dict[str, Any]:
    """x-dynamic-options block for a searchable dropdown (project_id/group_id)."""
    extra: Dict[str, Any] = {
        "x-dynamic-options": {
            "field_name": field_name,
            "placeholder": f"Select {label.lower()}...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": f"Or paste a {label.lower()} LUID",
        }
    }
    rt = _FIELD_RESOURCE_TYPE.get(field_name)
    if rt:
        extra["x-resource-type"] = rt
    return extra


# Populated below by per-category blocks. The main node imports these two.
OPERATION_CONFIGS: List[type] = []
OPERATION_HANDLERS: Dict[str, Any] = {}


# ============================================================================
# <generated per-category operation blocks are appended here>
# ============================================================================


# ============================================================================
# Authentication category operations
# ============================================================================

class TableauSwitchSiteConfig(BaseModel):
    """Switch the authenticated session to another site (not available on Tableau Cloud)."""
    operation: Literal["switch_site"] = Field(
        "switch_site",
        json_schema_extra={"const": "switch_site", "ui:hidden": True,
                           "x-category": "Authentication", "x-is-trigger": False,
                           "x-display-name": "Switch Site"},
        title="Switch Site",
    )
    content_url: str = Field(..., title="Site Content URL",
        description="The contentUrl (subpath) of the site to switch to; empty for the Default site")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the site body for advanced fields")


async def _switch_site(c, server_url, token, site_id) -> Dict[str, Any]:
    site: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    site["contentUrl"] = c.content_url
    return await _tableau_request(server_url, token, "POST",
        "/auth/switchSite",
        json_body={"site": site}, action_name="switch_site")


class TableauListPatsConfig(BaseModel):
    """List the personal access tokens (PATs) for a user (not available on Tableau Server)."""
    operation: Literal["list_pats"] = Field(
        "list_pats",
        json_schema_extra={"const": "list_pats", "ui:hidden": True,
                           "x-category": "Authentication", "x-is-trigger": False,
                           "x-display-name": "List Personal Access Tokens"},
        title="List Personal Access Tokens",
    )
    user_id: str = Field(..., title="User LUID", description="LUID of the user whose PATs to list")
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _list_pats(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/users/{c.user_id}/personal-access-tokens",
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="list_pats")


class TableauRevokePatConfig(BaseModel):
    """Revoke a personal access token (PAT) by name for a user (not available on Tableau Server)."""
    operation: Literal["revoke_pat"] = Field(
        "revoke_pat",
        json_schema_extra={"const": "revoke_pat", "ui:hidden": True,
                           "x-category": "Authentication", "x-is-trigger": False,
                           "x-display-name": "Revoke Personal Access Token"},
        title="Revoke Personal Access Token",
    )
    user_id: str = Field(..., title="User LUID", description="LUID of the user who owns the PAT")
    pat_name: str = Field(..., title="PAT Name", description="Name of the personal access token to revoke")


async def _revoke_pat(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/users/{c.user_id}/personal-access-tokens/{c.pat_name}",
        action_name="revoke_pat")


class TableauGetCurrentSessionConfig(BaseModel):
    """Get details of the current server session (user, site, and auth settings)."""
    operation: Literal["get_current_session"] = Field(
        "get_current_session",
        json_schema_extra={"const": "get_current_session", "ui:hidden": True,
                           "x-category": "Authentication", "x-is-trigger": False,
                           "x-display-name": "Get Current Server Session"},
        title="Get Current Server Session",
    )


async def _get_current_session(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "/sessions/current",
        action_name="get_current_session")


OPERATION_CONFIGS.extend([
    TableauSwitchSiteConfig,
    TableauListPatsConfig,
    TableauRevokePatConfig,
    TableauGetCurrentSessionConfig,
])
OPERATION_HANDLERS.update({
    "switch_site": _switch_site,
    "list_pats": _list_pats,
    "revoke_pat": _revoke_pat,
    "get_current_session": _get_current_session,
})


# ---- Sites category ------------------------------------------------------
class TableauCreateSiteConfig(BaseModel):
    """Create a new site (server admin only)."""
    operation: Literal["create_site"] = Field(
        "create_site",
        json_schema_extra={"const": "create_site", "ui:hidden": True,
                           "x-category": "Sites", "x-is-trigger": False,
                           "x-display-name": "Create Site"},
        title="Create Site",
    )
    name: str = Field(..., title="Name")
    content_url: str = Field(..., title="Content URL",
        description="URL namespace for the site (unique)")
    admin_mode: Optional[str] = Field(None, title="Admin Mode",
        json_schema_extra={"enum": ["ContentAndUsers", "ContentOnly"], "x-enum-searchable": True})
    storage_quota: Optional[str] = Field(None, title="Storage Quota (MB)")
    user_quota: Optional[str] = Field(None, title="User Quota")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the site body for advanced fields")


async def _create_site(c, server_url, token, site_id) -> Dict[str, Any]:
    site: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    site["name"] = c.name
    site["contentUrl"] = c.content_url
    if c.admin_mode is not None: site["adminMode"] = c.admin_mode
    if c.storage_quota is not None: site["storageQuota"] = c.storage_quota
    if c.user_quota is not None: site["userQuota"] = c.user_quota
    return await _tableau_request(server_url, token, "POST", "/sites",
        json_body={"site": site}, action_name="create_site")


class TableauQuerySiteConfig(BaseModel):
    """Query information about the specified site."""
    operation: Literal["query_site"] = Field(
        "query_site",
        json_schema_extra={"const": "query_site", "ui:hidden": True,
                           "x-category": "Sites", "x-is-trigger": False,
                           "x-display-name": "Query Site"},
        title="Query Site",
    )
    target_site_id: Optional[str] = Field(None, title="Site LUID",
        description="LUID of the site to query; defaults to the signed-in site")
    include_usage: Optional[str] = Field(None, title="Include Usage",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


async def _query_site(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{c.target_site_id or site_id}",
        params={"includeUsage": c.include_usage}, action_name="query_site")


class TableauQuerySitesConfig(BaseModel):
    """List all sites on the server (server admin only)."""
    operation: Literal["query_sites"] = Field(
        "query_sites",
        json_schema_extra={"const": "query_sites", "ui:hidden": True,
                           "x-category": "Sites", "x-is-trigger": False,
                           "x-display-name": "Query Sites"},
        title="Query Sites",
    )
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _query_sites(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "/sites",
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="query_sites")


class TableauQuerySiteViewsConfig(BaseModel):
    """List all views in the site, optionally with usage statistics."""
    operation: Literal["query_site_views"] = Field(
        "query_site_views",
        json_schema_extra={"const": "query_site_views", "ui:hidden": True,
                           "x-category": "Sites", "x-is-trigger": False,
                           "x-display-name": "Query Views for Site"},
        title="Query Views for Site",
    )
    include_usage_statistics: Optional[str] = Field(None, title="Include Usage Statistics",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    filter: Optional[str] = Field(None, title="Filter")
    sort: Optional[str] = Field(None, title="Sort")
    fields: Optional[str] = Field(None, title="Fields")
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _query_site_views(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/views",
        params={"includeUsageStatistics": c.include_usage_statistics,
                "filter": c.filter, "sort": c.sort, "fields": c.fields,
                "pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="query_site_views")


class TableauGetRecentlyViewedConfig(BaseModel):
    """Get the content recently viewed by the signed-in user on the site."""
    operation: Literal["get_recently_viewed"] = Field(
        "get_recently_viewed",
        json_schema_extra={"const": "get_recently_viewed", "ui:hidden": True,
                           "x-category": "Sites", "x-is-trigger": False,
                           "x-display-name": "Get Recently Viewed for Site"},
        title="Get Recently Viewed for Site",
    )


async def _get_recently_viewed(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/content/recent", action_name="get_recently_viewed")


class TableauUpdateSiteConfig(BaseModel):
    """Update settings for the specified site (server admin only)."""
    operation: Literal["update_site"] = Field(
        "update_site",
        json_schema_extra={"const": "update_site", "ui:hidden": True,
                           "x-category": "Sites", "x-is-trigger": False,
                           "x-display-name": "Update Site"},
        title="Update Site",
    )
    target_site_id: Optional[str] = Field(None, title="Site LUID",
        description="LUID of the site to update; defaults to the signed-in site")
    name: Optional[str] = Field(None, title="Name")
    content_url: Optional[str] = Field(None, title="Content URL")
    admin_mode: Optional[str] = Field(None, title="Admin Mode",
        json_schema_extra={"enum": ["ContentAndUsers", "ContentOnly"], "x-enum-searchable": True})
    storage_quota: Optional[str] = Field(None, title="Storage Quota (MB)")
    user_quota: Optional[str] = Field(None, title="User Quota")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the site body for advanced fields")


async def _update_site(c, server_url, token, site_id) -> Dict[str, Any]:
    site: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: site["name"] = c.name
    if c.content_url is not None: site["contentUrl"] = c.content_url
    if c.admin_mode is not None: site["adminMode"] = c.admin_mode
    if c.storage_quota is not None: site["storageQuota"] = c.storage_quota
    if c.user_quota is not None: site["userQuota"] = c.user_quota
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{c.target_site_id or site_id}",
        json_body={"site": site}, action_name="update_site")


class TableauDeleteSiteConfig(BaseModel):
    """Delete the specified site (server admin only)."""
    operation: Literal["delete_site"] = Field(
        "delete_site",
        json_schema_extra={"const": "delete_site", "ui:hidden": True,
                           "x-category": "Sites", "x-is-trigger": False,
                           "x-display-name": "Delete Site"},
        title="Delete Site",
    )
    target_site_id: Optional[str] = Field(None, title="Site LUID",
        description="LUID of the site to delete; defaults to the signed-in site")


async def _delete_site(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{c.target_site_id or site_id}", action_name="delete_site")


class TableauGetSiteEmbeddingSettingsConfig(BaseModel):
    """Get the embedding settings for the site."""
    operation: Literal["get_site_embedding_settings"] = Field(
        "get_site_embedding_settings",
        json_schema_extra={"const": "get_site_embedding_settings", "ui:hidden": True,
                           "x-category": "Sites", "x-is-trigger": False,
                           "x-display-name": "Get Embedding Settings for Site"},
        title="Get Embedding Settings for Site",
    )


async def _get_site_embedding_settings(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/settings/embedding",
        action_name="get_site_embedding_settings")


class TableauUpdateSiteEmbeddingSettingsConfig(BaseModel):
    """Update the embedding settings for the site."""
    operation: Literal["update_site_embedding_settings"] = Field(
        "update_site_embedding_settings",
        json_schema_extra={"const": "update_site_embedding_settings", "ui:hidden": True,
                           "x-category": "Sites", "x-is-trigger": False,
                           "x-display-name": "Update Embedding Settings for Site"},
        title="Update Embedding Settings for Site",
    )
    unrestricted_embedding: Optional[str] = Field(None, title="Unrestricted Embedding",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the embedding settings body (e.g. allowList)")


async def _update_site_embedding_settings(c, server_url, token, site_id) -> Dict[str, Any]:
    settings: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.unrestricted_embedding is not None:
        settings["unrestrictedEmbedding"] = c.unrestricted_embedding == "true"
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/settings/embedding",
        json_body={"site": settings}, action_name="update_site_embedding_settings")


class TableauGetDataAccelerationReportConfig(BaseModel):
    """Get the data acceleration report for the site."""
    operation: Literal["get_data_acceleration_report"] = Field(
        "get_data_acceleration_report",
        json_schema_extra={"const": "get_data_acceleration_report", "ui:hidden": True,
                           "x-category": "Sites", "x-is-trigger": False,
                           "x-display-name": "Get Data Acceleration Report for Site"},
        title="Get Data Acceleration Report for Site",
    )


async def _get_data_acceleration_report(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/dataAccelerationReport",
        action_name="get_data_acceleration_report")


class TableauGetUserPersonalSpaceConfig(BaseModel):
    """Get information about the personal space of the signed-in user on the site."""
    operation: Literal["get_user_personal_space"] = Field(
        "get_user_personal_space",
        json_schema_extra={"const": "get_user_personal_space", "ui:hidden": True,
                           "x-category": "Sites", "x-is-trigger": False,
                           "x-display-name": "Get User Personal Space"},
        title="Get User Personal Space",
    )


async def _get_user_personal_space(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/personalSpace",
        action_name="get_user_personal_space")


class TableauListSiteAuthConfigurationsConfig(BaseModel):
    """List the authentication configurations for the site."""
    operation: Literal["list_site_auth_configurations"] = Field(
        "list_site_auth_configurations",
        json_schema_extra={"const": "list_site_auth_configurations", "ui:hidden": True,
                           "x-category": "Sites", "x-is-trigger": False,
                           "x-display-name": "List Authentication Configurations for Site"},
        title="List Authentication Configurations for Site",
    )


async def _list_site_auth_configurations(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/site-auth-configurations",
        action_name="list_site_auth_configurations")


OPERATION_CONFIGS.extend([
    TableauCreateSiteConfig,
    TableauQuerySiteConfig,
    TableauQuerySitesConfig,
    TableauQuerySiteViewsConfig,
    TableauGetRecentlyViewedConfig,
    TableauUpdateSiteConfig,
    TableauDeleteSiteConfig,
    TableauGetSiteEmbeddingSettingsConfig,
    TableauUpdateSiteEmbeddingSettingsConfig,
    TableauGetDataAccelerationReportConfig,
    TableauGetUserPersonalSpaceConfig,
    TableauListSiteAuthConfigurationsConfig,
])
OPERATION_HANDLERS.update({
    "create_site": _create_site,
    "query_site": _query_site,
    "query_sites": _query_sites,
    "query_site_views": _query_site_views,
    "get_recently_viewed": _get_recently_viewed,
    "update_site": _update_site,
    "delete_site": _delete_site,
    "get_site_embedding_settings": _get_site_embedding_settings,
    "update_site_embedding_settings": _update_site_embedding_settings,
    "get_data_acceleration_report": _get_data_acceleration_report,
    "get_user_personal_space": _get_user_personal_space,
    "list_site_auth_configurations": _list_site_auth_configurations,
})


# ---- Projects: update_project --------------------------------------------
class TableauUpdateProjectConfig(BaseModel):
    """Update a project's name, description, owner, or permissions."""
    operation: Literal["update_project"] = Field(
        "update_project",
        json_schema_extra={"const": "update_project", "ui:hidden": True,
                           "x-category": "Projects", "x-is-trigger": False,
                           "x-display-name": "Update Project"},
        title="Update Project",
    )
    project_id: str = Field(..., title="Project", description="LUID of the project to update",
        json_schema_extra=_dyn("project_id", "a project"))
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(None, title="Description")
    parent_project_id: Optional[str] = Field(None, title="Parent Project ID",
        description="Empty string moves the project to top level")
    content_permissions: Optional[str] = Field(None, title="Content Permissions",
        json_schema_extra={"enum": ["ManagedByOwner", "LockedToProject",
                                    "LockedToProjectWithoutNested"],
                           "x-enum-searchable": True})
    owner_id: Optional[str] = Field(None, title="Owner User LUID")
    publish_samples: Optional[str] = Field("false", title="Publish Samples",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the project body for advanced fields")


async def _update_project(c, server_url, token, site_id) -> Dict[str, Any]:
    project: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: project["name"] = c.name
    if c.description is not None: project["description"] = c.description
    if c.parent_project_id is not None: project["parentProjectId"] = c.parent_project_id
    if c.content_permissions is not None: project["contentPermissions"] = c.content_permissions
    if c.owner_id is not None: project["owner"] = {"id": c.owner_id}
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/projects/{c.project_id}",
        params={"publishSamples": c.publish_samples},
        json_body={"project": project}, action_name="update_project")


# ---- Projects: create_project_with_samples -------------------------------
class TableauCreateProjectWithSamplesConfig(BaseModel):
    """Create a project and optionally publish Tableau sample content into it."""
    operation: Literal["create_project_with_samples"] = Field(
        "create_project_with_samples",
        json_schema_extra={"const": "create_project_with_samples", "ui:hidden": True,
            "x-creates-resource": True,
            "x-resource-type": "tableau_project",
            "x-resource-id-path": "data.project.id",
                           "x-category": "Projects", "x-is-trigger": False,
                           "x-display-name": "Create Project With Samples"},
        title="Create Project With Samples",
    )
    name: str = Field(..., title="Name")
    description: Optional[str] = Field(None, title="Description")
    parent_project_id: Optional[str] = Field(None, title="Parent Project ID",
        description="Omit for a top-level project",
        json_schema_extra=_dyn("project_id", "a parent project"))
    content_permissions: Optional[str] = Field(None, title="Content Permissions",
        json_schema_extra={"enum": ["ManagedByOwner", "LockedToProject",
                                    "LockedToProjectWithoutNested"],
                           "x-enum-searchable": True})
    owner_id: Optional[str] = Field(None, title="Owner User LUID")
    publish_samples: Optional[str] = Field("true", title="Publish Samples",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the project body for advanced fields")


async def _create_project_with_samples(c, server_url, token, site_id) -> Dict[str, Any]:
    project: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    project["name"] = c.name
    if c.description is not None: project["description"] = c.description
    if c.parent_project_id is not None: project["parentProjectId"] = c.parent_project_id
    if c.content_permissions is not None: project["contentPermissions"] = c.content_permissions
    if c.owner_id is not None: project["owner"] = {"id": c.owner_id}
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/projects",
        params={"publishSamples": c.publish_samples},
        json_body={"project": project}, action_name="create_project_with_samples")


OPERATION_CONFIGS.extend([
    TableauUpdateProjectConfig,
    TableauCreateProjectWithSamplesConfig,
])
OPERATION_HANDLERS.update({
    "update_project": _update_project,
    "create_project_with_samples": _create_project_with_samples,
})


# ============================ WORKBOOKS ============================

class TableauUpdateWorkbookConfig(BaseModel):
    """Update a workbook's settings (name, description, project, owner, showTabs)."""
    operation: Literal["update_workbook"] = Field(
        "update_workbook",
        json_schema_extra={"const": "update_workbook", "ui:hidden": True,
                           "x-category": "Workbooks", "x-is-trigger": False,
                           "x-display-name": "Update Workbook"},
        title="Update Workbook",
    )
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(None, title="Description")
    show_tabs: Optional[str] = Field(None, title="Show Tabs",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    project_id: Optional[str] = Field(None, title="Project",
        description="LUID of the project to move the workbook into",
        json_schema_extra=_dyn("project_id", "a project"))
    owner_id: Optional[str] = Field(None, title="Owner LUID")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the workbook body for advanced fields")


async def _update_workbook(c, server_url, token, site_id) -> Dict[str, Any]:
    workbook: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: workbook["name"] = c.name
    if c.description is not None: workbook["description"] = c.description
    if c.show_tabs is not None: workbook["showTabs"] = c.show_tabs
    if c.project_id is not None: workbook["project"] = {"id": c.project_id}
    if c.owner_id is not None: workbook["owner"] = {"id": c.owner_id}
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/workbooks/{c.workbook_id}",
        json_body={"workbook": workbook}, action_name="update_workbook")


class TableauDownloadWorkbookConfig(BaseModel):
    """Download a workbook's content (.twb or .twbx)."""
    operation: Literal["download_workbook"] = Field(
        "download_workbook",
        json_schema_extra={"const": "download_workbook", "ui:hidden": True,
                           "x-category": "Workbooks", "x-is-trigger": False,
                           "x-display-name": "Download Workbook"},
        title="Download Workbook",
    )
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))
    include_extract: Optional[str] = Field("true", title="Include Extract",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


async def _download_workbook(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/workbooks/{c.workbook_id}/content",
        params={"includeExtract": c.include_extract}, raw_response=True,
        action_name="download_workbook")


class TableauDownloadWorkbookPdfConfig(BaseModel):
    """Download a PDF of all views in a workbook."""
    operation: Literal["download_workbook_pdf"] = Field(
        "download_workbook_pdf",
        json_schema_extra={"const": "download_workbook_pdf", "ui:hidden": True,
                           "x-category": "Workbooks", "x-is-trigger": False,
                           "x-display-name": "Download Workbook PDF"},
        title="Download Workbook PDF",
    )
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))
    type: Optional[str] = Field(None, title="Page Type",
        description="Page/paper type, e.g. A4, Letter, Legal, Tabloid")
    orientation: Optional[str] = Field(None, title="Orientation",
        json_schema_extra={"enum": ["Portrait", "Landscape"], "x-enum-searchable": True})
    max_age: Optional[str] = Field(None, title="Max Age (minutes)")


async def _download_workbook_pdf(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/workbooks/{c.workbook_id}/pdf",
        params={"type": c.type, "orientation": c.orientation, "maxAge": c.max_age},
        raw_response=True, action_name="download_workbook_pdf")


class TableauDownloadWorkbookPowerpointConfig(BaseModel):
    """Download a PowerPoint (.pptx) of the views in a workbook."""
    operation: Literal["download_workbook_powerpoint"] = Field(
        "download_workbook_powerpoint",
        json_schema_extra={"const": "download_workbook_powerpoint", "ui:hidden": True,
                           "x-category": "Workbooks", "x-is-trigger": False,
                           "x-display-name": "Download Workbook PowerPoint"},
        title="Download Workbook PowerPoint",
    )
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))
    max_age: Optional[str] = Field(None, title="Max Age (minutes)")


async def _download_workbook_powerpoint(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/workbooks/{c.workbook_id}/powerpoint",
        params={"maxAge": c.max_age}, raw_response=True,
        action_name="download_workbook_powerpoint")


class TableauGetWorkbookRevisionsConfig(BaseModel):
    """List the revision history for a workbook."""
    operation: Literal["get_workbook_revisions"] = Field(
        "get_workbook_revisions",
        json_schema_extra={"const": "get_workbook_revisions", "ui:hidden": True,
                           "x-category": "Workbooks", "x-is-trigger": False,
                           "x-display-name": "Get Workbook Revisions"},
        title="Get Workbook Revisions",
    )
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _get_workbook_revisions(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/workbooks/{c.workbook_id}/revisions",
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="get_workbook_revisions")


class TableauDownloadWorkbookRevisionConfig(BaseModel):
    """Download a specific revision of a workbook's content."""
    operation: Literal["download_workbook_revision"] = Field(
        "download_workbook_revision",
        json_schema_extra={"const": "download_workbook_revision", "ui:hidden": True,
                           "x-category": "Workbooks", "x-is-trigger": False,
                           "x-display-name": "Download Workbook Revision"},
        title="Download Workbook Revision",
    )
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))
    revision_number: str = Field(..., title="Revision Number")
    include_extract: Optional[str] = Field("true", title="Include Extract",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


async def _download_workbook_revision(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/workbooks/{c.workbook_id}/revisions/{c.revision_number}/content",
        params={"includeExtract": c.include_extract}, raw_response=True,
        action_name="download_workbook_revision")


class TableauRemoveWorkbookRevisionConfig(BaseModel):
    """Remove a specific revision of a workbook."""
    operation: Literal["remove_workbook_revision"] = Field(
        "remove_workbook_revision",
        json_schema_extra={"const": "remove_workbook_revision", "ui:hidden": True,
                           "x-category": "Workbooks", "x-is-trigger": False,
                           "x-display-name": "Remove Workbook Revision"},
        title="Remove Workbook Revision",
    )
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))
    revision_number: str = Field(..., title="Revision Number")


async def _remove_workbook_revision(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/workbooks/{c.workbook_id}/revisions/{c.revision_number}",
        action_name="remove_workbook_revision")


class TableauQueryWorkbookConnectionsConfig(BaseModel):
    """List the data connections in a workbook."""
    operation: Literal["query_workbook_connections"] = Field(
        "query_workbook_connections",
        json_schema_extra={"const": "query_workbook_connections", "ui:hidden": True,
                           "x-category": "Workbooks", "x-is-trigger": False,
                           "x-display-name": "Query Workbook Connections"},
        title="Query Workbook Connections",
    )
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))


async def _query_workbook_connections(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/workbooks/{c.workbook_id}/connections",
        action_name="query_workbook_connections")


class TableauUpdateWorkbookConnectionConfig(BaseModel):
    """Update the server address, port, or credentials of a workbook connection."""
    operation: Literal["update_workbook_connection"] = Field(
        "update_workbook_connection",
        json_schema_extra={"const": "update_workbook_connection", "ui:hidden": True,
                           "x-category": "Workbooks", "x-is-trigger": False,
                           "x-display-name": "Update Workbook Connection"},
        title="Update Workbook Connection",
    )
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))
    connection_id: str = Field(..., title="Connection LUID")
    server_address: Optional[str] = Field(None, title="Server Address")
    server_port: Optional[str] = Field(None, title="Server Port")
    user_name: Optional[str] = Field(None, title="User Name")
    password: Optional[str] = Field(None, title="Password")
    embed_password: Optional[str] = Field(None, title="Embed Password",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the connection body for advanced fields")


async def _update_workbook_connection(c, server_url, token, site_id) -> Dict[str, Any]:
    connection: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.server_address is not None: connection["serverAddress"] = c.server_address
    if c.server_port is not None: connection["serverPort"] = c.server_port
    if c.user_name is not None: connection["userName"] = c.user_name
    if c.password is not None: connection["password"] = c.password
    if c.embed_password is not None: connection["embedPassword"] = c.embed_password
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/workbooks/{c.workbook_id}/connections/{c.connection_id}",
        json_body={"connection": connection}, action_name="update_workbook_connection")


class TableauAddWorkbookTagsConfig(BaseModel):
    """Add one or more tags to a workbook."""
    operation: Literal["add_workbook_tags"] = Field(
        "add_workbook_tags",
        json_schema_extra={"const": "add_workbook_tags", "ui:hidden": True,
                           "x-category": "Workbooks", "x-is-trigger": False,
                           "x-display-name": "Add Tags to Workbook"},
        title="Add Tags to Workbook",
    )
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))
    tags: Optional[str] = Field(None, title="Tags",
        description="Comma-separated tag labels to add")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON for the tags body; overrides the Tags field if set")


async def _add_workbook_tags(c, server_url, token, site_id) -> Dict[str, Any]:
    if c.body_json:
        tags_body: Dict[str, Any] = json.loads(c.body_json)
    else:
        labels = [t.strip() for t in (c.tags or "").split(",") if t.strip()]
        tags_body = {"tag": [{"label": label} for label in labels]}
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/workbooks/{c.workbook_id}/tags",
        json_body={"tags": tags_body}, action_name="add_workbook_tags")


class TableauDeleteWorkbookTagConfig(BaseModel):
    """Delete a tag from a workbook."""
    operation: Literal["delete_workbook_tag"] = Field(
        "delete_workbook_tag",
        json_schema_extra={"const": "delete_workbook_tag", "ui:hidden": True,
                           "x-category": "Workbooks", "x-is-trigger": False,
                           "x-display-name": "Delete Tag from Workbook"},
        title="Delete Tag from Workbook",
    )
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))
    tag_name: str = Field(..., title="Tag Name")


async def _delete_workbook_tag(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/workbooks/{c.workbook_id}/tags/{c.tag_name}",
        action_name="delete_workbook_tag")


class TableauQueryViewsForWorkbookConfig(BaseModel):
    """List the views contained in a workbook."""
    operation: Literal["query_views_for_workbook"] = Field(
        "query_views_for_workbook",
        json_schema_extra={"const": "query_views_for_workbook", "ui:hidden": True,
                           "x-category": "Workbooks", "x-is-trigger": False,
                           "x-display-name": "Query Views for Workbook"},
        title="Query Views for Workbook",
    )
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))
    include_usage_statistics: Optional[str] = Field(None, title="Include Usage Statistics",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


async def _query_views_for_workbook(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/workbooks/{c.workbook_id}/views",
        params={"includeUsageStatistics": c.include_usage_statistics},
        action_name="query_views_for_workbook")


class TableauAddWorkbookPermissionsConfig(BaseModel):
    """Add permissions (grantee capabilities) to a workbook."""
    operation: Literal["add_workbook_permissions"] = Field(
        "add_workbook_permissions",
        json_schema_extra={"const": "add_workbook_permissions", "ui:hidden": True,
                           "x-category": "Workbooks", "x-is-trigger": False,
                           "x-display-name": "Add Workbook Permissions"},
        title="Add Workbook Permissions",
    )
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))
    body_json: str = Field(..., title="Grantee Capabilities (JSON)",
        description='JSON for the permissions body, e.g. {"granteeCapabilities":[{"user":{"id":"..."},"capabilities":{"capability":[{"name":"Read","mode":"Allow"}]}}]}')


async def _add_workbook_permissions(c, server_url, token, site_id) -> Dict[str, Any]:
    permissions: Dict[str, Any] = json.loads(c.body_json)
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/workbooks/{c.workbook_id}/permissions",
        json_body={"permissions": permissions}, action_name="add_workbook_permissions")


class TableauQueryWorkbookPermissionsConfig(BaseModel):
    """List the permissions set on a workbook."""
    operation: Literal["query_workbook_permissions"] = Field(
        "query_workbook_permissions",
        json_schema_extra={"const": "query_workbook_permissions", "ui:hidden": True,
                           "x-category": "Workbooks", "x-is-trigger": False,
                           "x-display-name": "Query Workbook Permissions"},
        title="Query Workbook Permissions",
    )
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))


async def _query_workbook_permissions(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/workbooks/{c.workbook_id}/permissions",
        action_name="query_workbook_permissions")


class TableauDeleteWorkbookPermissionConfig(BaseModel):
    """Delete a specific capability granted to a user or group on a workbook."""
    operation: Literal["delete_workbook_permission"] = Field(
        "delete_workbook_permission",
        json_schema_extra={"const": "delete_workbook_permission", "ui:hidden": True,
                           "x-category": "Workbooks", "x-is-trigger": False,
                           "x-display-name": "Delete Workbook Permission"},
        title="Delete Workbook Permission",
    )
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))
    grantee_type: str = Field("users", title="Grantee Type",
        json_schema_extra={"enum": ["users", "groups"], "x-enum-searchable": True})
    grantee_id: str = Field(..., title="Grantee LUID",
        description="LUID of the user or group")
    capability_name: str = Field(..., title="Capability Name",
        description="e.g. Read, Write, ExportImage, ShareView")
    capability_mode: str = Field("Allow", title="Capability Mode",
        json_schema_extra={"enum": ["Allow", "Deny"], "x-enum-searchable": True})


async def _delete_workbook_permission(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/workbooks/{c.workbook_id}/permissions/"
        f"{c.grantee_type}/{c.grantee_id}/{c.capability_name}/{c.capability_mode}",
        action_name="delete_workbook_permission")


class TableauRetrieveWorkbookKeychainConfig(BaseModel):
    """Retrieve the encrypted keychain of a workbook (for cross-site/server copy)."""
    operation: Literal["retrieve_workbook_keychain"] = Field(
        "retrieve_workbook_keychain",
        json_schema_extra={"const": "retrieve_workbook_keychain", "ui:hidden": True,
                           "x-category": "Workbooks", "x-is-trigger": False,
                           "x-display-name": "Retrieve Workbook Keychain"},
        title="Retrieve Workbook Keychain",
    )
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))
    destination_site_url_namespace: Optional[str] = Field(None, title="Destination Site URL Namespace")
    destination_site_luid: Optional[str] = Field(None, title="Destination Site LUID")
    destination_server_url: Optional[str] = Field(None, title="Destination Server URL")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the keychain request body")


async def _retrieve_workbook_keychain(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.destination_site_url_namespace is not None:
        body["destinationSiteUrlNamespace"] = c.destination_site_url_namespace
    if c.destination_site_luid is not None:
        body["destinationSiteLuid"] = c.destination_site_luid
    if c.destination_server_url is not None:
        body["destinationServerUrl"] = c.destination_server_url
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/workbooks/{c.workbook_id}/retrieveKeychain",
        json_body=body, action_name="retrieve_workbook_keychain")


class TableauGetWorkbookDowngradeInfoConfig(BaseModel):
    """Get info on features that would be lost downgrading a workbook to an older version."""
    operation: Literal["get_workbook_downgrade_info"] = Field(
        "get_workbook_downgrade_info",
        json_schema_extra={"const": "get_workbook_downgrade_info", "ui:hidden": True,
                           "x-category": "Workbooks", "x-is-trigger": False,
                           "x-display-name": "Get Workbook Downgrade Info"},
        title="Get Workbook Downgrade Info",
    )
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))
    product_version: str = Field(..., title="Product Version",
        description="Target Tableau version, e.g. 2021.4")


async def _get_workbook_downgrade_info(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/workbooks/{c.workbook_id}/downGradeInfo",
        params={"productVersion": c.product_version},
        action_name="get_workbook_downgrade_info")


OPERATION_CONFIGS.extend([
    TableauUpdateWorkbookConfig,
    TableauDownloadWorkbookConfig,
    TableauDownloadWorkbookPdfConfig,
    TableauDownloadWorkbookPowerpointConfig,
    TableauGetWorkbookRevisionsConfig,
    TableauDownloadWorkbookRevisionConfig,
    TableauRemoveWorkbookRevisionConfig,
    TableauQueryWorkbookConnectionsConfig,
    TableauUpdateWorkbookConnectionConfig,
    TableauAddWorkbookTagsConfig,
    TableauDeleteWorkbookTagConfig,
    TableauQueryViewsForWorkbookConfig,
    TableauAddWorkbookPermissionsConfig,
    TableauQueryWorkbookPermissionsConfig,
    TableauDeleteWorkbookPermissionConfig,
    TableauRetrieveWorkbookKeychainConfig,
    TableauGetWorkbookDowngradeInfoConfig,
])
OPERATION_HANDLERS.update({
    "update_workbook": _update_workbook,
    "download_workbook": _download_workbook,
    "download_workbook_pdf": _download_workbook_pdf,
    "download_workbook_powerpoint": _download_workbook_powerpoint,
    "get_workbook_revisions": _get_workbook_revisions,
    "download_workbook_revision": _download_workbook_revision,
    "remove_workbook_revision": _remove_workbook_revision,
    "query_workbook_connections": _query_workbook_connections,
    "update_workbook_connection": _update_workbook_connection,
    "add_workbook_tags": _add_workbook_tags,
    "delete_workbook_tag": _delete_workbook_tag,
    "query_views_for_workbook": _query_views_for_workbook,
    "add_workbook_permissions": _add_workbook_permissions,
    "query_workbook_permissions": _query_workbook_permissions,
    "delete_workbook_permission": _delete_workbook_permission,
    "retrieve_workbook_keychain": _retrieve_workbook_keychain,
    "get_workbook_downgrade_info": _get_workbook_downgrade_info,
})


# ============================ VIEWS + CUSTOM VIEWS =============================

class TableauGetViewConfig(BaseModel):
    """Get details of a specific view."""
    operation: Literal["get_view"] = Field(
        "get_view",
        json_schema_extra={"const": "get_view", "ui:hidden": True,
                           "x-category": "Views", "x-is-trigger": False,
                           "x-display-name": "Get View"},
        title="Get View",
    )
    view_id: str = Field(..., title="View", json_schema_extra=_dyn("view_id", "a view"))
    include_usage_statistics: Optional[str] = Field("false", title="Include Usage Statistics",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


async def _get_view(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/views/{c.view_id}",
        params={"includeUsageStatistics": c.include_usage_statistics},
        action_name="get_view")


class TableauGetViewByPathConfig(BaseModel):
    """Get a view by its URL name via a filter expression."""
    operation: Literal["get_view_by_path"] = Field(
        "get_view_by_path",
        json_schema_extra={"const": "get_view_by_path", "ui:hidden": True,
                           "x-category": "Views", "x-is-trigger": False,
                           "x-display-name": "Get View by Path"},
        title="Get View by Path",
    )
    filter: Optional[str] = Field(None, title="Filter",
        description="Filter expression, e.g. viewUrlName:eq:MyView")
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _get_view_by_path(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/views",
        params={"filter": c.filter, "pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="get_view_by_path")


class TableauDeleteViewConfig(BaseModel):
    """Delete a view from the site."""
    operation: Literal["delete_view"] = Field(
        "delete_view",
        json_schema_extra={"const": "delete_view", "ui:hidden": True,
                           "x-category": "Views", "x-is-trigger": False,
                           "x-display-name": "Delete View"},
        title="Delete View",
    )
    view_id: str = Field(..., title="View", json_schema_extra=_dyn("view_id", "a view"))


async def _delete_view(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/views/{c.view_id}",
        action_name="delete_view")


class TableauDownloadViewCrosstabConfig(BaseModel):
    """Download a view's crosstab data as an Excel (.xlsx) file."""
    operation: Literal["download_view_crosstab"] = Field(
        "download_view_crosstab",
        json_schema_extra={"const": "download_view_crosstab", "ui:hidden": True,
                           "x-category": "Views", "x-is-trigger": False,
                           "x-display-name": "Download View Crosstab (Excel)"},
        title="Download View Crosstab (Excel)",
    )
    view_id: str = Field(..., title="View", json_schema_extra=_dyn("view_id", "a view"))
    max_age: Optional[str] = Field(None, title="Max Age (minutes)")


async def _download_view_crosstab(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/views/{c.view_id}/crosstab/excel",
        params={"maxAge": c.max_age}, raw_response=True,
        action_name="download_view_crosstab")


class TableauAddViewTagsConfig(BaseModel):
    """Add one or more tags to a view."""
    operation: Literal["add_view_tags"] = Field(
        "add_view_tags",
        json_schema_extra={"const": "add_view_tags", "ui:hidden": True,
                           "x-category": "Views", "x-is-trigger": False,
                           "x-display-name": "Add Tags to View"},
        title="Add Tags to View",
    )
    view_id: str = Field(..., title="View", json_schema_extra=_dyn("view_id", "a view"))
    tags: Optional[str] = Field(None, title="Tags",
        description="Comma-separated list of tag labels to add")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the tags body for advanced fields")


async def _add_view_tags(c, server_url, token, site_id) -> Dict[str, Any]:
    tags_obj: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.tags is not None:
        tags_obj["tag"] = [{"label": t.strip()} for t in c.tags.split(",") if t.strip()]
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/views/{c.view_id}/tags",
        json_body={"tags": tags_obj}, action_name="add_view_tags")


class TableauDeleteViewTagConfig(BaseModel):
    """Delete a tag from a view."""
    operation: Literal["delete_view_tag"] = Field(
        "delete_view_tag",
        json_schema_extra={"const": "delete_view_tag", "ui:hidden": True,
                           "x-category": "Views", "x-is-trigger": False,
                           "x-display-name": "Delete Tag from View"},
        title="Delete Tag from View",
    )
    view_id: str = Field(..., title="View", json_schema_extra=_dyn("view_id", "a view"))
    tag_name: str = Field(..., title="Tag Name")


async def _delete_view_tag(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/views/{c.view_id}/tags/{c.tag_name}",
        action_name="delete_view_tag")


class TableauGetViewRecommendationsConfig(BaseModel):
    """Get view recommendations for the current user (deprecated in API 3.19)."""
    operation: Literal["get_view_recommendations"] = Field(
        "get_view_recommendations",
        json_schema_extra={"const": "get_view_recommendations", "ui:hidden": True,
                           "x-category": "Views", "x-is-trigger": False,
                           "x-display-name": "Get View Recommendations"},
        title="Get View Recommendations",
    )


async def _get_view_recommendations(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/recommendations",
        params={"type": "view"}, action_name="get_view_recommendations")


class TableauListCustomViewsConfig(BaseModel):
    """List custom views on the site."""
    operation: Literal["list_custom_views"] = Field(
        "list_custom_views",
        json_schema_extra={"const": "list_custom_views", "ui:hidden": True,
                           "x-category": "Views", "x-is-trigger": False,
                           "x-display-name": "List Custom Views"},
        title="List Custom Views",
    )
    filter: Optional[str] = Field(None, title="Filter")
    sort: Optional[str] = Field(None, title="Sort")
    fields: Optional[str] = Field(None, title="Fields")
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _list_custom_views(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/customviews",
        params={"filter": c.filter, "sort": c.sort, "fields": c.fields,
                "pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="list_custom_views")


class TableauGetCustomViewConfig(BaseModel):
    """Get details of a specific custom view."""
    operation: Literal["get_custom_view"] = Field(
        "get_custom_view",
        json_schema_extra={"const": "get_custom_view", "ui:hidden": True,
                           "x-category": "Views", "x-is-trigger": False,
                           "x-display-name": "Get Custom View"},
        title="Get Custom View",
    )
    custom_view_id: str = Field(..., title="Custom View LUID")


async def _get_custom_view(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/customviews/{c.custom_view_id}",
        action_name="get_custom_view")


class TableauGetCustomViewImageConfig(BaseModel):
    """Download an image (PNG) of a custom view."""
    operation: Literal["get_custom_view_image"] = Field(
        "get_custom_view_image",
        json_schema_extra={"const": "get_custom_view_image", "ui:hidden": True,
                           "x-category": "Views", "x-is-trigger": False,
                           "x-display-name": "Get Custom View Image"},
        title="Get Custom View Image",
    )
    custom_view_id: str = Field(..., title="Custom View LUID")
    resolution: Optional[str] = Field(None, title="Resolution",
        json_schema_extra={"enum": ["high"], "x-enum-searchable": True})
    max_age: Optional[str] = Field(None, title="Max Age (minutes)")


async def _get_custom_view_image(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/customviews/{c.custom_view_id}/image",
        params={"resolution": c.resolution, "maxAge": c.max_age}, raw_response=True,
        action_name="get_custom_view_image")


class TableauGetCustomViewDataConfig(BaseModel):
    """Download the underlying data (CSV) of a custom view."""
    operation: Literal["get_custom_view_data"] = Field(
        "get_custom_view_data",
        json_schema_extra={"const": "get_custom_view_data", "ui:hidden": True,
                           "x-category": "Views", "x-is-trigger": False,
                           "x-display-name": "Get Custom View Data (CSV)"},
        title="Get Custom View Data (CSV)",
    )
    custom_view_id: str = Field(..., title="Custom View LUID")
    max_age: Optional[str] = Field(None, title="Max Age (minutes)")


async def _get_custom_view_data(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/customviews/{c.custom_view_id}/data",
        params={"maxAge": c.max_age}, raw_response=True,
        action_name="get_custom_view_data")


class TableauGetCustomViewPdfConfig(BaseModel):
    """Download a PDF of a custom view."""
    operation: Literal["get_custom_view_pdf"] = Field(
        "get_custom_view_pdf",
        json_schema_extra={"const": "get_custom_view_pdf", "ui:hidden": True,
                           "x-category": "Views", "x-is-trigger": False,
                           "x-display-name": "Get Custom View PDF"},
        title="Get Custom View PDF",
    )
    custom_view_id: str = Field(..., title="Custom View LUID")
    viz_height: Optional[str] = Field(None, title="Viz Height")
    viz_width: Optional[str] = Field(None, title="Viz Width")
    type: Optional[str] = Field(None, title="Page Type")
    orientation: Optional[str] = Field(None, title="Orientation",
        json_schema_extra={"enum": ["Portrait", "Landscape"], "x-enum-searchable": True})
    max_age: Optional[str] = Field(None, title="Max Age (minutes)")


async def _get_custom_view_pdf(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/customviews/{c.custom_view_id}/pdf",
        params={"vizHeight": c.viz_height, "vizWidth": c.viz_width, "type": c.type,
                "orientation": c.orientation, "maxAge": c.max_age}, raw_response=True,
        action_name="get_custom_view_pdf")


class TableauUpdateCustomViewConfig(BaseModel):
    """Update a custom view's name or owner."""
    operation: Literal["update_custom_view"] = Field(
        "update_custom_view",
        json_schema_extra={"const": "update_custom_view", "ui:hidden": True,
                           "x-category": "Views", "x-is-trigger": False,
                           "x-display-name": "Update Custom View"},
        title="Update Custom View",
    )
    custom_view_id: str = Field(..., title="Custom View LUID")
    name: Optional[str] = Field(None, title="Name")
    owner_id: Optional[str] = Field(None, title="Owner User LUID")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the customView body for advanced fields")


async def _update_custom_view(c, server_url, token, site_id) -> Dict[str, Any]:
    custom_view: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: custom_view["name"] = c.name
    if c.owner_id is not None: custom_view["owner"] = {"id": c.owner_id}
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/customviews/{c.custom_view_id}",
        json_body={"customView": custom_view}, action_name="update_custom_view")


class TableauDeleteCustomViewConfig(BaseModel):
    """Delete a custom view from the site."""
    operation: Literal["delete_custom_view"] = Field(
        "delete_custom_view",
        json_schema_extra={"const": "delete_custom_view", "ui:hidden": True,
                           "x-category": "Views", "x-is-trigger": False,
                           "x-display-name": "Delete Custom View"},
        title="Delete Custom View",
    )
    custom_view_id: str = Field(..., title="Custom View LUID")


async def _delete_custom_view(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/customviews/{c.custom_view_id}",
        action_name="delete_custom_view")


OPERATION_CONFIGS.extend([
    TableauGetViewConfig,
    TableauGetViewByPathConfig,
    TableauDeleteViewConfig,
    TableauDownloadViewCrosstabConfig,
    TableauAddViewTagsConfig,
    TableauDeleteViewTagConfig,
    TableauGetViewRecommendationsConfig,
    TableauListCustomViewsConfig,
    TableauGetCustomViewConfig,
    TableauGetCustomViewImageConfig,
    TableauGetCustomViewDataConfig,
    TableauGetCustomViewPdfConfig,
    TableauUpdateCustomViewConfig,
    TableauDeleteCustomViewConfig,
])
OPERATION_HANDLERS.update({
    "get_view": _get_view,
    "get_view_by_path": _get_view_by_path,
    "delete_view": _delete_view,
    "download_view_crosstab": _download_view_crosstab,
    "add_view_tags": _add_view_tags,
    "delete_view_tag": _delete_view_tag,
    "get_view_recommendations": _get_view_recommendations,
    "list_custom_views": _list_custom_views,
    "get_custom_view": _get_custom_view,
    "get_custom_view_image": _get_custom_view_image,
    "get_custom_view_data": _get_custom_view_data,
    "get_custom_view_pdf": _get_custom_view_pdf,
    "update_custom_view": _update_custom_view,
    "delete_custom_view": _delete_custom_view,
})

# ============================================================================
# Data Sources category operations
# ============================================================================
_DS_CAT = "Data Sources"


class TableauUpdateDatasourceConfig(BaseModel):
    """Update a data source's name, project, owner, or certification."""
    operation: Literal["update_datasource"] = Field(
        "update_datasource",
        json_schema_extra={"const": "update_datasource", "ui:hidden": True,
                           "x-category": _DS_CAT, "x-is-trigger": False,
                           "x-display-name": "Update Data Source"},
        title="Update Data Source",
    )
    datasource_id: str = Field(..., title="Data Source", json_schema_extra=_dyn("datasource_id", "a data source"))
    name: Optional[str] = Field(None, title="Name")
    is_certified: Optional[str] = Field(None, title="Is Certified",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    certification_note: Optional[str] = Field(None, title="Certification Note")
    encrypt_extracts: Optional[str] = Field(None, title="Encrypt Extracts",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    project_id: Optional[str] = Field(None, title="Project",
        description="Move the data source to this project",
        json_schema_extra=_dyn("project_id", "a project"))
    owner_id: Optional[str] = Field(None, title="New Owner User LUID")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the datasource body")


async def _update_datasource(c, server_url, token, site_id) -> Dict[str, Any]:
    ds: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: ds["name"] = c.name
    if c.is_certified is not None: ds["isCertified"] = c.is_certified
    if c.certification_note is not None: ds["certificationNote"] = c.certification_note
    if c.encrypt_extracts is not None: ds["encryptExtracts"] = c.encrypt_extracts
    if c.project_id is not None: ds["project"] = {"id": c.project_id}
    if c.owner_id is not None: ds["owner"] = {"id": c.owner_id}
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/datasources/{c.datasource_id}",
        json_body={"datasource": ds}, action_name="update_datasource")


class TableauDownloadDatasourceConfig(BaseModel):
    """Download a data source (.tdsx/.tds) content."""
    operation: Literal["download_datasource"] = Field(
        "download_datasource",
        json_schema_extra={"const": "download_datasource", "ui:hidden": True,
                           "x-category": _DS_CAT, "x-is-trigger": False,
                           "x-display-name": "Download Data Source"},
        title="Download Data Source",
    )
    datasource_id: str = Field(..., title="Data Source", json_schema_extra=_dyn("datasource_id", "a data source"))
    include_extract: Optional[str] = Field("true", title="Include Extract",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


async def _download_datasource(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/datasources/{c.datasource_id}/content",
        params={"includeExtract": c.include_extract}, raw_response=True,
        action_name="download_datasource")


class TableauQueryDatasourceConnectionsConfig(BaseModel):
    """List the connections of a data source."""
    operation: Literal["query_datasource_connections"] = Field(
        "query_datasource_connections",
        json_schema_extra={"const": "query_datasource_connections", "ui:hidden": True,
                           "x-category": _DS_CAT, "x-is-trigger": False,
                           "x-display-name": "Query Data Source Connections"},
        title="Query Data Source Connections",
    )
    datasource_id: str = Field(..., title="Data Source", json_schema_extra=_dyn("datasource_id", "a data source"))


async def _query_datasource_connections(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/datasources/{c.datasource_id}/connections",
        action_name="query_datasource_connections")


class TableauUpdateDatasourceConnectionConfig(BaseModel):
    """Update the server address, port, or credentials of a data source connection."""
    operation: Literal["update_datasource_connection"] = Field(
        "update_datasource_connection",
        json_schema_extra={"const": "update_datasource_connection", "ui:hidden": True,
                           "x-category": _DS_CAT, "x-is-trigger": False,
                           "x-display-name": "Update Data Source Connection"},
        title="Update Data Source Connection",
    )
    datasource_id: str = Field(..., title="Data Source", json_schema_extra=_dyn("datasource_id", "a data source"))
    connection_id: str = Field(..., title="Connection LUID")
    server_address: Optional[str] = Field(None, title="Server Address")
    server_port: Optional[str] = Field(None, title="Server Port")
    user_name: Optional[str] = Field(None, title="User Name")
    password: Optional[str] = Field(None, title="Password")
    embed_password: Optional[str] = Field(None, title="Embed Password",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    query_tagging_enabled: Optional[str] = Field(None, title="Query Tagging Enabled",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the connection body")


async def _update_datasource_connection(c, server_url, token, site_id) -> Dict[str, Any]:
    conn: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.server_address is not None: conn["serverAddress"] = c.server_address
    if c.server_port is not None: conn["serverPort"] = c.server_port
    if c.user_name is not None: conn["userName"] = c.user_name
    if c.password is not None: conn["password"] = c.password
    if c.embed_password is not None: conn["embedPassword"] = c.embed_password
    if c.query_tagging_enabled is not None: conn["queryTaggingEnabled"] = c.query_tagging_enabled
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/datasources/{c.datasource_id}/connections/{c.connection_id}",
        json_body={"connection": conn}, action_name="update_datasource_connection")


class TableauQueryDatasourceRevisionsConfig(BaseModel):
    """List the revisions of a data source."""
    operation: Literal["query_datasource_revisions"] = Field(
        "query_datasource_revisions",
        json_schema_extra={"const": "query_datasource_revisions", "ui:hidden": True,
                           "x-category": _DS_CAT, "x-is-trigger": False,
                           "x-display-name": "Get Data Source Revisions"},
        title="Get Data Source Revisions",
    )
    datasource_id: str = Field(..., title="Data Source", json_schema_extra=_dyn("datasource_id", "a data source"))
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _query_datasource_revisions(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/datasources/{c.datasource_id}/revisions",
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="query_datasource_revisions")


class TableauRemoveDatasourceRevisionConfig(BaseModel):
    """Remove a specific revision of a data source."""
    operation: Literal["remove_datasource_revision"] = Field(
        "remove_datasource_revision",
        json_schema_extra={"const": "remove_datasource_revision", "ui:hidden": True,
                           "x-category": _DS_CAT, "x-is-trigger": False,
                           "x-display-name": "Remove Data Source Revision"},
        title="Remove Data Source Revision",
    )
    datasource_id: str = Field(..., title="Data Source", json_schema_extra=_dyn("datasource_id", "a data source"))
    revision_number: str = Field(..., title="Revision Number")


async def _remove_datasource_revision(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/datasources/{c.datasource_id}/revisions/{c.revision_number}",
        action_name="remove_datasource_revision")


class TableauDownloadDatasourceRevisionConfig(BaseModel):
    """Download the content of a specific data source revision."""
    operation: Literal["download_datasource_revision"] = Field(
        "download_datasource_revision",
        json_schema_extra={"const": "download_datasource_revision", "ui:hidden": True,
                           "x-category": _DS_CAT, "x-is-trigger": False,
                           "x-display-name": "Download Data Source Revision"},
        title="Download Data Source Revision",
    )
    datasource_id: str = Field(..., title="Data Source", json_schema_extra=_dyn("datasource_id", "a data source"))
    revision_number: str = Field(..., title="Revision Number")


async def _download_datasource_revision(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/datasources/{c.datasource_id}/revisions/{c.revision_number}/content",
        raw_response=True, action_name="download_datasource_revision")


class TableauAddDatasourceTagsConfig(BaseModel):
    """Add one or more tags to a data source."""
    operation: Literal["add_datasource_tags"] = Field(
        "add_datasource_tags",
        json_schema_extra={"const": "add_datasource_tags", "ui:hidden": True,
                           "x-category": _DS_CAT, "x-is-trigger": False,
                           "x-display-name": "Add Tags to Data Source"},
        title="Add Tags to Data Source",
    )
    datasource_id: str = Field(..., title="Data Source", json_schema_extra=_dyn("datasource_id", "a data source"))
    tags: str = Field(..., title="Tags", description="Comma-separated tag labels")


async def _add_datasource_tags(c, server_url, token, site_id) -> Dict[str, Any]:
    labels = [{"label": t.strip()} for t in c.tags.split(",") if t.strip()]
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/datasources/{c.datasource_id}/tags",
        json_body={"tags": {"tag": labels}}, action_name="add_datasource_tags")


class TableauDeleteDatasourceTagConfig(BaseModel):
    """Delete a tag from a data source."""
    operation: Literal["delete_datasource_tag"] = Field(
        "delete_datasource_tag",
        json_schema_extra={"const": "delete_datasource_tag", "ui:hidden": True,
                           "x-category": _DS_CAT, "x-is-trigger": False,
                           "x-display-name": "Delete Tag from Data Source"},
        title="Delete Tag from Data Source",
    )
    datasource_id: str = Field(..., title="Data Source", json_schema_extra=_dyn("datasource_id", "a data source"))
    tag_name: str = Field(..., title="Tag Name")


async def _delete_datasource_tag(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/datasources/{c.datasource_id}/tags/{c.tag_name}",
        action_name="delete_datasource_tag")


class TableauAddDatasourcePermissionsConfig(BaseModel):
    """Add permissions (grantee capabilities) to a data source."""
    operation: Literal["add_datasource_permissions"] = Field(
        "add_datasource_permissions",
        json_schema_extra={"const": "add_datasource_permissions", "ui:hidden": True,
                           "x-category": _DS_CAT, "x-is-trigger": False,
                           "x-display-name": "Add Data Source Permissions"},
        title="Add Data Source Permissions",
    )
    datasource_id: str = Field(..., title="Data Source", json_schema_extra=_dyn("datasource_id", "a data source"))
    body_json: str = Field(..., title="Permissions Body (JSON)",
        description='JSON for granteeCapabilities, e.g. {"granteeCapabilities":[{"user":{"id":"..."},"capabilities":{"capability":[{"name":"Read","mode":"Allow"}]}}]}')


async def _add_datasource_permissions(c, server_url, token, site_id) -> Dict[str, Any]:
    permissions: Dict[str, Any] = json.loads(c.body_json)
    permissions.setdefault("datasource", {"id": c.datasource_id})
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/datasources/{c.datasource_id}/permissions",
        json_body={"permissions": permissions}, action_name="add_datasource_permissions")


class TableauQueryDatasourcePermissionsConfig(BaseModel):
    """List the permissions on a data source."""
    operation: Literal["query_datasource_permissions"] = Field(
        "query_datasource_permissions",
        json_schema_extra={"const": "query_datasource_permissions", "ui:hidden": True,
                           "x-category": _DS_CAT, "x-is-trigger": False,
                           "x-display-name": "Query Data Source Permissions"},
        title="Query Data Source Permissions",
    )
    datasource_id: str = Field(..., title="Data Source", json_schema_extra=_dyn("datasource_id", "a data source"))


async def _query_datasource_permissions(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/datasources/{c.datasource_id}/permissions",
        action_name="query_datasource_permissions")


class TableauDeleteDatasourcePermissionConfig(BaseModel):
    """Delete a single capability from a user or group on a data source."""
    operation: Literal["delete_datasource_permission"] = Field(
        "delete_datasource_permission",
        json_schema_extra={"const": "delete_datasource_permission", "ui:hidden": True,
                           "x-category": _DS_CAT, "x-is-trigger": False,
                           "x-display-name": "Delete Data Source Permission"},
        title="Delete Data Source Permission",
    )
    datasource_id: str = Field(..., title="Data Source", json_schema_extra=_dyn("datasource_id", "a data source"))
    entity_type: str = Field("users", title="Grantee Type",
        json_schema_extra={"enum": ["users", "groups"], "x-enum-searchable": True})
    entity_id: str = Field(..., title="User or Group LUID")
    capability_name: str = Field(..., title="Capability Name",
        description="e.g. Connect, Read, Write, ExportXml, ChangePermissions, ExtractRefresh")
    capability_mode: str = Field("Allow", title="Capability Mode",
        json_schema_extra={"enum": ["Allow", "Deny"], "x-enum-searchable": True})


async def _delete_datasource_permission(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/datasources/{c.datasource_id}/permissions/"
        f"{c.entity_type}/{c.entity_id}/{c.capability_name}/{c.capability_mode}",
        action_name="delete_datasource_permission")


class TableauRetrieveDatasourceKeychainConfig(BaseModel):
    """Retrieve the encrypted keychain of a data source (for migration to another site)."""
    operation: Literal["retrieve_datasource_keychain"] = Field(
        "retrieve_datasource_keychain",
        json_schema_extra={"const": "retrieve_datasource_keychain", "ui:hidden": True,
                           "x-category": _DS_CAT, "x-is-trigger": False,
                           "x-display-name": "Retrieve Data Source Keychain"},
        title="Retrieve Data Source Keychain",
    )
    datasource_id: str = Field(..., title="Data Source", json_schema_extra=_dyn("datasource_id", "a data source"))
    destination_site_url_namespace: Optional[str] = Field(None, title="Destination Site URL Namespace")
    destination_site_luid: Optional[str] = Field(None, title="Destination Site LUID")
    destination_server_url: Optional[str] = Field(None, title="Destination Server URL")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the retrieveKeychain body")


async def _retrieve_datasource_keychain(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.destination_site_url_namespace is not None:
        body["destinationSiteUrlNamespace"] = c.destination_site_url_namespace
    if c.destination_site_luid is not None:
        body["destinationSiteLuid"] = c.destination_site_luid
    if c.destination_server_url is not None:
        body["destinationServerUrl"] = c.destination_server_url
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/datasources/{c.datasource_id}/retrieveKeychain",
        json_body=body or None, action_name="retrieve_datasource_keychain")


class TableauUpdateDatasourceDataConfig(BaseModel):
    """Update data in a published Hyper data source via insert/update/delete/replace actions."""
    operation: Literal["update_datasource_data"] = Field(
        "update_datasource_data",
        json_schema_extra={"const": "update_datasource_data", "ui:hidden": True,
                           "x-category": _DS_CAT, "x-is-trigger": False,
                           "x-display-name": "Update Data in Hyper Data Source"},
        title="Update Data in Hyper Data Source",
    )
    datasource_id: str = Field(..., title="Data Source", json_schema_extra=_dyn("datasource_id", "a data source"))
    upload_session_id: str = Field(..., title="Upload Session ID",
        description="ID from a prior file upload containing the source Hyper payload")
    actions_json: str = Field(..., title="Actions (JSON)",
        description='JSON array of actions, e.g. [{"action":"upsert","source-schema":"Extract","source-table":"Extract","target-schema":"Extract","target-table":"Extract","condition":{...}}]')


async def _update_datasource_data(c, server_url, token, site_id) -> Dict[str, Any]:
    actions = json.loads(c.actions_json)
    return await _tableau_request(server_url, token, "PATCH",
        f"/sites/{site_id}/datasources/{c.datasource_id}/data",
        params={"uploadSessionId": c.upload_session_id},
        json_body={"actions": actions}, action_name="update_datasource_data")


class TableauUpdateDatasourceConnectionDataConfig(BaseModel):
    """Update data in a specific Hyper connection of a data source."""
    operation: Literal["update_datasource_connection_data"] = Field(
        "update_datasource_connection_data",
        json_schema_extra={"const": "update_datasource_connection_data", "ui:hidden": True,
                           "x-category": _DS_CAT, "x-is-trigger": False,
                           "x-display-name": "Update Data in Hyper Connection"},
        title="Update Data in Hyper Connection",
    )
    datasource_id: str = Field(..., title="Data Source", json_schema_extra=_dyn("datasource_id", "a data source"))
    connection_id: str = Field(..., title="Connection LUID")
    upload_session_id: str = Field(..., title="Upload Session ID",
        description="ID from a prior file upload containing the source Hyper payload")
    actions_json: str = Field(..., title="Actions (JSON)",
        description="JSON array of insert/update/delete/replace/upsert actions")


async def _update_datasource_connection_data(c, server_url, token, site_id) -> Dict[str, Any]:
    actions = json.loads(c.actions_json)
    return await _tableau_request(server_url, token, "PATCH",
        f"/sites/{site_id}/datasources/{c.datasource_id}/connections/{c.connection_id}/data",
        params={"uploadSessionId": c.upload_session_id},
        json_body={"actions": actions}, action_name="update_datasource_connection_data")


OPERATION_CONFIGS.extend([
    TableauUpdateDatasourceConfig,
    TableauDownloadDatasourceConfig,
    TableauQueryDatasourceConnectionsConfig,
    TableauUpdateDatasourceConnectionConfig,
    TableauQueryDatasourceRevisionsConfig,
    TableauRemoveDatasourceRevisionConfig,
    TableauDownloadDatasourceRevisionConfig,
    TableauAddDatasourceTagsConfig,
    TableauDeleteDatasourceTagConfig,
    TableauAddDatasourcePermissionsConfig,
    TableauQueryDatasourcePermissionsConfig,
    TableauDeleteDatasourcePermissionConfig,
    TableauRetrieveDatasourceKeychainConfig,
    TableauUpdateDatasourceDataConfig,
    TableauUpdateDatasourceConnectionDataConfig,
])
OPERATION_HANDLERS.update({
    "update_datasource": _update_datasource,
    "download_datasource": _download_datasource,
    "query_datasource_connections": _query_datasource_connections,
    "update_datasource_connection": _update_datasource_connection,
    "query_datasource_revisions": _query_datasource_revisions,
    "remove_datasource_revision": _remove_datasource_revision,
    "download_datasource_revision": _download_datasource_revision,
    "add_datasource_tags": _add_datasource_tags,
    "delete_datasource_tag": _delete_datasource_tag,
    "add_datasource_permissions": _add_datasource_permissions,
    "query_datasource_permissions": _query_datasource_permissions,
    "delete_datasource_permission": _delete_datasource_permission,
    "retrieve_datasource_keychain": _retrieve_datasource_keychain,
    "update_datasource_data": _update_datasource_data,
    "update_datasource_connection_data": _update_datasource_connection_data,
})

# ==================== FLOW (Tableau Prep) OPERATIONS ====================

class TableauQueryFlowsConfig(BaseModel):
    """Query all flows on the site."""
    operation: Literal["query_flows"] = Field(
        "query_flows",
        json_schema_extra={"const": "query_flows", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Query Flows"},
        title="Query Flows",
    )
    filter: Optional[str] = Field(None, title="Filter",
        description="Filter expression, e.g. name:eq:MyFlow")
    sort: Optional[str] = Field(None, title="Sort")
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _query_flows(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/flows",
        params={"filter": c.filter, "sort": c.sort,
                "pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="query_flows")


class TableauGetFlowConfig(BaseModel):
    """Get a single flow by LUID."""
    operation: Literal["get_flow"] = Field(
        "get_flow",
        json_schema_extra={"const": "get_flow", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Get Flow"},
        title="Get Flow",
    )
    flow_id: str = Field(..., title="Flow", json_schema_extra=_dyn("flow_id", "a flow"))


async def _get_flow(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/flows/{c.flow_id}",
        action_name="get_flow")


class TableauQueryFlowsForUserConfig(BaseModel):
    """Query flows owned by / available to a user."""
    operation: Literal["query_flows_for_user"] = Field(
        "query_flows_for_user",
        json_schema_extra={"const": "query_flows_for_user", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Query Flows For User"},
        title="Query Flows For User",
    )
    user_id: str = Field(..., title="User", json_schema_extra=_dyn("user_id", "a user"))
    owned_by: Optional[str] = Field(None, title="Owned By",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _query_flows_for_user(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/users/{c.user_id}/flows",
        params={"ownedBy": c.owned_by,
                "pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="query_flows_for_user")


class TableauUpdateFlowConfig(BaseModel):
    """Update a flow's name, description, or project."""
    operation: Literal["update_flow"] = Field(
        "update_flow",
        json_schema_extra={"const": "update_flow", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Update Flow"},
        title="Update Flow",
    )
    flow_id: str = Field(..., title="Flow", json_schema_extra=_dyn("flow_id", "a flow"))
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(None, title="Description")
    project_id: Optional[str] = Field(None, title="Project",
        json_schema_extra=_dyn("project_id", "a project"))
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the flow body for advanced fields")


async def _update_flow(c, server_url, token, site_id) -> Dict[str, Any]:
    flow: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: flow["name"] = c.name
    if c.description is not None: flow["description"] = c.description
    if c.project_id is not None: flow["project"] = {"id": c.project_id}
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/flows/{c.flow_id}",
        json_body={"flow": flow}, action_name="update_flow")


class TableauDeleteFlowConfig(BaseModel):
    """Delete a flow."""
    operation: Literal["delete_flow"] = Field(
        "delete_flow",
        json_schema_extra={"const": "delete_flow", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Delete Flow"},
        title="Delete Flow",
    )
    flow_id: str = Field(..., title="Flow", json_schema_extra=_dyn("flow_id", "a flow"))


async def _delete_flow(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/flows/{c.flow_id}",
        action_name="delete_flow")


class TableauDownloadFlowConfig(BaseModel):
    """Download a flow (.tfl / .tflx)."""
    operation: Literal["download_flow"] = Field(
        "download_flow",
        json_schema_extra={"const": "download_flow", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Download Flow"},
        title="Download Flow",
    )
    flow_id: str = Field(..., title="Flow", json_schema_extra=_dyn("flow_id", "a flow"))


async def _download_flow(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/flows/{c.flow_id}/content",
        raw_response=True, action_name="download_flow")


class TableauRunFlowNowConfig(BaseModel):
    """Run a flow immediately."""
    operation: Literal["run_flow_now"] = Field(
        "run_flow_now",
        json_schema_extra={"const": "run_flow_now", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Run Flow Now"},
        title="Run Flow Now",
    )
    flow_id: str = Field(..., title="Flow", json_schema_extra=_dyn("flow_id", "a flow"))
    run_mode: Optional[str] = Field(None, title="Run Mode",
        json_schema_extra={"enum": ["full", "incremental"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into flowRunSpec (output steps, flow parameters)")


async def _run_flow_now(c, server_url, token, site_id) -> Dict[str, Any]:
    spec: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.run_mode is not None: spec["runMode"] = c.run_mode
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/flows/{c.flow_id}/runs",
        json_body={"flowRunSpec": spec}, action_name="run_flow_now")


class TableauGetFlowRunsConfig(BaseModel):
    """Get all flow runs on the site."""
    operation: Literal["get_flow_runs"] = Field(
        "get_flow_runs",
        json_schema_extra={"const": "get_flow_runs", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Get Flow Runs"},
        title="Get Flow Runs",
    )
    filter: Optional[str] = Field(None, title="Filter")


async def _get_flow_runs(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/flows/runs",
        params={"filter": c.filter}, action_name="get_flow_runs")


class TableauGetFlowRunConfig(BaseModel):
    """Get a single flow run by LUID."""
    operation: Literal["get_flow_run"] = Field(
        "get_flow_run",
        json_schema_extra={"const": "get_flow_run", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Get Flow Run"},
        title="Get Flow Run",
    )
    flow_run_id: str = Field(..., title="Flow Run LUID")


async def _get_flow_run(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/flows/runs/{c.flow_run_id}",
        action_name="get_flow_run")


class TableauCancelFlowRunConfig(BaseModel):
    """Cancel an in-progress flow run."""
    operation: Literal["cancel_flow_run"] = Field(
        "cancel_flow_run",
        json_schema_extra={"const": "cancel_flow_run", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Cancel Flow Run"},
        title="Cancel Flow Run",
    )
    flow_run_id: str = Field(..., title="Flow Run LUID")


async def _cancel_flow_run(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/flows/runs/{c.flow_run_id}",
        action_name="cancel_flow_run")


class TableauQueryFlowConnectionsConfig(BaseModel):
    """List a flow's connections."""
    operation: Literal["query_flow_connections"] = Field(
        "query_flow_connections",
        json_schema_extra={"const": "query_flow_connections", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Query Flow Connections"},
        title="Query Flow Connections",
    )
    flow_id: str = Field(..., title="Flow", json_schema_extra=_dyn("flow_id", "a flow"))


async def _query_flow_connections(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/flows/{c.flow_id}/connections",
        action_name="query_flow_connections")


class TableauUpdateFlowConnectionConfig(BaseModel):
    """Update a flow connection."""
    operation: Literal["update_flow_connection"] = Field(
        "update_flow_connection",
        json_schema_extra={"const": "update_flow_connection", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Update Flow Connection"},
        title="Update Flow Connection",
    )
    flow_id: str = Field(..., title="Flow", json_schema_extra=_dyn("flow_id", "a flow"))
    connection_id: str = Field(..., title="Connection LUID")
    server_address: Optional[str] = Field(None, title="Server Address")
    server_port: Optional[str] = Field(None, title="Server Port")
    user_name: Optional[str] = Field(None, title="User Name")
    password: Optional[str] = Field(None, title="Password")
    embed_password: Optional[str] = Field(None, title="Embed Password",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the connection body")


async def _update_flow_connection(c, server_url, token, site_id) -> Dict[str, Any]:
    connection: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.server_address is not None: connection["serverAddress"] = c.server_address
    if c.server_port is not None: connection["serverPort"] = c.server_port
    if c.user_name is not None: connection["userName"] = c.user_name
    if c.password is not None: connection["password"] = c.password
    if c.embed_password is not None: connection["embedPassword"] = c.embed_password
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/flows/{c.flow_id}/connections/{c.connection_id}",
        json_body={"connection": connection}, action_name="update_flow_connection")


class TableauListFlowPermissionsConfig(BaseModel):
    """List a flow's permissions."""
    operation: Literal["list_flow_permissions"] = Field(
        "list_flow_permissions",
        json_schema_extra={"const": "list_flow_permissions", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "List Flow Permissions"},
        title="List Flow Permissions",
    )
    flow_id: str = Field(..., title="Flow", json_schema_extra=_dyn("flow_id", "a flow"))


async def _list_flow_permissions(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/flows/{c.flow_id}/permissions",
        action_name="list_flow_permissions")


class TableauAddFlowPermissionsConfig(BaseModel):
    """Add permissions (capabilities) to a flow for users/groups."""
    operation: Literal["add_flow_permissions"] = Field(
        "add_flow_permissions",
        json_schema_extra={"const": "add_flow_permissions", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Add Flow Permissions"},
        title="Add Flow Permissions",
    )
    flow_id: str = Field(..., title="Flow", json_schema_extra=_dyn("flow_id", "a flow"))
    body_json: str = Field(..., title="Permissions Body (JSON)",
        description='granteeCapabilities JSON, e.g. {"granteeCapabilities":[{"user":{"id":"..."},"capabilities":{"capability":[{"name":"Read","mode":"Allow"}]}}]}')


async def _add_flow_permissions(c, server_url, token, site_id) -> Dict[str, Any]:
    permissions: Dict[str, Any] = json.loads(c.body_json)
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/flows/{c.flow_id}/permissions",
        json_body={"permissions": permissions}, action_name="add_flow_permissions")


class TableauDeleteFlowPermissionConfig(BaseModel):
    """Delete a single flow permission (capability) for a grantee."""
    operation: Literal["delete_flow_permission"] = Field(
        "delete_flow_permission",
        json_schema_extra={"const": "delete_flow_permission", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Delete Flow Permission"},
        title="Delete Flow Permission",
    )
    flow_id: str = Field(..., title="Flow", json_schema_extra=_dyn("flow_id", "a flow"))
    grantee_type: str = Field(..., title="Grantee Type",
        json_schema_extra={"enum": ["users", "groups"], "x-enum-searchable": True})
    grantee_id: str = Field(..., title="Grantee LUID")
    capability_name: str = Field(..., title="Capability Name")
    capability_mode: str = Field(..., title="Capability Mode",
        json_schema_extra={"enum": ["Allow", "Deny"], "x-enum-searchable": True})


async def _delete_flow_permission(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/flows/{c.flow_id}/permissions/{c.grantee_type}/{c.grantee_id}/{c.capability_name}/{c.capability_mode}",
        action_name="delete_flow_permission")


class TableauGetFlowRunTasksConfig(BaseModel):
    """Get all scheduled flow-run tasks on the site."""
    operation: Literal["get_flow_run_tasks"] = Field(
        "get_flow_run_tasks",
        json_schema_extra={"const": "get_flow_run_tasks", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Get Flow Run Tasks"},
        title="Get Flow Run Tasks",
    )


async def _get_flow_run_tasks(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/tasks/runFlow",
        action_name="get_flow_run_tasks")


class TableauGetFlowRunTaskConfig(BaseModel):
    """Get a single scheduled flow-run task by LUID."""
    operation: Literal["get_flow_run_task"] = Field(
        "get_flow_run_task",
        json_schema_extra={"const": "get_flow_run_task", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Get Flow Run Task"},
        title="Get Flow Run Task",
    )
    task_id: str = Field(..., title="Task LUID")


async def _get_flow_run_task(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/tasks/runFlow/{c.task_id}",
        action_name="get_flow_run_task")


class TableauRunFlowTaskConfig(BaseModel):
    """Run a scheduled flow-run task immediately."""
    operation: Literal["run_flow_task"] = Field(
        "run_flow_task",
        json_schema_extra={"const": "run_flow_task", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Run Flow Task Now"},
        title="Run Flow Task Now",
    )
    task_id: str = Field(..., title="Task LUID")


async def _run_flow_task(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/tasks/runFlow/{c.task_id}/runNow",
        action_name="run_flow_task")


class TableauGetLinkedTasksConfig(BaseModel):
    """Get all linked tasks on the site."""
    operation: Literal["get_linked_tasks"] = Field(
        "get_linked_tasks",
        json_schema_extra={"const": "get_linked_tasks", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Get Linked Tasks"},
        title="Get Linked Tasks",
    )


async def _get_linked_tasks(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/tasks/linked",
        action_name="get_linked_tasks")


class TableauGetLinkedTaskConfig(BaseModel):
    """Get a single linked task by LUID."""
    operation: Literal["get_linked_task"] = Field(
        "get_linked_task",
        json_schema_extra={"const": "get_linked_task", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Get Linked Task"},
        title="Get Linked Task",
    )
    linked_task_id: str = Field(..., title="Linked Task LUID")


async def _get_linked_task(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/tasks/linked/{c.linked_task_id}",
        action_name="get_linked_task")


class TableauRunLinkedTaskNowConfig(BaseModel):
    """Run a linked task immediately."""
    operation: Literal["run_linked_task_now"] = Field(
        "run_linked_task_now",
        json_schema_extra={"const": "run_linked_task_now", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Run Linked Task Now"},
        title="Run Linked Task Now",
    )
    linked_task_id: str = Field(..., title="Linked Task LUID")


async def _run_linked_task_now(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/tasks/linked/{c.linked_task_id}/runs",
        action_name="run_linked_task_now")


class TableauCreateFlowTaskConfig(BaseModel):
    """Create a scheduled (Tableau Cloud) flow task."""
    operation: Literal["create_flow_task"] = Field(
        "create_flow_task",
        json_schema_extra={"const": "create_flow_task", "ui:hidden": True,
                           "x-category": "Flow", "x-is-trigger": False,
                           "x-display-name": "Create Cloud Flow Task"},
        title="Create Cloud Flow Task",
    )
    body_json: str = Field(..., title="Flow Task Body (JSON)",
        description='schedule + flow spec JSON, e.g. {"schedule":{"frequency":"Daily","frequencyDetails":{...}},"flowRunSpec":{"flowId":"..."}}')


async def _create_flow_task(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json)
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/tasks/flows",
        json_body=body, action_name="create_flow_task")


OPERATION_CONFIGS.extend([
    TableauQueryFlowsConfig,
    TableauGetFlowConfig,
    TableauQueryFlowsForUserConfig,
    TableauUpdateFlowConfig,
    TableauDeleteFlowConfig,
    TableauDownloadFlowConfig,
    TableauRunFlowNowConfig,
    TableauGetFlowRunsConfig,
    TableauGetFlowRunConfig,
    TableauCancelFlowRunConfig,
    TableauQueryFlowConnectionsConfig,
    TableauUpdateFlowConnectionConfig,
    TableauListFlowPermissionsConfig,
    TableauAddFlowPermissionsConfig,
    TableauDeleteFlowPermissionConfig,
    TableauGetFlowRunTasksConfig,
    TableauGetFlowRunTaskConfig,
    TableauRunFlowTaskConfig,
    TableauGetLinkedTasksConfig,
    TableauGetLinkedTaskConfig,
    TableauRunLinkedTaskNowConfig,
    TableauCreateFlowTaskConfig,
])
OPERATION_HANDLERS.update({
    "query_flows": _query_flows,
    "get_flow": _get_flow,
    "query_flows_for_user": _query_flows_for_user,
    "update_flow": _update_flow,
    "delete_flow": _delete_flow,
    "download_flow": _download_flow,
    "run_flow_now": _run_flow_now,
    "get_flow_runs": _get_flow_runs,
    "get_flow_run": _get_flow_run,
    "cancel_flow_run": _cancel_flow_run,
    "query_flow_connections": _query_flow_connections,
    "update_flow_connection": _update_flow_connection,
    "list_flow_permissions": _list_flow_permissions,
    "add_flow_permissions": _add_flow_permissions,
    "delete_flow_permission": _delete_flow_permission,
    "get_flow_run_tasks": _get_flow_run_tasks,
    "get_flow_run_task": _get_flow_run_task,
    "run_flow_task": _run_flow_task,
    "get_linked_tasks": _get_linked_tasks,
    "get_linked_task": _get_linked_task,
    "run_linked_task_now": _run_linked_task_now,
    "create_flow_task": _create_flow_task,
})

# ============================================================================
# Users and Groups
# ============================================================================

# ---- Users ---------------------------------------------------------------
class TableauUpdateUserConfig(BaseModel):
    """Update a user's full name, email, site role, or auth setting."""
    operation: Literal["update_user"] = Field(
        "update_user",
        json_schema_extra={"const": "update_user", "ui:hidden": True,
                           "x-category": "Users and Groups", "x-is-trigger": False,
                           "x-display-name": "Update User"},
        title="Update User",
    )
    user_id: str = Field(..., title="User LUID", description="LUID of the user to update")
    full_name: Optional[str] = Field(None, title="Full Name")
    email: Optional[str] = Field(None, title="Email")
    site_role: Optional[str] = Field(None, title="Site Role")
    auth_setting: Optional[str] = Field(None, title="Auth Setting")
    password: Optional[str] = Field(None, title="Password")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the user body for advanced fields")


async def _update_user(c, server_url, token, site_id) -> Dict[str, Any]:
    user: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.full_name is not None: user["fullName"] = c.full_name
    if c.email is not None: user["email"] = c.email
    if c.site_role is not None: user["siteRole"] = c.site_role
    if c.auth_setting is not None: user["authSetting"] = c.auth_setting
    if c.password is not None: user["password"] = c.password
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/users/{c.user_id}",
        json_body={"user": user}, action_name="update_user")


class TableauRemoveUserConfig(BaseModel):
    """Remove a user from the site."""
    operation: Literal["remove_user"] = Field(
        "remove_user",
        json_schema_extra={"const": "remove_user", "ui:hidden": True,
                           "x-category": "Users and Groups", "x-is-trigger": False,
                           "x-display-name": "Remove User from Site"},
        title="Remove User from Site",
    )
    user_id: str = Field(..., title="User LUID", description="LUID of the user to remove")
    map_assets_to: Optional[str] = Field(None, title="Map Assets To (User LUID)",
        description="LUID of the user to reassign the removed user's content to")


async def _remove_user(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/users/{c.user_id}",
        params={"mapAssetsTo": c.map_assets_to}, action_name="remove_user")


class TableauGetGroupsForUserConfig(BaseModel):
    """List the groups a user belongs to."""
    operation: Literal["get_groups_for_user"] = Field(
        "get_groups_for_user",
        json_schema_extra={"const": "get_groups_for_user", "ui:hidden": True,
                           "x-category": "Users and Groups", "x-is-trigger": False,
                           "x-display-name": "Get Groups for a User"},
        title="Get Groups for a User",
    )
    user_id: str = Field(..., title="User", json_schema_extra=_dyn("user_id", "a user"))
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _get_groups_for_user(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/users/{c.user_id}/groups",
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="get_groups_for_user")


class TableauImportUsersCsvConfig(BaseModel):
    """Import users to the site from a CSV payload."""
    operation: Literal["import_users_csv"] = Field(
        "import_users_csv",
        json_schema_extra={"const": "import_users_csv", "ui:hidden": True,
                           "x-category": "Users and Groups", "x-is-trigger": False,
                           "x-display-name": "Import Users from CSV"},
        title="Import Users from CSV",
    )
    body_json: Optional[str] = Field(None, title="Payload (JSON)",
        description="Raw JSON payload describing the users to import (CSV/multipart content)")


async def _import_users_csv(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/users/import",
        json_body=body or None, action_name="import_users_csv")


class TableauDeleteUsersCsvConfig(BaseModel):
    """Delete users from the site using a CSV payload."""
    operation: Literal["delete_users_csv"] = Field(
        "delete_users_csv",
        json_schema_extra={"const": "delete_users_csv", "ui:hidden": True,
                           "x-category": "Users and Groups", "x-is-trigger": False,
                           "x-display-name": "Delete Users from CSV"},
        title="Delete Users from CSV",
    )
    body_json: Optional[str] = Field(None, title="Payload (JSON)",
        description="Raw JSON payload describing the users to delete (CSV/multipart content)")


async def _delete_users_csv(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/users/delete",
        json_body=body or None, action_name="delete_users_csv")


# ---- Groups --------------------------------------------------------------
class TableauCreateGroupConfig(BaseModel):
    """Create a local group (or import an Active Directory group)."""
    operation: Literal["create_group"] = Field(
        "create_group",
        json_schema_extra={"const": "create_group", "ui:hidden": True,
            "x-creates-resource": True,
            "x-resource-type": "tableau_group",
            "x-resource-id-path": "data.group.id",
                           "x-category": "Users and Groups", "x-is-trigger": False,
                           "x-display-name": "Create Group"},
        title="Create Group",
    )
    name: Optional[str] = Field(None, title="Name")
    minimum_site_role: Optional[str] = Field(None, title="Minimum Site Role")
    as_job: Optional[str] = Field("false", title="As Job",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the group body (e.g. AD import settings)")


async def _create_group(c, server_url, token, site_id) -> Dict[str, Any]:
    group: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: group["name"] = c.name
    if c.minimum_site_role is not None: group["minimumSiteRole"] = c.minimum_site_role
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/groups",
        params={"asJob": c.as_job}, json_body={"group": group},
        action_name="create_group")


class TableauUpdateGroupConfig(BaseModel):
    """Update a group's name or import settings."""
    operation: Literal["update_group"] = Field(
        "update_group",
        json_schema_extra={"const": "update_group", "ui:hidden": True,
                           "x-category": "Users and Groups", "x-is-trigger": False,
                           "x-display-name": "Update Group"},
        title="Update Group",
    )
    group_id: str = Field(..., title="Group", description="LUID of the group",
        json_schema_extra=_dyn("group_id", "a group"))
    name: Optional[str] = Field(None, title="Name")
    minimum_site_role: Optional[str] = Field(None, title="Minimum Site Role")
    as_job: Optional[str] = Field("false", title="As Job",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the group body (e.g. AD import settings)")


async def _update_group(c, server_url, token, site_id) -> Dict[str, Any]:
    group: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: group["name"] = c.name
    if c.minimum_site_role is not None: group["minimumSiteRole"] = c.minimum_site_role
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/groups/{c.group_id}",
        params={"asJob": c.as_job}, json_body={"group": group},
        action_name="update_group")


class TableauDeleteGroupConfig(BaseModel):
    """Delete a group from the site."""
    operation: Literal["delete_group"] = Field(
        "delete_group",
        json_schema_extra={"const": "delete_group", "ui:hidden": True,
                           "x-category": "Users and Groups", "x-is-trigger": False,
                           "x-display-name": "Delete Group"},
        title="Delete Group",
    )
    group_id: str = Field(..., title="Group", description="LUID of the group",
        json_schema_extra=_dyn("group_id", "a group"))


async def _delete_group(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/groups/{c.group_id}", action_name="delete_group")


class TableauGetUsersInGroupConfig(BaseModel):
    """List the users that belong to a group."""
    operation: Literal["get_users_in_group"] = Field(
        "get_users_in_group",
        json_schema_extra={"const": "get_users_in_group", "ui:hidden": True,
                           "x-category": "Users and Groups", "x-is-trigger": False,
                           "x-display-name": "Get Users in Group"},
        title="Get Users in Group",
    )
    group_id: str = Field(..., title="Group", description="LUID of the group",
        json_schema_extra=_dyn("group_id", "a group"))
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _get_users_in_group(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/groups/{c.group_id}/users",
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="get_users_in_group")


class TableauRemoveUserFromGroupConfig(BaseModel):
    """Remove a user from a group."""
    operation: Literal["remove_user_from_group"] = Field(
        "remove_user_from_group",
        json_schema_extra={"const": "remove_user_from_group", "ui:hidden": True,
                           "x-category": "Users and Groups", "x-is-trigger": False,
                           "x-display-name": "Remove User from Group"},
        title="Remove User from Group",
    )
    group_id: str = Field(..., title="Group", description="LUID of the group",
        json_schema_extra=_dyn("group_id", "a group"))
    user_id: str = Field(..., title="User", json_schema_extra=_dyn("user_id", "a user"))


async def _remove_user_from_group(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/groups/{c.group_id}/users/{c.user_id}",
        action_name="remove_user_from_group")


# ---- Group Sets ----------------------------------------------------------
class TableauCreateGroupSetConfig(BaseModel):
    """Create a group set."""
    operation: Literal["create_group_set"] = Field(
        "create_group_set",
        json_schema_extra={"const": "create_group_set", "ui:hidden": True,
                           "x-category": "Users and Groups", "x-is-trigger": False,
                           "x-display-name": "Create Group Set"},
        title="Create Group Set",
    )
    name: Optional[str] = Field(None, title="Name")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the group set body")


async def _create_group_set(c, server_url, token, site_id) -> Dict[str, Any]:
    group_set: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: group_set["name"] = c.name
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/groupsets",
        json_body={"groupSet": group_set}, action_name="create_group_set")


class TableauUpdateGroupSetConfig(BaseModel):
    """Update a group set's properties."""
    operation: Literal["update_group_set"] = Field(
        "update_group_set",
        json_schema_extra={"const": "update_group_set", "ui:hidden": True,
                           "x-category": "Users and Groups", "x-is-trigger": False,
                           "x-display-name": "Update Group Set"},
        title="Update Group Set",
    )
    group_set_id: str = Field(..., title="Group Set LUID")
    name: Optional[str] = Field(None, title="Name")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the group set body")


async def _update_group_set(c, server_url, token, site_id) -> Dict[str, Any]:
    group_set: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: group_set["name"] = c.name
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/groupsets/{c.group_set_id}",
        json_body={"groupSet": group_set}, action_name="update_group_set")


class TableauDeleteGroupSetConfig(BaseModel):
    """Delete a group set."""
    operation: Literal["delete_group_set"] = Field(
        "delete_group_set",
        json_schema_extra={"const": "delete_group_set", "ui:hidden": True,
                           "x-category": "Users and Groups", "x-is-trigger": False,
                           "x-display-name": "Delete Group Set"},
        title="Delete Group Set",
    )
    group_set_id: str = Field(..., title="Group Set LUID")


async def _delete_group_set(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/groupsets/{c.group_set_id}",
        action_name="delete_group_set")


class TableauGetGroupSetConfig(BaseModel):
    """Get a single group set by LUID."""
    operation: Literal["get_group_set"] = Field(
        "get_group_set",
        json_schema_extra={"const": "get_group_set", "ui:hidden": True,
                           "x-category": "Users and Groups", "x-is-trigger": False,
                           "x-display-name": "Get Group Set"},
        title="Get Group Set",
    )
    group_set_id: str = Field(..., title="Group Set LUID")


async def _get_group_set(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/groupsets/{c.group_set_id}",
        action_name="get_group_set")


class TableauQueryGroupSetsConfig(BaseModel):
    """List group sets on the site."""
    operation: Literal["query_group_sets"] = Field(
        "query_group_sets",
        json_schema_extra={"const": "query_group_sets", "ui:hidden": True,
                           "x-category": "Users and Groups", "x-is-trigger": False,
                           "x-display-name": "Query Group Sets"},
        title="Query Group Sets",
    )
    filter: Optional[str] = Field(None, title="Filter")
    sort: Optional[str] = Field(None, title="Sort")
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _query_group_sets(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/groupsets",
        params={"filter": c.filter, "sort": c.sort,
                "pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="query_group_sets")


class TableauGetGroupsInGroupSetConfig(BaseModel):
    """List the groups that belong to a group set."""
    operation: Literal["get_groups_in_group_set"] = Field(
        "get_groups_in_group_set",
        json_schema_extra={"const": "get_groups_in_group_set", "ui:hidden": True,
                           "x-category": "Users and Groups", "x-is-trigger": False,
                           "x-display-name": "Get Groups in Group Set"},
        title="Get Groups in Group Set",
    )
    group_set_id: str = Field(..., title="Group Set LUID")
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _get_groups_in_group_set(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/groupsets/{c.group_set_id}/groups",
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="get_groups_in_group_set")


class TableauAddGroupToGroupSetConfig(BaseModel):
    """Add a group to a group set."""
    operation: Literal["add_group_to_group_set"] = Field(
        "add_group_to_group_set",
        json_schema_extra={"const": "add_group_to_group_set", "ui:hidden": True,
                           "x-category": "Users and Groups", "x-is-trigger": False,
                           "x-display-name": "Add Group to Group Set"},
        title="Add Group to Group Set",
    )
    group_set_id: str = Field(..., title="Group Set LUID")
    group_id: str = Field(..., title="Group", description="LUID of the group",
        json_schema_extra=_dyn("group_id", "a group"))


async def _add_group_to_group_set(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/groupsets/{c.group_set_id}/groups/{c.group_id}",
        action_name="add_group_to_group_set")


class TableauRemoveGroupFromGroupSetConfig(BaseModel):
    """Remove a group from a group set."""
    operation: Literal["remove_group_from_group_set"] = Field(
        "remove_group_from_group_set",
        json_schema_extra={"const": "remove_group_from_group_set", "ui:hidden": True,
                           "x-category": "Users and Groups", "x-is-trigger": False,
                           "x-display-name": "Remove Group from Group Set"},
        title="Remove Group from Group Set",
    )
    group_set_id: str = Field(..., title="Group Set LUID")
    group_id: str = Field(..., title="Group", description="LUID of the group",
        json_schema_extra=_dyn("group_id", "a group"))


async def _remove_group_from_group_set(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/groupsets/{c.group_set_id}/groups/{c.group_id}",
        action_name="remove_group_from_group_set")


OPERATION_CONFIGS.extend([
    TableauUpdateUserConfig,
    TableauRemoveUserConfig,
    TableauGetGroupsForUserConfig,
    TableauImportUsersCsvConfig,
    TableauDeleteUsersCsvConfig,
    TableauCreateGroupConfig,
    TableauUpdateGroupConfig,
    TableauDeleteGroupConfig,
    TableauGetUsersInGroupConfig,
    TableauRemoveUserFromGroupConfig,
    TableauCreateGroupSetConfig,
    TableauUpdateGroupSetConfig,
    TableauDeleteGroupSetConfig,
    TableauGetGroupSetConfig,
    TableauQueryGroupSetsConfig,
    TableauGetGroupsInGroupSetConfig,
    TableauAddGroupToGroupSetConfig,
    TableauRemoveGroupFromGroupSetConfig,
])
OPERATION_HANDLERS.update({
    "update_user": _update_user,
    "remove_user": _remove_user,
    "get_groups_for_user": _get_groups_for_user,
    "import_users_csv": _import_users_csv,
    "delete_users_csv": _delete_users_csv,
    "create_group": _create_group,
    "update_group": _update_group,
    "delete_group": _delete_group,
    "get_users_in_group": _get_users_in_group,
    "remove_user_from_group": _remove_user_from_group,
    "create_group_set": _create_group_set,
    "update_group_set": _update_group_set,
    "delete_group_set": _delete_group_set,
    "get_group_set": _get_group_set,
    "query_group_sets": _query_group_sets,
    "get_groups_in_group_set": _get_groups_in_group_set,
    "add_group_to_group_set": _add_group_to_group_set,
    "remove_group_from_group_set": _remove_group_from_group_set,
})


# ==================== FAVORITES ====================

_FAV_CAT = "Favorites"


class TableauAddWorkbookFavoriteConfig(BaseModel):
    """Add a workbook to a user's favorites."""
    operation: Literal["add_workbook_favorite"] = Field(
        "add_workbook_favorite",
        json_schema_extra={"const": "add_workbook_favorite", "ui:hidden": True,
                           "x-category": _FAV_CAT, "x-is-trigger": False,
                           "x-display-name": "Add Workbook to Favorites"},
        title="Add Workbook to Favorites",
    )
    user_id: str = Field(..., title="User LUID", description="LUID of the user whose favorites to add to")
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))
    label: str = Field(..., title="Label", description="A label to assign to the favorite")


async def _add_workbook_favorite(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/favorites/{c.user_id}",
        json_body={"favorite": {"label": c.label, "workbook": {"id": c.workbook_id}}},
        action_name="add_workbook_favorite")


class TableauAddDatasourceFavoriteConfig(BaseModel):
    """Add a data source to a user's favorites."""
    operation: Literal["add_datasource_favorite"] = Field(
        "add_datasource_favorite",
        json_schema_extra={"const": "add_datasource_favorite", "ui:hidden": True,
                           "x-category": _FAV_CAT, "x-is-trigger": False,
                           "x-display-name": "Add Data Source to Favorites"},
        title="Add Data Source to Favorites",
    )
    user_id: str = Field(..., title="User LUID", description="LUID of the user whose favorites to add to")
    datasource_id: str = Field(..., title="Data Source", json_schema_extra=_dyn("datasource_id", "a data source"))
    label: str = Field(..., title="Label", description="A label to assign to the favorite")


async def _add_datasource_favorite(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/favorites/{c.user_id}",
        json_body={"favorite": {"label": c.label, "datasource": {"id": c.datasource_id}}},
        action_name="add_datasource_favorite")


class TableauAddViewFavoriteConfig(BaseModel):
    """Add a view to a user's favorites."""
    operation: Literal["add_view_favorite"] = Field(
        "add_view_favorite",
        json_schema_extra={"const": "add_view_favorite", "ui:hidden": True,
                           "x-category": _FAV_CAT, "x-is-trigger": False,
                           "x-display-name": "Add View to Favorites"},
        title="Add View to Favorites",
    )
    user_id: str = Field(..., title="User LUID", description="LUID of the user whose favorites to add to")
    view_id: str = Field(..., title="View", json_schema_extra=_dyn("view_id", "a view"))
    label: str = Field(..., title="Label", description="A label to assign to the favorite")


async def _add_view_favorite(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/favorites/{c.user_id}",
        json_body={"favorite": {"label": c.label, "view": {"id": c.view_id}}},
        action_name="add_view_favorite")


class TableauAddProjectFavoriteConfig(BaseModel):
    """Add a project to a user's favorites."""
    operation: Literal["add_project_favorite"] = Field(
        "add_project_favorite",
        json_schema_extra={"const": "add_project_favorite", "ui:hidden": True,
                           "x-category": _FAV_CAT, "x-is-trigger": False,
                           "x-display-name": "Add Project to Favorites"},
        title="Add Project to Favorites",
    )
    user_id: str = Field(..., title="User LUID", description="LUID of the user whose favorites to add to")
    project_id: str = Field(..., title="Project", description="LUID of the project",
        json_schema_extra=_dyn("project_id", "a project"))
    label: str = Field(..., title="Label", description="A label to assign to the favorite")


async def _add_project_favorite(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/favorites/{c.user_id}",
        json_body={"favorite": {"label": c.label, "project": {"id": c.project_id}}},
        action_name="add_project_favorite")


class TableauAddFlowFavoriteConfig(BaseModel):
    """Add a flow to a user's favorites."""
    operation: Literal["add_flow_favorite"] = Field(
        "add_flow_favorite",
        json_schema_extra={"const": "add_flow_favorite", "ui:hidden": True,
                           "x-category": _FAV_CAT, "x-is-trigger": False,
                           "x-display-name": "Add Flow to Favorites"},
        title="Add Flow to Favorites",
    )
    user_id: str = Field(..., title="User LUID", description="LUID of the user whose favorites to add to")
    flow_id: str = Field(..., title="Flow", json_schema_extra=_dyn("flow_id", "a flow"))
    label: str = Field(..., title="Label", description="A label to assign to the favorite")


async def _add_flow_favorite(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/favorites/{c.user_id}",
        json_body={"favorite": {"label": c.label, "flow": {"id": c.flow_id}}},
        action_name="add_flow_favorite")


class TableauAddMetricFavoriteConfig(BaseModel):
    """Add a metric to a user's favorites (retired in API 3.22)."""
    operation: Literal["add_metric_favorite"] = Field(
        "add_metric_favorite",
        json_schema_extra={"const": "add_metric_favorite", "ui:hidden": True,
                           "x-category": _FAV_CAT, "x-is-trigger": False,
                           "x-display-name": "Add Metric to Favorites"},
        title="Add Metric to Favorites",
    )
    user_id: str = Field(..., title="User LUID", description="LUID of the user whose favorites to add to")
    metric_id: str = Field(..., title="Metric LUID")
    label: str = Field(..., title="Label", description="A label to assign to the favorite")


async def _add_metric_favorite(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/favorites/{c.user_id}",
        json_body={"favorite": {"label": c.label, "metric": {"id": c.metric_id}}},
        action_name="add_metric_favorite")


class TableauGetUserFavoritesConfig(BaseModel):
    """Get the favorites for a user."""
    operation: Literal["get_user_favorites"] = Field(
        "get_user_favorites",
        json_schema_extra={"const": "get_user_favorites", "ui:hidden": True,
                           "x-category": _FAV_CAT, "x-is-trigger": False,
                           "x-display-name": "Get Favorites for User"},
        title="Get Favorites for User",
    )
    user_id: str = Field(..., title="User LUID", description="LUID of the user whose favorites to get")
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _get_user_favorites(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/favorites/{c.user_id}",
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="get_user_favorites")


class TableauDeleteWorkbookFavoriteConfig(BaseModel):
    """Delete a workbook from a user's favorites."""
    operation: Literal["delete_workbook_favorite"] = Field(
        "delete_workbook_favorite",
        json_schema_extra={"const": "delete_workbook_favorite", "ui:hidden": True,
                           "x-category": _FAV_CAT, "x-is-trigger": False,
                           "x-display-name": "Delete Workbook from Favorites"},
        title="Delete Workbook from Favorites",
    )
    user_id: str = Field(..., title="User LUID", description="LUID of the user whose favorites to remove from")
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))


async def _delete_workbook_favorite(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/favorites/{c.user_id}/workbooks/{c.workbook_id}",
        action_name="delete_workbook_favorite")


class TableauDeleteDatasourceFavoriteConfig(BaseModel):
    """Delete a data source from a user's favorites."""
    operation: Literal["delete_datasource_favorite"] = Field(
        "delete_datasource_favorite",
        json_schema_extra={"const": "delete_datasource_favorite", "ui:hidden": True,
                           "x-category": _FAV_CAT, "x-is-trigger": False,
                           "x-display-name": "Delete Data Source from Favorites"},
        title="Delete Data Source from Favorites",
    )
    user_id: str = Field(..., title="User LUID", description="LUID of the user whose favorites to remove from")
    datasource_id: str = Field(..., title="Data Source", json_schema_extra=_dyn("datasource_id", "a data source"))


async def _delete_datasource_favorite(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/favorites/{c.user_id}/datasources/{c.datasource_id}",
        action_name="delete_datasource_favorite")


class TableauDeleteViewFavoriteConfig(BaseModel):
    """Delete a view from a user's favorites."""
    operation: Literal["delete_view_favorite"] = Field(
        "delete_view_favorite",
        json_schema_extra={"const": "delete_view_favorite", "ui:hidden": True,
                           "x-category": _FAV_CAT, "x-is-trigger": False,
                           "x-display-name": "Delete View from Favorites"},
        title="Delete View from Favorites",
    )
    user_id: str = Field(..., title="User LUID", description="LUID of the user whose favorites to remove from")
    view_id: str = Field(..., title="View", json_schema_extra=_dyn("view_id", "a view"))


async def _delete_view_favorite(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/favorites/{c.user_id}/views/{c.view_id}",
        action_name="delete_view_favorite")


class TableauDeleteProjectFavoriteConfig(BaseModel):
    """Delete a project from a user's favorites."""
    operation: Literal["delete_project_favorite"] = Field(
        "delete_project_favorite",
        json_schema_extra={"const": "delete_project_favorite", "ui:hidden": True,
                           "x-category": _FAV_CAT, "x-is-trigger": False,
                           "x-display-name": "Delete Project from Favorites"},
        title="Delete Project from Favorites",
    )
    user_id: str = Field(..., title="User LUID", description="LUID of the user whose favorites to remove from")
    project_id: str = Field(..., title="Project", description="LUID of the project",
        json_schema_extra=_dyn("project_id", "a project"))


async def _delete_project_favorite(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/favorites/{c.user_id}/projects/{c.project_id}",
        action_name="delete_project_favorite")


class TableauDeleteFlowFavoriteConfig(BaseModel):
    """Delete a flow from a user's favorites."""
    operation: Literal["delete_flow_favorite"] = Field(
        "delete_flow_favorite",
        json_schema_extra={"const": "delete_flow_favorite", "ui:hidden": True,
                           "x-category": _FAV_CAT, "x-is-trigger": False,
                           "x-display-name": "Delete Flow from Favorites"},
        title="Delete Flow from Favorites",
    )
    user_id: str = Field(..., title="User LUID", description="LUID of the user whose favorites to remove from")
    flow_id: str = Field(..., title="Flow", json_schema_extra=_dyn("flow_id", "a flow"))


async def _delete_flow_favorite(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/favorites/{c.user_id}/flows/{c.flow_id}",
        action_name="delete_flow_favorite")


class TableauOrganizeFavoritesConfig(BaseModel):
    """Organize/reorder a user's favorites by moving a favorite after another."""
    operation: Literal["organize_favorites"] = Field(
        "organize_favorites",
        json_schema_extra={"const": "organize_favorites", "ui:hidden": True,
                           "x-category": _FAV_CAT, "x-is-trigger": False,
                           "x-display-name": "Organize Favorites"},
        title="Organize Favorites",
    )
    user_id: str = Field(..., title="User LUID", description="LUID of the user whose favorites to reorder")
    favorite_id: Optional[str] = Field(None, title="Favorite ID",
        description="LUID of the favorite to move")
    favorite_type: Optional[str] = Field(None, title="Favorite Type",
        description="Content type of the favorite (e.g. workbook, datasource, view, project, flow)")
    favorite_id_move_after: Optional[str] = Field(None, title="Move After Favorite ID",
        description="LUID of the favorite to position the moved favorite after")
    favorite_type_move_after: Optional[str] = Field(None, title="Move After Favorite Type",
        description="Content type of the favorite to position after")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON for favoriteOrderings; overrides the single-ordering fields when provided")


async def _organize_favorites(c, server_url, token, site_id) -> Dict[str, Any]:
    if c.body_json:
        orderings = json.loads(c.body_json)
    else:
        orderings = {"favoriteOrdering": [{
            "favoriteId": c.favorite_id,
            "favoriteType": c.favorite_type,
            "favoriteIdMoveAfter": c.favorite_id_move_after,
            "favoriteTypeMoveAfter": c.favorite_type_move_after,
        }]}
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/orderFavorites/{c.user_id}",
        json_body={"favoriteOrderings": orderings},
        action_name="organize_favorites")


OPERATION_CONFIGS.extend([
    TableauAddWorkbookFavoriteConfig,
    TableauAddDatasourceFavoriteConfig,
    TableauAddViewFavoriteConfig,
    TableauAddProjectFavoriteConfig,
    TableauAddFlowFavoriteConfig,
    TableauAddMetricFavoriteConfig,
    TableauGetUserFavoritesConfig,
    TableauDeleteWorkbookFavoriteConfig,
    TableauDeleteDatasourceFavoriteConfig,
    TableauDeleteViewFavoriteConfig,
    TableauDeleteProjectFavoriteConfig,
    TableauDeleteFlowFavoriteConfig,
    TableauOrganizeFavoritesConfig,
])
OPERATION_HANDLERS.update({
    "add_workbook_favorite": _add_workbook_favorite,
    "add_datasource_favorite": _add_datasource_favorite,
    "add_view_favorite": _add_view_favorite,
    "add_project_favorite": _add_project_favorite,
    "add_flow_favorite": _add_flow_favorite,
    "add_metric_favorite": _add_metric_favorite,
    "get_user_favorites": _get_user_favorites,
    "delete_workbook_favorite": _delete_workbook_favorite,
    "delete_datasource_favorite": _delete_datasource_favorite,
    "delete_view_favorite": _delete_view_favorite,
    "delete_project_favorite": _delete_project_favorite,
    "delete_flow_favorite": _delete_flow_favorite,
    "organize_favorites": _organize_favorites,
})

# ============================================================================
# Jobs, Tasks, and Schedules
# ============================================================================


class TableauQueryJobsConfig(BaseModel):
    """List background jobs (extract refreshes, subscriptions, flows, etc.)."""
    operation: Literal["query_jobs"] = Field(
        "query_jobs",
        json_schema_extra={"const": "query_jobs", "ui:hidden": True,
                           "x-category": "Jobs Tasks Schedules", "x-is-trigger": False,
                           "x-display-name": "Query Jobs"},
        title="Query Jobs",
    )
    filter: Optional[str] = Field(None, title="Filter",
        description="Filter expression, e.g. jobType:eq:refresh_extracts")
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _query_jobs(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/jobs",
        params={"filter": c.filter, "pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="query_jobs")


class TableauGetJobConfig(BaseModel):
    """Get the status of a background job."""
    operation: Literal["get_job"] = Field(
        "get_job",
        json_schema_extra={"const": "get_job", "ui:hidden": True,
                           "x-category": "Jobs Tasks Schedules", "x-is-trigger": False,
                           "x-display-name": "Get Job"},
        title="Get Job",
    )
    job_id: str = Field(..., title="Job LUID")


async def _get_job(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/jobs/{c.job_id}", action_name="get_job")


class TableauCancelJobConfig(BaseModel):
    """Cancel a running or pending background job."""
    operation: Literal["cancel_job"] = Field(
        "cancel_job",
        json_schema_extra={"const": "cancel_job", "ui:hidden": True,
                           "x-category": "Jobs Tasks Schedules", "x-is-trigger": False,
                           "x-display-name": "Cancel Job"},
        title="Cancel Job",
    )
    job_id: str = Field(..., title="Job LUID")


async def _cancel_job(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/jobs/{c.job_id}", action_name="cancel_job")


class TableauListExtractRefreshTasksConfig(BaseModel):
    """List extract refresh tasks on the site."""
    operation: Literal["list_extract_refresh_tasks"] = Field(
        "list_extract_refresh_tasks",
        json_schema_extra={"const": "list_extract_refresh_tasks", "ui:hidden": True,
                           "x-category": "Jobs Tasks Schedules", "x-is-trigger": False,
                           "x-display-name": "List Extract Refresh Tasks"},
        title="List Extract Refresh Tasks",
    )
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _list_extract_refresh_tasks(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/tasks/extractRefreshes",
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="list_extract_refresh_tasks")


class TableauGetExtractRefreshTaskConfig(BaseModel):
    """Get information about a single extract refresh task."""
    operation: Literal["get_extract_refresh_task"] = Field(
        "get_extract_refresh_task",
        json_schema_extra={"const": "get_extract_refresh_task", "ui:hidden": True,
                           "x-category": "Jobs Tasks Schedules", "x-is-trigger": False,
                           "x-display-name": "Get Extract Refresh Task"},
        title="Get Extract Refresh Task",
    )
    task_id: str = Field(..., title="Task LUID")


async def _get_extract_refresh_task(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/tasks/extractRefreshes/{c.task_id}",
        action_name="get_extract_refresh_task")


class TableauRunExtractRefreshTaskConfig(BaseModel):
    """Run an extract refresh task immediately (run now)."""
    operation: Literal["run_extract_refresh_task"] = Field(
        "run_extract_refresh_task",
        json_schema_extra={"const": "run_extract_refresh_task", "ui:hidden": True,
                           "x-category": "Jobs Tasks Schedules", "x-is-trigger": False,
                           "x-display-name": "Run Extract Refresh Task Now"},
        title="Run Extract Refresh Task Now",
    )
    task_id: str = Field(..., title="Task LUID")


async def _run_extract_refresh_task(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/tasks/extractRefreshes/{c.task_id}/runNow",
        json_body={"tsRequest": {}}, action_name="run_extract_refresh_task")


class TableauListDataAccelerationTasksConfig(BaseModel):
    """List data acceleration tasks on the site."""
    operation: Literal["list_data_acceleration_tasks"] = Field(
        "list_data_acceleration_tasks",
        json_schema_extra={"const": "list_data_acceleration_tasks", "ui:hidden": True,
                           "x-category": "Jobs Tasks Schedules", "x-is-trigger": False,
                           "x-display-name": "List Data Acceleration Tasks"},
        title="List Data Acceleration Tasks",
    )
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _list_data_acceleration_tasks(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/tasks/dataAcceleration",
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="list_data_acceleration_tasks")


class TableauDeleteDataAccelerationTaskConfig(BaseModel):
    """Delete a data acceleration task."""
    operation: Literal["delete_data_acceleration_task"] = Field(
        "delete_data_acceleration_task",
        json_schema_extra={"const": "delete_data_acceleration_task", "ui:hidden": True,
                           "x-category": "Jobs Tasks Schedules", "x-is-trigger": False,
                           "x-display-name": "Delete Data Acceleration Task"},
        title="Delete Data Acceleration Task",
    )
    data_acceleration_id: str = Field(..., title="Data Acceleration Task LUID")


async def _delete_data_acceleration_task(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/tasks/dataAcceleration/{c.data_acceleration_id}",
        action_name="delete_data_acceleration_task")


class TableauQuerySchedulesConfig(BaseModel):
    """List server-level schedules."""
    operation: Literal["query_schedules"] = Field(
        "query_schedules",
        json_schema_extra={"const": "query_schedules", "ui:hidden": True,
                           "x-category": "Jobs Tasks Schedules", "x-is-trigger": False,
                           "x-display-name": "Query Schedules"},
        title="Query Schedules",
    )
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _query_schedules(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "/schedules",
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="query_schedules")


class TableauGetScheduleConfig(BaseModel):
    """Get details of a server-level schedule."""
    operation: Literal["get_schedule"] = Field(
        "get_schedule",
        json_schema_extra={"const": "get_schedule", "ui:hidden": True,
                           "x-category": "Jobs Tasks Schedules", "x-is-trigger": False,
                           "x-display-name": "Get Schedule"},
        title="Get Schedule",
    )
    schedule_id: str = Field(..., title="Schedule LUID")


async def _get_schedule(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/schedules/{c.schedule_id}", action_name="get_schedule")


class TableauCreateScheduleConfig(BaseModel):
    """Create a server-level schedule."""
    operation: Literal["create_schedule"] = Field(
        "create_schedule",
        json_schema_extra={"const": "create_schedule", "ui:hidden": True,
                           "x-category": "Jobs Tasks Schedules", "x-is-trigger": False,
                           "x-display-name": "Create Schedule"},
        title="Create Schedule",
    )
    name: str = Field(..., title="Name")
    schedule_type: Optional[str] = Field(None, title="Type",
        description="Extract, Subscription, or Flow",
        json_schema_extra={"enum": ["Extract", "Subscription", "Flow"], "x-enum-searchable": True})
    priority: Optional[str] = Field(None, title="Priority", description="1-100")
    execution_order: Optional[str] = Field(None, title="Execution Order",
        json_schema_extra={"enum": ["Parallel", "Serial"], "x-enum-searchable": True})
    frequency: Optional[str] = Field(None, title="Frequency",
        json_schema_extra={"enum": ["Hourly", "Daily", "Weekly", "Monthly"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the schedule body (e.g. frequencyDetails)")


async def _create_schedule(c, server_url, token, site_id) -> Dict[str, Any]:
    schedule: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    schedule["name"] = c.name
    if c.schedule_type is not None: schedule["type"] = c.schedule_type
    if c.priority is not None: schedule["priority"] = c.priority
    if c.execution_order is not None: schedule["executionOrder"] = c.execution_order
    if c.frequency is not None: schedule["frequency"] = c.frequency
    return await _tableau_request(server_url, token, "POST", "/schedules",
        json_body={"schedule": schedule}, action_name="create_schedule")


class TableauUpdateScheduleConfig(BaseModel):
    """Update a server-level schedule."""
    operation: Literal["update_schedule"] = Field(
        "update_schedule",
        json_schema_extra={"const": "update_schedule", "ui:hidden": True,
                           "x-category": "Jobs Tasks Schedules", "x-is-trigger": False,
                           "x-display-name": "Update Schedule"},
        title="Update Schedule",
    )
    schedule_id: str = Field(..., title="Schedule LUID")
    name: Optional[str] = Field(None, title="Name")
    priority: Optional[str] = Field(None, title="Priority", description="1-100")
    execution_order: Optional[str] = Field(None, title="Execution Order",
        json_schema_extra={"enum": ["Parallel", "Serial"], "x-enum-searchable": True})
    frequency: Optional[str] = Field(None, title="Frequency",
        json_schema_extra={"enum": ["Hourly", "Daily", "Weekly", "Monthly"], "x-enum-searchable": True})
    state: Optional[str] = Field(None, title="State",
        json_schema_extra={"enum": ["Active", "Suspended"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the schedule body (e.g. frequencyDetails)")


async def _update_schedule(c, server_url, token, site_id) -> Dict[str, Any]:
    schedule: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: schedule["name"] = c.name
    if c.priority is not None: schedule["priority"] = c.priority
    if c.execution_order is not None: schedule["executionOrder"] = c.execution_order
    if c.frequency is not None: schedule["frequency"] = c.frequency
    if c.state is not None: schedule["state"] = c.state
    return await _tableau_request(server_url, token, "PUT",
        f"/schedules/{c.schedule_id}",
        json_body={"schedule": schedule}, action_name="update_schedule")


class TableauDeleteScheduleConfig(BaseModel):
    """Delete a server-level schedule."""
    operation: Literal["delete_schedule"] = Field(
        "delete_schedule",
        json_schema_extra={"const": "delete_schedule", "ui:hidden": True,
                           "x-category": "Jobs Tasks Schedules", "x-is-trigger": False,
                           "x-display-name": "Delete Schedule"},
        title="Delete Schedule",
    )
    schedule_id: str = Field(..., title="Schedule LUID")


async def _delete_schedule(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/schedules/{c.schedule_id}", action_name="delete_schedule")


class TableauGetScheduleExtractRefreshTasksConfig(BaseModel):
    """List the extract refresh tasks associated with a schedule."""
    operation: Literal["get_schedule_extract_refresh_tasks"] = Field(
        "get_schedule_extract_refresh_tasks",
        json_schema_extra={"const": "get_schedule_extract_refresh_tasks", "ui:hidden": True,
                           "x-category": "Jobs Tasks Schedules", "x-is-trigger": False,
                           "x-display-name": "Get Schedule Extract Refresh Tasks"},
        title="Get Schedule Extract Refresh Tasks",
    )
    schedule_id: str = Field(..., title="Schedule LUID")
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _get_schedule_extract_refresh_tasks(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/schedules/{c.schedule_id}/extracts",
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="get_schedule_extract_refresh_tasks")


class TableauAddWorkbookToScheduleConfig(BaseModel):
    """Add a workbook to a server extract refresh schedule."""
    operation: Literal["add_workbook_to_schedule"] = Field(
        "add_workbook_to_schedule",
        json_schema_extra={"const": "add_workbook_to_schedule", "ui:hidden": True,
                           "x-category": "Jobs Tasks Schedules", "x-is-trigger": False,
                           "x-display-name": "Add Workbook to Schedule"},
        title="Add Workbook to Schedule",
    )
    schedule_id: str = Field(..., title="Schedule LUID")
    workbook_id: str = Field(..., title="Workbook", json_schema_extra=_dyn("workbook_id", "a workbook"))


async def _add_workbook_to_schedule(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/schedules/{c.schedule_id}/workbooks",
        json_body={"task": {"extractRefresh": {"workbook": {"id": c.workbook_id}}}},
        action_name="add_workbook_to_schedule")


class TableauAddDatasourceToScheduleConfig(BaseModel):
    """Add a data source to a server extract refresh schedule."""
    operation: Literal["add_datasource_to_schedule"] = Field(
        "add_datasource_to_schedule",
        json_schema_extra={"const": "add_datasource_to_schedule", "ui:hidden": True,
                           "x-category": "Jobs Tasks Schedules", "x-is-trigger": False,
                           "x-display-name": "Add Data Source to Schedule"},
        title="Add Data Source to Schedule",
    )
    schedule_id: str = Field(..., title="Schedule LUID")
    datasource_id: str = Field(..., title="Data Source", json_schema_extra=_dyn("datasource_id", "a data source"))


async def _add_datasource_to_schedule(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/schedules/{c.schedule_id}/datasources",
        json_body={"task": {"extractRefresh": {"datasource": {"id": c.datasource_id}}}},
        action_name="add_datasource_to_schedule")


OPERATION_CONFIGS.extend([
    TableauQueryJobsConfig,
    TableauGetJobConfig,
    TableauCancelJobConfig,
    TableauListExtractRefreshTasksConfig,
    TableauGetExtractRefreshTaskConfig,
    TableauRunExtractRefreshTaskConfig,
    TableauListDataAccelerationTasksConfig,
    TableauDeleteDataAccelerationTaskConfig,
    TableauQuerySchedulesConfig,
    TableauGetScheduleConfig,
    TableauCreateScheduleConfig,
    TableauUpdateScheduleConfig,
    TableauDeleteScheduleConfig,
    TableauGetScheduleExtractRefreshTasksConfig,
    TableauAddWorkbookToScheduleConfig,
    TableauAddDatasourceToScheduleConfig,
])
OPERATION_HANDLERS.update({
    "query_jobs": _query_jobs,
    "get_job": _get_job,
    "cancel_job": _cancel_job,
    "list_extract_refresh_tasks": _list_extract_refresh_tasks,
    "get_extract_refresh_task": _get_extract_refresh_task,
    "run_extract_refresh_task": _run_extract_refresh_task,
    "list_data_acceleration_tasks": _list_data_acceleration_tasks,
    "delete_data_acceleration_task": _delete_data_acceleration_task,
    "query_schedules": _query_schedules,
    "get_schedule": _get_schedule,
    "create_schedule": _create_schedule,
    "update_schedule": _update_schedule,
    "delete_schedule": _delete_schedule,
    "get_schedule_extract_refresh_tasks": _get_schedule_extract_refresh_tasks,
    "add_workbook_to_schedule": _add_workbook_to_schedule,
    "add_datasource_to_schedule": _add_datasource_to_schedule,
})

# ============================================================================
# CATEGORY: Subscriptions
# ============================================================================


class TableauCreateSubscriptionConfig(BaseModel):
    """Create a subscription to a view or workbook for a user on a schedule."""
    operation: Literal["create_subscription"] = Field(
        "create_subscription",
        json_schema_extra={"const": "create_subscription", "ui:hidden": True,
                           "x-category": "Subscriptions", "x-is-trigger": False,
                           "x-display-name": "Create Subscription"},
        title="Create Subscription",
    )
    subject: str = Field(..., title="Subject")
    content_id: str = Field(..., title="Content LUID",
        description="LUID of the view or workbook to subscribe to")
    content_type: str = Field("View", title="Content Type",
        json_schema_extra={"enum": ["View", "Workbook"], "x-enum-searchable": True})
    schedule_id: Optional[str] = Field(None, title="Schedule LUID",
        description="LUID of the schedule (Tableau Server only)")
    user_id: str = Field(..., title="User", description="LUID of the user to create the subscription for", json_schema_extra=_dyn("user_id", "a user"))
    attach_image: Optional[str] = Field("true", title="Attach Image",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    attach_pdf: Optional[str] = Field("false", title="Attach PDF",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    page_orientation: Optional[str] = Field(None, title="Page Orientation",
        json_schema_extra={"enum": ["Portrait", "Landscape"], "x-enum-searchable": True})
    page_size_option: Optional[str] = Field(None, title="Page Size Option")
    message: Optional[str] = Field(None, title="Message")
    suspended: Optional[str] = Field(None, title="Suspended",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    send_if_view_empty: Optional[str] = Field(None, title="Send If View Empty",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    custom_view_id: Optional[str] = Field(None, title="Custom View LUID")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the subscription body for advanced fields")


async def _create_subscription(c, server_url, token, site_id) -> Dict[str, Any]:
    subscription: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    subscription["subject"] = c.subject
    if c.attach_image is not None: subscription["attachImage"] = c.attach_image
    if c.attach_pdf is not None: subscription["attachPdf"] = c.attach_pdf
    if c.page_orientation is not None: subscription["pageOrientation"] = c.page_orientation
    if c.page_size_option is not None: subscription["pageSizeOption"] = c.page_size_option
    if c.message is not None: subscription["message"] = c.message
    if c.suspended is not None: subscription["suspended"] = c.suspended
    content: Dict[str, Any] = {"id": c.content_id, "type": c.content_type}
    if c.send_if_view_empty is not None: content["sendIfViewEmpty"] = c.send_if_view_empty
    if c.custom_view_id is not None: content["customViewId"] = c.custom_view_id
    subscription["content"] = content
    if c.schedule_id is not None: subscription["schedule"] = {"id": c.schedule_id}
    subscription["user"] = {"id": c.user_id}
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/subscriptions",
        json_body={"subscription": subscription}, action_name="create_subscription")


class TableauQuerySubscriptionsConfig(BaseModel):
    """List the subscriptions on the site."""
    operation: Literal["query_subscriptions"] = Field(
        "query_subscriptions",
        json_schema_extra={"const": "query_subscriptions", "ui:hidden": True,
                           "x-category": "Subscriptions", "x-is-trigger": False,
                           "x-display-name": "Query Subscriptions"},
        title="Query Subscriptions",
    )
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _query_subscriptions(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/subscriptions",
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="query_subscriptions")


class TableauGetSubscriptionConfig(BaseModel):
    """Get details of a single subscription."""
    operation: Literal["get_subscription"] = Field(
        "get_subscription",
        json_schema_extra={"const": "get_subscription", "ui:hidden": True,
                           "x-category": "Subscriptions", "x-is-trigger": False,
                           "x-display-name": "Get Subscription"},
        title="Get Subscription",
    )
    subscription_id: str = Field(..., title="Subscription LUID")


async def _get_subscription(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/subscriptions/{c.subscription_id}",
        action_name="get_subscription")


class TableauUpdateSubscriptionConfig(BaseModel):
    """Update a subscription's subject, schedule, or delivery options."""
    operation: Literal["update_subscription"] = Field(
        "update_subscription",
        json_schema_extra={"const": "update_subscription", "ui:hidden": True,
                           "x-category": "Subscriptions", "x-is-trigger": False,
                           "x-display-name": "Update Subscription"},
        title="Update Subscription",
    )
    subscription_id: str = Field(..., title="Subscription LUID")
    subject: Optional[str] = Field(None, title="Subject")
    attach_image: Optional[str] = Field(None, title="Attach Image",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    attach_pdf: Optional[str] = Field(None, title="Attach PDF",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    page_orientation: Optional[str] = Field(None, title="Page Orientation",
        json_schema_extra={"enum": ["Portrait", "Landscape"], "x-enum-searchable": True})
    page_size_option: Optional[str] = Field(None, title="Page Size Option")
    suspended: Optional[str] = Field(None, title="Suspended",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    schedule_id: Optional[str] = Field(None, title="New Schedule LUID")
    send_if_view_empty: Optional[str] = Field(None, title="Send If View Empty",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the subscription body for advanced fields")


async def _update_subscription(c, server_url, token, site_id) -> Dict[str, Any]:
    subscription: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.subject is not None: subscription["subject"] = c.subject
    if c.attach_image is not None: subscription["attachImage"] = c.attach_image
    if c.attach_pdf is not None: subscription["attachPdf"] = c.attach_pdf
    if c.page_orientation is not None: subscription["pageOrientation"] = c.page_orientation
    if c.page_size_option is not None: subscription["pageSizeOption"] = c.page_size_option
    if c.suspended is not None: subscription["suspended"] = c.suspended
    if c.schedule_id is not None: subscription["schedule"] = {"id": c.schedule_id}
    if c.send_if_view_empty is not None:
        subscription["content"] = {"sendIfViewEmpty": c.send_if_view_empty}
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/subscriptions/{c.subscription_id}",
        json_body={"subscription": subscription}, action_name="update_subscription")


class TableauDeleteSubscriptionConfig(BaseModel):
    """Delete a subscription."""
    operation: Literal["delete_subscription"] = Field(
        "delete_subscription",
        json_schema_extra={"const": "delete_subscription", "ui:hidden": True,
                           "x-category": "Subscriptions", "x-is-trigger": False,
                           "x-display-name": "Delete Subscription"},
        title="Delete Subscription",
    )
    subscription_id: str = Field(..., title="Subscription LUID")


async def _delete_subscription(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/subscriptions/{c.subscription_id}",
        action_name="delete_subscription")


OPERATION_CONFIGS.extend([
    TableauCreateSubscriptionConfig,
    TableauQuerySubscriptionsConfig,
    TableauGetSubscriptionConfig,
    TableauUpdateSubscriptionConfig,
    TableauDeleteSubscriptionConfig,
])
OPERATION_HANDLERS.update({
    "create_subscription": _create_subscription,
    "query_subscriptions": _query_subscriptions,
    "get_subscription": _get_subscription,
    "update_subscription": _update_subscription,
    "delete_subscription": _delete_subscription,
})

# ============================ Notifications ============================

# ---- Webhooks: Get ----
class TableauGetWebhookConfig(BaseModel):
    """Get information about a webhook."""
    operation: Literal["get_webhook"] = Field(
        "get_webhook",
        json_schema_extra={"const": "get_webhook", "ui:hidden": True,
                           "x-category": "Notifications", "x-is-trigger": False,
                           "x-display-name": "Get Webhook"},
        title="Get Webhook",
    )
    webhook_id: str = Field(..., title="Webhook LUID", description="LUID of the webhook to get")


async def _get_webhook(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/webhooks/{c.webhook_id}",
        action_name="get_webhook")


# ---- Webhooks: Update ----
class TableauUpdateWebhookConfig(BaseModel):
    """Update an existing webhook."""
    operation: Literal["update_webhook"] = Field(
        "update_webhook",
        json_schema_extra={"const": "update_webhook", "ui:hidden": True,
                           "x-category": "Notifications", "x-is-trigger": False,
                           "x-display-name": "Update Webhook"},
        title="Update Webhook",
    )
    webhook_id: str = Field(..., title="Webhook LUID", description="LUID of the webhook to update")
    name: Optional[str] = Field(None, title="Name")
    is_enabled: Optional[str] = Field(None, title="Is Enabled",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    status_change_reason: Optional[str] = Field(None, title="Status Change Reason")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the webhook body (e.g. event, webhook-source, webhook-destination)")


async def _update_webhook(c, server_url, token, site_id) -> Dict[str, Any]:
    webhook: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: webhook["name"] = c.name
    if c.is_enabled is not None: webhook["isEnabled"] = c.is_enabled == "true"
    if c.status_change_reason is not None: webhook["statusChangeReason"] = c.status_change_reason
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/webhooks/{c.webhook_id}",
        json_body={"webhook": webhook}, action_name="update_webhook")


# ---- Data-Driven Alerts: Create ----
class TableauCreateDataAlertConfig(BaseModel):
    """Create a data-driven alert on a view/worksheet."""
    operation: Literal["create_data_alert"] = Field(
        "create_data_alert",
        json_schema_extra={"const": "create_data_alert", "ui:hidden": True,
                           "x-category": "Notifications", "x-is-trigger": False,
                           "x-display-name": "Create Data-Driven Alert"},
        title="Create Data-Driven Alert",
    )
    subject: Optional[str] = Field(None, title="Subject")
    condition: Optional[str] = Field(None, title="Alert Condition",
        description="e.g. above, below, equal")
    threshold: Optional[str] = Field(None, title="Alert Threshold")
    frequency: Optional[str] = Field(None, title="Frequency",
        description="e.g. Once, Hourly, Daily, Weekly")
    visibility: Optional[str] = Field(None, title="Visibility",
        json_schema_extra={"enum": ["private", "public"], "x-enum-searchable": True})
    worksheet_name: Optional[str] = Field(None, title="Worksheet Name")
    view_id: Optional[str] = Field(None, title="View LUID")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the dataAlert body for advanced fields")


async def _create_data_alert(c, server_url, token, site_id) -> Dict[str, Any]:
    alert: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.subject is not None: alert["subject"] = c.subject
    if c.condition is not None: alert["alertCondition"] = c.condition
    if c.threshold is not None: alert["alertThreshold"] = c.threshold
    if c.frequency is not None: alert["frequency"] = c.frequency
    if c.visibility is not None: alert["visibility"] = c.visibility
    if c.worksheet_name is not None: alert["worksheetName"] = c.worksheet_name
    if c.view_id is not None: alert["view"] = {"id": c.view_id}
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/dataAlerts",
        json_body={"dataAlert": alert}, action_name="create_data_alert")


# ---- Data-Driven Alerts: List ----
class TableauQueryDataAlertsConfig(BaseModel):
    """List data-driven alerts on the site."""
    operation: Literal["query_data_alerts"] = Field(
        "query_data_alerts",
        json_schema_extra={"const": "query_data_alerts", "ui:hidden": True,
                           "x-category": "Notifications", "x-is-trigger": False,
                           "x-display-name": "Query Data-Driven Alerts"},
        title="Query Data-Driven Alerts",
    )
    filter: Optional[str] = Field(None, title="Filter",
        description="e.g. viewId:eq:view-luid")
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _query_data_alerts(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/dataAlerts",
        params={"filter": c.filter, "pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="query_data_alerts")


# ---- Data-Driven Alerts: Get ----
class TableauGetDataAlertConfig(BaseModel):
    """Get a single data-driven alert."""
    operation: Literal["get_data_alert"] = Field(
        "get_data_alert",
        json_schema_extra={"const": "get_data_alert", "ui:hidden": True,
                           "x-category": "Notifications", "x-is-trigger": False,
                           "x-display-name": "Get Data-Driven Alert"},
        title="Get Data-Driven Alert",
    )
    data_alert_id: str = Field(..., title="Data Alert LUID")


async def _get_data_alert(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/dataAlerts/{c.data_alert_id}",
        action_name="get_data_alert")


# ---- Data-Driven Alerts: Update ----
class TableauUpdateDataAlertConfig(BaseModel):
    """Update a data-driven alert."""
    operation: Literal["update_data_alert"] = Field(
        "update_data_alert",
        json_schema_extra={"const": "update_data_alert", "ui:hidden": True,
                           "x-category": "Notifications", "x-is-trigger": False,
                           "x-display-name": "Update Data-Driven Alert"},
        title="Update Data-Driven Alert",
    )
    data_alert_id: str = Field(..., title="Data Alert LUID")
    subject: Optional[str] = Field(None, title="Subject")
    frequency: Optional[str] = Field(None, title="Frequency")
    public: Optional[str] = Field(None, title="Public",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    owner_id: Optional[str] = Field(None, title="Owner LUID")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the dataAlert body for advanced fields")


async def _update_data_alert(c, server_url, token, site_id) -> Dict[str, Any]:
    alert: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.subject is not None: alert["subject"] = c.subject
    if c.frequency is not None: alert["frequency"] = c.frequency
    if c.public is not None: alert["public"] = c.public == "true"
    if c.owner_id is not None: alert["owner"] = {"id": c.owner_id}
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/dataAlerts/{c.data_alert_id}",
        json_body={"dataAlert": alert}, action_name="update_data_alert")


# ---- Data-Driven Alerts: Delete ----
class TableauDeleteDataAlertConfig(BaseModel):
    """Delete a data-driven alert."""
    operation: Literal["delete_data_alert"] = Field(
        "delete_data_alert",
        json_schema_extra={"const": "delete_data_alert", "ui:hidden": True,
                           "x-category": "Notifications", "x-is-trigger": False,
                           "x-display-name": "Delete Data-Driven Alert"},
        title="Delete Data-Driven Alert",
    )
    data_alert_id: str = Field(..., title="Data Alert LUID")


async def _delete_data_alert(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/dataAlerts/{c.data_alert_id}",
        action_name="delete_data_alert")


# ---- Data-Driven Alerts: Add User ----
class TableauAddDataAlertUserConfig(BaseModel):
    """Add a user as a recipient of a data-driven alert."""
    operation: Literal["add_data_alert_user"] = Field(
        "add_data_alert_user",
        json_schema_extra={"const": "add_data_alert_user", "ui:hidden": True,
                           "x-category": "Notifications", "x-is-trigger": False,
                           "x-display-name": "Add User to Data-Driven Alert"},
        title="Add User to Data-Driven Alert",
    )
    data_alert_id: str = Field(..., title="Data Alert LUID")
    user_id: str = Field(..., title="User", json_schema_extra=_dyn("user_id", "a user"))


async def _add_data_alert_user(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/dataAlerts/{c.data_alert_id}/users",
        json_body={"user": {"id": c.user_id}}, action_name="add_data_alert_user")


# ---- Data-Driven Alerts: Delete User ----
class TableauDeleteDataAlertUserConfig(BaseModel):
    """Remove a user as a recipient of a data-driven alert."""
    operation: Literal["delete_data_alert_user"] = Field(
        "delete_data_alert_user",
        json_schema_extra={"const": "delete_data_alert_user", "ui:hidden": True,
                           "x-category": "Notifications", "x-is-trigger": False,
                           "x-display-name": "Delete User from Data-Driven Alert"},
        title="Delete User from Data-Driven Alert",
    )
    data_alert_id: str = Field(..., title="Data Alert LUID")
    user_id: str = Field(..., title="User", json_schema_extra=_dyn("user_id", "a user"))


async def _delete_data_alert_user(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/dataAlerts/{c.data_alert_id}/users/{c.user_id}",
        action_name="delete_data_alert_user")


# ---- User Notification Preferences: Get ----
class TableauGetNotificationPreferencesConfig(BaseModel):
    """Get user notification preferences for the site."""
    operation: Literal["get_notification_preferences"] = Field(
        "get_notification_preferences",
        json_schema_extra={"const": "get_notification_preferences", "ui:hidden": True,
                           "x-category": "Notifications", "x-is-trigger": False,
                           "x-display-name": "Get Notification Preferences"},
        title="Get Notification Preferences",
    )
    filter: Optional[str] = Field(None, title="Filter",
        description="Optional filter by channel and notificationType")


async def _get_notification_preferences(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/settings/notifications",
        params={"filter": c.filter}, action_name="get_notification_preferences")


# ---- User Notification Preferences: Update ----
class TableauUpdateNotificationPreferencesConfig(BaseModel):
    """Update user notification preferences for the site."""
    operation: Literal["update_notification_preferences"] = Field(
        "update_notification_preferences",
        json_schema_extra={"const": "update_notification_preferences", "ui:hidden": True,
                           "x-category": "Notifications", "x-is-trigger": False,
                           "x-display-name": "Update Notification Preferences"},
        title="Update Notification Preferences",
    )
    enabled: Optional[str] = Field(None, title="Enabled",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    channel: Optional[str] = Field(None, title="Channel",
        description="e.g. email, in_app, slack")
    notification_type: Optional[str] = Field(None, title="Notification Type")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the notificationPreference body")


async def _update_notification_preferences(c, server_url, token, site_id) -> Dict[str, Any]:
    pref: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.enabled is not None: pref["enabled"] = c.enabled == "true"
    if c.channel is not None: pref["channel"] = c.channel
    if c.notification_type is not None: pref["notificationType"] = c.notification_type
    return await _tableau_request(server_url, token, "PATCH",
        f"/sites/{site_id}/settings/notifications",
        json_body={"notificationPreference": pref},
        action_name="update_notification_preferences")


# ---- REGISTRATION ----
OPERATION_CONFIGS.extend([
    TableauGetWebhookConfig,
    TableauUpdateWebhookConfig,
    TableauCreateDataAlertConfig,
    TableauQueryDataAlertsConfig,
    TableauGetDataAlertConfig,
    TableauUpdateDataAlertConfig,
    TableauDeleteDataAlertConfig,
    TableauAddDataAlertUserConfig,
    TableauDeleteDataAlertUserConfig,
    TableauGetNotificationPreferencesConfig,
    TableauUpdateNotificationPreferencesConfig,
])
OPERATION_HANDLERS.update({
    "get_webhook": _get_webhook,
    "update_webhook": _update_webhook,
    "create_data_alert": _create_data_alert,
    "query_data_alerts": _query_data_alerts,
    "get_data_alert": _get_data_alert,
    "update_data_alert": _update_data_alert,
    "delete_data_alert": _delete_data_alert,
    "add_data_alert_user": _add_data_alert_user,
    "delete_data_alert_user": _delete_data_alert_user,
    "get_notification_preferences": _get_notification_preferences,
    "update_notification_preferences": _update_notification_preferences,
})

# ============================================================================
# TABLEAU — Server category operations
# ============================================================================


class TableauGetServerInfoConfig(BaseModel):
    """Get server info + supported REST API version."""
    operation: Literal["get_server_info"] = Field(
        "get_server_info",
        json_schema_extra={"const": "get_server_info", "ui:hidden": True,
                           "x-category": "Server", "x-is-trigger": False,
                           "x-display-name": "Get Server Info"},
        title="Get Server Info",
    )


async def _get_server_info(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "/serverinfo",
        action_name="get_server_info")


class TableauGetCurrentSessionConfig(BaseModel):
    """Get details of the current server session (site + user)."""
    operation: Literal["get_current_session"] = Field(
        "get_current_session",
        json_schema_extra={"const": "get_current_session", "ui:hidden": True,
                           "x-category": "Server", "x-is-trigger": False,
                           "x-display-name": "Get Current Session"},
        title="Get Current Session",
    )


async def _get_current_session(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "/sessions/current",
        action_name="get_current_session")


class TableauDeleteSessionConfig(BaseModel):
    """Delete a server session by its ID."""
    operation: Literal["delete_session"] = Field(
        "delete_session",
        json_schema_extra={"const": "delete_session", "ui:hidden": True,
                           "x-category": "Server", "x-is-trigger": False,
                           "x-display-name": "Delete Session"},
        title="Delete Session",
    )
    session_id: str = Field(..., title="Session ID", description="ID of the session to delete")


async def _delete_session(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sessions/{c.session_id}", action_name="delete_session")


class TableauListAdDomainsConfig(BaseModel):
    """List the Active Directory domains in use on the server."""
    operation: Literal["list_ad_domains"] = Field(
        "list_ad_domains",
        json_schema_extra={"const": "list_ad_domains", "ui:hidden": True,
                           "x-category": "Server", "x-is-trigger": False,
                           "x-display-name": "List Active Directory Domains"},
        title="List Active Directory Domains",
    )


async def _list_ad_domains(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "/domains",
        action_name="list_ad_domains")


class TableauUpdateAdDomainConfig(BaseModel):
    """Update the nickname (short name) of an Active Directory domain."""
    operation: Literal["update_ad_domain"] = Field(
        "update_ad_domain",
        json_schema_extra={"const": "update_ad_domain", "ui:hidden": True,
                           "x-category": "Server", "x-is-trigger": False,
                           "x-display-name": "Update Active Directory Domain"},
        title="Update Active Directory Domain",
    )
    domain_id: str = Field(..., title="Domain ID", description="ID of the domain to update")
    name: Optional[str] = Field(None, title="Name", description="Full domain name")
    short_name: Optional[str] = Field(None, title="Short Name", description="Domain nickname")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the domain body for advanced fields")


async def _update_ad_domain(c, server_url, token, site_id) -> Dict[str, Any]:
    domain: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: domain["name"] = c.name
    if c.short_name is not None: domain["shortName"] = c.short_name
    return await _tableau_request(server_url, token, "PUT",
        f"/domains/{c.domain_id}",
        json_body={"domain": domain}, action_name="update_ad_domain")


OPERATION_CONFIGS.extend([
    TableauGetServerInfoConfig,
    TableauGetCurrentSessionConfig,
    TableauDeleteSessionConfig,
    TableauListAdDomainsConfig,
    TableauUpdateAdDomainConfig,
])
OPERATION_HANDLERS.update({
    "get_server_info": _get_server_info,
    "get_current_session": _get_current_session,
    "delete_session": _delete_session,
    "list_ad_domains": _list_ad_domains,
    "update_ad_domain": _update_ad_domain,
})

# ============================================================================
# Extract and Encryption operations
# ============================================================================

class TableauCreateWorkbookExtractConfig(BaseModel):
    """Create extracts for the embedded data sources in a workbook."""
    operation: Literal["create_workbook_extract"] = Field(
        "create_workbook_extract",
        json_schema_extra={"const": "create_workbook_extract", "ui:hidden": True,
                           "x-category": "Extract and Encryption", "x-is-trigger": False,
                           "x-display-name": "Create Extract for Workbook"},
        title="Create Extract for Workbook",
    )
    workbook_id: str = Field(..., title="Workbook", description="LUID of the workbook whose embedded data sources get extracts", json_schema_extra=_dyn("workbook_id", "a workbook"))
    encrypt: Optional[str] = Field("false", title="Encrypt Extract",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    include_all: Optional[str] = Field("true", title="Include All Data Sources",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    datasource_id: Optional[str] = Field(None, title="Embedded Data Source LUID",
        description="Single embedded data source LUID (used when Include All is false)")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the datasources body for advanced fields")


async def _create_workbook_extract(c, server_url, token, site_id) -> Dict[str, Any]:
    datasources: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.include_all is not None:
        datasources["includeAll"] = c.include_all
    if c.datasource_id:
        datasources["datasource"] = {"id": c.datasource_id}
    params = {"encrypt": c.encrypt} if c.encrypt is not None else None
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/workbooks/{c.workbook_id}/createExtract",
        params=params, json_body={"datasources": datasources},
        action_name="create_workbook_extract")


class TableauDeleteWorkbookExtractConfig(BaseModel):
    """Delete the extracts of the embedded data sources in a workbook."""
    operation: Literal["delete_workbook_extract"] = Field(
        "delete_workbook_extract",
        json_schema_extra={"const": "delete_workbook_extract", "ui:hidden": True,
                           "x-category": "Extract and Encryption", "x-is-trigger": False,
                           "x-display-name": "Delete Extract for Workbook"},
        title="Delete Extract for Workbook",
    )
    workbook_id: str = Field(..., title="Workbook", description="LUID of the workbook whose embedded data source extracts get deleted", json_schema_extra=_dyn("workbook_id", "a workbook"))
    include_all: Optional[str] = Field("true", title="Include All Data Sources",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the datasources body for advanced fields")


async def _delete_workbook_extract(c, server_url, token, site_id) -> Dict[str, Any]:
    datasources: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.include_all is not None:
        datasources["includeAll"] = c.include_all
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/workbooks/{c.workbook_id}/deleteExtract",
        json_body={"datasources": datasources},
        action_name="delete_workbook_extract")


class TableauCreateDatasourceExtractConfig(BaseModel):
    """Create an extract for a published data source."""
    operation: Literal["create_datasource_extract"] = Field(
        "create_datasource_extract",
        json_schema_extra={"const": "create_datasource_extract", "ui:hidden": True,
                           "x-category": "Extract and Encryption", "x-is-trigger": False,
                           "x-display-name": "Create Extract for Data Source"},
        title="Create Extract for Data Source",
    )
    datasource_id: str = Field(..., title="Data Source", description="LUID of the data source to create an extract for", json_schema_extra=_dyn("datasource_id", "a data source"))
    encrypt: Optional[str] = Field("false", title="Encrypt Extract",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


async def _create_datasource_extract(c, server_url, token, site_id) -> Dict[str, Any]:
    params = {"encrypt": c.encrypt} if c.encrypt is not None else None
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/datasources/{c.datasource_id}/createExtract",
        params=params, action_name="create_datasource_extract")


class TableauDeleteDatasourceExtractConfig(BaseModel):
    """Delete the extract from a published data source."""
    operation: Literal["delete_datasource_extract"] = Field(
        "delete_datasource_extract",
        json_schema_extra={"const": "delete_datasource_extract", "ui:hidden": True,
                           "x-category": "Extract and Encryption", "x-is-trigger": False,
                           "x-display-name": "Delete Extract for Data Source"},
        title="Delete Extract for Data Source",
    )
    datasource_id: str = Field(..., title="Data Source", description="LUID of the data source whose extract gets deleted", json_schema_extra=_dyn("datasource_id", "a data source"))


async def _delete_datasource_extract(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/datasources/{c.datasource_id}/deleteExtract",
        action_name="delete_datasource_extract")


class TableauEncryptExtractsConfig(BaseModel):
    """Encrypt all extracts on the site."""
    operation: Literal["encrypt_extracts"] = Field(
        "encrypt_extracts",
        json_schema_extra={"const": "encrypt_extracts", "ui:hidden": True,
                           "x-category": "Extract and Encryption", "x-is-trigger": False,
                           "x-display-name": "Encrypt Extracts"},
        title="Encrypt Extracts",
    )


async def _encrypt_extracts(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/encrypt-extracts",
        action_name="encrypt_extracts")


class TableauDecryptExtractsConfig(BaseModel):
    """Decrypt all extracts on the site."""
    operation: Literal["decrypt_extracts"] = Field(
        "decrypt_extracts",
        json_schema_extra={"const": "decrypt_extracts", "ui:hidden": True,
                           "x-category": "Extract and Encryption", "x-is-trigger": False,
                           "x-display-name": "Decrypt Extracts"},
        title="Decrypt Extracts",
    )


async def _decrypt_extracts(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/decrypt-extracts",
        action_name="decrypt_extracts")


class TableauReencryptExtractsConfig(BaseModel):
    """Reencrypt all extracts on the site with new encryption keys."""
    operation: Literal["reencrypt_extracts"] = Field(
        "reencrypt_extracts",
        json_schema_extra={"const": "reencrypt_extracts", "ui:hidden": True,
                           "x-category": "Extract and Encryption", "x-is-trigger": False,
                           "x-display-name": "Reencrypt Extracts"},
        title="Reencrypt Extracts",
    )


async def _reencrypt_extracts(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/reencrypt-extracts",
        action_name="reencrypt_extracts")


OPERATION_CONFIGS.extend([
    TableauCreateWorkbookExtractConfig,
    TableauDeleteWorkbookExtractConfig,
    TableauCreateDatasourceExtractConfig,
    TableauDeleteDatasourceExtractConfig,
    TableauEncryptExtractsConfig,
    TableauDecryptExtractsConfig,
    TableauReencryptExtractsConfig,
])
OPERATION_HANDLERS.update({
    "create_workbook_extract": _create_workbook_extract,
    "delete_workbook_extract": _delete_workbook_extract,
    "create_datasource_extract": _create_datasource_extract,
    "delete_datasource_extract": _delete_datasource_extract,
    "encrypt_extracts": _encrypt_extracts,
    "decrypt_extracts": _decrypt_extracts,
    "reencrypt_extracts": _reencrypt_extracts,
})

# ============================ METADATA CATEGORY ============================

# ---- Databases -----------------------------------------------------------
class TableauQueryDatabasesConfig(BaseModel):
    """Query databases known to the metadata store on the site."""
    operation: Literal["query_databases"] = Field(
        "query_databases",
        json_schema_extra={"const": "query_databases", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Query Databases"},
        title="Query Databases",
    )
    filter: Optional[str] = Field(None, title="Filter")
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _query_databases(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/databases",
        params={"filter": c.filter, "pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="query_databases")


class TableauGetDatabaseConfig(BaseModel):
    """Get information about a database asset."""
    operation: Literal["get_database"] = Field(
        "get_database",
        json_schema_extra={"const": "get_database", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Get Database"},
        title="Get Database",
    )
    database_id: str = Field(..., title="Database LUID")


async def _get_database(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/databases/{c.database_id}",
        action_name="get_database")


class TableauUpdateDatabaseConfig(BaseModel):
    """Update metadata (description, certification, contact) of a database."""
    operation: Literal["update_database"] = Field(
        "update_database",
        json_schema_extra={"const": "update_database", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Update Database"},
        title="Update Database",
    )
    database_id: str = Field(..., title="Database LUID")
    description: Optional[str] = Field(None, title="Description")
    is_certified: Optional[str] = Field(None, title="Is Certified",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    certification_note: Optional[str] = Field(None, title="Certification Note")
    contact_id: Optional[str] = Field(None, title="Contact User LUID")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the database body")


async def _update_database(c, server_url, token, site_id) -> Dict[str, Any]:
    database: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.description is not None: database["description"] = c.description
    if c.is_certified is not None: database["isCertified"] = c.is_certified == "true"
    if c.certification_note is not None: database["certificationNote"] = c.certification_note
    if c.contact_id is not None: database["contact"] = {"id": c.contact_id}
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/databases/{c.database_id}",
        json_body={"database": database}, action_name="update_database")


class TableauDeleteDatabaseConfig(BaseModel):
    """Remove a database asset from the metadata store."""
    operation: Literal["delete_database"] = Field(
        "delete_database",
        json_schema_extra={"const": "delete_database", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Delete Database"},
        title="Delete Database",
    )
    database_id: str = Field(..., title="Database LUID")


async def _delete_database(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/databases/{c.database_id}",
        action_name="delete_database")


# ---- Tables --------------------------------------------------------------
class TableauQueryTablesConfig(BaseModel):
    """Query tables known to the metadata store on the site."""
    operation: Literal["query_tables"] = Field(
        "query_tables",
        json_schema_extra={"const": "query_tables", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Query Tables"},
        title="Query Tables",
    )
    filter: Optional[str] = Field(None, title="Filter")
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _query_tables(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/tables",
        params={"filter": c.filter, "pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="query_tables")


class TableauGetTableConfig(BaseModel):
    """Get information about a table asset."""
    operation: Literal["get_table"] = Field(
        "get_table",
        json_schema_extra={"const": "get_table", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Get Table"},
        title="Get Table",
    )
    table_id: str = Field(..., title="Table LUID")


async def _get_table(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/tables/{c.table_id}",
        action_name="get_table")


class TableauUpdateTableConfig(BaseModel):
    """Update metadata (description, certification, contact) of a table."""
    operation: Literal["update_table"] = Field(
        "update_table",
        json_schema_extra={"const": "update_table", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Update Table"},
        title="Update Table",
    )
    table_id: str = Field(..., title="Table LUID")
    description: Optional[str] = Field(None, title="Description")
    is_certified: Optional[str] = Field(None, title="Is Certified",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    certification_note: Optional[str] = Field(None, title="Certification Note")
    contact_id: Optional[str] = Field(None, title="Contact User LUID")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the table body")


async def _update_table(c, server_url, token, site_id) -> Dict[str, Any]:
    table: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.description is not None: table["description"] = c.description
    if c.is_certified is not None: table["isCertified"] = c.is_certified == "true"
    if c.certification_note is not None: table["certificationNote"] = c.certification_note
    if c.contact_id is not None: table["contact"] = {"id": c.contact_id}
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/tables/{c.table_id}",
        json_body={"table": table}, action_name="update_table")


class TableauDeleteTableConfig(BaseModel):
    """Remove a table asset from the metadata store."""
    operation: Literal["delete_table"] = Field(
        "delete_table",
        json_schema_extra={"const": "delete_table", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Delete Table"},
        title="Delete Table",
    )
    table_id: str = Field(..., title="Table LUID")


async def _delete_table(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/tables/{c.table_id}",
        action_name="delete_table")


# ---- Columns -------------------------------------------------------------
class TableauQueryColumnsConfig(BaseModel):
    """Query columns in a table known to the metadata store."""
    operation: Literal["query_columns"] = Field(
        "query_columns",
        json_schema_extra={"const": "query_columns", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Query Columns"},
        title="Query Columns",
    )
    table_id: str = Field(..., title="Table LUID")
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _query_columns(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/tables/{c.table_id}/columns",
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="query_columns")


class TableauGetColumnConfig(BaseModel):
    """Get information about a column in a table."""
    operation: Literal["get_column"] = Field(
        "get_column",
        json_schema_extra={"const": "get_column", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Get Column"},
        title="Get Column",
    )
    table_id: str = Field(..., title="Table LUID")
    column_id: str = Field(..., title="Column LUID")


async def _get_column(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/tables/{c.table_id}/columns/{c.column_id}",
        action_name="get_column")


class TableauUpdateColumnConfig(BaseModel):
    """Update the description of a column in a table."""
    operation: Literal["update_column"] = Field(
        "update_column",
        json_schema_extra={"const": "update_column", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Update Column"},
        title="Update Column",
    )
    table_id: str = Field(..., title="Table LUID")
    column_id: str = Field(..., title="Column LUID")
    description: Optional[str] = Field(None, title="Description")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the column body")


async def _update_column(c, server_url, token, site_id) -> Dict[str, Any]:
    column: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.description is not None: column["description"] = c.description
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/tables/{c.table_id}/columns/{c.column_id}",
        json_body={"column": column}, action_name="update_column")


class TableauDeleteColumnConfig(BaseModel):
    """Remove a column asset from the metadata store."""
    operation: Literal["delete_column"] = Field(
        "delete_column",
        json_schema_extra={"const": "delete_column", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Delete Column"},
        title="Delete Column",
    )
    table_id: str = Field(..., title="Table LUID")
    column_id: str = Field(..., title="Column LUID")


async def _delete_column(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/tables/{c.table_id}/columns/{c.column_id}",
        action_name="delete_column")


# ---- Data Quality Warnings -----------------------------------------------
class TableauAddDataQualityWarningConfig(BaseModel):
    """Add a data quality warning to a content asset."""
    operation: Literal["add_data_quality_warning"] = Field(
        "add_data_quality_warning",
        json_schema_extra={"const": "add_data_quality_warning", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Add Data Quality Warning"},
        title="Add Data Quality Warning",
    )
    content_type: str = Field(..., title="Content Type",
        description="database, table, column, datasource, flow, virtualconnection, etc.")
    content_luid: str = Field(..., title="Content LUID")
    warning_type: Optional[str] = Field(None, title="Warning Type",
        description="Warning, Deprecated, Stale, Sensitive")
    message: Optional[str] = Field(None, title="Message")
    is_active: Optional[str] = Field("true", title="Is Active",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    is_severe: Optional[str] = Field("false", title="Is Severe",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the dataQualityWarning body")


async def _add_data_quality_warning(c, server_url, token, site_id) -> Dict[str, Any]:
    dqw: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.warning_type is not None: dqw["type"] = c.warning_type
    if c.message is not None: dqw["message"] = c.message
    if c.is_active is not None: dqw["isActive"] = c.is_active == "true"
    if c.is_severe is not None: dqw["isSevere"] = c.is_severe == "true"
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/dataQualityWarnings/{c.content_type}/{c.content_luid}",
        json_body={"dataQualityWarning": dqw}, action_name="add_data_quality_warning")


class TableauGetDataQualityWarningConfig(BaseModel):
    """Get a data quality warning by its LUID."""
    operation: Literal["get_data_quality_warning"] = Field(
        "get_data_quality_warning",
        json_schema_extra={"const": "get_data_quality_warning", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Get Data Quality Warning"},
        title="Get Data Quality Warning",
    )
    dqw_id: str = Field(..., title="Data Quality Warning LUID")


async def _get_data_quality_warning(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/dataQualityWarnings/{c.dqw_id}",
        action_name="get_data_quality_warning")


class TableauGetDataQualityWarningByContentConfig(BaseModel):
    """Get the data quality warning(s) on a content asset."""
    operation: Literal["get_data_quality_warning_by_content"] = Field(
        "get_data_quality_warning_by_content",
        json_schema_extra={"const": "get_data_quality_warning_by_content", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Get Data Quality Warning By Content"},
        title="Get Data Quality Warning By Content",
    )
    content_type: str = Field(..., title="Content Type",
        description="database, table, column, datasource, flow, virtualconnection, etc.")
    content_luid: str = Field(..., title="Content LUID")


async def _get_data_quality_warning_by_content(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/dataQualityWarnings/{c.content_type}/{c.content_luid}",
        action_name="get_data_quality_warning_by_content")


class TableauUpdateDataQualityWarningConfig(BaseModel):
    """Update a data quality warning by its LUID."""
    operation: Literal["update_data_quality_warning"] = Field(
        "update_data_quality_warning",
        json_schema_extra={"const": "update_data_quality_warning", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Update Data Quality Warning"},
        title="Update Data Quality Warning",
    )
    dqw_id: str = Field(..., title="Data Quality Warning LUID")
    warning_type: Optional[str] = Field(None, title="Warning Type")
    message: Optional[str] = Field(None, title="Message")
    is_active: Optional[str] = Field(None, title="Is Active",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    is_severe: Optional[str] = Field(None, title="Is Severe",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the dataQualityWarning body")


async def _update_data_quality_warning(c, server_url, token, site_id) -> Dict[str, Any]:
    dqw: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.warning_type is not None: dqw["type"] = c.warning_type
    if c.message is not None: dqw["message"] = c.message
    if c.is_active is not None: dqw["isActive"] = c.is_active == "true"
    if c.is_severe is not None: dqw["isSevere"] = c.is_severe == "true"
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/dataQualityWarnings/{c.dqw_id}",
        json_body={"dataQualityWarning": dqw}, action_name="update_data_quality_warning")


class TableauDeleteDataQualityWarningConfig(BaseModel):
    """Delete a data quality warning by its LUID."""
    operation: Literal["delete_data_quality_warning"] = Field(
        "delete_data_quality_warning",
        json_schema_extra={"const": "delete_data_quality_warning", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Delete Data Quality Warning"},
        title="Delete Data Quality Warning",
    )
    dqw_id: str = Field(..., title="Data Quality Warning LUID")


async def _delete_data_quality_warning(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/dataQualityWarnings/{c.dqw_id}",
        action_name="delete_data_quality_warning")


class TableauDeleteDataQualityWarningByContentConfig(BaseModel):
    """Delete the data quality warning(s) on a content asset."""
    operation: Literal["delete_data_quality_warning_by_content"] = Field(
        "delete_data_quality_warning_by_content",
        json_schema_extra={"const": "delete_data_quality_warning_by_content", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Delete Data Quality Warning By Content"},
        title="Delete Data Quality Warning By Content",
    )
    content_type: str = Field(..., title="Content Type",
        description="database, table, column, datasource, flow, virtualconnection, etc.")
    content_luid: str = Field(..., title="Content LUID")


async def _delete_data_quality_warning_by_content(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/dataQualityWarnings/{c.content_type}/{c.content_luid}",
        action_name="delete_data_quality_warning_by_content")


class TableauBatchUpdateDataQualityWarningConfig(BaseModel):
    """Batch add or update data quality warnings on a list of content."""
    operation: Literal["batch_update_data_quality_warning"] = Field(
        "batch_update_data_quality_warning",
        json_schema_extra={"const": "batch_update_data_quality_warning", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Batch Update Data Quality Warnings"},
        title="Batch Update Data Quality Warnings",
    )
    body_json: str = Field(..., title="Body (JSON)",
        description='e.g. {"contentList":[{"contentType":"table","id":"..."}],"dataQualityWarning":{"type":"Warning","message":"...","isActive":true,"isSevere":false}}')


async def _batch_update_data_quality_warning(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/dataQualityWarnings/createOrUpdate",
        json_body=json.loads(c.body_json), action_name="batch_update_data_quality_warning")


class TableauBatchDeleteDataQualityWarningConfig(BaseModel):
    """Batch delete data quality warnings on a list of content."""
    operation: Literal["batch_delete_data_quality_warning"] = Field(
        "batch_delete_data_quality_warning",
        json_schema_extra={"const": "batch_delete_data_quality_warning", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Batch Delete Data Quality Warnings"},
        title="Batch Delete Data Quality Warnings",
    )
    body_json: str = Field(..., title="Body (JSON)",
        description='e.g. {"contentList":[{"contentType":"table","id":"..."}]}')


async def _batch_delete_data_quality_warning(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/dataQualityWarnings/batchDelete",
        json_body=json.loads(c.body_json), action_name="batch_delete_data_quality_warning")


# ---- Labels --------------------------------------------------------------
class TableauCreateLabelCategoryConfig(BaseModel):
    """Create a label category on the site."""
    operation: Literal["create_label_category"] = Field(
        "create_label_category",
        json_schema_extra={"const": "create_label_category", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Create Label Category"},
        title="Create Label Category",
    )
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(None, title="Description")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the labelCategory body")


async def _create_label_category(c, server_url, token, site_id) -> Dict[str, Any]:
    category: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: category["name"] = c.name
    if c.description is not None: category["description"] = c.description
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/labelCategories",
        json_body={"labelCategory": category}, action_name="create_label_category")


class TableauCreateOrUpdateLabelValueConfig(BaseModel):
    """Create or update a label value on the site."""
    operation: Literal["create_or_update_label_value"] = Field(
        "create_or_update_label_value",
        json_schema_extra={"const": "create_or_update_label_value", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Create Or Update Label Value"},
        title="Create Or Update Label Value",
    )
    name: Optional[str] = Field(None, title="Name")
    category: Optional[str] = Field(None, title="Category")
    description: Optional[str] = Field(None, title="Description")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the labelValue body")


async def _create_or_update_label_value(c, server_url, token, site_id) -> Dict[str, Any]:
    label_value: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: label_value["name"] = c.name
    if c.category is not None: label_value["category"] = c.category
    if c.description is not None: label_value["description"] = c.description
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/labelValues",
        json_body={"labelValue": label_value}, action_name="create_or_update_label_value")


class TableauGetLabelConfig(BaseModel):
    """Get a label by its LUID."""
    operation: Literal["get_label"] = Field(
        "get_label",
        json_schema_extra={"const": "get_label", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Get Label"},
        title="Get Label",
    )
    label_id: str = Field(..., title="Label LUID")


async def _get_label(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/labels/{c.label_id}",
        action_name="get_label")


class TableauDeleteLabelConfig(BaseModel):
    """Delete a label by its LUID."""
    operation: Literal["delete_label"] = Field(
        "delete_label",
        json_schema_extra={"const": "delete_label", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Delete Label"},
        title="Delete Label",
    )
    label_id: str = Field(..., title="Label LUID")


async def _delete_label(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/labels/{c.label_id}",
        action_name="delete_label")


class TableauDeleteLabelsConfig(BaseModel):
    """Delete labels on a list of content."""
    operation: Literal["delete_labels"] = Field(
        "delete_labels",
        json_schema_extra={"const": "delete_labels", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Delete Labels"},
        title="Delete Labels",
    )
    body_json: str = Field(..., title="Body (JSON)",
        description='e.g. {"contentList":[{"contentType":"table","id":"..."}]}')


async def _delete_labels(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/labels",
        json_body=json.loads(c.body_json), action_name="delete_labels")


# ---- Tags ----------------------------------------------------------------
class TableauAddDatabaseTagsConfig(BaseModel):
    """Add one or more tags to a database asset."""
    operation: Literal["add_database_tags"] = Field(
        "add_database_tags",
        json_schema_extra={"const": "add_database_tags", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Add Database Tags"},
        title="Add Database Tags",
    )
    database_id: str = Field(..., title="Database LUID")
    tags: Optional[str] = Field(None, title="Tags",
        description="Comma-separated tag labels")
    body_json: Optional[str] = Field(None, title="Tags Body (JSON)",
        description='Optional raw JSON, e.g. {"tag":[{"label":"x"}]}')


def _build_tags_body(tags: Optional[str], body_json: Optional[str]) -> Dict[str, Any]:
    if body_json:
        return {"tags": json.loads(body_json)}
    labels = [{"label": t.strip()} for t in (tags or "").split(",") if t.strip()]
    return {"tags": {"tag": labels}}


async def _add_database_tags(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/databases/{c.database_id}/tags",
        json_body=_build_tags_body(c.tags, c.body_json), action_name="add_database_tags")


class TableauAddTableTagsConfig(BaseModel):
    """Add one or more tags to a table asset."""
    operation: Literal["add_table_tags"] = Field(
        "add_table_tags",
        json_schema_extra={"const": "add_table_tags", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Add Table Tags"},
        title="Add Table Tags",
    )
    table_id: str = Field(..., title="Table LUID")
    tags: Optional[str] = Field(None, title="Tags",
        description="Comma-separated tag labels")
    body_json: Optional[str] = Field(None, title="Tags Body (JSON)")


async def _add_table_tags(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/tables/{c.table_id}/tags",
        json_body=_build_tags_body(c.tags, c.body_json), action_name="add_table_tags")


class TableauAddColumnTagsConfig(BaseModel):
    """Add one or more tags to a column asset."""
    operation: Literal["add_column_tags"] = Field(
        "add_column_tags",
        json_schema_extra={"const": "add_column_tags", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Add Column Tags"},
        title="Add Column Tags",
    )
    column_id: str = Field(..., title="Column LUID")
    tags: Optional[str] = Field(None, title="Tags",
        description="Comma-separated tag labels")
    body_json: Optional[str] = Field(None, title="Tags Body (JSON)")


async def _add_column_tags(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/columns/{c.column_id}/tags",
        json_body=_build_tags_body(c.tags, c.body_json), action_name="add_column_tags")


class TableauAddVirtualConnectionTagsConfig(BaseModel):
    """Add one or more tags to a virtual connection asset."""
    operation: Literal["add_virtualconnection_tags"] = Field(
        "add_virtualconnection_tags",
        json_schema_extra={"const": "add_virtualconnection_tags", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Add Virtual Connection Tags"},
        title="Add Virtual Connection Tags",
    )
    virtualconnection_id: str = Field(..., title="Virtual Connection LUID")
    tags: Optional[str] = Field(None, title="Tags",
        description="Comma-separated tag labels")
    body_json: Optional[str] = Field(None, title="Tags Body (JSON)")


async def _add_virtualconnection_tags(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/virtualconnections/{c.virtualconnection_id}/tags",
        json_body=_build_tags_body(c.tags, c.body_json), action_name="add_virtualconnection_tags")


class TableauBatchAddTagsConfig(BaseModel):
    """Batch add tags to a list of content assets."""
    operation: Literal["batch_add_tags"] = Field(
        "batch_add_tags",
        json_schema_extra={"const": "batch_add_tags", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Batch Add Tags"},
        title="Batch Add Tags",
    )
    body_json: str = Field(..., title="Body (JSON)",
        description='e.g. {"tagBatch":{"tags":{"tag":[{"label":"x"}]},"contents":{"content":[{"id":"..."}]}}}')


async def _batch_add_tags(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/tags:batchCreate",
        json_body=json.loads(c.body_json), action_name="batch_add_tags")


class TableauBatchDeleteTagsConfig(BaseModel):
    """Batch delete tags from a list of content assets."""
    operation: Literal["batch_delete_tags"] = Field(
        "batch_delete_tags",
        json_schema_extra={"const": "batch_delete_tags", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Batch Delete Tags"},
        title="Batch Delete Tags",
    )
    body_json: str = Field(..., title="Body (JSON)",
        description='e.g. {"tagBatch":{"tags":{"tag":[{"label":"x"}]},"contents":{"content":[{"id":"..."}]}}}')


async def _batch_delete_tags(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/tags:batchDelete",
        json_body=json.loads(c.body_json), action_name="batch_delete_tags")


class TableauDeleteDatabaseTagConfig(BaseModel):
    """Delete a tag from a database asset."""
    operation: Literal["delete_database_tag"] = Field(
        "delete_database_tag",
        json_schema_extra={"const": "delete_database_tag", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Delete Database Tag"},
        title="Delete Database Tag",
    )
    database_id: str = Field(..., title="Database LUID")
    tag_name: str = Field(..., title="Tag Name")


async def _delete_database_tag(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/databases/{c.database_id}/tags/{c.tag_name}",
        action_name="delete_database_tag")


class TableauDeleteTableTagConfig(BaseModel):
    """Delete a tag from a table asset."""
    operation: Literal["delete_table_tag"] = Field(
        "delete_table_tag",
        json_schema_extra={"const": "delete_table_tag", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Delete Table Tag"},
        title="Delete Table Tag",
    )
    table_id: str = Field(..., title="Table LUID")
    tag_name: str = Field(..., title="Tag Name")


async def _delete_table_tag(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/tables/{c.table_id}/tags/{c.tag_name}",
        action_name="delete_table_tag")


class TableauDeleteColumnTagConfig(BaseModel):
    """Delete a tag from a column asset."""
    operation: Literal["delete_column_tag"] = Field(
        "delete_column_tag",
        json_schema_extra={"const": "delete_column_tag", "ui:hidden": True,
                           "x-category": "Metadata", "x-is-trigger": False,
                           "x-display-name": "Delete Column Tag"},
        title="Delete Column Tag",
    )
    column_id: str = Field(..., title="Column LUID")
    tag_name: str = Field(..., title="Tag Name")


async def _delete_column_tag(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/columns/{c.column_id}/tags/{c.tag_name}",
        action_name="delete_column_tag")


OPERATION_CONFIGS.extend([
    TableauQueryDatabasesConfig,
    TableauGetDatabaseConfig,
    TableauUpdateDatabaseConfig,
    TableauDeleteDatabaseConfig,
    TableauQueryTablesConfig,
    TableauGetTableConfig,
    TableauUpdateTableConfig,
    TableauDeleteTableConfig,
    TableauQueryColumnsConfig,
    TableauGetColumnConfig,
    TableauUpdateColumnConfig,
    TableauDeleteColumnConfig,
    TableauAddDataQualityWarningConfig,
    TableauGetDataQualityWarningConfig,
    TableauGetDataQualityWarningByContentConfig,
    TableauUpdateDataQualityWarningConfig,
    TableauDeleteDataQualityWarningConfig,
    TableauDeleteDataQualityWarningByContentConfig,
    TableauBatchUpdateDataQualityWarningConfig,
    TableauBatchDeleteDataQualityWarningConfig,
    TableauCreateLabelCategoryConfig,
    TableauCreateOrUpdateLabelValueConfig,
    TableauGetLabelConfig,
    TableauDeleteLabelConfig,
    TableauDeleteLabelsConfig,
    TableauAddDatabaseTagsConfig,
    TableauAddTableTagsConfig,
    TableauAddColumnTagsConfig,
    TableauAddVirtualConnectionTagsConfig,
    TableauBatchAddTagsConfig,
    TableauBatchDeleteTagsConfig,
    TableauDeleteDatabaseTagConfig,
    TableauDeleteTableTagConfig,
    TableauDeleteColumnTagConfig,
])
OPERATION_HANDLERS.update({
    "query_databases": _query_databases,
    "get_database": _get_database,
    "update_database": _update_database,
    "delete_database": _delete_database,
    "query_tables": _query_tables,
    "get_table": _get_table,
    "update_table": _update_table,
    "delete_table": _delete_table,
    "query_columns": _query_columns,
    "get_column": _get_column,
    "update_column": _update_column,
    "delete_column": _delete_column,
    "add_data_quality_warning": _add_data_quality_warning,
    "get_data_quality_warning": _get_data_quality_warning,
    "get_data_quality_warning_by_content": _get_data_quality_warning_by_content,
    "update_data_quality_warning": _update_data_quality_warning,
    "delete_data_quality_warning": _delete_data_quality_warning,
    "delete_data_quality_warning_by_content": _delete_data_quality_warning_by_content,
    "batch_update_data_quality_warning": _batch_update_data_quality_warning,
    "batch_delete_data_quality_warning": _batch_delete_data_quality_warning,
    "create_label_category": _create_label_category,
    "create_or_update_label_value": _create_or_update_label_value,
    "get_label": _get_label,
    "delete_label": _delete_label,
    "delete_labels": _delete_labels,
    "add_database_tags": _add_database_tags,
    "add_table_tags": _add_table_tags,
    "add_column_tags": _add_column_tags,
    "add_virtualconnection_tags": _add_virtualconnection_tags,
    "batch_add_tags": _batch_add_tags,
    "batch_delete_tags": _batch_delete_tags,
    "delete_database_tag": _delete_database_tag,
    "delete_table_tag": _delete_table_tag,
    "delete_column_tag": _delete_column_tag,
})

# ============================================================================
# Connected App category — direct trust, secrets, external auth servers (EAS)
# ============================================================================


class TableauCreateConnectedAppConfig(BaseModel):
    """Create a connected app (direct trust)."""
    operation: Literal["create_connected_app"] = Field(
        "create_connected_app",
        json_schema_extra={"const": "create_connected_app", "ui:hidden": True,
                           "x-category": "Connected App", "x-is-trigger": False,
                           "x-display-name": "Create Connected App"},
        title="Create Connected App",
    )
    name: str = Field(..., title="Name")
    enabled: Optional[str] = Field("true", title="Enabled",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    domain_safelist: Optional[str] = Field(None, title="Domain Safelist",
        description="Space-separated list of allowed domains")
    unrestricted_embedding: Optional[str] = Field(None, title="Unrestricted Embedding",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the connectedApplication body (e.g. projectIds)")


async def _create_connected_app(c, server_url, token, site_id) -> Dict[str, Any]:
    app: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    app["name"] = c.name
    if c.enabled is not None: app["enabled"] = c.enabled
    if c.domain_safelist is not None: app["domainSafelist"] = c.domain_safelist
    if c.unrestricted_embedding is not None: app["unrestrictedEmbedding"] = c.unrestricted_embedding
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/connected-apps/direct-trust",
        json_body={"connectedApplication": app}, action_name="create_connected_app")


class TableauListConnectedAppsConfig(BaseModel):
    """List all connected apps (direct trust) on the site."""
    operation: Literal["list_connected_apps"] = Field(
        "list_connected_apps",
        json_schema_extra={"const": "list_connected_apps", "ui:hidden": True,
                           "x-category": "Connected App", "x-is-trigger": False,
                           "x-display-name": "List Connected Apps"},
        title="List Connected Apps",
    )
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _list_connected_apps(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/connected-apps/direct-trust",
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="list_connected_apps")


class TableauGetConnectedAppConfig(BaseModel):
    """Get a connected app (direct trust) by client id."""
    operation: Literal["get_connected_app"] = Field(
        "get_connected_app",
        json_schema_extra={"const": "get_connected_app", "ui:hidden": True,
                           "x-category": "Connected App", "x-is-trigger": False,
                           "x-display-name": "Get Connected App"},
        title="Get Connected App",
    )
    client_id: str = Field(..., title="Client ID", description="LUID of the connected app")


async def _get_connected_app(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/connected-apps/direct-trust/{c.client_id}",
        action_name="get_connected_app")


class TableauUpdateConnectedAppConfig(BaseModel):
    """Update a connected app (direct trust)."""
    operation: Literal["update_connected_app"] = Field(
        "update_connected_app",
        json_schema_extra={"const": "update_connected_app", "ui:hidden": True,
                           "x-category": "Connected App", "x-is-trigger": False,
                           "x-display-name": "Update Connected App"},
        title="Update Connected App",
    )
    client_id: str = Field(..., title="Client ID", description="LUID of the connected app")
    name: Optional[str] = Field(None, title="Name")
    enabled: Optional[str] = Field(None, title="Enabled",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    domain_safelist: Optional[str] = Field(None, title="Domain Safelist",
        description="Space-separated list of allowed domains")
    unrestricted_embedding: Optional[str] = Field(None, title="Unrestricted Embedding",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the connectedApplication body (e.g. projectIds)")


async def _update_connected_app(c, server_url, token, site_id) -> Dict[str, Any]:
    app: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: app["name"] = c.name
    if c.enabled is not None: app["enabled"] = c.enabled
    if c.domain_safelist is not None: app["domainSafelist"] = c.domain_safelist
    if c.unrestricted_embedding is not None: app["unrestrictedEmbedding"] = c.unrestricted_embedding
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/connected-apps/direct-trust/{c.client_id}",
        json_body={"connectedApplication": app}, action_name="update_connected_app")


class TableauDeleteConnectedAppConfig(BaseModel):
    """Delete a connected app (direct trust)."""
    operation: Literal["delete_connected_app"] = Field(
        "delete_connected_app",
        json_schema_extra={"const": "delete_connected_app", "ui:hidden": True,
                           "x-category": "Connected App", "x-is-trigger": False,
                           "x-display-name": "Delete Connected App"},
        title="Delete Connected App",
    )
    client_id: str = Field(..., title="Client ID", description="LUID of the connected app")


async def _delete_connected_app(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/connected-apps/direct-trust/{c.client_id}",
        action_name="delete_connected_app")


class TableauCreateConnectedAppSecretConfig(BaseModel):
    """Create a new secret for a connected app (direct trust)."""
    operation: Literal["create_connected_app_secret"] = Field(
        "create_connected_app_secret",
        json_schema_extra={"const": "create_connected_app_secret", "ui:hidden": True,
                           "x-category": "Connected App", "x-is-trigger": False,
                           "x-display-name": "Create Connected App Secret"},
        title="Create Connected App Secret",
    )
    client_id: str = Field(..., title="Client ID", description="LUID of the connected app")


async def _create_connected_app_secret(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/connected-apps/direct-trust/{c.client_id}/secrets",
        action_name="create_connected_app_secret")


class TableauGetConnectedAppSecretConfig(BaseModel):
    """Get a connected app secret by id."""
    operation: Literal["get_connected_app_secret"] = Field(
        "get_connected_app_secret",
        json_schema_extra={"const": "get_connected_app_secret", "ui:hidden": True,
                           "x-category": "Connected App", "x-is-trigger": False,
                           "x-display-name": "Get Connected App Secret"},
        title="Get Connected App Secret",
    )
    client_id: str = Field(..., title="Client ID", description="LUID of the connected app")
    secret_id: str = Field(..., title="Secret ID", description="LUID of the secret")


async def _get_connected_app_secret(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/connected-apps/direct-trust/{c.client_id}/secrets/{c.secret_id}",
        action_name="get_connected_app_secret")


class TableauDeleteConnectedAppSecretConfig(BaseModel):
    """Delete a connected app secret by id."""
    operation: Literal["delete_connected_app_secret"] = Field(
        "delete_connected_app_secret",
        json_schema_extra={"const": "delete_connected_app_secret", "ui:hidden": True,
                           "x-category": "Connected App", "x-is-trigger": False,
                           "x-display-name": "Delete Connected App Secret"},
        title="Delete Connected App Secret",
    )
    client_id: str = Field(..., title="Client ID", description="LUID of the connected app")
    secret_id: str = Field(..., title="Secret ID", description="LUID of the secret")


async def _delete_connected_app_secret(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/connected-apps/direct-trust/{c.client_id}/secrets/{c.secret_id}",
        action_name="delete_connected_app_secret")


class TableauRegisterEasConfig(BaseModel):
    """Register an external authorization server (EAS) for connected apps."""
    operation: Literal["register_eas"] = Field(
        "register_eas",
        json_schema_extra={"const": "register_eas", "ui:hidden": True,
                           "x-category": "Connected App", "x-is-trigger": False,
                           "x-display-name": "Register EAS"},
        title="Register EAS",
    )
    issuer_url: str = Field(..., title="Issuer URL")
    jwks_uri: Optional[str] = Field(None, title="JWKS URI")
    name: Optional[str] = Field(None, title="Name")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the externalAuthorizationServer body")


async def _register_eas(c, server_url, token, site_id) -> Dict[str, Any]:
    eas: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    eas["issuerUrl"] = c.issuer_url
    if c.jwks_uri is not None: eas["jwksUri"] = c.jwks_uri
    if c.name is not None: eas["name"] = c.name
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/connected-apps/external-authorization-servers",
        json_body={"externalAuthorizationServer": eas}, action_name="register_eas")


class TableauListEasConfig(BaseModel):
    """List all registered external authorization servers (EAS) on the site."""
    operation: Literal["list_eas"] = Field(
        "list_eas",
        json_schema_extra={"const": "list_eas", "ui:hidden": True,
                           "x-category": "Connected App", "x-is-trigger": False,
                           "x-display-name": "List EAS"},
        title="List EAS",
    )


async def _list_eas(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/connected-apps/external-authorization-servers",
        action_name="list_eas")


class TableauGetEasConfig(BaseModel):
    """Get a registered external authorization server (EAS) by id."""
    operation: Literal["get_eas"] = Field(
        "get_eas",
        json_schema_extra={"const": "get_eas", "ui:hidden": True,
                           "x-category": "Connected App", "x-is-trigger": False,
                           "x-display-name": "Get EAS"},
        title="Get EAS",
    )
    eas_id: str = Field(..., title="EAS ID", description="LUID of the external authorization server")


async def _get_eas(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/connected-apps/external-authorization-servers/{c.eas_id}",
        action_name="get_eas")


class TableauUpdateEasConfig(BaseModel):
    """Update a registered external authorization server (EAS)."""
    operation: Literal["update_eas"] = Field(
        "update_eas",
        json_schema_extra={"const": "update_eas", "ui:hidden": True,
                           "x-category": "Connected App", "x-is-trigger": False,
                           "x-display-name": "Update EAS"},
        title="Update EAS",
    )
    eas_id: str = Field(..., title="EAS ID", description="LUID of the external authorization server")
    issuer_url: Optional[str] = Field(None, title="Issuer URL")
    jwks_uri: Optional[str] = Field(None, title="JWKS URI")
    name: Optional[str] = Field(None, title="Name")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the externalAuthorizationServer body")


async def _update_eas(c, server_url, token, site_id) -> Dict[str, Any]:
    eas: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.issuer_url is not None: eas["issuerUrl"] = c.issuer_url
    if c.jwks_uri is not None: eas["jwksUri"] = c.jwks_uri
    if c.name is not None: eas["name"] = c.name
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/connected-apps/external-authorization-servers/{c.eas_id}",
        json_body={"externalAuthorizationServer": eas}, action_name="update_eas")


class TableauDeleteEasConfig(BaseModel):
    """Delete a registered external authorization server (EAS)."""
    operation: Literal["delete_eas"] = Field(
        "delete_eas",
        json_schema_extra={"const": "delete_eas", "ui:hidden": True,
                           "x-category": "Connected App", "x-is-trigger": False,
                           "x-display-name": "Delete EAS"},
        title="Delete EAS",
    )
    eas_id: str = Field(..., title="EAS ID", description="LUID of the external authorization server")


async def _delete_eas(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/connected-apps/external-authorization-servers/{c.eas_id}",
        action_name="delete_eas")


OPERATION_CONFIGS.extend([
    TableauCreateConnectedAppConfig,
    TableauListConnectedAppsConfig,
    TableauGetConnectedAppConfig,
    TableauUpdateConnectedAppConfig,
    TableauDeleteConnectedAppConfig,
    TableauCreateConnectedAppSecretConfig,
    TableauGetConnectedAppSecretConfig,
    TableauDeleteConnectedAppSecretConfig,
    TableauRegisterEasConfig,
    TableauListEasConfig,
    TableauGetEasConfig,
    TableauUpdateEasConfig,
    TableauDeleteEasConfig,
])
OPERATION_HANDLERS.update({
    "create_connected_app": _create_connected_app,
    "list_connected_apps": _list_connected_apps,
    "get_connected_app": _get_connected_app,
    "update_connected_app": _update_connected_app,
    "delete_connected_app": _delete_connected_app,
    "create_connected_app_secret": _create_connected_app_secret,
    "get_connected_app_secret": _get_connected_app_secret,
    "delete_connected_app_secret": _delete_connected_app_secret,
    "register_eas": _register_eas,
    "list_eas": _list_eas,
    "get_eas": _get_eas,
    "update_eas": _update_eas,
    "delete_eas": _delete_eas,
})

# ============================ Virtual Connections ============================

class TableauListVirtualConnectionsConfig(BaseModel):
    """List virtual connections on the site."""
    operation: Literal["list_virtual_connections"] = Field(
        "list_virtual_connections",
        json_schema_extra={"const": "list_virtual_connections", "ui:hidden": True,
                           "x-category": "Virtual Connections", "x-is-trigger": False,
                           "x-display-name": "List Virtual Connections"},
        title="List Virtual Connections",
    )
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")
    sort: Optional[str] = Field(None, title="Sort", description="e.g. name:asc")


async def _list_virtual_connections(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/virtualconnections",
        params={"pageSize": c.page_size, "pageNumber": c.page_number, "sort": c.sort},
        action_name="list_virtual_connections")


class TableauGetVirtualConnectionConfig(BaseModel):
    """Get (download) a virtual connection's definition."""
    operation: Literal["get_virtual_connection"] = Field(
        "get_virtual_connection",
        json_schema_extra={"const": "get_virtual_connection", "ui:hidden": True,
                           "x-category": "Virtual Connections", "x-is-trigger": False,
                           "x-display-name": "Get Virtual Connection"},
        title="Get Virtual Connection",
    )
    virtual_connection_id: str = Field(..., title="Virtual Connection LUID")


async def _get_virtual_connection(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/virtualconnections/{c.virtual_connection_id}",
        action_name="get_virtual_connection")


class TableauListVirtualConnectionConnectionsConfig(BaseModel):
    """List the database connections of a virtual connection."""
    operation: Literal["list_virtual_connection_connections"] = Field(
        "list_virtual_connection_connections",
        json_schema_extra={"const": "list_virtual_connection_connections", "ui:hidden": True,
                           "x-category": "Virtual Connections", "x-is-trigger": False,
                           "x-display-name": "List Virtual Connection DB Connections"},
        title="List Virtual Connection DB Connections",
    )
    virtual_connection_id: str = Field(..., title="Virtual Connection LUID")
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _list_virtual_connection_connections(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/virtualconnections/{c.virtual_connection_id}/connections",
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="list_virtual_connection_connections")


class TableauUpdateVirtualConnectionConnectionConfig(BaseModel):
    """Update a database connection of a virtual connection."""
    operation: Literal["update_virtual_connection_connection"] = Field(
        "update_virtual_connection_connection",
        json_schema_extra={"const": "update_virtual_connection_connection", "ui:hidden": True,
                           "x-category": "Virtual Connections", "x-is-trigger": False,
                           "x-display-name": "Update Virtual Connection DB Connection"},
        title="Update Virtual Connection DB Connection",
    )
    virtual_connection_id: str = Field(..., title="Virtual Connection LUID")
    connection_id: str = Field(..., title="Connection ID")
    server_address: Optional[str] = Field(None, title="Server Address")
    server_port: Optional[str] = Field(None, title="Server Port")
    user_name: Optional[str] = Field(None, title="User Name")
    password: Optional[str] = Field(None, title="Password")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the connection body for advanced fields")


async def _update_virtual_connection_connection(c, server_url, token, site_id) -> Dict[str, Any]:
    connection: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.server_address is not None: connection["serverAddress"] = c.server_address
    if c.server_port is not None: connection["serverPort"] = c.server_port
    if c.user_name is not None: connection["userName"] = c.user_name
    if c.password is not None: connection["password"] = c.password
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/virtualconnections/{c.virtual_connection_id}/connections/{c.connection_id}/modify",
        json_body={"connection": connection},
        action_name="update_virtual_connection_connection")


class TableauUpdateVirtualConnectionConfig(BaseModel):
    """Update a virtual connection's metadata."""
    operation: Literal["update_virtual_connection"] = Field(
        "update_virtual_connection",
        json_schema_extra={"const": "update_virtual_connection", "ui:hidden": True,
                           "x-category": "Virtual Connections", "x-is-trigger": False,
                           "x-display-name": "Update Virtual Connection"},
        title="Update Virtual Connection",
    )
    virtual_connection_id: str = Field(..., title="Virtual Connection LUID")
    name: Optional[str] = Field(None, title="Name")
    is_certified: Optional[str] = Field(None, title="Is Certified",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    certification_note: Optional[str] = Field(None, title="Certification Note")
    project_id: Optional[str] = Field(None, title="Project",
        json_schema_extra=_dyn("project_id", "a project"))
    owner_id: Optional[str] = Field(None, title="Owner User LUID")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the virtualConnection body for advanced fields")


async def _update_virtual_connection(c, server_url, token, site_id) -> Dict[str, Any]:
    vc: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: vc["name"] = c.name
    if c.is_certified is not None: vc["isCertified"] = c.is_certified
    if c.certification_note is not None: vc["certificationNote"] = c.certification_note
    if c.project_id is not None: vc["project"] = {"id": c.project_id}
    if c.owner_id is not None: vc["owner"] = {"id": c.owner_id}
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/virtualconnections/{c.virtual_connection_id}",
        json_body={"virtualConnection": vc},
        action_name="update_virtual_connection")


class TableauPublishVirtualConnectionConfig(BaseModel):
    """Publish a virtual connection."""
    operation: Literal["publish_virtual_connection"] = Field(
        "publish_virtual_connection",
        json_schema_extra={"const": "publish_virtual_connection", "ui:hidden": True,
                           "x-category": "Virtual Connections", "x-is-trigger": False,
                           "x-display-name": "Publish Virtual Connection"},
        title="Publish Virtual Connection",
    )
    name: str = Field(..., title="Name")
    project_id: str = Field(..., title="Project",
        json_schema_extra=_dyn("project_id", "a project"))
    content: str = Field(..., title="Content", description="Virtual connection JSON content string")
    owner_id: Optional[str] = Field(None, title="Owner User LUID")
    publish_as_draft: Optional[str] = Field(None, title="Publish As Draft",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    overwrite: Optional[str] = Field(None, title="Overwrite",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the virtualConnection body for advanced fields")


async def _publish_virtual_connection(c, server_url, token, site_id) -> Dict[str, Any]:
    vc: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    vc["name"] = c.name
    vc["project"] = {"id": c.project_id}
    vc["content"] = c.content
    if c.owner_id is not None: vc["owner"] = {"id": c.owner_id}
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/virtualconnections",
        params={"publishAsDraft": c.publish_as_draft, "overwrite": c.overwrite},
        json_body={"virtualConnection": vc},
        action_name="publish_virtual_connection")


class TableauDeleteVirtualConnectionConfig(BaseModel):
    """Delete a virtual connection."""
    operation: Literal["delete_virtual_connection"] = Field(
        "delete_virtual_connection",
        json_schema_extra={"const": "delete_virtual_connection", "ui:hidden": True,
                           "x-category": "Virtual Connections", "x-is-trigger": False,
                           "x-display-name": "Delete Virtual Connection"},
        title="Delete Virtual Connection",
    )
    virtual_connection_id: str = Field(..., title="Virtual Connection LUID")


async def _delete_virtual_connection(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/virtualconnections/{c.virtual_connection_id}",
        action_name="delete_virtual_connection")


class TableauListVirtualConnectionRevisionsConfig(BaseModel):
    """List revisions of a virtual connection."""
    operation: Literal["list_virtual_connection_revisions"] = Field(
        "list_virtual_connection_revisions",
        json_schema_extra={"const": "list_virtual_connection_revisions", "ui:hidden": True,
                           "x-category": "Virtual Connections", "x-is-trigger": False,
                           "x-display-name": "List Virtual Connection Revisions"},
        title="List Virtual Connection Revisions",
    )
    virtual_connection_id: str = Field(..., title="Virtual Connection LUID")
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _list_virtual_connection_revisions(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/virtualconnections/{c.virtual_connection_id}/revisions",
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="list_virtual_connection_revisions")


class TableauDownloadVirtualConnectionRevisionConfig(BaseModel):
    """Download a specific revision of a virtual connection."""
    operation: Literal["download_virtual_connection_revision"] = Field(
        "download_virtual_connection_revision",
        json_schema_extra={"const": "download_virtual_connection_revision", "ui:hidden": True,
                           "x-category": "Virtual Connections", "x-is-trigger": False,
                           "x-display-name": "Download Virtual Connection Revision"},
        title="Download Virtual Connection Revision",
    )
    virtual_connection_id: str = Field(..., title="Virtual Connection LUID")
    revision_number: str = Field(..., title="Revision Number")


async def _download_virtual_connection_revision(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/virtualconnections/{c.virtual_connection_id}/revisions/{c.revision_number}",
        raw_response=True,
        action_name="download_virtual_connection_revision")


class TableauListVirtualConnectionPermissionsConfig(BaseModel):
    """List permissions on a virtual connection."""
    operation: Literal["list_virtual_connection_permissions"] = Field(
        "list_virtual_connection_permissions",
        json_schema_extra={"const": "list_virtual_connection_permissions", "ui:hidden": True,
                           "x-category": "Virtual Connections", "x-is-trigger": False,
                           "x-display-name": "List Virtual Connection Permissions"},
        title="List Virtual Connection Permissions",
    )
    virtual_connection_id: str = Field(..., title="Virtual Connection LUID")


async def _list_virtual_connection_permissions(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET",
        f"/sites/{site_id}/virtualconnections/{c.virtual_connection_id}/permissions",
        action_name="list_virtual_connection_permissions")


class TableauAddVirtualConnectionPermissionsConfig(BaseModel):
    """Add permissions to a virtual connection."""
    operation: Literal["add_virtual_connection_permissions"] = Field(
        "add_virtual_connection_permissions",
        json_schema_extra={"const": "add_virtual_connection_permissions", "ui:hidden": True,
                           "x-category": "Virtual Connections", "x-is-trigger": False,
                           "x-display-name": "Add Virtual Connection Permissions"},
        title="Add Virtual Connection Permissions",
    )
    virtual_connection_id: str = Field(..., title="Virtual Connection LUID")
    body_json: str = Field(..., title="Permissions Body (JSON)",
        description='granteeCapabilities object, e.g. {"granteeCapabilities":[{"user":{"id":"..."},"capabilities":{"capability":[{"name":"Read","mode":"Allow"}]}}]}')


async def _add_virtual_connection_permissions(c, server_url, token, site_id) -> Dict[str, Any]:
    permissions: Dict[str, Any] = json.loads(c.body_json)
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/virtualconnections/{c.virtual_connection_id}/permissions",
        json_body={"permissions": permissions},
        action_name="add_virtual_connection_permissions")


class TableauDeleteVirtualConnectionPermissionConfig(BaseModel):
    """Delete a single permission from a virtual connection."""
    operation: Literal["delete_virtual_connection_permission"] = Field(
        "delete_virtual_connection_permission",
        json_schema_extra={"const": "delete_virtual_connection_permission", "ui:hidden": True,
                           "x-category": "Virtual Connections", "x-is-trigger": False,
                           "x-display-name": "Delete Virtual Connection Permission"},
        title="Delete Virtual Connection Permission",
    )
    virtual_connection_id: str = Field(..., title="Virtual Connection LUID")
    grantee_type: str = Field(..., title="Grantee Type",
        json_schema_extra={"enum": ["users", "groups"], "x-enum-searchable": True})
    grantee_id: str = Field(..., title="Grantee LUID", description="User or group LUID")
    capability_name: str = Field(..., title="Capability Name",
        description="e.g. Read, Connect, Overwrite, ChangeHierarchy, Delete, ChangePermissions")
    capability_mode: str = Field(..., title="Capability Mode",
        json_schema_extra={"enum": ["Allow", "Deny"], "x-enum-searchable": True})


async def _delete_virtual_connection_permission(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/virtualconnections/{c.virtual_connection_id}/permissions/"
        f"{c.grantee_type}/{c.grantee_id}/{c.capability_name}/{c.capability_mode}",
        action_name="delete_virtual_connection_permission")


class TableauAddVirtualConnectionTagsConfig(BaseModel):
    """Add tags to a virtual connection."""
    operation: Literal["add_virtual_connection_tags"] = Field(
        "add_virtual_connection_tags",
        json_schema_extra={"const": "add_virtual_connection_tags", "ui:hidden": True,
                           "x-category": "Virtual Connections", "x-is-trigger": False,
                           "x-display-name": "Add Virtual Connection Tags"},
        title="Add Virtual Connection Tags",
    )
    virtual_connection_id: str = Field(..., title="Virtual Connection LUID")
    tags: Optional[str] = Field(None, title="Tags",
        description="Comma-separated tag labels")
    body_json: Optional[str] = Field(None, title="Tags Body (JSON)",
        description='Optional raw tag array, e.g. [{"label":"finance"}] — overrides Tags')


async def _add_virtual_connection_tags(c, server_url, token, site_id) -> Dict[str, Any]:
    if c.body_json:
        tag_list = json.loads(c.body_json)
    else:
        tag_list = [{"label": t.strip()} for t in (c.tags or "").split(",") if t.strip()]
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/virtualconnections/{c.virtual_connection_id}/tags",
        json_body={"tags": {"tag": tag_list}},
        action_name="add_virtual_connection_tags")


class TableauDeleteVirtualConnectionTagConfig(BaseModel):
    """Delete a tag from a virtual connection."""
    operation: Literal["delete_virtual_connection_tag"] = Field(
        "delete_virtual_connection_tag",
        json_schema_extra={"const": "delete_virtual_connection_tag", "ui:hidden": True,
                           "x-category": "Virtual Connections", "x-is-trigger": False,
                           "x-display-name": "Delete Virtual Connection Tag"},
        title="Delete Virtual Connection Tag",
    )
    virtual_connection_id: str = Field(..., title="Virtual Connection LUID")
    tag_name: str = Field(..., title="Tag Name")


async def _delete_virtual_connection_tag(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE",
        f"/sites/{site_id}/virtualconnections/{c.virtual_connection_id}/tags/{c.tag_name}",
        action_name="delete_virtual_connection_tag")


OPERATION_CONFIGS.extend([
    TableauListVirtualConnectionsConfig,
    TableauGetVirtualConnectionConfig,
    TableauListVirtualConnectionConnectionsConfig,
    TableauUpdateVirtualConnectionConnectionConfig,
    TableauUpdateVirtualConnectionConfig,
    TableauPublishVirtualConnectionConfig,
    TableauDeleteVirtualConnectionConfig,
    TableauListVirtualConnectionRevisionsConfig,
    TableauDownloadVirtualConnectionRevisionConfig,
    TableauListVirtualConnectionPermissionsConfig,
    TableauAddVirtualConnectionPermissionsConfig,
    TableauDeleteVirtualConnectionPermissionConfig,
    TableauAddVirtualConnectionTagsConfig,
    TableauDeleteVirtualConnectionTagConfig,
])
OPERATION_HANDLERS.update({
    "list_virtual_connections": _list_virtual_connections,
    "get_virtual_connection": _get_virtual_connection,
    "list_virtual_connection_connections": _list_virtual_connection_connections,
    "update_virtual_connection_connection": _update_virtual_connection_connection,
    "update_virtual_connection": _update_virtual_connection,
    "publish_virtual_connection": _publish_virtual_connection,
    "delete_virtual_connection": _delete_virtual_connection,
    "list_virtual_connection_revisions": _list_virtual_connection_revisions,
    "download_virtual_connection_revision": _download_virtual_connection_revision,
    "list_virtual_connection_permissions": _list_virtual_connection_permissions,
    "add_virtual_connection_permissions": _add_virtual_connection_permissions,
    "delete_virtual_connection_permission": _delete_virtual_connection_permission,
    "add_virtual_connection_tags": _add_virtual_connection_tags,
    "delete_virtual_connection_tag": _delete_virtual_connection_tag,
})

# ============================================================================
# Publishing — chunked file upload session endpoints.
# Full multipart publish (workbook/datasource/flow) is out of scope; these two
# initiate + append to the upload session that a multipart publish consumes.
# ============================================================================


class TableauInitiateFileUploadConfig(BaseModel):
    """Initiate a chunked file upload session; returns an uploadSessionId."""
    operation: Literal["initiate_file_upload"] = Field(
        "initiate_file_upload",
        json_schema_extra={"const": "initiate_file_upload", "ui:hidden": True,
                           "x-category": "Publishing", "x-is-trigger": False,
                           "x-display-name": "Initiate File Upload"},
        title="Initiate File Upload",
    )


async def _initiate_file_upload(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "POST",
        f"/sites/{site_id}/fileUploads",
        action_name="initiate_file_upload")


class TableauAppendFileUploadConfig(BaseModel):
    """Append a chunk to an existing file upload session."""
    operation: Literal["append_file_upload"] = Field(
        "append_file_upload",
        json_schema_extra={"const": "append_file_upload", "ui:hidden": True,
                           "x-category": "Publishing", "x-is-trigger": False,
                           "x-display-name": "Append to File Upload"},
        title="Append to File Upload",
    )
    upload_session_id: str = Field(..., title="Upload Session ID",
        description="The uploadSessionId returned by Initiate File Upload")
    sequence_id: str = Field(..., title="Sequence ID",
        description="The order of this chunk within the upload session")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON for the multipart chunk payload (advanced)")


async def _append_file_upload(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else None
    return await _tableau_request(server_url, token, "PUT",
        f"/sites/{site_id}/fileUploads/{c.upload_session_id}",
        params={"sequenceID": c.sequence_id}, json_body=body,
        action_name="append_file_upload")


OPERATION_CONFIGS.extend([
    TableauInitiateFileUploadConfig,
    TableauAppendFileUploadConfig,
])
OPERATION_HANDLERS.update({
    "initiate_file_upload": _initiate_file_upload,
    "append_file_upload": _append_file_upload,
})

# ============================================================================
# PULSE OPERATIONS — Tableau Pulse metrics API.
# Pulse lives OFF the versioned/site-scoped base: {server}/api/-/pulse/...
# Every handler passes url_override so it hits the Pulse surface directly.
# ============================================================================

_PULSE_CAT = {"x-category": "Pulse", "x-is-trigger": False}


def _pulse_url(server_url: str, path: str) -> str:
    return f"{server_url.rstrip('/')}{path}"


# ---- Alerts ---------------------------------------------------------------
class TableauListPulseAlertsConfig(BaseModel):
    """List Pulse alerts on the site."""
    operation: Literal["list_pulse_alerts"] = Field(
        "list_pulse_alerts",
        json_schema_extra={"const": "list_pulse_alerts", "ui:hidden": True,
                           "x-display-name": "List Pulse Alerts", **_PULSE_CAT},
        title="List Pulse Alerts",
    )
    page_size: Optional[str] = Field(None, title="Page Size")
    page_token: Optional[str] = Field(None, title="Page Token")


async def _list_pulse_alerts(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/alerts"),
        params={"page_size": c.page_size, "page_token": c.page_token},
        action_name="list_pulse_alerts")


# ---- Definitions ----------------------------------------------------------
class TableauListMetricDefinitionsConfig(BaseModel):
    """List Pulse metric definitions."""
    operation: Literal["list_metric_definitions"] = Field(
        "list_metric_definitions",
        json_schema_extra={"const": "list_metric_definitions", "ui:hidden": True,
                           "x-display-name": "List Metric Definitions", **_PULSE_CAT},
        title="List Metric Definitions",
    )
    view: Optional[str] = Field(None, title="View",
        description="DEFINITION_VIEW_BASIC | DEFINITION_VIEW_FULL | DEFINITION_VIEW_DEFAULT")
    page_size: Optional[str] = Field(None, title="Page Size")
    page_token: Optional[str] = Field(None, title="Page Token")


async def _list_metric_definitions(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/definitions"),
        params={"view": c.view, "page_size": c.page_size, "page_token": c.page_token},
        action_name="list_metric_definitions")


class TableauCreateMetricDefinitionConfig(BaseModel):
    """Create a Pulse metric definition."""
    operation: Literal["create_metric_definition"] = Field(
        "create_metric_definition",
        json_schema_extra={"const": "create_metric_definition", "ui:hidden": True,
                           "x-display-name": "Create Metric Definition", **_PULSE_CAT},
        title="Create Metric Definition",
    )
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(None, title="Description")
    body_json: Optional[str] = Field(None, title="Definition Body (JSON)",
        description="Raw JSON for the metric definition (specification, datasource, etc.), merged at top level")


async def _create_metric_definition(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: body["name"] = c.name
    if c.description is not None: body["description"] = c.description
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/definitions"),
        json_body=body, action_name="create_metric_definition")


class TableauDeleteMetricDefinitionConfig(BaseModel):
    """Delete a Pulse metric definition."""
    operation: Literal["delete_metric_definition"] = Field(
        "delete_metric_definition",
        json_schema_extra={"const": "delete_metric_definition", "ui:hidden": True,
                           "x-display-name": "Delete Metric Definition", **_PULSE_CAT},
        title="Delete Metric Definition",
    )
    definition_id: str = Field(..., title="Definition ID")


async def _delete_metric_definition(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE", "",
        url_override=_pulse_url(server_url, f"/api/-/pulse/definitions/{c.definition_id}"),
        action_name="delete_metric_definition")


class TableauGetMetricDefinitionConfig(BaseModel):
    """Get a Pulse metric definition."""
    operation: Literal["get_metric_definition"] = Field(
        "get_metric_definition",
        json_schema_extra={"const": "get_metric_definition", "ui:hidden": True,
                           "x-display-name": "Get Metric Definition", **_PULSE_CAT},
        title="Get Metric Definition",
    )
    definition_id: str = Field(..., title="Definition ID")
    view: Optional[str] = Field(None, title="View",
        description="DEFINITION_VIEW_BASIC | DEFINITION_VIEW_FULL | DEFINITION_VIEW_DEFAULT")


async def _get_metric_definition(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_pulse_url(server_url, f"/api/-/pulse/definitions/{c.definition_id}"),
        params={"view": c.view}, action_name="get_metric_definition")


class TableauUpdateMetricDefinitionConfig(BaseModel):
    """Update a Pulse metric definition."""
    operation: Literal["update_metric_definition"] = Field(
        "update_metric_definition",
        json_schema_extra={"const": "update_metric_definition", "ui:hidden": True,
                           "x-display-name": "Update Metric Definition", **_PULSE_CAT},
        title="Update Metric Definition",
    )
    definition_id: str = Field(..., title="Definition ID")
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(None, title="Description")
    body_json: Optional[str] = Field(None, title="Definition Body (JSON)",
        description="Raw JSON merged at top level for advanced fields")


async def _update_metric_definition(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: body["name"] = c.name
    if c.description is not None: body["description"] = c.description
    return await _tableau_request(server_url, token, "PATCH", "",
        url_override=_pulse_url(server_url, f"/api/-/pulse/definitions/{c.definition_id}"),
        json_body=body, action_name="update_metric_definition")


class TableauListDefinitionMetricsConfig(BaseModel):
    """List the metrics belonging to a Pulse metric definition."""
    operation: Literal["list_definition_metrics"] = Field(
        "list_definition_metrics",
        json_schema_extra={"const": "list_definition_metrics", "ui:hidden": True,
                           "x-display-name": "List Definition Metrics", **_PULSE_CAT},
        title="List Definition Metrics",
    )
    definition_id: str = Field(..., title="Definition ID")
    page_size: Optional[str] = Field(None, title="Page Size")
    page_token: Optional[str] = Field(None, title="Page Token")


async def _list_definition_metrics(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_pulse_url(server_url, f"/api/-/pulse/definitions/{c.definition_id}/metrics"),
        params={"page_size": c.page_size, "page_token": c.page_token},
        action_name="list_definition_metrics")


class TableauBatchGetMetricDefinitionsConfig(BaseModel):
    """Batch get a small number of Pulse metric definitions (GET)."""
    operation: Literal["batch_get_metric_definitions"] = Field(
        "batch_get_metric_definitions",
        json_schema_extra={"const": "batch_get_metric_definitions", "ui:hidden": True,
                           "x-display-name": "Batch Get Metric Definitions", **_PULSE_CAT},
        title="Batch Get Metric Definitions",
    )
    definition_ids: Optional[str] = Field(None, title="Definition IDs",
        description="Comma-separated definition LUIDs")
    view: Optional[str] = Field(None, title="View")


async def _batch_get_metric_definitions(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/definitions:batchGet"),
        params={"definition_ids": c.definition_ids, "view": c.view},
        action_name="batch_get_metric_definitions")


class TableauBatchGetMetricDefinitionsByPostConfig(BaseModel):
    """Batch get many Pulse metric definitions (POST)."""
    operation: Literal["batch_get_metric_definitions_by_post"] = Field(
        "batch_get_metric_definitions_by_post",
        json_schema_extra={"const": "batch_get_metric_definitions_by_post", "ui:hidden": True,
                           "x-display-name": "Batch Get Metric Definitions (POST)", **_PULSE_CAT},
        title="Batch Get Metric Definitions (POST)",
    )
    body_json: Optional[str] = Field(None, title="Request Body (JSON)",
        description="Raw JSON, e.g. {\"definition_ids\": [...], \"view\": \"...\"}")


async def _batch_get_metric_definitions_by_post(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/definitions:batchGet"),
        json_body=body, action_name="batch_get_metric_definitions_by_post")


# ---- Entitlements ---------------------------------------------------------
class TableauGetPulseEntitlementsConfig(BaseModel):
    """Get Pulse site entitlements."""
    operation: Literal["get_pulse_entitlements"] = Field(
        "get_pulse_entitlements",
        json_schema_extra={"const": "get_pulse_entitlements", "ui:hidden": True,
                           "x-display-name": "Get Pulse Entitlements", **_PULSE_CAT},
        title="Get Pulse Entitlements",
    )


async def _get_pulse_entitlements(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/entitlements"),
        action_name="get_pulse_entitlements")


# ---- Images ---------------------------------------------------------------
class TableauGenerateMetricCardImageConfig(BaseModel):
    """Generate a Pulse metric card image."""
    operation: Literal["generate_metric_card_image"] = Field(
        "generate_metric_card_image",
        json_schema_extra={"const": "generate_metric_card_image", "ui:hidden": True,
                           "x-display-name": "Generate Metric Card Image", **_PULSE_CAT},
        title="Generate Metric Card Image",
    )
    body_json: Optional[str] = Field(None, title="Request Body (JSON)",
        description="Raw JSON, e.g. {\"metric\": {...}, \"size\": {...}, \"time_zone\": \"...\"}")


async def _generate_metric_card_image(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/images/metricCard"),
        json_body=body, raw_response=True, action_name="generate_metric_card_image")


# ---- Insights -------------------------------------------------------------
class TableauGenerateInsightBanConfig(BaseModel):
    """Generate the current-metric-value (BAN) insight bundle."""
    operation: Literal["generate_insight_ban"] = Field(
        "generate_insight_ban",
        json_schema_extra={"const": "generate_insight_ban", "ui:hidden": True,
                           "x-display-name": "Generate Insight Bundle (BAN)", **_PULSE_CAT},
        title="Generate Insight Bundle (BAN)",
    )
    body_json: Optional[str] = Field(None, title="Request Body (JSON)",
        description="Raw JSON insight bundle request (bundle_request with input/output specs)")


async def _generate_insight_ban(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/insights/ban"),
        json_body=body, action_name="generate_insight_ban")


class TableauGenerateInsightBasicConfig(BaseModel):
    """Generate the basic insight bundle."""
    operation: Literal["generate_insight_basic"] = Field(
        "generate_insight_basic",
        json_schema_extra={"const": "generate_insight_basic", "ui:hidden": True,
                           "x-display-name": "Generate Insight Bundle (Basic)", **_PULSE_CAT},
        title="Generate Insight Bundle (Basic)",
    )
    body_json: Optional[str] = Field(None, title="Request Body (JSON)",
        description="Raw JSON insight bundle request")


async def _generate_insight_basic(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/insights/basic"),
        json_body=body, action_name="generate_insight_basic")


class TableauGenerateInsightBreakdownConfig(BaseModel):
    """Generate the breakdown insight bundle."""
    operation: Literal["generate_insight_breakdown"] = Field(
        "generate_insight_breakdown",
        json_schema_extra={"const": "generate_insight_breakdown", "ui:hidden": True,
                           "x-display-name": "Generate Insight Bundle (Breakdown)", **_PULSE_CAT},
        title="Generate Insight Bundle (Breakdown)",
    )
    body_json: Optional[str] = Field(None, title="Request Body (JSON)",
        description="Raw JSON insight bundle request")


async def _generate_insight_breakdown(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/insights/breakdown"),
        json_body=body, action_name="generate_insight_breakdown")


class TableauGenerateInsightBriefConfig(BaseModel):
    """Generate an insight brief."""
    operation: Literal["generate_insight_brief"] = Field(
        "generate_insight_brief",
        json_schema_extra={"const": "generate_insight_brief", "ui:hidden": True,
                           "x-display-name": "Generate Insight Brief", **_PULSE_CAT},
        title="Generate Insight Brief",
    )
    body_json: Optional[str] = Field(None, title="Request Body (JSON)",
        description="Raw JSON insight brief request")


async def _generate_insight_brief(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/insights/brief"),
        json_body=body, action_name="generate_insight_brief")


class TableauGenerateInsightDetailConfig(BaseModel):
    """Generate the detail insight bundle."""
    operation: Literal["generate_insight_detail"] = Field(
        "generate_insight_detail",
        json_schema_extra={"const": "generate_insight_detail", "ui:hidden": True,
                           "x-display-name": "Generate Insight Bundle (Detail)", **_PULSE_CAT},
        title="Generate Insight Bundle (Detail)",
    )
    body_json: Optional[str] = Field(None, title="Request Body (JSON)",
        description="Raw JSON insight bundle request")


async def _generate_insight_detail(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/insights/detail"),
        json_body=body, action_name="generate_insight_detail")


class TableauGenerateInsightExplorationConfig(BaseModel):
    """Generate the exploration insight bundle."""
    operation: Literal["generate_insight_exploration"] = Field(
        "generate_insight_exploration",
        json_schema_extra={"const": "generate_insight_exploration", "ui:hidden": True,
                           "x-display-name": "Generate Insight Bundle (Exploration)", **_PULSE_CAT},
        title="Generate Insight Bundle (Exploration)",
    )
    body_json: Optional[str] = Field(None, title="Request Body (JSON)",
        description="Raw JSON insight bundle request")


async def _generate_insight_exploration(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/insights/exploration"),
        json_body=body, action_name="generate_insight_exploration")


class TableauGenerateInsightSpringboardConfig(BaseModel):
    """Generate the springboard insight bundle."""
    operation: Literal["generate_insight_springboard"] = Field(
        "generate_insight_springboard",
        json_schema_extra={"const": "generate_insight_springboard", "ui:hidden": True,
                           "x-display-name": "Generate Insight Bundle (Springboard)", **_PULSE_CAT},
        title="Generate Insight Bundle (Springboard)",
    )
    body_json: Optional[str] = Field(None, title="Request Body (JSON)",
        description="Raw JSON insight bundle request")


async def _generate_insight_springboard(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/insights/springboard"),
        json_body=body, action_name="generate_insight_springboard")


# ---- Measurement periods --------------------------------------------------
class TableauGetMeasurementPeriodsConfig(BaseModel):
    """List a Pulse metric definition's measurement periods."""
    operation: Literal["get_measurement_periods"] = Field(
        "get_measurement_periods",
        json_schema_extra={"const": "get_measurement_periods", "ui:hidden": True,
                           "x-display-name": "Get Measurement Periods", **_PULSE_CAT},
        title="Get Measurement Periods",
    )
    body_json: Optional[str] = Field(None, title="Request Body (JSON)",
        description="Raw JSON, e.g. {\"definition\": {...}}")


async def _get_measurement_periods(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/measurementPeriods"),
        json_body=body, action_name="get_measurement_periods")


# ---- Metrics --------------------------------------------------------------
class TableauCreatePulseMetricConfig(BaseModel):
    """Create a Pulse metric."""
    operation: Literal["create_pulse_metric"] = Field(
        "create_pulse_metric",
        json_schema_extra={"const": "create_pulse_metric", "ui:hidden": True,
                           "x-display-name": "Create Pulse Metric", **_PULSE_CAT},
        title="Create Pulse Metric",
    )
    definition_id: Optional[str] = Field(None, title="Definition ID")
    body_json: Optional[str] = Field(None, title="Metric Body (JSON)",
        description="Raw JSON metric (specification, is_default_metric, etc.), merged at top level")


async def _create_pulse_metric(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.definition_id is not None: body["definition_id"] = c.definition_id
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/metrics"),
        json_body=body, action_name="create_pulse_metric")


class TableauDeletePulseMetricConfig(BaseModel):
    """Delete a Pulse metric."""
    operation: Literal["delete_pulse_metric"] = Field(
        "delete_pulse_metric",
        json_schema_extra={"const": "delete_pulse_metric", "ui:hidden": True,
                           "x-display-name": "Delete Pulse Metric", **_PULSE_CAT},
        title="Delete Pulse Metric",
    )
    metric_id: str = Field(..., title="Metric ID")


async def _delete_pulse_metric(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE", "",
        url_override=_pulse_url(server_url, f"/api/-/pulse/metrics/{c.metric_id}"),
        action_name="delete_pulse_metric")


class TableauGetPulseMetricConfig(BaseModel):
    """Get a Pulse metric."""
    operation: Literal["get_pulse_metric"] = Field(
        "get_pulse_metric",
        json_schema_extra={"const": "get_pulse_metric", "ui:hidden": True,
                           "x-display-name": "Get Pulse Metric", **_PULSE_CAT},
        title="Get Pulse Metric",
    )
    metric_id: str = Field(..., title="Metric ID")


async def _get_pulse_metric(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_pulse_url(server_url, f"/api/-/pulse/metrics/{c.metric_id}"),
        action_name="get_pulse_metric")


class TableauUpdatePulseMetricConfig(BaseModel):
    """Update a Pulse metric."""
    operation: Literal["update_pulse_metric"] = Field(
        "update_pulse_metric",
        json_schema_extra={"const": "update_pulse_metric", "ui:hidden": True,
                           "x-display-name": "Update Pulse Metric", **_PULSE_CAT},
        title="Update Pulse Metric",
    )
    metric_id: str = Field(..., title="Metric ID")
    body_json: Optional[str] = Field(None, title="Metric Body (JSON)",
        description="Raw JSON merged at top level (specification, etc.)")


async def _update_pulse_metric(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _tableau_request(server_url, token, "PATCH", "",
        url_override=_pulse_url(server_url, f"/api/-/pulse/metrics/{c.metric_id}"),
        json_body=body, action_name="update_pulse_metric")


class TableauCreateMetricTagConfig(BaseModel):
    """Create a Pulse metric tag for the current user."""
    operation: Literal["create_metric_tag"] = Field(
        "create_metric_tag",
        json_schema_extra={"const": "create_metric_tag", "ui:hidden": True,
                           "x-display-name": "Create Metric Tag", **_PULSE_CAT},
        title="Create Metric Tag",
    )
    metric_id: str = Field(..., title="Metric ID")
    body_json: Optional[str] = Field(None, title="Tag Body (JSON)",
        description="Raw JSON tag request, e.g. {\"tag_value\": \"...\"}")


async def _create_metric_tag(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_pulse_url(server_url, f"/api/-/pulse/metrics/{c.metric_id}/tag"),
        json_body=body, action_name="create_metric_tag")


class TableauDeleteMetricTagConfig(BaseModel):
    """Delete a Pulse metric tag."""
    operation: Literal["delete_metric_tag"] = Field(
        "delete_metric_tag",
        json_schema_extra={"const": "delete_metric_tag", "ui:hidden": True,
                           "x-display-name": "Delete Metric Tag", **_PULSE_CAT},
        title="Delete Metric Tag",
    )
    metric_id: str = Field(..., title="Metric ID")
    tag_id: str = Field(..., title="Tag ID")


async def _delete_metric_tag(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE", "",
        url_override=_pulse_url(server_url, f"/api/-/pulse/metrics/{c.metric_id}/tag/{c.tag_id}"),
        action_name="delete_metric_tag")


class TableauBatchGetPulseMetricsConfig(BaseModel):
    """Batch get a small number of Pulse metrics (GET)."""
    operation: Literal["batch_get_pulse_metrics"] = Field(
        "batch_get_pulse_metrics",
        json_schema_extra={"const": "batch_get_pulse_metrics", "ui:hidden": True,
                           "x-display-name": "Batch Get Pulse Metrics", **_PULSE_CAT},
        title="Batch Get Pulse Metrics",
    )
    metric_ids: Optional[str] = Field(None, title="Metric IDs",
        description="Comma-separated metric LUIDs")


async def _batch_get_pulse_metrics(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/metrics:batchGet"),
        params={"metric_ids": c.metric_ids},
        action_name="batch_get_pulse_metrics")


class TableauBatchGetPulseMetricsByPostConfig(BaseModel):
    """Batch get many Pulse metrics (POST)."""
    operation: Literal["batch_get_pulse_metrics_by_post"] = Field(
        "batch_get_pulse_metrics_by_post",
        json_schema_extra={"const": "batch_get_pulse_metrics_by_post", "ui:hidden": True,
                           "x-display-name": "Batch Get Pulse Metrics (POST)", **_PULSE_CAT},
        title="Batch Get Pulse Metrics (POST)",
    )
    body_json: Optional[str] = Field(None, title="Request Body (JSON)",
        description="Raw JSON, e.g. {\"metric_ids\": [...]}")


async def _batch_get_pulse_metrics_by_post(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/metrics:batchGet"),
        json_body=body, action_name="batch_get_pulse_metrics_by_post")


class TableauListFollowedMetricsGroupsConfig(BaseModel):
    """List followed Pulse metrics groups for the current user."""
    operation: Literal["list_followed_metrics_groups"] = Field(
        "list_followed_metrics_groups",
        json_schema_extra={"const": "list_followed_metrics_groups", "ui:hidden": True,
                           "x-display-name": "List Followed Metrics Groups", **_PULSE_CAT},
        title="List Followed Metrics Groups",
    )
    page_size: Optional[str] = Field(None, title="Page Size")
    page_token: Optional[str] = Field(None, title="Page Token")


async def _list_followed_metrics_groups(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/metrics:followedMetricsGroups"),
        params={"page_size": c.page_size, "page_token": c.page_token},
        action_name="list_followed_metrics_groups")


class TableauGetOrCreatePulseMetricConfig(BaseModel):
    """Get or create a Pulse metric."""
    operation: Literal["get_or_create_pulse_metric"] = Field(
        "get_or_create_pulse_metric",
        json_schema_extra={"const": "get_or_create_pulse_metric", "ui:hidden": True,
                           "x-display-name": "Get or Create Pulse Metric", **_PULSE_CAT},
        title="Get or Create Pulse Metric",
    )
    definition_id: Optional[str] = Field(None, title="Definition ID")
    body_json: Optional[str] = Field(None, title="Metric Body (JSON)",
        description="Raw JSON metric (specification, etc.), merged at top level")


async def _get_or_create_pulse_metric(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.definition_id is not None: body["definition_id"] = c.definition_id
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/metrics:getOrCreate"),
        json_body=body, action_name="get_or_create_pulse_metric")


class TableauGetRecommendedMetricsConfig(BaseModel):
    """Get recommended Pulse metrics."""
    operation: Literal["get_recommended_metrics"] = Field(
        "get_recommended_metrics",
        json_schema_extra={"const": "get_recommended_metrics", "ui:hidden": True,
                           "x-display-name": "Get Recommended Metrics", **_PULSE_CAT},
        title="Get Recommended Metrics",
    )


async def _get_recommended_metrics(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/metrics:recommended"),
        action_name="get_recommended_metrics")


# ---- Subscriptions --------------------------------------------------------
class TableauListPulseSubscriptionsConfig(BaseModel):
    """List Pulse subscriptions."""
    operation: Literal["list_pulse_subscriptions"] = Field(
        "list_pulse_subscriptions",
        json_schema_extra={"const": "list_pulse_subscriptions", "ui:hidden": True,
                           "x-display-name": "List Pulse Subscriptions", **_PULSE_CAT},
        title="List Pulse Subscriptions",
    )
    metric_id: Optional[str] = Field(None, title="Metric ID Filter")
    user_id: Optional[str] = Field(None, title="User ID Filter")
    page_size: Optional[str] = Field(None, title="Page Size")
    page_token: Optional[str] = Field(None, title="Page Token")


async def _list_pulse_subscriptions(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/subscriptions"),
        params={"metric_id": c.metric_id, "user_id": c.user_id,
                "page_size": c.page_size, "page_token": c.page_token},
        action_name="list_pulse_subscriptions")


class TableauCreatePulseSubscriptionConfig(BaseModel):
    """Create a Pulse subscription."""
    operation: Literal["create_pulse_subscription"] = Field(
        "create_pulse_subscription",
        json_schema_extra={"const": "create_pulse_subscription", "ui:hidden": True,
                           "x-display-name": "Create Pulse Subscription", **_PULSE_CAT},
        title="Create Pulse Subscription",
    )
    metric_id: Optional[str] = Field(None, title="Metric ID")
    body_json: Optional[str] = Field(None, title="Subscription Body (JSON)",
        description="Raw JSON subscription (follower, metric_id, etc.), merged at top level")


async def _create_pulse_subscription(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.metric_id is not None: body["metric_id"] = c.metric_id
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/subscriptions"),
        json_body=body, action_name="create_pulse_subscription")


class TableauDeletePulseSubscriptionConfig(BaseModel):
    """Delete a Pulse subscription."""
    operation: Literal["delete_pulse_subscription"] = Field(
        "delete_pulse_subscription",
        json_schema_extra={"const": "delete_pulse_subscription", "ui:hidden": True,
                           "x-display-name": "Delete Pulse Subscription", **_PULSE_CAT},
        title="Delete Pulse Subscription",
    )
    subscription_id: str = Field(..., title="Subscription ID")


async def _delete_pulse_subscription(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE", "",
        url_override=_pulse_url(server_url, f"/api/-/pulse/subscriptions/{c.subscription_id}"),
        action_name="delete_pulse_subscription")


class TableauGetPulseSubscriptionConfig(BaseModel):
    """Get a Pulse subscription."""
    operation: Literal["get_pulse_subscription"] = Field(
        "get_pulse_subscription",
        json_schema_extra={"const": "get_pulse_subscription", "ui:hidden": True,
                           "x-display-name": "Get Pulse Subscription", **_PULSE_CAT},
        title="Get Pulse Subscription",
    )
    subscription_id: str = Field(..., title="Subscription ID")


async def _get_pulse_subscription(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_pulse_url(server_url, f"/api/-/pulse/subscriptions/{c.subscription_id}"),
        action_name="get_pulse_subscription")


class TableauBatchCreatePulseSubscriptionsConfig(BaseModel):
    """Batch create Pulse subscriptions."""
    operation: Literal["batch_create_pulse_subscriptions"] = Field(
        "batch_create_pulse_subscriptions",
        json_schema_extra={"const": "batch_create_pulse_subscriptions", "ui:hidden": True,
                           "x-display-name": "Batch Create Pulse Subscriptions", **_PULSE_CAT},
        title="Batch Create Pulse Subscriptions",
    )
    body_json: Optional[str] = Field(None, title="Request Body (JSON)",
        description="Raw JSON, e.g. {\"subscriptions\": [...]}")


async def _batch_create_pulse_subscriptions(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/subscriptions:batchCreate"),
        json_body=body, action_name="batch_create_pulse_subscriptions")


class TableauBatchGetPulseSubscriptionsConfig(BaseModel):
    """Batch get Pulse subscriptions."""
    operation: Literal["batch_get_pulse_subscriptions"] = Field(
        "batch_get_pulse_subscriptions",
        json_schema_extra={"const": "batch_get_pulse_subscriptions", "ui:hidden": True,
                           "x-display-name": "Batch Get Pulse Subscriptions", **_PULSE_CAT},
        title="Batch Get Pulse Subscriptions",
    )
    subscription_ids: Optional[str] = Field(None, title="Subscription IDs",
        description="Comma-separated subscription LUIDs")


async def _batch_get_pulse_subscriptions(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/subscriptions:batchGet"),
        params={"subscription_ids": c.subscription_ids},
        action_name="batch_get_pulse_subscriptions")


class TableauBatchGetMetricFollowerCountsConfig(BaseModel):
    """Batch get Pulse metric follower (subscriber) counts."""
    operation: Literal["batch_get_metric_follower_counts"] = Field(
        "batch_get_metric_follower_counts",
        json_schema_extra={"const": "batch_get_metric_follower_counts", "ui:hidden": True,
                           "x-display-name": "Batch Get Metric Follower Counts", **_PULSE_CAT},
        title="Batch Get Metric Follower Counts",
    )
    metric_ids: Optional[str] = Field(None, title="Metric IDs",
        description="Comma-separated metric LUIDs")


async def _batch_get_metric_follower_counts(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/subscriptions:batchGetMetricFollowerCounts"),
        params={"metric_ids": c.metric_ids},
        action_name="batch_get_metric_follower_counts")


# ---- User preferences -----------------------------------------------------
class TableauGetPulseUserPreferencesConfig(BaseModel):
    """List Pulse user preferences for the current user."""
    operation: Literal["get_pulse_user_preferences"] = Field(
        "get_pulse_user_preferences",
        json_schema_extra={"const": "get_pulse_user_preferences", "ui:hidden": True,
                           "x-display-name": "Get Pulse User Preferences", **_PULSE_CAT},
        title="Get Pulse User Preferences",
    )


async def _get_pulse_user_preferences(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/user/preferences"),
        action_name="get_pulse_user_preferences")


class TableauUpdatePulseUserPreferencesConfig(BaseModel):
    """Update Pulse user preferences for the current user."""
    operation: Literal["update_pulse_user_preferences"] = Field(
        "update_pulse_user_preferences",
        json_schema_extra={"const": "update_pulse_user_preferences", "ui:hidden": True,
                           "x-display-name": "Update Pulse User Preferences", **_PULSE_CAT},
        title="Update Pulse User Preferences",
    )
    body_json: Optional[str] = Field(None, title="Preferences Body (JSON)",
        description="Raw JSON preferences payload")


async def _update_pulse_user_preferences(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _tableau_request(server_url, token, "PATCH", "",
        url_override=_pulse_url(server_url, "/api/-/pulse/user/preferences"),
        json_body=body, action_name="update_pulse_user_preferences")


OPERATION_CONFIGS.extend([
    TableauListPulseAlertsConfig,
    TableauListMetricDefinitionsConfig,
    TableauCreateMetricDefinitionConfig,
    TableauDeleteMetricDefinitionConfig,
    TableauGetMetricDefinitionConfig,
    TableauUpdateMetricDefinitionConfig,
    TableauListDefinitionMetricsConfig,
    TableauBatchGetMetricDefinitionsConfig,
    TableauBatchGetMetricDefinitionsByPostConfig,
    TableauGetPulseEntitlementsConfig,
    TableauGenerateMetricCardImageConfig,
    TableauGenerateInsightBanConfig,
    TableauGenerateInsightBasicConfig,
    TableauGenerateInsightBreakdownConfig,
    TableauGenerateInsightBriefConfig,
    TableauGenerateInsightDetailConfig,
    TableauGenerateInsightExplorationConfig,
    TableauGenerateInsightSpringboardConfig,
    TableauGetMeasurementPeriodsConfig,
    TableauCreatePulseMetricConfig,
    TableauDeletePulseMetricConfig,
    TableauGetPulseMetricConfig,
    TableauUpdatePulseMetricConfig,
    TableauCreateMetricTagConfig,
    TableauDeleteMetricTagConfig,
    TableauBatchGetPulseMetricsConfig,
    TableauBatchGetPulseMetricsByPostConfig,
    TableauListFollowedMetricsGroupsConfig,
    TableauGetOrCreatePulseMetricConfig,
    TableauGetRecommendedMetricsConfig,
    TableauListPulseSubscriptionsConfig,
    TableauCreatePulseSubscriptionConfig,
    TableauDeletePulseSubscriptionConfig,
    TableauGetPulseSubscriptionConfig,
    TableauBatchCreatePulseSubscriptionsConfig,
    TableauBatchGetPulseSubscriptionsConfig,
    TableauBatchGetMetricFollowerCountsConfig,
    TableauGetPulseUserPreferencesConfig,
    TableauUpdatePulseUserPreferencesConfig,
])
OPERATION_HANDLERS.update({
    "list_pulse_alerts": _list_pulse_alerts,
    "list_metric_definitions": _list_metric_definitions,
    "create_metric_definition": _create_metric_definition,
    "delete_metric_definition": _delete_metric_definition,
    "get_metric_definition": _get_metric_definition,
    "update_metric_definition": _update_metric_definition,
    "list_definition_metrics": _list_definition_metrics,
    "batch_get_metric_definitions": _batch_get_metric_definitions,
    "batch_get_metric_definitions_by_post": _batch_get_metric_definitions_by_post,
    "get_pulse_entitlements": _get_pulse_entitlements,
    "generate_metric_card_image": _generate_metric_card_image,
    "generate_insight_ban": _generate_insight_ban,
    "generate_insight_basic": _generate_insight_basic,
    "generate_insight_breakdown": _generate_insight_breakdown,
    "generate_insight_brief": _generate_insight_brief,
    "generate_insight_detail": _generate_insight_detail,
    "generate_insight_exploration": _generate_insight_exploration,
    "generate_insight_springboard": _generate_insight_springboard,
    "get_measurement_periods": _get_measurement_periods,
    "create_pulse_metric": _create_pulse_metric,
    "delete_pulse_metric": _delete_pulse_metric,
    "get_pulse_metric": _get_pulse_metric,
    "update_pulse_metric": _update_pulse_metric,
    "create_metric_tag": _create_metric_tag,
    "delete_metric_tag": _delete_metric_tag,
    "batch_get_pulse_metrics": _batch_get_pulse_metrics,
    "batch_get_pulse_metrics_by_post": _batch_get_pulse_metrics_by_post,
    "list_followed_metrics_groups": _list_followed_metrics_groups,
    "get_or_create_pulse_metric": _get_or_create_pulse_metric,
    "get_recommended_metrics": _get_recommended_metrics,
    "list_pulse_subscriptions": _list_pulse_subscriptions,
    "create_pulse_subscription": _create_pulse_subscription,
    "delete_pulse_subscription": _delete_pulse_subscription,
    "get_pulse_subscription": _get_pulse_subscription,
    "batch_create_pulse_subscriptions": _batch_create_pulse_subscriptions,
    "batch_get_pulse_subscriptions": _batch_get_pulse_subscriptions,
    "batch_get_metric_follower_counts": _batch_get_metric_follower_counts,
    "get_pulse_user_preferences": _get_pulse_user_preferences,
    "update_pulse_user_preferences": _update_pulse_user_preferences,
})

# ============================================================================
# Collections — CRUD + items management. All endpoints live off the versioned
# base at {server}/api/-/collections, so every handler uses url_override.
# ============================================================================
def _collections_base(server_url: str) -> str:
    return f"{server_url.rstrip('/')}/api/-/collections"


# ---- List collections ------------------------------------------------------
class TableauQueryCollectionsConfig(BaseModel):
    """List collections on the site."""
    operation: Literal["query_collections"] = Field(
        "query_collections",
        json_schema_extra={"const": "query_collections", "ui:hidden": True,
                           "x-category": "Collections", "x-is-trigger": False,
                           "x-display-name": "Query Collections"},
        title="Query Collections",
    )
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _query_collections(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_collections_base(server_url),
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="query_collections")


# ---- Create a collection ---------------------------------------------------
class TableauCreateCollectionConfig(BaseModel):
    """Create a collection."""
    operation: Literal["create_collection"] = Field(
        "create_collection",
        json_schema_extra={"const": "create_collection", "ui:hidden": True,
                           "x-category": "Collections", "x-is-trigger": False,
                           "x-display-name": "Create Collection"},
        title="Create Collection",
    )
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(None, title="Description")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the collection body for advanced fields")


async def _create_collection(c, server_url, token, site_id) -> Dict[str, Any]:
    collection: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: collection["name"] = c.name
    if c.description is not None: collection["description"] = c.description
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_collections_base(server_url),
        json_body={"collection": collection}, action_name="create_collection")


# ---- Batch update collections ----------------------------------------------
class TableauBatchUpdateCollectionsConfig(BaseModel):
    """Batch update collections."""
    operation: Literal["batch_update_collections"] = Field(
        "batch_update_collections",
        json_schema_extra={"const": "batch_update_collections", "ui:hidden": True,
                           "x-category": "Collections", "x-is-trigger": False,
                           "x-display-name": "Batch Update Collections"},
        title="Batch Update Collections",
    )
    body_json: str = Field(..., title="Body (JSON)",
        description="Raw JSON body describing the collections to update")


async def _batch_update_collections(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "POST", "",
        url_override=f"{_collections_base(server_url)}/batchUpdate",
        json_body=json.loads(c.body_json), action_name="batch_update_collections")


# ---- Delete collections (batch) --------------------------------------------
class TableauDeleteCollectionsConfig(BaseModel):
    """Delete multiple collections by their LUIDs."""
    operation: Literal["delete_collections"] = Field(
        "delete_collections",
        json_schema_extra={"const": "delete_collections", "ui:hidden": True,
                           "x-category": "Collections", "x-is-trigger": False,
                           "x-display-name": "Delete Collections"},
        title="Delete Collections",
    )
    luids: Optional[str] = Field(None, title="Collection LUIDs",
        description="Comma-separated collection LUIDs to delete")


async def _delete_collections(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE", "",
        url_override=_collections_base(server_url),
        params={"luids": c.luids}, action_name="delete_collections")


# ---- Get a collection ------------------------------------------------------
class TableauGetCollectionConfig(BaseModel):
    """Get details of a collection."""
    operation: Literal["get_collection"] = Field(
        "get_collection",
        json_schema_extra={"const": "get_collection", "ui:hidden": True,
                           "x-category": "Collections", "x-is-trigger": False,
                           "x-display-name": "Get Collection"},
        title="Get Collection",
    )
    collection_id: str = Field(..., title="Collection LUID")


async def _get_collection(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=f"{_collections_base(server_url)}/{c.collection_id}",
        action_name="get_collection")


# ---- Delete a collection ---------------------------------------------------
class TableauDeleteCollectionConfig(BaseModel):
    """Delete a single collection by its LUID."""
    operation: Literal["delete_collection"] = Field(
        "delete_collection",
        json_schema_extra={"const": "delete_collection", "ui:hidden": True,
                           "x-category": "Collections", "x-is-trigger": False,
                           "x-display-name": "Delete Collection"},
        title="Delete Collection",
    )
    collection_id: str = Field(..., title="Collection LUID")


async def _delete_collection(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE", "",
        url_override=f"{_collections_base(server_url)}/{c.collection_id}",
        action_name="delete_collection")


# ---- List items in a collection --------------------------------------------
class TableauQueryCollectionItemsConfig(BaseModel):
    """List items in a collection."""
    operation: Literal["query_collection_items"] = Field(
        "query_collection_items",
        json_schema_extra={"const": "query_collection_items", "ui:hidden": True,
                           "x-category": "Collections", "x-is-trigger": False,
                           "x-display-name": "Query Collection Items"},
        title="Query Collection Items",
    )
    collection_id: str = Field(..., title="Collection LUID")
    page_size: Optional[str] = Field("100", title="Page Size")
    page_number: Optional[str] = Field("1", title="Page Number")


async def _query_collection_items(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=f"{_collections_base(server_url)}/{c.collection_id}/items",
        params={"pageSize": c.page_size, "pageNumber": c.page_number},
        action_name="query_collection_items")


# ---- Add items to a collection ---------------------------------------------
class TableauAddCollectionItemsConfig(BaseModel):
    """Add items to a collection."""
    operation: Literal["add_collection_items"] = Field(
        "add_collection_items",
        json_schema_extra={"const": "add_collection_items", "ui:hidden": True,
                           "x-category": "Collections", "x-is-trigger": False,
                           "x-display-name": "Add Collection Items"},
        title="Add Collection Items",
    )
    collection_id: str = Field(..., title="Collection LUID")
    body_json: str = Field(..., title="Body (JSON)",
        description="Raw JSON body listing the items to add to the collection")


async def _add_collection_items(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "POST", "",
        url_override=f"{_collections_base(server_url)}/{c.collection_id}/items/batchCreate",
        json_body=json.loads(c.body_json), action_name="add_collection_items")


# ---- Remove items from a collection ----------------------------------------
class TableauRemoveCollectionItemsConfig(BaseModel):
    """Remove items from a collection."""
    operation: Literal["remove_collection_items"] = Field(
        "remove_collection_items",
        json_schema_extra={"const": "remove_collection_items", "ui:hidden": True,
                           "x-category": "Collections", "x-is-trigger": False,
                           "x-display-name": "Remove Collection Items"},
        title="Remove Collection Items",
    )
    collection_id: str = Field(..., title="Collection LUID")
    body_json: str = Field(..., title="Body (JSON)",
        description="Raw JSON body listing the items to remove from the collection")


async def _remove_collection_items(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "POST", "",
        url_override=f"{_collections_base(server_url)}/{c.collection_id}/items/batchDelete",
        json_body=json.loads(c.body_json), action_name="remove_collection_items")


# ---- Reorder items in a collection -----------------------------------------
class TableauReorderCollectionItemsConfig(BaseModel):
    """Reorder items in a collection."""
    operation: Literal["reorder_collection_items"] = Field(
        "reorder_collection_items",
        json_schema_extra={"const": "reorder_collection_items", "ui:hidden": True,
                           "x-category": "Collections", "x-is-trigger": False,
                           "x-display-name": "Reorder Collection Items"},
        title="Reorder Collection Items",
    )
    collection_id: str = Field(..., title="Collection LUID")
    body_json: str = Field(..., title="Body (JSON)",
        description="Raw JSON body describing the new item ordering")


async def _reorder_collection_items(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "PATCH", "",
        url_override=f"{_collections_base(server_url)}/{c.collection_id}/orderItems",
        json_body=json.loads(c.body_json), action_name="reorder_collection_items")


OPERATION_CONFIGS.extend([
    TableauQueryCollectionsConfig,
    TableauCreateCollectionConfig,
    TableauBatchUpdateCollectionsConfig,
    TableauDeleteCollectionsConfig,
    TableauGetCollectionConfig,
    TableauDeleteCollectionConfig,
    TableauQueryCollectionItemsConfig,
    TableauAddCollectionItemsConfig,
    TableauRemoveCollectionItemsConfig,
    TableauReorderCollectionItemsConfig,
])
OPERATION_HANDLERS.update({
    "query_collections": _query_collections,
    "create_collection": _create_collection,
    "batch_update_collections": _batch_update_collections,
    "delete_collections": _delete_collections,
    "get_collection": _get_collection,
    "delete_collection": _delete_collection,
    "query_collection_items": _query_collection_items,
    "add_collection_items": _add_collection_items,
    "remove_collection_items": _remove_collection_items,
    "reorder_collection_items": _reorder_collection_items,
})

# ============================================================================
# IDENTITY POOLS — auth configurations + identity pools + identity stores.
# All endpoints live off the versioned base at {server}/api/-/authn-service/...
# (server-level, NOT site-scoped), so every handler passes url_override.
# Request bodies are flat protobuf-style JSON (no Tableau top-key wrapper).
# ============================================================================

def _authn_url(server_url: str, path: str) -> str:
    return f"{server_url.rstrip('/')}/api/-/authn-service{path}"


# ---- Auth Configurations ---------------------------------------------------
class TableauListAuthConfigurationConfig(BaseModel):
    """List authentication configurations on the server."""
    operation: Literal["list_auth_configuration"] = Field(
        "list_auth_configuration",
        json_schema_extra={"const": "list_auth_configuration", "ui:hidden": True,
                           "x-category": "Identity Pools", "x-is-trigger": False,
                           "x-display-name": "List Authentication Configurations"},
        title="List Authentication Configurations",
    )


async def _list_auth_configuration(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_authn_url(server_url, "/auth-configurations"),
        action_name="list_auth_configuration")


class TableauCreateAuthConfigurationConfig(BaseModel):
    """Create (register) an authentication configuration."""
    operation: Literal["create_auth_configuration"] = Field(
        "create_auth_configuration",
        json_schema_extra={"const": "create_auth_configuration", "ui:hidden": True,
                           "x-category": "Identity Pools", "x-is-trigger": False,
                           "x-display-name": "Create Authentication Configuration"},
        title="Create Authentication Configuration",
    )
    auth_type: Optional[str] = Field(None, title="Auth Type",
        description="Authentication type, e.g. OIDC")
    known_provider_alias: Optional[str] = Field(None, title="Known Provider Alias")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Raw JSON merged into the auth-configuration body (client_id, config_url, etc.)")


async def _create_auth_configuration(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.auth_type is not None: body["auth_type"] = c.auth_type
    if c.known_provider_alias is not None: body["known_provider_alias"] = c.known_provider_alias
    return await _tableau_request(server_url, token, "POST", "",
        json_body=body, url_override=_authn_url(server_url, "/auth-configurations"),
        action_name="create_auth_configuration")


class TableauDeleteAuthConfigurationConfig(BaseModel):
    """Delete an authentication configuration."""
    operation: Literal["delete_auth_configuration"] = Field(
        "delete_auth_configuration",
        json_schema_extra={"const": "delete_auth_configuration", "ui:hidden": True,
                           "x-category": "Identity Pools", "x-is-trigger": False,
                           "x-display-name": "Delete Authentication Configuration"},
        title="Delete Authentication Configuration",
    )
    auth_configuration_id: str = Field(..., title="Auth Configuration ID")


async def _delete_auth_configuration(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE", "",
        url_override=_authn_url(server_url, f"/auth-configurations/{c.auth_configuration_id}"),
        action_name="delete_auth_configuration")


class TableauUpdateAuthConfigurationConfig(BaseModel):
    """Update an authentication configuration."""
    operation: Literal["update_auth_configuration"] = Field(
        "update_auth_configuration",
        json_schema_extra={"const": "update_auth_configuration", "ui:hidden": True,
                           "x-category": "Identity Pools", "x-is-trigger": False,
                           "x-display-name": "Update Authentication Configuration"},
        title="Update Authentication Configuration",
    )
    auth_configuration_id: str = Field(..., title="Auth Configuration ID")
    auth_type: Optional[str] = Field(None, title="Auth Type")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Raw JSON merged into the auth-configuration body")


async def _update_auth_configuration(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.auth_type is not None: body["auth_type"] = c.auth_type
    return await _tableau_request(server_url, token, "PUT", "",
        json_body=body,
        url_override=_authn_url(server_url, f"/auth-configurations/{c.auth_configuration_id}"),
        action_name="update_auth_configuration")


# ---- Identity Pools --------------------------------------------------------
class TableauListIdentityPoolConfig(BaseModel):
    """List identity pools on the server."""
    operation: Literal["list_identity_pool"] = Field(
        "list_identity_pool",
        json_schema_extra={"const": "list_identity_pool", "ui:hidden": True,
                           "x-category": "Identity Pools", "x-is-trigger": False,
                           "x-display-name": "List Identity Pools"},
        title="List Identity Pools",
    )


async def _list_identity_pool(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_authn_url(server_url, "/identity-pools"),
        action_name="list_identity_pool")


class TableauCreateIdentityPoolConfig(BaseModel):
    """Create (register) an identity pool."""
    operation: Literal["create_identity_pool"] = Field(
        "create_identity_pool",
        json_schema_extra={"const": "create_identity_pool", "ui:hidden": True,
                           "x-category": "Identity Pools", "x-is-trigger": False,
                           "x-display-name": "Create Identity Pool"},
        title="Create Identity Pool",
    )
    name: Optional[str] = Field(None, title="Name")
    identity_store_instance: Optional[str] = Field(None, title="Identity Store Instance ID")
    auth_type_configuration_instance: Optional[str] = Field(None,
        title="Auth Type Configuration Instance ID")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Raw JSON merged into the identity-pool body")


async def _create_identity_pool(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: body["name"] = c.name
    if c.identity_store_instance is not None:
        body["identity_store_instance"] = c.identity_store_instance
    if c.auth_type_configuration_instance is not None:
        body["auth_type_configuration_instance"] = c.auth_type_configuration_instance
    return await _tableau_request(server_url, token, "POST", "",
        json_body=body, url_override=_authn_url(server_url, "/identity-pools"),
        action_name="create_identity_pool")


class TableauGetIdentityPoolConfig(BaseModel):
    """Get an identity pool by UUID."""
    operation: Literal["get_identity_pool"] = Field(
        "get_identity_pool",
        json_schema_extra={"const": "get_identity_pool", "ui:hidden": True,
                           "x-category": "Identity Pools", "x-is-trigger": False,
                           "x-display-name": "Get Identity Pool"},
        title="Get Identity Pool",
    )
    identity_pool_uuid: str = Field(..., title="Identity Pool UUID")


async def _get_identity_pool(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_authn_url(server_url, f"/identity-pools/{c.identity_pool_uuid}"),
        action_name="get_identity_pool")


class TableauDeleteIdentityPoolConfig(BaseModel):
    """Delete an identity pool by UUID."""
    operation: Literal["delete_identity_pool"] = Field(
        "delete_identity_pool",
        json_schema_extra={"const": "delete_identity_pool", "ui:hidden": True,
                           "x-category": "Identity Pools", "x-is-trigger": False,
                           "x-display-name": "Delete Identity Pool"},
        title="Delete Identity Pool",
    )
    identity_pool_uuid: str = Field(..., title="Identity Pool UUID")


async def _delete_identity_pool(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE", "",
        url_override=_authn_url(server_url, f"/identity-pools/{c.identity_pool_uuid}"),
        action_name="delete_identity_pool")


class TableauUpdateIdentityPoolConfig(BaseModel):
    """Update an identity pool by UUID."""
    operation: Literal["update_identity_pool"] = Field(
        "update_identity_pool",
        json_schema_extra={"const": "update_identity_pool", "ui:hidden": True,
                           "x-category": "Identity Pools", "x-is-trigger": False,
                           "x-display-name": "Update Identity Pool"},
        title="Update Identity Pool",
    )
    identity_pool_uuid: str = Field(..., title="Identity Pool UUID")
    name: Optional[str] = Field(None, title="Name")
    is_enabled: Optional[str] = Field(None, title="Is Enabled",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Raw JSON merged into the identity-pool body")


async def _update_identity_pool(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: body["name"] = c.name
    if c.is_enabled is not None: body["is_enabled"] = c.is_enabled == "true"
    return await _tableau_request(server_url, token, "PUT", "",
        json_body=body,
        url_override=_authn_url(server_url, f"/identity-pools/{c.identity_pool_uuid}"),
        action_name="update_identity_pool")


# ---- Identity Stores -------------------------------------------------------
class TableauListIdentityStoreConfig(BaseModel):
    """List identity stores on the server."""
    operation: Literal["list_identity_store"] = Field(
        "list_identity_store",
        json_schema_extra={"const": "list_identity_store", "ui:hidden": True,
                           "x-category": "Identity Pools", "x-is-trigger": False,
                           "x-display-name": "List Identity Stores"},
        title="List Identity Stores",
    )


async def _list_identity_store(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_authn_url(server_url, "/identity-stores"),
        action_name="list_identity_store")


class TableauConfigureIdentityStoreConfig(BaseModel):
    """Configure (register) an identity store."""
    operation: Literal["configure_identity_store"] = Field(
        "configure_identity_store",
        json_schema_extra={"const": "configure_identity_store", "ui:hidden": True,
                           "x-category": "Identity Pools", "x-is-trigger": False,
                           "x-display-name": "Configure Identity Store"},
        title="Configure Identity Store",
    )
    name: Optional[str] = Field(None, title="Name")
    type: Optional[str] = Field(None, title="Type",
        description="Identity store type, e.g. OpenID or LOCAL")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Raw JSON merged into the identity-store body")


async def _configure_identity_store(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None: body["name"] = c.name
    if c.type is not None: body["type"] = c.type
    return await _tableau_request(server_url, token, "POST", "",
        json_body=body, url_override=_authn_url(server_url, "/identity-stores"),
        action_name="configure_identity_store")


class TableauDeleteIdentityStoreConfig(BaseModel):
    """Delete an identity store."""
    operation: Literal["delete_identity_store"] = Field(
        "delete_identity_store",
        json_schema_extra={"const": "delete_identity_store", "ui:hidden": True,
                           "x-category": "Identity Pools", "x-is-trigger": False,
                           "x-display-name": "Delete Identity Store"},
        title="Delete Identity Store",
    )
    identity_store_id: str = Field(..., title="Identity Store ID")


async def _delete_identity_store(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE", "",
        url_override=_authn_url(server_url, f"/identity-stores/{c.identity_store_id}"),
        action_name="delete_identity_store")


OPERATION_CONFIGS.extend([
    TableauListAuthConfigurationConfig,
    TableauCreateAuthConfigurationConfig,
    TableauDeleteAuthConfigurationConfig,
    TableauUpdateAuthConfigurationConfig,
    TableauListIdentityPoolConfig,
    TableauCreateIdentityPoolConfig,
    TableauGetIdentityPoolConfig,
    TableauDeleteIdentityPoolConfig,
    TableauUpdateIdentityPoolConfig,
    TableauListIdentityStoreConfig,
    TableauConfigureIdentityStoreConfig,
    TableauDeleteIdentityStoreConfig,
])
OPERATION_HANDLERS.update({
    "list_auth_configuration": _list_auth_configuration,
    "create_auth_configuration": _create_auth_configuration,
    "delete_auth_configuration": _delete_auth_configuration,
    "update_auth_configuration": _update_auth_configuration,
    "list_identity_pool": _list_identity_pool,
    "create_identity_pool": _create_identity_pool,
    "get_identity_pool": _get_identity_pool,
    "delete_identity_pool": _delete_identity_pool,
    "update_identity_pool": _update_identity_pool,
    "list_identity_store": _list_identity_store,
    "configure_identity_store": _configure_identity_store,
    "delete_identity_store": _delete_identity_store,
})

# ============================================================================
# Content Exploration — content search + suggestions + usage stats.
# These live off the versioned REST base under {server}/api/-/... so every
# handler builds a full url_override.
# ============================================================================


class TableauBatchGetContentUsageConfig(BaseModel):
    """Get batch content usage statistics for multiple content items."""
    operation: Literal["batch_get_content_usage"] = Field(
        "batch_get_content_usage",
        json_schema_extra={"const": "batch_get_content_usage", "ui:hidden": True,
                           "x-category": "Content Exploration", "x-is-trigger": False,
                           "x-display-name": "Batch Get Content Usage"},
        title="Batch Get Content Usage",
    )
    body_json: Optional[str] = Field(None, title="Request Body (JSON)",
        description='Raw JSON body, e.g. {"content_items":[{"luid":"...","type":"workbook"}]}')


async def _batch_get_content_usage(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _tableau_request(server_url, token, "POST", "",
        json_body=body, action_name="batch_get_content_usage",
        url_override=f"{server_url.rstrip('/')}/api/-/content/usage-stats")


class TableauGetContentUsageConfig(BaseModel):
    """Get usage statistics for a single content item."""
    operation: Literal["get_content_usage"] = Field(
        "get_content_usage",
        json_schema_extra={"const": "get_content_usage", "ui:hidden": True,
                           "x-category": "Content Exploration", "x-is-trigger": False,
                           "x-display-name": "Get Content Usage"},
        title="Get Content Usage",
    )
    type: str = Field(..., title="Content Type",
        description="Content type, e.g. workbook, view, datasource")
    luid: str = Field(..., title="Content LUID",
        description="LUID of the content item")


async def _get_content_usage(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        action_name="get_content_usage",
        url_override=f"{server_url.rstrip('/')}/api/-/content/usage-stats/{c.type}/{c.luid}")


class TableauSearchContentConfig(BaseModel):
    """Get content search results across the site."""
    operation: Literal["search_content"] = Field(
        "search_content",
        json_schema_extra={"const": "search_content", "ui:hidden": True,
                           "x-category": "Content Exploration", "x-is-trigger": False,
                           "x-display-name": "Search Content"},
        title="Search Content",
    )
    terms: Optional[str] = Field(None, title="Search Terms",
        description="Terms to search for")
    filter: Optional[str] = Field(None, title="Filter",
        description="Filter expression, e.g. type:eq:workbook")
    order_by: Optional[str] = Field(None, title="Order By",
        description="Sort expression, e.g. hitsTotal:desc")
    limit: Optional[str] = Field("10", title="Limit")
    page: Optional[str] = Field(None, title="Page")


async def _search_content(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        params={"terms": c.terms, "filter": c.filter, "order_by": c.order_by,
                "limit": c.limit, "page": c.page},
        action_name="search_content",
        url_override=f"{server_url.rstrip('/')}/api/-/search")


class TableauGetContentSuggestionsConfig(BaseModel):
    """Get content suggestions for a search term."""
    operation: Literal["get_content_suggestions"] = Field(
        "get_content_suggestions",
        json_schema_extra={"const": "get_content_suggestions", "ui:hidden": True,
                           "x-category": "Content Exploration", "x-is-trigger": False,
                           "x-display-name": "Get Content Suggestions"},
        title="Get Content Suggestions",
    )
    terms: Optional[str] = Field(None, title="Search Terms",
        description="Partial terms to get suggestions for")
    filter: Optional[str] = Field(None, title="Filter",
        description="Filter expression, e.g. type:eq:workbook")
    limit: Optional[str] = Field("10", title="Limit")


async def _get_content_suggestions(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        params={"terms": c.terms, "filter": c.filter, "limit": c.limit},
        action_name="get_content_suggestions",
        url_override=f"{server_url.rstrip('/')}/api/-/suggestions")


OPERATION_CONFIGS.extend([
    TableauBatchGetContentUsageConfig,
    TableauGetContentUsageConfig,
    TableauSearchContentConfig,
    TableauGetContentSuggestionsConfig,
])
OPERATION_HANDLERS.update({
    "batch_get_content_usage": _batch_get_content_usage,
    "get_content_usage": _get_content_usage,
    "search_content": _search_content,
    "get_content_suggestions": _get_content_suggestions,
})

# ============================================================================
# Custom Domain — site custom domain settings CRUD.
# Off-version surface: {server}/api/-/customdomains/... (url_override).
# The {site_luid} path param is the signed-in site, so we use site_id directly.
# ============================================================================
def _customdomains_url(server_url: str, path: str) -> str:
    return f"{server_url.rstrip('/')}/api/-/customdomains{path}"


class TableauGetCustomDomainSettingsConfig(BaseModel):
    """Get custom domain settings for the site."""
    operation: Literal["get_custom_domain_settings"] = Field(
        "get_custom_domain_settings",
        json_schema_extra={"const": "get_custom_domain_settings", "ui:hidden": True,
                           "x-category": "Custom Domain", "x-is-trigger": False,
                           "x-display-name": "Get Custom Domain Settings"},
        title="Get Custom Domain Settings",
    )


async def _get_custom_domain_settings(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_customdomains_url(server_url, f"/settings/site/{site_id}"),
        action_name="get_custom_domain_settings")


class TableauCreateCustomDomainSettingsConfig(BaseModel):
    """Create custom domain settings for the site."""
    operation: Literal["create_custom_domain_settings"] = Field(
        "create_custom_domain_settings",
        json_schema_extra={"const": "create_custom_domain_settings", "ui:hidden": True,
                           "x-category": "Custom Domain", "x-is-trigger": False,
                           "x-display-name": "Create Custom Domain Settings"},
        title="Create Custom Domain Settings",
    )
    hostname: Optional[str] = Field(None, title="Hostname",
        description="Custom domain hostname (e.g. analytics.example.com)")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the SiteCustomDomainSettingsRequest body")


async def _create_custom_domain_settings(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.hostname is not None:
        body["hostname"] = c.hostname
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_customdomains_url(server_url, f"/settings/site/{site_id}"),
        json_body=body, action_name="create_custom_domain_settings")


class TableauUpdateCustomDomainSettingsConfig(BaseModel):
    """Update custom domain settings for the site."""
    operation: Literal["update_custom_domain_settings"] = Field(
        "update_custom_domain_settings",
        json_schema_extra={"const": "update_custom_domain_settings", "ui:hidden": True,
                           "x-category": "Custom Domain", "x-is-trigger": False,
                           "x-display-name": "Update Custom Domain Settings"},
        title="Update Custom Domain Settings",
    )
    hostname: Optional[str] = Field(None, title="Hostname",
        description="Custom domain hostname (e.g. analytics.example.com)")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the SiteCustomDomainSettingsRequest body")


async def _update_custom_domain_settings(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.hostname is not None:
        body["hostname"] = c.hostname
    return await _tableau_request(server_url, token, "PUT", "",
        url_override=_customdomains_url(server_url, f"/settings/site/{site_id}"),
        json_body=body, action_name="update_custom_domain_settings")


class TableauDeleteCustomDomainSettingsConfig(BaseModel):
    """Delete custom domain settings for the site."""
    operation: Literal["delete_custom_domain_settings"] = Field(
        "delete_custom_domain_settings",
        json_schema_extra={"const": "delete_custom_domain_settings", "ui:hidden": True,
                           "x-category": "Custom Domain", "x-is-trigger": False,
                           "x-display-name": "Delete Custom Domain Settings"},
        title="Delete Custom Domain Settings",
    )


async def _delete_custom_domain_settings(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE", "",
        url_override=_customdomains_url(server_url, f"/settings/site/{site_id}"),
        action_name="delete_custom_domain_settings")


class TableauGetCustomDomainConfig(BaseModel):
    """Get the custom domain name for the site."""
    operation: Literal["get_custom_domain"] = Field(
        "get_custom_domain",
        json_schema_extra={"const": "get_custom_domain", "ui:hidden": True,
                           "x-category": "Custom Domain", "x-is-trigger": False,
                           "x-display-name": "Get Custom Domain Name"},
        title="Get Custom Domain Name",
    )


async def _get_custom_domain(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_customdomains_url(server_url, f"/site/{site_id}"),
        action_name="get_custom_domain")


OPERATION_CONFIGS.extend([
    TableauGetCustomDomainSettingsConfig,
    TableauCreateCustomDomainSettingsConfig,
    TableauUpdateCustomDomainSettingsConfig,
    TableauDeleteCustomDomainSettingsConfig,
    TableauGetCustomDomainConfig,
])
OPERATION_HANDLERS.update({
    "get_custom_domain_settings": _get_custom_domain_settings,
    "create_custom_domain_settings": _create_custom_domain_settings,
    "update_custom_domain_settings": _update_custom_domain_settings,
    "delete_custom_domain_settings": _delete_custom_domain_settings,
    "get_custom_domain": _get_custom_domain,
})

# ============================================================================
# Analytics Extensions — connections + settings (site + server level).
# All endpoints live off the versioned base at {server}/api/-/settings/...,
# so every handler builds a url_override.
# ============================================================================

def _ae_url(server_url: str, suffix: str) -> str:
    """Full URL for an analytics-extensions settings endpoint (off /api/<version>)."""
    return f"{server_url.rstrip('/')}/api/-/settings{suffix}"


# ---- Server settings -------------------------------------------------------
class TableauGetAnalyticsServerSettingsConfig(BaseModel):
    """Get enabled state of analytics extensions on the server."""
    operation: Literal["get_analytics_server_settings"] = Field(
        "get_analytics_server_settings",
        json_schema_extra={"const": "get_analytics_server_settings", "ui:hidden": True,
                           "x-category": "Analytics Extensions", "x-is-trigger": False,
                           "x-display-name": "Get Analytics Server Settings"},
        title="Get Analytics Server Settings",
    )


async def _get_analytics_server_settings(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_ae_url(server_url, "/server/extensions/analytics"),
        action_name="get_analytics_server_settings")


class TableauUpdateAnalyticsServerSettingsConfig(BaseModel):
    """Enable or disable analytics extensions on the server."""
    operation: Literal["update_analytics_server_settings"] = Field(
        "update_analytics_server_settings",
        json_schema_extra={"const": "update_analytics_server_settings", "ui:hidden": True,
                           "x-category": "Analytics Extensions", "x-is-trigger": False,
                           "x-display-name": "Update Analytics Server Settings"},
        title="Update Analytics Server Settings",
    )
    enabled: Optional[str] = Field(None, title="Enabled",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the server settings body")


async def _update_analytics_server_settings(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.enabled is not None:
        body["enabled"] = c.enabled == "true"
    return await _tableau_request(server_url, token, "PUT", "",
        url_override=_ae_url(server_url, "/server/extensions/analytics"),
        json_body=body, action_name="update_analytics_server_settings")


# ---- Site settings ---------------------------------------------------------
class TableauGetAnalyticsSiteSettingsConfig(BaseModel):
    """Get enabled state of analytics extensions on the site."""
    operation: Literal["get_analytics_site_settings"] = Field(
        "get_analytics_site_settings",
        json_schema_extra={"const": "get_analytics_site_settings", "ui:hidden": True,
                           "x-category": "Analytics Extensions", "x-is-trigger": False,
                           "x-display-name": "Get Analytics Site Settings"},
        title="Get Analytics Site Settings",
    )


async def _get_analytics_site_settings(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_ae_url(server_url, "/site/extensions/analytics"),
        action_name="get_analytics_site_settings")


class TableauUpdateAnalyticsSiteSettingsConfig(BaseModel):
    """Update enabled state of analytics extensions on the site."""
    operation: Literal["update_analytics_site_settings"] = Field(
        "update_analytics_site_settings",
        json_schema_extra={"const": "update_analytics_site_settings", "ui:hidden": True,
                           "x-category": "Analytics Extensions", "x-is-trigger": False,
                           "x-display-name": "Update Analytics Site Settings"},
        title="Update Analytics Site Settings",
    )
    enabled: Optional[str] = Field(None, title="Enabled",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the site settings body")


async def _update_analytics_site_settings(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.enabled is not None:
        body["enabled"] = c.enabled == "true"
    return await _tableau_request(server_url, token, "PUT", "",
        url_override=_ae_url(server_url, "/site/extensions/analytics"),
        json_body=body, action_name="update_analytics_site_settings")


# ---- Connections -----------------------------------------------------------
class TableauListAnalyticsConnectionsConfig(BaseModel):
    """List analytics extension connections on the site."""
    operation: Literal["list_analytics_connections"] = Field(
        "list_analytics_connections",
        json_schema_extra={"const": "list_analytics_connections", "ui:hidden": True,
                           "x-category": "Analytics Extensions", "x-is-trigger": False,
                           "x-display-name": "List Analytics Connections"},
        title="List Analytics Connections",
    )


async def _list_analytics_connections(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_ae_url(server_url, "/site/extensions/analytics/connections"),
        action_name="list_analytics_connections")


class TableauAddAnalyticsConnectionConfig(BaseModel):
    """Add an analytics extension connection to the site."""
    operation: Literal["add_analytics_connection"] = Field(
        "add_analytics_connection",
        json_schema_extra={"const": "add_analytics_connection", "ui:hidden": True,
                           "x-category": "Analytics Extensions", "x-is-trigger": False,
                           "x-display-name": "Add Analytics Connection"},
        title="Add Analytics Connection",
    )
    connection_name: Optional[str] = Field(None, title="Connection Name")
    host: Optional[str] = Field(None, title="Host")
    port: Optional[str] = Field(None, title="Port")
    enabled: Optional[str] = Field(None, title="Enabled",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the connection item body")


async def _add_analytics_connection(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.connection_name is not None: body["connectionName"] = c.connection_name
    if c.host is not None: body["host"] = c.host
    if c.port is not None: body["port"] = c.port
    if c.enabled is not None: body["enabled"] = c.enabled == "true"
    return await _tableau_request(server_url, token, "POST", "",
        url_override=_ae_url(server_url, "/site/extensions/analytics/connections"),
        json_body=body, action_name="add_analytics_connection")


class TableauGetAnalyticsConnectionConfig(BaseModel):
    """Get analytics extension connection details."""
    operation: Literal["get_analytics_connection"] = Field(
        "get_analytics_connection",
        json_schema_extra={"const": "get_analytics_connection", "ui:hidden": True,
                           "x-category": "Analytics Extensions", "x-is-trigger": False,
                           "x-display-name": "Get Analytics Connection"},
        title="Get Analytics Connection",
    )
    connection_luid: str = Field(..., title="Connection LUID")


async def _get_analytics_connection(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_ae_url(server_url, f"/site/extensions/analytics/connections/{c.connection_luid}"),
        action_name="get_analytics_connection")


class TableauUpdateAnalyticsConnectionConfig(BaseModel):
    """Update an analytics extension connection of the site."""
    operation: Literal["update_analytics_connection"] = Field(
        "update_analytics_connection",
        json_schema_extra={"const": "update_analytics_connection", "ui:hidden": True,
                           "x-category": "Analytics Extensions", "x-is-trigger": False,
                           "x-display-name": "Update Analytics Connection"},
        title="Update Analytics Connection",
    )
    connection_luid: str = Field(..., title="Connection LUID")
    connection_name: Optional[str] = Field(None, title="Connection Name")
    host: Optional[str] = Field(None, title="Host")
    port: Optional[str] = Field(None, title="Port")
    enabled: Optional[str] = Field(None, title="Enabled",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the connection item body")


async def _update_analytics_connection(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.connection_name is not None: body["connectionName"] = c.connection_name
    if c.host is not None: body["host"] = c.host
    if c.port is not None: body["port"] = c.port
    if c.enabled is not None: body["enabled"] = c.enabled == "true"
    return await _tableau_request(server_url, token, "PUT", "",
        url_override=_ae_url(server_url, f"/site/extensions/analytics/connections/{c.connection_luid}"),
        json_body=body, action_name="update_analytics_connection")


class TableauDeleteAnalyticsConnectionConfig(BaseModel):
    """Delete an analytics extension connection from the site."""
    operation: Literal["delete_analytics_connection"] = Field(
        "delete_analytics_connection",
        json_schema_extra={"const": "delete_analytics_connection", "ui:hidden": True,
                           "x-category": "Analytics Extensions", "x-is-trigger": False,
                           "x-display-name": "Delete Analytics Connection"},
        title="Delete Analytics Connection",
    )
    connection_luid: str = Field(..., title="Connection LUID")


async def _delete_analytics_connection(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE", "",
        url_override=_ae_url(server_url, f"/site/extensions/analytics/connections/{c.connection_luid}"),
        action_name="delete_analytics_connection")


# ---- Workbook connection mapping ------------------------------------------
class TableauListAnalyticsWorkbookConnectionsConfig(BaseModel):
    """List analytics extension connections available to a workbook."""
    operation: Literal["list_analytics_workbook_connections"] = Field(
        "list_analytics_workbook_connections",
        json_schema_extra={"const": "list_analytics_workbook_connections", "ui:hidden": True,
                           "x-category": "Analytics Extensions", "x-is-trigger": False,
                           "x-display-name": "List Analytics Workbook Connections"},
        title="List Analytics Workbook Connections",
    )
    workbook_luid: str = Field(..., title="Workbook LUID")


async def _list_analytics_workbook_connections(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_ae_url(server_url, f"/site/extensions/analytics/workbooks/{c.workbook_luid}/connections"),
        action_name="list_analytics_workbook_connections")


class TableauGetAnalyticsWorkbookConnectionConfig(BaseModel):
    """Get the current analytics extension connection selected for a workbook."""
    operation: Literal["get_analytics_workbook_connection"] = Field(
        "get_analytics_workbook_connection",
        json_schema_extra={"const": "get_analytics_workbook_connection", "ui:hidden": True,
                           "x-category": "Analytics Extensions", "x-is-trigger": False,
                           "x-display-name": "Get Analytics Workbook Connection"},
        title="Get Analytics Workbook Connection",
    )
    workbook_luid: str = Field(..., title="Workbook LUID")


async def _get_analytics_workbook_connection(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "GET", "",
        url_override=_ae_url(server_url, f"/site/extensions/analytics/workbooks/{c.workbook_luid}/selected_connection"),
        action_name="get_analytics_workbook_connection")


class TableauUpdateAnalyticsWorkbookConnectionConfig(BaseModel):
    """Set the analytics extension connection for a workbook."""
    operation: Literal["update_analytics_workbook_connection"] = Field(
        "update_analytics_workbook_connection",
        json_schema_extra={"const": "update_analytics_workbook_connection", "ui:hidden": True,
                           "x-category": "Analytics Extensions", "x-is-trigger": False,
                           "x-display-name": "Update Analytics Workbook Connection"},
        title="Update Analytics Workbook Connection",
    )
    workbook_luid: str = Field(..., title="Workbook LUID")
    connection_luid: Optional[str] = Field(None, title="Connection LUID",
        description="LUID of the analytics extension connection to map to the workbook")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the connection mapping body")


async def _update_analytics_workbook_connection(c, server_url, token, site_id) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.connection_luid is not None:
        body["connectionLuid"] = c.connection_luid
    return await _tableau_request(server_url, token, "PUT", "",
        url_override=_ae_url(server_url, f"/site/extensions/analytics/workbooks/{c.workbook_luid}/selected_connection"),
        json_body=body, action_name="update_analytics_workbook_connection")


class TableauDeleteAnalyticsWorkbookConnectionConfig(BaseModel):
    """Remove the current analytics extension connection for a workbook."""
    operation: Literal["delete_analytics_workbook_connection"] = Field(
        "delete_analytics_workbook_connection",
        json_schema_extra={"const": "delete_analytics_workbook_connection", "ui:hidden": True,
                           "x-category": "Analytics Extensions", "x-is-trigger": False,
                           "x-display-name": "Delete Analytics Workbook Connection"},
        title="Delete Analytics Workbook Connection",
    )
    workbook_luid: str = Field(..., title="Workbook LUID")


async def _delete_analytics_workbook_connection(c, server_url, token, site_id) -> Dict[str, Any]:
    return await _tableau_request(server_url, token, "DELETE", "",
        url_override=_ae_url(server_url, f"/site/extensions/analytics/workbooks/{c.workbook_luid}/selected_connection"),
        action_name="delete_analytics_workbook_connection")


OPERATION_CONFIGS.extend([
    TableauGetAnalyticsServerSettingsConfig,
    TableauUpdateAnalyticsServerSettingsConfig,
    TableauGetAnalyticsSiteSettingsConfig,
    TableauUpdateAnalyticsSiteSettingsConfig,
    TableauListAnalyticsConnectionsConfig,
    TableauAddAnalyticsConnectionConfig,
    TableauGetAnalyticsConnectionConfig,
    TableauUpdateAnalyticsConnectionConfig,
    TableauDeleteAnalyticsConnectionConfig,
    TableauListAnalyticsWorkbookConnectionsConfig,
    TableauGetAnalyticsWorkbookConnectionConfig,
    TableauUpdateAnalyticsWorkbookConnectionConfig,
    TableauDeleteAnalyticsWorkbookConnectionConfig,
])
OPERATION_HANDLERS.update({
    "get_analytics_server_settings": _get_analytics_server_settings,
    "update_analytics_server_settings": _update_analytics_server_settings,
    "get_analytics_site_settings": _get_analytics_site_settings,
    "update_analytics_site_settings": _update_analytics_site_settings,
    "list_analytics_connections": _list_analytics_connections,
    "add_analytics_connection": _add_analytics_connection,
    "get_analytics_connection": _get_analytics_connection,
    "update_analytics_connection": _update_analytics_connection,
    "delete_analytics_connection": _delete_analytics_connection,
    "list_analytics_workbook_connections": _list_analytics_workbook_connections,
    "get_analytics_workbook_connection": _get_analytics_workbook_connection,
    "update_analytics_workbook_connection": _update_analytics_workbook_connection,
    "delete_analytics_workbook_connection": _delete_analytics_workbook_connection,
})


# ============================================================================
# Dedup: a few permission/session ops were defined by both the Permissions
# category and per-content-type categories. Keep one config per operation name
# (handlers is a dict so last-wins is already fine).
# ============================================================================
_seen = set()
_deduped = []
for _cfg in OPERATION_CONFIGS:
    _op = _cfg.model_fields["operation"].default
    if _op in _seen:
        continue
    _seen.add(_op)
    _deduped.append(_cfg)
OPERATION_CONFIGS[:] = _deduped


# Webhook trigger events the user can subscribe to (single event per webhook).
TABLEAU_WEBHOOK_EVENTS = [
    "WorkbookCreated",
    "WorkbookUpdated",
    "WorkbookDeleted",
    "WorkbookRefreshStarted",
    "WorkbookRefreshSucceeded",
    "WorkbookRefreshFailed",
    "DatasourceCreated",
    "DatasourceUpdated",
    "DatasourceDeleted",
    "DatasourceRefreshStarted",
    "DatasourceRefreshSucceeded",
    "DatasourceRefreshFailed",
    "ViewDeleted",
]


# ============================================================================
# Credential Schema
# ============================================================================


class TableauPATCredential(BaseModel):
    """Personal Access Token credential for Tableau."""

    credential_type: Literal["tableau_pat"] = Field(
        "tableau_pat", json_schema_extra={"ui:hidden": True}
    )
    server_url: str = Field(
        ...,
        title="Server URL",
        description=(
            "Your Tableau server, including the pod for Tableau Cloud "
            "(e.g. https://10ax.online.tableau.com) or your Tableau Server host."
        ),
    )
    site_content_url: str = Field(
        "",
        title="Site Content URL",
        description=(
            "The site's content URL (the part after /site/ in the browser URL). "
            "Leave blank for the Default site."
        ),
    )
    pat_name: str = Field(
        ...,
        title="Token Name",
        description="The name of the Personal Access Token from My Account Settings -> Personal Access Tokens",
    )
    pat_secret: str = Field(
        ...,
        title="Token Secret",
        description="The one-time secret shown when the Personal Access Token was created",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://help.tableau.com/current/pro/desktop/en-us/useracct.htm#create-and-revoke-personal-access-tokens"
        }
    )


TableauCredential = TableauPATCredential


# ============================================================================
# Project Operation Configs
# ============================================================================


class TableauQueryProjectsConfig(BaseModel):
    """List projects (folders) on the site."""

    operation: Literal["query_projects"] = Field(
        "query_projects",
        json_schema_extra={
            "const": "query_projects",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Query Projects",
        },
        title="Query Projects",
    )
    page_size: Optional[str] = Field(
        "100", title="Page Size", description="Number of projects per page (max 1000)"
    )
    page_number: Optional[str] = Field(
        "1", title="Page Number", description="1-based page number to fetch"
    )


class TableauCreateProjectConfig(BaseModel):
    """Create a new project on the site."""

    operation: Literal["create_project"] = Field(
        "create_project",
        json_schema_extra={
            "const": "create_project",
            "x-creates-resource": True,
            "x-resource-type": "tableau_project",
            "x-resource-id-path": "data.project.id",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Create Project",
        },
        title="Create Project",
    )
    name: str = Field(..., title="Name", description="Name of the new project")
    description: Optional[str] = Field(
        None, title="Description", description="Optional project description"
    )
    parent_project_id: Optional[str] = Field(
        None,
        title="Parent Project",
        description="LUID of the parent project to nest under (optional)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "parent_project_id",
                "placeholder": "Select a parent project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project LUID",
            }
        },
    )


class TableauDeleteProjectConfig(BaseModel):
    """Delete a project and all of its contents."""

    operation: Literal["delete_project"] = Field(
        "delete_project",
        json_schema_extra={
            "const": "delete_project",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Delete Project",
        },
        title="Delete Project",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="LUID of the project to delete",
        json_schema_extra={
            "x-resource-type": "tableau_project",
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project LUID",
            }
        },
    )


# ============================================================================
# Workbook Operation Configs
# ============================================================================


class TableauQueryWorkbooksConfig(BaseModel):
    """List workbooks on the site (supports filter / sort / paging)."""

    operation: Literal["query_workbooks"] = Field(
        "query_workbooks",
        json_schema_extra={
            "const": "query_workbooks",
            "ui:hidden": True,
            "x-category": "Workbooks",
            "x-is-trigger": False,
            "x-display-name": "Query Workbooks",
        },
        title="Query Workbooks",
    )
    filter: Optional[str] = Field(
        None,
        title="Filter",
        description="Filter expression, e.g. name:eq:Sales",
    )
    sort: Optional[str] = Field(
        None, title="Sort", description="Sort expression, e.g. name:asc"
    )
    page_size: Optional[str] = Field(
        "100", title="Page Size", description="Number of workbooks per page (max 1000)"
    )
    page_number: Optional[str] = Field(
        "1", title="Page Number", description="1-based page number to fetch"
    )


class TableauGetWorkbookConfig(BaseModel):
    """Get details for a single workbook."""

    operation: Literal["get_workbook"] = Field(
        "get_workbook",
        json_schema_extra={
            "const": "get_workbook",
            "ui:hidden": True,
            "x-category": "Workbooks",
            "x-is-trigger": False,
            "x-display-name": "Get Workbook",
        },
        title="Get Workbook",
    )
    workbook_id: str = Field(
        ..., title="Workbook ID", description="LUID of the workbook to retrieve"
    )


class TableauRefreshWorkbookConfig(BaseModel):
    """Trigger an immediate extract refresh for a workbook (returns a job)."""

    operation: Literal["refresh_workbook"] = Field(
        "refresh_workbook",
        json_schema_extra={
            "const": "refresh_workbook",
            "ui:hidden": True,
            "x-category": "Workbooks",
            "x-is-trigger": False,
            "x-display-name": "Refresh Workbook Now",
        },
        title="Refresh Workbook Now",
    )
    workbook_id: str = Field(
        ..., title="Workbook ID", description="LUID of the workbook to refresh"
    )


class TableauDeleteWorkbookConfig(BaseModel):
    """Delete a workbook from the site."""

    operation: Literal["delete_workbook"] = Field(
        "delete_workbook",
        json_schema_extra={
            "const": "delete_workbook",
            "ui:hidden": True,
            "x-category": "Workbooks",
            "x-is-trigger": False,
            "x-display-name": "Delete Workbook",
        },
        title="Delete Workbook",
    )
    workbook_id: str = Field(
        ..., title="Workbook ID", description="LUID of the workbook to delete"
    )


# ============================================================================
# View Operation Configs
# ============================================================================


class TableauQueryViewsConfig(BaseModel):
    """List all views on the site."""

    operation: Literal["query_views"] = Field(
        "query_views",
        json_schema_extra={
            "const": "query_views",
            "ui:hidden": True,
            "x-category": "Views",
            "x-is-trigger": False,
            "x-display-name": "Query Views",
        },
        title="Query Views",
    )
    filter: Optional[str] = Field(
        None, title="Filter", description="Filter expression, e.g. name:eq:Overview"
    )
    sort: Optional[str] = Field(
        None, title="Sort", description="Sort expression, e.g. name:asc"
    )
    page_size: Optional[str] = Field(
        "100", title="Page Size", description="Number of views per page (max 1000)"
    )
    page_number: Optional[str] = Field(
        "1", title="Page Number", description="1-based page number to fetch"
    )


class TableauQueryViewImageConfig(BaseModel):
    """Render a view as a PNG image."""

    operation: Literal["query_view_image"] = Field(
        "query_view_image",
        json_schema_extra={
            "const": "query_view_image",
            "ui:hidden": True,
            "x-category": "Views",
            "x-is-trigger": False,
            "x-display-name": "Query View Image",
        },
        title="Query View Image",
    )
    view_id: str = Field(
        ..., title="View ID", description="LUID of the view to render as PNG"
    )
    high_resolution: str = Field(
        "false",
        title="High Resolution",
        description="Render at high resolution",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class TableauQueryViewPdfConfig(BaseModel):
    """Render a view as a PDF document."""

    operation: Literal["query_view_pdf"] = Field(
        "query_view_pdf",
        json_schema_extra={
            "const": "query_view_pdf",
            "ui:hidden": True,
            "x-category": "Views",
            "x-is-trigger": False,
            "x-display-name": "Query View PDF",
        },
        title="Query View PDF",
    )
    view_id: str = Field(
        ..., title="View ID", description="LUID of the view to render as PDF"
    )


class TableauQueryViewDataConfig(BaseModel):
    """Export the underlying view data as CSV."""

    operation: Literal["query_view_data"] = Field(
        "query_view_data",
        json_schema_extra={
            "const": "query_view_data",
            "ui:hidden": True,
            "x-category": "Views",
            "x-is-trigger": False,
            "x-display-name": "Query View Data (CSV)",
        },
        title="Query View Data (CSV)",
    )
    view_id: str = Field(
        ..., title="View ID", description="LUID of the view to export as CSV"
    )


# ============================================================================
# Data Source Operation Configs
# ============================================================================


class TableauQueryDataSourcesConfig(BaseModel):
    """List published data sources on the site."""

    operation: Literal["query_datasources"] = Field(
        "query_datasources",
        json_schema_extra={
            "const": "query_datasources",
            "ui:hidden": True,
            "x-category": "Data Sources",
            "x-is-trigger": False,
            "x-display-name": "Query Data Sources",
        },
        title="Query Data Sources",
    )
    filter: Optional[str] = Field(
        None, title="Filter", description="Filter expression, e.g. name:eq:Orders"
    )
    sort: Optional[str] = Field(
        None, title="Sort", description="Sort expression, e.g. name:asc"
    )
    page_size: Optional[str] = Field(
        "100", title="Page Size", description="Number of data sources per page (max 1000)"
    )
    page_number: Optional[str] = Field(
        "1", title="Page Number", description="1-based page number to fetch"
    )


class TableauGetDataSourceConfig(BaseModel):
    """Get details for a single data source."""

    operation: Literal["get_datasource"] = Field(
        "get_datasource",
        json_schema_extra={
            "const": "get_datasource",
            "ui:hidden": True,
            "x-category": "Data Sources",
            "x-is-trigger": False,
            "x-display-name": "Get Data Source",
        },
        title="Get Data Source",
    )
    datasource_id: str = Field(
        ..., title="Data Source ID", description="LUID of the data source to retrieve"
    )


class TableauRefreshDataSourceConfig(BaseModel):
    """Trigger an immediate extract refresh for a data source (returns a job)."""

    operation: Literal["refresh_datasource"] = Field(
        "refresh_datasource",
        json_schema_extra={
            "const": "refresh_datasource",
            "ui:hidden": True,
            "x-category": "Data Sources",
            "x-is-trigger": False,
            "x-display-name": "Refresh Data Source Now",
        },
        title="Refresh Data Source Now",
    )
    datasource_id: str = Field(
        ..., title="Data Source ID", description="LUID of the data source to refresh"
    )


class TableauDeleteDataSourceConfig(BaseModel):
    """Delete a data source from the site."""

    operation: Literal["delete_datasource"] = Field(
        "delete_datasource",
        json_schema_extra={
            "const": "delete_datasource",
            "ui:hidden": True,
            "x-category": "Data Sources",
            "x-is-trigger": False,
            "x-display-name": "Delete Data Source",
        },
        title="Delete Data Source",
    )
    datasource_id: str = Field(
        ..., title="Data Source ID", description="LUID of the data source to delete"
    )


# ============================================================================
# User & Group Operation Configs
# ============================================================================


class TableauGetUsersConfig(BaseModel):
    """List users on the site."""

    operation: Literal["get_users"] = Field(
        "get_users",
        json_schema_extra={
            "const": "get_users",
            "ui:hidden": True,
            "x-category": "Users & Groups",
            "x-is-trigger": False,
            "x-display-name": "Get Users on Site",
        },
        title="Get Users on Site",
    )
    filter: Optional[str] = Field(
        None, title="Filter", description="Filter expression, e.g. name:eq:jsmith"
    )
    page_size: Optional[str] = Field(
        "100", title="Page Size", description="Number of users per page (max 1000)"
    )
    page_number: Optional[str] = Field(
        "1", title="Page Number", description="1-based page number to fetch"
    )


class TableauAddUserConfig(BaseModel):
    """Provision a user on the site with a site role."""

    operation: Literal["add_user"] = Field(
        "add_user",
        json_schema_extra={
            "const": "add_user",
            "ui:hidden": True,
            "x-category": "Users & Groups",
            "x-is-trigger": False,
            "x-display-name": "Add User to Site",
        },
        title="Add User to Site",
    )
    user_name: str = Field(
        ...,
        title="Username",
        description="The username (or email for Tableau Cloud) of the user to add",
    )
    site_role: str = Field(
        "Viewer",
        title="Site Role",
        description="The site role to grant the new user",
        json_schema_extra={
            "enum": [
                "Creator",
                "Explorer",
                "ExplorerCanPublish",
                "SiteAdministratorExplorer",
                "SiteAdministratorCreator",
                "Unlicensed",
                "Viewer",
            ],
            "x-enum-searchable": True,
        },
    )


class TableauQueryGroupsConfig(BaseModel):
    """List groups on the site."""

    operation: Literal["query_groups"] = Field(
        "query_groups",
        json_schema_extra={
            "const": "query_groups",
            "ui:hidden": True,
            "x-category": "Users & Groups",
            "x-is-trigger": False,
            "x-display-name": "Query Groups",
        },
        title="Query Groups",
    )
    page_size: Optional[str] = Field(
        "100", title="Page Size", description="Number of groups per page (max 1000)"
    )
    page_number: Optional[str] = Field(
        "1", title="Page Number", description="1-based page number to fetch"
    )


class TableauAddUserToGroupConfig(BaseModel):
    """Add a user to a group."""

    operation: Literal["add_user_to_group"] = Field(
        "add_user_to_group",
        json_schema_extra={
            "const": "add_user_to_group",
            "ui:hidden": True,
            "x-category": "Users & Groups",
            "x-is-trigger": False,
            "x-display-name": "Add User to Group",
        },
        title="Add User to Group",
    )
    group_id: str = Field(
        ...,
        title="Group",
        description="LUID of the group to add the user to",
        json_schema_extra={
            "x-resource-type": "tableau_group",
            "x-dynamic-options": {
                "field_name": "group_id",
                "placeholder": "Select a group...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a group LUID",
            }
        },
    )
    user_id: str = Field(
        ..., title="User ID", description="LUID of the user to add to the group"
    )


# ============================================================================
# Webhook Management Operation Configs
# ============================================================================


class TableauListWebhooksConfig(BaseModel):
    """List configured webhooks on the site."""

    operation: Literal["list_webhooks"] = Field(
        "list_webhooks",
        json_schema_extra={
            "const": "list_webhooks",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "List Webhooks",
        },
        title="List Webhooks",
    )


class TableauCreateWebhookConfig(BaseModel):
    """Subscribe an HTTPS URL to a single Tableau trigger event."""

    operation: Literal["create_webhook"] = Field(
        "create_webhook",
        json_schema_extra={
            "const": "create_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Create Webhook",
        },
        title="Create Webhook",
    )
    name: str = Field(..., title="Name", description="A name for the webhook")
    destination_url: str = Field(
        ...,
        title="Destination URL",
        description="The HTTPS URL Tableau POSTs events to (valid cert required)",
    )
    event: str = Field(
        "WorkbookRefreshFailed",
        title="Event",
        description="The trigger event to subscribe to",
        json_schema_extra={
            "enum": TABLEAU_WEBHOOK_EVENTS,
            "x-enum-searchable": True,
        },
    )


class TableauTestWebhookConfig(BaseModel):
    """Send a test POST to validate a webhook."""

    operation: Literal["test_webhook"] = Field(
        "test_webhook",
        json_schema_extra={
            "const": "test_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Test Webhook",
        },
        title="Test Webhook",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="LUID of the webhook to test"
    )


class TableauDeleteWebhookConfig(BaseModel):
    """Remove a webhook subscription."""

    operation: Literal["delete_webhook"] = Field(
        "delete_webhook",
        json_schema_extra={
            "const": "delete_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Delete Webhook",
        },
        title="Delete Webhook",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="LUID of the webhook to delete"
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


# One trigger operation per Tableau webhook event. op_name -> (event, display).
_TABLEAU_TRIGGER_EVENTS = {
    "on_workbook_created": ("WorkbookCreated", "On Workbook Created"),
    "on_workbook_updated": ("WorkbookUpdated", "On Workbook Updated"),
    "on_workbook_deleted": ("WorkbookDeleted", "On Workbook Deleted"),
    "on_workbook_refresh_started": ("WorkbookRefreshStarted", "On Workbook Refresh Started"),
    "on_workbook_refresh_succeeded": ("WorkbookRefreshSucceeded", "On Workbook Refresh Succeeded"),
    "on_workbook_refresh_failed": ("WorkbookRefreshFailed", "On Workbook Refresh Failed"),
    "on_datasource_created": ("DatasourceCreated", "On Data Source Created"),
    "on_datasource_updated": ("DatasourceUpdated", "On Data Source Updated"),
    "on_datasource_deleted": ("DatasourceDeleted", "On Data Source Deleted"),
    "on_datasource_refresh_started": ("DatasourceRefreshStarted", "On Data Source Refresh Started"),
    "on_datasource_refresh_succeeded": ("DatasourceRefreshSucceeded", "On Data Source Refresh Succeeded"),
    "on_datasource_refresh_failed": ("DatasourceRefreshFailed", "On Data Source Refresh Failed"),
    "on_view_deleted": ("ViewDeleted", "On View Deleted"),
    "on_label_created": ("LabelCreated", "On Label Created"),
    "on_label_updated": ("LabelUpdated", "On Label Updated"),
    "on_label_deleted": ("LabelDeleted", "On Label Deleted"),
    "on_admin_promoted": ("AdminPromoted", "On Admin Promoted"),
    "on_admin_demoted": ("AdminDemoted", "On Admin Demoted"),
    "on_site_deleted": ("SiteDeleted", "On Site Deleted"),
    "on_user_deleted": ("UserDeleted", "On User Deleted"),
}
_TABLEAU_TRIGGER_EVENT_BY_OP = {op: ev for op, (ev, _d) in _TABLEAU_TRIGGER_EVENTS.items()}


class _TableauTriggerBase(BaseModel):
    """Shared fields for the per-event webhook triggers (one operation per event)."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Tableau posts events here. Registered automatically when you connect credentials.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


def _make_tableau_trigger(op_name: str, display: str) -> type:
    cls_name = "Tableau" + "".join(w.capitalize() for w in op_name.split("_")) + "Config"
    return create_model(
        cls_name,
        __base__=_TableauTriggerBase,
        operation=(
            Literal[op_name],
            Field(op_name, title=display, json_schema_extra={
                "const": op_name, "ui:hidden": True, "x-category": None,
                "x-is-trigger": True, "x-display-name": display,
            }),
        ),
    )


TABLEAU_TRIGGER_CONFIGS = [
    _make_tableau_trigger(op, disp) for op, (_ev, disp) in _TABLEAU_TRIGGER_EVENTS.items()
]


# ============================================================================
# Discriminated Union
# ============================================================================


TableauConfig = Annotated[
    Union[
        TableauQueryProjectsConfig,
        TableauCreateProjectConfig,
        TableauDeleteProjectConfig,
        TableauQueryWorkbooksConfig,
        TableauGetWorkbookConfig,
        TableauRefreshWorkbookConfig,
        TableauDeleteWorkbookConfig,
        TableauQueryViewsConfig,
        TableauQueryViewImageConfig,
        TableauQueryViewPdfConfig,
        TableauQueryViewDataConfig,
        TableauQueryDataSourcesConfig,
        TableauGetDataSourceConfig,
        TableauRefreshDataSourceConfig,
        TableauDeleteDataSourceConfig,
        TableauGetUsersConfig,
        TableauAddUserConfig,
        TableauQueryGroupsConfig,
        TableauAddUserToGroupConfig,
        TableauListWebhooksConfig,
        TableauCreateWebhookConfig,
        TableauTestWebhookConfig,
        TableauDeleteWebhookConfig,
        *TABLEAU_TRIGGER_CONFIGS,
        *OPERATION_CONFIGS,
    ],
    Discriminator("operation"),
]


class TableauNodeConfig(NodeConfig[TableauConfig, TableauCredential]):
    """Full configuration for the Tableau node including credentials."""

    pass


# ============================================================================
# HTTP / Sign-In Helpers
# ============================================================================


# Helpers (_tableau_request, _tableau_signin, _base_url, constants) live in
# nodes/tableau_common.py and are imported at the top of this module.


# ============================================================================
# Node Implementation
# ============================================================================


class TableauNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Tableau analytics & BI automation node."""

    # Tableau doesn't sign webhook deliveries (see verify_webhook_signature) —
    # without this flag the mixin's secret-requiring idempotency guard never
    # holds and every config-panel open re-registers + orphans the endpoint.
    webhook_signing_secret_not_issued = True

    edit_examples = [
        "List all workbooks on the Tableau site",
        "Refresh a data source extract every morning",
        "Export a view's data as CSV",
        "Render a dashboard view as a PDF",
        "Trigger a workflow when a workbook refresh fails",
    ]

    @classmethod
    def get_config_model(cls):
        return TableauNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (projects, groups)
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
        # field_name -> (collection wrapper key, item key) for the site-scoped list.
        specs = {
            "project_id": ("projects", "project"),
            "parent_project_id": ("projects", "project"),
            "group_id": ("groups", "group"),
            "workbook_id": ("workbooks", "workbook"),
            "datasource_id": ("datasources", "datasource"),
            "view_id": ("views", "view"),
            "user_id": ("users", "user"),
            "flow_id": ("flows", "flow"),
        }
        if field_name not in specs:
            return {"options": []}
        credential = credential_data
        if not credential:
            return {"options": []}

        signin = await _tableau_signin(
            credential.get("server_url"),
            credential.get("pat_name"),
            credential.get("pat_secret"),
            credential.get("site_content_url") or "",
        )
        if signin.get("status") != "success":
            return {"options": []}
        token = signin["token"]
        site_id = signin["site_id"]

        collection_key, item_key = specs[field_name]
        endpoint = f"/sites/{site_id}/{collection_key}"

        result = await _tableau_request(
            credential.get("server_url"),
            token,
            "GET",
            endpoint,
            params={"pageSize": "1000"},
            action_name=f"list_{collection_key}",
        )
        if result.get("status") != "success":
            return {"options": []}
        collection = (result.get("data") or {}).get(collection_key) or {}
        items = collection.get(item_key) or []
        if isinstance(items, dict):
            items = [items]
        options = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            name = item.get("name") or item_id
            if item_id:
                options.append({"label": str(name), "value": str(item_id)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Webhook trigger registration
    # ------------------------------------------------------------------
    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "event": (config or {}).get("event"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        signin = await _tableau_signin(
            credential.get("server_url"),
            credential.get("pat_name"),
            credential.get("pat_secret"),
            credential.get("site_content_url") or "",
        )
        if signin.get("status") != "success":
            raise ValueError(f"Tableau sign in failed: {signin.get('error')}")
        token = signin["token"]
        site_id = signin["site_id"]
        cfg = config or {}
        event = (
            _TABLEAU_TRIGGER_EVENT_BY_OP.get(cfg.get("operation"))
            or cfg.get("event")
            or "WorkbookRefreshFailed"
        )
        result = await _tableau_request(
            credential.get("server_url"),
            token,
            "POST",
            f"/sites/{site_id}/webhooks",
            json_body={
                "webhook": {
                    "name": f"NoClick {node_id}",
                    "event": event,
                    "webhook-destination": {
                        "webhook-destination-http": {
                            "method": "POST",
                            "url": webhook_url,
                        }
                    },
                }
            },
            action_name="register_webhook",
        )
        if result.get("status") != "success":
            raise ValueError(f"Tableau webhook registration failed: {result.get('error')}")
        webhook = (result.get("data") or {}).get("webhook") or {}
        external_id = webhook.get("id")
        # Tableau webhooks carry NO signature/HMAC header — security is the
        # unguessable per-node webhook URL. So we store no signing secret.
        return {
            "external_webhook_id": str(external_id) if external_id else None,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        if not external_id or not credential:
            return
        signin = await _tableau_signin(
            credential.get("server_url"),
            credential.get("pat_name"),
            credential.get("pat_secret"),
            credential.get("site_content_url") or "",
        )
        if signin.get("status") != "success":
            return
        await _tableau_request(
            credential.get("server_url"),
            signin["token"],
            "DELETE",
            f"/sites/{signin['site_id']}/webhooks/{external_id}",
            action_name="unregister_webhook",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        # Tableau does not sign webhook deliveries (no HMAC/signature header —
        # confirmed against the official events-and-payload docs). Security is
        # the unguessable, per-node webhook URL that only Tableau was given, so
        # any POST that reaches this trigger's URL is accepted.
        return True

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, TableauNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, _TableauTriggerBase):
            return {
                "status": "success",
                "action": op.operation,
                "data": {
                    **inputs,
                    "event": _TABLEAU_TRIGGER_EVENT_BY_OP.get(op.operation),
                    "webhook_url": op.webhook_url,
                },
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Tableau Personal Access Token.")

        signin = await _tableau_signin(
            credentials.server_url,
            credentials.pat_name,
            credentials.pat_secret,
            credentials.site_content_url or "",
        )
        if signin.get("status") != "success":
            signin["timing_ms"] = {
                **signin.get("timing_ms", {}),
                "total": round((time.time() - start_time) * 1000, 2),
            }
            return signin
        token = signin["token"]
        site_id = signin["site_id"]
        server_url = credentials.server_url

        handlers = {
            "query_projects": self._query_projects,
            "create_project": self._create_project,
            "delete_project": self._delete_project,
            "query_workbooks": self._query_workbooks,
            "get_workbook": self._get_workbook,
            "refresh_workbook": self._refresh_workbook,
            "delete_workbook": self._delete_workbook,
            "query_views": self._query_views,
            "query_view_image": self._query_view_image,
            "query_view_pdf": self._query_view_pdf,
            "query_view_data": self._query_view_data,
            "query_datasources": self._query_datasources,
            "get_datasource": self._get_datasource,
            "refresh_datasource": self._refresh_datasource,
            "delete_datasource": self._delete_datasource,
            "get_users": self._get_users,
            "add_user": self._add_user,
            "query_groups": self._query_groups,
            "add_user_to_group": self._add_user_to_group,
            "list_webhooks": self._list_webhooks,
            "create_webhook": self._create_webhook,
            "test_webhook": self._test_webhook,
            "delete_webhook": self._delete_webhook,
        }
        # Merge the full REST-API operation registry (module-level handlers take
        # the same (c, server_url, token, site_id) args as the dispatch below).
        handlers.update(OPERATION_HANDLERS)
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, server_url, token, site_id)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "signin": signin.get("timing_ms", {}).get("signin"),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Project handlers
    # ------------------------------------------------------------------
    async def _query_projects(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "GET", f"/sites/{site_id}/projects",
            params={"pageSize": c.page_size, "pageNumber": c.page_number},
            action_name="query_projects",
        )

    async def _create_project(self, c, server_url, token, site_id) -> Dict[str, Any]:
        project: Dict[str, Any] = {"name": c.name}
        if c.description:
            project["description"] = c.description
        if c.parent_project_id:
            project["parentProjectId"] = c.parent_project_id
        return await _tableau_request(
            server_url, token, "POST", f"/sites/{site_id}/projects",
            json_body={"project": project}, action_name="create_project",
        )

    async def _delete_project(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "DELETE", f"/sites/{site_id}/projects/{c.project_id}",
            action_name="delete_project",
        )

    # ------------------------------------------------------------------
    # Workbook handlers
    # ------------------------------------------------------------------
    async def _query_workbooks(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "GET", f"/sites/{site_id}/workbooks",
            params={
                "filter": c.filter,
                "sort": c.sort,
                "pageSize": c.page_size,
                "pageNumber": c.page_number,
            },
            action_name="query_workbooks",
        )

    async def _get_workbook(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "GET", f"/sites/{site_id}/workbooks/{c.workbook_id}",
            action_name="get_workbook",
        )

    async def _refresh_workbook(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "POST", f"/sites/{site_id}/workbooks/{c.workbook_id}/refresh",
            json_body={}, action_name="refresh_workbook",
        )

    async def _delete_workbook(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "DELETE", f"/sites/{site_id}/workbooks/{c.workbook_id}",
            action_name="delete_workbook",
        )

    # ------------------------------------------------------------------
    # View handlers
    # ------------------------------------------------------------------
    async def _query_views(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "GET", f"/sites/{site_id}/views",
            params={
                "filter": c.filter,
                "sort": c.sort,
                "pageSize": c.page_size,
                "pageNumber": c.page_number,
            },
            action_name="query_views",
        )

    async def _query_view_image(self, c, server_url, token, site_id) -> Dict[str, Any]:
        params = {"resolution": "high"} if c.high_resolution == "true" else None
        return await _tableau_request(
            server_url, token, "GET", f"/sites/{site_id}/views/{c.view_id}/image",
            params=params, action_name="query_view_image", raw_response=True,
        )

    async def _query_view_pdf(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "GET", f"/sites/{site_id}/views/{c.view_id}/pdf",
            action_name="query_view_pdf", raw_response=True,
        )

    async def _query_view_data(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "GET", f"/sites/{site_id}/views/{c.view_id}/data",
            action_name="query_view_data", raw_response=True,
        )

    # ------------------------------------------------------------------
    # Data source handlers
    # ------------------------------------------------------------------
    async def _query_datasources(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "GET", f"/sites/{site_id}/datasources",
            params={
                "filter": c.filter,
                "sort": c.sort,
                "pageSize": c.page_size,
                "pageNumber": c.page_number,
            },
            action_name="query_datasources",
        )

    async def _get_datasource(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "GET", f"/sites/{site_id}/datasources/{c.datasource_id}",
            action_name="get_datasource",
        )

    async def _refresh_datasource(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "POST", f"/sites/{site_id}/datasources/{c.datasource_id}/refresh",
            json_body={}, action_name="refresh_datasource",
        )

    async def _delete_datasource(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "DELETE", f"/sites/{site_id}/datasources/{c.datasource_id}",
            action_name="delete_datasource",
        )

    # ------------------------------------------------------------------
    # User & group handlers
    # ------------------------------------------------------------------
    async def _get_users(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "GET", f"/sites/{site_id}/users",
            params={
                "filter": c.filter,
                "pageSize": c.page_size,
                "pageNumber": c.page_number,
            },
            action_name="get_users",
        )

    async def _add_user(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "POST", f"/sites/{site_id}/users",
            json_body={"user": {"name": c.user_name, "siteRole": c.site_role}},
            action_name="add_user",
        )

    async def _query_groups(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "GET", f"/sites/{site_id}/groups",
            params={"pageSize": c.page_size, "pageNumber": c.page_number},
            action_name="query_groups",
        )

    async def _add_user_to_group(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "POST", f"/sites/{site_id}/groups/{c.group_id}/users",
            json_body={"user": {"id": c.user_id}}, action_name="add_user_to_group",
        )

    # ------------------------------------------------------------------
    # Webhook management handlers
    # ------------------------------------------------------------------
    async def _list_webhooks(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "GET", f"/sites/{site_id}/webhooks",
            action_name="list_webhooks",
        )

    async def _create_webhook(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "POST", f"/sites/{site_id}/webhooks",
            json_body={
                "webhook": {
                    "name": c.name,
                    "event": c.event,
                    "webhook-destination": {
                        "webhook-destination-http": {
                            "method": "POST",
                            "url": c.destination_url,
                        }
                    },
                }
            },
            action_name="create_webhook",
        )

    async def _test_webhook(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "GET", f"/sites/{site_id}/webhooks/{c.webhook_id}/test",
            action_name="test_webhook",
        )

    async def _delete_webhook(self, c, server_url, token, site_id) -> Dict[str, Any]:
        return await _tableau_request(
            server_url, token, "DELETE", f"/sites/{site_id}/webhooks/{c.webhook_id}",
            action_name="delete_webhook",
        )
