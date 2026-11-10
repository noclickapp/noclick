"""BILL AP/AR v3: vendors, bills, approval routing, payments and customers.

Contract: https://developer.bill.com/openapi/bill-v3-api.json (version 1).
AP/AR accepts devKey + sessionId, not the Spend & Expense apiToken. Sessions
expire after 35 minutes idle; users supply a new session, never their password.
Payment scheduling requires an MFA-trusted session. No login or MFA side effects.
"""

import base64
import hashlib
import hmac
import json
from uuid import uuid4
from datetime import date
from typing import Annotated, Any, ClassVar, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase


BillCurrency = Literal[
    "AED",
    "AFN",
    "ALL",
    "AMD",
    "ANG",
    "AOA",
    "ARS",
    "AUD",
    "AWG",
    "AZN",
    "BAM",
    "BBD",
    "BDT",
    "BGN",
    "BHD",
    "BIF",
    "BMD",
    "BND",
    "BOB",
    "BRL",
    "BSD",
    "BTN",
    "BWP",
    "BYN",
    "BZD",
    "CAD",
    "CDF",
    "CHF",
    "CLP",
    "CNY",
    "COP",
    "CRC",
    "CUC",
    "CUP",
    "CVE",
    "CZK",
    "DJF",
    "DKK",
    "DOP",
    "DZD",
    "EGP",
    "ERN",
    "ETB",
    "EUR",
    "FJD",
    "FKP",
    "GBP",
    "GEL",
    "GGP",
    "GHS",
    "GIP",
    "GMD",
    "GNF",
    "GTQ",
    "GYD",
    "HKD",
    "HNL",
    "HRK",
    "HTG",
    "HUF",
    "IDR",
    "ILS",
    "IMP",
    "INR",
    "IQD",
    "IRR",
    "ISK",
    "JEP",
    "JMD",
    "JOD",
    "JPY",
    "KES",
    "KGS",
    "KHR",
    "KMF",
    "KPW",
    "KRW",
    "KWD",
    "KYD",
    "KZT",
    "LAK",
    "LBP",
    "LKR",
    "LRD",
    "LSL",
    "LYD",
    "MAD",
    "MDL",
    "MGA",
    "MKD",
    "MMK",
    "MNT",
    "MOP",
    "MRU",
    "MUR",
    "MVR",
    "MWK",
    "MXN",
    "MYR",
    "MZN",
    "NAD",
    "NGN",
    "NIO",
    "NOK",
    "NPR",
    "NZD",
    "OMR",
    "PAB",
    "PEN",
    "PGK",
    "PHP",
    "PKR",
    "PLN",
    "PYG",
    "QAR",
    "RON",
    "RSD",
    "RUB",
    "RWF",
    "SAR",
    "SBD",
    "SCR",
    "SDG",
    "SEK",
    "SGD",
    "SHP",
    "SLE",
    "SLL",
    "SOS",
    "SPL",
    "SRD",
    "STN",
    "SVC",
    "SYP",
    "SZL",
    "THB",
    "TJS",
    "TMT",
    "TND",
    "TOP",
    "TRY",
    "TTD",
    "TVD",
    "TWD",
    "TZS",
    "UAH",
    "UGX",
    "USD",
    "UYU",
    "UZS",
    "VEF",
    "VND",
    "VUV",
    "WST",
    "XAF",
    "XCD",
    "XDR",
    "XOF",
    "XPF",
    "YER",
    "ZAR",
    "ZMW",
    "ZWD",
]


class BILLSessionCredential(BaseModel):
    credential_type: Literal["bill_session"] = Field(
        "bill_session", json_schema_extra={"ui:hidden": True}
    )
    dev_key: str = Field(
        ..., title="Developer Key", json_schema_extra={"ui:widget": "password"}
    )
    session_id: str = Field(
        ..., title="Session ID", json_schema_extra={"ui:widget": "password"}
    )
    environment: Literal["production", "sandbox"] = Field(
        "production", title="Environment"
    )

    model_config = ConfigDict(
        title="BILL AP/AR Session",
        json_schema_extra={
            "x-credential-url": "https://developer.bill.com/reference/login",
            "x-credential-instructions": "Paste your BILL AP/AR developer key and its matching session ID from POST /v3/login. Sessions expire after 35 minutes of inactivity; replace the session ID when it expires. Scheduling payments requires an MFA-trusted session. Spend & Expense API tokens do not work for AP/AR. Select the environment where the session was created.",
        }
    )


class BillRequestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    json_fields: ClassVar[dict[str, str]] = {}


class BillListVendorsConfig(BillRequestConfig):
    """Get list of vendors."""

    operation: Literal["list_vendors"] = Field(
        "list_vendors",
        title="Get list of vendors",
        json_schema_extra={
            "const": "list_vendors",
            "ui:hidden": True,
            "x-category": "Vendors",
            "x-is-trigger": False,
        },
    )
    max_results: int | None = Field(
        None, title="Max", description="Maximum number of results", ge=1, le=100
    )
    sort: str | None = Field(
        None,
        title="Sort",
        description="Field name and sort order. Both simple and compound sorting is available.",
    )
    filters: str | None = Field(
        None,
        title="Filters",
        description="Field name, operator, and value. Both simple and compound filtering is available.",
    )
    page: str | None = Field(None, title="Page", description="Next page of results.")


class BillCreateVendorConfig(BillRequestConfig):
    """Create a vendor."""

    operation: Literal["create_vendor"] = Field(
        "create_vendor",
        title="Create a vendor",
        json_schema_extra={
            "const": "create_vendor",
            "ui:hidden": True,
            "x-category": "Vendors",
            "x-is-trigger": False,
        },
    )
    name: str = Field(
        ..., title="Name", description="Vendor name", min_length=1, max_length=100
    )
    short_name: str | None = Field(
        None, title="Short Name", description="Vendor short name", max_length=40
    )
    account_number: str | None = Field(
        None,
        title="Account Number",
        description="User account number set by the vendor. Set this field as the billing statement account number for vendor services such as utility or credit card bills.",
    )
    account_type: Literal["NONE", "BUSINESS", "PERSON"] | None = Field(
        None, title="Account Type", description="Vendor account type"
    )
    email: str | None = Field(None, title="Email", description="Vendor email address")
    phone: str | None = Field(None, title="Phone", description="Vendor phone number")
    address: str = Field(
        ...,
        title="Address",
        description="Vendor address information JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    payment_information: str | None = Field(
        None,
        title="Payment Information",
        description="Vendor payment information JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    additional_info: str | None = Field(
        None,
        title="Additional Info",
        description="Vendor additional information JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    bill_currency: BillCurrency | None = Field(
        None,
        title="Bill Currency",
        description="Bill currency. Three-letter abbreviation in the ISO 4217 format.",
    )
    auto_pay: str | None = Field(
        None,
        title="Auto Pay",
        description="Vendor auto-pay information. JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    json_fields: ClassVar[dict[str, str]] = {
        "address": "object",
        "payment_information": "object",
        "additional_info": "object",
        "auto_pay": "object",
    }


class BillGetVendorConfig(BillRequestConfig):
    """Get vendor details."""

    operation: Literal["get_vendor"] = Field(
        "get_vendor",
        title="Get vendor details",
        json_schema_extra={
            "const": "get_vendor",
            "ui:hidden": True,
            "x-category": "Vendors",
            "x-is-trigger": False,
        },
    )
    vendor_id: str = Field(
        ...,
        title="Vendor ID",
        description="BILL-generated ID of the vendor. The value begins with `009`.",
        min_length=1,
    )


class BillUpdateVendorConfig(BillRequestConfig):
    """Update a vendor."""

    operation: Literal["update_vendor"] = Field(
        "update_vendor",
        title="Update a vendor",
        json_schema_extra={
            "const": "update_vendor",
            "ui:hidden": True,
            "x-category": "Vendors",
            "x-is-trigger": False,
        },
    )
    vendor_id: str = Field(
        ...,
        title="Vendor ID",
        description="BILL-generated ID of the vendor. The value begins with `009`.",
        min_length=1,
    )
    name: str | None = Field(
        None, title="Name", description="Vendor name", max_length=100
    )
    short_name: str | None = Field(
        None, title="Short Name", description="Vendor short name", max_length=40
    )
    account_number: str | None = Field(
        None,
        title="Account Number",
        description="User account number set by the vendor. Set this field as the billing statement account number for vendor services such as utility or credit card bills.",
    )
    account_type: Literal["NONE", "BUSINESS", "PERSON"] | None = Field(
        None, title="Account Type", description="Vendor account type"
    )
    email: str | None = Field(None, title="Email", description="Vendor email address")
    phone: str | None = Field(None, title="Phone", description="Vendor phone number")
    address: str | None = Field(
        None,
        title="Address",
        description="Vendor address information JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    payment_information: str | None = Field(
        None,
        title="Payment Information",
        description="Vendor payment information JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    additional_info: str | None = Field(
        None,
        title="Additional Info",
        description="Vendor additional information JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    bill_currency: BillCurrency | None = Field(
        None,
        title="Bill Currency",
        description="Bill currency. Three-letter abbreviation in the ISO 4217 format.",
    )
    auto_pay: str | None = Field(
        None,
        title="Auto Pay",
        description="Vendor auto-pay information. JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    json_fields: ClassVar[dict[str, str]] = {
        "address": "object",
        "payment_information": "object",
        "additional_info": "object",
        "auto_pay": "object",
    }


class BillListBillsConfig(BillRequestConfig):
    """Get list of bills."""

    operation: Literal["list_bills"] = Field(
        "list_bills",
        title="Get list of bills",
        json_schema_extra={
            "const": "list_bills",
            "ui:hidden": True,
            "x-category": "Bills",
            "x-is-trigger": False,
        },
    )
    max_results: int | None = Field(
        None, title="Max", description="Maximum number of results", ge=1, le=100
    )
    sort: str | None = Field(
        None,
        title="Sort",
        description="Field name and sort order. Both simple and compound sorting is available.",
    )
    filters: str | None = Field(
        None,
        title="Filters",
        description="Field name, operator, and value. Both simple and compound filtering is available.",
    )
    page: str | None = Field(None, title="Page", description="Next page of results.")


class BillCreateBillConfig(BillRequestConfig):
    """Create a bill."""

    operation: Literal["create_bill"] = Field(
        "create_bill",
        title="Create a bill",
        json_schema_extra={
            "const": "create_bill",
            "ui:hidden": True,
            "x-category": "Bills",
            "x-is-trigger": False,
        },
    )
    vendor_id: str = Field(
        ...,
        title="Vendor ID",
        description="BILL-generated ID of the vendor. The value begins with `009`.",
        min_length=1,
    )
    description: str | None = Field(
        None, title="Description", description="Bill description", max_length=4000
    )
    due_date: date = Field(
        ...,
        title="Due Date",
        description="Bill due date. The value is in the `yyyy-MM-dd` format.",
    )
    payment_term_id: str | None = Field(None, title="Payment Term ID", description="")
    bill_line_items: str = Field(
        ...,
        title="Bill Line Items",
        description="Bill line items information JSON array.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    invoice: str = Field(
        ...,
        title="Invoice",
        description="Invoice information JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    pay_from_chart_of_account_id: str | None = Field(
        None,
        title="Pay From Chart Of Account ID",
        description="BILL-generated ID of the chart of accounts for the bill payment. The value begins with `0ca`.",
    )
    classifications: str | None = Field(
        None,
        title="Classifications",
        description="General ledger classifications information for the bill JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    vendor_credits: str | None = Field(
        None,
        title="Vendor Credits",
        description="Vendor credits applied to the bill JSON array.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    purchase_order_number: str | None = Field(
        None,
        title="Purchase Order Number",
        description="Purchase order number linked with the bill",
    )
    bill_approvals: bool | None = Field(
        None,
        title="Bill Approvals",
        description="Set as `true` for BILL to add approvals information in the response.",
    )
    allow_duplicate_invoice_number: bool | None = Field(
        None,
        title="Allow Duplicate Invoice Number",
        description="Set as `false` to reject the request when the bill's `invoice.invoiceNumber` duplicates an existing invoice number for the vendor. Defaults to `true`, which allows duplicate invoice numbers.",
    )
    json_fields: ClassVar[dict[str, str]] = {
        "bill_line_items": "array",
        "invoice": "object",
        "classifications": "object",
        "vendor_credits": "array",
    }


class BillGetBillConfig(BillRequestConfig):
    """Get bill details."""

    operation: Literal["get_bill"] = Field(
        "get_bill",
        title="Get bill details",
        json_schema_extra={
            "const": "get_bill",
            "ui:hidden": True,
            "x-category": "Bills",
            "x-is-trigger": False,
        },
    )
    bill_id: str = Field(
        ...,
        title="Bill ID",
        description="BILL-generated ID of the bill. The value begins with `00n`.",
        pattern="^00n[a-zA-Z0-9]{17}$",
        min_length=1,
    )


class BillUpdateBillConfig(BillRequestConfig):
    """Update a bill."""

    operation: Literal["update_bill"] = Field(
        "update_bill",
        title="Update a bill",
        json_schema_extra={
            "const": "update_bill",
            "ui:hidden": True,
            "x-category": "Bills",
            "x-is-trigger": False,
        },
    )
    bill_id: str = Field(
        ...,
        title="Bill ID",
        description="BILL-generated ID of the bill. The value begins with `00n`.",
        min_length=1,
    )
    vendor_id: str | None = Field(
        None,
        title="Vendor ID",
        description="BILL-generated ID of the vendor. The value begins with `009`.",
    )
    description: str | None = Field(
        None, title="Description", description="Bill description", max_length=4000
    )
    due_date: date | None = Field(
        None,
        title="Due Date",
        description="Bill due date. The value is in the `yyyy-MM-dd` format.",
    )
    # BILL's updateBill example changes line items without paymentTermId:
    # https://developer.bill.com/reference/updatebill
    payment_term_id: str | None = Field(None, title="Payment Term ID")
    bill_line_items: str | None = Field(
        None,
        title="Bill Line Items",
        description="Bill line items information JSON array.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    invoice: str | None = Field(
        None,
        title="Invoice",
        description="Invoice information JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    pay_from_chart_of_account_id: str | None = Field(
        None,
        title="Pay From Chart Of Account ID",
        description="BILL-generated ID of the chart of accounts for the bill payment. The value begins with `0ca`.",
    )
    classifications: str | None = Field(
        None,
        title="Classifications",
        description="General ledger classifications information for the bill JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    vendor_credits: str | None = Field(
        None,
        title="Vendor Credits",
        description="Vendor credits applied to the bill JSON array.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    purchase_order_number: str | None = Field(
        None,
        title="Purchase Order Number",
        description="Purchase order number linked with the bill",
    )
    bill_approvals: bool | None = Field(
        None,
        title="Bill Approvals",
        description="Set as `true` for BILL to add approvals information in the response.",
    )
    policy_rematch: bool | None = Field(
        None,
        title="Policy Rematch",
        description="Rule for whether BILL re-matches the updated bill against your approval policies. The default value is `false`.",
    )
    json_fields: ClassVar[dict[str, str]] = {
        "bill_line_items": "array",
        "invoice": "object",
        "classifications": "object",
        "vendor_credits": "array",
    }


class BillListCustomersConfig(BillRequestConfig):
    """Get list of customers."""

    operation: Literal["list_customers"] = Field(
        "list_customers",
        title="Get list of customers",
        json_schema_extra={
            "const": "list_customers",
            "ui:hidden": True,
            "x-category": "Customers",
            "x-is-trigger": False,
        },
    )
    max_results: int | None = Field(
        None, title="Max", description="Maximum number of results", ge=1, le=100
    )
    sort: str | None = Field(
        None,
        title="Sort",
        description="Field name and sort order. Both simple and compound sorting is available.",
    )
    filters: str | None = Field(
        None,
        title="Filters",
        description="Field name, operator, and value. Both simple and compound filtering is available.",
    )
    page: str | None = Field(None, title="Page", description="Next page of results.")


class BillCreateCustomerConfig(BillRequestConfig):
    """Create a customer."""

    operation: Literal["create_customer"] = Field(
        "create_customer",
        title="Create a customer",
        json_schema_extra={
            "const": "create_customer",
            "ui:hidden": True,
            "x-category": "Customers",
            "x-is-trigger": False,
        },
    )
    name: str = Field(
        ..., title="Name", description="Customer name", min_length=1, max_length=100
    )
    company_name: str | None = Field(
        None, title="Company Name", description="Customer company name", max_length=250
    )
    contact: str | None = Field(
        None,
        title="Contact",
        description="Customer contact information JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    email: str = Field(
        ..., title="Email", description="Customer email address", min_length=1
    )
    phone: str | None = Field(None, title="Phone", description="Customer phone number")
    fax: str | None = Field(None, title="Fax", description="Customer fax number")
    description: str | None = Field(
        None, title="Description", description="Customer description", max_length=4000
    )
    invoice_currency: BillCurrency | None = Field(
        None,
        title="Invoice Currency",
        description="Invoice currency. Three-letter abbreviation.",
    )
    account_type: Literal["NONE", "BUSINESS", "PERSON"] | None = Field(
        None, title="Account Type", description="Customer account type"
    )
    payment_term_id: str | None = Field(
        None,
        title="Payment Term ID",
        description="BILL-generated ID of the payment term. Use payment terms to set the number of days the customer has to clear an invoice.",
    )
    account_number: str | None = Field(
        None,
        title="Account Number",
        description="Customer account number. The number appears in customer invoices.",
        max_length=100,
    )
    billing_address: str | None = Field(
        None,
        title="Billing Address",
        description="Customer billing address JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    shipping_address: str | None = Field(
        None,
        title="Shipping Address",
        description="Customer shipping address JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    json_fields: ClassVar[dict[str, str]] = {
        "contact": "object",
        "billing_address": "object",
        "shipping_address": "object",
    }


class BillGetCustomerConfig(BillRequestConfig):
    """Get customer details."""

    operation: Literal["get_customer"] = Field(
        "get_customer",
        title="Get customer details",
        json_schema_extra={
            "const": "get_customer",
            "ui:hidden": True,
            "x-category": "Customers",
            "x-is-trigger": False,
        },
    )
    customer_id: str = Field(
        ...,
        title="Customer ID",
        description="BILL-generated ID of the customer. The value begins with `0cu`.",
        min_length=1,
    )


class BillUpdateCustomerConfig(BillRequestConfig):
    """Update a customer."""

    operation: Literal["update_customer"] = Field(
        "update_customer",
        title="Update a customer",
        json_schema_extra={
            "const": "update_customer",
            "ui:hidden": True,
            "x-category": "Customers",
            "x-is-trigger": False,
        },
    )
    customer_id: str = Field(
        ...,
        title="Customer ID",
        description="BILL-generated ID of the customer. The value begins with `0cu`.",
        min_length=1,
    )
    name: str | None = Field(
        None, title="Name", description="Customer name", max_length=100
    )
    company_name: str | None = Field(
        None, title="Company Name", description="Customer company name", max_length=250
    )
    contact: str | None = Field(
        None,
        title="Contact",
        description="Customer contact information JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    email: str | None = Field(None, title="Email", description="Customer email address")
    phone: str | None = Field(None, title="Phone", description="Customer phone number")
    fax: str | None = Field(None, title="Fax", description="Customer fax number")
    description: str | None = Field(
        None, title="Description", description="Customer description", max_length=4000
    )
    invoice_currency: BillCurrency | None = Field(
        None,
        title="Invoice Currency",
        description="Invoice currency. Three-letter abbreviation.",
    )
    account_type: Literal["NONE", "BUSINESS", "PERSON"] | None = Field(
        None, title="Account Type", description="Customer account type"
    )
    payment_term_id: str | None = Field(
        None,
        title="Payment Term ID",
        description="BILL-generated ID of the payment term. Use payment terms to set the number of days the customer has to clear an invoice.",
    )
    account_number: str | None = Field(
        None,
        title="Account Number",
        description="Customer account number. The number appears in customer invoices.",
        max_length=100,
    )
    billing_address: str | None = Field(
        None,
        title="Billing Address",
        description="Customer billing address JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    shipping_address: str | None = Field(
        None,
        title="Shipping Address",
        description="Customer shipping address JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    json_fields: ClassVar[dict[str, str]] = {
        "contact": "object",
        "billing_address": "object",
        "shipping_address": "object",
    }


class BillListPendingApprovalsConfig(BillRequestConfig):
    """Get list of bills pending approval."""

    operation: Literal["list_pending_approvals"] = Field(
        "list_pending_approvals",
        title="Get list of bills pending approval",
        json_schema_extra={
            "const": "list_pending_approvals",
            "ui:hidden": True,
            "x-category": "Approvals",
            "x-is-trigger": False,
        },
    )


class BillListApprovalPoliciesConfig(BillRequestConfig):
    """Get list of bill approval policies."""

    operation: Literal["list_approval_policies"] = Field(
        "list_approval_policies",
        title="Get list of bill approval policies",
        json_schema_extra={
            "const": "list_approval_policies",
            "ui:hidden": True,
            "x-category": "Approvals",
            "x-is-trigger": False,
        },
    )


class BillCreateApprovalPolicyConfig(BillRequestConfig):
    """Create a bill approval policy."""

    operation: Literal["create_approval_policy"] = Field(
        "create_approval_policy",
        title="Create a bill approval policy",
        json_schema_extra={
            "const": "create_approval_policy",
            "ui:hidden": True,
            "x-category": "Approvals",
            "x-is-trigger": False,
        },
    )
    policy_name: str = Field(
        ..., title="Policy Name", description="Bill approval policy name"
    )
    rules: str = Field(
        ...,
        title="Rules",
        description="Bill approval policy rules. You can set multiple rules for a policy. JSON array.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    approvers: str = Field(
        ...,
        title="Approvers",
        description="List of approvers. For each approver, set the BILL-generated ID of the user. The value begins with `006`. JSON array.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    json_fields: ClassVar[dict[str, str]] = {"rules": "array", "approvers": "array"}


class BillApproveOrDenyBillsConfig(BillRequestConfig):
    """Approve or deny a bill."""

    operation: Literal["approve_or_deny_bills"] = Field(
        "approve_or_deny_bills",
        title="Approve or deny a bill",
        json_schema_extra={
            "const": "approve_or_deny_bills",
            "ui:hidden": True,
            "x-category": "Approvals",
            "x-is-trigger": False,
        },
    )
    actions: str = Field(
        ...,
        title="Approval Actions (JSON)",
        description='Array of {"billId": "00n...", "action": "APPROVE" or "DENY", "comment": "..."}.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    json_fields: ClassVar[dict[str, str]] = {"actions": "array"}


class BillListPaymentsConfig(BillRequestConfig):
    """Get list of payments."""

    operation: Literal["list_payments"] = Field(
        "list_payments",
        title="Get list of payments",
        json_schema_extra={
            "const": "list_payments",
            "ui:hidden": True,
            "x-category": "Payments",
            "x-is-trigger": False,
        },
    )
    max_results: int | None = Field(
        None, title="Max", description="Maximum number of results", ge=1, le=100
    )
    sort: str | None = Field(
        None,
        title="Sort",
        description="Field name and sort order. Both simple and compound sorting is available.",
    )
    filters: str | None = Field(
        None,
        title="Filters",
        description="Field name, operator, and value. Both simple and compound filtering is available.",
    )
    page: str | None = Field(None, title="Page", description="Next page of results.")


class BillGetPaymentConfig(BillRequestConfig):
    """Get payment details."""

    operation: Literal["get_payment"] = Field(
        "get_payment",
        title="Get payment details",
        json_schema_extra={
            "const": "get_payment",
            "ui:hidden": True,
            "x-category": "Payments",
            "x-is-trigger": False,
        },
    )
    payment_id: str = Field(
        ...,
        title="Payment ID",
        description="BILL-generated ID of the payment. The value begins with `stp`.",
        min_length=1,
    )


class BillSchedulePaymentConfig(BillRequestConfig):
    """Create a payment."""

    operation: Literal["schedule_payment"] = Field(
        "schedule_payment",
        title="Create a payment",
        json_schema_extra={
            "const": "schedule_payment",
            "ui:hidden": True,
            "x-category": "Payments",
            "x-is-trigger": False,
        },
    )
    vendor_id: str | None = Field(
        None,
        title="Vendor ID",
        description="BILL-generated ID of the vendor to be paid. The value begins with `009`.",
    )
    bill_id: str | None = Field(
        None,
        title="Bill ID",
        description="BILL-generated ID of the bill to be paid. The value begins with `00n`. If `createBill` is `true`, do not set `billId` in your payment request.",
    )
    description: str | None = Field(
        None,
        title="Description",
        description="Bill payment description. This value is included in the check memo or in the bank descriptor for electronic payments.",
        max_length=70,
    )
    process_date: date | None = Field(
        None,
        title="Process Date",
        description="Payment process date in the `yyyy-MM-dd` format. On this date, BILL starts processing the payment and starts withdrawing funds from the sender's funding account.",
    )
    exchange_rate_batch_id: int | None = Field(
        None,
        title="Exchange Rate Batch ID",
        description="Exchange rate batch ID. This field is required for paying international vendors when the vendor bill currency is not `USD`.",
    )
    funding_account: str = Field(
        ...,
        title="Funding Account",
        description="Payment funding information (Bank account, card account, or wallet) JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    amount: float = Field(
        ...,
        title="Amount",
        description="Payment amount. For a payment in an international currency (not USD), this value is in the local currency.",
    )
    processing_options: str = Field(
        ...,
        title="Processing Options",
        description="Payment processing options JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    payment_purpose: str | None = Field(
        None,
        title="Payment Purpose",
        description="Payment purpose information for compliance with international payment rules of the vendor country. This one-time configuration is required for enabling electronic payments to international vendors. JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    transaction_number: str | None = Field(
        None,
        title="Transaction Number",
        description="Payment transaction reference used as an external identifier.",
        max_length=50,
    )
    card_funding_purpose: str | None = Field(
        None,
        title="Card Funding Purpose",
        description="Card funding purpose. This field is required for the `CARD_ACCOUNT` funding account `type` if BILL cannot identify the vendor industry.",
    )
    vendor_credits: str | None = Field(
        None,
        title="Vendor Credits",
        description="Vendor credits applied to the bill payment. To edit the vendor credit amount applied to the bill, set the same vendor credit `id` in your payment request. To apply an additional vendor credit to the bill, set the new vendor credit `id` in your payment request. JSON array.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    json_fields: ClassVar[dict[str, str]] = {
        "funding_account": "object",
        "processing_options": "object",
        "payment_purpose": "object",
        "vendor_credits": "array",
    }


class BillRecordPaymentConfig(BillRequestConfig):
    """Record AP payment."""

    operation: Literal["record_payment"] = Field(
        "record_payment",
        title="Record AP payment",
        json_schema_extra={
            "const": "record_payment",
            "ui:hidden": True,
            "x-category": "Payments",
            "x-is-trigger": False,
        },
    )
    vendor_id: str = Field(
        ...,
        title="Vendor ID",
        description="BILL-generated ID of the vendor. The value begins with `009`.",
        min_length=1,
    )
    process_date: date = Field(
        ...,
        title="Process Date",
        description="Payment process date. The value is in the `yyyy-MM-dd` format.",
    )
    to_print_check: bool = Field(
        ...,
        title="To Print Check",
        description="Set as `true` to set the payment check as printable in your accounting system. Use this field only for check payments.",
    )
    classifications: str | None = Field(
        None,
        title="Classifications",
        description="General ledger classifications information for the payment JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    description: str | None = Field(
        None, title="Description", description="Payment description"
    )
    sync_reference: str | None = Field(
        None,
        title="Sync Reference",
        description="Payment reference ID in your accounting system. Set this field with payment information, such as check number.",
    )
    payments: str = Field(
        ...,
        title="Payments",
        description="List of bill payments JSON array.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    allow_export: bool | None = Field(
        None,
        title="Allow Export",
        description="Set as `true` to sync the bill payment with your accounting system",
    )
    json_fields: ClassVar[dict[str, str]] = {
        "classifications": "object",
        "payments": "array",
    }


# Registration: https://developer.bill.com/docs/working-with-bill-webhooks
# Payloads: https://developer.bill.com/docs/bill-webhook-notification-payloads
# https://developer.bill.com/docs/payment-webhook-notification-payloads
# https://developer.bill.com/docs/vendor-webhook-notification-payloads
class BillWebhookConfig(WebhookTriggerConfigBase):
    webhook_url: str | None = Field(
        None, title="Webhook URL", description="Registered with BILL automatically",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )


class BillOnBillEventConfig(BillWebhookConfig):
    operation: Literal["on_bill_event"] = Field(
        "on_bill_event", title="On Bill Event", json_schema_extra={
            "const": "on_bill_event", "ui:hidden": True, "x-category": "Triggers",
            "x-is-trigger": True, "x-display-name": "On Bill Event",
        },
    )
    event_type: Literal['bill.created', 'bill.updated', 'bill.archived', 'bill.restored'] = Field(
        "bill.created", title="Event Type", description="BILL event that starts this workflow",
    )


class BillOnPaymentEventConfig(BillWebhookConfig):
    operation: Literal["on_payment_event"] = Field(
        "on_payment_event", title="On Payment Event", json_schema_extra={
            "const": "on_payment_event", "ui:hidden": True, "x-category": "Triggers",
            "x-is-trigger": True, "x-display-name": "On Payment Event",
        },
    )
    event_type: Literal['payment.updated', 'payment.failed'] = Field(
        "payment.updated", title="Event Type", description="BILL event that starts this workflow",
    )


class BillOnVendorEventConfig(BillWebhookConfig):
    operation: Literal["on_vendor_event"] = Field(
        "on_vendor_event", title="On Vendor Event", json_schema_extra={
            "const": "on_vendor_event", "ui:hidden": True, "x-category": "Triggers",
            "x-is-trigger": True, "x-display-name": "On Vendor Event",
        },
    )
    event_type: Literal['vendor.created', 'vendor.updated'] = Field(
        "vendor.created", title="Event Type", description="BILL event that starts this workflow",
    )


BILL_TRIGGER_EVENTS = {'on_bill_event': ('bill.created', 'bill.updated', 'bill.archived', 'bill.restored'), 'on_payment_event': ('payment.updated', 'payment.failed'), 'on_vendor_event': ('vendor.created', 'vendor.updated')}


BillConfig = Annotated[
    Union[
        BillOnBillEventConfig,
        BillOnPaymentEventConfig,
        BillOnVendorEventConfig,
        BillListVendorsConfig,
        BillCreateVendorConfig,
        BillGetVendorConfig,
        BillUpdateVendorConfig,
        BillListBillsConfig,
        BillCreateBillConfig,
        BillGetBillConfig,
        BillUpdateBillConfig,
        BillListCustomersConfig,
        BillCreateCustomerConfig,
        BillGetCustomerConfig,
        BillUpdateCustomerConfig,
        BillListPendingApprovalsConfig,
        BillListApprovalPoliciesConfig,
        BillCreateApprovalPolicyConfig,
        BillApproveOrDenyBillsConfig,
        BillListPaymentsConfig,
        BillGetPaymentConfig,
        BillSchedulePaymentConfig,
        BillRecordPaymentConfig,
    ],
    Discriminator("operation"),
]


class BillNodeConfig(NodeConfig[BillConfig, BILLSessionCredential]):
    pass


BILL_ROUTES = {
    "list_vendors": {
        "method": "GET",
        "path": "/v3/vendors",
        "path_fields": {},
        "query_fields": {
            "max_results": "max",
            "sort": "sort",
            "filters": "filters",
            "page": "page",
        },
        "body_fields": {},
        "array_body": False,
    },
    "create_vendor": {
        "method": "POST",
        "path": "/v3/vendors",
        "path_fields": {},
        "query_fields": {},
        "body_fields": {
            "name": "name",
            "short_name": "shortName",
            "account_number": "accountNumber",
            "account_type": "accountType",
            "email": "email",
            "phone": "phone",
            "address": "address",
            "payment_information": "paymentInformation",
            "additional_info": "additionalInfo",
            "bill_currency": "billCurrency",
            "auto_pay": "autoPay",
        },
        "array_body": False,
    },
    "get_vendor": {
        "method": "GET",
        "path": "/v3/vendors/{vendorId}",
        "path_fields": {"vendor_id": "vendorId"},
        "query_fields": {},
        "body_fields": {},
        "array_body": False,
    },
    "update_vendor": {
        "method": "PATCH",
        "path": "/v3/vendors/{vendorId}",
        "path_fields": {"vendor_id": "vendorId"},
        "query_fields": {},
        "body_fields": {
            "name": "name",
            "short_name": "shortName",
            "account_number": "accountNumber",
            "account_type": "accountType",
            "email": "email",
            "phone": "phone",
            "address": "address",
            "payment_information": "paymentInformation",
            "additional_info": "additionalInfo",
            "bill_currency": "billCurrency",
            "auto_pay": "autoPay",
        },
        "array_body": False,
    },
    "list_bills": {
        "method": "GET",
        "path": "/v3/bills",
        "path_fields": {},
        "query_fields": {
            "max_results": "max",
            "sort": "sort",
            "filters": "filters",
            "page": "page",
        },
        "body_fields": {},
        "array_body": False,
    },
    "create_bill": {
        "method": "POST",
        "path": "/v3/bills",
        "path_fields": {},
        "query_fields": {},
        "body_fields": {
            "vendor_id": "vendorId",
            "description": "description",
            "due_date": "dueDate",
            "payment_term_id": "paymentTermId",
            "bill_line_items": "billLineItems",
            "invoice": "invoice",
            "pay_from_chart_of_account_id": "payFromChartOfAccountId",
            "classifications": "classifications",
            "vendor_credits": "vendorCredits",
            "purchase_order_number": "purchaseOrderNumber",
            "bill_approvals": "billApprovals",
            "allow_duplicate_invoice_number": "allowDuplicateInvoiceNumber",
        },
        "array_body": False,
    },
    "get_bill": {
        "method": "GET",
        "path": "/v3/bills/{billId}",
        "path_fields": {"bill_id": "billId"},
        "query_fields": {},
        "body_fields": {},
        "array_body": False,
    },
    "update_bill": {
        "method": "PATCH",
        "path": "/v3/bills/{billId}",
        "path_fields": {"bill_id": "billId"},
        "query_fields": {},
        "body_fields": {
            "vendor_id": "vendorId",
            "description": "description",
            "due_date": "dueDate",
            "payment_term_id": "paymentTermId",
            "bill_line_items": "billLineItems",
            "invoice": "invoice",
            "pay_from_chart_of_account_id": "payFromChartOfAccountId",
            "classifications": "classifications",
            "vendor_credits": "vendorCredits",
            "purchase_order_number": "purchaseOrderNumber",
            "bill_approvals": "billApprovals",
            "policy_rematch": "policyRematch",
        },
        "array_body": False,
    },
    "list_customers": {
        "method": "GET",
        "path": "/v3/customers",
        "path_fields": {},
        "query_fields": {
            "max_results": "max",
            "sort": "sort",
            "filters": "filters",
            "page": "page",
        },
        "body_fields": {},
        "array_body": False,
    },
    "create_customer": {
        "method": "POST",
        "path": "/v3/customers",
        "path_fields": {},
        "query_fields": {},
        "body_fields": {
            "name": "name",
            "company_name": "companyName",
            "contact": "contact",
            "email": "email",
            "phone": "phone",
            "fax": "fax",
            "description": "description",
            "invoice_currency": "invoiceCurrency",
            "account_type": "accountType",
            "payment_term_id": "paymentTermId",
            "account_number": "accountNumber",
            "billing_address": "billingAddress",
            "shipping_address": "shippingAddress",
        },
        "array_body": False,
    },
    "get_customer": {
        "method": "GET",
        "path": "/v3/customers/{customerId}",
        "path_fields": {"customer_id": "customerId"},
        "query_fields": {},
        "body_fields": {},
        "array_body": False,
    },
    "update_customer": {
        "method": "PATCH",
        "path": "/v3/customers/{customerId}",
        "path_fields": {"customer_id": "customerId"},
        "query_fields": {},
        "body_fields": {
            "name": "name",
            "company_name": "companyName",
            "contact": "contact",
            "email": "email",
            "phone": "phone",
            "fax": "fax",
            "description": "description",
            "invoice_currency": "invoiceCurrency",
            "account_type": "accountType",
            "payment_term_id": "paymentTermId",
            "account_number": "accountNumber",
            "billing_address": "billingAddress",
            "shipping_address": "shippingAddress",
        },
        "array_body": False,
    },
    "list_pending_approvals": {
        "method": "GET",
        "path": "/v3/bill-approvals/pending-user-approvals",
        "path_fields": {},
        "query_fields": {},
        "body_fields": {},
        "array_body": False,
    },
    "list_approval_policies": {
        "method": "GET",
        "path": "/v3/bill-approvals/policies",
        "path_fields": {},
        "query_fields": {},
        "body_fields": {},
        "array_body": False,
    },
    "create_approval_policy": {
        "method": "POST",
        "path": "/v3/bill-approvals/policies",
        "path_fields": {},
        "query_fields": {},
        "body_fields": {
            "policy_name": "policyName",
            "rules": "rules",
            "approvers": "approvers",
        },
        "array_body": False,
    },
    "approve_or_deny_bills": {
        "method": "POST",
        "path": "/v3/bill-approvals/actions",
        "path_fields": {},
        "query_fields": {},
        "body_fields": {"actions": "actions"},
        "array_body": True,
    },
    "list_payments": {
        "method": "GET",
        "path": "/v3/payments",
        "path_fields": {},
        "query_fields": {
            "max_results": "max",
            "sort": "sort",
            "filters": "filters",
            "page": "page",
        },
        "body_fields": {},
        "array_body": False,
    },
    "get_payment": {
        "method": "GET",
        "path": "/v3/payments/{paymentId}",
        "path_fields": {"payment_id": "paymentId"},
        "query_fields": {},
        "body_fields": {},
        "array_body": False,
    },
    "schedule_payment": {
        "method": "POST",
        "path": "/v3/payments",
        "path_fields": {},
        "query_fields": {},
        "body_fields": {
            "vendor_id": "vendorId",
            "bill_id": "billId",
            "description": "description",
            "process_date": "processDate",
            "exchange_rate_batch_id": "exchangeRateBatchId",
            "funding_account": "fundingAccount",
            "amount": "amount",
            "processing_options": "processingOptions",
            "payment_purpose": "paymentPurpose",
            "transaction_number": "transactionNumber",
            "card_funding_purpose": "cardFundingPurpose",
            "vendor_credits": "vendorCredits",
        },
        "array_body": False,
    },
    "record_payment": {
        "method": "POST",
        "path": "/v3/bills/record-payment",
        "path_fields": {},
        "query_fields": {},
        "body_fields": {
            "vendor_id": "vendorId",
            "process_date": "processDate",
            "to_print_check": "toPrintCheck",
            "classifications": "classifications",
            "description": "description",
            "sync_reference": "syncReference",
            "payments": "payments",
            "allow_export": "allowExport",
        },
        "array_body": False,
    },
}


class BillNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-bill"

    connection_evidence = ConnectionEvidence(operation="list_vendors", noun="vendors")
    edit_examples = [
        "Create a vendor and bill from a supplier invoice",
        "Route bills above $1000 to approvers with an approval policy",
        "List bills pending my approval and approve a bill",
        "Schedule a bill payment or record an offline payment",
        "Sync customers from my CRM into BILL",
    ]

    @classmethod
    def get_config_model(cls):
        return BillNodeConfig

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type")}

    @classmethod
    async def _webhook_request(cls, credential, method, path, *, body=None):
        if not credential or not credential.get("dev_key") or not credential.get("session_id"):
            raise ValueError("Connect a BILL AP/AR session before activating this trigger")
        host = "gateway.stage.bill.com" if credential.get("environment") == "sandbox" else "gateway.prod.bill.com"
        headers = {"devKey": credential["dev_key"], "sessionId": credential["session_id"], "Accept": "application/json"}
        if method == "POST":
            headers["X-Idempotent-Key"] = str(uuid4())
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await client.request(
                method, f"https://{host}/connect-events{path}", headers=headers,
                **({"json": body} if body is not None else {}),
            )
        # A subscription already removed at BILL is also a successful teardown.
        if method == "DELETE" and response.status_code == 404:
            return {}
        if not response.is_success:
            raise ValueError(f"BILL webhook API returned HTTP {response.status_code}; check your session and developer key")
        return response.json() if response.content else {}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        config = config or {}
        operation = config.get("operation")
        event_type = config.get("event_type")
        if event_type not in BILL_TRIGGER_EVENTS.get(operation, ()):
            raise ValueError("Choose a supported BILL event for this trigger")
        result = await cls._webhook_request(credential, "POST", "/v3/subscriptions", body={
            "name": f"NoClick {node_id}", "status": {"enabled": True},
            "events": [{"type": event_type, "version": "1"}], "notificationUrl": webhook_url,
        })
        if not result.get("id") or not result.get("securityKey"):
            raise ValueError("BILL did not return a subscription ID and security key")
        return {"external_webhook_id": result["id"], "signing_secret": result["securityKey"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        subscription_id = (config or {}).get("external_webhook_id")
        if subscription_id:
            await cls._webhook_request(credential, "DELETE", f"/v3/subscriptions/{quote(str(subscription_id), safe='')}")

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict[str, str], config: dict[str, Any]) -> bool:
        # https://developer.bill.com/docs/test-with-webhook-security
        # The HTTP request is the event payload, not the escaped payload field
        # in the event-history API response. Verify its exact bytes.
        secret = (config or {}).get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "x-bill-sha-signature"), "")
        if not secret or not signature:
            return False
        expected = base64.b64encode(hmac.new(str(secret).encode(), body, hashlib.sha256).digest()).decode()
        return hmac.compare_digest(expected.encode(), signature.encode())

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            return False
        operation = (config or {}).get("operation")
        event_type = (config or {}).get("event_type")
        return (event_type in BILL_TRIGGER_EVENTS.get(operation, ())
                and metadata.get("eventType") == event_type and metadata.get("version") == "1")

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"status": "success", "action": config.get("operation"), "data": payload}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict):
            return None
        payload = output["data"] if "data" in output and isinstance(output["data"], dict) else output
        if "metadata" not in payload or not isinstance(payload["metadata"], dict):
            return None
        metadata = payload["metadata"]
        kind = metadata.get("eventType", "")
        entity = kind.split(".", 1)[0]
        if entity not in ("bill", "payment", "vendor") or entity not in payload:
            return None
        record = payload[entity]
        if not isinstance(record, dict):
            return None
        # payment.failed carries bills and errors, but no payment ID. Never
        # manufacture one or offer get_payment with the event ID instead.
        resource_id = record["id"] if "id" in record else None
        label = record["name"] if "name" in record else record["transactionNumber"] if "transactionNumber" in record else resource_id
        lines = [f"BILL {kind}: {label}",
                 f"Organization: {metadata.get('organizationId')}",
                 f"Event ID: {metadata.get('eventId')}"]
        # Keep the provider's names and identifiers visible so agents can verify
        # the current entity through get_bill/get_payment/get_vendor before acting.
        for key in ("createdBy", "vendorId", "description", "amount", "paymentStatus", "status", "email", "createdTime", "updatedTime"):
            if key in record:
                lines.append(f"{key}: {record[key]}")
        for key in ("invoice", "vendor", "funding", "billIds", "bills", "fundingAccount"):
            if key in record:
                lines.append(f"{key}: {json.dumps(record[key], ensure_ascii=False)}")
        if "errors" in payload:
            lines.append(f"Errors: {json.dumps(payload['errors'], ensure_ascii=False)}")
        if resource_id:
            lines.append(f"To verify current details: get_{entity} {entity}_id={resource_id}.")
        else:
            lines.append("Verify the listed bills with get_bill bill_id=<bills.id>; BILL did not include a payment ID.")
        return {"text": "\n".join(lines),
                "conversation_key": f"{metadata.get('organizationId')}:{entity}:{resource_id or metadata.get('eventId')}",
                "title": f"BILL {kind}: {label}"}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, BillNodeConfig) or not self.config.credentials:
            raise ValueError(
                "Connect a BILL AP/AR session credential before running this operation"
            )
        config = self.config.config
        credential = self.config.credentials
        if config.operation in BILL_TRIGGER_EVENTS:
            return self.no_event_output(config.operation)
        route = BILL_ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        for field, kind in config.json_fields.items():
            if field not in values:
                continue
            try:
                value = json.loads(values[field])
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{field} must be valid JSON") from exc
            expected = list if kind == "array" else dict
            if not isinstance(value, expected):
                raise ValueError(f"{field} must be a JSON {kind}")
            values[field] = value
        path = route["path"]
        for field, key in route["path_fields"].items():
            path = path.replace("{" + key + "}", quote(values[field], safe=""))
        params = {
            key: values[field]
            for field, key in route["query_fields"].items()
            if field in values
        }
        body = {
            key: values[field]
            for field, key in route["body_fields"].items()
            if field in values
        }
        if route["array_body"]:
            body = body["actions"]
        host = (
            "gateway.prod.bill.com"
            if credential.environment == "production"
            else "gateway.stage.bill.com"
        )
        try:
            async with httpx.AsyncClient(
                timeout=30.0, follow_redirects=False
            ) as client:
                response = await client.request(
                    route["method"],
                    f"https://{host}/connect{path}",
                    headers={
                        "devKey": credential.dev_key,
                        "sessionId": credential.session_id,
                        "Accept": "application/json",
                    },
                    params=params,
                    **({"json": body} if route["body_fields"] else {}),
                )
        except httpx.RequestError:
            return {
                "status": "error",
                "action": config.operation,
                "error": "Could not reach the BILL API",
            }
        if not response.is_success:
            # BILL error text may echo credentials; redact before crossing the workflow boundary.
            message = response.text
            for secret in (credential.dev_key, credential.session_id):
                message = message.replace(secret, "[redacted]")
            return {
                "status": "error",
                "action": config.operation,
                "status_code": response.status_code,
                "error": f"BILL HTTP {response.status_code}: {message[:2000]}",
            }
        try:
            data = response.json()
        except ValueError:
            return {
                "status": "error",
                "action": config.operation,
                "error": "BILL returned invalid JSON",
            }
        if config.operation == "list_approval_policies" and isinstance(data, list):
            return {
                "status": "success",
                "action": config.operation,
                "data": {"policies": data},
                "status_code": response.status_code,
            }
        if not isinstance(data, dict):
            return {
                "status": "error",
                "action": config.operation,
                "error": "BILL returned an unexpected response",
            }
        if data.get("status") == "FAILURE":
            return {
                "status": "error",
                "action": config.operation,
                "error": "BILL reported FAILURE",
                "data": data,
            }
        if config.operation.startswith("list_"):
            key = "bills" if config.operation == "list_pending_approvals" else "results"
            if not isinstance(data.get(key), list):
                return {
                    "status": "error",
                    "action": config.operation,
                    "error": f"BILL response is missing {key}",
                }
        return {
            "status": "success",
            "action": config.operation,
            "data": data,
            "status_code": response.status_code,
        }
