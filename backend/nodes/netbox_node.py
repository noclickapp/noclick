"""NetBox DCIM/IPAM operations, pinned to the published 4.7.4 REST contract."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret, https_origin
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import guarded_async_client


class NetBoxTokenCredential(BaseModel):
    model_config = ConfigDict(title="Netbox API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://netbox.readthedocs.io/en/stable/integrations/rest-api/#authentication",
        "x-credential-instructions": "Enter your public HTTPS NetBox origin and paste an API token from your user profile. Prefer a v2 token (nbt_<key>.<token>); legacy v1 tokens are also supported. Enable writes and grant the relevant object permissions for write operations. Triggers also need add/delete permissions for extras.webhook and extras.eventrule. Private network instances cannot be reached from NoClick.",
    })
    credential_type: Literal["netbox_api_token"] = Field("netbox_api_token", json_schema_extra={"ui:hidden": True})
    base_url: str = Field(..., title="NetBox URL", description="Public HTTPS origin, for example https://netbox.example.com. Use an instance served at the domain root.")
    api_token: str = Field(..., title="API Token", repr=False, min_length=1, max_length=4096,
        description="Paste the token without the Authorization, Bearer or Token prefix.", json_schema_extra={"ui:widget": "password"})

    @field_validator("base_url", mode="before")
    @classmethod
    def server(cls, value):
        origin = https_origin(value, field_name="NetBox URL")
        if not origin.startswith("https://"):
            raise ValueError("Use a public HTTPS NetBox origin")
        return origin

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class Operation:
    label: str
    method: str
    path: str
    fields: dict[str, Any]
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()


def text(title, *, required=False, maximum=200, pattern=None):
    return (str if required else str | None, Field(... if required else None,
        title=title, max_length=maximum, min_length=1 if required else None, pattern=pattern))


def identifier(title, *, required=False):
    return (int if required else int | None, Field(... if required else None, title=title, ge=1))


def choice(title, values):
    return (Literal[tuple(values)] | None, Field(None, title=title))


PAGE = {
    "limit": (int, Field(50, ge=1, le=1000, title="Page Size")),
    "offset": (int, Field(0, ge=0, title="Offset", description="Use next_offset from the previous response.")),
    "q": text("Search"),
}
RECORD = {"id": identifier("Record ID", required=True)}


OPERATIONS = {
    'list_devices': Operation('List Devices', 'GET', '/api/dcim/devices/', {
        **PAGE,
        'site_id': identifier('Site Id'),
        'name': text('Name'),
        'status': choice("Status", ['offline', 'active', 'planned', 'staged', 'failed', 'inventory', 'decommissioning'])},
        query=('limit', 'offset', 'q', 'site_id', 'name', 'status')),
    'get_device': Operation('Get Device', 'GET', '/api/dcim/devices/{id}/', {
        **RECORD},
    ),
    'create_device': Operation('Create Device', 'POST', '/api/dcim/devices/', {
        'name': text('Name', required=False, maximum=64),
        'device_type': identifier('Device Type', required=True),
        'role': identifier('Role', required=True),
        'site': identifier('Site', required=True),
        'status': choice('Status', ['offline', 'active', 'planned', 'staged', 'failed', 'inventory', 'decommissioning']),
        'serial': text('Serial', required=False, maximum=50),
        'asset_tag': text('Asset Tag', required=False, maximum=50),
        'description': text('Description', required=False, maximum=200),
        'primary_ip4': identifier('Primary IP4', required=False),
        'primary_ip6': identifier('Primary IP6', required=False),
        'tenant': identifier('Tenant', required=False),
        'rack': identifier('Rack', required=False),
        'custom_fields': (dict[str, Any] | None, Field(None, title="Custom Fields"))},
        body=('name', 'device_type', 'role', 'site', 'status', 'serial', 'asset_tag', 'description', 'primary_ip4', 'primary_ip6', 'tenant', 'rack', 'custom_fields')),
    'update_device': Operation('Update Device', 'PATCH', '/api/dcim/devices/{id}/', {
        **RECORD,
        'name': text('Name', required=False, maximum=64),
        'device_type': identifier('Device Type', required=False),
        'role': identifier('Role', required=False),
        'site': identifier('Site', required=False),
        'status': choice('Status', ['offline', 'active', 'planned', 'staged', 'failed', 'inventory', 'decommissioning']),
        'serial': text('Serial', required=False, maximum=50),
        'asset_tag': text('Asset Tag', required=False, maximum=50),
        'description': text('Description', required=False, maximum=200),
        'primary_ip4': identifier('Primary IP4', required=False),
        'primary_ip6': identifier('Primary IP6', required=False),
        'tenant': identifier('Tenant', required=False),
        'rack': identifier('Rack', required=False),
        'custom_fields': (dict[str, Any] | None, Field(None, title="Custom Fields"))},
        body=('name', 'device_type', 'role', 'site', 'status', 'serial', 'asset_tag', 'description', 'primary_ip4', 'primary_ip6', 'tenant', 'rack', 'custom_fields')),
    'list_sites': Operation('List Sites', 'GET', '/api/dcim/sites/', {
        **PAGE,
        'name': text('Name'),
        'slug': text('Slug'),
        'status': choice("Status", ['planned', 'staging', 'active', 'decommissioning', 'retired'])},
        query=('limit', 'offset', 'q', 'name', 'slug', 'status')),
    'get_site': Operation('Get Site', 'GET', '/api/dcim/sites/{id}/', {
        **RECORD},
    ),
    'create_site': Operation('Create Site', 'POST', '/api/dcim/sites/', {
        'name': text('Name', required=True, maximum=100),
        'slug': text('Slug', required=True, maximum=100, pattern='^[-a-zA-Z0-9_]+$'),
        'status': choice('Status', ['planned', 'staging', 'active', 'decommissioning', 'retired']),
        'description': text('Description', required=False, maximum=200),
        'physical_address': text('Physical Address', required=False, maximum=200),
        'tenant': identifier('Tenant', required=False),
        'custom_fields': (dict[str, Any] | None, Field(None, title="Custom Fields"))},
        body=('name', 'slug', 'status', 'description', 'physical_address', 'tenant', 'custom_fields')),
    'update_site': Operation('Update Site', 'PATCH', '/api/dcim/sites/{id}/', {
        **RECORD,
        'name': text('Name', required=False, maximum=100),
        'slug': text('Slug', required=False, maximum=100, pattern='^[-a-zA-Z0-9_]+$'),
        'status': choice('Status', ['planned', 'staging', 'active', 'decommissioning', 'retired']),
        'description': text('Description', required=False, maximum=200),
        'physical_address': text('Physical Address', required=False, maximum=200),
        'tenant': identifier('Tenant', required=False),
        'custom_fields': (dict[str, Any] | None, Field(None, title="Custom Fields"))},
        body=('name', 'slug', 'status', 'description', 'physical_address', 'tenant', 'custom_fields')),
    'list_ip_addresses': Operation('List IP Addresses', 'GET', '/api/ipam/ip-addresses/', {
        **PAGE,
        'address': text('Address'),
        'device_id': identifier('Device Id'),
        'status': choice("Status", ['active', 'reserved', 'deprecated', 'dhcp', 'slaac'])},
        query=('limit', 'offset', 'q', 'address', 'device_id', 'status')),
    'get_ip_address': Operation('Get IP Address', 'GET', '/api/ipam/ip-addresses/{id}/', {
        **RECORD},
    ),
    'create_ip_address': Operation('Create IP Address', 'POST', '/api/ipam/ip-addresses/', {
        'address': text('Address', required=True, maximum=200),
        'status': choice('Status', ['active', 'reserved', 'deprecated', 'dhcp', 'slaac']),
        'vrf': identifier('Vrf', required=False),
        'tenant': identifier('Tenant', required=False),
        'dns_name': text('DNS Name', required=False, maximum=200),
        'description': text('Description', required=False, maximum=200),
        'assigned_object_type': text('Assigned Object Type', required=False, maximum=200),
        'assigned_object_id': identifier('Assigned Object Id', required=False),
        'custom_fields': (dict[str, Any] | None, Field(None, title="Custom Fields"))},
        body=('address', 'status', 'vrf', 'tenant', 'dns_name', 'description', 'assigned_object_type', 'assigned_object_id', 'custom_fields')),
    'update_ip_address': Operation('Update IP Address', 'PATCH', '/api/ipam/ip-addresses/{id}/', {
        **RECORD,
        'address': text('Address', required=False, maximum=200),
        'status': choice('Status', ['active', 'reserved', 'deprecated', 'dhcp', 'slaac']),
        'vrf': identifier('Vrf', required=False),
        'tenant': identifier('Tenant', required=False),
        'dns_name': text('DNS Name', required=False, maximum=200),
        'description': text('Description', required=False, maximum=200),
        'assigned_object_type': text('Assigned Object Type', required=False, maximum=200),
        'assigned_object_id': identifier('Assigned Object Id', required=False),
        'custom_fields': (dict[str, Any] | None, Field(None, title="Custom Fields"))},
        body=('address', 'status', 'vrf', 'tenant', 'dns_name', 'description', 'assigned_object_type', 'assigned_object_id', 'custom_fields')),
    'list_prefixes': Operation('List Prefixes', 'GET', '/api/ipam/prefixes/', {
        **PAGE,
        'prefix': text('Prefix'),
        'status': choice("Status", ['container', 'active', 'reserved', 'deprecated']),
        'vrf_id': identifier('Vrf Id')},
        query=('limit', 'offset', 'q', 'prefix', 'status', 'vrf_id')),
    'get_prefix': Operation('Get Prefix', 'GET', '/api/ipam/prefixes/{id}/', {
        **RECORD},
    ),
    'create_prefix': Operation('Create Prefix', 'POST', '/api/ipam/prefixes/', {
        'prefix': text('Prefix', required=True, maximum=200),
        'status': choice('Status', ['container', 'active', 'reserved', 'deprecated']),
        'vrf': identifier('Vrf', required=False),
        'tenant': identifier('Tenant', required=False),
        'vlan': identifier('Vlan', required=False),
        'description': text('Description', required=False, maximum=200),
        'is_pool': (bool | None, Field(None, title='Is Pool')),
        'custom_fields': (dict[str, Any] | None, Field(None, title="Custom Fields"))},
        body=('prefix', 'status', 'vrf', 'tenant', 'vlan', 'description', 'is_pool', 'custom_fields')),
    'update_prefix': Operation('Update Prefix', 'PATCH', '/api/ipam/prefixes/{id}/', {
        **RECORD,
        'prefix': text('Prefix', required=False, maximum=200),
        'status': choice('Status', ['container', 'active', 'reserved', 'deprecated']),
        'vrf': identifier('Vrf', required=False),
        'tenant': identifier('Tenant', required=False),
        'vlan': identifier('Vlan', required=False),
        'description': text('Description', required=False, maximum=200),
        'is_pool': (bool | None, Field(None, title='Is Pool')),
        'custom_fields': (dict[str, Any] | None, Field(None, title="Custom Fields"))},
        body=('prefix', 'status', 'vrf', 'tenant', 'vlan', 'description', 'is_pool', 'custom_fields')),
    'list_virtual_machines': Operation('List Virtual Machines', 'GET', '/api/virtualization/virtual-machines/', {
        **PAGE,
        'name': text('Name'),
        'status': choice("Status", ['offline', 'active', 'planned', 'staged', 'failed', 'decommissioning', 'paused']),
        'cluster_id': identifier('Cluster Id')},
        query=('limit', 'offset', 'q', 'name', 'status', 'cluster_id')),
    'get_virtual_machine': Operation('Get Virtual Machine', 'GET', '/api/virtualization/virtual-machines/{id}/', {
        **RECORD},
    ),
    'create_virtual_machine': Operation('Create Virtual Machine', 'POST', '/api/virtualization/virtual-machines/', {
        'name': text('Name', required=True, maximum=64),
        'status': choice('Status', ['offline', 'active', 'planned', 'staged', 'failed', 'decommissioning', 'paused']),
        'cluster': identifier('Cluster', required=False),
        'site': identifier('Site', required=False),
        'tenant': identifier('Tenant', required=False),
        'vcpus': (float | None, Field(None, title='vCPUs', ge=0.01, lt=10000)),
        'memory': (int | None, Field(None, title='Memory', ge=0, le=2147483647)),
        'disk': (int | None, Field(None, title='Disk', ge=0, le=2147483647)),
        'description': text('Description', required=False, maximum=200),
        'custom_fields': (dict[str, Any] | None, Field(None, title="Custom Fields"))},
        body=('name', 'status', 'cluster', 'site', 'tenant', 'vcpus', 'memory', 'disk', 'description', 'custom_fields')),
    'update_virtual_machine': Operation('Update Virtual Machine', 'PATCH', '/api/virtualization/virtual-machines/{id}/', {
        **RECORD,
        'name': text('Name', required=False, maximum=64),
        'status': choice('Status', ['offline', 'active', 'planned', 'staged', 'failed', 'decommissioning', 'paused']),
        'cluster': identifier('Cluster', required=False),
        'site': identifier('Site', required=False),
        'tenant': identifier('Tenant', required=False),
        'vcpus': (float | None, Field(None, title='vCPUs', ge=0.01, lt=10000)),
        'memory': (int | None, Field(None, title='Memory', ge=0, le=2147483647)),
        'disk': (int | None, Field(None, title='Disk', ge=0, le=2147483647)),
        'description': text('Description', required=False, maximum=200),
        'custom_fields': (dict[str, Any] | None, Field(None, title="Custom Fields"))},
        body=('name', 'status', 'cluster', 'site', 'tenant', 'vcpus', 'memory', 'disk', 'description', 'custom_fields')),
    "list_interfaces": Operation("List Interfaces", "GET", "/api/dcim/interfaces/", {
        **PAGE, "device_id": identifier("Device ID"), "name": text("Name")},
        query=("limit", "offset", "q", "device_id", "name")),
    "update_interface": Operation("Update Interface", "PATCH", "/api/dcim/interfaces/{id}/", {
        **RECORD, "name": text("Name", maximum=64),
        "enabled": (bool | None, Field(None, title="Enabled")),
        "description": text("Description"), "mtu": (int | None, Field(None, ge=1, le=65536, title="MTU"))},
        body=("name", "enabled", "description", "mtu")),
    "allocate_ip_address": Operation("Allocate Available IP Address", "POST", "/api/ipam/prefixes/{id}/available-ips/", {
        "id": identifier("Parent Prefix ID", required=True),
        "prefix_length": (int | None, Field(None, ge=0, le=128, title="Prefix Length", description="Optional mask length. Omit to use NetBox's default."))},
        body=("prefix_length",)),
    "delete_ip_address": Operation("Delete IP Address", "DELETE", "/api/ipam/ip-addresses/{id}/", RECORD),
}


def _model(name, spec):
    return create_model("NetBox" + "".join(part.title() for part in name.split("_")), __base__=_Input,
        operation=(Literal[name], Field(name, title=spec.label, json_schema_extra={
            "ui:hidden": True, "x-display-name": spec.label,
            "x-category": "IPAM" if "/ipam/" in spec.path else "Virtualization" if "/virtualization/" in spec.path else "DCIM"})),
        **spec.fields)


CONFIG_MODELS = {name: _model(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
OBJECT_TYPES = ("dcim.device", "dcim.site", "dcim.interface", "ipam.ipaddress", "ipam.prefix", "virtualization.virtualmachine")


class NetBoxOnObjectCreated(WebhookTriggerConfigBase):
    operation: Literal["on_object_created"] = Field("on_object_created", title="On Object Created", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On Object Created", "x-category": "Triggers", "x-is-trigger": True})
    object_type: Literal[*OBJECT_TYPES] = Field("dcim.site", title="Object Type")
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={
        "ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


NetBoxConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (NetBoxOnObjectCreated,)], Field(discriminator="operation")]


class NetBoxNodeConfig(NodeConfig[NetBoxConfig, NetBoxTokenCredential]):
    pass


class NetBoxNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-netbox"
    credential_provider_labels = {"netbox": "NetBox"}
    connection_evidence = ConnectionEvidence(operation="list_sites", noun="sites")
    edit_examples = ["Find NetBox devices at a site", "Assign an IP address to an interface", "Update a prefix", "Run when a NetBox object is created"]

    @classmethod
    def get_config_model(cls):
        return NetBoxNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None, allow_missing=False, many=False):
        credential = NetBoxTokenCredential.model_validate(credential)
        token = credential.api_token
        headers = {"Authorization": ("Bearer " if token.startswith("nbt_") else "Token ") + token,
                   "Accept": "application/json"}
        async with guarded_async_client(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, credential.base_url + path, headers=headers, params=params, json=body)
        if allow_missing and response.status_code == 404:
            return None
        if not 200 <= response.status_code < 300:
            # Preserve the provider rejection for the connection-evidence seam.
            raise ValueError(f"NetBox API error {response.status_code}: {response.text.replace(token, '[redacted]')[:1000]}")
        if response.status_code == 204:
            return {"deleted": True}
        data = response.json()
        if (many and (not isinstance(data, list) or any(not isinstance(item, dict) for item in data))) or (not many and not isinstance(data, dict)):
            raise ValueError("NetBox returned an invalid resource response")
        return data

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect your NetBox instance")
        config = self.config.config
        if isinstance(config, NetBoxOnObjectCreated):
            return {"status": "success", "operation": config.operation, "data": inputs}
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec.path.replace("{id}", str(values.get("id", "")))
        params = {key: values[key] for key in spec.query if key in values}
        body = {key: values[key] for key in spec.body if key in values}
        if spec.method == "PATCH" and not body:
            raise ValueError("Choose at least one field to update")
        many = config.operation == "allocate_ip_address"
        data = await self._request(self.config.credentials, spec.method, path, params=params or None,
                                   body=[body] if many else body if spec.method in {"POST", "PATCH"} else None,
                                   many=many)
        output = {"status": "success", "operation": config.operation, "data": data}
        if spec.query:
            if not isinstance(data.get("results"), list):
                raise ValueError("NetBox returned an invalid paginated response")
            # Never follow a server-supplied continuation URL with a token.
            output["next_offset"] = values["offset"] + len(data["results"]) if data.get("next") else None
            output["has_more"] = bool(data.get("next"))
        return output

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        object_type = NetBoxOnObjectCreated.model_validate(config).object_type
        secret = secrets.token_hex(32)
        name = "NoClick " + str(node_id)
        webhook = await cls._request(credential, "POST", "/api/extras/webhooks/", body={
            "name": name, "payload_url": webhook_url, "http_method": "POST",
            "http_content_type": "application/json", "secret": secret, "ssl_verification": True})
        webhook_id = int(webhook["id"])
        if webhook_id <= 0:
            raise ValueError("NetBox did not return a webhook ID")
        try:
            rule = await cls._request(credential, "POST", "/api/extras/event-rules/", body={
                "name": name, "object_types": [object_type], "event_types": ["object_created"],
                "action_type": "webhook", "action_object_type": "extras.webhook", "action_object_id": webhook_id,
                "enabled": True})
            rule_id = int(rule["id"])
            if rule_id <= 0:
                raise ValueError("NetBox did not return an event rule ID")
        except Exception:
            await cls._request(credential, "DELETE", f"/api/extras/webhooks/{webhook_id}/", allow_missing=True)
            raise
        # One persisted lifecycle ID carries both resources; teardown deletes the rule first.
        return {"external_webhook_id": f"{webhook_id}:{rule_id}", "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        registration = config.get("external_webhook_id")
        if not registration:
            return
        if not credential:
            raise ValueError("Connect NetBox to remove its webhook and event rule")
        parts = str(registration).split(":")
        if len(parts) != 2 or any(not p.isdecimal() or int(p) <= 0 for p in parts):
            raise ValueError("Invalid NetBox webhook registration IDs")
        webhook_id, rule_id = map(int, parts)
        await cls._request(credential, "DELETE", f"/api/extras/event-rules/{rule_id}/", allow_missing=True)
        await cls._request(credential, "DELETE", f"/api/extras/webhooks/{webhook_id}/", allow_missing=True)

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"object_type": config.get("object_type", "dcim.site")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = config.get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "x-hook-signature"), "")
        if not isinstance(secret, str) or not secret or not isinstance(signature, str) or not signature.isascii():
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected, signature)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get("event") == "created" and payload.get("object_type") == config.get("object_type", "dcim.site")

    @classmethod
    def resolve_agent_event(cls, output):
        data = output.get("data")
        if output.get("event") != "created" or not isinstance(data, dict):
            return None
        object_type = output.get("object_type")
        identifier = data.get("id")
        label = data.get("display")
        request = output.get("request") or {}
        text = f"NetBox: {object_type} created: {label} (ID {identifier})."
        if request.get("user"):
            text += f" Created by {request['user']}."
        text += f" Time: {output.get('timestamp')}. Object URL: {data.get('display_url')}. API URL: {data.get('url')}."
        text += "\nObject details: " + json.dumps(data, ensure_ascii=False)[:6000]
        return {"text": text, "conversation_key": f"{object_type}:{identifier}", "title": f"NetBox: {label} created"}
