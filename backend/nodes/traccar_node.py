"""Fleet automation against Traccar's published OpenAPI 6.17 contract."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from typing import Annotated, Literal, Union, Optional, Any
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import https_origin, clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

class TraccarTokenCredential(BaseModel):
    model_config = ConfigDict(title="Traccar API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://www.traccar.org/api-reference/",
        "x-credential-instructions": "Paste an existing Traccar bearer token and your server HTTPS origin (without /api). Generate a token in your Traccar account settings. The token has your account permissions."})
    credential_type: Literal["traccar_token"] = Field("traccar_token", json_schema_extra={"ui:hidden": True})
    server_url: str = Field(..., title="Server URL", description="HTTPS origin of your Traccar server, for example https://demo.traccar.org")
    api_token: str = Field(..., title="API token", json_schema_extra={"ui:widget": "password"})
    @field_validator("server_url", mode="before")
    @classmethod
    def origin(cls, value):
        origin = https_origin(value)
        if not origin.startswith("https://"):
            raise ValueError("Use an HTTPS server URL")
        return origin
    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the bearer token")
        return value

class DeviceBody(BaseModel):
    name: str = Field(..., min_length=1)
    uniqueId: str = Field(..., min_length=1, title="Unique device ID")
    groupId: Optional[int] = None
    disabled: Optional[bool] = None
    phone: Optional[str] = None
    model: Optional[str] = None
    contact: Optional[str] = None
    category: Optional[str] = None
    attributes: Optional[dict[str, Any]] = None

class GroupBody(BaseModel):
    name: str = Field(..., min_length=1)
    groupId: Optional[int] = None
    attributes: Optional[dict[str, Any]] = None

class GeofenceBody(BaseModel):
    name: str = Field(..., min_length=1)
    area: str = Field(..., min_length=1, description="Traccar geofence WKT area")
    description: Optional[str] = None
    calendarId: Optional[int] = None
    attributes: Optional[dict[str, Any]] = None

class CommandBody(BaseModel):
    deviceId: int = Field(..., gt=0)
    type: str = Field(..., min_length=1, description="Command type supported by this device")
    textChannel: bool = False
    attributes: dict[str, Any] = Field(default_factory=dict)

# Each operation maps to exactly one published endpoint.
OPERATIONS = {
    "list_devices": ("GET", "/devices", None),
    "get_device": ("GET", "/devices/{id}", None),
    "create_device": ("POST", "/devices", DeviceBody),
    "update_device": ("PUT", "/devices/{id}", DeviceBody),
    "delete_device": ("DELETE", "/devices/{id}", None),
    "list_groups": ("GET", "/groups", None),
    "create_group": ("POST", "/groups", GroupBody),
    "list_geofences": ("GET", "/geofences", None),
    "get_geofence": ("GET", "/geofences/{id}", None),
    "create_geofence": ("POST", "/geofences", GeofenceBody),
    "update_geofence": ("PUT", "/geofences/{id}", GeofenceBody),
    "delete_geofence": ("DELETE", "/geofences/{id}", None),
    "list_positions": ("GET", "/positions", None),
    "list_commands": ("GET", "/commands", None),
    "get_command_types": ("GET", "/commands/types", None),
    "send_command": ("POST", "/commands/send", CommandBody),
    "get_event": ("GET", "/events/{id}", None),
    "report_route": ("GET", "/reports/route", None),
    "report_events": ("GET", "/reports/events", None),
    "report_trips": ("GET", "/reports/trips", None),
    "report_summary": ("GET", "/reports/summary", None),
    "report_stops": ("GET", "/reports/stops", None),
}

class ReportConfig(BaseModel):
    device_id: int = Field(..., gt=0, title="Device ID")
    from_time: datetime = Field(..., title="From (ISO 8601)")
    to_time: datetime = Field(..., title="To (ISO 8601)")
    @model_validator(mode="after")
    def ordered(self):
        if self.from_time.tzinfo is None or self.to_time.tzinfo is None or self.from_time > self.to_time:
            raise ValueError("Use timezone-aware timestamps with From at or before To")
        return self

CONFIG_MODELS = {}
for name, (method, path, body) in OPERATIONS.items():
    fields = {"operation": (Literal[name], Field(name, json_schema_extra={"ui:hidden": True, "x-display-name": name.replace("_", " ").title()}))}
    if "{id}" in path:
        fields["resource_id"] = (int, Field(..., gt=0, title="Resource ID"))
    if body:
        fields["body"] = (body, Field(..., title="Resource fields"))
    if name.startswith("list_") and name != "list_positions":
        fields["limit"] = (int, Field(100, ge=1, le=1000))
        fields["offset"] = (int, Field(0, ge=0))
    if name in ("list_positions", "get_command_types"):
        fields["device_id"] = (Optional[int], Field(None, gt=0, description="Omit for all accessible devices"))
    base = ReportConfig if name.startswith("report_") else BaseModel
    CONFIG_MODELS[name] = create_model("Traccar" + name.title().replace("_", "") + "Config", __base__=base, **fields)
globals().update({m.__name__: m for m in CONFIG_MODELS.values()})

class TraccarOnEventConfig(PollTriggerConfigBase):
    operation: Literal["on_new_event"] = Field("on_new_event", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-display-name": "On New Device Event"})
    device_id: int = Field(..., gt=0, title="Device ID")
    lookback_minutes: int = Field(60, ge=5, le=1440, description="Overlap window; choose longer than the schedule interval. First poll establishes a baseline.")

TraccarConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (TraccarOnEventConfig,)], Field(discriminator="operation")]
class TraccarNodeConfig(NodeConfig[TraccarConfig, TraccarTokenCredential]):
    pass

class TraccarNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-traccar"
    connection_evidence = ConnectionEvidence(operation="list_devices", noun="devices")

    @classmethod
    def get_config_model(cls):
        return TraccarNodeConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("events")) if config.get("operation") == "on_new_event" else True

    @classmethod
    def resolve_agent_event(cls, output):
        if "events" not in output:
            return super().resolve_agent_event(output)
        events = output["events"]
        if not events:
            return None
        lines = [f"Device {e.get('deviceId')}: {e.get('type')} at {e.get('eventTime')} (event {e.get('id')}, position {e.get('positionId')}, geofence {e.get('geofenceId')})" for e in events]
        return {"text": "Traccar device events:\n" + "\n".join(lines), "conversation_key": None}

    async def _request(self, method, path, params=None, body=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Traccar account")
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, credential.server_url + "/api" + path,
                headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"}, params=params, json=body)
        response.raise_for_status()
        if response.status_code == 204:
            return None
        return response.json()

    async def execute(self, inputs):
        op = self.config.config
        if op.operation == "on_new_event":
            now = datetime.now(timezone.utc)
            rows = await self._request("GET", "/reports/events", params={"deviceId": op.device_id,
                "from": (now - timedelta(minutes=op.lookback_minutes)).isoformat(), "to": now.isoformat()})
            if not isinstance(rows, list):
                raise ValueError("Expected Traccar events list")
            fresh = await self._filter_unseen(rows, lambda e: str(e["id"]))
            return {"events": fresh, "new_event_count": len(fresh)}
        method, path, body_type = OPERATIONS[op.operation]
        if "{id}" in path:
            path = path.replace("{id}", str(op.resource_id))
        params = {}
        for field in ("limit", "offset"):
            if hasattr(op, field):
                params[field] = getattr(op, field)
        if hasattr(op, "device_id") and op.device_id is not None:
            params["deviceId"] = op.device_id
        if isinstance(op, ReportConfig):
            params.update({"from": op.from_time.isoformat(), "to": op.to_time.isoformat()})
        body = op.body.model_dump(exclude_none=True) if body_type else None
        if method == "PUT":
            body["id"] = op.resource_id
        data = await self._request(method, path, params=params, body=body)
        return {"data": data}
