"""Mollie v2 profile API: one published endpoint per operation, no write retries."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union
from urllib.parse import parse_qs, quote, urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

PaymentID = Annotated[str, Field(pattern=r"^tr_[A-Za-z0-9]+$")]
CustomerID = Annotated[str, Field(pattern=r"^cst_[A-Za-z0-9]+$")]
RefundID = Annotated[str, Field(pattern=r"^re_[A-Za-z0-9]+$")]
SubscriptionID = Annotated[str, Field(pattern=r"^sub_[A-Za-z0-9]+$")]
PaymentLinkID = Annotated[str, Field(pattern=r"^pl_[A-Za-z0-9]+$")]
URL = Annotated[str, Field(pattern=r"^https?://[^\s]+$")]
Description = Annotated[str, Field(min_length=1, max_length=255)]
Metadata = Union[str, float, dict, list[str]]


def _interval(value: str) -> str:
    count, unit = value.split()
    maximum = 365 if unit.startswith("day") else 52 if unit.startswith("week") else 12
    if not 1 <= int(count) <= maximum:
        raise ValueError("Subscription interval must be positive and at most one year")
    return value


Interval = Annotated[str, Field(pattern=r"^\d+ (days?|weeks?|months?)$"), AfterValidator(_interval)]


class MollieAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Mollie API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://my.mollie.com/dashboard/developers/api-keys",
        "x-credential-instructions": "Paste a profile API key from Mollie Dashboard → Developers → API keys, without Bearer. Use a test_ key for testing or a live_ key for real payments. Enable the payment, refund, customer, subscription and payment-link permissions you need. This connection uses the key's profile and mode; organization tokens and OAuth tokens are not supported.",
    })
    credential_type: Literal["mollie_1_api_key"] = Field("mollie_1_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Amount(Closed):
    currency: str = Field(..., pattern=r"^[A-Z]{3}$", description="ISO 4217 currency code, e.g. EUR.")
    value: str = Field(..., pattern=r"^\d+(?:\.\d+)?$", description="Exact decimal string in this currency, e.g. 10.00. Do not use floating point numbers.")


class Write(Closed):
    idempotency_key: str | None = Field(None, min_length=1, max_length=255, pattern=r"^[\x21-\x7e]+$", description="Reuse this key when retrying the same request. NoClick does not retry writes automatically.")


class Page(Closed):
    limit: int = Field(50, ge=1, le=250, title="Page Size", description="Returns one page; pass next_from to From ID to continue.")


class ListPayments(Page):
    operation: Literal["list_payments"] = Field("list_payments", title="List Payments")
    from_id: PaymentID | None = Field(None, title="From ID")
    sort: Literal["asc", "desc"] | None = None


class GetPayment(Closed):
    operation: Literal["get_payment"] = Field("get_payment", title="Get Payment")
    payment_id: PaymentID


class CreatePayment(Write):
    operation: Literal["create_payment"] = Field("create_payment", title="Create Payment")
    amount: Amount
    description: Description
    redirect_url: URL = Field(..., description="Customer returns here after checkout. Follow data._links.checkout.href from the response to accept payment.")
    webhook_url: URL | None = Field(None, description="Public endpoint for payment status updates; verify status with Get Payment.")
    cancel_url: URL | None = None
    customer_id: CustomerID | None = None
    sequence_type: Literal["oneoff", "first"] = Field("oneoff", description="Use first with a customer to establish a mandate for subsequent subscriptions.")
    metadata: Metadata | None = None

    @model_validator(mode="after")
    def first_payment_customer(self):
        if self.sequence_type == "first" and self.customer_id is None:
            raise ValueError("A first payment requires a customer ID")
        return self


class UpdatePayment(Write):
    operation: Literal["update_payment"] = Field("update_payment", title="Update Payment")
    payment_id: PaymentID
    description: Description | None = None
    redirect_url: URL | None = None
    webhook_url: URL | None = None
    cancel_url: URL | None = None
    metadata: Metadata | None = None


class CancelPayment(Write):
    operation: Literal["cancel_payment"] = Field("cancel_payment", title="Cancel Payment", description="Mollie only permits cancellation for supported payment methods and states.")
    payment_id: PaymentID


class CreateRefund(Write):
    operation: Literal["create_refund"] = Field("create_refund", title="Create Payment Refund", description="Refund a paid payment. A pending response does not mean funds have reached the customer.")
    payment_id: PaymentID
    amount: Amount
    description: Description | None = None
    metadata: Metadata | None = None


class ListRefunds(Page):
    operation: Literal["list_refunds"] = Field("list_refunds", title="List Payment Refunds")
    payment_id: PaymentID
    from_id: RefundID | None = Field(None, title="From ID")


class GetRefund(Closed):
    operation: Literal["get_refund"] = Field("get_refund", title="Get Payment Refund")
    payment_id: PaymentID
    refund_id: RefundID


class CancelRefund(Write):
    operation: Literal["cancel_refund"] = Field("cancel_refund", title="Cancel Payment Refund", description="Only queued or pending refunds can be canceled.")
    payment_id: PaymentID
    refund_id: RefundID


class ListCustomers(Page):
    operation: Literal["list_customers"] = Field("list_customers", title="List Customers")
    from_id: CustomerID | None = Field(None, title="From ID")
    sort: Literal["asc", "desc"] | None = None


class GetCustomer(Closed):
    operation: Literal["get_customer"] = Field("get_customer", title="Get Customer")
    customer_id: CustomerID


class CreateCustomer(Write):
    operation: Literal["create_customer"] = Field("create_customer", title="Create Customer")
    name: str | None = None
    email: str | None = None
    metadata: Metadata | None = None


class UpdateCustomer(Write):
    operation: Literal["update_customer"] = Field("update_customer", title="Update Customer")
    customer_id: CustomerID
    name: str | None = None
    email: str | None = None
    metadata: Metadata | None = None


class DeleteCustomer(Write):
    operation: Literal["delete_customer"] = Field("delete_customer", title="Delete Customer", description="Permanently remove the customer. This does not refund payments.")
    customer_id: CustomerID


class ListCustomerPayments(Page):
    operation: Literal["list_customer_payments"] = Field("list_customer_payments", title="List Customer Payments")
    customer_id: CustomerID
    from_id: PaymentID | None = Field(None, title="From ID")
    sort: Literal["asc", "desc"] | None = None


class CreateSubscription(Write):
    operation: Literal["create_subscription"] = Field("create_subscription", title="Create Subscription", description="Requires an existing valid customer mandate. Schedules real recurring charges with a live key.")
    customer_id: CustomerID
    amount: Amount
    interval: Interval
    description: Description
    times: int | None = Field(None, ge=1)
    start_date: date | None = None
    webhook_url: URL | None = None
    mandate_id: Annotated[str, Field(pattern=r"^mdt_[A-Za-z0-9]+$")] | None = None
    metadata: Metadata | None = None


class ListSubscriptions(Page):
    operation: Literal["list_subscriptions"] = Field("list_subscriptions", title="List Customer Subscriptions")
    customer_id: CustomerID
    from_id: SubscriptionID | None = Field(None, title="From ID")
    sort: Literal["asc", "desc"] | None = None


class GetSubscription(Closed):
    operation: Literal["get_subscription"] = Field("get_subscription", title="Get Subscription")
    customer_id: CustomerID
    subscription_id: SubscriptionID


class UpdateSubscription(Write):
    operation: Literal["update_subscription"] = Field("update_subscription", title="Update Subscription")
    customer_id: CustomerID
    subscription_id: SubscriptionID
    amount: Amount | None = None
    interval: Interval | None = None
    description: Description | None = None
    times: int | None = Field(None, ge=1)
    start_date: date | None = None
    webhook_url: URL | None = None
    metadata: Metadata | None = None


class CancelSubscription(Write):
    operation: Literal["cancel_subscription"] = Field("cancel_subscription", title="Cancel Subscription", description="Stops future subscription payments; does not refund past payments.")
    customer_id: CustomerID
    subscription_id: SubscriptionID


class CreatePaymentLink(Write):
    operation: Literal["create_payment_link"] = Field("create_payment_link", title="Create Payment Link")
    description: Description
    amount: Amount | None = Field(None, description="Omit to let the customer choose an amount.")
    redirect_url: URL | None = None
    webhook_url: URL | None = None
    reusable: bool = False
    expires_at: datetime | None = None


class ListPaymentLinks(Page):
    operation: Literal["list_payment_links"] = Field("list_payment_links", title="List Payment Links")
    from_id: PaymentLinkID | None = Field(None, title="From ID")


class GetPaymentLink(Closed):
    operation: Literal["get_payment_link"] = Field("get_payment_link", title="Get Payment Link")
    payment_link_id: PaymentLinkID


class UpdatePaymentLink(Write):
    operation: Literal["update_payment_link"] = Field("update_payment_link", title="Update Payment Link")
    payment_link_id: PaymentLinkID
    description: Description | None = None
    amount: Amount | None = None
    archived: bool | None = None


class DeletePaymentLink(Write):
    operation: Literal["delete_payment_link"] = Field("delete_payment_link", title="Delete Payment Link")
    payment_link_id: PaymentLinkID


Operation = Annotated[Union[ListPayments, GetPayment, CreatePayment, UpdatePayment, CancelPayment,
    CreateRefund, ListRefunds, GetRefund, CancelRefund, ListCustomers, GetCustomer, CreateCustomer,
    UpdateCustomer, DeleteCustomer, ListCustomerPayments, CreateSubscription, ListSubscriptions,
    GetSubscription, UpdateSubscription, CancelSubscription, CreatePaymentLink, ListPaymentLinks,
    GetPaymentLink, UpdatePaymentLink, DeletePaymentLink], Field(discriminator="operation")]


class MollieConfig(NodeConfig[Operation, MollieAPIKeyCredential]):
    pass


ROUTES = {
    "list_payments": ("GET", "/v2/payments"),
    "get_payment": ("GET", "/v2/payments/{payment_id}"),
    "create_payment": ("POST", "/v2/payments"),
    "update_payment": ("PATCH", "/v2/payments/{payment_id}"),
    "cancel_payment": ("DELETE", "/v2/payments/{payment_id}"),
    "create_refund": ("POST", "/v2/payments/{payment_id}/refunds"),
    "list_refunds": ("GET", "/v2/payments/{payment_id}/refunds"),
    "get_refund": ("GET", "/v2/payments/{payment_id}/refunds/{refund_id}"),
    "cancel_refund": ("DELETE", "/v2/payments/{payment_id}/refunds/{refund_id}"),
    "list_customers": ("GET", "/v2/customers"),
    "get_customer": ("GET", "/v2/customers/{customer_id}"),
    "create_customer": ("POST", "/v2/customers"),
    "update_customer": ("PATCH", "/v2/customers/{customer_id}"),
    "delete_customer": ("DELETE", "/v2/customers/{customer_id}"),
    "list_customer_payments": ("GET", "/v2/customers/{customer_id}/payments"),
    "create_subscription": ("POST", "/v2/customers/{customer_id}/subscriptions"),
    "list_subscriptions": ("GET", "/v2/customers/{customer_id}/subscriptions"),
    "get_subscription": ("GET", "/v2/customers/{customer_id}/subscriptions/{subscription_id}"),
    "update_subscription": ("PATCH", "/v2/customers/{customer_id}/subscriptions/{subscription_id}"),
    "cancel_subscription": ("DELETE", "/v2/customers/{customer_id}/subscriptions/{subscription_id}"),
    "create_payment_link": ("POST", "/v2/payment-links"),
    "list_payment_links": ("GET", "/v2/payment-links"),
    "get_payment_link": ("GET", "/v2/payment-links/{payment_link_id}"),
    "update_payment_link": ("PATCH", "/v2/payment-links/{payment_link_id}"),
    "delete_payment_link": ("DELETE", "/v2/payment-links/{payment_link_id}"),
}
LIST_KEYS = {"list_payments": "payments", "list_customer_payments": "payments", "list_refunds": "refunds",
    "list_customers": "customers", "list_subscriptions": "subscriptions", "list_payment_links": "payment_links"}
RENAMES = {"from_id": "from", "redirect_url": "redirectUrl", "webhook_url": "webhookUrl", "cancel_url": "cancelUrl",
    "customer_id": "customerId", "sequence_type": "sequenceType", "start_date": "startDate", "mandate_id": "mandateId", "expires_at": "expiresAt"}


class MollieNode(WorkflowNode):
    integration_type = "automation-mollie-1"
    connection_evidence = ConnectionEvidence(noun="customers", operation="list_customers")

    @classmethod
    def get_config_model(cls):
        return MollieConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Mollie API key")
        method, path = ROUTES[config.operation]
        data = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for key in list(data):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(data.pop(key), safe=""))
        headers = {"Authorization": "Bearer " + credential.api_key, "Accept": "application/hal+json"}
        idempotency = data.pop("idempotency_key", None)
        if idempotency:
            headers["Idempotency-Key"] = idempotency
        data = {RENAMES.get(key, key): value for key, value in data.items()}
        if method == "PATCH" and not data:
            raise ValueError("Supply at least one field to update")
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.mollie.com" + path, headers=headers,
                params=data if method == "GET" else None,
                json=data if method in {"POST", "PATCH"} else None)
        response.raise_for_status()
        if response.status_code == 204 and method == "DELETE":
            return {"status": "success", "deleted": True}
        if not response.content or response.headers.get("content-type", "").split(";", 1)[0] not in {"application/hal+json", "application/json"}:
            raise ValueError("Mollie returned an unexpected response type")
        body = response.json()
        if not isinstance(body, dict) or "detail" in body or "title" in body and isinstance(body.get("status"), int):
            raise ValueError("Mollie returned an unexpected response or API error")
        if config.operation in LIST_KEYS:
            items = body.get("_embedded", {}).get(LIST_KEYS[config.operation])
            if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
                raise ValueError("Mollie returned an unexpected list response")
            next_link = body.get("_links", {}).get("next")
            next_from = None
            if next_link:
                parsed = urlsplit(next_link["href"])
                # Return only a cursor, never follow a provider-supplied URL.
                if parsed.scheme != "https" or parsed.netloc != "api.mollie.com":
                    raise ValueError("Mollie returned an unexpected pagination link")
                next_from = parse_qs(parsed.query).get("from", [None])[0]
                if next_from is None:
                    raise ValueError("Mollie pagination link has no From ID")
            return {"status": "success", "items": items, "next_from": next_from, "page_only": True}
        if not isinstance(body.get("id"), str) or not isinstance(body.get("resource"), str):
            raise ValueError("Mollie returned an unexpected resource response")
        return {"status": "success", "data": body}
