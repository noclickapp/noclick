"""HitPay business API v1 operations, pinned to the published OpenAPI 1.0 contract.

Each operation performs one request. List results preserve the provider's paging
metadata; callers supply the returned cursor/page explicitly for subsequent pages.
Writes are never retried, including when the outcome is unknown after a timeout.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, SSRFError


class HitpayAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Hitpay API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.hitpayapp.com/apis/guide/online-payments",
            "x-credential-instructions": "Copy your business API key from the HitPay dashboard under Settings > API Keys. Paste the key without a header prefix. Select the environment where the key was issued. NoClick sends it only to HitPay's matching API host."
        })
    credential_type: Literal["hitpay_api_key"] = Field("hitpay_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", repr=False, json_schema_extra={"ui:widget": "password"})
    environment: Literal["production", "sandbox"] = Field("production", title="Environment")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your business API key")
        value = clean_secret(value, field_name="API key", key=True)
        if any(ch.isspace() or ord(ch) < 33 or ord(ch) == 127 for ch in value):
            raise ValueError("Paste the API key without whitespace or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def business_rules(self):
        if getattr(self, "operation", "") in {"create_payment_request", "update_payment_request"}:
            if "wifi_card_reader" in (getattr(self, "payment_methods", None) or []) and not self.wifi_terminal_id:
                raise ValueError("A terminal ID is required for wifi_card_reader")
        return self

class HitpayAddress0(_Input):
    line1: str = Field(...)
    line2: str | None = Field(None)
    city: str = Field(...)
    country: str = Field(...)
    state: str = Field(...)
    postal_code: str = Field(...)

class HitpayAddress1(_Input):
    line1: str = Field(...)
    line2: str | None = Field(None)
    city: str = Field(...)
    country: str = Field(...)
    state: str = Field(...)
    postal_code: str = Field(...)

class HitpayAddress2(_Input):
    city: str = Field(...)
    state: str = Field(...)
    street: str = Field(...)
    postal_code: str = Field(...)
    country: str | None = Field(None)

class HitpayAddress3(_Input):
    city: str = Field(...)
    state: str = Field(...)
    street: str = Field(...)
    postal_code: str = Field(...)
    country: str | None = Field(None)

class HitpayGetAccountStatusConfig(_Input):
    operation: Literal['get_account_status'] = Field('get_account_status', json_schema_extra={"ui:hidden": True})

class HitpayCreatePaymentRequestConfig(_Input):
    operation: Literal['create_payment_request'] = Field('create_payment_request', json_schema_extra={"ui:hidden": True})
    amount: float | None = Field(None, ge=0.3, le=999999999.99, description="It's optional field. Amount related to the payment. Example: 2500. If we pass, it should be greater than 0.3 and less than 999999999.99")
    currency: str = Field(..., max_length=3, description="It's required field. Currency related to the payment.")
    payment_methods: list[str] | None = Field(None, description="They're available payment methods supported on your account.(Example: paynow_online , card, wechat, alipay, grabpay_direct, grabpay_paylater, shopee_pay ... etc.). If we don't pass, use the available methods")
    email: EmailStr | None = Field(None, description='Buyer’s email')
    name: str | None = Field(None, description='Buyer’s name')
    phone: str | None = Field(None, description='Buyer’s phone number and should be in E.164 format. Example: +6591234567')
    wifi_terminal_id: str | None = Field(None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="It's terminal id and it's required if payment method is wifi_card_reader")
    staff_id: UUID | None = Field(None, description="It's active staff id from the dashboard")
    location_id: UUID | None = Field(None, description='The active location belongs to business. Support both `location_id` and `business_location_id` for backward compatibility, but we recommend using `business_location_id` for future use.')
    business_location_id: UUID | None = Field(None, description='The active location belongs to business.')
    purpose: str | None = Field(None, max_length=255, description='Purpose of the Payment request.')
    reference_number: str | None = Field(None, max_length=255, description='Arbitrary reference number that you can map to your internal reference number. This value cannot be edited by the customer')
    redirect_url: AnyHttpUrl | None = Field(None, max_length=1028, description='URL where we redirect the user after a payment. Query arguments reference (payment request id) and status are sent along')
    webhook: AnyHttpUrl | None = Field(None, description='URL where our server do POST request after a payment If done')
    allow_repeated_payments: Literal['true', 'false'] | None = Field(None, description='If set to true, multiple payments can be paid on a payment request link. Default value is false')
    expiry_date: str | None = Field(None, description='Time after which the payment link will be expired (time in SG with YYYY-MM-DD HH:mm:ss format). Applicable for repeated payments.')
    expires_after: str | None = Field(None, description='E.g "30 mins" Other supported keys are "mins", "hours", "days"')
    send_email: Literal['true', 'false'] | None = Field(None, description='It\'s "true" or "false". If set to true, an email receipt will be sent to the customer after the payment is completed. Default is false')
    send_sms: Literal['true', 'false'] | None = Field(None, description='It\'s "true" or "false". If set to "true", SMS will be sent to the customer after the payment is completed. Default is false')
    address: HitpayAddress0 | None = Field(None)
    generate_qr: bool | None = Field(None, description='Only valid for paynow_online, qrph_netbank and shopee_pay if generate_qr was true')
    metadata: dict[str, str] | None = Field(None, description='Support the key-value. The value must be string type, and the max length of the value is 500 characters, up to 50 key-value. Example: {"car_model": "toyota", "car_color": "red"}')

class HitpayGetPaymentRequestConfig(_Input):
    operation: Literal['get_payment_request'] = Field('get_payment_request', json_schema_extra={"ui:hidden": True})
    request_id: UUID = Field(...)

class HitpayUpdatePaymentRequestConfig(_Input):
    operation: Literal['update_payment_request'] = Field('update_payment_request', json_schema_extra={"ui:hidden": True})
    request_id: UUID = Field(...)
    amount: float = Field(..., ge=0.3, le=999999999.99, description="It's required field. Amount related to the payment.")
    currency: str = Field(..., max_length=3, description='Currency related to the payment.')
    payment_methods: list[str] | None = Field(None, description="Payment method type (paynow_online , card, wechat, alipay, grabpay_direct, grabpay_paylater, shopee_pay, zip, fpx). If we don't pass, use the available methods")
    email: EmailStr | None = Field(None, description='Buyer’s email')
    name: str | None = Field(None, description='Buyer’s name')
    phone: str | None = Field(None, description='Buyer’s phone number')
    wifi_terminal_id: str | None = Field(None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="It's terminal id and it's required if payment method is wifi_card_reader")
    staff_id: UUID | None = Field(None, description="It's active staff id from the dashboard")
    purpose: str | None = Field(None, max_length=255, description='Purpose of the Payment request.')
    reference_number: str | None = Field(None, max_length=255, description='Arbitrary reference number that you can map to your internal reference number. This value cannot be edited by the customer')
    redirect_url: AnyHttpUrl | None = Field(None, max_length=1028, description='URL where we redirect the user after a payment. Query arguments reference (payment request id) and status are sent along')
    webhook: AnyHttpUrl | None = Field(None, description='URL where our server do POST request after a payment If done')
    allow_repeated_payments: Literal['true', 'false'] | None = Field(None, description='If set to true, multiple payments can be paid on a payment request link. Default value is false')
    expiry_date: str | None = Field(None, description='Time after which the payment link will be expired(time in SG with YYYY-MM-DD HH:mm:ss format). Applicable for repeated payments. Default is Null')
    expires_after: str | None = Field(None, description='E.g "30 mins" Other supported keys are "mins", "hours", "days"')
    send_email: Literal['true', 'false'] | None = Field(None, description='It\'s "true" or "false". If set to true, an email receipt will be sent to the customer after the payment is completed. Default is false')
    send_sms: Literal['true', 'false'] | None = Field(None, description='It\'s "true" or "false". If set to "true", SMS will be sent to the customer after the payment is completed. Default is false')
    address: HitpayAddress1 | None = Field(None)
    generate_qr: bool | None = Field(None, description='Only valid for payment methods:  paynow_online, qrph_netbank and shopee_pay if generate_qr was true')

class HitpayDeletePaymentRequestConfig(_Input):
    operation: Literal['delete_payment_request'] = Field('delete_payment_request', json_schema_extra={"ui:hidden": True})
    request_id: UUID = Field(...)

class HitpayListCustomersConfig(_Input):
    operation: Literal['list_customers'] = Field('list_customers', json_schema_extra={"ui:hidden": True})
    per_page: Literal[5, 10, 20, 25, 50, 100] | None = Field(None, ge=1)
    cursor: str | None = Field(None, max_length=4096)

class HitpayCreateCustomerConfig(_Input):
    operation: Literal['create_customer'] = Field('create_customer', json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, description='The name of the customer')
    email: EmailStr = Field(..., description='The email of the customer')
    phone_number: str = Field(..., description='The phone number of the customer')
    phone_number_country_code: str | None = Field(None, description='The country code of the phone number')
    remark: str | None = Field(None, max_length=255, description='The remark of the customer')
    birth_date: date | None = Field(None, description='The birth date of the customer')
    gender: str | None = Field(None, description='The gender of the customer')
    address: HitpayAddress2 | None = Field(None)

class HitpayGetCustomerConfig(_Input):
    operation: Literal['get_customer'] = Field('get_customer', json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")

class HitpayUpdateCustomerConfig(_Input):
    operation: Literal['update_customer'] = Field('update_customer', json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    name: str | None = Field(None, description='The name of the customer')
    email: EmailStr | None = Field(None, description='The email of the customer')
    phone_number: str | None = Field(None, description='The phone number of the customer')
    phone_number_country_code: str | None = Field(None, description='The country code of the phone number')
    remark: str | None = Field(None, description='The remark of the customer')
    birth_date: date | None = Field(None, description='The birth date of the customer')
    gender: str | None = Field(None, description='The gender of the customer')
    address: HitpayAddress3 | None = Field(None)

class HitpayDeleteCustomerConfig(_Input):
    operation: Literal['delete_customer'] = Field('delete_customer', json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")

class HitpayListChargesConfig(_Input):
    operation: Literal['list_charges'] = Field('list_charges', json_schema_extra={"ui:hidden": True})
    per_page: int | None = Field(None, ge=1)
    cursor: str | None = Field(None, max_length=4096, description="The cursor parameter accepts a next_cursor value obtained from the previous response's meta object (meta.next_cursor). Use this parameter to fetch the next page of results when implementing pagination.")
    keywords: str | None = Field(None, max_length=4096)
    status: Literal['succeeded', 'failed', 'refunded'] | None = Field(None)
    location_ids: list[UUID] | None = Field(None)
    user_ids: list[str] | None = Field(None)
    statuses: list[Literal['success', 'succeeded_manually', 'pending', 'failed', 'refunded', 'cancelled', 'partially_refunded', 'void']] | None = Field(None)
    date_from: str | None = Field(None)
    date_to: str | None = Field(None)
    amount_from: float | None = Field(None)
    amount_to: float | None = Field(None)
    payment_request_id: UUID | None = Field(None)
    customer_id: UUID | None = Field(None)
    payout_id: UUID | None = Field(None)

class HitpayGetChargeConfig(_Input):
    operation: Literal['get_charge'] = Field('get_charge', json_schema_extra={"ui:hidden": True})
    charge_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")

class HitpayCreateRefundConfig(_Input):
    operation: Literal['create_refund'] = Field('create_refund', json_schema_extra={"ui:hidden": True})
    amount: float = Field(..., description='The remaining amount to be refunded.')
    payment_id: UUID = Field(..., description='Payment ID for the successful payment request')
    webhook: AnyHttpUrl | None = Field(None, description='The webhook URL')
    send_email: Literal['true', 'false'] | None = Field(None)
    email: EmailStr | None = Field(None)

class HitpayGetRefundConfig(_Input):
    operation: Literal['get_refund'] = Field('get_refund', json_schema_extra={"ui:hidden": True})
    refund_id: UUID = Field(...)

class HitpayGetBalancesConfig(_Input):
    operation: Literal['get_balances'] = Field('get_balances', json_schema_extra={"ui:hidden": True})

class HitpayListPayoutsConfig(_Input):
    operation: Literal['list_payouts'] = Field('list_payouts', json_schema_extra={"ui:hidden": True})
    status: Literal['scheduled', 'processing', 'paid', 'failed', 'canceled', 'pending'] | None = Field(None)
    created_at_from: date | None = Field(None)
    created_at_to: date | None = Field(None)
    per_page: int | None = Field(None, ge=1)
    cursor: str | None = Field(None, max_length=4096, description="The cursor parameter accepts a next_cursor value obtained from the previous response's meta object (meta.next_cursor).")

class HitpayGetPayoutConfig(_Input):
    operation: Literal['get_payout'] = Field('get_payout', json_schema_extra={"ui:hidden": True})
    payout_id: UUID = Field(...)

class HitpayListSubscriptionPlansConfig(_Input):
    operation: Literal['list_subscription_plans'] = Field('list_subscription_plans', json_schema_extra={"ui:hidden": True})
    per_page: float | None = Field(None, ge=1)
    page: float | None = Field(None, ge=1)

class HitpayGetSubscriptionPlanConfig(_Input):
    operation: Literal['get_subscription_plan'] = Field('get_subscription_plan', json_schema_extra={"ui:hidden": True})
    plan_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")

HitpayConfig = Annotated[Union[HitpayGetAccountStatusConfig, HitpayCreatePaymentRequestConfig, HitpayGetPaymentRequestConfig, HitpayUpdatePaymentRequestConfig, HitpayDeletePaymentRequestConfig, HitpayListCustomersConfig, HitpayCreateCustomerConfig, HitpayGetCustomerConfig, HitpayUpdateCustomerConfig, HitpayDeleteCustomerConfig, HitpayListChargesConfig, HitpayGetChargeConfig, HitpayCreateRefundConfig, HitpayGetRefundConfig, HitpayGetBalancesConfig, HitpayListPayoutsConfig, HitpayGetPayoutConfig, HitpayListSubscriptionPlansConfig, HitpayGetSubscriptionPlanConfig], Field(discriminator="operation")]


class HitpayFullConfig(NodeConfig[HitpayConfig, HitpayAPIKeyCredential]):
    pass


ROUTES = {'get_account_status': ('GET', '/v1/account-status', [], [], []),
 'create_payment_request': ('POST',
                            '/v1/payment-requests',
                            [],
                            [],
                            ['amount',
                             'currency',
                             'payment_methods',
                             'email',
                             'name',
                             'phone',
                             'wifi_terminal_id',
                             'staff_id',
                             'location_id',
                             'business_location_id',
                             'purpose',
                             'reference_number',
                             'redirect_url',
                             'webhook',
                             'allow_repeated_payments',
                             'expiry_date',
                             'expires_after',
                             'send_email',
                             'send_sms',
                             'address',
                             'generate_qr',
                             'metadata']),
 'get_payment_request': ('GET', '/v1/payment-requests/{request_id}', ['request_id'], [], []),
 'update_payment_request': ('PUT',
                            '/v1/payment-requests/{request_id}',
                            ['request_id'],
                            [],
                            ['amount',
                             'currency',
                             'payment_methods',
                             'email',
                             'name',
                             'phone',
                             'wifi_terminal_id',
                             'staff_id',
                             'purpose',
                             'reference_number',
                             'redirect_url',
                             'webhook',
                             'allow_repeated_payments',
                             'expiry_date',
                             'expires_after',
                             'send_email',
                             'send_sms',
                             'address',
                             'generate_qr']),
 'delete_payment_request': ('DELETE', '/v1/payment-requests/{request_id}', ['request_id'], [], []),
 'list_customers': ('GET', '/v1/customers', [], ['per_page', 'cursor'], []),
 'create_customer': ('POST',
                     '/v1/customers',
                     [],
                     [],
                     ['name',
                      'email',
                      'phone_number',
                      'phone_number_country_code',
                      'remark',
                      'birth_date',
                      'gender',
                      'address']),
 'get_customer': ('GET', '/v1/customers/{customer_id}', ['customer_id'], [], []),
 'update_customer': ('PATCH',
                     '/v1/customers/{customer_id}',
                     ['customer_id'],
                     [],
                     ['name',
                      'email',
                      'phone_number',
                      'phone_number_country_code',
                      'remark',
                      'birth_date',
                      'gender',
                      'address']),
 'delete_customer': ('DELETE', '/v1/customers/{customer_id}', ['customer_id'], [], []),
 'list_charges': ('GET',
                  '/v1/charges',
                  [],
                  ['per_page',
                   'cursor',
                   'keywords',
                   'status',
                   'location_ids',
                   'user_ids',
                   'statuses',
                   'date_from',
                   'date_to',
                   'amount_from',
                   'amount_to',
                   'payment_request_id',
                   'customer_id',
                   'payout_id'],
                  []),
 'get_charge': ('GET', '/v1/charges/{charge_id}', ['charge_id'], [], []),
 'create_refund': ('POST', '/v1/refund', [], [], ['amount', 'payment_id', 'webhook', 'send_email', 'email']),
 'get_refund': ('GET', '/v1/refund/{refund_id}', ['refund_id'], [], []),
 'get_balances': ('GET', '/v1/balances', [], [], []),
 'list_payouts': ('GET',
                  '/v1/payouts',
                  [],
                  ['status', 'created_at_from', 'created_at_to', 'per_page', 'cursor'],
                  []),
 'get_payout': ('GET', '/v1/payouts/{payout_id}', ['payout_id'], [], []),
 'list_subscription_plans': ('GET', '/v1/subscription-plan', [], ['per_page', 'page'], []),
 'get_subscription_plan': ('GET', '/v1/subscription-plan/{plan_id}', ['plan_id'], [], [])}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    return value


class HitpayNode(WorkflowNode):
    integration_type = "automation-hitpay"
    connection_evidence = ConnectionEvidence(noun="customers", operation="list_customers")

    @classmethod
    def get_config_model(cls):
        return HitpayFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect your HitPay business API key")
        config = self.config.config
        credential = self.config.credentials
        method, path, path_fields, query_fields, body_fields = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        for field in path_fields:
            path = path.replace("{" + field + "}", quote(str(values[field]), safe=""))
        params = []
        for field in query_fields:
            if field in values:
                value = values[field]
                for item in value if isinstance(value, list) else [value]:
                    params.append((field, str(item).lower() if isinstance(item, bool) else str(item)))
        body = {field: values[field] for field in body_fields if field in values}
        host = "https://api.hit-pay.com" if credential.environment == "production" else "https://api.sandbox.hit-pay.com"
        headers = {"X-BUSINESS-API-KEY": credential.api_key, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, host + path, params=params,
                    headers=headers, **({"json": body} if body_fields else {}))
        except (httpx.HTTPError, SSRFError):
            result = {"status": "error", "error": "HitPay request did not complete", "outcome_unknown": method != "GET"}
        else:
            if not 200 <= response.status_code < 300:
                # Keep the provider's rejection text for the shared connect verdict.
                try:
                    error = response.json()
                    message = error.get("message") or error.get("error") if isinstance(error, dict) else None
                except ValueError:
                    message = None
                result = {"status": "error", "http_status": response.status_code,
                    "error": str(message or "HitPay request failed")[:1000]}
            elif response.status_code == 204:
                result = {"status": "success", "data": None}
            elif not response.content:
                result = ({"status": "error", "error": "HitPay returned an empty read response"}
                    if method == "GET" else {"status": "success", "data": None})
            else:
                try:
                    data = response.json()
                    if not isinstance(data, (dict, list)):
                        raise ValueError("Expected JSON object or list")
                    if isinstance(data, dict) and (data.get("error") or data.get("errors") or data.get("success") is False):
                        result = {"status": "error", "error": str(data.get("message") or data.get("error") or data.get("errors"))[:1000]}
                    else:
                        result = {"status": "success", "data": data}
                        if isinstance(data, dict) and isinstance(data.get("data"), list):
                            result["items"] = data["data"]
                except ValueError:
                    result = {"status": "error", "error": "HitPay returned an unexpected response", "outcome_unknown": method != "GET"}
        result = _redact(result, credential.api_key)
        await self.emit(result)
        return result
