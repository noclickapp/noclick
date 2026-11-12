"""Automate FacturaDirecta's published 1.0.10 API with a company API key.

Each operation issues one documented request. Lists expose explicit offset
pagination, and writes support the provider's 24-hour idempotency keys.
"""
from __future__ import annotations

from datetime import date as Date
from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.facturadirecta.com/api"
API_VERSION = "1.0.10"


class FacturaDirectaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="FacturaDirecta API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.facturadirecta.com/desarrolladores/api/guias/authentication/",
            "x-credential-instructions": "In FacturaDirecta, open Settings > API and integrations. Copy your company ID and create an API key with contacts, products, invoices, estimates and bills read/write permissions. Paste both below. Connection evidence reads your contacts; check API key returns the granted scopes. A successful read does not verify write permissions.",
        })
    credential_type: Literal["facturadirecta_api_key"] = Field("facturadirecta_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})
    company_id: str = Field(..., title="Company ID", pattern=r"^[A-Za-z0-9_-]{1,128}$",
        description="Company identifier shown in Settings > API and integrations.")

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Accounts(_Input):
    client: str | None = Field(None, pattern=r"^[0-9]{6}$")
    clientCredit: str | None = Field(None, pattern=r"^[0-9]{6}$")
    provider: str | None = Field(None, pattern=r"^[0-9]{6}$")
    providerCredit: str | None = Field(None, pattern=r"^[0-9]{6}$")
    employee: str | None = Field(None, pattern=r"^[0-9]{6}$")
    employeeCredit: str | None = Field(None, pattern=r"^[0-9]{6}$")


class ContactMain(_Input):
    name: str
    country: str = Field(..., min_length=2, max_length=2)
    currency: str = Field(..., min_length=3, max_length=3)
    accounts: Accounts
    surname: str | None = None
    title: str | None = None
    email: str | None = None
    phone: str | None = None
    fiscalId: str | None = None
    address: str | None = None
    zipcode: str | None = None
    city: str | None = None
    region: str | None = None
    externalId: str | None = None
    notes: str | None = None


class ProductFacet(_Input):
    account: str = Field(..., pattern=r"^[0-9]{6}$")
    tax: list[str]
    price: float | None = None
    description: str | None = None
    discountRate: float | None = None


class ProductMain(_Input):
    name: str
    currency: str = Field(..., min_length=3, max_length=3)
    sku: str | None = None
    externalId: str | None = None
    sales: ProductFacet | None = None
    purchases: ProductFacet | None = None


class DocumentNumber(_Input):
    series: str
    number: float | None = None
    formattedSeries: str | None = None


class SalesLine(_Input):
    quantity: float
    text: str
    unitPrice: float
    account: str | None = Field(None, pattern=r"^[0-9]{6}$")
    document: str | None = None
    tax: list[str] | None = None
    discountRate: float | None = None


class InvoiceMain(_Input):
    docNumber: DocumentNumber
    lines: list[SalesLine]
    contact: str | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    date: Date | None = None
    dueDate: Date | None = None
    draft: bool | None = Field(None, description="Set true to create a provisional invoice; otherwise company settings apply.")
    notes: str | None = None
    emails: str | None = None
    paymentMethod: str | None = None


class EstimateMain(_Input):
    baseState: Literal["pending", "closed", "accepted", "rejected"]
    docNumber: DocumentNumber
    lines: list[SalesLine]
    contact: str | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    date: Date | None = None
    dueDate: Date | None = None
    notes: str | None = None
    isProforma: bool | None = None


class BillLine(_Input):
    text: str
    quantity: float | None = None
    unitPrice: float | None = None
    lineTotal: float | None = None
    account: str | None = Field(None, pattern=r"^[0-9]{6}$")
    tax: list[str] | None = None
    document: str | None = None


class BillMain(_Input):
    contact: str | None = Field(..., description="Supplier ID, or null for a purchase receipt.")
    currency: str = Field(..., min_length=3, max_length=3)
    lines: list[BillLine]
    referenceNumber: str | None = None
    account: str | None = Field(None, pattern=r"^[0-9]{6}$")
    date: Date | None = None
    dueDate: Date | None = None
    notes: str | None = None
    draft: bool | None = None


class InvoicePayment(_Input):
    bank: str
    amount: float | None = Field(None, description="Omit to settle the balance; only the final payment may omit amount.")
    date: Date | None = None
    companyCurrencyAmount: float | None = None
    description: str | None = None
    notes: str | None = None


class _List(_Input):
    limit: int = Field(100, ge=1, le=500)
    offset: int = Field(0, ge=0)


class _Selected(_Input):
    id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", title="Resource ID")


class _Write(_Input):
    idempotency_key: str | None = Field(None, min_length=16, max_length=255, pattern=r"^[!-~]+$",
        description="Reuse the same key only for an identical request within 24 hours. Recommended: a UUID v4.")


class CheckAPIKey(_Input):
    operation: Literal["check_api_key"] = "check_api_key"


class ListContacts(_List):
    """List contacts using one documented API operation."""
    operation: Literal["list_contacts"] = "list_contacts"
    search: str | None = None
    externalId: str | None = None


class GetContact(_Selected):
    """Get a contact using one documented API operation."""
    operation: Literal["get_contact"] = "get_contact"


class CreateContact(_Write):
    """Create a contact using one documented API operation."""
    operation: Literal["create_contact"] = "create_contact"
    main: ContactMain = Field(..., description="Documented content.main fields. Updates replace the supplied resource content.")
    tags: list[str] | None = None


class UpdateContact(_Selected, _Write):
    """Update a contact using one documented API operation."""
    operation: Literal["update_contact"] = "update_contact"
    main: ContactMain = Field(..., description="Documented content.main fields. Updates replace the supplied resource content.")
    tags: list[str] | None = None


class DeleteContact(_Selected, _Write):
    """Delete a contact using one documented API operation."""
    operation: Literal["delete_contact"] = "delete_contact"


class ListProducts(_List):
    """List products using one documented API operation."""
    operation: Literal["list_products"] = "list_products"
    search: str | None = None
    externalId: str | None = None


class GetProduct(_Selected):
    """Get a product using one documented API operation."""
    operation: Literal["get_product"] = "get_product"


class CreateProduct(_Write):
    """Create a product using one documented API operation."""
    operation: Literal["create_product"] = "create_product"
    main: ProductMain = Field(..., description="Documented content.main fields. Updates replace the supplied resource content.")
    tags: list[str] | None = None


class UpdateProduct(_Selected, _Write):
    """Update a product using one documented API operation."""
    operation: Literal["update_product"] = "update_product"
    main: ProductMain = Field(..., description="Documented content.main fields. Updates replace the supplied resource content.")
    tags: list[str] | None = None


class DeleteProduct(_Selected, _Write):
    """Delete a product using one documented API operation."""
    operation: Literal["delete_product"] = "delete_product"


class ListInvoices(_List):
    """List invoices using one documented API operation."""
    operation: Literal["list_invoices"] = "list_invoices"


class GetInvoice(_Selected):
    """Get a invoice using one documented API operation."""
    operation: Literal["get_invoice"] = "get_invoice"


class CreateInvoice(_Write):
    """Create a invoice using one documented API operation."""
    operation: Literal["create_invoice"] = "create_invoice"
    main: InvoiceMain = Field(..., description="Documented content.main fields. Updates replace the supplied resource content.")
    tags: list[str] | None = None


class UpdateInvoice(_Selected, _Write):
    """Update a invoice using one documented API operation."""
    operation: Literal["update_invoice"] = "update_invoice"
    main: InvoiceMain = Field(..., description="Documented content.main fields. Updates replace the supplied resource content.")
    tags: list[str] | None = None


class DeleteInvoice(_Selected, _Write):
    """Delete a invoice using one documented API operation."""
    operation: Literal["delete_invoice"] = "delete_invoice"


class ListEstimates(_List):
    """List estimates using one documented API operation."""
    operation: Literal["list_estimates"] = "list_estimates"


class GetEstimate(_Selected):
    """Get a estimate using one documented API operation."""
    operation: Literal["get_estimate"] = "get_estimate"


class CreateEstimate(_Write):
    """Create a estimate using one documented API operation."""
    operation: Literal["create_estimate"] = "create_estimate"
    main: EstimateMain = Field(..., description="Documented content.main fields. Updates replace the supplied resource content.")
    tags: list[str] | None = None


class UpdateEstimate(_Selected, _Write):
    """Update a estimate using one documented API operation."""
    operation: Literal["update_estimate"] = "update_estimate"
    main: EstimateMain = Field(..., description="Documented content.main fields. Updates replace the supplied resource content.")
    tags: list[str] | None = None


class DeleteEstimate(_Selected, _Write):
    """Delete a estimate using one documented API operation."""
    operation: Literal["delete_estimate"] = "delete_estimate"


class ListBills(_List):
    """List bills using one documented API operation."""
    operation: Literal["list_bills"] = "list_bills"


class GetBill(_Selected):
    """Get a bill using one documented API operation."""
    operation: Literal["get_bill"] = "get_bill"


class CreateBill(_Write):
    """Create a bill using one documented API operation."""
    operation: Literal["create_bill"] = "create_bill"
    main: BillMain = Field(..., description="Documented content.main fields. Updates replace the supplied resource content.")
    tags: list[str] | None = None


class CreateInvoicePayments(_Selected, _Write):
    """Record invoice payments; a missing final amount settles the remaining balance."""
    operation: Literal["create_invoice_payments"] = "create_invoice_payments"
    payments: list[InvoicePayment] = Field(..., min_length=1)

    @field_validator("payments")
    @classmethod
    def check_payments(cls, value):
        if any(p.amount is None for p in value[:-1]):
            raise ValueError("Only the final payment may omit amount")
        return value


# FacturaDirecta's own MCP server: agents get its tools through a person's FacturaDirecta sign-in.
FacturadirectaMcpCredential = mcp_credential("facturadirecta", "https://mcp.facturadirecta.com", app="FacturaDirecta")
FacturaDirectaCredential = Union[FacturaDirectaAPIKeyCredential, FacturadirectaMcpCredential]


FacturaDirectaOperation = Annotated[Union[
    CheckAPIKey,
    ListContacts,
    GetContact,
    CreateContact,
    UpdateContact,
    DeleteContact,
    ListProducts,
    GetProduct,
    CreateProduct,
    UpdateProduct,
    DeleteProduct,
    ListInvoices,
    GetInvoice,
    CreateInvoice,
    UpdateInvoice,
    DeleteInvoice,
    ListEstimates,
    GetEstimate,
    CreateEstimate,
    UpdateEstimate,
    DeleteEstimate,
    ListBills,
    GetBill,
    CreateBill,
    CreateInvoicePayments
], Field(discriminator="operation")]


class FacturaDirectaConfig(NodeConfig[FacturaDirectaOperation, FacturaDirectaCredential]):
    pass


ROUTES = {'check_api_key': ('GET', 'apiKeyInfo', None),
 'list_contacts': ('GET', 'contacts', None),
 'get_contact': ('GET', 'contacts/{id}', None),
 'create_contact': ('POST', 'contacts', 'contact'),
 'update_contact': ('PUT', 'contacts/{id}', 'contact'),
 'delete_contact': ('DELETE', 'contacts/{id}', None),
 'list_products': ('GET', 'products', None),
 'get_product': ('GET', 'products/{id}', None),
 'create_product': ('POST', 'products', 'product'),
 'update_product': ('PUT', 'products/{id}', 'product'),
 'delete_product': ('DELETE', 'products/{id}', None),
 'list_invoices': ('GET', 'invoices', None),
 'get_invoice': ('GET', 'invoices/{id}', None),
 'create_invoice': ('POST', 'invoices', 'invoice'),
 'update_invoice': ('PUT', 'invoices/{id}', 'invoice'),
 'delete_invoice': ('DELETE', 'invoices/{id}', None),
 'list_estimates': ('GET', 'estimates', None),
 'get_estimate': ('GET', 'estimates/{id}', None),
 'create_estimate': ('POST', 'estimates', 'estimate'),
 'update_estimate': ('PUT', 'estimates/{id}', 'estimate'),
 'delete_estimate': ('DELETE', 'estimates/{id}', None),
 'list_bills': ('GET', 'bills', None),
 'get_bill': ('GET', 'bills/{id}', None),
 'create_bill': ('POST', 'bills', 'bill'),
 'create_invoice_payments': ('POST', 'invoices/{id}/payments', None)}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {str(k).replace(secret, "[redacted]"): _redact(v, secret) for k, v in value.items()}
    return value


class FacturaDirectaNode(WorkflowNode):
    integration_type = "automation-facturadirecta"
    credential_provider_labels = {"facturadirecta": "FacturaDirecta Account"}
    connection_evidence = ConnectionEvidence(noun="contacts", operation="list_contacts", label_keys=("title", "name", "id"))

    @classmethod
    def get_config_model(cls):
        return FacturaDirectaConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a FacturaDirecta API key and company ID")
        credential = self.config.credentials
        op = self.config.config
        method, route, kind = ROUTES[op.operation]
        route = route.replace("{id}", getattr(op, "id", ""))
        headers = {"facturadirecta-api-key": credential.api_key,
                   "accept-version": API_VERSION, "Accept": "application/json"}
        key = getattr(op, "idempotency_key", None)
        if key is not None:
            headers["Idempotency-Key"] = key
        params, body = None, None
        if isinstance(op, _List):
            params = op.model_dump(exclude_none=True, exclude={"operation"})
        elif kind:
            body = {"content": {"type": kind, "main": op.main.model_dump(mode="json", exclude_none=True)}}
            # A null supplier is an explicit purchase-receipt value, not an omitted field.
            if isinstance(op.main, BillMain):
                body["content"]["main"]["contact"] = op.main.contact
            if op.tags is not None:
                body["tags"] = op.tags
        elif isinstance(op, CreateInvoicePayments):
            body = {"payments": [p.model_dump(mode="json", exclude_none=True) for p in op.payments]}
        writing = method != "GET"
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, f"{BASE_URL}/{credential.company_id}/{route}",
                                                headers=headers, params=params, json=body)
        except (httpx.HTTPError, OSError):
            result = {"status": "unknown" if writing else "error", "success": False,
                      "message": "FacturaDirecta request did not complete"}
            if writing:
                result["write_outcome"] = "unverified; inspect the resource or retry the identical request with its original idempotency key"
            await self.emit(result)
            return result
        if not 200 <= response.status_code < 300:
            result = {"status": "unknown" if writing and response.status_code >= 500 else "error",
                      "success": False, "http_status": response.status_code,
                      "message": _redact(response.text[:4000], credential.api_key)}
            if result["status"] == "unknown":
                result["write_outcome"] = "unverified"
            await self.emit(result)
            return result
        try:
            data = response.json()
            if not isinstance(data, dict) or any(k in data for k in ("error", "errors")):
                raise ValueError("Unexpected response")
            result = {"status": "success", "success": True, "http_status": response.status_code, "data": data}
            if isinstance(op, _List):
                if not isinstance(data.get("items"), list) or not isinstance(data.get("pagination"), dict):
                    raise ValueError("Missing list envelope")
                page = data["pagination"]
                if any(type(page.get(k)) is not int or page[k] < 0 for k in ("limit", "offset", "total")) or page["limit"] < 1:
                    raise ValueError("Invalid pagination")
                following = page["offset"] + len(data["items"])
                if not data["items"] and following < page["total"]:
                    raise ValueError("Nonadvancing pagination")
                result.update(items=[{**row, "title": row.get("content", {}).get("main", {}).get("title") or row.get("content", {}).get("main", {}).get("name") or row.get("id")} for row in data["items"]],
                              pagination=page, next_offset=following if following < page["total"] else None)
            elif op.operation == "check_api_key":
                if not isinstance(data.get("scopes"), list) or not all(isinstance(s, str) for s in data["scopes"]):
                    raise ValueError("Missing API key scopes")
            if writing:
                result["write_acknowledged"] = True
        except (ValueError, TypeError, AttributeError):
            result = {"status": "unknown" if writing else "error", "success": False,
                      "http_status": response.status_code, "message": "FacturaDirecta returned an unexpected response"}
            if writing:
                result["write_outcome"] = "unverified"
        result = _redact(result, credential.api_key)
        await self.emit(result)
        return result
