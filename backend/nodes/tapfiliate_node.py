"""Tapfiliate REST API 1.6: one documented endpoint per operation.

Contract: https://developers.tapfiliate.com/api-reference/openapi.json
Pagination: https://developers.tapfiliate.com/api-reference/introduction
Authentication: https://developers.tapfiliate.com/authentication
"""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.tapfiliate.com/1.6"
ResourceID = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")]
NumericID = Annotated[int, Field(strict=True, ge=1)]
Text = Annotated[str, Field(min_length=1, max_length=1000)]
Amount = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class TapfiliateAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Tapfiliate API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.tapfiliate.com/a/profile/",
            "x-credential-instructions": "Copy your API key from Tapfiliate profile settings. The key acts with your user permissions in one advertiser account. Approving or disapproving commissions requires the separate Approve commissions permission. NoClick checks access by reading your programs.",
        })
    credential_type: Literal["tapfiliate_api_key"] = Field("tapfiliate_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not isinstance(value, str) or any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, le=1000000, description="Page number, starting at 1. Tapfiliate returns 25 items per page; use next_page from the result.")


class ListAffiliates(_Page):
    """Find affiliates by email, referral code, parent or group."""
    operation: Literal["list_affiliates"] = "list_affiliates"
    email: Text | None = None
    referral_code: Text | None = None
    parent_id: ResourceID | None = None
    affiliate_group_id: ResourceID | None = None
    click_id: Text | None = None
    source_id: Text | None = None


class GetAffiliate(_Input):
    """Read an affiliate by their Tapfiliate ID."""
    operation: Literal["get_affiliate"] = "get_affiliate"
    affiliate_id: ResourceID


class CreateAffiliate(_Input):
    """Create an affiliate login. Store the password in a secret workflow input."""
    operation: Literal["create_affiliate"] = "create_affiliate"
    firstname: Text
    lastname: Text
    email: str = Field(..., min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(..., min_length=8, max_length=1000, repr=False, json_schema_extra={"ui:widget": "password"})


class DeleteAffiliate(GetAffiliate):
    """Permanently delete an affiliate."""
    operation: Literal["delete_affiliate"] = "delete_affiliate"


class _DatedPage(_Page):
    program_id: ResourceID | None = None
    affiliate_id: ResourceID | None = None
    date_from: str | None = Field(None, description="Inclusive day in UTC: YYYY-MM-DD")
    date_to: str | None = Field(None, description="End day in UTC: YYYY-MM-DD")

    @field_validator("date_from", "date_to")
    @classmethod
    def day(cls, value):
        if value is not None:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("Use YYYY-MM-DD")
            date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def date_order(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("End date must be on or after start date")
        return self


class ListCustomers(_DatedPage):
    """Find referred customers by program, affiliate or your customer ID."""
    operation: Literal["list_customers"] = "list_customers"
    customer_id: Text | None = None


class GetCustomer(_Input):
    """Read a customer using the Tapfiliate-generated ID, not your external ID."""
    operation: Literal["get_customer"] = "get_customer"
    id: ResourceID = Field(..., title="Tapfiliate customer ID")


class _Attribution(_Input):
    referral_code: Text | None = None
    tracking_id: Text | None = None
    click_id: Text | None = None
    coupon: Text | None = None
    asset_id: Text | None = None
    source_id: Text | None = None


class CreateCustomer(_Attribution):
    """Track a customer with a referral code, coupon, tracking ID or click ID."""
    operation: Literal["create_customer"] = "create_customer"
    customer_id: Text = Field(..., description="Unique customer ID in your own system")
    status: Literal["trial", "lead", "new"] = "new"
    override_max_cookie_time: StrictBool = False

    @model_validator(mode="after")
    def attribution(self):
        if not any((self.referral_code, self.tracking_id, self.click_id, self.coupon)):
            raise ValueError("Supply a referral code, tracking ID, click ID or coupon")
        return self


class UpdateCustomer(GetCustomer):
    """Change your external customer ID."""
    operation: Literal["update_customer"] = "update_customer"
    customer_id: Text


class DeleteCustomer(GetCustomer):
    """Permanently delete a customer."""
    operation: Literal["delete_customer"] = "delete_customer"


class ListConversions(_DatedPage):
    """Find conversions by external order ID, program, affiliate or date."""
    operation: Literal["list_conversions"] = "list_conversions"
    external_id: Text | None = None
    pending: StrictBool | None = None


class GetConversion(_Input):
    """Read a conversion and its commissions."""
    operation: Literal["get_conversion"] = "get_conversion"
    conversion_id: NumericID


class CreateConversion(_Attribution):
    """Track an order or recurring conversion. Use a unique external order ID."""
    operation: Literal["create_conversion"] = "create_conversion"
    external_id: Text
    amount: Amount
    customer_id: Text | None = Field(None, description="Your external customer ID for recurring/lifetime commissions")
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    commission_type: Text | None = None
    program_group: Text | None = None
    override_max_cookie_time: StrictBool = False

    @model_validator(mode="after")
    def attribution(self):
        if not any((self.referral_code, self.tracking_id, self.click_id, self.coupon, self.customer_id)):
            raise ValueError("Supply attribution or an existing external customer ID")
        return self


class UpdateConversion(GetConversion):
    """Change a conversion amount or external ID; optionally recalculate commissions."""
    operation: Literal["update_conversion"] = "update_conversion"
    amount: Amount | None = None
    external_id: Text | None = None
    recalculate_commissions: StrictBool = False

    @model_validator(mode="after")
    def change(self):
        if self.amount is None and self.external_id is None:
            raise ValueError("Supply an amount or external ID to update")
        return self


class DeleteConversion(GetConversion):
    """Permanently delete a conversion."""
    operation: Literal["delete_conversion"] = "delete_conversion"


class ListCommissions(_Page):
    """Find commissions by affiliate, approval state or payout state."""
    operation: Literal["list_commissions"] = "list_commissions"
    affiliate_id: ResourceID | None = None
    status: Literal["approved", "disapproved", "pending"] | None = None
    paid: StrictBool | None = None


class GetCommission(_Input):
    """Read one commission."""
    operation: Literal["get_commission"] = "get_commission"
    commission_id: NumericID


class ApproveCommission(GetCommission):
    """Approve a commission. Requires Approve commissions permission."""
    operation: Literal["approve_commission"] = "approve_commission"


class DisapproveCommission(GetCommission):
    """Disapprove a commission. Requires Approve commissions permission."""
    operation: Literal["disapprove_commission"] = "disapprove_commission"


class ListPrograms(_Page):
    """Read the advertiser account's affiliate programs."""
    operation: Literal["list_programs"] = "list_programs"
    asset_id: Text | None = None


class ListAffiliateGroups(_Page):
    """Read affiliate groups and affiliate counts."""
    operation: Literal["list_affiliate_groups"] = "list_affiliate_groups"


TapfiliateConfig = Annotated[Union[
    ListAffiliates, GetAffiliate, CreateAffiliate, DeleteAffiliate,
    ListCustomers, GetCustomer, CreateCustomer, UpdateCustomer, DeleteCustomer,
    ListConversions, GetConversion, CreateConversion, UpdateConversion, DeleteConversion,
    ListCommissions, GetCommission, ApproveCommission, DisapproveCommission,
    ListPrograms, ListAffiliateGroups,
], Field(discriminator="operation")]


class TapfiliateFullConfig(NodeConfig[TapfiliateConfig, TapfiliateAPIKeyCredential]):
    pass


# method, route, path fields, query fields, success status, response kind
ROUTES = {
    "list_affiliates": ("GET", "/affiliates/", (), ("email", "referral_code", "parent_id", "affiliate_group_id", "click_id", "source_id"), 200, "list"),
    "get_affiliate": ("GET", "/affiliates/{affiliate_id}/", ("affiliate_id",), (), 200, "object"),
    "create_affiliate": ("POST", "/affiliates/", (), (), 200, "optional"),
    "delete_affiliate": ("DELETE", "/affiliates/{affiliate_id}/", ("affiliate_id",), (), 204, "empty"),
    "list_customers": ("GET", "/customers/", (), ("program_id", "affiliate_id", "customer_id", "date_from", "date_to"), 200, "list"),
    "get_customer": ("GET", "/customers/{id}/", ("id",), (), 200, "object"),
    "create_customer": ("POST", "/customers/", (), ("override_max_cookie_time",), 200, "object"),
    "update_customer": ("PATCH", "/customers/{id}/", ("id",), (), 200, "object"),
    "delete_customer": ("DELETE", "/customers/{id}/", ("id",), (), 204, "empty"),
    "list_conversions": ("GET", "/conversions/", (), ("program_id", "affiliate_id", "external_id", "pending", "date_from", "date_to"), 200, "list"),
    "get_conversion": ("GET", "/conversions/{conversion_id}/", ("conversion_id",), (), 200, "object"),
    "create_conversion": ("POST", "/conversions/", (), ("override_max_cookie_time",), 200, "object"),
    "update_conversion": ("PATCH", "/conversions/{conversion_id}/", ("conversion_id",), ("recalculate_commissions",), 200, "optional"),
    "delete_conversion": ("DELETE", "/conversions/{conversion_id}/", ("conversion_id",), (), 204, "empty"),
    "list_commissions": ("GET", "/commissions/", (), ("affiliate_id", "status", "paid"), 200, "list"),
    "get_commission": ("GET", "/commissions/{commission_id}/", ("commission_id",), (), 200, "object"),
    "approve_commission": ("PUT", "/commissions/{commission_id}/approved/", ("commission_id",), (), 200, "object"),
    "disapprove_commission": ("DELETE", "/commissions/{commission_id}/approved/", ("commission_id",), (), 200, "object"),
    "list_programs": ("GET", "/programs/", (), ("asset_id",), 200, "list"),
    "list_affiliate_groups": ("GET", "/affiliate-groups/", (), (), 200, "list"),
}


def _redact(value, secrets):
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items() if k.lower() not in {"password", "api_key", "access_token", "refresh_token", "authorization"}}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
    return value


def _next_page(response, current, route):
    """Use only the documented Link next relation, never request its URL."""
    link = response.links.get("next")
    if link is None:
        return None
    url = urlsplit(link["url"])
    query = parse_qs(url.query)
    pages = query.get("page", [])
    if url.scheme != "https" or url.netloc != "api.tapfiliate.com" or url.path != "/1.6" + route or len(pages) != 1 or not re.fullmatch(r"[1-9][0-9]{0,6}", pages[0]):
        raise ValueError("Tapfiliate returned an invalid pagination link")
    following = int(pages[0])
    if following <= current or following > 1000000:
        raise ValueError("Tapfiliate returned a nonadvancing pagination link")
    return following


class TapfiliateNode(WorkflowNode):
    integration_type = "automation-tapfiliate"
    connection_evidence = ConnectionEvidence(operation="list_programs", noun="Tapfiliate programs", label_keys=("title", "id"))

    @classmethod
    def get_config_model(cls):
        return TapfiliateFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Tapfiliate API key")
        op = self.config.config
        credential = self.config.credentials
        method, route, path_fields, query_fields, expected, kind = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        route = route.format(**{name: str(values[name]) for name in path_fields})
        params = {}
        for name in query_fields:
            if name in values:
                value = values[name]
                params[name] = ("1" if value else "0") if name == "paid" else str(value).lower() if isinstance(value, bool) else value
        if isinstance(op, _Page) and op.page != 1:
            params["page"] = op.page
        body = None
        if method in {"POST", "PATCH"}:
            body = {k: v for k, v in values.items() if k not in {"operation", "page", *path_fields, *query_fields}}
        secrets = (credential.api_key, getattr(op, "password", None))
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route, params=params,
                    headers={"X-Api-Key": credential.api_key, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            suffix = " The write outcome is unknown; inspect Tapfiliate before retrying." if method != "GET" else ""
            raise ValueError("Tapfiliate request did not complete." + suffix) from None
        if response.status_code != expected:
            message = _redact(response.text[:1000], secrets)
            raise ValueError(f"Tapfiliate HTTP {response.status_code}: {message}")
        data = None
        if kind != "empty" and (response.content or kind != "optional"):
            if len(response.content) > 5000000 or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError("Tapfiliate returned an unexpected response; inspect writes before retrying")
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Tapfiliate returned invalid JSON; inspect writes before retrying") from None
            if (kind == "list" and (not isinstance(data, list) or any(not isinstance(row, dict) for row in data))) or (kind != "list" and not isinstance(data, dict)):
                raise ValueError("Tapfiliate returned an unexpected JSON shape; inspect writes before retrying")
            if isinstance(data, dict) and ("error" in data or "errors" in data or data.get("code", 0) in {400, 401, 403, 404, 429, 500}):
                raise ValueError("Tapfiliate rejected the request: " + str(_redact(data, secrets))[:1000])
        result = {"status": "success", "operation": op.operation, "http_status": response.status_code, "data": _redact(data, secrets)}
        if kind == "list":
            result.update(page=op.page, next_page=_next_page(response, op.page, route))
        if method != "GET":
            result["acknowledged"] = True
        await self.emit(result)
        return result
