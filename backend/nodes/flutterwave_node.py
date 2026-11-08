"""Flutterwave v4 operations using an existing, short-lived bearer access token."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URLS = {
    "sandbox": "https://developersandbox-api.flutterwave.com",
    "production": "https://f4bexperience.flutterwave.com",
}


class FlutterwaveAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="Flutterwave Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.flutterwave.com/v4.0.0/docs/authentication",
            "x-credential-instructions": "Paste a Flutterwave v4 access token generated with your client credentials, and select its environment. Access tokens expire after 10 minutes: replace the token before running again after expiry. NoClick does not generate or refresh tokens. A v3 secret key does not work with this integration.",
        })
    credential_type: Literal["flutterwave_access_token"] = Field("flutterwave_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1, max_length=16384, json_schema_extra={"ui:widget": "password"})
    environment: Literal["sandbox", "production"] = Field("sandbox", title="Environment")

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the access token without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


ResourceID = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$")]
Currency = Literal[
    'AED', 'AFN', 'ALL', 'AMD', 'ANG', 'AOA', 'AQD', 'ARS', 'AUD', 'AZN', 'BAM', 'BBD', 'BDT', 'BGN', 'BHD', 'BIF', 'BMD', 'BND', 'BOB', 'BRL', 'BSD', 'BWP', 'BYR', 'BZD', 'CAD', 'CDF', 'CHF', 'CLP', 'CNY', 'COP', 'CRC', 'CUP', 'CVE', 'CYP', 'CZK', 'DJF', 'DKK', 'DOP', 'DZD', 'ECS', 'EEK', 'EGP', 'ETB', 'EUR', 'FJD', 'FKP', 'GBP', 'GEL', 'GGP', 'GHS', 'GIP', 'GMD', 'GNF', 'GTQ', 'GYD', 'HKD', 'HNL', 'HRK', 'HTG', 'HUF', 'IDR', 'ILS', 'INR', 'IQD', 'IRR', 'ISK', 'JMD', 'JOD', 'JPY', 'KES', 'KGS', 'KHR', 'KMF', 'KPW', 'KRW', 'KWD', 'KYD', 'KZT', 'LAK', 'LBP', 'LKR', 'LRD', 'LSL', 'LTL', 'LVL', 'LYD', 'MAD', 'MDL', 'MGA', 'MKD', 'MMK', 'MNT', 'MOP', 'MRO', 'MTL', 'MUR', 'MVR', 'MWK', 'MXN', 'MYR', 'MZN', 'NAD', 'NGN', 'NIO', 'NOK', 'NPR', 'NZD', 'OMR', 'PAB', 'PEN', 'PGK', 'PHP', 'PKR', 'PLN', 'PYG', 'QAR', 'RON', 'RSD', 'RUB', 'RWF', 'SAR', 'SBD', 'SCR', 'SDG', 'SEK', 'SGD', 'SKK', 'SLL', 'SOS', 'SRD', 'STD', 'SVC', 'SYP', 'SZL', 'THB', 'TJS', 'TMT', 'TND', 'TOP', 'TRY', 'TTD', 'TWD', 'TZS', 'UAH', 'UGX', 'USD', 'UYU', 'UZS', 'VEF', 'VND', 'VUV', 'XAF', 'XCD', 'XOF', 'XPF', 'YER', 'ZAR', 'ZMK', 'ZWD', 'ZMW', 'USDC', 'USDT', 'RLUSD'
]
Reference = Annotated[str, Field(min_length=6, max_length=42, pattern=r"^[A-Za-z0-9-]+$")]
Amount = Annotated[float, Field(ge=0.01, allow_inf_nan=False)]


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number; this operation returns one page only.")
    size: int = Field(10, ge=10, le=50)


class _PeriodPage(_Page):
    from_datetime: datetime | None = Field(None, description="Inclusive start in ISO 8601 format, sent as from.")
    to_datetime: datetime | None = Field(None, description="End in ISO 8601 format, sent as to.")

    @model_validator(mode="after")
    def dates(self):
        if self.from_datetime is not None and self.to_datetime is not None:
            try:
                if self.from_datetime >= self.to_datetime:
                    raise ValueError("End must be after start")
            except TypeError:
                raise ValueError("Use matching time zones for the date range") from None
        return self


class _Detail(_Input):
    id: ResourceID = Field(..., title="Resource ID")


class _Write(_Input):
    idempotency_key: str = Field(..., min_length=12, max_length=255,
        description="Unique key for this intended write. Reuse the same key when retrying the same write, and use a new key for a new write.")

    @field_validator("idempotency_key")
    @classmethod
    def header(cls, value):
        if not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Use a visible ASCII idempotency key without spaces")
        return value


class CustomerName(_Input):
    first: str | None = None
    middle: str | None = None
    last: str | None = None

    @field_validator("first", "middle", "last")
    @classmethod
    def name_part(cls, value):
        if value is not None and not re.fullmatch(r"(?![ ,.'-]*$)[A-Za-z ,.'-]{2,50}", value):
            raise ValueError("Use a name of 2 to 50 letters, spaces or name punctuation")
        return value


class CustomerPhone(_Input):
    country_code: str = Field(..., pattern=r"^[0-9]{1,3}$")
    number: str = Field(..., pattern=r"^[0-9]{7,10}$")


class CustomerAddress(_Input):
    line1: str = Field(..., min_length=1)
    line2: str | None = None
    city: str = Field(..., min_length=1)
    state: str = Field(..., min_length=1)
    country: str = Field(..., pattern=r"^[A-Z]{2}$")
    postal_code: str = Field(..., min_length=1)


class _CustomerFields(_Input):
    name: CustomerName | None = None
    phone: CustomerPhone | None = None
    address: CustomerAddress | None = None
    meta: dict[str, str] | None = None


class ListCustomers(_Page):
    operation: Literal["list_customers"] = "list_customers"


class GetCustomer(_Detail):
    operation: Literal["get_customer"] = "get_customer"


class CreateCustomer(_Write, _CustomerFields):
    operation: Literal["create_customer"] = "create_customer"
    email: str = Field(..., min_length=3, description="Customer email address.")

    @field_validator("email")
    @classmethod
    def customer_email(cls, value):
        if not re.fullmatch(r"[a-zA-Z0-9_+&*-]+(?:\.[a-zA-Z0-9_+&*-]+)*@(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}", value):
            raise ValueError("Use a customer email address")
        return value


class UpdateCustomer(_Detail, _CustomerFields):
    operation: Literal["update_customer"] = "update_customer"

    @model_validator(mode="after")
    def changed(self):
        if all(getattr(self, key) is None for key in _CustomerFields.model_fields):
            raise ValueError("Provide at least one customer field to update")
        return self


class ListCharges(_PeriodPage):
    operation: Literal["list_charges"] = "list_charges"
    reference: str | None = None
    customer_id: ResourceID | None = None
    payment_method_id: ResourceID | None = None


class GetCharge(_Detail):
    operation: Literal["get_charge"] = "get_charge"


class CreateCharge(_Write):
    operation: Literal["create_charge"] = "create_charge"
    amount: Amount
    currency: Currency
    customer_id: ResourceID
    payment_method_id: ResourceID
    reference: Reference
    redirect_url: str | None = Field(None, description="Payment redirect URL; returned actions may require customer authorization.")
    meta: dict[str, str] | None = None


class ListCheckoutSessions(_Page):
    operation: Literal["list_checkout_sessions"] = "list_checkout_sessions"


class GetCheckoutSession(_Detail):
    operation: Literal["get_checkout_session"] = "get_checkout_session"


class CreateCheckoutSession(_Write):
    operation: Literal["create_checkout_session"] = "create_checkout_session"
    amount: Amount
    currency: Currency
    customer_id: ResourceID
    reference: Reference
    redirect_url: str = Field(..., min_length=1)
    max_retry_attempts: int = Field(3, ge=0, le=10)
    session_duration: int | None = Field(None, ge=5, le=2880)


class ListPaymentMethods(_Page):
    operation: Literal["list_payment_methods"] = "list_payment_methods"


class GetPaymentMethod(_Detail):
    operation: Literal["get_payment_method"] = "get_payment_method"


class ListTransfers(_Input):
    operation: Literal["list_transfers"] = "list_transfers"
    size: int = Field(10, ge=10, le=50)
    next_cursor: str | None = Field(None, description="Use data.cursor.next from the preceding response. Returns one page.")
    recipient_id: ResourceID | None = None


class GetTransfer(_Detail):
    operation: Literal["get_transfer"] = "get_transfer"


class TransferAmount(_Input):
    value: float = Field(..., ge=1, allow_inf_nan=False, description="Amount in the provider's documented smallest currency unit.")
    applies_to: Literal["destination_currency", "source_currency"]


class TransferInstruction(_Input):
    source_currency: Currency
    amount: TransferAmount
    recipient_id: ResourceID
    sender_id: ResourceID | None = None


class CreateTransfer(_Write):
    operation: Literal["create_transfer"] = "create_transfer"
    action: Literal["instant", "deferred"]
    payment_instruction: TransferInstruction
    reference: Reference | None = None
    narration: str | None = Field(None, min_length=1, max_length=180)
    meta: dict[str, str] | None = None


class ListRefunds(_PeriodPage):
    operation: Literal["list_refunds"] = "list_refunds"


class GetRefund(_Detail):
    operation: Literal["get_refund"] = "get_refund"


class CreateRefund(_Write):
    operation: Literal["create_refund"] = "create_refund"
    amount: Amount
    charge_id: ResourceID
    reason: Literal["duplicate", "fraudulent", "requested_by_customer", "expired_uncaptured_charge"]
    meta: dict[str, str] | None = None


class ListSettlements(_PeriodPage):
    operation: Literal["list_settlements"] = "list_settlements"


class GetSettlement(_Detail, _Page):
    operation: Literal["get_settlement"] = "get_settlement"


class ListWalletBalances(_Input):
    operation: Literal["list_wallet_balances"] = "list_wallet_balances"


class GetWalletBalance(_Input):
    operation: Literal["get_wallet_balance"] = "get_wallet_balance"
    currency: Currency


class ListVirtualAccounts(_PeriodPage):
    operation: Literal["list_virtual_accounts"] = "list_virtual_accounts"
    reference: str | None = None


class GetVirtualAccount(_Detail):
    operation: Literal["get_virtual_account"] = "get_virtual_account"


FlutterwaveConfig = Annotated[Union[
    ListCustomers, GetCustomer, CreateCustomer, UpdateCustomer, ListCharges, GetCharge, CreateCharge,
    ListCheckoutSessions, GetCheckoutSession, CreateCheckoutSession, ListPaymentMethods, GetPaymentMethod,
    ListTransfers, GetTransfer, CreateTransfer, ListRefunds, GetRefund, CreateRefund, ListSettlements,
    GetSettlement, ListWalletBalances, GetWalletBalance, ListVirtualAccounts, GetVirtualAccount,
], Field(discriminator="operation")]


class FlutterwaveNodeConfig(NodeConfig[FlutterwaveConfig, FlutterwaveAccessTokenCredential]):
    pass


# Each exposed operation makes exactly one request from the pinned v4 contract.
ROUTES = {
    "list_customers": ("GET", "/customers"),
    "get_customer": ("GET", "/customers/{id}"),
    "create_customer": ("POST", "/customers"),
    "update_customer": ("PUT", "/customers/{id}"),
    "list_charges": ("GET", "/charges"),
    "get_charge": ("GET", "/charges/{id}"),
    "create_charge": ("POST", "/charges"),
    "list_checkout_sessions": ("GET", "/checkout/sessions"),
    "get_checkout_session": ("GET", "/checkout/sessions/{id}"),
    "create_checkout_session": ("POST", "/checkout/sessions"),
    "list_payment_methods": ("GET", "/payment-methods"),
    "get_payment_method": ("GET", "/payment-methods/{id}"),
    "list_transfers": ("GET", "/transfers"),
    "get_transfer": ("GET", "/transfers/{id}"),
    "create_transfer": ("POST", "/transfers"),
    "list_refunds": ("GET", "/refunds"),
    "get_refund": ("GET", "/refunds/{id}"),
    "create_refund": ("POST", "/refunds"),
    "list_settlements": ("GET", "/settlements"),
    "get_settlement": ("GET", "/settlements/{id}"),
    "list_wallet_balances": ("GET", "/wallets/balances"),
    "get_wallet_balance": ("GET", "/wallets/balances/{currency}"),
    "list_virtual_accounts": ("GET", "/virtual-accounts"),
    "get_virtual_account": ("GET", "/virtual-accounts/{id}"),
}


def _redact(value, token):
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()
                if key.lower() not in {"access_token", "refresh_token", "client_secret", "credentials", "password", "secret_key", "api_key"}}
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    return value.replace(token, "[redacted]") if isinstance(value, str) else value


class FlutterwaveNode(WorkflowNode):
    integration_type = "automation-flutterwave"
    connection_evidence = ConnectionEvidence(noun="customers", operation="list_customers", label_keys=("email", "id"))

    @classmethod
    def get_config_model(cls):
        return FlutterwaveNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Flutterwave v4 access token")
        credential = self.config.credentials
        op = self.config.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation", "idempotency_key"})
        for key in ("id", "currency"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", values.pop(key))
        headers = {"Authorization": "Bearer " + credential.access_token,
                   "Accept": "application/json", "X-Trace-Id": str(uuid4())}
        if isinstance(op, _Write):
            headers["X-Idempotency-Key"] = op.idempotency_key
        if method == "GET":
            params = {{"from_datetime": "from", "to_datetime": "to", "next_cursor": "next"}.get(key, key): value for key, value in values.items()}
            request = {"params": params}
        else:
            request = {"json": values}
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URLS[credential.environment] + path, headers=headers, **request)
        except httpx.HTTPError:
            raise ValueError("Flutterwave request did not complete" + ("; write outcome is unknown; inspect before retrying with the same idempotency key" if method != "GET" else "")) from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Flutterwave returned a non-JSON response" + ("; write outcome is unverified" if method != "GET" else "")) from None
        token = credential.access_token
        accepted_statuses = {"success", "pending"} if op.operation == "create_charge" else {"success"}
        if response.status_code >= 300 or not isinstance(payload, dict) or payload.get("status") not in accepted_statuses:
            message = (payload.get("message") or (payload.get("error", {}).get("message") if isinstance(payload.get("error"), dict) else None) or "Flutterwave refused the request") if isinstance(payload, dict) else "Flutterwave response is invalid"
            output = {"status": "error", "success": False, "http_status": response.status_code, "message": _redact(str(message), token)}
            if method != "GET":
                output["write_outcome"] = "unverified"
        else:
            data = payload.get("data")
            expected = list if op.operation.startswith("list_") and op.operation != "list_transfers" else dict
            if not isinstance(data, expected):
                raise ValueError("Flutterwave returned an invalid data envelope" + ("; write outcome is unverified" if method != "GET" else ""))
            if op.operation == "list_transfers" and not isinstance(data.get("transfers"), list):
                raise ValueError("Flutterwave returned an invalid transfer page")
            output = {"status": "success", "success": True, "http_status": response.status_code,
                      "data": _redact(data, token)}
            if "meta" in payload:
                output["meta"] = _redact(payload["meta"], token)
            if op.operation.startswith("list_") or op.operation == "get_settlement":
                output["page_only"] = True
            if method != "GET":
                output["request_accepted"] = True
                # Acceptance can return pending, failed or requires_action resource states.
                output["resource_status"] = data.get("status")
        await self.emit(output)
        return output
