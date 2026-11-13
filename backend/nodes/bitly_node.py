"""Bitly v4 link, group, analytics, QR, site and webhook workflow actions.

The guided actions cover common link workflows. The official endpoint catalogue
exposes advanced JSON actions without inventing a raw URL or HTTP method field.
"""

import json
import mimetypes
import re
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.bitly_operations import OPERATIONS
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.scopes.bitly import BITLY_SCOPES

BITLY_API_BASE = "https://api-ssl.bitly.com/v4"


def _operation(name: str, label: str, category: str, **extra: Any) -> Any:
    return Field(name, title=label, json_schema_extra={
        "const": name, "ui:hidden": True, "x-category": category,
        "x-display-name": label, "x-is-trigger": False, **extra,
    })


def _group_field() -> Any:
    return Field(..., title="Group", json_schema_extra={"x-dynamic-options": {
        "field_name": "group_guid", "placeholder": "Select a group…",
        "searchable": True, "allow_custom": True,
        "custom_placeholder": "Or paste group GUID",
    }})


class BitlyTokenCredential(BaseModel):
    """A generic access token generated in Bitly Settings → API."""
    credential_type: Literal["bitly_api_key"] = Field("bitly_api_key", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(json_schema_extra={
        "title": "Bitly Access Token",
        "x-credential-url": "https://app.bitly.com/settings/api",
    })


class BitlyOAuthCredential(BaseModel):
    """OAuth authorization-code access token. Bitly does not issue refresh tokens."""
    credential_type: Literal["bitly_oauth"] = Field("bitly_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", json_schema_extra={"ui:widget": "password"})
    login: Optional[str] = Field(None, title="Bitly Login")
    model_config = ConfigDict(json_schema_extra={
        "title": "Bitly OAuth", "x-credential-type": "oauth", "x-oauth-provider": "bitly",
        "x-oauth-scopes": BITLY_SCOPES.declared_scopes(),
        "x-credential-url": "https://app.bitly.com/settings/api",
    })


BitlyCredential = Union[BitlyOAuthCredential, BitlyTokenCredential]


class GetUser(BaseModel):
    operation: Literal["get_user"] = _operation("get_user", "Get Connected Account", "Account")


class ListGroups(BaseModel):
    operation: Literal["list_groups"] = _operation("list_groups", "List Groups", "Groups")


class GetGroup(BaseModel):
    operation: Literal["get_group"] = _operation("get_group", "Get Group", "Groups")
    group_guid: str = _group_field()


class ListBitlinks(BaseModel):
    operation: Literal["list_bitlinks"] = _operation("list_bitlinks", "List Bitlinks", "Bitlinks")
    group_guid: str = _group_field()
    size: int = Field(50, ge=1, le=100, title="Page Size")
    search_after: Optional[str] = Field(None, title="Next Page Cursor")
    query: Optional[str] = Field(None, title="Search Query")


class ShortenLink(BaseModel):
    operation: Literal["shorten_link"] = _operation("shorten_link", "Shorten Link", "Bitlinks", **{
        "x-creates-resource": True, "x-resource-type": "bitly_bitlink", "x-resource-id-path": "data.id",
    })
    long_url: str = Field(..., title="Destination URL")
    group_guid: Optional[str] = Field(None, title="Group GUID")
    domain: str = Field("bit.ly", title="Short Domain")
    force_new_link: bool = Field(False, title="Force New Link")


class CreateBitlink(BaseModel):
    operation: Literal["create_bitlink"] = _operation("create_bitlink", "Create Bitlink", "Bitlinks", **{
        "x-creates-resource": True, "x-resource-type": "bitly_bitlink", "x-resource-id-path": "data.id",
    })
    long_url: str = Field(..., title="Destination URL")
    group_guid: Optional[str] = Field(None, title="Group GUID")
    domain: str = Field("bit.ly", title="Short Domain")
    title: Optional[str] = Field(None, title="Title")
    tags_json: Optional[str] = Field(None, title="Tags JSON", description="JSON array of tag names.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    force_new_link: bool = Field(False, title="Force New Link")


class GetBitlink(BaseModel):
    operation: Literal["get_bitlink"] = _operation("get_bitlink", "Get Bitlink", "Bitlinks")
    bitlink: str = Field(..., title="Bitlink ID", description="Domain and hash, for example bit.ly/abc123.")


class UpdateBitlink(BaseModel):
    operation: Literal["update_bitlink"] = _operation("update_bitlink", "Update Bitlink", "Bitlinks")
    bitlink: str = Field(..., title="Bitlink ID")
    title: Optional[str] = Field(None, title="New Title")
    long_url: Optional[str] = Field(None, title="New Destination URL", description="Redirecting a link consumes an encode from the account's plan.")
    archived: Optional[bool] = Field(None, title="Archived")
    tags_json: Optional[str] = Field(None, title="Tags JSON", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


class DeleteBitlink(BaseModel):
    operation: Literal["delete_bitlink"] = _operation("delete_bitlink", "Delete Bitlink", "Bitlinks")
    bitlink: str = Field(..., title="Bitlink ID", description="Bitly permits deletion of an unedited hash Bitlink only.")


class ExpandLink(BaseModel):
    operation: Literal["expand_link"] = _operation("expand_link", "Expand Link", "Bitlinks")
    bitlink_id: str = Field(..., title="Bitlink ID")


class GetEngagements(BaseModel):
    operation: Literal["get_engagements"] = _operation("get_engagements", "Get Link Engagements", "Analytics")
    bitlink: str = Field(..., title="Bitlink ID")
    unit: Literal["day", "week", "month"] = Field("day", title="Time Unit")
    units: int = Field(30, ge=1, le=999, title="Number of Units")


class GetCountries(BaseModel):
    operation: Literal["get_countries"] = _operation("get_countries", "Get Link Countries", "Analytics")
    bitlink: str = Field(..., title="Bitlink ID")
    unit: Literal["day", "week", "month"] = Field("day", title="Time Unit")
    units: int = Field(30, ge=1, le=999, title="Number of Units")


class GetPlatformLimits(BaseModel):
    operation: Literal["get_platform_limits"] = _operation("get_platform_limits", "Get Usage and Limits", "Account")


def _generic_model(name: str, spec: dict[str, Any]) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {}
    for param in re.findall(r"\{([^}]+)\}", spec["path"]):
        fields[param] = (str, Field(..., title=param.replace("_", " ").title()))
    for param, typ in spec["required_query"]:
        pytype = {"integer": int, "number": float, "boolean": bool}.get(typ, str)
        fields[param] = (pytype, Field(..., title=param.replace("_", " ").title()))
    fields["query_json"] = (Optional[str], Field(None, title="Query Parameters JSON", description="Optional filtering, sorting and pagination as a JSON object.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))
    if spec["has_body"]:
        fields["body_json"] = (str if spec["body_required"] else Optional[str], Field(
            ... if spec["body_required"] else None, title="Request Body JSON",
            description=spec["description"] or "Bitly request body as JSON.",
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))
    return create_model(
        "Bitly" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__,
        operation=(Literal[name], _operation(name, spec["label"], spec["category"])),
        **fields,
    )


class BitlyOnEngagementConfig(WebhookTriggerConfigBase):
    operation: Literal["on_engagement"] = _operation(
        "on_engagement", "On Link Engagement", "Triggers", **{"x-is-trigger": True})
    organization_guid: str = Field(..., title="Organization GUID")
    group_guid: Optional[str] = Field(None, title="Group GUID")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", json_schema_extra={
        "ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


GENERIC_CONFIGS = {name: _generic_model(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in GENERIC_CONFIGS.values()})

BitlyConfig = Annotated[Union[tuple([
    GetUser, ListGroups, GetGroup, ListBitlinks, ShortenLink, CreateBitlink,
    GetBitlink, UpdateBitlink, DeleteBitlink, ExpandLink, GetEngagements,
    GetCountries, GetPlatformLimits, BitlyOnEngagementConfig, *GENERIC_CONFIGS.values(),
])], Discriminator("operation")]


class BitlyNodeConfig(NodeConfig[BitlyConfig, BitlyCredential]):
    pass


class BitlyNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Execute supported Bitly v4 operations with an OAuth or generic access token."""

    integration_type = "automation-bitly"
    credential_provider_labels = {"bitly": "Bitly Account"}
    scope_registry = BITLY_SCOPES

    connection_evidence = ConnectionEvidence(field="group_guid", noun="groups", identity_operation="get_user")
    edit_examples = ["Shorten a URL with Bitly", "List my Bitly links", "Get clicks for a Bitly link"]

    @classmethod
    def get_config_model(cls):
        return BitlyNodeConfig

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        parsed = BitlyOnEngagementConfig.model_validate(config or {})
        token = (credential or {}).get("access_token")
        if not token:
            raise ValueError("Connect Bitly before activating this trigger")
        body = {"organization_guid": parsed.organization_guid, "name": f"NoClick {node_id}",
                "event": "decodes", "url": webhook_url, "is_active": True}
        if parsed.group_guid:
            body["group_guid"] = parsed.group_guid
        data, _ = await cls._request(token, "POST", "/webhooks", body=body)
        if not isinstance(data, dict) or not data.get("guid"):
            raise ValueError("Bitly did not return a webhook GUID")
        return {"external_webhook_id": data["guid"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        guid = (config or {}).get("external_webhook_id")
        token = (credential or {}).get("access_token")
        if guid and token:
            await cls._request(token, "DELETE", f"/webhooks/{quote(str(guid), safe='')}")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {key: (config or {}).get(key) for key in ("organization_guid", "group_guid")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # No payload signature is documented. Bitly offers URL keys/basic auth
        # and OAuth client credentials; we use the platform's opaque delivery URL.
        # https://dev.bitly.com/docs/tutorials/create-a-webhook/#authentication
        return True

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if not isinstance(payload, dict) or payload.get("event_type") != "engagement":
            return {}
        if payload.get("organization_guid") != config.get("organization_guid"):
            return {}
        if config.get("group_guid") and payload.get("group_guid") != config["group_guid"]:
            return {}
        return {"status": "success", "operation": "on_engagement", "data": payload}

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") == "on_engagement":
            return (output.get("data") or {}).get("event_type") == "engagement"
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or not isinstance(output.get("data"), dict):
            return super().resolve_agent_event(output)
        event = output["data"]
        if event.get("event_type") != "engagement":
            return super().resolve_agent_event(output)
        return {"text": (
            f"Bitly link engagement: {event.get('bitlink')} → {event.get('url')}\n"
            f"Visitor in {event.get('country')} using {event.get('device_type')}; "
            f"referrer: {event.get('referrer')}; time: {event.get('datetime')}\n"
            f"Event {event.get('event_id')}; group {event.get('group_guid')}; "
            f"organization {event.get('organization_guid')}"), "conversation_key": None}

    @staticmethod
    async def _request(token: str, method: str, path: str, *, params=None, body=None) -> tuple[Any, float]:
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.request(
                method, BITLY_API_BASE + path, params={k: v for k, v in (params or {}).items() if v is not None},
                json=body, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        if response.is_error:
            try:
                payload = response.json()
                detail = payload.get("description") or payload.get("message") or payload.get("error")
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f"Bitly API error {response.status_code}: {detail or 'request failed'}")
        if not response.content:
            return {"ok": True}, elapsed
        if "json" in response.headers.get("content-type", "") or response.content[:1] in (b"{", b"["):
            return response.json(), elapsed
        content_type = response.headers.get("content-type", "application/octet-stream")
        name = path.rstrip("/").rsplit("/", 1)[-1] or "download"
        extension = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ""
        return {"content_type": content_type, "file": BinaryOutput(
            data=response.content, content_type=content_type, filename=f"bitly-{name}{extension}")}, elapsed

    @staticmethod
    def _object(raw: Optional[str], label: str) -> dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{label} must be a JSON object")
        return value

    @staticmethod
    def _array(raw: str, label: str) -> list[Any]:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} must be valid JSON") from exc
        if not isinstance(value, list):
            raise ValueError(f"{label} must be a JSON array")
        return value

    @classmethod
    async def load_field_options(cls, field_name: str, credential_data: dict, context=None, page_token=None, search=None) -> list[dict]:
        if field_name != "group_guid":
            return []
        payload, _ = await cls._request(credential_data["access_token"], "GET", "/groups")
        groups = payload.get("groups", []) if isinstance(payload, dict) else []
        term = (search or "").casefold()
        return [{"value": group["guid"], "label": group.get("name") or group["guid"]}
                for group in groups if group.get("guid") and term in (group.get("name") or group["guid"]).casefold()]

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, BitlyNodeConfig):
            raise ValueError("Bitly configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Bitly account or access token")
        op = self.config.config
        name = op.operation
        self.scope_registry.require(name)
        if isinstance(op, BitlyOnEngagementConfig):
            return {"status": "success", "operation": name, "data": inputs}
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        method, path, params, body = "GET", "", None, None
        if name in OPERATIONS:
            spec = OPERATIONS[name]
            method, path = spec["method"], spec["path"]
            params = self._object(values.pop("query_json", None), "Query Parameters JSON")
            for param, _ in spec["required_query"]:
                value = values.pop(param)
                params[param] = str(value).lower() if isinstance(value, bool) else value
            raw_body = values.pop("body_json", None)
            if raw_body is not None:
                try:
                    body = json.loads(raw_body)
                except json.JSONDecodeError as exc:
                    raise ValueError("Request Body JSON must be valid JSON") from exc
            for param in re.findall(r"\{([^}]+)\}", path):
                value = str(values.pop(param))
                path = path.replace("{" + param + "}", quote(value, safe=""))
        elif isinstance(op, GetUser):
            path = "/user"
        elif isinstance(op, ListGroups):
            path = "/groups"
        elif isinstance(op, GetGroup):
            path = f"/groups/{quote(op.group_guid, safe='')}"
        elif isinstance(op, ListBitlinks):
            path = f"/groups/{quote(op.group_guid, safe='')}/bitlinks"
            params = {"size": op.size, "search_after": op.search_after, "query": op.query}
        elif isinstance(op, ShortenLink):
            method, path = "POST", "/shorten"
            body = op.model_dump(exclude={"operation"}, exclude_none=True)
        elif isinstance(op, CreateBitlink):
            method, path = "POST", "/bitlinks"
            body = op.model_dump(exclude={"operation", "tags_json"}, exclude_none=True)
            if op.tags_json is not None:
                body["tags"] = self._array(op.tags_json, "Tags JSON")
        elif isinstance(op, (GetBitlink, UpdateBitlink, DeleteBitlink, GetEngagements, GetCountries)):
            path = f"/bitlinks/{quote(op.bitlink, safe='')}"
            if isinstance(op, UpdateBitlink):
                method = "PATCH"
                body = op.model_dump(exclude={"operation", "bitlink", "tags_json"}, exclude_none=True)
                if op.tags_json is not None:
                    body["tags"] = self._array(op.tags_json, "Tags JSON")
                if not body:
                    raise ValueError("Provide a field to update")
            elif isinstance(op, DeleteBitlink):
                method = "DELETE"
            elif isinstance(op, GetEngagements):
                path += "/engagements"
                params = {"unit": op.unit, "units": op.units}
            elif isinstance(op, GetCountries):
                path += "/countries"
                params = {"unit": op.unit, "units": op.units}
        elif isinstance(op, ExpandLink):
            method, path, body = "POST", "/expand", {"bitlink_id": op.bitlink_id}
        elif isinstance(op, GetPlatformLimits):
            path = "/user/platform_limits"
        else:
            raise ValueError(f"Unsupported Bitly operation: {name}")
        data, elapsed = await self._request(credential.access_token, method, path, params=params, body=body)
        return {"status": "success", "operation": name, "data": data,
                "timing_ms": {"api_request": elapsed}}
