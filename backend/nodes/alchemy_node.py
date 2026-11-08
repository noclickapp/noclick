"""Alchemy Admin API v1 app management using a user-supplied access key.

Contract: https://dev-docs.alchemy.com/alchemy/rest/admin-api.json (1.0.0).
Each operation makes one request; list_apps exposes the provider's next cursor.
App API keys and key-bearing RPC URLs are omitted from workflow output.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://admin-api.alchemy.com"
PRODUCTS = Literal[
    "node-api", "nft-api", "swaps-api", "block-timestamp-api", "token-api",
    "transfers-api", "bundler-api", "debug-api", "embedded-accounts",
    "gas-manager-api", "trace-api", "prices-api", "transaction-simulation-api",
    "transaction-receipts-api", "user-operations-api", "smart-websockets", "webhooks", "grpc",
]


class AlchemyAccessKeyCredential(BaseModel):
    model_config = ConfigDict(title="Alchemy Access Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.alchemy.com/settings/security",
            "x-credential-instructions": "Create an access key in Alchemy Dashboard → Security. Enable App Management read permissions for reads, or read and write for changes. Paste the access key here, without Bearer. An app API key cannot authenticate the Admin API. See https://www.alchemy.com/docs/reference/admin-api/overview.",
        })
    credential_type: Literal["alchemy_access_key"] = Field("alchemy_access_key", json_schema_extra={"ui:hidden": True})
    access_key: str = Field(..., min_length=1, max_length=4096, title="Access key", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="Access key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the access key, without Bearer")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListChains(_Input):
    """List supported chain network IDs for app configuration."""
    operation: Literal["list_chains"] = "list_chains"


class ListApps(_Input):
    """List this account's apps, one page at a time; pass back next_cursor."""
    operation: Literal["list_apps"] = "list_apps"
    cursor: str | None = Field(None, max_length=8192, description="Opaque next_cursor from the previous page.")
    limit: int = Field(25, ge=1, le=25)


class _AppInput(_Input):
    app_id: str = Field(..., min_length=1, max_length=256, description="Alchemy app ID from list_apps; not an API key.")

    @field_validator("app_id")
    @classmethod
    def valid_id(cls, value):
        if any(c.isspace() for c in value) or any(c in value for c in "/\\?#%") or value in {".", ".."}:
            raise ValueError("Use a single Alchemy app ID")
        return value


class GetApp(_AppInput):
    """Retrieve an app's metadata and allowlists; API keys and RPC URLs are omitted."""
    operation: Literal["get_app"] = "get_app"


class CreateApp(_Input):
    """Create an app with network IDs returned by list_chains."""
    operation: Literal["create_app"] = "create_app"
    name: str = Field(..., min_length=1, max_length=1000)
    description: str | None = Field(None, max_length=10000)
    network_allowlist: list[str] = Field(..., max_length=1000, description="Network IDs, for example ETH_MAINNET. Replaces the entire network selection.")
    products: list[PRODUCTS] | None = Field(None, max_length=100)


class UpdateApp(_AppInput):
    """Change an app's name or description without replacing its allowlists."""
    operation: Literal["update_app"] = "update_app"
    name: str | None = Field(None, min_length=1, max_length=1000)
    description: str | None = Field(None, max_length=10000)

    @model_validator(mode="after")
    def changes(self):
        if self.name is None and self.description is None:
            raise ValueError("Provide a name or description to update")
        return self


class DeleteApp(_AppInput):
    """Permanently delete the specified app, invalidating its API access."""
    operation: Literal["delete_app"] = "delete_app"


class UpdateNetworkAllowlist(_AppInput):
    """Replace all enabled networks; an empty list removes all networks."""
    operation: Literal["update_network_allowlist"] = "update_network_allowlist"
    network_allowlist: list[str] = Field(..., max_length=1000)


class AllowlistEntry(_Input):
    value: str = Field(..., min_length=1, max_length=4096)
    name: str | None = Field(None, max_length=1000)


class UpdateAddressAllowlist(_AppInput):
    """Replace the address allowlist; an empty list clears restrictions."""
    operation: Literal["update_address_allowlist"] = "update_address_allowlist"
    address_allowlist: list[AllowlistEntry] = Field(..., max_length=1000)


class UpdateOriginAllowlist(_AppInput):
    """Replace the origin allowlist; an empty list clears restrictions."""
    operation: Literal["update_origin_allowlist"] = "update_origin_allowlist"
    origin_allowlist: list[AllowlistEntry] = Field(..., max_length=1000)


class UpdateIpAllowlist(_AppInput):
    """Replace the IP/CIDR allowlist; an empty list clears restrictions."""
    operation: Literal["update_ip_allowlist"] = "update_ip_allowlist"
    ip_allowlist: list[AllowlistEntry] = Field(..., max_length=1000)


AlchemyConfig = Annotated[Union[
    ListChains, ListApps, GetApp, CreateApp, UpdateApp, DeleteApp,
    UpdateNetworkAllowlist, UpdateAddressAllowlist, UpdateOriginAllowlist, UpdateIpAllowlist,
], Field(discriminator="operation")]


class AlchemyFullConfig(NodeConfig[AlchemyConfig, AlchemyAccessKeyCredential]):
    pass


ROUTES = {
    "list_chains": ("GET", "/v1/chains"),
    "list_apps": ("GET", "/v1/apps"),
    "get_app": ("GET", "/v1/apps/{id}"),
    "create_app": ("POST", "/v1/apps"),
    "update_app": ("PATCH", "/v1/apps/{id}"),
    "delete_app": ("DELETE", "/v1/apps/{id}"),
    "update_network_allowlist": ("PUT", "/v1/apps/{id}/networks"),
    "update_address_allowlist": ("PUT", "/v1/apps/{id}/address-allowlist"),
    "update_origin_allowlist": ("PUT", "/v1/apps/{id}/origin-allowlist"),
    "update_ip_allowlist": ("PUT", "/v1/apps/{id}/ip-allowlist"),
}
BODY_NAMES = {
    "network_allowlist": "networkAllowlist", "address_allowlist": "addressAllowlist",
    "origin_allowlist": "originAllowlist", "ip_allowlist": "ipAllowlist",
}


def _app(data):
    if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not isinstance(data.get("name"), str):
        raise ValueError("Alchemy returned invalid app metadata")
    # App responses contain live API keys, including within RPC endpoints.
    result = {k: data[k] for k in ("id", "name", "description", "products", "addressAllowlist", "originAllowlist", "ipAllowlist", "createdAt") if k in data}
    networks = data.get("chainNetworks", [])
    if not isinstance(networks, list) or any(not isinstance(n, dict) for n in networks):
        raise ValueError("Alchemy returned invalid app networks")
    result["chainNetworks"] = [{k: n[k] for k in ("id", "name", "networkChainId") if k in n} for n in networks]
    return result


class AlchemyNode(WorkflowNode):
    integration_type = "automation-alchemy"
    connection_evidence = ConnectionEvidence(noun="Alchemy apps", operation="list_apps")

    @classmethod
    def get_config_model(cls):
        return AlchemyFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an Alchemy access key")
        method, route = ROUTES[config.operation]
        if "{id}" in route:
            route = route.replace("{id}", quote(config.app_id, safe=""))
        params = config.model_dump(exclude={"operation"}, exclude_none=True) if isinstance(config, ListApps) else None
        body = None
        if method in {"POST", "PATCH", "PUT"}:
            body = {BODY_NAMES.get(k, k): v for k, v in config.model_dump(exclude={"operation", "app_id"}, exclude_none=True).items()}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route, params=params,
                    headers={"Authorization": "Bearer " + credential.access_key, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
            if response.status_code != (201 if isinstance(config, CreateApp) else 200):
                # Avoid returning an exception with response content, app secrets or headers.
                message = "Alchemy Admin API request failed; check access key App Management permissions and app ID"
                if response.status_code in {401, 403}:
                    try:
                        rejection = response.json().get("error", {}).get("message")
                        if isinstance(rejection, str) and 0 < len(rejection) <= 1000:
                            message = rejection.replace(credential.access_key, "[redacted]")
                    except (ValueError, AttributeError):
                        pass
                return {"status": "error", "http_status": response.status_code, "error": message}
            if len(response.content) > 5_000_000:
                raise ValueError("Alchemy response exceeded the supported size")
            envelope = response.json()
            if not isinstance(envelope, dict) or "error" in envelope or "errors" in envelope or "data" not in envelope:
                raise ValueError("Alchemy returned an invalid response envelope")
            data = envelope["data"]
            result = {"status": "success", "operation": config.operation, "http_status": response.status_code}
            if isinstance(config, ListApps):
                if not isinstance(data, dict) or not isinstance(data.get("apps"), list) or type(data.get("totalCount")) is not int:
                    raise ValueError("Alchemy returned invalid app pagination")
                cursor = data.get("cursor")
                if cursor is not None and not isinstance(cursor, str):
                    raise ValueError("Alchemy returned an invalid cursor")
                if cursor and cursor == config.cursor:
                    raise ValueError("Alchemy returned a nonadvancing cursor")
                return {**result, "items": [_app(a) for a in data["apps"]], "total_count": data["totalCount"], "next_cursor": cursor or None, "has_more": bool(cursor)}
            if isinstance(config, ListChains):
                if not isinstance(data, list) or any(not isinstance(n, dict) or not isinstance(n.get("id"), str) for n in data):
                    raise ValueError("Alchemy returned invalid chains")
                return {**result, "items": data}
            if isinstance(config, DeleteApp):
                if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not isinstance(data.get("message"), str):
                    raise ValueError("Alchemy did not acknowledge app deletion")
                return {**result, "data": {"id": data["id"], "message": data["message"]}}
            return {**result, "data": _app(data)}
        except (httpx.HTTPError, ValueError):
            return {"status": "error", "error": "Alchemy request could not be confirmed; inspect the app before retrying a write"}
