"""HassleFreeBooks bookkeeping API and signed outbound webhook events.

Contract: https://hasslefreebooks.com/openapi.json (1.0.0).
API keys are pasted by a person; no login, key creation or token exchange occurs.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date as Date
from decimal import Decimal
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.scopes.hasslefreebooks import HASSLEFREEBOOKS_SCOPES

BASE_URL = "https://hasslefreebooks.com"


class HassleFreeBooksAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="HassleFreeBooks API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://hasslefreebooks.com/api-keys",
            "x-credential-instructions": "Paste an API key created in HassleFreeBooks with read and write scopes. Webhook subscriptions require the owner role. NoClick sends it as a Bearer token to hasslefreebooks.com."
        })
    credential_type: Literal["hasslefreebooks_api_key"] = Field("hasslefreebooks_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HassleFreeBooksListTransactionsConfig(_Input):
    operation: Literal['list_transactions'] = Field('list_transactions', title='List Transactions', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Transactions', "x-category": 'Transactions'})
    page: int | None = Field(1, title='Page', ge=1, description='Page number (1-based)')
    start_date: Date | None = Field(None, title='Start Date', description='Filter transactions from this date (inclusive, Y-m-d format)')
    end_date: Date | None = Field(None, title='End Date', description='Filter transactions until this date (inclusive, Y-m-d format)')
    min_amount: float | None = Field(None, title='Min Amount', ge=0, allow_inf_nan=False, description='Filter transactions with amount >= this value')
    max_amount: float | None = Field(None, title='Max Amount', ge=0, allow_inf_nan=False, description='Filter transactions with amount <= this value')
    source: Literal['manual', 'import', 'api'] | None = Field(None, title='Source', description='Filter by transaction source')
    q: str | None = Field(None, title='Q', description='Search in transaction description')
    entity_id: int | None = Field(None, title='Entity Id', description="Entity to list; defaults to the caller's active entity (POST /api/v1/entities/switch). An entity the caller is not a member of is answered 404.")
    limit: int | None = Field(50, title='Limit', ge=1, le=100, description='Rows to return; wins over per_page.')
    offset: int | None = Field(None, title='Offset', ge=0, description='Rows to skip; wins over page.')


class HassleFreeBooksCreateTransactionConfigLinesItem(_Input):
    account_id: int = Field(..., title='Account Id', ge=1, description='Chart of accounts ID')
    debit_amount: str = Field(..., pattern=r"^[0-9]+(?:\.[0-9]{1,2})?$", title='Debit Amount', description='Debit amount (use "0.00" if this is a credit line)')
    credit_amount: str = Field(..., pattern=r"^[0-9]+(?:\.[0-9]{1,2})?$", title='Credit Amount', description='Credit amount (use "0.00" if this is a debit line)')
    memo: str | None = Field(None, title='Memo', description='Optional memo for this line')


class HassleFreeBooksCreateTransactionConfig(_Input):
    operation: Literal['create_transaction'] = Field('create_transaction', title='Create Journal Entry', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create Journal Entry', "x-category": 'Transactions'})
    description: str = Field(..., title='Description', description='Journal entry description')
    date: Date = Field(..., title='Date', description='Transaction date in Y-m-d format')
    entity_id: int | None = Field(None, title='Entity Id', description="Entity ID (optional, defaults to user's primary entity)")
    lines: list[HassleFreeBooksCreateTransactionConfigLinesItem] = Field(..., title='Lines', min_length=2, description='Transaction lines (minimum 2, must balance)')

    @model_validator(mode="after")
    def balanced(self):
        debits = sum(Decimal(line.debit_amount) for line in self.lines)
        credits = sum(Decimal(line.credit_amount) for line in self.lines)
        if not debits.is_finite() or not credits.is_finite() or debits <= 0 or debits != credits:
            raise ValueError("Journal entry debits and credits must balance to a positive amount")
        if any(Decimal(line.debit_amount) < 0 or Decimal(line.credit_amount) < 0 for line in self.lines):
            raise ValueError("Journal amounts must be nonnegative")
        return self


class HassleFreeBooksGetTransactionConfig(_Input):
    operation: Literal['get_transaction'] = Field('get_transaction', title='Get Transaction Detail', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Transaction Detail', "x-category": 'Transactions'})
    id: int = Field(..., title='Id', ge=1, description='Transaction ID')
    entity_id: int | None = Field(None, title='Entity Id', description="Entity to read from; defaults to the caller's active entity.")


class HassleFreeBooksGetInvoiceConfig(_Input):
    operation: Literal['get_invoice'] = Field('get_invoice', title='Get an invoice', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get an invoice', "x-category": 'Invoices'})
    invoiceId: int = Field(..., title='Invoice Id')


class HassleFreeBooksSendInvoiceConfig(_Input):
    operation: Literal['send_invoice'] = Field('send_invoice', title='Send an invoice', json_schema_extra={"ui:hidden": True, "x-display-name": 'Send an invoice', "x-category": 'Invoices'})
    invoiceId: int = Field(..., title='Invoice Id')


class HassleFreeBooksGetBalanceSheetConfig(_Input):
    operation: Literal['get_balance_sheet'] = Field('get_balance_sheet', title='Balance sheet', json_schema_extra={"ui:hidden": True, "x-display-name": 'Balance sheet', "x-category": 'Reports'})
    entity_id: int | None = Field(None, title='Entity Id')
    as_of_date: Date | None = Field(None, title='As Of Date')
    end_date: Date | None = Field(None, title='End Date', description='Balance sheet as of this date (alias of as_of_date).')


class HassleFreeBooksListAccountsConfig(_Input):
    operation: Literal['list_accounts'] = Field('list_accounts', title='List chart of accounts', json_schema_extra={"ui:hidden": True, "x-display-name": 'List chart of accounts', "x-category": 'ChartOfAccounts'})
    entity_id: int | None = Field(None, title='Entity Id', description="Defaults to the caller's active entity.")


class HassleFreeBooksListContactsConfig(_Input):
    operation: Literal['list_contacts'] = Field('list_contacts', title='List Contacts', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Contacts', "x-category": 'Contacts'})
    type: Literal['customer', 'vendor', 'both'] | None = Field(None, title='Type', description='Filter by contact type')
    active: Literal['0', '1', 'true', 'false'] | None = Field(None, title='Active', description='Filter by active status (defaults to active-only when omitted)')
    q: str | None = Field(None, title='Q', description='Case-insensitive match on name, display name or email')
    page: int | None = Field(None, title='Page', ge=1, description='Opt in to paging; 1-based. Without `page` and `per_page` the whole list is returned.')
    per_page: int | None = Field(None, title='Per Page', ge=1, le=200, description='Rows per page when paging (default 50, clamped to 200). Adds `data.pagination`.')


class HassleFreeBooksCreateContactConfig(_Input):
    operation: Literal['create_contact'] = Field('create_contact', title='Create Contact', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create Contact', "x-category": 'Contacts'})
    display_name: str = Field(..., title='Display Name', description='Display name (also accepts `name` as alias)')
    type: Literal['customer', 'vendor', 'both'] = Field(..., title='Type', description='Contact type')
    email: EmailStr | None = Field(None, title='Email', description='Contact email (unique per entity)')
    phone: str | None = Field(None, title='Phone', description='Contact phone number')
    metadata: dict[str, Any] | None = Field(None, title='Metadata', description='Arbitrary metadata as JSON object')
    is_active: bool | None = Field(None, title='Is Active', description='Active status (defaults to true)')


class HassleFreeBooksGetContactConfig(_Input):
    operation: Literal['get_contact'] = Field('get_contact', title='Get Contact', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Contact', "x-category": 'Contacts'})
    id: int = Field(..., title='Id', ge=1, description='Contact ID')


class HassleFreeBooksUpdateContactConfig(_Input):
    operation: Literal['update_contact'] = Field('update_contact', title='Update Contact', json_schema_extra={"ui:hidden": True, "x-display-name": 'Update Contact', "x-category": 'Contacts'})
    id: int = Field(..., title='Id', ge=1, description='Contact ID')
    display_name: str | None = Field(None, title='Display Name', description='Updated display name (also accepts `name`)')
    type: Literal['customer', 'vendor', 'both'] | None = Field(None, title='Type', description='Updated contact type')
    email: EmailStr | None = Field(None, title='Email', description='Updated email (null clears the value)')
    phone: str | None = Field(None, title='Phone', description='Updated phone (null clears the value)')
    metadata: dict[str, Any] | None = Field(None, title='Metadata', description='Updated metadata (null clears the value)')
    is_active: bool | None = Field(None, title='Is Active', description='Updated active status')

    @model_validator(mode="after")
    def nonempty_update(self):
        if not (self.model_fields_set - {"operation", "id"}):
            raise ValueError("Provide at least one contact field to update")
        return self


class HassleFreeBooksGetCurrentUserConfig(_Input):
    operation: Literal['get_current_user'] = Field('get_current_user', title='Get Current User', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Current User', "x-category": 'User'})


class HassleFreeBooksListInvoicesConfig(_Input):
    operation: Literal['list_invoices'] = Field('list_invoices', title='List Invoices', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Invoices', "x-category": 'Invoices'})
    page: int | None = Field(1, title='Page', ge=1, description='Page number (1-based)')
    per_page: int | None = Field(50, title='Per Page', ge=1, le=100, description='Results per page (max 100)')
    status: Literal['draft', 'sent', 'finalized', 'partial', 'paid', 'void'] | None = Field(None, title='Status', description='Filter by invoice status')
    contact_id: int | None = Field(None, title='Contact Id', description='Filter by contact/customer ID')
    start_date: Date | None = Field(None, title='Start Date', description='Filter invoices on or after this date (YYYY-MM-DD)')
    end_date: Date | None = Field(None, title='End Date', description='Filter invoices on or before this date (YYYY-MM-DD)')


class HassleFreeBooksCreateInvoiceConfigLinesItem(_Input):
    description: str = Field(..., title='Description', min_length=1, max_length=500)
    quantity: float = Field(..., title='Quantity', ge=0.01, allow_inf_nan=False)
    unit_price: float = Field(..., title='Unit Price', ge=0, allow_inf_nan=False)


class HassleFreeBooksCreateInvoiceConfig(_Input):
    operation: Literal['create_invoice'] = Field('create_invoice', title='Create an invoice', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create an invoice', "x-category": 'Invoices'})
    contact_id: int = Field(..., title='Contact Id')
    invoice_date: Date = Field(..., title='Invoice Date')
    due_date: Date | None = Field(None, title='Due Date')
    invoice_number: str | None = Field(None, title='Invoice Number')
    notes: str | None = Field(None, title='Notes')
    lines: list[HassleFreeBooksCreateInvoiceConfigLinesItem] = Field(..., title='Lines', min_length=1, description='Line items; at least one is required (in `lines` or `line_items`). `line_items` is accepted as a synonym and is what the Flutter client sends. Each line needs a description (500 characters or fewer), a quantity greater than 0 and a unit_price of 0 or more; both are rounded to 2 decimals and line_total is quantity x unit_price. A client line_total is ignored.')


class HassleFreeBooksListBillsConfig(_Input):
    operation: Literal['list_bills'] = Field('list_bills', title='List Bills', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Bills', "x-category": 'Bills'})
    page: int | None = Field(1, title='Page', ge=1, description='Page number, from 1.')
    per_page: int | None = Field(20, title='Per Page', ge=1, le=100, description='Rows per page; above 100 is clamped to 100.')
    status: Literal['paid', 'unpaid'] | None = Field(None, title='Status', description="Paid state. Any other value is ignored. The workflow state (draft, approved, paid) is in each bill's `status`.")
    search: str | None = Field(None, title='Search', description='Free text matched against vendor name and description.')
    overdue: bool | None = Field(None, title='Overdue', description='true: only unpaid bills past their due date.')


class HassleFreeBooksCreateBillConfig(_Input):
    operation: Literal['create_bill'] = Field('create_bill', title='Create Bill', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create Bill', "x-category": 'Bills'})
    amount: str = Field(..., title='Amount', description='Bill amount (must be greater than zero)')
    due_date: Date | None = Field(None, title='Due Date', description='Payment due date (YYYY-MM-DD); defaults to 30 days from today')
    bill_date: Date | None = Field(None, title='Bill Date', description='Bill date (YYYY-MM-DD); defaults to today')
    vendor_name: str = Field(..., title='Vendor Name', description='Vendor or supplier name; the bill is recorded against the vendor contact of this name')
    description: str | None = Field(None, title='Description', description='Bill description or memo (optional)')


class HassleFreeBooksGetBillConfig(_Input):
    operation: Literal['get_bill'] = Field('get_bill', title='Get Bill', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Bill', "x-category": 'Bills'})
    id: int = Field(..., title='Id', ge=1, description='Bill ID')


class HassleFreeBooksPayBillConfig(_Input):
    operation: Literal['pay_bill'] = Field('pay_bill', title='Pay Bill', json_schema_extra={"ui:hidden": True, "x-display-name": 'Pay Bill', "x-category": 'Bills'})
    id: int = Field(..., title='Id', ge=1, description='Bill ID')
    amount: str | None = Field(None, title='Amount', description='Amount to pay (default the outstanding balance). "1,500.00" and "$1,500.00" are read as 1500.00.')
    payment_date: Date | None = Field(None, title='Payment Date', description="Date the money left (default the business's today)")
    payment_account_id: int | None = Field(None, title='Payment Account Id', ge=1, description='Active bank or cash (asset) account the payment came from (default the cash account)')
    expected_outstanding: str | None = Field(None, title='Expected Outstanding', description="The balance you showed the person (default: not checked). When the bill's balance under its row lock differs, the answer is 409 BALANCE_CHANGED and nothing is paid. Send it with part payments so a repeated request cannot pay twice.")


class HassleFreeBooksGetProfitLossConfig(_Input):
    operation: Literal['get_profit_loss'] = Field('get_profit_loss', title='Generate Profit & Loss Report', json_schema_extra={"ui:hidden": True, "x-display-name": 'Generate Profit & Loss Report', "x-category": 'Reports'})
    entity_id: int = Field(..., title='Entity Id', ge=1, description='Entity ID for multi-tenant isolation')
    start_date: Date | None = Field(None, title='Start Date', description='Report period start date (YYYY-MM-DD)')
    end_date: Date | None = Field(None, title='End Date', description='Report period end date (YYYY-MM-DD)')
    account_type: Literal['income', 'expense'] | None = Field(None, title='Account Type', description='Filter by account type')
    account_code: str | None = Field(None, title='Account Code', max_length=50, description='Filter by account code (partial match, max 50 chars)')
    department: str | None = Field(None, title='Department', max_length=100, description='Filter by department (max 100 chars)')
    tag: str | None = Field(None, title='Tag', max_length=50, description='Filter by tag (max 50 chars)')
    dimensions: str | None = Field(None, title='Dimensions', description='Comma-separated list of dimensions to group by')
    compare_to_previous: Literal['true', 'false'] | None = Field(None, title='Compare To Previous', description='Include comparison to the previous period')


class HassleFreeBooksRecordInvoicePaymentConfig(_Input):
    operation: Literal['record_invoice_payment'] = Field('record_invoice_payment', title='Record Invoice Payment', json_schema_extra={"ui:hidden": True, "x-display-name": 'Record Invoice Payment', "x-category": 'Invoices'})
    invoice_id: int = Field(..., title='Invoice Id')
    amount: float = Field(..., title='Amount', allow_inf_nan=False)
    payment_date: Date = Field(..., title='Payment Date')
    deposit_account_id: int = Field(..., title='Deposit Account Id', description='Active asset account of the entity, other than Accounts Receivable')
    payment_method: str | None = Field(None, title='Payment Method')
    reference_number: str | None = Field(None, title='Reference Number')
    notes: str | None = Field(None, title='Notes')


class HassleFreeBooksFinalizeInvoiceConfig(_Input):
    operation: Literal['finalize_invoice'] = Field('finalize_invoice', title='Finalize Invoice', json_schema_extra={"ui:hidden": True, "x-display-name": 'Finalize Invoice', "x-category": 'Invoices'})
    id: int = Field(..., title='Id', ge=1, description='Invoice ID')


class HassleFreeBooksApproveBillConfig(_Input):
    operation: Literal['approve_bill'] = Field('approve_bill', title='Approve Bill', json_schema_extra={"ui:hidden": True, "x-display-name": 'Approve Bill', "x-category": 'Bills'})
    id: int = Field(..., title='Id', ge=1, description='Bill ID')
    expense_account_id: int = Field(..., title='Expense Account Id', description="An active expense account of this business; the bill's amount is charged to it.")


EVENT_TYPES = ("invoice.paid",)

ROUTES = {'list_transactions': ('GET', '/api/v1/transactions', ['page', 'start_date', 'end_date', 'min_amount', 'max_amount', 'source', 'q', 'entity_id', 'limit', 'offset'], []), 'create_transaction': ('POST', '/api/v1/transactions', [], ['description', 'date', 'entity_id', 'lines']), 'get_transaction': ('GET', '/api/v1/transactions/{id}', ['entity_id'], []), 'get_invoice': ('GET', '/api/v1/invoices/{invoiceId}', [], []), 'send_invoice': ('POST', '/api/v1/invoices/{invoiceId}/send', [], []), 'get_balance_sheet': ('GET', '/api/v1/reports/bs', ['entity_id', 'as_of_date', 'end_date'], []), 'list_accounts': ('GET', '/api/v1/accounts', ['entity_id'], []), 'list_contacts': ('GET', '/api/v1/contacts', ['type', 'active', 'q', 'page', 'per_page'], []), 'create_contact': ('POST', '/api/v1/contacts', [], ['display_name', 'type', 'email', 'phone', 'metadata', 'is_active']), 'get_contact': ('GET', '/api/v1/contacts/{id}', [], []), 'update_contact': ('PUT', '/api/v1/contacts/{id}', [], ['display_name', 'type', 'email', 'phone', 'metadata', 'is_active']), 'get_current_user': ('GET', '/api/v1/me', [], []), 'list_invoices': ('GET', '/api/v1/invoices', ['page', 'per_page', 'status', 'contact_id', 'start_date', 'end_date'], []), 'create_invoice': ('POST', '/api/v1/invoices', [], ['contact_id', 'invoice_date', 'due_date', 'invoice_number', 'notes', 'lines']), 'list_bills': ('GET', '/api/v1/bills', ['page', 'per_page', 'status', 'search', 'overdue'], []), 'create_bill': ('POST', '/api/v1/bills', [], ['amount', 'due_date', 'bill_date', 'vendor_name', 'description']), 'get_bill': ('GET', '/api/v1/bills/{id}', [], []), 'pay_bill': ('POST', '/api/v1/bills/{id}/pay', [], ['amount', 'payment_date', 'payment_account_id', 'expected_outstanding']), 'get_profit_loss': ('GET', '/api/v1/reports/pl', ['entity_id', 'start_date', 'end_date', 'account_type', 'account_code', 'department', 'tag', 'dimensions', 'compare_to_previous'], []), 'record_invoice_payment': ('POST', '/api/v1/invoices/record-payment', [], ['invoice_id', 'amount', 'payment_date', 'deposit_account_id', 'payment_method', 'reference_number', 'notes']), 'finalize_invoice': ('POST', '/api/v1/invoices/{id}/finalize', [], []), 'approve_bill': ('POST', '/api/v1/bills/{id}/approve', [], ['expense_account_id'])}


class HassleFreeBooksOnEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_event"] = Field("on_event", title="On Invoice Paid", json_schema_extra={
        "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Invoice Paid"})
    event_type: Literal["invoice.paid"] = Field("invoice.paid", title="Event Type")
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={
        "ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


HassleFreeBooksConfig = Annotated[Union[HassleFreeBooksListTransactionsConfig, HassleFreeBooksCreateTransactionConfig, HassleFreeBooksGetTransactionConfig, HassleFreeBooksGetInvoiceConfig, HassleFreeBooksSendInvoiceConfig, HassleFreeBooksGetBalanceSheetConfig, HassleFreeBooksListAccountsConfig, HassleFreeBooksListContactsConfig, HassleFreeBooksCreateContactConfig, HassleFreeBooksGetContactConfig, HassleFreeBooksUpdateContactConfig, HassleFreeBooksGetCurrentUserConfig, HassleFreeBooksListInvoicesConfig, HassleFreeBooksCreateInvoiceConfig, HassleFreeBooksListBillsConfig, HassleFreeBooksCreateBillConfig, HassleFreeBooksGetBillConfig, HassleFreeBooksPayBillConfig, HassleFreeBooksGetProfitLossConfig, HassleFreeBooksRecordInvoicePaymentConfig, HassleFreeBooksFinalizeInvoiceConfig, HassleFreeBooksApproveBillConfig, HassleFreeBooksOnEventConfig], Field(discriminator="operation")]


class HassleFreeBooksNodeConfig(NodeConfig[HassleFreeBooksConfig, HassleFreeBooksAPIKeyCredential]):
    pass


class HassleFreeBooksNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-hasslefreebooks"
    scope_registry = HASSLEFREEBOOKS_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_current_user", identity_operation="get_current_user", noun="account")

    @classmethod
    def get_config_model(cls):
        return HassleFreeBooksNodeConfig

    @staticmethod
    async def _request(api_key, method, path, *, params=None, body=None):
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                params=params, json=body)
        if response.is_error:
            try:
                error = response.json().get("error", {})
                detail = error.get("message") if isinstance(error, dict) else str(error)
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f"HassleFreeBooks API error {response.status_code}: {detail or response.reason_phrase}")
        if response.status_code == 204:
            return {}
        result = response.json()
        if not isinstance(result, dict) or result.get("ok") is not True:
            error = result.get("error") if isinstance(result, dict) else None
            raise ValueError(f"HassleFreeBooks rejected the request: {error}")
        return result.get("data", {})

    async def execute(self, inputs):
        config = self.config.config
        if isinstance(config, HassleFreeBooksOnEventConfig):
            return self.no_event_output(config.operation)
        if self.config.credentials is None:
            raise ValueError("Connect a HassleFreeBooks API key")
        self.scope_registry.require(config.operation)
        method, path, query_fields, body_fields = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", str(values.pop(key)))
        params = {k: values[k] for k in query_fields if k in values}
        body = {k: values[k] for k in body_fields if k in values}
        if config.operation == "update_contact":
            for key in ("email", "phone", "metadata"):
                if key in config.model_fields_set:
                    body[key] = getattr(config, key)
        data = await self._request(self.config.credentials.api_key, method, path,
            params=params or None, body=body if body_fields else None)
        return {"status": "success", "operation": config.operation, "data": data}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event_type = (config or {}).get("event_type", "invoice.paid")
        if event_type not in EVENT_TYPES:
            raise ValueError("Choose a supported HassleFreeBooks event")
        key = HassleFreeBooksAPIKeyCredential.model_validate(credential).api_key
        data = await cls._request(key, "POST", "/api/v1/webhooks/endpoints", body={
            "name": f"NoClick {node_id}"[:255], "url": webhook_url, "event_types": [event_type]})
        endpoint = data.get("endpoint", {})
        if not endpoint.get("id") or not data.get("secret"):
            raise ValueError("HassleFreeBooks did not return the endpoint ID and signing secret")
        return {"external_webhook_id": str(endpoint["id"]), "signing_secret": data["secret"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint_id = (config or {}).get("external_webhook_id")
        if not endpoint_id or not credential:
            return
        endpoint_id = int(endpoint_id)
        if endpoint_id <= 0:
            raise ValueError("Invalid HassleFreeBooks webhook endpoint ID")
        key = HassleFreeBooksAPIKeyCredential.model_validate(credential).api_key
        await cls._request(key, "DELETE", f"/api/v1/webhooks/endpoints/{endpoint_id}")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type", "invoice.paid")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = (config or {}).get("signing_secret")
        if not isinstance(secret, str) or not secret:
            return False
        signature = next((value for key, value in headers.items() if key.lower() == "x-hasslefrebooks-signature"), "")
        if not isinstance(signature, str) or not signature.isascii():
            return False
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get("event") == (config or {}).get("event_type", "invoice.paid")

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("event") not in EVENT_TYPES:
            return super().resolve_agent_event(output)
        kind = output["event"]
        entity_id = output.get("entity_id")
        resource_id = output.get("resource_id")
        details = output.get("data", {})
        invoice = details.get("invoice", {}) if isinstance(details, dict) else {}
        customer = invoice.get("contact_name") if isinstance(invoice, dict) else None
        number = invoice.get("invoice_number") if isinstance(invoice, dict) else None
        text = (f"HassleFreeBooks invoice paid: {number or resource_id} for {customer or 'the customer'}. "
                f"HassleFreeBooks: {kind.replace('.', ' ').replace('_', ' ')}. "
                f"Business {entity_id}, {kind.split('.')[0]} {resource_id}, at {output.get('occurred_at')}.\n"
                f"Event ID: {output.get('id')}.\nDetails: {json.dumps(output.get('data', {}), ensure_ascii=False)}")
        return {"text": text, "title": f"HassleFreeBooks {kind}",
                "conversation_key": f"hasslefreebooks:{entity_id}:{kind.split('.')[0]}:{resource_id}"}
