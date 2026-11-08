"""Moneybird v2 personal-token integration. Each operation makes one API request.

Lists return one page. Creates make drafts; sending invoices/estimates is separate.
Contract: https://raw.githubusercontent.com/moneybird/openapi/main/openapi.json
Authentication: https://developer.moneybird.com/authentication/
"""
from __future__ import annotations
from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://moneybird.com/api/v2"
ID = Annotated[str, Field(pattern=r"^[0-9]+$", max_length=40, description="Moneybird numeric ID. Copy from the resource URL or a list operation.")]

class MoneybirdTokenCredential(BaseModel):
    model_config = ConfigDict(title="Moneybird Personal API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developer.moneybird.com/authentication/",
        "x-credential-instructions": "Register a personal API token in Moneybird and paste it here. Select sales_invoices for invoices, estimates for estimates, settings for products and accounting settings, and bank for financial accounts. Contacts accept any of these scopes. The token's accessible administrations are read to verify the connection."
    })
    credential_type: Literal["moneybird_token"] = Field("moneybird_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Personal API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def clean_token(cls, value):
        value = clean_secret(value, field_name="Personal API token")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste only the personal API token without a Bearer prefix")
        return value

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class AdministrationInput(Input):
    administration_id: ID

class PageInput(AdministrationInput):
    page: int = Field(1, ge=1, description="Fetch one page; increment to retrieve subsequent pages.")
    per_page: int = Field(100, ge=1, le=100)

class Detail(Input):
    description: str
    price: str = Field(..., pattern=r"^-?[0-9]+(?:[.,][0-9]+)?$", description="Decimal unit price, e.g. 129.95.")
    amount: str = Field("1", pattern=r"^[0-9]+(?:[.,][0-9]+)?$")
    tax_rate_id: ID | None = None
    ledger_account_id: ID | None = None
    product_id: ID | None = None

class ContactFields(Input):
    company_name: str | None = None
    firstname: str | None = None
    lastname: str | None = None
    address1: str | None = None
    address2: str | None = None
    zipcode: str | None = None
    city: str | None = None
    country: str | None = Field(None, min_length=2, max_length=2)
    phone: str | None = None
    customer_id: str | None = None
    tax_number: str | None = None
    send_invoices_to_email: str | None = None
    send_estimates_to_email: str | None = None

class NewContact(ContactFields):
    @model_validator(mode="after")
    def name_required(self):
        if not ((self.company_name or "").strip() or ((self.firstname or "").strip() and (self.lastname or "").strip())):
            raise ValueError("Provide a company name or both first and last name")
        return self

class DocumentFields(Input):
    contact_id: ID | None = None
    reference: str | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    details_attributes: list[Detail] | None = Field(None, min_length=1, max_length=100)

class NewDocument(DocumentFields):
    contact_id: ID

class ProductFields(Input):
    title: str | None = None
    description: str | None = None
    price: str | None = Field(None, pattern=r"^-?[0-9]+(?:[.,][0-9]+)?$")
    ledger_account_id: ID | None = None
    tax_rate_id: ID | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    identifier: str | None = None

class NewProduct(ProductFields):
    price: str = Field(..., pattern=r"^-?[0-9]+(?:[.,][0-9]+)?$")
    ledger_account_id: ID

class ListAdministrationsConfig(Input):
    operation: Literal["list_administrations"] = Field("list_administrations", json_schema_extra={"ui:hidden": True})

class ListContactsConfig(PageInput):
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    query: str | None = None

class CreateContactConfig(AdministrationInput):
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    contact: NewContact

class ListSalesInvoicesConfig(PageInput):
    operation: Literal["list_sales_invoices"] = Field("list_sales_invoices", json_schema_extra={"ui:hidden": True})

class CreateSalesInvoiceConfig(AdministrationInput):
    operation: Literal["create_sales_invoice"] = Field("create_sales_invoice", json_schema_extra={"ui:hidden": True})
    sales_invoice: NewDocument

class ListEstimatesConfig(PageInput):
    operation: Literal["list_estimates"] = Field("list_estimates", json_schema_extra={"ui:hidden": True})

class CreateEstimateConfig(AdministrationInput):
    operation: Literal["create_estimate"] = Field("create_estimate", json_schema_extra={"ui:hidden": True})
    estimate: NewDocument

class ListProductsConfig(PageInput):
    operation: Literal["list_products"] = Field("list_products", json_schema_extra={"ui:hidden": True})

class CreateProductConfig(AdministrationInput):
    operation: Literal["create_product"] = Field("create_product", json_schema_extra={"ui:hidden": True})
    product: NewProduct

class ListLedgerAccountsConfig(AdministrationInput):
    operation: Literal["list_ledger_accounts"] = Field("list_ledger_accounts", json_schema_extra={"ui:hidden": True})

class ListTaxRatesConfig(AdministrationInput):
    operation: Literal["list_tax_rates"] = Field("list_tax_rates", json_schema_extra={"ui:hidden": True})

class ListFinancialAccountsConfig(AdministrationInput):
    operation: Literal["list_financial_accounts"] = Field("list_financial_accounts", json_schema_extra={"ui:hidden": True})

MoneybirdConfig = Annotated[Union[ListAdministrationsConfig, ListContactsConfig, CreateContactConfig, ListSalesInvoicesConfig, CreateSalesInvoiceConfig, ListEstimatesConfig, CreateEstimateConfig, ListProductsConfig, CreateProductConfig, ListLedgerAccountsConfig, ListTaxRatesConfig, ListFinancialAccountsConfig], Field(discriminator="operation")]

class MoneybirdFullConfig(NodeConfig[MoneybirdConfig, MoneybirdTokenCredential]):
    pass

ROUTES = {'list_administrations': ('GET', '/administrations', None), 'list_contacts': ('GET', '/{administration_id}/contacts', None), 'create_contact': ('POST', '/{administration_id}/contacts', 'contact'), 'list_sales_invoices': ('GET', '/{administration_id}/sales_invoices', None), 'create_sales_invoice': ('POST', '/{administration_id}/sales_invoices', 'sales_invoice'), 'list_estimates': ('GET', '/{administration_id}/estimates', None), 'create_estimate': ('POST', '/{administration_id}/estimates', 'estimate'), 'list_products': ('GET', '/{administration_id}/products', None), 'create_product': ('POST', '/{administration_id}/products', 'product'), 'list_ledger_accounts': ('GET', '/{administration_id}/ledger_accounts', None), 'list_tax_rates': ('GET', '/{administration_id}/tax_rates', None), 'list_financial_accounts': ('GET', '/{administration_id}/financial_accounts', None)}

class MoneybirdNode(WorkflowNode):
    integration_type = "automation-moneybird"
    connection_evidence = ConnectionEvidence(noun="administrations", operation="list_administrations")

    @classmethod
    def get_config_model(cls):
        return MoneybirdFullConfig

    async def execute(self, context):
        op = self.config.config
        credential = self.config.credentials
        if credential is None:
            return {"status": "error", "error": "Supply a Moneybird personal API token"}
        method, route, body_field = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        path = route.format(**values) + ".json"
        params = {k: values[k] for k in ("page", "per_page", "query") if k in values}
        body = {body_field: values[body_field]} if body_field else None
        if body_field and not body[body_field]:
            return {"status": "error", "error": "Provide at least one field to update"}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
            if response.status_code not in ({201} if method == "POST" else {200}):
                return {"status": "error", "http_status": response.status_code, "error": f"Moneybird HTTP {response.status_code}"}
            data = response.json()
            listing = op.operation.startswith("list_")
            if not isinstance(data, list if listing else dict) or (isinstance(data, dict) and ("error" in data or "errors" in data)):
                raise ValueError("Unexpected Moneybird response")
            if listing and any(not isinstance(row, dict) for row in data):
                raise ValueError("Unexpected Moneybird list")
            result = {"status": "success", "data": data}
            if hasattr(op, "page"):
                result.update(page=op.page, per_page=op.per_page, next_page=op.page + 1 if len(data) == op.per_page else None)
            return result
        except (httpx.HTTPError, ValueError):
            return {"status": "error", "error": "Moneybird request failed; inspect the account before retrying a write"}
