"""Altoviz v1: fixed JSON operations, using the provider's published contract.

Contract: https://developer.altoviz.com/openapi.yaml (v1).
Pagination: https://developer.altoviz.com/docs/api/guides/pagination.
Writes send only explicitly supplied fields and are never retried automatically.
"""
from __future__ import annotations

from datetime import date as Date
from typing import Annotated, Literal, Union
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.altoviz.com"


class AltovizAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Altoviz API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developer.altoviz.com/docs/api/guides/authentication",
        "x-credential-instructions": "In Altoviz, open Settings, then API access, create a key and paste it here. NoClick sends it in the X-API-KEY header to api.altoviz.com. The connection check reads your customers.",
    })
    credential_type: Literal["altoviz_api_key"] = Field("altoviz_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class AltovizAddressFields(_Input):
    city: str | None = Field(None, description='')
    countryIso: str | None = Field(None, description='')
    street: str | None = Field(None, description='')
    zipcode: str | None = Field(None, description='')


class AltovizCompanyInfo(_Input):
    siret: str | None = Field(None, description='')
    vatNumber: str | None = Field(None, description='')


class AltovizDiscount(_Input):
    type: Literal['Percent', 'Fixed'] = Field(None, description='')
    value: float = Field(None, description='')


class AltovizVat(_Input):
    rate: float | None = Field(None, description='Rate')
    region: Literal['FR', 'EU', 'IE', 'DOM', 'Corse', 'Monaco'] = Field(None, description='')


class AltovizUnit(_Input):
    code: str | None = Field(None, description='Code')
    type: Literal['Time', 'Weight', 'Area', 'Volume', 'Dimension', 'Other'] = Field(None, description='')


class AltovizCustomerCreate(_Input):
    active: bool = Field(None, description='Active')
    billingAddress: AltovizAddressFields = Field(None, description='')
    cellPhone: str | None = Field(None, description='Cell phone number')
    companyInformations: AltovizCompanyInfo = Field(None, description='')
    companyName: str | None = Field(None, description='Company name')
    email: str | None = Field(None, description='Email')
    firstName: str | None = Field(None, description='First name')
    internalId: str | None = Field(None, description='ID used in information system')
    internalNotes: str | None = Field(None, description='Internal notes')
    lastName: str | None = Field(None, description='Last name')
    metadata: dict[str, str | None] | None = Field(None, description='Metadata: free-form key/value pairs carried with the customer, for an integration to keep')
    number: str | None = Field(None, description='Number')
    phone: str | None = Field(None, description='Phone number')
    shippingAddress: AltovizAddressFields = Field(None, description='')
    title: str | None = Field(None, description='Title')
    type: Literal['Business', 'Consumer', 'Government'] = Field(None, description='')


class AltovizProduct(_Input):
    active: bool = Field(None, description='Indicates whether the product is active')
    defaultQuantity: float = Field(None, description='Default quantity')
    description: str | None = Field(None, description='Description')
    internalId: str | None = Field(None, description='ID used in your system')
    internalNotes: str | None = Field(None, description='Internal notes')
    metadata: dict[str, str | None] | None = Field(None, description='Metadata: free-form key/value pairs carried with the product, for an integration to keep')
    name: str | None = Field(None, description='Name')
    number: str | None = Field(None, description='Number')
    purchasePrice: float = Field(None, description='Purchase price')
    taxExcludedPrice: float = Field(None, description='Sale price excluding tax.')
    taxIncludedPrice: float = Field(None, description='Sale price including tax.')
    type: Literal['Product', 'Service', 'Text'] = Field(None, description='')
    unit: AltovizUnit = Field(None, description='')
    vat: AltovizVat = Field(None, description='')


class AltovizSaleDocumentLine(_Input):
    classificationId: int | None = Field(None, description='Classification ID (used if no product is set)')
    date: Date | None = Field(None, description='Date')
    description: str | None = Field(None, description='Description (can be html)')
    discount: AltovizDiscount = Field(None, description='')
    productId: int | None = Field(None, description='Product ID')
    productInternalId: str | None = Field(None, description='Product internal ID')
    productNumber: str | None = Field(None, description='Product number')
    purchasePrice: float | None = Field(None, description='Purchase price')
    quantity: float | None = Field(None, description='Quantity')
    taxExcludedPrice: float | None = Field(None, description='Tax excluded price')
    taxIncludedPrice: float | None = Field(None, description='Tax included price')
    type: Literal['Empty', 'Product', 'Service', 'Subtotal', 'Text', 'NewPage'] = Field(None, description='')
    unit: AltovizUnit = Field(None, description='')
    vat: AltovizVat = Field(None, description='')


class AltovizInvoice(_Input):
    billingAddress: AltovizAddressFields = Field(None, description='')
    customerId: int | None = Field(None, description='Customer ID')
    customerOrderReference: str | None = Field(None, description='Customer order reference')
    date: Date | None = Field(None, description='Date')
    footerNotes: str | None = Field(None, description='Footer notes to be print')
    globalDiscount: AltovizDiscount = Field(None, description='')
    headerNotes: str | None = Field(None, description='Header notes to be print')
    internalId: str | None = Field(None, description='ID used in your system')
    internalNotes: str | None = Field(None, description='Internal notes')
    liableToVat: bool | None = Field(None, description='Indicates whether the document is liable to VAT')
    lines: list[AltovizSaleDocumentLine] | None = Field(None, description='Invoice lines')
    metadata: dict[str, str | None] | None = Field(None, description='Metadata: free-form key/value pairs carried with the document, for an integration to keep')
    shippingAddress: AltovizAddressFields = Field(None, description='')
    shippingAmount: float = Field(None, description='Shipping amount')
    shippingVat: AltovizVat = Field(None, description='')
    subject: str | None = Field(None, description='Subject')
    useTaxIncludedPrices: bool = Field(None, description='Indicates whether invoice prices and amount are tax included')
    vatMode: Literal['Auto', 'Debit', 'Collection'] = Field(None, description='')
    vatNote: str | None = Field(None, description='VAT note to print')
    vatReverseCharge: bool = Field(None, description='VAT reverse charge')
    vendorReference: str | None = Field(None, description='Vendor reference to be print')


class AltovizQuote(_Input):
    billingAddress: AltovizAddressFields = Field(None, description='')
    customerId: int | None = Field(None, description='Customer ID')
    customerOrderReference: str | None = Field(None, description='Customer order reference')
    date: Date | None = Field(None, description='Date')
    footerNotes: str | None = Field(None, description='Footer notes to be print')
    globalDiscount: AltovizDiscount = Field(None, description='')
    headerNotes: str | None = Field(None, description='Header notes to be print')
    internalId: str | None = Field(None, description='ID used in your system')
    internalNotes: str | None = Field(None, description='Internal notes')
    liableToVat: bool | None = Field(None, description='Indicates whether the document is liable to VAT')
    lines: list[AltovizSaleDocumentLine] | None = Field(None, description='Invoice lines')
    metadata: dict[str, str | None] | None = Field(None, description='Metadata: free-form key/value pairs carried with the document, for an integration to keep')
    shippingAddress: AltovizAddressFields = Field(None, description='')
    shippingAmount: float = Field(None, description='Shipping amount')
    shippingVat: AltovizVat = Field(None, description='')
    subject: str | None = Field(None, description='Subject')
    useTaxIncludedPrices: bool = Field(None, description='Indicates whether invoice prices and amount are tax included')
    vatNote: str | None = Field(None, description='VAT note to print')
    vatReverseCharge: bool = Field(None, description='VAT reverse charge')
    vendorReference: str | None = Field(None, description='Vendor reference to be print')


class AltovizListCustomersConfig(_Input):
    """List customers."""
    operation: Literal['list_customers'] = Field('list_customers', json_schema_extra={"ui:hidden": True})
    page_index: int = Field(1, ge=1, le=2147483647, description="One-based PageIndex; use next_page_index from the previous result.")
    page_size: int = Field(10, ge=1, le=100)
    order_by: str | None = None
    query: str | None = None


class AltovizGetCustomerConfig(_Input):
    """Get a customer by ID."""
    operation: Literal['get_customer'] = Field('get_customer', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, le=2147483647, title="Resource ID")


class AltovizCreateCustomerConfig(_Input):
    """Create a new customer."""
    operation: Literal['create_customer'] = Field('create_customer', json_schema_extra={"ui:hidden": True})
    customer: AltovizCustomerCreate = Field(..., description="Fields to send to Altoviz. Omitted fields are not sent; invoice updates require a draft.")


class AltovizUpdateCustomerConfig(_Input):
    """Update a customer."""
    operation: Literal['update_customer'] = Field('update_customer', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, le=2147483647, title="Resource ID")
    customer: AltovizCustomerCreate = Field(..., description="Fields to send to Altoviz. Omitted fields are not sent; invoice updates require a draft.")


class AltovizListProductsConfig(_Input):
    """List products."""
    operation: Literal['list_products'] = Field('list_products', json_schema_extra={"ui:hidden": True})
    page_index: int = Field(1, ge=1, le=2147483647, description="One-based PageIndex; use next_page_index from the previous result.")
    page_size: int = Field(10, ge=1, le=100)
    order_by: str | None = None
    query: str | None = None


class AltovizGetProductConfig(_Input):
    """Get a product by ID."""
    operation: Literal['get_product'] = Field('get_product', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, le=2147483647, title="Resource ID")


class AltovizCreateProductConfig(_Input):
    """Create a new product."""
    operation: Literal['create_product'] = Field('create_product', json_schema_extra={"ui:hidden": True})
    product: AltovizProduct = Field(..., description="Fields to send to Altoviz. Omitted fields are not sent; invoice updates require a draft.")


class AltovizUpdateProductConfig(_Input):
    """Update a product."""
    operation: Literal['update_product'] = Field('update_product', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, le=2147483647, title="Resource ID")
    product: AltovizProduct = Field(..., description="Fields to send to Altoviz. Omitted fields are not sent; invoice updates require a draft.")


class AltovizListInvoicesConfig(_Input):
    """List invoices."""
    operation: Literal['list_invoices'] = Field('list_invoices', json_schema_extra={"ui:hidden": True})
    page_index: int = Field(1, ge=1, le=2147483647, description="One-based PageIndex; use next_page_index from the previous result.")
    page_size: int = Field(10, ge=1, le=100)
    order_by: str | None = None
    from_date: Date | None = None
    to_date: Date | None = None
    customer_id: int | None = Field(None, ge=1, le=2147483647)


class AltovizGetInvoiceConfig(_Input):
    """Get an invoice by ID."""
    operation: Literal['get_invoice'] = Field('get_invoice', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, le=2147483647, title="Resource ID")


class AltovizCreateInvoiceConfig(_Input):
    """Create a new draft invoice."""
    operation: Literal['create_invoice'] = Field('create_invoice', json_schema_extra={"ui:hidden": True})
    invoice: AltovizInvoice = Field(..., description="Fields to send to Altoviz. Omitted fields are not sent; invoice updates require a draft.")


class AltovizUpdateInvoiceConfig(_Input):
    """Update a draft invoice."""
    operation: Literal['update_invoice'] = Field('update_invoice', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, le=2147483647, title="Resource ID")
    invoice: AltovizInvoice = Field(..., description="Fields to send to Altoviz. Omitted fields are not sent; invoice updates require a draft.")


class AltovizListQuotesConfig(_Input):
    """List quotes."""
    operation: Literal['list_quotes'] = Field('list_quotes', json_schema_extra={"ui:hidden": True})
    page_index: int = Field(1, ge=1, le=2147483647, description="One-based PageIndex; use next_page_index from the previous result.")
    page_size: int = Field(10, ge=1, le=100)
    order_by: str | None = None
    from_date: Date | None = None
    to_date: Date | None = None
    customer_id: int | None = Field(None, ge=1, le=2147483647)


class AltovizGetQuoteConfig(_Input):
    """Get an quote by ID."""
    operation: Literal['get_quote'] = Field('get_quote', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, le=2147483647, title="Resource ID")


class AltovizCreateQuoteConfig(_Input):
    """Create a new quote."""
    operation: Literal['create_quote'] = Field('create_quote', json_schema_extra={"ui:hidden": True})
    quote: AltovizQuote = Field(..., description="Fields to send to Altoviz. Omitted fields are not sent; invoice updates require a draft.")


class AltovizListSuppliersConfig(_Input):
    """List suppliers."""
    operation: Literal['list_suppliers'] = Field('list_suppliers', json_schema_extra={"ui:hidden": True})
    page_index: int = Field(1, ge=1, le=2147483647, description="One-based PageIndex; use next_page_index from the previous result.")
    page_size: int = Field(10, ge=1, le=100)
    order_by: str | None = None
    query: str | None = None


class AltovizGetSupplierConfig(_Input):
    """Get a supplier by ID."""
    operation: Literal['get_supplier'] = Field('get_supplier', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, le=2147483647, title="Resource ID")


class AltovizListCreditsConfig(_Input):
    """List credits."""
    operation: Literal['list_credits'] = Field('list_credits', json_schema_extra={"ui:hidden": True})
    page_index: int = Field(1, ge=1, le=2147483647, description="One-based PageIndex; use next_page_index from the previous result.")
    page_size: int = Field(10, ge=1, le=100)
    order_by: str | None = None
    from_date: Date | None = None
    to_date: Date | None = None
    customer_id: int | None = Field(None, ge=1, le=2147483647)


class AltovizGetCreditConfig(_Input):
    """Get an credit by ID."""
    operation: Literal['get_credit'] = Field('get_credit', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, le=2147483647, title="Resource ID")


class AltovizListContactsConfig(_Input):
    """List Contacts."""
    operation: Literal['list_contacts'] = Field('list_contacts', json_schema_extra={"ui:hidden": True})
    page_index: int = Field(1, ge=1, le=2147483647, description="One-based PageIndex; use next_page_index from the previous result.")
    page_size: int = Field(10, ge=1, le=100)
    order_by: str | None = None
    query: str | None = None


class AltovizGetContactConfig(_Input):
    """Get a Contact by ID."""
    operation: Literal['get_contact'] = Field('get_contact', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, le=2147483647, title="Resource ID")


class AltovizListBankAccountsConfig(_Input):
    """List bank accounts."""
    operation: Literal['list_bank_accounts'] = Field('list_bank_accounts', json_schema_extra={"ui:hidden": True})


class AltovizListVatsConfig(_Input):
    """List all vats."""
    operation: Literal['list_vats'] = Field('list_vats', json_schema_extra={"ui:hidden": True})


class AltovizListUnitsConfig(_Input):
    """List all units."""
    operation: Literal['list_units'] = Field('list_units', json_schema_extra={"ui:hidden": True})


class AltovizGetSettingsConfig(_Input):
    """Get settings."""
    operation: Literal['get_settings'] = Field('get_settings', json_schema_extra={"ui:hidden": True})


# Altoviz's own MCP server: agents get its tools through a person's Altoviz sign-in.
AltovizMcpCredential = mcp_credential("altoviz", "https://mcp.altoviz.com", app="Altoviz")
AltovizCredential = Union[AltovizAPIKeyCredential, AltovizMcpCredential]


AltovizConfig = Annotated[Union[
    AltovizListCustomersConfig,
    AltovizGetCustomerConfig,
    AltovizCreateCustomerConfig,
    AltovizUpdateCustomerConfig,
    AltovizListProductsConfig,
    AltovizGetProductConfig,
    AltovizCreateProductConfig,
    AltovizUpdateProductConfig,
    AltovizListInvoicesConfig,
    AltovizGetInvoiceConfig,
    AltovizCreateInvoiceConfig,
    AltovizUpdateInvoiceConfig,
    AltovizListQuotesConfig,
    AltovizGetQuoteConfig,
    AltovizCreateQuoteConfig,
    AltovizListSuppliersConfig,
    AltovizGetSupplierConfig,
    AltovizListCreditsConfig,
    AltovizGetCreditConfig,
    AltovizListContactsConfig,
    AltovizGetContactConfig,
    AltovizListBankAccountsConfig,
    AltovizListVatsConfig,
    AltovizListUnitsConfig,
    AltovizGetSettingsConfig,
], Field(discriminator="operation")]


class AltovizFullConfig(NodeConfig[AltovizConfig, AltovizCredential]):
    pass


OPERATIONS = {
    'list_customers': ('GET', '/v1/Customers'),
    'get_customer': ('GET', '/v1/Customers/{id}'),
    'create_customer': ('POST', '/v1/Customers'),
    'update_customer': ('PUT', '/v1/Customers/{id}'),
    'list_products': ('GET', '/v1/Products'),
    'get_product': ('GET', '/v1/Products/{id}'),
    'create_product': ('POST', '/v1/Products'),
    'update_product': ('PUT', '/v1/Products/{id}'),
    'list_invoices': ('GET', '/v1/SalesInvoices'),
    'get_invoice': ('GET', '/v1/SalesInvoices/{id}'),
    'create_invoice': ('POST', '/v1/SalesInvoices'),
    'update_invoice': ('PUT', '/v1/SalesInvoices/{id}'),
    'list_quotes': ('GET', '/v1/SalesQuotes'),
    'get_quote': ('GET', '/v1/SalesQuotes/{id}'),
    'create_quote': ('POST', '/v1/SalesQuotes'),
    'list_suppliers': ('GET', '/v1/Suppliers'),
    'get_supplier': ('GET', '/v1/Suppliers/{id}'),
    'list_credits': ('GET', '/v1/SalesCredits'),
    'get_credit': ('GET', '/v1/SalesCredits/{id}'),
    'list_contacts': ('GET', '/v1/Contacts'),
    'get_contact': ('GET', '/v1/Contacts/{id}'),
    'list_bank_accounts': ('GET', '/v1/BankAccounts'),
    'list_vats': ('GET', '/v1/Vats'),
    'list_units': ('GET', '/v1/Units'),
    'get_settings': ('GET', '/v1/Settings'),
}


def _next_page(response, path, current, params):
    """Expose the provider's next page without requesting a URL from its header."""
    link = response.headers.get("X-PAGE-NEXT")
    if not link:
        return None
    url = urlsplit(link)
    if (url.scheme or url.netloc) and (url.scheme != "https" or url.netloc != "api.altoviz.com"):
        raise ValueError("Altoviz returned a foreign pagination origin")
    if url.path.lower() != path.lower() or url.fragment:
        raise ValueError("Altoviz returned a different pagination resource")
    query = parse_qs(url.query, keep_blank_values=True)
    if any(len(v) != 1 for v in query.values()):
        raise ValueError("Altoviz returned ambiguous pagination")
    value = query.get("PageIndex", [""])[0]
    if not value.isdecimal() or not current < int(value) <= 2147483647:
        raise ValueError("Altoviz returned a non-advancing page")
    expected = {k: str(v) for k, v in params.items() if k != "PageIndex"}
    if any(k != "PageIndex" and (k not in expected or v[0] != expected[k]) for k, v in query.items()):
        raise ValueError("Altoviz changed pagination filters")
    return int(value)


class AltovizNode(WorkflowNode):
    integration_type = "automation-altoviz"
    credential_provider_labels = {"altoviz": "Altoviz Account"}
    connection_evidence = ConnectionEvidence(noun="customers", operation="list_customers")

    @classmethod
    def get_config_model(cls):
        return AltovizFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an Altoviz API key")
        method, path = OPERATIONS[config.operation]
        if "{id}" in path:
            path = path.replace("{id}", str(config.id))
        params = {}
        for field, wire in {"page_index": "PageIndex", "page_size": "PageSize", "order_by": "OrderBy", "query": "query", "from_date": "From", "to_date": "To", "customer_id": "CustomerId"}.items():
            value = getattr(config, field, None)
            if value is not None:
                params[wire] = value.isoformat() if isinstance(value, Date) else value
        body = None
        if method in {"POST", "PUT"}:
            resource = config.operation.split("_", 1)[1]
            body = getattr(config, resource).model_dump(mode="json", exclude_unset=True)
            if not body:
                raise ValueError("Supply at least one field to write")
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, headers={"X-API-KEY": credential.api_key, "Accept": "application/json"}, params=params, **({"json": body} if body is not None else {}))
        if response.status_code != 200:
            # Preserve provider diagnostics for the connection verdict without exposing the credential.
            message = response.text.replace(credential.api_key, "[redacted]")[:2000]
            raise ValueError(f"Altoviz HTTP {response.status_code}: {message}")
        data = response.json()
        listing = config.operation.startswith("list_")
        if listing:
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError("Altoviz returned an invalid list response")
        elif not isinstance(data, dict):
            raise ValueError("Altoviz returned an invalid object response")
        if isinstance(data, dict) and (data.get("error") or data.get("errors")):
            raise ValueError("Altoviz returned an error envelope")
        result = {"data": data}
        if listing and hasattr(config, "page_index"):
            result["next_page_index"] = _next_page(response, path, config.page_index, params)
            result["has_more"] = result["next_page_index"] is not None
        return result
