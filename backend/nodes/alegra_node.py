"""Alegra sales operations using the user's email and personal API token.

Routes and fields follow the published sales contract. Webhook subscriptions and
payloads follow Alegra's separate published subscription API and delivery examples.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import json
from datetime import date as Date
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE_URL = "https://api.alegra.com/api/v1"
AUTH_DOC = "https://developer.alegra.com/reference/autenticaci%C3%B3n"
WEBHOOK_DOC = "https://developer.alegra.com/reference/post_webhooks-subscriptions"


class AlegraAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Alegra API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": AUTH_DOC,
        "x-credential-instructions": "In Alegra, open Settings → API / Integrations and copy your API email and token. Use the API token, not your account password. NoClick sends them with HTTP Basic authentication to api.alegra.com.",
    })
    credential_type: Literal["alegra_api_token"] = Field("alegra_api_token", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., title="API email", min_length=3, max_length=254)
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        value = value.strip()
        if "@" not in value or ":" in value or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Enter the API email shown in Alegra")
        return value

    @field_validator("api_token")
    @classmethod
    def valid_token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() or ord(c) < 32 for c in value) or ":" in value:
            raise ValueError("Paste the API token without a Basic header")
        return value


ResourceID = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _List(_Input):
    start: int = Field(0, ge=0, title="Start offset", description="Zero-based offset; use next_start for the next page.")
    limit: int = Field(30, ge=1, le=30, title="Page size")
    order_direction: Literal["ASC", "DESC"] = Field("ASC", title="Order direction")
    date: Optional[Date] = Field(None, title="Document date")


class _Tax(_Input):
    id: ResourceID


class _Item(_Input):
    id: ResourceID
    price: float = Field(..., ge=0, allow_inf_nan=False)
    quantity: float = Field(..., gt=0, allow_inf_nan=False)
    description: Optional[str] = None
    reference: Optional[str] = None
    tax: Optional[list[_Tax]] = None
    discount: Optional[float] = Field(None, ge=0, le=100, allow_inf_nan=False)


class _PaymentInvoice(_Input):
    id: ResourceID
    amount: float = Field(..., gt=0, allow_inf_nan=False)


class _DocumentWrite(_Input):
    date: Date = Field(..., title="Document date")
    client_id: ResourceID = Field(..., title="Client ID")
    items_json: str = Field(..., max_length=100000, title="Line items JSON", description='Array of items, each with id, price and quantity; optional description and discount.', json_schema_extra={"ui:widget": "textarea"})
    observations: Optional[str] = Field(None, max_length=500, title="Internal observations")
    anotation: Optional[str] = Field(None, max_length=500, title="Printed notes")

    @field_validator("items_json")
    @classmethod
    def items(cls, value):
        if value is None:
            return None
        rows = TypeAdapter(list[_Item]).validate_json(value)
        if not 1 <= len(rows) <= 100:
            raise ValueError("Supply 1 to 100 line items")
        return json.dumps([row.model_dump(exclude_none=True) for row in rows])


class _DueDocumentWrite(_DocumentWrite):
    due_date: Date = Field(..., title="Due date")


class _PaymentWrite(_Input):
    date: Date = Field(..., title="Payment date")
    bank_account_id: ResourceID = Field(..., title="Bank account ID")
    invoices_json: str = Field(..., max_length=100000, title="Invoice payments JSON", description='Array of sales invoice payments, each with id and amount.', json_schema_extra={"ui:widget": "textarea"})
    payment_method: Literal["cash", "check", "transfer", "deposit", "credit-card", "debit-card"] = Field("cash", title="Payment method")
    observations: Optional[str] = Field(None, max_length=500)

    @field_validator("invoices_json")
    @classmethod
    def invoices(cls, value):
        if value is None:
            return None
        rows = TypeAdapter(list[_PaymentInvoice]).validate_json(value)
        if not 1 <= len(rows) <= 100:
            raise ValueError("Supply 1 to 100 invoice payments")
        return json.dumps([row.model_dump() for row in rows])


class _UpdateInput(_Input):
    @model_validator(mode="after")
    def nonempty_update(self):
        if not any(value is not None for key, value in self.model_dump().items() if key not in {"operation", "id"}):
            raise ValueError("Supply at least one field to update")
        return self


# Each action has one fixed method and route; there is no arbitrary request operation.
RESOURCES = {"invoice": "/invoices", "payment": "/payments", "credit_note": "/credit-notes", "estimate": "/estimates"}
OPERATIONS = {}
CONFIG_MODELS = {}
for _resource, _route in RESOURCES.items():
    for _verb, _method in (("list", "GET"), ("get", "GET"), ("create", "POST"), ("update", "PUT"), ("delete", "DELETE")):
        _name = _verb + "_" + _resource + ("s" if _verb == "list" else "")
        _label = _name.replace("_", " ").title()
        _path = _route + ("/{id}" if _verb in {"get", "update", "delete"} else "")
        OPERATIONS[_name] = (_method, _path)
        _parent = _List if _verb == "list" else (_PaymentWrite if _resource == "payment" else _DocumentWrite if _resource == "credit_note" else _DueDocumentWrite) if _verb in {"create", "update"} else _Input
        if _verb == "update":
            # PUT is a documented partial update. Omitted fields stay untouched.
            _overrides = {}
            for key, field in _parent.model_fields.items():
                if _resource == "credit_note" and key == "client_id":
                    continue
                _field = deepcopy(field)
                _field.default = None
                _overrides[key] = (Optional[field.annotation], _field)
            _parent = create_model("Alegra" + _resource.title().replace("_", "") + "UpdateFields", __base__=(_parent, _UpdateInput), __module__=__name__, **_overrides)
        _fields = {"id": (ResourceID, Field(..., title=_resource.replace("_", " ").title() + " ID"))} if "{id}" in _path else {}
        _extra = {"ui:hidden": True, "x-category": _resource.replace("_", " ").title() + "s", "x-is-trigger": False, "x-display-name": _label}
        if _verb == "create":
            _extra.update({"x-creates-resource": True, "x-resource-type": "alegra_" + _resource, "x-resource-id-path": "data.id"})
        _model = create_model("Alegra" + "".join(p.title() for p in _name.split("_")) + "Config", __base__=_parent, __module__=__name__,
                              operation=(Literal[_name], Field(_name, title=_label, json_schema_extra=_extra)), **_fields)
        CONFIG_MODELS[_name] = _model
        globals()[_model.__name__] = _model

EVENTS = {"on_new_invoice": ("new-invoice", "invoice"), "on_new_client": ("new-client", "client"), "on_new_item": ("new-item", "item")}
for _name, (_event, _kind) in EVENTS.items():
    _label = _name.replace("_", " ").title()
    _model = create_model("Alegra" + "".join(p.title() for p in _name.split("_")) + "Config", __base__=WebhookTriggerConfigBase, __module__=__name__,
        operation=(Literal[_name], Field(_name, title=_label, json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": _label})),
        webhook_url=(Optional[str], Field(None, title="Webhook URL", description="Alegra delivers unsigned notifications to this private URL. Keep it secret. Subscription activation can take a minute; events during activation may be missed.", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})))
    CONFIG_MODELS[_name] = _model
    globals()[_model.__name__] = _model

AlegraConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class AlegraNodeConfig(NodeConfig[AlegraConfig, AlegraAPITokenCredential]):
    pass


class AlegraNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-alegra"
    connection_evidence = ConnectionEvidence(noun="invoices", operation="list_invoices", label_keys=("id",))
    webhook_signing_secret_not_issued = True
    edit_examples = ["Create a sales invoice", "Record a payment against an invoice", "Create a credit note", "When a new invoice arrives"]

    @classmethod
    def get_config_model(cls):
        return AlegraNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        auth = AlegraAPITokenCredential.model_validate(credential)
        encoded = base64.b64encode(f"{auth.email}:{auth.api_token}".encode()).decode()
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, params=params, json=body,
                    headers={"Authorization": "Basic " + encoded, "Accept": "application/json"})
        except httpx.RequestError:
            raise ValueError("Alegra could not be reached. If this was a write, check Alegra before retrying.") from None
        if response.is_error:
            try:
                detail = response.json().get("error") or response.json().get("message") or "Request rejected"
            except (ValueError, AttributeError):
                detail = "Request rejected"
            detail = str(detail).replace(auth.api_token, "[redacted]").replace(encoded, "[redacted]")
            raise ValueError(f"Alegra API error {response.status_code}: {detail}")
        if response.is_redirect:
            raise ValueError("Alegra returned an unexpected redirect")
        return response.json() if response.content else None

    async def execute(self, inputs: dict[str, Any]):
        if not isinstance(self.config, AlegraNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect an Alegra API email and token")
        op = self.config.config
        name = op.operation
        if name in EVENTS:
            return self.no_event_output(name)
        method, path = OPERATIONS[name]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            path = path.replace("{id}", quote(values.pop("id"), safe=""))
        params, body = None, None
        if name.startswith("list_"):
            params = values
        elif method in {"POST", "PUT"}:
            body = dict(values)
            if "client_id" in body:
                body["client"] = {"id": body.pop("client_id")}
            if "due_date" in body:
                body["dueDate"] = body.pop("due_date")
            if "items_json" in body:
                body["items"] = json.loads(body.pop("items_json"))
            if "bank_account_id" in body:
                body["bankAccount"] = {"id": body.pop("bank_account_id")}
            if "invoices_json" in body:
                body["invoices"] = json.loads(body.pop("invoices_json"))
            if "payment_method" in body:
                body["paymentMethod"] = body.pop("payment_method")
        data = await self._request(self.config.credentials.model_dump(), method, path, params=params, body=body)
        output = {"status": "success", "operation": name, "data": data}
        if name.startswith("list_"):
            rows = data.get("data") if isinstance(data, dict) else data
            if not isinstance(rows, list):
                raise ValueError("Alegra returned an invalid list response")
            output["data"] = rows
            output["next_start"] = op.start + len(rows) if len(rows) == op.limit else None
        return output

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = EVENTS[(config or {}).get("operation")][0]
        url = urlsplit(webhook_url)
        if url.scheme != "https" or not url.netloc or url.username or url.password or url.fragment:
            raise ValueError("Alegra requires a public HTTPS webhook URL")
        # Alegra adds https:// itself; its API explicitly forbids the scheme in url.
        data = await cls._request(credential, "POST", "/webhooks/subscriptions", body={"event": event, "url": webhook_url.removeprefix("https://")})
        subscription = data.get("subscription") if isinstance(data, dict) else None
        identifier = subscription.get("id") if isinstance(subscription, dict) else None
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("Alegra did not return a subscription ID")
        return {"external_webhook_id": identifier}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = (config or {}).get("external_webhook_id")
        if identifier is not None:
            await cls._request(credential, "DELETE", "/webhooks/subscriptions/" + quote(str(identifier), safe=""))

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # Alegra documents HTTPS delivery with subject/message, no signature or secret:
        # https://developer.alegra.com/reference/post_webhooks-subscriptions
        return True

    @classmethod
    def handle_webhook_handshake(cls, body, headers, config=None):
        if not body.strip():
            return {"ok": True}
        try:
            if json.loads(body) == {}:
                return {"ok": True}
        except (ValueError, UnicodeDecodeError):
            pass
        return None

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        expected = EVENTS.get((config or {}).get("operation"))
        if not expected or not isinstance(payload, dict) or payload.get("subject") != expected[0]:
            return False
        message = payload.get("message")
        return isinstance(message, dict) and isinstance(message.get(expected[1]), dict) and bool(message[expected[1]].get("id"))

    @classmethod
    def resolve_trigger_payload(cls, payload, config=None):
        if not cls.filter_trigger_payload(payload, config):
            return None
        return {"status": "success", "operation": config["operation"], "subject": payload["subject"], "message": payload["message"]}

    @classmethod
    def resolve_agent_event(cls, output):
        subject = output.get("subject") if isinstance(output, dict) else None
        kind = next((kind for event, kind in EVENTS.values() if event == subject), None)
        if kind is None:
            return None
        message = output.get("message")
        record = message.get(kind) if isinstance(message, dict) else None
        if not isinstance(record, dict) or not record.get("id"):
            return None
        lines = [f"Alegra: new {kind}, ID {record['id']}"]
        if kind == "invoice":
            client = record.get("client") or {}
            lines += [f"Client ID: {client.get('id', 'unspecified')}",
                      f"Date: {record.get('date', 'unspecified')}; due: {record.get('dueDate', 'unspecified')}",
                      f"Status: {record.get('status', 'unspecified')}; total: {record.get('total', 'unspecified')}; balance: {record.get('balance', 'unspecified')}",
                      f"Notes: {record.get('anotation') or ''}"]
        elif kind == "client":
            name = record.get("name") or {}
            label = " ".join(str(v) for v in name.values() if v) if isinstance(name, dict) else str(name)
            lines += [f"Name: {label}", f"Email: {record.get('email') or ''}", f"Phone: {record.get('phonePrimary') or ''}"]
        else:
            lines += [f"Name: {record.get('name') or ''}", f"Description: {record.get('description') or ''}",
                      f"Reference: {record.get('reference') or ''}", f"Status: {record.get('status') or ''}"]
        return {"text": "\n".join(lines), "conversation_key": f"alegra:{kind}:{record['id']}"}
