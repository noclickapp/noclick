"""
QuickBooks Online (Intuit Accounting API) automation node.

Provides workflow integration with QuickBooks Online for operations including:
- Query: run SQL-like statements against any entity (the only list/search path)
- Invoices: create, read, update, delete, send (email), get PDF
- Customers: create, read, update
- Vendors: create, read, update
- Bills: create, read, update, delete
- Payments / Bill payments: create, read, update
- Estimates, Sales receipts, Credit memos
- Items, Accounts: create, read, update
- Purchases, Journal entries, Purchase orders: create
- Reports: run a financial report (ProfitAndLoss, BalanceSheet, ...)
- Batch: bundle up to 30 operations in one request
- Company info: read the connected company's profile
- Advanced coverage:
  - Any Accounting REST endpoint via a generic custom request
  - Any Payments REST endpoint via a generic custom request
- Webhook triggers: one per (entity, operation), e.g. "On Invoice Created",
  "On Customer Updated", "On Payment Deleted" — fires on the matching Intuit
  webhook delivery (dashboard-registered; ~119 triggers across 31 entities)

Authentication: OAuth 2.0 (authorization_code) — Intuit's only supported auth.
Every call is scoped by a per-company ``realmId`` captured at OAuth time and
carried in the request URL path (not a header).

API Base URL: https://quickbooks.api.intuit.com/v3/company/{realmId}/ (production)
              https://sandbox-quickbooks.api.intuit.com/v3/company/{realmId}/ (sandbox)
Documentation: https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/account
"""

import hashlib
import hmac
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
import re
from pydantic import BaseModel, Field, ConfigDict, Discriminator, create_model
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.binary_output import BinaryOutput
from nodes.core.dynamic_options import load_paginated_options
from nodes.oauth.quickbooks_oauth import (
    refresh_access_token,
    is_token_expired,
    QUICKBOOKS_FULL_SCOPES,
)
from nodes.scopes.quickbooks import QUICKBOOKS_SCOPES

logger = logging.getLogger(__name__)

QUICKBOOKS_API_BASE_PROD = "https://quickbooks.api.intuit.com/v3/company"
QUICKBOOKS_API_BASE_SANDBOX = "https://sandbox-quickbooks.api.intuit.com/v3/company"

# Pin the API schema version so the contract doesn't shift under us.
QUICKBOOKS_MINOR_VERSION = "75"

# Entities the webhook triggers can subscribe to (configured in the Intuit
# Developer dashboard — there is no registerable webhook API). QuickBooks POSTs
# Create/Update/Delete/Merge/Void/Emailed notifications for each of these to the
# single dashboard webhook URL; one generated trigger per (entity, operation)
# filters the inbound delivery down to exactly its event.
WEBHOOK_ENTITIES = [
    "Account",
    "Bill",
    "BillPayment",
    "Budget",
    "Class",
    "CreditMemo",
    "Currency",
    "Customer",
    "Department",
    "Deposit",
    "Employee",
    "Estimate",
    "Invoice",
    "Item",
    "JournalCode",
    "JournalEntry",
    "Payment",
    "PaymentMethod",
    "PayrollEmployee",
    "Payslips",
    "Preferences",
    "Purchase",
    "PurchaseOrder",
    "RefundReceipt",
    "SalesReceipt",
    "TaxAgency",
    "Term",
    "TimeActivity",
    "Transfer",
    "Vendor",
    "VendorCredit",
]

# ============================================================================
# Credential Schema (OAuth 2.0 only — Intuit supports no API keys)
# ============================================================================


class QuickBooksOAuthCredential(BaseModel):
    """OAuth 2.0 credential for QuickBooks Online (Intuit).

    Tokens are obtained via the OAuth flow, not entered manually. The
    ``realm_id`` (company ID) is returned by the OAuth callback and scopes
    every API call.
    """

    credential_type: Literal["quickbooks_oauth"] = Field(
        "quickbooks_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Intuit"
    )
    refresh_token: str = Field(
        ...,
        title="Refresh Token",
        description="OAuth 2.0 refresh token (rotates on each use — must be persisted)",
    )
    expires_at: str = Field(
        ...,
        title="Token Expiry",
        description="ISO 8601 timestamp when the access token expires",
    )
    realm_id: str = Field(
        ...,
        title="Company (Realm) ID",
        description="QuickBooks company ID returned at OAuth time; part of every API URL",
    )
    is_sandbox: Optional[bool] = Field(
        default=False,
        title="Sandbox",
        description="Use the sandbox host instead of production",
    )
    email: Optional[str] = Field(
        None,
        title="Account Email",
        description="Email address of the connected Intuit account",
    )
    client_id: Optional[str] = Field(
        None,
        title="Client ID (Optional)",
        description="Your Intuit OAuth 2.0 Client ID - leave empty to use NoClick's OAuth app",
        json_schema_extra={"x-optional-custom": True},
    )
    client_secret: Optional[str] = Field(
        None,
        title="Client Secret (Optional)",
        description="Your Intuit OAuth 2.0 Client Secret - leave empty to use NoClick's OAuth app",
        json_schema_extra={"ui:widget": "password", "x-optional-custom": True},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "quickbooks",
            "x-oauth-scopes": QUICKBOOKS_FULL_SCOPES,
            "x-oauth-supports-custom-client": True,
            "x-oauth-redirect-uri": "/api/auth/intuit/callback",
            "x-oauth-custom-client-help": (
                "Optionally bring your own Intuit OAuth app. Register one at "
                "https://developer.intuit.com (My Apps), add the redirect URI above, "
                "and paste its client ID and secret here. "
                "Leave blank to use NoClick's shared QuickBooks app."
            ),
            "x-credential-url": "https://developer.intuit.com",
        }
    )


QuickBooksCredential = QuickBooksOAuthCredential


# ============================================================================
# Operation Configs
# ============================================================================


class QuickBooksRunQueryConfig(BaseModel):
    """Run a SQL-like query against any entity (the primary list/search path)."""

    operation: Literal["run_query"] = Field(
        "run_query",
        json_schema_extra={
            "const": "run_query",
            "ui:hidden": True,
            "x-category": "Query",
            "x-is-trigger": False,
            "x-display-name": "Run Query",
        },
        title="Run Query",
    )
    query: str = Field(
        ...,
        title="Query",
        description="SQL-like statement, e.g. SELECT * FROM Invoice WHERE Balance > '0' MAXRESULTS 50",
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksCreateInvoiceConfig(BaseModel):
    """Create a sales invoice."""

    operation: Literal["create_invoice"] = Field(
        "create_invoice",
        json_schema_extra={
            "const": "create_invoice",
            "ui:hidden": True,
            "x-category": "Invoices",
            "x-is-trigger": False,
            "x-display-name": "Create Invoice",
        },
        title="Create Invoice",
    )
    customer_id: str = Field(
        ...,
        title="Customer",
        description="The customer to bill",
        json_schema_extra={
            "x-resource-type": "quickbooks_customer",
            "x-dynamic-options": {
                "field_name": "customer_id",
                "placeholder": "Select a customer...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste customer Id",
            }
        },
    )
    line: str = Field(
        ...,
        title="Line Items (JSON)",
        description='JSON array of invoice Line objects, e.g. [{"Amount":100,"DetailType":"SalesItemLineDetail","SalesItemLineDetail":{"ItemRef":{"value":"1"}}}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksReadInvoiceConfig(BaseModel):
    """Fetch a single invoice by Id."""

    operation: Literal["read_invoice"] = Field(
        "read_invoice",
        json_schema_extra={
            "const": "read_invoice",
            "ui:hidden": True,
            "x-category": "Invoices",
            "x-is-trigger": False,
            "x-display-name": "Read Invoice",
        },
        title="Read Invoice",
    )
    invoice_id: str = Field(..., title="Invoice Id", description="The Id of the invoice")


class QuickBooksUpdateInvoiceConfig(BaseModel):
    """Sparse-update an existing invoice (requires Id + SyncToken)."""

    operation: Literal["update_invoice"] = Field(
        "update_invoice",
        json_schema_extra={
            "const": "update_invoice",
            "ui:hidden": True,
            "x-category": "Invoices",
            "x-is-trigger": False,
            "x-display-name": "Update Invoice",
        },
        title="Update Invoice",
    )
    invoice_id: str = Field(..., title="Invoice Id", description="The Id of the invoice")
    sync_token: str = Field(
        ..., title="Sync Token", description="Current SyncToken (read the invoice first)"
    )
    fields: str = Field(
        ...,
        title="Fields to Update (JSON)",
        description='JSON object of fields to patch, e.g. {"CustomerMemo":{"value":"Thanks"}}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksDeleteInvoiceConfig(BaseModel):
    """Delete an invoice (requires Id + SyncToken)."""

    operation: Literal["delete_invoice"] = Field(
        "delete_invoice",
        json_schema_extra={
            "const": "delete_invoice",
            "ui:hidden": True,
            "x-category": "Invoices",
            "x-is-trigger": False,
            "x-display-name": "Delete Invoice",
        },
        title="Delete Invoice",
    )
    invoice_id: str = Field(..., title="Invoice Id", description="The Id of the invoice")
    sync_token: str = Field(
        ..., title="Sync Token", description="Current SyncToken (read the invoice first)"
    )


class QuickBooksSendInvoiceConfig(BaseModel):
    """Email an invoice PDF to the customer."""

    operation: Literal["send_invoice"] = Field(
        "send_invoice",
        json_schema_extra={
            "const": "send_invoice",
            "ui:hidden": True,
            "x-category": "Invoices",
            "x-is-trigger": False,
            "x-display-name": "Send Invoice",
        },
        title="Send Invoice",
    )
    invoice_id: str = Field(..., title="Invoice Id", description="The Id of the invoice to send")
    send_to: Optional[str] = Field(
        None,
        title="Send To",
        description="Override recipient email (defaults to the customer's billing email)",
    )


class QuickBooksGetInvoicePdfConfig(BaseModel):
    """Download an invoice as a PDF."""

    operation: Literal["get_invoice_pdf"] = Field(
        "get_invoice_pdf",
        json_schema_extra={
            "const": "get_invoice_pdf",
            "ui:hidden": True,
            "x-category": "Invoices",
            "x-is-trigger": False,
            "x-display-name": "Get Invoice PDF",
        },
        title="Get Invoice PDF",
    )
    invoice_id: str = Field(..., title="Invoice Id", description="The Id of the invoice")


class QuickBooksCreateCustomerConfig(BaseModel):
    """Create a customer/contact record."""

    operation: Literal["create_customer"] = Field(
        "create_customer",
        json_schema_extra={
            "const": "create_customer",
            "x-creates-resource": True,
            "x-resource-type": "quickbooks_customer",
            "x-resource-id-path": "data.Customer.Id",
            "ui:hidden": True,
            "x-category": "Customers",
            "x-is-trigger": False,
            "x-display-name": "Create Customer",
        },
        title="Create Customer",
    )
    display_name: str = Field(
        ..., title="Display Name", description="Unique display name for the customer"
    )
    email: Optional[str] = Field(None, title="Email", description="Primary email address")
    company_name: Optional[str] = Field(None, title="Company Name", description="Company name")
    phone: Optional[str] = Field(None, title="Phone", description="Primary phone number")


class QuickBooksReadCustomerConfig(BaseModel):
    """Fetch a single customer by Id."""

    operation: Literal["read_customer"] = Field(
        "read_customer",
        json_schema_extra={
            "const": "read_customer",
            "ui:hidden": True,
            "x-category": "Customers",
            "x-is-trigger": False,
            "x-display-name": "Read Customer",
        },
        title="Read Customer",
    )
    customer_id: str = Field(..., title="Customer Id", description="The Id of the customer")


class QuickBooksUpdateCustomerConfig(BaseModel):
    """Sparse-update a customer (requires Id + SyncToken)."""

    operation: Literal["update_customer"] = Field(
        "update_customer",
        json_schema_extra={
            "const": "update_customer",
            "ui:hidden": True,
            "x-category": "Customers",
            "x-is-trigger": False,
            "x-display-name": "Update Customer",
        },
        title="Update Customer",
    )
    customer_id: str = Field(..., title="Customer Id", description="The Id of the customer")
    sync_token: str = Field(
        ..., title="Sync Token", description="Current SyncToken (read the customer first)"
    )
    fields: str = Field(
        ...,
        title="Fields to Update (JSON)",
        description='JSON object of fields to patch, e.g. {"PrimaryEmailAddr":{"Address":"new@x.com"}}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksCreateVendorConfig(BaseModel):
    """Create a vendor/supplier record."""

    operation: Literal["create_vendor"] = Field(
        "create_vendor",
        json_schema_extra={
            "const": "create_vendor",
            "x-creates-resource": True,
            "x-resource-type": "quickbooks_vendor",
            "x-resource-id-path": "data.Vendor.Id",
            "ui:hidden": True,
            "x-category": "Vendors",
            "x-is-trigger": False,
            "x-display-name": "Create Vendor",
        },
        title="Create Vendor",
    )
    display_name: str = Field(
        ..., title="Display Name", description="Unique display name for the vendor"
    )
    email: Optional[str] = Field(None, title="Email", description="Primary email address")
    company_name: Optional[str] = Field(None, title="Company Name", description="Company name")


class QuickBooksReadVendorConfig(BaseModel):
    """Fetch a single vendor by Id."""

    operation: Literal["read_vendor"] = Field(
        "read_vendor",
        json_schema_extra={
            "const": "read_vendor",
            "ui:hidden": True,
            "x-category": "Vendors",
            "x-is-trigger": False,
            "x-display-name": "Read Vendor",
        },
        title="Read Vendor",
    )
    vendor_id: str = Field(
        ...,
        title="Vendor",
        description="The Id of the vendor",
        json_schema_extra={
            "x-resource-type": "quickbooks_vendor",
            "x-dynamic-options": {
                "field_name": "vendor_id",
                "placeholder": "Select a vendor...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste vendor Id",
            }
        },
    )


class QuickBooksUpdateVendorConfig(BaseModel):
    """Sparse-update a vendor (requires Id + SyncToken)."""

    operation: Literal["update_vendor"] = Field(
        "update_vendor",
        json_schema_extra={
            "const": "update_vendor",
            "ui:hidden": True,
            "x-category": "Vendors",
            "x-is-trigger": False,
            "x-display-name": "Update Vendor",
        },
        title="Update Vendor",
    )
    vendor_id: str = Field(
        ...,
        title="Vendor",
        description="The Id of the vendor",
        json_schema_extra={
            "x-resource-type": "quickbooks_vendor",
            "x-dynamic-options": {
                "field_name": "vendor_id",
                "placeholder": "Select a vendor...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste vendor Id",
            }
        },
    )
    sync_token: str = Field(
        ..., title="Sync Token", description="Current SyncToken (read the vendor first)"
    )
    fields: str = Field(
        ...,
        title="Fields to Update (JSON)",
        description="JSON object of fields to patch",
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksCreateBillConfig(BaseModel):
    """Create an accounts-payable bill."""

    operation: Literal["create_bill"] = Field(
        "create_bill",
        json_schema_extra={
            "const": "create_bill",
            "ui:hidden": True,
            "x-category": "Bills",
            "x-is-trigger": False,
            "x-display-name": "Create Bill",
        },
        title="Create Bill",
    )
    vendor_id: str = Field(
        ...,
        title="Vendor",
        description="The vendor the bill is from",
        json_schema_extra={
            "x-resource-type": "quickbooks_vendor",
            "x-dynamic-options": {
                "field_name": "vendor_id",
                "placeholder": "Select a vendor...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste vendor Id",
            }
        },
    )
    line: str = Field(
        ...,
        title="Line Items (JSON)",
        description="JSON array of bill Line objects (expense or item lines)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksReadBillConfig(BaseModel):
    """Fetch a single bill by Id."""

    operation: Literal["read_bill"] = Field(
        "read_bill",
        json_schema_extra={
            "const": "read_bill",
            "ui:hidden": True,
            "x-category": "Bills",
            "x-is-trigger": False,
            "x-display-name": "Read Bill",
        },
        title="Read Bill",
    )
    bill_id: str = Field(..., title="Bill Id", description="The Id of the bill")


class QuickBooksUpdateBillConfig(BaseModel):
    """Sparse-update a bill (requires Id + SyncToken)."""

    operation: Literal["update_bill"] = Field(
        "update_bill",
        json_schema_extra={
            "const": "update_bill",
            "ui:hidden": True,
            "x-category": "Bills",
            "x-is-trigger": False,
            "x-display-name": "Update Bill",
        },
        title="Update Bill",
    )
    bill_id: str = Field(..., title="Bill Id", description="The Id of the bill")
    sync_token: str = Field(
        ..., title="Sync Token", description="Current SyncToken (read the bill first)"
    )
    fields: str = Field(
        ...,
        title="Fields to Update (JSON)",
        description="JSON object of fields to patch",
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksDeleteBillConfig(BaseModel):
    """Delete a bill (requires Id + SyncToken)."""

    operation: Literal["delete_bill"] = Field(
        "delete_bill",
        json_schema_extra={
            "const": "delete_bill",
            "ui:hidden": True,
            "x-category": "Bills",
            "x-is-trigger": False,
            "x-display-name": "Delete Bill",
        },
        title="Delete Bill",
    )
    bill_id: str = Field(..., title="Bill Id", description="The Id of the bill")
    sync_token: str = Field(
        ..., title="Sync Token", description="Current SyncToken (read the bill first)"
    )


class QuickBooksCreatePaymentConfig(BaseModel):
    """Record a customer payment and link it to invoices."""

    operation: Literal["create_payment"] = Field(
        "create_payment",
        json_schema_extra={
            "const": "create_payment",
            "ui:hidden": True,
            "x-category": "Payments",
            "x-is-trigger": False,
            "x-display-name": "Create Payment",
        },
        title="Create Payment",
    )
    customer_id: str = Field(..., title="Customer Id", description="The paying customer")
    total_amount: str = Field(..., title="Total Amount", description="Payment amount, e.g. 100.00")
    line: Optional[str] = Field(
        None,
        title="Line / Linked Transactions (JSON)",
        description="JSON array linking the payment to invoices via LinkedTxn",
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksReadPaymentConfig(BaseModel):
    """Fetch a single received payment by Id."""

    operation: Literal["read_payment"] = Field(
        "read_payment",
        json_schema_extra={
            "const": "read_payment",
            "ui:hidden": True,
            "x-category": "Payments",
            "x-is-trigger": False,
            "x-display-name": "Read Payment",
        },
        title="Read Payment",
    )
    payment_id: str = Field(..., title="Payment Id", description="The Id of the payment")


class QuickBooksUpdatePaymentConfig(BaseModel):
    """Sparse-update a received payment (requires Id + SyncToken)."""

    operation: Literal["update_payment"] = Field(
        "update_payment",
        json_schema_extra={
            "const": "update_payment",
            "ui:hidden": True,
            "x-category": "Payments",
            "x-is-trigger": False,
            "x-display-name": "Update Payment",
        },
        title="Update Payment",
    )
    payment_id: str = Field(..., title="Payment Id", description="The Id of the payment")
    sync_token: str = Field(
        ..., title="Sync Token", description="Current SyncToken (read the payment first)"
    )
    fields: str = Field(
        ...,
        title="Fields to Update (JSON)",
        description="JSON object of fields to patch",
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksCreateBillPaymentConfig(BaseModel):
    """Record a payment made to a vendor against bills."""

    operation: Literal["create_bill_payment"] = Field(
        "create_bill_payment",
        json_schema_extra={
            "const": "create_bill_payment",
            "ui:hidden": True,
            "x-category": "Payments",
            "x-is-trigger": False,
            "x-display-name": "Create Bill Payment",
        },
        title="Create Bill Payment",
    )
    vendor_id: str = Field(
        ...,
        title="Vendor",
        description="The vendor being paid",
        json_schema_extra={
            "x-resource-type": "quickbooks_vendor",
            "x-dynamic-options": {
                "field_name": "vendor_id",
                "placeholder": "Select a vendor...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste vendor Id",
            }
        },
    )
    total_amount: str = Field(..., title="Total Amount", description="Payment amount, e.g. 100.00")
    pay_type: str = Field(
        "Check",
        title="Pay Type",
        description="Payment method type",
        json_schema_extra={
            "enum": ["Check", "CreditCard"],
            "enumNames": ["Check", "Credit Card"],
            "x-enum-searchable": True,
        },
    )
    account_id: str = Field(
        ...,
        title="Bank / Credit Card Account",
        description="Account the payment is drawn from — a bank account for Check, a credit card account for Credit Card. QuickBooks requires this.",
        json_schema_extra={
            "x-resource-type": "quickbooks_account",
            "x-dynamic-options": {
                "field_name": "account_id",
                "placeholder": "Select an account...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste account Id",
            }
        },
    )
    line: str = Field(
        ...,
        title="Line / Linked Bills (JSON)",
        description="JSON array linking the payment to bills via LinkedTxn",
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksCreateEstimateConfig(BaseModel):
    """Create a quote/estimate."""

    operation: Literal["create_estimate"] = Field(
        "create_estimate",
        json_schema_extra={
            "const": "create_estimate",
            "ui:hidden": True,
            "x-category": "Sales",
            "x-is-trigger": False,
            "x-display-name": "Create Estimate",
        },
        title="Create Estimate",
    )
    customer_id: str = Field(..., title="Customer Id", description="The customer for the estimate")
    line: str = Field(
        ...,
        title="Line Items (JSON)",
        description="JSON array of estimate Line objects",
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksCreateSalesReceiptConfig(BaseModel):
    """Record a paid-at-time-of-sale transaction."""

    operation: Literal["create_sales_receipt"] = Field(
        "create_sales_receipt",
        json_schema_extra={
            "const": "create_sales_receipt",
            "ui:hidden": True,
            "x-category": "Sales",
            "x-is-trigger": False,
            "x-display-name": "Create Sales Receipt",
        },
        title="Create Sales Receipt",
    )
    customer_id: Optional[str] = Field(
        None, title="Customer Id", description="Optional customer the sale is attributed to"
    )
    line: str = Field(
        ...,
        title="Line Items (JSON)",
        description="JSON array of sales receipt Line objects",
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksCreateCreditMemoConfig(BaseModel):
    """Create a customer credit memo."""

    operation: Literal["create_credit_memo"] = Field(
        "create_credit_memo",
        json_schema_extra={
            "const": "create_credit_memo",
            "ui:hidden": True,
            "x-category": "Sales",
            "x-is-trigger": False,
            "x-display-name": "Create Credit Memo",
        },
        title="Create Credit Memo",
    )
    customer_id: str = Field(..., title="Customer Id", description="The customer to credit")
    line: str = Field(
        ...,
        title="Line Items (JSON)",
        description="JSON array of credit memo Line objects",
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksCreateItemConfig(BaseModel):
    """Create a product/service item."""

    operation: Literal["create_item"] = Field(
        "create_item",
        json_schema_extra={
            "const": "create_item",
            "x-creates-resource": True,
            "x-resource-type": "quickbooks_item",
            "x-resource-id-path": "data.Item.Id",
            "ui:hidden": True,
            "x-category": "Lists",
            "x-is-trigger": False,
            "x-display-name": "Create Item",
        },
        title="Create Item",
    )
    name: str = Field(..., title="Name", description="Unique name of the item")
    item_type: str = Field(
        "Service",
        title="Type",
        description="Item type",
        json_schema_extra={
            "enum": ["Service", "Inventory", "NonInventory"],
            "enumNames": ["Service", "Inventory", "Non-Inventory"],
            "x-enum-searchable": True,
        },
    )
    income_account_id: Optional[str] = Field(
        None,
        title="Income Account",
        description="IncomeAccountRef for the item",
        json_schema_extra={
            "x-resource-type": "quickbooks_account",
            "x-dynamic-options": {
                "field_name": "income_account_id",
                "placeholder": "Select an account...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste account Id",
            }
        },
    )
    unit_price: Optional[str] = Field(
        None, title="Unit Price", description="Default sales price, e.g. 25.00"
    )


class QuickBooksReadItemConfig(BaseModel):
    """Fetch a single item by Id."""

    operation: Literal["read_item"] = Field(
        "read_item",
        json_schema_extra={
            "const": "read_item",
            "ui:hidden": True,
            "x-category": "Lists",
            "x-is-trigger": False,
            "x-display-name": "Read Item",
        },
        title="Read Item",
    )
    item_id: str = Field(
        ...,
        title="Item",
        description="The Id of the item",
        json_schema_extra={
            "x-resource-type": "quickbooks_item",
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select an item...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste item Id",
            }
        },
    )


class QuickBooksUpdateItemConfig(BaseModel):
    """Sparse-update an item (requires Id + SyncToken)."""

    operation: Literal["update_item"] = Field(
        "update_item",
        json_schema_extra={
            "const": "update_item",
            "ui:hidden": True,
            "x-category": "Lists",
            "x-is-trigger": False,
            "x-display-name": "Update Item",
        },
        title="Update Item",
    )
    item_id: str = Field(
        ...,
        title="Item",
        description="The Id of the item",
        json_schema_extra={
            "x-resource-type": "quickbooks_item",
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select an item...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste item Id",
            }
        },
    )
    sync_token: str = Field(
        ..., title="Sync Token", description="Current SyncToken (read the item first)"
    )
    fields: str = Field(
        ...,
        title="Fields to Update (JSON)",
        description="JSON object of fields to patch",
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksCreateAccountConfig(BaseModel):
    """Create a chart-of-accounts entry."""

    operation: Literal["create_account"] = Field(
        "create_account",
        json_schema_extra={
            "const": "create_account",
            "x-creates-resource": True,
            "x-resource-type": "quickbooks_account",
            "x-resource-id-path": "data.Account.Id",
            "ui:hidden": True,
            "x-category": "Lists",
            "x-is-trigger": False,
            "x-display-name": "Create Account",
        },
        title="Create Account",
    )
    name: str = Field(..., title="Name", description="Unique name of the account")
    account_type: Optional[str] = Field(
        None,
        title="Account Type",
        description="e.g. Bank, Expense, Income, Accounts Receivable",
    )


class QuickBooksReadAccountConfig(BaseModel):
    """Fetch a single ledger account by Id."""

    operation: Literal["read_account"] = Field(
        "read_account",
        json_schema_extra={
            "const": "read_account",
            "ui:hidden": True,
            "x-category": "Lists",
            "x-is-trigger": False,
            "x-display-name": "Read Account",
        },
        title="Read Account",
    )
    account_id: str = Field(
        ...,
        title="Account",
        description="The Id of the account",
        json_schema_extra={
            "x-resource-type": "quickbooks_account",
            "x-dynamic-options": {
                "field_name": "account_id",
                "placeholder": "Select an account...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste account Id",
            }
        },
    )


class QuickBooksUpdateAccountConfig(BaseModel):
    """Sparse-update a ledger account (requires Id + SyncToken)."""

    operation: Literal["update_account"] = Field(
        "update_account",
        json_schema_extra={
            "const": "update_account",
            "ui:hidden": True,
            "x-category": "Lists",
            "x-is-trigger": False,
            "x-display-name": "Update Account",
        },
        title="Update Account",
    )
    account_id: str = Field(
        ...,
        title="Account",
        description="The Id of the account",
        json_schema_extra={
            "x-resource-type": "quickbooks_account",
            "x-dynamic-options": {
                "field_name": "account_id",
                "placeholder": "Select an account...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste account Id",
            }
        },
    )
    sync_token: str = Field(
        ..., title="Sync Token", description="Current SyncToken (read the account first)"
    )
    fields: str = Field(
        ...,
        title="Fields to Update (JSON)",
        description="JSON object of fields to patch",
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksCreatePurchaseConfig(BaseModel):
    """Record an expense / cash / credit-card purchase."""

    operation: Literal["create_purchase"] = Field(
        "create_purchase",
        json_schema_extra={
            "const": "create_purchase",
            "ui:hidden": True,
            "x-category": "Expenses",
            "x-is-trigger": False,
            "x-display-name": "Create Purchase",
        },
        title="Create Purchase",
    )
    account_id: str = Field(
        ...,
        title="Payment Account",
        description="AccountRef the purchase is paid from",
        json_schema_extra={
            "x-resource-type": "quickbooks_account",
            "x-dynamic-options": {
                "field_name": "account_id",
                "placeholder": "Select an account...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste account Id",
            }
        },
    )
    payment_type: str = Field(
        "Cash",
        title="Payment Type",
        description="How the purchase was paid",
        json_schema_extra={
            "enum": ["Cash", "Check", "CreditCard"],
            "enumNames": ["Cash", "Check", "Credit Card"],
            "x-enum-searchable": True,
        },
    )
    line: str = Field(
        ...,
        title="Line Items (JSON)",
        description="JSON array of purchase Line objects (account-based expense lines)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksCreateJournalEntryConfig(BaseModel):
    """Post a manual double-entry journal entry."""

    operation: Literal["create_journal_entry"] = Field(
        "create_journal_entry",
        json_schema_extra={
            "const": "create_journal_entry",
            "ui:hidden": True,
            "x-category": "Expenses",
            "x-is-trigger": False,
            "x-display-name": "Create Journal Entry",
        },
        title="Create Journal Entry",
    )
    line: str = Field(
        ...,
        title="Line Items (JSON)",
        description="JSON array of balanced JournalEntryLineDetail debit/credit lines",
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksCreatePurchaseOrderConfig(BaseModel):
    """Create a purchase order to a vendor."""

    operation: Literal["create_purchase_order"] = Field(
        "create_purchase_order",
        json_schema_extra={
            "const": "create_purchase_order",
            "ui:hidden": True,
            "x-category": "Expenses",
            "x-is-trigger": False,
            "x-display-name": "Create Purchase Order",
        },
        title="Create Purchase Order",
    )
    vendor_id: str = Field(
        ...,
        title="Vendor",
        description="The vendor the PO is sent to",
        json_schema_extra={
            "x-resource-type": "quickbooks_vendor",
            "x-dynamic-options": {
                "field_name": "vendor_id",
                "placeholder": "Select a vendor...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste vendor Id",
            }
        },
    )
    ap_account_id: str = Field(
        ...,
        title="AP Account",
        description="APAccountRef (accounts-payable account)",
        json_schema_extra={
            "x-resource-type": "quickbooks_account",
            "x-dynamic-options": {
                "field_name": "ap_account_id",
                "placeholder": "Select an account...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste account Id",
            }
        },
    )
    line: str = Field(
        ...,
        title="Line Items (JSON)",
        description="JSON array of purchase order Line objects",
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksGetReportConfig(BaseModel):
    """Run a financial report."""

    operation: Literal["get_report"] = Field(
        "get_report",
        json_schema_extra={
            "const": "get_report",
            "ui:hidden": True,
            "x-category": "Reports",
            "x-is-trigger": False,
            "x-display-name": "Get Report",
        },
        title="Get Report",
    )
    report_name: str = Field(
        "ProfitAndLoss",
        title="Report",
        description="Which financial report to run",
        json_schema_extra={
            "enum": [
                "ProfitAndLoss",
                "BalanceSheet",
                "CashFlow",
                "GeneralLedger",
                "AgedReceivables",
                "AgedPayables",
                "TrialBalance",
            ],
            "enumNames": [
                "Profit and Loss",
                "Balance Sheet",
                "Cash Flow",
                "General Ledger",
                "Aged Receivables",
                "Aged Payables",
                "Trial Balance",
            ],
            "x-enum-searchable": True,
        },
    )
    start_date: Optional[str] = Field(
        None, title="Start Date", description="Report start date (YYYY-MM-DD)"
    )
    end_date: Optional[str] = Field(
        None, title="End Date", description="Report end date (YYYY-MM-DD)"
    )


class QuickBooksBatchConfig(BaseModel):
    """Bundle up to 30 operations into one request."""

    operation: Literal["batch"] = Field(
        "batch",
        json_schema_extra={
            "const": "batch",
            "ui:hidden": True,
            "x-category": "Advanced",
            "x-is-trigger": False,
            "x-display-name": "Batch Operations",
        },
        title="Batch Operations",
    )
    batch_item_request: str = Field(
        ...,
        title="Batch Items (JSON)",
        description='JSON array of BatchItemRequest objects (each with a bId + operation/entity or Query)',
        json_schema_extra={"ui:widget": "textarea"},
    )


class QuickBooksGetCompanyInfoConfig(BaseModel):
    """Read the connected company's profile."""

    operation: Literal["get_company_info"] = Field(
        "get_company_info",
        json_schema_extra={
            "const": "get_company_info",
            "ui:hidden": True,
            "x-category": "Company",
            "x-is-trigger": False,
            "x-display-name": "Get Company Info",
        },
        title="Get Company Info",
    )


class QuickBooksCustomAccountingRestRequestConfig(BaseModel):
    """Execute any QuickBooks Online Accounting REST request."""

    operation: Literal["execute_custom_accounting_rest_request"] = Field(
        "execute_custom_accounting_rest_request",
        json_schema_extra={
            "const": "execute_custom_accounting_rest_request",
            "ui:hidden": True,
            "x-category": "Advanced",
            "x-is-trigger": False,
            "x-display-name": "Custom Accounting REST Request",
        },
        title="Custom Accounting REST Request",
    )
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = Field(
        "GET",
        title="Method",
        description="HTTP method for the Accounting API request",
    )
    endpoint: str = Field(
        ...,
        title="Endpoint",
        description="Relative Accounting API endpoint, e.g. /invoice, /invoice/123, /reports/ProfitAndLoss, /query",
    )
    query_params: Optional[str] = Field(
        None,
        title="Query Params",
        description="Optional query parameters as a JSON object",
        json_schema_extra={"ui:widget": "textarea"},
    )
    body: Optional[str] = Field(
        None,
        title="Request Body",
        description="Optional JSON request body",
        json_schema_extra={"ui:widget": "textarea"},
    )
    accept: str = Field(
        "application/json",
        title="Accept Header",
        description="Accept header for the request, e.g. application/json or application/pdf",
    )


# ============================================================================
# Webhook Trigger Config (dashboard-registered — no webhook API)
# ============================================================================


class QuickBooksWebhookTriggerBase(BaseModel):
    """Shared config for every QuickBooks webhook trigger.

    QuickBooks webhooks are configured in the Intuit Developer dashboard (there
    is no registerable webhook API), so this only provisions the inbound URL;
    the user pastes it into the dashboard's webhook settings and selects which
    entities/events to receive. The specific (entity, operation) this trigger
    fires on is baked into each generated subclass's ``operation`` — there is no
    entity/event picker field because the operation IS the selection.
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    realm_id: Optional[str] = Field(
        default=None,
        title="Company (Realm) ID",
        description="Only fire for webhook deliveries from this connected QuickBooks company",
        json_schema_extra={
            "ui:loadValue": True,
            "ui:copyable": True,
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Add this URL in the Intuit Developer dashboard (Webhooks) and select the entities/events to receive.",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        default=None,
        title="Verifier Token",
        description="The app's webhook verifier token from the Intuit dashboard (used to verify the intuit-signature header)",
        json_schema_extra={"ui:widget": "password"},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


# One trigger per (entity, operation). QuickBooks POSTs every subscribed
# entity's Create/Update/Delete/Merge/Void/Emailed notifications to the single
# dashboard webhook URL, so each generated trigger filters the inbound delivery
# down to exactly one entity+operation (enforced in filter_trigger_payload).
_MERGE_ENTITIES = {
    "Account", "Class", "Customer", "Department", "Employee", "Item",
    "PaymentMethod", "TaxAgency", "Term", "Vendor",
}
_VOID_ENTITIES = {
    "Bill", "BillPayment", "CreditMemo", "Deposit", "Estimate", "Invoice",
    "JournalEntry", "Payment", "Purchase", "PurchaseOrder", "RefundReceipt",
    "SalesReceipt", "Transfer", "VendorCredit",
}
_EMAILED_ENTITIES = {"Invoice", "Estimate"}
_EVENT_PAST = {
    "Create": "Created", "Update": "Updated", "Delete": "Deleted",
    "Merge": "Merged", "Void": "Voided", "Emailed": "Emailed",
}


def _entity_events(entity: str) -> List[str]:
    events = ["Create", "Update", "Delete"]
    if entity in _MERGE_ENTITIES:
        events.append("Merge")
    if entity in _VOID_ENTITIES:
        events.append("Void")
    if entity in _EMAILED_ENTITIES:
        events.append("Emailed")
    return events


def _spaced(name: str) -> str:
    """'BillPayment' -> 'Bill Payment' for display labels."""
    return re.sub(r"(?<!^)(?=[A-Z])", " ", name)


# op string -> (entity, event lowercase); the runtime match key for deliveries.
WEBHOOK_TRIGGER_OP_MAP: Dict[str, tuple] = {}
_WEBHOOK_TRIGGER_CLASSES: List[type] = []

for _entity in WEBHOOK_ENTITIES:
    for _event in _entity_events(_entity):
        _op = f"on_{_entity.lower()}_{_event.lower()}"
        _display = f"On {_spaced(_entity)} {_EVENT_PAST[_event]}"
        _cls = create_model(
            f"QuickBooksTrigger_{_entity}_{_event}",
            __base__=QuickBooksWebhookTriggerBase,
            operation=(
                Literal[_op],
                Field(
                    _op,
                    title=_display,
                    json_schema_extra={
                        "const": _op,
                        "ui:hidden": True,
                        "x-category": _spaced(_entity),
                        "x-is-trigger": True,
                        "x-display-name": _display,
                        "x-keywords": f"{_spaced(_entity)} {_event} {_EVENT_PAST[_event]} webhook trigger event",
                    },
                ),
            ),
        )
        WEBHOOK_TRIGGER_OP_MAP[_op] = (_entity, _event.lower())
        _WEBHOOK_TRIGGER_CLASSES.append(_cls)


# ============================================================================
# Discriminated Union
# ============================================================================


_QUICKBOOKS_ACTION_CONFIGS = (
    QuickBooksRunQueryConfig,
    QuickBooksCreateInvoiceConfig,
    QuickBooksReadInvoiceConfig,
    QuickBooksUpdateInvoiceConfig,
    QuickBooksDeleteInvoiceConfig,
    QuickBooksSendInvoiceConfig,
    QuickBooksGetInvoicePdfConfig,
    QuickBooksCreateCustomerConfig,
    QuickBooksReadCustomerConfig,
    QuickBooksUpdateCustomerConfig,
    QuickBooksCreateVendorConfig,
    QuickBooksReadVendorConfig,
    QuickBooksUpdateVendorConfig,
    QuickBooksCreateBillConfig,
    QuickBooksReadBillConfig,
    QuickBooksUpdateBillConfig,
    QuickBooksDeleteBillConfig,
    QuickBooksCreatePaymentConfig,
    QuickBooksReadPaymentConfig,
    QuickBooksUpdatePaymentConfig,
    QuickBooksCreateBillPaymentConfig,
    QuickBooksCreateEstimateConfig,
    QuickBooksCreateSalesReceiptConfig,
    QuickBooksCreateCreditMemoConfig,
    QuickBooksCreateItemConfig,
    QuickBooksReadItemConfig,
    QuickBooksUpdateItemConfig,
    QuickBooksCreateAccountConfig,
    QuickBooksReadAccountConfig,
    QuickBooksUpdateAccountConfig,
    QuickBooksCreatePurchaseConfig,
    QuickBooksCreateJournalEntryConfig,
    QuickBooksCreatePurchaseOrderConfig,
    QuickBooksGetReportConfig,
    QuickBooksBatchConfig,
    QuickBooksGetCompanyInfoConfig,
    QuickBooksCustomAccountingRestRequestConfig,
)

QuickBooksConfig = Annotated[
    Union[tuple(_QUICKBOOKS_ACTION_CONFIGS) + tuple(_WEBHOOK_TRIGGER_CLASSES)],
    Discriminator("operation"),
]


class QuickBooksNodeConfig(NodeConfig[QuickBooksConfig, QuickBooksCredential]):
    """Full configuration for the QuickBooks node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _parse_json(value: Optional[str], field_name: str) -> Any:
    """Parse a JSON string config field, raising a clear error if it's invalid."""
    if value is None or value == "":
        return None
    import json

    try:
        return json.loads(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid JSON in '{field_name}': {e}")


def _safe_float(value: Any, field_name: str) -> float:
    """Coerce a user-supplied config value to float, raising a clear error."""
    try:
        return float(value)
    except (ValueError, TypeError):
        raise ValueError(f"'{field_name}' must be a number, got {value!r}")


# ============================================================================
# Node Implementation
# ============================================================================


class QuickBooksNode(WorkflowNode):
    """QuickBooks Online (Intuit Accounting API) automation node."""

    edit_examples = [
        "Create an invoice for a customer when a deal closes",
        "Look up all unpaid invoices with a query",
        "Create a customer record from a new signup",
        "Record a customer payment against an invoice",
        "Run a Profit and Loss report for last month",
        "Trigger a workflow when an invoice is created or updated in QuickBooks",
    ]

    scope_registry = QUICKBOOKS_SCOPES
    connection_evidence = ConnectionEvidence(
        field="customer_id",
        noun="customers",
    )

    @classmethod
    def get_config_model(cls):
        return QuickBooksNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring QuickBooks OAuth token at credential load
        (dropdowns, trigger registration). Intuit access tokens last 1 hour and
        the refresh token rotates on every use, so the freshen choke point
        persists the rotated token under lock."""
        from nodes.core.oauth_refresh import freshen_oauth_credential

        async def _refresh(refresh_token: str):
            return await refresh_access_token(
                refresh_token,
                client_id=(credential_data or {}).get("client_id"),
                client_secret=(credential_data or {}).get("client_secret"),
            )

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=_refresh,
            is_expired=is_token_expired,
            provider="quickbooks",
        )

    # ------------------------------------------------------------------
    # Webhook URL provisioning (dashboard-registered trigger)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Provision trigger-derived values the UI reads lazily."""
        if field_name not in {"webhook_url", "realm_id"}:
            return {"value": None}

        values: Dict[str, Any] = {}

        from utils.credential_loader import load_credential

        credential_id = next((cid for cid in (credential_ids or {}).values() if cid), None)
        credential = await load_credential(pool, user_id, credential_id) if credential_id else None
        realm_id = (credential or {}).get("realm_id")
        if realm_id:
            values["realm_id"] = str(realm_id)

        if field_name == "realm_id":
            return {"value": values.get("realm_id")}

        from utils.webhook_manager import WebhookManager

        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
        )
        values.update({
            "webhook_id": webhook_data.get("webhook_id"),
            "webhook_url": webhook_data.get("webhook_url"),
            "relay_connected": webhook_data.get("relay_connected"),
            "is_production": webhook_data.get("is_production"),
        })
        return {
            "values": values
        }

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify the ``intuit-signature`` header (base64 HMAC-SHA256 of the body)."""
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no verifier token stored — accept (trigger not yet armed)
        sent = headers.get("intuit-signature") or headers.get("Intuit-Signature")
        if not sent:
            return False
        import base64

        digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode()
        return hmac.compare_digest(expected, sent)

    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        """Fire only for the delivery matching this trigger's (entity, operation).

        QuickBooks has no per-subscription event filter — every entity the app
        subscribes to in the Intuit dashboard is POSTed to the one webhook URL —
        so each trigger's baked-in entity+operation is enforced here at delivery
        time. Intuit's current docs describe a CloudEvents-style JSON array,
        while older deliveries used an ``eventNotifications`` envelope; accept
        both. Also honor an optional ``realm_id`` company filter.
        """
        target = WEBHOOK_TRIGGER_OP_MAP.get((config or {}).get("operation"))
        selected_realm_id = str((config or {}).get("realm_id") or "").strip()
        for entity_name, operation, realm_id in cls._iter_webhook_changes(payload):
            entity_ok = target is None or entity_name.lower() == target[0].lower()
            op_ok = target is None or cls._normalize_op(operation) == target[1]
            realm_ok = not selected_realm_id or str(realm_id or "").strip() == selected_realm_id
            if entity_ok and op_ok and realm_ok:
                return True
        return False

    _OP_ALIASES = {
        "create": "create", "created": "create",
        "update": "update", "updated": "update",
        "delete": "delete", "deleted": "delete",
        "merge": "merge", "merged": "merge",
        "void": "void", "voided": "void",
        "emailed": "emailed", "email": "emailed",
    }

    @classmethod
    def _normalize_op(cls, op: Any) -> Optional[str]:
        if not op:
            return None
        return cls._OP_ALIASES.get(str(op).strip().lower())

    @classmethod
    def _iter_webhook_changes(cls, payload: Any):
        """Yield (entity_name, operation, realm_id) for every change in a
        delivery, across both the CloudEvents array and legacy envelope shapes."""
        if isinstance(payload, list):
            for event in payload:
                if isinstance(event, dict):
                    entity, op = cls._extract_entity_op_from_event_type(event.get("type"))
                    if entity:
                        yield entity, op, event.get("intuitaccountid")
            return

        if not isinstance(payload, dict):
            return

        if payload.get("type"):
            entity, op = cls._extract_entity_op_from_event_type(payload.get("type"))
            if entity:
                yield entity, op, payload.get("intuitaccountid")

        for notification in payload.get("eventNotifications") or []:
            if not isinstance(notification, dict):
                continue
            realm_id = notification.get("realmId")
            entities = (notification.get("dataChangeEvent") or {}).get("entities") or []
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                entity_name = entity.get("name") or entity.get("Name")
                if entity_name:
                    yield str(entity_name), entity.get("operation") or entity.get("Operation"), realm_id

    @staticmethod
    def _extract_entity_op_from_event_type(raw_type: Any) -> tuple:
        """Parse a CloudEvents ``type`` (e.g. ``...invoice.create``) into
        ``(entity, operation)``; returns ``(None, None)`` when unparseable."""
        if not raw_type:
            return None, None
        parts = [str(part).strip() for part in str(raw_type).split(".") if str(part).strip()]
        if len(parts) < 2:
            return None, None
        action_tokens = {
            "create", "created", "update", "updated", "delete", "deleted",
            "merge", "merged", "void", "voided", "emailed", "email",
        }
        for index, token in enumerate(parts):
            if token.lower() in action_tokens and index > 0:
                return parts[index - 1], token
        return parts[-2], parts[-1]

    # ------------------------------------------------------------------
    # Dynamic options (top-level listable resources via the /query endpoint)
    # ------------------------------------------------------------------
    # Each dynamic field maps to a queryable QuickBooks entity + the field on
    # that entity used as the human-readable label.
    _DYNAMIC_ENTITY_MAP = {
        "customer_id": ("Customer", "DisplayName"),
        "vendor_id": ("Vendor", "DisplayName"),
        "item_id": ("Item", "Name"),
        "account_id": ("Account", "Name"),
        "income_account_id": ("Account", "Name"),
        "ap_account_id": ("Account", "Name"),
    }

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        mapping = cls._DYNAMIC_ENTITY_MAP.get(field_name)
        if not mapping:
            return {"options": []}
        entity, label_field = mapping

        credential = credential_data or {}
        realm_id = credential.get("realm_id")
        is_sandbox = bool(credential.get("is_sandbox"))
        access_token = credential.get("access_token")
        if not realm_id or not access_token:
            return {"options": []}

        page_size = 200

        async def fetch_page(cursor: Optional[str]):
            try:
                start_position = int(cursor or "1")
            except ValueError:
                start_position = 1
            query = (
                f"SELECT Id, {label_field} FROM {entity} "
                f"STARTPOSITION {start_position} MAXRESULTS {page_size}"
            )
            result = await _quickbooks_request(
                access_token=access_token,
                realm_id=realm_id,
                is_sandbox=is_sandbox,
                method="GET",
                endpoint="/query",
                params={"query": query},
                action_name=f"list_{entity.lower()}",
            )
            if result.get("status") != "success":
                return [], None
            data = result.get("data") or {}
            rows = (data.get("QueryResponse") or {}).get(entity) or []
            if isinstance(rows, dict):
                rows = [rows]
            options = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row_id = row.get("Id")
                label = row.get(label_field) or f"{entity} {row_id}"
                if row_id is not None:
                    options.append({"label": str(label), "value": str(row_id)})
            next_cursor = str(start_position + page_size) if len(options) >= page_size else None
            return options, next_cursor

        return await load_paginated_options(
            fetch_page,
            page_token=page_token,
            search=search,
            fields=("label", "value"),
            log_label=f"QuickBooksNode.{field_name}",
        )

    # ------------------------------------------------------------------
    # Access token (OAuth with refresh)
    # ------------------------------------------------------------------
    async def _get_access_token(self, credentials: QuickBooksOAuthCredential) -> str:
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token

        cred_dict = credentials.model_dump()
        async def _refresh(refresh_token: str):
            return await refresh_access_token(
                refresh_token,
                client_id=cred_dict.get("client_id"),
                client_secret=cred_dict.get("client_secret"),
            )
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=_refresh,
            is_expired=is_token_expired,
            provider="quickbooks",
            caller_path="execute",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        credentials.client_id = cred_dict.get("client_id")
        credentials.client_secret = cred_dict.get("client_secret")
        return token

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, QuickBooksNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, QuickBooksWebhookTriggerBase):
            return {
                "status": "success",
                "action": op.operation,
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Connect your QuickBooks account.")

        access_token = await self._get_access_token(credentials)
        realm_id = credentials.realm_id
        is_sandbox = bool(credentials.is_sandbox)

        handlers = {
            "run_query": self._run_query,
            "create_invoice": self._create_invoice,
            "read_invoice": self._read_invoice,
            "update_invoice": self._update_invoice,
            "delete_invoice": self._delete_invoice,
            "send_invoice": self._send_invoice,
            "get_invoice_pdf": self._get_invoice_pdf,
            "create_customer": self._create_customer,
            "read_customer": self._read_customer,
            "update_customer": self._update_customer,
            "create_vendor": self._create_vendor,
            "read_vendor": self._read_vendor,
            "update_vendor": self._update_vendor,
            "create_bill": self._create_bill,
            "read_bill": self._read_bill,
            "update_bill": self._update_bill,
            "delete_bill": self._delete_bill,
            "create_payment": self._create_payment,
            "read_payment": self._read_payment,
            "update_payment": self._update_payment,
            "create_bill_payment": self._create_bill_payment,
            "create_estimate": self._create_estimate,
            "create_sales_receipt": self._create_sales_receipt,
            "create_credit_memo": self._create_credit_memo,
            "create_item": self._create_item,
            "read_item": self._read_item,
            "update_item": self._update_item,
            "create_account": self._create_account,
            "read_account": self._read_account,
            "update_account": self._update_account,
            "create_purchase": self._create_purchase,
            "create_journal_entry": self._create_journal_entry,
            "create_purchase_order": self._create_purchase_order,
            "get_report": self._get_report,
            "batch": self._batch,
            "get_company_info": self._get_company_info,
            "execute_custom_accounting_rest_request": self._custom_accounting_rest_request,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        try:
            result = await handler(op, access_token, realm_id, is_sandbox)
        except ValueError as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            return {
                "status": "error",
                "action": op.operation,
                "error": msg,
                "status_code": 400,
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Entity helpers (read / sparse-update / delete share the same shape)
    # ------------------------------------------------------------------
    async def _request(
        self,
        access_token: str,
        realm_id: str,
        is_sandbox: bool,
        method: str,
        endpoint: str,
        action_name: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Any] = None,
        accept: str = "application/json",
    ) -> Dict[str, Any]:
        return await _quickbooks_request(
            access_token=access_token,
            realm_id=realm_id,
            is_sandbox=is_sandbox,
            method=method,
            endpoint=endpoint,
            action_name=action_name,
            params=params,
            json_body=json_body,
            accept=accept,
        )

    async def _read_entity(self, access_token, realm_id, is_sandbox, entity, entity_id, action):
        return await self._request(
            access_token, realm_id, is_sandbox, "GET", f"/{entity}/{entity_id}", action
        )

    async def _sparse_update(
        self, access_token, realm_id, is_sandbox, entity, entity_id, sync_token, fields, action
    ):
        body = {"Id": entity_id, "SyncToken": sync_token, "sparse": True}
        patch = _parse_json(fields, "fields")
        if isinstance(patch, dict):
            body.update(patch)
        return await self._request(
            access_token, realm_id, is_sandbox, "POST", f"/{entity}",
            action, params={"operation": "update"}, json_body=body,
        )

    async def _delete_entity(
        self, access_token, realm_id, is_sandbox, entity, entity_id, sync_token, action
    ):
        return await self._request(
            access_token, realm_id, is_sandbox, "POST", f"/{entity}", action,
            params={"operation": "delete"},
            json_body={"Id": entity_id, "SyncToken": sync_token},
        )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    async def _run_query(self, c: QuickBooksRunQueryConfig, token, realm, sandbox):
        return await self._request(
            token, realm, sandbox, "GET", "/query", "run_query", params={"query": c.query}
        )

    async def _create_invoice(self, c: QuickBooksCreateInvoiceConfig, token, realm, sandbox):
        body = {"CustomerRef": {"value": c.customer_id}, "Line": _parse_json(c.line, "line")}
        return await self._request(token, realm, sandbox, "POST", "/invoice", "create_invoice", json_body=body)

    async def _read_invoice(self, c: QuickBooksReadInvoiceConfig, token, realm, sandbox):
        return await self._read_entity(token, realm, sandbox, "invoice", c.invoice_id, "read_invoice")

    async def _update_invoice(self, c: QuickBooksUpdateInvoiceConfig, token, realm, sandbox):
        return await self._sparse_update(
            token, realm, sandbox, "invoice", c.invoice_id, c.sync_token, c.fields, "update_invoice"
        )

    async def _delete_invoice(self, c: QuickBooksDeleteInvoiceConfig, token, realm, sandbox):
        return await self._delete_entity(
            token, realm, sandbox, "invoice", c.invoice_id, c.sync_token, "delete_invoice"
        )

    async def _send_invoice(self, c: QuickBooksSendInvoiceConfig, token, realm, sandbox):
        params = {"sendTo": c.send_to} if c.send_to else None
        return await self._request(
            token, realm, sandbox, "POST", f"/invoice/{c.invoice_id}/send",
            "send_invoice", params=params,
        )

    async def _get_invoice_pdf(self, c: QuickBooksGetInvoicePdfConfig, token, realm, sandbox):
        return await self._request(
            token, realm, sandbox, "GET", f"/invoice/{c.invoice_id}/pdf",
            "get_invoice_pdf", accept="application/pdf",
        )

    async def _create_customer(self, c: QuickBooksCreateCustomerConfig, token, realm, sandbox):
        body: Dict[str, Any] = {"DisplayName": c.display_name}
        if c.company_name:
            body["CompanyName"] = c.company_name
        if c.email:
            body["PrimaryEmailAddr"] = {"Address": c.email}
        if c.phone:
            body["PrimaryPhone"] = {"FreeFormNumber": c.phone}
        return await self._request(token, realm, sandbox, "POST", "/customer", "create_customer", json_body=body)

    async def _read_customer(self, c: QuickBooksReadCustomerConfig, token, realm, sandbox):
        return await self._read_entity(token, realm, sandbox, "customer", c.customer_id, "read_customer")

    async def _update_customer(self, c: QuickBooksUpdateCustomerConfig, token, realm, sandbox):
        return await self._sparse_update(
            token, realm, sandbox, "customer", c.customer_id, c.sync_token, c.fields, "update_customer"
        )

    async def _create_vendor(self, c: QuickBooksCreateVendorConfig, token, realm, sandbox):
        body: Dict[str, Any] = {"DisplayName": c.display_name}
        if c.company_name:
            body["CompanyName"] = c.company_name
        if c.email:
            body["PrimaryEmailAddr"] = {"Address": c.email}
        return await self._request(token, realm, sandbox, "POST", "/vendor", "create_vendor", json_body=body)

    async def _read_vendor(self, c: QuickBooksReadVendorConfig, token, realm, sandbox):
        return await self._read_entity(token, realm, sandbox, "vendor", c.vendor_id, "read_vendor")

    async def _update_vendor(self, c: QuickBooksUpdateVendorConfig, token, realm, sandbox):
        return await self._sparse_update(
            token, realm, sandbox, "vendor", c.vendor_id, c.sync_token, c.fields, "update_vendor"
        )

    async def _create_bill(self, c: QuickBooksCreateBillConfig, token, realm, sandbox):
        body = {"VendorRef": {"value": c.vendor_id}, "Line": _parse_json(c.line, "line")}
        return await self._request(token, realm, sandbox, "POST", "/bill", "create_bill", json_body=body)

    async def _read_bill(self, c: QuickBooksReadBillConfig, token, realm, sandbox):
        return await self._read_entity(token, realm, sandbox, "bill", c.bill_id, "read_bill")

    async def _update_bill(self, c: QuickBooksUpdateBillConfig, token, realm, sandbox):
        return await self._sparse_update(
            token, realm, sandbox, "bill", c.bill_id, c.sync_token, c.fields, "update_bill"
        )

    async def _delete_bill(self, c: QuickBooksDeleteBillConfig, token, realm, sandbox):
        return await self._delete_entity(token, realm, sandbox, "bill", c.bill_id, c.sync_token, "delete_bill")

    async def _create_payment(self, c: QuickBooksCreatePaymentConfig, token, realm, sandbox):
        body: Dict[str, Any] = {
            "CustomerRef": {"value": c.customer_id},
            "TotalAmt": _safe_float(c.total_amount, "total_amount"),
        }
        line = _parse_json(c.line, "line")
        if line is not None:
            body["Line"] = line
        return await self._request(token, realm, sandbox, "POST", "/payment", "create_payment", json_body=body)

    async def _read_payment(self, c: QuickBooksReadPaymentConfig, token, realm, sandbox):
        return await self._read_entity(token, realm, sandbox, "payment", c.payment_id, "read_payment")

    async def _update_payment(self, c: QuickBooksUpdatePaymentConfig, token, realm, sandbox):
        return await self._sparse_update(
            token, realm, sandbox, "payment", c.payment_id, c.sync_token, c.fields, "update_payment"
        )

    async def _create_bill_payment(self, c: QuickBooksCreateBillPaymentConfig, token, realm, sandbox):
        body = {
            "VendorRef": {"value": c.vendor_id},
            "TotalAmt": _safe_float(c.total_amount, "total_amount"),
            "PayType": c.pay_type,
            "Line": _parse_json(c.line, "line"),
        }
        # QuickBooks requires the drawn-from account nested under a PayType-specific
        # object (CheckPayment.BankAccountRef / CreditCardPayment.CCAccountRef).
        if c.pay_type == "CreditCard":
            body["CreditCardPayment"] = {"CCAccountRef": {"value": c.account_id}}
        else:
            body["CheckPayment"] = {"BankAccountRef": {"value": c.account_id}}
        return await self._request(token, realm, sandbox, "POST", "/billpayment", "create_bill_payment", json_body=body)

    async def _create_estimate(self, c: QuickBooksCreateEstimateConfig, token, realm, sandbox):
        body = {"CustomerRef": {"value": c.customer_id}, "Line": _parse_json(c.line, "line")}
        return await self._request(token, realm, sandbox, "POST", "/estimate", "create_estimate", json_body=body)

    async def _create_sales_receipt(self, c: QuickBooksCreateSalesReceiptConfig, token, realm, sandbox):
        body: Dict[str, Any] = {"Line": _parse_json(c.line, "line")}
        if c.customer_id:
            body["CustomerRef"] = {"value": c.customer_id}
        return await self._request(token, realm, sandbox, "POST", "/salesreceipt", "create_sales_receipt", json_body=body)

    async def _create_credit_memo(self, c: QuickBooksCreateCreditMemoConfig, token, realm, sandbox):
        body = {"CustomerRef": {"value": c.customer_id}, "Line": _parse_json(c.line, "line")}
        return await self._request(token, realm, sandbox, "POST", "/creditmemo", "create_credit_memo", json_body=body)

    async def _create_item(self, c: QuickBooksCreateItemConfig, token, realm, sandbox):
        body: Dict[str, Any] = {"Name": c.name, "Type": c.item_type}
        if c.income_account_id:
            body["IncomeAccountRef"] = {"value": c.income_account_id}
        if c.unit_price:
            body["UnitPrice"] = _safe_float(c.unit_price, "unit_price")
        return await self._request(token, realm, sandbox, "POST", "/item", "create_item", json_body=body)

    async def _read_item(self, c: QuickBooksReadItemConfig, token, realm, sandbox):
        return await self._read_entity(token, realm, sandbox, "item", c.item_id, "read_item")

    async def _update_item(self, c: QuickBooksUpdateItemConfig, token, realm, sandbox):
        return await self._sparse_update(
            token, realm, sandbox, "item", c.item_id, c.sync_token, c.fields, "update_item"
        )

    async def _create_account(self, c: QuickBooksCreateAccountConfig, token, realm, sandbox):
        body: Dict[str, Any] = {"Name": c.name}
        if c.account_type:
            body["AccountType"] = c.account_type
        return await self._request(token, realm, sandbox, "POST", "/account", "create_account", json_body=body)

    async def _read_account(self, c: QuickBooksReadAccountConfig, token, realm, sandbox):
        return await self._read_entity(token, realm, sandbox, "account", c.account_id, "read_account")

    async def _update_account(self, c: QuickBooksUpdateAccountConfig, token, realm, sandbox):
        return await self._sparse_update(
            token, realm, sandbox, "account", c.account_id, c.sync_token, c.fields, "update_account"
        )

    async def _create_purchase(self, c: QuickBooksCreatePurchaseConfig, token, realm, sandbox):
        body = {
            "AccountRef": {"value": c.account_id},
            "PaymentType": c.payment_type,
            "Line": _parse_json(c.line, "line"),
        }
        return await self._request(token, realm, sandbox, "POST", "/purchase", "create_purchase", json_body=body)

    async def _create_journal_entry(self, c: QuickBooksCreateJournalEntryConfig, token, realm, sandbox):
        body = {"Line": _parse_json(c.line, "line")}
        return await self._request(token, realm, sandbox, "POST", "/journalentry", "create_journal_entry", json_body=body)

    async def _create_purchase_order(self, c: QuickBooksCreatePurchaseOrderConfig, token, realm, sandbox):
        body = {
            "VendorRef": {"value": c.vendor_id},
            "APAccountRef": {"value": c.ap_account_id},
            "Line": _parse_json(c.line, "line"),
        }
        return await self._request(token, realm, sandbox, "POST", "/purchaseorder", "create_purchase_order", json_body=body)

    async def _get_report(self, c: QuickBooksGetReportConfig, token, realm, sandbox):
        params = {"start_date": c.start_date, "end_date": c.end_date}
        return await self._request(
            token, realm, sandbox, "GET", f"/reports/{c.report_name}", "get_report", params=params
        )

    async def _batch(self, c: QuickBooksBatchConfig, token, realm, sandbox):
        body = {"BatchItemRequest": _parse_json(c.batch_item_request, "batch_item_request")}
        return await self._request(token, realm, sandbox, "POST", "/batch", "batch", json_body=body)

    async def _get_company_info(self, c: QuickBooksGetCompanyInfoConfig, token, realm, sandbox):
        return await self._request(
            token, realm, sandbox, "GET", f"/companyinfo/{realm}", "get_company_info"
        )

    async def _custom_accounting_rest_request(
        self, c: QuickBooksCustomAccountingRestRequestConfig, token, realm, sandbox
    ):
        query_params = _parse_json(c.query_params, "query_params") if c.query_params else None
        body = _parse_json(c.body, "body") if c.body else None
        endpoint = c.endpoint if c.endpoint.startswith("/") else f"/{c.endpoint}"
        return await self._request(
            token,
            realm,
            sandbox,
            c.method,
            endpoint,
            "execute_custom_accounting_rest_request",
            params=query_params if isinstance(query_params, dict) else None,
            json_body=body,
            accept=c.accept,
        )

# ============================================================================
# HTTP Request Helper (module-level so dynamic options can reuse it)
# ============================================================================


async def _quickbooks_request(
    access_token: str,
    realm_id: str,
    is_sandbox: bool,
    method: str,
    endpoint: str,
    action_name: str = "request",
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    accept: str = "application/json",
) -> Dict[str, Any]:
    """Make an authenticated QuickBooks Accounting API request."""
    base = QUICKBOOKS_API_BASE_SANDBOX if is_sandbox else QUICKBOOKS_API_BASE_PROD
    url = f"{base}/{realm_id}{endpoint}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": accept,
    }
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        if isinstance(json_body, dict):
            json_body = {k: v for k, v in json_body.items() if v is not None}

    request_params = {"minorversion": QUICKBOOKS_MINOR_VERSION}
    if params:
        request_params.update({k: v for k, v in params.items() if v not in (None, "")})

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=request_params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                message = _extract_error(response)
                logger.error(f"[QuickBooksNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            data = _parse_success_response(response, accept, action_name)
            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[QuickBooksNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


def _parse_success_response(response, accept: str, action_name: str = "download") -> Any:
    if accept == "application/pdf":
        # Hand back the raw bytes as a BinaryOutput marker; the executor stores
        # them in R2 and swaps in a usable {url, mime_type, ...} file reference
        # (base64-in-output is unusable media — enforced by CI).
        return BinaryOutput(
            data=response.content,
            content_type="application/pdf",
            filename=f"{action_name}.pdf",
        )
    if response.status_code == 204 or not response.content:
        return {"success": True}
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def _extract_error(response) -> str:
    """Pull a human-readable message out of an Intuit error response."""
    try:
        err = response.json()
    except Exception:
        return response.text
    fault = err.get("Fault") if isinstance(err, dict) else None
    if isinstance(fault, dict):
        errors = fault.get("Error") or []
        if errors and isinstance(errors[0], dict):
            e0 = errors[0]
            detail = e0.get("Detail") or e0.get("Message") or ""
            return detail or str(err)
    if isinstance(err, dict):
        return err.get("message") or err.get("error_description") or str(err)
    return str(err)
