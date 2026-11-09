"""Tailscale v2 device, route, DNS, user and key automation.

Contract: https://api.tailscale.com/api/v2 (v2). Personal API access tokens
are sent only to the fixed API origin. Each operation makes one API request;
Tailscale returns complete lists without pagination. Writes report the API's
acknowledgment, not an independently verified network state.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.tailscale.com/api/v2"
FAMILY = "tailscale_api_token"


class TailscaleAPITokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Tailscale API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://login.tailscale.com/admin/settings/keys",
            "x-credential-instructions": "Paste a personal API access token from Tailscale Settings → Keys. Use an API access token, not a device auth key or OAuth client secret. Tokens inherit your Tailscale permissions and expire after 1–90 days; replace the saved token when it expires. Connecting reads devices in the token's default tailnet. Write permissions are checked by Tailscale when each operation runs.",
        },
    )
    credential_type: Literal["tailscale_api_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096,
                           json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a header or whitespace")
        if value.startswith(("tskey-auth-", "tskey-client-")):
            raise ValueError("Use a personal API access token, not a device auth key or OAuth client secret")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_segments(cls, value, info):
        if info.field_name in {"tailnet", "device_id", "user_id", "key_id"}:
            if not re.fullmatch(r"[A-Za-z0-9_@+.-]{1,253}", value) or value in {".", ".."}:
                raise ValueError("Use a single Tailscale identifier, not a URL or path")
        return value


class _Tailnet(_Input):
    tailnet: str = Field("-", description="Tailnet ID or legacy name. '-' uses the access token's default tailnet.")


class _Device(_Input):
    device_id: str = Field(..., description="Device nodeId (preferred) or legacy id, from List Devices.")


class TailscaleListDevicesConfig(_Tailnet):
    """List all devices in the tailnet, without pagination."""
    operation: Literal["list_devices"] = "list_devices"
    fields: Literal["default", "all"] = "default"


class TailscaleGetDeviceConfig(_Device):
    """Get a device's details."""
    operation: Literal["get_device"] = "get_device"
    fields: Literal["default", "all"] = "default"


class TailscaleDeleteDeviceConfig(_Device):
    """Remove a device from its tailnet."""
    operation: Literal["delete_device"] = "delete_device"


class TailscaleExpireDeviceKeyConfig(_Device):
    """Expire the device's node key, requiring reauthentication."""
    operation: Literal["expire_device_key"] = "expire_device_key"


class TailscaleListDeviceRoutesConfig(_Device):
    """Read advertised and enabled subnet routes."""
    operation: Literal["list_device_routes"] = "list_device_routes"


class TailscaleSetDeviceRoutesConfig(_Device):
    """Replace enabled routes; an empty list disables all routes."""
    operation: Literal["set_device_routes"] = "set_device_routes"
    routes: list[str] = Field(..., max_length=1000, description="Complete list of enabled CIDR routes, e.g. ['10.0.0.0/16']. Routes must also be advertised by the device to carry traffic.")


class TailscaleAuthorizeDeviceConfig(_Device):
    """Authorize or deauthorize a device."""
    operation: Literal["authorize_device"] = "authorize_device"
    authorized: StrictBool


class TailscaleSetDeviceNameConfig(_Device):
    """Set a device's MagicDNS name, or reset it from its OS hostname."""
    operation: Literal["set_device_name"] = "set_device_name"
    name: str = Field("", max_length=253, description="Base name or full MagicDNS name. Empty resets to the OS hostname.")


class TailscaleSetDeviceTagsConfig(_Device):
    """Replace the complete list of identity tags on a device."""
    operation: Literal["set_device_tags"] = "set_device_tags"
    tags: list[str] = Field(..., max_length=1000, description="Complete replacement list, e.g. ['tag:prod']; [] removes all tags.")


class TailscaleUpdateDeviceKeyConfig(_Device):
    """Enable or disable device key expiry."""
    operation: Literal["update_device_key"] = "update_device_key"
    key_expiry_disabled: StrictBool = Field(..., description="True disables expiry. False restores the original expiry time, which may already be in the past.")


class TailscaleListDnsNameserversConfig(_Tailnet):
    """Read the global DNS nameservers."""
    operation: Literal["list_dns_nameservers"] = "list_dns_nameservers"


class TailscaleSetDnsNameserversConfig(_Tailnet):
    """Replace global DNS nameservers; [] removes them."""
    operation: Literal["set_dns_nameservers"] = "set_dns_nameservers"
    dns: list[str] = Field(..., max_length=1000, description="Complete nameserver list, e.g. ['8.8.8.8', '1.2.3.4'].")


class TailscaleGetDnsPreferencesConfig(_Tailnet):
    """Read whether MagicDNS is enabled."""
    operation: Literal["get_dns_preferences"] = "get_dns_preferences"


class TailscaleSetDnsPreferencesConfig(_Tailnet):
    """Enable or disable MagicDNS."""
    operation: Literal["set_dns_preferences"] = "set_dns_preferences"
    magic_dns: StrictBool


class TailscaleListDnsSearchPathsConfig(_Tailnet):
    """Read DNS search domains."""
    operation: Literal["list_dns_search_paths"] = "list_dns_search_paths"


class TailscaleSetDnsSearchPathsConfig(_Tailnet):
    """Replace DNS search domains; [] removes them."""
    operation: Literal["set_dns_search_paths"] = "set_dns_search_paths"
    search_paths: list[str] = Field(..., max_length=1000, description="Complete domain list, e.g. ['user1.example.com', 'user2.example.com'].")


class TailscaleListKeysConfig(_Tailnet):
    """List key metadata; secret key material is omitted."""
    operation: Literal["list_keys"] = "list_keys"
    all_keys: StrictBool = Field(False, description="Include revoked and expired keys.")


class TailscaleGetKeyConfig(_Tailnet):
    """Read metadata for an auth key or trust credential."""
    operation: Literal["get_key"] = "get_key"
    key_id: str


class TailscaleDeleteKeyConfig(_Tailnet):
    """Revoke an auth key or trust credential."""
    operation: Literal["delete_key"] = "delete_key"
    key_id: str


class TailscaleListUsersConfig(_Tailnet):
    """List tailnet users with optional relation and role filters."""
    operation: Literal["list_users"] = "list_users"
    user_type: Literal["member", "shared", "all"] = "member"
    role: Literal["owner", "member", "admin", "it-admin", "network-admin", "billing-admin", "auditor", "all"] = "all"


class TailscaleGetUserConfig(_Input):
    """Get a tailnet user's details."""
    operation: Literal["get_user"] = "get_user"
    user_id: str


TailscaleOperation = Annotated[Union[
    TailscaleListDevicesConfig, TailscaleGetDeviceConfig, TailscaleDeleteDeviceConfig,
    TailscaleExpireDeviceKeyConfig, TailscaleListDeviceRoutesConfig, TailscaleSetDeviceRoutesConfig,
    TailscaleAuthorizeDeviceConfig, TailscaleSetDeviceNameConfig, TailscaleSetDeviceTagsConfig,
    TailscaleUpdateDeviceKeyConfig, TailscaleListDnsNameserversConfig, TailscaleSetDnsNameserversConfig,
    TailscaleGetDnsPreferencesConfig, TailscaleSetDnsPreferencesConfig, TailscaleListDnsSearchPathsConfig,
    TailscaleSetDnsSearchPathsConfig, TailscaleListKeysConfig, TailscaleGetKeyConfig,
    TailscaleDeleteKeyConfig, TailscaleListUsersConfig, TailscaleGetUserConfig,
], Field(discriminator="operation")]


class TailscaleFullConfig(NodeConfig[TailscaleOperation, TailscaleAPITokenCredential]):
    pass


# operation -> method, path, query field mapping, JSON body field mapping.
ROUTES = {
    "list_devices": ("GET", "/tailnet/{tailnet}/devices", {"fields": "fields"}, {}),
    "get_device": ("GET", "/device/{device_id}", {"fields": "fields"}, {}),
    "delete_device": ("DELETE", "/device/{device_id}", {}, {}),
    "expire_device_key": ("POST", "/device/{device_id}/expire", {}, {}),
    "list_device_routes": ("GET", "/device/{device_id}/routes", {}, {}),
    "set_device_routes": ("POST", "/device/{device_id}/routes", {}, {"routes": "routes"}),
    "authorize_device": ("POST", "/device/{device_id}/authorized", {}, {"authorized": "authorized"}),
    "set_device_name": ("POST", "/device/{device_id}/name", {}, {"name": "name"}),
    "set_device_tags": ("POST", "/device/{device_id}/tags", {}, {"tags": "tags"}),
    "update_device_key": ("POST", "/device/{device_id}/key", {}, {"key_expiry_disabled": "keyExpiryDisabled"}),
    "list_dns_nameservers": ("GET", "/tailnet/{tailnet}/dns/nameservers", {}, {}),
    "set_dns_nameservers": ("POST", "/tailnet/{tailnet}/dns/nameservers", {}, {"dns": "dns"}),
    "get_dns_preferences": ("GET", "/tailnet/{tailnet}/dns/preferences", {}, {}),
    "set_dns_preferences": ("POST", "/tailnet/{tailnet}/dns/preferences", {}, {"magic_dns": "magicDNS"}),
    "list_dns_search_paths": ("GET", "/tailnet/{tailnet}/dns/searchpaths", {}, {}),
    "set_dns_search_paths": ("POST", "/tailnet/{tailnet}/dns/searchpaths", {}, {"search_paths": "searchPaths"}),
    "list_keys": ("GET", "/tailnet/{tailnet}/keys", {"all_keys": "all"}, {}),
    "get_key": ("GET", "/tailnet/{tailnet}/keys/{key_id}", {}, {}),
    "delete_key": ("DELETE", "/tailnet/{tailnet}/keys/{key_id}", {}, {}),
    "list_users": ("GET", "/tailnet/{tailnet}/users", {"user_type": "type", "role": "role"}, {}),
    "get_user": ("GET", "/users/{user_id}", {}, {}),
}
NO_CONTENT = {"delete_device", "expire_device_key", "authorize_device", "set_device_name", "set_device_tags", "update_device_key", "delete_key"}
LISTS = {"list_devices": "devices", "list_keys": "keys", "list_users": "users"}


def _redact(value, token):
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items() if k.lower() not in {"key", "api_token", "access_token", "authorization", "secret"}}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    return value


class TailscaleNode(WorkflowNode):
    integration_type = "automation-tailscale"
    connection_evidence = ConnectionEvidence(noun="tailnet devices", operation="list_devices", label_keys=("name", "hostname", "nodeId", "id"))

    @classmethod
    def get_config_model(cls):
        return TailscaleFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Tailscale API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, path, query_map, body_map = ROUTES[op.operation]
        fields = op.model_dump()
        for name in ("tailnet", "device_id", "key_id", "user_id"):
            if name in fields:
                path = path.replace("{" + name + "}", quote(fields[name], safe=""))
        params = {wire: str(fields[name]).lower() if isinstance(fields[name], bool) else fields[name]
                  for name, wire in query_map.items()}
        body = {wire: fields[name] for name, wire in body_map.items()}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    **({"json": body} if body_map else {}))
        except httpx.RequestError:
            return {"status": "error", "error": "Tailscale request could not be completed; inspect the tailnet before retrying a write", "write_outcome": "unverified" if method != "GET" else None}
        if response.status_code != 200:
            message = "Tailscale request failed"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"].replace(token, "[redacted]")[:2000]
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": message,
                    "write_outcome": "unverified" if method != "GET" else None}
        if op.operation in NO_CONTENT:
            return {"status": "success", "http_status": 200, "acknowledged": True, "state_verified": False}
        try:
            result = response.json()
        except ValueError:
            return {"status": "error", "error": "Tailscale returned an invalid JSON response"}
        if not isinstance(result, dict) or any(k in result for k in ("error", "errors", "message")):
            return {"status": "error", "error": "Tailscale returned an unexpected response"}
        result = _redact(result, token)
        output = {"status": "success", "http_status": 200, "data": result}
        if op.operation in LISTS:
            items = result.get(LISTS[op.operation])
            if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
                return {"status": "error", "error": "Tailscale returned an invalid list response"}
            output.update(items=items, complete=True)
        if method != "GET":
            output.update(acknowledged=True, state_verified=False)
        return output
