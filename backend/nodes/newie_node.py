"""Newie REST operations, pinned to OpenAPI 0.1.0.

https://api.newie.app/openapi.json
Lists return one page; continue with page.nextCursor and unchanged filters.
Metadata writes merge keys; a null value deletes a key and changes no Newie fields.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.newie import NEWIE_SCOPES
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.newie.app"


class NewieOAuthCredential(BaseModel):
    model_config = ConfigDict(
        title="Newie Account",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "newie",
            "x-oauth-scopes": NEWIE_SCOPES.declared_scopes(),
            "x-credential-url": "https://api.newie.app/docs/guides/identity.md",
            "x-credential-instructions": "Sign in to Newie and choose one organization. Your role must allow the requested read and metadata permissions. For manual connection, paste a REST access token; refresh token and expiry are optional. Tokens for the MCP resource do not work here.",
        },
    )
    credential_type: Literal["newie_oauth"] = Field(
        "newie_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        repr=False,
        min_length=1,
        max_length=16384,
        json_schema_extra={"ui:widget": "password"},
    )
    refresh_token: str | None = Field(
        None,
        title="Refresh Token",
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )
    expires_at: str | None = Field(
        None,
        title="Token Expiry",
        description="ISO 8601 access token expiry, if known.",
    )
    scope: str | None = Field(None, title="Granted Scopes")

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def token(cls, value):
        if value is None:
            return value
        value = clean_secret(value, field_name="Token")
        if not value.isascii() or any(
            c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value
        ):
            raise ValueError("Paste the token without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value):
                raise ValueError("Use a single Newie resource ID")
            prefix = {
                "customer_id": "cus_",
                "payment_id": "payrec_",
                "payout_id": "payout_",
            }.get(info.field_name)
            if prefix and not value.startswith(prefix):
                raise ValueError("Use the Newie ID beginning with " + prefix)
        if isinstance(value, list):
            if len(value) != len(set(value)):
                raise ValueError("Repeated values must be unique")
            if info.field_name in {"customer_id_filter", "offering_id_filter"}:
                for item in value:
                    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", item):
                        raise ValueError("Use canonical Newie filter IDs")
                    if info.field_name == "customer_id_filter" and not item.startswith(
                        "cus_"
                    ):
                        raise ValueError("Customer IDs begin with cus_")
        return value


class _Page(_Input):
    page_limit: int = Field(25, ge=1, le=100, title="Page Size")
    page_after: str | None = Field(
        None,
        min_length=1,
        max_length=2048,
        title="Next Cursor",
        description="Use page.nextCursor from the previous response and keep every filter unchanged.",
    )
    profile: Literal["compact", "full"] = Field("compact", title="Representation")


class _Metadata(_Input):
    metadata: dict[str, str | None] = Field(
        ...,
        title="Metadata",
        description="Merge your own keys; null removes a key. This does not edit customer details, prices, payments or subscription status.",
    )

    @field_validator("metadata")
    @classmethod
    def bounded_metadata(cls, value):
        if len(value) > 50:
            raise ValueError("At most 50 metadata keys are allowed")
        for key, item in value.items():
            if not 1 <= len(key) <= 40 or item is not None and len(item) > 500:
                raise ValueError(
                    "Metadata keys take 1–40 characters and values at most 500"
                )
            if any(
                c == "\x00" or 0xD800 <= ord(c) <= 0xDFFF for c in key + (item or "")
            ):
                raise ValueError("Metadata must contain valid Unicode without NUL")
        return value


class _Period(_Input):
    period_start: str = Field(
        ...,
        title="Period Start",
        description="Inclusive UTC timestamp ending in Z.",
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$",
    )
    period_end: str = Field(
        ...,
        title="Period End",
        description="Exclusive UTC timestamp, at most 366 days after start.",
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$",
    )

    @model_validator(mode="after")
    def valid_period(self):
        start = datetime.fromisoformat(self.period_start.replace("Z", "+00:00"))
        end = datetime.fromisoformat(self.period_end.replace("Z", "+00:00"))
        if not 0 < (end - start).total_seconds() <= 366 * 86400:
            raise ValueError("Report period must be positive and at most 366 days")
        return self


class GetCurrentUser(_Input):
    """Get the current user."""

    operation: Literal["get_current_user"] = Field(
        "get_current_user",
        title="Get the current user",
        json_schema_extra={"ui:hidden": True},
    )


class GetOrganization(_Input):
    """Get the organization."""

    operation: Literal["get_organization"] = Field(
        "get_organization",
        title="Get the organization",
        json_schema_extra={"ui:hidden": True},
    )


class ListOfferings(_Page):
    """List offerings."""

    operation: Literal["list_offerings"] = Field(
        "list_offerings", title="List offerings", json_schema_extra={"ui:hidden": True}
    )
    name_contains: str | None = Field(
        None,
        min_length=2,
        max_length=100,
        pattern="^[^\\s\\u0000-\\u001f\\u007f](?:[^\\u0000-\\u001f\\u007f]*[^\\s\\u0000-\\u001f\\u007f])?$",
    )
    status_filter: list[Literal["draft", "active", "archived"]] | None = Field(
        None, min_length=1, max_length=25
    )


class GetOffering(_Input):
    """Get an offering."""

    operation: Literal["get_offering"] = Field(
        "get_offering", title="Get an offering", json_schema_extra={"ui:hidden": True}
    )
    offering_id: str = Field(..., title="Offering Id", min_length=1, max_length=128)


class UpdateOffering(_Metadata):
    """Update offering metadata."""

    operation: Literal["update_offering"] = Field(
        "update_offering",
        title="Update offering metadata",
        json_schema_extra={"ui:hidden": True},
    )
    offering_id: str = Field(..., title="Offering Id", min_length=1, max_length=128)


class ListCustomers(_Page):
    """List customers."""

    operation: Literal["list_customers"] = Field(
        "list_customers", title="List customers", json_schema_extra={"ui:hidden": True}
    )
    email_contains: str | None = Field(
        None,
        min_length=2,
        max_length=100,
        pattern="^[^\\s\\u0000-\\u001f\\u007f](?:[^\\u0000-\\u001f\\u007f]*[^\\s\\u0000-\\u001f\\u007f])?$",
    )
    name_contains: str | None = Field(
        None,
        min_length=2,
        max_length=100,
        pattern="^[^\\s\\u0000-\\u001f\\u007f](?:[^\\u0000-\\u001f\\u007f]*[^\\s\\u0000-\\u001f\\u007f])?$",
    )


class GetCustomer(_Input):
    """Get a customer."""

    operation: Literal["get_customer"] = Field(
        "get_customer", title="Get a customer", json_schema_extra={"ui:hidden": True}
    )
    customer_id: str = Field(..., title="Customer Id", min_length=1, max_length=128)


class UpdateCustomer(_Metadata):
    """Update customer metadata."""

    operation: Literal["update_customer"] = Field(
        "update_customer",
        title="Update customer metadata",
        json_schema_extra={"ui:hidden": True},
    )
    customer_id: str = Field(..., title="Customer Id", min_length=1, max_length=128)


class GetCustomerOverview(_Input):
    """Get a customer overview."""

    operation: Literal["get_customer_overview"] = Field(
        "get_customer_overview",
        title="Get a customer overview",
        json_schema_extra={"ui:hidden": True},
    )
    customer_id: str = Field(..., title="Customer Id", min_length=1, max_length=128)


class ListPurchases(_Page):
    """List purchases."""

    operation: Literal["list_purchases"] = Field(
        "list_purchases", title="List purchases", json_schema_extra={"ui:hidden": True}
    )
    customer_id_filter: list[str] | None = Field(None, min_length=1, max_length=25)
    offering_id_filter: list[str] | None = Field(None, min_length=1, max_length=25)
    status_filter: list[
        Literal["pending", "processing", "completed", "failed", "expired"]
    ] | None = Field(None, min_length=1, max_length=25)


class GetPurchase(_Input):
    """Get a purchase."""

    operation: Literal["get_purchase"] = Field(
        "get_purchase", title="Get a purchase", json_schema_extra={"ui:hidden": True}
    )
    purchase_id: str = Field(..., title="Purchase Id", min_length=1, max_length=128)


class ListSubscriptions(_Page):
    """List subscriptions."""

    operation: Literal["list_subscriptions"] = Field(
        "list_subscriptions",
        title="List subscriptions",
        json_schema_extra={"ui:hidden": True},
    )
    customer_id_filter: list[str] | None = Field(None, min_length=1, max_length=25)
    offering_id_filter: list[str] | None = Field(None, min_length=1, max_length=25)
    status_filter: list[
        Literal[
            "pending", "scheduled", "active", "paused", "pastDue", "ended", "failed"
        ]
    ] | None = Field(None, min_length=1, max_length=25)


class GetSubscription(_Input):
    """Get a subscription."""

    operation: Literal["get_subscription"] = Field(
        "get_subscription",
        title="Get a subscription",
        json_schema_extra={"ui:hidden": True},
    )
    subscription_id: str = Field(
        ..., title="Subscription Id", min_length=1, max_length=128
    )


class UpdateSubscription(_Metadata):
    """Update subscription metadata."""

    operation: Literal["update_subscription"] = Field(
        "update_subscription",
        title="Update subscription metadata",
        json_schema_extra={"ui:hidden": True},
    )
    subscription_id: str = Field(
        ..., title="Subscription Id", min_length=1, max_length=128
    )


class ListPayments(_Page):
    """List payments."""

    operation: Literal["list_payments"] = Field(
        "list_payments", title="List payments", json_schema_extra={"ui:hidden": True}
    )
    customer_id_filter: list[str] | None = Field(None, min_length=1, max_length=25)
    offering_id_filter: list[str] | None = Field(None, min_length=1, max_length=25)
    payment_status: list[
        Literal[
            "pending",
            "processing",
            "failed",
            "overdue",
            "paid",
            "refunded",
            "paused",
            "void",
            "uncollectible",
        ]
    ] | None = Field(None, min_length=1, max_length=25)


class GetPayment(_Input):
    """Get a payment."""

    operation: Literal["get_payment"] = Field(
        "get_payment", title="Get a payment", json_schema_extra={"ui:hidden": True}
    )
    payment_id: str = Field(..., title="Payment Id", min_length=1, max_length=128)


class UpdatePayment(_Metadata):
    """Update payment metadata."""

    operation: Literal["update_payment"] = Field(
        "update_payment",
        title="Update payment metadata",
        json_schema_extra={"ui:hidden": True},
    )
    payment_id: str = Field(..., title="Payment Id", min_length=1, max_length=128)


class ListPayouts(_Page):
    """List payouts."""

    operation: Literal["list_payouts"] = Field(
        "list_payouts", title="List payouts", json_schema_extra={"ui:hidden": True}
    )
    status_filter: list[
        Literal["pending", "inTransit", "paid", "failed", "canceled"]
    ] | None = Field(None, min_length=1, max_length=25)


class GetPayout(_Input):
    """Get a payout."""

    operation: Literal["get_payout"] = Field(
        "get_payout", title="Get a payout", json_schema_extra={"ui:hidden": True}
    )
    payout_id: str = Field(..., title="Payout Id", min_length=1, max_length=128)


class GetOfferingsReport(_Period):
    """Report on offerings."""

    operation: Literal["get_offerings_report"] = Field(
        "get_offerings_report",
        title="Report on offerings",
        json_schema_extra={"ui:hidden": True},
    )
    metric: list[Literal["count"]] = Field(["count"], min_length=1, max_length=1)
    group_by: list[
        Literal["status", "offeringType", "groupID", "currency", "createdDate"]
    ] | None = Field(None, max_length=5)

    interval: Literal["day", "week", "month"] | None = Field(
        None, title="Date Group Interval"
    )

    @model_validator(mode="after")
    def date_groups(self):
        if self.group_by and "createdDate" in self.group_by and not self.interval:
            raise ValueError("Date grouping needs an interval")
        return self


class GetSubscriptionsReport(_Input):
    """Report on subscriptions."""

    operation: Literal["get_subscriptions_report"] = Field(
        "get_subscriptions_report",
        title="Report on subscriptions",
        json_schema_extra={"ui:hidden": True},
    )
    metric: list[Literal["count", "monthlyRecurringAmount"]] = Field(
        ["count"], min_length=1, max_length=2
    )
    group_by: list[Literal["status", "offeringID", "currency"]] | None = Field(
        None, max_length=3
    )

    @model_validator(mode="after")
    def money_groups(self):
        if (
            "monthlyRecurringAmount" in self.metric
            and self.group_by
            and "currency" not in self.group_by
        ):
            raise ValueError("Recurring amounts must group by currency")
        return self


class GetPaymentsReport(_Period):
    """Report on payments."""

    operation: Literal["get_payments_report"] = Field(
        "get_payments_report",
        title="Report on payments",
        json_schema_extra={"ui:hidden": True},
    )
    metric: list[
        Literal[
            "count",
            "grossAmount",
            "refundedAmount",
            "pendingRefundAmount",
            "realizedNetAmount",
            "requestedAmount",
            "outstandingAmount",
        ]
    ] = Field(["count"], min_length=1, max_length=7)
    group_by: list[
        Literal[
            "currency",
            "paidDate",
            "createdDate",
            "offeringID",
            "paymentType",
            "paymentStatus",
            "customerID",
        ]
    ] | None = Field(None, max_length=7)

    interval: Literal["day", "week", "month"] | None = Field(
        None, title="Date Group Interval"
    )
    period_on: Literal["paidAt", "createdAt"] | None = Field(
        None, title="Report Date Field"
    )

    @model_validator(mode="after")
    def money_groups(self):
        groups = self.group_by or []
        if "createdDate" in groups and self.period_on != "createdAt":
            raise ValueError("createdDate grouping requires period_on createdAt")
        if "paidDate" in groups and self.period_on == "createdAt":
            raise ValueError("paidDate grouping requires period_on paidAt")
        if {"createdDate", "paidDate"} & set(groups) and not self.interval:
            raise ValueError("Date grouping needs an interval")
        if self.group_by and "currency" not in self.group_by:
            raise ValueError("Payment reports must group by currency")
        return self


NewieConfig = Annotated[
    Union[
        GetCurrentUser,
        GetOrganization,
        ListOfferings,
        GetOffering,
        UpdateOffering,
        ListCustomers,
        GetCustomer,
        UpdateCustomer,
        GetCustomerOverview,
        ListPurchases,
        GetPurchase,
        ListSubscriptions,
        GetSubscription,
        UpdateSubscription,
        ListPayments,
        GetPayment,
        UpdatePayment,
        ListPayouts,
        GetPayout,
        GetOfferingsReport,
        GetSubscriptionsReport,
        GetPaymentsReport,
    ],
    Field(discriminator="operation"),
]


class NewieFullConfig(NodeConfig[NewieConfig, NewieOAuthCredential]):
    pass


ROUTES = {
    "get_current_user": ("GET", "/v1/users/me"),
    "get_organization": ("GET", "/v1/organization"),
    "list_offerings": ("GET", "/v1/offerings"),
    "get_offering": ("GET", "/v1/offerings/{offering_id}"),
    "update_offering": ("PATCH", "/v1/offerings/{offering_id}"),
    "list_customers": ("GET", "/v1/customers"),
    "get_customer": ("GET", "/v1/customers/{customer_id}"),
    "update_customer": ("PATCH", "/v1/customers/{customer_id}"),
    "get_customer_overview": ("GET", "/v1/customers/{customer_id}/overview"),
    "list_purchases": ("GET", "/v1/purchases"),
    "get_purchase": ("GET", "/v1/purchases/{purchase_id}"),
    "list_subscriptions": ("GET", "/v1/subscriptions"),
    "get_subscription": ("GET", "/v1/subscriptions/{subscription_id}"),
    "update_subscription": ("PATCH", "/v1/subscriptions/{subscription_id}"),
    "list_payments": ("GET", "/v1/payments"),
    "get_payment": ("GET", "/v1/payments/{payment_id}"),
    "update_payment": ("PATCH", "/v1/payments/{payment_id}"),
    "list_payouts": ("GET", "/v1/payouts"),
    "get_payout": ("GET", "/v1/payouts/{payout_id}"),
    "get_offerings_report": ("GET", "/v1/reports/offerings"),
    "get_subscriptions_report": ("GET", "/v1/reports/subscriptions"),
    "get_payments_report": ("GET", "/v1/reports/payments"),
}

QUERY_NAMES = {
    "page_limit": "page[limit]",
    "page_after": "page[after]",
    "period_start": "period[start]",
    "period_end": "period[end]",
    "period_on": "period[on]",
    "group_by": "groupBy",
    "customer_id_filter": "filter[customerID]",
    "offering_id_filter": "filter[offeringID]",
    "status_filter": "filter[status]",
    "name_contains": "filter[name][contains]",
    "email_contains": "filter[email][contains]",
    "payment_status": "filter[paymentStatus]",
}

EXPECTED_OBJECT = {
    "get_current_user": "user",
    "get_organization": "organization",
    "list_offerings": "list",
    "get_offering": "offering",
    "update_offering": "offering",
    "list_customers": "list",
    "get_customer": "customer",
    "update_customer": "customer",
    "get_customer_overview": "customerOverview",
    "list_purchases": "list",
    "get_purchase": "purchase",
    "list_subscriptions": "list",
    "get_subscription": "subscription",
    "update_subscription": "subscription",
    "list_payments": "list",
    "get_payment": "payment",
    "update_payment": "payment",
    "list_payouts": "list",
    "get_payout": "payout",
    "get_offerings_report": "report",
    "get_subscriptions_report": "report",
    "get_payments_report": "report",
}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
    elif isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    elif isinstance(value, dict):
        return {
            _redact(key, secrets): _redact(item, secrets) for key, item in value.items()
        }
    return value


class NewieNode(WorkflowNode):
    integration_type = "automation-newie"
    scope_registry = NEWIE_SCOPES
    connection_evidence = ConnectionEvidence(
        operation="get_organization",
        noun="organization",
        identity_operation="get_current_user",
    )

    @classmethod
    def get_config_model(cls):
        return NewieFullConfig

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        if not credential_data.get("refresh_token"):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.newie_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="newie",
        )

    async def execute(self, inputs):
        if not isinstance(self.config, NewieFullConfig) or not self.config.credentials:
            raise ValueError("Connect a Newie account")
        config, credential = self.config.config, self.config.credentials
        self.scope_registry.require(config.operation)
        token = credential.access_token
        if credential.refresh_token:
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            from nodes.oauth.newie_oauth import refresh_access_token

            credential_data = credential.model_dump()
            token = await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id,
                credential=credential_data,
                refresh=refresh_access_token,
                provider="newie",
                caller_path="execute",
            )
            credential.access_token = credential_data["access_token"]
            credential.refresh_token = credential_data.get("refresh_token")
            credential.expires_at = credential_data.get("expires_at")
        method, template = ROUTES[config.operation]
        values = config.model_dump(
            mode="json", exclude_none=True, exclude={"operation"}
        )
        # exclude_none must not erase metadata's null deletion values.
        if method == "PATCH":
            values["metadata"] = config.metadata
        path_fields = re.findall(r"\{(\w+)\}", template)
        path = template.format(
            **{field: quote(values.pop(field), safe="") for field in path_fields}
        )
        kwargs = {}
        if method == "GET":
            params = []
            for key, value in values.items():
                query_key = QUERY_NAMES.get(key, key)
                for item in value if isinstance(value, list) else [value]:
                    params.append((query_key, item))
            kwargs["params"] = params
        else:
            kwargs["json"] = values
        async with guarded_async_client(
            timeout=30, trust_env=False, follow_redirects=False
        ) as client:
            response = await client.request(
                method,
                BASE_URL + path,
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/json",
                },
                **kwargs,
            )
        secrets = (token, credential.refresh_token)
        if len(response.content) > 10_000_000:
            raise ValueError("Newie response exceeds the size limit")
        if 300 <= response.status_code < 400:
            raise ValueError("Newie redirected the request; reconnect your account")
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if mime not in {"application/json", "application/problem+json"}:
            raise ValueError("Expected JSON from Newie")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Newie returned invalid JSON") from None
        request_id = response.headers.get("Newie-Request-ID")
        if (
            response.status_code >= 400
            or isinstance(body, dict)
            and (
                body.get("error")
                or body.get("errors")
                or "code" in body
                and "detail" in body
            )
        ):
            return _redact(
                {
                    "status": "error",
                    "http_status": response.status_code,
                    "error": body.get("detail", "Newie rejected the request")
                    if isinstance(body, dict)
                    else "Newie rejected the request",
                    "problem": body,
                    "request_id": request_id,
                    "retry_after": response.headers.get("Retry-After"),
                },
                secrets,
            )
        if response.status_code != 200:
            raise ValueError("Newie did not confirm this operation")
        if (
            not isinstance(body, dict)
            or body.get("object") != EXPECTED_OBJECT[config.operation]
        ):
            raise ValueError("Unexpected Newie response object")
        if config.operation.startswith("list_"):
            page = body.get("page")
            if (
                not isinstance(body.get("data"), list)
                or any(not isinstance(row, dict) for row in body["data"])
                or not isinstance(page, dict)
                or "nextCursor" not in page
            ):
                raise ValueError("Expected a Newie collection and continuation cursor")
            if page["nextCursor"] is not None and not isinstance(
                page["nextCursor"], str
            ):
                raise ValueError("Unexpected Newie continuation cursor")
        return _redact(
            {
                "status": "success",
                "operation": config.operation,
                "http_status": response.status_code,
                "data": body,
                "request_id": request_id,
            },
            secrets,
        )
