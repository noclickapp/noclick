"""DPD v2 account reads, notification verification and purchase reactivation.

Contract: https://docs.getdpd.com/openapi.yaml (version 2).
Each action performs one documented API request; no implicit writes or retries.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.getdpd.com/v2"


class Dpd2Credential(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, title="Dpd2 API Password",
        json_schema_extra={
            "x-credential-url": "https://docs.getdpd.com/api/",
            "x-credential-instructions": "Enter your DPD username and the API password from your profile in the DPD admin. Use the API password, not your account password. NoClick sends these using HTTP Basic authentication to api.getdpd.com. Connecting reads your storefronts; reactivating a purchase emails its buyer and can optionally refulfill it.",
        })
    credential_type: Literal["dpd2_api_password"] = Field("dpd2_api_password", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, max_length=512, title="Username")
    api_password: str = Field(..., min_length=1, max_length=4096, title="API password", json_schema_extra={"ui:widget": "password"})

    @field_validator("username")
    @classmethod
    def valid_username(cls, value):
        value = value.strip()
        if not value or ":" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Enter your DPD username without a colon or control characters")
        return value

    @field_validator("api_password")
    @classmethod
    def valid_password(cls, value):
        value = clean_secret(value, field_name="API password")
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API password without control characters")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Dpd2PingConfig(_Input):
    """Ping."""
    operation: Literal["ping"] = Field("ping", json_schema_extra={"ui:hidden": True})


class Dpd2VerifyNotificationConfig(_Input):
    """Verify a purchase notification."""
    operation: Literal["verify_notification"] = Field("verify_notification", json_schema_extra={"ui:hidden": True})
    verify_sign: str = Field(..., min_length=1, max_length=4096, description='The signature DPD sent with the notification.')
    notification_fields: dict[str, str] = Field(default_factory=dict, description="Every other original notification POST parameter, unchanged; verify_sign is entered separately.")

    @model_validator(mode="after")
    def signature_not_overridden(self):
        if "verify_sign" in self.notification_fields:
            raise ValueError("Enter verify_sign only in its dedicated field")
        return self


class Dpd2ListStorefrontsConfig(_Input):
    """List storefronts."""
    operation: Literal["list_storefronts"] = Field("list_storefronts", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description='Page number, 100 records per page. Request next_page until an empty NOTFOUND page. Each run reads one page.')


class Dpd2GetStorefrontConfig(_Input):
    """Get a storefront."""
    operation: Literal["get_storefront"] = Field("get_storefront", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)


class Dpd2ListProductsConfig(_Input):
    """List products."""
    operation: Literal["list_products"] = Field("list_products", json_schema_extra={"ui:hidden": True})
    storefront_id: int | None = Field(None, ge=1, description='Only products in this storefront. Defaults to all storefronts.')
    page: int = Field(1, ge=1, description='Page number, 100 records per page. Request next_page until an empty NOTFOUND page. Each run reads one page.')


class Dpd2GetProductConfig(_Input):
    """Get a product."""
    operation: Literal["get_product"] = Field("get_product", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)


class Dpd2ListPurchasesConfig(_Input):
    """List purchases."""
    operation: Literal["list_purchases"] = Field("list_purchases", json_schema_extra={"ui:hidden": True})
    status: Literal['ACT', 'PND', 'RFD', 'ERR', 'CAN', 'HLD'] | None = Field(None, min_length=1, max_length=4096)
    product_id: int | None = Field(None, ge=1)
    storefront_id: int | None = Field(None, ge=1)
    customer_id: int | None = Field(None, ge=1)
    customer_email: str | None = Field(None, min_length=1, max_length=4096, description='Customer email address. Matches the start of the address, not case sensitive.')
    customer_first_name: str | None = Field(None, min_length=1, max_length=4096, description='Matches the start of the name, not case sensitive.')
    customer_last_name: str | None = Field(None, min_length=1, max_length=4096, description='Matches the start of the name, not case sensitive.')
    date_min: str | None = Field(None, min_length=1, max_length=4096, description="Created after this date (anything PHP's `strtotime()` accepts).")
    date_max: str | None = Field(None, min_length=1, max_length=4096, description="Created before this date (anything PHP's `strtotime()` accepts).")
    total: str | None = Field(None, min_length=1, max_length=4096, description='Purchase total, compared with `total_op`.')
    total_op: Literal['eq', 'ne', 'gt', 'lt'] | None = Field(None, min_length=1, max_length=4096, description='How to compare `total`.')
    ship: bool | None = Field(None, description="Only purchases with physical goods that haven't shipped yet.")
    page: int = Field(1, ge=1, description='Page number, 100 records per page. Request next_page until an empty NOTFOUND page. Each run reads one page.')


class Dpd2GetPurchaseConfig(_Input):
    """Get a purchase."""
    operation: Literal["get_purchase"] = Field("get_purchase", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)


class Dpd2ReactivatePurchaseConfig(_Input):
    """Email an active purchase to its buyer again, optionally changing their address or refulfilling it."""
    operation: Literal["reactivate_purchase"] = Field("reactivate_purchase", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)
    buyer_email: str | None = Field(None, min_length=1, max_length=4096, description='Optional: change the purchase email address and resend to it. Leaving this blank uses the existing buyer email.')
    refulfill: bool | None = Field(None, description='Also send the purchase to its fulfillment service again. This can have external fulfillment effects.')


class Dpd2ListCustomersConfig(_Input):
    """List customers."""
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})
    email: str | None = Field(None, min_length=1, max_length=4096, description='Matches the start of the address, not case sensitive.')
    first_name: str | None = Field(None, min_length=1, max_length=4096, description='Matches the start of the name, not case sensitive.')
    last_name: str | None = Field(None, min_length=1, max_length=4096, description='Matches the start of the name, not case sensitive.')
    product_id: int | None = Field(None, ge=1, description='Only customers who bought this product.')
    receives_newsletters: bool | None = Field(None, description="Only customers who do (or don't) get your product update emails.")
    date_min: str | None = Field(None, min_length=1, max_length=4096, description="Created after this date (anything PHP's `strtotime()` accepts).")
    date_max: str | None = Field(None, min_length=1, max_length=4096, description="Created before this date (anything PHP's `strtotime()` accepts).")
    page: int = Field(1, ge=1, description='Page number, 100 records per page. Request next_page until an empty NOTFOUND page. Each run reads one page.')


class Dpd2GetCustomerConfig(_Input):
    """Get a customer."""
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)


class Dpd2ListSubscribersConfig(_Input):
    """List subscribers."""
    operation: Literal["list_subscribers"] = Field("list_subscribers", json_schema_extra={"ui:hidden": True})
    storefront_id: int = Field(..., ge=1)
    username: str | None = Field(None, min_length=1, max_length=4096, description="The subscriber's username (their email address).")
    page: int = Field(1, ge=1, description='Page number, 100 records per page. Request next_page until an empty NOTFOUND page. Each run reads one page.')


class Dpd2VerifySubscriberConfig(_Input):
    """Verify a subscriber."""
    operation: Literal["verify_subscriber"] = Field("verify_subscriber", json_schema_extra={"ui:hidden": True})
    storefront_id: int = Field(..., ge=1)
    username: str | None = Field(None, min_length=1, max_length=4096, description="The subscriber's username (their email address).")
    id: int | None = Field(None, ge=1, description='The subscriber ID. Used instead of `username` when both are given.')

    @model_validator(mode="after")
    def subscriber_selector(self):
        if self.id is None and not self.username:
            raise ValueError("Provide a subscriber ID or username")
        return self


class Dpd2GetSubscriberConfig(_Input):
    """Get a subscriber."""
    operation: Literal["get_subscriber"] = Field("get_subscriber", json_schema_extra={"ui:hidden": True})
    storefront_id: int = Field(..., ge=1)
    id: int = Field(..., ge=1)


Dpd2Operation = Annotated[Union[
    Dpd2PingConfig,
    Dpd2VerifyNotificationConfig,
    Dpd2ListStorefrontsConfig,
    Dpd2GetStorefrontConfig,
    Dpd2ListProductsConfig,
    Dpd2GetProductConfig,
    Dpd2ListPurchasesConfig,
    Dpd2GetPurchaseConfig,
    Dpd2ReactivatePurchaseConfig,
    Dpd2ListCustomersConfig,
    Dpd2GetCustomerConfig,
    Dpd2ListSubscribersConfig,
    Dpd2VerifySubscriberConfig,
    Dpd2GetSubscriberConfig
], Field(discriminator="operation")]


class Dpd2NodeConfig(NodeConfig[Dpd2Operation, Dpd2Credential]):
    pass


ROUTES = {
    "ping": ("GET", "/"),
    "verify_notification": ("POST", "/notification/verify"),
    "list_storefronts": ("GET", "/storefronts"),
    "get_storefront": ("GET", "/storefronts/{id}"),
    "list_products": ("GET", "/products"),
    "get_product": ("GET", "/products/{id}"),
    "list_purchases": ("GET", "/purchases"),
    "get_purchase": ("GET", "/purchases/{id}"),
    "reactivate_purchase": ("POST", "/purchases/{id}/reactivate"),
    "list_customers": ("GET", "/customers"),
    "get_customer": ("GET", "/customers/{id}"),
    "list_subscribers": ("GET", "/storefronts/{storefront_id}/subscribers"),
    "verify_subscriber": ("GET", "/storefronts/{storefront_id}/subscribers/verify"),
    "get_subscriber": ("GET", "/storefronts/{storefront_id}/subscribers/{id}"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    return value


class Dpd2Node(WorkflowNode):
    integration_type = "automation-dpd2"
    connection_evidence = ConnectionEvidence(noun="storefronts", operation="list_storefronts", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return Dpd2NodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Dpd2 API password")
        credential = self.config.credentials
        config = self.config.config
        action = config.operation
        method, path = ROUTES[action]
        fields = config.model_dump(exclude={"operation"}, exclude_none=True)
        for key in ("id", "storefront_id"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", str(fields.pop(key)))
        if action == "verify_notification":
            fields = {**fields.pop("notification_fields"), **fields}
        fields = {key: str(value).lower() if isinstance(value, bool) else value for key, value in fields.items()}
        output = {"operation": action}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    auth=httpx.BasicAuth(credential.username, credential.api_password),
                    headers={"Accept": "text/plain" if action in {"verify_notification", "verify_subscriber"} else "application/json"},
                    **({"params": fields} if method == "GET" else {"data": fields}))
        except httpx.TransportError:
            return {**output, "status": "unknown" if method == "POST" else "error",
                "error": "Dpd2 request did not complete; inspect the purchase before retrying" if action == "reactivate_purchase" else "Dpd2 request did not complete"}
        if response.status_code == 404 and action.startswith("list_"):
            try:
                if response.json() == {"status": "NOTFOUND"}:
                    return {**output, "status": "success", "data": [], "page": config.page, "next_page": None, "has_more": False}
            except ValueError:
                pass
        if response.status_code != 200:
            # Preserve the provider's rejection for the shared connect verdict,
            # while ensuring a response that echoes a secret cannot disclose it.
            message = _redact(response.text, credential.api_password)[:2000]
            return {**output, "status": "error", "http_status": response.status_code,
                "status_code": response.status_code,
                "error": message or "Dpd2 returned HTTP " + str(response.status_code)}
        try:
            if action in {"verify_notification", "verify_subscriber"}:
                data = response.text.strip()
                allowed = {"VERIFIED", "INVALID"} if action == "verify_notification" else {"NEW", "TRIAL", "ACTIVE", "CANCELED", "CLOSED", "PAST_DUE"}
                if data not in allowed:
                    raise ValueError("Unexpected Dpd2 verification response")
            else:
                data = response.json()
                if action.startswith("list_"):
                    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data) or len(data) > 100:
                        raise ValueError("Unexpected Dpd2 collection response")
                elif not isinstance(data, dict):
                    raise ValueError("Unexpected Dpd2 object response")
                if action == "ping" and data.get("status") != "SUCCESS":
                    raise ValueError("Unexpected Dpd2 ping response")
                if action == "reactivate_purchase" and data.get("status") != "OK":
                    raise ValueError("Unexpected Dpd2 reactivation response")
        except ValueError:
            return {**output, "status": "unknown" if action == "reactivate_purchase" else "error",
                "error": "Dpd2 returned an unexpected response; inspect the purchase before retrying" if action == "reactivate_purchase" else "Dpd2 returned an unexpected response"}
        output.update(status="success", data=_redact(data, credential.api_password))
        if action.startswith("list_"):
            output.update(page=config.page, has_more=len(data) == 100, next_page=config.page + 1 if len(data) == 100 else None)
        if action == "reactivate_purchase":
            output.update(reactivation_acknowledged=True, email_delivery_verified=False, fulfillment_verified=False)
        return output
