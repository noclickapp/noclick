"""QuickFile REST v2 personal-token actions and creation polling.

Contract: https://api-beta.quickfile.co.uk/api-docs/v2
Authentication: https://support.quickfile.co.uk/t/rest-api-overview/64912
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE_URL = "https://api-beta.quickfile.co.uk"


class QuickFileTokenCredential(BaseModel):
    model_config = ConfigDict(title="Quickfile Personal Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://support.quickfile.co.uk/t/rest-api-overview/64912",
            "x-credential-instructions": "In your QuickFile account, open Account Settings → Third Party Integration → API. Generate a personal bearer token for your own account, enabling the endpoint groups your workflow uses. Paste the token without the Bearer prefix. The connection check reads your business details via /account/me. The REST API is in beta.",
        })
    credential_type: Literal["quickfile_token"] = Field("quickfile_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Personal Bearer Token", repr=False, min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal bearer token", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without the Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class GetAccountConfig(_Input):
    """Get the business details for the connected user, e.g. business name, type, address, year end date, vat status and account size statistics.."""
    operation: Literal['get_account'] = Field('get_account', title='Get Account', json_schema_extra={"ui:hidden": True})


class ListClientsConfig(_Input):
    """Retrieve client records based on a set of search parameters."""
    operation: Literal['list_clients'] = Field('list_clients', title='List Clients', json_schema_extra={"ui:hidden": True})
    order_column: str | None = Field(None, title='Order Column', description='Which columns should be used for ordering the record set. E.g. created_date, company_name.')
    order_direction: str | None = Field(None, title='Order Direction', description='Order direction. Ascending (asc) or Descending (desc).')
    include_deleted: bool | None = Field(None, title='Include Deleted', description='Show previously deleted clients. Default is false.')
    company_name: str | None = Field(None, title='Company Name', description='Search by partial company name.')
    first_name: str | None = Field(None, title='First Name', description='Search by first name.')
    surname: str | None = Field(None, title='Surname', description='Search by surname.')
    email: str | None = Field(None, title='Email', description='Search by email.')
    account_reference: str | None = Field(None, title='Account Reference', description='Search by client account reference.')
    telephone: str | None = Field(None, title='Telephone', description='Search by telephone.')
    include_total_invoiced: bool | None = Field(None, title='Include Total Invoiced', description='Returns the total amount invoiced for each client.')
    include_total_paid: bool | None = Field(None, title='Include Total Paid', description='Returns the total payments received for each client.')
    include_total_credits: bool | None = Field(None, title='Include Total Credits', description='Returns the total of prepayments held on account for each client.')
    offset: int | None = Field(None, title='Offset', description='Page offset. Zero (0) would show results from the beginning of the record set. Offset can be used for paging functions.', ge=0, le=1000000)
    limit: int | None = Field(None, title='Limit', description='How many records would you like the API to return.', ge=0, le=100)


class GetClientConfig(_Input):
    """Retrieve client and contact data."""
    operation: Literal['get_client'] = Field('get_client', title='Get Client', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., title='Id', description='Client id')
    contacts: bool | None = Field(None, title='Contacts', description='Returns a list of client contacts associated with this particular client record.')
    financials: bool | None = Field(None, title='Financials', description='Returns credits on account and balance info.')


class CreateClientConfig(_Input):
    """Create a new client record."""
    operation: Literal['create_client'] = Field('create_client', title='Create Client', json_schema_extra={"ui:hidden": True})
    company_name: str = Field(..., title='Company Name', description='Company name', min_length=0, max_length=100)
    company_number: str | None = Field(None, title='Company Number', description='Company number', min_length=0, max_length=10)
    account_reference: str | None = Field(None, title='Account Reference', description='Your own account identifier (Optional)', min_length=0, max_length=30)
    address_line1: str | None = Field(None, title='Address Line1', description='Address line1', min_length=0, max_length=75)
    address_line2: str | None = Field(None, title='Address Line2', description='Address line2', min_length=0, max_length=75)
    address_line3: str | None = Field(None, title='Address Line3', description='Address line3', min_length=0, max_length=75)
    town: str | None = Field(None, title='Town', description='Town', min_length=0, max_length=75)
    country_iso: str | None = Field(None, title='Country Iso', description='Country iso', min_length=2, max_length=2)
    post_code: str | None = Field(None, title='Post Code', description='Post code', min_length=0, max_length=15)
    vat_number: str | None = Field(None, title='Vat Number', description='Vat number', min_length=0, max_length=20)
    go_cardless_mandate: str | None = Field(None, title='Go Cardless Mandate', description='Optional GoCardless Direct Debit mandate ID', min_length=6, max_length=15)
    allow_attach_pdf: bool | None = Field(None, title='Allow Attach Pdf', description='Set this to allow invoices/statements and estimates to be attached to emails in PDF format')
    default_send_method: str | None = Field(None, title='Default Send Method', description='What default send method would you like to use for outbound invoices? E.g. email, snailmail')
    default_currency: str | None = Field(None, title='Default Currency', description='If not supply will revert to account default.', min_length=3, max_length=3)
    default_term: int | None = Field(None, title='Default Term', description='If not supply will revert to account default.')
    trading_style: int | None = Field(None, title='Trading Style', description='The Trading Style ID where multiple trading styles are defined on the account. To locate the ID click to edit the trading style within the web application.')
    payment_restrictions: list[str] | None = Field(None, title='Payment Restrictions', description='A list of restricted payment processors for this client. E.g. paypal, gocardless, paymentsense, bitpay, stripe, worldpay, sagepay')


class UpdateClientConfig(_Input):
    """Update an existing client record."""
    operation: Literal['update_client'] = Field('update_client', title='Update Client', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., title='Id', description='Client id')
    company_name: str | None = Field(None, title='Company Name', description='Company name', min_length=0, max_length=100)
    company_number: str | None = Field(None, title='Company Number', description='Company number', min_length=0, max_length=10)
    account_reference: str | None = Field(None, title='Account Reference', description='Your own account identifier (Optional)', min_length=0, max_length=30)
    address_line1: str | None = Field(None, title='Address Line1', description='Address line1', min_length=0, max_length=75)
    address_line2: str | None = Field(None, title='Address Line2', description='Address line2', min_length=0, max_length=75)
    address_line3: str | None = Field(None, title='Address Line3', description='Address line3', min_length=0, max_length=75)
    town: str | None = Field(None, title='Town', description='Town', min_length=0, max_length=75)
    country_iso: str | None = Field(None, title='Country Iso', description='Country iso', min_length=2, max_length=2)
    post_code: str | None = Field(None, title='Post Code', description='Post code', min_length=0, max_length=15)
    vat_number: str | None = Field(None, title='Vat Number', description='Vat number', min_length=0, max_length=20)
    go_cardless_mandate: str | None = Field(None, title='Go Cardless Mandate', description='Optional GoCardless Direct Debit mandate ID', min_length=6, max_length=15)
    allow_attach_pdf: bool | None = Field(None, title='Allow Attach Pdf', description='Set this to allow invoices/statements and estimates to be attached to emails in PDF format')
    default_send_method: str | None = Field(None, title='Default Send Method', description='What default send method would you like to use for outbound invoices? E.g. email, snailmail')
    default_currency: str | None = Field(None, title='Default Currency', description='If not supply will revert to account default.', min_length=3, max_length=3)
    default_term: int | None = Field(None, title='Default Term', description='If not supply will revert to account default.')
    trading_style: int | None = Field(None, title='Trading Style', description='The Trading Style ID where multiple trading styles are defined on the account. To locate the ID click to edit the trading style within the web application.')
    payment_restrictions: list[str] | None = Field(None, title='Payment Restrictions', description='A list of restricted payment processors for this client. E.g. paypal, gocardless, paymentsense, bitpay, stripe, worldpay, sagepay')


class ListSuppliersConfig(_Input):
    """Retrieve supplier records based on a set of search parameters."""
    operation: Literal['list_suppliers'] = Field('list_suppliers', title='List Suppliers', json_schema_extra={"ui:hidden": True})
    order_column: str | None = Field(None, title='Order Column', description='Which columns should be used for ordering the record set. E.g. created_date, company_name.')
    order_direction: str | None = Field(None, title='Order Direction', description='Order direction. Ascending (asc) or Descending (desc).')
    include_deleted: bool | None = Field(None, title='Include Deleted', description='Show previously deleted clients. Default is false.')
    company_name: str | None = Field(None, title='Company Name', description='Search by partial company name.')
    first_name: str | None = Field(None, title='First Name', description='Search by first name.')
    surname: str | None = Field(None, title='Surname', description='Search by surname.')
    email: str | None = Field(None, title='Email', description='Search by email.')
    supplier_reference: str | None = Field(None, title='Supplier Reference', description='Search by supplier reference.')
    telephone: str | None = Field(None, title='Telephone', description='Search by telephone.')
    include_total_invoiced: bool | None = Field(None, title='Include Total Invoiced', description='Returns the total amount invoiced for each supplier.')
    include_total_paid: bool | None = Field(None, title='Include Total Paid', description='Returns the total payments received for each supplier.')
    include_total_credits: bool | None = Field(None, title='Include Total Credits', description='Returns the total of prepayments held on account for each supplier.')
    offset: int | None = Field(None, title='Offset', description='Page offset. Zero (0) would show results from the beginning of the record set. Offset can be used for paging functions.', ge=0, le=1000000)
    limit: int | None = Field(None, title='Limit', description='How many records would you like the API to return.', ge=0, le=100)


class GetSupplierConfig(_Input):
    """Retrieve supplier and contact data."""
    operation: Literal['get_supplier'] = Field('get_supplier', title='Get Supplier', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., title='Id', description='Supplier id')


class CreateSupplierConfig(_Input):
    """Create a new supplier record."""
    operation: Literal['create_supplier'] = Field('create_supplier', title='Create Supplier', json_schema_extra={"ui:hidden": True})
    company_name: str = Field(..., title='Company Name', min_length=0, max_length=100)
    contact_first_name: str | None = Field(None, title='Contact First Name', min_length=0, max_length=50)
    contact_surname: str | None = Field(None, title='Contact Surname', min_length=0, max_length=50)
    contact_telephone: str | None = Field(None, title='Contact Telephone', min_length=0, max_length=20)
    contact_email: str | None = Field(None, title='Contact Email', min_length=0, max_length=100)
    company_number: str | None = Field(None, title='Company Number', min_length=0, max_length=10)
    supplier_reference: str | None = Field(None, title='Supplier Reference', min_length=0, max_length=15)
    address_line1: str | None = Field(None, title='Address Line1', min_length=0, max_length=75)
    address_line2: str | None = Field(None, title='Address Line2', min_length=0, max_length=75)
    address_line3: str | None = Field(None, title='Address Line3', min_length=0, max_length=75)
    town: str | None = Field(None, title='Town', min_length=0, max_length=75)
    country_iso: str | None = Field(None, title='Country Iso')
    post_code: str | None = Field(None, title='Post Code', min_length=0, max_length=15)
    website: str | None = Field(None, title='Website', min_length=0, max_length=50)
    vat_number: str | None = Field(None, title='Vat Number', min_length=0, max_length=20)
    default_currency: str | None = Field(None, title='Default Currency', min_length=3, max_length=3)
    default_term: int | None = Field(None, title='Default Term')
    default_vatrate: float | None = Field(None, title='Default Vatrate')
    default_nominalcode: int | None = Field(None, title='Default Nominalcode', ge=5000, le=9997)


class UpdateSupplierConfig(_Input):
    """Update a supplier record."""
    operation: Literal['update_supplier'] = Field('update_supplier', title='Update Supplier', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., title='Id', description='Supplier id')
    company_name: str | None = Field(None, title='Company Name', min_length=0, max_length=100)
    company_number: str | None = Field(None, title='Company Number', min_length=0, max_length=10)
    supplier_reference: str | None = Field(None, title='Supplier Reference', min_length=0, max_length=15)
    address_line1: str | None = Field(None, title='Address Line1', min_length=0, max_length=75)
    address_line2: str | None = Field(None, title='Address Line2', min_length=0, max_length=75)
    address_line3: str | None = Field(None, title='Address Line3', min_length=0, max_length=75)
    town: str | None = Field(None, title='Town', min_length=0, max_length=75)
    country_iso: str | None = Field(None, title='Country Iso')
    post_code: str | None = Field(None, title='Post Code', min_length=0, max_length=15)
    website: str | None = Field(None, title='Website', min_length=0, max_length=50)
    vat_number: str | None = Field(None, title='Vat Number', min_length=0, max_length=20)
    default_currency: str | None = Field(None, title='Default Currency', min_length=3, max_length=3)
    default_term: int | None = Field(None, title='Default Term')
    default_vatrate: float | None = Field(None, title='Default Vatrate')
    default_nominalcode: int | None = Field(None, title='Default Nominalcode', ge=5000, le=9997)


class ListInvoicesConfig(_Input):
    """Search for invoices and estimates using a specific set of search parameters."""
    operation: Literal['list_invoices'] = Field('list_invoices', title='List Invoices', json_schema_extra={"ui:hidden": True})
    order_column: str | None = Field(None, title='Order Column', description='Which columns should be used for ordering the record set. E.g. invoice_number, issue_date, client_contact_name, gross_total.')
    order_direction: str | None = Field(None, title='Order Direction', description='Order direction. Ascending (asc) or Descending (desc).')
    type: str | None = Field(None, title='Type', description='Type of document to return. E.g. invoice, estimate, recurring.')
    tag_name: str | None = Field(None, title='Tag Name', description='Project tag name')
    include_deleted: bool | None = Field(None, title='Include Deleted', description='Show previously deleted invoices. Default is false.')
    client_id: int | None = Field(None, title='Client Id', description='Client ID can be used to return all invoices for a given client.')
    client_contact_name: str | None = Field(None, title='Client Contact Name', description='Whole or part of client company name.')
    recurring_profile_id: int | None = Field(None, title='Recurring Profile Id', description='Search by recurring profile ID')
    invoice_number: str | None = Field(None, title='Invoice Number', description='Search by invoice number')
    item_name: str | None = Field(None, title='Item Name', description='Search by item name')
    item_desc: str | None = Field(None, title='Item Desc', description='Search by item description')
    date_from: str | None = Field(None, title='Date From', description='Issued date range from (yyyy-mm-dd)')
    date_to: str | None = Field(None, title='Date To', description='Issued date range to (yyyy-mm-dd)')
    amount_from: str | None = Field(None, title='Amount From', description='Amount range from')
    amount_to: str | None = Field(None, title='Amount To', description='Amount range to')
    currency: str | None = Field(None, title='Currency', description='Currency ISO code must be 3 characters long.', min_length=3, max_length=3)
    status: str | None = Field(None, title='Status', description='Invoice status. E.g. draft, sent, disputed, paidpart, paidfull, active, unpaid, deleted, aged, paused, agreed, declined')
    purchase_ref: str | None = Field(None, title='Purchase Ref', description='Purchase Reference. Maximum 25 characters long.', min_length=0, max_length=25)
    offset: int | None = Field(None, title='Offset', description='Page offset. Zero (0) would show results from the beginning of the record set. Offset can be used for paging functions.', ge=0, le=1000000)
    limit: int | None = Field(None, title='Limit', description='How many records would you like the API to return.', ge=0, le=100)


class GetInvoiceConfig(_Input):
    """Retrieve a single invoice, estimate or recurring invoice template."""
    operation: Literal['get_invoice'] = Field('get_invoice', title='Get Invoice', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., title='Id', description='Invoice id')


class InvoicesCreateLine(_Input):
    item_id: int | None = Field(None, title='Item Id', description='Optional. If supplied, must match an existing inventory item ID to pre-populate details. Explicitly provided fields will override the inventory defaults.')
    item_name: str | None = Field(None, title='Item Name', description='Item Name (Short). Max 25 characters', min_length=0, max_length=25)
    description: str | None = Field(None, title='Description', description='Item Description (Long). Max 5000 characters. Required when item_id is not supplied.', min_length=0, max_length=5000)
    nominal_code: int | None = Field(None, title='Nominal Code', description='Nominal Code. Between 1 and 9999')
    vat_rate: float | None = Field(None, title='Vat Rate', description='The VAT rate to be applied. For non-VAT Reg suppliers use 0.00')
    vat_amount: float | None = Field(None, title='Vat Amount', description='Overrides the VAT Rate for specific VAT amounts. If missing will be calculated from the rate.')
    unit_cost: float | None = Field(None, title='Unit Cost')
    qty: float | None = Field(None, title='Qty')


class InvoicesCreateTask(_Input):
    id: int | None = Field(None, title='Id', description='Optional. If supplied, must match an existing inventory task ID to pre-populate details. Explicitly provided fields will override the inventory defaults.')
    item_name: str | None = Field(None, title='Item Name', description='Item Name (Short). Max 25 characters', min_length=0, max_length=25)
    description: str | None = Field(None, title='Description', description='Item Description (Long). Max 1000 characters', min_length=0, max_length=1000)
    nominal_code: int | None = Field(None, title='Nominal Code', description='Nominal Code. Between 1 and 9999')
    hourly_rate: float | None = Field(None, title='Hourly Rate')
    hours: float | None = Field(None, title='Hours', description='Number of hours')
    vat_rate: float | None = Field(None, title='Vat Rate')
    vat_amount: float | None = Field(None, title='Vat Amount', description='Optional tax element to be levied on the item. Between 1 and 7 characters long')


class InvoicesCreateScheduleRecurring(_Input):
    interval: str = Field(..., title='Interval', min_length=1)
    frequency: int = Field(..., title='Frequency')
    start_date: str = Field(..., title='Start Date', min_length=1)
    pro_rata_days: int | None = Field(None, title='Pro Rata Days')
    dd_auto_bill: bool | None = Field(None, title='Dd Auto Bill')
    dd_delay: int | None = Field(None, title='Dd Delay', description='Specify the number of days delay you would like to add before initiating a Direct Debit collection. Between 0 and 60', ge=0, le=60)
    send_by_email: bool | None = Field(None, title='Send By Email')
    send_by_post: bool | None = Field(None, title='Send By Post')
    auto_activate: bool | None = Field(None, title='Auto Activate')


class InvoicesCreateCreditNote(_Input):
    type: str = Field(..., title='Type', description='Type of credit note: void (write off unpaid balance), refund (return money to client), or hold (credit on account).', min_length=1)
    invoice_id: int | None = Field(None, title='Invoice Id', description='The invoice ID to set the credit note against. Required for void and hold types.')
    nominal_code: int | None = Field(None, title='Nominal Code', description='Bank nominal (1200-1299) that the refund should be paid from. Required for refund type.')


class CreateInvoiceConfig(_Input):
    """Create a new invoice, estimate or recurring invoice template."""
    operation: Literal['create_invoice'] = Field('create_invoice', title='Create Invoice', json_schema_extra={"ui:hidden": True})
    type: str = Field(..., title='Type', description='Type of document. E.g. invoice, estimate, recurring.', min_length=1)
    client_id: int = Field(..., title='Client Id', description='Unique Client ID.')
    client_contact_name: str | None = Field(None, title='Client Contact Name', description='Contact name to appear on the invoice. Omit node to apply default contact for the client.', min_length=0, max_length=100)
    client_address: str | None = Field(None, title='Client Address', description='Supply a different client address to overide the default. Omit node to apply default address on file.')
    client_country: str | None = Field(None, title='Client Country', description='Client ISO 3166 Country Code. 2 characters long.', min_length=2, max_length=2)
    currency: str = Field(..., title='Currency', description='Currency ISO code must be 3 characters long.', min_length=3, max_length=3)
    exchange_rate: float | None = Field(None, title='Exchange Rate', description='Optional exchange rate (GBP to invoice currency), to a maximum of 4 decimal places.\r\nOnly applied when currency is not GBP. If omitted for a non-GBP currency, the system XE rate is used. Ignored when currency is GBP.')
    discount_percentage: float | None = Field(None, title='Discount Percentage', description='Optional discount percentage applied to invoice total.')
    term_days: int | None = Field(None, title='Term Days', description='Number of days permitted to pay the invoice.')
    language: str | None = Field(None, title='Language', description='ISO 639-1 language  code. Maximum 2 characters long.', min_length=0, max_length=2)
    description: str | None = Field(None, title='Description', description='A brief description of the invoice raised. If not supplied will assume the description of the first invoice item/task. Between 2-35 characters long.', min_length=2, max_length=35)
    payment_term_notes: str | None = Field(None, title='Payment Term Notes', description='Additional invoice terms')
    notes: str | None = Field(None, title='Notes', description='Additional notes to appear on invoice.')
    ec_vat_exempt: bool | None = Field(None, title='Ec Vat Exempt', description='Legacy pre-Brexit EC VAT flag. Do not use.')
    invoice_number: str | None = Field(None, title='Invoice Number', description='If invoice number is not supplied the system will auto-increment. Between 1 and 20 characters long', min_length=1, max_length=20)
    issue_date: str | None = Field(None, title='Issue Date')
    purchase_reference: str | None = Field(None, title='Purchase Reference')
    vat_codes: list[str] | None = Field(None, title='Vat Codes', description='Possible codes: exempt (VAT Exempt), oos (VAT Out of Scope), cisrc (CIS Reverse Charge), nisogs (EU supply of goods), niserv (EU supply of services).')
    tags: list[str] | None = Field(None, title='Tags', description='Provide up to 5 additional project tags')
    item_lines: list[InvoicesCreateLine] | None = Field(None, title='Item Lines', description='Use for products and services priced using the quantity and unit cost model.')
    task_lines: list[InvoicesCreateTask] | None = Field(None, title='Task Lines', description='Use for itemising elements charged on an hourly rate at a fixed amount per hour.')
    recurring: InvoicesCreateScheduleRecurring | None = Field(None, title='Recurring')
    credit_note: InvoicesCreateCreditNote | None = Field(None, title='Credit Note')


class UpdateInvoiceConfig(_Input):
    """Create a new invoice, estimate or recurring invoice template."""
    operation: Literal['update_invoice'] = Field('update_invoice', title='Update Invoice', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., title='Id', description='Invoice id')
    type: str = Field(..., title='Type', description='Type of document. E.g. invoice, estimate, recurring.', min_length=1)
    client_id: int = Field(..., title='Client Id', description='Unique Client ID.')
    client_contact_name: str | None = Field(None, title='Client Contact Name', description='Contact name to appear on the invoice. Omit node to apply default contact for the client.', min_length=0, max_length=100)
    client_address: str | None = Field(None, title='Client Address', description='Supply a different client address to overide the default. Omit node to apply default address on file.')
    client_country: str | None = Field(None, title='Client Country', description='Client ISO 3166 Country Code. 2 characters long.', min_length=2, max_length=2)
    currency: str = Field(..., title='Currency', description='Currency ISO code must be 3 characters long.', min_length=3, max_length=3)
    exchange_rate: float | None = Field(None, title='Exchange Rate', description='Optional exchange rate (GBP to invoice currency), to a maximum of 4 decimal places.\r\nOnly applied when currency is not GBP. If omitted for a non-GBP currency, the system XE rate is used. Ignored when currency is GBP.')
    discount_percentage: float | None = Field(None, title='Discount Percentage', description='Optional discount percentage applied to invoice total.')
    term_days: int | None = Field(None, title='Term Days', description='Number of days permitted to pay the invoice.')
    language: str | None = Field(None, title='Language', description='ISO 639-1 language  code. Maximum 2 characters long.', min_length=0, max_length=2)
    description: str | None = Field(None, title='Description', description='A brief description of the invoice raised. If not supplied will assume the description of the first invoice item/task. Between 2-35 characters long.', min_length=2, max_length=35)
    payment_term_notes: str | None = Field(None, title='Payment Term Notes', description='Additional invoice terms')
    notes: str | None = Field(None, title='Notes', description='Additional notes to appear on invoice.')
    ec_vat_exempt: bool | None = Field(None, title='Ec Vat Exempt', description='Legacy pre-Brexit EC VAT flag. Do not use.')
    invoice_number: str | None = Field(None, title='Invoice Number', description='If invoice number is not supplied the system will auto-increment. Between 1 and 20 characters long', min_length=1, max_length=20)
    issue_date: str | None = Field(None, title='Issue Date')
    purchase_reference: str | None = Field(None, title='Purchase Reference')
    vat_codes: list[str] | None = Field(None, title='Vat Codes', description='Possible codes: exempt (VAT Exempt), oos (VAT Out of Scope), cisrc (CIS Reverse Charge), nisogs (EU supply of goods), niserv (EU supply of services).')
    tags: list[str] | None = Field(None, title='Tags', description='Provide up to 5 additional project tags')
    item_lines: list[InvoicesCreateLine] | None = Field(None, title='Item Lines', description='Use for products and services priced using the quantity and unit cost model.')
    task_lines: list[InvoicesCreateTask] | None = Field(None, title='Task Lines', description='Use for itemising elements charged on an hourly rate at a fixed amount per hour.')
    recurring: InvoicesCreateScheduleRecurring | None = Field(None, title='Recurring')
    credit_note: InvoicesCreateCreditNote | None = Field(None, title='Credit Note')


class GetInvoicePdfConfig(_Input):
    """Retrieve a URL to for an invoice or estimate PDF document."""
    operation: Literal['get_invoice_pdf'] = Field('get_invoice_pdf', title='Get Invoice PDF', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., title='Id', description='Invoice id')


class SendInvoiceConfig(_Input):
    """Send a single invoice, estimate or recurring invoice template."""
    operation: Literal['send_invoice'] = Field('send_invoice', title='Send Invoice by Email or Post', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., title='Id', description='Invoice id')
    by_email: bool | None = Field(None, title='By Email')
    by_snail_mail: bool | None = Field(None, title='By Snail Mail')
    client_contact_id: int | None = Field(None, title='Client Contact Id')


class ListClientPaymentsConfig(_Input):
    """Search for a payment based on specific search parameters."""
    operation: Literal['list_client_payments'] = Field('list_client_payments', title='List Client Payments', json_schema_extra={"ui:hidden": True})
    order_column: str | None = Field(None, title='Order Column', description='Which columns should be used for ordering the record set. E.g. amount, pay_date.')
    order_direction: str | None = Field(None, title='Order Direction', description='Order direction. Ascending (asc) or Descending (desc).')
    include_deleted: bool | None = Field(None, title='Include Deleted', description='Show previously deleted payments. Default is false.')
    client_id: int | None = Field(None, title='Client Id', description='Show all payments for a given Client ID.')
    client_name: str | None = Field(None, title='Client Name', description='Whole or part of client company name.', min_length=0, max_length=100)
    type: str | None = Field(None, title='Type', description='allocated/unallocated.')
    date_from: str | None = Field(None, title='Date From', description='Payment date range from')
    date_to: str | None = Field(None, title='Date To', description='Payment date range to')
    amount_from: str | None = Field(None, title='Amount From', description='Amount range from')
    amount_to: str | None = Field(None, title='Amount To', description='Amount range to')
    currency: str | None = Field(None, title='Currency', description='Currency ISO code must be 3 characters long.', min_length=3, max_length=3)
    offset: int | None = Field(None, title='Offset', description='Page offset. Zero (0) would show results from the beginning of the record set. Offset can be used for paging functions.', ge=0, le=1000000)
    limit: int | None = Field(None, title='Limit', description='How many records would you like the API to return.', ge=0, le=100)


class GetClientPaymentConfig(_Input):
    """Retrieve a payment record."""
    operation: Literal['get_client_payment'] = Field('get_client_payment', title='Get Client Payment', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., title='Id')


class CreateClientPaymentConfig(_Input):
    """Create a new payment record."""
    operation: Literal['create_client_payment'] = Field('create_client_payment', title='Create Client Payment', json_schema_extra={"ui:hidden": True})
    type: str = Field(..., title='Type', description='payment/credit - Payments are attributed to an invoice. Credits are used for holding funds on a client or supplier account.', min_length=1)
    date: str = Field(..., title='Date', description='Date the payment was made.', min_length=1)
    invoice_id: int | None = Field(None, title='Invoice Id', description='Provide an invoice ID if type is payment.')
    client_id: int = Field(..., title='Client Id', description='Client ID for which the payment will be linked to.')
    amount: float = Field(..., title='Amount', description='Total amount of payment.')
    currency: str = Field(..., title='Currency', description='Payment currency.', min_length=3, max_length=3)
    nominal_code: int | None = Field(None, title='Nominal Code', description='Missing bank nominal code.')
    apply_credit: bool | None = Field(None, title='Apply Credit', description='When set to true we will first try to pay the invoice from available credit on the client account.')
    send_confirmation: bool | None = Field(None, title='Send Confirmation', description='When set to true we will send an email notification to the client.')
    notes: str | None = Field(None, title='Notes', description='Additional notes relating to this payment.', min_length=0, max_length=100)


class ListPurchasesConfig(_Input):
    """Search for purchases using a specific set of search parameters."""
    operation: Literal['list_purchases'] = Field('list_purchases', title='List Purchases', json_schema_extra={"ui:hidden": True})
    order_column: str | None = Field(None, title='Order Column', description='Which columns should be used for ordering the record set. E.g. receipt_number, receipt_date, supplier, gross_total.')
    order_direction: str | None = Field(None, title='Order Direction', description='Order direction. Ascending (asc) or Descending (desc).')
    include_deleted: bool | None = Field(None, title='Include Deleted', description='Show previously deleted invoices. Default is false.')
    tag_name: str | None = Field(None, title='Tag Name', description='Project tag name')
    supplier_name: str | None = Field(None, title='Supplier Name', description='Search by supplier name', min_length=0, max_length=100)
    supplier_id: int | None = Field(None, title='Supplier Id', description='Search by supplier id')
    supplier_reference: str | None = Field(None, title='Supplier Reference', description='Search by supplier reference', min_length=0, max_length=30)
    receipt_number: str | None = Field(None, title='Receipt Number', description='Search by receipt number', min_length=0, max_length=20)
    item_desc: str | None = Field(None, title='Item Desc', description='Search by item description', min_length=0, max_length=35)
    date_from: str | None = Field(None, title='Date From', description='Issued date range from (yyyy-mm-dd)')
    date_to: str | None = Field(None, title='Date To', description='Issued date range to (yyyy-mm-dd)')
    amount_from: str | None = Field(None, title='Amount From', description='Amount range from')
    amount_to: str | None = Field(None, title='Amount To', description='Amount range to')
    currency: str | None = Field(None, title='Currency', description='Currency ISO code. Maximum 3 characters long.', min_length=3, max_length=3)
    status: str | None = Field(None, title='Status', description='Invoice status. E.g. draft, sent, disputed, paidpart, paidfull, active, unpaid, deleted, aged, paused, agreed, declined')
    has_receipts: bool | None = Field(None, title='Has Receipts', description='set this to know purchases with or without receipts attached')
    offset: int | None = Field(None, title='Offset', description='Page offset. Zero (0) would show results from the beginning of the record set. Offset can be used for paging functions.', ge=0, le=1000000)
    limit: int | None = Field(None, title='Limit', description='How many records would you like the API to return.', ge=0, le=100)


class GetPurchaseConfig(_Input):
    """Retrieve a single purchase."""
    operation: Literal['get_purchase'] = Field('get_purchase', title='Get Purchase', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., title='Id', description='Purchase id')


class PurchaseCreateLine(_Input):
    nominal_code: int | None = Field(None, title='Nominal Code', description='Nominal Code. Between 1 and 9999')
    description: str = Field(..., title='Description', description='Item description', min_length=1)
    sub_total: float = Field(..., title='Sub Total', description='Item sub_total')
    vat_rate: float = Field(..., title='Vat Rate', description='The VAT rate to be applied. For non-VAT Reg suppliers use 0.00', ge=0, le=2147483647)
    vat_amount: float | None = Field(None, title='Vat Amount', description='Overrides the VAT Rate for specific VAT amounts. If missing will be calculated from the rate.')


class PurchasePaymentData(_Input):
    date: str = Field(..., title='Date', description='Paid date', min_length=1)
    nominal_code: int | None = Field(None, title='Nominal Code', description='Nominal Code. Between 1200 and 1299')
    amount: float = Field(..., title='Amount', description='Pay amount')
    notes: str | None = Field(None, title='Notes', description='Optional payment notes container.', min_length=0, max_length=100)


class CreatePurchaseConfig(_Input):
    """Create a new purchase."""
    operation: Literal['create_purchase'] = Field('create_purchase', title='Create Purchase', json_schema_extra={"ui:hidden": True})
    supplier_id: int = Field(..., title='Supplier Id', description='Supplier id')
    receipt_date: str = Field(..., title='Receipt Date', description='Receipt date', min_length=1)
    currency: str = Field(..., title='Currency', description='Currency ISO code. Maximum 3 characters long.', min_length=3, max_length=3)
    exchange_rate: float | None = Field(None, title='Exchange Rate', description='Optional exchange rate (GBP to purchase currency), to a maximum of 4 decimal places.\r\nOnly applied when currency is not GBP. If omitted for a non-GBP currency, the system XE rate is used. Ignored when currency is GBP.')
    description: str | None = Field(None, title='Description', description='Description', min_length=0, max_length=35)
    vat_codes: list[str] | None = Field(None, title='Vat Codes', description='Possible codes: exempt (VAT Exempt), oos (VAT Out of Scope), cisrc (CIS Reverse Charge), nisogs (EU supply of goods), servrc, postgoods.')
    supplier_reference: str | None = Field(None, title='Supplier Reference', description='Search by supplier reference', min_length=0, max_length=30)
    term_days: int | None = Field(None, title='Term Days', description='Number of days permitted to pay the purchase.')
    item_lines: list[PurchaseCreateLine] = Field(..., title='Item Lines')
    payment: PurchasePaymentData | None = Field(None, title='Payment')
    tags: list[str] | None = Field(None, title='Tags', description='Provide up to 5 additional project tags')


class ListBankAccountsConfig(_Input):
    """Returns a list of bank accounts with optional nominal code and type filtering."""
    operation: Literal['list_bank_accounts'] = Field('list_bank_accounts', title='List Bank Accounts', json_schema_extra={"ui:hidden": True})
    nominal_code: int | None = Field(None, title='Nominal Code', description='Nominal code')
    types: list[str] | None = Field(None, title='Types', description='List of account types to be returned. E.g. current, petty, buildingsoc, loan, merchant, equity, creditcard, reserve')
    include_hidden: bool | None = Field(None, title='Include Hidden', description='Show hidden bank accounts. Default is false.')
    include_consents: bool | None = Field(None, title='Include Consents', description='Show Open Banking consents. Default is false.')


class GetChartOfAccountsConfig(_Input):
    """Retreives a chart of nominal accounts."""
    operation: Literal['get_chart_of_accounts'] = Field('get_chart_of_accounts', title='Get Chart Of Accounts', json_schema_extra={"ui:hidden": True})
    nominal_code_start: int | None = Field(None, title='Nominal Code Start', description='The nominal code range from where you would like to start. Default is 1', ge=1, le=9999)
    nominal_code_end: int | None = Field(None, title='Nominal Code End', description='The nominal code range to where you would like to end. Default is 9999', ge=1, le=9999)
    date_from: str | None = Field(None, title='Date From', description='From date. If excluded returns all transactions from beginning of time.')
    date_to: str | None = Field(None, title='Date To', description='To date. If excluded returns all transactions to the current date.')
    exclude_zero_balance_ledgers: bool | None = Field(None, title='Exclude Zero Balance Ledgers', description='Excludes any ledgers that hold a zero balance for the given date range. If excluded will assume to be true.')


class OnNewClientConfig(PollTriggerConfigBase):
    """Poll all clients ordered by the documented created_date column.

    Existing records become the baseline when armed. Edits do not fire.
    """
    operation: Literal["on_new_client"] = Field("on_new_client", title="On New Client",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})


class OnNewSupplierConfig(PollTriggerConfigBase):
    """Poll all suppliers ordered by the documented created_date column.

    Existing records become the baseline when armed. Edits do not fire.
    """
    operation: Literal["on_new_supplier"] = Field("on_new_supplier", title="On New Supplier",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})


OPERATIONS = {'get_account': {'method': 'GET',
                 'path': '/account/me',
                 'query': [],
                 'body': [],
                 'contract_operation': 'AccountMe'},
 'list_clients': {'method': 'GET',
                  'path': '/clients',
                  'query': ['order_column',
                            'order_direction',
                            'include_deleted',
                            'company_name',
                            'first_name',
                            'surname',
                            'email',
                            'account_reference',
                            'telephone',
                            'include_total_invoiced',
                            'include_total_paid',
                            'include_total_credits',
                            'offset',
                            'limit'],
                  'body': [],
                  'contract_operation': 'ClientSearch'},
 'get_client': {'method': 'GET',
                'path': '/clients/{id}',
                'query': ['contacts', 'financials'],
                'body': [],
                'contract_operation': 'ClientGet'},
 'create_client': {'method': 'POST',
                   'path': '/clients',
                   'query': [],
                   'body': ['company_name',
                            'company_number',
                            'account_reference',
                            'address_line1',
                            'address_line2',
                            'address_line3',
                            'town',
                            'country_iso',
                            'post_code',
                            'vat_number',
                            'go_cardless_mandate',
                            'allow_attach_pdf',
                            'default_send_method',
                            'default_currency',
                            'default_term',
                            'trading_style',
                            'payment_restrictions'],
                   'contract_operation': 'ClientCreate'},
 'update_client': {'method': 'PUT',
                   'path': '/clients/{id}',
                   'query': [],
                   'body': ['company_name',
                            'company_number',
                            'account_reference',
                            'address_line1',
                            'address_line2',
                            'address_line3',
                            'town',
                            'country_iso',
                            'post_code',
                            'vat_number',
                            'go_cardless_mandate',
                            'allow_attach_pdf',
                            'default_send_method',
                            'default_currency',
                            'default_term',
                            'trading_style',
                            'payment_restrictions'],
                   'contract_operation': 'ClientUpdate'},
 'list_suppliers': {'method': 'GET',
                    'path': '/suppliers',
                    'query': ['order_column',
                              'order_direction',
                              'include_deleted',
                              'company_name',
                              'first_name',
                              'surname',
                              'email',
                              'supplier_reference',
                              'telephone',
                              'include_total_invoiced',
                              'include_total_paid',
                              'include_total_credits',
                              'offset',
                              'limit'],
                    'body': [],
                    'contract_operation': 'SupplierSearch'},
 'get_supplier': {'method': 'GET',
                  'path': '/suppliers/{id}',
                  'query': [],
                  'body': [],
                  'contract_operation': 'SupplierGet'},
 'create_supplier': {'method': 'POST',
                     'path': '/suppliers',
                     'query': [],
                     'body': ['company_name',
                              'contact_first_name',
                              'contact_surname',
                              'contact_telephone',
                              'contact_email',
                              'company_number',
                              'supplier_reference',
                              'address_line1',
                              'address_line2',
                              'address_line3',
                              'town',
                              'country_iso',
                              'post_code',
                              'website',
                              'vat_number',
                              'default_currency',
                              'default_term',
                              'default_vatrate',
                              'default_nominalcode'],
                     'contract_operation': 'SupplierCreate'},
 'update_supplier': {'method': 'PUT',
                     'path': '/suppliers/{id}',
                     'query': [],
                     'body': ['company_name',
                              'company_number',
                              'supplier_reference',
                              'address_line1',
                              'address_line2',
                              'address_line3',
                              'town',
                              'country_iso',
                              'post_code',
                              'website',
                              'vat_number',
                              'default_currency',
                              'default_term',
                              'default_vatrate',
                              'default_nominalcode'],
                     'contract_operation': 'SupplierUpdate'},
 'list_invoices': {'method': 'GET',
                   'path': '/invoices',
                   'query': ['order_column',
                             'order_direction',
                             'type',
                             'tag_name',
                             'include_deleted',
                             'client_id',
                             'client_contact_name',
                             'recurring_profile_id',
                             'invoice_number',
                             'item_name',
                             'item_desc',
                             'date_from',
                             'date_to',
                             'amount_from',
                             'amount_to',
                             'currency',
                             'status',
                             'purchase_ref',
                             'offset',
                             'limit'],
                   'body': [],
                   'contract_operation': 'InvoicesSearch'},
 'get_invoice': {'method': 'GET',
                 'path': '/invoices/{id}',
                 'query': [],
                 'body': [],
                 'contract_operation': 'InvoicesGet'},
 'create_invoice': {'method': 'POST',
                    'path': '/invoices',
                    'query': [],
                    'body': ['type',
                             'client_id',
                             'client_contact_name',
                             'client_address',
                             'client_country',
                             'currency',
                             'exchange_rate',
                             'discount_percentage',
                             'term_days',
                             'language',
                             'description',
                             'payment_term_notes',
                             'notes',
                             'ec_vat_exempt',
                             'invoice_number',
                             'issue_date',
                             'purchase_reference',
                             'vat_codes',
                             'tags',
                             'item_lines',
                             'task_lines',
                             'recurring',
                             'credit_note'],
                    'contract_operation': 'InvoicesPost'},
 'update_invoice': {'method': 'PUT',
                    'path': '/invoices/{id}',
                    'query': [],
                    'body': ['type',
                             'client_id',
                             'client_contact_name',
                             'client_address',
                             'client_country',
                             'currency',
                             'exchange_rate',
                             'discount_percentage',
                             'term_days',
                             'language',
                             'description',
                             'payment_term_notes',
                             'notes',
                             'ec_vat_exempt',
                             'invoice_number',
                             'issue_date',
                             'purchase_reference',
                             'vat_codes',
                             'tags',
                             'item_lines',
                             'task_lines',
                             'recurring',
                             'credit_note'],
                    'contract_operation': 'InvoicesPut'},
 'get_invoice_pdf': {'method': 'GET',
                     'path': '/invoices/{id}/get-pdf',
                     'query': [],
                     'body': [],
                     'contract_operation': 'InvoiceGetPdf'},
 'send_invoice': {'method': 'POST',
                  'path': '/invoices/{id}/send',
                  'query': [],
                  'body': ['by_email', 'by_snail_mail', 'client_contact_id'],
                  'contract_operation': 'InvoiceSendSingle'},
 'list_client_payments': {'method': 'GET',
                          'path': '/client_payments',
                          'query': ['order_column',
                                    'order_direction',
                                    'include_deleted',
                                    'client_id',
                                    'client_name',
                                    'type',
                                    'date_from',
                                    'date_to',
                                    'amount_from',
                                    'amount_to',
                                    'currency',
                                    'offset',
                                    'limit'],
                          'body': [],
                          'contract_operation': 'PaymentsClientSearch'},
 'get_client_payment': {'method': 'GET',
                        'path': '/client_payments/{id}',
                        'query': [],
                        'body': [],
                        'contract_operation': 'PaymentsClientGet'},
 'create_client_payment': {'method': 'POST',
                           'path': '/client_payments',
                           'query': [],
                           'body': ['type',
                                    'date',
                                    'invoice_id',
                                    'client_id',
                                    'amount',
                                    'currency',
                                    'nominal_code',
                                    'apply_credit',
                                    'send_confirmation',
                                    'notes'],
                           'contract_operation': 'PaymentsClientPost'},
 'list_purchases': {'method': 'GET',
                    'path': '/purchases',
                    'query': ['order_column',
                              'order_direction',
                              'include_deleted',
                              'tag_name',
                              'supplier_name',
                              'supplier_id',
                              'supplier_reference',
                              'receipt_number',
                              'item_desc',
                              'date_from',
                              'date_to',
                              'amount_from',
                              'amount_to',
                              'currency',
                              'status',
                              'has_receipts',
                              'offset',
                              'limit'],
                    'body': [],
                    'contract_operation': 'PurchasesSearch'},
 'get_purchase': {'method': 'GET',
                  'path': '/purchases/{id}',
                  'query': [],
                  'body': [],
                  'contract_operation': 'PurchasesGet'},
 'create_purchase': {'method': 'POST',
                     'path': '/purchases',
                     'query': [],
                     'body': ['supplier_id',
                              'receipt_date',
                              'currency',
                              'exchange_rate',
                              'description',
                              'vat_codes',
                              'supplier_reference',
                              'term_days',
                              'item_lines',
                              'payment',
                              'tags'],
                     'contract_operation': 'PurchasesPost'},
 'list_bank_accounts': {'method': 'GET',
                        'path': '/bank_accounts',
                        'query': ['nominal_code', 'types', 'include_hidden', 'include_consents'],
                        'body': [],
                        'contract_operation': 'BanksGetAccounts'},
 'get_chart_of_accounts': {'method': 'GET',
                           'path': '/reports/chart-of-accounts',
                           'query': ['nominal_code_start',
                                     'nominal_code_end',
                                     'date_from',
                                     'date_to',
                                     'exclude_zero_balance_ledgers'],
                           'body': [],
                           'contract_operation': 'ReportsChartOfAccounts'},
 'on_new_client': {'method': 'GET',
                   'path': '/clients',
                   'query': [],
                   'body': [],
                   'contract_operation': 'ClientSearch'},
 'on_new_supplier': {'method': 'GET',
                     'path': '/suppliers',
                     'query': [],
                     'body': [],
                     'contract_operation': 'SupplierSearch'}}

QuickFileOperation = Annotated[Union[GetAccountConfig, ListClientsConfig, GetClientConfig, CreateClientConfig, UpdateClientConfig, ListSuppliersConfig, GetSupplierConfig, CreateSupplierConfig, UpdateSupplierConfig, ListInvoicesConfig, GetInvoiceConfig, CreateInvoiceConfig, UpdateInvoiceConfig, GetInvoicePdfConfig, SendInvoiceConfig, ListClientPaymentsConfig, GetClientPaymentConfig, CreateClientPaymentConfig, ListPurchasesConfig, GetPurchaseConfig, CreatePurchaseConfig, ListBankAccountsConfig, GetChartOfAccountsConfig, OnNewClientConfig, OnNewSupplierConfig], Field(discriminator="operation")]


class QuickFileNodeConfig(NodeConfig[QuickFileOperation, QuickFileTokenCredential]):
    pass


class QuickFileNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-quickfile"
    connection_evidence = ConnectionEvidence(
        noun="QuickFile business", identity_operation="get_account",
        identity_keys=("BusinessName", "AccNumber"),
    )

    @classmethod
    def get_config_model(cls):
        return QuickFileNodeConfig

    @staticmethod
    async def _request(token, method, path, *, params=None, body=None):
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                params=params, json=body)
        if response.is_error:
            # Keep the provider's rejection verbatim for connection evidence.
            raise ValueError(f"QuickFile API {response.status_code}: {response.text}")
        if response.is_redirect:
            raise ValueError("QuickFile returned an unexpected redirect")
        return response.json() if response.content else {}

    async def _poll(self, token, path):
        # Never follow the provider's paging URL: keep the token on the fixed API host.
        items = []
        for offset in range(0, 10000, 100):
            data = await self._request(token, "GET", path, params={
                "order_column": "created_date", "order_direction": "desc",
                "include_deleted": False, "offset": offset, "limit": 100,
            })
            if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                raise ValueError("QuickFile did not return a paged record list")
            rows = data["data"]
            if any(not isinstance(row, dict) or not isinstance(row.get("id"), int) for row in rows):
                raise ValueError("QuickFile returned a record without its numeric ID")
            items.extend(rows)
            if len(rows) < 100:
                break
        else:
            # Do not mutate the baseline after an incomplete scan.
            raise ValueError("QuickFile polling is limited to fewer than 10,000 records")
        fresh = await self._filter_unseen(items, lambda row: str(row["id"]))
        return {"status": "success", "operation": self.config.config.operation,
                "data": fresh, "new_record_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation", "").startswith("on_new_"):
            return bool(output.get("new_record_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        operation = output.get("operation", "")
        if operation not in {"on_new_client", "on_new_supplier"}:
            return super().resolve_agent_event(output)
        rows = output.get("data")
        if not isinstance(rows, list) or not rows:
            return None
        kind = "client" if operation == "on_new_client" else "supplier"
        lines = [f"QuickFile: {len(rows)} new {kind}(s)"]
        for row in rows[:50]:
            lines.append(f"{row.get('company_name') or kind.title()} — ID {row['id']}, "
                         f"created {row.get('created_date') or 'time unavailable'}. "
                         f"To act, use get_{kind} or update_{kind} with id={row['id']}.")
        if len(rows) > 50:
            lines.append("Additional records are available in the trigger output.")
        return {"text": "\n".join(lines), "conversation_key": None,
                "title": f"New QuickFile {kind}s"}

    async def execute(self, inputs):
        if not isinstance(self.config, QuickFileNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a QuickFile personal bearer token")
        config = self.config.config
        spec = OPERATIONS[config.operation]
        token = self.config.credentials.api_token
        if config.operation.startswith("on_new_"):
            return await self._poll(token, spec["path"])
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = spec["path"]
        if "{id}" in path:
            path = path.replace("{id}", str(values.pop("id")))
        params = {key: values[key] for key in spec["query"] if key in values}
        body = {key: values[key] for key in spec["body"] if key in values}
        result = await self._request(token, spec["method"], path,
            params=params or None, body=body if spec["method"] in {"POST", "PUT"} else None)
        return {"status": "success", "operation": config.operation, "data": result}
