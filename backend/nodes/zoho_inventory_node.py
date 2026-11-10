"""Zoho Inventory v1 workflow actions from Zoho's published OpenAPI archive."""

from __future__ import annotations

import base64
import binascii
import json
import hashlib
import re
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.binary_output import BinaryOutput
from nodes.scopes.zoho_inventory import ZOHO_INVENTORY_SCOPES
from nodes.zoho_inventory_operations import OPERATIONS
from nodes.oauth.zoho_inventory_oauth import OAUTH_PROVIDER, validate_api_domain
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client


class ZohoInventoryOAuthCredential(BaseModel):
    credential_type: Literal["zoho_inventory_oauth"] = Field(
        "zoho_inventory_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: str = Field(..., title="Token Expiry")
    api_domain: str = Field(..., title="Regional API Domain")
    accounts: str = Field(..., title="Data Center")
    accounts_server: str = Field(..., title="Regional Accounts Server")
    organization_id: Optional[str] = Field(None, title="Default Organization ID")
    organization_name: Optional[str] = Field(None, title="Default Organization")

    model_config = ConfigDict(json_schema_extra={
        "title": "Zoho Inventory OAuth",
        "x-credential-type": "oauth",
        "x-oauth-provider": "zoho_inventory",
        "x-oauth-scopes": ZOHO_INVENTORY_SCOPES.declared_scopes(),
        "x-credential-url": "https://api-console.zoho.com/",
    })


_JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


def _field_name(prefix: str, raw: str) -> str:
    return prefix + "_" + re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()


def _make_config(op: dict[str, Any]) -> type[BaseModel]:
    name = op["name"]
    fields: dict[str, tuple[Any, Any]] = {
        "operation": (Literal[name], Field(
            name, title=op["label"], description=op["description"],
            json_schema_extra={"const": name, "ui:hidden": True,
                               "x-category": op["category"], "x-display-name": op["label"],
                               "x-is-trigger": False},
        )),
    }
    if op["requires_org_id"]:
        fields["organization_id"] = (Optional[str], Field(
            None, title="Organization ID", description="Uses the connected default organization when blank."))
    for raw in op["path_params"]:
        key = _field_name("path", raw)
        optional = raw == "organization_id"
        fields[key] = (Optional[str] if optional else str, Field(
            None if optional else ..., title=raw.replace("_", " ").title(),
            description="Uses the connected default organization when blank." if optional else None))
    for raw in op["required_query"]:
        key = _field_name("query", raw)
        fields[key] = (str, Field(..., title=raw.replace("_", " ").title()))
    for raw in op["required_headers"]:
        key = _field_name("header", raw)
        fields[key] = (str, Field(..., title=raw.replace("-", " ").title()))
    fields["query_json"] = (Optional[str], Field(
        None, title="Other Query Parameters (JSON)",
        description="Filters, pagination, and other optional API query parameters.",
        json_schema_extra=_JSON_EDITOR))
    if op["body_mime"] == "application/json":
        body_required = op["body_required"]
        required_keys = op["body_required_fields"]
        description = "Object or array matching Zoho Inventory's API reference for this action."
        if required_keys:
            description += " Required keys: " + ", ".join(required_keys) + "."
        fields["body_json"] = (str if body_required else Optional[str], Field(
            ... if body_required else None, title="Request Body (JSON)",
            description=description,
            json_schema_extra=_JSON_EDITOR))
    elif op["body_mime"] == "multipart/form-data":
        fields["file_base64"] = (str, Field(..., title="Attachment (Base64)",
                                            description="Base64 encoded file, maximum 10 MB."))
        fields["file_name"] = (str, Field(..., title="File Name"))
        fields["file_content_type"] = (str, Field("application/octet-stream", title="Content Type"))
        fields["form_json"] = (Optional[str], Field(None, title="Other Form Fields (JSON)",
                                                json_schema_extra=_JSON_EDITOR))
    return create_model(
        "ZohoInventory" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__, **fields,
    )


CONFIG_MODELS = {name: _make_config(op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
# Zoho documents webhook setup in its UI, but exposes no registration route in
# the Inventory v1 API. Poll the documented lists, including every page.
# https://www.zoho.com/us/inventory/help/settings/automation.html
POLL_RESOURCES = {
    "on_item_created_or_updated": ("list_items", "items", "item_id", "name", "Items"),
    "on_sales_order_created_or_updated": ("list_sales_orders", "salesorders", "salesorder_id", "salesorder_number", "Sales Orders"),
    "on_purchase_order_created_or_updated": ("list_purchase_orders", "purchaseorders", "purchaseorder_id", "purchaseorder_number", "Purchase Orders"),
    "on_invoice_created_or_updated": ("list_invoices", "invoices", "invoice_id", "invoice_number", "Invoices"),
}
POLL_MODELS = {}
for _name, (_, _, _, _, _label) in POLL_RESOURCES.items():
    _title = "On New or Updated " + _label
    POLL_MODELS[_name] = create_model(
        "ZohoInventory" + "".join(part.title() for part in _name.split("_")) + "Config",
        __base__=PollTriggerConfigBase, __module__=__name__,
        operation=(Literal[_name], Field(_name, title=_title, json_schema_extra={
            "const": _name, "ui:hidden": True, "x-is-trigger": True,
            "x-category": "Triggers", "x-display-name": _title,
        })),
        organization_id=(str, Field(..., min_length=1, title="Organization ID")),
    )
globals().update({model.__name__: model for model in POLL_MODELS.values()})
ZohoInventoryConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + tuple(POLL_MODELS.values())], Discriminator("operation")]


class ZohoInventoryNodeConfig(NodeConfig[ZohoInventoryConfig, ZohoInventoryOAuthCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _parse_json(raw: Optional[str], label: str, *, allow_array: bool = False) -> Any:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain valid JSON") from exc
    if not isinstance(value, (dict, list) if allow_array else dict):
        raise ValueError(f"{label} must be a JSON {'object or array' if allow_array else 'object'}")
    return value


class ZohoInventoryNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-zoho-inventory"
    scope_registry = ZOHO_INVENTORY_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_organizations", noun="organizations")
    edit_examples = [
        "List Zoho Inventory customers", "Create an invoice in Zoho Inventory",
        "Record a customer payment", "Find overdue invoices",
    ]

    @classmethod
    def get_config_model(cls):
        return ZohoInventoryNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        if not credential_data:
            return credential_data
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=OAUTH_PROVIDER.bind_refresh(credential_data),
            additional_token_fields=OAUTH_PROVIDER.credential_fields, provider="zoho_inventory")

    @staticmethod
    async def _request(credential: dict, name: str, values: dict[str, Any]) -> dict[str, Any]:
        op = OPERATIONS[name]
        path = op["path"]
        for raw in op["path_params"]:
            key = _field_name("path", raw)
            value = values.pop(key, None) or (credential.get("organization_id") if raw == "organization_id" else None)
            if not value or str(value) in {".", ".."} or "/" in str(value) or "\\" in str(value):
                raise ValueError(f"{raw} must be a valid identifier")
            path = path.replace("{" + raw + "}", quote(str(value), safe=""))
        params = _parse_json(values.pop("query_json", None), "Query Parameters") or {}
        if op["requires_org_id"]:
            org_id = values.pop("organization_id", None) or credential.get("organization_id")
            if not org_id:
                raise ValueError("Select a Zoho Inventory organization before running this action")
            params["organization_id"] = str(org_id)
        for raw in op["required_query"]:
            params[raw] = values.pop(_field_name("query", raw))
        headers = {"Authorization": f"Zoho-oauthtoken {credential['access_token']}",
                   "Accept": "application/json"}
        for raw in op["required_headers"]:
            headers[raw] = values.pop(_field_name("header", raw))
        request: dict[str, Any] = {}
        if op["body_mime"] == "application/json":
            body = _parse_json(values.pop("body_json", None), "Request Body", allow_array=True)
            if op["body_required"] and body is None:
                raise ValueError("Request Body is required for this action")
            required_keys = op["body_required_fields"]
            if required_keys:
                missing = [key for key in required_keys
                           if not isinstance(body, dict) or key not in body]
                if missing:
                    raise ValueError("Request Body is missing required keys: " + ", ".join(missing))
            if body is not None:
                request["json"] = body
        elif op["body_mime"] == "multipart/form-data":
            try:
                content = base64.b64decode(values.pop("file_base64"), validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("Attachment must be valid Base64") from exc
            if len(content) > 10 * 1024 * 1024:
                raise ValueError("Attachment exceeds the 10 MB limit")
            form = _parse_json(values.pop("form_json", None), "Other Form Fields") or {}
            request["data"] = {key: str(value) for key, value in form.items()}
            request["files"] = {op["file_field"]: (values.pop("file_name"), content,
                                                   values.pop("file_content_type"))}
        base = validate_api_domain(credential["api_domain"])
        started = time.monotonic()
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(op["method"], base + "/inventory/v1" + path,
                                            params=params or None, headers=headers, **request)
        content_type = response.headers.get("content-type", "").split(";", 1)[0]
        if content_type in {"application/pdf", "application/octet-stream"} or content_type.startswith("image/"):
            data: Any = BinaryOutput(response.content, content_type=content_type, filename=name)
        elif not response.content:
            data = {}
        else:
            try:
                data = response.json()
            except ValueError:
                data = {"text": response.text[:1000]}
        if response.is_error or response.is_redirect or (isinstance(data, dict) and data.get("code") not in (None, 0)):
            message = data.get("message") if isinstance(data, dict) else None
            raise ValueError(f"Zoho Inventory API error {response.status_code}: {message or 'request failed'}")
        return {"status": "success", "operation": name, "status_code": response.status_code,
                "data": data, "timing_ms": {"api_request": round((time.monotonic()-started)*1000, 2)}}

    async def _poll_records(self, credential: dict, config) -> dict[str, Any]:
        list_operation, list_key, id_key, _, _ = POLL_RESOURCES[config.operation]
        records = []
        for page in range(1, 21):
            result = await self._request(credential, list_operation, {
                "organization_id": config.organization_id,
                "query_json": json.dumps({"page": page, "per_page": 200}),
            })
            payload = result["data"]
            if not isinstance(payload, dict) or not isinstance(payload.get(list_key), list):
                raise ValueError("Zoho Inventory did not return the documented resource list")
            batch = payload[list_key]
            if any(not isinstance(row, dict) or not row.get(id_key) for row in batch):
                raise ValueError("Zoho Inventory listed a record without its identifier")
            records.extend(batch)
            # An additional empty page also ends a list whose size is a multiple
            # of the page size; no unlisted pagination fields are assumed.
            if len(batch) < 200:
                break
        else:
            raise ValueError("Zoho Inventory poll exceeds 4,000 records; use a smaller organization")

        def version(row):
            # The list representations include the attributes users monitor.
            # Hash the documented representation to detect changes even for
            # endpoints whose list does not include last_modified_time.
            digest = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            return str(row[id_key]) + ":" + digest

        fresh = await self._filter_unseen(records, version)
        return {"operation": config.operation, "records": fresh, "record_count": len(fresh),
                "organization_id": config.organization_id}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("record_count")) if config.get("operation") in POLL_RESOURCES else True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("operation") not in POLL_RESOURCES:
            return super().resolve_agent_event(output)
        records = output.get("records")
        if not records:
            return None
        _, _, id_key, title_key, label = POLL_RESOURCES[output["operation"]]
        lines = [f"Zoho Inventory: {len(records)} new or updated {label.lower()}."]
        for row in records[:10]:
            lines.append(f"- {row.get(title_key) or row[id_key]} ({id_key}={row[id_key]})")
        if len(records) > 10:
            lines.append(f"- and {len(records) - 10} more")
        return {"text": "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, ZohoInventoryNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Zoho Inventory account before running this action")
        config = self.config.config
        self.scope_registry.require(config.operation)
        credential = self.config.credentials.model_dump()
        credential = await self.freshen_credential(credential, user_id=self.user_id,
                                      credential_id=(self.node_data or {}).get("credential_id"))
        if config.operation in POLL_RESOURCES:
            return await self._poll_records(credential, config)
        return await self._request(credential, config.operation,
                                   config.model_dump(exclude={"operation"}, exclude_none=True))
