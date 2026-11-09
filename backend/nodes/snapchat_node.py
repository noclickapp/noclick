"""Snap Conversions API v3: web conversions and asset-scoped test diagnostics.

Contract: https://github.com/Snapchat/business-sdk-v3-java/blob/main/api/openapi.yaml
Token setup: https://developers.snap.com/marketing-api/Conversions-API/GetStarted
Presets below are event types, each making exactly one sendEvent request. No
advertising-management, private messages, account login or token refresh API is used.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE = "https://tr.snapchat.com"
FAMILY = "snapchat_capi_token"
PRESETS = {
    "send_purchase": "PURCHASE",
    "send_add_cart": "ADD_CART",
    "send_start_checkout": "START_CHECKOUT",
    "send_view_content": "VIEW_CONTENT",
    "send_sign_up": "SIGN_UP",
    "send_search": "SEARCH",
    "send_subscribe": "SUBSCRIBE",
    "send_add_to_wishlist": "ADD_TO_WISHLIST",
}


class SnapchatCAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Snapchat Conversions API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://ads.snapchat.com/",
            "x-credential-instructions": "In Ads Manager, open Business Details → Conversions API Tokens and generate a token as an Organization Admin. Paste the token and a website Pixel ID belonging to that organization. NoClick reads that asset's validation stats to check access. Tokens are long lived; replace a revoked token manually.",
            "x-help-url": "https://developers.snap.com/marketing-api/Conversions-API/GetStarted",
        })
    credential_type: Literal["snapchat_capi_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Conversions API token", min_length=1,
        json_schema_extra={"ui:widget": "password"})
    asset_id: str = Field(..., title="Pixel ID", min_length=1,
        description="A website pixel owned by the organization that generated the token.")

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Conversions API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without a Bearer prefix or whitespace")
        return value

    @field_validator("asset_id")
    @classmethod
    def asset(cls, value):
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
            raise ValueError("Paste a single Pixel ID")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _WebEvent(_Input):
    event_time: int = Field(..., gt=0, description="Unix timestamp in seconds or milliseconds of the real conversion, at most seven days old.")
    event_id: str = Field(..., min_length=1, description="Stable unique conversion ID. Reuse it when retrying and for Pixel deduplication.")
    event_source_url: str = Field(..., description="HTTP(S) page URL where the web conversion happened.")
    email_sha256: str = Field(..., description="SHA256 hex digest of the email after trimming and lowercasing. Never paste an unhashed email.")
    sc_click_id: str | None = Field(None, description="Optional Snap click ID from the landing page.")
    sc_cookie1: str | None = Field(None, description="Optional _scid first-party cookie.")
    currency: str | None = Field(None, description="ISO 4217 currency code; required for purchases.")
    value: float | None = Field(None, ge=0, allow_inf_nan=False, description="Conversion value; required for purchases.")
    order_id: str | None = None
    content_ids: list[str] | None = None
    search_string: str | None = None

    @field_validator("email_sha256")
    @classmethod
    def email_hash(cls, value):
        if not re.fullmatch(r"[a-fA-F0-9]{64}", value):
            raise ValueError("Use a 64-character SHA256 email digest")
        return value.lower()

    @field_validator("event_source_url")
    @classmethod
    def source_url(cls, value):
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Use the HTTP(S) URL of the conversion page")
        return value

    @field_validator("currency")
    @classmethod
    def currency_code(cls, value):
        if value is not None and not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("Use an uppercase three-letter currency code")
        return value


class SendPurchase(_WebEvent):
    """Report a website purchase with value, currency and a deduplication ID."""
    operation: Literal["send_purchase"] = "send_purchase"
    currency: str = Field(..., description="ISO 4217 currency code.")
    value: float = Field(..., ge=0, allow_inf_nan=False)


class SendAddCart(_WebEvent):
    """Report a website add-to-cart conversion."""
    operation: Literal["send_add_cart"] = "send_add_cart"


class SendStartCheckout(_WebEvent):
    """Report a website checkout start."""
    operation: Literal["send_start_checkout"] = "send_start_checkout"


class SendViewContent(_WebEvent):
    """Report a website product or content view."""
    operation: Literal["send_view_content"] = "send_view_content"


class SendSignUp(_WebEvent):
    """Report a completed website signup."""
    operation: Literal["send_sign_up"] = "send_sign_up"


class SendSearch(_WebEvent):
    """Report a website search with optional search text."""
    operation: Literal["send_search"] = "send_search"


class SendSubscribe(_WebEvent):
    """Report a website subscription conversion."""
    operation: Literal["send_subscribe"] = "send_subscribe"


class SendAddToWishlist(_WebEvent):
    """Report a website wishlist addition."""
    operation: Literal["send_add_to_wishlist"] = "send_add_to_wishlist"


def _events(value):
    try:
        events = json.loads(value)
    except (ValueError, TypeError):
        raise ValueError("Events must be a JSON array") from None
    if not isinstance(events, list) or not 1 <= len(events) <= 2000:
        raise ValueError("Provide 1 to 2000 conversion events")
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("Each event must be an object")
        for field in ("event_name", "event_id", "event_source_url"):
            if not isinstance(event.get(field), str) or not event[field].strip():
                raise ValueError(f"Each event needs {field}")
        if event.get("action_source") != "WEB":
            raise ValueError("This integration accepts WEB events; use a Pixel ID")
        if type(event.get("event_time")) is not int or event["event_time"] <= 0:
            raise ValueError("Each event needs an integer event_time")
        _WebEvent.source_url(event["event_source_url"])
        user = event.get("user_data")
        if not isinstance(user, dict) or not isinstance(user.get("em"), list) or not user["em"]:
            raise ValueError("Each event needs user_data.em with SHA256 email digests")
        for digest in user["em"]:
            if not isinstance(digest, str):
                raise ValueError("Email digests must be strings")
            _WebEvent.email_hash(digest)
        if event["event_name"].upper() == "PURCHASE":
            custom = event.get("custom_data", {})
            if not isinstance(custom, dict) or not isinstance(custom.get("currency"), str) or type(custom.get("value")) not in (int, float):
                raise ValueError("Purchase events need custom_data.currency and numeric custom_data.value")
            _WebEvent.currency_code(custom["currency"])
    return events


class _Batch(_Input):
    events_json: str = Field(..., description="JSON array of WEB conversion events with event_id and hashed user_data.em. Up to 2000. Values are sent as supplied; normalize and hash all personal identifiers first.",
        json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})

    @field_validator("events_json")
    @classmethod
    def validate_events(cls, value):
        _events(value)
        return value


class SendEvents(_Batch):
    """Send a batch of website conversions in one sendEvent request."""
    operation: Literal["send_events"] = "send_events"
    test_event_code: str | None = Field(None, description="Optional Events Manager test code; routes events to debug/test processing.")


class ValidateEvents(_Batch):
    """Send website events to the test validation endpoint, without live conversions."""
    operation: Literal["validate_events"] = "validate_events"


class GetValidationLogs(_Input):
    """Read the asset's test event metadata from the last 24 hours."""
    operation: Literal["get_validation_logs"] = "get_validation_logs"


class GetValidationStats(_Input):
    """Read live and test event counts and latest timestamps for this asset."""
    operation: Literal["get_validation_stats"] = "get_validation_stats"


SnapchatConfig = Annotated[Union[
    SendPurchase, SendAddCart, SendStartCheckout, SendViewContent, SendSignUp,
    SendSearch, SendSubscribe, SendAddToWishlist, SendEvents, ValidateEvents,
    GetValidationLogs, GetValidationStats,
], Field(discriminator="operation")]


class SnapchatFullConfig(NodeConfig[SnapchatConfig, SnapchatCAPITokenCredential]):
    pass


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items() if key not in {"access_token", "authorization"}}
    return value


class SnapchatNode(WorkflowNode):
    integration_type = "automation-snapchat"
    connection_evidence = ConnectionEvidence(operation="get_validation_stats", noun="Snapchat asset event statistics")

    @classmethod
    def get_config_model(cls):
        return SnapchatFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Snapchat Conversions API token and Pixel ID")
        config = self.config.config
        operation = config.operation
        path = f"/v3/{credential.asset_id}/events"
        body = None
        method = "POST"
        if operation in PRESETS:
            user = {"em": [config.email_sha256]}
            for key in ("sc_click_id", "sc_cookie1"):
                if getattr(config, key) is not None:
                    user[key] = getattr(config, key)
            event = {"event_name": PRESETS[operation], "event_time": config.event_time,
                "event_id": config.event_id, "event_source_url": config.event_source_url,
                "action_source": "WEB", "user_data": user}
            custom = {key: getattr(config, key) for key in ("currency", "value", "order_id", "content_ids", "search_string") if getattr(config, key) is not None}
            if custom:
                event["custom_data"] = custom
            body = {"data": [event]}
        elif isinstance(config, _Batch):
            body = {"data": _events(config.events_json)}
            if isinstance(config, ValidateEvents):
                path += "/validate"
            elif config.test_event_code is not None:
                body["test_event_code"] = config.test_event_code
        else:
            method = "GET"
            path += "/validate/" + ("logs" if operation == "get_validation_logs" else "stats")
        # Fixed provider host, no redirects and no automatic POST retries. The
        # provider requires its token in the query; never expose request URLs.
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    params={"access_token": credential.access_token},
                    headers={"Accept": "application/json"}, **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("Snapchat request could not be completed; inspect the asset before retrying conversions") from None
        try:
            data = response.json()
        except ValueError:
            return {"status": "error", "status_code": response.status_code, "error": "Snapchat returned a non-JSON response"}
        data = _redact(data, credential.access_token)
        expected = "SUCCESS" if method == "GET" else "VALID"
        if not 200 <= response.status_code < 300 or not isinstance(data, dict) or data.get("status") != expected:
            reason = data.get("reason") if isinstance(data, dict) else None
            return {"status": "error", "status_code": response.status_code,
                "error": reason or "Snapchat did not confirm the request", "data": data}
        return {"status": "success", "asset_id": credential.asset_id, "data": data}
