"""Airwallex Client API 2026-08-21: account reads and explicit payout writes."""
from __future__ import annotations

import hashlib
import hmac
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase


class AirwallexAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Airwallex API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.airwallex.com/docs/developer-tools/api/manage-api-keys",
            "x-credential-instructions": "In Airwallex Settings > Developer > API keys, copy your client ID and API key. Grant the read and write permissions your operations need. Choose the matching production or sandbox environment. NoClick obtains a short-lived access token for each run; connecting reads your global accounts and does not prove write permissions.",
        })
    credential_type: Literal["airwallex_api_key"] = Field("airwallex_api_key", json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., min_length=1, title="Client ID", json_schema_extra={"ui:widget": "password"})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})
    environment: Literal["production", "sandbox"] = Field("production", title="Environment")

    account_id: str | None = Field(None, title="Target account ID", pattern=r"^[A-Za-z0-9_-]+$", description="Required when a scoped API key covers multiple accounts. Sent as x-login-as during token creation.")

    @field_validator("client_id", "api_key", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the value without whitespace or a header")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class NumberPage(Input):
    page_num: int = Field(0, ge=0, description="Zero-based page number; this operation returns one page.")
    page_size: int = Field(100, ge=1, le=100, description="Maximum records in this page.")


class CursorPage(Input):
    page: str | None = Field(None, description="Opaque page_after or page_before from the preceding response.")
    page_size: int = Field(100, ge=1, le=100)


class ListBalances(Input):
    operation: Literal["list_balances"] = "list_balances"
    account_type: str = "cash"


class BalanceHistory(NumberPage):
    operation: Literal["list_balance_history"] = "list_balance_history"
    currency: str | None = None
    from_post_at: str | None = None
    to_post_at: str | None = None


class ListTransactions(NumberPage):
    operation: Literal["list_financial_transactions"] = "list_financial_transactions"
    currency: str | None = None
    from_created_at: str | None = None
    to_created_at: str | None = None
    status: str | None = None
    source_id: str | None = None


class Resource(Input):
    id: str = Field(..., min_length=1, max_length=200, description="Airwallex resource ID.")

    @field_validator("id")
    @classmethod
    def identifier(cls, value):
        if value in {".", ".."} or any(c in value for c in "/\\?#") or any(c.isspace() for c in value):
            raise ValueError("Use a single Airwallex resource ID")
        return value


class UUIDResource(Resource):
    @field_validator("id")
    @classmethod
    def uuid_identifier(cls, value):
        return str(UUID(value))


class GetTransaction(Resource):
    operation: Literal["get_financial_transaction"] = "get_financial_transaction"


class ListBeneficiaries(NumberPage):
    operation: Literal["list_beneficiaries"] = "list_beneficiaries"
    name: str | None = None
    company_name: str | None = None
    bank_account_number: str | None = None


class GetBeneficiary(UUIDResource):
    operation: Literal["get_beneficiary"] = "get_beneficiary"


class BankDetails(Input):
    account_currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    account_name: str = Field(..., min_length=1)
    bank_country_code: str = Field(..., pattern=r"^[A-Z]{2}$")
    account_number: str | None = None
    iban: str | None = None
    swift_code: str | None = None
    account_routing_type1: str | None = None
    account_routing_value1: str | None = None
    bank_name: str | None = None


class Address(Input):
    city: str | None = None
    country_code: str = Field(..., pattern=r"^[A-Z]{2}$")
    postcode: str | None = None
    state: str | None = None
    street_address: str | None = None


class Beneficiary(Input):
    entity_type: Literal["COMPANY", "PERSONAL"]
    bank_details: BankDetails
    company_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    address: Address | None = None


class CreateBeneficiary(Input):
    operation: Literal["create_beneficiary"] = "create_beneficiary"
    beneficiary: Beneficiary
    transfer_methods: list[Literal["LOCAL", "SWIFT"]] = Field(..., min_length=1)
    nickname: str | None = None


class DeleteBeneficiary(UUIDResource):
    operation: Literal["delete_beneficiary"] = "delete_beneficiary"


class ListTransfers(CursorPage):
    operation: Literal["list_transfers"] = "list_transfers"
    beneficiary_id: str | None = None
    status: str | None = None
    transfer_currency: str | None = None
    from_created_at: str | None = None
    to_created_at: str | None = None


class GetTransfer(UUIDResource):
    operation: Literal["get_transfer"] = "get_transfer"


class TransferInput(Input):
    beneficiary_id: str = Field(..., description="ID of an existing beneficiary.")
    request_id: str = Field(..., min_length=1, description="Unique idempotency identifier. Reuse it when retrying the same transfer.")
    transfer_amount: str = Field(..., pattern=r"^[0-9]+(?:\.[0-9]+)?$", description="Amount in major currency units, as a decimal string.")
    transfer_currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    source_currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    reason: str = Field(..., min_length=1, description="Provider-supported transfer reason, for example travel.")
    reference: str = Field(..., min_length=1, description="Reference shown to the recipient.")
    transfer_method: Literal["LOCAL", "SWIFT"]
    transfer_date: str | None = Field(None, description="Scheduled date, YYYY-MM-DD.")
    swift_charge_option: Literal["SHARED", "PAYER"] | None = None

    @field_validator("beneficiary_id")
    @classmethod
    def beneficiary_uuid(cls, value):
        return str(UUID(value))


class CreateTransfer(TransferInput):
    operation: Literal["create_transfer"] = "create_transfer"


class ValidateTransfer(TransferInput):
    operation: Literal["validate_transfer"] = "validate_transfer"


class CancelTransfer(UUIDResource):
    operation: Literal["cancel_transfer"] = "cancel_transfer"


class ListGlobalAccounts(CursorPage):
    operation: Literal["list_global_accounts"] = "list_global_accounts"
    country_code: str | None = None
    nick_name: str | None = None
    status: str | None = None


class GetGlobalAccount(Resource):
    operation: Literal["get_global_account"] = "get_global_account"


class UpdateGlobalAccount(UUIDResource):
    operation: Literal["update_global_account"] = "update_global_account"
    nick_name: str = Field(..., min_length=1)


DEPOSIT_EVENTS = ("deposit.pending", "deposit.settled", "deposit.rejected", "deposit.reversed")
# These status events share the resource payload documented on the Transfers webhook page.
TRANSFER_EVENTS = (
    "payout.transfer.in_approval", "payout.transfer.scheduled", "payout.transfer.overdue",
    "payout.transfer.processing", "payout.transfer.sent", "payout.transfer.failed",
    "payout.transfer.paid", "payout.transfer.cancellation_requested", "payout.transfer.cancelled",
)


class AirwallexWebhookConfig(WebhookTriggerConfigBase):
    webhook_url: str | None = Field(None, title="Webhook URL",
        description="Registered automatically. Your API key needs webhook:write and access to the selected event.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


class OnDepositEvent(AirwallexWebhookConfig):
    operation: Literal["on_deposit_event"] = Field("on_deposit_event", title="On Deposit Event",
        json_schema_extra={"x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Deposit Event"})
    event_type: Literal[*DEPOSIT_EVENTS] = Field("deposit.settled", title="Deposit event")


class OnTransferEvent(AirwallexWebhookConfig):
    operation: Literal["on_transfer_event"] = Field("on_transfer_event", title="On Transfer Event",
        json_schema_extra={"x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Transfer Event"})
    event_type: Literal[*TRANSFER_EVENTS] = Field("payout.transfer.sent", title="Transfer event",
        description="PAID means processed by the banking partner; a transfer can still fail afterwards.")


TRIGGER_DEFAULTS = {"on_deposit_event": "deposit.settled", "on_transfer_event": "payout.transfer.sent"}


AirwallexConfig = Annotated[Union[ListBalances, BalanceHistory, ListTransactions,
    GetTransaction, ListBeneficiaries, GetBeneficiary, CreateBeneficiary,
    DeleteBeneficiary, ListTransfers, GetTransfer, CreateTransfer, ValidateTransfer,
    CancelTransfer, ListGlobalAccounts, GetGlobalAccount, UpdateGlobalAccount, OnDepositEvent, OnTransferEvent],
    Field(discriminator="operation")]


class AirwallexFullConfig(NodeConfig[AirwallexConfig, AirwallexAPIKeyCredential]):
    pass


# One provider operation per workflow operation; login is solely the authentication prerequisite.
ROUTES = {
    "list_balances": ("GET", "/balances/current"),
    "list_balance_history": ("GET", "/balances/history"),
    "list_financial_transactions": ("GET", "/financial_transactions"),
    "get_financial_transaction": ("GET", "/financial_transactions/{id}"),
    "list_beneficiaries": ("GET", "/beneficiaries"),
    "get_beneficiary": ("GET", "/beneficiaries/{id}"),
    "create_beneficiary": ("POST", "/beneficiaries/create"),
    "delete_beneficiary": ("POST", "/beneficiaries/{id}/delete"),
    "list_transfers": ("GET", "/transfers"),
    "get_transfer": ("GET", "/transfers/{id}"),
    "create_transfer": ("POST", "/transfers/create"),
    "validate_transfer": ("POST", "/transfers/validate"),
    "cancel_transfer": ("POST", "/transfers/{id}/cancel"),
    "list_global_accounts": ("GET", "/global_accounts"),
    "get_global_account": ("GET", "/global_accounts/{id}"),
    "update_global_account": ("POST", "/global_accounts/{id}/update"),
}


class AirwallexNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-airwallex"
    connection_evidence = ConnectionEvidence(operation="list_global_accounts", noun="global accounts", label_keys=("nick_name", "account_name", "id"))

    @classmethod
    def get_config_model(cls):
        return AirwallexFullConfig

    @classmethod
    def _event_type(cls, config):
        operation = config.get("operation")
        event = config.get("event_type") or TRIGGER_DEFAULTS.get(operation)
        allowed = DEPOSIT_EVENTS if operation == "on_deposit_event" else TRANSFER_EVENTS if operation == "on_transfer_event" else ()
        if event not in allowed:
            raise ValueError("Choose a supported Airwallex event")
        return event

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": cls._event_type(config)} if config.get("operation") in TRIGGER_DEFAULTS else {}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = cls._event_type(config)
        request_id = str(uuid4())
        data = await cls._request(AirwallexAPIKeyCredential.model_validate(credential), "POST", "/webhooks/create",
            body={"url": webhook_url, "events": [event], "version": "2026-08-21", "request_id": request_id})
        if not isinstance(data, dict) or not data.get("id") or not data.get("secret"):
            raise ValueError("Airwallex did not return a webhook ID and signing secret")
        return {"external_webhook_id": data["id"], "signing_secret": data["secret"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint_id = config.get("external_webhook_id")
        if not endpoint_id:
            return
        if not credential:
            raise ValueError("Connect Airwallex to remove its webhook")
        try:
            data = await cls._request(AirwallexAPIKeyCredential.model_validate(credential), "POST",
                "/webhooks/" + quote(str(endpoint_id), safe="") + "/delete")
        except ValueError as exc:
            if str(exc).startswith("Airwallex HTTP 404:"):
                return
            raise
        if not isinstance(data, dict) or data.get("deleted") is not True:
            raise ValueError("Airwallex did not confirm webhook deletion")

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = config.get("signing_secret")
        headers = {key.lower(): value for key, value in headers.items()}
        timestamp = headers.get("x-timestamp", "")
        signature = headers.get("x-signature", "")
        if not secret or not timestamp.isdigit() or not signature:
            return False
        # Hash the timestamp as received (milliseconds), followed by the unmodified body.
        expected = hmac.new(secret.encode(), timestamp.encode() + body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return isinstance(payload, dict) and payload.get("name") == cls._event_type(config)

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or "name" not in output:
            return super().resolve_agent_event(output)
        event = output.get("name")
        if event not in DEPOSIT_EVENTS + TRANSFER_EVENTS:
            return None
        data = output.get("data")
        if not isinstance(data, dict):
            return None
        # Product examples use data directly; the common envelope also documents data.object.
        if "object" in data:
            data = data["object"]
        if not isinstance(data, dict):
            return None
        account = output["account_id"] if "account_id" in output else output.get("accountId")
        lines = ["Airwallex " + event + (f" in account {account}" if account else "")]
        if event in TRANSFER_EVENTS:
            beneficiary = data.get("beneficiary") or {}
            who = beneficiary["company_name"] if "company_name" in beneficiary else " ".join(str(beneficiary[k]) for k in ("first_name", "last_name") if k in beneficiary)
            lines.append(f"Transfer {data.get('id')}: {data.get('transfer_amount')} {data.get('transfer_currency')} to {who or 'beneficiary'}; status {data.get('status')}.")
        else:
            payer = data["payer"] if "payer" in data else {}
            who = payer.get("name") if isinstance(payer, dict) else None
            lines.append(f"Deposit {data.get('id')}: {data.get('amount')} {data.get('currency')}" + (f" from {who}" if who else "") + f"; status {data.get('status')}.")
        for key in ("reference", "request_id", "beneficiary_id", "global_account_id", "funding_source_id", "failure_details"):
            if key in data:
                lines.append(f"{key}: {data[key]}")
        lines.append(f"Event ID: {output.get('id')}")
        return {"text": "\n".join(lines), "conversation_key": str(data.get("id")) if data.get("id") else None}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Airwallex API key")
        config = self.config.config
        if config.operation in TRIGGER_DEFAULTS:
            return self.no_event_output(config.operation)
        method, route = ROUTES[config.operation]
        fields = config.model_dump(exclude_none=True, exclude={"operation", "id"})
        route = route.replace("{id}", quote(getattr(config, "id", ""), safe=""))
        body = await self._request(self.config.credentials, method, route,
            params=fields if method == "GET" else None, body=fields if method != "GET" and fields else None)
        if config.operation == "list_balances":
            valid = isinstance(body, list)
        elif config.operation.startswith("list_"):
            valid = isinstance(body, dict) and isinstance(body.get("items"), list)
        elif config.operation == "delete_beneficiary":
            valid = isinstance(body, bool)
        elif config.operation == "validate_transfer":
            valid = isinstance(body, (dict, str))
        else:
            valid = isinstance(body, dict)
        if not valid:
            raise ValueError("Airwallex returned an unexpected response shape")
        return {"status": "success", "operation": config.operation, "data": body}

    @classmethod
    async def _request(cls, credential, method, route, *, params=None, body=None):
        base = {"production": "https://api.airwallex.com", "sandbox": "https://api.sandbox.airwallex.com"}[credential.environment] + "/api/v1"
        secrets = [credential.api_key, credential.client_id]

        def redact(value):
            if isinstance(value, str):
                for secret in secrets:
                    value = value.replace(secret, "[redacted]")
                return value
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items()}
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value

        def checked(response):
            if not 200 <= response.status_code < 300:
                # Preserve provider rejection wording for the credential-connect verdict.
                raise ValueError(redact(f"Airwallex HTTP {response.status_code}: {response.text}"))
            return response.json()

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            auth = await client.post(base + "/authentication/login", headers={
                "x-api-key": credential.api_key, "x-client-id": credential.client_id,
                "Content-Type": "application/json",
                **({"x-login-as": credential.account_id} if credential.account_id else {}),
            })
            login = checked(auth)
            token = login.get("token") if isinstance(login, dict) else None
            if not isinstance(token, str) or not token or any(c.isspace() for c in token):
                raise ValueError("Airwallex login did not return an access token")
            secrets.append(token)
            response = await client.request(method, base + route,
                headers={"Authorization": "Bearer " + token},
                **({"params": params} if params is not None else {"json": body} if body is not None else {}))
            return redact(checked(response))
