"""Native Voluum REST metadata management and bounded aggregate reports.

Wire source: https://developers.voluum.com/ and its public /api/openapi.
Access-key sessions are not OAuth. Tokens exist only in one operation/picker;
they are never persisted, exported, returned, or automatically replayed.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import math
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

BASE = "https://api.voluum.com"
FAMILY = "voluum_access_key"
TYPE = "automation-voluum"
MAX_BYTES = 2 * 1024 * 1024
_private_request = ContextVar("voluum_private_http", default=False)


class _HTTPFilter(logging.Filter):
    def filter(self, record):
        if _private_request.get():
            record.msg, record.args = "Voluum HTTP exchange; details omitted", ()
            record.exc_info = record.exc_text = None
        return True


@contextmanager
def _private_http():
    # ContextVar confines projection to this coroutine; unrelated HTTP logs pass.
    filters = [(logging.getLogger(name), _HTTPFilter()) for name in (
        "httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2",
    )]
    token = _private_request.set(True)
    try:
        for logger, filter_ in filters:
            logger.addFilter(filter_)
        yield
    finally:
        for logger, filter_ in filters:
            logger.removeFilter(filter_)
        _private_request.reset(token)


def _uuid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Voluum requires a valid resource UUID") from None


def _text(value, maximum=240):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError("Voluum text field is invalid")
    return value


def _date(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Voluum requires a timezone-aware ISO timestamp") from None


def _url(value):
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Voluum destination must be an HTTP(S) URL without user information")
    if len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise ValueError("Voluum destination URL is invalid")
    # This value is submitted to Voluum, never fetched by NoClick.
    return value


class VoluumAccessKeyCredential(BaseModel):
    model_config = ConfigDict(title="Voluum Access Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://doc.voluum.com/article/voluum-api-docs",
        "x-credential-instructions": "In Voluum Settings → Security → Access keys, create or select a key for the intended user. Copy its Access ID and Access Key together. NoClick creates a temporary API session; this is not OAuth.",
        "x-credential-notice": "Permissions match this Voluum user's panel. Session success establishes access-key acceptance, not account identity.",
        "x-sensitive-auth-diagnostics": True,
    })
    credential_type: Literal["voluum_access_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    access_id: str = Field(..., title="Access ID", description="UUID from Voluum Settings → Security → Access keys")
    access_key: str = Field(..., title="Access Key", description="Access key for the same Voluum user", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_id")
    @classmethod
    def valid_id(cls, value):
        return _uuid(value)

    @field_validator("access_key")
    @classmethod
    def valid_key(cls, value):
        if not isinstance(value, str) or not 8 <= len(value) <= 8192 or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Voluum access key is invalid")
        return value


def _credential(data):
    if not isinstance(data, dict) or data.get("credential_type", FAMILY) != FAMILY:
        raise ValueError("This node requires a Voluum access-key credential")
    try:
        return VoluumAccessKeyCredential.model_validate(data).model_dump()
    except Exception:
        raise ValueError("Voluum access-key credential is invalid") from None


def _operation(name, label, category):
    return Field(name, title=label, json_schema_extra={"const": name, "ui:hidden": True,
        "x-display-name": label, "x-category": category, "x-is-trigger": False})


def _picker(field, label, parent=None):
    options = {"field_name": field, "placeholder": f"Select {label}", "searchable": True, "allow_custom": True}
    if parent:
        options["depends_on"] = parent
    return Field(..., title=label.title(), json_schema_extra={"format": "uuid", "x-dynamic-options": options})


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("workspace_id", "campaign_id", "offer_id", "lander_id", "traffic_source_id", check_fields=False)
    @classmethod
    def valid_resource_id(cls, value):
        return _uuid(value)

    @field_validator("destination_url", check_fields=False)
    @classmethod
    def valid_destination_url(cls, value):
        return _url(value)


class _List(_Config):
    workspace_id: str = _picker("workspace_id", "workspace")
    name: Optional[str] = Field(None, title="Name filter", max_length=240)
    include_archived: bool = Field(False, title="Include archived")
    limit: int = Field(25, ge=1, le=100, title="Page size")
    page_token: Optional[str] = Field(None, title="Continuation", max_length=4096)


class _Entity(_Config):
    workspace_id: str = _picker("workspace_id", "workspace")


class _Create(_Entity):
    name: str = Field(..., min_length=1, max_length=240, title="Name")
    tags: list[str] = Field(default_factory=list, max_length=30, title="Tags")


class _Update(_Entity):
    name: str = Field(..., min_length=1, max_length=240, title="New name")
    tags: Optional[list[str]] = Field(None, max_length=30, title="Replace tags", description="Omit to retain tags; an empty list clears tags")
    note: Optional[str] = Field(None, max_length=4000, title="New note")
    clear_note: bool = Field(False, title="Clear note")


class _TrafficCreate(_Entity):
    name: str = Field(..., min_length=1, max_length=240, title="Name")


class _TrafficUpdate(_TrafficCreate):
    note: Optional[str] = Field(None, max_length=4000, title="New note")
    clear_note: bool = Field(False, title="Clear note")


class VoluumTestConnectionConfig(_Config):
    operation: Literal["test_connection"] = _operation("test_connection", "Check Access-Key Session", "Connection")


class VoluumListWorkspacesConfig(_Config):
    operation: Literal["list_workspaces"] = _operation("list_workspaces", "List Workspaces", "Connection")


class VoluumListCampaignsConfig(_List):
    operation: Literal["list_campaigns"] = _operation("list_campaigns", "List Campaigns", "Campaigns")


class VoluumGetCampaignConfig(_Entity):
    operation: Literal["get_campaign"] = _operation("get_campaign", "Get Campaign Metadata", "Campaigns")
    campaign_id: str = _picker("campaign_id", "campaign", "workspace_id")


class VoluumCreateCampaignConfig(_Create):
    """Creates direct-URL configuration; does not buy/send traffic or guarantee an inactive draft."""
    operation: Literal["create_campaign"] = _operation("create_campaign", "Create Direct-URL Campaign", "Campaigns")
    traffic_source_id: str = _picker("traffic_source_id", "traffic source", "workspace_id")
    destination_url: str = Field(..., title="Destination URL", max_length=4096, json_schema_extra={"format": "uri"})


class VoluumUpdateCampaignConfig(_Update):
    operation: Literal["update_campaign_metadata"] = _operation("update_campaign_metadata", "Update Direct-URL Campaign Metadata", "Campaigns")
    campaign_id: str = _picker("campaign_id", "campaign", "workspace_id")


class VoluumArchiveCampaignConfig(_Entity):
    operation: Literal["archive_campaign"] = _operation("archive_campaign", "Archive Campaign", "Campaigns")
    campaign_id: str = _picker("campaign_id", "campaign", "workspace_id")


class VoluumListOffersConfig(_List):
    operation: Literal["list_offers"] = _operation("list_offers", "List Offers", "Offers")


class VoluumGetOfferConfig(_Entity):
    operation: Literal["get_offer"] = _operation("get_offer", "Get Offer Metadata", "Offers")
    offer_id: str = _picker("offer_id", "offer", "workspace_id")


class VoluumCreateOfferConfig(_Create):
    operation: Literal["create_offer"] = _operation("create_offer", "Create Offer", "Offers")
    destination_url: str = Field(..., title="Offer URL", max_length=4096, json_schema_extra={"format": "uri"})
    currency: str = Field("USD", title="Reporting currency", pattern="^[A-Z]{3}$")


class VoluumUpdateOfferConfig(_Update):
    operation: Literal["update_offer_metadata"] = _operation("update_offer_metadata", "Update Offer Metadata", "Offers")
    offer_id: str = _picker("offer_id", "offer", "workspace_id")


class VoluumArchiveOfferConfig(_Entity):
    operation: Literal["archive_offer"] = _operation("archive_offer", "Archive Offer", "Offers")
    offer_id: str = _picker("offer_id", "offer", "workspace_id")


class VoluumListLandersConfig(_List):
    operation: Literal["list_landers"] = _operation("list_landers", "List Landers", "Landers")


class VoluumGetLanderConfig(_Entity):
    operation: Literal["get_lander"] = _operation("get_lander", "Get Lander Metadata", "Landers")
    lander_id: str = _picker("lander_id", "lander", "workspace_id")


class VoluumCreateLanderConfig(_Create):
    operation: Literal["create_lander"] = _operation("create_lander", "Create Lander", "Landers")
    destination_url: str = Field(..., title="Lander URL", max_length=4096, json_schema_extra={"format": "uri"})
    lander_type: Literal["LANDER", "PRELANDER"] = Field("LANDER", title="Lander type")
    should_have_tracking_script: bool = Field(False, title="Track without redirects")


class VoluumUpdateLanderConfig(_Update):
    operation: Literal["update_lander_metadata"] = _operation("update_lander_metadata", "Update Lander Metadata", "Landers")
    lander_id: str = _picker("lander_id", "lander", "workspace_id")


class VoluumArchiveLanderConfig(_Entity):
    operation: Literal["archive_lander"] = _operation("archive_lander", "Archive Lander", "Landers")
    lander_id: str = _picker("lander_id", "lander", "workspace_id")


class VoluumListTrafficSourcesConfig(_List):
    operation: Literal["list_traffic_sources"] = _operation("list_traffic_sources", "List Traffic Sources", "Traffic Sources")


class VoluumGetTrafficSourceConfig(_Entity):
    operation: Literal["get_traffic_source"] = _operation("get_traffic_source", "Get Traffic Source Metadata", "Traffic Sources")
    traffic_source_id: str = _picker("traffic_source_id", "traffic source", "workspace_id")


class VoluumCreateTrafficSourceConfig(_TrafficCreate):
    operation: Literal["create_traffic_source"] = _operation("create_traffic_source", "Create Custom Traffic Source", "Traffic Sources")


class VoluumUpdateTrafficSourceConfig(_TrafficUpdate):
    operation: Literal["update_traffic_source_metadata"] = _operation("update_traffic_source_metadata", "Update Traffic Source Metadata", "Traffic Sources")
    traffic_source_id: str = _picker("traffic_source_id", "traffic source", "workspace_id")


class VoluumArchiveTrafficSourceConfig(_Entity):
    operation: Literal["archive_traffic_source"] = _operation("archive_traffic_source", "Archive Traffic Source", "Traffic Sources")
    traffic_source_id: str = _picker("traffic_source_id", "traffic source", "workspace_id")


class VoluumReportColumnsConfig(_Config):
    operation: Literal["list_report_columns"] = _operation("list_report_columns", "List Safe Report Columns", "Reports")


class VoluumCampaignReportConfig(_Entity):
    operation: Literal["get_campaign_report"] = _operation("get_campaign_report", "Get Campaign Aggregate Report", "Reports")
    campaign_id: str = _picker("campaign_id", "campaign", "workspace_id")
    from_time: str = Field(..., title="From (inclusive)", description="ISO timestamp on an hour boundary")
    to_time: str = Field(..., title="To (exclusive)", description="ISO timestamp on an hour boundary; range <=31 days")
    group_by: Literal["campaignId", "offerId", "landerId", "trafficSourceId", "day"] = Field("campaignId", title="Group by")
    currency: str = Field("USD", pattern="^[A-Z]{3}$", title="Reporting currency")
    conversion_time_mode: Literal["VISIT", "CONVERSION"] = Field("VISIT", title="Conversion attribution time")
    include: Literal["TRAFFIC", "ACTIVE", "ARCHIVED", "ALL"] = Field("TRAFFIC", title="Include")
    limit: int = Field(25, ge=1, le=100, title="Page size")
    page_token: Optional[str] = Field(None, max_length=4096, title="Continuation")


VoluumConfig = Annotated[Union[
    VoluumTestConnectionConfig, VoluumListWorkspacesConfig,
    VoluumListCampaignsConfig, VoluumGetCampaignConfig, VoluumCreateCampaignConfig,
    VoluumUpdateCampaignConfig, VoluumArchiveCampaignConfig,
    VoluumListOffersConfig, VoluumGetOfferConfig, VoluumCreateOfferConfig,
    VoluumUpdateOfferConfig, VoluumArchiveOfferConfig,
    VoluumListLandersConfig, VoluumGetLanderConfig, VoluumCreateLanderConfig,
    VoluumUpdateLanderConfig, VoluumArchiveLanderConfig,
    VoluumListTrafficSourcesConfig, VoluumGetTrafficSourceConfig, VoluumCreateTrafficSourceConfig,
    VoluumUpdateTrafficSourceConfig, VoluumArchiveTrafficSourceConfig,
    VoluumReportColumnsConfig, VoluumCampaignReportConfig,
], Field(discriminator="operation")]


class VoluumNodeConfig(NodeConfig[VoluumConfig, VoluumAccessKeyCredential]):
    pass


_KINDS = {
    "campaign": ("campaign", "campaigns", "campaign_id"),
    "offer": ("offer", "offers", "offer_id"),
    "lander": ("lander", "landers", "lander_id"),
    "traffic_source": ("traffic-source", "trafficSources", "traffic_source_id"),
}
_WRITE_FIELDS = {
    "campaign": ("basic", "costModel", "country", "directTracking", "directTrackingLanderId", "directTrackingOfferId", "namePostfix", "note", "pixelRedirectUrl", "postbackUrl", "preferredTrackingDomain", "redirectTarget", "smartRotation", "tags", "trafficSource", "trafficType", "workspace"),
    "offer": ("affiliateNetwork", "capConfiguration", "conversionTrackingMethod", "country", "currencyCode", "namePostfix", "note", "payout", "preferredTrackingDomain", "tags", "url", "vertical", "workspace"),
    "lander": ("country", "landerType", "namePostfix", "note", "numberOfOffers", "preferredTrackingDomain", "shouldHaveTrackingScript", "tags", "url", "workspace"),
    "traffic_source": ("clickIdVariable", "costVariable", "currencyCode", "customPostbacksConfiguration", "customVariables", "externalIds", "impressionSpecific", "limitedGeoTracking", "name", "note", "pixelRedirectUrl", "postbackUrl", "predefinedType", "skipSendingPostback", "templateId", "type", "workspace"),
}
_METRICS = ("visits", "clicks", "conversions", "cost", "revenue", "profit", "ctr", "cr", "roi")
_DIMENSIONS = ("campaignId", "offerId", "landerId", "trafficSourceId", "day")
_NAMES = ("campaignName", "offerName", "landerName", "trafficSourceName")
OPERATIONS = (
    "test_connection", "list_workspaces", "list_campaigns", "get_campaign", "create_campaign", "update_campaign_metadata", "archive_campaign",
    "list_offers", "get_offer", "create_offer", "update_offer_metadata", "archive_offer",
    "list_landers", "get_lander", "create_lander", "update_lander_metadata", "archive_lander",
    "list_traffic_sources", "get_traffic_source", "create_traffic_source", "update_traffic_source_metadata", "archive_traffic_source",
    "list_report_columns", "get_campaign_report",
)
SCOPES = ScopeRegistry("voluum", {operation: ScopeRequirement(credential_types=(FAMILY,), note="Voluum access-key user permissions; no OAuth scope strings") for operation in OPERATIONS})


def _profile(data, operation, parameters):
    return hashlib.sha256(json.dumps([data["access_id"], operation, parameters], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _cursor(data, profile, value=None, token=None):
    if token is None:
        payload = json.dumps({"p": profile, "v": value}, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(payload + hmac.new(data["access_key"].encode(), payload, hashlib.sha256).digest()).decode().rstrip("=")
    try:
        wire = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        payload, signature = wire[:-32], wire[-32:]
        if not hmac.compare_digest(signature, hmac.new(data["access_key"].encode(), payload, hashlib.sha256).digest()):
            raise ValueError()
        decoded = json.loads(payload)
        if decoded["p"] != profile:
            raise ValueError()
        return decoded["v"]
    except Exception:
        raise ValueError("Voluum continuation does not match the credential, operation or filters") from None


def _entity(raw, workspace=None, expected_id=None):
    if not isinstance(raw, dict):
        raise ValueError("Voluum entity response is invalid")
    entity_id = _uuid(raw.get("id"))
    if expected_id and entity_id != expected_id:
        raise ValueError("Voluum returned a different resource")
    owning = raw.get("workspace") or {}
    if not isinstance(owning, dict):
        raise ValueError("Voluum workspace response is invalid")
    owner = _uuid(owning["id"]) if owning.get("id") else None
    # Documentation explicitly includes account-shared entities with no workspace.
    if workspace and owner and owner != workspace:
        raise ValueError("Voluum resource belongs to a different workspace")
    result = {"id": entity_id, "name": _text(raw.get("name")), "workspace_id": owner,
              "shared": owner is None, "archived": raw.get("deleted") is True}
    for field in ("namePostfix", "createdTime", "updatedTime", "type", "landerType", "trafficType", "currencyCode"):
        if isinstance(raw.get(field), str) and len(raw[field]) <= 240:
            result[field] = raw[field]
    if isinstance(raw.get("tags"), list):
        result["tags"] = [_text(tag, 100) for tag in raw["tags"][:30]]
    result["allowed_actions"] = [x for x in raw.get("allowedActions", []) if x in {"EDIT", "DELETE", "RESTORE"}]
    return result


class _API:
    def __init__(self, data, client):
        self.data, self.client = _credential(data), client
        self.token = None
        self.expires = None

    async def request(self, method, path, *, params=None, body=None, session=False):
        allowed = {"/auth/access/session", "/startup", "/column/info", "/report"}
        valid = path in allowed or any(path == "/" + route or (path.startswith("/" + route + "/") and _uuid(path.rsplit("/", 1)[1])) for route, _, _ in _KINDS.values())
        if not valid or method not in {"GET", "POST", "PUT", "DELETE"}:
            raise ValueError("Unsupported native Voluum route")
        if path in allowed:
            expected_method = "POST" if session else "GET"
            if method != expected_method:
                raise ValueError("Unsupported native Voluum method")
        elif path.count("/") == 2 and method not in {"GET", "PUT"}:
            raise ValueError("Unsupported native Voluum entity method")
        elif path.count("/") == 1 and method not in {"GET", "POST", "DELETE"}:
            raise ValueError("Unsupported native Voluum collection method")
        if (path == "/auth/access/session") != session:
            raise ValueError("Voluum session and resource transport must remain separate")
        if not session and (not self.token or self.expires <= datetime.now(timezone.utc)):
            raise ValueError("Voluum access-key session expired; retry the operation")
        headers = {"Accept": "application/json", "Content-Type": "application/json; charset=utf-8"}
        if not session:
            headers["cwauth-token"] = self.token
        try:
            with _private_http():
                async with self.client.stream(method, BASE + path, headers=headers, params=params, json=body) as response:
                    status = response.status_code
                    if status in {202, 204}:
                        return {"_completion": "accepted" if status == 202 else "no_content", "_http_status": status}
                    if not 200 <= status < 300:
                        category = {401: "Authentication rejected", 403: "Permission denied", 404: "Resource not found", 409: "Configuration conflict", 429: "Rate limit reached"}.get(status, "Provider request failed")
                        raise ValueError(f"Voluum: {category} (HTTP {status})")
                    parts, size = [], 0
                    async for part in response.aiter_bytes():
                        size += len(part)
                        if size > MAX_BYTES:
                            raise ValueError("Voluum response exceeds the metadata limit")
                        parts.append(part)
                    content = b"".join(parts)
                    if not content:
                        raise ValueError("Voluum returned no JSON confirmation")
                    if "json" not in response.headers.get("content-type", "").lower():
                        raise ValueError("Voluum returned an unsupported response format")
                    try:
                        result = json.loads(content)
                    except Exception:
                        raise ValueError("Voluum returned malformed JSON") from None
        except (httpx.HTTPError, OSError):
            raise ValueError("Voluum transport failed; request details omitted") from None
        if not isinstance(result, dict) or result.get("error") or result.get("errorCode"):
            raise ValueError("Voluum returned a provider error; details omitted")
        return result

    async def start(self):
        data = self.data
        raw = await self.request("POST", "/auth/access/session", session=True,
                                 body={"accessId": data["access_id"], "accessKey": data["access_key"]})
        if "_completion" in raw:
            raise ValueError("Voluum session creation was not confirmed")
        token = raw.get("token")
        if not isinstance(token, str) or not 8 <= len(token) <= 8192 or any(c.isspace() or ord(c) < 32 for c in token):
            raise ValueError("Voluum session response is invalid")
        expires = _date(raw.get("expirationTimestamp"))
        if expires <= datetime.now(timezone.utc):
            raise ValueError("Voluum session is already expired")
        self.token, self.expires = token, expires

    async def workspaces(self):
        raw = await self.request("GET", "/startup")
        response = (raw.get("responses") or {}).get("workspaces")
        if not isinstance(response, dict) or response.get("status") != 200:
            raise ValueError("Voluum workspace context was not confirmed")
        rows = (response.get("body") or {}).get("workspaces")
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError("Voluum workspace context is invalid")
        result = [{"id": _uuid(row.get("id")), "name": _text(row.get("name"))} for row in rows if isinstance(row, dict)]
        if len(result) != len(rows) or len({row["id"] for row in result}) != len(result):
            raise ValueError("Voluum workspace context is invalid")
        return result

    async def require_workspace(self, workspace):
        workspace = _uuid(workspace)
        if workspace not in {row["id"] for row in await self.workspaces()}:
            raise ValueError("Selected Voluum workspace is unavailable to this access key")
        return workspace

    async def get_entity(self, kind, resource_id, workspace):
        raw = await self.request("GET", f"/{_KINDS[kind][0]}/{_uuid(resource_id)}")
        _entity(raw, workspace, _uuid(resource_id))
        return raw


class VoluumNode(WorkflowNode):
    integration_type = TYPE
    scope_registry = SCOPES
    # Token-bound workspaces are account-specific data, not invented user identity.
    connection_evidence = ConnectionEvidence(noun="workspaces", operation="list_workspaces", proves="account")

    @classmethod
    def get_config_model(cls):
        return VoluumNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        if isinstance(config_data, dict) and config_data.get("credentials"):
            _credential(config_data["credentials"])
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            if isinstance(config_data, dict) and config_data.get("credentials"):
                _credential(config_data["credentials"])
        except ValueError:
            return {"valid": False, "errors": ["This node requires a Voluum access-key credential"], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        fields = {"workspace_id": None, **{field: kind for kind, (_, _, field) in _KINDS.items()}}
        if field_name not in fields:
            return {"options": [], "next_page_token": None}
        data = _credential(credential_data)
        kind = fields[field_name]
        context = context if isinstance(context, dict) else {}
        # Reject missing parents before session creation, irrespective of caller metadata.
        workspace = _uuid(context.get("workspace_id")) if kind else None
        args = {"operation": "list_" + ("traffic_sources" if kind == "traffic_source" else kind + "s"),
                "workspace_id": workspace, "limit": 50, "name": search, "include_archived": False, "page_token": page_token} if kind else None
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5), follow_redirects=False, trust_env=False) as client:
            api = _API(data, client)
            if kind:
                _list_cursor(data, args)  # Verify before any provider I/O.
            await api.start()
            if kind:
                await api.require_workspace(workspace)
                result = await _list(api, data, kind, args)
            else:
                rows = await api.workspaces()
                rows = [row for row in rows if not search or search.casefold() in row["name"].casefold()]
                result = {"data": rows[:100], "next_page_token": None, "truncated": len(rows) > 100}
            return {"options": [{"value": row["id"], "label": row["name"]} for row in result["data"]], "next_page_token": result.get("next_page_token")}

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Voluum access-key credentials are required")
        config = self.config.config.model_dump()
        operation = config["operation"]
        data = _credential(self.config.credentials.model_dump())
        if operation.startswith("list_") and operation not in {"list_workspaces", "list_report_columns"}:
            _list_cursor(data, config)
        if operation == "get_campaign_report":
            _report_parameters(data, config)
        for field in ("workspace_id", "campaign_id", "offer_id", "lander_id", "traffic_source_id"):
            if config.get(field):
                _uuid(config[field])
        if config.get("note") is not None and config.get("clear_note"):
            raise ValueError("Choose a note or clear note, not both")
        for key in ("name", "note"):
            if config.get(key):
                _text(config[key], 4000 if key == "note" else 240)
        for tag in config.get("tags") or []:
            _text(tag, 100)
        if config.get("destination_url"):
            _url(config["destination_url"])
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5), follow_redirects=False, trust_env=False) as client:
            api = _API(data, client)
            await api.start()
            if operation == "test_connection":
                return {"status": "success", "action": operation, "data": {"message": "Voluum access key accepted; account identity not established", "identity_verified": False}}
            if operation == "list_workspaces":
                return {"status": "success", "action": operation, "data": await api.workspaces()}
            if operation == "list_report_columns":
                raw = await api.request("GET", "/column/info")
                return {"status": "success", "action": operation, "data": _columns(raw)}
            workspace = await api.require_workspace(config["workspace_id"])
            if operation == "get_campaign_report":
                await api.get_entity("campaign", config["campaign_id"], workspace)
                return await _report(api, data, config)
            for kind, (route, collection, id_field) in _KINDS.items():
                plural = "traffic_sources" if kind == "traffic_source" else kind + "s"
                if operation == "list_" + plural:
                    return await _list(api, data, kind, config)
                if operation in {"get_" + kind, "update_" + kind + "_metadata", "archive_" + kind}:
                    resource_id = _uuid(config[id_field])
                    raw = await api.get_entity(kind, resource_id, workspace)
                    if operation == "get_" + kind:
                        return {"status": "success", "action": operation, "data": _entity(raw, workspace, resource_id)}
                    if _entity(raw, workspace, resource_id)["workspace_id"] != workspace:
                        raise ValueError("Voluum writes require a record owned by the selected workspace; shared records are read-only here")
                    action = "DELETE" if operation.startswith("archive_") else "EDIT"
                    if action not in raw.get("allowedActions", []):
                        raise ValueError("Voluum user does not have the required entity permission")
                    if operation.startswith("archive_"):
                        result = await api.request("DELETE", "/" + route, body={"ids": [resource_id]})
                        if "_completion" in result:
                            return _unverified(operation, result)
                        rows = result.get("items")
                        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict) or _uuid(rows[0].get("id")) != resource_id:
                            raise ValueError("Voluum archive result did not confirm the selected entity")
                        status = rows[0].get("status")
                        if status not in {"SUCCESSFUL", "FAILED", "PARTIALLY_APPLIED"}:
                            raise ValueError("Voluum archive response is invalid")
                        if result.get("status") != status:
                            raise ValueError("Voluum archive envelope contradicts its entity result")
                        return {"status": "success" if status == "SUCCESSFUL" else "error", "action": operation,
                                "data": {"id": resource_id, "archive_status": status, "reference_count": len(rows[0].get("references") or [])},
                                "message": "Archive response received; no hard deletion or restoration implied"}
                    body = _update(kind, raw, config)
                    result = await api.request("PUT", f"/{route}/{resource_id}", body=body)
                    if "_completion" in result:
                        return _unverified(operation, result)
                    _entity(result, workspace, resource_id)
                    readback = await api.get_entity(kind, resource_id, workspace)
                    _verify_metadata(kind, readback, config)
                    return {"status": "success", "action": operation, "data": _entity(readback, workspace, resource_id), "readback_verified": True}
                if operation == "create_" + kind:
                    if kind == "campaign":
                        await api.get_entity("traffic_source", config["traffic_source_id"], workspace)
                    result = await api.request("POST", "/" + route, body=_create(kind, config, workspace))
                    if "_completion" in result:
                        return _unverified(operation, result)
                    created = _entity(result, workspace)
                    if created["workspace_id"] != workspace:
                        raise ValueError("Voluum creation did not confirm the requested workspace")
                    readback = await api.get_entity(kind, created["id"], workspace)
                    _verify_metadata(kind, readback, config)
                    return {"status": "success", "action": operation, "data": _entity(readback, workspace, created["id"]), "readback_verified": True}
        raise ValueError("Unsupported native Voluum operation")


def _unverified(operation, result):
    return {"status": "accepted" if result["_completion"] == "accepted" else "unverified", "action": operation,
            "executed": True, "completion_confirmed": False, "data": {}, "http_status": result["_http_status"]}


def _list_cursor(data, config):
    signature = _profile(data, config["operation"], {key: config.get(key) for key in ("workspace_id", "name", "include_archived", "limit")})
    value = _cursor(data, signature, token=config["page_token"]) if config.get("page_token") else None
    return signature, _uuid(value) if value is not None else None


async def _list(api, data, kind, config):
    signature, continuation = _list_cursor(data, config)
    route, collection, _ = _KINDS[kind]
    params = {"workspaceId": _uuid(config["workspace_id"]), "limit": config["limit"], "includeDeleted": str(config["include_archived"]).lower()}
    if config.get("name"):
        params["name" if kind == "traffic_source" else "namePostfix"] = _text(config["name"])
    if continuation:
        params["nextId"] = continuation
    raw = await api.request("GET", "/" + route, params=params)
    rows = raw.get(collection)
    if not isinstance(rows, list) or len(rows) > config["limit"]:
        raise ValueError("Voluum returned an invalid catalog page")
    output = [_entity(row, config["workspace_id"]) for row in rows]
    if len({row["id"] for row in output}) != len(output):
        raise ValueError("Voluum returned duplicate catalog IDs")
    next_id = _uuid(raw["nextId"]) if raw.get("nextId") else None
    if next_id and next_id == continuation:
        raise ValueError("Voluum returned a repeated continuation")
    return {"status": "success", "action": config["operation"], "data": output,
            "next_page_token": _cursor(data, signature, next_id) if next_id else None}


def _create(kind, config, workspace):
    common = {"workspace": {"id": workspace}, "tags": config.get("tags") or []}
    if kind == "traffic_source":
        return {"workspace": {"id": workspace}, "name": config["name"], "type": "CUSTOM", "impressionSpecific": False, "skipSendingPostback": True}
    common["namePostfix"] = config["name"]
    if kind == "campaign":
        return {**common, "costModel": {"type": "NOT_TRACKED"}, "trafficSource": {"id": _uuid(config["traffic_source_id"])},
                "redirectTarget": {"redirectUrl": {"url": _url(config["destination_url"]), "redirectMode": "REGULAR"}}}
    if kind == "offer":
        return {**common, "url": _url(config["destination_url"]), "currencyCode": config["currency"], "payout": {"type": "AUTO"}}
    return {**common, "url": _url(config["destination_url"]), "landerType": config["lander_type"], "shouldHaveTrackingScript": config["should_have_tracking_script"]}


def _update(kind, raw, config):
    body = {key: deepcopy(raw[key]) for key in _WRITE_FIELDS[kind] if key in raw}
    for key in ("workspace", "trafficSource", "affiliateNetwork"):
        if isinstance(body.get(key), dict):
            body[key] = {"id": _uuid(body[key]["id"])}
    if isinstance(body.get("country"), dict):
        body["country"] = {"code": body["country"]["code"]}
    if kind == "campaign":
        target = body.get("redirectTarget") or {}
        direct = target.get("redirectUrl")
        if not isinstance(direct, dict) or not direct.get("url"):
            raise ValueError("Campaign metadata update supports documented direct-URL campaigns only")
        body["redirectTarget"] = {"redirectUrl": {"url": direct["url"], "redirectMode": direct["redirectMode"]}}
        cost = body.get("costModel") or {}
        body["costModel"] = {key: cost[key] for key in ("type", "value", "trafficLossEnabled", "trafficLossRatio", "customConversionCostConfiguration") if key in cost}
    body["name" if kind == "traffic_source" else "namePostfix"] = config["name"]
    if config.get("tags") is not None:
        body["tags"] = config["tags"]
    if config.get("note") is not None and config["clear_note"]:
        raise ValueError("Choose a note or clear note, not both")
    if config.get("note") is not None or config["clear_note"]:
        body["note"] = {"note": config.get("note") or ""}
    return body


def _verify_metadata(kind, raw, config):
    if raw.get("name" if kind == "traffic_source" else "namePostfix") != config["name"]:
        raise ValueError("Voluum write readback did not confirm the requested name")
    if config.get("tags") is not None and raw.get("tags", []) != config["tags"]:
        raise ValueError("Voluum write readback did not confirm the requested tags")
    if config.get("clear_note") or config.get("note") is not None:
        if (raw.get("note") or {}).get("note", "") != (config.get("note") or ""):
            raise ValueError("Voluum write readback did not confirm the requested note")


def _columns(raw):
    rows = raw.get("columnMappings")
    if not isinstance(rows, list) or len(rows) > 2000:
        raise ValueError("Voluum report column metadata is invalid")
    return [{"key": row["key"], "label": _text(row.get("label")), "type": _text(row.get("type"), 40),
             "can_group_by": row.get("canGroupBy") is True} for row in rows if isinstance(row, dict) and row.get("key") in _DIMENSIONS + _NAMES + _METRICS]


def _report_parameters(data, config):
    start, end = _date(config["from_time"]), _date(config["to_time"])
    if start >= end or end - start > timedelta(days=31) or any((value.minute, value.second, value.microsecond) != (0, 0, 0) for value in (start, end)):
        raise ValueError("Voluum report requires an hour-aligned half-open range of at most 31 days")
    signature = _profile(data, config["operation"], {key: value for key, value in config.items() if key != "page_token"})
    offset = _cursor(data, signature, token=config["page_token"]) if config.get("page_token") else 0
    if type(offset) is not int or not 0 <= offset <= 100000:
        raise ValueError("Voluum report continuation is invalid")
    return signature, offset


async def _report(api, data, config):
    signature, offset = _report_parameters(data, config)
    columns = _columns(await api.request("GET", "/column/info"))
    supported = {row["key"] for row in columns}
    group = config["group_by"]
    if not any(row["key"] == group and row["can_group_by"] for row in columns):
        raise ValueError("Selected Voluum report grouping is unavailable to this key")
    wanted = [group, *[key for key in _NAMES + _METRICS if key in supported]]
    params = [("from", config["from_time"]), ("to", config["to_time"]), ("tz", "Etc/GMT"),
              ("groupBy", group), ("filter1", "campaignId"), ("filter1Value", _uuid(config["campaign_id"])),
              ("workspaces", _uuid(config["workspace_id"])), ("limit", config["limit"]), ("offset", offset),
              ("currency", config["currency"]), ("conversionTimeMode", config["conversion_time_mode"]), ("include", config["include"])]
    params.extend(("column", key) for key in wanted)
    raw = await api.request("GET", "/report", params=params)
    rows, total, applied = raw.get("rows"), raw.get("totalRows"), raw.get("limit")
    if not isinstance(rows, list) or type(total) is not int or type(applied) is not int or not 1 <= applied <= config["limit"] or raw.get("offset") != offset or len(rows) > applied or not 0 <= total <= 100000 or (rows and offset + len(rows) > total):
        raise ValueError("Voluum report page is invalid")
    def project(row):
        if not isinstance(row, dict):
            raise ValueError("Voluum aggregate row is invalid")
        result = {}
        for key in wanted:
            value = row.get(key)
            if value is None:
                continue
            if key in _METRICS:
                if type(value) not in {int, float} or not math.isfinite(value):
                    raise ValueError("Voluum aggregate metric is invalid")
            elif key in _DIMENSIONS and key != "day":
                value = _uuid(value)
            else:
                value = _text(value)
            result[key] = value
        if group not in result:
            raise ValueError("Voluum aggregate dimension is missing")
        if group == "campaignId" and result[group] != _uuid(config["campaign_id"]):
            raise ValueError("Voluum report returned a different campaign")
        return result
    next_offset = offset + len(rows)
    if next_offset < total and not rows:
        raise ValueError("Voluum report returned an empty continuation page")
    return {"status": "success", "action": config["operation"], "data": [project(row) for row in rows],
            "totals": {key: value for key, value in (raw.get("totals") or {}).items() if key in _METRICS and type(value) in {int, float} and math.isfinite(value)},
            "totals_scope": "All matching rows, not only this page", "total_rows": total,
            "time_range_truncated": raw.get("truncated") is True, "provider_message_count": len(raw.get("messages") or []),
            "next_page_token": _cursor(data, signature, next_offset) if next_offset < total else None}
