"""WeezTicket operations against Weezevent's published OpenAPI 1.0.0.

Bearer tokens are supplied by the user; account-owned events prove the connection.
Webhooks require provider-side configuration, so attendee/order changes use polling.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE = "https://api.weezevent.com/ticket"
CREDENTIAL_TYPE = "weezevent_da56471_bearer"
DOCS = "https://docapi.weezevent.com/weezticket.json"


class WeezeventCredential(BaseModel):
    model_config = ConfigDict(title="Weezevent Access Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://docapi.weezevent.com/",
            "x-credential-instructions": "Paste an existing WeezTicket bearer access token and your organization ID. Obtain client credentials from Weezevent Support, then generate an access token using the documented client credentials grant. Replace expired tokens here. Permissions are assigned by Weezevent; event, attendee, order and resale operations require the corresponding account capacities. NoClick checks access by listing your organization's events."})
    credential_type: Literal["weezevent_da56471_bearer"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Access token", repr=False,
        json_schema_extra={"ui:widget": "password"})
    organization_id: int = Field(..., ge=1, title="Organization ID")

    @field_validator("access_token")
    @classmethod
    def token(cls, value):
        value = value.strip()
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the bearer access token")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


EVENT_OPTIONS = {"x-dynamic-options": {"field_name": "event_id", "allow_custom": True, "searchable": True}}
EVENT_PATH = "/organizations/{organization_id}/events/{event_id}"
# name: method, path, query fields, body fields, output resource.
OPERATIONS = {
    "list_events": ("GET", "/organizations/{organization_id}/events", ("id", "name", "expand", "chart", "publication_status__in", "end_date", "tag__in", "time_status", "ordering"), (), "events"),
    "get_event": ("GET", EVENT_PATH, ("expand",), (), "events"),
    "create_event": ("POST", "/organizations/{organization_id}/events", (), ("name", "start_date", "end_date", "timezone", "description", "currency", "default_language", "website", "subtitle", "surtitle", "status", "type"), "events"),
    "list_rates": ("GET", EVENT_PATH + "/rates", ("expand",), (), "rates"),
    "create_rate": ("POST", EVENT_PATH + "/rates", (), ("name", "price", "description", "distributor"), "rate"),
    "list_attendees": ("GET", EVENT_PATH + "/attendees", ("rate__in", "buyer_email", "scan_status", "modified__gt", "include_deleted", "order__sold_date_before", "order__sold_date_after", "order__status__in"), (), "attendees"),
    "get_attendee": ("GET", EVENT_PATH + "/attendees/{attendee_id}", (), (), "attendee"),
    "get_attendee_by_barcode": ("GET", EVENT_PATH + "/barcode/{barcode}", (), (), "attendee"),
    "list_orders": ("GET", EVENT_PATH + "/orders", ("id_transaction__in", "modified__gt"), (), "orders"),
    "get_order": ("GET", EVENT_PATH + "/orders/{order_id}", (), (), "order"),
    "get_invoice": ("GET", EVENT_PATH + "/orders/{order_id}/invoice", (), (), "invoice"),
    # The published contract includes /ticket in these paths in addition to the server base.
    "validate_resale_ticket": ("GET", "/ticket" + EVENT_PATH + "/resale/validate", ("barcode",), (), "ticket"),
    "swap_resale_ticket": ("POST", "/ticket" + EVENT_PATH + "/resale/swap", (), ("barcode", "first_name", "last_name", "email"), "ticket"),
    "get_swap_history": ("GET", "/ticket" + EVENT_PATH + "/swap_history", ("barcode",), (), "ticket"),
    "on_new_or_updated_attendee": ("GET", EVENT_PATH + "/attendees", ("modified__gt", "include_deleted"), (), "attendees"),
    "on_new_or_updated_order": ("GET", EVENT_PATH + "/orders", ("modified__gt",), (), "orders"),
}
TRIGGERS = frozenset({"on_new_or_updated_attendee", "on_new_or_updated_order"})


def _field(name, required, op):
    kind = int if name in {"event_id", "attendee_id", "order_id", "distributor", "id", "tag__in"} else bool if name in {"include_deleted", "scan_status"} else float if name == "price" else str
    if name == "expand" and op == "list_rates":
        kind = list[str]
    extra = EVENT_OPTIONS if name == "event_id" else {}
    kwargs = {"title": name.replace("__", " ").replace("_", " ").title(), "json_schema_extra": extra}
    if kind is int and name in {"event_id", "attendee_id", "order_id"}: kwargs["ge"] = 1
    if name == "modified__gt": kwargs["description"] = "Only records modified after this date, for example 2021-04-26. Leave empty to watch the complete event."
    if name == "start_date": kwargs["description"] = "ISO 8601 date and time, for example 2013-09-01T12:00:00Z."
    return (kind if required else kind | None, Field(... if required else None, **kwargs))


def _model(op, spec):
    method, path, query, body, resource = spec
    names = set(query + body)
    names.update(part.split("}")[0] for part in path.split("{")[1:] if not part.startswith("organization_id}"))
    required = {name for name in names if "{" + name + "}" in path}
    if op == "create_event": required.update({"name", "start_date"})
    if op == "create_rate": required.update({"name", "price"})
    if op in {"validate_resale_ticket", "get_swap_history"}: required.add("barcode")
    if op == "swap_resale_ticket": required.update(body)
    label = op.replace("_", " ").title()
    return create_model("Weezevent" + label.replace(" ", "") + "Config", __module__=__name__,
        __base__=PollTriggerConfigBase if op in TRIGGERS else Input,
        operation=(Literal[op], Field(op, title=label, json_schema_extra={"ui:hidden": True,
            "x-display-name": label, "x-is-trigger": op in TRIGGERS,
            "x-category": "Triggers" if op in TRIGGERS else resource.title()})),
        **{name: _field(name, name in required, op) for name in sorted(names)})


CONFIG_MODELS = {op: _model(op, spec) for op, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
WeezeventConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class WeezeventNodeConfig(NodeConfig[WeezeventConfig, WeezeventCredential]):
    pass


class WeezeventNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-weezevent-da56471"
    connection_evidence = ConnectionEvidence(field="event_id", operation="list_events", noun="events")

    @classmethod
    def get_config_model(cls):
        return WeezeventNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"})
        if response.is_error:
            try:
                detail = response.json()
                detail = detail.get("detail") or detail.get("message") or detail.get("error") if isinstance(detail, dict) else None
            except ValueError:
                detail = None
            raise ValueError(f"Weezevent API error {response.status_code}: {detail or 'request failed'}")
        if not 200 <= response.status_code < 300:
            raise ValueError(f"Weezevent unexpected response {response.status_code}")
        return response.json()

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name != "event_id": return {"options": []}
        if page_token: raise ValueError("Weezevent does not document event pagination parameters")
        credential = WeezeventCredential.model_validate(credential_data)
        result = await cls._request(credential, "GET", f"/organizations/{credential.organization_id}/events",
            params={"name": search} if search else {})
        if not isinstance(result, list): raise ValueError("Expected Weezevent event list")
        return {"options": [{"value": str(row["id"]), "label": row.get("name") or str(row["id"])}
            for row in result if isinstance(row, dict) and row.get("id") is not None]}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("changed_count")) if config.get("operation") in TRIGGERS else True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or "changed_count" not in output:
            return super().resolve_agent_event(output)
        items = output.get("items", [])
        if not items: return None
        resource = output["resource"]
        lines = []
        for item in items[:10]:
            if resource == "attendees":
                who = " ".join(str(item.get(k) or "") for k in ("first_name", "last_name")).strip()
                lines.append(f"- Attendee {who or item.get('email') or 'unnamed'}; id {item.get('id')}; email {item.get('email') or ''}; rate {item.get('rate')}")
            else:
                who = " ".join(str(item.get(k) or "") for k in ("buyer_first_name", "buyer_last_name")).strip()
                lines.append(f"- Order {item.get('id_transaction')} from {who or item.get('buyer_email') or 'unnamed buyer'}; email {item.get('buyer_email') or ''}; status {item.get('status')}; reference {item.get('transaction_reference')}")
        return {"text": f"Weezevent: {len(items)} new or updated {resource} in event {output['event_id']} (organization {output['organization_id']}).\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Weezevent access token and organization")
        credential = self.config.credentials
        config = self.config.config
        op = config.operation
        method, path, query, fields, resource = OPERATIONS[op]
        values = config.model_dump(exclude_none=True)
        path = path.replace("{organization_id}", str(credential.organization_id))
        for name, value in values.items():
            marker = "{" + name + "}"
            if marker in path:
                if str(value) in {"", ".", ".."}:
                    raise ValueError(f"{name} must be a resource identifier")
                path = path.replace(marker, quote(str(value), safe=""))
        params = {name: values[name] for name in query if name in values}
        body = {name: values[name] for name in fields if name in values} if fields else None
        if op == "swap_resale_ticket":
            body = {"ticket": {"barcode": values["barcode"]}, "customer": {name: values[name] for name in ("first_name", "last_name", "email")}}
        if op == "create_event":
            for field in ("start_date", "end_date"):
                if field in body:
                    try: datetime.fromisoformat(body[field].replace("Z", "+00:00"))
                    except ValueError: raise ValueError(f"{field} must be an ISO 8601 date and time") from None
        result = await self._request(credential, method, path, params=params, body=body)
        if resource in {"events", "rates", "attendees", "orders"}:
            if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
                raise ValueError("Expected a Weezevent list of records")
            if op in TRIGGERS:
                if len(result) > 10000: raise ValueError("Narrow the modified-after filter to at most 10000 records")
                id_field = "id" if resource == "attendees" else "id_transaction"
                def version(item):
                    if item.get(id_field) is None: raise ValueError("Weezevent record has no documented identifier")
                    return str(item[id_field]) + ":" + hashlib.sha256(json.dumps(item, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                changed = await self._filter_unseen(result, version)
                return {"items": changed, "changed_count": len(changed), "resource": resource,
                    "event_id": config.event_id, "organization_id": credential.organization_id}
            return {"items": result, "count": len(result)}
        if not isinstance(result, dict): raise ValueError("Expected a Weezevent record")
        return {"data": result}
