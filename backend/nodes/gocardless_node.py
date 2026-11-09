"""GoCardless account automation against API version 2015-07-06.

Each operation performs one documented request; list results expose cursor paging.
Writes return the provider acknowledgement and are never automatically retried.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from datetime import date
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class GoCardlessTokenCredential(BaseModel):
    model_config = ConfigDict(title="GoCardless Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://manage.gocardless.com/developers/access-tokens",
            "x-credential-instructions": "In your GoCardless dashboard, open Developers, then Create access token. Paste the token only. Choose the matching Live or Sandbox environment. Read-write access is required for writes; read-only tokens can run reads. Live writes can move real money or cancel collections."
        })
    credential_type: Literal["gocardless_access_token"] = Field("gocardless_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})
    environment: Literal["live", "sandbox"] = Field("live", title="Environment")

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without a Bearer prefix or whitespace")
        return value


ResourceID = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
Currency = Literal["AUD", "CAD", "DKK", "EUR", "GBP", "NZD", "SEK", "USD"]
Amount = Annotated[int, Field(strict=True, gt=0, description="Amount in minor currency units (pence/cents), not whole currency units.")]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def metadata_bounds(cls, value, info):
        if info.field_name == "metadata" and value is not None:
            if len(value) > 3 or any(not k or len(k) > 50 or len(v) > 500 for k, v in value.items()):
                raise ValueError("Metadata allows 3 keys, key length 50 and value length 500")
        return value


class ListInput(Input):
    limit: int = Field(50, ge=1, le=500, strict=True)
    after: ResourceID | None = Field(None, description="Cursor from meta.cursors.after; each call reads one page.")


class ListCreditorsConfig(ListInput):
    """List creditors."""
    operation: Literal["list_creditors"] = Field("list_creditors", json_schema_extra={"ui:hidden": True})


class ListCustomersConfig(ListInput):
    """List customers."""
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})


class GetCustomerConfig(Input):
    """Get customer."""
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True})
    customer_id: ResourceID


class ListCustomerBankAccountsConfig(ListInput):
    """List customer bank accounts."""
    operation: Literal["list_customer_bank_accounts"] = Field("list_customer_bank_accounts", json_schema_extra={"ui:hidden": True})
    customer: ResourceID | None = None


class GetCustomerBankAccountConfig(Input):
    """Get customer bank account."""
    operation: Literal["get_customer_bank_account"] = Field("get_customer_bank_account", json_schema_extra={"ui:hidden": True})
    customer_bank_account_id: ResourceID


class ListMandatesConfig(ListInput):
    """List mandates."""
    operation: Literal["list_mandates"] = Field("list_mandates", json_schema_extra={"ui:hidden": True})
    customer: ResourceID | None = None


class GetMandateConfig(Input):
    """Get mandate."""
    operation: Literal["get_mandate"] = Field("get_mandate", json_schema_extra={"ui:hidden": True})
    mandate_id: ResourceID


class ListPaymentsConfig(ListInput):
    """List payments."""
    operation: Literal["list_payments"] = Field("list_payments", json_schema_extra={"ui:hidden": True})
    customer: ResourceID | None = None
    mandate: ResourceID | None = None


class GetPaymentConfig(Input):
    """Get payment."""
    operation: Literal["get_payment"] = Field("get_payment", json_schema_extra={"ui:hidden": True})
    payment_id: ResourceID


class ListSubscriptionsConfig(ListInput):
    """List subscriptions."""
    operation: Literal["list_subscriptions"] = Field("list_subscriptions", json_schema_extra={"ui:hidden": True})
    customer: ResourceID | None = None
    mandate: ResourceID | None = None


class GetSubscriptionConfig(Input):
    """Get subscription."""
    operation: Literal["get_subscription"] = Field("get_subscription", json_schema_extra={"ui:hidden": True})
    subscription_id: ResourceID


class ListRefundsConfig(ListInput):
    """List refunds."""
    operation: Literal["list_refunds"] = Field("list_refunds", json_schema_extra={"ui:hidden": True})
    payment: ResourceID | None = None


class GetRefundConfig(Input):
    """Get refund."""
    operation: Literal["get_refund"] = Field("get_refund", json_schema_extra={"ui:hidden": True})
    refund_id: ResourceID


class ListPayoutsConfig(ListInput):
    """List payouts."""
    operation: Literal["list_payouts"] = Field("list_payouts", json_schema_extra={"ui:hidden": True})


class GetPayoutConfig(Input):
    """Get payout."""
    operation: Literal["get_payout"] = Field("get_payout", json_schema_extra={"ui:hidden": True})
    payout_id: ResourceID


class UpdateCustomerConfig(Input):
    """Update customer."""
    operation: Literal["update_customer"] = Field("update_customer", json_schema_extra={"ui:hidden": True})
    customer_id: ResourceID
    email: str | None = Field(None, max_length=255)
    given_name: str | None = Field(None, max_length=255)
    family_name: str | None = Field(None, max_length=255)
    company_name: str | None = Field(None, max_length=255)
    address_line1: str | None = Field(None, max_length=255)
    address_line2: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=255)
    postal_code: str | None = Field(None, max_length=20)
    country_code: str | None = Field(None, pattern=r"^[A-Z]{2}$")
    metadata: dict[str, str] | None = None


class CreatePaymentConfig(Input):
    """Create payment."""
    operation: Literal["create_payment"] = Field("create_payment", json_schema_extra={"ui:hidden": True})
    mandate_id: ResourceID
    amount: Amount
    currency: Currency
    description: str | None = None
    charge_date: date | None = None
    reference: str | None = None
    metadata: dict[str, str] | None = None
    idempotency_key: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Unique stable key for this intended payment. Reuse it when retrying the same request.")


class UpdatePaymentConfig(Input):
    """Update payment."""
    operation: Literal["update_payment"] = Field("update_payment", json_schema_extra={"ui:hidden": True})
    payment_id: ResourceID
    retry_if_possible: bool | None = None
    metadata: dict[str, str] | None = None


class CreateSubscriptionConfig(Input):
    """Create subscription."""
    operation: Literal["create_subscription"] = Field("create_subscription", json_schema_extra={"ui:hidden": True})
    mandate_id: ResourceID
    amount: Amount
    currency: Currency
    interval_unit: Literal["weekly", "monthly", "yearly"]
    interval: int = Field(1, ge=1, strict=True)
    name: str | None = Field(None, max_length=255)
    count: int | None = Field(None, gt=0, strict=True)
    start_date: date | None = None
    metadata: dict[str, str] | None = None
    idempotency_key: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Unique stable key for this intended subscription; reuse for the same request.")


class UpdateSubscriptionConfig(Input):
    """Update subscription."""
    operation: Literal["update_subscription"] = Field("update_subscription", json_schema_extra={"ui:hidden": True})
    subscription_id: ResourceID
    amount: Amount | None = None
    name: str | None = Field(None, max_length=255)
    payment_reference: str | None = None
    metadata: dict[str, str] | None = None


class CreateRefundConfig(Input):
    """Create refund."""
    operation: Literal["create_refund"] = Field("create_refund", json_schema_extra={"ui:hidden": True})
    payment_id: ResourceID
    amount: Amount
    total_amount_confirmation: Amount = Field(..., description="Expected sum of existing refunds plus this refund, in minor units.")
    reference: str | None = None
    metadata: dict[str, str] | None = None
    idempotency_key: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Unique stable key for this intended refund; reuse for the same request.")


class CancelMandateConfig(Input):
    """Cancel this mandate; this changes live collections in the Live environment."""
    operation: Literal["cancel_mandate"] = Field("cancel_mandate", json_schema_extra={"ui:hidden": True})
    mandate_id: ResourceID
    metadata: dict[str, str] | None = None


class CancelPaymentConfig(Input):
    """Cancel this payment; this changes live collections in the Live environment."""
    operation: Literal["cancel_payment"] = Field("cancel_payment", json_schema_extra={"ui:hidden": True})
    payment_id: ResourceID
    metadata: dict[str, str] | None = None


class CancelSubscriptionConfig(Input):
    """Cancel this subscription; this changes live collections in the Live environment."""
    operation: Literal["cancel_subscription"] = Field("cancel_subscription", json_schema_extra={"ui:hidden": True})
    subscription_id: ResourceID
    metadata: dict[str, str] | None = None


class RetryPaymentConfig(Input):
    """Retry a failed payment; GoCardless decides eligibility. Never automatically retried by NoClick."""
    operation: Literal["retry_payment"] = Field("retry_payment", json_schema_extra={"ui:hidden": True})
    payment_id: ResourceID
    charge_date: date | None = None
    metadata: dict[str, str] | None = None


GoCardlessConfig = Annotated[Union[
    ListCreditorsConfig,
    ListCustomersConfig,
    GetCustomerConfig,
    ListCustomerBankAccountsConfig,
    GetCustomerBankAccountConfig,
    ListMandatesConfig,
    GetMandateConfig,
    ListPaymentsConfig,
    GetPaymentConfig,
    ListSubscriptionsConfig,
    GetSubscriptionConfig,
    ListRefundsConfig,
    GetRefundConfig,
    ListPayoutsConfig,
    GetPayoutConfig,
    UpdateCustomerConfig,
    CreatePaymentConfig,
    UpdatePaymentConfig,
    CreateSubscriptionConfig,
    UpdateSubscriptionConfig,
    CreateRefundConfig,
    CancelMandateConfig,
    CancelPaymentConfig,
    CancelSubscriptionConfig,
    RetryPaymentConfig
], Field(discriminator="operation")]


class GoCardlessFullConfig(NodeConfig[GoCardlessConfig, GoCardlessTokenCredential]):
    pass


OPERATIONS = {'list_creditors': ('GET', '/creditors', 'creditors'),
 'list_customers': ('GET', '/customers', 'customers'),
 'get_customer': ('GET', '/customers/{customer_id}', 'customers'),
 'list_customer_bank_accounts': ('GET', '/customer_bank_accounts', 'customer_bank_accounts'),
 'get_customer_bank_account': ('GET',
                               '/customer_bank_accounts/{customer_bank_account_id}',
                               'customer_bank_accounts'),
 'list_mandates': ('GET', '/mandates', 'mandates'),
 'get_mandate': ('GET', '/mandates/{mandate_id}', 'mandates'),
 'list_payments': ('GET', '/payments', 'payments'),
 'get_payment': ('GET', '/payments/{payment_id}', 'payments'),
 'list_subscriptions': ('GET', '/subscriptions', 'subscriptions'),
 'get_subscription': ('GET', '/subscriptions/{subscription_id}', 'subscriptions'),
 'list_refunds': ('GET', '/refunds', 'refunds'),
 'get_refund': ('GET', '/refunds/{refund_id}', 'refunds'),
 'list_payouts': ('GET', '/payouts', 'payouts'),
 'get_payout': ('GET', '/payouts/{payout_id}', 'payouts'),
 'update_customer': ('PUT', '/customers/{customer_id}', 'customers'),
 'create_payment': ('POST', '/payments', 'payments'),
 'update_payment': ('PUT', '/payments/{payment_id}', 'payments'),
 'create_subscription': ('POST', '/subscriptions', 'subscriptions'),
 'update_subscription': ('PUT', '/subscriptions/{subscription_id}', 'subscriptions'),
 'create_refund': ('POST', '/refunds', 'refunds'),
 'cancel_mandate': ('POST', '/mandates/{mandate_id}/actions/cancel', 'mandates'),
 'cancel_payment': ('POST', '/payments/{payment_id}/actions/cancel', 'payments'),
 'cancel_subscription': ('POST',
                         '/subscriptions/{subscription_id}/actions/cancel',
                         'subscriptions'),
 'retry_payment': ('POST', '/payments/{payment_id}/actions/retry', 'payments')}


class GoCardlessNode(WorkflowNode):
    integration_type = "automation-gocardless"
    connection_evidence = ConnectionEvidence(operation="list_creditors", noun="GoCardless creditor accounts")

    @classmethod
    def get_config_model(cls):
        return GoCardlessFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, GoCardlessFullConfig) or not self.config.credentials:
            raise ValueError("Supply a GoCardless access token")
        credential = self.config.credentials
        config = self.config.config
        method, route, resource = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path_fields = re.findall(r"\{(\w+)\}", route)
        for field in path_fields:
            route = route.replace("{" + field + "}", values.pop(field))
        headers = {"Authorization": "Bearer " + credential.access_token,
            "GoCardless-Version": "2015-07-06", "Accept": "application/json"}
        key = values.pop("idempotency_key", None)
        if key:
            headers["Idempotency-Key"] = key
        params, body = None, None
        listing = config.operation.startswith("list_")
        if method == "GET":
            params = values
        else:
            if config.operation.startswith("create_"):
                linked = "payment" if resource == "refunds" else "mandate"
                values["links"] = {linked: values.pop(linked + "_id")}
            if method == "PUT" and not values:
                raise ValueError("Choose at least one field to update")
            body = {resource: values}
        base = "https://api-sandbox.gocardless.com" if credential.environment == "sandbox" else "https://api.gocardless.com"
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, base + route, params=params, json=body, headers=headers)
        if not 200 <= response.status_code < 300:
            # Preserve the provider's rejection for the shared connection verdict,
            # without leaking a reflected credential or arbitrary error payload.
            message = "GoCardless request failed"
            try:
                raw = response.json().get("error", {}).get("message")
                if isinstance(raw, str):
                    message = raw[:2000].replace(credential.access_token, "[redacted]")
            except (ValueError, AttributeError):
                pass
            return {"status": "error", "error": message, "http_status": response.status_code,
                "write_outcome_unknown": method != "GET" and response.status_code >= 500}
        if len(response.content) > 10_000_000 or response.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
            raise ValueError("Expected bounded GoCardless JSON")
        result = response.json()
        if not isinstance(result, dict) or "error" in result:
            raise ValueError("Invalid GoCardless response")
        data = result.get(resource)
        if listing:
            if not isinstance(data, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in data):
                raise ValueError("Invalid GoCardless resource list")
            meta = result.get("meta")
            if not isinstance(meta, dict) or not isinstance(meta.get("cursors"), dict):
                raise ValueError("Missing GoCardless pagination metadata")
            following = meta["cursors"].get("after")
            if following is not None and (not isinstance(following, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", following)):
                raise ValueError("Invalid GoCardless cursor")
            return {"status": "success", "items": data, "meta": meta, "next_page_token": following, "has_more": following is not None}
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise ValueError("Invalid GoCardless resource")
        if path_fields and data["id"] != getattr(config, path_fields[0]):
            raise ValueError("GoCardless returned a different resource")
        return {"status": "success", "data": data, "http_status": response.status_code}
