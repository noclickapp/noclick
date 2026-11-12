"""PocketSmith v2 personal-finance operations using a manually supplied developer key.

Contract: https://raw.githubusercontent.com/pocketsmith/api/master/openapi.json
Auth and paging: https://developers.pocketsmith.com/docs/introduction and /docs/pagination.
"""
from __future__ import annotations

from datetime import date as Date
from typing import Annotated, Literal, Union
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.pocketsmith.com/v2"
ID = Annotated[int, Field(gt=0, strict=True)]
Money = Annotated[float, Field(allow_inf_nan=False)]
Text = Annotated[str, Field(max_length=10000)]


class PocketSmithDeveloperKeyCredential(BaseModel):
    model_config = ConfigDict(title="PocketSmith Developer Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.pocketsmith.com/docs/introduction",
            "x-credential-instructions": "In PocketSmith, open Profile > Security & integrations > Manage developer keys. Create a key for your own account and paste it here. The key can read and change your financial data. NoClick sends it only to api.pocketsmith.com in the X-Developer-Key header.",
        })
    credential_type: Literal["pocketsmith_developer_key"] = Field("pocketsmith_developer_key", json_schema_extra={"ui:hidden": True})
    developer_key: str = Field(..., title="Developer key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("developer_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your developer key as text")
        value = clean_secret(value, field_name="Developer key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the developer key without a header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class UserInput(Input):
    user_id: ID = Field(..., description="PocketSmith user ID from Get me.")


class GetMe(Input):
    operation: Literal["get_me"] = Field("get_me", title="Get Me", json_schema_extra={"ui:hidden": True})


class GetUser(UserInput):
    operation: Literal["get_user"] = Field("get_user", title="Get User", json_schema_extra={"ui:hidden": True})


class ListAccounts(UserInput):
    operation: Literal["list_accounts"] = Field("list_accounts", title="List Accounts", json_schema_extra={"ui:hidden": True})


class GetAccount(Input):
    operation: Literal["get_account"] = Field("get_account", title="Get Account", json_schema_extra={"ui:hidden": True})
    account_id: ID


class ListTransactionAccounts(UserInput):
    operation: Literal["list_transaction_accounts"] = Field("list_transaction_accounts", title="List Transaction Accounts", json_schema_extra={"ui:hidden": True})


class GetTransactionAccount(Input):
    operation: Literal["get_transaction_account"] = Field("get_transaction_account", title="Get Transaction Account", json_schema_extra={"ui:hidden": True})
    transaction_account_id: ID


class UpdateTransactionAccount(Input):
    operation: Literal["update_transaction_account"] = Field("update_transaction_account", title="Update Transaction Account", json_schema_extra={"ui:hidden": True})
    transaction_account_id: ID
    institution_id: ID | None = None
    starting_balance: Money | None = None
    starting_balance_date: Date | None = None

    @model_validator(mode="after")
    def changes(self):
        if not any(getattr(self, key) is not None for key in ("institution_id", "starting_balance", "starting_balance_date")):
            raise ValueError("Provide at least one transaction account field to change")
        return self


class TransactionFilters(Input):
    start_date: Date | None = None
    end_date: Date | None = None
    updated_since: str | None = Field(None, max_length=100, description="ISO 8601 update timestamp.")
    uncategorised: Literal[0, 1] | None = None
    type: Literal["debit", "credit"] | None = None
    needs_review: Literal[0, 1] | None = None
    search: Text | None = None
    page: int = Field(1, ge=1, le=1000000, strict=True, description="One page per run. Use next_page from the previous output.")

    @model_validator(mode="after")
    def dates(self):
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("Provide both start_date and end_date")
        if self.start_date and self.start_date > self.end_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class ListTransactions(TransactionFilters, UserInput):
    operation: Literal["list_transactions"] = Field("list_transactions", title="List Transactions", json_schema_extra={"ui:hidden": True})


class ListTransactionAccountTransactions(TransactionFilters):
    operation: Literal["list_transaction_account_transactions"] = Field("list_transaction_account_transactions", title="List Transaction Account Transactions", json_schema_extra={"ui:hidden": True})
    transaction_account_id: ID


class GetTransaction(Input):
    operation: Literal["get_transaction"] = Field("get_transaction", title="Get Transaction", json_schema_extra={"ui:hidden": True})
    transaction_id: ID


class TransactionFields(Input):
    payee: Text | None = None
    amount: Money | None = None
    date: Date | None = None
    is_transfer: StrictBool | None = None
    labels: Text | None = Field(None, description="Comma-separated labels. Omit to leave unchanged on update.")
    category_id: ID | None = None
    note: Text | None = None
    memo: Text | None = None
    cheque_number: Text | None = None
    needs_review: StrictBool | None = None


class CreateTransaction(TransactionFields):
    operation: Literal["create_transaction"] = Field("create_transaction", title="Create Transaction", json_schema_extra={"ui:hidden": True})
    transaction_account_id: ID
    payee: Text
    amount: Money = Field(..., description="Signed amount: positive credit, negative debit.")
    date: Date


class UpdateTransaction(TransactionFields):
    operation: Literal["update_transaction"] = Field("update_transaction", title="Update Transaction", json_schema_extra={"ui:hidden": True})
    transaction_id: ID

    @model_validator(mode="after")
    def changes(self):
        if not any(getattr(self, key) is not None for key in TransactionFields.model_fields):
            raise ValueError("Provide at least one transaction field to change")
        return self


class DeleteTransaction(Input):
    operation: Literal["delete_transaction"] = Field("delete_transaction", title="Delete Transaction", json_schema_extra={"ui:hidden": True})
    transaction_id: ID = Field(..., description="Transaction to permanently delete.")


class ListCategories(UserInput):
    operation: Literal["list_categories"] = Field("list_categories", title="List Categories", json_schema_extra={"ui:hidden": True})


class GetCategory(Input):
    operation: Literal["get_category"] = Field("get_category", title="Get Category", json_schema_extra={"ui:hidden": True})
    category_id: ID


class CategoryFields(Input):
    title: Text | None = None
    colour: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$", description="CSS hex colour, for example #e0e7ff.")
    parent_id: ID | None = None
    is_transfer: StrictBool | None = None
    is_bill: StrictBool | None = None
    roll_up: StrictBool | None = None
    refund_behaviour: Literal["debits_are_deductions", "credits_are_refunds"] | None = Field(None, description="Refund behaviour. Omit to leave unchanged.")


class CreateCategory(CategoryFields, UserInput):
    operation: Literal["create_category"] = Field("create_category", title="Create Category", json_schema_extra={"ui:hidden": True})
    title: Text = Field(..., min_length=1)


class UpdateCategory(CategoryFields):
    operation: Literal["update_category"] = Field("update_category", title="Update Category", json_schema_extra={"ui:hidden": True})
    category_id: ID

    @model_validator(mode="after")
    def changes(self):
        if not any(getattr(self, key) is not None for key in CategoryFields.model_fields):
            raise ValueError("Provide at least one category field to change")
        return self


class DeleteCategory(Input):
    operation: Literal["delete_category"] = Field("delete_category", title="Delete Category", json_schema_extra={"ui:hidden": True})
    category_id: ID = Field(..., description="Deleting a category also deletes its budgets and uncategorises its transactions.")


class ListLabels(UserInput):
    operation: Literal["list_labels"] = Field("list_labels", title="List Labels", json_schema_extra={"ui:hidden": True})


class ListSavedSearches(UserInput):
    operation: Literal["list_saved_searches"] = Field("list_saved_searches", title="List Saved Searches", json_schema_extra={"ui:hidden": True})


class GetBudgetSummary(UserInput):
    operation: Literal["get_budget_summary"] = Field("get_budget_summary", title="Get Budget Summary", json_schema_extra={"ui:hidden": True})
    period: Literal["weeks", "months", "years", "event"]
    interval: int = Field(..., ge=1, strict=True)
    start_date: Date
    end_date: Date

    @model_validator(mode="after")
    def dates(self):
        if self.start_date > self.end_date:
            raise ValueError("end_date must be on or after start_date")
        return self


# PocketSmith's own MCP server: agents get its tools through a person's PocketSmith sign-in.
PocketsmithMcpCredential = mcp_credential("pocketsmith", "https://mcp.pocketsmith.com/mcp", app="PocketSmith")
PocketSmithCredential = Union[PocketSmithDeveloperKeyCredential, PocketsmithMcpCredential]


PocketSmithOperation = Annotated[Union[GetMe, GetUser, ListAccounts, GetAccount,
    ListTransactionAccounts, GetTransactionAccount, UpdateTransactionAccount,
    ListTransactions, ListTransactionAccountTransactions, GetTransaction,
    CreateTransaction, UpdateTransaction, DeleteTransaction, ListCategories,
    GetCategory, CreateCategory, UpdateCategory, DeleteCategory, ListLabels,
    ListSavedSearches, GetBudgetSummary], Field(discriminator="operation")]


class PocketSmithConfig(NodeConfig[PocketSmithOperation, PocketSmithCredential]):
    pass


# Each operation issues exactly one request to its documented endpoint.
ROUTES = {
    "get_me": ("GET", "/me", None),
    "get_user": ("GET", "/users/{user_id}", "user_id"),
    "list_accounts": ("GET", "/users/{user_id}/accounts", "user_id"),
    "get_account": ("GET", "/accounts/{account_id}", "account_id"),
    "list_transaction_accounts": ("GET", "/users/{user_id}/transaction_accounts", "user_id"),
    "get_transaction_account": ("GET", "/transaction_accounts/{transaction_account_id}", "transaction_account_id"),
    "update_transaction_account": ("PUT", "/transaction_accounts/{transaction_account_id}", "transaction_account_id"),
    "list_transactions": ("GET", "/users/{user_id}/transactions", "user_id"),
    "list_transaction_account_transactions": ("GET", "/transaction_accounts/{transaction_account_id}/transactions", "transaction_account_id"),
    "get_transaction": ("GET", "/transactions/{transaction_id}", "transaction_id"),
    "create_transaction": ("POST", "/transaction_accounts/{transaction_account_id}/transactions", "transaction_account_id"),
    "update_transaction": ("PUT", "/transactions/{transaction_id}", "transaction_id"),
    "delete_transaction": ("DELETE", "/transactions/{transaction_id}", "transaction_id"),
    "list_categories": ("GET", "/users/{user_id}/categories", "user_id"),
    "get_category": ("GET", "/categories/{category_id}", "category_id"),
    "create_category": ("POST", "/users/{user_id}/categories", "user_id"),
    "update_category": ("PUT", "/categories/{category_id}", "category_id"),
    "delete_category": ("DELETE", "/categories/{category_id}", "category_id"),
    "list_labels": ("GET", "/users/{user_id}/labels", "user_id"),
    "list_saved_searches": ("GET", "/users/{user_id}/saved_searches", "user_id"),
    "get_budget_summary": ("GET", "/users/{user_id}/budget_summary", "user_id"),
}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {str(k).replace(key, "[redacted]"): _redact(v, key) for k, v in value.items()}
    return value


def _next_page(response, page):
    link = response.links.get("next")
    if not link:
        return None
    target, current = urlsplit(link["url"]), urlsplit(str(response.request.url))
    query, original = parse_qs(target.query), parse_qs(current.query)
    pages = query.pop("page", [])
    original.pop("page", None)
    if (target.scheme, target.netloc, target.path) != (current.scheme, current.netloc, current.path) or query != original or len(pages) != 1 or not pages[0].isascii() or not pages[0].isdigit():
        raise ValueError("PocketSmith returned an invalid pagination link")
    following = int(pages[0])
    if not page < following <= 1000000:
        raise ValueError("PocketSmith returned a nonadvancing pagination link")
    return following


class PocketSmithNode(WorkflowNode):
    integration_type = "automation-pocketsmith"
    credential_provider_labels = {"pocketsmith": "PocketSmith Account"}
    connection_evidence = ConnectionEvidence(noun="PocketSmith account", identity_operation="get_me", identity_keys=("name", "login", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return PocketSmithConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect your PocketSmith developer key")
        operation = self.config.config
        method, route, identifier = ROUTES[operation.operation]
        values = operation.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = route.format(**values)
        if identifier:
            values.pop(identifier)
        key = self.config.credentials.developer_key
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"X-Developer-Key": key, "Accept": "application/json"},
                    params=values if method == "GET" else None,
                    json=values if method in {"POST", "PUT"} else None)
        except httpx.RequestError:
            raise ValueError("PocketSmith request could not be confirmed; inspect writes before retrying") from None
        expected = 204 if method == "DELETE" else 201 if method == "POST" else 200
        if response.status_code != expected:
            output = {"status": "error", "http_status": response.status_code,
                "message": _redact(response.text[:2000], key),
                "write_outcome": "unverified" if method != "GET" else None}
        elif method == "DELETE":
            output = {"status": "success", "http_status": 204,
                "deleted_id": getattr(operation, identifier), "deletion_acknowledged": True}
        else:
            if len(response.content) > 10000000 or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError("PocketSmith returned an unexpected response; inspect writes before retrying")
            try:
                body = response.json()
            except ValueError:
                raise ValueError("PocketSmith returned invalid JSON; inspect writes before retrying") from None
            listing = operation.operation.startswith("list_") or operation.operation == "get_budget_summary"
            if not isinstance(body, list if listing else dict) or (isinstance(body, dict) and any(k in body for k in ("error", "errors"))):
                raise ValueError("PocketSmith returned an unexpected response shape; inspect writes before retrying")
            if operation.operation == "get_me" and (type(body.get("id")) is not int or body["id"] <= 0):
                raise ValueError("PocketSmith account identity is missing")
            output = {"status": "success", "http_status": response.status_code, "data": _redact(body, key)}
            if isinstance(operation, TransactionFilters):
                following = _next_page(response, operation.page)
                output.update(page=operation.page, next_page=following, has_more=following is not None)
        await self.emit(output)
        return output
