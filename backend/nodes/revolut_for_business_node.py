"""Revolut Business operations against the published Business API 1.0 contract.

A prepared bearer token is supplied manually and expires after 40 minutes.
Writes make one request, preserving caller-supplied idempotency IDs without retries.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Amount = Annotated[float, Field(gt=0, allow_inf_nan=False)]
RequestID = Annotated[str, Field(min_length=1, max_length=40, description="Reuse the same ID when retrying the same transaction. Payment idempotency expires after two weeks.")]


class RevolutBusinessCredential(BaseModel):
    model_config = ConfigDict(title="Revolut Business Access Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developer.revolut.com/docs/guides/manage-accounts/get-started/make-your-first-api-request",
        "x-credential-instructions": "Prepare an access token with your Revolut Business API certificate and JWT flow. Paste it without Bearer. Tokens expire after 40 minutes; replace an expired token here. READ is needed for reads, WRITE for counterparties and drafts, PAY for payments and exchange. This connection does not refresh tokens.",
    })
    credential_type: Literal["revolut_business_access_token"] = Field("revolut_business_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})
    environment: Literal["production", "sandbox"] = Field("production", title="Environment", description="Production uses real money. Sandbox uses test accounts and funds.")


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListAccounts(Closed):
    operation: Literal["list_accounts"] = Field("list_accounts", title="List Accounts", json_schema_extra={"ui:hidden": True})


class GetAccount(Closed):
    operation: Literal["get_account"] = Field("get_account", title="Get Account", json_schema_extra={"ui:hidden": True})
    account_id: UUID = Field(..., title="Account ID")


class GetBankDetails(Closed):
    operation: Literal["get_bank_details"] = Field("get_bank_details", title="Get Account Bank Details", json_schema_extra={"ui:hidden": True})
    account_id: UUID = Field(..., title="Account ID")


class ListTransactions(Closed):
    operation: Literal["list_transactions"] = Field("list_transactions", title="List Transactions", json_schema_extra={"ui:hidden": True})
    from_time: str | None = Field(None, title="From Date or Time", description="ISO 8601 date or timestamp.")
    to_time: str | None = Field(None, title="To Date or Time", description="One page is returned. Use the last transaction's created_at to continue.")
    account: UUID | None = Field(None, title="Account ID")
    count: int = Field(100, ge=1, le=1000, title="Page Size")
    type: Literal["atm", "card_payment", "card_refund", "card_chargeback", "card_credit", "charge", "charge_refund", "exchange", "transfer", "loan", "fee", "refund", "topup", "topup_return", "tax", "tax_refund", "rev_payment"] | None = None
    request_id: str | None = Field(None, title="Request ID")
    state: list[Literal["created", "pending", "completed", "declined", "failed", "reverted"]] | None = None


class GetTransaction(Closed):
    operation: Literal["get_transaction"] = Field("get_transaction", title="Get Transaction", json_schema_extra={"ui:hidden": True})
    transaction_id: str = Field(..., min_length=1, title="Transaction or Request ID")
    id_type: Literal["request_id"] | None = Field(None, title="ID Type", description="Set request_id to look up your supplied request ID; otherwise use a transaction ID.")

    @field_validator("transaction_id")
    @classmethod
    def path_component(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 or c in "/\\" for c in value):
            raise ValueError("Use a transaction ID or request ID without path separators")
        return value


class ListCounterparties(Closed):
    operation: Literal["list_counterparties"] = Field("list_counterparties", title="List Counterparties", json_schema_extra={"ui:hidden": True})
    name: str | None = None
    account_no: str | None = None
    sort_code: str | None = None
    iban: str | None = None
    bic: str | None = None
    created_before: datetime | None = Field(None, title="Created Before", description="Use the last counterparty's created_at for the next page.")
    limit: int = Field(100, ge=1, le=1000, title="Page Size")


class GetCounterparty(Closed):
    operation: Literal["get_counterparty"] = Field("get_counterparty", title="Get Counterparty", json_schema_extra={"ui:hidden": True})
    counterparty_id: UUID = Field(..., title="Counterparty ID")


class DeleteCounterparty(Closed):
    operation: Literal["delete_counterparty"] = Field("delete_counterparty", title="Delete Counterparty", json_schema_extra={"ui:hidden": True})
    counterparty_id: UUID = Field(..., title="Counterparty ID")


class CreateCounterparty(Closed):
    operation: Literal["create_counterparty"] = Field("create_counterparty", title="Create Revolut Counterparty by Revtag", description="Adds a recipient using their Revtag and matching name. Requires WRITE.", json_schema_extra={"ui:hidden": True})
    profile_type: Literal["personal", "business"] = Field(..., title="Profile Type")
    name: str = Field(..., min_length=1, title="Recipient Name")
    revtag: str = Field(..., min_length=1, title="Revtag")


class GetExchangeRate(Closed):
    operation: Literal["get_exchange_rate"] = Field("get_exchange_rate", title="Get Exchange Rate", json_schema_extra={"ui:hidden": True})
    from_currency: Currency = Field(..., title="From Currency")
    to_currency: Currency = Field(..., title="To Currency")
    amount: Amount = Field(1, title="Amount")


class ListExpenses(Closed):
    operation: Literal["list_expenses"] = Field("list_expenses", title="List Expenses", json_schema_extra={"ui:hidden": True})
    from_time: datetime | None = Field(None, title="From Time")
    to_time: datetime | None = Field(None, title="To Time", description="One page is returned. Use the last expense's expense_date to continue.")
    count: int = Field(100, ge=1, le=500, title="Page Size")
    state: Literal["missing_info", "awaiting_review", "reverted", "pending_reimbursement", "refund_requested", "refunded", "approved", "rejected"] | None = None
    transaction_type: Literal["atm", "card_payment", "fee", "transfer", "external", "mileage_reimbursement", "rev_payment"] | None = None


class GetExpense(Closed):
    operation: Literal["get_expense"] = Field("get_expense", title="Get Expense", json_schema_extra={"ui:hidden": True})
    expense_id: UUID = Field(..., title="Expense ID")


class ListPaymentDrafts(Closed):
    operation: Literal["list_payment_drafts"] = Field("list_payment_drafts", title="List Payment Drafts", json_schema_extra={"ui:hidden": True})
    source: Literal["api", "integration", "email", "all"] | None = Field(None, title="Source")


class GetPaymentDraft(Closed):
    operation: Literal["get_payment_draft"] = Field("get_payment_draft", title="Get Payment Draft", json_schema_extra={"ui:hidden": True})
    payment_draft_id: UUID = Field(..., title="Payment Draft ID")


class DeletePaymentDraft(Closed):
    operation: Literal["delete_payment_draft"] = Field("delete_payment_draft", title="Delete Payment Draft", json_schema_extra={"ui:hidden": True})
    payment_draft_id: UUID = Field(..., title="Payment Draft ID")


class Receiver(Closed):
    counterparty_id: UUID = Field(..., title="Counterparty ID")
    account_id: UUID | None = Field(None, title="Recipient Account ID")
    card_id: UUID | None = Field(None, title="Recipient Card ID")

    @model_validator(mode="after")
    def single_method(self):
        if self.account_id and self.card_id:
            raise ValueError("Choose an account or a card, not both")
        return self


class DraftPayment(Closed):
    account_id: UUID = Field(..., title="Source Account ID")
    receiver: Receiver = Field(..., title="Receiver")
    amount: Amount = Field(..., title="Amount")
    currency: Currency = Field(..., title="Currency")
    reference: str = Field(..., max_length=255, title="Reference")
    charge_bearer: Literal["shared", "debtor"] | None = None
    transfer_reason_code: str | None = None


class CreatePaymentDraft(Closed):
    operation: Literal["create_payment_draft"] = Field("create_payment_draft", title="Create Payment Draft", description="Creates a draft for approval in Revolut Business. Requires WRITE.", json_schema_extra={"ui:hidden": True})
    title: str | None = Field(None, min_length=1, max_length=255, title="Title")
    schedule_for: date | None = Field(None, title="Scheduled Date")
    payments: list[DraftPayment] = Field(..., min_length=1, title="Payments")

    @model_validator(mode="after")
    def one_source(self):
        if len({p.account_id for p in self.payments}) != 1:
            raise ValueError("All payments in a draft must use the same source account")
        if len(self.payments) > 1 and any(p.charge_bearer for p in self.payments):
            raise ValueError("Bulk drafts do not support charge bearer selection")
        return self


class CreatePayment(Closed):
    operation: Literal["create_payment"] = Field("create_payment", title="Send Payment", description="Sends real funds in production. Requires PAY. A pending response does not mean completion.", json_schema_extra={"ui:hidden": True})
    request_id: RequestID = Field(..., title="Request ID")
    account_id: UUID = Field(..., title="Source Account ID")
    receiver: Receiver = Field(..., title="Receiver")
    amount: Amount = Field(..., title="Amount")
    currency: Currency = Field(..., title="Currency")
    reference: str | None = Field(None, max_length=140, title="Reference")
    charge_bearer: Literal["shared", "debtor"] | None = None
    transfer_reason_code: str | None = None
    exchange_reason_code: str | None = None
    fiscal_code: str | None = Field(None, max_length=50, pattern=r"^[a-zA-Z0-9]+$")
    name_validation_id: UUID | None = None


class CreateTransfer(Closed):
    operation: Literal["create_transfer"] = Field("create_transfer", title="Transfer Between Own Accounts", description="Moves funds between your accounts in the same currency. Requires PAY.", json_schema_extra={"ui:hidden": True})
    request_id: RequestID = Field(..., title="Request ID")
    source_account_id: UUID = Field(..., title="Source Account ID")
    target_account_id: UUID = Field(..., title="Target Account ID")
    amount: Amount = Field(..., title="Amount")
    currency: Currency = Field(..., title="Currency")
    reference: str | None = None


class ExchangePart(Closed):
    account_id: UUID = Field(..., title="Account ID")
    currency: Currency = Field(..., title="Currency")
    amount: Amount | None = Field(None, title="Amount")


class ExchangeMoney(Closed):
    operation: Literal["exchange_money"] = Field("exchange_money", title="Exchange Currency", description="Exchanges real funds. Specify amount on exactly one side: sell from, or buy to. Requires PAY.", json_schema_extra={"ui:hidden": True})
    request_id: RequestID = Field(..., title="Request ID")
    from_side: ExchangePart = Field(..., title="Sell From")
    to_side: ExchangePart = Field(..., title="Buy To")
    reference: str | None = None
    exchange_reason_code: str | None = None

    @model_validator(mode="after")
    def one_amount(self):
        if (self.from_side.amount is None) == (self.to_side.amount is None):
            raise ValueError("Supply an amount on exactly one exchange side")
        return self


class ListCards(Closed):
    created_before: datetime | None = Field(None, title="Created Before", description="Use the last card created_at to continue.")
    limit: int = Field(100, ge=1, le=100, title="Page Size")
    operation: Literal["list_cards"] = Field("list_cards", title="List Cards", json_schema_extra={"ui:hidden": True})


class GetCard(Closed):
    operation: Literal["get_card"] = Field("get_card", title="Get Card", json_schema_extra={"ui:hidden": True})
    card_id: UUID = Field(..., title="Card ID")


Operation = Annotated[Union[ListAccounts, GetAccount, GetBankDetails, ListTransactions, GetTransaction,
    ListCounterparties, GetCounterparty, CreateCounterparty, DeleteCounterparty, GetExchangeRate,
    ListExpenses, GetExpense, ListPaymentDrafts, GetPaymentDraft, CreatePaymentDraft,
    DeletePaymentDraft, CreatePayment, CreateTransfer, ExchangeMoney, ListCards, GetCard], Field(discriminator="operation")]


class RevolutBusinessConfig(NodeConfig[Operation, RevolutBusinessCredential]):
    pass


# Each route represents exactly one operation in the provider contract.
ROUTES = {
    "list_cards": ("GET", "/cards"),
    "get_card": ("GET", "/cards/{card_id}"),
    "list_accounts": ("GET", "/accounts"),
    "get_account": ("GET", "/accounts/{account_id}"),
    "get_bank_details": ("GET", "/accounts/{account_id}/bank-details"),
    "list_transactions": ("GET", "/transactions"),
    "get_transaction": ("GET", "/transaction/{transaction_id}"),
    "list_counterparties": ("GET", "/counterparties"),
    "get_counterparty": ("GET", "/counterparty/{counterparty_id}"),
    "create_counterparty": ("POST", "/counterparty"),
    "delete_counterparty": ("DELETE", "/counterparty/{counterparty_id}"),
    "get_exchange_rate": ("GET", "/rate"),
    "list_expenses": ("GET", "/expenses"),
    "get_expense": ("GET", "/expenses/{expense_id}"),
    "list_payment_drafts": ("GET", "/payment-drafts"),
    "get_payment_draft": ("GET", "/payment-drafts/{payment_draft_id}"),
    "create_payment_draft": ("POST", "/payment-drafts"),
    "delete_payment_draft": ("DELETE", "/payment-drafts/{payment_draft_id}"),
    "create_payment": ("POST", "/pay"),
    "create_transfer": ("POST", "/transfer"),
    "exchange_money": ("POST", "/exchange"),
}


class RevolutBusinessNode(WorkflowNode):
    integration_type = "automation-revolut-for-business"
    connection_evidence = ConnectionEvidence(noun="accounts", operation="list_accounts")

    @classmethod
    def get_config_model(cls):
        return RevolutBusinessConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Revolut Business access token")
        method, path = ROUTES[config.operation]
        data = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for key in list(data):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(data.pop(key)), safe=""))
        renames = {"from_time": "from", "to_time": "to", "from_currency": "from", "to_currency": "to", "from_side": "from", "to_side": "to"}
        data = {renames.get(k, k): v for k, v in data.items()}
        base = "https://b2b.revolut.com/api/1.0" if credential.environment == "production" else "https://sandbox-b2b.revolut.com/api/1.0"
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, base + path,
                headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"},
                params=data if method == "GET" else None,
                json=data if method == "POST" else None)
        response.raise_for_status()
        if not response.content:
            if method != "DELETE":
                raise ValueError("Revolut returned an empty response")
            return {"status": "success", "deleted": True}
        body = response.json()
        if not isinstance(body, (dict, list)):
            raise ValueError("Revolut returned an unexpected response shape")
        if isinstance(body, dict) and ("error" in body or "message" in body and "code" in body):
            raise ValueError("Revolut returned an API error")
        if config.operation.startswith("list_"):
            if config.operation == "list_payment_drafts":
                body = body.get("payment_orders") if isinstance(body, dict) else None
            if not isinstance(body, list):
                raise ValueError("Revolut returned an unexpected list response")
            return {"status": "success", "items": body, "page_only": True}
        return {"status": "success", "data": body}
