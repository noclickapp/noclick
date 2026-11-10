"""Statuspage Manage API v1: incidents, maintenance, components and subscribers.

Reference and provider-published OpenAPI: https://developer.statuspage.io/
API keys use the literal ``OAuth`` authorization scheme, without an OAuth flow.
Each operation makes one request. Lists expose the provider's page parameters;
there is no hidden pagination, mutation retry or notification suppression.
Maintenance is an incident with status=scheduled, scheduled_for/scheduled_until;
update_incident moves it through in_progress, verifying and completed.
Webhook subscriptions can be created with create_subscriber (email + endpoint).
This node has no webhook receiver/trigger.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

API_BASE = "https://api.statuspage.io/v1"
IncidentStatus = Literal["investigating", "identified", "monitoring", "resolved", "scheduled", "in_progress", "verifying", "completed"]
ComponentStatus = Literal["operational", "under_maintenance", "degraded_performance", "partial_outage", "major_outage"]


def operation(name: str, title: str, description: str):
    return Field(name, title=title, description=description,
                 json_schema_extra={"const": name, "ui:hidden": True})


class StatuspageAPIKeyCredential(BaseModel):
    credential_type: Literal["statuspage_api_key"] = Field("statuspage_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", description="Your Statuspage API key",
                         json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Statuspage API Key", json_schema_extra={
        "x-credential-url": "https://support.atlassian.com/statuspage/docs/create-and-manage-api-keys/",
        "x-credential-instructions": "In Statuspage, open your avatar menu → API info, create an API key, and paste it here. The key can access the pages available to your account.",
    })


class PageConfig(BaseModel):
    page_id: str = Field(..., min_length=1, title="Page ID", description="Page identifier from Statuspage API info or List Pages")


class ListPagesConfig(BaseModel):
    operation: Literal["list_pages"] = operation("list_pages", "List Pages", "List the pages accessible to this API key; also proves the connected account.")


class ListIncidentsConfig(PageConfig):
    operation: Literal["list_incidents"] = operation("list_incidents", "List Incidents", "Read one page of incidents, optionally searching their name, status and updates.")
    q: str | None = Field(None, title="Search", description="Search incident text")
    limit: int = Field(100, ge=1, le=100, description="Maximum results per page")
    page: int = Field(1, ge=1, description="Page offset to fetch")


class IncidentConfig(PageConfig):
    incident_id: str = Field(..., min_length=1, title="Incident ID", description="Incident or scheduled maintenance identifier")


class GetIncidentConfig(IncidentConfig):
    operation: Literal["get_incident"] = operation("get_incident", "Get Incident", "Read an incident or maintenance, including its update history.")


class IncidentFields(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255, title="Name")
    status: IncidentStatus | None = Field(None, description="Incident status; use scheduled for new maintenance, in_progress/verifying/completed to transition it")
    body: str | None = Field(None, max_length=25000, description="Message to publish as an incident update", json_schema_extra={"ui:widget": "textarea"})
    impact_override: Literal["none", "maintenance", "minor", "major", "critical"] | None = Field(None, title="Impact Override")
    component_ids: str | None = Field(None, title="Component IDs", description="JSON array of affected component IDs; omit to leave unchanged")
    components: str | None = Field(None, title="Component Status Changes", description='JSON object mapping component IDs to statuses, e.g. {"component-id":"partial_outage"}')
    deliver_notifications: bool | None = Field(None, description="Whether to notify subscribers. When omitted, Statuspage applies its default (true).")
    scheduled_for: str | None = Field(None, description="Maintenance start, ISO 8601 with timezone", json_schema_extra={"format": "date-time"})
    scheduled_until: str | None = Field(None, description="Maintenance end, ISO 8601 with timezone", json_schema_extra={"format": "date-time"})
    scheduled_remind_prior: bool | None = None
    scheduled_auto_in_progress: bool | None = None
    scheduled_auto_completed: bool | None = None
    auto_transition_to_maintenance_state: bool | None = None
    auto_transition_to_operational_state: bool | None = None
    auto_transition_deliver_notifications_at_start: bool | None = None
    auto_transition_deliver_notifications_at_end: bool | None = None

    @field_validator("components")
    @classmethod
    def valid_components(cls, value):
        if value is not None:
            data = json.loads(value)
            allowed = {"operational", "under_maintenance", "degraded_performance", "partial_outage", "major_outage", ""}
            if not isinstance(data, dict) or any(not key or not isinstance(status, str) or status not in allowed for key, status in data.items()):
                raise ValueError("Components must map nonempty IDs to Statuspage component statuses")
        return value

    @field_validator("component_ids")
    @classmethod
    def valid_component_ids(cls, value):
        return _validate_ids(value)

    @field_validator("scheduled_for", "scheduled_until")
    @classmethod
    def valid_timestamp(cls, value):
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Include a timezone in maintenance timestamps")
        return value

    @model_validator(mode="after")
    def maintenance_window(self):
        if self.scheduled_for and self.scheduled_until:
            start = datetime.fromisoformat(self.scheduled_for.replace("Z", "+00:00"))
            end = datetime.fromisoformat(self.scheduled_until.replace("Z", "+00:00"))
            if end <= start:
                raise ValueError("Maintenance end must follow its start")
        return self


def _validate_ids(value):
    if value is not None:
        data = json.loads(value)
        if not isinstance(data, list) or not data or any(not isinstance(item, str) or not item.strip() for item in data):
            raise ValueError("Component IDs must be a nonempty JSON array of strings")
    return value


class CreateIncidentConfig(PageConfig, IncidentFields):
    operation: Literal["create_incident"] = operation("create_incident", "Create Incident or Maintenance", "Create an incident; for scheduled maintenance set status=scheduled and supply both timestamps.")
    name: str = Field(..., min_length=1, max_length=255, title="Name")

    @model_validator(mode="after")
    def required_window(self):
        if self.status == "scheduled" and not (self.scheduled_for and self.scheduled_until):
            raise ValueError("Scheduled maintenance requires both scheduled_for and scheduled_until")
        return self


class UpdateIncidentConfig(IncidentConfig, IncidentFields):
    operation: Literal["update_incident"] = operation("update_incident", "Update Incident or Maintenance", "Publish an update, resolve an incident, or transition a maintenance. Omitted fields are unchanged.")


class DeleteIncidentConfig(IncidentConfig):
    operation: Literal["delete_incident"] = operation("delete_incident", "Delete Incident", "Permanently delete an incident or scheduled maintenance.")


class ListUnresolvedIncidentsConfig(PageConfig):
    page: int = Field(1, ge=1, description="Page offset to fetch")
    per_page: int = Field(100, ge=1, le=100, description="Maximum results per page")
    operation: Literal["list_unresolved_incidents"] = operation("list_unresolved_incidents", "List Unresolved Incidents", "Read unresolved incidents for a page.")


class MaintenanceListConfig(PageConfig):
    page: int = Field(1, ge=1, description="Page offset to fetch")
    per_page: int = Field(100, ge=1, le=100, description="Maximum results per page")


class ListScheduledMaintenanceConfig(MaintenanceListConfig):
    operation: Literal["list_scheduled_maintenance"] = operation("list_scheduled_maintenance", "List Scheduled Maintenance", "Read one page of scheduled incidents.")


class ListUpcomingMaintenanceConfig(MaintenanceListConfig):
    operation: Literal["list_upcoming_maintenance"] = operation("list_upcoming_maintenance", "List Upcoming Maintenance", "Read one page of upcoming maintenance.")


class ListActiveMaintenanceConfig(MaintenanceListConfig):
    operation: Literal["list_active_maintenance"] = operation("list_active_maintenance", "List Active Maintenance", "Read one page of maintenance currently in progress.")


class ListComponentsConfig(MaintenanceListConfig):
    operation: Literal["list_components"] = operation("list_components", "List Components", "Read one page of components and their statuses (at most 100).")


class ComponentConfig(PageConfig):
    component_id: str = Field(..., min_length=1, title="Component ID")


class GetComponentConfig(ComponentConfig):
    operation: Literal["get_component"] = operation("get_component", "Get Component", "Read a component and its status.")


class ComponentFields(BaseModel):
    name: str | None = Field(None, min_length=1, title="Name")
    description: str | None = None
    status: ComponentStatus | None = None
    group_id: str | None = Field(None, title="Group ID")
    only_show_if_degraded: bool | None = Field(None, description="Requires the corresponding Statuspage feature flag")
    showcase: bool | None = None


class CreateComponentConfig(PageConfig, ComponentFields):
    operation: Literal["create_component"] = operation("create_component", "Create Component", "Create a component on the page.")
    name: str = Field(..., min_length=1, title="Name")


class UpdateComponentConfig(ComponentConfig, ComponentFields):
    operation: Literal["update_component"] = operation("update_component", "Update Component", "Change a component's status, name, description or group.")


class DeleteComponentConfig(ComponentConfig):
    operation: Literal["delete_component"] = operation("delete_component", "Delete Component", "Permanently delete a component.")


class ListSubscribersConfig(PageConfig):
    operation: Literal["list_subscribers"] = operation("list_subscribers", "List Subscribers", "Read one page of subscribers; this API's first page is zero.")
    page: int = Field(0, ge=0, description="Zero-based subscriber page")
    limit: int = Field(100, ge=1, le=100)
    q: str | None = Field(None, title="Search", description="Search contact information (except Slack)")
    type: Literal["email", "sms", "webhook", "slack", "teams", "integration_partner"] | None = Field(None, title="Subscriber Type")
    state: Literal["active", "unconfirmed", "quarantined", "all"] | None = None
    sort_field: Literal["primary", "created_at", "quarantined_at", "relevance"] | None = None
    sort_direction: Literal["asc", "desc"] | None = None


class SubscriberConfig(PageConfig):
    subscriber_id: str = Field(..., min_length=1, title="Subscriber ID")


class GetSubscriberConfig(SubscriberConfig):
    operation: Literal["get_subscriber"] = operation("get_subscriber", "Get Subscriber", "Read one subscriber.")


class CreateSubscriberConfig(PageConfig):
    operation: Literal["create_subscriber"] = operation("create_subscriber", "Create Subscriber", "Create an email, SMS or webhook subscriber. Statuspage may send a confirmation notification.")
    email: str | None = Field(None, description="Email address for email and webhook subscribers")
    endpoint: str | None = Field(None, description="Webhook endpoint URL (also supply email)")
    phone_country: str | None = Field(None, description="Two-letter country code for SMS")
    phone_number: str | None = Field(None, description="Local phone number for SMS")
    skip_confirmation_notification: bool | None = Field(None, description="Skip confirmation and automatically opt in email subscribers (paid pages only; ignored for trials)")
    page_access_user: str | None = Field(None, title="Page Access User Code")
    component_ids: str | None = Field(None, description="Nonempty JSON array of component IDs; omit to subscribe to all")

    @field_validator("component_ids")
    @classmethod
    def valid_ids(cls, value):
        return _validate_ids(value)

    @model_validator(mode="after")
    def contact_required(self):
        if not self.email and not (self.phone_country and self.phone_number):
            raise ValueError("Supply email or both phone_country and phone_number")
        if self.endpoint and not self.email:
            raise ValueError("Webhook subscribers require email and endpoint")
        if bool(self.phone_country) != bool(self.phone_number):
            raise ValueError("SMS subscribers require both phone_country and phone_number")
        return self


class UpdateSubscriberConfig(SubscriberConfig):
    operation: Literal["update_subscriber"] = operation("update_subscriber", "Update Subscriber Components", "Change a subscriber's component subscriptions; omit component_ids to subscribe to all components.")
    component_ids: str | None = Field(None, description="Nonempty JSON array of component IDs; omit for all components")

    @field_validator("component_ids")
    @classmethod
    def valid_ids(cls, value):
        return _validate_ids(value)


class UnsubscribeSubscriberConfig(SubscriberConfig):
    operation: Literal["unsubscribe_subscriber"] = operation("unsubscribe_subscriber", "Unsubscribe Subscriber", "Unsubscribe one subscriber, optionally suppressing the unsubscription notification.")
    skip_unsubscription_notification: bool | None = None


StatuspageConfig = Annotated[Union[
    ListPagesConfig, ListIncidentsConfig, GetIncidentConfig, CreateIncidentConfig,
    UpdateIncidentConfig, DeleteIncidentConfig, ListUnresolvedIncidentsConfig,
    ListScheduledMaintenanceConfig, ListUpcomingMaintenanceConfig, ListActiveMaintenanceConfig,
    ListComponentsConfig, GetComponentConfig, CreateComponentConfig, UpdateComponentConfig,
    DeleteComponentConfig, ListSubscribersConfig, GetSubscriberConfig, CreateSubscriberConfig,
    UpdateSubscriberConfig, UnsubscribeSubscriberConfig,
], Field(discriminator="operation")]


class StatuspageNodeConfig(NodeConfig[StatuspageConfig, StatuspageAPIKeyCredential]):
    pass


# Each operation maps to exactly one documented operation; maintenance writes
# intentionally use the incident API, as Statuspage documents.
ROUTES = {
    "list_pages": ("GET", "/pages"),
    "list_incidents": ("GET", "/pages/{page_id}/incidents"),
    "get_incident": ("GET", "/pages/{page_id}/incidents/{incident_id}"),
    "create_incident": ("POST", "/pages/{page_id}/incidents"),
    "update_incident": ("PATCH", "/pages/{page_id}/incidents/{incident_id}"),
    "delete_incident": ("DELETE", "/pages/{page_id}/incidents/{incident_id}"),
    "list_unresolved_incidents": ("GET", "/pages/{page_id}/incidents/unresolved"),
    "list_scheduled_maintenance": ("GET", "/pages/{page_id}/incidents/scheduled"),
    "list_upcoming_maintenance": ("GET", "/pages/{page_id}/incidents/upcoming"),
    "list_active_maintenance": ("GET", "/pages/{page_id}/incidents/active_maintenance"),
    "list_components": ("GET", "/pages/{page_id}/components"),
    "get_component": ("GET", "/pages/{page_id}/components/{component_id}"),
    "create_component": ("POST", "/pages/{page_id}/components"),
    "update_component": ("PATCH", "/pages/{page_id}/components/{component_id}"),
    "delete_component": ("DELETE", "/pages/{page_id}/components/{component_id}"),
    "list_subscribers": ("GET", "/pages/{page_id}/subscribers"),
    "get_subscriber": ("GET", "/pages/{page_id}/subscribers/{subscriber_id}"),
    "create_subscriber": ("POST", "/pages/{page_id}/subscribers"),
    "update_subscriber": ("PATCH", "/pages/{page_id}/subscribers/{subscriber_id}"),
    "unsubscribe_subscriber": ("DELETE", "/pages/{page_id}/subscribers/{subscriber_id}"),
}


class StatuspageNode(WorkflowNode):
    integration_type = "automation-statuspage"
    credential_provider_labels = {"statuspage": "Statuspage Account"}
    connection_evidence = ConnectionEvidence(operation="list_pages", noun="pages", label_keys=("name",))
    edit_examples = ["Publish an incident update", "Schedule maintenance for my API", "Mark a component operational", "Subscribe a customer to incident notifications"]

    @classmethod
    def get_config_model(cls):
        return StatuspageNodeConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, StatuspageNodeConfig):
            raise ValueError("Statuspage configuration is required")
        if not self.config.credentials:
            raise ValueError("Connect a Statuspage API key")
        config = self.config.config
        op = config.operation
        method, template = ROUTES[op]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        ids = {key: quote(str(values.pop(key)), safe="") for key in tuple(values) if "{" + key + "}" in template}
        path = template.format(**ids)
        for key in ("components", "component_ids"):
            if key in values:
                values[key] = json.loads(values[key])
        kwargs = {}
        if method == "GET" or op == "unsubscribe_subscriber":
            kwargs["params"] = values
        elif method in ("POST", "PATCH"):
            # Updating a subscriber is the API's exception: component_ids lives
            # at the top level, NOT inside a subscriber envelope.
            if op == "update_subscriber":
                body = values
            else:
                resource = "incident" if "incident" in op else "component" if "component" in op else "subscriber"
                body = {resource: values}
            kwargs["json"] = body
        started = time.monotonic()
        result = {"operation": op}
        api_key = self.config.credentials.api_key
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(method, API_BASE + path,
                    headers={"Authorization": f"OAuth {api_key}", "Accept": "application/json"}, **kwargs)
            result["status_code"] = response.status_code
            if response.status_code >= 400:
                result.update(status="error", error=response.text.replace(api_key, "<redacted>"))
                if response.headers.get("Retry-After"):
                    result["retry_after"] = response.headers["Retry-After"]
                return result
            if op == "delete_component" and response.status_code == 204:
                result.update(status="success", data={"deleted": True})
                return result
            data = response.json()
            if isinstance(data, dict) and (data.get("error") or data.get("errors") or data.get("success") is False):
                result.update(status="error", error=json.dumps(data).replace(api_key, "<redacted>"))
                return result
            if op.startswith("list_"):
                if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                    raise ValueError("Statuspage returned an invalid list response")
                if op == "list_pages" and any(not isinstance(item.get("id"), str) or not item["id"].strip() or not isinstance(item.get("name"), str) or not item["name"].strip() for item in data):
                    raise ValueError("Statuspage returned an invalid page identity")
            elif not isinstance(data, dict):
                raise ValueError("Statuspage returned an invalid object response")
            if op.startswith("list_"):
                collection = "pages" if op == "list_pages" else "components" if op == "list_components" else "subscribers" if op == "list_subscribers" else "maintenances" if "maintenance" in op else "incidents"
                data = {collection: data, "count": len(data)}
            result.update(status="success", data=data)
            return result
        except (httpx.RequestError, ValueError) as exc:
            result.update(status="error", error=str(exc).replace(api_key, "<redacted>"))
            return result
        finally:
            result["timing_ms"] = {"total": round((time.monotonic() - started) * 1000, 2)}
