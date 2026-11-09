"""OpsGenie REST API v2: one provider request per operation.

Contract: https://github.com/opsgenie/opsgenie-oas/blob/master/swagger.json
Auth: https://docs.opsgenie.com/docs/authentication
Alert writes are asynchronous; acceptance never claims that the change completed.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class OpsGenieApiKeyCredential(Closed):
    model_config = ConfigDict(title="OpsGenie API Key", extra="forbid", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://docs.opsgenie.com/docs/api-integration",
            "x-credential-instructions": "In OpsGenie, open Settings > Integrations and add an API integration. Copy its API key. Enable read access and the write permissions your workflow needs. Choose the region of your OpsGenie account."})
    credential_type: Literal["opsgenie_api_key"] = Field("opsgenie_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False,
        description="Paste the API integration key without the GenieKey prefix.", json_schema_extra={"ui:widget": "password"})
    region: Literal["us", "eu"] = Field("us", title="Region", description="Use EU for an account hosted in the European region; otherwise use US.")

    @field_validator("api_key")
    @classmethod
    def clean_key(cls, value):
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without spaces or the GenieKey prefix")
        return value


class ListAlerts(Closed):
    """Read one page of alerts. Use offset for subsequent pages."""
    operation: Literal["list_alerts"] = "list_alerts"
    query: str | None = Field(None, description="OpsGenie alert search query, for example status:open")
    offset: int = Field(0, ge=0, le=19999)
    limit: int = Field(20, ge=1, le=100)
    sort: Literal["createdAt", "updatedAt", "tinyId", "alias", "message", "status"] = "createdAt"
    order: Literal["asc", "desc"] = "desc"


class AlertRef(Closed):
    identifier: str = Field(..., min_length=1, max_length=512, description="Alert ID, alias, or tiny ID")
    identifier_type: Literal["id", "alias", "tiny"] = "id"


class GetAlert(AlertRef):
    operation: Literal["get_alert"] = "get_alert"


class ActionFields(Closed):
    user: str | None = Field(None, max_length=100, description="Display name recorded as the request owner")
    source: str | None = Field(None, max_length=100)
    note: str | None = Field(None, max_length=25000)


class Responder(Closed):
    type: Literal["team", "user", "escalation", "schedule"]
    id: str = Field(..., min_length=1, description="Responder ID")


class CreateAlert(ActionFields):
    """Create an alert and notify its responders. Returns an asynchronous request ID."""
    operation: Literal["create_alert"] = "create_alert"
    message: str = Field(..., min_length=1, max_length=130)
    alias: str | None = Field(None, max_length=512)
    description: str | None = Field(None, max_length=15000)
    priority: Literal["P1", "P2", "P3", "P4", "P5"] = "P3"
    responders: list[Responder] | None = Field(None, max_length=50)
    tags: list[Annotated[str, Field(min_length=1, max_length=50)]] | None = Field(None, max_length=20)
    details: dict[str, str] | None = None
    entity: str | None = Field(None, max_length=512)


class AcknowledgeAlert(AlertRef, ActionFields):
    operation: Literal["acknowledge_alert"] = "acknowledge_alert"


class UnacknowledgeAlert(AlertRef, ActionFields):
    operation: Literal["unacknowledge_alert"] = "unacknowledge_alert"


class CloseAlert(AlertRef, ActionFields):
    operation: Literal["close_alert"] = "close_alert"


class DeleteAlert(AlertRef):
    """Permanently delete an alert; returns an asynchronous request ID."""
    operation: Literal["delete_alert"] = "delete_alert"
    user: str | None = Field(None, max_length=100)
    source: str | None = Field(None, max_length=100)


class AddNote(AlertRef, ActionFields):
    operation: Literal["add_note"] = "add_note"
    note: str = Field(..., min_length=1, max_length=25000)


class ListNotes(AlertRef):
    operation: Literal["list_notes"] = "list_notes"
    offset: str | None = Field(None, description="The opaque offset returned in the provider paging response")
    limit: int = Field(20, ge=1, le=100)
    order: Literal["asc", "desc"] = "desc"
    direction: Literal["next", "prev"] = "next"


class AddTags(AlertRef, ActionFields):
    operation: Literal["add_tags"] = "add_tags"
    tags: list[Annotated[str, Field(min_length=1, max_length=50)]] = Field(..., min_length=1, max_length=20)


class UpdateMessage(AlertRef):
    operation: Literal["update_alert_message"] = "update_alert_message"
    message: str = Field(..., min_length=1, max_length=130)


class UpdatePriority(AlertRef):
    operation: Literal["update_alert_priority"] = "update_alert_priority"
    priority: Literal["P1", "P2", "P3", "P4", "P5"]


class RequestStatus(Closed):
    operation: Literal["get_request_status"] = "get_request_status"
    request_id: str = Field(..., min_length=1)


class ListTeams(Closed):
    operation: Literal["list_teams"] = "list_teams"


class ListUsers(Closed):
    operation: Literal["list_users"] = "list_users"
    offset: int = Field(0, ge=0)
    limit: int = Field(100, ge=1, le=100)
    query: str | None = None
    order: Literal["asc", "desc"] = "asc"


class ListSchedules(Closed):
    operation: Literal["list_schedules"] = "list_schedules"


class GetOnCalls(Closed):
    operation: Literal["get_on_calls"] = "get_on_calls"
    identifier: str = Field(..., min_length=1, description="Schedule ID or name")
    schedule_identifier_type: Literal["id", "name"] = "id"
    flat: bool = False


class ListHeartbeats(Closed):
    operation: Literal["list_heartbeats"] = "list_heartbeats"


class CreateHeartbeat(Closed):
    operation: Literal["create_heartbeat"] = "create_heartbeat"
    name: str = Field(..., min_length=1, max_length=200)
    interval: int = Field(..., ge=1)
    interval_unit: Literal["minutes", "hours", "days"]
    enabled: bool = True
    description: str | None = Field(None, max_length=10000)


class PingHeartbeat(Closed):
    """Signal that a monitored process is alive (a write despite using HTTP GET)."""
    operation: Literal["ping_heartbeat"] = "ping_heartbeat"
    name: str = Field(..., min_length=1, max_length=200)


OpsGenieConfig = Annotated[Union[ListAlerts, GetAlert, CreateAlert, AcknowledgeAlert,
    UnacknowledgeAlert, CloseAlert, DeleteAlert, AddNote, ListNotes, AddTags,
    UpdateMessage, UpdatePriority, RequestStatus, ListTeams, ListUsers, ListSchedules,
    GetOnCalls, ListHeartbeats, CreateHeartbeat, PingHeartbeat], Field(discriminator="operation")]


class OpsGenieFullConfig(NodeConfig[OpsGenieConfig, OpsGenieApiKeyCredential]):
    model_config = ConfigDict(title="OpsGenie Node Configuration", hide_input_in_errors=True)


# Each entry maps exactly one node operation to one pinned OpenAPI operation.
ROUTES = {
    "list_alerts": ("GET", "/v2/alerts"),
    "get_alert": ("GET", "/v2/alerts/{identifier}"),
    "create_alert": ("POST", "/v2/alerts"),
    "acknowledge_alert": ("POST", "/v2/alerts/{identifier}/acknowledge"),
    "unacknowledge_alert": ("POST", "/v2/alerts/{identifier}/unacknowledge"),
    "close_alert": ("POST", "/v2/alerts/{identifier}/close"),
    "delete_alert": ("DELETE", "/v2/alerts/{identifier}"),
    "add_note": ("POST", "/v2/alerts/{identifier}/notes"),
    "list_notes": ("GET", "/v2/alerts/{identifier}/notes"),
    "add_tags": ("POST", "/v2/alerts/{identifier}/tags"),
    "update_alert_message": ("PUT", "/v2/alerts/{identifier}/message"),
    "update_alert_priority": ("PUT", "/v2/alerts/{identifier}/priority"),
    "get_request_status": ("GET", "/v2/alerts/requests/{requestId}"),
    "list_teams": ("GET", "/v2/teams"),
    "list_users": ("GET", "/v2/users"),
    "list_schedules": ("GET", "/v2/schedules"),
    "get_on_calls": ("GET", "/v2/schedules/{identifier}/on-calls"),
    "list_heartbeats": ("GET", "/v2/heartbeats"),
    "create_heartbeat": ("POST", "/v2/heartbeats"),
    "ping_heartbeat": ("GET", "/v2/heartbeats/{name}/ping"),
}
ALIASES = {"identifier_type": "identifierType", "schedule_identifier_type": "scheduleIdentifierType", "interval_unit": "intervalUnit"}


class OpsGenieNode(WorkflowNode):
    integration_type = "automation-opsgenie"
    connection_evidence = ConnectionEvidence(operation="list_alerts", noun="alerts")

    @classmethod
    def get_config_model(cls):
        return OpsGenieFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, OpsGenieFullConfig) or not self.config.credentials:
            raise ValueError("Connect an OpsGenie API key")
        config = self.config.config
        credential = self.config.credentials
        operation = config.operation
        method, path = ROUTES[operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for field, placeholder in (("identifier", "identifier"), ("request_id", "requestId"), ("name", "name")):
            if "{" + placeholder + "}" in path:
                value = values.pop(field)
                if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
                    raise ValueError("A valid OpsGenie resource identifier is required")
                path = path.replace("{" + placeholder + "}", quote(value, safe=""))
        values = {ALIASES.get(k, k): v for k, v in values.items()}
        params = {}
        if "identifierType" in values:
            params["identifierType"] = values.pop("identifierType")
        body = None
        if method in {"GET", "DELETE"}:
            params.update(values)
        else:
            body = values
        host = "https://api.eu.opsgenie.com" if credential.region == "eu" else "https://api.opsgenie.com"
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, host + path, params=params,
                **({"json": body} if body is not None else {}),
                headers={"Authorization": "GenieKey " + credential.api_key, "Accept": "application/json"})
        # Do not include request headers or credentials in HTTP exception strings.
        if not 200 <= response.status_code < 300:
            message = "OpsGenie returned HTTP " + str(response.status_code)
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"].replace(credential.api_key, "[redacted]")
            except ValueError:
                pass
            return {"status": "error", "error": message, "http_status": response.status_code}
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("OpsGenie returned a non-JSON response") from None
        if not isinstance(payload, dict) or "message" in payload and "data" not in payload and response.status_code != 202 and "requestId" not in payload:
            raise ValueError("OpsGenie returned an unexpected response envelope")
        if response.status_code == 202:
            if not isinstance(payload.get("requestId"), str) or not payload["requestId"]:
                raise ValueError("OpsGenie did not return an asynchronous request ID")
            return {"status": "accepted", "request_id": payload["requestId"], "operation": operation, "response": payload}
        if "data" not in payload:
            raise ValueError("OpsGenie response is missing data")
        if operation == "get_request_status":
            data = payload["data"]
            if not isinstance(data, dict) or not isinstance(data.get("isSuccess"), bool):
                raise ValueError("OpsGenie returned an invalid request status")
            return {"status": "success" if data["isSuccess"] else "error", "operation": operation,
                "data": data, **({"error": str(data.get("status", "OpsGenie request failed"))} if not data["isSuccess"] else {})}
        return {"status": "success", "operation": operation, **payload}
