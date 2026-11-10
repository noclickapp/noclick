"""Track-POD delivery automations against the provider's published API v2 contract.

API key: https://api.track-pod.com/swagger/v1/swagger.json
Webhooks require UI registration, so status changes use the documented
GET /Order/Status/Date/{date} endpoint and the shared scheduled-poll family.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    create_model,
    field_validator,
)

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.track_pod_operations import FIELDS, OPERATIONS

BASE_URL = "https://api.track-pod.com"


class TrackPODAPIKeyCredential(BaseModel):
    credential_type: Literal["track_pod_api_key"] = Field(
        "track_pod_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., title="API Key", min_length=1, json_schema_extra={"ui:widget": "password"}
    )
    model_config = ConfigDict(
        hide_input_in_errors=True,
        title="Track-POD API Key",
        json_schema_extra={
            "x-credential-url": "https://web.track-pod.com/",
            "x-credential-instructions": "Copy your API key from Track-POD Settings → Web API. Paste the key here; NoClick sends it in the X-API-KEY header.",
        },
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class TrackPODInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator(*FIELDS, mode="before", check_fields=False)
    @classmethod
    def validate_input(cls, value, info):
        spec = FIELDS.get(info.field_name, {}).get("schema", {})
        if value is not None and spec.get("format") == "date-time":
            text = str(value)
            # The docs accept yyyy-MM-dd for order/route dates and HH:mm for
            # planned times. Canonicalize calendar dates for the OpenAPI wire.
            if len(text) == 10:
                text += "T00:00:00"
            if info.field_name not in {
                "start_time_plan",
                "time_slot_from",
                "time_slot_to",
            }:
                datetime.fromisoformat(text.replace("Z", "+00:00"))
            return text
        if value is not None and info.field_name.endswith("_json"):
            parsed = json.loads(value) if isinstance(value, str) else value
            if not isinstance(parsed, list) or any(
                not isinstance(item, dict) for item in parsed
            ):
                raise ValueError("Use a JSON array of objects")
            return json.dumps(parsed, allow_nan=False)
        return value


def _field(name, required):
    meta = FIELDS[name]
    schema = meta["schema"]
    kind = {"integer": int, "number": float, "boolean": bool}.get(
        schema.get("type"), str
    )
    extra = {}
    if name.endswith("_json"):
        extra = {
            "ui:widget": "textarea",
            "x-code-language": "json",
            "contentMediaType": "application/json",
            "contentSchema": {"type": "array", "items": {"type": "object"}},
        }
    elif schema.get("format") in {"date-time", "uuid"}:
        extra["format"] = schema["format"]
    bounds = {
        target: schema[source]
        for source, target in [
            ("minimum", "ge"),
            ("maximum", "le"),
            ("maxLength", "max_length"),
        ]
        if source in schema and schema.get("type") != "array"
    }
    if required and kind is str:
        bounds["min_length"] = 1
    return (
        kind if required else Optional[kind],
        Field(
            ... if required else None,
            title=meta["title"],
            description=meta["description"],
            examples=[schema["example"]] if "example" in schema else None,
            json_schema_extra=extra or None,
            **bounds,
        ),
    )


def _config(name, spec):
    names = set(spec["query"]) | set(spec["body"]) | set(spec["required"])
    return create_model(
        "TrackPOD" + "".join(part.title() for part in name.split("_")) + "Config",
        __base__=TrackPODInput,
        __module__=__name__,
        operation=(
            Literal[name],
            Field(
                name,
                title=spec["label"],
                json_schema_extra={
                    "ui:hidden": True,
                    "const": name,
                    "x-display-name": spec["label"],
                    "x-category": spec["category"],
                    "x-is-trigger": False,
                },
            ),
        ),
        **{name: _field(name, name in spec["required"]) for name in sorted(names)},
    )


CONFIG_MODELS = {name: _config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class TrackPODOnOrderStatusChangedConfig(PollTriggerConfigBase):
    operation: Literal["on_order_status_changed"] = Field(
        "on_order_status_changed",
        title="On Order Status Changed",
        json_schema_extra={
            "ui:hidden": True,
            "const": "on_order_status_changed",
            "x-category": "Triggers",
            "x-is-trigger": True,
            "x-display-name": "On Order Status Changed",
        },
    )
    lookback_minutes: int = Field(
        60,
        ge=1,
        le=1435,
        title="Lookback (minutes)",
        description="Poll orders modified within this window. Track-POD retains at most one day of status changes. Choose a window longer than the schedule interval; changes during longer outages may be missed.",
    )


TrackPODConfig = Annotated[
    Union[tuple(CONFIG_MODELS.values()) + (TrackPODOnOrderStatusChangedConfig,)],
    Discriminator("operation"),
]


class TrackPODNodeConfig(NodeConfig[TrackPODConfig, TrackPODAPIKeyCredential]):
    pass


class TrackPODNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-track-pod"
    connection_evidence = ConnectionEvidence(
        operation="list_drivers", noun="drivers", label_keys=("Name", "Username", "Id")
    )
    edit_examples = [
        "Create a Track-POD delivery order",
        "Complete an order in Track-POD",
        "Move an order to a route",
        "Watch for delivery status changes",
    ]

    @classmethod
    def get_config_model(cls):
        return TrackPODNodeConfig

    @staticmethod
    async def _request(key, method, path, *, params=None, body=None):
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.request(
                method,
                BASE_URL + path,
                params=params,
                json=body,
                headers={"X-API-KEY": key, "Accept": "application/json"},
            )
        if not 200 <= response.status_code < 300:
            try:
                payload = response.json()
                detail = (
                    (payload.get("Detail") or payload.get("Title"))
                    if isinstance(payload, dict)
                    else payload
                )
            except ValueError:
                detail = response.text
            detail = str(detail or response.reason_phrase).replace(key, "[redacted]")[
                :1000
            ]
            raise ValueError(f"Track-POD API {response.status_code}: {detail}")
        if not response.content:
            return None
        data = response.json()
        if (
            isinstance(data, dict)
            and isinstance(data.get("Status"), int)
            and data["Status"] >= 400
        ):
            detail = str(
                data.get("Detail") or data.get("Title") or "Request rejected"
            ).replace(key, "[redacted]")
            raise ValueError(f"Track-POD API {data['Status']}: {detail}")
        return data

    @classmethod
    def resolve_agent_event(cls, output: dict[str, Any]):
        orders = output.get("orders") if isinstance(output, dict) else None
        if not isinstance(orders, list):
            return super().resolve_agent_event(output)
        if not orders:
            return None
        lines = [
            f"- Order {order.get('Number') or order.get('Id')} for {order.get('Client') or 'customer'} at "
            f"{order.get('Address') or 'unspecified address'}: {order.get('Status') or 'status changed'} "
            f"({order.get('StatusDate') or 'time unspecified'}); TrackId {order.get('TrackId')}; "
            f"external id {order.get('Id')}; note: {order.get('Note') or ''}"
            for order in orders[:10]
        ]
        return {
            "text": f"Track-POD: {len(orders)} order status change(s)\n"
            + "\n".join(lines),
            "conversation_key": None,
        }

    @classmethod
    def should_propagate_output(cls, output, config):
        return (
            bool(output.get("new_order_count"))
            if config.get("operation") == "on_order_status_changed"
            else True
        )

    async def execute(self, inputs):
        if (
            not isinstance(self.config, TrackPODNodeConfig)
            or not self.config.credentials
        ):
            raise ValueError("Connect a Track-POD API key")
        config = self.config.config
        key = self.config.credentials.api_key
        if isinstance(config, TrackPODOnOrderStatusChangedConfig):
            since = datetime.now(timezone.utc) - timedelta(
                minutes=config.lookback_minutes
            )
            path = "/Order/Status/Date/" + quote(since.isoformat(), safe="")
            orders = await self._request(key, "GET", path)
            if not isinstance(orders, list) or any(
                not isinstance(item, dict) for item in orders
            ):
                raise ValueError("Track-POD returned an invalid order list")

            def event_id(order):
                identifier = (
                    order.get("TrackId") or order.get("Id") or order.get("Number")
                )
                if not identifier:
                    return None
                version = json.dumps(
                    [identifier, order.get("StatusDate"), order.get("Status")]
                )
                return hashlib.sha256(version.encode()).hexdigest()

            fresh = await self._filter_unseen(orders, event_id)
            return {"status": "success", "orders": fresh, "new_order_count": len(fresh)}
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec["path"]
        for name, value in values.items():
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
        params = {
            wire: values[name] for name, wire in spec["query"].items() if name in values
        }
        body = {
            wire: json.loads(values[name]) if name.endswith("_json") else values[name]
            for name, wire in spec["body"].items()
            if name in values
        }
        data = await self._request(
            key,
            spec["method"],
            path,
            params=params or None,
            body=body if spec["body"] else None,
        )
        return {"status": "success", "operation": config.operation, "data": data}
