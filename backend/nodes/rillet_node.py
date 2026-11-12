"""Single-request operations for Rillet Accounting API v4.

Contract: https://docs.api.rillet.com/openapi/rillet-accounting-api.json
Auth/version/idempotency: https://docs.api.rillet.com/docs/getting-started
"""
from __future__ import annotations
import json
from datetime import date, datetime
from typing import Annotated, Literal, Union
from uuid import UUID
from pydantic import AnyUrl, BaseModel, Json, ConfigDict, Field, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class RilletAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Rillet API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.rillet.io/settings/api-access",
        "x-credential-instructions": "Ask your Rillet team to enable API access, then create an API key in Organization Settings → API access. Paste the key without the Bearer prefix. Choose the environment that issued your key.",
    })
    credential_type: Literal["rillet_api_key"] = Field("rillet_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    environment: Literal["production", "sandbox"] = Field("production", title="Environment")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without spaces or the Bearer prefix")
        return value


# Rillet's own MCP server: agents get its tools through a person's Rillet sign-in.
RilletMcpCredential = mcp_credential("rillet", "https://api.rillet.com/mcp", app="Rillet")
RilletCredential = Union[RilletAPIKeyCredential, RilletMcpCredential]


_JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def structured_editor_values(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        for name, field in cls.model_fields.items():
            if (field.json_schema_extra or {}).get("ui:widget") == "code_editor" and isinstance(value.get(name), (dict, list)):
                value[name] = json.dumps(value[name])
        return value


class _Page(_Input):
    limit: int = Field(25, ge=1, le=100)
    cursor: str | None = Field(None, max_length=4096, description="Use next_cursor from the previous page. Cursors expire after two hours; expired cursors restart the sequence.")


class _Updated(_Input):
    updated_after: datetime | None = Field(None, description="Records updated after this timestamp (updated.gt).")


class _EntityPage(_Page):
    subsidiary_id: UUID | None = None


class _References(_Input):
    external_reference_id: str | None = None
    external_reference_type: str | None = None

    @model_validator(mode="after")
    def paired_references(self):
        if bool(self.external_reference_id) != bool(self.external_reference_type):
            raise ValueError("Supply both external reference ID and type")
        return self


class RilletGetOrganizationConfig(_Input):
    """Read the organization associated with this API key."""
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"ui:hidden": True})


class RilletListAccountsConfig(_Updated):
    operation: Literal["list_accounts"] = Field("list_accounts", json_schema_extra={"ui:hidden": True})


class RilletListSubsidiariesConfig(_Input):
    operation: Literal["list_subsidiaries"] = Field("list_subsidiaries", json_schema_extra={"ui:hidden": True})


class RilletListCustomersConfig(_Page, _Updated, _References):
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})
    search: str | None = None
    sort_by: Literal["created", "updated"] | None = None


class RilletGetCustomerConfig(_Input):
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True})
    customer_id: UUID


class Address(_Input):
    line1: str
    line2: str | None = None
    city: str
    state: str | None = Field(None, description="Required for United States addresses.")
    zip_code: str
    country: str = Field(..., pattern=r"^[A-Z]{2}$")

    @model_validator(mode="after")
    def us_state(self):
        if self.country == "US" and not self.state:
            raise ValueError("State is required for United States addresses")
        return self


class CustomerEmail(_Input):
    email: str
    type: Literal["MAIN_SENDER", "CC", "BCC"]


class ExternalReference(_Input):
    type: str
    id: str
    url: AnyUrl | None = None


class _Create(_Input):
    idempotency_key: str | None = Field(None, min_length=1, max_length=255, pattern=r"^[!-~]+$",
        description="Unique key reused only when retrying this same creation. Rillet retains it for 24 hours.")


class RilletCreateCustomerConfig(_Create):
    """Create a customer with optional billing/shipping addresses and emails."""
    operation: Literal["create_customer"] = Field("create_customer", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    name_on_invoice: str | None = None
    address: Json[Address] | None = Field(None, json_schema_extra=_JSON_EDITOR)
    shipping_address: Json[Address] | None = Field(None, json_schema_extra=_JSON_EDITOR)
    emails: Json[list[CustomerEmail]] | None = Field(None, json_schema_extra=_JSON_EDITOR)
    external_references: Json[list[ExternalReference]] | None = Field(None, json_schema_extra=_JSON_EDITOR)
    payment_terms: int | None = Field(None, ge=0)
    send_invoices_automatically: StrictBool | None = None
    send_payment_reminders: StrictBool | None = None
    allow_online_payments: StrictBool | None = None


class RilletListVendorsConfig(_Page, _Updated):
    operation: Literal["list_vendors"] = Field("list_vendors", json_schema_extra={"ui:hidden": True})


class RilletGetVendorConfig(_Input):
    operation: Literal["get_vendor"] = Field("get_vendor", json_schema_extra={"ui:hidden": True})
    vendor_id: UUID


class RilletCreateVendorConfig(_Create):
    operation: Literal["create_vendor"] = Field("create_vendor", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    account_code: str | None = None
    address: Json[Address] | None = Field(None, json_schema_extra=_JSON_EDITOR)
    email: str | None = Field(None, json_schema_extra={"format": "email"})
    payment_terms: int | None = Field(None, ge=0, le=180)
    external_references: Json[list[ExternalReference]] | None = Field(None, json_schema_extra=_JSON_EDITOR)
    ten_ninety_nine_eligible: StrictBool | None = None
    tax_id: str | None = None


class RilletListProductsConfig(_Page):
    operation: Literal["list_products"] = Field("list_products", json_schema_extra={"ui:hidden": True})
    status: str | None = None
    currency: str | None = None
    product_types: list[Literal["PRODUCT", "BUNDLE"]] | None = None


class RilletGetProductConfig(_Input):
    operation: Literal["get_product"] = Field("get_product", json_schema_extra={"ui:hidden": True})
    product_id: UUID


class RilletListContractsConfig(_EntityPage):
    operation: Literal["list_contracts"] = Field("list_contracts", json_schema_extra={"ui:hidden": True})
    customer_id: UUID | None = None
    status: Literal["ACTIVE", "IN_EFFECT", "CANCELLED", "ENDED", "AMENDED"] | None = None


class RilletGetContractConfig(_Input):
    operation: Literal["get_contract"] = Field("get_contract", json_schema_extra={"ui:hidden": True})
    contract_id: UUID


class RilletListInvoicesConfig(_EntityPage, _Updated, _References):
    operation: Literal["list_invoices"] = Field("list_invoices", json_schema_extra={"ui:hidden": True})
    customer_id: UUID | None = None
    overdue: StrictBool | None = None
    status: Literal["UNPAID", "PAID", "PARTIALLY_PAID", "UNBILLED", "CREDITED", "PARTIALLY_CREDITED"] | None = None


class RilletGetInvoiceConfig(_Input):
    operation: Literal["get_invoice"] = Field("get_invoice", json_schema_extra={"ui:hidden": True})
    invoice_id: UUID


class MonetaryAmount(_Input):
    amount: str = Field(..., pattern=r"^-?[0-9]+(?:\.[0-9]+)?$", description="Decimal string; round bill and journal amounts to the currency's decimal places.")
    currency: str = Field(..., pattern=r"^[A-Z]{3}$")


class InvoicePrice(_Input):
    product_id: UUID
    quantity: float = Field(..., allow_inf_nan=False)
    amount_per_unit: MonetaryAmount


class CalendarPeriod(_Input):
    start: date
    end: date


class InvoiceRevenue(_Input):
    period: CalendarPeriod | None = None
    account_code: str | None = None


class InvoiceItem(_Input):
    description: str
    price: InvoicePrice
    revenue: InvoiceRevenue | None = None


class RilletCreateInvoiceConfig(_Create):
    """Create a full AR/revenue invoice; HTTP 202 means held for approval."""
    operation: Literal["create_invoice"] = Field("create_invoice", json_schema_extra={"ui:hidden": True})
    scope: Literal["FULL"] = Field("FULL", json_schema_extra={"ui:hidden": True})
    customer_id: UUID
    invoice_date: date
    items: Json[list[InvoiceItem]] = Field(..., min_length=1, json_schema_extra=_JSON_EDITOR)
    due_date: date | None = None
    subsidiary_id: UUID | None = None
    purchase_order_number: str | None = None
    memo: str | None = None
    bank_account_id: UUID | None = None
    external_references: Json[list[ExternalReference]] | None = Field(None, json_schema_extra=_JSON_EDITOR)


class RilletUpdateInvoiceSentStatusConfig(_Input):
    """Record delivery status after delivery is confirmed; does not send email."""
    operation: Literal["update_invoice_sent_status"] = Field("update_invoice_sent_status", json_schema_extra={"ui:hidden": True})
    invoice_id: UUID
    sent: StrictBool


class RilletListBillsConfig(_EntityPage, _Updated):
    operation: Literal["list_bills"] = Field("list_bills", json_schema_extra={"ui:hidden": True})
    vendor_id: UUID | None = None
    status: Literal["UNPAID", "PAID", "PARTIALLY_PAID", "CREDITED", "PARTIALLY_CREDITED", "APPLIED"] | None = None


class RilletGetBillConfig(_Input):
    operation: Literal["get_bill"] = Field("get_bill", json_schema_extra={"ui:hidden": True})
    bill_id: UUID


class BillItem(_Input):
    account_code: str
    amount: MonetaryAmount
    description: str | None = None
    service_period: CalendarPeriod | None = None


class RilletCreateBillConfig(_Create):
    operation: Literal["create_bill"] = Field("create_bill", json_schema_extra={"ui:hidden": True})
    vendor_id: UUID
    expense_number: str
    items: Json[list[BillItem]] = Field(..., min_length=1, json_schema_extra=_JSON_EDITOR)
    bill_date: date
    due_date: date
    impact_date: date | None = None
    subsidiary_id: UUID | None = None
    external_references: Json[list[ExternalReference]] | None = Field(None, json_schema_extra=_JSON_EDITOR)


class RilletListJournalEntriesConfig(_EntityPage, _Updated):
    operation: Literal["list_journal_entries"] = Field("list_journal_entries", json_schema_extra={"ui:hidden": True})
    book_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    account_ids: Json[list[UUID]] | None = Field(None, json_schema_extra=_JSON_EDITOR)
    sort_by: Literal["created", "updated"] | None = None


class RilletGetJournalEntryConfig(_Input):
    operation: Literal["get_journal_entry"] = Field("get_journal_entry", json_schema_extra={"ui:hidden": True})
    journal_entry_id: UUID


class JournalItem(_Input):
    amount: MonetaryAmount
    account_code: str
    side: Literal["DEBIT", "CREDIT"]
    description: str | None = None


class RilletCreateJournalEntryConfig(_Create):
    operation: Literal["create_journal_entry"] = Field("create_journal_entry", json_schema_extra={"ui:hidden": True})
    date: date
    name: str
    currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    items: Json[list[JournalItem]] = Field(..., min_length=2, json_schema_extra=_JSON_EDITOR)
    reversal_date: date | None = None
    subsidiary_id: UUID | None = None
    book_id: UUID | None = None


class RilletListBankAccountsConfig(_Input):
    operation: Literal["list_bank_accounts"] = Field("list_bank_accounts", json_schema_extra={"ui:hidden": True})
    subsidiary_id: UUID | None = None


class RilletListBankTransactionsConfig(_EntityPage, _Updated):
    operation: Literal["list_bank_transactions"] = Field("list_bank_transactions", json_schema_extra={"ui:hidden": True})
    bank_account_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    sort_by: Literal["created", "updated"] | None = None


RilletConfig = Annotated[Union[
    RilletGetOrganizationConfig, RilletListAccountsConfig, RilletListSubsidiariesConfig,
    RilletListCustomersConfig, RilletGetCustomerConfig, RilletCreateCustomerConfig,
    RilletListVendorsConfig, RilletGetVendorConfig, RilletCreateVendorConfig,
    RilletListProductsConfig, RilletGetProductConfig, RilletListContractsConfig, RilletGetContractConfig,
    RilletListInvoicesConfig, RilletGetInvoiceConfig, RilletCreateInvoiceConfig, RilletUpdateInvoiceSentStatusConfig,
    RilletListBillsConfig, RilletGetBillConfig, RilletCreateBillConfig,
    RilletListJournalEntriesConfig, RilletGetJournalEntryConfig, RilletCreateJournalEntryConfig,
    RilletListBankAccountsConfig, RilletListBankTransactionsConfig,
], Field(discriminator="operation")]


class RilletFullConfig(NodeConfig[RilletConfig, RilletCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Every entry is one operation in the pinned v4.0 contract.
ROUTES = {
    "get_organization": ("GET", "/organizations/self", None),
    "list_accounts": ("GET", "/accounts", "accounts"),
    "list_subsidiaries": ("GET", "/subsidiaries", "subsidiaries"),
    "list_customers": ("GET", "/customers", "customers"),
    "get_customer": ("GET", "/customers/{customer_id}", None),
    "create_customer": ("POST", "/customers", None),
    "list_vendors": ("GET", "/vendors", "vendors"),
    "get_vendor": ("GET", "/vendors/{vendor_id}", None),
    "create_vendor": ("POST", "/vendors", None),
    "list_products": ("GET", "/products", "products"),
    "get_product": ("GET", "/products/{product_id}", None),
    "list_contracts": ("GET", "/contracts", "contracts"),
    "get_contract": ("GET", "/contracts/{contract_id}", None),
    "list_invoices": ("GET", "/invoices", "invoices"),
    "get_invoice": ("GET", "/invoices/{invoice_id}", None),
    "create_invoice": ("POST", "/invoices", None),
    "update_invoice_sent_status": ("PUT", "/invoices/{invoice_id}/sent-status", None),
    "list_bills": ("GET", "/bills", "bills"),
    "get_bill": ("GET", "/bills/{bill_id}", None),
    "create_bill": ("POST", "/bills", None),
    "list_journal_entries": ("GET", "/journal-entries", "journal_entries"),
    "get_journal_entry": ("GET", "/journal-entries/{journal_entry_id}", None),
    "create_journal_entry": ("POST", "/journal-entries", None),
    "list_bank_accounts": ("GET", "/bank-accounts", "accounts"),
    "list_bank_transactions": ("GET", "/bank-transactions", "bank_transactions"),
}
QUERY_NAMES = {"updated_after": "updated.gt", "date_from": "date.gte", "date_to": "date.lte", "product_types": "type"}


class RilletNode(WorkflowNode):
    integration_type = "automation-rillet"
    credential_provider_labels = {"rillet": "Rillet Account"}
    connection_evidence = ConnectionEvidence(noun="Rillet organization", identity_operation="get_organization", identity_keys=("trade_name",))

    @classmethod
    def get_config_model(cls):
        return RilletFullConfig

    @classmethod
    def _check_credential(cls, data):
        raw = data.get("credentials")
        if raw is not None and (not isinstance(raw, dict) or raw.get("credential_type", "rillet_api_key") != "rillet_api_key"):
            raise ValueError("Connect a Rillet API key credential")

    @classmethod
    def parse_config(cls, config_data):
        cls._check_credential(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._check_credential(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a Rillet API key")
        config = self.config.config
        method, template, collection = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        values.pop("operation")
        path = template
        for name in tuple(values):
            if "{" + name + "}" in path:
                path = path.replace("{" + name + "}", values.pop(name))
        idempotency_key = values.pop("idempotency_key", None)
        headers = {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json", "X-Rillet-API-Version": "4"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        kwargs = {}
        if method == "GET":
            params = {}
            for name, value in values.items():
                if isinstance(value, list):
                    value = ",".join(value)
                elif isinstance(value, bool):
                    value = str(value).lower()
                params[QUERY_NAMES.get(name, name)] = value
            kwargs["params"] = params
        else:
            kwargs["json"] = values
        base = "https://api.rillet.com" if credential.environment == "production" else "https://sandbox.api.rillet.com"
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, base + path, headers=headers, **kwargs)
        if not 200 <= response.status_code < 300:
            message = response.text[:4000].replace(credential.api_key, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": message or "Rillet rejected the request"}
        if response.status_code == 200 and not response.content and config.operation == "update_invoice_sent_status":
            return {"status": "success", "http_status": response.status_code, "acknowledged": True}
        if len(response.content) > 10_000_000 or response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Expected a bounded JSON response from Rillet")
        body = response.json()
        if not isinstance(body, dict) or "error" in body or "errors" in body:
            raise ValueError("Unexpected Rillet response")
        if response.status_code == 202:
            if config.operation != "create_invoice":
                raise ValueError("Unexpected asynchronous Rillet response")
            return {"status": "pending_approval", "http_status": 202, "invoice_created": False, "data": body}
        if response.status_code != 200:
            raise ValueError("Unexpected Rillet success status")
        if config.operation == "get_organization":
            if any(not isinstance(body.get(name), str) or not body[name].strip() for name in ("id", "trade_name", "currency", "timezone")):
                raise ValueError("Rillet organization identity is incomplete")
        if collection:
            if not isinstance(body.get(collection), list):
                raise ValueError("Rillet list response is missing " + collection)
            pagination = body.get("pagination", {})
            if not isinstance(pagination, dict):
                raise ValueError("Invalid Rillet pagination")
            cursor = pagination.get("next_cursor")
            if cursor is not None and not isinstance(cursor, str):
                raise ValueError("Invalid Rillet next cursor")
            return {"status": "success", "items": body[collection], "next_cursor": cursor, "has_more": bool(cursor), "data": body}
        return {"status": "success", "data": body}
