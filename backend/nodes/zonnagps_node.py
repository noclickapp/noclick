"""ZonnaGPS fleet actions and signed webhook events from public API v1.2.0.

The provider contract is https://app.zonnagps.es/api/docs/openapi.yaml.
Each action makes one request; list actions return a single page and its metadata.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import date
from typing import Annotated, Any, Literal, Union

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.zonnagps.es/api/public/v1"
EVENTS = ("alert.triggered", "geofence.enter", "geofence.exit", "deca.issued", "vehicle.offline")


class ZonnaGPSAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="ZonnaGPS API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.zonnagps.es/api/docs",
            "x-credential-instructions": "In ZonnaGPS, open Settings → Integrations and create a dedicated API key. Paste the key shown once, without Bearer. Enable assets.list for connection evidence and each action's documented scope. Triggers also need webhooks.create and webhooks.delete; older keys only support reads."})
    credential_type: Literal["zonnagps_api_token"] = Field("zonnagps_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the API token without a header or whitespace")
        return value


class ActionConfig(BaseModel):
    @model_validator(mode="after")
    def meaningful_update(self):
        operation = getattr(self, "operation", "")
        nullable = {"nif", "phone", "notes", "address"}
        if operation.startswith("update_") and not any(
            key not in {"operation", "id"} and (getattr(self, key) is not None or key in nullable)
            for key in self.model_fields_set
        ):
            raise ValueError("Provide at least one field to update")
        start, end = getattr(self, "from_time", None), getattr(self, "to_time", None)
        if start and end:
            if end < start:
                raise ValueError("End must be on or after start")
            maximum_days = 31 if operation == "list_positions" else 366 if operation == "get_report" else None
            if maximum_days and (end - start).total_seconds() > maximum_days * 86400:
                raise ValueError(f"Use a date range of at most {maximum_days} days")
        return self


class ZonnaGPSListAssetsConfig(ActionConfig):
    """List Assets."""
    operation: Literal['list_assets'] = Field('list_assets', json_schema_extra={'ui:hidden': True, 'x-display-name': 'List Assets', 'x-category': 'Assets', 'x-is-trigger': False})
    page: int | None = Field(None, title='Page', ge=1)
    per_page: int | None = Field(None, title='Per Page', ge=1, le=200)
    search: str | None = Field(None, title='Search', max_length=255)

class ZonnaGPSGetAssetConfig(ActionConfig):
    """Get Asset."""
    operation: Literal['get_asset'] = Field('get_asset', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Get Asset', 'x-category': 'Assets', 'x-is-trigger': False})
    asset: int = Field(..., title='Vehicle ID', ge=1)

class ZonnaGPSGetLatestPositionConfig(ActionConfig):
    """Get Latest Position."""
    operation: Literal['get_latest_position'] = Field('get_latest_position', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Get Latest Position', 'x-category': 'Assets', 'x-is-trigger': False})
    asset: int = Field(..., title='Vehicle ID', ge=1)

class ZonnaGPSListPositionsConfig(ActionConfig):
    """List Positions."""
    operation: Literal['list_positions'] = Field('list_positions', json_schema_extra={'ui:hidden': True, 'x-display-name': 'List Positions', 'x-category': 'Assets', 'x-is-trigger': False})
    asset: int = Field(..., title='Vehicle ID', ge=1)
    from_time: AwareDatetime | None = Field(None, title='From Time')
    to_time: AwareDatetime | None = Field(None, title='To Time')
    page: int | None = Field(None, title='Page', ge=1)
    per_page: int | None = Field(None, title='Per Page', ge=1, le=200)

class ZonnaGPSListAlarmsConfig(ActionConfig):
    """List Alarms."""
    operation: Literal['list_alarms'] = Field('list_alarms', json_schema_extra={'ui:hidden': True, 'x-display-name': 'List Alarms', 'x-category': 'Alarms', 'x-is-trigger': False})
    from_time: AwareDatetime | None = Field(None, title='From Time')
    to_time: AwareDatetime | None = Field(None, title='To Time')
    page: int | None = Field(None, title='Page', ge=1)
    per_page: int | None = Field(None, title='Per Page', ge=1, le=200)

class ZonnaGPSListDriversConfig(ActionConfig):
    """List Drivers."""
    operation: Literal['list_drivers'] = Field('list_drivers', json_schema_extra={'ui:hidden': True, 'x-display-name': 'List Drivers', 'x-category': 'Drivers', 'x-is-trigger': False})
    search: str | None = Field(None, title='Search', max_length=160)
    nif: str | None = Field(None, title='Nif')
    include_inactive: bool | None = Field(None, title='Include Inactive')
    page: int | None = Field(None, title='Page', ge=1)
    per_page: int | None = Field(None, title='Per Page', ge=1, le=200)

class ZonnaGPSCreateDriverConfig(ActionConfig):
    """Create Driver."""
    operation: Literal['create_driver'] = Field('create_driver', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Create Driver', 'x-category': 'Drivers', 'x-is-trigger': False})
    name: str = Field(..., title='Name', max_length=160, min_length=1)
    nif: str | None = Field(None, title='Nif', max_length=32)
    phone: str | None = Field(None, title='Phone', max_length=32)
    notes: str | None = Field(None, title='Notes', max_length=2000)

class ZonnaGPSUpdateDriverConfig(ActionConfig):
    """Update Driver."""
    operation: Literal['update_driver'] = Field('update_driver', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Update Driver', 'x-category': 'Drivers', 'x-is-trigger': False})
    id: int = Field(..., title='Id', ge=1)
    name: str | None = Field(None, title='Name', max_length=160)
    nif: str | None = Field(None, title='Nif', max_length=32)
    phone: str | None = Field(None, title='Phone', max_length=32)
    notes: str | None = Field(None, title='Notes', max_length=2000)

class ZonnaGPSDeactivateDriverConfig(ActionConfig):
    """Deactivate Driver."""
    operation: Literal['deactivate_driver'] = Field('deactivate_driver', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Deactivate Driver', 'x-category': 'Drivers', 'x-is-trigger': False})
    id: int = Field(..., title='Id', ge=1)

class ZonnaGPSCreatePlaceConfig(ActionConfig):
    """Create Place."""
    operation: Literal['create_place'] = Field('create_place', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Create Place', 'x-category': 'Places', 'x-is-trigger': False})
    name: str = Field(..., title='Name', max_length=160, min_length=1)
    latitude: float = Field(..., title='Latitude', ge=-90, le=90)
    longitude: float = Field(..., title='Longitude', ge=-180, le=180)
    radius_meters: int | None = Field(None, title='Radius Meters', ge=1, le=100000)
    address: str | None = Field(None, title='Address', max_length=500)
    is_active: bool | None = Field(None, title='Is Active')

class ZonnaGPSUpdatePlaceConfig(ActionConfig):
    """Update Place."""
    operation: Literal['update_place'] = Field('update_place', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Update Place', 'x-category': 'Places', 'x-is-trigger': False})
    id: int = Field(..., title='Id', ge=1)
    name: str | None = Field(None, title='Name', max_length=160)
    latitude: float | None = Field(None, title='Latitude', ge=-90, le=90)
    longitude: float | None = Field(None, title='Longitude', ge=-180, le=180)
    radius_meters: int | None = Field(None, title='Radius Meters', ge=1, le=100000)
    address: str | None = Field(None, title='Address', max_length=500)
    is_active: bool | None = Field(None, title='Is Active')

class ZonnaGPSDeactivatePlaceConfig(ActionConfig):
    """Deactivate Place."""
    operation: Literal['deactivate_place'] = Field('deactivate_place', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Deactivate Place', 'x-category': 'Places', 'x-is-trigger': False})
    id: int = Field(..., title='Id', ge=1)

class ZonnaGPSCreateGeofenceConfig(ActionConfig):
    """Create Geofence."""
    operation: Literal['create_geofence'] = Field('create_geofence', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Create Geofence', 'x-category': 'Geofences', 'x-is-trigger': False})
    name: str = Field(..., title='Name', max_length=160, min_length=1)
    center_latitude: float = Field(..., title='Center Latitude', ge=-90, le=90)
    center_longitude: float = Field(..., title='Center Longitude', ge=-180, le=180)
    radius_meters: int = Field(..., title='Radius Meters', ge=1, le=100000)
    is_active: bool | None = Field(None, title='Is Active')

class ZonnaGPSUpdateGeofenceConfig(ActionConfig):
    """Update Geofence."""
    operation: Literal['update_geofence'] = Field('update_geofence', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Update Geofence', 'x-category': 'Geofences', 'x-is-trigger': False})
    id: int = Field(..., title='Id', ge=1)
    name: str | None = Field(None, title='Name', max_length=160)
    center_latitude: float | None = Field(None, title='Center Latitude', ge=-90, le=90)
    center_longitude: float | None = Field(None, title='Center Longitude', ge=-180, le=180)
    radius_meters: int | None = Field(None, title='Radius Meters', ge=1, le=100000)
    is_active: bool | None = Field(None, title='Is Active')

class ZonnaGPSDeactivateGeofenceConfig(ActionConfig):
    """Deactivate Geofence."""
    operation: Literal['deactivate_geofence'] = Field('deactivate_geofence', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Deactivate Geofence', 'x-category': 'Geofences', 'x-is-trigger': False})
    id: int = Field(..., title='Id', ge=1)

class ZonnaGPSAssignDriverConfig(ActionConfig):
    """Assign Driver."""
    operation: Literal['assign_driver'] = Field('assign_driver', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Assign Driver', 'x-category': 'Assets', 'x-is-trigger': False})
    id: int = Field(..., title='Id', ge=1)
    driver_id: int = Field(..., title='Driver Id', ge=1)

class ZonnaGPSListWebhooksConfig(ActionConfig):
    """List Webhooks."""
    operation: Literal['list_webhooks'] = Field('list_webhooks', json_schema_extra={'ui:hidden': True, 'x-display-name': 'List Webhooks', 'x-category': 'Webhooks', 'x-is-trigger': False})

class ZonnaGPSGetReportConfig(ActionConfig):
    """Get Report."""
    operation: Literal['get_report'] = Field('get_report', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Get Report', 'x-category': 'Reports', 'x-is-trigger': False})
    dataset: Literal['vehicles', 'vehicle-daily', 'driver-daily', 'alerts', 'deca'] = Field(..., title='Dataset', min_length=1)
    from_time: date | None = Field(None, title='From Time')
    to_time: date | None = Field(None, title='To Time')
    page: int | None = Field(None, title='Page', ge=1)
    per_page: int | None = Field(None, title='Per Page', ge=1, le=5000)


class ZonnaGPSOnEventConfig(WebhookTriggerConfigBase):
    """Receive selected fleet events through an automatically registered webhook."""
    operation: Literal["on_event"] = Field("on_event", json_schema_extra={"ui:hidden": True,
        "x-is-trigger": True, "x-display-name": "On Fleet Event", "x-category": "Triggers"})
    event_type: Literal["all", *EVENTS] = Field("all", title="Event type")
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={
        "ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


OPERATIONS = {'list_assets': {'method': 'GET', 'path': '/assets', 'query': {'page': 'page', 'per_page': 'per_page', 'search': 'search'}, 'body': []}, 'get_asset': {'method': 'GET', 'path': '/assets/{asset}', 'query': {}, 'body': []}, 'get_latest_position': {'method': 'GET', 'path': '/assets/{asset}/position', 'query': {}, 'body': []}, 'list_positions': {'method': 'GET', 'path': '/assets/{asset}/positions', 'query': {'from_time': 'from', 'to_time': 'to', 'page': 'page', 'per_page': 'per_page'}, 'body': []}, 'list_alarms': {'method': 'GET', 'path': '/alarms', 'query': {'from_time': 'from', 'to_time': 'to', 'page': 'page', 'per_page': 'per_page'}, 'body': []}, 'list_drivers': {'method': 'GET', 'path': '/drivers', 'query': {'search': 'search', 'nif': 'nif', 'include_inactive': 'include_inactive', 'page': 'page', 'per_page': 'per_page'}, 'body': []}, 'create_driver': {'method': 'POST', 'path': '/drivers', 'query': {}, 'body': ['name', 'nif', 'phone', 'notes']}, 'update_driver': {'method': 'PATCH', 'path': '/drivers/{id}', 'query': {}, 'body': ['name', 'nif', 'phone', 'notes']}, 'deactivate_driver': {'method': 'DELETE', 'path': '/drivers/{id}', 'query': {}, 'body': []}, 'create_place': {'method': 'POST', 'path': '/places', 'query': {}, 'body': ['name', 'latitude', 'longitude', 'radius_meters', 'address', 'is_active']}, 'update_place': {'method': 'PATCH', 'path': '/places/{id}', 'query': {}, 'body': ['name', 'latitude', 'longitude', 'radius_meters', 'address', 'is_active']}, 'deactivate_place': {'method': 'DELETE', 'path': '/places/{id}', 'query': {}, 'body': []}, 'create_geofence': {'method': 'POST', 'path': '/geofences', 'query': {}, 'body': ['name', 'center_latitude', 'center_longitude', 'radius_meters', 'is_active']}, 'update_geofence': {'method': 'PATCH', 'path': '/geofences/{id}', 'query': {}, 'body': ['name', 'center_latitude', 'center_longitude', 'radius_meters', 'is_active']}, 'deactivate_geofence': {'method': 'DELETE', 'path': '/geofences/{id}', 'query': {}, 'body': []}, 'assign_driver': {'method': 'PUT', 'path': '/assets/{id}/driver', 'query': {}, 'body': ['driver_id']}, 'list_webhooks': {'method': 'GET', 'path': '/webhooks', 'query': {}, 'body': []}, 'get_report': {'method': 'GET', 'path': '/reports/{dataset}', 'query': {'from_time': 'from', 'to_time': 'to', 'page': 'page', 'per_page': 'per_page'}, 'body': []}}

ZonnaGPSConfig = Annotated[Union[ZonnaGPSListAssetsConfig, ZonnaGPSGetAssetConfig, ZonnaGPSGetLatestPositionConfig, ZonnaGPSListPositionsConfig, ZonnaGPSListAlarmsConfig, ZonnaGPSListDriversConfig, ZonnaGPSCreateDriverConfig, ZonnaGPSUpdateDriverConfig, ZonnaGPSDeactivateDriverConfig, ZonnaGPSCreatePlaceConfig, ZonnaGPSUpdatePlaceConfig, ZonnaGPSDeactivatePlaceConfig, ZonnaGPSCreateGeofenceConfig, ZonnaGPSUpdateGeofenceConfig, ZonnaGPSDeactivateGeofenceConfig, ZonnaGPSAssignDriverConfig, ZonnaGPSListWebhooksConfig, ZonnaGPSGetReportConfig, ZonnaGPSOnEventConfig], Field(discriminator="operation")]


class ZonnaGPSNodeConfig(NodeConfig[ZonnaGPSConfig, ZonnaGPSAPITokenCredential]):
    pass


class ZonnaGPSNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-zonnagps"
    connection_evidence = ConnectionEvidence(operation="list_assets", noun="vehicles", label_keys=("name", "plate", "identifier", "id"))

    @classmethod
    def get_config_model(cls):
        return ZonnaGPSNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        token = ZonnaGPSAPITokenCredential.model_validate(credential).api_token
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, params=params, json=body,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        if not 200 <= response.status_code < 300:
            # Keep provider errors verbatim for the shared connection-evidence classifier.
            try:
                error = response.json().get("error", {})
                message = error.get("message") if isinstance(error, dict) else error
            except (ValueError, AttributeError):
                message = None
            raise ValueError(f"ZonnaGPS HTTP {response.status_code}: {message or 'request failed'}")
        if not response.content:
            return {}
        data = response.json()
        if not isinstance(data, dict) or "error" in data:
            raise ValueError("ZonnaGPS returned an unexpected response")
        return data

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        config = self.config.config
        if isinstance(config, ZonnaGPSOnEventConfig):
            return self.no_event_output("on_event")
        if self.config.credentials is None:
            raise ValueError("Connect a ZonnaGPS API token")
        spec = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = spec["path"]
        for key, value in values.items():
            path = path.replace("{" + key + "}", str(value))
        params = {wire: values[key] for key, wire in spec["query"].items() if key in values}
        if config.operation == "get_report":
            params["format"] = "json"
        body = {key: values[key] for key in spec["body"] if key in values}
        # Explicit nulls clear nullable fields in PATCH, while omitted fields stay unchanged.
        if spec["method"] == "PATCH":
            body.update({key: None for key in config.model_fields_set if key in spec["body"] and key in {"nif", "phone", "notes", "address"} and getattr(config, key) is None})
        data = await self._request(self.config.credentials.model_dump(), spec["method"], path,
            params=params or None, body=body if spec["body"] else None)
        return {"status": "success", "operation": config.operation, **data}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = ZonnaGPSOnEventConfig.model_validate(config or {}).event_type
        result = await cls._request(credential, "POST", "/webhooks", body={
            "url": webhook_url, "events": list(EVENTS) if event == "all" else [event]})
        identifier = result.get("data", {}).get("id")
        secret = result.get("secret")
        if not isinstance(identifier, int) or identifier < 1 or not isinstance(secret, str) or not secret:
            raise ValueError("ZonnaGPS did not return a webhook ID and signing secret")
        return {"external_webhook_id": identifier, "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = (config or {}).get("external_webhook_id")
        if identifier is not None and credential:
            identifier = int(identifier)
            if identifier < 1:
                raise ValueError("Invalid ZonnaGPS webhook ID")
            await cls._request(credential, "DELETE", f"/webhooks/{identifier}")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type", "all")}

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict[str, str], config: dict[str, Any]) -> bool:
        secret = (config or {}).get("signing_secret")
        if not isinstance(secret, str) or not secret:
            return False
        signature = next((v for k, v in headers.items() if k.lower() == "x-zonna-signature"), "")
        if not isinstance(signature, str):
            return False
        parts = [part.strip() for part in signature.split(",")]
        timestamps = [p[2:] for p in parts if p.startswith("t=")]
        signatures = [p[3:] for p in parts if p.startswith("v1=")]
        if len(timestamps) != 1 or len(signatures) != 1:
            return False
        timestamp = timestamps[0]
        if not timestamp.isascii() or not timestamp.isdigit() or len(timestamp) > 12 or abs(time.time() - int(timestamp)) > 300:
            return False
        expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        supplied = signatures[0]
        if len(supplied) != 64 or any(c not in "0123456789abcdefABCDEF" for c in supplied):
            return False
        return hmac.compare_digest(supplied.lower(), expected)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        event = payload.get("event")
        selected = (config or {}).get("event_type", "all")
        return event in EVENTS and (selected == "all" or event == selected)

    @classmethod
    async def drop_trigger_event(cls, payload, config):
        # Scope duplicate delivery IDs to this subscription, so independent
        # workflows receiving the same fleet event each get their own turn.
        from utils.redis_client import get_shared_redis
        webhook_id = (config or {}).get("webhook_id")
        event_id = payload.get("id")
        if not webhook_id or not isinstance(event_id, str):
            return None
        redis = get_shared_redis()
        if redis is None:
            return None
        key = f"zonnagps:delivery:{webhook_id}:{event_id}"
        try:
            admitted = await redis.set(key, "1", nx=True, ex=172800)
        except Exception:
            # Preserve the provider's at-least-once delivery on storage outages.
            return None
        return None if admitted else "Duplicate ZonnaGPS event"

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("event") not in EVENTS:
            return None
        event = output["event"]
        record = output.get("data", {})
        if not isinstance(record, dict):
            return None
        if event in {"geofence.enter", "geofence.exit"}:
            movement = "entered" if event == "geofence.enter" else "left"
            summary = f"Device {record.get('device_id')} {movement} geofence {record.get('geofence_id')} at {record.get('latitude')}, {record.get('longitude')}."
        elif event == "deca.issued":
            summary = f"Transport document {record.get('reference')} was issued: status {record.get('status')}, version {record.get('current_version')}."
        else:
            action = "triggered an alert" if event == "alert.triggered" else "went offline"
            summary = f"{record.get('entity_type')} {record.get('entity_id')} {action}; severity {record.get('severity')}."
        return {"text": f"ZonnaGPS {event}: {summary} At {output.get('occurred_at')}. Record ID: {record.get('id')}; event ID: {output.get('id')}.",
            "title": "ZonnaGPS " + event, "conversation_key": str(output.get("id"))}
