"""
LaunchDarkly feature management automation node.

Provides workflow integration with LaunchDarkly's REST management API (v2) for:
- Feature flags: list, get, create, update (toggle), delete, copy, status
- Projects: list, get, create, delete
- Environments: list, create, delete
- Segments: list, create, update, delete
- Webhooks: list, create, delete
- Account members: list, invite
- Audit log, metrics, custom roles, teams, approval requests, access tokens
- Webhook Trigger: fire the workflow on LaunchDarkly account activity

Authentication: API access token (personal/service token) in the `Authorization`
header WITHOUT a `Bearer` prefix. OAuth 2.0 authorization_code is also supported
by the provider but requires a partner-registered OAuth client (human follow-up).

API Base URL: https://app.launchdarkly.com/api/v2 (Commercial)
              https://app.eu.launchdarkly.com/api/v2 (EU)
              https://app.launchdarkly.us/api/v2 (Federal)
REST API version is pinned via the `LD-API-Version` header.
Documentation: https://launchdarkly.com/docs/api
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin

logger = logging.getLogger(__name__)


# ==========================================================================
# Shared REST helpers (formerly launchdarkly_common.py)
# ==========================================================================

LD_API_VERSION = "20240415"

# Regional base URLs keyed by the credential's `region` selector.
LD_API_BASES = {
    "commercial": "https://app.launchdarkly.com/api/v2",
    "eu": "https://app.eu.launchdarkly.com/api/v2",
    "federal": "https://app.launchdarkly.us/api/v2",
}

# Content-Type for semantic patches (flag toggling, segment/experiment/holdout
# instruction-based updates). Body shape: {"comment"?, "instructions": [...]}.
SEMANTIC_PATCH_CONTENT_TYPE = "application/json; domain-model=launchdarkly.semanticpatch"


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    """Split a comma-separated string into a trimmed list, or None if empty."""
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _base_url(region: Optional[str]) -> str:
    return LD_API_BASES.get((region or "commercial").lower(), LD_API_BASES["commercial"])


async def _ld_request(
    access_token: str,
    region: Optional[str],
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    content_type: str = "application/json",
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated LaunchDarkly v2 request and return a structured result.

    The Authorization header takes the raw token value (no Bearer prefix), and
    every request pins behavior via the LD-API-Version header.
    """
    url = f"{_base_url(region)}{endpoint}"
    headers = {
        "Authorization": access_token,
        "Content-Type": content_type,
        "LD-API-Version": LD_API_VERSION,
    }
    if isinstance(json_body, dict):
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
                    message = err.get("message") if isinstance(err, dict) else None
                    if not message:
                        message = err.get("error") if isinstance(err, dict) else None
                    if not message:
                        message = str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[LaunchDarklyNode] API error ({action_name}): {message}")
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
            logger.error(f"[LaunchDarklyNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ==========================================================================
# Operation registry: config classes + handlers for the full stable API
# surface (formerly launchdarkly_operations.py). OPERATION_CONFIGS is merged
# into the discriminated union below; OPERATION_HANDLERS into execute().
# ==========================================================================

# Inline "Create new <resource>" builder affordances: LaunchDarkly keys every
# resource by a string `key`, echoed back at data.key on create; matching picker
# fields declare the same resource type.
_CREATES_RESOURCE: Dict[str, tuple] = {
    "create_flag": ("launchdarkly_flag", "data.key"),
    "create_project": ("launchdarkly_project", "data.key"),
    "create_environment": ("launchdarkly_environment", "data.key"),
    "create_segment": ("launchdarkly_segment", "data.key"),
    "create_experiment": ("launchdarkly_experiment", "data.key"),
    "create_team": ("launchdarkly_team", "data.key"),
    "create_metric": ("launchdarkly_metric", "data.key"),
    "create_role": ("launchdarkly_custom_role", "data.key"),
    "create_holdout": ("launchdarkly_holdout", "data.key"),
}
_FIELD_RESOURCE_TYPE: Dict[str, str] = {
    "feature_flag_key": "launchdarkly_flag",
    "project_key": "launchdarkly_project",
    "environment_key": "launchdarkly_environment",
    "segment_key": "launchdarkly_segment",
    "experiment_key": "launchdarkly_experiment",
    "team_key": "launchdarkly_team",
    "metric_key": "launchdarkly_metric",
    "custom_role_key": "launchdarkly_custom_role",
    "holdout_key": "launchdarkly_holdout",
}


def _dyn(field_name: str, label: str, depends_on: Optional[str] = None) -> Dict[str, Any]:
    """Build an x-dynamic-options block (searchable dropdown + custom paste)."""
    opts: Dict[str, Any] = {
        "field_name": field_name,
        "placeholder": f"Select {label.lower()}...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": f"Or paste a {label.lower()} key" if field_name != "member_id" else "Or paste a member ID",
    }
    if depends_on:
        opts["depends_on"] = depends_on
    extra: Dict[str, Any] = {"x-dynamic-options": opts}
    rt = _FIELD_RESOURCE_TYPE.get(field_name)
    if rt:
        extra["x-resource-type"] = rt
    return extra


def _project_key_field(description: str = "The project") -> Any:
    """Standard project_key field with the searchable dynamic-options dropdown."""
    return Field(..., title="Project", description=description, json_schema_extra=_dyn("project_key", "a project"))


# Dependent/loose dropdown fields for the other listable resources. load_field_options
# in launchdarkly_node.py resolves each field_name (reading parent keys from context).
def _environment_key_field(required: bool = True, description: str = "The environment (pick one or paste a key)",
                           field_name: str = "environment_key", title: str = "Environment") -> Any:
    return Field(... if required else None, title=title, description=description,
                 json_schema_extra=_dyn(field_name, "an environment", depends_on="project_key"))


def _feature_flag_key_field(description: str = "The feature flag (pick one or paste a key)") -> Any:
    return Field(..., title="Feature Flag", description=description,
                 json_schema_extra=_dyn("feature_flag_key", "a flag", depends_on="project_key"))


def _segment_key_field(description: str = "The segment (pick one or paste a key)") -> Any:
    return Field(..., title="Segment", description=description,
                 json_schema_extra=_dyn("segment_key", "a segment", depends_on="environment_key"))


def _metric_key_field(description: str = "The metric (pick one or paste a key)") -> Any:
    return Field(..., title="Metric", description=description,
                 json_schema_extra=_dyn("metric_key", "a metric", depends_on="project_key"))


def _team_key_field(description: str = "The team (pick one or paste a key)") -> Any:
    return Field(..., title="Team", description=description, json_schema_extra=_dyn("team_key", "a team"))


def _role_key_field(description: str = "The custom role (pick one or paste a key)") -> Any:
    return Field(..., title="Custom Role", description=description, json_schema_extra=_dyn("custom_role_key", "a role"))


def _member_id_field(description: str = "The account member (pick one or paste an ID)") -> Any:
    return Field(..., title="Member", description=description, json_schema_extra=_dyn("member_id", "a member"))


def _repo_field(description: str = "The code-references repository (pick one or paste a name)") -> Any:
    return Field(..., title="Repository", description=description, json_schema_extra=_dyn("repo", "a repository"))


def _client_id_field(description: str = "The OAuth client (pick one or paste a client ID)") -> Any:
    return Field(..., title="OAuth Client", description=description, json_schema_extra=_dyn("client_id", "an OAuth client"))


def _experiment_key_field(description: str = "The experiment (pick one or paste a key)") -> Any:
    return Field(..., title="Experiment", description=description,
                 json_schema_extra=_dyn("experiment_key", "an experiment", depends_on="environment_key"))


def _holdout_key_field(description: str = "The holdout (pick one or paste a key)") -> Any:
    return Field(..., title="Holdout", description=description,
                 json_schema_extra=_dyn("holdout_key", "a holdout", depends_on="environment_key"))


# Populated below by per-category blocks. The main node imports these two.
OPERATION_CONFIGS: List[type] = []
OPERATION_HANDLERS: Dict[str, Any] = {}


# ============================================================================
# <generated per-category operation blocks are appended here>
# ============================================================================


# ============================================================================
# CATEGORY: Segments
# ============================================================================

class LaunchDarklyEvaluateSegmentMembershipsConfig(BaseModel):
    """List segment memberships for a context instance in an environment."""
    operation: Literal["evaluate_segment_memberships"] = Field(
        "evaluate_segment_memberships",
        json_schema_extra={"const": "evaluate_segment_memberships", "ui:hidden": True,
                           "x-category": "Segments", "x-is-trigger": False,
                           "x-display-name": "List Segment Memberships For Context Instance"},
        title="List Segment Memberships For Context Instance",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    body_json: Optional[str] = Field(None, title="Context Instance (JSON)",
        description="Raw JSON context instance to evaluate segment memberships for")


async def _evaluate_segment_memberships(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _ld_request(token, region, "POST",
                             f"/projects/{c.project_key}/environments/{c.environment_key}/segments/evaluate",
                             json_body=body, action_name="evaluate_segment_memberships")


class LaunchDarklyGetSegmentConfig(BaseModel):
    """Get a single segment."""
    operation: Literal["get_segment"] = Field(
        "get_segment",
        json_schema_extra={"const": "get_segment", "ui:hidden": True,
                           "x-category": "Segments", "x-is-trigger": False,
                           "x-display-name": "Get Segment"},
        title="Get Segment",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    segment_key: str = _segment_key_field()


async def _get_segment(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/segments/{c.project_key}/{c.environment_key}/{c.segment_key}",
                             action_name="get_segment")


class LaunchDarklyUpdateBigSegmentContextTargetsConfig(BaseModel):
    """Update context targets on a big segment."""
    operation: Literal["update_big_segment_context_targets"] = Field(
        "update_big_segment_context_targets",
        json_schema_extra={"const": "update_big_segment_context_targets", "ui:hidden": True,
                           "x-category": "Segments", "x-is-trigger": False,
                           "x-display-name": "Update Context Targets On Big Segment"},
        title="Update Context Targets On Big Segment",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    segment_key: str = _segment_key_field()
    included: Optional[str] = Field(None, title="Included Contexts",
        description="Comma-separated context keys to include")
    excluded: Optional[str] = Field(None, title="Excluded Contexts",
        description="Comma-separated context keys to exclude")
    included_remove: Optional[str] = Field(None, title="Remove From Included",
        description="Comma-separated context keys to remove from the included list")
    excluded_remove: Optional[str] = Field(None, title="Remove From Excluded",
        description="Comma-separated context keys to remove from the excluded list")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _update_big_segment_context_targets(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({
        "included": _comma_list(c.included),
        "excluded": _comma_list(c.excluded),
        "includedContexts": None,
    })
    if _comma_list(c.included_remove):
        body["includedRemove"] = _comma_list(c.included_remove)
    if _comma_list(c.excluded_remove):
        body["excludedRemove"] = _comma_list(c.excluded_remove)
    return await _ld_request(token, region, "POST",
                             f"/segments/{c.project_key}/{c.environment_key}/{c.segment_key}/contexts",
                             json_body=body, action_name="update_big_segment_context_targets")


class LaunchDarklyGetSegmentContextMembershipConfig(BaseModel):
    """Get big segment membership for a context."""
    operation: Literal["get_segment_context_membership"] = Field(
        "get_segment_context_membership",
        json_schema_extra={"const": "get_segment_context_membership", "ui:hidden": True,
                           "x-category": "Segments", "x-is-trigger": False,
                           "x-display-name": "Get Big Segment Membership For Context"},
        title="Get Big Segment Membership For Context",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    segment_key: str = _segment_key_field()
    context_key: str = Field(..., title="Context Key", description="The context key")


async def _get_segment_context_membership(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/segments/{c.project_key}/{c.environment_key}/{c.segment_key}/contexts/{c.context_key}",
                             action_name="get_segment_context_membership")


class LaunchDarklyCreateBigSegmentExportConfig(BaseModel):
    """Create a big segment export."""
    operation: Literal["create_big_segment_export"] = Field(
        "create_big_segment_export",
        json_schema_extra={"const": "create_big_segment_export", "ui:hidden": True,
                           "x-category": "Segments", "x-is-trigger": False,
                           "x-display-name": "Create Big Segment Export"},
        title="Create Big Segment Export",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    segment_key: str = _segment_key_field()


async def _create_big_segment_export(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "POST",
                             f"/segments/{c.project_key}/{c.environment_key}/{c.segment_key}/exports",
                             action_name="create_big_segment_export")


class LaunchDarklyGetBigSegmentExportConfig(BaseModel):
    """Get a big segment export."""
    operation: Literal["get_big_segment_export"] = Field(
        "get_big_segment_export",
        json_schema_extra={"const": "get_big_segment_export", "ui:hidden": True,
                           "x-category": "Segments", "x-is-trigger": False,
                           "x-display-name": "Get Big Segment Export"},
        title="Get Big Segment Export",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    segment_key: str = _segment_key_field()
    export_id: str = Field(..., title="Export ID", description="The big segment export ID")


async def _get_big_segment_export(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/segments/{c.project_key}/{c.environment_key}/{c.segment_key}/exports/{c.export_id}",
                             action_name="get_big_segment_export")


class LaunchDarklyCreateBigSegmentImportConfig(BaseModel):
    """Create a big segment import."""
    operation: Literal["create_big_segment_import"] = Field(
        "create_big_segment_import",
        json_schema_extra={"const": "create_big_segment_import", "ui:hidden": True,
                           "x-category": "Segments", "x-is-trigger": False,
                           "x-display-name": "Create Big Segment Import"},
        title="Create Big Segment Import",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    segment_key: str = _segment_key_field()
    body_json: Optional[str] = Field(None, title="Import Body (JSON)",
        description="Raw JSON body describing the import (mode, file reference, etc.)")


async def _create_big_segment_import(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _ld_request(token, region, "POST",
                             f"/segments/{c.project_key}/{c.environment_key}/{c.segment_key}/imports",
                             json_body=body, action_name="create_big_segment_import")


class LaunchDarklyGetBigSegmentImportConfig(BaseModel):
    """Get a big segment import."""
    operation: Literal["get_big_segment_import"] = Field(
        "get_big_segment_import",
        json_schema_extra={"const": "get_big_segment_import", "ui:hidden": True,
                           "x-category": "Segments", "x-is-trigger": False,
                           "x-display-name": "Get Big Segment Import"},
        title="Get Big Segment Import",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    segment_key: str = _segment_key_field()
    import_id: str = Field(..., title="Import ID", description="The big segment import ID")


async def _get_big_segment_import(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/segments/{c.project_key}/{c.environment_key}/{c.segment_key}/imports/{c.import_id}",
                             action_name="get_big_segment_import")


class LaunchDarklyUpdateBigSegmentUserTargetsConfig(BaseModel):
    """Update user context targets on a big segment."""
    operation: Literal["update_big_segment_user_targets"] = Field(
        "update_big_segment_user_targets",
        json_schema_extra={"const": "update_big_segment_user_targets", "ui:hidden": True,
                           "x-category": "Segments", "x-is-trigger": False,
                           "x-display-name": "Update User Context Targets On Big Segment"},
        title="Update User Context Targets On Big Segment",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    segment_key: str = _segment_key_field()
    included: Optional[str] = Field(None, title="Included Users",
        description="Comma-separated user keys to include")
    excluded: Optional[str] = Field(None, title="Excluded Users",
        description="Comma-separated user keys to exclude")
    included_remove: Optional[str] = Field(None, title="Remove From Included",
        description="Comma-separated user keys to remove from the included list")
    excluded_remove: Optional[str] = Field(None, title="Remove From Excluded",
        description="Comma-separated user keys to remove from the excluded list")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _update_big_segment_user_targets(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({
        "included": _comma_list(c.included),
        "excluded": _comma_list(c.excluded),
    })
    if _comma_list(c.included_remove):
        body["includedRemove"] = _comma_list(c.included_remove)
    if _comma_list(c.excluded_remove):
        body["excludedRemove"] = _comma_list(c.excluded_remove)
    return await _ld_request(token, region, "POST",
                             f"/segments/{c.project_key}/{c.environment_key}/{c.segment_key}/users",
                             json_body=body, action_name="update_big_segment_user_targets")


class LaunchDarklyGetSegmentUserMembershipConfig(BaseModel):
    """Get big segment membership for a user."""
    operation: Literal["get_segment_user_membership"] = Field(
        "get_segment_user_membership",
        json_schema_extra={"const": "get_segment_user_membership", "ui:hidden": True,
                           "x-category": "Segments", "x-is-trigger": False,
                           "x-display-name": "Get Big Segment Membership For User"},
        title="Get Big Segment Membership For User",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    segment_key: str = _segment_key_field()
    user_key: str = Field(..., title="User Key", description="The user key")


async def _get_segment_user_membership(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/segments/{c.project_key}/{c.environment_key}/{c.segment_key}/users/{c.user_key}",
                             action_name="get_segment_user_membership")


class LaunchDarklyGetSegmentExpiringTargetsConfig(BaseModel):
    """Get expiring targets for a segment."""
    operation: Literal["get_segment_expiring_targets"] = Field(
        "get_segment_expiring_targets",
        json_schema_extra={"const": "get_segment_expiring_targets", "ui:hidden": True,
                           "x-category": "Segments", "x-is-trigger": False,
                           "x-display-name": "Get Expiring Targets For Segment"},
        title="Get Expiring Targets For Segment",
    )
    project_key: str = _project_key_field("The project key")
    segment_key: str = _segment_key_field()
    environment_key: str = _environment_key_field()


async def _get_segment_expiring_targets(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/segments/{c.project_key}/{c.segment_key}/expiring-targets/{c.environment_key}",
                             action_name="get_segment_expiring_targets")


class LaunchDarklyUpdateSegmentExpiringTargetsConfig(BaseModel):
    """Update expiring targets for a segment via instructions."""
    operation: Literal["update_segment_expiring_targets"] = Field(
        "update_segment_expiring_targets",
        json_schema_extra={"const": "update_segment_expiring_targets", "ui:hidden": True,
                           "x-category": "Segments", "x-is-trigger": False,
                           "x-display-name": "Update Expiring Targets For Segment"},
        title="Update Expiring Targets For Segment",
    )
    project_key: str = _project_key_field("The project key")
    segment_key: str = _segment_key_field()
    environment_key: str = _environment_key_field()
    instructions_json: str = Field(..., title="Instructions (JSON array)",
        description='Instructions array, e.g. [{"kind":"addExpiringTarget","value":"user-key","targetType":"included","expirationDate":0}]')
    comment: Optional[str] = Field(None, title="Comment")


async def _update_segment_expiring_targets(c, token, region) -> Dict[str, Any]:
    body = {"comment": c.comment, "instructions": json.loads(c.instructions_json)}
    return await _ld_request(token, region, "PATCH",
                             f"/segments/{c.project_key}/{c.segment_key}/expiring-targets/{c.environment_key}",
                             json_body=body, action_name="update_segment_expiring_targets")


class LaunchDarklyGetSegmentExpiringUserTargetsConfig(BaseModel):
    """Get expiring user targets for a segment."""
    operation: Literal["get_segment_expiring_user_targets"] = Field(
        "get_segment_expiring_user_targets",
        json_schema_extra={"const": "get_segment_expiring_user_targets", "ui:hidden": True,
                           "x-category": "Segments", "x-is-trigger": False,
                           "x-display-name": "Get Expiring User Targets For Segment"},
        title="Get Expiring User Targets For Segment",
    )
    project_key: str = _project_key_field("The project key")
    segment_key: str = _segment_key_field()
    environment_key: str = _environment_key_field()


async def _get_segment_expiring_user_targets(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/segments/{c.project_key}/{c.segment_key}/expiring-user-targets/{c.environment_key}",
                             action_name="get_segment_expiring_user_targets")


class LaunchDarklyUpdateSegmentExpiringUserTargetsConfig(BaseModel):
    """Update expiring user targets for a segment via instructions."""
    operation: Literal["update_segment_expiring_user_targets"] = Field(
        "update_segment_expiring_user_targets",
        json_schema_extra={"const": "update_segment_expiring_user_targets", "ui:hidden": True,
                           "x-category": "Segments", "x-is-trigger": False,
                           "x-display-name": "Update Expiring User Targets For Segment"},
        title="Update Expiring User Targets For Segment",
    )
    project_key: str = _project_key_field("The project key")
    segment_key: str = _segment_key_field()
    environment_key: str = _environment_key_field()
    instructions_json: str = Field(..., title="Instructions (JSON array)",
        description='Instructions array, e.g. [{"kind":"addExpiringTarget","value":"user-key","targetType":"included","expirationDate":0}]')
    comment: Optional[str] = Field(None, title="Comment")


async def _update_segment_expiring_user_targets(c, token, region) -> Dict[str, Any]:
    body = {"comment": c.comment, "instructions": json.loads(c.instructions_json)}
    return await _ld_request(token, region, "PATCH",
                             f"/segments/{c.project_key}/{c.segment_key}/expiring-user-targets/{c.environment_key}",
                             json_body=body, action_name="update_segment_expiring_user_targets")


OPERATION_CONFIGS.extend([
    LaunchDarklyEvaluateSegmentMembershipsConfig,
    LaunchDarklyGetSegmentConfig,
    LaunchDarklyUpdateBigSegmentContextTargetsConfig,
    LaunchDarklyGetSegmentContextMembershipConfig,
    LaunchDarklyCreateBigSegmentExportConfig,
    LaunchDarklyGetBigSegmentExportConfig,
    LaunchDarklyCreateBigSegmentImportConfig,
    LaunchDarklyGetBigSegmentImportConfig,
    LaunchDarklyUpdateBigSegmentUserTargetsConfig,
    LaunchDarklyGetSegmentUserMembershipConfig,
    LaunchDarklyGetSegmentExpiringTargetsConfig,
    LaunchDarklyUpdateSegmentExpiringTargetsConfig,
    LaunchDarklyGetSegmentExpiringUserTargetsConfig,
    LaunchDarklyUpdateSegmentExpiringUserTargetsConfig,
])
OPERATION_HANDLERS.update({
    "evaluate_segment_memberships": _evaluate_segment_memberships,
    "get_segment": _get_segment,
    "update_big_segment_context_targets": _update_big_segment_context_targets,
    "get_segment_context_membership": _get_segment_context_membership,
    "create_big_segment_export": _create_big_segment_export,
    "get_big_segment_export": _get_big_segment_export,
    "create_big_segment_import": _create_big_segment_import,
    "get_big_segment_import": _get_big_segment_import,
    "update_big_segment_user_targets": _update_big_segment_user_targets,
    "get_segment_user_membership": _get_segment_user_membership,
    "get_segment_expiring_targets": _get_segment_expiring_targets,
    "update_segment_expiring_targets": _update_segment_expiring_targets,
    "get_segment_expiring_user_targets": _get_segment_expiring_user_targets,
    "update_segment_expiring_user_targets": _update_segment_expiring_user_targets,
})


# ============================================================================
# Feature flags category operations
# ============================================================================

class LaunchDarklyGetFlagStatusAcrossEnvironmentsConfig(BaseModel):
    """Get the status of a feature flag across all environments."""
    operation: Literal["get_flag_status_across_environments"] = Field(
        "get_flag_status_across_environments",
        json_schema_extra={"const": "get_flag_status_across_environments", "ui:hidden": True,
                           "x-category": "Feature flags", "x-is-trigger": False,
                           "x-display-name": "Get Flag Status Across Environments"},
        title="Get Flag Status Across Environments",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    env: Optional[str] = Field(None, title="Environment",
        description="Filter to a specific environment (comma-separated for multiple)")


async def _get_flag_status_across_environments(c, token, region) -> Dict[str, Any]:
    params = {"env": c.env}
    return await _ld_request(token, region, "GET",
                             f"/flag-status/{c.project_key}/{c.feature_flag_key}",
                             params=params, action_name="get_flag_status_across_environments")


class LaunchDarklyListFlagStatusesConfig(BaseModel):
    """List the statuses of all feature flags in an environment."""
    operation: Literal["list_flag_statuses"] = Field(
        "list_flag_statuses",
        json_schema_extra={"const": "list_flag_statuses", "ui:hidden": True,
                           "x-category": "Feature flags", "x-is-trigger": False,
                           "x-display-name": "List Feature Flag Statuses"},
        title="List Feature Flag Statuses",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()


async def _list_flag_statuses(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/flag-statuses/{c.project_key}/{c.environment_key}",
                             action_name="list_flag_statuses")


class LaunchDarklyGetExpiringContextTargetsConfig(BaseModel):
    """Get expiring context targets for a feature flag in an environment."""
    operation: Literal["get_expiring_context_targets"] = Field(
        "get_expiring_context_targets",
        json_schema_extra={"const": "get_expiring_context_targets", "ui:hidden": True,
                           "x-category": "Feature flags", "x-is-trigger": False,
                           "x-display-name": "Get Expiring Context Targets"},
        title="Get Expiring Context Targets",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    feature_flag_key: str = _feature_flag_key_field()


async def _get_expiring_context_targets(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/flags/{c.project_key}/{c.feature_flag_key}/expiring-targets/{c.environment_key}",
                             action_name="get_expiring_context_targets")


class LaunchDarklyUpdateExpiringContextTargetsConfig(BaseModel):
    """Update expiring context targets on a feature flag via semantic-patch instructions."""
    operation: Literal["update_expiring_context_targets"] = Field(
        "update_expiring_context_targets",
        json_schema_extra={"const": "update_expiring_context_targets", "ui:hidden": True,
                           "x-category": "Feature flags", "x-is-trigger": False,
                           "x-display-name": "Update Expiring Context Targets"},
        title="Update Expiring Context Targets",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    feature_flag_key: str = _feature_flag_key_field()
    instructions_json: str = Field(..., title="Instructions (JSON array)",
        description='Semantic-patch instructions, e.g. [{"kind":"addExpiringTarget","value":1686412800000,"variationId":"...","contextKey":"...","contextKind":"user"}]')
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment describing the change")


async def _update_expiring_context_targets(c, token, region) -> Dict[str, Any]:
    body = {"comment": c.comment, "instructions": json.loads(c.instructions_json)}
    return await _ld_request(token, region, "PATCH",
                             f"/flags/{c.project_key}/{c.feature_flag_key}/expiring-targets/{c.environment_key}",
                             json_body=body, content_type=SEMANTIC_PATCH_CONTENT_TYPE,
                             action_name="update_expiring_context_targets")


class LaunchDarklyGetExpiringUserTargetsConfig(BaseModel):
    """Get expiring user targets for a feature flag in an environment."""
    operation: Literal["get_expiring_user_targets"] = Field(
        "get_expiring_user_targets",
        json_schema_extra={"const": "get_expiring_user_targets", "ui:hidden": True,
                           "x-category": "Feature flags", "x-is-trigger": False,
                           "x-display-name": "Get Expiring User Targets"},
        title="Get Expiring User Targets",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    feature_flag_key: str = _feature_flag_key_field()


async def _get_expiring_user_targets(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/flags/{c.project_key}/{c.feature_flag_key}/expiring-user-targets/{c.environment_key}",
                             action_name="get_expiring_user_targets")


class LaunchDarklyUpdateExpiringUserTargetsConfig(BaseModel):
    """Update expiring user targets on a feature flag via semantic-patch instructions."""
    operation: Literal["update_expiring_user_targets"] = Field(
        "update_expiring_user_targets",
        json_schema_extra={"const": "update_expiring_user_targets", "ui:hidden": True,
                           "x-category": "Feature flags", "x-is-trigger": False,
                           "x-display-name": "Update Expiring User Targets"},
        title="Update Expiring User Targets",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    feature_flag_key: str = _feature_flag_key_field()
    instructions_json: str = Field(..., title="Instructions (JSON array)",
        description='Semantic-patch instructions, e.g. [{"kind":"addExpireUserTargetDate","userKey":"sandy","value":1686412800000,"variationId":"..."}]')
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment describing the change")


async def _update_expiring_user_targets(c, token, region) -> Dict[str, Any]:
    body = {"comment": c.comment, "instructions": json.loads(c.instructions_json)}
    return await _ld_request(token, region, "PATCH",
                             f"/flags/{c.project_key}/{c.feature_flag_key}/expiring-user-targets/{c.environment_key}",
                             json_body=body, content_type=SEMANTIC_PATCH_CONTENT_TYPE,
                             action_name="update_expiring_user_targets")


class LaunchDarklyGetMigrationSafetyIssuesConfig(BaseModel):
    """Get migration safety issues for a proposed set of semantic-patch instructions on a flag."""
    operation: Literal["get_migration_safety_issues"] = Field(
        "get_migration_safety_issues",
        json_schema_extra={"const": "get_migration_safety_issues", "ui:hidden": True,
                           "x-category": "Feature flags", "x-is-trigger": False,
                           "x-display-name": "Get Migration Safety Issues"},
        title="Get Migration Safety Issues",
    )
    project_key: str = _project_key_field("The project key")
    flag_key: str = Field(..., title="Flag Key", description="The feature flag key")
    environment_key: str = _environment_key_field()
    instructions_json: str = Field(..., title="Instructions (JSON array)",
        description='Semantic-patch instructions to evaluate for safety issues, e.g. [{"kind":"updateStages","stages":[...]}]')
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment describing the change")


async def _get_migration_safety_issues(c, token, region) -> Dict[str, Any]:
    body = {"comment": c.comment, "instructions": json.loads(c.instructions_json)}
    return await _ld_request(token, region, "POST",
                             f"/projects/{c.project_key}/flags/{c.flag_key}/environments/{c.environment_key}/migration-safety-issues",
                             json_body=body, content_type=SEMANTIC_PATCH_CONTENT_TYPE,
                             action_name="get_migration_safety_issues")


OPERATION_CONFIGS.extend([
    LaunchDarklyGetFlagStatusAcrossEnvironmentsConfig,
    LaunchDarklyListFlagStatusesConfig,
    LaunchDarklyGetExpiringContextTargetsConfig,
    LaunchDarklyUpdateExpiringContextTargetsConfig,
    LaunchDarklyGetExpiringUserTargetsConfig,
    LaunchDarklyUpdateExpiringUserTargetsConfig,
    LaunchDarklyGetMigrationSafetyIssuesConfig,
])
OPERATION_HANDLERS.update({
    "get_flag_status_across_environments": _get_flag_status_across_environments,
    "list_flag_statuses": _list_flag_statuses,
    "get_expiring_context_targets": _get_expiring_context_targets,
    "update_expiring_context_targets": _update_expiring_context_targets,
    "get_expiring_user_targets": _get_expiring_user_targets,
    "update_expiring_user_targets": _update_expiring_user_targets,
    "get_migration_safety_issues": _get_migration_safety_issues,
})


# ============================================================================
# APPROVALS category operations
# ============================================================================


class LaunchDarklyListApprovalRequestsConfig(BaseModel):
    """List approval requests in the account."""
    operation: Literal["list_approval_requests"] = Field(
        "list_approval_requests",
        json_schema_extra={"const": "list_approval_requests", "ui:hidden": True,
                           "x-category": "Approvals", "x-is-trigger": False,
                           "x-display-name": "List Approval Requests"},
        title="List Approval Requests",
    )
    filter: Optional[str] = Field(None, title="Filter",
        description="A comma-separated list of filters, e.g. resourceId:proj/env:flag")
    expand: Optional[str] = Field(None, title="Expand",
        description="Comma-separated fields to expand in the response")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    offset: Optional[str] = Field(None, title="Offset", description="Pagination offset")


async def _list_approval_requests(c, token, region) -> Dict[str, Any]:
    params = {"filter": c.filter, "expand": c.expand, "limit": c.limit, "offset": c.offset}
    return await _ld_request(token, region, "GET", "/approval-requests",
                             params=params, action_name="list_approval_requests")


class LaunchDarklyGetApprovalRequestConfig(BaseModel):
    """Get a single approval request."""
    operation: Literal["get_approval_request"] = Field(
        "get_approval_request",
        json_schema_extra={"const": "get_approval_request", "ui:hidden": True,
                           "x-category": "Approvals", "x-is-trigger": False,
                           "x-display-name": "Get Approval Request"},
        title="Get Approval Request",
    )
    id: str = Field(..., title="Approval Request ID", description="The approval request ID")
    expand: Optional[str] = Field(None, title="Expand",
        description="Comma-separated fields to expand in the response")


async def _get_approval_request(c, token, region) -> Dict[str, Any]:
    params = {"expand": c.expand}
    return await _ld_request(token, region, "GET", f"/approval-requests/{c.id}",
                             params=params, action_name="get_approval_request")


class LaunchDarklyDeleteApprovalRequestConfig(BaseModel):
    """Delete an approval request."""
    operation: Literal["delete_approval_request"] = Field(
        "delete_approval_request",
        json_schema_extra={"const": "delete_approval_request", "ui:hidden": True,
                           "x-category": "Approvals", "x-is-trigger": False,
                           "x-display-name": "Delete Approval Request"},
        title="Delete Approval Request",
    )
    id: str = Field(..., title="Approval Request ID", description="The approval request ID")


async def _delete_approval_request(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "DELETE", f"/approval-requests/{c.id}",
                             action_name="delete_approval_request")


class LaunchDarklyApplyApprovalRequestConfig(BaseModel):
    """Apply an approved approval request."""
    operation: Literal["apply_approval_request"] = Field(
        "apply_approval_request",
        json_schema_extra={"const": "apply_approval_request", "ui:hidden": True,
                           "x-category": "Approvals", "x-is-trigger": False,
                           "x-display-name": "Apply Approval Request"},
        title="Apply Approval Request",
    )
    id: str = Field(..., title="Approval Request ID", description="The approval request ID")
    comment: Optional[str] = Field(None, title="Comment",
        description="Optional comment about the approval request")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _apply_approval_request(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"comment": c.comment})
    return await _ld_request(token, region, "POST", f"/approval-requests/{c.id}/apply",
                             json_body=body, action_name="apply_approval_request")


class LaunchDarklyReviewApprovalRequestConfig(BaseModel):
    """Review (approve/decline) an approval request."""
    operation: Literal["review_approval_request"] = Field(
        "review_approval_request",
        json_schema_extra={"const": "review_approval_request", "ui:hidden": True,
                           "x-category": "Approvals", "x-is-trigger": False,
                           "x-display-name": "Review Approval Request"},
        title="Review Approval Request",
    )
    id: str = Field(..., title="Approval Request ID", description="The approval request ID")
    kind: Optional[str] = Field(None, title="Review Kind",
        description="The type of review for this approval request (e.g. approve, decline)")
    comment: Optional[str] = Field(None, title="Comment",
        description="Optional comment about the approval request")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _review_approval_request(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"kind": c.kind, "comment": c.comment})
    return await _ld_request(token, region, "POST", f"/approval-requests/{c.id}/reviews",
                             json_body=body, action_name="review_approval_request")


class LaunchDarklyListFlagApprovalRequestsConfig(BaseModel):
    """List approval requests for a feature flag in an environment."""
    operation: Literal["list_flag_approval_requests"] = Field(
        "list_flag_approval_requests",
        json_schema_extra={"const": "list_flag_approval_requests", "ui:hidden": True,
                           "x-category": "Approvals", "x-is-trigger": False,
                           "x-display-name": "List Flag Approval Requests"},
        title="List Flag Approval Requests",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()


async def _list_flag_approval_requests(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/approval-requests",
                             action_name="list_flag_approval_requests")


class LaunchDarklyCreateFlagApprovalRequestConfig(BaseModel):
    """Create an approval request for a feature flag in an environment."""
    operation: Literal["create_flag_approval_request"] = Field(
        "create_flag_approval_request",
        json_schema_extra={"const": "create_flag_approval_request", "ui:hidden": True,
                           "x-category": "Approvals", "x-is-trigger": False,
                           "x-display-name": "Create Flag Approval Request"},
        title="Create Flag Approval Request",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    description: str = Field(..., title="Description",
        description="A brief description of the changes you're requesting")
    instructions_json: str = Field(..., title="Instructions (JSON array)",
        description='Semantic-patch instructions to apply, e.g. [{"kind":"turnFlagOn"}]')
    comment: Optional[str] = Field(None, title="Comment",
        description="Optional comment describing the approval request")
    notify_member_ids: Optional[str] = Field(None, title="Notify Member IDs",
        description="Comma-separated member IDs to notify for review")
    notify_team_keys: Optional[str] = Field(None, title="Notify Team Keys",
        description="Comma-separated team keys whose members are notified for review")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _create_flag_approval_request(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"description": c.description, "instructions": json.loads(c.instructions_json),
                 "comment": c.comment, "notifyMemberIds": _comma_list(c.notify_member_ids),
                 "notifyTeamKeys": _comma_list(c.notify_team_keys)})
    return await _ld_request(token, region, "POST",
                             f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/approval-requests",
                             json_body=body, action_name="create_flag_approval_request")


class LaunchDarklyCreateFlagCopyApprovalRequestConfig(BaseModel):
    """Create an approval request to copy flag configurations across environments."""
    operation: Literal["create_flag_copy_approval_request"] = Field(
        "create_flag_copy_approval_request",
        json_schema_extra={"const": "create_flag_copy_approval_request", "ui:hidden": True,
                           "x-category": "Approvals", "x-is-trigger": False,
                           "x-display-name": "Create Flag Copy Approval Request"},
        title="Create Flag Copy Approval Request",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field(description="The target environment the configuration is copied into")
    description: str = Field(..., title="Description", description="A brief description of your changes")
    source_json: str = Field(..., title="Source (JSON)",
        description='The flag to copy from, as JSON, e.g. {"key":"env-key","version":1}')
    comment: Optional[str] = Field(None, title="Comment",
        description="Optional comment describing the approval request")
    notify_member_ids: Optional[str] = Field(None, title="Notify Member IDs",
        description="Comma-separated member IDs to notify for review")
    notify_team_keys: Optional[str] = Field(None, title="Notify Team Keys",
        description="Comma-separated team keys whose members are notified for review")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _create_flag_copy_approval_request(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"description": c.description, "source": json.loads(c.source_json),
                 "comment": c.comment, "notifyMemberIds": _comma_list(c.notify_member_ids),
                 "notifyTeamKeys": _comma_list(c.notify_team_keys)})
    return await _ld_request(token, region, "POST",
                             f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/approval-requests-flag-copy",
                             json_body=body, action_name="create_flag_copy_approval_request")


class LaunchDarklyGetFlagApprovalRequestConfig(BaseModel):
    """Get a single approval request for a feature flag in an environment."""
    operation: Literal["get_flag_approval_request"] = Field(
        "get_flag_approval_request",
        json_schema_extra={"const": "get_flag_approval_request", "ui:hidden": True,
                           "x-category": "Approvals", "x-is-trigger": False,
                           "x-display-name": "Get Flag Approval Request"},
        title="Get Flag Approval Request",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    id: str = Field(..., title="Approval Request ID", description="The approval request ID")


async def _get_flag_approval_request(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/approval-requests/{c.id}",
                             action_name="get_flag_approval_request")


class LaunchDarklyDeleteFlagApprovalRequestConfig(BaseModel):
    """Delete an approval request for a feature flag in an environment."""
    operation: Literal["delete_flag_approval_request"] = Field(
        "delete_flag_approval_request",
        json_schema_extra={"const": "delete_flag_approval_request", "ui:hidden": True,
                           "x-category": "Approvals", "x-is-trigger": False,
                           "x-display-name": "Delete Flag Approval Request"},
        title="Delete Flag Approval Request",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    id: str = Field(..., title="Approval Request ID", description="The approval request ID")


async def _delete_flag_approval_request(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "DELETE",
                             f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/approval-requests/{c.id}",
                             action_name="delete_flag_approval_request")


class LaunchDarklyApplyFlagApprovalRequestConfig(BaseModel):
    """Apply an approved approval request for a feature flag in an environment."""
    operation: Literal["apply_flag_approval_request"] = Field(
        "apply_flag_approval_request",
        json_schema_extra={"const": "apply_flag_approval_request", "ui:hidden": True,
                           "x-category": "Approvals", "x-is-trigger": False,
                           "x-display-name": "Apply Flag Approval Request"},
        title="Apply Flag Approval Request",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    id: str = Field(..., title="Approval Request ID", description="The approval request ID")
    comment: Optional[str] = Field(None, title="Comment",
        description="Optional comment about the approval request")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _apply_flag_approval_request(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"comment": c.comment})
    return await _ld_request(token, region, "POST",
                             f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/approval-requests/{c.id}/apply",
                             json_body=body, action_name="apply_flag_approval_request")


class LaunchDarklyReviewFlagApprovalRequestConfig(BaseModel):
    """Review (approve/decline) an approval request for a feature flag in an environment."""
    operation: Literal["review_flag_approval_request"] = Field(
        "review_flag_approval_request",
        json_schema_extra={"const": "review_flag_approval_request", "ui:hidden": True,
                           "x-category": "Approvals", "x-is-trigger": False,
                           "x-display-name": "Review Flag Approval Request"},
        title="Review Flag Approval Request",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    id: str = Field(..., title="Approval Request ID", description="The approval request ID")
    kind: Optional[str] = Field(None, title="Review Kind",
        description="The type of review for this approval request (e.g. approve, decline)")
    comment: Optional[str] = Field(None, title="Comment",
        description="Optional comment about the approval request")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _review_flag_approval_request(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"kind": c.kind, "comment": c.comment})
    return await _ld_request(token, region, "POST",
                             f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/approval-requests/{c.id}/reviews",
                             json_body=body, action_name="review_flag_approval_request")


OPERATION_CONFIGS.extend([
    LaunchDarklyListApprovalRequestsConfig,
    LaunchDarklyGetApprovalRequestConfig,
    LaunchDarklyDeleteApprovalRequestConfig,
    LaunchDarklyApplyApprovalRequestConfig,
    LaunchDarklyReviewApprovalRequestConfig,
    LaunchDarklyListFlagApprovalRequestsConfig,
    LaunchDarklyCreateFlagApprovalRequestConfig,
    LaunchDarklyCreateFlagCopyApprovalRequestConfig,
    LaunchDarklyGetFlagApprovalRequestConfig,
    LaunchDarklyDeleteFlagApprovalRequestConfig,
    LaunchDarklyApplyFlagApprovalRequestConfig,
    LaunchDarklyReviewFlagApprovalRequestConfig,
])
OPERATION_HANDLERS.update({
    "list_approval_requests": _list_approval_requests,
    "get_approval_request": _get_approval_request,
    "delete_approval_request": _delete_approval_request,
    "apply_approval_request": _apply_approval_request,
    "review_approval_request": _review_approval_request,
    "list_flag_approval_requests": _list_flag_approval_requests,
    "create_flag_approval_request": _create_flag_approval_request,
    "create_flag_copy_approval_request": _create_flag_copy_approval_request,
    "get_flag_approval_request": _get_flag_approval_request,
    "delete_flag_approval_request": _delete_flag_approval_request,
    "apply_flag_approval_request": _apply_flag_approval_request,
    "review_flag_approval_request": _review_flag_approval_request,
})

# ============================================================================
# Code references category operations
# ============================================================================


class LaunchDarklyListExtinctionsConfig(BaseModel):
    """List extinctions (removed flag code references)."""
    operation: Literal["list_extinctions"] = Field(
        "list_extinctions",
        json_schema_extra={"const": "list_extinctions", "ui:hidden": True,
                           "x-category": "Code references", "x-is-trigger": False,
                           "x-display-name": "List Extinctions"},
        title="List Extinctions",
    )
    repo_name: Optional[str] = Field(None, title="Repository Name", description="Filter by repository name")
    branch_name: Optional[str] = Field(None, title="Branch Name", description="Filter by branch name")
    proj_key: Optional[str] = Field(None, title="Project Key", description="Filter by project key")
    flag_key: Optional[str] = Field(None, title="Flag Key", description="Filter by flag key")
    from_time: Optional[str] = Field(None, title="From", description="Unix ms lower time bound")
    to_time: Optional[str] = Field(None, title="To", description="Unix ms upper time bound")


async def _list_extinctions(c, token, region) -> Dict[str, Any]:
    params = {"repoName": c.repo_name, "branchName": c.branch_name, "projKey": c.proj_key,
              "flagKey": c.flag_key, "from": c.from_time, "to": c.to_time}
    return await _ld_request(token, region, "GET", "/code-refs/extinctions",
                             params=params, action_name="list_extinctions")


class LaunchDarklyListRepositoriesConfig(BaseModel):
    """List code reference repositories."""
    operation: Literal["list_repositories"] = Field(
        "list_repositories",
        json_schema_extra={"const": "list_repositories", "ui:hidden": True,
                           "x-category": "Code references", "x-is-trigger": False,
                           "x-display-name": "List Repositories"},
        title="List Repositories",
    )
    with_branches: Optional[str] = Field(None, title="With Branches",
        description="Include branches when set to 'true'")
    with_references_for_default_branch: Optional[str] = Field(None, title="With References For Default Branch",
        description="Include code references for the default branch when set to 'true'")
    proj_key: Optional[str] = Field(None, title="Project Key", description="Filter by project key")
    flag_key: Optional[str] = Field(None, title="Flag Key", description="Filter by flag key")


async def _list_repositories(c, token, region) -> Dict[str, Any]:
    params = {"withBranches": c.with_branches,
              "withReferencesForDefaultBranch": c.with_references_for_default_branch,
              "projKey": c.proj_key, "flagKey": c.flag_key}
    return await _ld_request(token, region, "GET", "/code-refs/repositories",
                             params=params, action_name="list_repositories")


class LaunchDarklyCreateRepositoryConfig(BaseModel):
    """Create a code reference repository."""
    operation: Literal["create_repository"] = Field(
        "create_repository",
        json_schema_extra={"const": "create_repository", "ui:hidden": True,
                           "x-category": "Code references", "x-is-trigger": False,
                           "x-display-name": "Create Repository"},
        title="Create Repository",
    )
    name: str = Field(..., title="Name", description="Repository name (unique identifier)")
    source_link: Optional[str] = Field(None, title="Source Link", description="URL for the repository")
    commit_url_template: Optional[str] = Field(None, title="Commit URL Template",
        description="Template for constructing a commit URL")
    hunk_url_template: Optional[str] = Field(None, title="Hunk URL Template",
        description="Template for constructing a code hunk URL")
    default_branch: Optional[str] = Field(None, title="Default Branch",
        description="The repository's default branch")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _create_repository(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"name": c.name, "sourceLink": c.source_link,
                 "commitUrlTemplate": c.commit_url_template,
                 "hunkUrlTemplate": c.hunk_url_template, "defaultBranch": c.default_branch})
    return await _ld_request(token, region, "POST", "/code-refs/repositories",
                             json_body=body, action_name="create_repository")


class LaunchDarklyGetRepositoryConfig(BaseModel):
    """Get a code reference repository."""
    operation: Literal["get_repository"] = Field(
        "get_repository",
        json_schema_extra={"const": "get_repository", "ui:hidden": True,
                           "x-category": "Code references", "x-is-trigger": False,
                           "x-display-name": "Get Repository"},
        title="Get Repository",
    )
    repo: str = _repo_field()


async def _get_repository(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", f"/code-refs/repositories/{c.repo}",
                             action_name="get_repository")


class LaunchDarklyUpdateRepositoryConfig(BaseModel):
    """Update a code reference repository via JSON Patch."""
    operation: Literal["update_repository"] = Field(
        "update_repository",
        json_schema_extra={"const": "update_repository", "ui:hidden": True,
                           "x-category": "Code references", "x-is-trigger": False,
                           "x-display-name": "Update Repository"},
        title="Update Repository",
    )
    repo: str = _repo_field()
    patch_json: str = Field(..., title="Patch (JSON array)",
        description='JSON Patch array, e.g. [{"op":"replace","path":"/sourceLink","value":"https://..."}]')


async def _update_repository(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "PATCH", f"/code-refs/repositories/{c.repo}",
                             json_body=json.loads(c.patch_json), action_name="update_repository")


class LaunchDarklyDeleteRepositoryConfig(BaseModel):
    """Delete a code reference repository."""
    operation: Literal["delete_repository"] = Field(
        "delete_repository",
        json_schema_extra={"const": "delete_repository", "ui:hidden": True,
                           "x-category": "Code references", "x-is-trigger": False,
                           "x-display-name": "Delete Repository"},
        title="Delete Repository",
    )
    repo: str = _repo_field()


async def _delete_repository(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "DELETE", f"/code-refs/repositories/{c.repo}",
                             action_name="delete_repository")


class LaunchDarklyDeleteBranchesConfig(BaseModel):
    """Queue a task to delete branches from a repository."""
    operation: Literal["delete_branches"] = Field(
        "delete_branches",
        json_schema_extra={"const": "delete_branches", "ui:hidden": True,
                           "x-category": "Code references", "x-is-trigger": False,
                           "x-display-name": "Delete Branches"},
        title="Delete Branches",
    )
    repo: str = _repo_field()
    branches: Optional[str] = Field(None, title="Branches",
        description="Comma-separated branch names to delete")
    body_json: Optional[str] = Field(None, title="Body (JSON array)",
        description="Optional raw JSON array of branch names (overrides Branches if set)")


async def _delete_branches(c, token, region) -> Dict[str, Any]:
    body = json.loads(c.body_json) if c.body_json else _comma_list(c.branches)
    return await _ld_request(token, region, "POST",
                             f"/code-refs/repositories/{c.repo}/branch-delete-tasks",
                             json_body=body, action_name="delete_branches")


class LaunchDarklyListBranchesConfig(BaseModel):
    """List branches for a code reference repository."""
    operation: Literal["list_branches"] = Field(
        "list_branches",
        json_schema_extra={"const": "list_branches", "ui:hidden": True,
                           "x-category": "Code references", "x-is-trigger": False,
                           "x-display-name": "List Branches"},
        title="List Branches",
    )
    repo: str = _repo_field()


async def _list_branches(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/code-refs/repositories/{c.repo}/branches",
                             action_name="list_branches")


class LaunchDarklyGetBranchConfig(BaseModel):
    """Get a branch for a code reference repository."""
    operation: Literal["get_branch"] = Field(
        "get_branch",
        json_schema_extra={"const": "get_branch", "ui:hidden": True,
                           "x-category": "Code references", "x-is-trigger": False,
                           "x-display-name": "Get Branch"},
        title="Get Branch",
    )
    repo: str = _repo_field()
    branch: str = Field(..., title="Branch Name", description="The branch name")
    proj_key: Optional[str] = Field(None, title="Project Key", description="Filter by project key")
    flag_key: Optional[str] = Field(None, title="Flag Key", description="Filter by flag key")


async def _get_branch(c, token, region) -> Dict[str, Any]:
    params = {"projKey": c.proj_key, "flagKey": c.flag_key}
    return await _ld_request(token, region, "GET",
                             f"/code-refs/repositories/{c.repo}/branches/{c.branch}",
                             params=params, action_name="get_branch")


class LaunchDarklyUpsertBranchConfig(BaseModel):
    """Create or update a branch and its code references."""
    operation: Literal["upsert_branch"] = Field(
        "upsert_branch",
        json_schema_extra={"const": "upsert_branch", "ui:hidden": True,
                           "x-category": "Code references", "x-is-trigger": False,
                           "x-display-name": "Upsert Branch"},
        title="Upsert Branch",
    )
    repo: str = _repo_field()
    branch: str = Field(..., title="Branch Name", description="The branch name")
    body_json: str = Field(..., title="Body (JSON)",
        description='Branch payload JSON, e.g. {"name":"main","head":"sha","references":[...]}')


async def _upsert_branch(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "PUT",
                             f"/code-refs/repositories/{c.repo}/branches/{c.branch}",
                             json_body=json.loads(c.body_json), action_name="upsert_branch")


class LaunchDarklyCreateExtinctionConfig(BaseModel):
    """Create extinction events for a branch."""
    operation: Literal["create_extinction"] = Field(
        "create_extinction",
        json_schema_extra={"const": "create_extinction", "ui:hidden": True,
                           "x-category": "Code references", "x-is-trigger": False,
                           "x-display-name": "Create Extinction"},
        title="Create Extinction",
    )
    repo: str = _repo_field()
    branch: str = Field(..., title="Branch Name", description="The branch name")
    body_json: str = Field(..., title="Body (JSON array)",
        description='JSON array of extinction events, e.g. [{"revision":"sha","flagKey":"key","projKey":"key"}]')


async def _create_extinction(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "POST",
                             f"/code-refs/repositories/{c.repo}/branches/{c.branch}/extinction-events",
                             json_body=json.loads(c.body_json), action_name="create_extinction")


class LaunchDarklyGetCodeRefsStatisticsConfig(BaseModel):
    """Get links to code reference repositories for each project."""
    operation: Literal["get_code_refs_statistics"] = Field(
        "get_code_refs_statistics",
        json_schema_extra={"const": "get_code_refs_statistics", "ui:hidden": True,
                           "x-category": "Code references", "x-is-trigger": False,
                           "x-display-name": "Get Code References Statistics (Root)"},
        title="Get Code References Statistics (Root)",
    )


async def _get_code_refs_statistics(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", "/code-refs/statistics",
                             action_name="get_code_refs_statistics")


class LaunchDarklyGetProjectCodeRefsStatisticsConfig(BaseModel):
    """Get code references statistics for the flags in a project."""
    operation: Literal["get_project_code_refs_statistics"] = Field(
        "get_project_code_refs_statistics",
        json_schema_extra={"const": "get_project_code_refs_statistics", "ui:hidden": True,
                           "x-category": "Code references", "x-is-trigger": False,
                           "x-display-name": "Get Project Code References Statistics"},
        title="Get Project Code References Statistics",
    )
    project_key: str = _project_key_field("The project key")
    flag_key: Optional[str] = Field(None, title="Flag Key", description="Filter by flag key")


async def _get_project_code_refs_statistics(c, token, region) -> Dict[str, Any]:
    params = {"flagKey": c.flag_key}
    return await _ld_request(token, region, "GET", f"/code-refs/statistics/{c.project_key}",
                             params=params, action_name="get_project_code_refs_statistics")


OPERATION_CONFIGS.extend([
    LaunchDarklyListExtinctionsConfig,
    LaunchDarklyListRepositoriesConfig,
    LaunchDarklyCreateRepositoryConfig,
    LaunchDarklyGetRepositoryConfig,
    LaunchDarklyUpdateRepositoryConfig,
    LaunchDarklyDeleteRepositoryConfig,
    LaunchDarklyDeleteBranchesConfig,
    LaunchDarklyListBranchesConfig,
    LaunchDarklyGetBranchConfig,
    LaunchDarklyUpsertBranchConfig,
    LaunchDarklyCreateExtinctionConfig,
    LaunchDarklyGetCodeRefsStatisticsConfig,
    LaunchDarklyGetProjectCodeRefsStatisticsConfig,
])
OPERATION_HANDLERS.update({
    "list_extinctions": _list_extinctions,
    "list_repositories": _list_repositories,
    "create_repository": _create_repository,
    "get_repository": _get_repository,
    "update_repository": _update_repository,
    "delete_repository": _delete_repository,
    "delete_branches": _delete_branches,
    "list_branches": _list_branches,
    "get_branch": _get_branch,
    "upsert_branch": _upsert_branch,
    "create_extinction": _create_extinction,
    "get_code_refs_statistics": _get_code_refs_statistics,
    "get_project_code_refs_statistics": _get_project_code_refs_statistics,
})

# ============================================================================
# Data Export destinations
# ============================================================================

class LaunchDarklyListDestinationsConfig(BaseModel):
    """List all Data Export destinations across the account."""
    operation: Literal["list_destinations"] = Field(
        "list_destinations",
        json_schema_extra={"const": "list_destinations", "ui:hidden": True,
                           "x-category": "Data Export destinations", "x-is-trigger": False,
                           "x-display-name": "List Destinations"},
        title="List Destinations",
    )


async def _list_destinations(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", "/destinations", action_name="list_destinations")


class LaunchDarklyGenerateWarehouseKeyPairConfig(BaseModel):
    """Generate a Snowflake Data Export destination key pair."""
    operation: Literal["generate_warehouse_key_pair"] = Field(
        "generate_warehouse_key_pair",
        json_schema_extra={"const": "generate_warehouse_key_pair", "ui:hidden": True,
                           "x-category": "Data Export destinations", "x-is-trigger": False,
                           "x-display-name": "Generate Snowflake Destination Key Pair"},
        title="Generate Snowflake Destination Key Pair",
    )


async def _generate_warehouse_key_pair(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "POST",
                             "/destinations/generate-warehouse-destination-key-pair",
                             action_name="generate_warehouse_key_pair")


class LaunchDarklyGenerateTrustPolicyConfig(BaseModel):
    """Generate a trust policy for a Data Export destination in an environment."""
    operation: Literal["generate_destination_trust_policy"] = Field(
        "generate_destination_trust_policy",
        json_schema_extra={"const": "generate_destination_trust_policy", "ui:hidden": True,
                           "x-category": "Data Export destinations", "x-is-trigger": False,
                           "x-display-name": "Generate Trust Policy"},
        title="Generate Trust Policy",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()


async def _generate_destination_trust_policy(c, token, region) -> Dict[str, Any]:
    return await _ld_request(
        token, region, "POST",
        f"/destinations/projects/{c.project_key}/environments/{c.environment_key}/generate-trust-policy",
        action_name="generate_destination_trust_policy")


class LaunchDarklyGenerateEnvWarehouseKeyPairConfig(BaseModel):
    """Generate a Snowflake destination key pair for a specific project environment."""
    operation: Literal["generate_environment_warehouse_key_pair"] = Field(
        "generate_environment_warehouse_key_pair",
        json_schema_extra={"const": "generate_environment_warehouse_key_pair", "ui:hidden": True,
                           "x-category": "Data Export destinations", "x-is-trigger": False,
                           "x-display-name": "Generate Environment Snowflake Key Pair"},
        title="Generate Environment Snowflake Key Pair",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()


async def _generate_environment_warehouse_key_pair(c, token, region) -> Dict[str, Any]:
    return await _ld_request(
        token, region, "POST",
        f"/destinations/projects/{c.project_key}/environments/{c.environment_key}/generate-warehouse-destination-key-pair",
        action_name="generate_environment_warehouse_key_pair")


class LaunchDarklyCompleteDestinationSetupConfig(BaseModel):
    """Complete warehouse destination setup for a given destination kind."""
    operation: Literal["complete_destination_setup"] = Field(
        "complete_destination_setup",
        json_schema_extra={"const": "complete_destination_setup", "ui:hidden": True,
                           "x-category": "Data Export destinations", "x-is-trigger": False,
                           "x-display-name": "Complete Warehouse Destination Setup"},
        title="Complete Warehouse Destination Setup",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    kind: str = Field(..., title="Kind", description="The type of Data Export destination")
    public_key: Optional[str] = Field(None, title="Public Key", description="The public key to complete setup")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _complete_destination_setup(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.public_key is not None:
        body["publicKey"] = c.public_key
    return await _ld_request(
        token, region, "POST",
        f"/destinations/projects/{c.project_key}/environments/{c.environment_key}/kinds/{c.kind}/complete-setup",
        json_body=body, action_name="complete_destination_setup")


class LaunchDarklyGenerateDestinationSetupScriptConfig(BaseModel):
    """Generate a warehouse destination setup script for a given destination kind."""
    operation: Literal["generate_destination_setup_script"] = Field(
        "generate_destination_setup_script",
        json_schema_extra={"const": "generate_destination_setup_script", "ui:hidden": True,
                           "x-category": "Data Export destinations", "x-is-trigger": False,
                           "x-display-name": "Generate Warehouse Destination Setup Script"},
        title="Generate Warehouse Destination Setup Script",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    kind: str = Field(..., title="Kind", description="The type of Data Export destination")
    name: Optional[str] = Field(None, title="Name", description="The destination name")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields such as "
                    "snowflakeHostAddress, databaseName, warehouseName, roleName, schemaName, userName")


async def _generate_destination_setup_script(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None:
        body["name"] = c.name
    return await _ld_request(
        token, region, "POST",
        f"/destinations/projects/{c.project_key}/environments/{c.environment_key}/kinds/{c.kind}/setup",
        json_body=body, action_name="generate_destination_setup_script")


class LaunchDarklyCreateDestinationConfig(BaseModel):
    """Create a Data Export destination in an environment."""
    operation: Literal["create_destination"] = Field(
        "create_destination",
        json_schema_extra={"const": "create_destination", "ui:hidden": True,
                           "x-category": "Data Export destinations", "x-is-trigger": False,
                           "x-display-name": "Create Data Export Destination"},
        title="Create Data Export Destination",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    name: str = Field(..., title="Name", description="A human-readable name for your destination")
    kind: str = Field(..., title="Kind", description="The type of Data Export destination")
    on: Optional[str] = Field(None, title="On",
        description="Whether the export is on",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Config / Extra Body (JSON)",
        description="Raw JSON merged into the request body; use this to supply the 'config' object "
                    "with destination-specific configuration parameters")


async def _create_destination(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"name": c.name, "kind": c.kind})
    if c.on is not None:
        body["on"] = c.on == "true"
    return await _ld_request(
        token, region, "POST",
        f"/destinations/{c.project_key}/{c.environment_key}",
        json_body=body, action_name="create_destination")


class LaunchDarklyGetDestinationConfig(BaseModel):
    """Get a single Data Export destination."""
    operation: Literal["get_destination"] = Field(
        "get_destination",
        json_schema_extra={"const": "get_destination", "ui:hidden": True,
                           "x-category": "Data Export destinations", "x-is-trigger": False,
                           "x-display-name": "Get Destination"},
        title="Get Destination",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    id: str = Field(..., title="Destination ID", description="The Data Export destination ID")


async def _get_destination(c, token, region) -> Dict[str, Any]:
    return await _ld_request(
        token, region, "GET",
        f"/destinations/{c.project_key}/{c.environment_key}/{c.id}",
        action_name="get_destination")


class LaunchDarklyUpdateDestinationConfig(BaseModel):
    """Update a Data Export destination via a JSON Patch document."""
    operation: Literal["update_destination"] = Field(
        "update_destination",
        json_schema_extra={"const": "update_destination", "ui:hidden": True,
                           "x-category": "Data Export destinations", "x-is-trigger": False,
                           "x-display-name": "Update Data Export Destination"},
        title="Update Data Export Destination",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    id: str = Field(..., title="Destination ID", description="The Data Export destination ID")
    patch_json: str = Field(..., title="Patch (JSON array)",
        description='JSON Patch array, e.g. [{"op":"replace","path":"/on","value":true}]')


async def _update_destination(c, token, region) -> Dict[str, Any]:
    body = json.loads(c.patch_json)
    return await _ld_request(
        token, region, "PATCH",
        f"/destinations/{c.project_key}/{c.environment_key}/{c.id}",
        json_body=body, action_name="update_destination")


class LaunchDarklyDeleteDestinationConfig(BaseModel):
    """Delete a Data Export destination."""
    operation: Literal["delete_destination"] = Field(
        "delete_destination",
        json_schema_extra={"const": "delete_destination", "ui:hidden": True,
                           "x-category": "Data Export destinations", "x-is-trigger": False,
                           "x-display-name": "Delete Data Export Destination"},
        title="Delete Data Export Destination",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    id: str = Field(..., title="Destination ID", description="The Data Export destination ID")


async def _delete_destination(c, token, region) -> Dict[str, Any]:
    return await _ld_request(
        token, region, "DELETE",
        f"/destinations/{c.project_key}/{c.environment_key}/{c.id}",
        action_name="delete_destination")


OPERATION_CONFIGS.extend([
    LaunchDarklyListDestinationsConfig,
    LaunchDarklyGenerateWarehouseKeyPairConfig,
    LaunchDarklyGenerateTrustPolicyConfig,
    LaunchDarklyGenerateEnvWarehouseKeyPairConfig,
    LaunchDarklyCompleteDestinationSetupConfig,
    LaunchDarklyGenerateDestinationSetupScriptConfig,
    LaunchDarklyCreateDestinationConfig,
    LaunchDarklyGetDestinationConfig,
    LaunchDarklyUpdateDestinationConfig,
    LaunchDarklyDeleteDestinationConfig,
])
OPERATION_HANDLERS.update({
    "list_destinations": _list_destinations,
    "generate_warehouse_key_pair": _generate_warehouse_key_pair,
    "generate_destination_trust_policy": _generate_destination_trust_policy,
    "generate_environment_warehouse_key_pair": _generate_environment_warehouse_key_pair,
    "complete_destination_setup": _complete_destination_setup,
    "generate_destination_setup_script": _generate_destination_setup_script,
    "create_destination": _create_destination,
    "get_destination": _get_destination,
    "update_destination": _update_destination,
    "delete_destination": _delete_destination,
})

# ============================================================================
# LaunchDarkly — Contexts category operations
# ============================================================================


class LaunchDarklyGetContextKindsConfig(BaseModel):
    """Get all context kinds for a project."""
    operation: Literal["get_context_kinds"] = Field(
        "get_context_kinds",
        json_schema_extra={"const": "get_context_kinds", "ui:hidden": True,
                           "x-category": "Contexts", "x-is-trigger": False,
                           "x-display-name": "Get Context Kinds"},
        title="Get Context Kinds",
    )
    project_key: str = _project_key_field("The project key")


async def _get_context_kinds(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/projects/{c.project_key}/context-kinds",
                             action_name="get_context_kinds")


class LaunchDarklyUpsertContextKindConfig(BaseModel):
    """Create or update a context kind."""
    operation: Literal["upsert_context_kind"] = Field(
        "upsert_context_kind",
        json_schema_extra={"const": "upsert_context_kind", "ui:hidden": True,
                           "x-category": "Contexts", "x-is-trigger": False,
                           "x-display-name": "Create or Update Context Kind"},
        title="Create or Update Context Kind",
    )
    project_key: str = _project_key_field("The project key")
    key: str = Field(..., title="Context Kind Key", description="The context kind key")
    name: str = Field(..., title="Name", description="The context kind name")
    description: Optional[str] = Field(None, title="Description")
    hide_in_targeting: Optional[str] = Field(None, title="Hide In Targeting",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
        description="Whether the context kind is hidden in targeting")
    archived: Optional[str] = Field(None, title="Archived",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
        description="Whether the context kind is archived")
    version: Optional[str] = Field(None, title="Version", description="The context kind version")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _upsert_context_kind(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body["name"] = c.name
    if c.description is not None:
        body["description"] = c.description
    if c.hide_in_targeting is not None:
        body["hideInTargeting"] = c.hide_in_targeting == "true"
    if c.archived is not None:
        body["archived"] = c.archived == "true"
    if c.version is not None:
        body["version"] = int(c.version)
    return await _ld_request(token, region, "PUT",
                             f"/projects/{c.project_key}/context-kinds/{c.key}",
                             json_body=body, action_name="upsert_context_kind")


class LaunchDarklyGetContextAttributeNamesConfig(BaseModel):
    """Get context attribute names for an environment."""
    operation: Literal["get_context_attribute_names"] = Field(
        "get_context_attribute_names",
        json_schema_extra={"const": "get_context_attribute_names", "ui:hidden": True,
                           "x-category": "Contexts", "x-is-trigger": False,
                           "x-display-name": "Get Context Attribute Names"},
        title="Get Context Attribute Names",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    filter: Optional[str] = Field(None, title="Filter", description="A comma-separated list of filters")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")


async def _get_context_attribute_names(c, token, region) -> Dict[str, Any]:
    params = {"filter": c.filter, "limit": c.limit}
    return await _ld_request(token, region, "GET",
                             f"/projects/{c.project_key}/environments/{c.environment_key}/context-attributes",
                             params=params, action_name="get_context_attribute_names")


class LaunchDarklyGetContextAttributeValuesConfig(BaseModel):
    """Get context attribute values for a given attribute name."""
    operation: Literal["get_context_attribute_values"] = Field(
        "get_context_attribute_values",
        json_schema_extra={"const": "get_context_attribute_values", "ui:hidden": True,
                           "x-category": "Contexts", "x-is-trigger": False,
                           "x-display-name": "Get Context Attribute Values"},
        title="Get Context Attribute Values",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    attribute_name: str = Field(..., title="Attribute Name", description="The attribute name")
    filter: Optional[str] = Field(None, title="Filter", description="A comma-separated list of filters")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")


async def _get_context_attribute_values(c, token, region) -> Dict[str, Any]:
    params = {"filter": c.filter, "limit": c.limit}
    return await _ld_request(token, region, "GET",
                             f"/projects/{c.project_key}/environments/{c.environment_key}/context-attributes/{c.attribute_name}",
                             params=params, action_name="get_context_attribute_values")


class LaunchDarklySearchContextInstancesConfig(BaseModel):
    """Search for context instances in an environment."""
    operation: Literal["search_context_instances"] = Field(
        "search_context_instances",
        json_schema_extra={"const": "search_context_instances", "ui:hidden": True,
                           "x-category": "Contexts", "x-is-trigger": False,
                           "x-display-name": "Search Context Instances"},
        title="Search Context Instances",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    continuation_token: Optional[str] = Field(None, title="Continuation Token",
        description="Token for paginating through results")
    sort: Optional[str] = Field(None, title="Sort", description="Field to sort results by")
    filter: Optional[str] = Field(None, title="Filter", description="A comma-separated list of filters")
    include_total_count: Optional[str] = Field(None, title="Include Total Count",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
        description="Whether to include the total count in the response")
    body_json: Optional[str] = Field(None, title="Search Body (JSON)",
        description="Optional raw JSON request body (filter, sort, limit, continuationToken)")


async def _search_context_instances(c, token, region) -> Dict[str, Any]:
    params = {"limit": c.limit, "continuationToken": c.continuation_token,
              "sort": c.sort, "filter": c.filter, "includeTotalCount": c.include_total_count}
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _ld_request(token, region, "POST",
                             f"/projects/{c.project_key}/environments/{c.environment_key}/context-instances/search",
                             params=params, json_body=body, action_name="search_context_instances")


class LaunchDarklyGetContextInstanceConfig(BaseModel):
    """Get context instances by ID."""
    operation: Literal["get_context_instance"] = Field(
        "get_context_instance",
        json_schema_extra={"const": "get_context_instance", "ui:hidden": True,
                           "x-category": "Contexts", "x-is-trigger": False,
                           "x-display-name": "Get Context Instances"},
        title="Get Context Instances",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    id: str = Field(..., title="Context Instance ID", description="The context instance ID")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    continuation_token: Optional[str] = Field(None, title="Continuation Token",
        description="Token for paginating through results")
    sort: Optional[str] = Field(None, title="Sort", description="Field to sort results by")
    filter: Optional[str] = Field(None, title="Filter", description="A comma-separated list of filters")
    include_total_count: Optional[str] = Field(None, title="Include Total Count",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
        description="Whether to include the total count in the response")


async def _get_context_instance(c, token, region) -> Dict[str, Any]:
    params = {"limit": c.limit, "continuationToken": c.continuation_token,
              "sort": c.sort, "filter": c.filter, "includeTotalCount": c.include_total_count}
    return await _ld_request(token, region, "GET",
                             f"/projects/{c.project_key}/environments/{c.environment_key}/context-instances/{c.id}",
                             params=params, action_name="get_context_instance")


class LaunchDarklyDeleteContextInstanceConfig(BaseModel):
    """Delete context instances by ID."""
    operation: Literal["delete_context_instance"] = Field(
        "delete_context_instance",
        json_schema_extra={"const": "delete_context_instance", "ui:hidden": True,
                           "x-category": "Contexts", "x-is-trigger": False,
                           "x-display-name": "Delete Context Instances"},
        title="Delete Context Instances",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    id: str = Field(..., title="Context Instance ID", description="The context instance ID")


async def _delete_context_instance(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "DELETE",
                             f"/projects/{c.project_key}/environments/{c.environment_key}/context-instances/{c.id}",
                             action_name="delete_context_instance")


class LaunchDarklySearchContextsConfig(BaseModel):
    """Search for contexts in an environment."""
    operation: Literal["search_contexts"] = Field(
        "search_contexts",
        json_schema_extra={"const": "search_contexts", "ui:hidden": True,
                           "x-category": "Contexts", "x-is-trigger": False,
                           "x-display-name": "Search Contexts"},
        title="Search Contexts",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    continuation_token: Optional[str] = Field(None, title="Continuation Token",
        description="Token for paginating through results")
    sort: Optional[str] = Field(None, title="Sort", description="Field to sort results by")
    filter: Optional[str] = Field(None, title="Filter", description="A comma-separated list of filters")
    include_total_count: Optional[str] = Field(None, title="Include Total Count",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
        description="Whether to include the total count in the response")
    body_json: Optional[str] = Field(None, title="Search Body (JSON)",
        description="Optional raw JSON request body (filter, sort, limit, continuationToken)")


async def _search_contexts(c, token, region) -> Dict[str, Any]:
    params = {"limit": c.limit, "continuationToken": c.continuation_token,
              "sort": c.sort, "filter": c.filter, "includeTotalCount": c.include_total_count}
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _ld_request(token, region, "POST",
                             f"/projects/{c.project_key}/environments/{c.environment_key}/contexts/search",
                             params=params, json_body=body, action_name="search_contexts")


class LaunchDarklyGetContextConfig(BaseModel):
    """Get contexts by kind and key."""
    operation: Literal["get_context"] = Field(
        "get_context",
        json_schema_extra={"const": "get_context", "ui:hidden": True,
                           "x-category": "Contexts", "x-is-trigger": False,
                           "x-display-name": "Get Contexts"},
        title="Get Contexts",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    kind: str = Field(..., title="Context Kind", description="The context kind")
    key: str = Field(..., title="Context Key", description="The context key")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    continuation_token: Optional[str] = Field(None, title="Continuation Token",
        description="Token for paginating through results")
    sort: Optional[str] = Field(None, title="Sort", description="Field to sort results by")
    filter: Optional[str] = Field(None, title="Filter", description="A comma-separated list of filters")
    include_total_count: Optional[str] = Field(None, title="Include Total Count",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
        description="Whether to include the total count in the response")


async def _get_context(c, token, region) -> Dict[str, Any]:
    params = {"limit": c.limit, "continuationToken": c.continuation_token,
              "sort": c.sort, "filter": c.filter, "includeTotalCount": c.include_total_count}
    return await _ld_request(token, region, "GET",
                             f"/projects/{c.project_key}/environments/{c.environment_key}/contexts/{c.kind}/{c.key}",
                             params=params, action_name="get_context")


class LaunchDarklyEvaluateContextInstanceConfig(BaseModel):
    """Evaluate all flags for a given context instance."""
    operation: Literal["evaluate_context_instance"] = Field(
        "evaluate_context_instance",
        json_schema_extra={"const": "evaluate_context_instance", "ui:hidden": True,
                           "x-category": "Contexts", "x-is-trigger": False,
                           "x-display-name": "Evaluate Flags For Context Instance"},
        title="Evaluate Flags For Context Instance",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    offset: Optional[str] = Field(None, title="Offset", description="Pagination offset")
    sort: Optional[str] = Field(None, title="Sort", description="Field to sort results by")
    filter: Optional[str] = Field(None, title="Filter", description="A comma-separated list of filters")
    body_json: Optional[str] = Field(None, title="Context Instance (JSON)",
        description="The context instance to evaluate, as a JSON object")


async def _evaluate_context_instance(c, token, region) -> Dict[str, Any]:
    params = {"limit": c.limit, "offset": c.offset, "sort": c.sort, "filter": c.filter}
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _ld_request(token, region, "POST",
                             f"/projects/{c.project_key}/environments/{c.environment_key}/flags/evaluate",
                             params=params, json_body=body, action_name="evaluate_context_instance")


OPERATION_CONFIGS.extend([
    LaunchDarklyGetContextKindsConfig,
    LaunchDarklyUpsertContextKindConfig,
    LaunchDarklyGetContextAttributeNamesConfig,
    LaunchDarklyGetContextAttributeValuesConfig,
    LaunchDarklySearchContextInstancesConfig,
    LaunchDarklyGetContextInstanceConfig,
    LaunchDarklyDeleteContextInstanceConfig,
    LaunchDarklySearchContextsConfig,
    LaunchDarklyGetContextConfig,
    LaunchDarklyEvaluateContextInstanceConfig,
])
OPERATION_HANDLERS.update({
    "get_context_kinds": _get_context_kinds,
    "upsert_context_kind": _upsert_context_kind,
    "get_context_attribute_names": _get_context_attribute_names,
    "get_context_attribute_values": _get_context_attribute_values,
    "search_context_instances": _search_context_instances,
    "get_context_instance": _get_context_instance,
    "delete_context_instance": _delete_context_instance,
    "search_contexts": _search_contexts,
    "get_context": _get_context,
    "evaluate_context_instance": _evaluate_context_instance,
})

class LaunchDarklyUpdateProjectConfig(BaseModel):
    """Update a project via a JSON Patch document."""
    operation: Literal["update_project"] = Field(
        "update_project",
        json_schema_extra={"const": "update_project", "ui:hidden": True,
                           "x-category": "Projects", "x-is-trigger": False,
                           "x-display-name": "Update Project"},
        title="Update Project",
    )
    project_key: str = _project_key_field("The project to update")
    patch_json: str = Field(..., title="Patch (JSON array)",
        description='JSON Patch array, e.g. [{"op":"replace","path":"/name","value":"New Name"}]')


async def _update_project(c, token, region) -> Dict[str, Any]:
    body = json.loads(c.patch_json)
    return await _ld_request(token, region, "PATCH", f"/projects/{c.project_key}",
                             json_body=body, action_name="update_project")


class LaunchDarklyGetFlagDefaultsConfig(BaseModel):
    """Get the flag defaults for a project."""
    operation: Literal["get_flag_defaults"] = Field(
        "get_flag_defaults",
        json_schema_extra={"const": "get_flag_defaults", "ui:hidden": True,
                           "x-category": "Projects", "x-is-trigger": False,
                           "x-display-name": "Get Flag Defaults"},
        title="Get Flag Defaults",
    )
    project_key: str = _project_key_field("The project whose flag defaults to retrieve")


async def _get_flag_defaults(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", f"/projects/{c.project_key}/flag-defaults",
                             action_name="get_flag_defaults")


class LaunchDarklyUpdateFlagDefaultsConfig(BaseModel):
    """Update the flag defaults for a project via a JSON Patch document."""
    operation: Literal["update_flag_defaults"] = Field(
        "update_flag_defaults",
        json_schema_extra={"const": "update_flag_defaults", "ui:hidden": True,
                           "x-category": "Projects", "x-is-trigger": False,
                           "x-display-name": "Update Flag Defaults"},
        title="Update Flag Defaults",
    )
    project_key: str = _project_key_field("The project whose flag defaults to update")
    patch_json: str = Field(..., title="Patch (JSON array)",
        description='JSON Patch array, e.g. [{"op":"replace","path":"/temporary","value":true}]')


async def _update_flag_defaults(c, token, region) -> Dict[str, Any]:
    body = json.loads(c.patch_json)
    return await _ld_request(token, region, "PATCH", f"/projects/{c.project_key}/flag-defaults",
                             json_body=body, action_name="update_flag_defaults")


class LaunchDarklyUpsertFlagDefaultsConfig(BaseModel):
    """Create or update (replace) the flag defaults for a project."""
    operation: Literal["upsert_flag_defaults"] = Field(
        "upsert_flag_defaults",
        json_schema_extra={"const": "upsert_flag_defaults", "ui:hidden": True,
                           "x-category": "Projects", "x-is-trigger": False,
                           "x-display-name": "Upsert Flag Defaults"},
        title="Upsert Flag Defaults",
    )
    project_key: str = _project_key_field("The project whose flag defaults to create or replace")
    body_json: str = Field(..., title="Flag Defaults Payload (JSON)",
        description="Full UpsertFlagDefaultsPayload JSON object with the flag default settings")


async def _upsert_flag_defaults(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json)
    return await _ld_request(token, region, "PUT", f"/projects/{c.project_key}/flag-defaults",
                             json_body=body, action_name="upsert_flag_defaults")


OPERATION_CONFIGS.extend([
    LaunchDarklyUpdateProjectConfig,
    LaunchDarklyGetFlagDefaultsConfig,
    LaunchDarklyUpdateFlagDefaultsConfig,
    LaunchDarklyUpsertFlagDefaultsConfig,
])
OPERATION_HANDLERS.update({
    "update_project": _update_project,
    "get_flag_defaults": _get_flag_defaults,
    "update_flag_defaults": _update_flag_defaults,
    "upsert_flag_defaults": _upsert_flag_defaults,
})


# ============================================================================
# Experiments category operations
# ============================================================================


class LaunchDarklyListExperimentsConfig(BaseModel):
    """Get experiments in an environment."""
    operation: Literal["list_experiments"] = Field(
        "list_experiments",
        json_schema_extra={"const": "list_experiments", "ui:hidden": True,
                           "x-category": "Experiments", "x-is-trigger": False,
                           "x-display-name": "List Experiments"},
        title="List Experiments",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    limit: Optional[str] = Field(None, title="Limit", description="Max number of experiments to return")
    offset: Optional[str] = Field(None, title="Offset", description="Pagination offset")
    filter: Optional[str] = Field(None, title="Filter", description="Filter experiments by attributes")
    expand: Optional[str] = Field(None, title="Expand", description="Comma-separated fields to expand")
    lifecycle_state: Optional[str] = Field(None, title="Lifecycle State",
        description="Filter by lifecycle state (e.g. active, archived)")


async def _list_experiments(c, token, region) -> Dict[str, Any]:
    params = {"limit": c.limit, "offset": c.offset, "filter": c.filter,
              "expand": c.expand, "lifecycleState": c.lifecycle_state}
    return await _ld_request(token, region, "GET",
        f"/projects/{c.project_key}/environments/{c.environment_key}/experiments",
        params=params, action_name="list_experiments")


class LaunchDarklyCreateExperimentConfig(BaseModel):
    """Create an experiment in an environment."""
    operation: Literal["create_experiment"] = Field(
        "create_experiment",
        json_schema_extra={"const": "create_experiment", "x-creates-resource": True, "x-resource-type": "launchdarkly_experiment", "x-resource-id-path": "data.key", "ui:hidden": True,
                           "x-category": "Experiments", "x-is-trigger": False,
                           "x-display-name": "Create Experiment"},
        title="Create Experiment",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    name: str = Field(..., title="Name", description="Experiment name")
    key: str = Field(..., title="Key", description="Experiment key")
    description: Optional[str] = Field(None, title="Description", description="Experiment description")
    maintainer_id: Optional[str] = Field(None, title="Maintainer ID", description="Member ID of the maintainer")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body (e.g. iteration, metrics, treatments)")


async def _create_experiment(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"name": c.name, "key": c.key, "description": c.description,
                 "maintainerId": c.maintainer_id})
    return await _ld_request(token, region, "POST",
        f"/projects/{c.project_key}/environments/{c.environment_key}/experiments",
        json_body=body, action_name="create_experiment")


class LaunchDarklyGetExperimentConfig(BaseModel):
    """Get a single experiment."""
    operation: Literal["get_experiment"] = Field(
        "get_experiment",
        json_schema_extra={"const": "get_experiment", "ui:hidden": True,
                           "x-category": "Experiments", "x-is-trigger": False,
                           "x-display-name": "Get Experiment"},
        title="Get Experiment",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    experiment_key: str = _experiment_key_field()
    expand: Optional[str] = Field(None, title="Expand", description="Comma-separated fields to expand")


async def _get_experiment(c, token, region) -> Dict[str, Any]:
    params = {"expand": c.expand}
    return await _ld_request(token, region, "GET",
        f"/projects/{c.project_key}/environments/{c.environment_key}/experiments/{c.experiment_key}",
        params=params, action_name="get_experiment")


class LaunchDarklyUpdateExperimentConfig(BaseModel):
    """Update an experiment via semantic-patch instructions."""
    operation: Literal["update_experiment"] = Field(
        "update_experiment",
        json_schema_extra={"const": "update_experiment", "ui:hidden": True,
                           "x-category": "Experiments", "x-is-trigger": False,
                           "x-display-name": "Update Experiment"},
        title="Update Experiment",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    experiment_key: str = _experiment_key_field()
    instructions_json: str = Field(..., title="Instructions (JSON array)",
        description='Semantic-patch instructions, e.g. [{"kind":"stopIteration"}]')
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment for the update")


async def _update_experiment(c, token, region) -> Dict[str, Any]:
    body = {"comment": c.comment, "instructions": json.loads(c.instructions_json)}
    return await _ld_request(token, region, "PATCH",
        f"/projects/{c.project_key}/environments/{c.environment_key}/experiments/{c.experiment_key}",
        json_body=body, content_type=SEMANTIC_PATCH_CONTENT_TYPE,
        action_name="update_experiment")


class LaunchDarklyCreateExperimentIterationConfig(BaseModel):
    """Create an iteration for an experiment."""
    operation: Literal["create_experiment_iteration"] = Field(
        "create_experiment_iteration",
        json_schema_extra={"const": "create_experiment_iteration", "ui:hidden": True,
                           "x-category": "Experiments", "x-is-trigger": False,
                           "x-display-name": "Create Experiment Iteration"},
        title="Create Experiment Iteration",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    experiment_key: str = _experiment_key_field()
    body_json: Optional[str] = Field(None, title="Iteration Body (JSON)",
        description="Raw JSON for the iteration (hypothesis, metrics, treatments, flags, etc.)")


async def _create_experiment_iteration(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _ld_request(token, region, "POST",
        f"/projects/{c.project_key}/environments/{c.environment_key}/experiments/{c.experiment_key}/iterations",
        json_body=body, action_name="create_experiment_iteration")


class LaunchDarklyGetExperimentationSettingsConfig(BaseModel):
    """Get experimentation settings for a project."""
    operation: Literal["get_experimentation_settings"] = Field(
        "get_experimentation_settings",
        json_schema_extra={"const": "get_experimentation_settings", "ui:hidden": True,
                           "x-category": "Experiments", "x-is-trigger": False,
                           "x-display-name": "Get Experimentation Settings"},
        title="Get Experimentation Settings",
    )
    project_key: str = _project_key_field("The project key")


async def _get_experimentation_settings(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
        f"/projects/{c.project_key}/experimentation-settings",
        action_name="get_experimentation_settings")


class LaunchDarklyUpdateExperimentationSettingsConfig(BaseModel):
    """Update experimentation (randomization) settings for a project."""
    operation: Literal["update_experimentation_settings"] = Field(
        "update_experimentation_settings",
        json_schema_extra={"const": "update_experimentation_settings", "ui:hidden": True,
                           "x-category": "Experiments", "x-is-trigger": False,
                           "x-display-name": "Update Experimentation Settings"},
        title="Update Experimentation Settings",
    )
    project_key: str = _project_key_field("The project key")
    body_json: Optional[str] = Field(None, title="Settings Body (JSON)",
        description="Raw JSON for randomization settings (e.g. randomizationUnits)")


async def _update_experimentation_settings(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    return await _ld_request(token, region, "PUT",
        f"/projects/{c.project_key}/experimentation-settings",
        json_body=body, action_name="update_experimentation_settings")


class LaunchDarklyListProjectExperimentsConfig(BaseModel):
    """Get experiments across all environments in a project."""
    operation: Literal["list_project_experiments"] = Field(
        "list_project_experiments",
        json_schema_extra={"const": "list_project_experiments", "ui:hidden": True,
                           "x-category": "Experiments", "x-is-trigger": False,
                           "x-display-name": "List Project Experiments"},
        title="List Project Experiments",
    )
    project_key: str = _project_key_field("The project key")
    limit: Optional[str] = Field(None, title="Limit", description="Max number of experiments to return")
    offset: Optional[str] = Field(None, title="Offset", description="Pagination offset")
    filter: Optional[str] = Field(None, title="Filter", description="Filter experiments by attributes")
    expand: Optional[str] = Field(None, title="Expand", description="Comma-separated fields to expand")
    lifecycle_state: Optional[str] = Field(None, title="Lifecycle State",
        description="Filter by lifecycle state (e.g. active, archived)")


async def _list_project_experiments(c, token, region) -> Dict[str, Any]:
    params = {"limit": c.limit, "offset": c.offset, "filter": c.filter,
              "expand": c.expand, "lifecycleState": c.lifecycle_state}
    return await _ld_request(token, region, "GET",
        f"/projects/{c.project_key}/experiments",
        params=params, action_name="list_project_experiments")


OPERATION_CONFIGS.extend([
    LaunchDarklyListExperimentsConfig,
    LaunchDarklyCreateExperimentConfig,
    LaunchDarklyGetExperimentConfig,
    LaunchDarklyUpdateExperimentConfig,
    LaunchDarklyCreateExperimentIterationConfig,
    LaunchDarklyGetExperimentationSettingsConfig,
    LaunchDarklyUpdateExperimentationSettingsConfig,
    LaunchDarklyListProjectExperimentsConfig,
])
OPERATION_HANDLERS.update({
    "list_experiments": _list_experiments,
    "create_experiment": _create_experiment,
    "get_experiment": _get_experiment,
    "update_experiment": _update_experiment,
    "create_experiment_iteration": _create_experiment_iteration,
    "get_experimentation_settings": _get_experimentation_settings,
    "update_experimentation_settings": _update_experimentation_settings,
    "list_project_experiments": _list_project_experiments,
})


class LaunchDarklyCreateTeamConfig(BaseModel):
    """Create a team."""
    operation: Literal["create_team"] = Field(
        "create_team",
        json_schema_extra={"const": "create_team", "x-creates-resource": True, "x-resource-type": "launchdarkly_team", "x-resource-id-path": "data.key", "ui:hidden": True,
                           "x-category": "Teams", "x-is-trigger": False,
                           "x-display-name": "Create Team"},
        title="Create Team",
    )
    name: str = Field(..., title="Name", description="A human-friendly name for the team")
    key: str = Field(..., title="Key", description="A unique key used to reference the team")
    description: Optional[str] = Field(None, title="Description", description="A description of the team")
    member_ids: Optional[str] = Field(None, title="Member IDs",
        description="Comma-separated list of member IDs to add to the team")
    custom_role_keys: Optional[str] = Field(None, title="Custom Role Keys",
        description="Comma-separated list of custom role keys to assign to the team")
    expand: Optional[str] = Field(None, title="Expand",
        description="Comma-separated fields to expand in the response")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _create_team(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"name": c.name, "key": c.key, "description": c.description,
                 "memberIDs": _comma_list(c.member_ids),
                 "customRoleKeys": _comma_list(c.custom_role_keys)})
    return await _ld_request(token, region, "POST", "/teams", params={"expand": c.expand},
                             json_body=body, action_name="create_team")


class LaunchDarklyGetTeamConfig(BaseModel):
    """Get a single team by key."""
    operation: Literal["get_team"] = Field(
        "get_team",
        json_schema_extra={"const": "get_team", "ui:hidden": True,
                           "x-category": "Teams", "x-is-trigger": False,
                           "x-display-name": "Get Team"},
        title="Get Team",
    )
    team_key: str = _team_key_field()
    expand: Optional[str] = Field(None, title="Expand",
        description="Comma-separated fields to expand in the response")


async def _get_team(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", f"/teams/{c.team_key}",
                             params={"expand": c.expand}, action_name="get_team")


class LaunchDarklyUpdateTeamConfig(BaseModel):
    """Update a team via semantic-patch instructions."""
    operation: Literal["update_team"] = Field(
        "update_team",
        json_schema_extra={"const": "update_team", "ui:hidden": True,
                           "x-category": "Teams", "x-is-trigger": False,
                           "x-display-name": "Update Team"},
        title="Update Team",
    )
    team_key: str = _team_key_field("The team to update")
    instructions_json: str = Field(..., title="Instructions (JSON array)",
        description='Semantic-patch instructions, e.g. [{"kind":"addMembers","memberIDs":["id"]}]')
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment describing the update")
    expand: Optional[str] = Field(None, title="Expand",
        description="Comma-separated fields to expand in the response")


async def _update_team(c, token, region) -> Dict[str, Any]:
    body = {"comment": c.comment, "instructions": json.loads(c.instructions_json)}
    return await _ld_request(token, region, "PATCH", f"/teams/{c.team_key}",
                             params={"expand": c.expand}, json_body=body,
                             content_type=SEMANTIC_PATCH_CONTENT_TYPE, action_name="update_team")


class LaunchDarklyDeleteTeamConfig(BaseModel):
    """Delete a team."""
    operation: Literal["delete_team"] = Field(
        "delete_team",
        json_schema_extra={"const": "delete_team", "ui:hidden": True,
                           "x-category": "Teams", "x-is-trigger": False,
                           "x-display-name": "Delete Team"},
        title="Delete Team",
    )
    team_key: str = _team_key_field("The team to delete")


async def _delete_team(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "DELETE", f"/teams/{c.team_key}", action_name="delete_team")


class LaunchDarklyListTeamMaintainersConfig(BaseModel):
    """Get the maintainers of a team."""
    operation: Literal["list_team_maintainers"] = Field(
        "list_team_maintainers",
        json_schema_extra={"const": "list_team_maintainers", "ui:hidden": True,
                           "x-category": "Teams", "x-is-trigger": False,
                           "x-display-name": "List Team Maintainers"},
        title="List Team Maintainers",
    )
    team_key: str = _team_key_field()
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    offset: Optional[str] = Field(None, title="Offset", description="Pagination offset")


async def _list_team_maintainers(c, token, region) -> Dict[str, Any]:
    params = {"limit": c.limit, "offset": c.offset}
    return await _ld_request(token, region, "GET", f"/teams/{c.team_key}/maintainers",
                             params=params, action_name="list_team_maintainers")


class LaunchDarklyAddTeamMembersConfig(BaseModel):
    """Add members to a team (semantic-patch addMembers instruction).

    The raw /teams/{key}/members endpoint only accepts CSV/multipart uploads; a
    semantic patch on the team is the JSON-friendly way to add members.
    """
    operation: Literal["add_team_members"] = Field(
        "add_team_members",
        json_schema_extra={"const": "add_team_members", "ui:hidden": True,
                           "x-category": "Teams", "x-is-trigger": False,
                           "x-display-name": "Add Team Members"},
        title="Add Team Members",
    )
    team_key: str = _team_key_field()
    member_ids: str = Field(..., title="Member IDs",
        description="Comma-separated member IDs to add to the team")
    comment: Optional[str] = Field(None, title="Comment")


async def _add_team_members(c, token, region) -> Dict[str, Any]:
    # Single-team addMembers instruction takes `values` (list of member IDs).
    body = {"comment": c.comment,
            "instructions": [{"kind": "addMembers", "values": _comma_list(c.member_ids)}]}
    return await _ld_request(token, region, "PATCH", f"/teams/{c.team_key}",
                             json_body=body, content_type=SEMANTIC_PATCH_CONTENT_TYPE,
                             action_name="add_team_members")


class LaunchDarklyListTeamRolesConfig(BaseModel):
    """Get the custom roles associated with a team."""
    operation: Literal["list_team_roles"] = Field(
        "list_team_roles",
        json_schema_extra={"const": "list_team_roles", "ui:hidden": True,
                           "x-category": "Teams", "x-is-trigger": False,
                           "x-display-name": "List Team Roles"},
        title="List Team Roles",
    )
    team_key: str = _team_key_field()
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    offset: Optional[str] = Field(None, title="Offset", description="Pagination offset")


async def _list_team_roles(c, token, region) -> Dict[str, Any]:
    params = {"limit": c.limit, "offset": c.offset}
    return await _ld_request(token, region, "GET", f"/teams/{c.team_key}/roles",
                             params=params, action_name="list_team_roles")


OPERATION_CONFIGS.extend([
    LaunchDarklyCreateTeamConfig,
    LaunchDarklyGetTeamConfig,
    LaunchDarklyUpdateTeamConfig,
    LaunchDarklyDeleteTeamConfig,
    LaunchDarklyListTeamMaintainersConfig,
    LaunchDarklyAddTeamMembersConfig,
    LaunchDarklyListTeamRolesConfig,
])
OPERATION_HANDLERS.update({
    "create_team": _create_team,
    "get_team": _get_team,
    "update_team": _update_team,
    "delete_team": _delete_team,
    "list_team_maintainers": _list_team_maintainers,
    "add_team_members": _add_team_members,
    "list_team_roles": _list_team_roles,
})

# ============================================================================
# Account members operations
# ============================================================================


class LaunchDarklyUpdateMembersConfig(BaseModel):
    """Modify multiple account members via semantic-patch instructions."""
    operation: Literal["update_members"] = Field(
        "update_members",
        json_schema_extra={"const": "update_members", "ui:hidden": True,
                           "x-category": "Account members", "x-is-trigger": False,
                           "x-display-name": "Modify Account Members"},
        title="Modify Account Members",
    )
    instructions_json: str = Field(..., title="Instructions (JSON array)",
        description='Semantic-patch instructions, e.g. [{"kind":"replaceMembersRoles","value":"reader"}]')
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment describing the update")


async def _update_members(c, token, region) -> Dict[str, Any]:
    body = {"comment": c.comment, "instructions": json.loads(c.instructions_json)}
    return await _ld_request(token, region, "PATCH", "/members",
                             json_body=body, content_type=SEMANTIC_PATCH_CONTENT_TYPE,
                             action_name="update_members")


class LaunchDarklyGetMemberConfig(BaseModel):
    """Get a single account member by ID."""
    operation: Literal["get_member"] = Field(
        "get_member",
        json_schema_extra={"const": "get_member", "ui:hidden": True,
                           "x-category": "Account members", "x-is-trigger": False,
                           "x-display-name": "Get Account Member"},
        title="Get Account Member",
    )
    id: str = Field(..., title="Member ID", description="The member ID")
    expand: Optional[str] = Field(None, title="Expand",
        description="Comma-separated fields to expand in the response")


async def _get_member(c, token, region) -> Dict[str, Any]:
    params = {"expand": c.expand}
    return await _ld_request(token, region, "GET", f"/members/{c.id}",
                             params=params, action_name="get_member")


class LaunchDarklyUpdateMemberConfig(BaseModel):
    """Modify a single account member via JSON Patch."""
    operation: Literal["update_member"] = Field(
        "update_member",
        json_schema_extra={"const": "update_member", "ui:hidden": True,
                           "x-category": "Account members", "x-is-trigger": False,
                           "x-display-name": "Modify Account Member"},
        title="Modify Account Member",
    )
    id: str = Field(..., title="Member ID", description="The member ID")
    patch_json: str = Field(..., title="JSON Patch (array)",
        description='JSON Patch array, e.g. [{"op":"replace","path":"/role","value":"admin"}]')


async def _update_member(c, token, region) -> Dict[str, Any]:
    body = json.loads(c.patch_json)
    return await _ld_request(token, region, "PATCH", f"/members/{c.id}",
                             json_body=body, action_name="update_member")


class LaunchDarklyDeleteMemberConfig(BaseModel):
    """Delete an account member."""
    operation: Literal["delete_member"] = Field(
        "delete_member",
        json_schema_extra={"const": "delete_member", "ui:hidden": True,
                           "x-category": "Account members", "x-is-trigger": False,
                           "x-display-name": "Delete Account Member"},
        title="Delete Account Member",
    )
    id: str = Field(..., title="Member ID", description="The member ID")


async def _delete_member(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "DELETE", f"/members/{c.id}",
                             action_name="delete_member")


class LaunchDarklyAddMemberTeamsConfig(BaseModel):
    """Add an account member to one or more teams."""
    operation: Literal["add_member_teams"] = Field(
        "add_member_teams",
        json_schema_extra={"const": "add_member_teams", "ui:hidden": True,
                           "x-category": "Account members", "x-is-trigger": False,
                           "x-display-name": "Add Member To Teams"},
        title="Add Member To Teams",
    )
    id: str = Field(..., title="Member ID", description="The member ID")
    team_keys: str = Field(..., title="Team Keys", description="Comma-separated list of team keys")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _add_member_teams(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"teamKeys": _comma_list(c.team_keys)})
    return await _ld_request(token, region, "POST", f"/members/{c.id}/teams",
                             json_body=body, action_name="add_member_teams")


OPERATION_CONFIGS.extend([
    LaunchDarklyUpdateMembersConfig,
    LaunchDarklyGetMemberConfig,
    LaunchDarklyUpdateMemberConfig,
    LaunchDarklyDeleteMemberConfig,
    LaunchDarklyAddMemberTeamsConfig,
])
OPERATION_HANDLERS.update({
    "update_members": _update_members,
    "get_member": _get_member,
    "update_member": _update_member,
    "delete_member": _delete_member,
    "add_member_teams": _add_member_teams,
})

class LaunchDarklyGetEnvironmentConfig(BaseModel):
    """Get a single environment in a project."""
    operation: Literal["get_environment"] = Field(
        "get_environment",
        json_schema_extra={"const": "get_environment", "ui:hidden": True,
                           "x-category": "Environments", "x-is-trigger": False,
                           "x-display-name": "Get Environment"},
        title="Get Environment",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()


async def _get_environment(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/projects/{c.project_key}/environments/{c.environment_key}",
                             action_name="get_environment")


class LaunchDarklyUpdateEnvironmentConfig(BaseModel):
    """Update an environment via JSON Patch."""
    operation: Literal["update_environment"] = Field(
        "update_environment",
        json_schema_extra={"const": "update_environment", "ui:hidden": True,
                           "x-category": "Environments", "x-is-trigger": False,
                           "x-display-name": "Update Environment"},
        title="Update Environment",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    patch_json: str = Field(..., title="Patch (JSON array)",
        description='JSON Patch operations, e.g. [{"op":"replace","path":"/name","value":"Prod"}]')


async def _update_environment(c, token, region) -> Dict[str, Any]:
    body = json.loads(c.patch_json)
    return await _ld_request(token, region, "PATCH",
                             f"/projects/{c.project_key}/environments/{c.environment_key}",
                             json_body=body, action_name="update_environment")


class LaunchDarklyResetEnvironmentSdkKeyConfig(BaseModel):
    """Reset an environment's SDK key, optionally keeping the old key alive for a period."""
    operation: Literal["reset_environment_sdk_key"] = Field(
        "reset_environment_sdk_key",
        json_schema_extra={"const": "reset_environment_sdk_key", "ui:hidden": True,
                           "x-category": "Environments", "x-is-trigger": False,
                           "x-display-name": "Reset Environment SDK Key"},
        title="Reset Environment SDK Key",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    expiry: Optional[str] = Field(None, title="Expiry",
        description="Unix ms timestamp until which the old SDK key remains valid")


async def _reset_environment_sdk_key(c, token, region) -> Dict[str, Any]:
    params = {"expiry": c.expiry}
    return await _ld_request(token, region, "POST",
                             f"/projects/{c.project_key}/environments/{c.environment_key}/apiKey",
                             params=params, action_name="reset_environment_sdk_key")


class LaunchDarklyResetEnvironmentMobileKeyConfig(BaseModel):
    """Reset an environment's mobile SDK key."""
    operation: Literal["reset_environment_mobile_key"] = Field(
        "reset_environment_mobile_key",
        json_schema_extra={"const": "reset_environment_mobile_key", "ui:hidden": True,
                           "x-category": "Environments", "x-is-trigger": False,
                           "x-display-name": "Reset Environment Mobile Key"},
        title="Reset Environment Mobile Key",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()


async def _reset_environment_mobile_key(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "POST",
                             f"/projects/{c.project_key}/environments/{c.environment_key}/mobileKey",
                             action_name="reset_environment_mobile_key")


OPERATION_CONFIGS.extend([
    LaunchDarklyGetEnvironmentConfig,
    LaunchDarklyUpdateEnvironmentConfig,
    LaunchDarklyResetEnvironmentSdkKeyConfig,
    LaunchDarklyResetEnvironmentMobileKeyConfig,
])
OPERATION_HANDLERS.update({
    "get_environment": _get_environment,
    "update_environment": _update_environment,
    "reset_environment_sdk_key": _reset_environment_sdk_key,
    "reset_environment_mobile_key": _reset_environment_mobile_key,
})

# ============================================================================
# Relay Proxy configurations
# ============================================================================
class LaunchDarklyListRelayProxyConfigsConfig(BaseModel):
    """List Relay Proxy configs in the account."""
    operation: Literal["list_relay_proxy_configs"] = Field(
        "list_relay_proxy_configs",
        json_schema_extra={"const": "list_relay_proxy_configs", "ui:hidden": True,
                           "x-category": "Relay Proxy configurations", "x-is-trigger": False,
                           "x-display-name": "List Relay Proxy Configs"},
        title="List Relay Proxy Configs",
    )


async def _list_relay_proxy_configs(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", "/account/relay-auto-configs",
                             action_name="list_relay_proxy_configs")


class LaunchDarklyCreateRelayProxyConfigConfig(BaseModel):
    """Create a new Relay Proxy config."""
    operation: Literal["create_relay_proxy_config"] = Field(
        "create_relay_proxy_config",
        json_schema_extra={"const": "create_relay_proxy_config", "ui:hidden": True,
                           "x-category": "Relay Proxy configurations", "x-is-trigger": False,
                           "x-display-name": "Create Relay Proxy Config"},
        title="Create Relay Proxy Config",
    )
    name: str = Field(..., title="Name", description="A human-friendly name for the Relay Proxy config")
    policy_json: str = Field(..., title="Policy (JSON array)",
        description='Array of policy statements granting the config access, e.g. [{"resources":["proj/*:env/*"],"actions":["*"],"effect":"allow"}]')
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _create_relay_proxy_config(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"name": c.name, "policy": json.loads(c.policy_json)})
    return await _ld_request(token, region, "POST", "/account/relay-auto-configs",
                             json_body=body, action_name="create_relay_proxy_config")


class LaunchDarklyGetRelayProxyConfigConfig(BaseModel):
    """Get a single Relay Proxy config by ID."""
    operation: Literal["get_relay_proxy_config"] = Field(
        "get_relay_proxy_config",
        json_schema_extra={"const": "get_relay_proxy_config", "ui:hidden": True,
                           "x-category": "Relay Proxy configurations", "x-is-trigger": False,
                           "x-display-name": "Get Relay Proxy Config"},
        title="Get Relay Proxy Config",
    )
    id: str = Field(..., title="ID", description="The relay auto config ID")


async def _get_relay_proxy_config(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", f"/account/relay-auto-configs/{c.id}",
                             action_name="get_relay_proxy_config")


class LaunchDarklyUpdateRelayProxyConfigConfig(BaseModel):
    """Update a Relay Proxy config via a JSON patch."""
    operation: Literal["update_relay_proxy_config"] = Field(
        "update_relay_proxy_config",
        json_schema_extra={"const": "update_relay_proxy_config", "ui:hidden": True,
                           "x-category": "Relay Proxy configurations", "x-is-trigger": False,
                           "x-display-name": "Update Relay Proxy Config"},
        title="Update Relay Proxy Config",
    )
    id: str = Field(..., title="ID", description="The relay auto config ID")
    patch_json: str = Field(..., title="Patch (JSON array)",
        description='JSON Patch operations, e.g. [{"op":"replace","path":"/name","value":"New name"}]')
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment describing the update")


async def _update_relay_proxy_config(c, token, region) -> Dict[str, Any]:
    body = {"patch": json.loads(c.patch_json), "comment": c.comment}
    return await _ld_request(token, region, "PATCH", f"/account/relay-auto-configs/{c.id}",
                             json_body=body, action_name="update_relay_proxy_config")


class LaunchDarklyDeleteRelayProxyConfigConfig(BaseModel):
    """Delete a Relay Proxy config by ID."""
    operation: Literal["delete_relay_proxy_config"] = Field(
        "delete_relay_proxy_config",
        json_schema_extra={"const": "delete_relay_proxy_config", "ui:hidden": True,
                           "x-category": "Relay Proxy configurations", "x-is-trigger": False,
                           "x-display-name": "Delete Relay Proxy Config"},
        title="Delete Relay Proxy Config",
    )
    id: str = Field(..., title="ID", description="The relay auto config ID")


async def _delete_relay_proxy_config(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "DELETE", f"/account/relay-auto-configs/{c.id}",
                             action_name="delete_relay_proxy_config")


class LaunchDarklyResetRelayProxyConfigConfig(BaseModel):
    """Reset a Relay Proxy configuration's secret key."""
    operation: Literal["reset_relay_proxy_config"] = Field(
        "reset_relay_proxy_config",
        json_schema_extra={"const": "reset_relay_proxy_config", "ui:hidden": True,
                           "x-category": "Relay Proxy configurations", "x-is-trigger": False,
                           "x-display-name": "Reset Relay Proxy Config Key"},
        title="Reset Relay Proxy Config Key",
    )
    id: str = Field(..., title="ID", description="The relay auto config ID")
    expiry: Optional[str] = Field(None, title="Expiry",
        description="An expiration time (Unix ms) for the old key; if omitted the old key expires immediately")


async def _reset_relay_proxy_config(c, token, region) -> Dict[str, Any]:
    params = {"expiry": c.expiry}
    return await _ld_request(token, region, "POST", f"/account/relay-auto-configs/{c.id}/reset",
                             params=params, action_name="reset_relay_proxy_config")


OPERATION_CONFIGS.extend([
    LaunchDarklyListRelayProxyConfigsConfig,
    LaunchDarklyCreateRelayProxyConfigConfig,
    LaunchDarklyGetRelayProxyConfigConfig,
    LaunchDarklyUpdateRelayProxyConfigConfig,
    LaunchDarklyDeleteRelayProxyConfigConfig,
    LaunchDarklyResetRelayProxyConfigConfig,
])
OPERATION_HANDLERS.update({
    "list_relay_proxy_configs": _list_relay_proxy_configs,
    "create_relay_proxy_config": _create_relay_proxy_config,
    "get_relay_proxy_config": _get_relay_proxy_config,
    "update_relay_proxy_config": _update_relay_proxy_config,
    "delete_relay_proxy_config": _delete_relay_proxy_config,
    "reset_relay_proxy_config": _reset_relay_proxy_config,
})

# ============================================================================
# Access tokens
# ============================================================================


class LaunchDarklyCreateTokenConfig(BaseModel):
    """Create an access token."""
    operation: Literal["create_token"] = Field(
        "create_token",
        json_schema_extra={"const": "create_token", "ui:hidden": True,
                           "x-category": "Access tokens", "x-is-trigger": False,
                           "x-display-name": "Create Access Token"},
        title="Create Access Token",
    )
    name: Optional[str] = Field(None, title="Name", description="A human-friendly name for the access token")
    description: Optional[str] = Field(None, title="Description", description="A description for the access token")
    role: Optional[str] = Field(None, title="Base Role", description="Base role for the token",
        json_schema_extra={"enum": ["reader", "writer", "admin"], "x-enum-searchable": True})
    custom_role_ids: Optional[str] = Field(None, title="Custom Role IDs",
        description="Comma-separated custom role IDs to use as access limits")
    service_token: Optional[str] = Field(None, title="Service Token", description="Whether the token is a service token",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    default_api_version: Optional[str] = Field(None, title="Default API Version",
        description="The default API version for this token")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields (e.g. inlineRole)")


async def _create_token(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.name is not None:
        body["name"] = c.name
    if c.description is not None:
        body["description"] = c.description
    if c.role is not None:
        body["role"] = c.role
    if c.custom_role_ids:
        body["customRoleIds"] = _comma_list(c.custom_role_ids)
    if c.service_token is not None:
        body["serviceToken"] = c.service_token == "true"
    if c.default_api_version is not None:
        body["defaultApiVersion"] = int(c.default_api_version)
    return await _ld_request(token, region, "POST", "/tokens", json_body=body, action_name="create_token")


class LaunchDarklyGetTokenConfig(BaseModel):
    """Get a single access token by ID."""
    operation: Literal["get_token"] = Field(
        "get_token",
        json_schema_extra={"const": "get_token", "ui:hidden": True,
                           "x-category": "Access tokens", "x-is-trigger": False,
                           "x-display-name": "Get Access Token"},
        title="Get Access Token",
    )
    id: str = Field(..., title="Token ID", description="The ID of the access token")


async def _get_token(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", f"/tokens/{c.id}", action_name="get_token")


class LaunchDarklyUpdateTokenConfig(BaseModel):
    """Update an access token via JSON Patch."""
    operation: Literal["update_token"] = Field(
        "update_token",
        json_schema_extra={"const": "update_token", "ui:hidden": True,
                           "x-category": "Access tokens", "x-is-trigger": False,
                           "x-display-name": "Update Access Token"},
        title="Update Access Token",
    )
    id: str = Field(..., title="Token ID", description="The ID of the access token")
    patch_json: str = Field(..., title="Patch (JSON array)",
        description='JSON Patch array, e.g. [{"op":"replace","path":"/name","value":"New name"}]')


async def _update_token(c, token, region) -> Dict[str, Any]:
    body = json.loads(c.patch_json)
    return await _ld_request(token, region, "PATCH", f"/tokens/{c.id}",
                             json_body=body, action_name="update_token")


class LaunchDarklyDeleteTokenConfig(BaseModel):
    """Delete an access token."""
    operation: Literal["delete_token"] = Field(
        "delete_token",
        json_schema_extra={"const": "delete_token", "ui:hidden": True,
                           "x-category": "Access tokens", "x-is-trigger": False,
                           "x-display-name": "Delete Access Token"},
        title="Delete Access Token",
    )
    id: str = Field(..., title="Token ID", description="The ID of the access token")


async def _delete_token(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "DELETE", f"/tokens/{c.id}", action_name="delete_token")


class LaunchDarklyResetTokenConfig(BaseModel):
    """Reset an access token's secret, optionally keeping the old one valid for a grace period."""
    operation: Literal["reset_token"] = Field(
        "reset_token",
        json_schema_extra={"const": "reset_token", "ui:hidden": True,
                           "x-category": "Access tokens", "x-is-trigger": False,
                           "x-display-name": "Reset Access Token"},
        title="Reset Access Token",
    )
    id: str = Field(..., title="Token ID", description="The ID of the access token")
    expiry: Optional[str] = Field(None, title="Expiry",
        description="Expiration time (UNIX ms) for the old token secret; if not set the old secret expires immediately")


async def _reset_token(c, token, region) -> Dict[str, Any]:
    params = {"expiry": c.expiry}
    return await _ld_request(token, region, "POST", f"/tokens/{c.id}/reset",
                             params=params, action_name="reset_token")


OPERATION_CONFIGS.extend([
    LaunchDarklyCreateTokenConfig,
    LaunchDarklyGetTokenConfig,
    LaunchDarklyUpdateTokenConfig,
    LaunchDarklyDeleteTokenConfig,
    LaunchDarklyResetTokenConfig,
])
OPERATION_HANDLERS.update({
    "create_token": _create_token,
    "get_token": _get_token,
    "update_token": _update_token,
    "delete_token": _delete_token,
    "reset_token": _reset_token,
})

class LaunchDarklyGetRootConfig(BaseModel):
    """Get the root resource of the LaunchDarkly API."""
    operation: Literal["get_root"] = Field(
        "get_root",
        json_schema_extra={"const": "get_root", "ui:hidden": True,
                           "x-category": "Other", "x-is-trigger": False,
                           "x-display-name": "Get Root Resource"},
        title="Get Root Resource",
    )


async def _get_root(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", "", action_name="get_root")


class LaunchDarklyGetCallerIdentityConfig(BaseModel):
    """Identify the caller associated with the API access token."""
    operation: Literal["get_caller_identity"] = Field(
        "get_caller_identity",
        json_schema_extra={"const": "get_caller_identity", "ui:hidden": True,
                           "x-category": "Other", "x-is-trigger": False,
                           "x-display-name": "Get Caller Identity"},
        title="Get Caller Identity",
    )


async def _get_caller_identity(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", "/caller-identity", action_name="get_caller_identity")


class LaunchDarklyGetOpenapiSpecConfig(BaseModel):
    """Get the LaunchDarkly OpenAPI specification in JSON."""
    operation: Literal["get_openapi_spec"] = Field(
        "get_openapi_spec",
        json_schema_extra={"const": "get_openapi_spec", "ui:hidden": True,
                           "x-category": "Other", "x-is-trigger": False,
                           "x-display-name": "Get OpenAPI Spec"},
        title="Get OpenAPI Spec",
    )


async def _get_openapi_spec(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", "/openapi.json", action_name="get_openapi_spec")


class LaunchDarklyGetPublicIpListConfig(BaseModel):
    """Get the list of public IP addresses used by LaunchDarkly."""
    operation: Literal["get_public_ip_list"] = Field(
        "get_public_ip_list",
        json_schema_extra={"const": "get_public_ip_list", "ui:hidden": True,
                           "x-category": "Other", "x-is-trigger": False,
                           "x-display-name": "Get Public IP List"},
        title="Get Public IP List",
    )


async def _get_public_ip_list(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", "/public-ip-list", action_name="get_public_ip_list")


class LaunchDarklyGetVersionsConfig(BaseModel):
    """Get LaunchDarkly API version information."""
    operation: Literal["get_versions"] = Field(
        "get_versions",
        json_schema_extra={"const": "get_versions", "ui:hidden": True,
                           "x-category": "Other", "x-is-trigger": False,
                           "x-display-name": "Get Versions"},
        title="Get Versions",
    )


async def _get_versions(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", "/versions", action_name="get_versions")


OPERATION_CONFIGS.extend([
    LaunchDarklyGetRootConfig,
    LaunchDarklyGetCallerIdentityConfig,
    LaunchDarklyGetOpenapiSpecConfig,
    LaunchDarklyGetPublicIpListConfig,
    LaunchDarklyGetVersionsConfig,
])
OPERATION_HANDLERS.update({
    "get_root": _get_root,
    "get_caller_identity": _get_caller_identity,
    "get_openapi_spec": _get_openapi_spec,
    "get_public_ip_list": _get_public_ip_list,
    "get_versions": _get_versions,
})

# ============================================================================
# Flag triggers
# ============================================================================
class LaunchDarklyListFlagTriggersConfig(BaseModel):
    """List all triggers for a feature flag in an environment."""
    operation: Literal["list_flag_triggers"] = Field(
        "list_flag_triggers",
        json_schema_extra={"const": "list_flag_triggers", "ui:hidden": True,
                           "x-category": "Flag triggers", "x-is-trigger": False,
                           "x-display-name": "List Flag Triggers"},
        title="List Flag Triggers",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()


async def _list_flag_triggers(c, token, region) -> Dict[str, Any]:
    return await _ld_request(
        token, region, "GET",
        f"/flags/{c.project_key}/{c.feature_flag_key}/triggers/{c.environment_key}",
        action_name="list_flag_triggers")


class LaunchDarklyCreateFlagTriggerConfig(BaseModel):
    """Create a trigger for a feature flag in an environment."""
    operation: Literal["create_flag_trigger"] = Field(
        "create_flag_trigger",
        json_schema_extra={"const": "create_flag_trigger", "ui:hidden": True,
                           "x-category": "Flag triggers", "x-is-trigger": False,
                           "x-display-name": "Create Flag Trigger"},
        title="Create Flag Trigger",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    integration_key: str = Field(..., title="Integration Key",
        description="Integration identifier, e.g. 'generic-trigger'")
    instructions_json: Optional[str] = Field(None, title="Instructions (JSON array)",
        description='Action to perform, e.g. [{"kind":"turnFlagOn"}]')
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment describing the trigger")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _create_flag_trigger(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body["integrationKey"] = c.integration_key
    if c.instructions_json:
        body["instructions"] = json.loads(c.instructions_json)
    if c.comment is not None:
        body["comment"] = c.comment
    return await _ld_request(
        token, region, "POST",
        f"/flags/{c.project_key}/{c.feature_flag_key}/triggers/{c.environment_key}",
        json_body=body, action_name="create_flag_trigger")


class LaunchDarklyGetFlagTriggerConfig(BaseModel):
    """Get a single flag trigger by ID."""
    operation: Literal["get_flag_trigger"] = Field(
        "get_flag_trigger",
        json_schema_extra={"const": "get_flag_trigger", "ui:hidden": True,
                           "x-category": "Flag triggers", "x-is-trigger": False,
                           "x-display-name": "Get Flag Trigger"},
        title="Get Flag Trigger",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    id: str = Field(..., title="Trigger ID", description="The trigger ID")


async def _get_flag_trigger(c, token, region) -> Dict[str, Any]:
    return await _ld_request(
        token, region, "GET",
        f"/flags/{c.project_key}/{c.feature_flag_key}/triggers/{c.environment_key}/{c.id}",
        action_name="get_flag_trigger")


class LaunchDarklyUpdateFlagTriggerConfig(BaseModel):
    """Update a flag trigger via semantic-patch instructions."""
    operation: Literal["update_flag_trigger"] = Field(
        "update_flag_trigger",
        json_schema_extra={"const": "update_flag_trigger", "ui:hidden": True,
                           "x-category": "Flag triggers", "x-is-trigger": False,
                           "x-display-name": "Update Flag Trigger"},
        title="Update Flag Trigger",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    id: str = Field(..., title="Trigger ID", description="The trigger ID")
    instructions_json: str = Field(..., title="Instructions (JSON array)",
        description='Semantic-patch instructions, e.g. [{"kind":"disableTrigger"}]')
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment describing the update")


async def _update_flag_trigger(c, token, region) -> Dict[str, Any]:
    body = {"comment": c.comment, "instructions": json.loads(c.instructions_json)}
    return await _ld_request(
        token, region, "PATCH",
        f"/flags/{c.project_key}/{c.feature_flag_key}/triggers/{c.environment_key}/{c.id}",
        json_body=body, content_type=SEMANTIC_PATCH_CONTENT_TYPE,
        action_name="update_flag_trigger")


class LaunchDarklyDeleteFlagTriggerConfig(BaseModel):
    """Delete a flag trigger by ID."""
    operation: Literal["delete_flag_trigger"] = Field(
        "delete_flag_trigger",
        json_schema_extra={"const": "delete_flag_trigger", "ui:hidden": True,
                           "x-category": "Flag triggers", "x-is-trigger": False,
                           "x-display-name": "Delete Flag Trigger"},
        title="Delete Flag Trigger",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    id: str = Field(..., title="Trigger ID", description="The trigger ID")


async def _delete_flag_trigger(c, token, region) -> Dict[str, Any]:
    return await _ld_request(
        token, region, "DELETE",
        f"/flags/{c.project_key}/{c.feature_flag_key}/triggers/{c.environment_key}/{c.id}",
        action_name="delete_flag_trigger")


OPERATION_CONFIGS.extend([
    LaunchDarklyListFlagTriggersConfig,
    LaunchDarklyCreateFlagTriggerConfig,
    LaunchDarklyGetFlagTriggerConfig,
    LaunchDarklyUpdateFlagTriggerConfig,
    LaunchDarklyDeleteFlagTriggerConfig,
])
OPERATION_HANDLERS.update({
    "list_flag_triggers": _list_flag_triggers,
    "create_flag_trigger": _create_flag_trigger,
    "get_flag_trigger": _get_flag_trigger,
    "update_flag_trigger": _update_flag_trigger,
    "delete_flag_trigger": _delete_flag_trigger,
})

# ============================================================================
# Integration audit log subscriptions
# ============================================================================


class LaunchDarklyListIntegrationSubscriptionsConfig(BaseModel):
    """Get all audit log subscriptions for a given integration."""
    operation: Literal["list_integration_subscriptions"] = Field(
        "list_integration_subscriptions",
        json_schema_extra={"const": "list_integration_subscriptions", "ui:hidden": True,
                           "x-category": "Integration audit log subscriptions", "x-is-trigger": False,
                           "x-display-name": "List Integration Subscriptions"},
        title="List Integration Subscriptions",
    )
    integration_key: str = Field(..., title="Integration Key",
        description="The integration key (e.g. datadog, splunk, msteams)")


async def _list_integration_subscriptions(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", f"/integrations/{c.integration_key}",
                             action_name="list_integration_subscriptions")


class LaunchDarklyCreateIntegrationSubscriptionConfig(BaseModel):
    """Create an audit log subscription for an integration."""
    operation: Literal["create_integration_subscription"] = Field(
        "create_integration_subscription",
        json_schema_extra={"const": "create_integration_subscription", "ui:hidden": True,
                           "x-category": "Integration audit log subscriptions", "x-is-trigger": False,
                           "x-display-name": "Create Integration Subscription"},
        title="Create Integration Subscription",
    )
    integration_key: str = Field(..., title="Integration Key",
        description="The integration key (e.g. datadog, splunk, msteams)")
    name: str = Field(..., title="Name", description="A human-friendly name for the audit log subscription")
    on: Optional[str] = Field(None, title="On", description="Whether the subscription actively sends events",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    tags: Optional[str] = Field(None, title="Tags", description="Comma-separated list of tags for this subscription")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description='Optional raw JSON merged into the request body for advanced fields, e.g. {"config": {...}, "statements": [...]}')


async def _create_integration_subscription(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body["name"] = c.name
    if c.on is not None:
        body["on"] = c.on == "true"
    if c.tags is not None:
        body["tags"] = _comma_list(c.tags)
    return await _ld_request(token, region, "POST", f"/integrations/{c.integration_key}",
                             json_body=body, action_name="create_integration_subscription")


class LaunchDarklyGetIntegrationSubscriptionConfig(BaseModel):
    """Get an audit log subscription by ID."""
    operation: Literal["get_integration_subscription"] = Field(
        "get_integration_subscription",
        json_schema_extra={"const": "get_integration_subscription", "ui:hidden": True,
                           "x-category": "Integration audit log subscriptions", "x-is-trigger": False,
                           "x-display-name": "Get Integration Subscription"},
        title="Get Integration Subscription",
    )
    integration_key: str = Field(..., title="Integration Key",
        description="The integration key (e.g. datadog, splunk, msteams)")
    id: str = Field(..., title="Subscription ID", description="The audit log subscription ID")


async def _get_integration_subscription(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", f"/integrations/{c.integration_key}/{c.id}",
                             action_name="get_integration_subscription")


class LaunchDarklyUpdateIntegrationSubscriptionConfig(BaseModel):
    """Update an audit log subscription via a JSON Patch array."""
    operation: Literal["update_integration_subscription"] = Field(
        "update_integration_subscription",
        json_schema_extra={"const": "update_integration_subscription", "ui:hidden": True,
                           "x-category": "Integration audit log subscriptions", "x-is-trigger": False,
                           "x-display-name": "Update Integration Subscription"},
        title="Update Integration Subscription",
    )
    integration_key: str = Field(..., title="Integration Key",
        description="The integration key (e.g. datadog, splunk, msteams)")
    id: str = Field(..., title="Subscription ID", description="The audit log subscription ID")
    patch_json: str = Field(..., title="Patch (JSON array)",
        description='JSON Patch array, e.g. [{"op":"replace","path":"/name","value":"New name"}]')


async def _update_integration_subscription(c, token, region) -> Dict[str, Any]:
    body = json.loads(c.patch_json)
    return await _ld_request(token, region, "PATCH", f"/integrations/{c.integration_key}/{c.id}",
                             json_body=body, action_name="update_integration_subscription")


class LaunchDarklyDeleteIntegrationSubscriptionConfig(BaseModel):
    """Delete an audit log subscription."""
    operation: Literal["delete_integration_subscription"] = Field(
        "delete_integration_subscription",
        json_schema_extra={"const": "delete_integration_subscription", "ui:hidden": True,
                           "x-category": "Integration audit log subscriptions", "x-is-trigger": False,
                           "x-display-name": "Delete Integration Subscription"},
        title="Delete Integration Subscription",
    )
    integration_key: str = Field(..., title="Integration Key",
        description="The integration key (e.g. datadog, splunk, msteams)")
    id: str = Field(..., title="Subscription ID", description="The audit log subscription ID")


async def _delete_integration_subscription(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "DELETE", f"/integrations/{c.integration_key}/{c.id}",
                             action_name="delete_integration_subscription")


OPERATION_CONFIGS.extend([
    LaunchDarklyListIntegrationSubscriptionsConfig,
    LaunchDarklyCreateIntegrationSubscriptionConfig,
    LaunchDarklyGetIntegrationSubscriptionConfig,
    LaunchDarklyUpdateIntegrationSubscriptionConfig,
    LaunchDarklyDeleteIntegrationSubscriptionConfig,
])
OPERATION_HANDLERS.update({
    "list_integration_subscriptions": _list_integration_subscriptions,
    "create_integration_subscription": _create_integration_subscription,
    "get_integration_subscription": _get_integration_subscription,
    "update_integration_subscription": _update_integration_subscription,
    "delete_integration_subscription": _delete_integration_subscription,
})

# ============================================================================
# LaunchDarkly — Metrics category operations
# ============================================================================


class LaunchDarklyGetMetricConfig(BaseModel):
    """Get a single metric from a project."""
    operation: Literal["get_metric"] = Field(
        "get_metric",
        json_schema_extra={"const": "get_metric", "ui:hidden": True,
                           "x-category": "Metrics", "x-is-trigger": False,
                           "x-display-name": "Get Metric"},
        title="Get Metric",
    )
    project_key: str = _project_key_field("The project key")
    metric_key: str = _metric_key_field()
    expand: Optional[str] = Field(None, title="Expand",
        description="Comma-separated fields to expand in the response")
    version_id: Optional[str] = Field(None, title="Version ID",
        description="The specific version ID of the metric to retrieve")


async def _get_metric(c, token, region) -> Dict[str, Any]:
    params = {"expand": c.expand, "versionId": c.version_id}
    return await _ld_request(token, region, "GET",
                             f"/metrics/{c.project_key}/{c.metric_key}",
                             params=params, action_name="get_metric")


class LaunchDarklyCreateMetricConfig(BaseModel):
    """Create a metric in a project."""
    operation: Literal["create_metric"] = Field(
        "create_metric",
        json_schema_extra={"const": "create_metric", "x-creates-resource": True, "x-resource-type": "launchdarkly_metric", "x-resource-id-path": "data.key", "ui:hidden": True,
                           "x-category": "Metrics", "x-is-trigger": False,
                           "x-display-name": "Create Metric"},
        title="Create Metric",
    )
    project_key: str = _project_key_field("The project key")
    key: str = Field(..., title="Key", description="A unique key to reference the metric")
    kind: str = Field(..., title="Kind",
        description="The kind of event the metric tracks (e.g. custom, click, pageview)")
    name: Optional[str] = Field(None, title="Name", description="A human-friendly name for the metric")
    description: Optional[str] = Field(None, title="Description", description="Description of the metric")
    event_key: Optional[str] = Field(None, title="Event Key",
        description="The event key to use in your code. Required for custom metrics")
    unit: Optional[str] = Field(None, title="Unit", description="The unit of measure for numeric metrics")
    tags: Optional[str] = Field(None, title="Tags", description="Comma-separated tags for the metric")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _create_metric(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"key": c.key, "kind": c.kind, "name": c.name,
                 "description": c.description, "eventKey": c.event_key,
                 "unit": c.unit, "tags": _comma_list(c.tags)})
    return await _ld_request(token, region, "POST", f"/metrics/{c.project_key}",
                             json_body=body, action_name="create_metric")


class LaunchDarklyUpdateMetricConfig(BaseModel):
    """Update a metric via JSON Patch instructions."""
    operation: Literal["update_metric"] = Field(
        "update_metric",
        json_schema_extra={"const": "update_metric", "ui:hidden": True,
                           "x-category": "Metrics", "x-is-trigger": False,
                           "x-display-name": "Update Metric"},
        title="Update Metric",
    )
    project_key: str = _project_key_field("The project key")
    metric_key: str = _metric_key_field()
    patch_json: str = Field(..., title="JSON Patch (JSON array)",
        description='JSON Patch operations, e.g. [{"op":"replace","path":"/name","value":"New name"}]')


async def _update_metric(c, token, region) -> Dict[str, Any]:
    body = json.loads(c.patch_json)
    return await _ld_request(token, region, "PATCH",
                             f"/metrics/{c.project_key}/{c.metric_key}",
                             json_body=body, action_name="update_metric")


class LaunchDarklyDeleteMetricConfig(BaseModel):
    """Delete a metric from a project."""
    operation: Literal["delete_metric"] = Field(
        "delete_metric",
        json_schema_extra={"const": "delete_metric", "ui:hidden": True,
                           "x-category": "Metrics", "x-is-trigger": False,
                           "x-display-name": "Delete Metric"},
        title="Delete Metric",
    )
    project_key: str = _project_key_field("The project key")
    metric_key: str = _metric_key_field()


async def _delete_metric(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "DELETE",
                             f"/metrics/{c.project_key}/{c.metric_key}",
                             action_name="delete_metric")


OPERATION_CONFIGS.extend([
    LaunchDarklyGetMetricConfig,
    LaunchDarklyCreateMetricConfig,
    LaunchDarklyUpdateMetricConfig,
    LaunchDarklyDeleteMetricConfig,
])
OPERATION_HANDLERS.update({
    "get_metric": _get_metric,
    "create_metric": _create_metric,
    "update_metric": _update_metric,
    "delete_metric": _delete_metric,
})

class LaunchDarklyListOAuthClientConfig(BaseModel):
    """Get all OAuth 2.0 clients registered in the account."""
    operation: Literal["list_oauth_client"] = Field(
        "list_oauth_client",
        json_schema_extra={"const": "list_oauth_client", "ui:hidden": True,
                           "x-category": "OAuth2 Clients", "x-is-trigger": False,
                           "x-display-name": "List OAuth Clients"},
        title="List OAuth Clients",
    )


async def _list_oauth_client(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", "/oauth/clients", action_name="list_oauth_client")


class LaunchDarklyCreateOAuthClientConfig(BaseModel):
    """Create a LaunchDarkly OAuth 2.0 client."""
    operation: Literal["create_oauth_client"] = Field(
        "create_oauth_client",
        json_schema_extra={"const": "create_oauth_client", "ui:hidden": True,
                           "x-category": "OAuth2 Clients", "x-is-trigger": False,
                           "x-display-name": "Create OAuth Client"},
        title="Create OAuth Client",
    )
    name: str = Field(..., title="Name", description="The name of your new OAuth 2.0 client")
    redirect_uri: str = Field(..., title="Redirect URI",
        description="The absolute HTTPS redirect URI for your new OAuth 2.0 application")
    description: Optional[str] = Field(None, title="Description",
        description="Description of your OAuth 2.0 client")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _create_oauth_client(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"name": c.name, "redirectUri": c.redirect_uri, "description": c.description})
    return await _ld_request(token, region, "POST", "/oauth/clients", json_body=body,
                             action_name="create_oauth_client")


class LaunchDarklyGetOAuthClientConfig(BaseModel):
    """Get a single OAuth 2.0 client by ID."""
    operation: Literal["get_oauth_client"] = Field(
        "get_oauth_client",
        json_schema_extra={"const": "get_oauth_client", "ui:hidden": True,
                           "x-category": "OAuth2 Clients", "x-is-trigger": False,
                           "x-display-name": "Get OAuth Client"},
        title="Get OAuth Client",
    )
    client_id: str = _client_id_field("The OAuth client to retrieve")


async def _get_oauth_client(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", f"/oauth/clients/{c.client_id}",
                             action_name="get_oauth_client")


class LaunchDarklyPatchOAuthClientConfig(BaseModel):
    """Patch an OAuth 2.0 client by ID using JSON Patch instructions."""
    operation: Literal["patch_oauth_client"] = Field(
        "patch_oauth_client",
        json_schema_extra={"const": "patch_oauth_client", "ui:hidden": True,
                           "x-category": "OAuth2 Clients", "x-is-trigger": False,
                           "x-display-name": "Patch OAuth Client"},
        title="Patch OAuth Client",
    )
    client_id: str = _client_id_field("The OAuth client to update")
    patch_json: str = Field(..., title="JSON Patch (JSON array)",
        description='JSON Patch operations, e.g. [{"op":"replace","path":"/name","value":"New name"}]')


async def _patch_oauth_client(c, token, region) -> Dict[str, Any]:
    body = json.loads(c.patch_json)
    return await _ld_request(token, region, "PATCH", f"/oauth/clients/{c.client_id}",
                             json_body=body, action_name="patch_oauth_client")


class LaunchDarklyDeleteOAuthClientConfig(BaseModel):
    """Delete an OAuth 2.0 client by ID."""
    operation: Literal["delete_oauth_client"] = Field(
        "delete_oauth_client",
        json_schema_extra={"const": "delete_oauth_client", "ui:hidden": True,
                           "x-category": "OAuth2 Clients", "x-is-trigger": False,
                           "x-display-name": "Delete OAuth Client"},
        title="Delete OAuth Client",
    )
    client_id: str = _client_id_field("The OAuth client to delete")


async def _delete_oauth_client(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "DELETE", f"/oauth/clients/{c.client_id}",
                             action_name="delete_oauth_client")


OPERATION_CONFIGS.extend([
    LaunchDarklyListOAuthClientConfig,
    LaunchDarklyCreateOAuthClientConfig,
    LaunchDarklyGetOAuthClientConfig,
    LaunchDarklyPatchOAuthClientConfig,
    LaunchDarklyDeleteOAuthClientConfig,
])
OPERATION_HANDLERS.update({
    "list_oauth_client": _list_oauth_client,
    "create_oauth_client": _create_oauth_client,
    "get_oauth_client": _get_oauth_client,
    "patch_oauth_client": _patch_oauth_client,
    "delete_oauth_client": _delete_oauth_client,
})

# ---- Holdouts -------------------------------------------------------------
class LaunchDarklyListHoldoutsConfig(BaseModel):
    """Get all holdouts in an environment."""
    operation: Literal["list_holdouts"] = Field(
        "list_holdouts",
        json_schema_extra={"const": "list_holdouts", "ui:hidden": True,
                           "x-category": "Holdouts", "x-is-trigger": False,
                           "x-display-name": "List Holdouts"},
        title="List Holdouts",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    limit: Optional[str] = Field(None, title="Limit", description="Max number of holdouts to return")
    offset: Optional[str] = Field(None, title="Offset", description="Where to start in the list for pagination")


async def _list_holdouts(c, token, region) -> Dict[str, Any]:
    params = {"limit": c.limit, "offset": c.offset}
    return await _ld_request(token, region, "GET",
                             f"/projects/{c.project_key}/environments/{c.environment_key}/holdouts",
                             params=params, action_name="list_holdouts")


class LaunchDarklyCreateHoldoutConfig(BaseModel):
    """Create a holdout in an environment."""
    operation: Literal["create_holdout"] = Field(
        "create_holdout",
        json_schema_extra={"const": "create_holdout", "x-creates-resource": True, "x-resource-type": "launchdarkly_holdout", "x-resource-id-path": "data.key", "ui:hidden": True,
                           "x-category": "Holdouts", "x-is-trigger": False,
                           "x-display-name": "Create Holdout"},
        title="Create Holdout",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    name: str = Field(..., title="Name", description="A human-friendly name for the holdout")
    key: str = Field(..., title="Key", description="A key that identifies the holdout")
    description: Optional[str] = Field(None, title="Description", description="Description of the holdout")
    randomization_unit: Optional[str] = Field(None, title="Randomization Unit",
        description="The chosen randomization unit for the holdout base experiment")
    holdout_amount: Optional[str] = Field(None, title="Holdout Amount",
        description="Audience allocation for the holdout")
    primary_metric_key: Optional[str] = Field(None, title="Primary Metric Key",
        description="The key of the primary metric for this holdout")
    prerequisite_flag_key: Optional[str] = Field(None, title="Prerequisite Flag Key",
        description="The key of the flag that the holdout is dependent on")
    maintainer_id: Optional[str] = Field(None, title="Maintainer ID", description="Maintainer id")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields such as attributes and metrics")


async def _create_holdout(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"name": c.name, "key": c.key, "description": c.description,
                 "randomizationunit": c.randomization_unit, "holdoutamount": c.holdout_amount,
                 "primarymetrickey": c.primary_metric_key, "prerequisiteflagkey": c.prerequisite_flag_key,
                 "maintainerId": c.maintainer_id})
    return await _ld_request(token, region, "POST",
                             f"/projects/{c.project_key}/environments/{c.environment_key}/holdouts",
                             json_body=body, action_name="create_holdout")


class LaunchDarklyGetHoldoutByIdConfig(BaseModel):
    """Get a holdout by its id."""
    operation: Literal["get_holdout_by_id"] = Field(
        "get_holdout_by_id",
        json_schema_extra={"const": "get_holdout_by_id", "ui:hidden": True,
                           "x-category": "Holdouts", "x-is-trigger": False,
                           "x-display-name": "Get Holdout by Id"},
        title="Get Holdout by Id",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    holdout_id: str = Field(..., title="Holdout ID", description="The holdout id")


async def _get_holdout_by_id(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/projects/{c.project_key}/environments/{c.environment_key}/holdouts/id/{c.holdout_id}",
                             action_name="get_holdout_by_id")


class LaunchDarklyGetHoldoutConfig(BaseModel):
    """Get a holdout by its key."""
    operation: Literal["get_holdout"] = Field(
        "get_holdout",
        json_schema_extra={"const": "get_holdout", "ui:hidden": True,
                           "x-category": "Holdouts", "x-is-trigger": False,
                           "x-display-name": "Get Holdout"},
        title="Get Holdout",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    holdout_key: str = _holdout_key_field()
    expand: Optional[str] = Field(None, title="Expand", description="Comma-separated fields to expand")


async def _get_holdout(c, token, region) -> Dict[str, Any]:
    params = {"expand": c.expand}
    return await _ld_request(token, region, "GET",
                             f"/projects/{c.project_key}/environments/{c.environment_key}/holdouts/{c.holdout_key}",
                             params=params, action_name="get_holdout")


class LaunchDarklyUpdateHoldoutConfig(BaseModel):
    """Update a holdout via semantic-patch instructions."""
    operation: Literal["update_holdout"] = Field(
        "update_holdout",
        json_schema_extra={"const": "update_holdout", "ui:hidden": True,
                           "x-category": "Holdouts", "x-is-trigger": False,
                           "x-display-name": "Update Holdout"},
        title="Update Holdout",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    holdout_key: str = _holdout_key_field("The holdout to update")
    instructions_json: str = Field(..., title="Instructions (JSON array)",
        description='Semantic-patch instructions, e.g. [{"kind":"updateName","value":"New name"}]')
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment describing the update")


async def _update_holdout(c, token, region) -> Dict[str, Any]:
    body = {"comment": c.comment, "instructions": json.loads(c.instructions_json)}
    return await _ld_request(token, region, "PATCH",
                             f"/projects/{c.project_key}/environments/{c.environment_key}/holdouts/{c.holdout_key}",
                             json_body=body, content_type=SEMANTIC_PATCH_CONTENT_TYPE,
                             action_name="update_holdout")


OPERATION_CONFIGS.extend([
    LaunchDarklyListHoldoutsConfig,
    LaunchDarklyCreateHoldoutConfig,
    LaunchDarklyGetHoldoutByIdConfig,
    LaunchDarklyGetHoldoutConfig,
    LaunchDarklyUpdateHoldoutConfig,
])
OPERATION_HANDLERS.update({
    "list_holdouts": _list_holdouts,
    "create_holdout": _create_holdout,
    "get_holdout_by_id": _get_holdout_by_id,
    "get_holdout": _get_holdout,
    "update_holdout": _update_holdout,
})

class LaunchDarklyListScheduledChangesConfig(BaseModel):
    """List scheduled changes for a feature flag in an environment."""
    operation: Literal["list_scheduled_changes"] = Field(
        "list_scheduled_changes",
        json_schema_extra={"const": "list_scheduled_changes", "ui:hidden": True,
                           "x-category": "Scheduled changes", "x-is-trigger": False,
                           "x-display-name": "List Scheduled Changes"},
        title="List Scheduled Changes",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()


async def _list_scheduled_changes(c, token, region) -> Dict[str, Any]:
    path = f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/scheduled-changes"
    return await _ld_request(token, region, "GET", path, action_name="list_scheduled_changes")


class LaunchDarklyCreateScheduledChangeConfig(BaseModel):
    """Create a scheduled changes workflow for a feature flag in an environment."""
    operation: Literal["create_scheduled_change"] = Field(
        "create_scheduled_change",
        json_schema_extra={"const": "create_scheduled_change", "ui:hidden": True,
                           "x-category": "Scheduled changes", "x-is-trigger": False,
                           "x-display-name": "Create Scheduled Change"},
        title="Create Scheduled Change",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    ignore_conflicts: Optional[str] = Field(None, title="Ignore Conflicts",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
        description="Whether to succeed even if this scheduled change conflicts with existing ones")
    execution_date: Optional[str] = Field(None, title="Execution Date",
        description="Unix timestamp (milliseconds) when the changes should execute")
    instructions_json: Optional[str] = Field(None, title="Instructions (JSON array)",
        description='Semantic-patch instructions array, e.g. [{"kind":"turnFlagOn"}]')
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _create_scheduled_change(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.execution_date is not None:
        body["executionDate"] = int(c.execution_date)
    if c.instructions_json is not None:
        body["instructions"] = json.loads(c.instructions_json)
    params = {"ignoreConflicts": c.ignore_conflicts}
    path = f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/scheduled-changes"
    return await _ld_request(token, region, "POST", path, params=params, json_body=body,
                             action_name="create_scheduled_change")


class LaunchDarklyGetScheduledChangeConfig(BaseModel):
    """Get a single scheduled change by ID."""
    operation: Literal["get_scheduled_change"] = Field(
        "get_scheduled_change",
        json_schema_extra={"const": "get_scheduled_change", "ui:hidden": True,
                           "x-category": "Scheduled changes", "x-is-trigger": False,
                           "x-display-name": "Get Scheduled Change"},
        title="Get Scheduled Change",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    id: str = Field(..., title="Scheduled Change ID", description="The scheduled change ID")


async def _get_scheduled_change(c, token, region) -> Dict[str, Any]:
    path = f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/scheduled-changes/{c.id}"
    return await _ld_request(token, region, "GET", path, action_name="get_scheduled_change")


class LaunchDarklyUpdateScheduledChangeConfig(BaseModel):
    """Update a scheduled changes workflow via semantic-patch instructions."""
    operation: Literal["update_scheduled_change"] = Field(
        "update_scheduled_change",
        json_schema_extra={"const": "update_scheduled_change", "ui:hidden": True,
                           "x-category": "Scheduled changes", "x-is-trigger": False,
                           "x-display-name": "Update Scheduled Change"},
        title="Update Scheduled Change",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    id: str = Field(..., title="Scheduled Change ID", description="The scheduled change ID")
    ignore_conflicts: Optional[str] = Field(None, title="Ignore Conflicts",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
        description="Whether to succeed even if this update conflicts with existing scheduled changes")
    instructions_json: str = Field(..., title="Instructions (JSON array)",
        description='Semantic-patch instructions array, e.g. [{"kind":"updateScheduledChanges","executionDate":0}]')
    comment: Optional[str] = Field(None, title="Comment")


async def _update_scheduled_change(c, token, region) -> Dict[str, Any]:
    body = {"comment": c.comment, "instructions": json.loads(c.instructions_json)}
    params = {"ignoreConflicts": c.ignore_conflicts}
    path = f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/scheduled-changes/{c.id}"
    return await _ld_request(token, region, "PATCH", path, params=params, json_body=body,
                             content_type=SEMANTIC_PATCH_CONTENT_TYPE,
                             action_name="update_scheduled_change")


class LaunchDarklyDeleteScheduledChangeConfig(BaseModel):
    """Delete a scheduled changes workflow."""
    operation: Literal["delete_scheduled_change"] = Field(
        "delete_scheduled_change",
        json_schema_extra={"const": "delete_scheduled_change", "ui:hidden": True,
                           "x-category": "Scheduled changes", "x-is-trigger": False,
                           "x-display-name": "Delete Scheduled Change"},
        title="Delete Scheduled Change",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    id: str = Field(..., title="Scheduled Change ID", description="The scheduled change ID")


async def _delete_scheduled_change(c, token, region) -> Dict[str, Any]:
    path = f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/scheduled-changes/{c.id}"
    return await _ld_request(token, region, "DELETE", path, action_name="delete_scheduled_change")


OPERATION_CONFIGS.extend([
    LaunchDarklyListScheduledChangesConfig,
    LaunchDarklyCreateScheduledChangeConfig,
    LaunchDarklyGetScheduledChangeConfig,
    LaunchDarklyUpdateScheduledChangeConfig,
    LaunchDarklyDeleteScheduledChangeConfig,
])
OPERATION_HANDLERS.update({
    "list_scheduled_changes": _list_scheduled_changes,
    "create_scheduled_change": _create_scheduled_change,
    "get_scheduled_change": _get_scheduled_change,
    "update_scheduled_change": _update_scheduled_change,
    "delete_scheduled_change": _delete_scheduled_change,
})

# ============================================================================
# Custom roles
# ============================================================================
class LaunchDarklyCreateRoleConfig(BaseModel):
    """Create a custom role."""
    operation: Literal["create_role"] = Field(
        "create_role",
        json_schema_extra={"const": "create_role", "x-creates-resource": True, "x-resource-type": "launchdarkly_custom_role", "x-resource-id-path": "data.key", "ui:hidden": True,
                           "x-category": "Custom roles", "x-is-trigger": False,
                           "x-display-name": "Create Custom Role"},
        title="Create Custom Role",
    )
    name: str = Field(..., title="Name", description="The name of the custom role")
    key: str = Field(..., title="Key", description="The unique key of the custom role")
    description: Optional[str] = Field(None, title="Description", description="Description of the custom role")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description='Optional raw JSON merged into the request body for advanced fields such as "policy", "basePermissions", or "assignedTo"')


async def _create_role(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"name": c.name, "key": c.key, "description": c.description})
    return await _ld_request(token, region, "POST", "/roles", json_body=body, action_name="create_role")


class LaunchDarklyGetRoleConfig(BaseModel):
    """Get a custom role by key."""
    operation: Literal["get_role"] = Field(
        "get_role",
        json_schema_extra={"const": "get_role", "ui:hidden": True,
                           "x-category": "Custom roles", "x-is-trigger": False,
                           "x-display-name": "Get Custom Role"},
        title="Get Custom Role",
    )
    custom_role_key: str = _role_key_field()


async def _get_role(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", f"/roles/{c.custom_role_key}", action_name="get_role")


class LaunchDarklyUpdateRoleConfig(BaseModel):
    """Update a custom role via JSON patch."""
    operation: Literal["update_role"] = Field(
        "update_role",
        json_schema_extra={"const": "update_role", "ui:hidden": True,
                           "x-category": "Custom roles", "x-is-trigger": False,
                           "x-display-name": "Update Custom Role"},
        title="Update Custom Role",
    )
    custom_role_key: str = _role_key_field("The custom role to update")
    patch_json: str = Field(..., title="Patch (JSON array)",
        description='JSON Patch array of operations, e.g. [{"op":"replace","path":"/name","value":"New name"}]')
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment describing the update")


async def _update_role(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = {"patch": json.loads(c.patch_json)}
    if c.comment is not None:
        body["comment"] = c.comment
    return await _ld_request(token, region, "PATCH", f"/roles/{c.custom_role_key}",
                             json_body=body, action_name="update_role")


class LaunchDarklyDeleteRoleConfig(BaseModel):
    """Delete a custom role."""
    operation: Literal["delete_role"] = Field(
        "delete_role",
        json_schema_extra={"const": "delete_role", "ui:hidden": True,
                           "x-category": "Custom roles", "x-is-trigger": False,
                           "x-display-name": "Delete Custom Role"},
        title="Delete Custom Role",
    )
    custom_role_key: str = _role_key_field("The custom role to delete")


async def _delete_role(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "DELETE", f"/roles/{c.custom_role_key}", action_name="delete_role")


OPERATION_CONFIGS.extend([
    LaunchDarklyCreateRoleConfig,
    LaunchDarklyGetRoleConfig,
    LaunchDarklyUpdateRoleConfig,
    LaunchDarklyDeleteRoleConfig,
])
OPERATION_HANDLERS.update({
    "create_role": _create_role,
    "get_role": _get_role,
    "update_role": _update_role,
    "delete_role": _delete_role,
})

class LaunchDarklyListUserFlagSettingsConfig(BaseModel):
    """List flag settings for a user."""
    operation: Literal["list_user_flag_settings"] = Field(
        "list_user_flag_settings",
        json_schema_extra={"const": "list_user_flag_settings", "ui:hidden": True,
                           "x-category": "User settings", "x-is-trigger": False,
                           "x-display-name": "List User Flag Settings"},
        title="List User Flag Settings",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    user_key: str = Field(..., title="User Key", description="The user key")


async def _list_user_flag_settings(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
        f"/users/{c.project_key}/{c.environment_key}/{c.user_key}/flags",
        action_name="list_user_flag_settings")


class LaunchDarklyGetUserFlagSettingConfig(BaseModel):
    """Get a single flag setting for a user."""
    operation: Literal["get_user_flag_setting"] = Field(
        "get_user_flag_setting",
        json_schema_extra={"const": "get_user_flag_setting", "ui:hidden": True,
                           "x-category": "User settings", "x-is-trigger": False,
                           "x-display-name": "Get User Flag Setting"},
        title="Get User Flag Setting",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    user_key: str = Field(..., title="User Key", description="The user key")
    feature_flag_key: str = _feature_flag_key_field()


async def _get_user_flag_setting(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
        f"/users/{c.project_key}/{c.environment_key}/{c.user_key}/flags/{c.feature_flag_key}",
        action_name="get_user_flag_setting")


class LaunchDarklyUpdateUserFlagSettingConfig(BaseModel):
    """Update a flag setting for a user."""
    operation: Literal["update_user_flag_setting"] = Field(
        "update_user_flag_setting",
        json_schema_extra={"const": "update_user_flag_setting", "ui:hidden": True,
                           "x-category": "User settings", "x-is-trigger": False,
                           "x-display-name": "Update User Flag Setting"},
        title="Update User Flag Setting",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    user_key: str = Field(..., title="User Key", description="The user key")
    feature_flag_key: str = _feature_flag_key_field()
    setting: Optional[str] = Field(None, title="Setting",
        description="The variation value to set for the user (must match the flag's variation type)")
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment describing the change")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields (e.g. a non-string setting value)")


async def _update_user_flag_setting(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.setting is not None:
        body["setting"] = c.setting
    if c.comment is not None:
        body["comment"] = c.comment
    return await _ld_request(token, region, "PUT",
        f"/users/{c.project_key}/{c.environment_key}/{c.user_key}/flags/{c.feature_flag_key}",
        json_body=body, action_name="update_user_flag_setting")


class LaunchDarklyGetExpiringUserTargetConfig(BaseModel):
    """Get expiring dates on flags for a user."""
    operation: Literal["get_expiring_user_target"] = Field(
        "get_expiring_user_target",
        json_schema_extra={"const": "get_expiring_user_target", "ui:hidden": True,
                           "x-category": "User settings", "x-is-trigger": False,
                           "x-display-name": "Get Expiring User Target"},
        title="Get Expiring User Target",
    )
    project_key: str = _project_key_field("The project key")
    user_key: str = Field(..., title="User Key", description="The user key")
    environment_key: str = _environment_key_field()


async def _get_expiring_user_target(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
        f"/users/{c.project_key}/{c.user_key}/expiring-user-targets/{c.environment_key}",
        action_name="get_expiring_user_target")


class LaunchDarklyUpdateExpiringUserTargetConfig(BaseModel):
    """Update expiring user targets for flags via instructions."""
    operation: Literal["update_expiring_user_target"] = Field(
        "update_expiring_user_target",
        json_schema_extra={"const": "update_expiring_user_target", "ui:hidden": True,
                           "x-category": "User settings", "x-is-trigger": False,
                           "x-display-name": "Update Expiring User Target"},
        title="Update Expiring User Target",
    )
    project_key: str = _project_key_field("The project key")
    user_key: str = Field(..., title="User Key", description="The user key")
    environment_key: str = _environment_key_field()
    instructions_json: str = Field(..., title="Instructions (JSON array)",
        description='Instructions to perform when updating, e.g. [{"kind":"removeExpireUserTargetDate","flagKey":"my-flag"}]')
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment describing the change")


async def _update_expiring_user_target(c, token, region) -> Dict[str, Any]:
    body = {"comment": c.comment, "instructions": json.loads(c.instructions_json)}
    return await _ld_request(token, region, "PATCH",
        f"/users/{c.project_key}/{c.user_key}/expiring-user-targets/{c.environment_key}",
        json_body=body, action_name="update_expiring_user_target")


OPERATION_CONFIGS.extend([
    LaunchDarklyListUserFlagSettingsConfig,
    LaunchDarklyGetUserFlagSettingConfig,
    LaunchDarklyUpdateUserFlagSettingConfig,
    LaunchDarklyGetExpiringUserTargetConfig,
    LaunchDarklyUpdateExpiringUserTargetConfig,
])
OPERATION_HANDLERS.update({
    "list_user_flag_settings": _list_user_flag_settings,
    "get_user_flag_setting": _get_user_flag_setting,
    "update_user_flag_setting": _update_user_flag_setting,
    "get_expiring_user_target": _get_expiring_user_target,
    "update_expiring_user_target": _update_expiring_user_target,
})

class LaunchDarklyGetWebhookConfig(BaseModel):
    """Get a single webhook by ID."""
    operation: Literal["get_webhook"] = Field(
        "get_webhook",
        json_schema_extra={"const": "get_webhook", "ui:hidden": True,
                           "x-category": "Webhooks", "x-is-trigger": False,
                           "x-display-name": "Get Webhook"},
        title="Get Webhook",
    )
    id: str = Field(..., title="Webhook ID", description="The ID of the webhook to fetch")


async def _get_webhook(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", f"/webhooks/{c.id}", action_name="get_webhook")


class LaunchDarklyUpdateWebhookConfig(BaseModel):
    """Update a webhook using a JSON Patch document."""
    operation: Literal["update_webhook"] = Field(
        "update_webhook",
        json_schema_extra={"const": "update_webhook", "ui:hidden": True,
                           "x-category": "Webhooks", "x-is-trigger": False,
                           "x-display-name": "Update Webhook"},
        title="Update Webhook",
    )
    id: str = Field(..., title="Webhook ID", description="The ID of the webhook to update")
    patch_json: str = Field(..., title="Patch (JSON array)",
        description='JSON Patch operations, e.g. [{"op":"replace","path":"/url","value":"https://example.com/hook"}]')


async def _update_webhook(c, token, region) -> Dict[str, Any]:
    body = json.loads(c.patch_json)
    return await _ld_request(token, region, "PATCH", f"/webhooks/{c.id}",
                             json_body=body, action_name="update_webhook")


OPERATION_CONFIGS.extend([
    LaunchDarklyGetWebhookConfig,
    LaunchDarklyUpdateWebhookConfig,
])
OPERATION_HANDLERS.update({
    "get_webhook": _get_webhook,
    "update_webhook": _update_webhook,
})

class LaunchDarklyListAuditLogEntriesConfig(BaseModel):
    """List audit log entries in the account."""
    operation: Literal["list_audit_log_entries"] = Field(
        "list_audit_log_entries",
        json_schema_extra={"const": "list_audit_log_entries", "ui:hidden": True,
                           "x-category": "Audit log", "x-is-trigger": False,
                           "x-display-name": "List Audit Log Entries"},
        title="List Audit Log Entries",
    )
    before: Optional[str] = Field(None, title="Before",
        description="Unix ms timestamp; filters entries before this time")
    after: Optional[str] = Field(None, title="After",
        description="Unix ms timestamp; filters entries after this time")
    q: Optional[str] = Field(None, title="Query", description="Text search across entries")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    spec: Optional[str] = Field(None, title="Spec",
        description="Resource specifier to filter entries")


async def _list_audit_log_entries(c, token, region) -> Dict[str, Any]:
    params = {"before": c.before, "after": c.after, "q": c.q,
              "limit": c.limit, "spec": c.spec}
    return await _ld_request(token, region, "GET", "/auditlog", params=params,
                             action_name="list_audit_log_entries")


class LaunchDarklySearchAuditLogEntriesConfig(BaseModel):
    """Search audit log entries using a list of policy statements."""
    operation: Literal["search_audit_log_entries"] = Field(
        "search_audit_log_entries",
        json_schema_extra={"const": "search_audit_log_entries", "ui:hidden": True,
                           "x-category": "Audit log", "x-is-trigger": False,
                           "x-display-name": "Search Audit Log Entries"},
        title="Search Audit Log Entries",
    )
    before: Optional[str] = Field(None, title="Before",
        description="Unix ms timestamp; filters entries before this time")
    after: Optional[str] = Field(None, title="After",
        description="Unix ms timestamp; filters entries after this time")
    q: Optional[str] = Field(None, title="Query", description="Text search across entries")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    body_json: Optional[str] = Field(None, title="Statements Body (JSON)",
        description='Raw JSON body of policy statements, e.g. {"statements":[{"effect":"allow","resources":["proj/*"],"actions":["*"]}]}')


async def _search_audit_log_entries(c, token, region) -> Dict[str, Any]:
    # Body is an optional policy StatementPostList; omit when absent (search via params).
    body = json.loads(c.body_json) if c.body_json else None
    params = {"before": c.before, "after": c.after, "q": c.q, "limit": c.limit}
    return await _ld_request(token, region, "POST", "/auditlog", params=params,
                             json_body=body, action_name="search_audit_log_entries")


class LaunchDarklyGetAuditLogEntryCountsConfig(BaseModel):
    """Get counts of audit log entries bucketed over a time range."""
    operation: Literal["get_audit_log_entry_counts"] = Field(
        "get_audit_log_entry_counts",
        json_schema_extra={"const": "get_audit_log_entry_counts", "ui:hidden": True,
                           "x-category": "Audit log", "x-is-trigger": False,
                           "x-display-name": "Get Audit Log Entry Counts"},
        title="Get Audit Log Entry Counts",
    )
    after: str = Field(..., title="After",
        description="Unix ms timestamp; start of the time range (required)")
    before: Optional[str] = Field(None, title="Before",
        description="Unix ms timestamp; end of the time range")
    buckets: Optional[str] = Field(None, title="Buckets",
        description="Number of time buckets to divide the range into")
    body_json: Optional[str] = Field(None, title="Statements Body (JSON)",
        description='Raw JSON body of policy statements, e.g. {"statements":[{"effect":"allow","resources":["proj/*"],"actions":["*"]}]}')


async def _get_audit_log_entry_counts(c, token, region) -> Dict[str, Any]:
    # Body is an optional policy StatementPostList (a JSON array); omit when absent.
    body = json.loads(c.body_json) if c.body_json else None
    params = {"after": c.after, "before": c.before, "buckets": c.buckets}
    return await _ld_request(token, region, "POST", "/auditlog/counts", params=params,
                             json_body=body, action_name="get_audit_log_entry_counts")


class LaunchDarklyGetAuditLogEntryConfig(BaseModel):
    """Get a single audit log entry by ID."""
    operation: Literal["get_audit_log_entry"] = Field(
        "get_audit_log_entry",
        json_schema_extra={"const": "get_audit_log_entry", "ui:hidden": True,
                           "x-category": "Audit log", "x-is-trigger": False,
                           "x-display-name": "Get Audit Log Entry"},
        title="Get Audit Log Entry",
    )
    id: str = Field(..., title="Entry ID", description="The audit log entry ID")


async def _get_audit_log_entry(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET", f"/auditlog/{c.id}",
                             action_name="get_audit_log_entry")


OPERATION_CONFIGS.extend([
    LaunchDarklyListAuditLogEntriesConfig,
    LaunchDarklySearchAuditLogEntriesConfig,
    LaunchDarklyGetAuditLogEntryCountsConfig,
    LaunchDarklyGetAuditLogEntryConfig,
])
OPERATION_HANDLERS.update({
    "list_audit_log_entries": _list_audit_log_entries,
    "search_audit_log_entries": _search_audit_log_entries,
    "get_audit_log_entry_counts": _get_audit_log_entry_counts,
    "get_audit_log_entry": _get_audit_log_entry,
})

# ---- Follow flags category ------------------------------------------------
class LaunchDarklyListEnvironmentFollowersConfig(BaseModel):
    """Get followers of all flags in a given project and environment."""
    operation: Literal["list_environment_followers"] = Field(
        "list_environment_followers",
        json_schema_extra={"const": "list_environment_followers", "ui:hidden": True,
                           "x-category": "Follow flags", "x-is-trigger": False,
                           "x-display-name": "List Environment Flag Followers"},
        title="List Environment Flag Followers",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()


async def _list_environment_followers(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/projects/{c.project_key}/environments/{c.environment_key}/followers",
                             action_name="list_environment_followers")


class LaunchDarklyListFlagFollowersConfig(BaseModel):
    """Get followers of a flag in a project and environment."""
    operation: Literal["list_flag_followers"] = Field(
        "list_flag_followers",
        json_schema_extra={"const": "list_flag_followers", "ui:hidden": True,
                           "x-category": "Follow flags", "x-is-trigger": False,
                           "x-display-name": "List Flag Followers"},
        title="List Flag Followers",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()


async def _list_flag_followers(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/followers",
                             action_name="list_flag_followers")


class LaunchDarklyAddFlagFollowerConfig(BaseModel):
    """Add a member as a follower of a flag in a project and environment."""
    operation: Literal["add_flag_follower"] = Field(
        "add_flag_follower",
        json_schema_extra={"const": "add_flag_follower", "ui:hidden": True,
                           "x-category": "Follow flags", "x-is-trigger": False,
                           "x-display-name": "Add Flag Follower"},
        title="Add Flag Follower",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    member_id: str = _member_id_field("The member to add as a follower")


async def _add_flag_follower(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "PUT",
                             f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/followers/{c.member_id}",
                             action_name="add_flag_follower")


class LaunchDarklyRemoveFlagFollowerConfig(BaseModel):
    """Remove a member as a follower of a flag in a project and environment."""
    operation: Literal["remove_flag_follower"] = Field(
        "remove_flag_follower",
        json_schema_extra={"const": "remove_flag_follower", "ui:hidden": True,
                           "x-category": "Follow flags", "x-is-trigger": False,
                           "x-display-name": "Remove Flag Follower"},
        title="Remove Flag Follower",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    member_id: str = _member_id_field("The member to remove as a follower")


async def _remove_flag_follower(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "DELETE",
                             f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/followers/{c.member_id}",
                             action_name="remove_flag_follower")


OPERATION_CONFIGS.extend([
    LaunchDarklyListEnvironmentFollowersConfig,
    LaunchDarklyListFlagFollowersConfig,
    LaunchDarklyAddFlagFollowerConfig,
    LaunchDarklyRemoveFlagFollowerConfig,
])
OPERATION_HANDLERS.update({
    "list_environment_followers": _list_environment_followers,
    "list_flag_followers": _list_flag_followers,
    "add_flag_follower": _add_flag_follower,
    "remove_flag_follower": _remove_flag_follower,
})

class LaunchDarklyListWorkflowsConfig(BaseModel):
    """List workflows for a feature flag in an environment."""
    operation: Literal["list_workflows"] = Field(
        "list_workflows",
        json_schema_extra={"const": "list_workflows", "ui:hidden": True,
                           "x-category": "Workflows", "x-is-trigger": False,
                           "x-display-name": "List Workflows"},
        title="List Workflows",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    status: Optional[str] = Field(None, title="Status", description="Filter by workflow status (active, completed, failed)")
    sort: Optional[str] = Field(None, title="Sort", description="Field to sort workflows by")
    limit: Optional[str] = Field(None, title="Limit", description="Max number of workflows to return")
    offset: Optional[str] = Field(None, title="Offset", description="Pagination offset")


async def _list_workflows(c, token, region) -> Dict[str, Any]:
    params = {"status": c.status, "sort": c.sort, "limit": c.limit, "offset": c.offset}
    return await _ld_request(
        token, region, "GET",
        f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/workflows",
        params=params, action_name="list_workflows")


class LaunchDarklyCreateWorkflowConfig(BaseModel):
    """Create a workflow for a feature flag in an environment."""
    operation: Literal["create_workflow"] = Field(
        "create_workflow",
        json_schema_extra={"const": "create_workflow", "ui:hidden": True,
                           "x-category": "Workflows", "x-is-trigger": False,
                           "x-display-name": "Create Workflow"},
        title="Create Workflow",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    name: str = Field(..., title="Name", description="The workflow name")
    description: Optional[str] = Field(None, title="Description", description="The workflow description")
    maintainer_id: Optional[str] = Field(None, title="Maintainer ID", description="The ID of the workflow maintainer")
    template_key: Optional[str] = Field(None, title="Template Key",
        description="Key of a workflow template to create the workflow from")
    dry_run: Optional[str] = Field(None, title="Dry Run",
        description="Validate the workflow without creating it",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields such as stages")


async def _create_workflow(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"name": c.name, "description": c.description, "maintainerId": c.maintainer_id})
    params = {"templateKey": c.template_key, "dryRun": c.dry_run}
    return await _ld_request(
        token, region, "POST",
        f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/workflows",
        params=params, json_body=body, action_name="create_workflow")


class LaunchDarklyGetWorkflowConfig(BaseModel):
    """Get a custom workflow by ID."""
    operation: Literal["get_workflow"] = Field(
        "get_workflow",
        json_schema_extra={"const": "get_workflow", "ui:hidden": True,
                           "x-category": "Workflows", "x-is-trigger": False,
                           "x-display-name": "Get Workflow"},
        title="Get Workflow",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    workflow_id: str = Field(..., title="Workflow ID", description="The workflow ID")


async def _get_workflow(c, token, region) -> Dict[str, Any]:
    return await _ld_request(
        token, region, "GET",
        f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/workflows/{c.workflow_id}",
        action_name="get_workflow")


class LaunchDarklyDeleteWorkflowConfig(BaseModel):
    """Delete a workflow by ID."""
    operation: Literal["delete_workflow"] = Field(
        "delete_workflow",
        json_schema_extra={"const": "delete_workflow", "ui:hidden": True,
                           "x-category": "Workflows", "x-is-trigger": False,
                           "x-display-name": "Delete Workflow"},
        title="Delete Workflow",
    )
    project_key: str = _project_key_field("The project key")
    feature_flag_key: str = _feature_flag_key_field()
    environment_key: str = _environment_key_field()
    workflow_id: str = Field(..., title="Workflow ID", description="The workflow ID")


async def _delete_workflow(c, token, region) -> Dict[str, Any]:
    return await _ld_request(
        token, region, "DELETE",
        f"/projects/{c.project_key}/flags/{c.feature_flag_key}/environments/{c.environment_key}/workflows/{c.workflow_id}",
        action_name="delete_workflow")


OPERATION_CONFIGS.extend([
    LaunchDarklyListWorkflowsConfig,
    LaunchDarklyCreateWorkflowConfig,
    LaunchDarklyGetWorkflowConfig,
    LaunchDarklyDeleteWorkflowConfig,
])
OPERATION_HANDLERS.update({
    "list_workflows": _list_workflows,
    "create_workflow": _create_workflow,
    "get_workflow": _get_workflow,
    "delete_workflow": _delete_workflow,
})

class LaunchDarklySearchUsersConfig(BaseModel):
    """Find users in a project environment."""
    operation: Literal["search_users"] = Field(
        "search_users",
        json_schema_extra={"const": "search_users", "ui:hidden": True,
                           "x-category": "Users", "x-is-trigger": False,
                           "x-display-name": "Find Users"},
        title="Find Users",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    q: Optional[str] = Field(None, title="Query", description="Search query text")
    limit: Optional[str] = Field(None, title="Limit", description="Max results per page")
    search_after: Optional[str] = Field(None, title="Search After",
        description="Pagination cursor limiting results to those after this value")
    filter: Optional[str] = Field(None, title="Filter", description="Comma-separated filter criteria")


async def _search_users(c, token, region) -> Dict[str, Any]:
    params = {"q": c.q, "limit": c.limit, "searchAfter": c.search_after, "filter": c.filter}
    return await _ld_request(token, region, "GET",
                             f"/user-search/{c.project_key}/{c.environment_key}",
                             params=params, action_name="search_users")


class LaunchDarklyListUsersConfig(BaseModel):
    """List users in a project environment."""
    operation: Literal["list_users"] = Field(
        "list_users",
        json_schema_extra={"const": "list_users", "ui:hidden": True,
                           "x-category": "Users", "x-is-trigger": False,
                           "x-display-name": "List Users"},
        title="List Users",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    limit: Optional[str] = Field(None, title="Limit", description="Max results per page")
    search_after: Optional[str] = Field(None, title="Search After",
        description="Pagination cursor limiting results to those after this value")


async def _list_users(c, token, region) -> Dict[str, Any]:
    params = {"limit": c.limit, "searchAfter": c.search_after}
    return await _ld_request(token, region, "GET",
                             f"/users/{c.project_key}/{c.environment_key}",
                             params=params, action_name="list_users")


class LaunchDarklyGetUserConfig(BaseModel):
    """Get a single user in a project environment."""
    operation: Literal["get_user"] = Field(
        "get_user",
        json_schema_extra={"const": "get_user", "ui:hidden": True,
                           "x-category": "Users", "x-is-trigger": False,
                           "x-display-name": "Get User"},
        title="Get User",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    user_key: str = Field(..., title="User Key", description="The user key")


async def _get_user(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "GET",
                             f"/users/{c.project_key}/{c.environment_key}/{c.user_key}",
                             action_name="get_user")


class LaunchDarklyDeleteUserConfig(BaseModel):
    """Delete a user from a project environment."""
    operation: Literal["delete_user"] = Field(
        "delete_user",
        json_schema_extra={"const": "delete_user", "ui:hidden": True,
                           "x-category": "Users", "x-is-trigger": False,
                           "x-display-name": "Delete User"},
        title="Delete User",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    user_key: str = Field(..., title="User Key", description="The user key")


async def _delete_user(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "DELETE",
                             f"/users/{c.project_key}/{c.environment_key}/{c.user_key}",
                             action_name="delete_user")


OPERATION_CONFIGS.extend([
    LaunchDarklySearchUsersConfig,
    LaunchDarklyListUsersConfig,
    LaunchDarklyGetUserConfig,
    LaunchDarklyDeleteUserConfig,
])
OPERATION_HANDLERS.update({
    "search_users": _search_users,
    "list_users": _list_users,
    "get_user": _get_user,
    "delete_user": _delete_user,
})

# ============================== Announcements ==============================
class LaunchDarklyListAnnouncementsConfig(BaseModel):
    """List announcements in the account."""
    operation: Literal["list_announcements"] = Field(
        "list_announcements",
        json_schema_extra={"const": "list_announcements", "ui:hidden": True,
                           "x-category": "Announcements", "x-is-trigger": False,
                           "x-display-name": "Get Announcements"},
        title="Get Announcements",
    )
    status: Optional[str] = Field(None, title="Status",
        description="Filter by announcement status (e.g. active, inactive, scheduled)")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    offset: Optional[str] = Field(None, title="Offset", description="Pagination offset")


async def _list_announcements(c, token, region) -> Dict[str, Any]:
    params = {"status": c.status, "limit": c.limit, "offset": c.offset}
    return await _ld_request(token, region, "GET", "/announcements", params=params,
                             action_name="list_announcements")


class LaunchDarklyCreateAnnouncementConfig(BaseModel):
    """Create an announcement."""
    operation: Literal["create_announcement"] = Field(
        "create_announcement",
        json_schema_extra={"const": "create_announcement", "ui:hidden": True,
                           "x-category": "Announcements", "x-is-trigger": False,
                           "x-display-name": "Create Announcement"},
        title="Create Announcement",
    )
    title: str = Field(..., title="Title", description="Announcement title")
    message: str = Field(..., title="Message", description="Announcement message body")
    severity: str = Field(..., title="Severity", description="Announcement severity",
        json_schema_extra={"enum": ["info", "warning", "critical"], "x-enum-searchable": True})
    start_time: str = Field(..., title="Start Time",
        description="Start time as Unix epoch milliseconds")
    end_time: Optional[str] = Field(None, title="End Time",
        description="End time as Unix epoch milliseconds")
    is_dismissible: str = Field("true", title="Is Dismissible",
        description="Whether users can dismiss the announcement",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _create_announcement(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({
        "title": c.title,
        "message": c.message,
        "severity": c.severity,
        "startTime": int(c.start_time),
        "endTime": int(c.end_time) if c.end_time else None,
        "isDismissible": c.is_dismissible == "true",
    })
    return await _ld_request(token, region, "POST", "/announcements", json_body=body,
                             action_name="create_announcement")


class LaunchDarklyUpdateAnnouncementConfig(BaseModel):
    """Update an announcement via JSON Patch."""
    operation: Literal["update_announcement"] = Field(
        "update_announcement",
        json_schema_extra={"const": "update_announcement", "ui:hidden": True,
                           "x-category": "Announcements", "x-is-trigger": False,
                           "x-display-name": "Update Announcement"},
        title="Update Announcement",
    )
    announcement_id: str = Field(..., title="Announcement ID",
        description="The announcement to update")
    patch_json: str = Field(..., title="Patch (JSON array)",
        description='JSON Patch array, e.g. [{"op":"replace","path":"/message","value":"..."}]')


async def _update_announcement(c, token, region) -> Dict[str, Any]:
    body = json.loads(c.patch_json)
    return await _ld_request(token, region, "PATCH", f"/announcements/{c.announcement_id}",
                             json_body=body, action_name="update_announcement")


class LaunchDarklyDeleteAnnouncementConfig(BaseModel):
    """Delete an announcement."""
    operation: Literal["delete_announcement"] = Field(
        "delete_announcement",
        json_schema_extra={"const": "delete_announcement", "ui:hidden": True,
                           "x-category": "Announcements", "x-is-trigger": False,
                           "x-display-name": "Delete Announcement"},
        title="Delete Announcement",
    )
    announcement_id: str = Field(..., title="Announcement ID",
        description="The announcement to delete")


async def _delete_announcement(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "DELETE", f"/announcements/{c.announcement_id}",
                             action_name="delete_announcement")


OPERATION_CONFIGS.extend([
    LaunchDarklyListAnnouncementsConfig,
    LaunchDarklyCreateAnnouncementConfig,
    LaunchDarklyUpdateAnnouncementConfig,
    LaunchDarklyDeleteAnnouncementConfig,
])
OPERATION_HANDLERS.update({
    "list_announcements": _list_announcements,
    "create_announcement": _create_announcement,
    "update_announcement": _update_announcement,
    "delete_announcement": _delete_announcement,
})

# ============================== Layers ======================================
class LaunchDarklyListLayersConfig(BaseModel):
    """List layers in a project."""
    operation: Literal["list_layers"] = Field(
        "list_layers",
        json_schema_extra={"const": "list_layers", "ui:hidden": True,
                           "x-category": "Layers", "x-is-trigger": False,
                           "x-display-name": "List Layers"},
        title="List Layers",
    )
    project_key: str = _project_key_field("The project containing the layers")
    filter: Optional[str] = Field(None, title="Filter",
        description="A comma-separated list of filters to apply")


async def _list_layers(c, token, region) -> Dict[str, Any]:
    params = {"filter": c.filter}
    return await _ld_request(token, region, "GET",
                             f"/projects/{c.project_key}/layers",
                             params=params, action_name="list_layers")


class LaunchDarklyCreateLayerConfig(BaseModel):
    """Create a layer in a project."""
    operation: Literal["create_layer"] = Field(
        "create_layer",
        json_schema_extra={"const": "create_layer", "ui:hidden": True,
                           "x-category": "Layers", "x-is-trigger": False,
                           "x-display-name": "Create Layer"},
        title="Create Layer",
    )
    project_key: str = _project_key_field("The project to create the layer in")
    key: str = Field(..., title="Key", description="Unique identifier for the layer")
    name: str = Field(..., title="Name", description="Layer name")
    description: str = Field(..., title="Description", description="Layer description")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _create_layer(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"key": c.key, "name": c.name, "description": c.description})
    return await _ld_request(token, region, "POST",
                             f"/projects/{c.project_key}/layers",
                             json_body=body, action_name="create_layer")


class LaunchDarklyUpdateLayerConfig(BaseModel):
    """Update a layer via semantic-patch instructions."""
    operation: Literal["update_layer"] = Field(
        "update_layer",
        json_schema_extra={"const": "update_layer", "ui:hidden": True,
                           "x-category": "Layers", "x-is-trigger": False,
                           "x-display-name": "Update Layer"},
        title="Update Layer",
    )
    project_key: str = _project_key_field("The project containing the layer")
    layer_key: str = Field(..., title="Layer Key", description="The layer to update")
    instructions_json: str = Field(..., title="Instructions (JSON array)",
        description='Semantic-patch instructions, e.g. [{"kind":"updateName","name":"Updated layer name"}]')
    environment_key: Optional[str] = _environment_key_field(required=False, description="Optional: the environment for environment-specific updates")
    comment: Optional[str] = Field(None, title="Comment")


async def _update_layer(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = {"comment": c.comment,
                            "instructions": json.loads(c.instructions_json)}
    if c.environment_key:
        body["environmentKey"] = c.environment_key
    return await _ld_request(token, region, "PATCH",
                             f"/projects/{c.project_key}/layers/{c.layer_key}",
                             json_body=body, content_type=SEMANTIC_PATCH_CONTENT_TYPE,
                             action_name="update_layer")


OPERATION_CONFIGS.extend([
    LaunchDarklyListLayersConfig,
    LaunchDarklyCreateLayerConfig,
    LaunchDarklyUpdateLayerConfig,
])
OPERATION_HANDLERS.update({
    "list_layers": _list_layers,
    "create_layer": _create_layer,
    "update_layer": _update_layer,
})

# ============================ Workflow templates ============================
class LaunchDarklyListWorkflowTemplatesConfig(BaseModel):
    """Get workflow templates in the account."""
    operation: Literal["list_workflow_templates"] = Field(
        "list_workflow_templates",
        json_schema_extra={"const": "list_workflow_templates", "ui:hidden": True,
                           "x-category": "Workflow templates", "x-is-trigger": False,
                           "x-display-name": "Get Workflow Templates"},
        title="Get Workflow Templates",
    )
    summary: Optional[str] = Field(None, title="Summary",
        description="Whether to return a summarized view of the templates (true/false)")
    search: Optional[str] = Field(None, title="Search",
        description="A search query to filter templates by name")


async def _list_workflow_templates(c, token, region) -> Dict[str, Any]:
    params = {"summary": c.summary, "search": c.search}
    return await _ld_request(token, region, "GET", "/templates", params=params,
                             action_name="list_workflow_templates")


class LaunchDarklyCreateWorkflowTemplateConfig(BaseModel):
    """Create a workflow template."""
    operation: Literal["create_workflow_template"] = Field(
        "create_workflow_template",
        json_schema_extra={"const": "create_workflow_template", "ui:hidden": True,
                           "x-category": "Workflow templates", "x-is-trigger": False,
                           "x-display-name": "Create Workflow Template"},
        title="Create Workflow Template",
    )
    name: str = Field(..., title="Name", description="The template name")
    key: str = Field(..., title="Key", description="The template key")
    description: Optional[str] = Field(None, title="Description",
        description="A description of the template")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields "
                    "such as the source workflow (workflowId/projectKey/environmentKey/flagKey/stages)")


async def _create_workflow_template(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    body.update({"name": c.name, "key": c.key, "description": c.description})
    return await _ld_request(token, region, "POST", "/templates", json_body=body,
                             action_name="create_workflow_template")


class LaunchDarklyDeleteWorkflowTemplateConfig(BaseModel):
    """Delete a workflow template."""
    operation: Literal["delete_workflow_template"] = Field(
        "delete_workflow_template",
        json_schema_extra={"const": "delete_workflow_template", "ui:hidden": True,
                           "x-category": "Workflow templates", "x-is-trigger": False,
                           "x-display-name": "Delete Workflow Template"},
        title="Delete Workflow Template",
    )
    template_key: str = Field(..., title="Template Key",
        description="The key of the workflow template to delete")


async def _delete_workflow_template(c, token, region) -> Dict[str, Any]:
    return await _ld_request(token, region, "DELETE", f"/templates/{c.template_key}",
                             action_name="delete_workflow_template")


OPERATION_CONFIGS.extend([
    LaunchDarklyListWorkflowTemplatesConfig,
    LaunchDarklyCreateWorkflowTemplateConfig,
    LaunchDarklyDeleteWorkflowTemplateConfig,
])
OPERATION_HANDLERS.update({
    "list_workflow_templates": _list_workflow_templates,
    "create_workflow_template": _create_workflow_template,
    "delete_workflow_template": _delete_workflow_template,
})

class LaunchDarklyUpdateContextFlagSettingConfig(BaseModel):
    """Update the flag setting for a specific context."""
    operation: Literal["update_context_flag_setting"] = Field(
        "update_context_flag_setting",
        json_schema_extra={"const": "update_context_flag_setting", "ui:hidden": True,
                           "x-category": "Context settings", "x-is-trigger": False,
                           "x-display-name": "Update Flag Settings For Context"},
        title="Update Flag Settings For Context",
    )
    project_key: str = _project_key_field("The project key")
    environment_key: str = _environment_key_field()
    context_kind: str = Field(..., title="Context Kind", description="The context kind")
    context_key: str = Field(..., title="Context Key", description="The context key")
    feature_flag_key: str = _feature_flag_key_field()
    setting_json: Optional[str] = Field(None, title="Setting (JSON)",
        description='The variation value to set for the context, as JSON (e.g. "value", true, 3). Set to JSON null to clear.')
    comment: Optional[str] = Field(None, title="Comment", description="Optional comment describing the change")
    body_json: Optional[str] = Field(None, title="Extra Body (JSON)",
        description="Optional raw JSON merged into the request body for advanced fields")


async def _update_context_flag_setting(c, token, region) -> Dict[str, Any]:
    body: Dict[str, Any] = json.loads(c.body_json) if c.body_json else {}
    if c.setting_json is not None:
        body["setting"] = json.loads(c.setting_json)
    if c.comment is not None:
        body["comment"] = c.comment
    path = (f"/projects/{c.project_key}/environments/{c.environment_key}"
            f"/contexts/{c.context_kind}/{c.context_key}/flags/{c.feature_flag_key}")
    return await _ld_request(token, region, "PUT", path, json_body=body,
                             action_name="update_context_flag_setting")


OPERATION_CONFIGS.extend([
    LaunchDarklyUpdateContextFlagSettingConfig,
])
OPERATION_HANDLERS.update({
    "update_context_flag_setting": _update_context_flag_setting,
})

class LaunchDarklyListTagsConfig(BaseModel):
    """List all tags in the account."""
    operation: Literal["list_tags"] = Field(
        "list_tags",
        json_schema_extra={"const": "list_tags", "ui:hidden": True,
                           "x-category": "Tags", "x-is-trigger": False,
                           "x-display-name": "List Tags"},
        title="List Tags",
    )
    kind: Optional[str] = Field(None, title="Kind",
        description="Filter by tag kind (e.g. flag, segment, project, environment)")
    pre: Optional[str] = Field(None, title="Prefix",
        description="Return tags with the given prefix")
    archived: Optional[str] = Field(None, title="Archived",
        description="Whether to include tags on archived resources",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    limit: Optional[str] = Field(None, title="Limit", description="Max number of tags to return")
    offset: Optional[str] = Field(None, title="Offset", description="Pagination offset")
    as_of: Optional[str] = Field(None, title="As Of",
        description="Return tags as they were at this point in time")


async def _list_tags(c, token, region) -> Dict[str, Any]:
    params = {"kind": c.kind, "pre": c.pre, "archived": c.archived,
              "limit": c.limit, "offset": c.offset, "asOf": c.as_of}
    return await _ld_request(token, region, "GET", "/tags", params=params, action_name="list_tags")


OPERATION_CONFIGS.extend([
    LaunchDarklyListTagsConfig,
])
OPERATION_HANDLERS.update({
    "list_tags": _list_tags,
})


# Webhook event-type selection.
#
# LaunchDarkly delivers ALL account activity to a single webhook URL and filters
# it with an optional `statements` policy (same syntax as custom roles: a list of
# {resources, actions, effect}). Each payload mirrors an audit-log entry — a
# top-level `kind` plus an `accesses` array of {action, resource}.
#
# We expose a user-friendly event_types selector. Each value maps to BOTH:
#   1. a policy `statement` passed to POST /webhooks (provider-side filter), and
#   2. an action-prefix matched at runtime in `filter_trigger_payload` against
#      the inbound payload's `accesses[].action` (belt-and-suspenders, in case
#      the provider webhook policy was edited out-of-band).
#
# `actions` use LaunchDarkly's glob syntax (e.g. `createFlag`, `update*`).
# `action_prefixes` are the runtime substrings we accept (case-insensitive) in
# any `accesses[].action`; an empty list means "accept all" (used by `*`).
# Each event:
#   statement       - the policy passed to POST /webhooks (None = no filter).
#   actions         - exact LaunchDarkly action verbs (lowercased) accepted at
#                     runtime. Empty + resource_kind set => any action on that kind.
#   resource_kind   - the `:<kind>/` segment that must appear in a delivery's
#                     `accesses[].resource` (audit-log shaped). Anchors the
#                     runtime filter to the right resource so e.g. a flag-update
#                     trigger never matches an `updateProjectName` on a project.
LD_WEBHOOK_EVENTS: Dict[str, Dict[str, Any]] = {
    "*": {
        "label": "All account activity",
        "statement": None,  # no policy -> LaunchDarkly sends everything
        "actions": [],
        "resource_kind": None,
    },
    "flag.created": {
        "label": "Feature flag created",
        "statement": {"resources": ["proj/*:env/*:flag/*"], "actions": ["createFlag"], "effect": "allow"},
        "actions": ["createflag"],
        "resource_kind": "flag",
    },
    "flag.deleted": {
        "label": "Feature flag deleted",
        "statement": {"resources": ["proj/*:env/*:flag/*"], "actions": ["deleteFlag"], "effect": "allow"},
        "actions": ["deleteflag"],
        "resource_kind": "flag",
    },
    "flag.toggled": {
        "label": "Feature flag turned on/off",
        "statement": {"resources": ["proj/*:env/*:flag/*"], "actions": ["updateOn"], "effect": "allow"},
        "actions": ["updateon"],
        "resource_kind": "flag",
    },
    "flag.updated": {
        "label": "Feature flag updated (any change)",
        "statement": {"resources": ["proj/*:env/*:flag/*"], "actions": ["*Flag", "update*"], "effect": "allow"},
        "actions": [],  # any action on a flag resource
        "resource_kind": "flag",
    },
    "project.changed": {
        "label": "Project created/updated/deleted",
        "statement": {"resources": ["proj/*"], "actions": ["*Project", "updateProject*"], "effect": "allow"},
        "actions": [],
        "resource_kind": "proj",
    },
    "environment.changed": {
        "label": "Environment created/updated/deleted",
        "statement": {"resources": ["proj/*:env/*"], "actions": ["*Environment", "updateEnvironment*"], "effect": "allow"},
        "actions": [],
        "resource_kind": "env",
    },
    "segment.changed": {
        "label": "Segment created/updated/deleted",
        "statement": {"resources": ["proj/*:env/*:segment/*"], "actions": ["*Segment", "update*"], "effect": "allow"},
        "actions": [],
        "resource_kind": "segment",
    },
    "member.changed": {
        "label": "Account member invited/updated/removed",
        "statement": {"resources": ["member/*"], "actions": ["*Member", "createMember*", "updateMember*"], "effect": "allow"},
        "actions": [],
        "resource_kind": "member",
    },
    "webhook.changed": {
        "label": "Webhook created/updated/deleted",
        "statement": {"resources": ["webhook/*"], "actions": ["*Webhook"], "effect": "allow"},
        "actions": [],
        "resource_kind": "webhook",
    },
}

LD_WEBHOOK_EVENT_KEYS = list(LD_WEBHOOK_EVENTS.keys())
LD_WEBHOOK_EVENT_LABELS = [LD_WEBHOOK_EVENTS[k]["label"] for k in LD_WEBHOOK_EVENT_KEYS]


def _selected_event_keys(config: Dict[str, Any]) -> List[str]:
    """Parse the trigger's event_types selection into a list of known keys.

    Accepts a comma-separated string (multi-select) or a single value. Unknown
    keys are dropped; an empty/"*"-containing selection means all events.
    """
    raw = (config or {}).get("event_types")
    if not raw:
        return ["*"]
    if isinstance(raw, (list, tuple)):
        parts = [str(p).strip() for p in raw]
    else:
        parts = [p.strip() for p in str(raw).split(",")]
    keys = [p for p in parts if p in LD_WEBHOOK_EVENTS]
    if not keys or "*" in keys:
        return ["*"]
    return keys


def _resource_kind(resource: str) -> Optional[str]:
    """The kind of the most-specific (last) segment of an audit-log resource.

    LaunchDarkly resources are hierarchical, e.g.
    ``proj/d:env/p:flag/my-flag`` -> the acted-on resource is ``flag``, even
    though ``proj`` and ``env`` appear as parent segments. Returns the kind
    before the final ``/`` (``flag``, ``proj``, ``env``, ``segment`` ...).
    """
    last = resource.rsplit(":", 1)[-1]
    return last.split("/", 1)[0] if "/" in last else None


# ============================================================================
# Credential Schema
# ============================================================================


class LaunchDarklyTokenCredential(BaseModel):
    """API access token credential for LaunchDarkly."""

    credential_type: Literal["launchdarkly_token"] = Field(
        "launchdarkly_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="API Access Token",
        description="A personal or service access token from Account settings -> Authorization. Sent raw (no Bearer prefix). SDK/mobile keys do NOT work.",
        json_schema_extra={"ui:widget": "password"},
    )
    region: str = Field(
        "commercial",
        title="Region",
        description="LaunchDarkly data residency / hosting region. Must match where your account lives.",
        json_schema_extra={
            "enum": ["commercial", "eu", "federal"],
            "enumNames": ["Commercial (app.launchdarkly.com)", "EU (app.eu.launchdarkly.com)", "Federal (app.launchdarkly.us)"],
            "x-enum-searchable": True,
        },
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://app.launchdarkly.com/settings/authorization",
            "x-credential-instructions": "Account settings -> Authorization -> Create token. Use a personal or service token (Reader/Writer/Admin scope as needed). SDK, mobile, and client-side keys cannot access the REST API.",
        }
    )


LaunchDarklyCredential = LaunchDarklyTokenCredential


# ============================================================================
# Operation Configs — Feature Flags
# ============================================================================


class LaunchDarklyListFlagsConfig(BaseModel):
    """List all feature flags in a project."""

    operation: Literal["list_flags"] = Field(
        "list_flags",
        json_schema_extra={
            "const": "list_flags",
            "ui:hidden": True,
            "x-category": "Feature Flags",
            "x-is-trigger": False,
            "x-display-name": "List Feature Flags",
        },
        title="List Feature Flags",
    )
    project_key: str = Field(
        ...,
        title="Project",
        description="The project to list flags from",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_key",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project key",
            }
        },
    )
    env: Optional[str] = Field(
        None, title="Environment Key", description="Optional environment key to include env-specific config"
    )
    tag: Optional[str] = Field(
        None, title="Tag", description="Filter flags by tag"
    )
    limit: Optional[str] = Field(
        "50", title="Limit", description="Max number of flags to return"
    )


class LaunchDarklyGetFlagConfig(BaseModel):
    """Get a single feature flag's configuration and targeting."""

    operation: Literal["get_flag"] = Field(
        "get_flag",
        json_schema_extra={
            "const": "get_flag",
            "ui:hidden": True,
            "x-category": "Feature Flags",
            "x-is-trigger": False,
            "x-display-name": "Get Feature Flag",
        },
        title="Get Feature Flag",
    )
    project_key: str = Field(
        ...,
        title="Project",
        description="The project containing the flag",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_key",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project key",
            }
        },
    )
    feature_flag_key: str = _feature_flag_key_field(description="The key of the feature flag to retrieve")
    env: Optional[str] = Field(
        None, title="Environment Key", description="Optional environment key to filter the returned config"
    )


class LaunchDarklyCreateFlagConfig(BaseModel):
    """Create a new feature flag in a project."""

    operation: Literal["create_flag"] = Field(
        "create_flag",
        json_schema_extra={
            "const": "create_flag",
            "x-creates-resource": True,
            "x-resource-type": "launchdarkly_flag",
            "x-resource-id-path": "data.key",
            "ui:hidden": True,
            "x-category": "Feature Flags",
            "x-is-trigger": False,
            "x-display-name": "Create Feature Flag",
        },
        title="Create Feature Flag",
    )
    project_key: str = Field(
        ...,
        title="Project",
        description="The project to create the flag in",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_key",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project key",
            }
        },
    )
    name: str = Field(..., title="Name", description="Human-readable flag name")
    key: str = Field(..., title="Key", description="Unique flag key (used in code)")
    description: Optional[str] = Field(
        None, title="Description", description="Optional flag description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="Comma-separated tags"
    )
    temporary: str = Field(
        "false",
        title="Temporary",
        description="Mark the flag as temporary (slated for removal)",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class LaunchDarklyUpdateFlagConfig(BaseModel):
    """Toggle a feature flag on or off in an environment (semantic patch)."""

    operation: Literal["update_flag"] = Field(
        "update_flag",
        json_schema_extra={
            "const": "update_flag",
            "ui:hidden": True,
            "x-category": "Feature Flags",
            "x-is-trigger": False,
            "x-display-name": "Toggle Feature Flag",
        },
        title="Toggle Feature Flag",
    )
    project_key: str = Field(
        ...,
        title="Project",
        description="The project containing the flag",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_key",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project key",
            }
        },
    )
    feature_flag_key: str = _feature_flag_key_field(description="The key of the feature flag to update")
    environment_key: str = _environment_key_field(description="The environment in which to toggle the flag")
    turn_on: str = Field(
        "true",
        title="Turn On",
        description="Turn the flag on (Yes) or off (No) in the chosen environment",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Turn On", "Turn Off"],
            "x-enum-searchable": True,
        },
    )
    comment: Optional[str] = Field(
        None, title="Comment", description="Optional comment describing the change"
    )


class LaunchDarklyDeleteFlagConfig(BaseModel):
    """Delete a feature flag."""

    operation: Literal["delete_flag"] = Field(
        "delete_flag",
        json_schema_extra={
            "const": "delete_flag",
            "ui:hidden": True,
            "x-category": "Feature Flags",
            "x-is-trigger": False,
            "x-display-name": "Delete Feature Flag",
        },
        title="Delete Feature Flag",
    )
    project_key: str = Field(
        ...,
        title="Project",
        description="The project containing the flag",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_key",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project key",
            }
        },
    )
    feature_flag_key: str = _feature_flag_key_field(description="The key of the feature flag to delete")


class LaunchDarklyCopyFlagConfig(BaseModel):
    """Copy a flag's targeting config from a source environment to a target environment."""

    operation: Literal["copy_flag"] = Field(
        "copy_flag",
        json_schema_extra={
            "const": "copy_flag",
            "ui:hidden": True,
            "x-category": "Feature Flags",
            "x-is-trigger": False,
            "x-display-name": "Copy Flag Settings",
        },
        title="Copy Flag Settings",
    )
    project_key: str = Field(
        ...,
        title="Project",
        description="The project containing the flag",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_key",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project key",
            }
        },
    )
    feature_flag_key: str = _feature_flag_key_field(description="The key of the flag to copy")
    source_environment_key: str = _environment_key_field(description="Environment to copy targeting from", field_name="source_environment_key", title="Source Environment")
    target_environment_key: str = _environment_key_field(description="Environment to copy targeting to", field_name="target_environment_key", title="Target Environment")


class LaunchDarklyGetFlagStatusConfig(BaseModel):
    """Get a flag's status (new/active/launched/inactive) in an environment."""

    operation: Literal["get_flag_status"] = Field(
        "get_flag_status",
        json_schema_extra={
            "const": "get_flag_status",
            "ui:hidden": True,
            "x-category": "Feature Flags",
            "x-is-trigger": False,
            "x-display-name": "Get Flag Status",
        },
        title="Get Flag Status",
    )
    project_key: str = Field(
        ...,
        title="Project",
        description="The project containing the flag",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_key",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project key",
            }
        },
    )
    environment_key: str = _environment_key_field(description="The environment to check the flag status in")
    feature_flag_key: str = _feature_flag_key_field(description="The key of the feature flag")


# ============================================================================
# Operation Configs — Projects
# ============================================================================


class LaunchDarklyListProjectsConfig(BaseModel):
    """List all projects in the account."""

    operation: Literal["list_projects"] = Field(
        "list_projects",
        json_schema_extra={
            "const": "list_projects",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "List Projects",
        },
        title="List Projects",
    )
    limit: Optional[str] = Field(
        "50", title="Limit", description="Max number of projects to return"
    )


class LaunchDarklyGetProjectConfig(BaseModel):
    """Get a single project."""

    operation: Literal["get_project"] = Field(
        "get_project",
        json_schema_extra={
            "const": "get_project",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Get Project",
        },
        title="Get Project",
    )
    project_key: str = Field(
        ...,
        title="Project",
        description="The project to retrieve",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_key",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project key",
            }
        },
    )


class LaunchDarklyCreateProjectConfig(BaseModel):
    """Create a new project."""

    operation: Literal["create_project"] = Field(
        "create_project",
        json_schema_extra={
            "const": "create_project",
            "x-creates-resource": True,
            "x-resource-type": "launchdarkly_project",
            "x-resource-id-path": "data.key",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Create Project",
        },
        title="Create Project",
    )
    name: str = Field(..., title="Name", description="Human-readable project name")
    key: str = Field(..., title="Key", description="Unique project key")
    tags: Optional[str] = Field(
        None, title="Tags", description="Comma-separated tags"
    )


class LaunchDarklyDeleteProjectConfig(BaseModel):
    """Delete a project."""

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
    project_key: str = Field(
        ...,
        title="Project",
        description="The project to delete",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_key",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project key",
            }
        },
    )


# ============================================================================
# Operation Configs — Environments
# ============================================================================


class LaunchDarklyListEnvironmentsConfig(BaseModel):
    """List environments within a project."""

    operation: Literal["list_environments"] = Field(
        "list_environments",
        json_schema_extra={
            "const": "list_environments",
            "ui:hidden": True,
            "x-category": "Environments",
            "x-is-trigger": False,
            "x-display-name": "List Environments",
        },
        title="List Environments",
    )
    project_key: str = Field(
        ...,
        title="Project",
        description="The project to list environments from",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_key",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project key",
            }
        },
    )


class LaunchDarklyCreateEnvironmentConfig(BaseModel):
    """Create an environment within a project."""

    operation: Literal["create_environment"] = Field(
        "create_environment",
        json_schema_extra={
            "const": "create_environment",
            "x-creates-resource": True,
            "x-resource-type": "launchdarkly_environment",
            "x-resource-id-path": "data.key",
            "ui:hidden": True,
            "x-category": "Environments",
            "x-is-trigger": False,
            "x-display-name": "Create Environment",
        },
        title="Create Environment",
    )
    project_key: str = Field(
        ...,
        title="Project",
        description="The project to create the environment in",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_key",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project key",
            }
        },
    )
    name: str = Field(..., title="Name", description="Human-readable environment name")
    key: str = Field(..., title="Key", description="Unique environment key")
    color: str = Field(
        "417505", title="Color", description="Hex color (no #) used for the environment badge"
    )


class LaunchDarklyDeleteEnvironmentConfig(BaseModel):
    """Delete an environment."""

    operation: Literal["delete_environment"] = Field(
        "delete_environment",
        json_schema_extra={
            "const": "delete_environment",
            "ui:hidden": True,
            "x-category": "Environments",
            "x-is-trigger": False,
            "x-display-name": "Delete Environment",
        },
        title="Delete Environment",
    )
    project_key: str = Field(
        ...,
        title="Project",
        description="The project containing the environment",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_key",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project key",
            }
        },
    )
    environment_key: str = _environment_key_field(description="The key of the environment to delete")


# ============================================================================
# Operation Configs — Segments
# ============================================================================


class LaunchDarklyListSegmentsConfig(BaseModel):
    """List segments in a project/environment."""

    operation: Literal["list_segments"] = Field(
        "list_segments",
        json_schema_extra={
            "const": "list_segments",
            "ui:hidden": True,
            "x-category": "Segments",
            "x-is-trigger": False,
            "x-display-name": "List Segments",
        },
        title="List Segments",
    )
    project_key: str = Field(
        ...,
        title="Project",
        description="The project containing the segments",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_key",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project key",
            }
        },
    )
    environment_key: str = _environment_key_field(description="The environment containing the segments")


class LaunchDarklyCreateSegmentConfig(BaseModel):
    """Create a user/context segment."""

    operation: Literal["create_segment"] = Field(
        "create_segment",
        json_schema_extra={
            "const": "create_segment",
            "x-creates-resource": True,
            "x-resource-type": "launchdarkly_segment",
            "x-resource-id-path": "data.key",
            "ui:hidden": True,
            "x-category": "Segments",
            "x-is-trigger": False,
            "x-display-name": "Create Segment",
        },
        title="Create Segment",
    )
    project_key: str = Field(
        ...,
        title="Project",
        description="The project to create the segment in",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_key",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project key",
            }
        },
    )
    environment_key: str = _environment_key_field(description="The environment to create the segment in")
    name: str = Field(..., title="Name", description="Human-readable segment name")
    key: str = Field(..., title="Key", description="Unique segment key")
    description: Optional[str] = Field(
        None, title="Description", description="Optional segment description",
        json_schema_extra={"ui:widget": "textarea"},
    )


class LaunchDarklyUpdateSegmentConfig(BaseModel):
    """Patch a segment's included/excluded targets (JSON patch array)."""

    operation: Literal["update_segment"] = Field(
        "update_segment",
        json_schema_extra={
            "const": "update_segment",
            "ui:hidden": True,
            "x-category": "Segments",
            "x-is-trigger": False,
            "x-display-name": "Update Segment",
        },
        title="Update Segment",
    )
    project_key: str = Field(
        ...,
        title="Project",
        description="The project containing the segment",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_key",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project key",
            }
        },
    )
    environment_key: str = _environment_key_field(description="The environment containing the segment")
    segment_key: str = _segment_key_field(description="The key of the segment to update")
    add_included: Optional[str] = Field(
        None,
        title="Add Included Targets",
        description="Comma-separated context keys to add to the segment's included list",
    )
    add_excluded: Optional[str] = Field(
        None,
        title="Add Excluded Targets",
        description="Comma-separated context keys to add to the segment's excluded list",
    )


class LaunchDarklyDeleteSegmentConfig(BaseModel):
    """Delete a segment."""

    operation: Literal["delete_segment"] = Field(
        "delete_segment",
        json_schema_extra={
            "const": "delete_segment",
            "ui:hidden": True,
            "x-category": "Segments",
            "x-is-trigger": False,
            "x-display-name": "Delete Segment",
        },
        title="Delete Segment",
    )
    project_key: str = Field(
        ...,
        title="Project",
        description="The project containing the segment",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_key",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project key",
            }
        },
    )
    environment_key: str = _environment_key_field(description="The environment containing the segment")
    segment_key: str = _segment_key_field(description="The key of the segment to delete")


# ============================================================================
# Operation Configs — Webhooks (management)
# ============================================================================


class LaunchDarklyListWebhooksConfig(BaseModel):
    """List all account webhooks."""

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


class LaunchDarklyCreateWebhookConfig(BaseModel):
    """Create an account webhook."""

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
    url: str = Field(..., title="URL", description="The endpoint LaunchDarkly should POST events to")
    name: Optional[str] = Field(None, title="Name", description="Human-readable webhook name")
    sign: str = Field(
        "false",
        title="Sign Payloads",
        description="HMAC-sign payloads with the secret (X-LD-Signature header)",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    secret: Optional[str] = Field(
        None, title="Secret", description="Signing secret (required if signing is enabled)",
        json_schema_extra={"ui:widget": "password"},
    )


class LaunchDarklyDeleteWebhookConfig(BaseModel):
    """Delete an account webhook."""

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
    webhook_id_value: str = Field(
        ..., title="Webhook ID", description="The ID of the webhook to delete"
    )


# ============================================================================
# Operation Configs — Members
# ============================================================================


class LaunchDarklyListMembersConfig(BaseModel):
    """List members of the account."""

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
    limit: Optional[str] = Field(
        "50", title="Limit", description="Max number of members to return"
    )


class LaunchDarklyInviteMembersConfig(BaseModel):
    """Invite a new member to the account."""

    operation: Literal["invite_members"] = Field(
        "invite_members",
        json_schema_extra={
            "const": "invite_members",
            "ui:hidden": True,
            "x-category": "Members",
            "x-is-trigger": False,
            "x-display-name": "Invite Member",
        },
        title="Invite Member",
    )
    email: str = Field(..., title="Email", description="Email address of the member to invite")
    role: str = Field(
        "reader",
        title="Role",
        description="Base role to grant the new member",
        json_schema_extra={
            "enum": ["reader", "writer", "admin", "no_access"],
            "enumNames": ["Reader", "Writer", "Admin", "No Access"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Operation Configs — Account / Misc
# ============================================================================


class LaunchDarklyGetAuditLogConfig(BaseModel):
    """Query the audit log."""

    operation: Literal["get_audit_log"] = Field(
        "get_audit_log",
        json_schema_extra={
            "const": "get_audit_log",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Audit Log",
        },
        title="Get Audit Log",
    )
    after: Optional[str] = Field(
        None, title="After (epoch ms)", description="Lower-bound timestamp in epoch milliseconds"
    )
    before: Optional[str] = Field(
        None, title="Before (epoch ms)", description="Upper-bound timestamp in epoch milliseconds"
    )
    limit: Optional[str] = Field(
        "20", title="Limit", description="Max number of audit log entries to return"
    )


class LaunchDarklyListMetricsConfig(BaseModel):
    """List experimentation/release metrics in a project."""

    operation: Literal["list_metrics"] = Field(
        "list_metrics",
        json_schema_extra={
            "const": "list_metrics",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "List Metrics",
        },
        title="List Metrics",
    )
    project_key: str = Field(
        ...,
        title="Project",
        description="The project to list metrics from",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_key",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project key",
            }
        },
    )


class LaunchDarklyListRolesConfig(BaseModel):
    """List custom roles defined in the account."""

    operation: Literal["list_roles"] = Field(
        "list_roles",
        json_schema_extra={
            "const": "list_roles",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "List Custom Roles",
        },
        title="List Custom Roles",
    )


class LaunchDarklyListTeamsConfig(BaseModel):
    """List teams in the account."""

    operation: Literal["list_teams"] = Field(
        "list_teams",
        json_schema_extra={
            "const": "list_teams",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "List Teams",
        },
        title="List Teams",
    )
    limit: Optional[str] = Field(
        "50", title="Limit", description="Max number of teams to return (max 100)"
    )


class LaunchDarklyCreateApprovalRequestConfig(BaseModel):
    """Create an approval request for a flag change."""

    operation: Literal["create_approval_request"] = Field(
        "create_approval_request",
        json_schema_extra={
            "const": "create_approval_request",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Create Approval Request",
        },
        title="Create Approval Request",
    )
    project_key: str = Field(
        ...,
        title="Project",
        description="The project containing the flag",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_key",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a project key",
            }
        },
    )
    feature_flag_key: str = _feature_flag_key_field(description="The flag the approval request targets")
    environment_key: str = _environment_key_field(description="The environment the change applies to")
    description: str = Field(
        ..., title="Description", description="What the approval request is for"
    )
    notify_member_ids: Optional[str] = Field(
        None,
        title="Notify Member IDs",
        description="Comma-separated member IDs to request approval from",
    )
    requested_change: str = Field(
        "turn_on",
        title="Requested Change",
        description="The flag change to request approval for (an approval request must carry at least one instruction).",
        json_schema_extra={
            "enum": ["turn_on", "turn_off"],
            "enumNames": ["Turn flag ON", "Turn flag OFF"],
            "x-enum-searchable": True,
        },
    )


class LaunchDarklyListTokensConfig(BaseModel):
    """List API access tokens for the account."""

    operation: Literal["list_tokens"] = Field(
        "list_tokens",
        json_schema_extra={
            "const": "list_tokens",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "List Access Tokens",
        },
        title="List Access Tokens",
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class LaunchDarklyWebhookTriggerConfig(BaseModel):
    """Fire the workflow when LaunchDarkly reports account activity."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_account_activity"] = Field(
        "on_account_activity",
        json_schema_extra={
            "const": "on_account_activity",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Account Activity",
        },
        title="On Account Activity",
    )
    event_types: str = Field(
        "*",
        title="Trigger On",
        description=(
            "Which LaunchDarkly events fire this workflow. Pick one or more "
            "(comma-separated). The webhook is registered with a matching policy "
            "filter and deliveries are also filtered at runtime, so the workflow "
            "only runs for the events you choose. Options:\n"
            "- All account activity (default): every change in the account\n"
            "- Feature flag created / deleted / turned on-off (toggle) / updated\n"
            "- Project created/updated/deleted\n"
            "- Environment created/updated/deleted\n"
            "- Segment created/updated/deleted\n"
            "- Account member invited/updated/removed\n"
            "- Webhook created/updated/deleted"
        ),
        json_schema_extra={
            "enum": LD_WEBHOOK_EVENT_KEYS,
            "enumNames": LD_WEBHOOK_EVENT_LABELS,
            "x-enum-searchable": True,
            "x-enum-multiple": True,
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="LaunchDarkly posts account activity events here. Registered automatically when you connect credentials.",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


LaunchDarklyConfig = Annotated[
    Union[
        LaunchDarklyListFlagsConfig,
        LaunchDarklyGetFlagConfig,
        LaunchDarklyCreateFlagConfig,
        LaunchDarklyUpdateFlagConfig,
        LaunchDarklyDeleteFlagConfig,
        LaunchDarklyCopyFlagConfig,
        LaunchDarklyGetFlagStatusConfig,
        LaunchDarklyListProjectsConfig,
        LaunchDarklyGetProjectConfig,
        LaunchDarklyCreateProjectConfig,
        LaunchDarklyDeleteProjectConfig,
        LaunchDarklyListEnvironmentsConfig,
        LaunchDarklyCreateEnvironmentConfig,
        LaunchDarklyDeleteEnvironmentConfig,
        LaunchDarklyListSegmentsConfig,
        LaunchDarklyCreateSegmentConfig,
        LaunchDarklyUpdateSegmentConfig,
        LaunchDarklyDeleteSegmentConfig,
        LaunchDarklyListWebhooksConfig,
        LaunchDarklyCreateWebhookConfig,
        LaunchDarklyDeleteWebhookConfig,
        LaunchDarklyListMembersConfig,
        LaunchDarklyInviteMembersConfig,
        LaunchDarklyGetAuditLogConfig,
        LaunchDarklyListMetricsConfig,
        LaunchDarklyListRolesConfig,
        LaunchDarklyListTeamsConfig,
        LaunchDarklyCreateApprovalRequestConfig,
        LaunchDarklyListTokensConfig,
        LaunchDarklyWebhookTriggerConfig,
        *OPERATION_CONFIGS,
    ],
    Discriminator("operation"),
]


class LaunchDarklyNodeConfig(NodeConfig[LaunchDarklyConfig, LaunchDarklyCredential]):
    """Full configuration for the LaunchDarkly node including credentials."""

    pass


# Helpers (_ld_request, _base_url, _comma_list, constants) live in
# nodes/launchdarkly_common.py and are imported at the top of this module.


# ============================================================================
# Node Implementation
# ============================================================================


class LaunchDarklyNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """LaunchDarkly feature management automation node."""

    edit_examples = [
        "Turn on the new-checkout feature flag in production",
        "List all feature flags in the web project",
        "Create a feature flag for an upcoming experiment",
        "Invite a teammate to LaunchDarkly as a Writer",
        "Trigger a workflow whenever a flag changes in LaunchDarkly",
    ]

    @classmethod
    def get_config_model(cls):
        return LaunchDarklyNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (projects)
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
        """Populate the searchable dropdowns for all listable LaunchDarkly resources.

        Dependent fields (environments/flags/segments/metrics) read their parent
        keys (project_key/environment_key) from ``context`` — the frontend sends
        the node's full config as context.
        """
        if not credential_data:
            return {"options": []}
        token = credential_data.get("access_token")
        region = credential_data.get("region")
        ctx = context or {}
        pk = ctx.get("project_key")
        env = ctx.get("environment_key")

        # (endpoint, key_field, label_fields) per dropdown field; None endpoint => needs a
        # parent value that isn't set yet, so return no options.
        if field_name == "project_key":
            spec = ("/projects", "key", ("name",))
        elif field_name.endswith("environment_key"):  # incl. source_/target_environment_key
            spec = (f"/projects/{pk}/environments", "key", ("name",)) if pk else None
        elif field_name == "feature_flag_key":
            spec = (f"/flags/{pk}", "key", ("name",)) if pk else None
        elif field_name == "segment_key":
            spec = (f"/segments/{pk}/{env}", "key", ("name",)) if (pk and env) else None
        elif field_name == "metric_key":
            spec = (f"/metrics/{pk}", "key", ("name",)) if pk else None
        elif field_name == "team_key":
            spec = ("/teams", "key", ("name",))
        elif field_name == "custom_role_key":
            spec = ("/roles", "key", ("name",))
        elif field_name == "member_id":
            spec = ("/members", "_id", ("email", "firstName", "lastName"))
        elif field_name == "repo":
            spec = ("/code-refs/repositories", "name", ("name",))
        elif field_name == "client_id":
            spec = ("/oauth/clients", "_clientId", ("name",))
        elif field_name == "experiment_key":
            spec = (f"/projects/{pk}/environments/{env}/experiments", "key", ("name",)) if (pk and env) else None
        elif field_name == "holdout_key":
            spec = (f"/projects/{pk}/environments/{env}/holdouts", "key", ("name",)) if (pk and env) else None
        else:
            return {"options": []}

        if spec is None:
            return {"options": []}
        endpoint, key_field, label_fields = spec
        result = await _ld_request(
            token, region, "GET", endpoint, params={"limit": "100"},
            action_name=f"options_{field_name}",
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        items = data.get("items") if isinstance(data, dict) else data
        options = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            value = item.get(key_field)
            if not value:
                continue
            label = " ".join(str(item[f]) for f in label_fields if item.get(f)) or str(value)
            options.append({"label": f"{label} ({value})" if label != str(value) else str(value), "value": str(value)})
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
            "event_types": (config or {}).get("event_types"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        access_token = credential.get("access_token")
        if not access_token:
            raise ValueError("A LaunchDarkly access token is required to register the trigger")
        region = credential.get("region")
        secret = hashlib.sha256(f"{node_id}:{webhook_url}".encode()).hexdigest()[:32]
        body: Dict[str, Any] = {
            "url": webhook_url,
            "name": f"NoClick trigger {node_id}",
            "sign": True,
            "secret": secret,
            "on": True,
        }
        # Scope the webhook to the chosen events via a policy filter (omit for
        # "all activity" so LaunchDarkly delivers everything).
        statements = [
            LD_WEBHOOK_EVENTS[k]["statement"]
            for k in _selected_event_keys(config)
            if LD_WEBHOOK_EVENTS[k]["statement"] is not None
        ]
        if statements:
            body["statements"] = statements
        result = await _ld_request(
            access_token,
            region,
            "POST",
            "/webhooks",
            json_body=body,
            action_name="register_webhook",
        )
        if result.get("status") != "success":
            raise ValueError(f"LaunchDarkly webhook registration failed: {result.get('error')}")
        data = result.get("data") or {}
        external_id = data.get("_id") or data.get("id") if isinstance(data, dict) else None
        return {
            "external_webhook_id": str(external_id) if external_id else None,
            "signing_secret": secret,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        access_token = (credential or {}).get("access_token")
        if not external_id or not access_token:
            return
        region = (credential or {}).get("region")
        await _ld_request(
            access_token, region, "DELETE", f"/webhooks/{external_id}",
            action_name="unregister_webhook",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no secret stored — accept (trigger not yet armed)
        sent = headers.get("x-ld-signature") or headers.get("X-LD-Signature")
        if not sent:
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sent)

    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        """Skip webhook deliveries that don't match the selected event_types.

        LaunchDarkly's provider-side policy already narrows deliveries, but the
        webhook policy can be edited out-of-band, so we re-check at runtime
        against the audit-log-shaped payload. Each `accesses[]` entry carries a
        `resource` (e.g. ``proj/d:env/p:flag/my-flag``) and an `action`. A
        delivery matches a selected event when one access targets that event's
        resource kind AND (if the event lists specific actions) its action is
        one of them. Selecting "All account activity" (`*`) accepts everything.
        """
        keys = _selected_event_keys(config)
        if "*" in keys:
            return True
        accesses = payload.get("accesses") if isinstance(payload, dict) else None
        entries = [a for a in (accesses or []) if isinstance(a, dict)]
        if not entries:
            return False  # selective trigger but payload has no access entries -> skip
        for key in keys:
            spec = LD_WEBHOOK_EVENTS[key]
            kind = spec["resource_kind"]
            wanted_actions = spec["actions"]
            for entry in entries:
                action = str(entry.get("action", "")).lower()
                if kind and _resource_kind(str(entry.get("resource", ""))) != kind:
                    continue
                if wanted_actions and action not in wanted_actions:
                    continue
                return True
        return False

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, LaunchDarklyNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, LaunchDarklyWebhookTriggerConfig):
            return {
                "status": "success",
                "action": "on_account_activity",
                "data": {
                    **inputs,
                    "webhook_url": op.webhook_url,
                    "event_types": _selected_event_keys({"event_types": op.event_types}),
                },
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your LaunchDarkly access token.")
        access_token = credentials.access_token
        region = credentials.region

        handlers = {
            "list_flags": self._list_flags,
            "get_flag": self._get_flag,
            "create_flag": self._create_flag,
            "update_flag": self._update_flag,
            "delete_flag": self._delete_flag,
            "copy_flag": self._copy_flag,
            "get_flag_status": self._get_flag_status,
            "list_projects": self._list_projects,
            "get_project": self._get_project,
            "create_project": self._create_project,
            "delete_project": self._delete_project,
            "list_environments": self._list_environments,
            "create_environment": self._create_environment,
            "delete_environment": self._delete_environment,
            "list_segments": self._list_segments,
            "create_segment": self._create_segment,
            "update_segment": self._update_segment,
            "delete_segment": self._delete_segment,
            "list_webhooks": self._list_webhooks,
            "create_webhook": self._create_webhook,
            "delete_webhook": self._delete_webhook,
            "list_members": self._list_members,
            "invite_members": self._invite_members,
            "get_audit_log": self._get_audit_log,
            "list_metrics": self._list_metrics,
            "list_roles": self._list_roles,
            "list_teams": self._list_teams,
            "create_approval_request": self._create_approval_request,
            "list_tokens": self._list_tokens,
        }
        # Merge the full stable-API operation registry (module-level handlers take
        # the same (c, token, region) args as the dispatch call below).
        handlers.update(OPERATION_HANDLERS)
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, access_token, region)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Flag handlers
    # ------------------------------------------------------------------
    async def _list_flags(self, c: LaunchDarklyListFlagsConfig, token: str, region: str) -> Dict[str, Any]:
        params = {"env": c.env, "tag": c.tag, "limit": c.limit}
        return await _ld_request(
            token, region, "GET", f"/flags/{c.project_key}", params=params, action_name="list_flags"
        )

    async def _get_flag(self, c: LaunchDarklyGetFlagConfig, token: str, region: str) -> Dict[str, Any]:
        params = {"env": c.env}
        return await _ld_request(
            token, region, "GET", f"/flags/{c.project_key}/{c.feature_flag_key}",
            params=params, action_name="get_flag",
        )

    async def _create_flag(self, c: LaunchDarklyCreateFlagConfig, token: str, region: str) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "key": c.key,
            "description": c.description,
            "tags": _comma_list(c.tags),
            "temporary": c.temporary == "true",
        }
        return await _ld_request(
            token, region, "POST", f"/flags/{c.project_key}", json_body=body, action_name="create_flag"
        )

    async def _update_flag(self, c: LaunchDarklyUpdateFlagConfig, token: str, region: str) -> Dict[str, Any]:
        kind = "turnFlagOn" if c.turn_on == "true" else "turnFlagOff"
        body: Dict[str, Any] = {
            "environmentKey": c.environment_key,
            "instructions": [{"kind": kind}],
        }
        if c.comment:
            body["comment"] = c.comment
        return await _ld_request(
            token, region, "PATCH", f"/flags/{c.project_key}/{c.feature_flag_key}",
            json_body=body, content_type=SEMANTIC_PATCH_CONTENT_TYPE, action_name="update_flag",
        )

    async def _delete_flag(self, c: LaunchDarklyDeleteFlagConfig, token: str, region: str) -> Dict[str, Any]:
        return await _ld_request(
            token, region, "DELETE", f"/flags/{c.project_key}/{c.feature_flag_key}",
            action_name="delete_flag",
        )

    async def _copy_flag(self, c: LaunchDarklyCopyFlagConfig, token: str, region: str) -> Dict[str, Any]:
        body = {
            "source": {"key": c.source_environment_key},
            "target": {"key": c.target_environment_key},
        }
        return await _ld_request(
            token, region, "POST", f"/flags/{c.project_key}/{c.feature_flag_key}/copy",
            json_body=body, action_name="copy_flag",
        )

    async def _get_flag_status(self, c: LaunchDarklyGetFlagStatusConfig, token: str, region: str) -> Dict[str, Any]:
        return await _ld_request(
            token, region, "GET",
            f"/flag-statuses/{c.project_key}/{c.environment_key}/{c.feature_flag_key}",
            action_name="get_flag_status",
        )

    # ------------------------------------------------------------------
    # Project handlers
    # ------------------------------------------------------------------
    async def _list_projects(self, c: LaunchDarklyListProjectsConfig, token: str, region: str) -> Dict[str, Any]:
        return await _ld_request(
            token, region, "GET", "/projects", params={"limit": c.limit}, action_name="list_projects"
        )

    async def _get_project(self, c: LaunchDarklyGetProjectConfig, token: str, region: str) -> Dict[str, Any]:
        return await _ld_request(
            token, region, "GET", f"/projects/{c.project_key}", action_name="get_project"
        )

    async def _create_project(self, c: LaunchDarklyCreateProjectConfig, token: str, region: str) -> Dict[str, Any]:
        body = {"name": c.name, "key": c.key, "tags": _comma_list(c.tags)}
        return await _ld_request(
            token, region, "POST", "/projects", json_body=body, action_name="create_project"
        )

    async def _delete_project(self, c: LaunchDarklyDeleteProjectConfig, token: str, region: str) -> Dict[str, Any]:
        return await _ld_request(
            token, region, "DELETE", f"/projects/{c.project_key}", action_name="delete_project"
        )

    # ------------------------------------------------------------------
    # Environment handlers
    # ------------------------------------------------------------------
    async def _list_environments(self, c: LaunchDarklyListEnvironmentsConfig, token: str, region: str) -> Dict[str, Any]:
        return await _ld_request(
            token, region, "GET", f"/projects/{c.project_key}/environments",
            action_name="list_environments",
        )

    async def _create_environment(self, c: LaunchDarklyCreateEnvironmentConfig, token: str, region: str) -> Dict[str, Any]:
        body = {"name": c.name, "key": c.key, "color": c.color}
        return await _ld_request(
            token, region, "POST", f"/projects/{c.project_key}/environments",
            json_body=body, action_name="create_environment",
        )

    async def _delete_environment(self, c: LaunchDarklyDeleteEnvironmentConfig, token: str, region: str) -> Dict[str, Any]:
        return await _ld_request(
            token, region, "DELETE",
            f"/projects/{c.project_key}/environments/{c.environment_key}",
            action_name="delete_environment",
        )

    # ------------------------------------------------------------------
    # Segment handlers
    # ------------------------------------------------------------------
    async def _list_segments(self, c: LaunchDarklyListSegmentsConfig, token: str, region: str) -> Dict[str, Any]:
        return await _ld_request(
            token, region, "GET", f"/segments/{c.project_key}/{c.environment_key}",
            action_name="list_segments",
        )

    async def _create_segment(self, c: LaunchDarklyCreateSegmentConfig, token: str, region: str) -> Dict[str, Any]:
        body = {"name": c.name, "key": c.key, "description": c.description}
        return await _ld_request(
            token, region, "POST", f"/segments/{c.project_key}/{c.environment_key}",
            json_body=body, action_name="create_segment",
        )

    async def _update_segment(self, c: LaunchDarklyUpdateSegmentConfig, token: str, region: str) -> Dict[str, Any]:
        patch: List[Dict[str, Any]] = []
        for ctx_key in _comma_list(c.add_included) or []:
            patch.append({"op": "add", "path": "/included/-", "value": ctx_key})
        for ctx_key in _comma_list(c.add_excluded) or []:
            patch.append({"op": "add", "path": "/excluded/-", "value": ctx_key})
        return await _ld_request(
            token, region, "PATCH",
            f"/segments/{c.project_key}/{c.environment_key}/{c.segment_key}",
            json_body=patch, action_name="update_segment",
        )

    async def _delete_segment(self, c: LaunchDarklyDeleteSegmentConfig, token: str, region: str) -> Dict[str, Any]:
        return await _ld_request(
            token, region, "DELETE",
            f"/segments/{c.project_key}/{c.environment_key}/{c.segment_key}",
            action_name="delete_segment",
        )

    # ------------------------------------------------------------------
    # Webhook (management) handlers
    # ------------------------------------------------------------------
    async def _list_webhooks(self, c: LaunchDarklyListWebhooksConfig, token: str, region: str) -> Dict[str, Any]:
        return await _ld_request(
            token, region, "GET", "/webhooks", action_name="list_webhooks"
        )

    async def _create_webhook(self, c: LaunchDarklyCreateWebhookConfig, token: str, region: str) -> Dict[str, Any]:
        body = {
            "url": c.url,
            "name": c.name,
            "sign": c.sign == "true",
            "secret": c.secret,
            "on": True,
        }
        return await _ld_request(
            token, region, "POST", "/webhooks", json_body=body, action_name="create_webhook"
        )

    async def _delete_webhook(self, c: LaunchDarklyDeleteWebhookConfig, token: str, region: str) -> Dict[str, Any]:
        return await _ld_request(
            token, region, "DELETE", f"/webhooks/{c.webhook_id_value}", action_name="delete_webhook"
        )

    # ------------------------------------------------------------------
    # Member handlers
    # ------------------------------------------------------------------
    async def _list_members(self, c: LaunchDarklyListMembersConfig, token: str, region: str) -> Dict[str, Any]:
        return await _ld_request(
            token, region, "GET", "/members", params={"limit": c.limit}, action_name="list_members"
        )

    async def _invite_members(self, c: LaunchDarklyInviteMembersConfig, token: str, region: str) -> Dict[str, Any]:
        body = [{"email": c.email, "role": c.role}]
        return await _ld_request(
            token, region, "POST", "/members", json_body=body, action_name="invite_members"
        )

    # ------------------------------------------------------------------
    # Account / misc handlers
    # ------------------------------------------------------------------
    async def _get_audit_log(self, c: LaunchDarklyGetAuditLogConfig, token: str, region: str) -> Dict[str, Any]:
        params = {"after": c.after, "before": c.before, "limit": c.limit}
        return await _ld_request(
            token, region, "GET", "/auditlog", params=params, action_name="get_audit_log"
        )

    async def _list_metrics(self, c: LaunchDarklyListMetricsConfig, token: str, region: str) -> Dict[str, Any]:
        return await _ld_request(
            token, region, "GET", f"/metrics/{c.project_key}", action_name="list_metrics"
        )

    async def _list_roles(self, c: LaunchDarklyListRolesConfig, token: str, region: str) -> Dict[str, Any]:
        return await _ld_request(
            token, region, "GET", "/roles", action_name="list_roles"
        )

    async def _list_teams(self, c: LaunchDarklyListTeamsConfig, token: str, region: str) -> Dict[str, Any]:
        return await _ld_request(
            token, region, "GET", "/teams", params={"limit": c.limit}, action_name="list_teams"
        )

    async def _create_approval_request(self, c: LaunchDarklyCreateApprovalRequestConfig, token: str, region: str) -> Dict[str, Any]:
        instruction_kind = "turnFlagOff" if c.requested_change == "turn_off" else "turnFlagOn"
        body = {
            "description": c.description,
            "instructions": [{"kind": instruction_kind}],
            "notifyMemberIds": _comma_list(c.notify_member_ids),
        }
        endpoint = (
            f"/projects/{c.project_key}/flags/{c.feature_flag_key}"
            f"/environments/{c.environment_key}/approval-requests"
        )
        return await _ld_request(
            token, region, "POST", endpoint, json_body=body, action_name="create_approval_request"
        )

    async def _list_tokens(self, c: LaunchDarklyListTokensConfig, token: str, region: str) -> Dict[str, Any]:
        return await _ld_request(
            token, region, "GET", "/tokens", action_name="list_tokens"
        )
