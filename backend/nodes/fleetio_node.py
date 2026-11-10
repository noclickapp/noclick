"""Fleetio account API, pinned to the published 2025-05-05 contract.

Each operation issues one request. Writes report the returned acknowledgement;
no readback, delivery, or downstream side effect is claimed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import guarded_async_client

BASE_URL = "https://secure.fleetio.com/api"
API_VERSION = "2025-05-05"
CREDENTIAL_TYPE = "fleetio_api_key"


class FleetioApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Fleetio API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://secure.fleetio.com/api_keys",
            "x-credential-instructions": "In Fleetio, open Settings → API Keys. Paste an API key and the Account Token for the account you want to automate. The key's permissions must allow each selected operation. NoClick checks access by listing that account's vehicles.",
        })
    credential_type: Literal["fleetio_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    account_token: str = Field(..., title="Account Token", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "account_token", mode="before")
    @classmethod
    def secret(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the Fleetio token as text")
        value = clean_secret(value, field_name="Fleetio token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token alone, without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    per_page: int = Field(50, ge=1, le=100, title="Records Per Page")
    start_cursor: str | None = Field(None, min_length=1, max_length=8192,
        description="Copy next_cursor from the previous result for this account and operation. Each run returns one page.")


class _Update(_Input):
    @model_validator(mode="after")
    def has_changes(self):
        values = self.model_dump(exclude_none=True, exclude={"operation", "vehicle_id", "contact_id", "vendor_id", "issue_id"})
        if not values:
            raise ValueError("Provide at least one field to update")
        return self


class FleetioListVehicles(_Page):
    """List vehicles."""
    operation: Literal["list_vehicles"] = Field("list_vehicles", json_schema_extra={"ui:hidden": True})


class FleetioGetVehicle(_Input):
    """Get vehicle."""
    operation: Literal["get_vehicle"] = Field("get_vehicle", json_schema_extra={"ui:hidden": True})
    vehicle_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, title="Vehicle ID", description="Fleetio numeric record ID.")


class FleetioListContacts(_Page):
    """List contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})


class FleetioGetContact(_Input):
    """Get contact."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, title="Contact ID", description="Fleetio numeric record ID.")


class FleetioListVendors(_Page):
    """List vendors."""
    operation: Literal["list_vendors"] = Field("list_vendors", json_schema_extra={"ui:hidden": True})


class FleetioGetVendor(_Input):
    """Get vendor."""
    operation: Literal["get_vendor"] = Field("get_vendor", json_schema_extra={"ui:hidden": True})
    vendor_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, title="Vendor ID", description="Fleetio numeric record ID.")


class FleetioListIssues(_Page):
    """List issues."""
    operation: Literal["list_issues"] = Field("list_issues", json_schema_extra={"ui:hidden": True})


class FleetioGetIssue(_Input):
    """Get issue."""
    operation: Literal["get_issue"] = Field("get_issue", json_schema_extra={"ui:hidden": True})
    issue_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, title="Issue ID", description="Fleetio numeric record ID.")


class FleetioListFuelEntries(_Page):
    """List fuel entries."""
    operation: Literal["list_fuel_entries"] = Field("list_fuel_entries", json_schema_extra={"ui:hidden": True})


class FleetioGetFuelEntry(_Input):
    """Get fuel entry."""
    operation: Literal["get_fuel_entry"] = Field("get_fuel_entry", json_schema_extra={"ui:hidden": True})
    fuel_entry_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, title="Fuel Entry ID", description="Fleetio numeric record ID.")


class FleetioListServiceEntries(_Page):
    """List service entries."""
    operation: Literal["list_service_entries"] = Field("list_service_entries", json_schema_extra={"ui:hidden": True})


class FleetioGetServiceEntry(_Input):
    """Get service entry."""
    operation: Literal["get_service_entry"] = Field("get_service_entry", json_schema_extra={"ui:hidden": True})
    service_entry_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, title="Service Entry ID", description="Fleetio numeric record ID.")


class FleetioListVehicleStatuses(_Page):
    """List vehicle statuses."""
    operation: Literal["list_vehicle_statuses"] = Field("list_vehicle_statuses", json_schema_extra={"ui:hidden": True})


class FleetioListVehicleTypes(_Page):
    """List vehicle types."""
    operation: Literal["list_vehicle_types"] = Field("list_vehicle_types", json_schema_extra={"ui:hidden": True})


class FleetioCreateVehicle(_Input):
    """Create vehicle."""
    operation: Literal["create_vehicle"] = Field("create_vehicle", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    primary_meter_unit: Literal["km", "hr", "mi"]
    vehicle_status_id: int = Field(..., ge=1)
    vehicle_type_id: int = Field(..., ge=1)
    vin: str | None = Field(None, max_length=17)
    license_plate: str | None = Field(None, max_length=255)
    make: str | None = Field(None, max_length=255)
    model: str | None = Field(None, max_length=255)
    year: int | None = None
    group_id: int | None = Field(None, ge=1)


class FleetioUpdateVehicle(_Update):
    """Update vehicle."""
    operation: Literal["update_vehicle"] = Field("update_vehicle", json_schema_extra={"ui:hidden": True})
    vehicle_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, title="Vehicle ID", description="Fleetio numeric record ID.")
    name: str | None = Field(None, min_length=1, max_length=255)
    meter_unit: Literal["km", "hr", "mi"] | None = None
    vehicle_status_id: int | None = Field(None, ge=1)
    vehicle_type_id: int | None = Field(None, ge=1)
    vin: str | None = Field(None, max_length=17)
    license_plate: str | None = Field(None, max_length=255)
    make: str | None = Field(None, max_length=255)
    model: str | None = Field(None, max_length=255)
    year: int | None = None
    group_id: int | None = Field(None, ge=1)


class FleetioCreateContact(_Input):
    """Create contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., min_length=1, max_length=255)
    last_name: str | None = Field(None, max_length=255)
    email: str | None = Field(None, max_length=255)
    mobile_phone_number: str | None = Field(None, max_length=255)
    employee_number: str | None = Field(None, max_length=255)
    job_title: str | None = Field(None, max_length=255)
    vehicle_operator: bool | None = None
    employee: bool | None = None
    technician: bool | None = None
    group_id: int | None = Field(None, ge=1)


class FleetioUpdateContact(_Update):
    """Update contact."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, title="Contact ID", description="Fleetio numeric record ID.")
    first_name: str | None = Field(None, min_length=1, max_length=255)
    last_name: str | None = Field(None, max_length=255)
    email: str | None = Field(None, max_length=255)
    mobile_phone_number: str | None = Field(None, max_length=255)
    employee_number: str | None = Field(None, max_length=255)
    job_title: str | None = Field(None, max_length=255)
    vehicle_operator: bool | None = None
    employee: bool | None = None
    technician: bool | None = None
    group_id: int | None = Field(None, ge=1)


class FleetioCreateVendor(_Input):
    """Create vendor."""
    operation: Literal["create_vendor"] = Field("create_vendor", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    notes: str | None = Field(None, max_length=100000)
    contact_name: str | None = Field(None, max_length=255)
    contact_email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=255)
    street_address: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=255)
    region: str | None = Field(None, max_length=255)
    postal_code: str | None = Field(None, max_length=255)
    country: str | None = Field(None, max_length=255)
    external_id: str | None = Field(None, max_length=255)
    fuel: bool | None = None
    service: bool | None = None
    parts: bool | None = None


class FleetioUpdateVendor(_Update):
    """Update vendor."""
    operation: Literal["update_vendor"] = Field("update_vendor", json_schema_extra={"ui:hidden": True})
    vendor_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, title="Vendor ID", description="Fleetio numeric record ID.")
    name: str | None = Field(None, min_length=1, max_length=255)
    notes: str | None = Field(None, max_length=100000)
    contact_name: str | None = Field(None, max_length=255)
    contact_email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=255)
    street_address: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=255)
    region: str | None = Field(None, max_length=255)
    postal_code: str | None = Field(None, max_length=255)
    country: str | None = Field(None, max_length=255)
    external_id: str | None = Field(None, max_length=255)
    fuel: bool | None = None
    service: bool | None = None
    parts: bool | None = None


class FleetioCreateIssue(_Input):
    """Create issue."""
    operation: Literal["create_issue"] = Field("create_issue", json_schema_extra={"ui:hidden": True})
    asset_id: int = Field(..., ge=1)
    asset_type: Literal["Vehicle", "Equipment"]
    summary: str = Field(..., min_length=1, max_length=100000)
    reported_at: str = Field(..., description="ISO 8601 report timestamp.", json_schema_extra={"ui:widget": "datetime"})
    description: str | None = Field(None, max_length=100000)
    reported_by_id: int | None = Field(None, ge=1)
    issue_priority_id: int | None = Field(None, ge=1)
    assigned_contact_ids: list[int] | None = Field(None, max_length=100)

    @field_validator("reported_at")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            from datetime import datetime
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise ValueError("Use an ISO 8601 timestamp with a timezone") from None
        return value


class FleetioUpdateIssue(_Update):
    """Update issue."""
    operation: Literal["update_issue"] = Field("update_issue", json_schema_extra={"ui:hidden": True})
    issue_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, title="Issue ID", description="Fleetio numeric record ID.")
    asset_id: int | None = Field(None, ge=1)
    asset_type: Literal["Vehicle", "Equipment"] | None = None
    summary: str | None = Field(None, min_length=1, max_length=100000)
    reported_at: str | None = Field(None, description="ISO 8601 report timestamp.", json_schema_extra={"ui:widget": "datetime"})
    description: str | None = Field(None, max_length=100000)
    reported_by_id: int | None = Field(None, ge=1)
    issue_priority_id: int | None = Field(None, ge=1)
    assigned_contact_ids: list[int] | None = Field(None, max_length=100)

    @field_validator("reported_at")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            from datetime import datetime
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise ValueError("Use an ISO 8601 timestamp with a timezone") from None
        return value


class FleetioCloseIssue(_Input):
    """Close issue."""
    operation: Literal["close_issue"] = Field("close_issue", json_schema_extra={"ui:hidden": True})
    issue_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, title="Issue ID", description="Fleetio numeric record ID.")
    note: str = Field(..., min_length=1, max_length=100000, description="Note added to the issue with this status change.")


class FleetioResolveIssue(_Input):
    """Resolve issue."""
    operation: Literal["resolve_issue"] = Field("resolve_issue", json_schema_extra={"ui:hidden": True})
    issue_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, title="Issue ID", description="Fleetio numeric record ID.")
    note: str = Field(..., min_length=1, max_length=100000, description="Note added to the issue with this status change.")


class FleetioReopenIssue(_Input):
    """Reopen issue."""
    operation: Literal["reopen_issue"] = Field("reopen_issue", json_schema_extra={"ui:hidden": True})
    issue_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, title="Issue ID", description="Fleetio numeric record ID.")


# POST /webhooks flags in the pinned 2025-05-05 OpenAPI. Event examples:
# https://developer.fleetio.com/docs/overview/webhook-event-reference
TRIGGER_EVENTS = {
    "on_vehicle_event": ("vehicle_updated", "vehicle_created", "vehicle_status_changed", "vehicle_assigned", "vehicle_archived", "vehicle_deleted", "vehicle_group_changed"),
    "on_issue_event": ("issue_created", "issue_updated", "issue_closed", "issue_resolved", "issue_deleted"),
    "on_fuel_entry_event": ("fuel_entry_created", "fuel_entry_updated", "fuel_entry_deleted"),
    "on_service_entry_event": ("service_entry_created", "service_entry_updated", "service_entry_deleted"),
}


class _FleetioTrigger(WebhookTriggerConfigBase):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered with Fleetio automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


class FleetioOnVehicleEvent(_FleetioTrigger):
    """Start when a vehicle is created, updated, assigned or changes status."""
    operation: Literal["on_vehicle_event"] = Field("on_vehicle_event", title="On Vehicle Event", json_schema_extra={
        "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Vehicle Event"})
    event_type: Literal["vehicle_updated", "vehicle_created", "vehicle_status_changed", "vehicle_assigned", "vehicle_archived", "vehicle_deleted", "vehicle_group_changed"] = Field("vehicle_updated", title="Event Type")


class FleetioOnIssueEvent(_FleetioTrigger):
    """Start when an issue is reported, updated, resolved or closed."""
    operation: Literal["on_issue_event"] = Field("on_issue_event", title="On Issue Event", json_schema_extra={
        "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Issue Event"})
    event_type: Literal["issue_created", "issue_updated", "issue_closed", "issue_resolved", "issue_deleted"] = Field("issue_created", title="Event Type")


class FleetioOnFuelEntryEvent(_FleetioTrigger):
    """Start when a fuel entry is created, updated or deleted."""
    operation: Literal["on_fuel_entry_event"] = Field("on_fuel_entry_event", title="On Fuel Entry Event", json_schema_extra={
        "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Fuel Entry Event"})
    event_type: Literal["fuel_entry_created", "fuel_entry_updated", "fuel_entry_deleted"] = Field("fuel_entry_created", title="Event Type")


class FleetioOnServiceEntryEvent(_FleetioTrigger):
    """Start when a service entry is created, updated or deleted."""
    operation: Literal["on_service_entry_event"] = Field("on_service_entry_event", title="On Service Entry Event", json_schema_extra={
        "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Service Entry Event"})
    event_type: Literal["service_entry_created", "service_entry_updated", "service_entry_deleted"] = Field("service_entry_created", title="Event Type")


FleetioConfig = Annotated[Union[
    FleetioOnVehicleEvent,
    FleetioOnIssueEvent,
    FleetioOnFuelEntryEvent,
    FleetioOnServiceEntryEvent,
    FleetioListVehicles,
    FleetioGetVehicle,
    FleetioListContacts,
    FleetioGetContact,
    FleetioListVendors,
    FleetioGetVendor,
    FleetioListIssues,
    FleetioGetIssue,
    FleetioListFuelEntries,
    FleetioGetFuelEntry,
    FleetioListServiceEntries,
    FleetioGetServiceEntry,
    FleetioListVehicleStatuses,
    FleetioListVehicleTypes,
    FleetioCreateVehicle,
    FleetioUpdateVehicle,
    FleetioCreateContact,
    FleetioUpdateContact,
    FleetioCreateVendor,
    FleetioUpdateVendor,
    FleetioCreateIssue,
    FleetioUpdateIssue,
    FleetioCloseIssue,
    FleetioResolveIssue,
    FleetioReopenIssue
], Field(discriminator="operation")]


class FleetioNodeConfig(NodeConfig[FleetioConfig, FleetioApiKeyCredential]):
    pass


ROUTES = {
    'list_vehicles': ('GET', '/vehicles', None),
    'get_vehicle': ('GET', '/vehicles/{vehicle_id}', None),
    'list_contacts': ('GET', '/contacts', None),
    'get_contact': ('GET', '/contacts/{contact_id}', None),
    'list_vendors': ('GET', '/vendors', None),
    'get_vendor': ('GET', '/vendors/{vendor_id}', None),
    'list_issues': ('GET', '/issues', None),
    'get_issue': ('GET', '/issues/{issue_id}', None),
    'list_fuel_entries': ('GET', '/fuel_entries', None),
    'get_fuel_entry': ('GET', '/fuel_entries/{fuel_entry_id}', None),
    'list_service_entries': ('GET', '/service_entries', None),
    'get_service_entry': ('GET', '/service_entries/{service_entry_id}', None),
    'list_vehicle_statuses': ('GET', '/vehicle_statuses', None),
    'list_vehicle_types': ('GET', '/vehicle_types', None),
    'create_vehicle': ('POST', '/vehicles', ''),
    'update_vehicle': ('PATCH', '/vehicles/{vehicle_id}', 'vehicle_id'),
    'create_contact': ('POST', '/contacts', ''),
    'update_contact': ('PATCH', '/contacts/{contact_id}', 'contact_id'),
    'create_vendor': ('POST', '/vendors', ''),
    'update_vendor': ('PATCH', '/vendors/{vendor_id}', 'vendor_id'),
    'create_issue': ('POST', '/issues', ''),
    'update_issue': ('PATCH', '/issues/{issue_id}', 'issue_id'),
    'close_issue': ('PUT', '/issues/{issue_id}/close', 'issue_id'),
    'resolve_issue': ('PUT', '/issues/{issue_id}/resolve', 'issue_id'),
    'reopen_issue': ('PUT', '/issues/{issue_id}/reopen', None),
}


def _redact(value, credential):
    if isinstance(value, str):
        for token in (credential.api_key, credential.account_token):
            value = value.replace(token, "[redacted]")
        return value
    if isinstance(value, dict):
        return {_redact(k, credential): _redact(v, credential) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, credential) for v in value]
    return value


class FleetioNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-fleetio"
    connection_evidence = ConnectionEvidence(noun="vehicles", operation="list_vehicles", label_keys=("name", "license_plate", "vin", "id"))

    @classmethod
    def get_config_model(cls):
        return FleetioNodeConfig

    @classmethod
    def _event_type(cls, config):
        events = TRIGGER_EVENTS.get((config or {}).get("operation"))
        if events is None:
            raise ValueError("Choose a Fleetio trigger operation")
        event = (config or {}).get("event_type", events[0])
        if event not in events:
            raise ValueError("Choose a supported Fleetio event")
        return event

    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Fingerprints are declarative and must also accept incomplete editor
        # configs. Registration validates the operation and event via _event_type.
        config = config or {}
        events = TRIGGER_EVENTS.get(config.get("operation"), (None,))
        return {"event_type": config.get("event_type", events[0])}

    @classmethod
    async def _webhook_request(cls, credential, method, path, body=None):
        credential = FleetioApiKeyCredential.model_validate(credential)
        headers = {"Authorization": "Token " + credential.api_key,
            "Account-Token": credential.account_token, "X-Api-Version": API_VERSION,
            "Accept": "application/json"}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, json=body, headers=headers)
        if method == "DELETE" and response.status_code == 404:
            return None  # Already absent: teardown has converged.
        if not response.is_success:
            raise ValueError(f"Fleetio webhook {method} failed (HTTP {response.status_code})")
        return response.json() if method == "POST" else None

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = cls._event_type(config)
        endpoint = await cls._webhook_request(credential, "POST", "/webhooks", {
            "url": webhook_url, "enabled": True, "all_events": False, event: True,
            "description": f"NoClick {node_id}",
        })
        if not isinstance(endpoint, dict) or type(endpoint.get("id")) is not int or endpoint["id"] < 1:
            raise ValueError("Fleetio did not return a webhook ID")
        secret = endpoint.get("shared_key")
        if not isinstance(secret, str) or not secret:
            raise ValueError("Fleetio did not return a webhook signing key")
        return {"external_webhook_id": str(endpoint["id"]), "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint_id = (config or {}).get("external_webhook_id")
        if endpoint_id is None:
            return
        if not str(endpoint_id).isdigit() or int(endpoint_id) < 1:
            raise ValueError("Fleetio webhook ID must be numeric")
        await cls._webhook_request(credential, "DELETE", f"/webhooks/{endpoint_id}")

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # Official receiving-a-webhook-event-payload guide: hexadecimal
        # HMAC-SHA256 of the unmodified body, keyed by the returned shared_key.
        secret = (config or {}).get("signing_secret")
        signature = next((value for key, value in headers.items()
                          if key.lower() == "x-fleetio-webhook-signature"), "")
        if not isinstance(secret, str) or not secret or not isinstance(signature, str):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return signature.isascii() and hmac.compare_digest(signature, expected)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return (isinstance(payload, dict) and payload.get("event") == cls._event_type(config)
                and type(payload.get("id")) is int and isinstance(payload.get("payload"), dict)
                and type(payload["payload"].get("id")) is int)

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict):
            return None
        kind = output.get("event")
        record = output.get("payload")
        if not isinstance(kind, str) or kind not in {event for events in TRIGGER_EVENTS.values() for event in events} or not isinstance(record, dict):
            return None
        record_id = record.get("id")
        if record_id is None:
            return None
        resource = kind.rsplit("_", 1)[0]
        if kind.startswith("vehicle_"):
            resource = "vehicle"
            label = record.get("name")
            location = record.get("group_name")
        elif resource == "issue":
            label = record.get("summary")
            location = record.get("vehicle_name")
        else:
            label = record.get("vehicle_name")
            location = record.get("vendor_name")
        heading = f"Fleetio {kind.replace('_', ' ')}: {label or record_id}"
        lines = [heading, f"By: {output.get('triggered_by') or 'Fleetio'}",
                 f"At: {output.get('timestamp')}", f"{resource}_id: {record_id}",
                 f"Event ID: {output.get('id')}"]
        if location:
            lines.append(f"Where: {location}")
        # Retain content and IDs needed to act on the record, bounded for an agent turn.
        lines.extend(["Record:", json.dumps(record, ensure_ascii=False, default=str)[:14000]])
        return {"text": "\n".join(lines), "title": heading[:200],
                "conversation_key": f"fleetio:{resource}:{record_id}"}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Fleetio API key and account token")
        credential = self.config.credentials
        op = self.config.config
        if op.operation in TRIGGER_EVENTS:
            return self.no_event_output(op.operation, "Waiting for a signed Fleetio event")
        method, template, body_id = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        route = template.format(**values)
        params = values if method == "GET" and op.operation.startswith("list_") else None
        body = {k: v for k, v in values.items() if k != body_id} if body_id is not None else None
        headers = {"Authorization": "Token " + credential.api_key,
            "Account-Token": credential.account_token, "X-Api-Version": API_VERSION,
            "Accept": "application/json"}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route, params=params, json=body, headers=headers)
            if not response.is_success:
                # Preserve the provider's rejection text for the connect seam,
                # removing secrets if a proxy or provider echoed a header.
                try:
                    error = response.json()
                    message = error.get("detail") or error.get("message") or error.get("title") or str(error)
                except (ValueError, AttributeError):
                    message = response.text[:2000] or "Fleetio rejected the request"
                result = {"status": "error", "error": str(message)[:4000], "http_status": response.status_code}
            else:
                if len(response.content) > 10_000_000:
                    raise ValueError("Fleetio response exceeds the supported page size")
                payload = response.json()
                if not isinstance(payload, dict) or "errors" in payload or "error" in payload:
                    raise ValueError("Fleetio returned an unexpected response")
                if op.operation.startswith("list_"):
                    rows = payload.get("records")
                    cursor = payload.get("next_cursor")
                    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                        raise ValueError("Fleetio returned an invalid records page")
                    if cursor is not None and (not isinstance(cursor, str) or not 1 <= len(cursor) <= 8192):
                        raise ValueError("Fleetio returned an invalid next cursor")
                    result = {"status": "success", "records": rows, "next_cursor": cursor,
                        "has_more": cursor is not None, "per_page": payload.get("per_page", op.per_page)}
                else:
                    if type(payload.get("id")) is not int:
                        raise ValueError("Fleetio returned a record without a numeric ID")
                    result = {"status": "success", "data": payload}
                    if method != "GET":
                        result["write_acknowledged"] = True
                result["http_status"] = response.status_code
        except httpx.TransportError:
            # Mutations are never retried: a transport failure can follow a write.
            result = {"status": "error", "error": "Fleetio could not be reached; inspect the account before retrying a write", "write_outcome": "unverified" if method != "GET" else None}
        result = _redact(result, credential)
        await self.emit(result)
        return result
