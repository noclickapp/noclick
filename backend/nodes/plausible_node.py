"""Plausible Analytics Stats, Events, and Sites APIs.

Stats keys support analytics and read-only site operations. The Sites API write
operations require an Enterprise Sites API key. Events are ingested without a
key, but remain tied to a connected site credential in NoClick.
"""

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from urllib.parse import quote, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


BASE_URL = "https://plausible.io"
SITE_FIELD = {
    "x-dynamic-options": {
        "field_name": "site_id",
        "placeholder": "Select a Plausible site",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or enter its domain",
    }
}


class PlausibleApiKeyCredential(BaseModel):
    credential_type: Literal["plausible_api_key"] = Field(
        "plausible_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(..., title="Stats or Sites API Key", json_schema_extra={"ui:widget": "password"})
    key_type: Literal["stats", "sites"] = Field(
        "stats", title="Key permissions", description="Sites API keys are available on Enterprise and enable site writes."
    )
    base_url: str = Field(
        BASE_URL, title="Plausible URL", description="Use the default for Plausible Cloud or your self-hosted HTTPS URL."
    )

    model_config = ConfigDict(title="Plausible API Key", json_schema_extra={
        "x-credential-url": "https://plausible.io/settings/api-keys",
        "x-credential-instructions": "Create a Stats API key for analytics and site reads. Enterprise customers can use a Sites API key for site writes.",
    })

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("Plausible URL must be an HTTPS origin without a path or query")
        return value.rstrip("/")


def operation_field(name: str, category: str, label: str):
    return Field(name, title=label, json_schema_extra={
        "const": name, "ui:hidden": True, "x-category": category,
        "x-is-trigger": False, "x-display-name": label,
    })


class SiteConfig(BaseModel):
    site_id: str = Field(..., title="Site", description="The site domain in Plausible.", json_schema_extra=SITE_FIELD)


class QueryStatsConfig(SiteConfig):
    operation: Literal["query_stats"] = operation_field("query_stats", "Analytics", "Query Stats")
    metrics: str = Field("visitors,pageviews", title="Metrics", description="Comma-separated Stats API metrics.")
    date_range: str = Field("7d", title="Date range", description="Preset such as 7d, 30d or a JSON array of ISO dates.")
    dimensions: str = Field("", title="Dimensions", description="Comma-separated dimensions such as event:page or visit:source.")
    filters_json: Optional[str] = Field(None, title="Filters JSON", json_schema_extra={"ui:widget": "textarea"})
    order_by_json: Optional[str] = Field(None, title="Order JSON", json_schema_extra={"ui:widget": "textarea"})
    include_imports: bool = Field(False, title="Include imported data")
    include_total_rows: bool = Field(False, title="Include total rows")
    limit: int = Field(1000, ge=1, le=10000, title="Page size")
    offset: int = Field(0, ge=0, title="Offset")


class OverviewConfig(SiteConfig):
    operation: Literal["get_overview"] = operation_field("get_overview", "Analytics", "Get Overview")
    date_range: str = Field("7d", title="Date range")


class RealtimeConfig(SiteConfig):
    operation: Literal["get_realtime"] = operation_field("get_realtime", "Analytics", "Get Realtime Visitors")


class BreakdownConfig(SiteConfig):
    operation: Literal["get_breakdown"] = operation_field("get_breakdown", "Analytics", "Get Breakdown")
    dimension: str = Field("event:page", title="Dimension")
    metric: str = Field("visitors", title="Metric")
    date_range: str = Field("7d", title="Date range")
    limit: int = Field(100, ge=1, le=10000, title="Page size")
    offset: int = Field(0, ge=0, title="Offset")


class TimeseriesConfig(SiteConfig):
    operation: Literal["get_timeseries"] = operation_field("get_timeseries", "Analytics", "Get Timeseries")
    interval: Literal["time:hour", "time:day", "time:week", "time:month"] = Field("time:day", title="Interval")
    metric: str = Field("visitors", title="Metric")
    date_range: str = Field("30d", title="Date range")


class ListSitesConfig(BaseModel):
    operation: Literal["list_sites"] = operation_field("list_sites", "Sites", "List Sites")
    team_id: Optional[str] = Field(None, title="Team ID")
    after: Optional[str] = Field(None, title="After cursor")
    limit: int = Field(100, ge=1, le=100, title="Page size")


class ListTeamsConfig(BaseModel):
    operation: Literal["list_teams"] = operation_field("list_teams", "Sites", "List Teams")
    after: Optional[str] = Field(None, title="After cursor")
    limit: int = Field(100, ge=1, le=100, title="Page size")


class GetSiteConfig(SiteConfig):
    operation: Literal["get_site"] = operation_field("get_site", "Sites", "Get Site")


class CreateSiteConfig(BaseModel):
    operation: Literal["create_site"] = operation_field("create_site", "Sites", "Create Site")
    domain: str = Field(..., title="Domain")
    timezone: str = Field("Etc/UTC", title="Timezone")
    team_id: Optional[str] = Field(None, title="Team ID")
    tracker_settings_json: Optional[str] = Field(None, title="Tracker settings JSON", json_schema_extra={"ui:widget": "textarea"})


class UpdateSiteConfig(SiteConfig):
    operation: Literal["update_site"] = operation_field("update_site", "Sites", "Update Site")
    new_domain: Optional[str] = Field(None, title="New domain")
    tracker_settings_json: Optional[str] = Field(None, title="Tracker settings JSON", json_schema_extra={"ui:widget": "textarea"})


class DeleteSiteConfig(SiteConfig):
    operation: Literal["delete_site"] = operation_field("delete_site", "Sites", "Delete Site")
    confirm_domain: str = Field(..., title="Confirm domain", description="Enter the site domain again. This permanently deletes site data.")


class ListGoalsConfig(SiteConfig):
    operation: Literal["list_goals"] = operation_field("list_goals", "Goals", "List Goals")
    after: Optional[str] = Field(None, title="After cursor")
    limit: int = Field(100, ge=1, le=100, title="Page size")


class UpsertGoalConfig(SiteConfig):
    operation: Literal["upsert_goal"] = operation_field("upsert_goal", "Goals", "Find or Create Goal")
    goal_type: Literal["event", "page"] = Field("event", title="Goal type")
    event_name: Optional[str] = Field(None, title="Event name")
    page_path: Optional[str] = Field(None, title="Page path")
    display_name: Optional[str] = Field(None, title="Display name")
    custom_props_json: Optional[str] = Field(None, title="Custom properties JSON", json_schema_extra={"ui:widget": "textarea"})

    @model_validator(mode="after")
    def validate_goal(self):
        if self.goal_type == "event" and not self.event_name:
            raise ValueError("Event goals need an event name")
        if self.goal_type == "page" and not self.page_path:
            raise ValueError("Page goals need a page path")
        return self


class DeleteGoalConfig(SiteConfig):
    operation: Literal["delete_goal"] = operation_field("delete_goal", "Goals", "Delete Goal")
    goal_id: str = Field(..., title="Goal ID")


class ListCustomPropsConfig(SiteConfig):
    operation: Literal["list_custom_properties"] = operation_field("list_custom_properties", "Custom Properties", "List Custom Properties")


class UpsertCustomPropConfig(SiteConfig):
    operation: Literal["upsert_custom_property"] = operation_field("upsert_custom_property", "Custom Properties", "Create Custom Property")
    property: str = Field(..., title="Property name")


class DeleteCustomPropConfig(SiteConfig):
    operation: Literal["delete_custom_property"] = operation_field("delete_custom_property", "Custom Properties", "Delete Custom Property")
    property: str = Field(..., title="Property name")


class ListGuestsConfig(SiteConfig):
    operation: Literal["list_guests"] = operation_field("list_guests", "Guests", "List Guests")
    after: Optional[str] = Field(None, title="After cursor")
    limit: int = Field(100, ge=1, le=100, title="Page size")


class UpsertGuestConfig(SiteConfig):
    operation: Literal["upsert_guest"] = operation_field("upsert_guest", "Guests", "Invite Guest")
    email: str = Field(..., title="Email")
    role: Literal["viewer", "editor"] = Field("viewer", title="Role")


class DeleteGuestConfig(SiteConfig):
    operation: Literal["delete_guest"] = operation_field("delete_guest", "Guests", "Remove Guest")
    email: str = Field(..., title="Email")


class SharedLinkConfig(SiteConfig):
    operation: Literal["upsert_shared_link"] = operation_field("upsert_shared_link", "Sites", "Find or Create Shared Link")
    name: str = Field(..., title="Link name")


class RecordEventConfig(SiteConfig):
    operation: Literal["record_event"] = operation_field("record_event", "Events", "Record Custom Event")
    name: str = Field(..., title="Event name")
    url: str = Field(..., title="Page URL")
    user_agent: str = Field(..., title="Visitor User-Agent", description="Forward the actual visitor's User-Agent for accurate unique visitor counts.")
    client_ip: Optional[str] = Field(None, title="Visitor IP", description="Use the original visitor IP. Without it, Plausible may discard events sent from NoClick's server IP.")
    referrer: Optional[str] = Field(None, title="Referrer")
    props_json: Optional[str] = Field(None, title="Properties JSON", json_schema_extra={"ui:widget": "textarea"})
    revenue_json: Optional[str] = Field(None, title="Revenue JSON", json_schema_extra={"ui:widget": "textarea"})


class RecordPageviewConfig(SiteConfig):
    operation: Literal["record_pageview"] = operation_field("record_pageview", "Events", "Record Pageview")
    url: str = Field(..., title="Page URL")
    user_agent: str = Field(..., title="Visitor User-Agent")
    client_ip: Optional[str] = Field(None, title="Visitor IP", description="Use the original visitor IP. Without it, Plausible may discard events sent from NoClick's server IP.")
    referrer: Optional[str] = Field(None, title="Referrer")
    props_json: Optional[str] = Field(None, title="Properties JSON", json_schema_extra={"ui:widget": "textarea"})


PlausibleConfig = Annotated[Union[
    QueryStatsConfig, OverviewConfig, RealtimeConfig, BreakdownConfig, TimeseriesConfig,
    ListSitesConfig, ListTeamsConfig, GetSiteConfig, CreateSiteConfig, UpdateSiteConfig,
    DeleteSiteConfig, ListGoalsConfig, UpsertGoalConfig, DeleteGoalConfig,
    ListCustomPropsConfig, UpsertCustomPropConfig, DeleteCustomPropConfig,
    ListGuestsConfig, UpsertGuestConfig, DeleteGuestConfig, SharedLinkConfig,
    RecordEventConfig, RecordPageviewConfig,
], Discriminator("operation")]


class PlausibleNodeConfig(NodeConfig[PlausibleConfig, PlausibleApiKeyCredential]):
    pass


def _json(value: Optional[str], expected: type, label: str):
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(parsed, expected):
        raise ValueError(f"{label} must be a JSON {expected.__name__}")
    return parsed


def _date_range(value: str):
    value = value.strip()
    return _json(value, list, "Date range") if value.startswith("[") else value


def _path_part(value: str):
    return quote(value, safe="")


async def _request(
    credential: PlausibleApiKeyCredential, method: str, path: str, action: str,
    *, params: Optional[Dict[str, Any]] = None, body: Optional[Dict[str, Any]] = None,
    form: Optional[Dict[str, Any]] = None, event_user_agent: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> Dict[str, Any]:
    headers = {"Accept": "application/json"}
    if event_user_agent is None:
        headers["Authorization"] = f"Bearer {credential.api_key}"
    else:
        headers["User-Agent"] = event_user_agent
        if client_ip:
            headers["X-Forwarded-For"] = client_ip
    if body is not None:
        headers["Content-Type"] = "application/json"
    kwargs: Dict[str, Any] = {"headers": headers, "params": {k: v for k, v in (params or {}).items() if v is not None}}
    if body is not None:
        kwargs["json"] = {k: v for k, v in body.items() if v is not None}
    if form is not None:
        kwargs["files"] = {k: (None, str(v)) for k, v in form.items() if v is not None}
    start = time.monotonic()
    try:
        async with guarded_async_client(timeout=30.0, follow_redirects=False) as client:
            response = await client.request(method, f"{credential.base_url}{path}", **kwargs)
        elapsed = round((time.monotonic() - start) * 1000, 2)
        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text[:2000]}
        if response.status_code >= 400:
            message = data.get("error") or data.get("message") if isinstance(data, dict) else str(data)
            return {"status": "error", "action": action, "status_code": response.status_code,
                    "error": str(message)[:500], "timing_ms": {"api_request": elapsed}}
        result = {"status": "success", "action": action, "status_code": response.status_code,
                  "data": data, "timing_ms": {"api_request": elapsed}}
        if event_user_agent is not None:
            result["accepted"] = response.status_code == 202
            result["dropped"] = response.headers.get("x-plausible-dropped") == "1"
            if result["dropped"]:
                result["status"] = "error"
                result["error"] = (
                    "Plausible dropped the event after accepting the HTTP request. "
                    "Check the original visitor IP, User-Agent, and site exclusion rules."
                )
        return result
    except httpx.HTTPError as exc:
        return {"status": "error", "action": action, "error": str(exc)[:500],
                "timing_ms": {"api_request": round((time.monotonic() - start) * 1000, 2)}}


class PlausibleNode(WorkflowNode):
    """Query analytics, emit events, and manage Plausible sites."""

    integration_type = "automation-plausible"

    edit_examples = [
        "Show visitors and pageviews for my Plausible site in the last 7 days",
        "Break down traffic by source and country",
        "Record a signup event in Plausible",
        "List goals configured for my site",
    ]
    connection_evidence = ConnectionEvidence(
        field="site_id", operation="list_sites", noun="sites", label_keys=("domain",),
    )

    @classmethod
    def get_config_model(cls):
        return PlausibleNodeConfig

    @classmethod
    async def load_field_options(
        cls, field_name: str, credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None, search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name != "site_id":
            return {"options": []}
        credential = PlausibleApiKeyCredential.model_validate(credential_data)
        result = await _request(credential, "GET", "/api/v1/sites", "list_sites", params={"limit": 100})
        if result["status"] != "success":
            return result
        sites = result.get("data", {}).get("sites", [])
        if search:
            sites = [item for item in sites if search.lower() in item.get("domain", "").lower()]
        return {"options": [{"label": item["domain"], "value": item["domain"]}
                             for item in sites if isinstance(item, dict) and item.get("domain")]}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, PlausibleNodeConfig) or not self.config.credentials:
            raise ValueError("Plausible API key credential is required")
        c = self.config.config
        key = self.config.credentials
        action = c.operation
        site = getattr(c, "site_id", None)
        site_path = f"/api/v1/sites/{_path_part(site)}" if site else None
        write_ops = {
            "create_site", "update_site", "delete_site", "upsert_goal", "delete_goal",
            "upsert_custom_property", "delete_custom_property", "upsert_guest",
            "delete_guest", "upsert_shared_link",
        }
        if action in write_ops and key.key_type != "sites":
            raise ValueError("This operation requires an Enterprise Sites API key")
        if action == "query_stats":
            body = {"site_id": site, "metrics": [s.strip() for s in c.metrics.split(",") if s.strip()],
                    "date_range": _date_range(c.date_range),
                    "dimensions": [s.strip() for s in c.dimensions.split(",") if s.strip()],
                    "filters": _json(c.filters_json, list, "Filters"),
                    "order_by": _json(c.order_by_json, list, "Order"),
                    "include": {"imports": c.include_imports, "total_rows": c.include_total_rows},
                    "pagination": {"limit": c.limit, "offset": c.offset}}
            return await _request(key, "POST", "/api/v2/query", action, body=body)
        if action in {"get_overview", "get_realtime", "get_breakdown", "get_timeseries"}:
            metrics = ["visitors", "visits", "pageviews", "bounce_rate", "visit_duration"] if action == "get_overview" else ["visitors"] if action == "get_realtime" else [c.metric]
            dimensions = [c.dimension] if action == "get_breakdown" else [c.interval] if action == "get_timeseries" else []
            now = datetime.now(timezone.utc)
            realtime_range = [(now - timedelta(minutes=30)).isoformat(), now.isoformat()]
            body = {"site_id": site, "metrics": metrics, "date_range": realtime_range if action == "get_realtime" else c.date_range,
                    "dimensions": dimensions}
            if action == "get_breakdown":
                body["pagination"] = {"limit": c.limit, "offset": c.offset}
            return await _request(key, "POST", "/api/v2/query", action, body=body)
        if action in {"record_event", "record_pageview"}:
            parsed = urlparse(c.url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.hostname != site:
                raise ValueError("Page URL must be an HTTP(S) URL on the selected site domain")
            body = {"name": c.name if action == "record_event" else "pageview", "url": c.url,
                    "domain": site, "referrer": c.referrer,
                    "props": _json(c.props_json, dict, "Properties")}
            if action == "record_event":
                body["revenue"] = _json(c.revenue_json, dict, "Revenue")
            return await _request(key, "POST", "/api/event", action, body=body,
                                  event_user_agent=c.user_agent, client_ip=c.client_ip)
        if action in {"list_sites", "list_teams", "list_goals", "list_guests"}:
            paths = {"list_sites": "/api/v1/sites", "list_teams": "/api/v1/sites/teams",
                     "list_goals": "/api/v1/sites/goals", "list_guests": "/api/v1/sites/guests"}
            params = {"after": c.after, "limit": c.limit}
            if site:
                params["site_id"] = site
            if action == "list_sites":
                params["team_id"] = c.team_id
            return await _request(key, "GET", paths[action], action, params=params)
        if action == "get_site":
            return await _request(key, "GET", site_path, action)
        if action == "create_site":
            body = {"domain": c.domain, "timezone": c.timezone, "team_id": c.team_id,
                    "tracker_script_configuration": _json(c.tracker_settings_json, dict, "Tracker settings")}
            return await _request(key, "POST", "/api/v1/sites", action, body=body)
        if action == "update_site":
            body = {"domain": c.new_domain,
                    "tracker_script_configuration": _json(c.tracker_settings_json, dict, "Tracker settings")}
            if all(value is None for value in body.values()):
                raise ValueError("Provide a new domain or tracker settings")
            return await _request(key, "PUT", site_path, action, body=body)
        if action == "delete_site":
            if c.confirm_domain != site:
                raise ValueError("Confirm domain must match the selected site")
            return await _request(key, "DELETE", site_path, action)
        if action == "list_custom_properties":
            return await _request(key, "GET", "/api/v1/sites/custom-props", action, params={"site_id": site})
        if action == "upsert_shared_link":
            return await _request(key, "PUT", "/api/v1/sites/shared-links", action, body={"site_id": site, "name": c.name})
        if action == "upsert_goal":
            body = {"site_id": site, "goal_type": c.goal_type, "event_name": c.event_name,
                    "page_path": c.page_path, "display_name": c.display_name,
                    "custom_props": _json(c.custom_props_json, dict, "Custom properties")}
            return await _request(key, "PUT", "/api/v1/sites/goals", action, body=body)
        if action == "delete_goal":
            return await _request(key, "DELETE", f"/api/v1/sites/goals/{_path_part(c.goal_id)}", action, body={"site_id": site})
        if action == "upsert_custom_property":
            return await _request(key, "PUT", "/api/v1/sites/custom-props", action,
                                  form={"site_id": site, "property": c.property})
        if action == "delete_custom_property":
            return await _request(key, "DELETE", f"/api/v1/sites/custom-props/{_path_part(c.property)}", action,
                                  form={"site_id": site})
        if action == "upsert_guest":
            return await _request(key, "PUT", "/api/v1/sites/guests", action,
                                  body={"site_id": site, "email": c.email, "role": c.role})
        if action == "delete_guest":
            return await _request(key, "DELETE", f"/api/v1/sites/guests/{_path_part(c.email)}", action)
        raise ValueError(f"Unsupported Plausible operation: {action}")
