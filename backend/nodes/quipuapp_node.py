"""Quipu API v1: account-scoped JSON:API operations.

Contract: https://raw.githubusercontent.com/quipuapp/api-v1-docs/main/openapi.yaml
Authentication uses the documented client-credentials grant, not browser consent.
No webhooks or created/updated list filters are documented by the provider.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://getquipu.com"
MEDIA = "application/vnd.quipu.v1+json"
CREDENTIAL_TYPE = "quipuapp_api_credentials"
DOCS = "https://quipuapp.github.io/api-v1-docs/"


class QuipuAPICredential(BaseModel):
    model_config = ConfigDict(title="Quipu API Client", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": DOCS,
            "x-credential-instructions": "Copy the client ID and client secret from your Quipu API application, and the business account slug from its Quipu URL. NoClick exchanges these for a two-hour access token using the ecommerce scope whenever an operation runs. These are API application credentials; no browser sign-in is needed.",
        })
    credential_type: Literal["quipuapp_api_credentials"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., min_length=1, max_length=4096, title="Client ID", repr=False, json_schema_extra={"ui:widget": "password"})
    client_secret: str = Field(..., min_length=1, max_length=4096, title="Client secret", repr=False, json_schema_extra={"ui:widget": "password"})
    owner_slug: str = Field(..., min_length=1, max_length=255, title="Business account slug", description="The account/business URL slug, without the host or slashes.")

    @field_validator("client_id", "client_secret", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(ord(c) < 33 or ord(c) == 127 for c in value) or (info.field_name == "client_id" and ":" in value):
            raise ValueError("Paste the API credential without an authorization header")
        return value

    @field_validator("owner_slug")
    @classmethod
    def slug(cls, value):
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,254}", value):
            raise ValueError("Paste only the business account slug from Quipu")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Config):
    page: int = Field(1, ge=1, title="Page number")
    page_size: int = Field(25, ge=1, le=100, title="Page size")


class _Resource(_Config):
    resource_id: int = Field(..., ge=1, title="Resource ID", description="The numeric Quipu ID returned by a list or create operation.")


class _ContactFields(_Config):
    name: str | None = Field(None, min_length=1, max_length=1000)
    country_code: str | None = Field(None, min_length=2, max_length=2)
    tax_id: str | None = None
    document_type: Literal["NIF", "passport", "official_id_from_residence_country", "residence_permit", "other", "none"] | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    town: str | None = None
    zip_code: str | None = None
    description: str | None = None
    client_number: str | None = None
    supplier_number: str | None = None
    employee_number: str | None = None
    is_supplier_of_direct_goods: bool | None = None
    bank_account_number: str | None = None
    bank_account_swift_bic: str | None = None


class _LineItem(_Config):
    id: str | None = Field(None, description="Existing line ID on updates; omitting it creates a new line.")
    concept: str = Field(..., min_length=1)
    unitary_amount: str = Field(..., pattern=r"^-?[0-9]+(?:\.[0-9]+)?$")
    quantity: float = Field(1, allow_inf_nan=False)
    vat_percent: float | None = Field(None, allow_inf_nan=False)
    retention_percent: float | None = Field(None, allow_inf_nan=False)
    discount_percent: float | None = Field(None, allow_inf_nan=False)
    description: str | None = None
    accounting_category_id: int | None = Field(None, ge=1)
    accounting_subcategory_id: int | None = Field(None, ge=1)


class _DocumentFields(_Config):
    issue_date: date | None = None
    number: str | None = None
    complete_number: str | None = None
    paid_at: date | None = Field(None, description="Payment date. Explicit null on an update clears the payment date.")
    payment_method: str | None = None
    tags: str | None = Field(None, description="Comma-separated tag names.")
    notes: str | None = None
    numeration_id: int | None = Field(None, ge=1, title="Numbering series ID")
    accounting_category_id: int | None = Field(None, ge=1)
    accounting_subcategory_id: int | None = Field(None, ge=1)
    items_json: str | None = Field(None, max_length=100000, title="Line items (JSON)",
        description='Array of line objects, e.g. [{"concept":"Consulting services","unitary_amount":"1500.00","quantity":1,"vat_percent":21}]. On update this REPLACES all lines: retain existing line IDs to update them, and repeat their accounting category/subcategory IDs to preserve them.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @field_validator("items_json")
    @classmethod
    def line_items(cls, value):
        if value is not None:
            items = json.loads(value)
            if not isinstance(items, list) or not 1 <= len(items) <= 500:
                raise ValueError("Supply a JSON array of 1 to 500 line items")
            TypeAdapter(list[_LineItem]).validate_python(items)
        return value


class _InvoiceFields(_DocumentFields):
    kind: Literal["income", "expenses"] | None = None
    operation_date: date | None = None
    contact_id: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def operation_date_order(self):
        if self.issue_date and self.operation_date and self.operation_date > self.issue_date:
            raise ValueError("Operation date must be on or before the issue date")
        return self


class _SimplifiedFields(_InvoiceFields):
    recipient_name: str | None = None
    target_country: str | None = None


class _AdditionalFields(_DocumentFields):
    recipient_name: str | None = None
    target_country: str | None = None


class _CreateDocument(_Config):
    @model_validator(mode="after")
    def creation_rules(self):
        kind = getattr(self, "kind", "income")
        if kind == "expenses" and self.issue_date is None:
            raise ValueError("Expense documents require an issue date")
        if kind == "income":
            if self.issue_date and not (self.number or self.complete_number or self.numeration_id):
                raise ValueError("A dated income document needs a number or numbering series (series exception requires a non-Verifactu account)")
            if (self.number or self.complete_number) and not self.issue_date:
                raise ValueError("Send the number and issue date together")
        return self


class ListContacts(_Page):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})
    kind: Literal["client", "supplier", "employee"] | None = None
    query: str | None = None
    email: str | None = None
    tax_id: str | None = None
    country: str | None = None
    sort: Literal["name", "-name", "total_paid_income", "-total_paid_income", "total_unpaid_income", "-total_unpaid_income", "total_paid_expenses", "-total_paid_expenses", "total_unpaid_expenses", "-total_unpaid_expenses"] | None = None


class ListInvoices(_Page):
    operation: Literal["list_invoices"] = Field("list_invoices", title="List Invoices", json_schema_extra={"ui:hidden": True})
    kind: Literal["income", "expenses"] | None = None
    query: str | None = None
    period: str | None = Field(None, description="Quipu accounting period filter.")
    payment_status: Literal["paid", "unpaid", "due", "pending"] | None = None
    contact_id: int | None = Field(None, ge=1)


class ListSimplifiedInvoices(_Page):
    operation: Literal["list_simplified_invoices"] = Field("list_simplified_invoices", title="List Simplified Invoices", json_schema_extra={"ui:hidden": True})
    kind: Literal["income", "expenses"] | None = None


class ListNumberingSeries(_Page):
    operation: Literal["list_numbering_series"] = Field("list_numbering_series", title="List Numbering Series", json_schema_extra={"ui:hidden": True})
    applicable_to: Literal["invoices", "tickets", "additional_incomes", "budgets", "orders", "delivery_notes"] | None = None
    amending: bool | None = None
    prefix: str | None = None
    applies_to: Literal["new", "existing"] | None = None


class ListAccountingCategories(_Page):
    operation: Literal["list_accounting_categories"] = Field("list_accounting_categories", title="List Accounting Categories", json_schema_extra={"ui:hidden": True})
    kind: str | None = None
    prefix: str | None = None


class ListAccountingSubcategories(_Page):
    operation: Literal["list_accounting_subcategories"] = Field("list_accounting_subcategories", title="List Accounting Subcategories", json_schema_extra={"ui:hidden": True})
    accounting_category_id: int | None = Field(None, ge=1)


class CreateContact(_ContactFields):
    operation: Literal["create_contact"] = Field("create_contact", title="Create Contact", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    country_code: str = Field(..., min_length=2, max_length=2)


class UpdateContact(_Resource, _ContactFields):
    operation: Literal["update_contact"] = Field("update_contact", title="Update Contact", json_schema_extra={"ui:hidden": True})


class CreateInvoice(_CreateDocument, _InvoiceFields):
    operation: Literal["create_invoice"] = Field("create_invoice", title="Create Invoice", json_schema_extra={"ui:hidden": True})
    kind: Literal["income", "expenses"] = "income"
    contact_id: int = Field(..., ge=1)
    items_json: str = Field(..., max_length=100000, title="Line items (JSON)", description=_DocumentFields.model_fields["items_json"].description, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


class UpdateInvoice(_Resource, _InvoiceFields):
    operation: Literal["update_invoice"] = Field("update_invoice", title="Update Invoice", json_schema_extra={"ui:hidden": True})


class CreateSimplifiedInvoice(_CreateDocument, _SimplifiedFields):
    operation: Literal["create_simplified_invoice"] = Field("create_simplified_invoice", title="Create Simplified Invoice", json_schema_extra={"ui:hidden": True})
    kind: Literal["income", "expenses"] = "income"
    items_json: str = Field(..., max_length=100000, title="Line items (JSON)", description=_DocumentFields.model_fields["items_json"].description, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @model_validator(mode="after")
    def recipient(self):
        if self.kind == "income" and not (self.contact_id or self.recipient_name):
            raise ValueError("Income simplified invoices need a contact or recipient name")
        return self


class UpdateSimplifiedInvoice(_Resource, _SimplifiedFields):
    operation: Literal["update_simplified_invoice"] = Field("update_simplified_invoice", title="Update Simplified Invoice", json_schema_extra={"ui:hidden": True})


class CreateAdditionalIncome(_CreateDocument, _AdditionalFields):
    operation: Literal["create_additional_income"] = Field("create_additional_income", title="Create Additional Income", json_schema_extra={"ui:hidden": True})
    issue_date: date
    recipient_name: str = Field(..., min_length=1)
    items_json: str = Field(..., max_length=100000, title="Line items (JSON)", description=_DocumentFields.model_fields["items_json"].description, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


class UpdateAdditionalIncome(_Resource, _AdditionalFields):
    operation: Literal["update_additional_income"] = Field("update_additional_income", title="Update Additional Income", json_schema_extra={"ui:hidden": True})


class CreatePaysheet(_Config):
    operation: Literal["create_paysheet"] = Field("create_paysheet", title="Create Paysheet", json_schema_extra={"ui:hidden": True})
    issue_date: date
    contact_id: int = Field(..., ge=1, description="Employee contact ID; the employee must have a tax ID in Quipu.")
    net_pay: float = Field(..., allow_inf_nan=False)
    employee_ss_amount: float | None = Field(None, allow_inf_nan=False)
    employee_retention: float | None = Field(None, allow_inf_nan=False)
    company_ss_amount: float | None = Field(None, allow_inf_nan=False)
    paid_at: date | None = None
    payment_method: str | None = None
    tags: str | None = None


class GetContact(_Resource):
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})


class DeleteContact(_Resource):
    operation: Literal["delete_contact"] = Field("delete_contact", title="Delete Contact", json_schema_extra={"ui:hidden": True})


class GetInvoice(_Resource):
    operation: Literal["get_invoice"] = Field("get_invoice", title="Get Invoice", json_schema_extra={"ui:hidden": True})


class DeleteInvoice(_Resource):
    operation: Literal["delete_invoice"] = Field("delete_invoice", title="Delete Invoice", json_schema_extra={"ui:hidden": True})


class GetSimplifiedInvoice(_Resource):
    operation: Literal["get_simplified_invoice"] = Field("get_simplified_invoice", title="Get Simplified Invoice", json_schema_extra={"ui:hidden": True})


class DeleteSimplifiedInvoice(_Resource):
    operation: Literal["delete_simplified_invoice"] = Field("delete_simplified_invoice", title="Delete Simplified Invoice", json_schema_extra={"ui:hidden": True})


class ListAdditionalIncomes(_Page):
    operation: Literal["list_additional_incomes"] = Field("list_additional_incomes", title="List Additional Incomes", json_schema_extra={"ui:hidden": True})


class GetAdditionalIncome(_Resource):
    operation: Literal["get_additional_income"] = Field("get_additional_income", title="Get Additional Income", json_schema_extra={"ui:hidden": True})


class ListPaysheets(_Page):
    operation: Literal["list_paysheets"] = Field("list_paysheets", title="List Paysheets", json_schema_extra={"ui:hidden": True})


class GetPaysheet(_Resource):
    operation: Literal["get_paysheet"] = Field("get_paysheet", title="Get Paysheet", json_schema_extra={"ui:hidden": True})


Operation = Annotated[
    Union[
        ListContacts,
        GetContact,
        CreateContact,
        UpdateContact,
        DeleteContact,
        ListInvoices,
        GetInvoice,
        CreateInvoice,
        UpdateInvoice,
        DeleteInvoice,
        ListSimplifiedInvoices,
        GetSimplifiedInvoice,
        CreateSimplifiedInvoice,
        UpdateSimplifiedInvoice,
        DeleteSimplifiedInvoice,
        ListAdditionalIncomes,
        GetAdditionalIncome,
        CreateAdditionalIncome,
        UpdateAdditionalIncome,
        ListPaysheets,
        GetPaysheet,
        CreatePaysheet,
        ListNumberingSeries,
        ListAccountingCategories,
        ListAccountingSubcategories
    ],
    Field(discriminator="operation")]


class QuipuConfig(NodeConfig[Operation, QuipuAPICredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


OPERATIONS = {
    "list_contacts": ('GET', 'contacts'),
    "get_contact": ('GET', 'contacts'),
    "create_contact": ('POST', 'contacts'),
    "update_contact": ('PATCH', 'contacts'),
    "delete_contact": ('DELETE', 'contacts'),
    "list_invoices": ('GET', 'invoices'),
    "get_invoice": ('GET', 'invoices'),
    "create_invoice": ('POST', 'invoices'),
    "update_invoice": ('PATCH', 'invoices'),
    "delete_invoice": ('DELETE', 'invoices'),
    "list_simplified_invoices": ('GET', 'simplified_invoices'),
    "get_simplified_invoice": ('GET', 'simplified_invoices'),
    "create_simplified_invoice": ('POST', 'simplified_invoices'),
    "update_simplified_invoice": ('PATCH', 'simplified_invoices'),
    "delete_simplified_invoice": ('DELETE', 'simplified_invoices'),
    "list_additional_incomes": ('GET', 'additional_incomes'),
    "get_additional_income": ('GET', 'additional_incomes'),
    "create_additional_income": ('POST', 'additional_incomes'),
    "update_additional_income": ('PATCH', 'additional_incomes'),
    "list_paysheets": ('GET', 'paysheets'),
    "get_paysheet": ('GET', 'paysheets'),
    "create_paysheet": ('POST', 'paysheets'),
    "list_numbering_series": ('GET', 'numbering_series'),
    "list_accounting_categories": ('GET', 'accounting_categories'),
    "list_accounting_subcategories": ('GET', 'accounting_subcategories'),
}

# Relationship keys are deliberately separate from writable attributes.
RELATIONSHIPS = {"contact_id": ("contact", "contacts"), "numeration_id": ("numeration", "numbering_series"),
                 "accounting_category_id": ("accounting_category", "accounting_categories"),
                 "accounting_subcategory_id": ("accounting_subcategory", "accounting_subcategories")}
NULLABLE_ATTRIBUTES = {"paid_at", "number", "complete_number", "operation_date", "document_type"}


def _write_body(config, resource):
    values = config.model_dump(mode="json", exclude_unset=True, exclude={"operation", "resource_id", "items_json"})
    # Required/defaulted kind still travels on every create, even when the person accepts its default.
    if config.operation.startswith("create_") and hasattr(config, "kind"):
        values["kind"] = config.kind
    attrs, relationships = {}, {}
    for key, value in values.items():
        if key in RELATIONSHIPS:
            if value is not None:
                relation, kind = RELATIONSHIPS[key]
                relationships[relation] = {"data": {"type": kind, "id": str(value)}}
        elif value is not None or key in NULLABLE_ATTRIBUTES:
            attrs[key] = value
    items_json = getattr(config, "items_json", None)
    if items_json is not None:
        items = TypeAdapter(list[_LineItem]).validate_python(json.loads(items_json))
        rows = []
        for item in items:
            fields = item.model_dump(exclude_none=True)
            identifier = fields.pop("id", None)
            rels = {}
            for key in ("accounting_category_id", "accounting_subcategory_id"):
                if key in fields:
                    relation, kind = RELATIONSHIPS[key]
                    rels[relation] = {"data": {"id": str(fields.pop(key)), "type": kind}}
            row = {"type": "book_entry_items", "attributes": fields}
            if identifier is not None:
                row["id"] = identifier
            if rels:
                row["relationships"] = rels
            rows.append(row)
        relationships["items"] = {"data": rows}
    data = {"type": resource, "attributes": attrs}
    if relationships:
        data["relationships"] = relationships
    return {"data": data}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    return value


class QuipuNode(WorkflowNode):
    integration_type = "automation-quipuapp"
    connection_evidence = ConnectionEvidence(noun="contacts", operation="list_contacts")

    @classmethod
    def get_config_model(cls):
        return QuipuConfig

    @staticmethod
    def _json(response):
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Quipu returned an unexpected JSON envelope")
        if response.is_error or "errors" in body or "error" in body:
            details = body.get("errors") or body.get("error_description") or body.get("error")
            raise ValueError(f"Quipu HTTP {response.status_code}: {json.dumps(details, ensure_ascii=False)[:2000]}")
        response.raise_for_status()
        return body

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect Quipu API credentials")
        config = self.config.config
        method, resource = OPERATIONS[config.operation]
        basic = base64.b64encode((credential.client_id + ":" + credential.client_secret).encode()).decode()
        secrets = [credential.client_id, credential.client_secret, basic]
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.post(BASE + "/oauth/token",
                    headers={"Authorization": "Basic " + basic, "Accept": "application/json"},
                    data={"grant_type": "client_credentials", "scope": "ecommerce"})
                token_body = self._json(response)
                token = token_body.get("access_token")
                if not isinstance(token, str) or not token or any(c.isspace() for c in token):
                    raise ValueError("Quipu did not return an access token")
                secrets.append(token)
                path = "/" + quote(credential.owner_slug, safe="") + "/" + resource
                if isinstance(config, _Resource):
                    path += "/" + str(config.resource_id)
                headers = {"Authorization": "Bearer " + token, "Accept": MEDIA}
                kwargs = {}
                if isinstance(config, _Page):
                    params = {"page[number]": config.page, "page[size]": config.page_size}
                    for key, value in config.model_dump(mode="json", exclude_none=True, exclude={"operation", "page", "page_size"}).items():
                        wire = "q" if key == "query" else key
                        params["sort" if key == "sort" else "filter[" + wire + "]"] = str(value).lower() if isinstance(value, bool) else value
                    kwargs["params"] = params
                elif method in {"POST", "PATCH"}:
                    headers["Content-Type"] = MEDIA
                    kwargs["json"] = _write_body(config, resource)
                response = await client.request(method, BASE + path, headers=headers, **kwargs)
                expected = 204 if method == "DELETE" else 201 if method == "POST" else 200
                if response.status_code != expected:
                    self._json(response)  # Preserve the provider's rejection text when available.
                    raise ValueError(f"Quipu returned HTTP {response.status_code}; expected {expected}. Check the result before retrying a write.")
                if expected == 204:
                    output = {"status": "success", "deleted": True, "resource_id": config.resource_id}
                else:
                    body = self._json(response)
                    if "data" not in body or not isinstance(body["data"], list if isinstance(config, _Page) else dict):
                        raise ValueError("Quipu response is missing resource data")
                    output = {"status": "success", **body}
                    if isinstance(config, _Page):
                        # Flatten only the display rows; the original JSON:API data and included graph survive.
                        output["items"] = [{**row.get("attributes", {}), "id": row["id"], "type": row["type"]} for row in body["data"]]
                        info = body.get("meta", {}).get("pagination_info", {})
                        current, total = info.get("current_page"), info.get("total_pages")
                        output["next_page"] = current + 1 if isinstance(current, int) and isinstance(total, int) and current < total else None
                        output["pagination_known"] = isinstance(current, int) and isinstance(total, int)
        except (httpx.HTTPError, ValueError) as exc:
            # Exception messages may contain provider-echoed credentials; scrub both tokens and Basic credentials.
            raise ValueError(_redact(str(exc), secrets)) from None
        output = _redact(output, secrets)
        await self.emit(output)
        return output
