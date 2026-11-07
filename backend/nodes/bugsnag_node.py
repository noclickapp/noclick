"""BugSnag Data Access API v2 workflow node.

Routes and authentication follow BugSnag's published Data Access API and its
official Ruby client. The Data Access API accepts a user auth token; the
project notifier API key is a different credential and is deliberately not
accepted here.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

API_BASE = "https://api.bugsnag.com"


class BugsnagAuthTokenCredential(BaseModel):
    """A personal auth token from BugSnag account settings."""

    credential_type: Literal["bugsnag_auth_token"] = "bugsnag_auth_token"

    auth_token: str = Field(
        ..., title="Personal Auth Token", min_length=1,
        description="Create a personal auth token in BugSnag Settings → My account → Auth tokens.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(title="Bugsnag Personal Auth Token", json_schema_extra={
        "x-credential-url": "https://app.bugsnag.com/settings/my-account",
        "x-help-text": "Use a personal auth token, not a project's notifier API key.",
    })


@dataclass(frozen=True)
class Route:
    title: str
    category: str
    method: str
    path: str
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    body: tuple[str, ...] = ()
    destructive: bool = False


# Route shape verified against the official BugSnag Ruby API client and the
# Data Access v2 examples. IDs are always encoded as path segments at runtime.
ROUTES: dict[str, Route] = {
    "list_organizations": Route("List Organizations", "Organizations", "GET", "/user/organizations", optional=("limit",)),
    "get_organization": Route("Get Organization", "Organizations", "GET", "/organizations/{organization_id}", ("organization_id",)),
    "create_organization": Route("Create Organization", "Organizations", "POST", "/organizations", ("name",), body=("name",)),
    "update_organization": Route("Update Organization", "Organizations", "PATCH", "/organizations/{organization_id}", ("organization_id", "name", "auto_upgrade"), body=("name", "auto_upgrade")),
    "list_projects": Route("List Projects", "Projects", "GET", "/organizations/{organization_id}/projects", ("organization_id",), ("limit",)),
    "get_project": Route("Get Project", "Projects", "GET", "/projects/{project_id}", ("project_id",)),
    "create_project": Route("Create Project", "Projects", "POST", "/organizations/{organization_id}/projects", ("organization_id", "name", "project_type"), body=("name", "project_type")),
    "update_project": Route("Update Project", "Projects", "PATCH", "/projects/{project_id}", ("project_id", "body_json"), body=("body_json",)),
    "delete_project": Route("Delete Project", "Projects", "DELETE", "/projects/{project_id}", ("project_id", "confirm_delete"), destructive=True),
    "list_errors": Route("List Errors", "Errors", "GET", "/projects/{project_id}/errors", ("project_id",), ("limit", "sort", "direction", "status")),
    "get_error": Route("Get Error", "Errors", "GET", "/projects/{project_id}/errors/{error_id}", ("project_id", "error_id")),
    "update_error": Route("Update Error", "Errors", "PATCH", "/projects/{project_id}/errors/{error_id}", ("project_id", "error_id", "error_operation"), ("severity", "assigned_collaborator_id"), ("error_operation", "severity", "assigned_collaborator_id")),
    "delete_error": Route("Delete Error", "Errors", "DELETE", "/projects/{project_id}/errors/{error_id}", ("project_id", "error_id", "confirm_delete"), destructive=True),
    "list_events": Route("List Events", "Events", "GET", "/projects/{project_id}/events", ("project_id",), ("limit",)),
    "get_event": Route("Get Event", "Events", "GET", "/projects/{project_id}/events/{event_id}", ("project_id", "event_id")),
    "list_error_events": Route("List Events for Error", "Events", "GET", "/projects/{project_id}/errors/{error_id}/events", ("project_id", "error_id"), ("limit",)),
    "get_latest_event": Route("Get Latest Event", "Events", "GET", "/errors/{error_id}/latest_event", ("error_id",)),
    "delete_event": Route("Delete Event", "Events", "DELETE", "/projects/{project_id}/events/{event_id}", ("project_id", "event_id", "confirm_delete"), destructive=True),
    "list_comments": Route("List Comments", "Comments", "GET", "/projects/{project_id}/errors/{error_id}/comments", ("project_id", "error_id"), ("limit",)),
    "get_comment": Route("Get Comment", "Comments", "GET", "/comments/{comment_id}", ("comment_id",)),
    "create_comment": Route("Create Comment", "Comments", "POST", "/projects/{project_id}/errors/{error_id}/comments", ("project_id", "error_id", "message"), body=("message",)),
    "update_comment": Route("Update Comment", "Comments", "PATCH", "/comments/{comment_id}", ("comment_id", "message"), body=("message",)),
    "delete_comment": Route("Delete Comment", "Comments", "DELETE", "/comments/{comment_id}", ("comment_id", "confirm_delete"), destructive=True),
    "list_releases": Route("List Releases", "Releases", "GET", "/projects/{project_id}/releases", ("project_id",), ("limit",)),
    "get_release": Route("Get Release", "Releases", "GET", "/projects/{project_id}/releases/{release_id}", ("project_id", "release_id")),
    "list_collaborators": Route("List Collaborators", "Collaborators", "GET", "/organizations/{organization_id}/collaborators", ("organization_id",), ("limit",)),
    "get_collaborator": Route("Get Collaborator", "Collaborators", "GET", "/organizations/{organization_id}/collaborators/{collaborator_id}", ("organization_id", "collaborator_id")),
    "list_project_collaborators": Route("List Project Collaborators", "Collaborators", "GET", "/projects/{project_id}/collaborators", ("project_id",), ("limit",)),
    "list_collaborator_projects": Route("List Collaborator Projects", "Collaborators", "GET", "/organizations/{organization_id}/collaborators/{collaborator_id}/projects", ("organization_id", "collaborator_id"), ("limit",)),
    "list_event_fields": Route("List Event Fields", "Event Fields", "GET", "/projects/{project_id}/event_fields", ("project_id",), ("limit",)),
    "create_event_field": Route("Create Event Field", "Event Fields", "POST", "/projects/{project_id}/event_fields", ("project_id", "display_id", "field_path", "filter_options_json"), body=("display_id", "field_path", "filter_options_json")),
    "list_pivots": Route("List Pivots", "Analytics", "GET", "/projects/{project_id}/pivots", ("project_id",)),
    "list_pivot_values": Route("List Pivot Values", "Analytics", "GET", "/projects/{project_id}/pivots/{display_id}/values", ("project_id", "display_id"), ("limit",)),
    "get_project_trend": Route("Get Project Trend", "Analytics", "GET", "/projects/{project_id}/trend", ("project_id",), ("resolution",)),
    "get_error_trend": Route("Get Error Trend", "Analytics", "GET", "/projects/{project_id}/errors/{error_id}/trend", ("project_id", "error_id"), ("resolution",)),
    "get_stability_trend": Route("Get Stability Trend", "Analytics", "GET", "/projects/{project_id}/stability_trend", ("project_id",)),
}

_TITLES = {
    "organization_id": "Organization ID", "project_id": "Project ID", "error_id": "Error ID",
    "event_id": "Event ID", "comment_id": "Comment ID", "release_id": "Release ID",
    "collaborator_id": "Collaborator ID", "project_type": "Platform Type",
    "error_operation": "Error Action", "body_json": "Project Fields (JSON)",
    "field_path": "Event Field Path", "filter_options_json": "Filter Options (JSON)",
    "display_id": "Display ID", "assigned_collaborator_id": "Assignee ID",
}
_FIELDS = {
    "organization_id", "project_id", "error_id", "event_id", "comment_id", "release_id",
    "collaborator_id", "name", "project_type", "body_json", "error_operation", "severity",
    "assigned_collaborator_id", "message", "display_id", "field_path", "filter_options_json",
    "limit", "sort", "direction", "status", "resolution", "confirm_delete", "all_pages", "auto_upgrade",
}


def _field(name: str, required: bool) -> tuple[Any, Any]:
    title = _TITLES.get(name, name.replace("_", " ").title())
    if name == "all_pages":
        return (bool, Field(False, title="Fetch all pages", description="Follow up to 10 BugSnag pages (at most 1,000 results)."))
    if name == "confirm_delete":
        return (bool, Field(..., title="Confirm permanent deletion", description="Must be enabled to run this destructive operation."))
    if name == "auto_upgrade":
        return (bool, Field(..., title="Automatically upgrade plan", description="Allow BugSnag to upgrade the organization's plan when its event limit is reached."))
    if name == "limit":
        return (int, Field(30, title="Results per page", ge=1, le=100))
    if name in {"body_json", "filter_options_json"}:
        return (str if required else Optional[str], Field(... if required else None, title=title, json_schema_extra={"ui:widget": "textarea"}))
    if name == "error_operation":
        return (Literal["fix", "open", "ignore", "snooze"], Field(..., title=title, description="fix marks the error as fixed; open reopens it."))
    if name == "severity":
        return (Optional[Literal["info", "warning", "error"]], Field(None, title=title))
    if name in {"organization_id", "project_id"}:
        return (str if required else Optional[str], Field(... if required else None, title=title, json_schema_extra={
            "x-dynamic-options": {"field_name": name, "searchable": True, "allow_custom": True}
        }))
    return (str if required else Optional[str], Field(... if required else None, title=title))


def _make_config(action: str, route: Route) -> type[BaseModel]:
    assert set(route.required + route.optional) <= _FIELDS
    fields: dict[str, tuple[Any, Any]] = {
        "operation": (Literal[action], Field(action, json_schema_extra={
            "const": action, "ui:hidden": True, "x-category": route.category,
            "x-display-name": route.title,
        }))
    }
    fields.update({name: _field(name, True) for name in route.required})
    fields.update({name: _field(name, False) for name in route.optional})
    if action.startswith("list_"):
        fields["all_pages"] = _field("all_pages", False)
    return create_model(f"Bugsnag{''.join(p.title() for p in action.split('_'))}Config", __module__=__name__, **fields)


_CONFIG_MODELS = tuple(_make_config(action, route) for action, route in ROUTES.items())
BugsnagConfig = Annotated[Union[_CONFIG_MODELS], Discriminator("operation")]


class BugsnagNodeConfig(NodeConfig[BugsnagConfig, BugsnagAuthTokenCredential]):
    pass


def _json_object(raw: str, name: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _path(route: Route, config: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = config.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} is required")
        return quote(value, safe="")
    return re.sub(r"\{([a-z_]+)\}", replace, route.path)


def _redact_project_keys(value: Any) -> Any:
    """Project list/get payloads include a notifier key; keep it out of runs."""
    if isinstance(value, list):
        return [_redact_project_keys(item) for item in value]
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if key == "api_key" else _redact_project_keys(item))
                for key, item in value.items()}
    return value


async def _request(token: str, method: str, path: str, *, params: Optional[dict[str, Any]] = None,
                   body: Optional[dict[str, Any]] = None) -> tuple[Any, Optional[str]]:
    if not token:
        raise ValueError("A BugSnag personal auth token is required")
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("BugSnag request path must be relative to its API host")
    async with httpx.AsyncClient(base_url=API_BASE, timeout=25.0) as client:
        response = await client.request(
            method, path, params=params or None, json=body,
            headers={"Authorization": f"token {token}", "X-Version": "2", "Accept": "application/json"},
        )
    if response.is_error:
        # Provider errors may echo query strings or submitted content. Never
        # return the raw body or token to the workflow output.
        raise ValueError(f"BugSnag API returned HTTP {response.status_code} for {method} {path}")
    data = _redact_project_keys(response.json()) if response.content else {}
    next_link = None
    for part in response.headers.get("Link", "").split(","):
        if 'rel="next"' in part:
            next_link = part.split(";", 1)[0].strip().strip("<>")
            break
    return data, next_link


class BugsnagNode(WorkflowNode):
    """Read and manage BugSnag organizations, projects, errors, and events."""

    integration_type = "automation-bugsnag"

    edit_examples = [
        "List open BugSnag errors for a project",
        "Resolve a BugSnag error after deployment",
        "Comment on a BugSnag error",
        "Get a project's stability trend",
    ]
    connection_evidence = ConnectionEvidence(
        field="organization_id", noun="organizations", identity_operation="list_organizations",
    )

    @classmethod
    def get_config_model(cls):
        return BugsnagNodeConfig

    @classmethod
    async def load_field_options(cls, field_name: str, credential_data: dict[str, Any],
                                 context: Optional[dict[str, Any]] = None,
                                 page_token: Optional[str] = None,
                                 search: Optional[str] = None) -> dict[str, Any]:
        token = credential_data.get("auth_token") or ""
        if not token:
            return {"options": [], "next_page_token": None}
        if field_name == "organization_id":
            data, _ = await _request(token, "GET", "/user/organizations", params={"per_page": 100})
        elif field_name == "project_id":
            org_id = (context or {}).get("organization_id")
            if org_id:
                data, _ = await _request(token, "GET", f"/organizations/{quote(str(org_id), safe='')}/projects", params={"per_page": 100})
            else:
                orgs, _ = await _request(token, "GET", "/user/organizations", params={"per_page": 100})
                data = []
                for org in orgs[:10]:
                    projects, _ = await _request(token, "GET", f"/organizations/{quote(str(org['id']), safe='')}/projects", params={"per_page": 100})
                    data.extend(projects)
        else:
            return {"options": [], "next_page_token": None}
        options = [{"value": str(item["id"]), "label": str(item.get("name") or item.get("slug") or item["id"])}
                   for item in data if isinstance(item, dict) and item.get("id")]
        if search:
            options = [option for option in options if search.casefold() in option["label"].casefold()]
        return {"options": options, "next_page_token": None}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()
        if not isinstance(self.config, BugsnagNodeConfig):
            raise ValueError("Valid BugSnag configuration is required")
        config = self.config.config.model_dump(exclude_none=True)
        action = config["operation"]
        route = ROUTES[action]
        if route.destructive and config.get("confirm_delete") is not True:
            raise ValueError("Confirm permanent deletion before running this action")
        credentials = self.config.credentials
        if not credentials:
            raise ValueError("BugSnag personal auth token is required")

        body: dict[str, Any] = {}
        for field in route.body:
            value = config.get(field)
            if value is None:
                continue
            if field == "body_json":
                body.update(_json_object(value, "Project fields"))
            elif field == "filter_options_json":
                body["filter_options"] = _json_object(value, "Filter options")
            elif field == "project_type":
                body["type"] = value
            elif field == "field_path":
                body["path"] = value
            elif field == "error_operation":
                body["operation"] = value
            else:
                body[field] = value

        params: dict[str, Any] = {}
        if config.get("limit"):
            params["per_page"] = config["limit"]
        for field in ("sort", "direction", "resolution"):
            if config.get(field):
                params[field] = config[field]
        if config.get("status"):
            params["filters[error.status][][value]"] = config["status"]
            params["filters[error.status][][type]"] = "eq"

        data, next_link = await _request(credentials.auth_token, route.method, _path(route, config),
                                         params=params, body=body if route.body else None)
        if config.get("all_pages") and isinstance(data, list):
            page_count = 1
            while next_link and page_count < 10:
                parsed = urlsplit(next_link)
                if parsed.scheme != "https" or parsed.netloc != "api.bugsnag.com":
                    raise ValueError("BugSnag supplied a next-page URL outside its API host")
                page, next_link = await _request(credentials.auth_token, "GET", parsed.path + ("?" + parsed.query if parsed.query else ""))
                if not isinstance(page, list):
                    raise ValueError("BugSnag next page was not a list")
                data.extend(page)
                page_count += 1
        result: dict[str, Any] = {"status": "success", "action": action, "data": data,
                                  "timing_ms": {"total": round((time.monotonic() - start) * 1000, 2)}}
        if isinstance(data, list):
            result["count"] = len(data)
        if next_link:
            result["next_page_url"] = next_link
        return result
