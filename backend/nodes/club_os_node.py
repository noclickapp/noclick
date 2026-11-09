"""Club OS v2 reporting, calendar actions and creation-time poll triggers.
Routes and request fields follow Club OS's published APIv2 and Calendar contracts.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.club_os_operations import OPERATIONS
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE_URL = "http://api2.club-os.com"
DOCS_URL = "https://s3.amazonaws.com/clubos-docs/api/APIv2_Doc.yaml"


class ClubOSTokenCredential(BaseModel):
    model_config = ConfigDict(title="Club OS API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": DOCS_URL,
            "x-credential-instructions": "Paste the token returned by Club OS's authenticate endpoint using the API username and password supplied by Club OS. Tokens last 24 hours; replace the token here after it expires. Paste only the token, without an Authorization or Bearer prefix. NoClick verifies access by reading the locations this API user can access. The published v2 contract specifies HTTP, so requests send this token without transport encryption.",
        })
    credential_type: Literal["club_os_token"] = Field("club_os_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=16384,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the token, without a header or prefix")
        return value


class _Action(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


def _config(name, spec):
    fields = {}
    for field, definition in spec["fields"].items():
        kind = int if definition["type"] == "integer" else str
        # Calendar's availability parameters are documented as integers, unlike
        # event-list datetime strings. Preserve that contract without coercing units.
        kwargs = {"title": field.replace("_", " ").title(), "description": definition["description"]}
        if field == "attendee_status":
            kind = Literal["CONFIRM", "CANCEL"]
        if definition["required"]:
            fields[field] = (kind, Field(..., **kwargs))
        else:
            fields[field] = (Optional[kind], Field(None, **kwargs))
    return create_model("ClubOS" + "".join(x.title() for x in name.split("_")) + "Config",
        __base__=_Action, __module__=__name__,
        operation=(Literal[name], Field(name, title=spec["label"], json_schema_extra={
            "ui:hidden": True, "x-display-name": spec["label"], "x-is-trigger": False,
            "x-category": "Calendar" if "/locations/" in spec["path"] or "/events" in spec["path"] else "Reports",
        })), **fields)


CONFIG_MODELS = {name: _config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class _Poll(PollTriggerConfigBase):
    club_id: int = Field(..., title="Club ID", description="The Club OS ID of the club to monitor.")
    location_id: int = Field(..., title="Location ID", description="The Club OS ID of the location to monitor.")
    lookback_hours: int = Field(24, ge=1, le=168, title="Lookback hours",
        description="Recheck this rolling creation-time window on every poll. The first poll establishes a baseline. Items outside this window are not monitored; choose a window longer than the schedule interval. The API documents no pagination.")


class ClubOSOnNewLeadConfig(_Poll):
    operation: Literal["on_new_lead"] = Field("on_new_lead", title="On New Lead", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On New Lead", "x-category": "Triggers"})


class ClubOSOnNewSalesEventConfig(_Poll):
    operation: Literal["on_new_sales_event"] = Field("on_new_sales_event", title="On New Sales Event", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On New Sales Event", "x-category": "Triggers"})


ClubOSConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (ClubOSOnNewLeadConfig, ClubOSOnNewSalesEventConfig)], Field(discriminator="operation")]


class ClubOSNodeConfig(NodeConfig[ClubOSConfig, ClubOSTokenCredential]):
    pass


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class ClubOSNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-club-os"
    connection_evidence = ConnectionEvidence(operation="list_locations", noun="locations", label_keys=("name", "id"))
    edit_examples = ["Watch for new Club OS leads", "List Club OS training agreements", "Book a personal training session", "Cancel a customer's event attendance"]

    @classmethod
    def get_config_model(cls):
        return ClubOSNodeConfig

    @staticmethod
    async def _request(token, method, path, *, params=None, body=None):
        # Fixed provider origin; redirects and automatic retries are disabled.
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            try:
                response = await client.request(method, BASE_URL + path, params=params,
                    json=body, headers={"Authorization": token, "Accept": "application/json"})
            except httpx.HTTPError:
                raise ValueError("Club OS request could not be completed; inspect any write before retrying") from None
        if not 200 <= response.status_code < 300:
            detail = _redact(response.text[:2000], token)
            raise ValueError(f"Club OS API error {response.status_code}: {detail}")
        try:
            return response.json() if response.content else {}
        except ValueError:
            raise ValueError("Club OS returned an unexpected non-JSON response; inspect any write before retrying") from None

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Club OS API token")
        token = self.config.credentials.api_token
        config = self.config.config
        if isinstance(config, _Poll):
            result = await self._poll(token, config)
        else:
            spec = OPERATIONS[config.operation]
            values = config.model_dump(exclude_none=True, exclude={"operation"})
            path = spec["path"]
            for key, definition in spec["fields"].items():
                marker = "{" + definition["wire"] + "}"
                if marker in path:
                    path = path.replace(marker, quote(str(values[key]), safe=""))
            # Several Calendar parameters are specified in both the URL template
            # and query. Send their query copy as published, without dropping it.
            params = {spec["fields"][k]["wire"]: values[k] for k in spec["query"] if k in values}
            body = {spec["fields"][k]["wire"]: values[k] for k in spec["body"]} if spec["body"] else None
            data = await self._request(token, spec["method"], path, params=params, body=body)
            if config.operation == "list_locations":
                if not isinstance(data, list) or any(not isinstance(row, dict) or not isinstance(row.get("location"), dict) for row in data):
                    raise ValueError("Club OS returned an unexpected location-list response")
                data = [row["location"] for row in data]
            result = {"data": data}
        output = _redact({"operation": config.operation, **result}, token)
        await self.emit(output)
        return output

    async def _poll(self, token, config):
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=config.lookback_hours)
        fmt = lambda dt: dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        lead = isinstance(config, ClubOSOnNewLeadConfig)
        params = {"clubId": config.club_id, "locationId": config.location_id,
            "startAt" if lead else "createdAtStartAt": fmt(start),
            "endAt" if lead else "createdAtEndAt": fmt(now)}
        data = await self._request(token, "GET", "/leads" if lead else "/sales-events-created", params=params)
        # The published reporting response schema is a single flat record.
        # Accept multiple records as a list too, without inventing wrapper keys.
        rows = [data] if isinstance(data, dict) else data
        id_field = "customerId" if lead else "eventId"
        if not isinstance(rows, list) or any(not isinstance(row, dict) or row.get(id_field) is None or row.get("createdAt") is None for row in rows):
            raise ValueError("Club OS returned an unexpected creation-time report")
        def identity(row):
            parts = [str(row[id_field]), str(row["createdAt"])]
            if not lead:
                parts.append(str(row.get("attendeeId", "")))
            return ":".join(parts)
        fresh = await self._filter_unseen(rows, identity)
        return {"data": fresh, "new_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_count")) if config.get("operation") in {"on_new_lead", "on_new_sales_event"} else True

    @classmethod
    def resolve_agent_event(cls, output):
        name = output.get("operation") if isinstance(output, dict) else None
        if name not in {"on_new_lead", "on_new_sales_event"}:
            return super().resolve_agent_event(output)
        rows = output.get("data")
        if not isinstance(rows, list) or not rows:
            return None
        lead = name == "on_new_lead"
        lines = []
        for row in rows[:10]:
            if lead:
                who = " ".join(str(row.get(k) or "") for k in ("customerFirstName", "customerLastName")).strip()
                lines.append(f"- New lead {who or 'Unnamed lead'} (customer ID {row.get('customerId')}), {row.get('email') or 'no email'}, source {row.get('source') or 'unspecified'}; location {row.get('locationName')} (ID {row.get('locationId')}), club {row.get('clubId')}; created {row.get('createdAt')}")
            else:
                who = " ".join(str(row.get(k) or "") for k in ("attendeeFirstName", "attendeeLastName")).strip()
                owner = " ".join(str(row.get(k) or "") for k in ("eventOwnerFirstName", "eventOwnerLastName")).strip()
                lines.append(f"- New {row.get('eventTypeName') or 'sales event'} (event ID {row.get('eventId')}) for {who or 'unnamed attendee'} (attendee ID {row.get('attendeeId')}), owner {owner} (ID {row.get('eventOwnerId')}); location {row.get('locationName')} (ID {row.get('locationId')}), club {row.get('clubId')}; created {row.get('createdAt')}")
        return {"text": (f"Club OS: {len(rows)} new {'lead(s)' if lead else 'sales event(s)'}:\n" + "\n".join(lines))[:4000], "conversation_key": None}
