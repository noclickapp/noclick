"""BTCPay Server Greenfield v1 operations using a user-created API key.

Contract: https://docs.btcpayserver.org/API/Greenfield/v1/swagger.json
Each execution makes one request; writes are never retried automatically.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret, https_origin
from utils.ssrf import guarded_async_client


class BtcpayServerAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Btcpay Server API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.btcpayserver.org/Developers/api/authentication/",
            "x-credential-instructions": "In your BTCPay Server account, open Account → Manage Account → API Keys and create an API key. Paste the key and your server's HTTPS origin. Enable btcpay.user.canviewprofile to verify the connection, plus the permissions needed for your operations: view store settings, view/create/modify invoices, manage invoice status, view/modify payment requests, or manage/create/archive pull payments. Keys can be restricted to individual stores. NoClick sends Authorization: token <key> to this server. An accepted profile read does not verify write permissions.",
        },
    )
    credential_type: Literal["btcpay_server_api_key"] = Field("btcpay_server_api_key", json_schema_extra={"ui:hidden": True})
    api_base_url: str = Field(..., min_length=1, title="Server URL", description="Your public HTTPS BTCPay Server origin, for example https://pay.example.com.")
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_base_url", mode="before")
    @classmethod
    def server(cls, value):
        origin = https_origin(value)
        if urlsplit(origin).scheme != "https":
            raise ValueError("Use your public HTTPS BTCPay Server URL")
        return origin

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API key")
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without the token prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
                raise ValueError("Use a single BTCPay resource ID")
        return value


class GetCurrentUser(_Input):
    operation: Literal["get_current_user"] = "get_current_user"


class ListStores(_Input):
    operation: Literal["list_stores"] = "list_stores"


class GetStore(_Input):
    operation: Literal["get_store"] = "get_store"
    store_id: str


class ListInvoices(_Input):
    operation: Literal["list_invoices"] = "list_invoices"
    store_id: str
    take: int = Field(50, ge=1, le=100, description="Maximum invoices on this page.")
    skip: int = Field(0, ge=0, description="Offset; increase by the returned count to fetch another page.")
    text_search: str | None = Field(None, max_length=1000)
    order_ids: list[str] | None = Field(None, max_length=100)
    status: Literal["New", "Processing", "Expired", "Invalid", "Settled"] | None = None
    start_date: int | None = Field(None, ge=0, description="Unix timestamp in seconds.")
    end_date: int | None = Field(None, ge=0, description="Unix timestamp in seconds.")


class GetInvoice(_Input):
    operation: Literal["get_invoice"] = "get_invoice"
    invoice_id: str
    include_payment_methods: StrictBool = False


class _Money(_Input):
    amount: str = Field(..., pattern=r"^[0-9]+(?:\.[0-9]+)?$", max_length=80, description="Positive decimal string, such as 5.00.")
    currency: str = Field(..., min_length=1, max_length=20)

    @field_validator("amount")
    @classmethod
    def positive(cls, value):
        try:
            if Decimal(value) <= 0:
                raise ValueError("Amount must be positive")
        except InvalidOperation:
            raise ValueError("Use a positive decimal amount") from None
        return value


class CreateInvoice(_Money):
    operation: Literal["create_invoice"] = "create_invoice"
    store_id: str
    metadata: dict | None = Field(None, description="Invoice metadata, such as orderId, buyerEmail or itemDesc.")


class UpdateInvoice(_Input):
    operation: Literal["update_invoice"] = "update_invoice"
    invoice_id: str
    metadata: dict = Field(..., description="Replacement invoice metadata; include all fields you want to retain.")


class ArchiveInvoice(_Input):
    operation: Literal["archive_invoice"] = "archive_invoice"
    invoice_id: str


class UnarchiveInvoice(_Input):
    operation: Literal["unarchive_invoice"] = "unarchive_invoice"
    invoice_id: str


class MarkInvoiceStatus(_Input):
    operation: Literal["mark_invoice_status"] = "mark_invoice_status"
    invoice_id: str
    status: Literal["Invalid", "Settled"] = Field(..., description="Manually marks the invoice; this does not send a payment.")


class GetInvoicePaymentMethods(_Input):
    operation: Literal["get_invoice_payment_methods"] = "get_invoice_payment_methods"
    invoice_id: str
    only_accounted_payments: StrictBool = True


class ListPaymentRequests(_Input):
    operation: Literal["list_payment_requests"] = "list_payment_requests"
    store_id: str


class CreatePaymentRequest(_Money):
    operation: Literal["create_payment_request"] = "create_payment_request"
    store_id: str
    title: str = Field(..., min_length=1, max_length=1000)
    description: str | None = Field(None, max_length=10000)
    reference_id: str | None = Field(None, max_length=200)
    expiry_date: int | None = Field(None, ge=0, description="Unix timestamp in seconds.")
    allow_custom_payment_amounts: StrictBool = False


class GetPaymentRequest(_Input):
    operation: Literal["get_payment_request"] = "get_payment_request"
    payment_request_id: str


class ArchivePaymentRequest(_Input):
    operation: Literal["archive_payment_request"] = "archive_payment_request"
    payment_request_id: str


class ListPullPayments(_Input):
    operation: Literal["list_pull_payments"] = "list_pull_payments"
    store_id: str
    include_archived: StrictBool = False


class CreatePullPayment(_Money):
    operation: Literal["create_pull_payment"] = "create_pull_payment"
    store_id: str
    name: str | None = Field(None, max_length=1000)
    description: str | None = Field(None, max_length=10000)
    payout_methods: list[str] | None = Field(None, max_length=50)
    starts_at: int | None = Field(None, ge=0)
    expires_at: int | None = Field(None, ge=0)


class GetPullPayment(_Input):
    operation: Literal["get_pull_payment"] = "get_pull_payment"
    pull_payment_id: str


class ArchivePullPayment(_Input):
    operation: Literal["archive_pull_payment"] = "archive_pull_payment"
    pull_payment_id: str = Field(..., description="Archiving also cancels payouts awaiting payment.")


BtcpayServerConfig = Annotated[Union[
    GetCurrentUser, ListStores, GetStore, ListInvoices, GetInvoice, CreateInvoice,
    UpdateInvoice, ArchiveInvoice, UnarchiveInvoice, MarkInvoiceStatus,
    GetInvoicePaymentMethods, ListPaymentRequests, CreatePaymentRequest,
    GetPaymentRequest, ArchivePaymentRequest, ListPullPayments, CreatePullPayment,
    GetPullPayment, ArchivePullPayment,
], Field(discriminator="operation")]


class BtcpayServerFullConfig(NodeConfig[BtcpayServerConfig, BtcpayServerAPIKeyCredential]):
    pass


# Fixed routes mirror the published operation paths; no caller-supplied URLs.
ROUTES = {
    "get_current_user": ("GET", "/api/v1/users/me"),
    "list_stores": ("GET", "/api/v1/stores"),
    "get_store": ("GET", "/api/v1/stores/{store_id}"),
    "list_invoices": ("GET", "/api/v1/stores/{store_id}/invoices"),
    "create_invoice": ("POST", "/api/v1/stores/{store_id}/invoices"),
    "get_invoice": ("GET", "/api/v1/invoices/{invoice_id}"),
    "update_invoice": ("PUT", "/api/v1/invoices/{invoice_id}"),
    "archive_invoice": ("DELETE", "/api/v1/invoices/{invoice_id}"),
    "unarchive_invoice": ("POST", "/api/v1/invoices/{invoice_id}/unarchive"),
    "mark_invoice_status": ("POST", "/api/v1/invoices/{invoice_id}/status"),
    "get_invoice_payment_methods": ("GET", "/api/v1/invoices/{invoice_id}/payment-methods"),
    "list_payment_requests": ("GET", "/api/v1/stores/{store_id}/payment-requests"),
    "create_payment_request": ("POST", "/api/v1/stores/{store_id}/payment-requests"),
    "get_payment_request": ("GET", "/api/v1/payment-requests/{payment_request_id}"),
    "archive_payment_request": ("DELETE", "/api/v1/payment-requests/{payment_request_id}"),
    "list_pull_payments": ("GET", "/api/v1/stores/{store_id}/pull-payments"),
    "create_pull_payment": ("POST", "/api/v1/stores/{store_id}/pull-payments"),
    "get_pull_payment": ("GET", "/api/v1/pull-payments/{pull_payment_id}"),
    "archive_pull_payment": ("DELETE", "/api/v1/pull-payments/{pull_payment_id}"),
}
EMPTY_RESPONSES = {"archive_invoice", "archive_payment_request", "archive_pull_payment"}
LIST_RESPONSES = {"list_stores", "list_invoices", "get_invoice_payment_methods", "list_payment_requests", "list_pull_payments"}


def request_parts(op):
    action = op.operation
    method, template = ROUTES[action]
    values = op.model_dump(exclude_none=True)
    path = template.format(**{key: quote(str(value), safe="") for key, value in values.items() if key.endswith("_id")})
    params, body = {}, None
    if action == "list_invoices":
        names = {"take": "take", "skip": "skip", "text_search": "textSearch", "order_ids": "orderId", "status": "status", "start_date": "startDate", "end_date": "endDate"}
        params = {target: values[source] for source, target in names.items() if source in values}
    elif action == "get_invoice":
        params = {"includePaymentMethods": str(op.include_payment_methods).lower()}
    elif action == "get_invoice_payment_methods":
        params = {"includeSensitive": "false", "onlyAccountedPayments": str(op.only_accounted_payments).lower()}
    elif action == "list_pull_payments":
        params = {"includeArchived": str(op.include_archived).lower()}
    elif action == "create_invoice":
        body = {key: values[key] for key in ("amount", "currency", "metadata") if key in values}
    elif action == "update_invoice":
        body = {"metadata": op.metadata}
    elif action == "mark_invoice_status":
        body = {"status": op.status}
    elif action == "create_payment_request":
        names = {"amount": "amount", "currency": "currency", "title": "title", "description": "description", "reference_id": "referenceId", "expiry_date": "expiryDate", "allow_custom_payment_amounts": "allowCustomPaymentAmounts"}
        body = {target: values[source] for source, target in names.items() if source in values}
    elif action == "create_pull_payment":
        names = {"amount": "amount", "currency": "currency", "name": "name", "description": "description", "payout_methods": "payoutMethods", "starts_at": "startsAt", "expires_at": "expiresAt"}
        body = {target: values[source] for source, target in names.items() if source in values}
        body["autoApproveClaims"] = False
    return method, path, params, body


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {str(key).replace(secret, "[redacted]"): _redact(item, secret) for key, item in value.items()}
    return value


def _rejection_message(response):
    try:
        data = response.json()
        message = data.get("message") or data.get("detail")
        if isinstance(message, str) and message.strip():
            return message[:2000]
    except Exception:
        pass
    return "BTCPay Server rejected the request; check the API key and its permissions."


class BtcpayServerNode(WorkflowNode):
    integration_type = "automation-btcpay-server"
    credential_provider_labels = {"btcpay_server": "BTCPay Server"}
    connection_evidence = ConnectionEvidence(noun="BTCPay Server account", identity_operation="get_current_user")

    @classmethod
    def get_config_model(cls):
        return BtcpayServerFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect your BTCPay Server API key")
        credential = self.config.credentials
        op = self.config.config
        method, path, params, body = request_parts(op)
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, credential.api_base_url + path,
                    headers={"Authorization": "token " + credential.api_key, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
            response.raise_for_status()
            # The contract specifies HTTP 200 for these operations, including archives.
            if response.status_code != 200:
                raise ValueError("Unexpected BTCPay Server success status")
            if op.operation in EMPTY_RESPONSES:
                result = {"acknowledged": True}
            else:
                if len(response.content) > 5_000_000 or response.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
                    raise ValueError("Expected a bounded BTCPay Server JSON response")
                data = response.json()
                if op.operation in LIST_RESPONSES:
                    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                        raise ValueError("Expected a BTCPay Server resource list")
                elif not isinstance(data, dict) or "code" in data or "error" in data:
                    raise ValueError("Expected a BTCPay Server resource")
                result = {"data": data}
                if op.operation == "list_invoices":
                    result.update(next_skip=op.skip + len(data) if len(data) == op.take else None,
                        has_more=None if len(data) == op.take else False,
                        pagination_note="A full page may have more invoices; request next_skip to check.")
            output = {"status": "success", "operation": op.operation, "http_status": response.status_code, **result}
        except Exception as exc:
            # Do not leak request URLs, keys or provider bodies in transport/parser errors.
            # HTTP rejections retain their status for the shared credential seam.
            if isinstance(exc, httpx.HTTPStatusError):
                output = {"status": "error", "http_status": exc.response.status_code,
                    "message": _rejection_message(exc.response)}
            else:
                output = {"status": "error" if method == "GET" else "unknown", "message": "BTCPay Server request could not be confirmed; inspect writes before retrying."}
        # Provider metadata is user-controlled; an echoed key must never become output.
        output = _redact(output, credential.api_key)
        await self.emit(output)
        return output
