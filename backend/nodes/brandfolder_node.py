"""Brandfolder assets and organization resources, authenticated with a personal API key.

Operations follow the published v4 contract; webhook subscriptions use its v1
server override. Deliveries contain identifiers, not asset content or an actor.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

DOCS = "https://developers.smartsheet.com/api/brandfolder/openapi/webhooks"
EVENTS = ("asset.create", "asset.update", "asset.delete")


class BrandfolderAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Brandfolder API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://brandfolder.com/profile#integrations",
        "x-credential-instructions": "Copy your API key from Profile → Integrations in Brandfolder. Paste only the key. Requests use your Brandfolder permissions.",
    })
    credential_type: Literal["brandfolder_api_key"] = Field("brandfolder_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not isinstance(value, str) or not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


ID = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=1000)]


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    category: str
    required: tuple[str, ...] = ()
    query: tuple[str, ...] = ()
    attributes: tuple[str, ...] = ()
    many: bool = False


PAGE = ("page", "per", "search", "fields", "include")
ASSET_FIELDS = ("name", "description", "approved", "availability_start", "availability_end", "thumbnail_url")
OPERATIONS = {
    "list_brandfolders": Operation("GET", "/brandfolders", "Brandfolders", query=("search", "fields", "include"), many=True),
    "get_brandfolder": Operation("GET", "/brandfolders/{brandfolder_id}", "Brandfolders", query=("fields", "include")),
    "list_collections": Operation("GET", "/brandfolders/{brandfolder_id}/collections", "Collections", query=("fields", "include"), many=True),
    "get_collection": Operation("GET", "/collections/{collection_id}", "Collections", query=("fields", "include")),
    "create_collection": Operation("POST", "/brandfolders/{brandfolder_id}/collections", "Collections", required=("name",), attributes=("name", "tagline")),
    "delete_collection": Operation("DELETE", "/collections/{collection_id}", "Collections"),
    "list_sections": Operation("GET", "/brandfolders/{brandfolder_id}/sections", "Sections", query=("include",), many=True),
    "get_section": Operation("GET", "/sections/{section_id}", "Sections", query=("include",)),
    "create_section": Operation("POST", "/brandfolders/{brandfolder_id}/sections", "Sections", required=("name", "default_asset_type"), attributes=("name", "default_asset_type", "position")),
    "list_assets": Operation("GET", "/brandfolders/{brandfolder_id}/assets", "Assets", query=PAGE, many=True),
    "list_collection_assets": Operation("GET", "/collections/{collection_id}/assets", "Assets", query=PAGE, many=True),
    "get_asset": Operation("GET", "/assets/{asset_id}", "Assets", query=("fields", "include")),
    "create_asset": Operation("POST", "/brandfolders/{brandfolder_id}/assets", "Assets", required=("name", "section_key"), attributes=ASSET_FIELDS + ("attachment_url", "attachment_filename"), many=True),
    "update_asset": Operation("PUT", "/assets/{asset_id}", "Assets", required=("name",), attributes=ASSET_FIELDS),
    "delete_asset": Operation("DELETE", "/assets/{asset_id}", "Assets"),
    "list_asset_tags": Operation("GET", "/assets/{asset_id}/tags", "Tags", many=True),
    "add_asset_tags": Operation("POST", "/assets/{asset_id}/tags", "Tags", required=("tags_json",), many=True),
    "list_tags": Operation("GET", "/brandfolders/{brandfolder_id}/tags", "Tags", many=True),
    "list_custom_field_keys": Operation("GET", "/brandfolders/{brandfolder_id}/custom_field_keys", "Custom Fields", many=True),
    "list_asset_custom_fields": Operation("GET", "/assets/{asset_id}/custom_field_values", "Custom Fields", query=("include",), many=True),
    "list_labels": Operation("GET", "/brandfolders/{brandfolder_id}/labels", "Labels", many=True),
    "get_label": Operation("GET", "/labels/{label_id}", "Labels"),
    "create_label": Operation("POST", "/brandfolders/{brandfolder_id}/labels", "Labels", required=("name",), attributes=("name", "parent_key")),
}


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def structured_values(cls, value, info):
        if value is None:
            return value
        if info.field_name == "tags_json":
            try:
                tags = json.loads(value)
            except (TypeError, ValueError):
                raise ValueError('Use a JSON array of tag names, e.g. ["product"]') from None
            if not isinstance(tags, list) or not 1 <= len(tags) <= 100 or any(not isinstance(t, str) or not t.strip() or len(t) > 1000 for t in tags):
                raise ValueError("Provide 1 to 100 nonempty tag names")
        if info.field_name in {"attachment_url", "thumbnail_url"}:
            from urllib.parse import urlsplit
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Use a public HTTP or HTTPS file URL without credentials")
        return value


def _field(name, required):
    kind: Any = ID if name.endswith("_id") or name.endswith("_key") else Text
    kwargs: dict[str, Any] = {}
    if name == "page":
        kind = int
        kwargs = {"ge": 1}
    elif name == "per":
        kind = int
        kwargs = {"ge": 1, "le": 3000}
    elif name == "position":
        kind = int
        kwargs = {"ge": 0}
    elif name == "approved":
        kind = bool
    elif name == "description":
        kind = Annotated[str, Field(max_length=100000)]
    elif name == "default_asset_type":
        kind = Literal["GenericFile", "Color", "Font", "ExternalMedium", "Person", "Press", "Text"]
    elif name in {"availability_start", "availability_end"}:
        from datetime import datetime
        kind = datetime
    elif name == "tags_json":
        kind = Annotated[str, Field(max_length=100000)]
        kwargs["json_schema_extra"] = {"ui:widget": "code_editor", "x-code-language": "json"}
    if name == "brandfolder_id":
        kwargs["json_schema_extra"] = {"x-dynamic-options": {"field_name": name, "allow_custom": True, "searchable": True}}
    return (kind if required else Optional[kind], Field(... if required else None, title=name.replace("_", " ").title().replace(" Id", " ID").replace(" Json", " JSON"), **kwargs))


def _make_config(name, spec):
    ids = re.findall(r"{(\w+)}", spec.path)
    fields = {key: _field(key, key in spec.required or key in ids) for key in dict.fromkeys((*ids, *spec.required, *spec.query, *spec.attributes))}
    if name == "get_collection":
        fields["fields"] = (Optional[Literal["asset_count"]], Field(None, title="Fields"))
    title = name.replace("_", " ").title()
    return create_model("Brandfolder" + title.replace(" ", "") + "Config", __base__=_Input, __module__=__name__,
        operation=(Literal[name], Field(name, title=title, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": title, "x-category": spec.category, "x-is-trigger": False})), **fields)


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class BrandfolderOnAssetEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_asset_event"] = Field("on_asset_event", title="On Asset Event", json_schema_extra={
        "const": "on_asset_event", "ui:hidden": True, "x-display-name": "On Asset Event", "x-category": "Triggers", "x-is-trigger": True})
    brandfolder_id: ID = Field(..., title="Brandfolder", json_schema_extra={"x-dynamic-options": {"field_name": "brandfolder_id", "allow_custom": True, "searchable": True}})
    event_type: Literal[*EVENTS] = Field("asset.create", title="Event Type", description="Created, updated (including ready for use), or deleted. Deliveries contain IDs, not asset content. Brandfolder does not document delivery signatures.")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


BrandfolderConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (BrandfolderOnAssetEventConfig,)], Field(discriminator="operation")]


class BrandfolderNodeConfig(NodeConfig[BrandfolderConfig, BrandfolderAPIKeyCredential]):
    pass


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class BrandfolderNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-brandfolder"
    connection_evidence = ConnectionEvidence(field="brandfolder_id", noun="Brandfolders")
    webhook_signing_secret_not_issued = True
    edit_examples = ["Find assets in my Brandfolder", "Create an asset from a file URL", "Tag this asset", "Start when a Brandfolder asset is updated"]

    @classmethod
    def get_config_model(cls):
        return BrandfolderNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None, version="v4"):
        key = BrandfolderAPIKeyCredential.model_validate(credential).api_key
        try:
            async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
                response = await client.request(method, f"https://brandfolder.com/api/{version}{path}",
                    headers={"Authorization": f"Bearer {key}", "Accept": "application/json", "Content-Type": "application/json"}, params=params, json=body)
        except httpx.HTTPError:
            raise ValueError("Brandfolder request could not be confirmed; inspect any write before retrying") from None
        if not 200 <= response.status_code < 300:
            try:
                detail = json.dumps(response.json(), ensure_ascii=False)
            except ValueError:
                detail = "Unexpected non-JSON response"
            raise ValueError(_redact(f"Brandfolder API error {response.status_code}: {detail[:4000]}", key))
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Brandfolder returned a non-JSON response; outcome could not be confirmed") from None
        if not isinstance(data, dict) or data.get("errors"):
            raise ValueError(_redact("Brandfolder returned an unexpected response: " + str(data)[:4000], key))
        return _redact(data, key)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Brandfolder API key")
        config = self.config.config
        name = config.operation
        if name == "on_asset_event":
            return self.no_event_output(name)
        spec = OPERATIONS[name]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = spec.path
        for key in re.findall(r"{(\w+)}", path):
            path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        params = {key: values[key] for key in spec.query if key in values}
        body = None
        if spec.method in {"POST", "PUT"}:
            attributes = {key: values[key] for key in spec.attributes if key in values and key not in {"attachment_url", "attachment_filename"}}
            if name == "add_asset_tags":
                attributes = [{"name": tag} for tag in json.loads(values["tags_json"])]
            if name == "create_asset":
                if values.get("attachment_filename") and not values.get("attachment_url"):
                    raise ValueError("Provide an attachment URL with the filename")
                if values.get("attachment_url"):
                    attributes["attachments"] = [{"url": values["attachment_url"], **({"filename": values["attachment_filename"]} if values.get("attachment_filename") else {})}]
                body = {"data": {"attributes": [attributes]}, "section_key": values["section_key"]}
            else:
                body = {"data": {"attributes": attributes}}
        result = await self._request(self.config.credentials.model_dump(), spec.method, path, params=params, body=body)
        if name == "create_collection":
            # This endpoint returns a bare Collection, unlike the other resource reads.
            if not isinstance(result.get("id"), str) or result.get("type") != "collections":
                raise ValueError("Brandfolder returned an unexpected collection")
            result = {"data": result}
        if spec.method != "DELETE" and not isinstance(result.get("data"), list if spec.many else dict):
            raise ValueError("Brandfolder returned an unexpected resource envelope")
        output = {"status": "success", "operation": name, **result}
        if spec.method == "DELETE":
            output["deletion_acknowledged"] = True
        await self.emit(output)
        return output

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        if field_name != "brandfolder_id":
            return []
        result = await cls._request(credential_data, "GET", "/brandfolders", params={"search": search} if search else None)
        rows = result.get("data")
        if not isinstance(rows, list):
            raise ValueError("Brandfolder returned an unexpected resource list")
        if not rows:
            # The contract explicitly says unauthorized requests can return an empty list.
            raise ValueError("Brandfolder returned no accessible Brandfolders; account access is unverified")
        return [{"value": row["id"], "label": row.get("attributes", {}).get("name") or row["id"]} for row in rows if isinstance(row, dict) and row.get("id")]

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {key: (config or {}).get(key) for key in ("brandfolder_id", "event_type")}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        parsed = BrandfolderOnAssetEventConfig.model_validate(config)
        result = await cls._request(credential, "POST", "/webhooks", version="v1", body={"data": {"attributes": {
            "event_type": parsed.event_type, "resource_key": parsed.brandfolder_id, "resource_type": "brandfolder", "callback_url": webhook_url}}})
        identifier = result.get("data", {}).get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("Brandfolder did not return a webhook ID")
        return {"external_webhook_id": identifier}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = (config or {}).get("external_webhook_id")
        if identifier and credential:
            await cls._request(credential, "DELETE", "/webhooks/" + quote(str(identifier), safe=""), version="v1")

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # The provider's documented callback has no signature header or secret.
        # https://developers.smartsheet.com/api/brandfolder/openapi/webhooks
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        data = output.get("data") if isinstance(output, dict) else None
        attributes = data.get("attributes") if isinstance(data, dict) else None
        if not isinstance(attributes, dict) or not attributes.get("key") or not attributes.get("event_type"):
            return None
        asset = attributes["key"]
        kind = attributes["event_type"]
        brandfolder = attributes.get("brandfolder_key")
        organization = attributes.get("organization_key")
        when = attributes.get("event_time")
        return {"text": f"Brandfolder {kind}: asset {asset}\nBrandfolder: {brandfolder}\nOrganization: {organization}\nAt: {when}\nBrandfolder's delivery identifies the change; it does not include the actor or asset content.\nTo inspect a created or updated asset, use get_asset with asset_id={asset}.",
            "title": f"Brandfolder {kind}: {asset}", "conversation_key": f"brandfolder:{brandfolder}:asset:{asset}"}
