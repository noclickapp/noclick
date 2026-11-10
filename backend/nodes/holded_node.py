"""Holded API v2: one published request per operation, with caller-driven cursor pagination.

Contract: https://api.holded.com/openapi/api2.json (1.0.0).
"""
from __future__ import annotations
from datetime import date as Date, datetime as DateTime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
import hashlib
import hmac
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

class HoldedAPIKey(BaseModel):
    model_config = ConfigDict(title="Holded API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://api.holded.com/openapi/api2.json",
            "x-credential-instructions": "Paste a Holded API v2 API key. NoClick sends it as a Bearer token to api.holded.com. Grant contacts:contacts.read to verify the connection, plus the read or write permissions for the resources you automate (contacts, invoicing, inventory and projects). Use a key for the published v2 API."})
    credential_type: Literal["holded_api_key"] = Field("holded_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without the Bearer prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class HoldedListContactsConfig(_Input):
    'List contacts'
    operation: Literal['list_contacts'] = Field('list_contacts', json_schema_extra={"ui:hidden": True})
    phone: str | None = Field(None, description='Filter contacts by exact phone number match')
    mobile: str | None = Field(None, description='Filter contacts by exact mobile number match')
    email: str | None = Field(None, description='Filter contacts by exact email address match')
    custom_id: str | None = Field(None, description='Filter contacts by your external reference identifier')
    code: str | None = Field(None, description='Filter contacts by exact tax identification number (NIF/CIF)')
    cursor: str | None = Field(None, description='Opaque cursor for pagination. Use the value returned in the previous response to fetch the next page.')
    limit: int | None = Field(None, ge=1, le=100, description='Maximum number of contacts to return per page. Defaults to 25, maximum 100.')

class HoldedCreateContactConfigBillAddress(_Input):
    address: str | None = Field(None, description='Street address')
    city: str | None = Field(None, description='City')
    postal_code: str | None = Field(None, description='Postal or ZIP code')
    province: str | None = Field(None, description='Province or state')
    country: str | None = Field(None, description='Country name')
    country_code: str | None = Field(None, description='ISO 3166-1 alpha-2 country code')
    info: str | None = Field(None, description='Additional address information')

class HoldedCreateContactConfigSocialNetworks(_Input):
    facebook: str | None = Field(None, description='Handle or URL for `facebook`')
    twitter: str | None = Field(None, description='Handle or URL for `twitter`')
    instagram: str | None = Field(None, description='Handle or URL for `instagram`')
    google: str | None = Field(None, description='Handle or URL for `google`')
    linkedin: str | None = Field(None, description='Handle or URL for `linkedin`')
    pinterest: str | None = Field(None, description='Handle or URL for `pinterest`')
    foursquare: str | None = Field(None, description='Handle or URL for `foursquare`')
    youtube: str | None = Field(None, description='Handle or URL for `youtube`')
    vimeo: str | None = Field(None, description='Handle or URL for `vimeo`')
    wordpress: str | None = Field(None, description='Handle or URL for `wordpress`')
    website: str | None = Field(None, description='Handle or URL for `website`')

class HoldedCreateContactConfigCustomFieldsItem(_Input):
    field: str | None = Field(None, description='Custom field identifier')
    value: str | None = Field(None, description='Value stored in the custom field')

class HoldedCreateContactConfigDefaultsNumberingSeries(_Input):
    invoice: str | None = Field(None, pattern='[a-f0-9]{24}', description='Numbering series ID for invoices')
    receipt: str | None = Field(None, pattern='[a-f0-9]{24}', description='Numbering series ID for receipts')
    salesorder: str | None = Field(None, pattern='[a-f0-9]{24}', description='Numbering series ID for sales orders')
    estimate: str | None = Field(None, pattern='[a-f0-9]{24}', description='Numbering series ID for estimates')
    order: str | None = Field(None, pattern='[a-f0-9]{24}', description='Numbering series ID for purchase orders')
    proform: str | None = Field(None, pattern='[a-f0-9]{24}', description='Numbering series ID for proforma invoices')
    waybill: str | None = Field(None, pattern='[a-f0-9]{24}', description='Numbering series ID for waybills')

class HoldedCreateContactConfigDefaults(_Input):
    sales_channel: str | None = Field(None, description='Default sales channel identifier')
    expenses_account: str | None = Field(None, description='Default expenses accounting account')
    due_days: int | None = Field(None, description='Default payment due days')
    payment_day: int | None = Field(None, description='Default fixed payment day of the month')
    payment_method: str | None = Field(None, description='Default payment method identifier')
    discount: int | None = Field(None, description='Default discount percentage')
    language: str | None = Field(None, description='Default document language code')
    currency: str | None = Field(None, description='Default currency code')
    sales_tax: list[str] | None = Field(None, description='Default sales tax keys applied to sales documents')
    purchases_tax: list[str] | None = Field(None, description='Default purchases tax keys applied to purchase documents')
    accumulate_in_form_347: bool | None = Field(None, description='Whether the contact accumulates in tax form 347. Defaults to true when omitted.')
    numbering_series: HoldedCreateContactConfigDefaultsNumberingSeries | None = Field(None, description='Default numbering series applied to new documents of each type created for this contact. Each value must be a valid numbering series ID; invalid or unrecognized IDs are silently ignored (stored as null).')

class HoldedCreateContactConfig(_Input):
    'Create a contact'
    operation: Literal['create_contact'] = Field('create_contact', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, description='Contact full name or company name')
    code: str | None = Field(None, description='Tax identification number (NIF, CIF, etc.)')
    vat_number: str | None = Field(None, description='EU VAT number')
    trade_name: str | None = Field(None, description='Commercial or trade name, if different from legal name')
    is_person: bool | None = Field(None, description='True if the contact is an individual, false if a company')
    email: str | None = Field(None, description='Email address. Several can be sent separated by commas or semicolons: the first is the primary, the rest are returned in `extra_emails`. Invalid ones are ignored (400 if none is valid).')
    phone: str | None = Field(None, description='Landline phone number')
    mobile: str | None = Field(None, description='Mobile phone number')
    website: str | None = Field(None, description='Website URL')
    type: Literal['client', 'debtor', 'supplier', 'creditor', 'lead'] | None = Field(None, description='Contact classification')
    client_record: int | None = Field(None, description='Number of the accounting account (chart of accounts) used when this contact acts as a client')
    supplier_record: int | None = Field(None, description='Number of the accounting account (chart of accounts) used when this contact acts as a supplier')
    iban: str | None = Field(None, description='IBAN bank account number')
    swift: str | None = Field(None, description='SWIFT/BIC code of the bank')
    sepa_ref: str | None = Field(None, description='SEPA mandate reference for direct debit collections')
    sepa_date: Date | None = Field(None, description='Date the SEPA direct debit mandate was signed')
    tax_operation: str | None = Field(None, description='Fiscal operation type of the contact (e.g. general, intra, receq, exento). Must be one of the operations defined by the account tax scheme')
    bill_address: HoldedCreateContactConfigBillAddress | None = Field(None, description='Billing address')
    social_networks: HoldedCreateContactConfigSocialNetworks | None = Field(None, description='Social network profiles of the contact. `website` is also used as the contact website when the top-level `website` is not sent')
    tags: list[str] | None = Field(None, description='Tags attached to the contact')
    custom_fields: list[HoldedCreateContactConfigCustomFieldsItem] | None = Field(None, description='User-defined custom fields')
    defaults: HoldedCreateContactConfigDefaults | None = Field(None, description='Default settings applied to documents created for this contact')

class HoldedGetContactConfig(_Input):
    'Get a contact by ID'
    operation: Literal['get_contact'] = Field('get_contact', json_schema_extra={"ui:hidden": True})
    contactId: str = Field(..., pattern='^[a-f0-9]{24}$', min_length=1, description='Contact ID (24-char hex ObjectId)')

class HoldedUpdateContactConfigBillAddress(_Input):
    address: str | None = Field(None, description='Street address')
    city: str | None = Field(None, description='City')
    postal_code: str | None = Field(None, description='Postal or ZIP code')
    province: str | None = Field(None, description='Province or state')
    country: str | None = Field(None, description='Country name')
    country_code: str | None = Field(None, description='ISO 3166-1 alpha-2 country code')
    info: str | None = Field(None, description='Additional address information')

class HoldedUpdateContactConfigSocialNetworks(_Input):
    facebook: str | None = Field(None, description='Handle or URL for `facebook`')
    twitter: str | None = Field(None, description='Handle or URL for `twitter`')
    instagram: str | None = Field(None, description='Handle or URL for `instagram`')
    google: str | None = Field(None, description='Handle or URL for `google`')
    linkedin: str | None = Field(None, description='Handle or URL for `linkedin`')
    pinterest: str | None = Field(None, description='Handle or URL for `pinterest`')
    foursquare: str | None = Field(None, description='Handle or URL for `foursquare`')
    youtube: str | None = Field(None, description='Handle or URL for `youtube`')
    vimeo: str | None = Field(None, description='Handle or URL for `vimeo`')
    wordpress: str | None = Field(None, description='Handle or URL for `wordpress`')
    website: str | None = Field(None, description='Handle or URL for `website`')

class HoldedUpdateContactConfigContactPersonsItem(_Input):
    person_id: str = Field(..., min_length=1, description='Contact ID of the person')

class HoldedUpdateContactConfigCustomFieldsItem(_Input):
    field: str | None = Field(None, description='Custom field identifier')
    value: str | None = Field(None, description='Value stored in the custom field')

class HoldedUpdateContactConfigDefaultsNumberingSeries(_Input):
    invoice: str | None = Field(None, pattern='[a-f0-9]{24}', description='Numbering series ID for invoices')
    receipt: str | None = Field(None, pattern='[a-f0-9]{24}', description='Numbering series ID for receipts')
    salesorder: str | None = Field(None, pattern='[a-f0-9]{24}', description='Numbering series ID for sales orders')
    estimate: str | None = Field(None, pattern='[a-f0-9]{24}', description='Numbering series ID for estimates')
    order: str | None = Field(None, pattern='[a-f0-9]{24}', description='Numbering series ID for purchase orders')
    proform: str | None = Field(None, pattern='[a-f0-9]{24}', description='Numbering series ID for proforma invoices')
    waybill: str | None = Field(None, pattern='[a-f0-9]{24}', description='Numbering series ID for waybills')

class HoldedUpdateContactConfigDefaults(_Input):
    sales_channel: str | None = Field(None, description='Default sales channel identifier')
    expenses_account: str | None = Field(None, description='Default expenses accounting account')
    due_days: int | None = Field(None, description='Default payment due days')
    payment_day: int | None = Field(None, description='Default fixed payment day of the month')
    payment_method: str | None = Field(None, description='Default payment method identifier')
    discount: int | None = Field(None, description='Default discount percentage')
    language: str | None = Field(None, description='Default document language code')
    currency: str | None = Field(None, description='Default currency code')
    sales_tax: list[str] | None = Field(None, description='Default sales tax keys applied to sales documents')
    purchases_tax: list[str] | None = Field(None, description='Default purchases tax keys applied to purchase documents')
    accumulate_in_form_347: bool | None = Field(None, description='Whether the contact accumulates in tax form 347. Omit it (or send null) to keep the current value.')
    numbering_series: HoldedUpdateContactConfigDefaultsNumberingSeries | None = Field(None, description='Default numbering series applied to new documents of each type created for this contact. Each value must be a valid numbering series ID; invalid or unrecognized IDs are silently ignored (stored as null). Omit this field entirely to keep the numbering series already configured for this contact.')

class HoldedUpdateContactConfig(_Input):
    'Update a contact'
    operation: Literal['update_contact'] = Field('update_contact', json_schema_extra={"ui:hidden": True})
    contactId: str = Field(..., pattern='^[a-f0-9]{24}$', min_length=1, description='Contact ID (24-char hex ObjectId)')
    name: str = Field(..., min_length=1, description='Contact full name or company name')
    code: str | None = Field(None, description='Tax identification number (NIF, CIF, etc.)')
    vat_number: str | None = Field(None, description='EU VAT number')
    trade_name: str | None = Field(None, description='Commercial or trade name, if different from legal name')
    is_person: bool | None = Field(None, description='True if the contact is an individual, false if a company')
    email: str | None = Field(None, description='Email address. Several can be sent separated by commas or semicolons: the first is the primary, the rest are returned in `extra_emails`. Invalid ones are ignored (400 if none is valid).')
    phone: str | None = Field(None, description='Landline phone number')
    mobile: str | None = Field(None, description='Mobile phone number')
    website: str | None = Field(None, description='Website URL')
    type: Literal['client', 'debtor', 'supplier', 'creditor', 'lead'] | None = Field(None, description='Contact classification')
    client_record: int | None = Field(None, description='Number of the accounting account (chart of accounts) used when this contact acts as a client')
    supplier_record: int | None = Field(None, description='Number of the accounting account (chart of accounts) used when this contact acts as a supplier')
    iban: str | None = Field(None, description='IBAN bank account number')
    swift: str | None = Field(None, description='SWIFT/BIC code of the bank')
    sepa_ref: str | None = Field(None, description='SEPA mandate reference for direct debit collections')
    sepa_date: Date | None = Field(None, description='Date the SEPA direct debit mandate was signed')
    tax_operation: str | None = Field(None, description='Fiscal operation type of the contact (e.g. general, intra, receq, exento). Must be one of the operations defined by the account tax scheme. On update, omitting it (or sending null) keeps the current value')
    bill_address: HoldedUpdateContactConfigBillAddress | None = Field(None, description='Billing address')
    social_networks: HoldedUpdateContactConfigSocialNetworks | None = Field(None, description='Social network profiles of the contact. Omit it to keep the current values. `website` is also used as the contact website when the top-level `website` is not sent')
    tags: list[str] | None = Field(None, description='Tags attached to the contact')
    contact_persons: list[HoldedUpdateContactConfigContactPersonsItem] | None = Field(None, description='Linked contact persons (by their contact ID). Only `person_id` is read; the other fields the GET returns for each person are kept as stored.')
    custom_fields: list[HoldedUpdateContactConfigCustomFieldsItem] | None = Field(None, description='User-defined custom fields')
    defaults: HoldedUpdateContactConfigDefaults | None = Field(None, description='Default settings applied to documents created for this contact')

class HoldedDeleteContactConfig(_Input):
    'Delete a contact'
    operation: Literal['delete_contact'] = Field('delete_contact', json_schema_extra={"ui:hidden": True})
    contactId: str = Field(..., pattern='^[a-f0-9]{24}$', min_length=1, description='Contact ID (24-char hex ObjectId)')

class HoldedListInvoicesConfig(_Input):
    'List invoices'
    operation: Literal['list_invoices'] = Field('list_invoices', json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=200, description='Maximum number of invoices to return per page. Defaults to 50, maximum 200.')
    cursor: str | None = Field(None, description='Pagination cursor returned by the previous response. Omit to start from the first page.')
    contact_id: str | None = Field(None, description='Filter invoices by contact identifier')
    status: Literal['pending', 'completed', 'partial', 'cancelled', 'failed', 'overdue', 'outstanding'] | None = Field(None, description='Filter invoices by payment status. "pending" matches invoices with no payment recorded and "partial" those collected in part; both still owe a balance. "outstanding" returns the two together, "overdue" narrows that set to a due date already past, and "completed" returns the settled ones.')
    start_date: DateTime | None = Field(None, description='Filter invoices from this date. Accepts ISO 8601 datetime (e.g. 2026-01-01T00:00:00+00:00) or date only (e.g. 2026-01-01)')
    end_date: DateTime | None = Field(None, description='Filter invoices up to this date. Accepts ISO 8601 datetime (e.g. 2026-12-31T23:59:59+00:00) or date only (e.g. 2026-12-31). A date without a time (YYYY-MM-DD) includes that whole day; a value with a time is applied exactly as sent.')
    due_date_start: DateTime | None = Field(None, description='Filter invoices whose DUE date is on or after this date. Accepts ISO 8601 datetime or date only (e.g. 2026-01-01).')
    due_date_end: DateTime | None = Field(None, description='Filter invoices whose DUE date is on or before this date. Accepts ISO 8601 datetime or date only (e.g. 2026-03-12). A date without a time (YYYY-MM-DD) includes that whole day; a value with a time is applied exactly as sent.')
    sort: Literal['date', '-date', 'dueDate', '-dueDate', 'total', '-total'] | None = Field(None, description='Sort order for results. Prefix with - for descending.')
    approval_status: Literal['draft', 'approved'] | None = Field(None, description='Filter by approval status. Use "draft" for unapproved invoices, "approved" for approved ones.')
    accounting_account_num: int | None = Field(None, description='Filter invoices that have at least one line booked to this accounting account, identified by its numeric PGC code (e.g. 70000000 for "Ventas de mercaderias"). Only the numeric code is accepted; a non-numeric value returns 400. Returns 404 if no accounting account with that number exists in the tenant. When called through the AI assistant, an account name is resolved to its code automatically before the request reaches this endpoint.')

class HoldedCreateInvoiceConfigItemsItem(_Input):
    name: str | None = Field(None, description='name')
    type: Literal['product', 'service', 'title'] | None = Field(None, description='Kind of line. `product` and `service` are billable lines whose amount (`units` × `price`, less `discount`, plus `taxes`) is added to the document total. `title` is a section-header line that shows only its `name` and carries no amount — it does not contribute to the total. Other values are special-purpose lines. Omit this field for an ordinary priced line item.')
    description: str | None = Field(None, description='description')
    product_id: str | None = Field(None, description='Identifier of an existing catalog product to link this line to. The id is stored as a reference associating the line with the product (used for stock and reporting). Each line field (`price`, `taxes`, ...) is taken as sent; api2 stores the line values you provide and does not itself read them back from the product record. Leave unset for a free-text line that is not a catalog product.')
    variant_id: str | None = Field(None, description='Identifier of the variant of `product_id` to link this line to. Requires `product_id`. Leave unset for a line without variant.')
    service_id: str | None = Field(None, description='Identifier of an existing catalog service to link this line to. When provided, the line type is automatically set to `service`. Leave unset for a free-text line that is not a catalog service.')
    units: float | None = Field(None, description='units')
    price: float | None = Field(None, description='price')
    discount: float | None = Field(None, description='discount')
    taxes: list[str] | None = Field(None, description='Tax keys applied to this line. When omitted, the contact default tax applies, or, if the contact has none, the account default tax when the request asks for it, else no tax.')
    tags: list[str] | None = Field(None, description='tags')
    sku: str | None = Field(None, description='sku')
    weight: float | None = Field(None, description='weight')
    cost_price: float | None = Field(None, description='Unit cost price for margin calculations')
    account: str | None = Field(None, description='account')
    project_id: str | None = Field(None, description='project_id')
    unit_type: str | None = Field(None, description='unit_type')
    supplied: bool | None = Field(None, description='Whether this line is a supply expense (suplido) paid on behalf of the client. Excluded from the tax base.')
    retention: float | None = Field(None, description='IRPF withholding percentage to apply to this line. Reduces the invoice total.')

class HoldedCreateInvoiceConfigCustomFieldsItem(_Input):
    field: str | None = Field(None, description='Custom field identifier')
    value: str | None = Field(None, description='Value stored in the custom field')

class HoldedCreateInvoiceConfigShippingAddress(_Input):
    type: Literal['billing', 'hidden', 'manual', 'contact'] = Field(..., description='Address mode: manual (uses the address fields), billing (the billing address of the contact), hidden (no address displayed) or contact (an address saved on the contact, requires contact_address_id)')
    name: str | None = Field(None, description='Name of the shipping recipient (the given name when family_name is also sent)')
    family_name: str | None = Field(None, description='Family name of the shipping recipient')
    organization: str | None = Field(None, description='Company or organization of the shipping recipient')
    address_line_1: str | None = Field(None, description='Primary address line')
    address_line_2: str | None = Field(None, description='Secondary address line')
    city: str | None = Field(None, description='City or locality')
    postal_code: str | None = Field(None, description='Postal or ZIP code')
    province: str | None = Field(None, description='State, province, or region')
    country: str | None = Field(None, description='Country name')
    country_code: str | None = Field(None, description='ISO 3166-1 alpha-2 country code')
    email: str | None = Field(None, description='Contact email for shipping')
    phone: str | None = Field(None, description='Contact phone number for shipping')
    mobile: str | None = Field(None, description='Mobile number for shipping')
    contact_address_id: str | None = Field(None, description='Identifier of an address saved on the contact (shipping_id in the contact shipping_addresses). Required when type is contact')

class HoldedCreateInvoiceConfig(_Input):
    'Create an invoice'
    operation: Literal['create_invoice'] = Field('create_invoice', json_schema_extra={"ui:hidden": True})
    contact_id: str = Field(..., min_length=1, description='Identifier of an existing contact')
    contact_name: str | None = Field(None, description='Name of the contact')
    description: str | None = Field(None, description='Free-text description of the invoice')
    date: Date | None = Field(None, description='Issue date in ISO 8601 format. Accepts date (YYYY-MM-DD) or datetime (e.g. 2026-01-15T00:00:00+00:00)')
    due_date: Date | None = Field(None, description='Payment due date in ISO 8601 format. Accepts date (YYYY-MM-DD) or datetime (e.g. 2026-01-15T00:00:00+00:00)')
    notes: str | None = Field(None, description='Internal notes visible only to your team')
    default_taxes: bool | None = Field(None, description="When true, a line with no taxes of its own, not linked to a catalog product or service, for a contact without default taxes takes the account's default taxes: its sales taxes on a sales document, its purchases taxes on a purchase document. When false or omitted, such a line is created untaxed.")
    body: str | None = Field(None, description='Rich-text content printed on the invoice')
    language: str | None = Field(None, description='ISO 639-1 language code for the invoice')
    currency: str | None = Field(None, description='ISO 4217 currency code')
    currency_change: float | None = Field(None, description='Exchange rate to apply when the currency differs from your account currency')
    items: list[HoldedCreateInvoiceConfigItemsItem] = Field(..., min_length=1, description='Line items to include in the invoice')
    tags: list[str] | None = Field(None, description='Tags to attach to the invoice')
    custom_fields: list[HoldedCreateInvoiceConfigCustomFieldsItem] | None = Field(None, description='Custom field values to set on the invoice')
    number: str | None = Field(None, description='Custom document number. Use only if you do not want to assign the number via one of the numbering series created in Holded (e.g. to replicate exactly the number from another platform). The value is saved as-is, without correlativity validation. If this field is sent, number_line_id is ignored.\n\nWarning: do not use a value that matches the format of an existing numbering series. The series keeps its own counter regardless of manually assigned numbers -- e.g. if a series is at number 24 and you manually create a document with 27, the series will keep issuing 25, 26, and when it reaches 27 it will try to create a number that already exists: the request will fail and the series will have lost its correlativity and order. If you need custom numbering, use a prefix or format that does not match any active series, or manage every document in that series with number_line_id.')
    number_line_id: str | None = Field(None, description='Identifier of the numbering series used to automatically assign the next correlative number. This is the recommended option, as it preserves the document order and correlativity. If both fields are sent, number takes priority and number_line_id is ignored.')
    warehouse_id: str | None = Field(None, description='Identifier of the warehouse for stock movements')
    sales_channel_id: str | None = Field(None, description='Identifier of the sales channel')
    discount: float | None = Field(None, description='Global discount percentage to apply')
    payment_method_id: str | None = Field(None, description='Identifier of the default payment method')
    design_id: str | None = Field(None, description='Identifier of the design template to apply to the document')
    shipping_address: HoldedCreateInvoiceConfigShippingAddress | None = Field(None, description='Structured shipping address. Omit to leave unchanged (update) or unset (create). Pass null to clear it. The address fields (name, address_line_1, city, ...) are only used with type=manual; with billing, hidden or contact they are ignored. Use type=contact with contact_address_id to point to an address saved on the contact.')

class HoldedGetInvoiceConfig(_Input):
    'Get an invoice'
    operation: Literal['get_invoice'] = Field('get_invoice', json_schema_extra={"ui:hidden": True})
    invoiceId: str = Field(..., pattern='^[a-f0-9]{24}$', min_length=1, description='Invoice ID (24-char hex ObjectId)')

class HoldedUpdateInvoiceConfigItemsItem(_Input):
    name: str | None = Field(None, description='name')
    type: Literal['product', 'shipping', 'title', 'rounding', 'refund', 'ecotax', 'wrapping', 'service'] | None = Field(None, description='Kind of line. `product` and `service` are billable lines whose amount (`units` × `price`, less `discount`, plus `taxes`) is added to the document total. `title` is a section-header line that shows only its `name` and carries no amount — it does not contribute to the total. Other values are special-purpose lines. Omit this field for an ordinary priced line item.')
    description: str | None = Field(None, description='description')
    product_id: str | None = Field(None, description='Identifier of an existing catalog product to link this line to. The id is stored as a reference associating the line with the product (used for stock and reporting). Each line field (`price`, `taxes`, ...) is taken as sent; api2 stores the line values you provide and does not itself read them back from the product record. Leave unset for a free-text line that is not a catalog product.')
    variant_id: str | None = Field(None, description='Identifier of the variant of `product_id` to link this line to. Requires `product_id`. Leave unset for a line without variant.')
    service_id: str | None = Field(None, description='Service identifier. When provided, the line type is automatically set to "service"')
    units: float | None = Field(None, description='units')
    price: float | None = Field(None, description='price')
    discount: float | None = Field(None, description='discount')
    taxes: list[str] | None = Field(None, description='Tax keys applied to this line. When omitted, the contact default tax applies, or, if the contact has none, the account default tax when the request asks for it, else no tax.')
    tags: list[str] | None = Field(None, description='tags')
    sku: str | None = Field(None, description='sku')
    weight: float | None = Field(None, description='weight')
    cost_price: float | None = Field(None, description='Unit cost price for margin calculations')
    account: str | None = Field(None, description='account')
    project_id: str | None = Field(None, description='project_id')
    unit_type: str | None = Field(None, description='unit_type')
    supplied: bool | None = Field(None, description='Whether this line is a supply expense (suplido) paid on behalf of the client. Excluded from the tax base.')
    retention: float | None = Field(None, description='IRPF withholding percentage to apply to this line. Reduces the invoice total.')

class HoldedUpdateInvoiceConfigCustomFieldsItem(_Input):
    field: str | None = Field(None, description='Custom field identifier')
    value: str | None = Field(None, description='Value stored in the custom field')

class HoldedUpdateInvoiceConfigShippingAddress(_Input):
    type: Literal['billing', 'hidden', 'manual', 'contact'] = Field(..., description='Address mode: manual (uses the address fields), billing (the billing address of the contact), hidden (no address displayed) or contact (an address saved on the contact, requires contact_address_id)')
    name: str | None = Field(None, description='Name of the shipping recipient (the given name when family_name is also sent)')
    family_name: str | None = Field(None, description='Family name of the shipping recipient')
    organization: str | None = Field(None, description='Company or organization of the shipping recipient')
    address_line_1: str | None = Field(None, description='Primary address line')
    address_line_2: str | None = Field(None, description='Secondary address line')
    city: str | None = Field(None, description='City or locality')
    postal_code: str | None = Field(None, description='Postal or ZIP code')
    province: str | None = Field(None, description='State, province, or region')
    country: str | None = Field(None, description='Country name')
    country_code: str | None = Field(None, description='ISO 3166-1 alpha-2 country code')
    email: str | None = Field(None, description='Contact email for shipping')
    phone: str | None = Field(None, description='Contact phone number for shipping')
    mobile: str | None = Field(None, description='Mobile number for shipping')
    contact_address_id: str | None = Field(None, description='Identifier of an address saved on the contact (shipping_id in the contact shipping_addresses). Required when type is contact')

class HoldedUpdateInvoiceConfig(_Input):
    'Update an invoice'
    operation: Literal['update_invoice'] = Field('update_invoice', json_schema_extra={"ui:hidden": True})
    invoiceId: str = Field(..., pattern='^[a-f0-9]{24}$', min_length=1, description='Invoice ID (24-char hex ObjectId)')
    contact_id: str | None = Field(None, description='Identifier of an existing contact')
    contact_name: str | None = Field(None, description='Name of the contact')
    description: str | None = Field(None, description='Free-text description of the invoice')
    date: Date | None = Field(None, description='Issue date in ISO 8601 format. Accepts date (YYYY-MM-DD) or datetime (e.g. 2026-01-15T00:00:00+00:00)')
    due_date: Date | None = Field(None, description='Payment due date in ISO 8601 format. Accepts date (YYYY-MM-DD) or datetime (e.g. 2026-01-15T00:00:00+00:00)')
    notes: str | None = Field(None, description='Internal notes visible only to your team')
    body: str | None = Field(None, description='Rich-text content printed on the invoice')
    language: str | None = Field(None, description='ISO 639-1 language code for the invoice')
    currency: str | None = Field(None, description='ISO 4217 currency code')
    currency_change: float | None = Field(None, description='Exchange rate to apply when the currency differs from your account currency')
    items: list[HoldedUpdateInvoiceConfigItemsItem] | None = Field(None, description='Line items to include in the invoice')
    tags: list[str] | None = Field(None, description='Tags to attach to the invoice')
    custom_fields: list[HoldedUpdateInvoiceConfigCustomFieldsItem] | None = Field(None, description='Custom field values to set on the invoice')
    number_line_id: str | None = Field(None, description='Identifier of the numbering series to use')
    warehouse_id: str | None = Field(None, description='Identifier of the warehouse for stock movements')
    sales_channel_id: str | None = Field(None, description='Identifier of the sales channel')
    discount: float | None = Field(None, description='Global discount percentage to apply')
    payment_method_id: str | None = Field(None, description='Identifier of the default payment method')
    design_id: str | None = Field(None, description='Identifier of the design template to apply to the document')
    shipping_address: HoldedUpdateInvoiceConfigShippingAddress | None = Field(None, description='Structured shipping address. Omit to leave unchanged (update) or unset (create). Pass null to clear it. The address fields (name, address_line_1, city, ...) are only used with type=manual; with billing, hidden or contact they are ignored. Use type=contact with contact_address_id to point to an address saved on the contact.')

class HoldedDeleteInvoiceConfig(_Input):
    'Delete an invoice'
    operation: Literal['delete_invoice'] = Field('delete_invoice', json_schema_extra={"ui:hidden": True})
    invoiceId: str = Field(..., pattern='^[a-f0-9]{24}$', min_length=1, description='Invoice ID (24-char hex ObjectId)')

class HoldedListProductsConfig(_Input):
    'List all products'
    operation: Literal['list_products'] = Field('list_products', json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, description='Search products by name across your whole catalog. Optional.')
    cursor: str | None = Field(None, description='Opaque cursor for pagination')
    limit: int | None = Field(None, ge=1, le=200, description='Number of products per page. Defaults to 50, maximum 200.')

class HoldedCreateProductConfigVariantsItem(_Input):
    sku: str | None = Field(None, description='sku')
    barcode: str | None = Field(None, description='barcode')
    price: str | None = Field(None, description='price')
    cost: str | None = Field(None, description='cost')
    purchase_price: str | None = Field(None, description='purchase_price')
    stock: float | None = Field(None, description='stock')
    description: str | None = Field(None, description='description')
    weight: float | None = Field(None, description='weight')
    factory_code: str | None = Field(None, description='factory_code')
    archived: bool | None = Field(None, description='archived')
    lot_number: str | None = Field(None, description='Only for LOTS products')
    start_date: Date | None = Field(None, description='Only for LOTS and serial number products. ISO 8601 format. Accepts date (YYYY-MM-DD) or datetime (e.g. 2025-01-01T00:00:00+00:00)')
    end_date: Date | None = Field(None, description='Only for LOTS and serial number products. ISO 8601 format. Accepts date (YYYY-MM-DD) or datetime (e.g. 2025-12-31T00:00:00+00:00)')

class HoldedCreateProductConfigPackItemsItem(_Input):
    product_selection: str | None = Field(None, description='Product ID or "productId#variantId"')
    units: float | None = Field(None, description='units')

class HoldedCreateProductConfig(_Input):
    'Create a product'
    operation: Literal['create_product'] = Field('create_product', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, description='Product name')
    kind: Literal['simple', 'lots', 'pack', 'variants', 'serialnumbers'] = Field(..., description="Product kind: 'simple' for standard products, 'variants' for products with attributes (color/size), 'lots' for batch-tracked products, 'serialnumbers' for individually tracked products, 'pack' for product bundles.")
    description: str | None = Field(None, description='Product description')
    sku: str | None = Field(None, description='Stock keeping unit code')
    barcode: str | None = Field(None, description='Barcode value')
    price: str | None = Field(None, description='Unit sale price as a decimal string')
    cost: str | None = Field(None, description='Unit cost price as a decimal string')
    purchase_price: str | None = Field(None, description='Unit purchase price as a decimal string')
    tags: list[str] | None = Field(None, description='List of tag names')
    taxes: list[str] | None = Field(None, description='Tax keys applied to this product. Accepts the human tax name (e.g. "IVA 21%") or the internal key (e.g. "s_iva_21"); resolved automatically.')
    stock: float | None = Field(None, description='Initial stock quantity')
    weight: float | None = Field(None, description='Weight in account default unit')
    has_stock: bool = Field(..., description='Whether stock tracking is enabled')
    for_sale: bool = Field(..., description='Whether the product is available for sale')
    for_purchase: bool = Field(..., description='Whether the product is available for purchase')
    variants: list[HoldedCreateProductConfigVariantsItem] | None = Field(None, description='Variants of the product (for variants, lots and serial numbers product types).')
    pack_items: list[HoldedCreateProductConfigPackItemsItem] | None = Field(None, description='Items included in this pack product.')
    show_start_date: bool | None = Field(None, description='Show lot start date in documents. Only for LOTS products.')
    show_end_date: bool | None = Field(None, description='Show lot end date in documents. Only for LOTS products.')
    warehouse_id: str | None = Field(None, description='Default warehouse identifier for this product')
    sales_channel_id: str | None = Field(None, description='Sales channel identifier for this product')
    exp_account_id: str | None = Field(None, description='Expense/purchases accounting account identifier for this product')

class HoldedGetProductConfig(_Input):
    'Get a product by ID'
    operation: Literal['get_product'] = Field('get_product', json_schema_extra={"ui:hidden": True})
    productId: str = Field(..., pattern='^[a-f0-9]{24}$', min_length=1, description='Product ID (24-char hex ObjectId)')

class HoldedUpdateProductConfigVariantsItem(_Input):
    id: str | None = Field(None, description='Variant identifier')
    sku: str | None = Field(None, description='sku')
    barcode: str | None = Field(None, description='barcode')
    price: str | None = Field(None, description='price')
    cost: str | None = Field(None, description='cost')
    purchase_price: str | None = Field(None, description='purchase_price')
    stock: float | None = Field(None, description='stock')
    description: str | None = Field(None, description='description')
    weight: float | None = Field(None, description='weight')
    factory_code: str | None = Field(None, description='factory_code')
    archived: bool | None = Field(None, description='archived')
    lot_number: str | None = Field(None, description='Only for LOTS products')
    start_date: Date | None = Field(None, description='Only for LOTS and serial number products. ISO 8601 format. Accepts date (YYYY-MM-DD) or datetime (e.g. 2025-01-01T00:00:00+00:00)')
    end_date: Date | None = Field(None, description='Only for LOTS and serial number products. ISO 8601 format. Accepts date (YYYY-MM-DD) or datetime (e.g. 2025-12-31T00:00:00+00:00)')

class HoldedUpdateProductConfigPackItemsItem(_Input):
    product_selection: str | None = Field(None, description='Product ID or "productId#variantId"')
    units: float | None = Field(None, description='units')

class HoldedUpdateProductConfig(_Input):
    'Update a product'
    operation: Literal['update_product'] = Field('update_product', json_schema_extra={"ui:hidden": True})
    productId: str = Field(..., pattern='^[a-f0-9]{24}$', min_length=1, description='Product ID (24-char hex ObjectId)')
    name: str = Field(..., min_length=1, description='Product name')
    description: str | None = Field(None, description='Product description')
    sku: str | None = Field(None, description='Stock keeping unit code')
    barcode: str | None = Field(None, description='Barcode value')
    price: str | None = Field(None, description='Unit sale price as a decimal string')
    cost: str | None = Field(None, description='Unit cost price as a decimal string')
    purchase_price: str | None = Field(None, description='Unit purchase price as a decimal string')
    weight: float | None = Field(None, description='Weight in account default unit')
    tags: list[str] | None = Field(None, description='List of tag names')
    taxes: list[str] | None = Field(None, description='Tax keys applied to this product. Accepts the human tax name (e.g. "IVA 21%") or the internal key (e.g. "s_iva_21"); resolved automatically.')
    for_sale: bool = Field(..., description='Whether the product is available for sale')
    for_purchase: bool = Field(..., description='Whether the product is available for purchase')
    archived: bool = Field(..., description='Whether the product is archived')
    variants: list[HoldedUpdateProductConfigVariantsItem] | None = Field(None, description='Variants of the product (for variants, lots and serial numbers product types). Sending this field replaces all existing variants.')
    pack_items: list[HoldedUpdateProductConfigPackItemsItem] | None = Field(None, description='Items included in this pack product. Sending this field replaces all existing pack items.')
    show_start_date: bool | None = Field(None, description='Show lot start date in documents. Only for LOTS products.')
    show_end_date: bool | None = Field(None, description='Show lot end date in documents. Only for LOTS products.')
    warehouse_id: str | None = Field(None, description='Default warehouse identifier for this product')
    sales_channel_id: str | None = Field(None, description='Sales channel identifier for this product')
    exp_account_id: str | None = Field(None, description='Expense/purchases accounting account identifier for this product')

class HoldedDeleteProductConfig(_Input):
    'Delete a product'
    operation: Literal['delete_product'] = Field('delete_product', json_schema_extra={"ui:hidden": True})
    productId: str = Field(..., pattern='^[a-f0-9]{24}$', min_length=1, description='Product ID (24-char hex ObjectId)')

class HoldedListProjectsConfig(_Input):
    'List projects'
    operation: Literal['list_projects'] = Field('list_projects', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, description='Pagination cursor returned by the previous response. Omit to start from the first page.')
    limit: int | None = Field(None, ge=1, le=200, description='Maximum number of items to return')
    status: Literal['active', 'in_progress', 'completed', 'cancelled', 'waiting', 'budgeted'] | None = Field(None, description='Filter projects by status. Use "active" or "in_progress" to retrieve only active/in-progress projects.')

class HoldedCreateProjectConfig(_Input):
    'Create a project'
    operation: Literal['create_project'] = Field('create_project', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, description='Project name')
    description: str | None = Field(None, description='Project description')
    due_date: Date | None = Field(None, description='Due date in ISO 8601')
    contact_id: str | None = Field(None, description='Contact ID')

class HoldedGetProjectConfig(_Input):
    'Get a project'
    operation: Literal['get_project'] = Field('get_project', json_schema_extra={"ui:hidden": True})
    projectId: str = Field(..., pattern='^[a-f0-9]{24}$', min_length=1, description='Project ID')

class HoldedUpdateProjectConfigListsItem(_Input):
    id: str = Field(..., min_length=1, description='List ID')
    key: str = Field(..., min_length=1, description='List key')
    name: str = Field(..., min_length=1, description='List name')
    desc: str = Field(..., min_length=1, description='List description')
    statuses: list[str] | None = Field(None, description='List statuses')
    completed: bool | None = Field(None, description='Whether the list is completed')

class HoldedUpdateProjectConfig(_Input):
    'Update a project'
    operation: Literal['update_project'] = Field('update_project', json_schema_extra={"ui:hidden": True})
    projectId: str = Field(..., pattern='^[a-f0-9]{24}$', min_length=1, description='Project ID')
    name: str | None = Field(None, description='Project name')
    description: str | None = Field(None, description='Project description')
    due_date: Date | None = Field(None, description='Due date in ISO 8601')
    contact_id: str | None = Field(None, description='Contact ID')
    status: int | None = Field(None, ge=0, le=4, description='Project status (0–4)')
    start_date: Date | None = Field(None, description='Start date in ISO 8601 format (YYYY-MM-DD)')
    billable: bool | None = Field(None, description='Whether the project is billable')
    tags: list[str] | None = Field(None, description='List of tags')
    allow_notifications: bool | None = Field(None, description='Whether notifications are enabled')
    lists: list[HoldedUpdateProjectConfigListsItem] | None = Field(None, description='Project lists')

class HoldedDeleteProjectConfig(_Input):
    'Delete a project'
    operation: Literal['delete_project'] = Field('delete_project', json_schema_extra={"ui:hidden": True})
    projectId: str = Field(..., pattern='^[a-f0-9]{24}$', min_length=1, description='Project ID')

class HoldedListTasksConfig(_Input):
    'List all tasks'
    operation: Literal['list_tasks'] = Field('list_tasks', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, description='Pagination cursor returned by the previous response. Omit to start from the first page.')
    limit: int | None = Field(None, ge=1, le=200, description='Maximum number of items to return')
    status: Literal['open', 'done'] | None = Field(None, description='`open`: tasks not in a done status and not archived. `done`: tasks in a done status, archived ones included. Omit to list every task, archived ones included.')

class HoldedCreateTaskConfig(_Input):
    'Create a task'
    operation: Literal['create_task'] = Field('create_task', json_schema_extra={"ui:hidden": True})
    project_id: str = Field(..., min_length=1, description='Project ID')
    name: str = Field(..., min_length=1, description='Task name')
    description: str | None = Field(None, description='Task description')
    due_date: Date | None = Field(None, description='Due date in ISO 8601')
    priority: int | None = Field(None, description='Task priority')
    status: str | None = Field(None, description='Task status')
    assigned_to: list[str] | None = Field(None, description='Assigned user IDs')

class HoldedGetTaskConfig(_Input):
    'Get a task'
    operation: Literal['get_task'] = Field('get_task', json_schema_extra={"ui:hidden": True})
    taskId: str = Field(..., pattern='^[a-f0-9]{24}$', min_length=1, description='Task ID')

class HoldedUpdateTaskConfig(_Input):
    'Update a task'
    operation: Literal['update_task'] = Field('update_task', json_schema_extra={"ui:hidden": True})
    taskId: str = Field(..., pattern='^[a-f0-9]{24}$', min_length=1, description='Task ID')
    project_id: str | None = Field(None, description='Project ID')
    name: str | None = Field(None, description='Task name')
    description: str | None = Field(None, description='Task description')
    due_date: Date | None = Field(None, description='Due date in ISO 8601')
    priority: int | None = Field(None, description='Task priority')
    status: str | None = Field(None, description='Task status')
    assigned_to: list[str] | None = Field(None, description='Assigned user IDs')

class HoldedDeleteTaskConfig(_Input):
    'Delete a task'
    operation: Literal['delete_task'] = Field('delete_task', json_schema_extra={"ui:hidden": True})
    taskId: str = Field(..., pattern='^[a-f0-9]{24}$', min_length=1, description='Task ID')

HOLDED_WEBHOOK_EVENTS = (
    "invoice.create", "invoice.update", "invoice.approve", "invoice.delete",
    "contact.create", "contact.update", "contact.delete",
    "product.create", "product.update", "stock.update",
)


class HoldedOnEventConfig(WebhookTriggerConfigBase):
    """Receive the documented Holded v1 webhook payload for the selected event."""

    operation: Literal["on_event"] = Field("on_event", title="On Holded Event", json_schema_extra={
        "const": "on_event", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On Holded Event",
    })
    event_type: Literal[*HOLDED_WEBHOOK_EVENTS] = Field(
        "invoice.create", title="Event", description="The Holded event that starts this workflow. Requires developers:webhooks.write permission on the API key.")
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered with Holded automatically",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


HoldedOperation = Annotated[Union[HoldedOnEventConfig, HoldedListContactsConfig, HoldedCreateContactConfig, HoldedGetContactConfig, HoldedUpdateContactConfig, HoldedDeleteContactConfig, HoldedListInvoicesConfig, HoldedCreateInvoiceConfig, HoldedGetInvoiceConfig, HoldedUpdateInvoiceConfig, HoldedDeleteInvoiceConfig, HoldedListProductsConfig, HoldedCreateProductConfig, HoldedGetProductConfig, HoldedUpdateProductConfig, HoldedDeleteProductConfig, HoldedListProjectsConfig, HoldedCreateProjectConfig, HoldedGetProjectConfig, HoldedUpdateProjectConfig, HoldedDeleteProjectConfig, HoldedListTasksConfig, HoldedCreateTaskConfig, HoldedGetTaskConfig, HoldedUpdateTaskConfig, HoldedDeleteTaskConfig], Field(discriminator="operation")]

class HoldedFullConfig(NodeConfig[HoldedOperation, HoldedAPIKey]):
    pass

ROUTES = {'list_contacts': ('GET', '/api/v2/contacts', [], ['phone', 'mobile', 'email', 'custom_id', 'code', 'cursor', 'limit']), 'create_contact': ('POST', '/api/v2/contacts', [], []), 'get_contact': ('GET', '/api/v2/contacts/{contactId}', ['contactId'], []), 'update_contact': ('PUT', '/api/v2/contacts/{contactId}', ['contactId'], []), 'delete_contact': ('DELETE', '/api/v2/contacts/{contactId}', ['contactId'], []), 'list_invoices': ('GET', '/api/v2/invoices', [], ['limit', 'cursor', 'contact_id', 'status', 'start_date', 'end_date', 'due_date_start', 'due_date_end', 'sort', 'approval_status', 'accounting_account_num']), 'create_invoice': ('POST', '/api/v2/invoices', [], []), 'get_invoice': ('GET', '/api/v2/invoices/{invoiceId}', ['invoiceId'], []), 'update_invoice': ('PUT', '/api/v2/invoices/{invoiceId}', ['invoiceId'], []), 'delete_invoice': ('DELETE', '/api/v2/invoices/{invoiceId}', ['invoiceId'], []), 'list_products': ('GET', '/api/v2/products', [], ['name', 'cursor', 'limit']), 'create_product': ('POST', '/api/v2/products', [], []), 'get_product': ('GET', '/api/v2/products/{productId}', ['productId'], []), 'update_product': ('PUT', '/api/v2/products/{productId}', ['productId'], []), 'delete_product': ('DELETE', '/api/v2/products/{productId}', ['productId'], []), 'list_projects': ('GET', '/api/v2/projects', [], ['cursor', 'limit', 'status']), 'create_project': ('POST', '/api/v2/projects', [], []), 'get_project': ('GET', '/api/v2/projects/{projectId}', ['projectId'], []), 'update_project': ('PUT', '/api/v2/projects/{projectId}', ['projectId'], []), 'delete_project': ('DELETE', '/api/v2/projects/{projectId}', ['projectId'], []), 'list_tasks': ('GET', '/api/v2/tasks', [], ['cursor', 'limit', 'status']), 'create_task': ('POST', '/api/v2/tasks', [], []), 'get_task': ('GET', '/api/v2/tasks/{taskId}', ['taskId'], []), 'update_task': ('PUT', '/api/v2/tasks/{taskId}', ['taskId'], []), 'delete_task': ('DELETE', '/api/v2/tasks/{taskId}', ['taskId'], [])}

def _redact(value, token):
    if isinstance(value, str): return value.replace(token, "[redacted]")
    if isinstance(value, list): return [_redact(x, token) for x in value]
    if isinstance(value, dict): return {k: _redact(v, token) for k, v in value.items() if k.lower() not in {"authorization", "api_key", "access_token"}}
    return value

class HoldedNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-holded"
    connection_evidence = ConnectionEvidence(noun="contacts", operation="list_contacts")

    @classmethod
    def get_config_model(cls): return HoldedFullConfig

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = (config or {}).get("event_type", "invoice.create")
        if event not in HOLDED_WEBHOOK_EVENTS:
            raise ValueError("Choose a supported Holded event")
        result = await cls._request(credential.get("api_key"), "POST", "/api/v2/webhooks", body={
            "url": webhook_url, "events": [event], "version": "v1", "description": f"NoClick {node_id}"})
        if not isinstance(result, dict) or not result.get("id") or not result.get("secret"):
            raise ValueError("Holded did not return a webhook ID and signing secret")
        return {"external_webhook_id": result["id"], "signing_secret": result["secret"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint_id = (config or {}).get("external_webhook_id")
        if endpoint_id:
            await cls._request((credential or {}).get("api_key"), "DELETE",
                "/api/v2/webhooks/" + quote(str(endpoint_id), safe=""))

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type", "invoice.create")}

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict[str, str], config: dict[str, Any]) -> bool:
        # https://www.holded.com/developers/webhooks: raw body, literal whsec_ secret.
        secret = (config or {}).get("signing_secret")
        received = next((v for k, v in headers.items() if k.lower() == "x-holded-webhook-signature"), "")
        if not secret or not isinstance(received, str) or not received.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(str(secret).encode(), body, hashlib.sha256).hexdigest()
        return received.isascii() and hmac.compare_digest(expected, received)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        headers = (payload.get("_webhook") or {}).get("headers") or {}
        event = next((v for k, v in headers.items() if k.lower() == "x-holded-webhook-event"), None)
        return (config or {}).get("operation") == "on_event" and event == (config or {}).get("event_type", "invoice.create")

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict):
            return None
        headers = {k.lower(): v for k, v in (output.get("_webhook", {}).get("headers") or {}).items()}
        event = headers.get("x-holded-webhook-event")
        if event not in HOLDED_WEBHOOK_EVENTS:
            return None
        resource, action = event.split(".")
        verb = {"create": "created", "update": "updated", "approve": "approved", "delete": "deleted"}[action]
        if resource == "stock":
            record_id = output.get("productId")
            facts = [("Product ID", record_id), ("Variant ID", output.get("variantId")),
                     ("Warehouse ID", output.get("warehouseId")), ("SKU", output.get("sku")),
                     ("Stock change", output.get("stockVariation"))]
            heading = f"Holded stock updated: {output.get('sku') or record_id}"
        else:
            record_id = output.get("id")
            facts = [(f"{resource.title()} ID", record_id)]
            if resource == "invoice":
                heading = f"Holded invoice {verb}: {output.get('documentNumber') or record_id}"
                facts.append(("Contact ID", output.get("contactId")))
                if action != "delete":
                    facts += [("Contact", output.get("contactName")), ("Total", output.get("total")),
                              ("Date", output.get("date")), ("Due date", output.get("dueDate"))]
            elif resource == "contact":
                heading = f"Holded contact {verb}: {record_id if action == 'delete' else output.get('name') or record_id}"
                if action != "delete":
                    facts += [("Email", output.get("email")), ("Phone", output.get("phoneNumber"))]
            else:
                heading = f"Holded product {verb}: {output.get('name') or record_id}"
                facts += [("SKU", output.get("sku")), ("Price", output.get("price")), ("Stock", output.get("stock"))]
        facts += [("Holded account", headers.get("x-holded-webhook-account-id")),
                  ("Event ID", headers.get("x-holded-webhook-id")), ("Sent at", headers.get("x-holded-webhook-date"))]
        text = "\n".join([heading] + [f"{key}: {value}" for key, value in facts if value is not None])
        return {"text": text, "conversation_key": f"holded:{headers.get('x-holded-webhook-account-id', '')}:{resource}:{record_id}",
                "title": heading}

    @staticmethod
    async def _request(token, method, path, *, query=None, body=None):
        if not token:
            raise ValueError("Connect a Holded API key")
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://api.holded.com" + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    params=query, **({"json": body} if method in {"POST", "PUT", "PATCH"} else {}))
        except (httpx.TimeoutException, httpx.TransportError):
            raise ValueError("Holded request did not complete; inspect the account before retrying a write") from None
        if not 200 <= response.status_code < 300:
            message = "Holded HTTP " + str(response.status_code)
            try:
                error = response.json()
                if isinstance(error, dict): message += ": " + str(error.get("detail") or error.get("title") or "Request rejected")[:1000]
            except ValueError: pass
            raise ValueError(_redact(message, token))
        if response.status_code == 204: return {"status": "success", "deleted": True}
        try: body = response.json()
        except ValueError: raise ValueError("Holded returned invalid JSON") from None
        if not isinstance(body, (dict, list)): raise ValueError("Holded returned an unexpected response")
        return _redact(body, token)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Holded API key")
        op = self.config.config
        if isinstance(op, HoldedOnEventConfig):
            return self.no_event_output(op.operation, "Waiting for a Holded webhook event")
        token = self.config.credentials.api_key
        method, path, path_fields, query_fields = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_unset=True, exclude={"operation"})
        for field in path_fields: path = path.replace("{" + field + "}", quote(str(values.pop(field)), safe=""))
        query = {key: values.pop(key) for key in query_fields if key in values and values[key] is not None}
        return await self._request(token, method, path, query=query, body=values)
