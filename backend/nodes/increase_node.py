"""Increase banking operations and signed Event Subscriptions.

Contract: https://www.increase.com/openapi.json, version 0.0.1.
Webhook signatures: https://increase.com/documentation/webhooks.
Lists return one page, including Increase's next_cursor, for explicit continuation.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase


class IncreaseAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Increase API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://dashboard.increase.com/developers/api_keys",
        "x-credential-instructions": "Paste an API key from the Increase dashboard. Choose the environment that issued the key. NoClick reads your accounts to check the connection.",
    })
    credential_type: Literal["increase_api_key"] = Field("increase_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})
    environment: Literal["production", "sandbox"] = Field("production", title="Environment")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(char.isspace() for char in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def destinations(self):
        for field in ("created_after", "created_before"):
            value = getattr(self, field, None)
            if value is not None:
                try:
                    if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                        raise ValueError()
                except ValueError:
                    raise ValueError("Use an ISO 8601 timestamp with a timezone") from None
        if self.operation in {"create_ach_transfer", "create_wire_transfer"}:
            external = self.external_account_id
            bank = self.account_number or self.routing_number
            if external and bank:
                raise ValueError("Choose an external account or an account number and routing number")
            if not external and not (self.account_number and self.routing_number):
                raise ValueError("Supply an external account or both account number and routing number")
            if external and getattr(self, "funding", None):
                raise ValueError("Funding must be absent when an external account is selected")
            if self.operation == "create_ach_transfer" and self.amount == 0:
                raise ValueError("ACH amount must be nonzero; positive sends funds, negative pulls funds")
        if self.operation == "update_card" and not (self.description or self.status):
            raise ValueError("Supply a description or status to update")
        return self


def text(title, *, required=False, description=None, **constraints):
    return (str if required else str | None, Field(... if required else None, title=title, description=description, **constraints))


def identifier(title, *, required=False):
    return text(title, required=required, min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")


def choice(title, values, *, required=False):
    kind = Literal[tuple(values)]
    return (kind if required else kind | None, Field(... if required else None, title=title))


def number(title, *, required=False, **constraints):
    return (int if required else int | None, Field(... if required else None, title=title, strict=True, **constraints))


def boolean(title):
    return (bool | None, Field(None, title=title, strict=True))


PAGE = {
    "cursor": text("Cursor", description="Pass next_cursor from the previous response to retrieve the next page."),
    "limit": number("Page Size", ge=1, le=100),
}
DATE_FILTER = {
    "created_after": text("Created After", description="Exclusive ISO 8601 timestamp; sent as created_at.after.", json_schema_extra={"format": "date-time"}),
    "created_before": text("Created Before", description="Exclusive ISO 8601 timestamp; sent as created_at.before.", json_schema_extra={"format": "date-time"}),
}


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    fields: dict
    query: tuple = ()
    body: tuple = ()


OPERATIONS = {
    'list_accounts': Operation('GET', '/accounts', {
        **PAGE,
        **DATE_FILTER
    }, query=('cursor', 'limit', 'created_after', 'created_before'), body=()),
    'get_account': Operation('GET', '/accounts/{account_id}', {
        'account_id': identifier('Account ID', required=True)
    }, query=(), body=()),
    'create_account': Operation('POST', '/accounts', {
        'name': text('Name', required=True, min_length=1, max_length=200),
        'entity_id': identifier('Entity ID', required=False),
        'program_id': identifier('Program ID', required=False),
        'idempotency_key': text('Idempotency Key', min_length=1, max_length=200, description='Reuse a unique key when retrying the same write. Sent as Idempotency-Key, never in the request body.')
    }, query=(), body=('name', 'entity_id', 'program_id')),
    'get_account_balance': Operation('GET', '/accounts/{account_id}/balance', {
        'account_id': identifier('Account ID', required=True)
    }, query=(), body=()),
    'list_account_numbers': Operation('GET', '/account_numbers', {
        **PAGE,
        **DATE_FILTER,
        'account_id': identifier('Account ID', required=False)
    }, query=('cursor', 'limit', 'account_id', 'created_after', 'created_before'), body=()),
    'create_account_number': Operation('POST', '/account_numbers', {
        'account_id': identifier('Account ID', required=True),
        'name': text('Name', required=True, min_length=1, max_length=200),
        'inbound_ach_debits': choice('Inbound ACH Debits', ('allowed', 'blocked'), required=False),
        'unregistered_inbound_checks': choice('Unregistered Inbound Checks', ('allowed', 'blocked'), required=False),
        'idempotency_key': text('Idempotency Key', min_length=1, max_length=200, description='Reuse a unique key when retrying the same write. Sent as Idempotency-Key, never in the request body.')
    }, query=(), body=('account_id', 'name', 'inbound_ach_debits', 'unregistered_inbound_checks')),
    'list_transactions': Operation('GET', '/transactions', {
        **PAGE,
        **DATE_FILTER,
        'account_id': identifier('Account ID', required=False)
    }, query=('cursor', 'limit', 'account_id', 'created_after', 'created_before'), body=()),
    'get_transaction': Operation('GET', '/transactions/{transaction_id}', {
        'transaction_id': identifier('Transaction ID', required=True)
    }, query=(), body=()),
    'list_ach_transfers': Operation('GET', '/ach_transfers', {
        **PAGE,
        **DATE_FILTER,
        'account_id': identifier('Account ID', required=False),
        'external_account_id': identifier('External Account ID', required=False)
    }, query=('cursor', 'limit', 'account_id', 'external_account_id', 'created_after', 'created_before'), body=()),
    'get_ach_transfer': Operation('GET', '/ach_transfers/{ach_transfer_id}', {
        'ach_transfer_id': identifier('ACH Transfer ID', required=True)
    }, query=(), body=()),
    'create_ach_transfer': Operation('POST', '/ach_transfers', {
        'account_id': identifier('Account ID', required=True),
        'amount': number('Amount in USD Cents', required=True, ge=-9999999999, le=9999999999, description='Positive sends funds; negative pulls funds from the recipient.'),
        'company_name': text('Company Name', required=True, min_length=1, max_length=16, pattern='^[ -~]*$'),
        'individual_name': text('Individual Name', required=True, min_length=1, max_length=22, pattern='^[ -~]*$'),
        'account_number': text('Account Number', required=False, min_length=1, max_length=17, pattern='^[a-zA-Z0-9]*$'),
        'routing_number': text('Routing Number', required=False, min_length=9, max_length=9, pattern='^[0-9]{9}$'),
        'external_account_id': identifier('External Account ID', required=False),
        'funding': choice('Funding', ('checking', 'savings', 'loan', 'general_ledger'), required=False),
        'standard_entry_class_code': choice('Standard Entry Class Code', ('corporate_credit_or_debit', 'corporate_trade_exchange', 'prearranged_payments_and_deposit', 'internet_initiated'), required=False),
        'require_approval': boolean('Require Approval'),
        'company_entry_description': text('Company Entry Description', required=False, min_length=1, max_length=10, pattern='^[ -~]*$'),
        'idempotency_key': text('Idempotency Key', min_length=1, max_length=200, description='Reuse a unique key when retrying the same write. Sent as Idempotency-Key, never in the request body.')
    }, query=(), body=('account_id', 'amount', 'company_name', 'individual_name', 'account_number', 'routing_number', 'external_account_id', 'funding', 'standard_entry_class_code', 'require_approval', 'company_entry_description')),
    'approve_ach_transfer': Operation('POST', '/ach_transfers/{ach_transfer_id}/approve', {
        'ach_transfer_id': identifier('ACH Transfer ID', required=True),
        'idempotency_key': text('Idempotency Key', min_length=1, max_length=200, description='Reuse a unique key when retrying the same write. Sent as Idempotency-Key, never in the request body.')
    }, query=(), body=()),
    'cancel_ach_transfer': Operation('POST', '/ach_transfers/{ach_transfer_id}/cancel', {
        'ach_transfer_id': identifier('ACH Transfer ID', required=True),
        'idempotency_key': text('Idempotency Key', min_length=1, max_length=200, description='Reuse a unique key when retrying the same write. Sent as Idempotency-Key, never in the request body.')
    }, query=(), body=()),
    'list_wire_transfers': Operation('GET', '/wire_transfers', {
        **PAGE,
        **DATE_FILTER,
        'account_id': identifier('Account ID', required=False),
        'external_account_id': identifier('External Account ID', required=False)
    }, query=('cursor', 'limit', 'account_id', 'external_account_id', 'created_after', 'created_before'), body=()),
    'get_wire_transfer': Operation('GET', '/wire_transfers/{wire_transfer_id}', {
        'wire_transfer_id': identifier('Wire Transfer ID', required=True)
    }, query=(), body=()),
    'create_wire_transfer': Operation('POST', '/wire_transfers', {
        'account_id': identifier('Account ID', required=True),
        'amount': number('Amount in USD Cents', required=True, ge=1, le=999999999999),
        'account_number': text('Account Number', required=False, min_length=1, max_length=34, pattern='^[ a-zA-Z0-9.?!,;:_/@\\\\&\'"`~()<>#%+\\-=$]*$'),
        'routing_number': text('Routing Number', required=False, min_length=9, max_length=9, pattern='^[0-9]{9}$'),
        'external_account_id': identifier('External Account ID', required=False),
        'require_approval': boolean('Require Approval'),
        'source_account_number_id': identifier('Source Account Number ID', required=False),
        'creditor_name': text('Recipient Name', required=True, min_length=1, max_length=140),
        'creditor_city': text('Recipient City', required=True, min_length=1, max_length=35),
        'creditor_country': text('Recipient Country', required=True, min_length=2, max_length=2),
        'creditor_line1': text('Recipient Address', max_length=35, min_length=1),
        'creditor_state': text('Recipient State', max_length=35, min_length=1),
        'creditor_postal_code': text('Recipient Postal Code', max_length=16, min_length=1),
        'remittance_message': text('Remittance Message', required=True, min_length=1, max_length=140),
        'idempotency_key': text('Idempotency Key', min_length=1, max_length=200, description='Reuse a unique key when retrying the same write. Sent as Idempotency-Key, never in the request body.')
    }, query=(), body=('account_id', 'amount', 'account_number', 'routing_number', 'external_account_id', 'require_approval', 'source_account_number_id')),
    'approve_wire_transfer': Operation('POST', '/wire_transfers/{wire_transfer_id}/approve', {
        'wire_transfer_id': identifier('Wire Transfer ID', required=True),
        'idempotency_key': text('Idempotency Key', min_length=1, max_length=200, description='Reuse a unique key when retrying the same write. Sent as Idempotency-Key, never in the request body.')
    }, query=(), body=()),
    'cancel_wire_transfer': Operation('POST', '/wire_transfers/{wire_transfer_id}/cancel', {
        'wire_transfer_id': identifier('Wire Transfer ID', required=True),
        'idempotency_key': text('Idempotency Key', min_length=1, max_length=200, description='Reuse a unique key when retrying the same write. Sent as Idempotency-Key, never in the request body.')
    }, query=(), body=()),
    'create_account_transfer': Operation('POST', '/account_transfers', {
        'account_id': identifier('Account ID', required=True),
        'amount': number('Amount in Minor Currency Units', required=True, ge=1, description='For a USD account, enter cents.'),
        'description': text('Description', required=True, min_length=1, max_length=200),
        'destination_account_id': identifier('Destination Account ID', required=True),
        'require_approval': boolean('Require Approval'),
        'idempotency_key': text('Idempotency Key', min_length=1, max_length=200, description='Reuse a unique key when retrying the same write. Sent as Idempotency-Key, never in the request body.')
    }, query=(), body=('account_id', 'amount', 'description', 'destination_account_id', 'require_approval')),
    'list_external_accounts': Operation('GET', '/external_accounts', {
        **PAGE,
        'routing_number': text('Routing Number', required=False, min_length=9, max_length=9, pattern='^[0-9]{9}$')
    }, query=('cursor', 'limit', 'routing_number'), body=()),
    'create_external_account': Operation('POST', '/external_accounts', {
        'routing_number': text('Routing Number', required=True, min_length=9, max_length=9, pattern='^[0-9]{9}$'),
        'account_number': text('Account Number', required=True, min_length=1, max_length=17, pattern='^[a-zA-Z0-9]*$'),
        'description': text('Description', required=True, min_length=1, max_length=200),
        'account_holder': choice('Account Holder', ('business', 'individual', 'unknown'), required=False),
        'funding': choice('Funding', ('checking', 'savings', 'general_ledger', 'other'), required=False),
        'idempotency_key': text('Idempotency Key', min_length=1, max_length=200, description='Reuse a unique key when retrying the same write. Sent as Idempotency-Key, never in the request body.')
    }, query=(), body=('routing_number', 'account_number', 'description', 'account_holder', 'funding')),
    'list_cards': Operation('GET', '/cards', {
        **PAGE,
        **DATE_FILTER,
        'account_id': identifier('Account ID', required=False)
    }, query=('cursor', 'limit', 'account_id', 'created_after', 'created_before'), body=()),
    'create_card': Operation('POST', '/cards', {
        'account_id': identifier('Account ID', required=True),
        'description': text('Description', required=False, min_length=1, max_length=200),
        'idempotency_key': text('Idempotency Key', min_length=1, max_length=200, description='Reuse a unique key when retrying the same write. Sent as Idempotency-Key, never in the request body.')
    }, query=(), body=('account_id', 'description')),
    'update_card': Operation('PATCH', '/cards/{card_id}', {
        'card_id': identifier('Card ID', required=True),
        'description': text('Description', required=False, min_length=1, max_length=200),
        'status': choice('Status', ('active', 'disabled', 'canceled'), required=False),
        'idempotency_key': text('Idempotency Key', min_length=1, max_length=200, description='Reuse a unique key when retrying the same write. Sent as Idempotency-Key, never in the request body.')
    }, query=(), body=('description', 'status')),
}


def _make_config(name, spec):
    category = "Transfers" if "transfer" in name else "Cards" if "card" in name else "Accounts"
    return create_model(
        "Increase" + "".join(word.title() for word in name.split("_")) + "Config",
        __base__=_Config, __module__=__name__,
        operation=(Literal[name], Field(name, title=name.replace("_", " ").title(), json_schema_extra={
            "ui:hidden": True, "x-is-trigger": False, "x-category": category,
            "x-display-name": name.replace("_", " ").title(),
        })),
        **spec.fields,
    )


CONFIG_MODELS = {name: _make_config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class IncreaseOnEventConfig(WebhookTriggerConfigBase):
    """Receive banking events; the event references the resource to retrieve."""
    operation: Literal["on_event"] = Field("on_event", title="On Increase Event", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Increase Event",
    })
    event_category: Literal[
        "all", "transaction.created", "ach_transfer.created", "ach_transfer.updated",
        "wire_transfer.created", "wire_transfer.updated", "account_transfer.created", "account_transfer.updated",
        "inbound_ach_transfer.created", "inbound_ach_transfer.updated", "inbound_wire_transfer.created",
        "inbound_wire_transfer.updated", "card.created", "card.updated", "account.created", "account.updated",
    ] = Field("all", title="Event Category", description="Choose all banking events or one category.")
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered automatically with Increase.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


IncreaseConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (IncreaseOnEventConfig,)], Field(discriminator="operation")]


class IncreaseNodeConfig(NodeConfig[IncreaseConfig, IncreaseAPIKeyCredential]):
    pass


class IncreaseNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-increase"
    connection_evidence = ConnectionEvidence(operation="list_accounts", noun="accounts")
    edit_examples = ["Read my Increase account balance", "Send an ACH transfer", "List recent transactions", "React to a settled transfer"]

    @classmethod
    def get_config_model(cls):
        return IncreaseNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None, idempotency_key=None):
        credential = IncreaseAPIKeyCredential.model_validate(credential)
        base = "https://sandbox.increase.com" if credential.environment == "sandbox" else "https://api.increase.com"
        headers = {"Authorization": f"Bearer {credential.api_key}", "Accept": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.request(method, base + path, headers=headers, params=params, json=body)
        if not 200 <= response.status_code < 300:
            try:
                detail = response.json()
                detail = detail.get("detail") or detail.get("title") if isinstance(detail, dict) else None
            except ValueError:
                detail = None
            raise ValueError(f"Increase API error {response.status_code}: {detail or 'request failed'}")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Increase returned an unexpected response")
        return data

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        parsed = IncreaseOnEventConfig.model_validate({**config, "operation": "on_event"})
        # Increase accepts a caller-chosen raw secret but never returns it on the subscription.
        secret = secrets.token_hex(32)
        body = {"url": webhook_url, "shared_secret": secret, "status": "active"}
        if parsed.event_category != "all":
            body["selected_event_categories"] = [parsed.event_category]
        result = await cls._request(credential, "POST", "/event_subscriptions", body=body)
        if not result.get("id"):
            raise ValueError("Increase did not return an Event Subscription ID")
        return {"external_webhook_id": result["id"], "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        subscription_id = config.get("external_webhook_id")
        if not subscription_id:
            return
        if not credential:
            raise ValueError("Reconnect Increase to delete this Event Subscription")
        await cls._request(credential, "PATCH", "/event_subscriptions/" + quote(str(subscription_id), safe=""),
                           body={"status": "deleted"})

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_category": config.get("event_category", "all")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = config.get("signing_secret")
        headers = {key.lower(): value for key, value in headers.items()}
        timestamp = headers.get("webhook-timestamp", "")
        message_id = headers.get("webhook-id", "")
        signature = headers.get("webhook-signature", "")
        if not secret or not message_id or not timestamp.isdigit() or len(timestamp) > 12:
            return False
        if abs(time.time() - int(timestamp)) > 300:
            return False
        message = message_id.encode() + b"." + timestamp.encode() + b"." + body
        expected = "v1," + base64.b64encode(hmac.new(secret.encode(), message, hashlib.sha256).digest()).decode()
        return any(hmac.compare_digest(expected.encode(), part.encode()) for part in signature.split())

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        if not isinstance(payload, dict) or payload.get("type") != "event":
            return False
        category = config.get("event_category", "all")
        return category == "all" or payload.get("category") == category

    @classmethod
    def resolve_agent_event(cls, output):
        event = output["data"] if isinstance(output, dict) and "status" in output and "data" in output else output
        if not isinstance(event, dict) or event.get("type") != "event":
            return super().resolve_agent_event(output)
        category = event.get("category")
        object_type = event.get("associated_object_type")
        object_id = event.get("associated_object_id")
        event_id = event.get("id")
        if not all((category, object_type, object_id, event_id)):
            return super().resolve_agent_event(output)
        text = (f"Increase: {str(category).replace('.', ' ').replace('_', ' ')}.\n"
                f"Resource: {object_type} {object_id}\nEvent: {event_id}\nAt: {event.get('created_at')}\n"
                "The event identifies a resource; retrieve it for its current details before acting.")
        return {"text": text, "conversation_key": str(object_id), "title": f"Increase {category}"}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, IncreaseNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect an Increase API key")
        config = self.config.config
        name = config.operation
        if isinstance(config, IncreaseOnEventConfig):
            if not self.filter_trigger_payload(inputs, config.model_dump()):
                return self.no_event_output(name)
            return {"status": "success", "operation": name, "data": inputs}
        spec = OPERATIONS[name]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec.path
        for field, value in values.items():
            path = path.replace("{" + field + "}", quote(str(value), safe=""))
        query_names = {"created_after": "created_at.after", "created_before": "created_at.before"}
        params = {query_names.get(key, key): values[key] for key in spec.query if key in values}
        body = {key: values[key] for key in spec.body if key in values}
        if name == "create_wire_transfer":
            address = {key: values["creditor_" + key] for key in ("city", "country", "line1", "state", "postal_code")
                       if "creditor_" + key in values}
            body["creditor"] = {"name": config.creditor_name, "address": {"structured": address}}
            body["remittance"] = {"category": "unstructured", "unstructured": {"message": config.remittance_message}}
        result = await self._request(self.config.credentials.model_dump(), spec.method, path,
                                     params=params or None, body=body if spec.method != "GET" else None,
                                     idempotency_key=values.get("idempotency_key"))
        return {"status": "success", "operation": name, "data": result}
