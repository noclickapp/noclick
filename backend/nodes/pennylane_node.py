"""Pennylane Company API v2, pinned to the provider's published 2.0 contract.

Company token setup: https://pennylane.readme.io/docs/generating-my-api-token
Every operation performs exactly one provider request; list operations return
one cursor page. Invoice creation creates a draft with existing product lines.
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
from nodes.scopes.pennylane import PENNYLANE_SCOPES
from utils.ssrf import guarded_async_client


class PennylaneAPIToken(BaseModel):
    model_config = ConfigDict(title="Pennylane API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://pennylane.readme.io/docs/generating-my-api-token",
            "x-credential-instructions": "In Pennylane, go to Settings > Connectivity > Developers and generate a Company API V2 token (Essential plan or higher, company admin access). Select read and write permissions for the resources you automate: customers, suppliers, products, customer invoices, supplier invoices, bank accounts and transactions. Paste the token here. NoClick sends it as a Bearer token to app.pennylane.com and verifies the company with /me. Replace the token here when it expires or is revoked. A Firm token also needs the company ID below."
        })
    credential_type: Literal["pennylane_api_token"] = Field("pennylane_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})
    company_id: str | None = Field(None, pattern=r"^[0-9]+$", title="Company ID", description="Required only for a Firm token; sent as X-Company-Id. Leave empty for a Company token.")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() or ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("Paste only the API token, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class PennylaneAddress(_Input):
    address: str
    postal_code: str
    city: str
    country_alpha2: str = Field(..., description="Two-letter country code, for example FR")


class PennylaneProductLine(_Input):
    product_id: int = Field(..., description="Existing Pennylane product ID")
    quantity: float = Field(..., description="Number of items; product supplies price, unit and VAT")



class PennylaneGetMeConfig(_Input):
    'User Profile'
    operation: Literal['get_me'] = Field('get_me', json_schema_extra={"ui:hidden": True})

class PennylaneListCustomersConfig(_Input):
    'List customers (company and individual)'
    operation: Literal['list_customers'] = Field('list_customers', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, max_length=8192, description="Cursor for pagination. Use this to fetch the next set of results.\nThe cursor is an opaque string returned in the previous response's metadata.\nLeave empty for the first request.\n")
    limit: int = Field(20, ge=1, le=100, description='Number of items to return per request.\nDefaults to 20 if not specified.\nMust be between 1 and 100.\n')
    filter: str | None = Field(None, max_length=8192, description='You can choose to filter items on specific fields.\nAvailable fields and values:\n- `id`: `lt`, `lteq`, `gt`, `gteq`, `eq`, `not_eq`, `in`, `not_in`\n- `customer_type`: `eq`, `not_eq`\n- `ledger_account_id`: `eq`, `not_eq`\n- `name`: `start_with`, `eq`\n- `external_reference`: `start_with`, `eq`, `not_eq`, `in`, `not_in`\n- `reg_no`: `eq`, `not_eq`, `in`, `not_in`\n- `emails`: `in`\n')
    sort: str | None = Field(None, max_length=8192, description='You can choose to sort items on specific attributes\nSort field may be prefixed with `-` for descending order.\nExample : `id` will sort by ascending order, `-id` will sort by descending order.\nAvailable fields : `id`\n')

class PennylaneGetCustomerConfig(_Input):
    'Retrieve a customer'
    operation: Literal['get_customer'] = Field('get_customer', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='Customer identifier')

class PennylaneListSuppliersConfig(_Input):
    'List suppliers'
    operation: Literal['list_suppliers'] = Field('list_suppliers', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, max_length=8192, description="Cursor for pagination. Use this to fetch the next set of results.\nThe cursor is an opaque string returned in the previous response's metadata.\nLeave empty for the first request.\n")
    limit: int = Field(20, ge=1, le=100, description='Number of items to return per request.\nDefaults to 20 if not specified.\nMust be between 1 and 100.\n')
    filter: str | None = Field(None, max_length=8192, description='You can choose to filter items on specific fields.\nAvailable fields and values:\n- `id`: `lt`, `lteq`, `gt`, `gteq`, `eq`, `not_eq`, `in`, `not_in`\n- `ledger_account_id`: `eq`, `not_eq`\n- `name`: `start_with`\n- `external_reference`: `eq`, `not_eq`, `in`, `not_in`\n- `emails`: `in`\n')
    sort: str | None = Field(None, max_length=8192, description='You can choose to sort items on specific attributes\nSort field may be prefixed with `-` for descending order.\nExample : `id` will sort by ascending order, `-id` will sort by descending order.\nAvailable fields : `id`\n')

class PennylaneGetSupplierConfig(_Input):
    'Retrieve a supplier'
    operation: Literal['get_supplier'] = Field('get_supplier', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='Supplier identifier')

class PennylaneListProductsConfig(_Input):
    'List products'
    operation: Literal['list_products'] = Field('list_products', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, max_length=8192, description="Cursor for pagination. Use this to fetch the next set of results.\nThe cursor is an opaque string returned in the previous response's metadata.\nLeave empty for the first request.\n")
    limit: int = Field(20, ge=1, le=100, description='Number of items to return per request.\nDefaults to 20 if not specified.\nMust be between 1 and 100.\n')
    filter: str | None = Field(None, max_length=8192, description='You can choose to filter items on specific fields.\nAvailable fields and values:\n- `id` : `lt`, `lteq`, `gt`, `gteq`, `eq`, `not_eq`, `in`, `not_in`\n- `label` : `eq`, `in`\n- `reference` : `eq`, `in`\n- `external_reference` : `eq`, `not_eq`, `in`, `not_in`\n')
    sort: str | None = Field(None, max_length=8192, description='You can choose to sort items on specific attributes\nSort field may be prefixed with `-` for descending order.\nExample : `id` will sort by ascending order, `-id` will sort by descending order.\nAvailable fields : `id`\n')

class PennylaneGetProductConfig(_Input):
    'Retrieve a product'
    operation: Literal['get_product'] = Field('get_product', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='Pennylane ID')

class PennylaneListCustomerInvoicesConfig(_Input):
    'List customer invoices'
    operation: Literal['list_customer_invoices'] = Field('list_customer_invoices', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, max_length=8192, description="Cursor for pagination. Use this to fetch the next set of results.\nThe cursor is an opaque string returned in the previous response's metadata.\nLeave empty for the first request.\n")
    limit: int = Field(20, ge=1, le=100, description='Number of items to return per request.\nDefaults to 20 if not specified.\nMust be between 1 and 100.\n')
    filter: str | None = Field(None, max_length=8192, description='You can choose to filter items on specific fields.\nAvailable fields and values:\n- `id`, `date`, `customer_id`, `billing_subscription_id`, `quote_id`: `lt`, `lteq`, `gt`, `gteq`, `eq`, `not_eq`, `in`, `not_in`\n- `invoice_number`: `eq`, `not_eq`, `in`, `not_in`\n- `draft`: `eq` (boolean)\n- `credit_note`: `eq` (boolean)\n- `external_reference`: `eq`\n- `flow_id`: `eq`, `not_eq`, `in`, `not_in`\n- `category_id`: `in`\n')
    sort: str | None = Field(None, max_length=8192, description='You can choose to sort items on specific attributes\nSort field may be prefixed with `-` for descending order.\nExample : `id` will sort by ascending order, `-id` will sort by descending order.\nAvailable fields : `id`, `date`\n')
    include: str | None = Field(None, max_length=8192, description='You can choose to include additional related resources in the response.\nWhen specified, related resources will be returned in a separate `included` section.\nAvailable includes: `invoice_lines`\n\n⚠️ **Warning**: This feature is currently experimental and may change or be removed in future releases.\nWe recommend using it with caution in production environments.\n')

class PennylaneGetCustomerInvoiceConfig(_Input):
    'Retrieve a customer invoice'
    operation: Literal['get_customer_invoice'] = Field('get_customer_invoice', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='The unique identifier of the customer invoice')

class PennylaneListSupplierInvoicesConfig(_Input):
    'List supplier invoices'
    operation: Literal['list_supplier_invoices'] = Field('list_supplier_invoices', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, max_length=8192, description="Cursor for pagination. Use this to fetch the next set of results.\nThe cursor is an opaque string returned in the previous response's metadata.\nLeave empty for the first request.\n")
    limit: int = Field(20, ge=1, le=100, description='Number of items to return per request.\nDefaults to 20 if not specified.\nMust be between 1 and 100.\n')
    filter: str | None = Field(None, max_length=8192, description='You can choose to filter items on specific fields.\nAvailable fields and values:\n- `id`: `lt`, `lteq`, `gt`, `gteq`, `eq`, `not_eq`, `in`, `not_in`\n- `supplier_id`: `lt`, `lteq`, `gt`, `gteq`, `eq`, `not_eq`, `in`, `not_in`\n- `invoice_number`: `eq`, `not_eq`, `in`, `not_in`\n- `date`: `lt`, `lteq`, `gt`, `gteq`, `eq`, `not_eq`, `in`, `not_in`\n- `category_id`: `in`\n- `external_reference`: `eq`, `not_eq`, `in`, `not_in`\n- `payment_status`: `eq`, `not_eq`, `in`, `not_in`\n- `flow_id`: `eq`, `not_eq`, `in`, `not_in`\n- `electronic_billing_address`: `eq`, `not_eq`, `in`, `not_in`\n')
    sort: str | None = Field(None, max_length=8192, description='You can choose to sort items on specific attributes\nSort field may be prefixed with `-` for descending order.\nExample : `id` will sort by ascending order, `-id` will sort by descending order.\nAvailable fields : `id`, `date`\n')

class PennylaneGetSupplierInvoiceConfig(_Input):
    'Retrieve a supplier invoice'
    operation: Literal['get_supplier_invoice'] = Field('get_supplier_invoice', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='Supplier invoice identifier')

class PennylaneListTransactionsConfig(_Input):
    'List transactions'
    operation: Literal['list_transactions'] = Field('list_transactions', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, max_length=8192, description="Cursor for pagination. Use this to fetch the next set of results.\nThe cursor is an opaque string returned in the previous response's metadata.\nLeave empty for the first request.\n")
    limit: int = Field(20, ge=1, le=100, description='Number of items to return per request.\nDefaults to 20 if not specified.\nMust be between 1 and 100.\n')
    filter: str | None = Field(None, max_length=8192, description='You can choose to filter items on specific fields.\nAvailable fields and values:\n- `id`: `eq`, `not_eq`, `in`, `not_in`\n- `bank_account_id`: `eq`, `not_eq`, `in`, `not_in`\n- `journal_id`: `eq`, `not_eq`, `in`, `not_in`\n- `date`: `eq`, `not_eq`, `gt`, `lt`, `lteq`, `gteq`\n')
    sort: str | None = Field(None, max_length=8192, description='You can choose to sort items on specific attributes\nSort field may be prefixed with `-` for descending order.\nExample : `id` will sort by ascending order, `-id` will sort by descending order.\nAvailable fields : `id`\n')

class PennylaneGetTransactionConfig(_Input):
    'Retrieve a transaction'
    operation: Literal['get_transaction'] = Field('get_transaction', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='Pennylane ID')

class PennylaneListBankAccountsConfig(_Input):
    'List bank accounts'
    operation: Literal['list_bank_accounts'] = Field('list_bank_accounts', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, max_length=8192, description="Cursor for pagination. Use this to fetch the next set of results.\nThe cursor is an opaque string returned in the previous response's metadata.\nLeave empty for the first request.\n")
    limit: int = Field(20, ge=1, le=100, description='Number of items to return per request.\nDefaults to 20 if not specified.\nMust be between 1 and 100.\n')
    sort: str | None = Field(None, max_length=8192, description='You can choose to sort items on specific attributes\nSort field may be prefixed with `-` for descending order.\nExample : `id` will sort by ascending order, `-id` will sort by descending order.\nAvailable fields : `id`\n')

class PennylaneCreateCompanyCustomerConfig(_Input):
    'Create a company customer'
    operation: Literal['create_company_customer'] = Field('create_company_customer', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='Name')
    vat_number: str | None = Field(None, description='Vat number')
    reg_no: str | None = Field(None, description='Reg no')
    phone: str | None = Field(None, description='Phone')
    billing_address: PennylaneAddress = Field(..., description='Billing address')
    delivery_address: PennylaneAddress | None = Field(None, description='Delivery address')
    payment_conditions: Literal['upon_receipt', 'custom', '7_days', '15_days', '30_days', '30_days_end_of_month', '45_days', '45_days_end_of_month', '60_days'] | None = Field(None, description="Note that the `custom` option is only used on Pennylane's web app to avoid pre-filling the deadline when creating an invoice. On the API it has no effect and you will still have to provide a deadline when creating an invoice.")
    billing_iban: str | None = Field(None, description='Billing iban')
    recipient: str | None = Field(None, description='The name of the person to whom the invoice is addressed')
    reference: str | None = Field(None, description='Reference')
    notes: str | None = Field(None, description='Notes')
    emails: list[str] | None = Field(None, description='Emails')
    external_reference: str | None = Field(None, description='You can use your own unique value when creating the customer. If not provided, Pennylane will pick one for you. Value must be unique')
    billing_language: Literal['fr_FR', 'en_GB', 'de_DE', 'es_ES'] | None = Field(None, description='The language in which the customer will receive invoices. Default is `fr_FR`')

class PennylaneUpdateCompanyCustomerConfig(_Input):
    'Update a company customer'
    operation: Literal['update_company_customer'] = Field('update_company_customer', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='Company customer identifier')
    name: str | None = Field(None, description='Name')
    vat_number: str | None = Field(None, description='Vat number')
    reg_no: str | None = Field(None, description='Reg no')
    phone: str | None = Field(None, description='Phone')
    billing_address: PennylaneAddress | None = Field(None, description='Billing address')
    delivery_address: PennylaneAddress | None = Field(None, description='Delivery address')
    payment_conditions: Literal['upon_receipt', 'custom', '7_days', '15_days', '30_days', '30_days_end_of_month', '45_days', '45_days_end_of_month', '60_days'] | None = Field(None, description="Note that the `custom` option is only used on Pennylane's web app to avoid pre-filling the deadline when creating an invoice. On the API it has no effect and you will still have to provide a deadline when creating an invoice.")
    billing_iban: str | None = Field(None, description='Billing iban')
    recipient: str | None = Field(None, description='The name of the person to whom the invoice is addressed')
    reference: str | None = Field(None, description='Reference')
    notes: str | None = Field(None, description='Notes')
    emails: list[str] | None = Field(None, description='Emails')
    external_reference: str | None = Field(None, description='You can use your own unique value when creating the customer. If not provided, Pennylane will pick one for you. Value must be unique')
    billing_language: Literal['fr_FR', 'en_GB', 'de_DE', 'es_ES'] | None = Field(None, description='The language in which the customer will receive invoices. Default is `fr_FR`')

class PennylaneCreateIndividualCustomerConfig(_Input):
    'Create an individual customer'
    operation: Literal['create_individual_customer'] = Field('create_individual_customer', json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., max_length=1000, description='First name')
    last_name: str = Field(..., max_length=1000, description='Last name')
    phone: str | None = Field(None, description='Phone')
    billing_address: PennylaneAddress = Field(..., description='Billing address')
    delivery_address: PennylaneAddress | None = Field(None, description='Delivery address')
    payment_conditions: Literal['upon_receipt', 'custom', '7_days', '15_days', '30_days', '30_days_end_of_month', '45_days', '45_days_end_of_month', '60_days'] | None = Field(None, description="Note that the `custom` option is only used on Pennylane's web app to avoid pre-filling the deadline when creating an invoice. On the API it has no effect and you will still have to provide a deadline when creating an invoice.")
    billing_iban: str | None = Field(None, description='Billing iban')
    recipient: str | None = Field(None, description='Recipient')
    reference: str | None = Field(None, description='Reference')
    notes: str | None = Field(None, description='Notes')
    emails: list[str] | None = Field(None, description='Emails')
    external_reference: str | None = Field(None, description='You can use your own unique value when creating the product. If not provided, Pennylane will pick one for you. Value must be unique')
    billing_language: Literal['fr_FR', 'en_GB', 'de_DE', 'es_ES'] | None = Field(None, description='The language in which the customer will receive invoices. Default is `fr_FR`')

class PennylaneUpdateIndividualCustomerConfig(_Input):
    'Update an individual customer'
    operation: Literal['update_individual_customer'] = Field('update_individual_customer', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='Individual customer identifier')
    first_name: str | None = Field(None, description='First name')
    last_name: str | None = Field(None, description='Last name')
    phone: str | None = Field(None, description='Phone')
    billing_address: PennylaneAddress | None = Field(None, description='Billing address')
    delivery_address: PennylaneAddress | None = Field(None, description='Delivery address')
    payment_conditions: Literal['upon_receipt', 'custom', '7_days', '15_days', '30_days', '30_days_end_of_month', '45_days', '45_days_end_of_month', '60_days'] | None = Field(None, description="Note that the `custom` option is only used on Pennylane's web app to avoid pre-filling the deadline when creating an invoice. On the API it has no effect and you will still have to provide a deadline when creating an invoice.")
    billing_iban: str | None = Field(None, description='Billing iban')
    recipient: str | None = Field(None, description='Recipient')
    reference: str | None = Field(None, description='Reference')
    notes: str | None = Field(None, description='Notes')
    emails: list[str] | None = Field(None, description='Emails')
    external_reference: str | None = Field(None, description='The unique external reference assigned to this customer, assigned on creation either by you or Pennylane.')
    billing_language: Literal['fr_FR', 'en_GB', 'de_DE', 'es_ES'] | None = Field(None, description='The language in which the customer will receive invoices. Default is `fr_FR`')

class PennylaneCreateSupplierConfig(_Input):
    'Create a Supplier'
    operation: Literal['create_supplier'] = Field('create_supplier', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='Name')
    reg_no: str | None = Field(None, pattern='^\\d{9}$', description='Supplier registration number (SIREN).\n- 9-digit number\n- Only applicable for French companies\n')
    establishment_no: str | None = Field(None, pattern='^\\d{14}$', description='Supplier identification number (SIRET).\n- 14-digit number combining SIREN (9 digits) and NIC (5 digits)\n- Only applicable for French companies\n')
    postal_address: PennylaneAddress | None = Field(None, description='Postal address')
    vat_number: str | None = Field(None, description='Vat number')
    emails: list[str] | None = Field(None, description='Emails')
    iban: str | None = Field(None, description='Iban')
    supplier_payment_method: Literal['automatic_transfer', 'manual_transfer', 'automatic_debiting', 'bill_of_exchange', 'check', 'cash', 'card', 'other'] | None = Field(None, description='Supplier payment method')
    supplier_due_date_delay: int | None = Field(None, description='Supplier due date delay')
    supplier_due_date_rule: Literal['days', 'days_or_end_of_month'] | None = Field(None, description='Supplier due date rule')
    external_reference: str | None = Field(None, description='A unique external reference you can provide to track this supplier. If not provided, Pennylane will generate an identifier for you.')

class PennylaneUpdateSupplierConfig(_Input):
    'Update a supplier'
    operation: Literal['update_supplier'] = Field('update_supplier', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='Pennylane ID')
    name: str | None = Field(None, description='Name')
    reg_no: str | None = Field(None, pattern='^\\d{9}$', description='Supplier registration number (SIREN).\n- 9-digit number\n- Only applicable for French companies\n')
    establishment_no: str | None = Field(None, pattern='^\\d{14}$', description='Supplier identification number (SIRET).\n- 14-digit number combining SIREN (9 digits) and NIC (5 digits)\n- Only applicable for French companies\n')
    postal_address: PennylaneAddress | None = Field(None, description='Postal address')
    vat_number: str | None = Field(None, description='Vat number')
    emails: list[str] | None = Field(None, description='Emails')
    iban: str | None = Field(None, description='Iban')
    supplier_payment_method: Literal['automatic_transfer', 'manual_transfer', 'automatic_debiting', 'bill_of_exchange', 'check', 'cash', 'card', 'other'] | None = Field(None, description='Supplier payment method')
    supplier_due_date_delay: int | None = Field(None, description='Supplier due date delay')
    supplier_due_date_rule: Literal['days', 'days_or_end_of_month'] | None = Field(None, description='Supplier due date rule')
    external_reference: str | None = Field(None, description='The unique external reference that was assigned during creation either by you or Pennylane.')

class PennylaneCreateProductConfig(_Input):
    'Create a product'
    operation: Literal['create_product'] = Field('create_product', json_schema_extra={"ui:hidden": True})
    label: str = Field(..., description='Product label')
    description: str | None = Field(None, description='Product description. Maximum 5,000 characters.')
    price_before_tax: str = Field(..., pattern='^-?\\d+(\\.\\d+)?$', description='Price before tax')
    vat_rate: Literal['FR_1_05', 'FR_1_75', 'FR_09', 'FR_21', 'FR_40', 'FR_50', 'FR_55', 'FR_60', 'FR_65', 'FR_85', 'FR_92', 'FR_100', 'FR_130', 'FR_15_385', 'FR_160', 'FR_196', 'FR_200', 'AD_10', 'AD_45', 'AD_95', 'AT_100', 'AT_130', 'AT_190', 'AT_200', 'BE_60', 'BE_120', 'BE_210', 'BG_90', 'BG_200', 'CH_25', 'CH_37', 'CH_77', 'CH_26', 'CH_38', 'CH_81', 'CY_30', 'CY_50', 'CY_80', 'CY_90', 'CY_190', 'CZ_100', 'CZ_120', 'CZ_150', 'CZ_210', 'DE_70', 'DE_190', 'DK_250', 'EE_90', 'EE_200', 'EE_220', 'EE_240', 'ES_40', 'ES_70', 'ES_100', 'ES_210', 'FI_100', 'FI_135', 'FI_140', 'FI_240', 'FI_255', 'GB_50', 'GB_200', 'GR_60', 'GR_130', 'GR_170', 'GR_240', 'GR_40', 'HR_50', 'HR_130', 'HR_250', 'HU_50', 'HU_180', 'HU_270', 'IE_48', 'IE_90', 'IE_135', 'IE_210', 'IE_230', 'IT_40', 'IT_50', 'IT_100', 'IT_220', 'LT_50', 'LT_90', 'LT_120', 'LT_210', 'LU_30', 'LU_70', 'LU_80', 'LU_120', 'LU_130', 'LU_140', 'LU_160', 'LU_170', 'LV_50', 'LV_120', 'LV_210', 'MC_09', 'MC_21', 'MC_55', 'MC_85', 'MC_100', 'MC_200', 'MT_50', 'MT_70', 'MT_120', 'MT_180', 'MU_150', 'NL_90', 'NL_210', 'PL_50', 'PL_80', 'PL_230', 'PT_60', 'PT_130', 'PT_160', 'PT_180', 'PT_220', 'PT_230', 'RO_50', 'RO_90', 'RO_110', 'RO_190', 'RO_210', 'SE_60', 'SE_120', 'SE_250', 'SI_50', 'SI_95', 'SI_220', 'SK_50', 'SK_100', 'SK_190', 'SK_200', 'SK_230', 'NO_120', 'NO_150', 'NO_250', 'DE_70_BU0002', 'DE_190_BU0003', 'DE_70_BU0008', 'DE_190_BU0009', 'DE_intracom_70_BU0012', 'DE_intracom_190_BU0013', 'DE_190_electronic_BU0226', 'exempt', 'DE_intracom_exempt_BU0011', 'DE_intracom_exempt_BU0047', 'DE_intracom_exempt_BU0233', 'DE_exempt_BU0001', 'DE_exempt_BU0181', 'DE_exempt_BU0490', 'intracom_21', 'intracom_55', 'intracom_85', 'intracom_100', 'crossborder', 'ES_intracom_sales_goods', 'ES_intracom_sales_services', 'DE_intracom_70_BU0018', 'DE_intracom_190_BU0019', 'DE_intracom_190_BU0506', 'extracom', 'DE_extracom_BU0173', 'DE_extracom_BU0191', 'DE_extracom_190_BU0511', 'ES_isp_sales', 'ES_suplido', 'FR_85_construction', 'FR_100_construction', 'FR_200_construction', 'DE_exempt_construction_BU0046', 'DE_70_construction_BU0091', 'DE_190_construction_BU0094', 'DE_190_construction_BU0526', 'DE_190_construction_BU0546', 'ES_isp_purchases_210', 'ES_isp_purchases_100'] = Field(..., description='Product VAT rate. A 20% VAT in France is FR_200.')
    unit: str | None = Field(None, description='Product unit')
    currency: Literal['EUR', 'USD', 'GBP', 'AED', 'AFN', 'ALL', 'AMD', 'ANG', 'AOA', 'ARS', 'AUD', 'AWG', 'AZN', 'BAM', 'BBD', 'BDT', 'BGN', 'BHD', 'BIF', 'BMD', 'BND', 'BOB', 'BRL', 'BSD', 'BTN', 'BWP', 'BYN', 'BYR', 'BZD', 'CAD', 'CDF', 'CHE', 'CHF', 'CLF', 'CLP', 'CNY', 'COP', 'CRC', 'CUC', 'CUP', 'CVE', 'CZK', 'DJF', 'DKK', 'DOP', 'DZD', 'EGP', 'ERN', 'ETB', 'FJD', 'FKP', 'GEL', 'GGP', 'GHS', 'GIP', 'GMD', 'GNF', 'GTQ', 'GYD', 'HKD', 'HNL', 'HRK', 'HTG', 'HUF', 'IDR', 'ILS', 'IMP', 'INR', 'IQD', 'IRR', 'ISK', 'JEP', 'JMD', 'JOD', 'JPY', 'KES', 'KGS', 'KHR', 'KMF', 'KPW', 'KRW', 'KWD', 'KYD', 'KZT', 'LAK', 'LBP', 'LKR', 'LRD', 'LSL', 'LTL', 'LVL', 'LYD', 'MAD', 'MDL', 'MGA', 'MKD', 'MMK', 'MNT', 'MOP', 'MRO', 'MRU', 'MUR', 'MVR', 'MWK', 'MXN', 'MYR', 'MZN', 'NAD', 'NGN', 'NIO', 'NOK', 'NPR', 'NZD', 'OMR', 'PAB', 'PEN', 'PGK', 'PHP', 'PKR', 'PLN', 'PYG', 'QAR', 'RON', 'RSD', 'RUB', 'RWF', 'SAR', 'SBD', 'SCR', 'SDG', 'SEK', 'SGD', 'SHP', 'SLL', 'SLE', 'SOS', 'SRD', 'STD', 'SVC', 'SYP', 'SZL', 'THB', 'TJS', 'TMT', 'TND', 'TOP', 'TRY', 'TTD', 'TWD', 'TZS', 'UAH', 'UGX', 'UYU', 'UZS', 'VEF', 'VES', 'VND', 'VUV', 'WST', 'XAF', 'XCD', 'XDR', 'XOF', 'XPF', 'YER', 'ZAR', 'ZMK', 'ZMW', 'ZWL'] | None = Field(None, description='Currency')
    reference: str | None = Field(None, description='Product reference')
    external_reference: str | None = Field(None, description='You can use your own unique value when creating the product. If not provided, Pennylane will pick one for you. Value must be unique')
    ledger_account_id: int | None = Field(None, description='Ledger account id')

class PennylaneUpdateProductConfig(_Input):
    'Update a product'
    operation: Literal['update_product'] = Field('update_product', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='Pennylane ID')
    label: str | None = Field(None, description='Label')
    description: str | None = Field(None, description='Product description. Maximum 5,000 characters.')
    price_before_tax: str | None = Field(None, pattern='^-?\\d+(\\.\\d+)?$', description='Price before tax')
    vat_rate: Literal['FR_1_05', 'FR_1_75', 'FR_09', 'FR_21', 'FR_40', 'FR_50', 'FR_55', 'FR_60', 'FR_65', 'FR_85', 'FR_92', 'FR_100', 'FR_130', 'FR_15_385', 'FR_160', 'FR_196', 'FR_200', 'AD_10', 'AD_45', 'AD_95', 'AT_100', 'AT_130', 'AT_190', 'AT_200', 'BE_60', 'BE_120', 'BE_210', 'BG_90', 'BG_200', 'CH_25', 'CH_37', 'CH_77', 'CH_26', 'CH_38', 'CH_81', 'CY_30', 'CY_50', 'CY_80', 'CY_90', 'CY_190', 'CZ_100', 'CZ_120', 'CZ_150', 'CZ_210', 'DE_70', 'DE_190', 'DK_250', 'EE_90', 'EE_200', 'EE_220', 'EE_240', 'ES_40', 'ES_70', 'ES_100', 'ES_210', 'FI_100', 'FI_135', 'FI_140', 'FI_240', 'FI_255', 'GB_50', 'GB_200', 'GR_60', 'GR_130', 'GR_170', 'GR_240', 'GR_40', 'HR_50', 'HR_130', 'HR_250', 'HU_50', 'HU_180', 'HU_270', 'IE_48', 'IE_90', 'IE_135', 'IE_210', 'IE_230', 'IT_40', 'IT_50', 'IT_100', 'IT_220', 'LT_50', 'LT_90', 'LT_120', 'LT_210', 'LU_30', 'LU_70', 'LU_80', 'LU_120', 'LU_130', 'LU_140', 'LU_160', 'LU_170', 'LV_50', 'LV_120', 'LV_210', 'MC_09', 'MC_21', 'MC_55', 'MC_85', 'MC_100', 'MC_200', 'MT_50', 'MT_70', 'MT_120', 'MT_180', 'MU_150', 'NL_90', 'NL_210', 'PL_50', 'PL_80', 'PL_230', 'PT_60', 'PT_130', 'PT_160', 'PT_180', 'PT_220', 'PT_230', 'RO_50', 'RO_90', 'RO_110', 'RO_190', 'RO_210', 'SE_60', 'SE_120', 'SE_250', 'SI_50', 'SI_95', 'SI_220', 'SK_50', 'SK_100', 'SK_190', 'SK_200', 'SK_230', 'NO_120', 'NO_150', 'NO_250', 'DE_70_BU0002', 'DE_190_BU0003', 'DE_70_BU0008', 'DE_190_BU0009', 'DE_intracom_70_BU0012', 'DE_intracom_190_BU0013', 'DE_190_electronic_BU0226', 'exempt', 'DE_intracom_exempt_BU0011', 'DE_intracom_exempt_BU0047', 'DE_intracom_exempt_BU0233', 'DE_exempt_BU0001', 'DE_exempt_BU0181', 'DE_exempt_BU0490', 'intracom_21', 'intracom_55', 'intracom_85', 'intracom_100', 'crossborder', 'ES_intracom_sales_goods', 'ES_intracom_sales_services', 'DE_intracom_70_BU0018', 'DE_intracom_190_BU0019', 'DE_intracom_190_BU0506', 'extracom', 'DE_extracom_BU0173', 'DE_extracom_BU0191', 'DE_extracom_190_BU0511', 'ES_isp_sales', 'ES_suplido', 'FR_85_construction', 'FR_100_construction', 'FR_200_construction', 'DE_exempt_construction_BU0046', 'DE_70_construction_BU0091', 'DE_190_construction_BU0094', 'DE_190_construction_BU0526', 'DE_190_construction_BU0546', 'ES_isp_purchases_210', 'ES_isp_purchases_100'] | None = Field(None, description='Product VAT rate. A 20% VAT in France is FR_200.')
    unit: str | None = Field(None, description='Product unit')
    currency: Literal['EUR', 'USD', 'GBP', 'AED', 'AFN', 'ALL', 'AMD', 'ANG', 'AOA', 'ARS', 'AUD', 'AWG', 'AZN', 'BAM', 'BBD', 'BDT', 'BGN', 'BHD', 'BIF', 'BMD', 'BND', 'BOB', 'BRL', 'BSD', 'BTN', 'BWP', 'BYN', 'BYR', 'BZD', 'CAD', 'CDF', 'CHE', 'CHF', 'CLF', 'CLP', 'CNY', 'COP', 'CRC', 'CUC', 'CUP', 'CVE', 'CZK', 'DJF', 'DKK', 'DOP', 'DZD', 'EGP', 'ERN', 'ETB', 'FJD', 'FKP', 'GEL', 'GGP', 'GHS', 'GIP', 'GMD', 'GNF', 'GTQ', 'GYD', 'HKD', 'HNL', 'HRK', 'HTG', 'HUF', 'IDR', 'ILS', 'IMP', 'INR', 'IQD', 'IRR', 'ISK', 'JEP', 'JMD', 'JOD', 'JPY', 'KES', 'KGS', 'KHR', 'KMF', 'KPW', 'KRW', 'KWD', 'KYD', 'KZT', 'LAK', 'LBP', 'LKR', 'LRD', 'LSL', 'LTL', 'LVL', 'LYD', 'MAD', 'MDL', 'MGA', 'MKD', 'MMK', 'MNT', 'MOP', 'MRO', 'MRU', 'MUR', 'MVR', 'MWK', 'MXN', 'MYR', 'MZN', 'NAD', 'NGN', 'NIO', 'NOK', 'NPR', 'NZD', 'OMR', 'PAB', 'PEN', 'PGK', 'PHP', 'PKR', 'PLN', 'PYG', 'QAR', 'RON', 'RSD', 'RUB', 'RWF', 'SAR', 'SBD', 'SCR', 'SDG', 'SEK', 'SGD', 'SHP', 'SLL', 'SLE', 'SOS', 'SRD', 'STD', 'SVC', 'SYP', 'SZL', 'THB', 'TJS', 'TMT', 'TND', 'TOP', 'TRY', 'TTD', 'TWD', 'TZS', 'UAH', 'UGX', 'UYU', 'UZS', 'VEF', 'VES', 'VND', 'VUV', 'WST', 'XAF', 'XCD', 'XDR', 'XOF', 'XPF', 'YER', 'ZAR', 'ZMK', 'ZMW', 'ZWL'] | None = Field(None, description='Currency')
    reference: str | None = Field(None, description='Reference')
    external_reference: str | None = Field(None, description='The unique external reference assigned to this Product, assigned on creation either by you or Pennylane.')
    ledger_account_id: int | None = Field(None, description='Ledger account id')

class PennylaneCreateCustomerInvoiceConfig(_Input):
    'Create a customer invoice'
    operation: Literal['create_customer_invoice'] = Field('create_customer_invoice', json_schema_extra={"ui:hidden": True})
    date: Date = Field(..., description='Invoice date (ISO 8601)')
    deadline: Date = Field(..., description='Invoice payment deadline (ISO 8601)')
    customer_id: int = Field(..., description='Customer identifier')
    draft: Literal[True] = Field(True, description='Indicates if the invoice is in draft status (has not been finalized)')
    invoice_lines: list[PennylaneProductLine] = Field(..., min_length=1, description='Invoice lines')
    pdf_invoice_subject: str | None = Field(None, description='Invoice title')
    pdf_invoice_free_text: str | None = Field(None, description='For example, the contact details of the person to contact')
    pdf_description: str | None = Field(None, description='Invoice description. Maximum 5,000 characters.')
    external_reference: str | None = Field(None, description='A unique external reference you can provide to track this customer invoice. If not provided, Pennylane will generate an identifier for you.')
    language: Literal['fr_FR', 'en_GB', 'de_DE', 'es_ES'] | None = Field(None, description='The local default is based on the thirdparty (customer / supplier ) billing_language . In case the customer is not present, we will default to the company locale.')
    currency: Literal['EUR', 'USD', 'GBP', 'AED', 'AFN', 'ALL', 'AMD', 'ANG', 'AOA', 'ARS', 'AUD', 'AWG', 'AZN', 'BAM', 'BBD', 'BDT', 'BGN', 'BHD', 'BIF', 'BMD', 'BND', 'BOB', 'BRL', 'BSD', 'BTN', 'BWP', 'BYN', 'BYR', 'BZD', 'CAD', 'CDF', 'CHE', 'CHF', 'CLF', 'CLP', 'CNY', 'COP', 'CRC', 'CUC', 'CUP', 'CVE', 'CZK', 'DJF', 'DKK', 'DOP', 'DZD', 'EGP', 'ERN', 'ETB', 'FJD', 'FKP', 'GEL', 'GGP', 'GHS', 'GIP', 'GMD', 'GNF', 'GTQ', 'GYD', 'HKD', 'HNL', 'HRK', 'HTG', 'HUF', 'IDR', 'ILS', 'IMP', 'INR', 'IQD', 'IRR', 'ISK', 'JEP', 'JMD', 'JOD', 'JPY', 'KES', 'KGS', 'KHR', 'KMF', 'KPW', 'KRW', 'KWD', 'KYD', 'KZT', 'LAK', 'LBP', 'LKR', 'LRD', 'LSL', 'LTL', 'LVL', 'LYD', 'MAD', 'MDL', 'MGA', 'MKD', 'MMK', 'MNT', 'MOP', 'MRO', 'MRU', 'MUR', 'MVR', 'MWK', 'MXN', 'MYR', 'MZN', 'NAD', 'NGN', 'NIO', 'NOK', 'NPR', 'NZD', 'OMR', 'PAB', 'PEN', 'PGK', 'PHP', 'PKR', 'PLN', 'PYG', 'QAR', 'RON', 'RSD', 'RUB', 'RWF', 'SAR', 'SBD', 'SCR', 'SDG', 'SEK', 'SGD', 'SHP', 'SLL', 'SLE', 'SOS', 'SRD', 'STD', 'SVC', 'SYP', 'SZL', 'THB', 'TJS', 'TMT', 'TND', 'TOP', 'TRY', 'TTD', 'TWD', 'TZS', 'UAH', 'UGX', 'UYU', 'UZS', 'VEF', 'VES', 'VND', 'VUV', 'WST', 'XAF', 'XCD', 'XDR', 'XOF', 'XPF', 'YER', 'ZAR', 'ZMK', 'ZMW', 'ZWL'] | None = Field(None, description='Currency')

class PennylaneMarkCustomerInvoicePaidConfig(_Input):
    'Mark a customer invoice as paid'
    operation: Literal['mark_customer_invoice_paid'] = Field('mark_customer_invoice_paid', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='The unique identifier of the customer invoice')

class PennylaneUpdateSupplierInvoicePaymentStatusConfig(_Input):
    'Update a supplier invoice payment status'
    operation: Literal['update_supplier_invoice_payment_status'] = Field('update_supplier_invoice_payment_status', json_schema_extra={"ui:hidden": True})
    supplier_invoice_id: int = Field(..., description='Supplier invoice identifier')
    payment_status: Literal['paid', 'to_be_paid'] = Field(..., description='Payment status')

# Pennylane's own MCP server: agents get its tools through a person's Pennylane sign-in.
PennylaneMcpCredential = mcp_credential("pennylane", "https://mcp.pennylane.com/mcp", app="Pennylane")
PennylaneCredential = Union[PennylaneAPIToken, PennylaneMcpCredential]


PennylaneOperation = Annotated[Union[PennylaneGetMeConfig, PennylaneListCustomersConfig, PennylaneGetCustomerConfig, PennylaneListSuppliersConfig, PennylaneGetSupplierConfig, PennylaneListProductsConfig, PennylaneGetProductConfig, PennylaneListCustomerInvoicesConfig, PennylaneGetCustomerInvoiceConfig, PennylaneListSupplierInvoicesConfig, PennylaneGetSupplierInvoiceConfig, PennylaneListTransactionsConfig, PennylaneGetTransactionConfig, PennylaneListBankAccountsConfig, PennylaneCreateCompanyCustomerConfig, PennylaneUpdateCompanyCustomerConfig, PennylaneCreateIndividualCustomerConfig, PennylaneUpdateIndividualCustomerConfig, PennylaneCreateSupplierConfig, PennylaneUpdateSupplierConfig, PennylaneCreateProductConfig, PennylaneUpdateProductConfig, PennylaneCreateCustomerInvoiceConfig, PennylaneMarkCustomerInvoicePaidConfig, PennylaneUpdateSupplierInvoicePaymentStatusConfig], Field(discriminator="operation")]

class PennylaneFullConfig(NodeConfig[PennylaneOperation, PennylaneCredential]):
    pass

# method, fixed path, path parameters, query parameters, JSON body
ROUTES = {'get_me': ('GET', '/api/external/v2/me', [], [], False), 'list_customers': ('GET', '/api/external/v2/customers', [], ['cursor', 'limit', 'filter', 'sort'], False), 'get_customer': ('GET', '/api/external/v2/customers/{id}', ['id'], [], False), 'list_suppliers': ('GET', '/api/external/v2/suppliers', [], ['cursor', 'limit', 'filter', 'sort'], False), 'get_supplier': ('GET', '/api/external/v2/suppliers/{id}', ['id'], [], False), 'list_products': ('GET', '/api/external/v2/products', [], ['cursor', 'limit', 'filter', 'sort'], False), 'get_product': ('GET', '/api/external/v2/products/{id}', ['id'], [], False), 'list_customer_invoices': ('GET', '/api/external/v2/customer_invoices', [], ['cursor', 'limit', 'filter', 'sort', 'include'], False), 'get_customer_invoice': ('GET', '/api/external/v2/customer_invoices/{id}', ['id'], [], False), 'list_supplier_invoices': ('GET', '/api/external/v2/supplier_invoices', [], ['cursor', 'limit', 'filter', 'sort'], False), 'get_supplier_invoice': ('GET', '/api/external/v2/supplier_invoices/{id}', ['id'], [], False), 'list_transactions': ('GET', '/api/external/v2/transactions', [], ['cursor', 'limit', 'filter', 'sort'], False), 'get_transaction': ('GET', '/api/external/v2/transactions/{id}', ['id'], [], False), 'list_bank_accounts': ('GET', '/api/external/v2/bank_accounts', [], ['cursor', 'limit', 'sort'], False), 'create_company_customer': ('POST', '/api/external/v2/company_customers', [], [], True), 'update_company_customer': ('PUT', '/api/external/v2/company_customers/{id}', ['id'], [], True), 'create_individual_customer': ('POST', '/api/external/v2/individual_customers', [], [], True), 'update_individual_customer': ('PUT', '/api/external/v2/individual_customers/{id}', ['id'], [], True), 'create_supplier': ('POST', '/api/external/v2/suppliers', [], [], True), 'update_supplier': ('PUT', '/api/external/v2/suppliers/{id}', ['id'], [], True), 'create_product': ('POST', '/api/external/v2/products', [], [], True), 'update_product': ('PUT', '/api/external/v2/products/{id}', ['id'], [], True), 'create_customer_invoice': ('POST', '/api/external/v2/customer_invoices', [], [], True), 'mark_customer_invoice_paid': ('PUT', '/api/external/v2/customer_invoices/{id}/mark_as_paid', ['id'], [], False), 'update_supplier_invoice_payment_status': ('PUT', '/api/external/v2/supplier_invoices/{supplier_invoice_id}/payment_status', ['supplier_invoice_id'], [], True)}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()
                if key.lower() not in {"authorization", "api_token", "access_token", "refresh_token"}}
    return value


class PennylaneNode(WorkflowNode):
    integration_type = "automation-pennylane"
    credential_provider_labels = {"pennylane": "Pennylane Account"}
    scope_registry = PENNYLANE_SCOPES
    connection_evidence = ConnectionEvidence(noun="Pennylane company", identity_operation="get_me")

    @classmethod
    def get_config_model(cls):
        return PennylaneFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Pennylane API token")
        op = self.config.config
        credential = self.config.credentials
        token = credential.api_token
        method, path, path_fields, query_fields, has_body = ROUTES[op.operation]
        # Include defaults such as draft=true and limit=20. Omitted optional
        # fields stay absent; no unknown config fields reach the provider.
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for name in path_fields:
            path = path.replace("{" + name + "}", str(values.pop(name)))
        params = {name: values.pop(name) for name in query_fields if name in values}
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        if credential.company_id:
            headers["X-Company-Id"] = credential.company_id
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://app.pennylane.com" + path,
                    headers=headers, params=params, **({"json": values} if has_body else {}))
        except (httpx.TimeoutException, httpx.TransportError):
            raise ValueError("Pennylane request did not complete; inspect the account before retrying a write") from None
        if not 200 <= response.status_code < 300:
            message = "Pennylane HTTP " + str(response.status_code)
            try:
                error = response.json()
                if isinstance(error, dict):
                    message += ": " + str(error.get("message") or error.get("error") or "Request rejected")[:1500]
            except ValueError:
                pass
            raise ValueError(_redact(message, token))
        if response.status_code == 204:
            return {"status": "success", "acknowledged": True}
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Pennylane returned invalid JSON") from None
        if not isinstance(body, dict):
            raise ValueError("Pennylane returned an unexpected response")
        if op.operation.startswith("list_"):
            if not isinstance(body.get("items"), list) or type(body.get("has_more")) is not bool:
                raise ValueError("Pennylane returned an unexpected cursor page")
        if op.operation == "get_me" and not isinstance(body.get("company"), dict):
            raise ValueError("Pennylane did not identify a company")
        return _redact(body, token)
