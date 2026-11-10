"""Invoice Ninja v5 clients, invoices, quotes, payments and product sync.

Official API: https://invoiceninja.github.io/docs/api-reference/invoice-ninja-api-reference
Pasted API token; one documented request per operation. Lists return one page,
including provider pagination metadata, for explicit incremental synchronization.
Quote conversion uses POST /quotes/bulk (the GET action route is deprecated).
"""
import json
import time
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import https_origin
from utils.ssrf import guarded_async_client


class InvoiceNinjaAPITokenCredential(BaseModel):
    credential_type: Literal["invoiceninja_api_token"] = Field("invoiceninja_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, title="API Token", repr=False, json_schema_extra={"ui:widget": "password"})
    base_url: str = Field("https://invoicing.co", title="Server URL", description="Invoice Ninja server origin. Use https://invoicing.co for hosted accounts or your self-hosted HTTPS server.")
    model_config = ConfigDict(title="Invoice Ninja API Token", json_schema_extra={
        "x-credential-url": "https://invoiceninja.github.io/docs/api-reference/invoice-ninja-api-reference",
        "x-credential-instructions": "In Invoice Ninja, open Settings → Account Management → Integrations → API tokens. Create a token and paste it here. For self-hosted accounts, enter your HTTPS server URL.",
    })

    @field_validator("base_url")
    @classmethod
    def server_origin(cls, value: str) -> str:
        origin = https_origin(value)
        if not origin.startswith("https://"):
            raise ValueError("Invoice Ninja requires an HTTPS server URL")
        return origin


def operation(value: str, label: str, category: str):
    return Field(value, title=label, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": label, "x-category": category})


class ListPage(BaseModel):
    page: int = Field(1, ge=1, title="Page", description="Read one page; use the returned meta.pagination for subsequent pages.")
    per_page: int = Field(20, ge=1, le=100, title="Page Size")
    updated_at: int | None = Field(None, ge=0, title="Updated Since", description="Unix timestamp filter for incremental sync.")
    filter: str | None = Field(None, title="Search", description="Provider text search filter.")


class ClientFields(BaseModel):
    name: str = Field(..., min_length=1, title="Client Name")
    contacts_json: str = Field(..., title="Contacts (JSON)", description="JSON array of client contacts. On updates, include ALL existing contacts: omitted contacts may be removed.", json_schema_extra={"ui:widget": "textarea"})
    country_id: int = Field(..., ge=1, title="Country ID", description="Invoice Ninja numeric country ID.")
    address1: str | None = Field(None, title="Address")
    city: str | None = Field(None, title="City")
    state: str | None = Field(None, title="State")
    postal_code: str | None = Field(None, title="Postal Code")
    phone: str | None = Field(None, title="Phone")
    website: str | None = Field(None, title="Website")
    private_notes: str | None = Field(None, title="Private Notes")


class InvoiceFields(BaseModel):
    client_id: str = Field(..., min_length=1, title="Client ID")
    line_items_json: str = Field(..., title="Line Items (JSON)", description="JSON array of line items with product_key, notes, cost and quantity. On updates supply the complete line item list.", json_schema_extra={"ui:widget": "textarea"})
    date: str | None = Field(None, title="Invoice Date", description="YYYY-MM-DD")
    due_date: str | None = Field(None, title="Due Date", description="YYYY-MM-DD")
    public_notes: str | None = Field(None, title="Public Notes")
    private_notes: str | None = Field(None, title="Private Notes")
    number: str | None = Field(None, title="Invoice Number")
    po_number: str | None = Field(None, title="Purchase Order Number")


class QuoteFields(BaseModel):
    client_id: str = Field(..., min_length=1, title="Client ID")
    date: str = Field(..., title="Quote Date", description="YYYY-MM-DD")
    due_date: str = Field(..., title="Due Date", description="YYYY-MM-DD")
    line_items_json: str = Field(..., title="Line Items (JSON)", description="JSON array of line items. On updates supply the complete line item list.", json_schema_extra={"ui:widget": "textarea"})
    public_notes: str | None = Field(None, title="Public Notes")
    private_notes: str | None = Field(None, title="Private Notes")


class PaymentFields(BaseModel):
    client_id: str = Field(..., min_length=1, title="Client ID")
    amount: float = Field(..., gt=0, title="Amount", description="Record an existing payment; this does not charge a payment gateway.")
    date: str = Field(..., title="Payment Date", description="YYYY-MM-DD")
    type_id: str | None = Field(None, title="Payment Type ID", description="For example 1 for bank transfer, 2 for cash, 15 for check.")
    transaction_reference: str | None = Field(None, title="Transaction Reference")
    invoices_json: str | None = Field(None, title="Invoice Allocations (JSON)", description='JSON array of {"invoice_id": "hashed ID", "amount": "10.00"}. Amounts are strings per the API contract.', json_schema_extra={"ui:widget": "textarea"})
    private_notes: str | None = Field(None, title="Private Notes")


class ProductFields(BaseModel):
    product_key: str = Field(..., min_length=1, title="Product Key")
    notes: str | None = Field(None, title="Description")
    cost: float | None = Field(None, title="Purchase Cost")
    price: float | None = Field(None, title="Sale Price")
    quantity: float | None = Field(None, title="Default Quantity")


class InvoiceNinjaListClientsConfig(ListPage):
    operation: Literal["list_clients"] = operation("list_clients", "List Clients", "Clients")


class InvoiceNinjaGetClientConfig(BaseModel):
    operation: Literal["get_client"] = operation("get_client", "Get Client", "Clients")
    client_id: str = Field(..., min_length=1, title="Client ID")


class InvoiceNinjaCreateClientConfig(ClientFields):
    operation: Literal["create_client"] = operation("create_client", "Create Client", "Clients")


class InvoiceNinjaUpdateClientConfig(ClientFields):
    operation: Literal["update_client"] = operation("update_client", "Update Client", "Clients")
    client_id: str = Field(..., min_length=1, title="Client ID")


class InvoiceNinjaListInvoicesConfig(ListPage):
    operation: Literal["list_invoices"] = operation("list_invoices", "List Invoices", "Invoices")
    client_id: str | None = Field(None, title="Client ID", description="Filter to one client.")


class InvoiceNinjaGetInvoiceConfig(BaseModel):
    operation: Literal["get_invoice"] = operation("get_invoice", "Get Invoice", "Invoices")
    invoice_id: str = Field(..., min_length=1, title="Invoice ID")


class InvoiceNinjaCreateInvoiceConfig(InvoiceFields):
    operation: Literal["create_invoice"] = operation("create_invoice", "Create Invoice", "Invoices")


class InvoiceNinjaUpdateInvoiceConfig(InvoiceFields):
    operation: Literal["update_invoice"] = operation("update_invoice", "Update Invoice", "Invoices")
    invoice_id: str = Field(..., min_length=1, title="Invoice ID")


class InvoiceNinjaListQuotesConfig(ListPage):
    operation: Literal["list_quotes"] = operation("list_quotes", "List Quotes", "Quotes")
    client_id: str | None = Field(None, title="Client ID", description="Filter to one client.")


class InvoiceNinjaGetQuoteConfig(BaseModel):
    operation: Literal["get_quote"] = operation("get_quote", "Get Quote", "Quotes")
    quote_id: str = Field(..., min_length=1, title="Quote ID")


class InvoiceNinjaCreateQuoteConfig(QuoteFields):
    operation: Literal["create_quote"] = operation("create_quote", "Create Quote", "Quotes")


class InvoiceNinjaUpdateQuoteConfig(QuoteFields):
    operation: Literal["update_quote"] = operation("update_quote", "Update Quote", "Quotes")
    quote_id: str = Field(..., min_length=1, title="Quote ID")


class InvoiceNinjaListPaymentsConfig(ListPage):
    operation: Literal["list_payments"] = operation("list_payments", "List Payments", "Payments")
    client_id: str | None = Field(None, title="Client ID", description="Filter to one client.")


class InvoiceNinjaGetPaymentConfig(BaseModel):
    operation: Literal["get_payment"] = operation("get_payment", "Get Payment", "Payments")
    payment_id: str = Field(..., min_length=1, title="Payment ID")


class InvoiceNinjaCreatePaymentConfig(PaymentFields):
    operation: Literal["create_payment"] = operation("create_payment", "Create Payment", "Payments")


class InvoiceNinjaUpdatePaymentConfig(PaymentFields):
    operation: Literal["update_payment"] = operation("update_payment", "Update Payment", "Payments")
    payment_id: str = Field(..., min_length=1, title="Payment ID")


class InvoiceNinjaListProductsConfig(ListPage):
    operation: Literal["list_products"] = operation("list_products", "List Products", "Products")


class InvoiceNinjaGetProductConfig(BaseModel):
    operation: Literal["get_product"] = operation("get_product", "Get Product", "Products")
    product_id: str = Field(..., min_length=1, title="Product ID")


class InvoiceNinjaCreateProductConfig(ProductFields):
    operation: Literal["create_product"] = operation("create_product", "Create Product", "Products")


class InvoiceNinjaConvertQuoteConfig(BaseModel):
    operation: Literal["convert_quote_to_invoice"] = operation("convert_quote_to_invoice", "Convert Quote to Invoice", "Quotes")
    quote_id: str = Field(..., min_length=1, title="Quote ID", description="The quote to convert into an invoice.")


InvoiceNinjaConfig = Annotated[Union[
    InvoiceNinjaListClientsConfig,
    InvoiceNinjaGetClientConfig,
    InvoiceNinjaCreateClientConfig,
    InvoiceNinjaUpdateClientConfig,
    InvoiceNinjaListInvoicesConfig,
    InvoiceNinjaGetInvoiceConfig,
    InvoiceNinjaCreateInvoiceConfig,
    InvoiceNinjaUpdateInvoiceConfig,
    InvoiceNinjaListQuotesConfig,
    InvoiceNinjaGetQuoteConfig,
    InvoiceNinjaCreateQuoteConfig,
    InvoiceNinjaUpdateQuoteConfig,
    InvoiceNinjaListPaymentsConfig,
    InvoiceNinjaGetPaymentConfig,
    InvoiceNinjaCreatePaymentConfig,
    InvoiceNinjaUpdatePaymentConfig,
    InvoiceNinjaListProductsConfig,
    InvoiceNinjaGetProductConfig,
    InvoiceNinjaCreateProductConfig,
    InvoiceNinjaConvertQuoteConfig,
], Field(discriminator="operation")]


class InvoiceNinjaNodeConfig(NodeConfig[InvoiceNinjaConfig, InvoiceNinjaAPITokenCredential]):
    pass


# Every entry maps to one operation in the official v5 OpenAPI contract.
OPERATIONS = {
    "list_clients": ("GET", "/api/v1/clients"),
    "get_client": ("GET", "/api/v1/clients/{id}"),
    "create_client": ("POST", "/api/v1/clients"),
    "update_client": ("PUT", "/api/v1/clients/{id}"),
    "list_invoices": ("GET", "/api/v1/invoices"),
    "get_invoice": ("GET", "/api/v1/invoices/{id}"),
    "create_invoice": ("POST", "/api/v1/invoices"),
    "update_invoice": ("PUT", "/api/v1/invoices/{id}"),
    "list_quotes": ("GET", "/api/v1/quotes"),
    "get_quote": ("GET", "/api/v1/quotes/{id}"),
    "create_quote": ("POST", "/api/v1/quotes"),
    "update_quote": ("PUT", "/api/v1/quotes/{id}"),
    "list_payments": ("GET", "/api/v1/payments"),
    "get_payment": ("GET", "/api/v1/payments/{id}"),
    "create_payment": ("POST", "/api/v1/payments"),
    "update_payment": ("PUT", "/api/v1/payments/{id}"),
    "list_products": ("GET", "/api/v1/products"),
    "get_product": ("GET", "/api/v1/products/{id}"),
    "create_product": ("POST", "/api/v1/products"),
    "convert_quote_to_invoice": ("POST", "/api/v1/quotes/bulk"),
}


def _json_objects(value: str, field: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        raise ValueError(f"{field} must be a valid JSON array of objects") from None
    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        raise ValueError(f"{field} must be a JSON array of objects")
    return parsed


class InvoiceNinjaNode(WorkflowNode):
    integration_type = "automation-invoiceninja"
    credential_provider_labels = {"invoiceninja": "Invoiceninja Account"}
    connection_evidence = ConnectionEvidence(operation="list_clients", noun="clients")

    @classmethod
    def get_config_model(cls):
        return InvoiceNinjaNodeConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        if not isinstance(self.config, InvoiceNinjaNodeConfig) or not self.config.credentials:
            raise ValueError("Invoice Ninja API token is required")
        op = self.config.config
        credentials = self.config.credentials
        method, path = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True)
        values.pop("operation")
        params, body = {}, None
        if "{id}" in path:
            id_field = op.operation.split("_", 1)[1] + "_id"
            path = path.replace("{id}", quote(values.pop(id_field), safe=""))
        if op.operation == "convert_quote_to_invoice":
            body = {"action": "convert", "ids": [values["quote_id"]]}
        elif method == "GET":
            params = values
        else:
            body = values
            for field in ("contacts", "line_items", "invoices"):
                raw = body.pop(field + "_json", None)
                if raw is not None:
                    body[field] = _json_objects(raw, field)
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False) as client:
                response = await client.request(method, credentials.base_url + path,
                    headers={"X-API-TOKEN": credentials.api_token, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            result = {"action": op.operation, "status_code": response.status_code, "timing_ms": {"api_request": elapsed, "total": elapsed}}
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if not 200 <= response.status_code < 300:
                message = payload.get("message") if isinstance(payload, dict) else None
                error = message if isinstance(message, str) and message else f"Invoice Ninja request failed (HTTP {response.status_code})"
                return {**result, "status": "error", "error": error.replace(credentials.api_token, "[redacted]")}
            if not isinstance(payload, dict) or not payload:
                return {**result, "status": "error", "error": "Invoice Ninja returned an invalid JSON response"}
            # List responses carry data + meta; entity responses can be either
            # the documented bare object or the runtime data envelope.
            data = payload.get("data", payload)
            if op.operation.startswith("list_"):
                valid = isinstance(data, list) and all(isinstance(row, dict) for row in data)
            else:
                valid = isinstance(data, (dict, list)) and bool(data)
            if not valid:
                return {**result, "status": "error", "error": "Invoice Ninja returned an unexpected response shape"}
            return {**result, "status": "success", "data": data, **({"meta": payload["meta"]} if "meta" in payload else {})}
        except httpx.TimeoutException:
            error = "Invoice Ninja request timed out"
        except (httpx.HTTPError, ValueError):
            error = "Could not reach the Invoice Ninja HTTPS server"
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        return {"status": "error", "action": op.operation, "error": error, "timing_ms": {"api_request": elapsed, "total": elapsed}}
