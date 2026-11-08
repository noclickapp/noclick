"""YNAB v1 operations using an account owner's personal access token.

Each action sends one request to the published 1.89.0 plans API. Amounts stay
in integer milliunits, and delta reads retain the server knowledge cursor.
"""
from __future__ import annotations

import re
from datetime import date as Date
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.ynab.com/v1"


class YnabPersonalAccessTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="YNAB Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.ynab.com/settings/developer",
            "x-credential-instructions": "In YNAB Account Settings, open Developer Settings and generate a Personal Access Token. Paste the token for your own account. NoClick uses it to read and update your plans. Amounts are in milliunits: 1000 is one currency unit.",
        },
    )
    credential_type: Literal["ynab_personal_access_token"] = Field(
        "ynab_personal_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=4096, repr=False,
        title="Personal access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your personal access token")
        value = clean_secret(value, field_name="Personal access token", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name.endswith("_id") and info.field_name != "import_id" and isinstance(value, str):
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
                raise ValueError("Use a single YNAB resource ID")
        return value


def _plan_field():
    return Field(..., title="Plan ID", description="Copy a plan ID from List Plans. YNAB also accepts last-used or default; default requires default plan selection.",
        json_schema_extra={"x-dynamic-options": {"field_name": "plan_id", "allow_custom": True}})


class _Plan(_Input):
    plan_id: str = _plan_field()


class _Delta(_Plan):
    last_knowledge_of_server: int | None = Field(None, ge=0,
        description="Use server_knowledge from a previous response to return changes, including deleted records.")


class GetUser(_Input):
    """Read the authenticated YNAB user ID."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})


class ListPlans(_Input):
    """List the connected account's plans."""
    operation: Literal["list_plans"] = Field("list_plans", json_schema_extra={"ui:hidden": True})
    include_accounts: StrictBool | None = None


class GetPlan(_Delta):
    """Read a plan with its accounts, categories, transactions and server knowledge."""
    operation: Literal["get_plan"] = Field("get_plan", json_schema_extra={"ui:hidden": True})


class ListAccounts(_Delta):
    """List plan accounts and balances in milliunits."""
    operation: Literal["list_accounts"] = Field("list_accounts", json_schema_extra={"ui:hidden": True})


class GetAccount(_Plan):
    """Read one plan account."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})
    account_id: UUID


class CreateAccount(_Plan):
    """Create an account with an opening balance in milliunits."""
    operation: Literal["create_account"] = Field("create_account", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    type: Literal["checking", "savings", "cash", "creditCard", "otherAsset", "otherLiability"]
    balance: int = Field(..., strict=True, description="Opening balance in milliunits; 1000 = one currency unit.")


class ListCategories(_Delta):
    """List category groups with their categories."""
    operation: Literal["list_categories"] = Field("list_categories", json_schema_extra={"ui:hidden": True})


class GetCategory(_Plan):
    """Read one category for the current month."""
    operation: Literal["get_category"] = Field("get_category", json_schema_extra={"ui:hidden": True})
    category_id: UUID


class UpdateCategory(GetCategory):
    """Rename a category and optionally update its note or target."""
    operation: Literal["update_category"] = Field("update_category", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    note: str | None = None
    goal_target: int | None = Field(None, strict=True, description="Milliunits. Explicit null removes an existing target.")
    goal_target_date: Date | None = None


class _Month(_Plan):
    month: Date = Field(..., description="Month as an ISO date, e.g. 2016-12-01. Use the first day of the month.")


class UpdateMonthCategory(_Month):
    """Assign an amount to a category for a specific month."""
    operation: Literal["update_month_category"] = Field("update_month_category", json_schema_extra={"ui:hidden": True})
    category_id: UUID
    budgeted: int = Field(..., strict=True, description="Assigned amount in milliunits.")


class ListPayees(_Delta):
    """List the plan's payees, including transfer payees."""
    operation: Literal["list_payees"] = Field("list_payees", json_schema_extra={"ui:hidden": True})


class UpdatePayee(_Plan):
    """Rename a payee."""
    operation: Literal["update_payee"] = Field("update_payee", json_schema_extra={"ui:hidden": True})
    payee_id: UUID
    name: str = Field(..., min_length=1, max_length=500)


class ListMonths(_Delta):
    """List monthly summaries and server knowledge."""
    operation: Literal["list_months"] = Field("list_months", json_schema_extra={"ui:hidden": True})


class GetMonth(_Month):
    """Read a month's income, spending and categories."""
    operation: Literal["get_month"] = Field("get_month", json_schema_extra={"ui:hidden": True})


class ListTransactions(_Delta):
    """List transactions with date, review-state and delta filters."""
    operation: Literal["list_transactions"] = Field("list_transactions", json_schema_extra={"ui:hidden": True})
    since_date: Date | None = Field(None, description="Inclusive start. If omitted, YNAB defaults to one year ago.")
    until_date: Date | None = Field(None, description="Inclusive end date.")
    type: Literal["uncategorized", "unapproved"] | None = None


class ListAccountTransactions(ListTransactions):
    """List transactions for one account with the same filters as plan transactions."""
    operation: Literal["list_account_transactions"] = Field("list_account_transactions", json_schema_extra={"ui:hidden": True})
    account_id: UUID


class GetTransaction(_Plan):
    """Read one transaction, including subtransactions."""
    operation: Literal["get_transaction"] = Field("get_transaction", json_schema_extra={"ui:hidden": True})
    transaction_id: str


class _TransactionFields(_Plan):
    payee_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    payee_name: str | None = Field(None, max_length=200)
    category_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    memo: str | None = Field(None, max_length=500)
    flag_color: Literal["red", "orange", "yellow", "green", "blue", "purple", ""] | None = None


class CreateTransaction(_TransactionFields):
    """Create one transaction; an import ID can prevent duplicate imports."""
    operation: Literal["create_transaction"] = Field("create_transaction", json_schema_extra={"ui:hidden": True})
    account_id: str = Field(..., json_schema_extra={"format": "uuid"})
    date: Date = Field(..., description="Transaction date in YYYY-MM-DD format; future dates require a scheduled transaction.")
    amount: int = Field(..., strict=True, description="Signed milliunits: -12500 spends 12.50 currency units.")
    cleared: Literal["cleared", "uncleared", "reconciled"] | None = None
    approved: StrictBool | None = None
    import_id: str | None = Field(None, max_length=36)


class UpdateTransaction(_TransactionFields):
    """Update a transaction's memo and optionally its amount, category or review state."""
    operation: Literal["update_transaction"] = Field("update_transaction", json_schema_extra={"ui:hidden": True})
    transaction_id: str
    memo: str | None = Field(..., max_length=500)
    account_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    date: Date | None = None
    amount: int | None = Field(None, strict=True, description="Signed milliunits.")
    cleared: Literal["cleared", "uncleared", "reconciled"] | None = None
    approved: StrictBool | None = None


class DeleteTransaction(GetTransaction):
    """Delete the selected transaction."""
    operation: Literal["delete_transaction"] = Field("delete_transaction", json_schema_extra={"ui:hidden": True})


class ListScheduledTransactions(_Delta):
    """List future and recurring transactions."""
    operation: Literal["list_scheduled_transactions"] = Field("list_scheduled_transactions", json_schema_extra={"ui:hidden": True})


class GetScheduledTransaction(_Plan):
    """Read one scheduled transaction."""
    operation: Literal["get_scheduled_transaction"] = Field("get_scheduled_transaction", json_schema_extra={"ui:hidden": True})
    scheduled_transaction_id: str


class CreateScheduledTransaction(_TransactionFields):
    """Create a future or recurring transaction."""
    operation: Literal["create_scheduled_transaction"] = Field("create_scheduled_transaction", json_schema_extra={"ui:hidden": True})
    account_id: str = Field(..., json_schema_extra={"format": "uuid"})
    date: Date = Field(..., description="Future ISO date, no more than five years ahead.")
    amount: int | None = Field(None, strict=True, description="Signed milliunits.")
    frequency: Literal["never", "daily", "weekly", "everyOtherWeek", "twiceAMonth", "every4Weeks", "monthly", "everyOtherMonth", "every3Months", "every4Months", "twiceAYear", "yearly", "everyOtherYear"] | None = None


class UpdateScheduledTransaction(CreateScheduledTransaction):
    """Update a scheduled transaction with its account and next date."""
    operation: Literal["update_scheduled_transaction"] = Field("update_scheduled_transaction", json_schema_extra={"ui:hidden": True})
    scheduled_transaction_id: str


class DeleteScheduledTransaction(GetScheduledTransaction):
    """Delete the selected scheduled transaction."""
    operation: Literal["delete_scheduled_transaction"] = Field("delete_scheduled_transaction", json_schema_extra={"ui:hidden": True})


YnabOperation = Annotated[Union[
    GetUser, ListPlans, GetPlan, ListAccounts, GetAccount, CreateAccount,
    ListCategories, GetCategory, UpdateCategory, UpdateMonthCategory, ListPayees,
    UpdatePayee, ListMonths, GetMonth, ListTransactions, ListAccountTransactions,
    GetTransaction, CreateTransaction, UpdateTransaction, DeleteTransaction,
    ListScheduledTransactions, GetScheduledTransaction, CreateScheduledTransaction,
    UpdateScheduledTransaction, DeleteScheduledTransaction,
], Field(discriminator="operation")]


class YnabNodeConfig(NodeConfig[YnabOperation, YnabPersonalAccessTokenCredential]):
    pass


# method, provider path, body wrapper (None for no body), expected data member.
ROUTES = {
    "get_user": ("GET", "/user", None, "user"),
    "list_plans": ("GET", "/plans", None, "plans"),
    "get_plan": ("GET", "/plans/{plan_id}", None, "plan"),
    "list_accounts": ("GET", "/plans/{plan_id}/accounts", None, "accounts"),
    "get_account": ("GET", "/plans/{plan_id}/accounts/{account_id}", None, "account"),
    "create_account": ("POST", "/plans/{plan_id}/accounts", "account", "account"),
    "list_categories": ("GET", "/plans/{plan_id}/categories", None, "category_groups"),
    "get_category": ("GET", "/plans/{plan_id}/categories/{category_id}", None, "category"),
    "update_category": ("PATCH", "/plans/{plan_id}/categories/{category_id}", "category", "category"),
    "update_month_category": ("PATCH", "/plans/{plan_id}/months/{month}/categories/{category_id}", "category", "category"),
    "list_payees": ("GET", "/plans/{plan_id}/payees", None, "payees"),
    "update_payee": ("PATCH", "/plans/{plan_id}/payees/{payee_id}", "payee", "payee"),
    "list_months": ("GET", "/plans/{plan_id}/months", None, "months"),
    "get_month": ("GET", "/plans/{plan_id}/months/{month}", None, "month"),
    "list_transactions": ("GET", "/plans/{plan_id}/transactions", None, "transactions"),
    "list_account_transactions": ("GET", "/plans/{plan_id}/accounts/{account_id}/transactions", None, "transactions"),
    "get_transaction": ("GET", "/plans/{plan_id}/transactions/{transaction_id}", None, "transaction"),
    "create_transaction": ("POST", "/plans/{plan_id}/transactions", "transaction", "transaction"),
    "update_transaction": ("PUT", "/plans/{plan_id}/transactions/{transaction_id}", "transaction", "transaction"),
    "delete_transaction": ("DELETE", "/plans/{plan_id}/transactions/{transaction_id}", None, "transaction"),
    "list_scheduled_transactions": ("GET", "/plans/{plan_id}/scheduled_transactions", None, "scheduled_transactions"),
    "get_scheduled_transaction": ("GET", "/plans/{plan_id}/scheduled_transactions/{scheduled_transaction_id}", None, "scheduled_transaction"),
    "create_scheduled_transaction": ("POST", "/plans/{plan_id}/scheduled_transactions", "scheduled_transaction", "scheduled_transaction"),
    "update_scheduled_transaction": ("PUT", "/plans/{plan_id}/scheduled_transactions/{scheduled_transaction_id}", "scheduled_transaction", "scheduled_transaction"),
    "delete_scheduled_transaction": ("DELETE", "/plans/{plan_id}/scheduled_transactions/{scheduled_transaction_id}", None, "scheduled_transaction"),
}


class YnabNode(WorkflowNode):
    integration_type = "automation-ynab"
    connection_evidence = ConnectionEvidence(field="plan_id", noun="plans", operation="list_plans")

    @classmethod
    def get_config_model(cls):
        return YnabNodeConfig

    @classmethod
    async def _request(cls, credential, method, path, *, params=None, body=None):
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            try:
                error = response.json().get("error", {})
                message = error.get("detail") or error.get("name") or "YNAB request failed"
            except (ValueError, AttributeError):
                message = "YNAB request failed"
            message = str(message).replace(credential.access_token, "[redacted]")
            raise ValueError(f"YNAB HTTP {response.status_code}: {message}")
        payload = response.json()
        if not isinstance(payload, dict) or "error" in payload or not isinstance(payload.get("data"), dict):
            raise ValueError("YNAB returned an invalid response envelope")
        return payload["data"]

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        if field_name != "plan_id":
            return []
        credential = YnabPersonalAccessTokenCredential.model_validate(credential_data)
        data = await cls._request(credential, "GET", "/plans")
        plans = data.get("plans")
        if not isinstance(plans, list):
            raise ValueError("YNAB returned an invalid plans list")
        return [{"value": plan["id"], "label": plan["name"]} for plan in plans
            if not search or search.casefold() in plan["name"].casefold()]

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a YNAB personal access token")
        config = self.config.config
        method, template, wrapper, member = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_unset=True)
        path_fields = re.findall(r"\{(\w+)\}", template)
        path = template.format(**{key: quote(str(getattr(config, key)), safe="") for key in path_fields})
        fields = {key: value for key, value in values.items() if key != "operation" and key not in path_fields}
        # Null is meaningful for nullable write fields, while absent fields must
        # stay absent. Query booleans use the provider's lowercase spelling.
        params = {key: str(value).lower() if isinstance(value, bool) else value
            for key, value in fields.items() if value is not None} if method == "GET" else None
        nullable = {"note", "goal_target", "goal_target_date", "memo", "payee_id", "payee_name", "category_id", "flag_color"}
        body = {wrapper: {key: value for key, value in fields.items() if value is not None or key in nullable}} if wrapper else None
        data = await self._request(self.config.credentials, method, path, params=params, body=body)
        expected = data.get(member)
        # The create response supports either transaction or transactions. The
        # single-object request normally selects transaction; preserve either.
        if config.operation == "create_transaction" and expected is None:
            expected = data.get("transactions")
        if not isinstance(expected, list if config.operation.startswith("list_") else (dict, list) if config.operation == "create_transaction" else dict):
            raise ValueError("YNAB response is missing " + member)
        return {"status": "success", "operation": config.operation, "data": data}
