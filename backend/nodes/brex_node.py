"""Brex expenses, cards, transactions and transfers.

API: https://developer.brex.com/ (official OpenAPI descriptions).
Auth: user-generated bearer token; no OAuth application required.
List operations return one page and preserve next_cursor for explicit pagination.
Webhook registration and signed deliveries follow the official Webhooks API.
"""
import base64
import binascii
import hashlib
import hmac
import json
import time
import uuid
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    field_validator,
    model_validator,
)

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.scopes.brex import BREX_SCOPES

BREX_API_BASE = "https://api.brex.com"


class BrexAPITokenCredential(BaseModel):
    credential_type: Literal["brex_api_token"] = Field(
        "brex_api_token", json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(
        ...,
        title="API Token",
        min_length=1,
        description="User token generated in Brex Developer settings.",
        json_schema_extra={"ui:widget": "password"},
    )
    model_config = ConfigDict(
        title="Brex API Token",
        json_schema_extra={
            "x-credential-url": "https://dashboard.brex.com/settings/developer",
            "x-help-url": "https://developer.brex.com/guides/authentication",
            "x-credential-instructions": "In Brex Developer settings, create a token with companies.readonly for the connection check. Enable expenses.card, cards, accounts.cash.readonly, accounts.card.readonly, transactions.card.readonly, transactions.cash.readonly, transfers, transfers.readonly and vendors.readonly for the operations you use. Copy the token when it is created; Brex only shows it once.",
        }
    )


def _operation(name: str, category: str):
    return Field(
        name,
        title=name.replace("_", " ").title(),
        json_schema_extra={
            "const": name,
            "ui:hidden": True,
            "x-category": category,
            "x-display-name": name.replace("_", " ").title(),
            "x-is-trigger": False,
        },
    )


class BrexPageConfig(BaseModel):
    cursor: Optional[str] = Field(
        None,
        description="next_cursor from the preceding page; omitted for the first page.",
    )
    limit: int = Field(100, ge=1, description="Maximum results on this page.")


class BrexExpenseOptions(BaseModel):
    expand: Optional[str] = Field(
        None,
        description="Comma-separated expansions: merchant, user, receipts.download_uris, location, department, cost_center, budget, payment, spending_entity, policy.",
    )
    load_custom_fields: Optional[bool] = Field(
        None, description="Include custom fields."
    )
    load_expense_addenda: Optional[bool] = Field(
        None, description="Include structured purchase addenda."
    )


class BrexJSONOptions(BaseModel):
    @field_validator(
        "spend_controls", "mailing_address", "metadata", check_fields=False
    )
    @classmethod
    def json_object(cls, value):
        if value is not None:
            parsed = json.loads(value)
            if not isinstance(parsed, dict):
                raise ValueError("Enter a JSON object")
        return value


class BrexListExpensesConfig(BrexPageConfig, BrexExpenseOptions):
    operation: Literal["list_expenses"] = _operation("list_expenses", "Expenses")
    limit: int = Field(
        100, ge=1, le=100, description="Maximum expenses per page (Brex maximum: 100)."
    )
    user_ids: Optional[str] = Field(None, description="Comma-separated Brex user IDs.")
    purchased_at_start: Optional[str] = Field(
        None, description="Inclusive RFC 3339 purchase start timestamp."
    )
    purchased_at_end: Optional[str] = Field(
        None, description="Exclusive RFC 3339 purchase end timestamp."
    )
    updated_at_start: Optional[str] = Field(
        None, description="RFC 3339 update start timestamp for incremental sync."
    )
    payment_status: Optional[str] = Field(
        None, description="Comma-separated payment statuses."
    )


class BrexGetExpenseConfig(BrexExpenseOptions):
    operation: Literal["get_expense"] = _operation("get_expense", "Expenses")
    expense_id: str = Field(..., min_length=1, description="Brex expense ID.")


class BrexUpdateExpenseConfig(BaseModel):
    operation: Literal["update_expense"] = _operation("update_expense", "Expenses")
    expense_id: str = Field(..., min_length=1, description="Brex card expense ID.")
    memo: Optional[str] = Field(
        ...,
        description="New memo for the card expense. Leave empty to clear the memo (sent as null).",
    )


class BrexListCardsConfig(BrexPageConfig):
    operation: Literal["list_cards"] = _operation("list_cards", "Cards")
    user_id: Optional[str] = Field(None, description="Only cards owned by this user.")


class BrexGetCardConfig(BaseModel):
    operation: Literal["get_card"] = _operation("get_card", "Cards")
    card_id: str = Field(..., min_length=1, description="Brex card ID.")


class BrexUnlockCardConfig(BaseModel):
    operation: Literal["unlock_card"] = _operation("unlock_card", "Cards")
    card_id: str = Field(..., min_length=1, description="Brex card ID.")


class BrexCreateCardConfig(BrexJSONOptions):
    operation: Literal["create_card"] = _operation("create_card", "Cards")
    idempotency_key: str = Field(
        ...,
        min_length=1,
        description="Unique retry key. Reuse for retries of this same creation, change for a new card.",
    )
    user_id: str = Field(..., min_length=1, description="Brex user who owns the card.")
    card_name: str = Field(..., min_length=1, description="Name for the new card.")
    card_type: Literal["VIRTUAL", "PHYSICAL"] = Field(
        "VIRTUAL", description="Physical cards require a mailing address."
    )
    limit_type: Literal["CARD", "USER"] = Field(
        "USER",
        description="CARD creates a virtual vendor card with spend controls; USER uses the owner's limit.",
    )
    spend_controls: Optional[str] = Field(
        None,
        description='JSON object, required for CARD: {"spend_limit":{"amount":10000,"currency":"USD"},"spend_duration":"MONTHLY"}. Omit for USER.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    mailing_address: Optional[str] = Field(
        None,
        description="Shipping address JSON object, required for physical cards.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    metadata: Optional[str] = Field(
        None,
        description="JSON object of string key/value pairs. Do not include sensitive information.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )

    @model_validator(mode="after")
    def card_requirements(self):
        if self.limit_type == "CARD" and (
            self.card_type != "VIRTUAL" or not self.spend_controls
        ):
            raise ValueError(
                "Vendor cards require VIRTUAL card_type and spend_controls"
            )
        if self.limit_type == "USER" and self.spend_controls:
            raise ValueError("USER cards must omit spend_controls")
        if self.card_type == "PHYSICAL" and not self.mailing_address:
            raise ValueError("Physical cards require mailing_address")
        return self


class BrexUpdateCardConfig(BrexJSONOptions):
    operation: Literal["update_card"] = _operation("update_card", "Cards")
    card_id: str = Field(..., min_length=1, description="Brex vendor card ID.")
    spend_controls: Optional[str] = Field(
        None,
        description="JSON object with spend controls to change.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    metadata: Optional[str] = Field(
        None,
        description="JSON object of string key/value pairs.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class BrexLockCardConfig(BaseModel):
    operation: Literal["lock_card"] = _operation("lock_card", "Cards")
    card_id: str = Field(..., min_length=1, description="Brex card ID.")
    reason: Literal[
        "CARD_DAMAGED",
        "CARD_LOST",
        "CARD_NOT_RECEIVED",
        "DO_NOT_NEED_PHYSICAL_CARD",
        "DO_NOT_NEED_VIRTUAL_CARD",
        "FRAUD",
        "OTHER",
    ] = Field(..., description="Reason for this card status change.")
    description: Optional[str] = Field(
        None, description="Additional explanation. Brex notifies the card owner."
    )


class BrexTerminateCardConfig(BaseModel):
    operation: Literal["terminate_card"] = _operation("terminate_card", "Cards")
    card_id: str = Field(..., min_length=1, description="Brex card ID.")
    reason: Literal[
        "CARD_DAMAGED",
        "CARD_LOST",
        "CARD_NOT_RECEIVED",
        "DO_NOT_NEED_PHYSICAL_CARD",
        "DO_NOT_NEED_VIRTUAL_CARD",
        "FRAUD",
        "OTHER",
    ] = Field(..., description="Reason for this card status change.")
    description: Optional[str] = Field(
        None, description="Additional explanation. Brex notifies the card owner."
    )


class BrexListCashAccountsConfig(BaseModel):
    operation: Literal["list_cash_accounts"] = _operation(
        "list_cash_accounts", "Accounts"
    )


class BrexListCardAccountsConfig(BaseModel):
    operation: Literal["list_card_accounts"] = _operation(
        "list_card_accounts", "Accounts"
    )


class BrexGetCompanyConfig(BaseModel):
    operation: Literal["get_company"] = _operation("get_company", "Accounts")


class BrexGetCashAccountConfig(BaseModel):
    operation: Literal["get_cash_account"] = _operation("get_cash_account", "Accounts")
    account_id: str = Field(..., min_length=1, description="Brex cash account ID.")


class BrexListCardTransactionsConfig(BrexPageConfig):
    operation: Literal["list_card_transactions"] = _operation(
        "list_card_transactions", "Transactions"
    )
    posted_at_start: Optional[str] = Field(
        None,
        description="RFC 3339 start timestamp. Overlap polling windows by a few days and deduplicate by transaction ID.",
    )
    user_ids: Optional[str] = Field(None, description="Comma-separated Brex user IDs.")
    expand: Optional[str] = Field(
        None, description="Comma-separated expansions, such as expense_id."
    )


class BrexListCashTransactionsConfig(BrexPageConfig):
    operation: Literal["list_cash_transactions"] = _operation(
        "list_cash_transactions", "Transactions"
    )
    posted_at_start: Optional[str] = Field(
        None,
        description="RFC 3339 start timestamp. Overlap polling windows by a few days and deduplicate by transaction ID.",
    )
    account_id: str = Field(..., min_length=1, description="Brex cash account ID.")


class BrexListTransfersConfig(BrexPageConfig):
    operation: Literal["list_transfers"] = _operation("list_transfers", "Transfers")


class BrexGetTransferConfig(BaseModel):
    operation: Literal["get_transfer"] = _operation("get_transfer", "Transfers")
    transfer_id: str = Field(..., min_length=1, description="Brex transfer ID.")


class BrexCreateTransferConfig(BaseModel):
    operation: Literal["create_transfer"] = _operation("create_transfer", "Transfers")
    idempotency_key: str = Field(
        ...,
        min_length=1,
        description="Unique key for this transfer; reuse for retries to avoid duplicate payments.",
    )
    account_id: str = Field(
        ..., min_length=1, description="Originating Brex cash account ID."
    )
    payment_instrument_id: str = Field(
        ...,
        min_length=1,
        description="Vendor payment instrument ID from the vendor's payment_accounts details.",
    )
    amount: int = Field(
        ...,
        gt=0,
        description="Positive amount in USD cents; 100000 is $1,000. Brex supports USD transfers here.",
    )
    description: str = Field(..., description="Internal description.")
    external_memo: str = Field(
        ...,
        max_length=90,
        description="External memo, at most 90 characters for ACH/wire and 40 for cheques.",
    )
    approval_type: Optional[Literal["MANUAL"]] = Field(
        None,
        description="Require a cash admin to approve, or omit to apply the account's default policy.",
    )


class BrexListVendorsConfig(BrexPageConfig):
    operation: Literal["list_vendors"] = _operation("list_vendors", "Vendors")
    name: Optional[str] = Field(None, description="Match vendors by name.")


BREX_TRIGGER_EVENTS = {
    "on_expense_payment_updated": "EXPENSE_PAYMENT_UPDATED",
    "on_transfer_processed": "TRANSFER_PROCESSED",
}


class BrexWebhookConfig(WebhookTriggerConfigBase):
    webhook_url: Optional[str] = Field(
        None, title="Webhook URL",
        description="Registered automatically. Brex documents one endpoint per customer/client ID. Expense events require CARD_ADMIN and expenses.card.readonly.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )


class BrexOnExpensePaymentUpdatedConfig(BrexWebhookConfig):
    operation: Literal["on_expense_payment_updated"] = Field(
        "on_expense_payment_updated", title="On Expense Payment Updated",
        json_schema_extra={"const": "on_expense_payment_updated", "ui:hidden": True,
                           "x-category": "Triggers", "x-display-name": "On Expense Payment Updated", "x-is-trigger": True},
    )


class BrexOnTransferProcessedConfig(BrexWebhookConfig):
    operation: Literal["on_transfer_processed"] = Field(
        "on_transfer_processed", title="On Transfer Processed",
        json_schema_extra={"const": "on_transfer_processed", "ui:hidden": True,
                           "x-category": "Triggers", "x-display-name": "On Transfer Processed", "x-is-trigger": True},
    )


BrexConfig = Annotated[
    Union[
        BrexOnExpensePaymentUpdatedConfig,
        BrexOnTransferProcessedConfig,
        BrexListExpensesConfig,
        BrexGetExpenseConfig,
        BrexUpdateExpenseConfig,
        BrexListCardsConfig,
        BrexGetCardConfig,
        BrexUnlockCardConfig,
        BrexCreateCardConfig,
        BrexUpdateCardConfig,
        BrexLockCardConfig,
        BrexTerminateCardConfig,
        BrexListCashAccountsConfig,
        BrexListCardAccountsConfig,
        BrexGetCompanyConfig,
        BrexGetCashAccountConfig,
        BrexListCardTransactionsConfig,
        BrexListCashTransactionsConfig,
        BrexListTransfersConfig,
        BrexGetTransferConfig,
        BrexCreateTransferConfig,
        BrexListVendorsConfig,
    ],
    Discriminator("operation"),
]


class BrexNodeConfig(NodeConfig[BrexConfig, BrexAPITokenCredential]):
    pass


# Each entry maps to exactly one documented Brex API operation.
BREX_OPERATIONS = {
    "list_expenses": ("GET", "/v1/expenses"),
    "get_expense": ("GET", "/v1/expenses/{expense_id}"),
    "update_expense": ("PUT", "/v1/expenses/card/{expense_id}"),
    "list_cards": ("GET", "/v2/cards"),
    "get_card": ("GET", "/v2/cards/{card_id}"),
    "create_card": ("POST", "/v2/cards"),
    "update_card": ("PUT", "/v2/cards/{card_id}"),
    "lock_card": ("POST", "/v2/cards/{card_id}/lock"),
    "unlock_card": ("POST", "/v2/cards/{card_id}/unlock"),
    "terminate_card": ("POST", "/v2/cards/{card_id}/terminate"),
    "list_cash_accounts": ("GET", "/v2/accounts/cash"),
    "get_cash_account": ("GET", "/v2/accounts/cash/{account_id}"),
    "list_card_accounts": ("GET", "/v2/accounts/card"),
    "get_company": ("GET", "/v2/company"),
    "list_card_transactions": ("GET", "/v2/transactions/card/primary"),
    "list_cash_transactions": ("GET", "/v2/transactions/cash/{account_id}"),
    "list_transfers": ("GET", "/v1/transfers"),
    "get_transfer": ("GET", "/v1/transfers/{transfer_id}"),
    "create_transfer": ("POST", "/v1/transfers"),
    "list_vendors": ("GET", "/v1/vendors"),
}


def _split(value: Optional[str]):
    return [part.strip() for part in (value or "").split(",") if part.strip()]


class BrexNode(ExternalWebhookTriggerMixin, WorkflowNode):
    webhook_replace_stale_endpoint = True
    integration_type = "automation-brex"
    scope_registry = BREX_SCOPES
    connection_evidence = ConnectionEvidence(
        identity_operation="get_company", noun="company", identity_keys=("legal_name",)
    )

    @classmethod
    def get_config_model(cls):
        return BrexNodeConfig

    @staticmethod
    async def _webhook_request(credential, method, path, *, body=None, idempotency_key=None):
        token = (credential or {}).get("api_token")
        if not token:
            raise ValueError("Connect a Brex API token before activating this trigger")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(method, BREX_API_BASE + path, headers=headers, json=body)
        response.raise_for_status()
        return response.json() if response.content else None

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = BREX_TRIGGER_EVENTS[(config or {})["operation"]]
        # Fetch before creating a subscription so a secrets failure cannot orphan it.
        secrets = await cls._webhook_request(credential, "GET", "/v1/webhooks/secrets")
        keys = [row["secret"] for row in secrets if row["status"] in ("ACTIVE", "PENDING_REVOKE")]
        if not keys:
            raise ValueError("Brex did not return an active webhook signing secret")
        subscription = await cls._webhook_request(
            credential, "POST", "/v1/webhooks", body={"url": webhook_url, "event_types": [event]},
            idempotency_key=str(uuid.uuid4()),
        )
        if not subscription.get("id"):
            raise ValueError("Brex did not return a webhook subscription ID")
        # Base64 has no commas: keep every rotation key in the persisted secret slot.
        return {"external_webhook_id": subscription["id"], "signing_secret": ",".join(keys)}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        subscription_id = (config or {}).get("external_webhook_id")
        if subscription_id:
            await cls._webhook_request(credential, "DELETE", "/v1/webhooks/" + quote(str(subscription_id), safe=""))

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        headers = {key.lower(): value for key, value in headers.items()}
        timestamp = headers.get("webhook-timestamp", "")
        message_id = headers.get("webhook-id", "")
        if not message_id or not timestamp.isdigit() or abs(time.time() - int(timestamp)) > 60:
            return False
        message = f"{message_id}.{timestamp}.".encode() + body
        signatures = [part[3:] for part in headers.get("webhook-signature", "").split() if part.startswith("v1,")]
        for secret in ((config or {}).get("signing_secret") or "").split(","):
            try:
                key = base64.b64decode(secret)
            except (ValueError, binascii.Error):
                continue
            if not key:
                continue
            expected = base64.b64encode(hmac.new(key, message, hashlib.sha256).digest()).decode()
            if any(hmac.compare_digest(expected, signature) for signature in signatures):
                return True
        return False

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get("event_type") == BREX_TRIGGER_EVENTS.get((config or {}).get("operation"))

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"status": "success", "data": payload}

    @classmethod
    def resolve_agent_event(cls, output):
        payload = output["data"] if output.get("status") == "success" else output
        event = payload.get("event_type")
        if event == "EXPENSE_PAYMENT_UPDATED":
            resource_id = payload.get("expense_id")
            text = (f"Brex expense payment {payload.get('payment_status')}: {payload.get('payment_description')}\n"
                    f"Company: {payload.get('company_id')}; expense_id: {resource_id}; payment type: {payload.get('payment_type')}.\n"
                    f"Amount (minor currency units): {payload.get('amount')}. Use get_expense with expense_id={resource_id} for details.")
        elif event == "TRANSFER_PROCESSED":
            resource_id = payload.get("transfer_id")
            text = (f"Brex transfer processed: {resource_id}\nCompany: {payload.get('company_id')}. "
                    f"Use get_transfer with transfer_id={resource_id} for the transfer details.")
        else:
            return None
        if not resource_id:
            return None
        return {"text": text, "conversation_key": f"{payload.get('company_id')}:{resource_id}",
                "title": f"Brex {event.replace('_', ' ').lower()}"}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, BrexNodeConfig):
            raise ValueError("Brex configuration is required")
        credentials = self.config.credentials
        if not credentials:
            raise ValueError("Connect a Brex API token in the credentials tab")
        config = self.config.config
        operation = config.operation
        if operation in BREX_TRIGGER_EVENTS:
            return self.no_event_output(operation)
        method, path = BREX_OPERATIONS[operation]
        values = config.model_dump(exclude_none=True)
        for field in ("expense_id", "card_id", "account_id", "transfer_id"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", quote(values[field], safe=""))
        headers = {
            "Authorization": f"Bearer {credentials.api_token}",
            "Accept": "application/json",
        }
        if values.get("idempotency_key"):
            headers["Idempotency-Key"] = values["idempotency_key"]
        params = []
        if method == "GET":
            for key in (
                "cursor",
                "limit",
                "user_id",
                "name",
                "posted_at_start",
                "purchased_at_start",
                "purchased_at_end",
                "updated_at_start",
                "load_custom_fields",
                "load_expense_addenda",
            ):
                if key in values and values[key] != "":
                    value = values[key]
                    params.append(
                        (key, str(value).lower() if isinstance(value, bool) else value)
                    )
            for field, key in (
                ("expand", "expand[]"),
                (
                    "user_ids",
                    "user_id[]" if operation == "list_expenses" else "user_ids",
                ),
                ("payment_status", "payment_status[]"),
            ):
                params.extend((key, v) for v in _split(values.get(field)))
        body = None
        if operation == "update_expense":
            body = {"memo": config.memo}
        elif operation == "create_card":
            body = {
                "owner": {"type": "USER", "user_id": config.user_id},
                "card_name": config.card_name,
                "card_type": config.card_type,
                "limit_type": config.limit_type,
            }
            for key in ("spend_controls", "mailing_address", "metadata"):
                if values.get(key) is not None:
                    body[key] = json.loads(values[key])
        elif operation == "update_card":
            body = {
                key: json.loads(values[key])
                for key in ("spend_controls", "metadata")
                if key in values
            }
        elif operation in ("lock_card", "terminate_card"):
            body = {
                key: values[key] for key in ("reason", "description") if key in values
            }
        elif operation == "create_transfer":
            body = {
                "amount": {"amount": config.amount, "currency": "USD"},
                "counterparty": {
                    "type": "VENDOR",
                    "payment_instrument_id": config.payment_instrument_id,
                },
                "originating_account": {"type": "BREX_CASH", "id": config.account_id},
                "description": config.description,
                "external_memo": config.external_memo,
            }
            if config.approval_type is not None:
                body["approval_type"] = config.approval_type
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method,
                    BREX_API_BASE + path,
                    headers=headers,
                    params=params or None,
                    json=body,
                )
            timing = {"api_request": round((time.perf_counter() - started) * 1000, 2)}
            if not 200 <= response.status_code < 300:
                try:
                    error = response.json()
                    message = (
                        error.get("message") or error.get("error")
                        if isinstance(error, dict)
                        else None
                    )
                except ValueError:
                    message = None
                # Keep provider rejection text for connection evidence, with token redaction.
                message = str(
                    message or f"Brex API returned HTTP {response.status_code}"
                ).replace(credentials.api_token, "[redacted]")
                return {
                    "status": "error",
                    "action": operation,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": timing,
                }
            try:
                data = response.json() if response.content else {}
            except ValueError:
                return {
                    "status": "error",
                    "action": operation,
                    "error": "Brex returned an invalid JSON response",
                    "status_code": response.status_code,
                    "timing_ms": timing,
                }
            if operation == "list_card_accounts":
                valid = isinstance(data, list) and all(
                    isinstance(row, dict) for row in data
                )
                data = {"accounts": data}
            elif operation.startswith("list_"):
                valid = (
                    isinstance(data, dict)
                    and isinstance(data.get("items"), list)
                    and all(isinstance(row, dict) for row in data["items"])
                )
            else:
                valid = isinstance(data, dict) and bool(data.get("id"))
                if operation == "get_company":
                    valid = valid and bool(data.get("legal_name"))
            if not valid:
                return {
                    "status": "error",
                    "action": operation,
                    "error": "Brex returned an unexpected response shape",
                    "status_code": response.status_code,
                    "timing_ms": timing,
                }
            return {
                "status": "success",
                "action": operation,
                "data": data,
                "timing_ms": timing,
            }
        except httpx.RequestError:
            return {
                "status": "error",
                "action": operation,
                "error": "Could not reach Brex; retry the request",
                "timing_ms": {
                    "api_request": round((time.perf_counter() - started) * 1000, 2)
                },
            }
