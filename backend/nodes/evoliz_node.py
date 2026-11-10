"""Evoliz API 1.61: fixed finance operations and timestamp-filtered event polls.

Contract: https://evoliz.io/api-docs/api-docs.yaml (version 1.61).
API keys are exchanged once per token lifetime; writes are never retried.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://www.evoliz.io"
DOCS = "https://evoliz.io/api-docs/"
CREDENTIAL = "evoliz_api_keys"
ID = Annotated[int, Field(gt=0)]
Text = Annotated[str, Field(min_length=1, max_length=10000)]
Money = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class EvolizAPIKeysCredential(BaseModel):
    model_config = ConfigDict(title="Evoliz API Keys", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.evoliz.com/",
            "x-credential-instructions": "In Evoliz, open Applications, enable the Evoliz API connector, then choose Create API Key. Paste both keys and your company number (shown below your name at the bottom left). NoClick exchanges these keys for a short-lived token and verifies access by reading your company.",
        })
    credential_type: Literal["evoliz_api_keys"] = Field(CREDENTIAL, json_schema_extra={"ui:hidden": True})
    public_key: str = Field(..., min_length=1, max_length=4096, title="Public API key", repr=False, json_schema_extra={"ui:widget": "password"})
    secret_key: str = Field(..., min_length=1, max_length=4096, title="Secret API key", repr=False, json_schema_extra={"ui:widget": "password"})
    companyid: ID = Field(..., title="Company number", description="Your Evoliz customer number, shown below your name in the app.")

    @field_validator("public_key", "secret_key", mode="before")
    @classmethod
    def keys(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Address(Input):
    postcode: Text
    town: Text
    iso2: str = Field(..., min_length=2, max_length=2)
    addr: str | None = None


class ClientCreate(Input):
    name: Text
    type: Literal["Particulier", "Professionnel", "Administration publique"]
    address: Address
    code: str | None = None
    phone: str | None = None
    comment: str | None = None
    business_number: str | None = Field(None, pattern=r"^\d{14}$")
    business_identification_number: str | None = Field(None, pattern=r"^\d{9}$")
    vat_number: str | None = None


class ClientUpdate(Input):
    name: Text
    phone: str | None = None
    comment: str | None = None


class ArticleCreate(Input):
    reference: Text
    designation: Text
    nature: Literal["product", "service"] | None = None
    unit_price: Money | None = None
    vat_rate: float | None = Field(None, allow_inf_nan=False)
    ttc: bool | None = None
    quantity: float | None = Field(None, allow_inf_nan=False)
    unit: str | None = None


class ArticleUpdate(Input):
    designation: Text
    unit_price: Money | None = None
    vat_rate: float | None = Field(None, allow_inf_nan=False)
    enabled: bool | None = None


class Term(Input):
    paytermid: ID
    duedate: date | None = None
    paydelay: int | None = Field(None, ge=0)
    endmonth: bool | None = None
    payday: int | None = Field(None, ge=0, le=31)
    paytypeid: ID | None = None
    bankid: ID | None = None

    @model_validator(mode="after")
    def conditional_terms(self):
        if self.paytermid == 18 and self.duedate is None:
            raise ValueError("Payment term 18 requires a due date")
        if self.paytermid == 16 and any(v is None for v in (self.paydelay, self.endmonth, self.payday)):
            raise ValueError("Payment term 16 requires paydelay, endmonth and payday")
        return self


class Item(Input):
    type: Literal["article"] = "article"
    designation: Text
    quantity: float = Field(..., allow_inf_nan=False)
    unit_price: Money
    reference: str | None = None
    unit: str | None = None
    vat_rate: float | None = Field(None, allow_inf_nan=False)
    sale_classificationid: ID | None = None


class DocumentCreate(Input):
    clientid: ID
    documentdate: date
    term: Term
    items: list[Item] = Field(..., min_length=1, max_length=1000)
    object: str | None = None
    external_document_number: str | None = None
    comment: str | None = None
    prices_include_vat: bool | None = None
    vat_exoneration: int | str | None = None
    analyticid: ID | None = None

    @model_validator(mode="after")
    def due_date(self):
        if self.term.duedate and self.term.duedate < self.documentdate:
            raise ValueError("Due date cannot precede document date")
        return self


class SendDocument(Input):
    to: list[EmailStr] = Field(..., min_length=1, max_length=15, description="Sends an email through Evoliz to these recipients.")
    subject: Text
    body: Text
    cc: list[EmailStr] | None = Field(None, max_length=5)
    cci: list[EmailStr] | None = Field(None, max_length=5)
    attachment: bool | None = None
    signature: bool | None = None
    copy: bool | None = None


class PaymentCreate(Input):
    paydate: date
    label: Text
    paytypeid: ID
    amount: Money | None = None
    creditid: ID | None = None
    comment: str | None = None

    @model_validator(mode="after")
    def payment_method(self):
        if self.paytypeid == 13:
            if self.creditid is None or self.amount is not None:
                raise ValueError("Credit-note payments require creditid and prohibit amount")
        elif self.creditid is not None:
            raise ValueError("creditid is only valid for payment type 13")
        return self


class TemplateUpdate(Input):
    templateid: ID = Field(..., description="Requires Evoliz MULTITEMPLATE and an invoice template belonging to this company.")


class ListConfig(Input):
    page: int = Field(1, ge=1, le=100000, description="Documented page number; each action returns one page and provider pagination metadata.")
    per_page: int = Field(100, ge=1, le=100)


# Every action fixes its method and route; no arbitrary request operation.
# The body class's fields appear directly in the operation's config form.
OPERATIONS = {
    "get_company": ("GET", "", Input),
    "list_clients": ("GET", "/clients", ListConfig),
    "get_client": ("GET", "/clients/{clientid}", Input),
    "create_client": ("POST", "/clients", ClientCreate),
    "update_client": ("PATCH", "/clients/{clientid}", ClientUpdate),
    "list_articles": ("GET", "/articles", ListConfig),
    "get_article": ("GET", "/articles/{articleid}", Input),
    "create_article": ("POST", "/articles", ArticleCreate),
    "update_article": ("PATCH", "/articles/{articleid}", ArticleUpdate),
    "list_invoices": ("GET", "/invoices", ListConfig),
    "get_invoice": ("GET", "/invoices/{invoiceid}", Input),
    "create_invoice": ("POST", "/invoices", DocumentCreate),
    "update_invoice_template": ("PATCH", "/invoices/{invoiceid}", TemplateUpdate),
    "send_invoice": ("POST", "/invoices/{invoiceid}/send", SendDocument),
    "create_invoice_payment": ("POST", "/invoices/{invoiceid}/payments", PaymentCreate),
    "list_quotes": ("GET", "/quotes", ListConfig),
    "get_quote": ("GET", "/quotes/{quoteid}", Input),
    "create_quote": ("POST", "/quotes", DocumentCreate),
    "send_quote": ("POST", "/quotes/{quoteid}/send", SendDocument),
    "list_payments": ("GET", "/payments", ListConfig),
    "get_payment": ("GET", "/payments/{paymentid}", Input),
    "list_suppliers": ("GET", "/suppliers", ListConfig),
}


def _operation(name, route, base):
    fields = {}
    for segment in route.split("/"):
        if segment.startswith("{"):
            key = segment[1:-1]
            fields[key] = (ID, Field(..., title=key[:-2].capitalize() + " ID"))
    if name.startswith("list_") and name not in {"list_payments"}:
        fields["search"] = (str | None, Field(None, title="Search"))
    extra = {"ui:hidden": True, "x-display-name": name.replace("_", " ").title(),
             "x-category": "Read" if name.startswith(("get_", "list_")) else "Write"}
    return create_model("Evoliz" + name.title().replace("_", "") + "Config", __base__=base,
        operation=(Literal[name], Field(name, title=name.replace("_", " ").title(), json_schema_extra=extra)), **fields)


MODELS = [_operation(name, route, base) for name, (_, route, base) in OPERATIONS.items()]
globals().update({model.__name__: model for model in MODELS})


class EventPoll(PollTriggerConfigBase):
    lookback_hours: int = Field(168, ge=1, le=720, description="Overlapping event window; first poll establishes a baseline. Resume within this window to avoid missing events. At most 10,000 events per poll; narrow the window if exceeded.")


def _trigger(kind):
    name = "on_" + kind + "_event"
    return create_model("EvolizOn" + kind.title() + "EventConfig", __base__=EventPoll,
        operation=(Literal[name], Field(name, title="On " + kind.title() + " Change", json_schema_extra={
            "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers",
            "x-display-name": "On " + kind.title() + " Change",
            "description": "Poll the timestamp-filtered Evoliz event feed for creation, updates and other changes.",
        })))


TRIGGERS = {"on_" + kind + "_event": kind for kind in ("client", "invoice", "payment")}
TRIGGER_MODELS = [_trigger(kind) for kind in TRIGGERS.values()]
globals().update({model.__name__: model for model in TRIGGER_MODELS})
EvolizConfig = Annotated[Union[tuple(MODELS + TRIGGER_MODELS)], Field(discriminator="operation")]


class EvolizNodeConfig(NodeConfig[EvolizConfig, EvolizAPIKeysCredential]):
    pass


class EvolizError(ValueError):
    pass


# Process-local, bounded cache: keys are digests, never raw secrets. Entries are
# discarded before expiry and the credential digest separates accounts.
_TOKENS: dict[str, tuple[str, float]] = {}
_LOCKS: dict[str, asyncio.Lock] = {}


def _cache_key(credential):
    raw = json.dumps([credential.public_key, credential.secret_key], separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _safe_message(response, secrets):
    try:
        payload = response.json()
        message = str(payload.get("message") or payload.get("error") or f"Evoliz HTTP {response.status_code}")
    except Exception:
        message = f"Evoliz HTTP {response.status_code}"
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[redacted]")
    return message[:2000]


async def _request(client, method, path, *, token=None, body=None, params=None, secrets=()):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        response = await client.request(method, BASE + path, headers=headers, params=params, json=body)
    except httpx.TransportError:
        raise EvolizError("Evoliz request did not complete; inspect any write before retrying") from None
    if not 200 <= response.status_code < 300:
        raise EvolizError(f"Evoliz HTTP {response.status_code}: " + _safe_message(response, (*secrets, token)))
    if response.status_code == 204 or not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError:
        raise EvolizError("Evoliz returned an unreadable response; inspect any write before retrying") from None
    if not isinstance(payload, (dict, list)):
        raise EvolizError("Evoliz returned an unexpected JSON response")
    return payload


async def _access_token(client, credential):
    key = _cache_key(credential)
    # Prune only expired, unlocked entries, including locks, keeping memory bounded.
    for old in tuple(_TOKENS):
        lock = _LOCKS.get(old)
        if _TOKENS[old][1] <= time.time() and not (lock and lock.locked()):
            _TOKENS.pop(old, None)
            _LOCKS.pop(old, None)
    lock = _LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        cached = _TOKENS.get(key)
        if cached and cached[1] > time.time():
            return cached[0]
        payload = await _request(client, "POST", "/api/login",
            body={"public_key": credential.public_key, "secret_key": credential.secret_key},
            secrets=(credential.public_key, credential.secret_key))
        token = payload.get("access_token")
        if not isinstance(token, str) or not token or any(c.isspace() for c in token):
            raise EvolizError("Evoliz login did not return an access token")
        try:
            expires = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00")).timestamp() - 30
        except (KeyError, TypeError, ValueError):
            raise EvolizError("Evoliz login did not return a valid expiry") from None
        # Respect the provider's expires_at, bounded by its documented 20 minutes.
        if len(_TOKENS) >= 1024:
            oldest = min(_TOKENS, key=lambda k: _TOKENS[k][1])
            _TOKENS.pop(oldest, None)
            if not _LOCKS[oldest].locked():
                _LOCKS.pop(oldest, None)
        _TOKENS[key] = (token, min(expires, time.time() + 1170))
        return token


class EvolizNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-evoliz"
    connection_evidence = ConnectionEvidence(noun="company", identity_operation="get_company", identity_keys=("name", "companyid"))
    edit_examples = ["Create an Evoliz client", "Create an invoice from line items", "Record an invoice payment", "Watch for invoice changes"]

    @classmethod
    def get_config_model(cls):
        return EvolizNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect Evoliz API keys and your company number")
        credential = self.config.credentials
        config = self.config.config
        root = f"/api/v1/companies/{credential.companyid}"
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            token = await _access_token(client, credential)
            secrets = (credential.public_key, credential.secret_key)
            if config.operation in TRIGGERS:
                result = await self._poll(client, token, root, config, secrets)
            else:
                method, route, _ = OPERATIONS[config.operation]
                values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
                for key in tuple(values):
                    marker = "{" + key + "}"
                    if marker in route:
                        route = route.replace(marker, str(values.pop(key)))
                payload = await _request(client, method, root + route, token=token,
                    params=values if method == "GET" else None,
                    body=values if method != "GET" else None, secrets=secrets)
                result = {"data": payload, "operation": config.operation}
        await self.emit(result)
        return result

    async def _poll(self, client, token, root, config, secrets):
        now = datetime.now(timezone.utc)
        params = {"element_type": TRIGGERS[config.operation], "period": "custom",
                  "date_min": (now - timedelta(hours=config.lookback_hours)).strftime("%Y-%m-%d %H:%M:%S"),
                  "date_max": now.strftime("%Y-%m-%d %H:%M:%S"), "per_page": 100}
        events = []
        for page in range(1, 101):
            payload = await _request(client, "GET", root + "/events", token=token,
                params={**params, "page": page}, secrets=secrets)
            rows = payload.get("data")
            if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("eventid"), int) for row in rows):
                raise EvolizError("Evoliz event list is missing event IDs")
            events.extend(rows)
            meta = payload.get("meta")
            if not isinstance(meta, dict) or not isinstance(meta.get("last_page"), int):
                raise EvolizError("Evoliz event pagination is missing")
            if page >= meta["last_page"]:
                break
        else:
            raise EvolizError("More than 10,000 Evoliz events in the poll window; reduce lookback hours")
        fresh = await self._filter_unseen(events, lambda event: str(event["eventid"]))
        return {"events": fresh, "event_count": len(fresh), "operation": config.operation,
                "companyid": self.config.credentials.companyid}

    @classmethod
    def resolve_agent_event(cls, output):
        events = output.get("events") if isinstance(output, dict) else None
        if not isinstance(events, list):
            return super().resolve_agent_event(output)
        if not events:
            return None
        lines = []
        for event in events[:20]:
            linked = event.get("linked_element") or {}
            lines.append(f"User {event.get('userid')} performed {event.get('action')} on {linked.get('type')} {linked.get('info') or linked.get('id')} (resource ID {linked.get('id')}, event ID {event.get('eventid')}, at {event.get('stampdate')}). {linked.get('link') or ''}")
        return {"text": f"Evoliz company {output.get('companyid')}: {len(events)} change(s).\n" + "\n".join(lines), "conversation_key": None}
