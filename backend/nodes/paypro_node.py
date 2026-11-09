"""PayPro v1 payments, customers, subscriptions, refunds and balances.

Contract: https://docs.paypro.nl/_spec/reference/api.yaml
Pagination: https://docs.paypro.nl/reference/pagination
Each operation sends one request; writes are never retried automatically.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote, urlsplit, parse_qs

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.paypro.nl"


class PayProAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="PayPro API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.paypro.nl/reference/getting-started",
            "x-credential-instructions": "Generate an API key in your approved PayPro account's dashboard and paste it here. NoClick sends it as a bearer token to api.paypro.nl. Use a test key to test workflows before connecting a live key.",
        })
    credential_type: Literal["paypro_api_key"] = Field("paypro_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name.endswith("_id") or info.field_name in {"customer", "mandate"}:
            if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value)):
                raise ValueError("Use a single PayPro resource ID")
        return value


class _Page(_Input):
    """One cursor page; next_cursor is returned when more results exist."""
    limit: int = Field(10, ge=1, le=100, description="Maximum results in this page (1–100).")
    cursor: Optional[str] = Field(None, max_length=4096, description="Use next_cursor from the previous result for this same operation and parent.")


class PayProCreateCustomer(_Input):
    email: Optional[str] = Field(None, description="Customer's email address")
    first_name: Optional[str] = Field(None, description="Customer's first name")
    last_name: Optional[str] = Field(None, description="Customer's last name")
    address: Optional[str] = Field(None, description="Customer's address")
    postal: Optional[str] = Field(None, description="Customer's postal code or ZIP")
    city: Optional[str] = Field(None, description="Customer's city")
    country: Optional[str] = Field(None, description="Customer's country in [ISO-3166-1 alpha-2](https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2) format, example: 'NL'")
    vat_number: Optional[str] = Field(None, description="Customer's company vat number")
    company_name: Optional[str] = Field(None, description="Customer's company name")
    phone_number: Optional[str] = Field(None, description="Customer's phone number")


class PayProUpdateCustomer(_Input):
    email: Optional[str] = Field(None, description="Customer's email address")
    first_name: Optional[str] = Field(None, description="Customer's first name")
    last_name: Optional[str] = Field(None, description="Customer's last name")
    address: Optional[str] = Field(None, description="Customer's address")
    postal: Optional[str] = Field(None, description="Customer's postal code or ZIP")
    city: Optional[str] = Field(None, description="Customer's city")
    country: Optional[str] = Field(None, description="Customer's country in [ISO-3166-1 alpha-2](https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2) format, example: 'NL'")
    vat_number: Optional[str] = Field(None, description="Customer's company vat number")
    company_name: Optional[str] = Field(None, description="Customer's company name")
    phone_number: Optional[str] = Field(None, description="Customer's phone number")


class PayProCreatePayment(_Input):
    amount: StrictInt = Field(..., description='The amount that the customer will have to pay.')
    currency: Literal['EUR'] = Field(..., description="The currency of the payment. Only 'EUR' is supported.")
    description: str = Field(..., description='The description of the payment. This will be shown to your customer and will be visible in the dashboard.')
    return_url: Optional[str] = Field(None, description='The URL where the customer will be send to after the payment has been processed.', json_schema_extra={"format": "uri"})
    cancel_url: Optional[str] = Field(None, description='The URL where the customer will be send to after the payment has been canceled by the customer.', json_schema_extra={"format": "uri"})
    pay_methods: Optional[list[Literal['afterpay', 'bancontact', 'bank-transfer', 'creditcard', 'direct-debit', 'ideal', 'ideal-qr', 'klarna-paynow', 'paypal']]] = Field(None, description='The allowed pay methods of the payment. If only one pay method is specified, it will be set as the payment pay method. Cannot be used together with a `mandate`.')
    metadata: Optional[dict] = Field(None, description='You can put in random data that you like to save alongside the payment. When you fetch the payment this will be returned in the `metadata` field.')
    customer: Optional[str] = Field(None, description='ID of the customer that pays. This field is optional, if nothing is given we create a new Customer. Cannot be used together with a `mandate`.')
    mandate: Optional[str] = Field(None, description='ID of the mandate for payment')
    setup_mandate: Optional[StrictBool] = Field(None, description='Indicates if the payment should create a mandate after it has been paid. This allows to setup recurring payments without the need to use a `Subscription` or `InstallmentPlan`. Needs the `customer` parameter to be set as well. Cannot be used together with a `mandate`.')
    locale: Optional[Literal['de', 'en', 'fr', 'nl']] = Field(None, description='Specifies the language to be used for the payment pages shown to the customer. If no locale or an invalid locale is specified we will ignore it and choose the locale based on the account settings or the locale used by the customer.')


class PayProCreateRefund(_Input):
    amount: StrictInt = Field(..., description="The amount that will be refunded to the customer. This can be an amount lower than the total amount to do a partial refund. You can't refund more than the total amount of the original payment.")
    description: Optional[str] = Field(None, description='The description of the refund. This will be shown to your customer and will be visible in the dashboard.')
    reason: Optional[str] = Field(None, description='The reason for this refund.')
    account_holder_name: Optional[str] = Field(None, description="Name of the account holder of the account where the refund will be credited. This is a required field for the pay methods 'bancontact' and 'creditcard'. For other pay methods we will use the orginal customer information provided by the pay method to do the refund.")
    iban: Optional[str] = Field(None, description="IBAN of the account where the refund will be credited. required field for the pay methods 'bancontact' and 'creditcard'. For other pay methods we will use the orginal customer information provided by the pay method to do the refund.")
    metadata: Optional[dict] = Field(None, description='You can put in random data that you like to save alongside the refund. When you fetch the refund this will be returned in the `metadata` field.')


class PayProCreateSubscriptionPaymentDetails(_Input):
    return_url: Optional[str] = Field(None, description='The URL where the customer will be send to after the payment has been processed.', json_schema_extra={"format": "uri"})
    cancel_url: Optional[str] = Field(None, description='The URL where the customer will be send to after the payment has been canceled by the customer.', json_schema_extra={"format": "uri"})


class PayProCreateSubscriptionPeriod(_Input):
    amount: StrictInt = Field(..., description='The amount in cents that the customer will have to pay.')
    vat: Optional[float] = Field(None, ge=0, le=30, description='The vat included in the amount. Accepted values: from 0 till 30')
    interval: Literal['day', 'week', 'month', 'year'] = Field(..., description='The interval of each period. Accepted values: `day`, `week`, `month` or `year`')
    multiplier: StrictInt = Field(..., ge=1, description='The multiplier of the interval between periods. Example: `interval=month` and `mulitplier=3` will create a new period every 3 months.')


class PayProCreateSubscriptionFirstPeriod(_Input):
    amount: StrictInt = Field(..., description='The amount in cents that the customer will have to pay.')
    vat: Optional[float] = Field(None, ge=0, le=30, description='The vat included in the amount. Accepted values: from 0 till 30')
    interval: Literal['day', 'week', 'month', 'year'] = Field(..., description='The interval of each period. Accepted values: `day`, `week`, `month` or `year`')
    multiplier: StrictInt = Field(..., ge=1, description='The multiplier of the interval between periods. Example: `interval=month` and `mulitplier=3` will create a new period every 3 months.')


class PayProCreateSubscription(_Input):
    """Create a subscription using the customer authorization-payment flow."""
    customer: str = Field(..., description='ID of the customer that subscribes. Cannot be used together with a `mandate`.')
    description: str = Field(..., description='Description of the subscription. This will be shown to customers and in the PayPro dashboard')
    currency: Literal["EUR"] = Field(..., description="The currency of the subscription. Only 'EUR' is supported")
    start_at: Optional[str] = Field(None, description='Date when the subscription will start. When left empty, it will start at creation')
    cancel_at: Optional[str] = Field(None, description='Date at which the subscription will be canceled. When left empty, the subscription will be active until manually canceled')
    expire_at: Optional[str] = Field(None, description='Date at which the subscription link will expire if the subscription has not started yet. When left empty, the subscription link will not expire')
    pay_methods: Optional[list[Literal['bancontact', 'bank-transfer', 'creditcard', 'direct-debit', 'ideal', 'ideal-qr', 'klarna-paynow']]] = Field(None, description='Pay methods that can be used to start the subscription. Using this creates the subscription with the `authorization` flow and will start the subscription when the first payment is paid. Use the checkout link in the `links` field to redirect the customer. Cannot be used together with a `mandate`.')
    payment_details: Optional[PayProCreateSubscriptionPaymentDetails] = Field(None, description='Fields to be passed to the authorization payment.')
    period: PayProCreateSubscriptionPeriod = Field(..., description='Settings for when new periods should be created and with which amounts')
    first_period: Optional[PayProCreateSubscriptionFirstPeriod] = Field(None, description='Settings for when the first period should be created and with what amount')
    metadata: Optional[dict] = Field(None, description='You can put in random data that you like to save alongside the subscription. When you fetch the subscription this will be returned in the `metadata` field.')


class PayProUpdateSubscriptionPeriod(_Input):
    amount: Optional[StrictInt] = Field(None, description='The amount in cents that the customer will have to pay.')
    vat: Optional[float] = Field(None, ge=0, le=30, description='The vat included in the amount. Accepted values: from 0 till 30')
    interval: Optional[Literal['day', 'week', 'month', 'year']] = Field(None, description='The interval of each period. Accepted values: `day`, `week`, `month` or `year`')
    multiplier: Optional[StrictInt] = Field(None, description='The multiplier of the interval between periods. Example: `interval=month` and `mulitplier=3` will create a new period every 3 months.')


class PayProUpdateSubscriptionFirstPeriod(_Input):
    amount: Optional[StrictInt] = Field(None, description='The amount in cents that the customer will have to pay.')
    vat: Optional[float] = Field(None, ge=0, le=30, description='The vat included in the amount. Accepted values: from 0 till 30')
    interval: Optional[Literal['day', 'week', 'month', 'year']] = Field(None, description='The interval of each period. Accepted values: `day`, `week`, `month` or `year`')
    multiplier: Optional[StrictInt] = Field(None, description='The multiplier of the interval between periods. Example: `interval=month` and `mulitplier=3` will create a new period every 3 months.')


class PayProUpdateSubscription(_Input):
    description: Optional[str] = Field(None, description='Description of the subscription. This will be shown to customers and in the PayPro dashboard')
    mandate: Optional[str] = Field(None, description="ID of the mandate for subscription. Only approved 'direct-debit' customer's mandates are supported.")
    cancel_at: Optional[str] = Field(None, description='Date at which the subscription will be canceled. When left empty, the subscription will be active until manually canceled')
    expire_at: Optional[str] = Field(None, description='Date at which the subscription link will expire if the subscription has not started yet. When left empty, the subscription link will not expire')
    cancel_periods_on_cancellation: Optional[StrictBool] = Field(None, description='If `true`, canceling a subscription will also cancel any open and reversed periods.')
    period: Optional[PayProUpdateSubscriptionPeriod] = Field(None, description='Settings for when new periods should be created and with which amounts. When the Subscription is active updates to these settings will only affect new periods.')
    first_period: Optional[PayProUpdateSubscriptionFirstPeriod] = Field(None, description='Settings for when the first period should be created and with what amount. These settings can only be updated if the Subscription has not started yet.')
    next_debit_date: Optional[str] = Field(None, description='Date when the next payment period will be collected')


class PayProListCustomersConfig(_Page):
    """Retrieves a list of customers."""
    operation: Literal['list_customers'] = Field('list_customers', json_schema_extra={"ui:hidden": True})


class PayProGetCustomerConfig(_Input):
    """Retrieves a customer."""
    operation: Literal['get_customer'] = Field('get_customer', json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., description="PayPro resource ID from the dashboard or a list operation.")


class PayProCreateCustomerConfig(_Input):
    """Creates a customer."""
    operation: Literal['create_customer'] = Field('create_customer', json_schema_extra={"ui:hidden": True})
    body: PayProCreateCustomer = Field(..., description="Documented PayPro JSON fields; omitted optional fields are left unchanged.")


class PayProUpdateCustomerConfig(_Input):
    """Updates a customer."""
    operation: Literal['update_customer'] = Field('update_customer', json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., description="PayPro resource ID from the dashboard or a list operation.")
    body: PayProUpdateCustomer = Field(..., description="Documented PayPro JSON fields; omitted optional fields are left unchanged.")


class PayProListPaymentsConfig(_Page):
    """Retrieve a list of payments."""
    operation: Literal['list_payments'] = Field('list_payments', json_schema_extra={"ui:hidden": True})


class PayProGetPaymentConfig(_Input):
    """Retrieves a payment."""
    operation: Literal['get_payment'] = Field('get_payment', json_schema_extra={"ui:hidden": True})
    payment_id: str = Field(..., description="PayPro resource ID from the dashboard or a list operation.")


class PayProCreatePaymentConfig(_Input):
    """Creates a payment."""
    operation: Literal['create_payment'] = Field('create_payment', json_schema_extra={"ui:hidden": True})
    body: PayProCreatePayment = Field(..., description="Documented PayPro JSON fields; omitted optional fields are left unchanged.")


class PayProCancelPaymentConfig(_Input):
    """Cancels a payment."""
    operation: Literal['cancel_payment'] = Field('cancel_payment', json_schema_extra={"ui:hidden": True})
    payment_id: str = Field(..., description="PayPro resource ID from the dashboard or a list operation.")


class PayProListPaymentRefundsConfig(_Page):
    """Retrieves a list of refunds that belong to this payment.."""
    operation: Literal['list_payment_refunds'] = Field('list_payment_refunds', json_schema_extra={"ui:hidden": True})
    payment_id: str = Field(..., description="PayPro resource ID from the dashboard or a list operation.")


class PayProCreateRefundConfig(_Input):
    """Creates a refund for this payment.."""
    operation: Literal['create_refund'] = Field('create_refund', json_schema_extra={"ui:hidden": True})
    payment_id: str = Field(..., description="PayPro resource ID from the dashboard or a list operation.")
    body: PayProCreateRefund = Field(..., description="Documented PayPro JSON fields; omitted optional fields are left unchanged.")


class PayProListRefundsConfig(_Page):
    """Retrieve a list of refunds."""
    operation: Literal['list_refunds'] = Field('list_refunds', json_schema_extra={"ui:hidden": True})


class PayProGetRefundConfig(_Input):
    """Retrieves a refund."""
    operation: Literal['get_refund'] = Field('get_refund', json_schema_extra={"ui:hidden": True})
    refund_id: str = Field(..., description="PayPro resource ID from the dashboard or a list operation.")


class PayProCancelRefundConfig(_Input):
    """Cancels a refund."""
    operation: Literal['cancel_refund'] = Field('cancel_refund', json_schema_extra={"ui:hidden": True})
    refund_id: str = Field(..., description="PayPro resource ID from the dashboard or a list operation.")


class PayProListSubscriptionsConfig(_Page):
    """Retrieves a list of subscriptions."""
    operation: Literal['list_subscriptions'] = Field('list_subscriptions', json_schema_extra={"ui:hidden": True})


class PayProGetSubscriptionConfig(_Input):
    """Retrieves a subscription."""
    operation: Literal['get_subscription'] = Field('get_subscription', json_schema_extra={"ui:hidden": True})
    subscription_id: str = Field(..., description="PayPro resource ID from the dashboard or a list operation.")


class PayProCreateSubscriptionConfig(_Input):
    """Creates a subscription."""
    operation: Literal['create_subscription'] = Field('create_subscription', json_schema_extra={"ui:hidden": True})
    body: PayProCreateSubscription = Field(..., description="Documented PayPro JSON fields; omitted optional fields are left unchanged.")


class PayProUpdateSubscriptionConfig(_Input):
    """Updates a subscription."""
    operation: Literal['update_subscription'] = Field('update_subscription', json_schema_extra={"ui:hidden": True})
    subscription_id: str = Field(..., description="PayPro resource ID from the dashboard or a list operation.")
    body: PayProUpdateSubscription = Field(..., description="Documented PayPro JSON fields; omitted optional fields are left unchanged.")


class PayProCancelSubscriptionConfig(_Input):
    """Cancels a subscription."""
    operation: Literal['cancel_subscription'] = Field('cancel_subscription', json_schema_extra={"ui:hidden": True})
    subscription_id: str = Field(..., description="PayPro resource ID from the dashboard or a list operation.")


class PayProPauseSubscriptionConfig(_Input):
    """Pauses a subscription."""
    operation: Literal['pause_subscription'] = Field('pause_subscription', json_schema_extra={"ui:hidden": True})
    subscription_id: str = Field(..., description="PayPro resource ID from the dashboard or a list operation.")


class PayProResumeSubscriptionConfig(_Input):
    """Resumes a paused subscription."""
    operation: Literal['resume_subscription'] = Field('resume_subscription', json_schema_extra={"ui:hidden": True})
    subscription_id: str = Field(..., description="PayPro resource ID from the dashboard or a list operation.")


class PayProListCustomerSubscriptionsConfig(_Page):
    """Retrieves a list of subscriptions that belong to this customer."""
    operation: Literal['list_customer_subscriptions'] = Field('list_customer_subscriptions', json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., description="PayPro resource ID from the dashboard or a list operation.")


class PayProListSubscriptionPeriodsConfig(_Page):
    """Retrieves a list subscription periods that belong to this subscription."""
    operation: Literal['list_subscription_periods'] = Field('list_subscription_periods', json_schema_extra={"ui:hidden": True})
    subscription_id: str = Field(..., description="PayPro resource ID from the dashboard or a list operation.")


class PayProListBalancesConfig(_Page):
    """Retrieve a list of balances."""
    operation: Literal['list_balances'] = Field('list_balances', json_schema_extra={"ui:hidden": True})


class PayProGetBalanceConfig(_Input):
    """Retrieves a balance."""
    operation: Literal['get_balance'] = Field('get_balance', json_schema_extra={"ui:hidden": True})
    balance_id: str = Field(..., description="PayPro resource ID from the dashboard or a list operation.")


class PayProListBalanceTransactionsConfig(_Page):
    """Retrieves a list of balance transactions."""
    operation: Literal['list_balance_transactions'] = Field('list_balance_transactions', json_schema_extra={"ui:hidden": True})
    balance_id: str = Field(..., description="PayPro resource ID from the dashboard or a list operation.")


PayProOperation = Annotated[Union[
    PayProListCustomersConfig,
    PayProGetCustomerConfig,
    PayProCreateCustomerConfig,
    PayProUpdateCustomerConfig,
    PayProListPaymentsConfig,
    PayProGetPaymentConfig,
    PayProCreatePaymentConfig,
    PayProCancelPaymentConfig,
    PayProListPaymentRefundsConfig,
    PayProCreateRefundConfig,
    PayProListRefundsConfig,
    PayProGetRefundConfig,
    PayProCancelRefundConfig,
    PayProListSubscriptionsConfig,
    PayProGetSubscriptionConfig,
    PayProCreateSubscriptionConfig,
    PayProUpdateSubscriptionConfig,
    PayProCancelSubscriptionConfig,
    PayProPauseSubscriptionConfig,
    PayProResumeSubscriptionConfig,
    PayProListCustomerSubscriptionsConfig,
    PayProListSubscriptionPeriodsConfig,
    PayProListBalancesConfig,
    PayProGetBalanceConfig,
    PayProListBalanceTransactionsConfig
], Field(discriminator="operation")]


class PayProNodeConfig(NodeConfig[PayProOperation, PayProAPIKeyCredential]):
    pass


# Method, contract path, config ID field, response resource type, success status.
ROUTES = {'list_customers': ('GET', '/customers', None, 'customer', 200),
 'get_customer': ('GET', '/customers/{id}', 'customer_id', 'customer', 200),
 'create_customer': ('POST', '/customers', None, 'customer', 201),
 'update_customer': ('PATCH', '/customers/{id}', 'customer_id', 'customer', 200),
 'list_payments': ('GET', '/payments', None, 'payment', 200),
 'get_payment': ('GET', '/payments/{id}', 'payment_id', 'payment', 200),
 'create_payment': ('POST', '/payments', None, 'payment', 201),
 'cancel_payment': ('DELETE', '/payments/{id}', 'payment_id', 'payment', 200),
 'list_payment_refunds': ('GET', '/payments/{id}/refunds', 'payment_id', 'refund', 200),
 'create_refund': ('POST', '/payments/{id}/refunds', 'payment_id', 'refund', 201),
 'list_refunds': ('GET', '/refunds', None, 'refund', 200),
 'get_refund': ('GET', '/refunds/{id}', 'refund_id', 'refund', 200),
 'cancel_refund': ('DELETE', '/refunds/{id}', 'refund_id', 'refund', 200),
 'list_subscriptions': ('GET', '/subscriptions', None, 'subscription', 200),
 'get_subscription': ('GET', '/subscriptions/{id}', 'subscription_id', 'subscription', 200),
 'create_subscription': ('POST', '/subscriptions', None, 'subscription', 201),
 'update_subscription': ('PATCH', '/subscriptions/{id}', 'subscription_id', 'subscription', 200),
 'cancel_subscription': ('DELETE', '/subscriptions/{id}', 'subscription_id', 'subscription', 200),
 'pause_subscription': ('POST',
                        '/subscriptions/{id}/pause',
                        'subscription_id',
                        'subscription',
                        200),
 'resume_subscription': ('POST',
                         '/subscriptions/{id}/resume',
                         'subscription_id',
                         'subscription',
                         200),
 'list_customer_subscriptions': ('GET',
                                 '/customers/{id}/subscriptions',
                                 'customer_id',
                                 'subscription',
                                 200),
 'list_subscription_periods': ('GET',
                               '/subscriptions/{id}/subscription_periods',
                               'subscription_id',
                               'subscription_period',
                               200),
 'list_balances': ('GET', '/balances', None, 'balance', 200),
 'get_balance': ('GET', '/balances/{id}', 'balance_id', 'balance', 200),
 'list_balance_transactions': ('GET',
                               '/balances/{balance_id}/transactions',
                               'balance_id',
                               'balance_transaction',
                               200)}


def _url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use an absolute HTTP(S) return or cancel URL")
    return value


class PayProNode(WorkflowNode):
    integration_type = "automation-paypro"
    connection_evidence = ConnectionEvidence(noun="customers", operation="list_customers",
        label_keys=("company_name", "email", "first_name", "id"))

    @classmethod
    def get_config_model(cls):
        return PayProNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a PayPro API key")
        op = self.config.config
        method, template, id_field, kind, expected_status = ROUTES[op.operation]
        route = template
        if id_field:
            route = re.sub(r"\{[^}]+\}", quote(getattr(op, id_field), safe=""), template)
        body = op.body.model_dump(exclude_unset=True) if hasattr(op, "body") else None
        if body:
            for key in ("return_url", "cancel_url"):
                if body.get(key) is not None:
                    _url(body[key])
            if body.get("mandate") and any(body.get(k) is not None for k in ("customer", "pay_methods", "setup_mandate")):
                raise ValueError("A mandate cannot be combined with customer, pay methods or setup mandate")
            if body.get("setup_mandate") and not body.get("customer"):
                raise ValueError("Setting up a mandate requires a customer")
        params = {"limit": op.limit, **({"cursor": op.cursor} if op.cursor else {})} if isinstance(op, _Page) else None
        key = self.config.credentials.api_key
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route, params=params,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
        except (httpx.HTTPError, OSError):
            output = {"status": "error" if method == "GET" else "unknown", "success": False,
                "message": "PayPro request could not be confirmed; inspect the dashboard before retrying a write."}
        else:
            if response.status_code != expected_status:
                # Retain the provider's rejection for the connect seam, redacting this key.
                message = response.text[:2000].replace(key, "[redacted]")
                output = {"status": "unknown" if method != "GET" and response.status_code >= 500 else "error", "success": False, "http_status": response.status_code,
                    "message": message or "PayPro did not confirm the request"}
            else:
                try:
                    if len(response.content) > 5_000_000:
                        raise ValueError("Response exceeds the supported size")
                    payload = response.json()
                    if not isinstance(payload, dict) or "error" in payload or "errors" in payload:
                        raise ValueError("Expected a PayPro resource")
                    if isinstance(op, _Page):
                        rows = payload.get("data")
                        if payload.get("type") != "list" or not isinstance(rows, list) or type(payload.get("count")) is not int:
                            raise ValueError("Expected a PayPro list")
                        if any(not isinstance(row, dict) or row.get("type") != kind or not isinstance(row.get("id"), (str, int)) for row in rows):
                            raise ValueError("Unexpected PayPro resource in list")
                        following = payload.get("_links", {}).get("next")
                        cursor = None
                        if following:
                            target = urlsplit(following)
                            if target.scheme != "https" or target.netloc != "api.paypro.nl" or target.path != route:
                                raise ValueError("Unexpected PayPro pagination link")
                            values = parse_qs(target.query)
                            if len(values.get("cursor", [])) != 1:
                                raise ValueError("Missing PayPro pagination cursor")
                            cursor = values["cursor"][0]
                            if cursor == op.cursor:
                                raise ValueError("PayPro returned a nonadvancing cursor")
                        output = {"data": rows, "count": payload["count"], "has_more": bool(following), "next_cursor": cursor}
                    else:
                        if payload.get("type") != kind or not isinstance(payload.get("id"), (str, int)):
                            raise ValueError("Unexpected PayPro resource")
                        output = {"data": payload}
                    output = {"status": "success", "success": True, "operation": op.operation, "http_status": response.status_code, **output}
                except (ValueError, TypeError, AttributeError):
                    output = {"status": "error" if method == "GET" else "unknown", "success": False,
                        "http_status": response.status_code, "message": "PayPro returned an unrecognized response; inspect the dashboard before retrying a write."}
        # Never emit this credential, even if a provider response echoes it.
        def redact(value):
            if isinstance(value, str):
                return value.replace(key, "[redacted]")
            if isinstance(value, dict):
                return {redact(k): redact(v) for k, v in value.items()}
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value
        output = redact(output)
        await self.emit(output)
        return output
