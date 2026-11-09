"""Universe ticketing REST actions from the provider's published REST/OAuth contracts.

Each action makes one API call. Guestlist reads return one explicit offset page;
write acknowledgements do not imply redemption, delivery or readback verification.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.oauth_refresh import ensure_fresh_oauth_token, freshen_oauth_credential
from nodes.oauth.universe_oauth import OAUTH_PROVIDER
from nodes.scopes.universe import UNIVERSE_SCOPES
from utils.ssrf import guarded_async_client


class UniverseOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Universe OAuth", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "universe",
        "x-oauth-scopes": sorted(UNIVERSE_SCOPES.declared_scopes()),
        "x-credential-url": "https://www.universe.com/oauth/applications",
        "x-credential-instructions": "Connect Universe, or paste an existing OAuth access token obtained through Universe's documented client credentials or authorization code flow. Optional refresh token and expiry enable renewal using the configured Universe OAuth application. An access token alone works until it expires.",
    })
    credential_type: Literal["universe_oauth"] = Field("universe_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Access token", json_schema_extra={"ui:widget": "password"})
    refresh_token: str | None = Field(None, title="Refresh token", json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = Field(None, title="Token expiry", description="ISO 8601 expiry timestamp, if known.")
    scope: str | None = Field(None, title="Granted scopes")

    @field_validator("access_token", "refresh_token")
    @classmethod
    def secret(cls, value):
        if value is None:
            return value
        value = clean_secret(value, field_name="token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CurrentUser(_Input):
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})


class TokenInfo(_Input):
    operation: Literal["get_token_info"] = Field("get_token_info", json_schema_extra={"ui:hidden": True})


class Listings(_Input):
    operation: Literal["list_listings"] = Field("list_listings", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, description="User ID returned by Get current user.")


class Guestlists(_Input):
    operation: Literal["list_guestlists"] = Field("list_guestlists", json_schema_extra={"ui:hidden": True})
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)
    since: str | None = Field(None, description="ISO 8601 timestamp: include tickets created or updated after this time.")
    listing_id: str | None = Field(None, description="Optional listing filter.")


class EventGuestlist(Guestlists):
    operation: Literal["list_event_guestlist"] = Field("list_event_guestlist", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., min_length=1, description="Restrict this page to one event.")


class CheckIn(_Input):
    operation: Literal["check_in"] = Field("check_in", json_schema_extra={"ui:hidden": True})
    cost_item_id: str = Field(..., min_length=1, description="Guestlist ticket ID. Sends the same ID in the URL and cost_item_id query parameter.")


class AccessKey(_Input):
    operation: Literal["create_access_key"] = Field("create_access_key", json_schema_extra={"ui:hidden": True})
    key: str = Field(..., min_length=1, description="User-facing access code.")
    listing_id: str = Field(..., min_length=1)
    rate_ids: list[str] = Field(..., min_length=1, description="Ticket type IDs unlocked by the code.")
    quantity: int | None = Field(None, ge=1, description="Redemption limit; serialized as a string per the REST contract.")


class Rate(_Input):
    operation: Literal["create_rate"] = Field("create_rate", json_schema_extra={"ui:hidden": True})
    listing_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, description="Unique ticket type display name.")
    price: float = Field(..., ge=0, allow_inf_nan=False, description="Price in dollars.")
    state: Literal["locked", "active", "inactive"] = "active"
    capacity: int | None = Field(None, ge=0)
    min_tickets: int | None = Field(None, ge=1)
    max_tickets: int | None = Field(None, ge=1)
    discountable: bool = True


class _Discount(_Input):
    listing_id: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1)
    quantity: int | None = Field(None, ge=1)
    rate_ids: list[str] | None = None


class PercentDiscount(_Discount):
    operation: Literal["create_percent_discount"] = Field("create_percent_discount", json_schema_extra={"ui:hidden": True})
    percent: float = Field(..., ge=0, le=1, allow_inf_nan=False, description="Fraction from 0 to 1, for example 0.2 for 20%.")


class FixedDiscount(_Discount):
    operation: Literal["create_fixed_discount"] = Field("create_fixed_discount", json_schema_extra={"ui:hidden": True})
    fixed: float = Field(..., ge=0, allow_inf_nan=False, description="Discount amount in dollars.")


UniverseOperation = Annotated[Union[CurrentUser, TokenInfo, Listings, Guestlists, EventGuestlist, CheckIn, AccessKey, Rate, PercentDiscount, FixedDiscount], Field(discriminator="operation")]


class UniverseNodeConfig(NodeConfig[UniverseOperation, UniverseOAuthCredential]):
    pass


class UniverseNode(WorkflowNode):
    integration_type = "automation-universe"
    scope_registry = UNIVERSE_SCOPES
    connection_evidence = ConnectionEvidence(noun="Universe account", operation="get_current_user", label_keys=("email", "first_name", "id"))

    @classmethod
    def get_config_model(cls):
        return UniverseNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=OAUTH_PROVIDER.refresh, provider="universe")

    @staticmethod
    def _wire(op):
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        if isinstance(op, CurrentUser):
            return "GET", "/api/v2/current_user", {}, None
        if isinstance(op, TokenInfo):
            return "GET", "/oauth/token/info", {}, None
        if isinstance(op, Listings):
            return "GET", "/api/v2/listings", values, None
        if isinstance(op, Guestlists):
            return "GET", "/api/v2/guestlists", values, None
        if isinstance(op, CheckIn):
            return "PUT", "/api/v2/cost_item_check_ins/" + quote(op.cost_item_id, safe=""), values, None
        if isinstance(op, AccessKey):
            if "quantity" in values:
                values["quantity"] = str(values["quantity"])
            return "POST", "/api/v2/access_keys", {}, {"access_key": values}
        if isinstance(op, Rate):
            values.pop("listing_id")
            return "PUT", "/api/v2/listings/" + quote(op.listing_id, safe=""), {}, {"listing": {"cost_attributes": {"rates_attributes": values}}}
        if isinstance(op, (PercentDiscount, FixedDiscount)):
            # Provider description explicitly requires ONE amount. The generated
            # OpenAPI incorrectly lists both percent and fixed as required.
            values["discount_type"] = "percent" if isinstance(op, PercentDiscount) else "fixed"
            return "POST", "/api/v2/discount_codes", {}, {"discount_code": values}
        raise ValueError("Unsupported Universe operation")

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Universe account")
        cred = self.config.credentials.model_dump()
        token = await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=cred, refresh=OAUTH_PROVIDER.refresh,
            provider="universe", caller_path="execute")
        self.config.credentials = UniverseOAuthCredential.model_validate(cred)
        op = self.config.config
        method, path, params, body = self._wire(op)
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json; charset=UTF-8"
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://www.universe.com" + path,
                    params=params, json=body, headers=headers)
        except httpx.RequestError:
            raise ValueError("Universe request could not be completed; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            # Preserve the provider's rejection, with credential material redacted.
            message = response.text[:2000]
            for value in (token, cred.get("refresh_token")):
                if value:
                    message = message.replace(value, "[redacted]")
            raise ValueError(f"Universe HTTP {response.status_code}: {message}")
        if len(response.content) > 10_000_000:
            raise ValueError("Universe response exceeds 10 MB; use a smaller page")
        try:
            data = response.json() if response.content else {}
        except ValueError:
            raise ValueError("Universe did not return JSON; inspect writes before retrying") from None
        if not isinstance(data, dict) or data.get("error") or data.get("errors"):
            raise ValueError("Universe returned an error or unexpected response")
        if isinstance(op, CurrentUser):
            user = data.get("current_user")
            if not isinstance(user, dict) or not user.get("id"):
                raise ValueError("Universe current-user response does not identify an account")
            result = {"data": user}
        else:
            result = {"data": data}
        output = {"status": "success", "operation": op.operation, "http_status": response.status_code, **result}
        # Do not expose any echoed OAuth secrets in workflow output.
        def redact(value):
            if isinstance(value, dict):
                return {k: redact(v) for k, v in value.items() if k not in {"access_token", "refresh_token"}}
            if isinstance(value, list):
                return [redact(v) for v in value]
            if isinstance(value, str):
                for secret in (token, cred.get("refresh_token")):
                    if secret:
                        value = value.replace(secret, "[redacted]")
            return value
        output = redact(output)
        await self.emit(output)
        return output
