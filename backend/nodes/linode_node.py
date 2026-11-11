"""Linode API v4 instance, DNS and inventory automation using a personal token.

Actions use fixed provider endpoints; event triggers poll the account history.
Power actions report acceptance because Linode completes those jobs asynchronously.
"""
from __future__ import annotations

import ipaddress
import json
import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://api.linode.com/v4"
PositiveId = Annotated[int, Field(gt=0)]
Text = Annotated[str, Field(min_length=1, max_length=255)]
TTL = Annotated[int, Field(ge=0, le=2419200)]


class LinodeTokenCredential(BaseModel):
    model_config = ConfigDict(title="Linode Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://cloud.linode.com/profile/tokens",
            "x-credential-instructions": "Create a personal access token in Cloud Manager > My Profile > API Tokens and paste it here. Grant only the categories needed: Linodes and Domains Read/Write for mutations, Images, Volumes and Events Read Only for reads. The profile read checks the current user; it does not verify every operation's permissions.",
        })
    credential_type: Literal["linode_personal_access_token"] = Field("linode_personal_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=4096, title="Personal access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the token alone, without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page to read; use next_page from the previous response.")
    page_size: int = Field(100, ge=25, le=500)


class GetProfile(_Input):
    """Read the current token's user profile."""
    operation: Literal["get_profile"] = "get_profile"


class ListInstances(_Page):
    """List one page of your Linode instances."""
    operation: Literal["list_instances"] = "list_instances"


class GetInstance(_Input):
    """Read one instance's current state."""
    operation: Literal["get_instance"] = "get_instance"
    linode_id: PositiveId


class _InstanceFields(_Input):
    label: Annotated[str, Field(min_length=3, max_length=64)] | None = None
    tags: list[Text] | None = Field(None, max_length=100)

    @field_validator("label")
    @classmethod
    def valid_label(cls, value):
        if value is not None and (not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*[A-Za-z0-9]", value) or any(x in value for x in ("--", "__", ".."))):
            raise ValueError("Use a Linode label beginning with a letter and ending with a letter or digit; no repeated separators")
        return value


class CreateInstance(_InstanceFields):
    """Create a billable Linode, optionally deploying an image."""
    operation: Literal["create_instance"] = "create_instance"
    region: Text = Field(..., description="Region ID from List Regions, such as us-east.")
    type: Text = Field(..., description="Plan ID from List Types, such as g6-standard-2. Creation incurs provider charges.")
    image: Text | None = Field(None, description="Image ID from List Images; omit for an empty instance.")
    root_pass: Annotated[str, Field(min_length=7, max_length=128)] | None = Field(None, repr=False, json_schema_extra={"ui:widget": "password", "writeOnly": True}, description="Required when deploying an image under this API contract.")
    authorized_keys: list[str] | None = Field(None, max_length=100, description="Public SSH keys to install when deploying an image.")
    booted: bool | None = None
    private_ip: bool | None = None
    backups_enabled: bool | None = Field(None, description="Enrolling in backups incurs an additional charge.")

    @model_validator(mode="after")
    def image_password(self):
        if self.image is not None and self.root_pass is None:
            raise ValueError("Provide a root password when deploying an image")
        return self


class UpdateInstance(_InstanceFields):
    """Update an instance label, tags or shutdown watchdog."""
    operation: Literal["update_instance"] = "update_instance"
    linode_id: PositiveId
    watchdog_enabled: bool | None = None

    @model_validator(mode="after")
    def changes(self):
        if all(getattr(self, k) is None for k in ("label", "tags", "watchdog_enabled")):
            raise ValueError("Provide a label, tags or watchdog setting to update")
        return self


class DeleteInstance(GetInstance):
    """Permanently delete an instance and its disks."""
    operation: Literal["delete_instance"] = "delete_instance"


class BootInstance(GetInstance):
    """Start booting an instance; completion is asynchronous."""
    operation: Literal["boot_instance"] = "boot_instance"
    config_id: PositiveId | None = None


class ShutdownInstance(GetInstance):
    """Start shutting down an instance; completion is asynchronous."""
    operation: Literal["shutdown_instance"] = "shutdown_instance"


class RebootInstance(BootInstance):
    """Start rebooting an instance; completion is asynchronous."""
    operation: Literal["reboot_instance"] = "reboot_instance"


class ListRegions(_Input):
    """List the public catalogue of available regions."""
    operation: Literal["list_regions"] = "list_regions"


class ListTypes(_Input):
    """List the public catalogue of instance plans and prices."""
    operation: Literal["list_types"] = "list_types"


class ListImages(_Page):
    """List official and account images available to the token."""
    operation: Literal["list_images"] = "list_images"


class ListDomains(_Page):
    """List one page of account DNS zones."""
    operation: Literal["list_domains"] = "list_domains"


class GetDomain(_Input):
    """Read one DNS zone."""
    operation: Literal["get_domain"] = "get_domain"
    domain_id: PositiveId


class CreateDomain(_Input):
    """Create a primary DNS zone for a domain you own."""
    operation: Literal["create_domain"] = "create_domain"
    domain: Annotated[str, Field(min_length=1, max_length=253)]
    type: Literal["master"] = "master"
    soa_email: EmailStr
    description: Annotated[str, Field(min_length=1, max_length=253)] | None = None
    ttl_sec: TTL | None = None
    tags: list[Text] | None = Field(None, max_length=100)


class DeleteDomain(GetDomain):
    """Delete a DNS zone and all of its records."""
    operation: Literal["delete_domain"] = "delete_domain"


class ListRecords(_Page):
    """List one page of records in a DNS zone."""
    operation: Literal["list_records"] = "list_records"
    domain_id: PositiveId


class CreateRecord(_Input):
    """Create an A, AAAA, CNAME, MX or TXT record."""
    operation: Literal["create_record"] = "create_record"
    domain_id: PositiveId
    type: Literal["A", "AAAA", "CNAME", "MX", "TXT"]
    name: Annotated[str, Field(min_length=1, max_length=100)] | None = Field(None, description="Omit for the zone apex; CNAME requires a hostname.")
    target: Annotated[str, Field(min_length=1, max_length=65535)]
    ttl_sec: TTL | None = None
    priority: Annotated[int, Field(ge=0, le=255)] | None = None

    @model_validator(mode="after")
    def record_fields(self):
        if self.type == "CNAME" and self.name is None:
            raise ValueError("CNAME records require a hostname")
        if self.priority is not None and self.type != "MX":
            raise ValueError("Priority is supported for MX records")
        if self.type in {"A", "AAAA"}:
            if self.target == "[remote_addr]" and self.type == "A":
                return self
            address = ipaddress.ip_address(self.target)
            if address.version != (4 if self.type == "A" else 6):
                raise ValueError("Target address family must match the record type")
        return self


class UpdateRecord(_Input):
    """Update selected fields of an existing record without changing its type."""
    operation: Literal["update_record"] = "update_record"
    domain_id: PositiveId
    record_id: PositiveId
    name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    target: Annotated[str, Field(min_length=1, max_length=65535)] | None = None
    ttl_sec: TTL | None = None
    priority: Annotated[int, Field(ge=0, le=255)] | None = None

    @model_validator(mode="after")
    def changes(self):
        if all(getattr(self, k) is None for k in ("name", "target", "ttl_sec", "priority")):
            raise ValueError("Provide at least one record field to update")
        return self


class DeleteRecord(_Input):
    """Delete one record from its explicit parent DNS zone."""
    operation: Literal["delete_record"] = "delete_record"
    domain_id: PositiveId
    record_id: PositiveId


class ListVolumes(_Page):
    """List one page of account block storage volumes."""
    operation: Literal["list_volumes"] = "list_volumes"


class ListEvents(_Page):
    """List one page of account events, including asynchronous job status."""
    operation: Literal["list_events"] = "list_events"


class OnNewEvent(PollTriggerConfigBase):
    """Poll account actions from the last 90 days; the first poll records a baseline."""
    operation: Literal["on_new_event"] = Field("on_new_event", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Account Event",
    })
    action: Text | None = Field(None, description="Optional exact event action, such as linode_boot, linode_create or dns_record_update. Leave empty for all actions.")


class OnEventFinished(OnNewEvent):
    """Poll account events reaching completed, finished or failed; existing terminal events are baselined."""
    operation: Literal["on_event_finished"] = Field("on_event_finished", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Event Finished or Failed",
    })


LinodeConfig = Annotated[Union[GetProfile, ListInstances, GetInstance, CreateInstance,
    UpdateInstance, DeleteInstance, BootInstance, ShutdownInstance, RebootInstance,
    ListRegions, ListTypes, ListImages, ListDomains, GetDomain, CreateDomain,
    DeleteDomain, ListRecords, CreateRecord, UpdateRecord, DeleteRecord, ListVolumes,
    ListEvents, OnNewEvent, OnEventFinished], Field(discriminator="operation")]


class LinodeNodeConfig(NodeConfig[LinodeConfig, LinodeTokenCredential]):
    pass


# Fixed routes and methods from the published Linode API v4 OpenAPI contract.
ROUTES = {
    "get_profile": ("GET", "/profile"),
    "list_instances": ("GET", "/linode/instances"),
    "get_instance": ("GET", "/linode/instances/{linode_id}"),
    "create_instance": ("POST", "/linode/instances"),
    "update_instance": ("PUT", "/linode/instances/{linode_id}"),
    "delete_instance": ("DELETE", "/linode/instances/{linode_id}"),
    "boot_instance": ("POST", "/linode/instances/{linode_id}/boot"),
    "shutdown_instance": ("POST", "/linode/instances/{linode_id}/shutdown"),
    "reboot_instance": ("POST", "/linode/instances/{linode_id}/reboot"),
    "list_regions": ("GET", "/regions"),
    "list_types": ("GET", "/linode/types"),
    "list_images": ("GET", "/images"),
    "list_domains": ("GET", "/domains"),
    "get_domain": ("GET", "/domains/{domain_id}"),
    "create_domain": ("POST", "/domains"),
    "delete_domain": ("DELETE", "/domains/{domain_id}"),
    "list_records": ("GET", "/domains/{domain_id}/records"),
    "create_record": ("POST", "/domains/{domain_id}/records"),
    "update_record": ("PUT", "/domains/{domain_id}/records/{record_id}"),
    "delete_record": ("DELETE", "/domains/{domain_id}/records/{record_id}"),
    "list_volumes": ("GET", "/volumes"),
    "list_events": ("GET", "/account/events"),
}
IDS = {"linode_id", "domain_id", "record_id"}


def _redact(value, secrets):
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items() if k not in {"root_pass", "access_token"}}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
    return value


class LinodeNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-linode"
    connection_evidence = ConnectionEvidence(noun="Linode user", identity_operation="get_profile", identity_keys=("username", "email"))

    @classmethod
    def get_config_model(cls):
        return LinodeNodeConfig

    @staticmethod
    async def _request(token, method, route, *, params=None, body=None, headers=None):
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            return await client.request(method, BASE + route,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json", **(headers or {})},
                params=params, **({"json": body} if body is not None else {}))

    @staticmethod
    def _payload(response):
        if len(response.content) > 10_000_000:
            raise ValueError("Linode response exceeds the supported JSON size")
        try:
            payload = response.json()
        except (ValueError, UnicodeError):
            raise ValueError("Expected a JSON object from Linode") from None
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object from Linode")
        return payload

    @staticmethod
    def _list_payload(payload):
        if not isinstance(payload.get("data"), list) or any(not isinstance(row, dict) for row in payload["data"]):
            raise ValueError("Expected a Linode list envelope")
        page, pages = payload.get("page"), payload.get("pages")
        if type(page) is not int or type(pages) is not int or page < 1 or pages < 0:
            raise ValueError("Expected Linode pagination metadata")
        return payload["data"], page, pages

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") in {"on_new_event", "on_event_finished"}:
            return bool(output.get("event_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        if "events" not in output:
            return super().resolve_agent_event(output)
        events = output["events"]
        if not events:
            return None
        lines = []
        for event in events[:20]:
            entity = event.get("entity") or {}
            lines.append(f"- {event.get('username') or 'Linode'}: {event['action'].replace('_', ' ')} ({event['action']}) "
                f"[{event['status']}] at {event['created']}; "
                f"{entity.get('type') or 'account'} {entity.get('label') or ''} "
                f"(entity id {entity.get('id')}, event id {event['id']}) "
                f"{entity.get('url') or ''}; {event.get('message') or ''}")
        if len(events) > 20:
            lines.append(f"- … and {len(events) - 20} more events in the workflow output")
        return {"text": f"Linode: {len(events)} account event(s):\n" + "\n".join(lines),
                "conversation_key": None}

    async def _poll_events(self, token, op):
        events = []
        ordering = {"+order_by": "created", "+order": "desc"}
        if op.action is not None:
            ordering["action"] = op.action
        for page in range(1, 21):
            response = await self._request(token, "GET", "/account/events",
                params={"page": page, "page_size": 500}, headers={"X-Filter": json.dumps(ordering)})
            payload = self._payload(response)
            if response.status_code != 200 or "errors" in payload:
                raise ValueError(f"Linode event poll rejected (HTTP {response.status_code})")
            rows, current, pages = self._list_payload(payload)
            if current != page:
                raise ValueError("Linode event poll returned an unexpected page")
            for event in rows:
                if type(event.get("id")) is not int or any(not isinstance(event.get(k), str) for k in ("action", "status", "created")):
                    raise ValueError("Expected Linode event identity, action, status and creation time")
                if op.action is not None and event["action"] != op.action:
                    continue
                if isinstance(op, OnEventFinished) and event["status"] not in {"completed", "finished", "failed"}:
                    continue
                events.append(event)
            if page >= pages:
                break
        else:
            raise ValueError("Linode returned more than 10,000 events; select a narrower action to monitor")
        # Oldest first keeps recent events at the end of the bounded seen set.
        unique = {event["id"]: event for event in events}
        fresh = await self._filter_unseen(list(reversed(list(unique.values()))), lambda event: str(event["id"]))
        result = {"status": "success", "operation": op.operation, "events": fresh, "event_count": len(fresh)}
        await self.emit(result)
        return result

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Linode personal access token")
        op = self.config.config
        token = self.config.credentials.access_token
        if isinstance(op, OnNewEvent):
            return await self._poll_events(token, op)
        secrets = (token, getattr(op, "root_pass", None))
        method, template = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        route = template.format(**values)
        fields = {k: v for k, v in values.items() if k not in IDS}
        params = fields if method == "GET" else None
        body = fields if method in {"POST", "PUT"} and fields else None
        try:
            response = await self._request(token, method, route, params=params, body=body)
        except httpx.TransportError:
            result = {"status": "error" if method == "GET" else "unknown", "success": False,
                "message": "Linode request could not be confirmed; inspect the resource before retrying a write."}
        else:
            payload = self._payload(response)
            if response.status_code != 200 or "errors" in payload:
                reasons = payload.get("errors", [])
                message = "; ".join(str(row.get("reason", "")) for row in reasons if isinstance(row, dict)) if isinstance(reasons, list) else ""
                result = {"status": "error", "success": False, "http_status": response.status_code,
                    "message": message or "Linode request was rejected"}
            else:
                result = {"status": "success", "success": True, "operation": op.operation,
                    "http_status": response.status_code, "data": payload}
                if op.operation.startswith("list_"):
                    _, page, pages = self._list_payload(payload)
                    result.update(data=payload["data"], page=page, pages=pages,
                        results=payload.get("results"), next_page=page + 1 if page < pages else None)
                elif op.operation == "get_profile":
                    if not isinstance(payload.get("username"), str) or not payload["username"]:
                        raise ValueError("Linode did not return a user identity")
                elif op.operation in {"boot_instance", "shutdown_instance", "reboot_instance"}:
                    result.update(accepted=True, completed=False)
                elif method == "DELETE":
                    result["deletion_acknowledged"] = True
        result = _redact(result, secrets)
        await self.emit(result)
        return result
