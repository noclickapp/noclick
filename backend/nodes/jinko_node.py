"""Jinko travel workflows over its published public REST contract."""
from __future__ import annotations

import re
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.jinko_operations import JinkoConfig, ROUTES
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.gojinko.com"


class JinkoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Jinko API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.gojinko.com/developers/keys",
            "x-credential-instructions": "Paste a production Jinko API key. Travel AI search needs a tenant key with search_live access and Travel AI enabled. Connection testing reads travel-demand data and may use Jinko credits; it proves key reachability, not account identity."
        })
    credential_type: Literal["jinko_api_key"] = Field("jinko_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class JinkoFullConfig(NodeConfig[JinkoConfig, JinkoAPIKeyCredential]):
    pass


def _path_segment(value):
    if not isinstance(value, str) or not value or value in {".", ".."} or len(value) > 1000 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Use the opaque identifier returned by Jinko")
    return quote(value, safe="")


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {k.replace(secret, "[redacted]"): _redact(v, secret) for k, v in value.items()}
    return value


class JinkoNode(WorkflowNode):
    integration_type = "automation-jinko"
    connection_evidence = ConnectionEvidence(
        noun="travel demand destinations", operation="list_destinations", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return JinkoFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Jinko API key")
        config = self.config.config
        method, route = ROUTES[config.operation]
        payload = config.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        for name in re.findall(r"\{(\w+)\}", route):
            route = route.replace("{" + name + "}", _path_segment(payload.pop(name)))
        if "service_operation" in payload:
            payload["operation"] = payload.pop("service_operation")
        if config.operation == "manage_trip":
            if not any(payload.get(k) for k in ("add_item", "remove_item", "upsert_travelers", "hotel_room_guests")):
                raise ValueError("Provide a trip item, travelers, or room guests to update")
            if any(payload.get(k) for k in ("remove_item", "hotel_room_guests")) and not payload.get("trip_id"):
                raise ValueError("An existing trip_id is required for removing items or setting room guests")
        if config.operation == "search_cars":
            pickup = payload["pick_up"]
            if sum(pickup.get(k) is not None for k in ("airport_code", "place", "geo")) != 1:
                raise ValueError("Pick-up needs exactly one airport_code, place, or geo")
            if not payload.get("drop_off_date_time") and not payload.get("drop_off", {}).get("date_time"):
                raise ValueError("Provide the drop-off date and time")
        kwargs = {"params": payload} if method == "GET" else ({"json": payload} if payload else {})
        # Exactly one request per operation; never retry checkout or servicing writes.
        async with guarded_async_client() as client:
            response = await client.request(method, BASE_URL + route,
                headers={"X-API-Key": credential.api_key, "Accept": "application/json"},
                timeout=90.0, follow_redirects=False, **kwargs)
        try:
            body = response.json()
        except ValueError:
            raise ValueError(f"Jinko returned a non-JSON response (HTTP {response.status_code})") from None
        body = _redact(body, credential.api_key)
        if not isinstance(body, dict):
            raise ValueError("Jinko returned an unexpected response envelope")
        if not 200 <= response.status_code < 300 or body.get("error"):
            return {"status": "error", "http_status": response.status_code,
                "error": body.get("error") or f"Jinko refused the request (HTTP {response.status_code})",
                "data": body}
        return {"status": "success", "http_status": response.status_code, "data": body,
            "retry_after": response.headers.get("Retry-After")}
