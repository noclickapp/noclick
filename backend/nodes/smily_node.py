"""Smily Channel API V1 (OTA), not the separate BookingSync API v3.

Contract: https://demo.platforms.bookingsync.com/api-docs/swagger/api/ota/v1/swagger.json
Host/key: https://channel-api.developers.bookingsync.com/guides/getting-started/
LOS sync: https://channel-api.developers.bookingsync.com/guides/live-los-records-api/
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Literal, Optional, Union
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Discriminator, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin, poll_scope
from nodes.cron_trigger_node import ScheduleConfig
from utils.ssrf import guarded_async_client, normalize_provider_https_origin

DOCS = "https://channel-api.developers.bookingsync.com/guides/getting-started/"
KINDS = Literal["final_price", "rental_price", "rental_price_before_special_offers"]
CANCEL_REASONS = Literal[
    "canceled_by_owner_other", "canceled_by_traveller_other", "canceled_by_owner_incorrect_price",
    "canceled_by_owner_rental_unbookable", "canceled_by_traveller_minimum_age_not_met",
    "canceled_by_traveller_travel_arrangements_infeasible", "canceled_by_traveller_travel_arrangements_infeasible_due_to_visa",
    "canceled_by_traveller_travel_arrangements_infeasible_due_to_covid", "canceled_by_traveller_host_request_book_elsewhere",
    "canceled_by_traveller_property_quality", "canceled_by_owner_no_payment", "canceled_by_owner_rental_overbooked",
    "canceled_by_traveller_wrong_price", "canceled_by_traveller_wrong_facilities", "canceled_by_traveller_rebooking",
    "canceled_by_traveller_personal",
]


class SmilyAPIKeyCredential(BaseModel):
    credential_type: Literal["smily_api_key"] = Field("smily_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", json_schema_extra={"ui:widget": "password"})
    host: str = Field(..., title="Channel API Host", description="The HTTPS host supplied by Smily, for example https://my-channel.platforms.bookingsync.com.")
    model_config = ConfigDict(title="Smily API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": DOCS,
        "x-credential-instructions": "Paste the Channel API key and host supplied by the Smily Partners Team (partners@smily.com). This integration uses the Channel API; API v3 OAuth tokens belong to a different API.",
    })

    @field_validator("host", mode="before")
    @classmethod
    def provider_host(cls, value):
        return normalize_provider_https_origin(value, "platforms.bookingsync.com", field_name="Channel API Host")

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        token = clean_secret(value, field_name="API Key", key=True)
        if any(c.isspace() for c in token):
            raise ValueError("Paste the API key without the Bearer prefix or whitespace")
        return token


@dataclass(frozen=True)
class Operation:
    label: str
    method: str
    path: str
    group: str
    required: tuple[str, ...] = ()
    query: tuple[tuple[str, str], ...] = ()
    body: tuple[str, ...] = ()
    resource: str = ""
    idempotent: bool = False


def list_query(resource, *filters, pagination=False):
    query = [("sort", "sort"), ("fields", f"fields[{resource}]")]
    query += [(f"filter_{key.replace('-', '_')}", f"filter[{key}]") for key in filters]
    if pagination:
        query += [("page_number", "page[number]"), ("page_size", "page[size]")]
    return tuple(query)


STAY = ("start_at", "end_at", "adults", "children", "rental_id")
GUEST = ("client_first_name", "client_last_name", "client_email", "client_phone_number")
BOOKING = (*STAY, "final_price", "currency", *GUEST)
OPERATIONS = {
    "list_accounts": Operation("List Accounts", "GET", "/accounts", "Accounts", query=list_query("accounts", "id")),
    "get_account": Operation("Get Account", "GET", "/accounts/{account_id}", "Accounts", ("account_id",), (("fields", "fields[accounts]"),)),
    "list_rentals": Operation("List Rentals", "GET", "/rentals", "Rentals", query=list_query("rentals", "id", "account-id", pagination=True)),
    "get_rental": Operation("Get Rental", "GET", "/rentals/{rental_id}", "Rentals", ("rental_id",), (("fields", "fields[rentals]"),)),
    "create_quote": Operation("Create Quote", "POST", "/quotes", "Bookings", STAY, body=STAY, resource="quotes"),
    "list_bookings": Operation("List Bookings", "GET", "/bookings", "Bookings", query=list_query("bookings", "id", "account-id", "rental-id")),
    "get_booking": Operation("Get Booking", "GET", "/bookings/{booking_id}", "Bookings", ("booking_id",), (("fields", "fields[bookings]"),)),
    "create_booking": Operation("Create Booking", "POST", "/bookings", "Bookings", BOOKING, body=(*BOOKING, "client_country_code", "client_preferred_locale", "channel_commission"), resource="bookings", idempotent=True),
    "cancel_booking": Operation("Cancel Booking", "PATCH", "/bookings/{booking_id}/cancel", "Bookings", ("booking_id", "cancelation_reason", "channel_cancelation_cost", "currency"), body=("cancelation_reason", "cancelation_description", "channel_cancelation_cost", "currency"), resource="bookings"),
    "list_payments": Operation("List Payments", "GET", "/payments", "Payments", query=list_query("payments", "id", "booking-id")),
    "get_payment": Operation("Get Payment", "GET", "/payments/{payment_id}", "Payments", ("payment_id",), (("fields", "fields[payments]"),)),
    "create_payment": Operation("Create Payment", "POST", "/payments", "Payments", ("amount", "currency", "booking_id"), body=("amount", "currency", "booking_id", "paid_at", "payment_kind"), resource="payments", idempotent=True),
    "list_los_records": Operation("List LOS Records", "GET", "/los-records", "Pricing", ("los_rental_id", "day"), (("los_rental_id", "filter[rental]"), ("day", "filter[day]"), ("kind", "filter[kind]"), ("occupancy", "filter[occupancy]"), ("fields", "fields[los-records]"), ("sort", "sort"))),
    "list_live_los_records": Operation("List Live LOS Records", "GET", "/live-los-records", "Pricing", query=(("kind", "kind"), ("changed_since", "changed_since"), ("cursor", "cursor"))),
    "get_rental_live_los_records": Operation("Get Rental Live LOS Records", "GET", "/rentals/{rental_id}/live-los-records", "Pricing", ("rental_id",), (("kind", "kind"), ("changed_since", "changed_since"))),
    "list_los_export_urls": Operation("List LOS Export URLs", "GET", "/los-record-export-urls", "Pricing", query=list_query("los-record-export-urls", "id")),
}


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def compatible_dates(self):
        start, end = getattr(self, "start_at", None), getattr(self, "end_at", None)
        if start is not None and end is not None and end <= start:
            raise ValueError("End must be after start")
        if getattr(self, "cursor", None) and getattr(self, "changed_since", None):
            raise ValueError("Omit changed_since when resuming with a cursor")
        return self


POSITIVE = Annotated[int, Field(gt=0)]
COUNT = Annotated[int, Field(ge=0)]
DECIMAL = Annotated[str, Field(pattern=r"^-?[0-9]+(?:\.[0-9]+)?$")]
TEXT = Annotated[str, Field(min_length=1, max_length=4096)]
FIELD_TYPES = {
    **{key: POSITIVE for key in ("account_id", "rental_id", "booking_id", "payment_id", "los_rental_id", "page_number", "page_size", "occupancy")},
    "adults": COUNT, "children": COUNT, "day": date, "paid_at": AwareDatetime,
    "changed_since": AwareDatetime, "kind": KINDS,
    "cancelation_reason": CANCEL_REASONS,
    "payment_kind": Literal["wiretransfer", "paypal", "travel-cheque", "credit-card"],
    **{key: DECIMAL for key in ("amount", "final_price", "channel_commission", "channel_cancelation_cost")},
    "idempotency_key": UUID,
}
DESCRIPTIONS = {
    "fields": "Comma-separated JSON:API attributes to return.",
    "sort": "Comma-separated scalar attributes; prefix with - for descending order.",
    "page_number": "Rental pagination must first be enabled by Smily. Omit to use the provider's default.",
    "page_size": "Rental pagination must first be enabled by Smily.",
    "final_price": "Use the price returned by Create Quote for the same stay.",
    "currency": "ISO currency from the quote or original booking.",
    "changed_since": "ISO 8601 checkpoint within retained history (one month). Omit for a full sync.",
    "cursor": "Opaque next_cursor from the previous page with the same kind; omit changed_since.",
    "idempotency_key": "Optional UUID reused only for retries of this identical write; successful responses are cached for six hours.",
}


def _make_config(name, spec):
    names = set(spec.required + spec.body + tuple(key for key, _ in spec.query))
    if spec.idempotent:
        names.add("idempotency_key")
    fields = {}
    for key in sorted(names):
        kind = FIELD_TYPES.get(key, TEXT)
        if key in {"start_at", "end_at"}:
            kind = date if name == "create_quote" else AwareDatetime
        if key == "rental_id" and name == "create_quote":
            # The V1 quote schema specifies a string (bookings use an integer).
            kind = Annotated[str, Field(pattern=r"^[0-9]+$")]
        required = key in spec.required
        default = ... if required else "final_price" if key == "kind" else None
        extra = {"x-dynamic-options": {"field_name": "account_id", "allow_custom": True}} if key == "account_id" else None
        fields[key] = (kind if required or key == "kind" else Optional[kind], Field(
            default, title=key.replace("_", " ").title(), description=DESCRIPTIONS.get(key), json_schema_extra=extra))
    return create_model("Smily" + "".join(w.title() for w in name.split("_")) + "Config", __base__=_Input,
        operation=(Literal[name], Field(name, title=spec.label, json_schema_extra={"ui:hidden": True,
            "x-display-name": spec.label, "x-category": spec.group, "x-is-trigger": False})), **fields)


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class SmilyOnLOSRecordsChangedConfig(PollTriggerConfigBase):
    operation: Literal["on_los_records_changed"] = Field("on_los_records_changed", title="On New or Updated LOS Prices", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On New or Updated LOS Prices", "x-category": "Triggers", "x-is-trigger": True})
    rental_id: POSITIVE = Field(..., title="Rental ID", description="Watch the current LOS prices for this rental.")
    kind: KINDS = Field("final_price", title="Price Kind")
    schedule: Optional[ScheduleConfig] = Field(default_factory=lambda: ScheduleConfig(frequency="minutes", interval=15),
        title="Schedule", description="Full snapshot comparison; 15 minutes respects the documented full-sync allowance.",
        json_schema_extra={"ui:widget": "schedule", "x-exclude-frequencies": ["seconds"]})


SmilyConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (SmilyOnLOSRecordsChangedConfig,)], Discriminator("operation")]


class SmilyNodeConfig(NodeConfig[SmilyConfig, SmilyAPIKeyCredential]):
    pass


class SmilyNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-smily"
    connection_evidence = ConnectionEvidence(field="account_id", noun="accounts")

    @classmethod
    def get_config_model(cls):
        return SmilyNodeConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        if field_name != "account_id":
            return {"options": []}
        credential = SmilyAPIKeyCredential.model_validate(credential_data)
        page = await cls._request(credential, "GET", "/accounts")
        if not isinstance(page["data"], list):
            raise ValueError("Smily returned an invalid account list")
        options = [{"value": str(row["id"]), "label": row.get("attributes", {}).get("name") or str(row["id"])}
                   for row in page["data"] if isinstance(row, dict) and row.get("id")]
        return {"options": [row for row in options if not search or search.casefold() in row["label"].casefold()]}

    @staticmethod
    def _redact(value, key):
        if isinstance(value, str):
            return value.replace(key, "[redacted]")
        if isinstance(value, list):
            return [SmilyNode._redact(v, key) for v in value]
        if isinstance(value, dict):
            return {k: SmilyNode._redact(v, key) for k, v in value.items()}
        return value

    @classmethod
    async def _request(cls, credential, method, path, *, params=None, body=None, idempotency_key=None):
        headers = {"Authorization": f"Bearer {credential.api_key}", "Accept": "application/vnd.api+json, application/json"}
        if body is not None:
            headers["Content-Type"] = "application/vnd.api+json"
        if idempotency_key:
            headers["Idempotency-Key"] = str(idempotency_key)
        async with guarded_async_client(timeout=45, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, credential.host + "/api/ota/v1" + path, params=params, json=body, headers=headers)
        if not 200 <= response.status_code < 300:
            # Keep the provider's rejection visible while removing echoed secrets.
            detail = cls._redact(response.text, credential.api_key)[:2000]
            raise ValueError(f"Smily API error {response.status_code}: {detail}")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Smily returned an invalid JSON response") from None
        if not isinstance(payload, dict) or "data" not in payload or "errors" in payload:
            raise ValueError("Smily returned an unexpected response envelope")
        return payload

    async def _poll_prices(self, credential, config):
        # The documented per-rental endpoint returns a complete snapshot in one
        # response; it accepts no cursor (unlike the all-rentals sync endpoint).
        page = await self._request(credential, "GET", f"/rentals/{config.rental_id}/live-los-records",
                                   params={"kind": config.kind})
        data = page.get("data")
        if not isinstance(data, list):
            raise ValueError("Smily returned an invalid live LOS snapshot")
        records = []
        for row in data:
            if not isinstance(row, dict) or not all(k in row for k in ("account_id", "rental_id", "currency", "rows")):
                raise ValueError("Smily returned an invalid live LOS record")
            if row["rental_id"] != config.rental_id or not isinstance(row["rows"], list):
                raise ValueError("Smily returned LOS records outside the selected rental")
            records.append({key: row[key] for key in ("account_id", "rental_id", "currency", "rows")})
        # Compare the latest complete snapshot, not all historical hashes: A→B→A
        # is two updates. Commit state only after the complete read has succeeded.
        ids = [hashlib.sha256(json.dumps(r, sort_keys=True, separators=(",", ":")).encode()).hexdigest() for r in records]
        scope = poll_scope(type(self), config.model_dump(mode="json"))

        def mutate(state):
            baseline = "seen_ids" not in state or state.get("scope", scope) != scope
            if not baseline and getattr(self, "_poll_baseline_only", False):
                return None, []
            seen = set(state.get("seen_ids", []))
            fresh = [] if baseline else [r for r, ident in zip(records, ids) if ident not in seen]
            return {"seen_ids": ids, "scope": scope}, fresh

        fresh = await self._update_node_state(mutate, skip_result=[])
        self._poll_emitted_count = len(fresh)
        return self._redact({"data": fresh, "changed_count": len(fresh), "kind": config.kind}, credential.api_key)

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("changed_count")) if config.get("operation") == "on_los_records_changed" else True

    @classmethod
    def resolve_agent_event(cls, output):
        if "changed_count" not in output:
            return super().resolve_agent_event(output)
        if not output.get("data"):
            return None
        lines = [f"- Account {r['account_id']}, rental {r['rental_id']}: {len(r['rows'])} LOS day/occupancy rows in {r['currency']}" for r in output["data"][:10]]
        return {"text": f"Smily: new or updated {output['kind']} LOS prices for {output['changed_count']} rental(s).\n" + "\n".join(lines) + "\nUse rental_id to fetch current prices and create a quote before booking.", "conversation_key": None}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Smily Channel API key and host")
        config = self.config.config
        if isinstance(config, SmilyOnLOSRecordsChangedConfig):
            return await self._poll_prices(credential, config)
        spec = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        path = spec.path
        for key in re.findall(r"\{(\w+)\}", path):
            path = path.replace("{" + key + "}", str(values[key]))
        params = {wire: values[key] for key, wire in spec.query if key in values}
        body = None
        if spec.body:
            attrs = {("kind" if key == "payment_kind" else key.replace("_", "-")): values[key] for key in spec.body if key in values}
            body = {"data": {"type": spec.resource, "attributes": attrs}}
        result = await self._request(credential, spec.method, path, params=params, body=body, idempotency_key=values.get("idempotency_key"))
        return self._redact(result, credential.api_key)
