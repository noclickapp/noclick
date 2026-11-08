"""Automate Rootly incidents and follow-up work using its published v1 JSON:API.

Each operation makes one documented request. Collection reads return one page;
writes are never retried automatically, including after an uncertain outcome.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.rootly.com"
MEDIA_TYPE = "application/vnd.api+json"
CREDENTIAL_TYPE = "rootly_api_key"


class RootlyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Rootly API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.rootly.com/api-reference/overview",
            "x-credential-instructions": "In Rootly, open the organization dropdown, then Organization Settings > API Keys. Create a key with access to the incidents and resources you want to automate, and paste the key here without the Bearer prefix. NoClick sends it only to api.rootly.com. Connecting reads your incidents; write permissions depend on the key's access.",
        },
    )
    credential_type: Literal["rootly_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def bounded_ids(cls, value, info):
        if info.field_name.endswith("_id") and isinstance(value, str):
            if not value or len(value) > 255 or value in {".", ".."} or any(c in value for c in "/\\%?#") or any(c.isspace() for c in value):
                raise ValueError("Use a single Rootly resource ID")
        return value


class _Page(_Input):
    page_number: int = Field(1, ge=1, le=1000000, description="Read one page. Increment the page number to fetch another page.")
    page_size: int = Field(20, ge=1, le=100, description="Maximum number of records requested in this page.")


class RootlyListIncidents(_Page):
    operation: Literal["list_incidents"] = "list_incidents"
    search: Optional[str] = Field(None, max_length=1000, description="Rootly incident search filter.")
    status: Optional[str] = Field(None, max_length=255, description="Rootly status filter, for example started or resolved.")
    severity_id: Optional[str] = None


class RootlyGetIncident(_Input):
    operation: Literal["get_incident"] = "get_incident"
    incident_id: str


IncidentStatus = Literal["in_triage", "started", "detected", "acknowledged", "mitigated", "resolved", "closed", "cancelled", "scheduled", "in_progress", "completed"]


class _IncidentFields(_Input):
    title: Optional[str] = Field(None, min_length=1, max_length=1000)
    summary: Optional[str] = Field(None, max_length=50000)
    status: Optional[IncidentStatus] = None
    severity_id: Optional[str] = None
    service_ids: Optional[list[str]] = Field(None, max_length=100, description="Service IDs to attach. An empty list clears the selection.")
    group_ids: Optional[list[str]] = Field(None, max_length=100, title="Team IDs", description="Rootly calls these group_ids. An empty list clears the selection.")


class RootlyCreateIncident(_IncidentFields):
    operation: Literal["create_incident"] = "create_incident"
    title: str = Field(..., min_length=1, max_length=1000)
    idempotency_key: Optional[str] = Field(None, min_length=1, max_length=255, description="Reuse the same key when retrying this creation within 24 hours to prevent duplicates.")

    @field_validator("idempotency_key")
    @classmethod
    def header_value(cls, value):
        if value is not None and (not value.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Use a printable ASCII idempotency key")
        return value


class RootlyUpdateIncident(_IncidentFields):
    operation: Literal["update_incident"] = "update_incident"
    incident_id: str
    resolution_message: Optional[str] = Field(None, max_length=50000)
    mitigation_message: Optional[str] = Field(None, max_length=50000)

    @model_validator(mode="after")
    def has_change(self):
        if not any(getattr(self, key) is not None for key in _IncidentFields.model_fields) and self.resolution_message is None and self.mitigation_message is None:
            raise ValueError("Provide at least one incident field to update")
        return self


class RootlyDeleteIncident(_Input):
    operation: Literal["delete_incident"] = "delete_incident"
    incident_id: str = Field(..., description="Incident to delete permanently.")


class RootlyListIncidentEvents(_Page):
    operation: Literal["list_incident_events"] = "list_incident_events"
    incident_id: str


class RootlyCreateIncidentEvent(_Input):
    operation: Literal["create_incident_event"] = "create_incident_event"
    incident_id: str
    event: str = Field(..., min_length=1, max_length=50000, description="Timeline event summary.")
    visibility: Optional[Literal["internal", "external"]] = None


class RootlyListActionItems(_Page):
    operation: Literal["list_action_items"] = "list_action_items"
    incident_id: str


class _ActionFields(_Input):
    summary: Optional[str] = Field(None, min_length=1, max_length=1000)
    description: Optional[str] = Field(None, max_length=50000)
    kind: Optional[Literal["task", "follow_up"]] = None
    priority: Optional[Literal["high", "medium", "low"]] = None
    status: Optional[Literal["open", "in_progress", "cancelled", "done"]] = None
    assigned_to_user_id: Optional[int] = Field(None, ge=1)
    assigned_to_group_ids: Optional[list[str]] = Field(None, max_length=100, title="Assigned team IDs")
    due_date: Optional[str] = Field(None, max_length=255, description="Due date accepted by Rootly, for example 2026-11-30.")


class RootlyCreateActionItem(_ActionFields):
    operation: Literal["create_action_item"] = "create_action_item"
    incident_id: str
    summary: str = Field(..., min_length=1, max_length=1000)


class RootlyGetActionItem(_Input):
    operation: Literal["get_action_item"] = "get_action_item"
    action_item_id: str


class RootlyUpdateActionItem(_ActionFields):
    operation: Literal["update_action_item"] = "update_action_item"
    action_item_id: str

    @model_validator(mode="after")
    def has_change(self):
        if not any(getattr(self, key) is not None for key in _ActionFields.model_fields):
            raise ValueError("Provide at least one action item field to update")
        return self


class RootlyListTeams(_Page):
    operation: Literal["list_teams"] = "list_teams"
    search: Optional[str] = Field(None, max_length=1000)


class RootlyGetTeam(_Input):
    operation: Literal["get_team"] = "get_team"
    team_id: str


class RootlyListServices(_Page):
    operation: Literal["list_services"] = "list_services"
    search: Optional[str] = Field(None, max_length=1000)


class RootlyGetService(_Input):
    operation: Literal["get_service"] = "get_service"
    service_id: str


class RootlyListSeverities(_Page):
    operation: Literal["list_severities"] = "list_severities"
    search: Optional[str] = Field(None, max_length=1000)


class RootlyGetSeverity(_Input):
    operation: Literal["get_severity"] = "get_severity"
    severity_id: str


class RootlyListUsers(_Page):
    operation: Literal["list_users"] = "list_users"
    search: Optional[str] = Field(None, max_length=1000)


class RootlyGetUser(_Input):
    operation: Literal["get_user"] = "get_user"
    user_id: str


class RootlyGetCurrentUser(_Input):
    operation: Literal["get_current_user"] = "get_current_user"


RootlyOperation = Annotated[Union[
    RootlyListIncidents, RootlyGetIncident, RootlyCreateIncident, RootlyUpdateIncident,
    RootlyDeleteIncident, RootlyListIncidentEvents, RootlyCreateIncidentEvent,
    RootlyListActionItems, RootlyCreateActionItem, RootlyGetActionItem, RootlyUpdateActionItem,
    RootlyListTeams, RootlyGetTeam, RootlyListServices, RootlyGetService,
    RootlyListSeverities, RootlyGetSeverity, RootlyListUsers, RootlyGetUser, RootlyGetCurrentUser,
], Field(discriminator="operation")]


class RootlyNodeConfig(NodeConfig[RootlyOperation, RootlyAPIKeyCredential]):
    model_config = ConfigDict(title="Rootly Node Configuration", hide_input_in_errors=True)


# Method, path, response resource type, optional resource path field.
# These are deliberately fixed: no arbitrary endpoint or HTTP request operation.
ROUTES = {
    "list_incidents": ("GET", "/v1/incidents", "incidents", None),
    "get_incident": ("GET", "/v1/incidents/{id}", "incidents", "incident_id"),
    "create_incident": ("POST", "/v1/incidents", "incidents", None),
    "update_incident": ("PUT", "/v1/incidents/{id}", "incidents", "incident_id"),
    "delete_incident": ("DELETE", "/v1/incidents/{id}", "incidents", "incident_id"),
    "list_incident_events": ("GET", "/v1/incidents/{id}/events", "incident_events", "incident_id"),
    "create_incident_event": ("POST", "/v1/incidents/{id}/events", "incident_events", "incident_id"),
    "list_action_items": ("GET", "/v1/incidents/{id}/action_items", "incident_action_items", "incident_id"),
    "create_action_item": ("POST", "/v1/incidents/{id}/action_items", "incident_action_items", "incident_id"),
    "get_action_item": ("GET", "/v1/action_items/{id}", "incident_action_items", "action_item_id"),
    "update_action_item": ("PUT", "/v1/action_items/{id}", "incident_action_items", "action_item_id"),
    "list_teams": ("GET", "/v1/teams", "groups", None),
    "get_team": ("GET", "/v1/teams/{id}", "groups", "team_id"),
    "list_services": ("GET", "/v1/services", "services", None),
    "get_service": ("GET", "/v1/services/{id}", "services", "service_id"),
    "list_severities": ("GET", "/v1/severities", "severities", None),
    "get_severity": ("GET", "/v1/severities/{id}", "severities", "severity_id"),
    "list_users": ("GET", "/v1/users", "users", None),
    "get_user": ("GET", "/v1/users/{id}", "users", "user_id"),
    "get_current_user": ("GET", "/v1/users/me", "users", None),
}


def _resource(row, kind):
    if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or row.get("type") != kind or not isinstance(row.get("attributes"), dict):
        raise ValueError("Rootly returned an unexpected resource")
    # Flatten attributes for workflow references and recognisable connection evidence.
    return {**row["attributes"], "id": row["id"], "type": kind}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value


def _config_view(data):
    credentials = data.get("credentials")
    if isinstance(credentials, dict) and "credential_type" in credentials and credentials["credential_type"] != CREDENTIAL_TYPE:
        raise ValueError("Attach a Rootly API key credential")
    config = data.get("config")
    if isinstance(config, dict):
        return {**data, "config": {k: v for k, v in config.items() if k != "credentialIds"}}
    return data


class RootlyNode(WorkflowNode):
    integration_type = "automation-rootly"
    connection_evidence = ConnectionEvidence(noun="incidents", operation="list_incidents", label_keys=("title", "id"))

    @classmethod
    def get_config_model(cls):
        return RootlyNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        return super().parse_config(_config_view(config_data))

    @classmethod
    def validate_config(cls, config_data):
        try:
            data = _config_view(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Rootly API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path, kind, id_field = ROUTES[op.operation]
        if id_field:
            path = path.replace("{id}", quote(str(getattr(op, id_field)), safe=""))
        headers = {"Authorization": "Bearer " + key, "Accept": MEDIA_TYPE, "Content-Type": MEDIA_TYPE}
        params = {}
        body = None
        if isinstance(op, _Page):
            params = {"page[number]": op.page_number, "page[size]": op.page_size}
            for field in ("search", "status", "severity_id"):
                value = getattr(op, field, None)
                if value is not None:
                    params["filter[" + field + "]"] = value
        if method in {"POST", "PUT"}:
            attributes = op.model_dump(exclude_none=True, exclude={"operation", "incident_id", "action_item_id", "idempotency_key"})
            body = {"data": {"type": kind, "attributes": attributes}}
            if getattr(op, "idempotency_key", None):
                headers["Idempotency-Key"] = op.idempotency_key
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, headers=headers, params=params, **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            output = {"status": "error" if method == "GET" else "unknown", "success": False,
                      "message": "Rootly request did not complete" if method == "GET" else "Rootly write outcome is unknown; inspect the resource before retrying"}
        else:
            if not 200 <= response.status_code < 300:
                output = {"status": "unknown" if method != "GET" and (response.status_code >= 500 or response.status_code == 408) else "error", "success": False, "http_status": response.status_code,
                          "message": response.text[:4000] or "Rootly rejected the request"}
            else:
                try:
                    payload = response.json()
                    if not isinstance(payload, dict) or "errors" in payload:
                        raise ValueError("Rootly returned an error envelope")
                    data = payload.get("data")
                    if isinstance(op, _Page):
                        if not isinstance(data, list):
                            raise ValueError("Rootly returned an unexpected collection")
                        data = [_resource(row, kind) for row in data]
                    else:
                        data = _resource(data, kind)
                    output = {"status": "success", "success": True, "data": data, "http_status": response.status_code}
                    if isinstance(op, _Page):
                        output["pagination"] = {"page_number": op.page_number, "page_size": op.page_size,
                                                "links": payload.get("links"), "meta": payload.get("meta")}
                except (ValueError, TypeError, KeyError):
                    output = {"status": "error" if method == "GET" else "unknown", "success": False,
                              "message": "Rootly returned an unexpected response" if method == "GET" else "Rootly accepted the write but its response could not be read; inspect before retrying"}
        output = _redact(output, key)
        await self.emit(output)
        return output
