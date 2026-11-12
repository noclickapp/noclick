"""Logo.dev v2 API: one fixed-contract request per operation.

Contract: https://www.logo.dev/docs/openapi.json (2.0.0).
Brand reads may create subscriptions unless nosubscribe is set. Image reads
return signed download URLs and expiry metadata, never image bytes.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.logo.dev"
CREDENTIAL_TYPE = "logo_dev_api_key"


class LogoDevCredential(BaseModel):
    model_config = ConfigDict(title="Logo Dev API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://www.logo.dev/dashboard",
        "x-credential-instructions": "Copy your secret API key (sk_) from the Logo.dev dashboard. Use a secret key, not the publishable CDN key or transaction beta key. NoClick checks your account plan and credit balance with a free account read. Paid plans and owner/admin access are required for some webhook operations; flagging requires Pro or above.",
    })
    credential_type: Literal["logo_dev_api_key"] = Field("logo_dev_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Secret API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="Secret API key")
        if any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste the secret key without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Lookup(_Input):
    domain: str | None = Field(None, min_length=1, description="Company domain, such as stripe.com. Send exactly one identifier.")
    ticker: str | None = Field(None, min_length=1, description="Stock/ETF ticker; exchange suffixes such as 7203.T are supported.")
    isin: str | None = Field(None, min_length=1)
    crypto: str | None = Field(None, min_length=1, description="Crypto symbol, such as BTC.")
    name: str | None = Field(None, min_length=1, description="Brand name resolved to its top search match.")

    @model_validator(mode="after")
    def one_identifier(self):
        if sum(getattr(self, k) is not None for k in ("domain", "ticker", "isin", "crypto", "name")) != 1:
            raise ValueError("Supply exactly one of domain, ticker, isin, crypto or name")
        return self


class GetBrand(_Lookup):
    operation: Literal["get_brand"] = Field("get_brand", title="Look Up Brand", json_schema_extra={"ui:hidden": True})
    nosubscribe: Literal["true"] | None = Field(None, description="Set true to skip automatic subscription. Brand reads cost API credits when ready.")


class _BrandId(_Input):
    brand_id: str = Field(..., min_length=1, pattern=r"^brand_[A-Za-z0-9]+$", description="Stable data.id from a brand response.")


class GetBrandById(_BrandId):
    operation: Literal["get_brand_by_id"] = Field("get_brand_by_id", title="Get Brand by ID", json_schema_extra={"ui:hidden": True})
    nosubscribe: Literal["true"] | None = Field(None, description="Set true to skip automatic subscription.")


class GetBrandLogo(_Lookup):
    operation: Literal["get_brand_logo"] = Field("get_brand_logo", title="Get Brand Logo", description="Returns JSON with a temporary image URL; costs API credits.", json_schema_extra={"ui:hidden": True})


class GetBrandmark(_Lookup):
    operation: Literal["get_brandmark"] = Field("get_brandmark", title="Get Brandmark", description="Returns the wide logo lockup as a temporary image URL; costs API credits.", json_schema_extra={"ui:hidden": True})


class SearchBrands(_Input):
    operation: Literal["search_brands"] = Field("search_brands", title="Search Brands", description="Each search costs API credits.", json_schema_extra={"ui:hidden": True})
    q: str = Field(..., min_length=1, title="Search query")
    method: Literal["match", "typeahead"] = "match"
    limit: int = Field(10, ge=1, le=25)


class GetSubscription(_BrandId):
    operation: Literal["get_subscription"] = Field("get_subscription", title="Get Brand Subscription", json_schema_extra={"ui:hidden": True})


class SubscribeBrand(_BrandId):
    operation: Literal["subscribe_brand"] = Field("subscribe_brand", title="Subscribe to Brand", description="Paid plan. Enables brand.updated events; safe to repeat.", json_schema_extra={"ui:hidden": True})


class UnsubscribeBrand(_BrandId):
    operation: Literal["unsubscribe_brand"] = Field("unsubscribe_brand", title="Unsubscribe from Brand", description="Paid plan. Stops brand.updated events for this brand.", json_schema_extra={"ui:hidden": True})


class _WebhookFields(_Input):
    url: str | None = Field(None, description="HTTPS delivery URL.")
    description: str | None = None
    filter_types: list[Literal["brand.updated", "brand.indexed"]] | None = Field(None, description="An empty list receives all event types.")
    disabled: bool | None = None

    @field_validator("url")
    @classmethod
    def endpoint_url(cls, value):
        if value is not None:
            from urllib.parse import urlsplit
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Supply an HTTPS delivery URL without embedded credentials")
        return value


class CreateWebhookEndpoint(_WebhookFields):
    operation: Literal["create_webhook_endpoint"] = Field("create_webhook_endpoint", title="Create Webhook Endpoint", description="Paid plan and owner/admin role. Registers a URL for event deliveries.", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, description="HTTPS delivery URL.")


class ListWebhookEndpoints(_Input):
    operation: Literal["list_webhook_endpoints"] = Field("list_webhook_endpoints", title="List Webhook Endpoints", description="Paid plan. Returns all team endpoints; not paginated.", json_schema_extra={"ui:hidden": True})


class _EndpointId(_Input):
    endpoint_id: str = Field(..., min_length=1, pattern=r"^ep_[A-Za-z0-9]+$", description="Webhook endpoint ID.")


class GetWebhookEndpoint(_EndpointId):
    operation: Literal["get_webhook_endpoint"] = Field("get_webhook_endpoint", title="Get Webhook Endpoint", description="Requires a paid plan.", json_schema_extra={"ui:hidden": True})


class UpdateWebhookEndpoint(_EndpointId, _WebhookFields):
    operation: Literal["update_webhook_endpoint"] = Field("update_webhook_endpoint", title="Update Webhook Endpoint", description="Paid plan and owner/admin role. Omitted fields retain their current value.", json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def has_changes(self):
        if not any(getattr(self, k) is not None for k in ("url", "description", "filter_types", "disabled")):
            raise ValueError("Supply at least one endpoint field to update")
        return self


class DeleteWebhookEndpoint(_EndpointId):
    operation: Literal["delete_webhook_endpoint"] = Field("delete_webhook_endpoint", title="Delete Webhook Endpoint", description="Paid plan and owner/admin role. Permanently stops deliveries to this endpoint.", json_schema_extra={"ui:hidden": True})


class GetWebhookSecret(_EndpointId):
    operation: Literal["get_webhook_secret"] = Field("get_webhook_secret", title="Get Webhook Signing Secret", description="Paid plan. Returns sensitive signing material; protect workflow outputs.", json_schema_extra={"ui:hidden": True})


class RotateWebhookSecret(_EndpointId):
    operation: Literal["rotate_webhook_secret"] = Field("rotate_webhook_secret", title="Rotate Webhook Signing Secret", description="Paid plan and owner/admin role. Replaces the secret; update your verification code with the returned key.", json_schema_extra={"ui:hidden": True})


class GetAccount(_Input):
    operation: Literal["get_account"] = Field("get_account", title="Get Account and Credits", description="Returns plan and credit balances. Not billed.", json_schema_extra={"ui:hidden": True})


class FlagDomains(_Input):
    operation: Literal["flag_domains"] = Field("flag_domains", title="Flag Domains for Review", description="Pro plan or above. Submits corrections for manual review; does not immediately change brand data.", json_schema_extra={"ui:hidden": True})
    domains: list[str] = Field(..., min_length=1, max_length=100)
    reason: Literal["incorrect_logo", "incorrect_brand", "outdated_data", "other"]
    comment: str | None = None


# Logo.dev's own MCP server: agents get its tools through a person's Logo.dev sign-in.
LogoDevMcpCredential = mcp_credential("logo_dev", "https://mcp.logo.dev/mcp", app="Logo.dev")


Operation = Annotated[Union[GetBrand, GetBrandById, GetBrandLogo, GetBrandmark, SearchBrands,
    GetSubscription, SubscribeBrand, UnsubscribeBrand, CreateWebhookEndpoint, ListWebhookEndpoints,
    GetWebhookEndpoint, UpdateWebhookEndpoint, DeleteWebhookEndpoint, GetWebhookSecret,
    RotateWebhookSecret, GetAccount, FlagDomains], Field(discriminator="operation")]


class LogoDevConfig(NodeConfig[Operation, Union[LogoDevCredential, LogoDevMcpCredential]]):
    pass


# Each entry is exactly one published OpenAPI operation.
ROUTES = {
    "get_brand": ("GET", "/v2/brands"),
    "get_brand_by_id": ("GET", "/v2/brands/{brand_id}"),
    "get_brand_logo": ("GET", "/v2/brands/logo"),
    "get_brandmark": ("GET", "/v2/brands/brandmark"),
    "search_brands": ("GET", "/v2/search"),
    "get_subscription": ("GET", "/v2/brands/{brand_id}/subscription"),
    "subscribe_brand": ("PUT", "/v2/brands/{brand_id}/subscription"),
    "unsubscribe_brand": ("DELETE", "/v2/brands/{brand_id}/subscription"),
    "create_webhook_endpoint": ("POST", "/v2/webhook_endpoints"),
    "list_webhook_endpoints": ("GET", "/v2/webhook_endpoints"),
    "get_webhook_endpoint": ("GET", "/v2/webhook_endpoints/{endpoint_id}"),
    "update_webhook_endpoint": ("PATCH", "/v2/webhook_endpoints/{endpoint_id}"),
    "delete_webhook_endpoint": ("DELETE", "/v2/webhook_endpoints/{endpoint_id}"),
    "get_webhook_secret": ("GET", "/v2/webhook_endpoints/{endpoint_id}/secret"),
    "rotate_webhook_secret": ("POST", "/v2/webhook_endpoints/{endpoint_id}/secret"),
    "get_account": ("GET", "/v2/account"),
    "flag_domains": ("POST", "/v2/flag"),
}


class LogoDevNode(WorkflowNode):
    integration_type = "automation-logo-dev"
    credential_provider_labels = {"logo_dev": "Logo.dev Account"}
    connection_evidence = ConnectionEvidence(operation="get_account", noun="Logo Dev account plan and credits")

    @classmethod
    def get_config_model(cls):
        return LogoDevConfig

    async def execute(self, inputs):
        config = self.config
        if not config.credentials:
            raise ValueError("Connect a Logo Dev secret API key")
        op = config.config
        method, route = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for key in ("brand_id", "endpoint_id"):
            if key in values:
                route = route.replace("{" + key + "}", values.pop(key))
        kwargs = {"params": values} if method == "GET" else {"json": values} if values else {}
        key = config.credentials.api_key
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + route, headers={
                "Authorization": "Bearer " + key, "Accept": "application/json",
            }, **kwargs)
        if response.status_code >= 400:
            # Preserve the provider's message for connection rejection evidence.
            try:
                payload = response.json()
                error = payload.get("error", {}) if isinstance(payload, dict) else {}
                message = error.get("message") if isinstance(error, dict) else error
                message = message or payload.get("message") if isinstance(payload, dict) else None
            except ValueError:
                message = None
            message = message if isinstance(message, str) else "Logo Dev request failed"
            raise ValueError(f"Logo Dev HTTP {response.status_code}: {message.replace(key, '[redacted]')}")
        expected = {204} if method == "DELETE" else {200, 201} if op.operation == "subscribe_brand" else {201} if op.operation == "create_webhook_endpoint" else {200, 202} if op.operation in {"get_brand", "get_brand_by_id", "get_brand_logo", "get_brandmark"} else {200}
        if response.status_code not in expected:
            raise ValueError(f"Unexpected Logo Dev HTTP {response.status_code}")
        if response.status_code == 204:
            return {"status": "success", "http_status": 204, "data": None}
        if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise ValueError("Expected JSON from Logo Dev")
        body = response.json()
        if not isinstance(body, dict) or "error" in body or "data" not in body or not isinstance(body.get("metadata"), dict):
            raise ValueError("Unexpected Logo Dev response envelope")
        if key in str(body):
            raise ValueError("Logo Dev unexpectedly returned the API credential")
        if response.status_code == 202:
            return {**body, "status": "pending", "http_status": 202}
        return {**body, "status": "success", "http_status": response.status_code}
