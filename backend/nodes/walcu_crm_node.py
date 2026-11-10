"""Walcu CRM operations from the published OpenAPI 0.0.2 contract.

Dealer-scoped Basic credentials support CRM reads, writes and scheduled change
polling without introducing provider-specific platform registration code.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

CONTRACT = "https://api.crm.walcu.com/.well-known/service-desc"
TYPE = "walcu_crm_basic"
SEGMENT = r"^[A-Za-z0-9_-]+$"
RECORD_ID = r"^[A-Fa-f0-9]{24}$"


class WalcuCRMBasicCredential(BaseModel):
    model_config = ConfigDict(title="Walcu CRM Basic Auth", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": CONTRACT,
            "x-credential-instructions": "Enter your Walcu API username, API password and dealer ID. The API uses HTTP Basic authentication; these are the API credentials supplied for your dealer account."})
    credential_type: Literal["walcu_crm_basic"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, max_length=4096, title="API username")
    password: str = Field(..., min_length=1, max_length=4096, title="API password", repr=False,
                          json_schema_extra={"ui:widget": "password"})
    dealer_id: str = Field(..., min_length=1, max_length=128, pattern=SEGMENT, title="Dealer ID")

    @field_validator("username", "password")
    @classmethod
    def no_controls(cls, value):
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("API credentials must not contain control characters")
        return value

    @field_validator("username")
    @classmethod
    def basic_username(cls, value):
        if ":" in value:
            raise ValueError("A Basic authentication username cannot contain a colon")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def omit_canvas_bookkeeping(cls, value):
        # DynamicOptionsField stores the display label beside the selected ID.
        # These platform fields are not provider inputs and must not be sent.
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k not in {"client_id__label", "credentialIds"}}
        return value


class _Page(_Input):
    skip: int = Field(0, ge=0, title="Skip")
    limit: int = Field(100, ge=1, le=1000, title="Page size")
    search: str | None = Field(None, title="Search", description="Walcu WQL search expression.")
    sort: str | None = Field(None, title="Sort", description="Walcu sort expression, for example updated_at.")


class WalcuPatch(_Input):
    """One RFC 6902 change accepted by Walcu's jsonpatch schema."""
    op: Literal["replace", "add", "remove", "copy", "move", "test"] = "replace"
    path: str = Field(..., min_length=1, pattern=r"^/", description="JSON Pointer to the field to change.")
    value: Any = Field(..., description="Value for add, replace or test; use null for remove, copy or move.")
    from_path: str | None = Field(None, pattern=r"^/", title="From", description="Source JSON Pointer for copy or move.")

    @model_validator(mode="after")
    def source_required(self):
        if self.op in {"copy", "move"} and self.from_path is None:
            raise ValueError("Copy and move require a source JSON Pointer")
        return self


class _Update(_Input):
    patch: list[WalcuPatch] = Field(..., min_length=1, title="Changes", description="JSON Patch changes to apply to this record.")


def _text(title, *, required=False):
    extra = {"x-dynamic-options": {"field_name": "client_id", "searchable": True,
        "allow_custom": True}} if title == "Client ID" else None
    return (str if required else str | None, Field(... if required else None, title=title, json_schema_extra=extra))


CREATE_FIELDS = {
    "client": {"first_name": _text("First name"), "last_name": _text("Last name"),
               "email": _text("Email"), "phone": _text("Phone")},
    "salelead": {"client_id": _text("Client ID", required=True), "inquiry": _text("Inquiry"),
                 "location": _text("Location"), "type": _text("Type")},
    "task": {"client_id": _text("Client ID", required=True), "description": _text("Description", required=True),
             "lead_id": _text("Lead ID"), "lead_type": (Literal["appraisallead", "salelead", "aftersalelead"] | None, None)},
    "note": {"client_id": _text("Client ID", required=True), "content": _text("Content", required=True),
             "lead_id": _text("Lead ID"), "lead_type": (Literal["appraisallead", "salelead", "aftersalelead"] | None, None)},
    "car": {"make": _text("Make"), "model": _text("Model"), "vin": _text("VIN"),
            "license_plate": _text("License plate"), "description": _text("Description"),
            "mileage": (int | None, Field(None, ge=0)), "published": (bool | None, None)},
    "date": {"title": _text("Title", required=True), "client_id": _text("Client ID"),
             "start_date": (date, Field(..., title="Start date")), "duration": (float | None, Field(None, ge=0)),
             "event_type": (Literal["test-drive", "vehicle-delivery"] | None, None)},
}
RESOURCES = {"client": ("clients", "Client"), "salelead": ("saleleads", "Sales Lead"),
             "task": ("tasks", "Task"), "note": ("notes", "Note"),
             "car": ("cars", "Vehicle"), "date": ("dates", "Appointment")}
OPERATIONS = {}
CONFIG_MODELS = {}
for _resource, (_plural, _label) in RESOURCES.items():
    for _action in (("list", "create") if _resource == "date" else ("list", "get", "create", "update")):
        _name = f"{_action}_{_plural if _action == 'list' else _resource}"
        _method = {"list": "GET", "get": "GET", "create": "POST", "update": "PATCH"}[_action]
        _path = "/" + _plural + ("/{" + _resource + "_id}" if _action in {"get", "update"} else "")
        OPERATIONS[_name] = (_method, _path, _resource, _action)
        _fields = CREATE_FIELDS[_resource].copy() if _action == "create" else {}
        if _action in {"get", "update"}:
            _fields[_resource + "_id"] = (str, Field(..., min_length=24, max_length=24, pattern=RECORD_ID, title=_label + " ID",
                json_schema_extra={"x-dynamic-options": {"field_name": "client_id", "searchable": True, "allow_custom": True}} if _resource == "client" else None))
        _model = create_model("Walcu" + "".join(p.title() for p in _name.split("_")) + "Config",
            __module__=__name__, __base__=_Page if _action == "list" else _Update if _action == "update" else _Input,
            operation=(Literal[_name], Field(_name, title=f"{_action.title()} {_label}{'s' if _action == 'list' else ''}",
                json_schema_extra={"ui:hidden": True, "x-category": _label + "s"})), **_fields)
        CONFIG_MODELS[_name] = _model
        globals()[_model.__name__] = _model


class WalcuOnClientChangedConfig(PollTriggerConfigBase):
    operation: Literal["on_client_changed"] = Field("on_client_changed", title="New or Updated Client",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    search: str | None = Field(None, title="Search", description="Optional Walcu WQL filter.")


class WalcuOnSaleleadChangedConfig(PollTriggerConfigBase):
    operation: Literal["on_salelead_changed"] = Field("on_salelead_changed", title="New or Updated Sales Lead",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    search: str | None = Field(None, title="Search", description="Optional Walcu WQL filter.")


TRIGGERS = {"on_client_changed": "client", "on_salelead_changed": "salelead"}
WalcuConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (WalcuOnClientChangedConfig, WalcuOnSaleleadChangedConfig)], Field(discriminator="operation")]


class WalcuCRMNodeConfig(NodeConfig[WalcuConfig, WalcuCRMBasicCredential]):
    pass


class WalcuCRMNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-walcu-crm"
    connection_evidence = ConnectionEvidence(field="client_id", operation="list_clients", noun="clients", label_keys=("label", "_id"))

    @classmethod
    def get_config_model(cls):
        return WalcuCRMNodeConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name != "client_id":
            return {"options": []}
        credential = WalcuCRMBasicCredential.model_validate(credential_data)
        skip = int(page_token or 0)
        if skip < 0:
            raise ValueError("Client page offset must be nonnegative")
        params = {"skip": skip, "limit": 100}
        if search:
            params["search"] = search
        data, more = await cls._request(credential, "GET", "/clients", params=params)
        if not isinstance(data, list):
            raise ValueError("Walcu client response must be an array")
        options = []
        for row in data:
            if not isinstance(row, dict) or not row.get("_id"):
                continue
            contact = row.get("primary_contact") or {}
            name = contact.get("name") or {}
            label = name.get("raw_name") or " ".join(filter(None, [name.get("first_name"), name.get("last_name")]))
            options.append({"value": row["_id"], "label": label or row["_id"]})
        if more and not data:
            raise ValueError("Walcu returned an empty client page with continuation")
        return {"options": options, "next_page_token": str(skip + len(data)) if more else None}

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        url = "https://api.crm.walcu.com/dealers/" + quote(credential.dealer_id, safe="") + path
        async with guarded_async_client(timeout=40, follow_redirects=False) as client:
            response = await client.request(method, url, params=params, json=body,
                auth=httpx.BasicAuth(credential.username, credential.password), headers={"Accept": "application/json"})
        if response.is_error or response.is_redirect:
            # Preserve provider rejection text for the manual-connect evidence seam.
            raise ValueError(f"Walcu CRM HTTP {response.status_code}: {response.text[:2000]}")
        return response.json(), response.headers.get("mapp-has-more", "").lower() == "true"

    async def _poll(self, credential, config):
        resource = TRIGGERS[config.operation]
        plural = RESOURCES[resource][0]
        rows = []
        for skip in range(0, 10000, 100):
            params = {"skip": skip, "limit": 100, "sort": "updated_at"}
            if config.search:
                params["search"] = config.search
            data, more = await self._request(credential, "GET", "/" + plural, params=params)
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError("Walcu list response must be an array of records")
            rows.extend(data)
            if not more:
                break
            if not data:
                raise ValueError("Walcu returned an empty page with more records pending")
        else:
            raise ValueError("More than 10,000 records in this poll scope; narrow the search")
        # Both fields are published on client and salelead schemas. Include the
        # record content because the contract types updated_at as a date: two
        # edits on the same date must still produce distinct versions.
        for row in rows:
            if not row.get("_id") or not row.get("updated_at"):
                raise ValueError("Walcu polling requires record _id and updated_at")
        fresh = await self._filter_unseen(rows, lambda row: json.dumps([row["_id"], row["updated_at"],
            hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()]))
        return {"status": "success", "operation": config.operation, "resource": resource,
                "items": fresh, "new_item_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_item_count")) if config.get("operation") in TRIGGERS else True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("operation") not in TRIGGERS:
            return super().resolve_agent_event(output)
        rows = output.get("items", [])
        if not rows:
            return None
        lines = []
        for row in rows[:10]:
            if output["resource"] == "client":
                name = (row.get("primary_contact") or {}).get("name") or {}
                content = name.get("raw_name") or " ".join(filter(None, [name.get("first_name"), name.get("last_name")])) or "Client"
            else:
                content = row.get("inquiry") or "Sales lead"
            lines.append(f"- {content} (id {row.get('_id')}, client {row.get('client_id') if output['resource'] == 'salelead' else row.get('_id')}, dealer {row.get('dealer_id')}, updated {row.get('updated_at')})")
        return {"text": f"Walcu CRM: {len(rows)} new or updated {RESOURCES[output['resource']][1].lower()} record(s):\n" + "\n".join(lines),
                "conversation_key": None}

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect Walcu CRM API credentials")
        config = self.config.config
        if config.operation in TRIGGERS:
            return await self._poll(credential, config)
        method, path, resource, action = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if action in {"get", "update"}:
            field = resource + "_id"
            path = path.replace("{" + field + "}", quote(values.pop(field), safe=""))
        params, body = None, None
        if action == "list":
            params = values
        elif action == "create":
            body = {"dealer_id": credential.dealer_id, **values}
            if resource == "client":
                contact = {"name": {k: body.pop(k) for k in ("first_name", "last_name") if k in body}}
                for field, plural in (("email", "emails"), ("phone", "phones")):
                    if field in body:
                        contact[plural] = [body.pop(field)]
                body["primary_contact"] = contact
        elif action == "update":
            body = []
            for patch in config.patch:
                item = {"op": patch.op, "path": patch.path}
                if patch.op in {"add", "replace", "test"}:
                    item["value"] = patch.value
                if patch.op in {"copy", "move"}:
                    item["from"] = patch.from_path
                body.append(item)
        data, more = await self._request(credential, method, path, params=params, body=body)
        if action == "list":
            if not isinstance(data, list):
                raise ValueError("Walcu list response must be an array")
            return {"status": "success", "operation": config.operation, "items": data,
                    "has_more": more, "next_skip": config.skip + len(data) if more else None}
        # getone-* schemas return arrays; preserve the provider's response.
        return {"status": "success", "operation": config.operation, "data": data}
