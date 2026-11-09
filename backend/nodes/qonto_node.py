"""Qonto Business API v2 using a customer's organization login and secret key.

Contract: https://docs.qonto.com/api-reference/business-api/introduction
Only endpoints accepting SecretKey authentication are exposed. Each operation
makes exactly one request; list operations return one page and its continuation.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://thirdparty.qonto.com"


class QontoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Qonto API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.qonto.com/guides/authentication/api-key",
            "x-credential-instructions": "In Qonto, select your organization, then Integrations and Partnerships > API key. Copy its login and secret key. NoClick sends login:secret-key directly to Qonto. API keys support the reads and bookkeeping writes shown here; payment transfers require OAuth and are not offered."})
    credential_type: Literal["qonto_api_key"] = Field("qonto_api_key", json_schema_extra={"ui:hidden": True})
    login: str = Field(..., title="Organization login", min_length=1, max_length=250,
        description="The organization's API login, for example pied-piper-7132; not your email address.")
    secret_key: str = Field(..., title="Secret key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("login", "secret_key", mode="before")
    @classmethod
    def header_part(cls, value, info):
        if not isinstance(value, str):
            raise ValueError("Paste the Qonto credential field")
        value = value.strip()
        if info.field_name == "secret_key":
            value = clean_secret(value, field_name="Secret key")
        if not value or not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 or c == ":" for c in value):
            raise ValueError("Paste a single credential value without a colon, prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("bank_account_id", "transaction_id", "beneficiary_id", "supplier_invoice_id", "client_id", "product_id", "client_invoice_id", mode="before", check_fields=False)
    @classmethod
    def canonical_id(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            try:
                return str(UUID(value))
            except (ValueError, TypeError, AttributeError):
                raise ValueError("Use the Qonto resource UUID") from None
        return value


class _Page(_Input):
    page: int = Field(1, ge=1, le=10000, description="Page number; use next_page from the previous result.")
    per_page: int = Field(100, ge=1, le=100, description="Number of records per page.")


class QontoGetOrganizationConfig(_Input):
    """Get organization."""
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"ui:hidden": True})
    include_external_accounts: bool = False


class QontoListTransactionsConfig(_Page):
    """List transactions."""
    operation: Literal["list_transactions"] = Field("list_transactions", json_schema_extra={"ui:hidden": True})
    bank_account_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    iban: str | None = None
    side: Literal["credit", "debit"] | None = None
    statuses: list[Literal["pending", "declined", "completed", "reversed"]] | None = None
    updated_at_from: datetime | None = None
    updated_at_to: datetime | None = None
    settled_at_from: datetime | None = None
    settled_at_to: datetime | None = None
    with_attachments: bool | None = None
    sort_by: Literal["created_at:asc", "created_at:desc", "updated_at:asc", "updated_at:desc", "settled_at:asc", "settled_at:desc", "emitted_at:asc", "emitted_at:desc"] | None = None

    @model_validator(mode="after")
    def result_window(self):
        if self.page * self.per_page > 10000:
            raise ValueError("Qonto limits transaction pagination to 10000; narrow the date filters")
        return self


class QontoGetTransactionConfig(_Input):
    """Get transaction."""
    operation: Literal["get_transaction"] = Field("get_transaction", json_schema_extra={"ui:hidden": True})
    transaction_id: str = Field(..., description="Qonto resource UUID.", json_schema_extra={"format": "uuid"})


class QontoListLabelsConfig(_Page):
    """List labels."""
    operation: Literal["list_labels"] = Field("list_labels", json_schema_extra={"ui:hidden": True})


class QontoListMembershipsConfig(_Page):
    """List memberships."""
    operation: Literal["list_memberships"] = Field("list_memberships", json_schema_extra={"ui:hidden": True})


class QontoListBeneficiariesConfig(_Page):
    """List beneficiaries."""
    operation: Literal["list_beneficiaries"] = Field("list_beneficiaries", json_schema_extra={"ui:hidden": True})
    trusted: bool | None = None


class QontoGetBeneficiaryConfig(_Input):
    """Get beneficiary."""
    operation: Literal["get_beneficiary"] = Field("get_beneficiary", json_schema_extra={"ui:hidden": True})
    beneficiary_id: str = Field(..., description="Qonto resource UUID.", json_schema_extra={"format": "uuid"})


class QontoListSupplierInvoicesConfig(_Page):
    """List supplier invoices."""
    operation: Literal["list_supplier_invoices"] = Field("list_supplier_invoices", json_schema_extra={"ui:hidden": True})
    status: Literal['to_review', 'to_pay', 'to_approve', 'awaiting_payment', 'pending', 'scheduled', 'paid', 'archived', 'rejected', 'discarded'] | None = None


class QontoGetSupplierInvoiceConfig(_Input):
    """Get supplier invoice."""
    operation: Literal["get_supplier_invoice"] = Field("get_supplier_invoice", json_schema_extra={"ui:hidden": True})
    supplier_invoice_id: str = Field(..., description="Qonto resource UUID.", json_schema_extra={"format": "uuid"})


class QontoMarkSupplierInvoiceAsPaidConfig(_Input):
    """Record a supplier invoice as paid for bookkeeping; this does not transfer funds."""
    operation: Literal["mark_supplier_invoice_as_paid"] = Field("mark_supplier_invoice_as_paid", json_schema_extra={"ui:hidden": True})
    supplier_invoice_id: str = Field(..., description="Qonto resource UUID.", json_schema_extra={"format": "uuid"})
    payment_date: date = Field(..., description="Explicit bookkeeping payment date. Does not execute a payment; avoids date-less retry changes across days.")


class QontoUnmarkSupplierInvoiceAsPaidConfig(_Input):
    """Clear the paid bookkeeping status. Only paid invoices are eligible; repeating fails."""
    operation: Literal["unmark_supplier_invoice_as_paid"] = Field("unmark_supplier_invoice_as_paid", json_schema_extra={"ui:hidden": True})
    supplier_invoice_id: str = Field(..., description="Qonto resource UUID.", json_schema_extra={"format": "uuid"})


class QontoListClientsConfig(_Page):
    """List clients."""
    operation: Literal["list_clients"] = Field("list_clients", json_schema_extra={"ui:hidden": True})
    email: EmailStr | None = None
    name: str | None = None


class QontoGetClientConfig(_Input):
    """Get client."""
    operation: Literal["get_client"] = Field("get_client", json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., description="Qonto resource UUID.", json_schema_extra={"format": "uuid"})


class QontoListProductsConfig(_Page):
    """List products."""
    operation: Literal["list_products"] = Field("list_products", json_schema_extra={"ui:hidden": True})
    product_type: Literal["good", "service"] | None = None


class QontoGetProductConfig(_Input):
    """Get product."""
    operation: Literal["get_product"] = Field("get_product", json_schema_extra={"ui:hidden": True})
    product_id: str = Field(..., description="Qonto resource UUID.", json_schema_extra={"format": "uuid"})


class QontoListClientInvoicesConfig(_Page):
    """List client invoices."""
    operation: Literal["list_client_invoices"] = Field("list_client_invoices", json_schema_extra={"ui:hidden": True})
    statuses: list[Literal["draft", "unpaid", "paid", "canceled"]] | None = None
    exclude_imported: bool = True


class QontoGetClientInvoiceConfig(_Input):
    """Get client invoice."""
    operation: Literal["get_client_invoice"] = Field("get_client_invoice", json_schema_extra={"ui:hidden": True})
    client_invoice_id: str = Field(..., description="Qonto resource UUID.", json_schema_extra={"format": "uuid"})


class QontoListStatementsConfig(_Page):
    """List statements."""
    operation: Literal["list_statements"] = Field("list_statements", json_schema_extra={"ui:hidden": True})


class QontoCreateClientConfig(_Input):
    """Create client."""
    operation: Literal["create_client"] = Field("create_client", json_schema_extra={"ui:hidden": True})
    kind: Literal["company", "individual", "freelancer"]
    name: str | None = Field(None, min_length=1, max_length=250)
    first_name: str | None = Field(None, min_length=1, max_length=60)
    last_name: str | None = Field(None, min_length=1, max_length=60)
    email: EmailStr | None = None
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    locale: str | None = None
    tax_identification_number: str | None = Field(None, max_length=20)
    vat_number: str | None = Field(None, max_length=20)
    address: str | None = Field(None, max_length=250)
    city: str | None = Field(None, max_length=50)
    zip_code: str | None = Field(None, max_length=20)
    country_code: str | None = Field(None, pattern=r"^[A-Z]{2}$")

    @model_validator(mode="after")
    def names(self):
        if self.kind in {"company", "freelancer"} and not self.name:
            raise ValueError("A company or freelancer requires a name")
        if self.kind in {"individual", "freelancer"} and not (self.first_name and self.last_name):
            raise ValueError("An individual or freelancer requires first and last names")
        return self


class QontoUpdateClientConfig(_Input):
    """Update client."""
    operation: Literal["update_client"] = Field("update_client", json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., description="Qonto resource UUID.", json_schema_extra={"format": "uuid"})
    name: str | None = Field(None, min_length=1, max_length=250)
    first_name: str | None = Field(None, min_length=1, max_length=60)
    last_name: str | None = Field(None, min_length=1, max_length=60)
    email: EmailStr | None = None
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    locale: str | None = None
    tax_identification_number: str | None = Field(None, max_length=20)
    vat_number: str | None = Field(None, max_length=20)
    address: str | None = Field(None, max_length=250)
    city: str | None = Field(None, max_length=50)
    zip_code: str | None = Field(None, max_length=20)
    country_code: str | None = Field(None, pattern=r"^[A-Z]{2}$")

    @model_validator(mode="after")
    def change(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "client_id"}):
            raise ValueError("Provide at least one client field to update")
        return self


class QontoDeleteClientConfig(_Input):
    """Delete client."""
    operation: Literal["delete_client"] = Field("delete_client", json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., description="Qonto resource UUID.", json_schema_extra={"format": "uuid"})


class QontoCreateProductConfig(_Input):
    """Create product."""
    operation: Literal["create_product"] = Field("create_product", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1, max_length=120)
    product_type: Literal["good", "service"]
    unit_price_value: str = Field(..., pattern=r"^[0-9]+(?:\.[0-9]+)?$", description="Decimal unit price, for example 150.00.")
    currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    vat_rate: str = Field(..., pattern=r"^[0-9]+(?:\.[0-9]+)?$", description="Decimal VAT rate, for example 0.2 for 20 percent.")
    description: str | None = Field(None, max_length=600)
    unit: str | None = None
    vat_exemption_code: Literal['N1', 'N2', 'N2.1', 'N2.2', 'N3', 'N3.1', 'N3.2', 'N3.3', 'N3.4', 'N3.5', 'N3.6', 'N4', 'N5', 'N6', 'N6.1', 'N6.2', 'N6.3', 'N6.4', 'N6.5', 'N6.6', 'N6.7', 'N6.8', 'N6.9', 'N7', 'S293B', 'S262.1', 'S259', 'S283', 'S261', 'S262', 'S263', 'S19.1', 'S4.1B', 'S4.1A', 'S4', 'S13B', 'S122', 'S25', 'S21', 'S69', 'S20', 'S84.1.2'] | None = None


class QontoDeleteProductConfig(_Input):
    """Delete product."""
    operation: Literal["delete_product"] = Field("delete_product", json_schema_extra={"ui:hidden": True})
    product_id: str = Field(..., description="Qonto resource UUID.", json_schema_extra={"format": "uuid"})


QontoConfig = Annotated[Union[
    QontoGetOrganizationConfig,
    QontoListTransactionsConfig,
    QontoGetTransactionConfig,
    QontoListLabelsConfig,
    QontoListMembershipsConfig,
    QontoListBeneficiariesConfig,
    QontoGetBeneficiaryConfig,
    QontoListSupplierInvoicesConfig,
    QontoGetSupplierInvoiceConfig,
    QontoMarkSupplierInvoiceAsPaidConfig,
    QontoUnmarkSupplierInvoiceAsPaidConfig,
    QontoListClientsConfig,
    QontoGetClientConfig,
    QontoListProductsConfig,
    QontoGetProductConfig,
    QontoListClientInvoicesConfig,
    QontoGetClientInvoiceConfig,
    QontoListStatementsConfig,
    QontoCreateClientConfig,
    QontoUpdateClientConfig,
    QontoDeleteClientConfig,
    QontoCreateProductConfig,
    QontoDeleteProductConfig,
], Field(discriminator="operation")]


class QontoFullConfig(NodeConfig[QontoConfig, QontoAPIKeyCredential]):
    pass


ROUTES = {
    'get_organization': ('GET', '/v2/organization'),
    'list_transactions': ('GET', '/v2/transactions'),
    'get_transaction': ('GET', '/v2/transactions/{transaction_id}'),
    'list_labels': ('GET', '/v2/labels'),
    'list_memberships': ('GET', '/v2/memberships'),
    'list_beneficiaries': ('GET', '/v2/sepa/beneficiaries'),
    'get_beneficiary': ('GET', '/v2/sepa/beneficiaries/{beneficiary_id}'),
    'list_supplier_invoices': ('GET', '/v2/supplier_invoices'),
    'get_supplier_invoice': ('GET', '/v2/supplier_invoices/{supplier_invoice_id}'),
    'mark_supplier_invoice_as_paid': ('POST', '/v2/supplier_invoices/{supplier_invoice_id}/mark_as_paid'),
    'unmark_supplier_invoice_as_paid': ('POST', '/v2/supplier_invoices/{supplier_invoice_id}/unmark_as_paid'),
    'list_clients': ('GET', '/v2/clients'),
    'get_client': ('GET', '/v2/clients/{client_id}'),
    'list_products': ('GET', '/v2/products'),
    'get_product': ('GET', '/v2/products/{product_id}'),
    'list_client_invoices': ('GET', '/v2/client_invoices'),
    'get_client_invoice': ('GET', '/v2/client_invoices/{client_invoice_id}'),
    'list_statements': ('GET', '/v2/statements'),
    'create_client': ('POST', '/v2/clients'),
    'update_client': ('PATCH', '/v2/clients/{client_id}'),
    'delete_client': ('DELETE', '/v2/clients/{client_id}'),
    'create_product': ('POST', '/v2/products'),
    'delete_product': ('DELETE', '/v2/products/{product_id}'),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    return value


class QontoNode(WorkflowNode):
    integration_type = "automation-qonto"
    connection_evidence = ConnectionEvidence(noun="organization", identity_operation="get_organization")

    @classmethod
    def get_config_model(cls):
        return QontoFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect your Qonto organization login and secret key")
        credential = self.config.credentials
        config = self.config.config
        method, template = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = template
        for key in list(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", values.pop(key))
        params, body = {}, None
        if method == "GET":
            params = values
            if config.operation == "list_transactions" and "statuses" in params:
                params["status[]"] = params.pop("statuses")
            elif config.operation == "list_supplier_invoices" and "status" in params:
                params["filter[status]"] = params.pop("status")
            elif config.operation == "list_clients":
                for key in ("email", "name"):
                    if key in params:
                        params["filter[" + key + "]"] = params.pop(key)
            elif config.operation == "list_products" and "product_type" in params:
                params["filter[type]"] = params.pop("product_type")
            elif config.operation == "list_client_invoices" and "statuses" in params:
                params["filter[status]"] = ",".join(params.pop("statuses"))
        elif config.operation == "mark_supplier_invoice_as_paid":
            body = {"supplier_invoice": values}
        elif config.operation == "create_product":
            body = values
            body["type"] = body.pop("product_type")
            body["unit_price"] = {"value": body.pop("unit_price_value"), "currency": body.pop("currency")}
        elif method in {"POST", "PATCH"} and values:
            body = values
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"Authorization": credential.login + ":" + credential.secret_key, "Accept": "application/json"})
        expected = 204 if method == "DELETE" else 201 if config.operation == "create_product" else 200
        if response.status_code != expected:
            message = "Qonto request failed (HTTP " + str(response.status_code) + ")"
            if len(response.content) <= 2_000_000:
                try:
                    error = response.json()
                    message = str(error.get("errors") or error.get("message") or message)[:2000]
                except (ValueError, AttributeError):
                    pass
            return {"status": "error", "error": _redact(message, credential.secret_key), "http_status": response.status_code}
        if expected == 204:
            return {"status": "success", "deleted": True}
        if len(response.content) > 10_000_000:
            raise ValueError("Qonto response exceeds the supported JSON size")
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("errors"):
            raise ValueError("Qonto returned an unexpected response")
        result = {"status": "success", "data": _redact(payload, credential.secret_key)}
        if config.operation.startswith("list_"):
            meta = payload.get("meta", {})
            result["next_page"] = meta.get("next_page") if isinstance(meta, dict) else None
            result["has_more"] = (result["next_page"] is not None) if isinstance(meta, dict) and "next_page" in meta else None
        return result
