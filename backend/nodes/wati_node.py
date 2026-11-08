"""Native WATI recommended V3 contacts and bounded service metadata.

Fixed host/no tenant path. Existing issued scoped access token only. Source
preparation performs no contact/message/account/permission/provider action.
"""
from __future__ import annotations
import base64
import hashlib
import json
import logging
import math
import re
from contextvars import ContextVar
from datetime import datetime
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote, quote_plus
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, ValidationResult, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-wati"
FAMILIES = ("wati_api_access_token",)
API_BASE = "https://live-mt-server.wati.io/api/ext/v3"
MAX_BYTES = 4 * 1024 * 1024
MAX_ROWS = 1000
WRITE_OPS = ("create_contact", "update_contact_attributes", "soft_delete_contact")


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Supply a bounded exact WATI resource ID, not a phone/channel target or URL")
    return value


def _token(value):
    if not isinstance(value, str) or not 8 <= len(value) <= 8192 or any(ord(c) <= 32 or ord(c) >= 127 for c in value) or value.startswith("Bearer "):
        raise ValueError("Supply the existing issued WATI API access token without the Bearer prefix")
    return value


class WATIApiAccessTokenCredential(BaseModel):
    credential_type: Literal["wati_api_access_token"] = Field("wati_api_access_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Access Token", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="WATI API Access Token", extra="ignore", json_schema_extra={
        "x-credential-url": "https://docs.wati.io/reference/authentication",
        "x-credential-instructions": "Paste an existing API access token from your WATI workspace without the Bearer prefix. The connection check reads contact metadata. Each operation requires its documented permissions and may depend on your role and plan.",
    })
    _native_token = field_validator("api_token")(_token)


def _whole(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,4}", value):
        value = int(value)
    if type(value) is not int:
        raise ValueError("Use a whole numeric option")
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValueError("Supply nonempty bounded text")
    return value


def _custom_params(value):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > 16384:
        raise ValueError("Supply a small flat JSON object of string attribute values")
    try:
        data = json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(data, dict) or not 1 <= len(data) <= 20 or any(not isinstance(k, str) or not 1 <= len(k) <= 64 or any(ord(c) < 32 for c in k) or not isinstance(v, str) or len(v) > 2048 or '\x00' in v for k, v in data.items()):
            raise ValueError()
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("WATI custom attributes require a small flat string-value object; null/clear semantics are not documented") from None
    return [{"name": key, "value": child} for key, child in data.items()]


def _dynamic(field):
    return {"x-dynamic-options": {"field_name": field, "searchable": True, "allow_custom": True}, "x-resource-type": "wati_" + field.removesuffix("_id"), "x-resource-id-path": field}


def _op(name, label, category, permissions):
    return Field(name, title=label, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False, "x-provider-permission-alternatives": permissions})


class WATIOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WATIPage(WATIOperation):
    page_number: int = Field(1, ge=1, le=1000, description="Documented 1-based page; local bound 1000. Each operation returns one bounded page.")
    page_size: int = Field(20, ge=1, le=100, description="Documented maximum 100. Nullable collections are not silently converted to empty lists.")
    _numeric_page = field_validator("page_number", "page_size", mode="before")(_whole)


class WATIContactScope(WATIOperation):
    contact_id: str = Field(..., title="Contact ID", json_schema_extra=_dynamic("contact_id"), description="Use the exact protected returned contact ID. Native slice deliberately excludes ambiguous phone/Channel:PhoneNumber targets.")
    _contact = field_validator("contact_id")(_id)


class WATIChannelScope(WATIOperation):
    channel_id: Optional[str] = Field(None, title="Optional Channel", json_schema_extra=_dynamic("channel_id"), description="Native resolves the current protected channel ID to its returned name because the endpoint's channel query accepts a name/phone, not an ID. Omit for provider's default scope. Default channel is excluded by channel discovery.")
    @field_validator("channel_id")
    @classmethod
    def channel(cls, value):
        return _id(value) if value is not None else None


class WATIChanges(WATIOperation):
    confirm_changes: bool = Field(False, description="Explicitly confirm real contact data effects. No quiet/no-notification guarantee; soft delete is not physical erasure.")


class WATICheckConfig(WATIOperation):
    operation: Literal["test_connection"] = _op("test_connection", "Check Protected Contacts Access", "Connection", ["api", "contactsv3:read"])



class WATIListContactsConfig(WATIPage):
    operation: Literal["list_contacts"] = _op("list_contacts", "List Contact Metadata", "Contacts", ["api", "contactsv3:read"])
    include_names: bool = Field(False, description="Explicitly include private contact names; phone/wa_id/photos/custom values are always omitted.")


class WATIGetContactConfig(WATIContactScope):
    operation: Literal["get_contact"] = _op("get_contact", "Get Contact and Independent Readback", "Contacts", ["api", "contactsv3:read"])
    include_names: bool = Field(False)


class WATIContactCountConfig(WATIOperation):
    operation: Literal["get_contact_count"] = _op("get_contact_count", "Get Current Contact Count", "Contacts", ["api", "contactsv3:read"])



class WATICreateContactConfig(WATIChanges):
    operation: Literal["create_contact"] = _op("create_contact", "Create Contact", "Contacts", ["api", "contactsv3:write"])
    whatsapp_number: str = Field(..., title="WhatsApp Number", max_length=15, description="Explicit international digits without +; private customer data. Contact effects are not a no-notification contract.")
    name: str = Field(..., max_length=256)
    custom_params_json: Optional[str] = Field(None, title="Custom Attributes (JSON)", max_length=16384, json_schema_extra={"ui:widget": "textarea"}, description="Optional flat JSON string-value object. POST serializes documented custom_params; no opt-in/broadcast/team controls.")
    _name = field_validator("name")(_text)
    @field_validator("whatsapp_number")
    @classmethod
    def phone(cls, value):
        if not re.fullmatch(r"[1-9][0-9]{5,14}", value):
            raise ValueError("Use bounded international digits without +")
        return value
    @field_validator("custom_params_json")
    @classmethod
    def params(cls, value):
        if value is not None and value.strip():
            _custom_params(value)
        return value



class WATIUpdateContactConfig(WATIContactScope, WATIChanges):
    operation: Literal["update_contact_attributes"] = _op("update_contact_attributes", "Update One Contact Attributes", "Contacts", ["api", "wati_integration:write", "contactsv3:write"])
    custom_params_json: str = Field(..., title="Custom Attributes (JSON)", max_length=16384, json_schema_extra={"ui:widget": "textarea"}, description="Nonempty string-value object. Native PUT sends one contacts[] entry with target and camelCase customParams. No undocumented name/phone/clear/opt-in/assignment fields.")
    @field_validator("custom_params_json")
    @classmethod
    def params(cls, value):
        _custom_params(value)
        return value



class WATIDeleteContactConfig(WATIContactScope, WATIChanges):
    operation: Literal["soft_delete_contact"] = _op("soft_delete_contact", "Soft Delete Contact", "Contacts", ["api", "wati_integration:write", "contactsv3:write"])



class WATIListChannelsConfig(WATIPage):
    operation: Literal["list_channels"] = _op("list_channels", "List Connected Channel Metadata", "Channels", ["api", "wati_integration:read", "channelsv3:read"])



class WATIListTemplatesConfig(WATIPage, WATIChannelScope):
    operation: Literal["list_templates"] = _op("list_templates", "List Template Metadata", "Templates", ["api", "wati_integration:read", "messagetemplatev3:read"])



class WATIGetTemplateConfig(WATIOperation):
    operation: Literal["get_template"] = _op("get_template", "Get Template Metadata", "Templates", ["api", "wati_integration:read", "messagetemplatev3:read"])
    template_id: str = Field(..., title="Template", json_schema_extra=_dynamic("template_id"))
    _template = field_validator("template_id")(_id)



class WATIListCampaignsConfig(WATIPage, WATIChannelScope):
    operation: Literal["list_campaigns"] = _op("list_campaigns", "List Existing Campaign Metadata", "Campaigns", ["api", "wati_integration:read", "campaignsv3:read"])



class WATIGetCampaignConfig(WATIOperation):
    operation: Literal["get_campaign"] = _op("get_campaign", "Get Existing Campaign Metadata", "Campaigns", ["api", "wati_integration:read", "campaignsv3:read"])
    campaign_id: str = Field(..., title="Campaign", json_schema_extra=_dynamic("campaign_id"))
    _campaign = field_validator("campaign_id")(_id)



class WATIListSegmentsConfig(WATIPage):
    operation: Literal["list_segments"] = _op("list_segments", "List Segment Metadata", "Segments", ["api", "wati_integration:read", "segmentsv3:read"])
    source: Literal[0, 1, 2] = Field(0, description="0 all, 1 custom, 2 system predefined.")
    sort_field: Literal[0, 1, 2] = Field(1, description="0 default, 1 created time, 2 updated time.")
    _enum_numeric = field_validator("source", "sort_field", mode="before")(_whole)



class WATIGetSegmentConfig(WATIOperation):
    operation: Literal["get_segment"] = _op("get_segment", "Get Segment Metadata", "Segments", ["api", "wati_integration:read", "segmentsv3:read"])
    segment_id: str = Field(..., title="Segment", json_schema_extra=_dynamic("segment_id"))
    _segment = field_validator("segment_id")(_id)



class WATIListMessagesConfig(WATIPage):
    operation: Literal["list_message_metadata"] = _op("list_message_metadata", "Read Existing Conversation Event Metadata", "Messages", ["api", "conversationsv3:read"])
    conversation_id: str = Field(..., title="Existing Conversation ID", description="Manual exact ConversationId only. V3 public index offers no native conversation discovery/detail route; returned event conversation_id must match. Empty rows do not prove conversation identity. No phone target, raw text, status/read-receipt, media or signed URL output.")
    _conversation = field_validator("conversation_id")(_id)


WATIConfig = Annotated[Union[WATICheckConfig, WATIListContactsConfig, WATIGetContactConfig, WATIContactCountConfig, WATICreateContactConfig, WATIUpdateContactConfig, WATIDeleteContactConfig, WATIListChannelsConfig, WATIListTemplatesConfig, WATIGetTemplateConfig, WATIListCampaignsConfig, WATIGetCampaignConfig, WATIListSegmentsConfig, WATIGetSegmentConfig, WATIListMessagesConfig], Field(discriminator="operation")]

class WATINodeConfig(NodeConfig[WATIConfig, WATIApiAccessTokenCredential]):
    pass

class WATIAPIError(ValueError):
    def __init__(self, message, *, authority_rejected=False):
        super().__init__(message)
        self.authority_rejected = authority_rejected


def _shape(data):
    if not isinstance(data, dict) or data.get("credential_type", FAMILIES[0]) not in FAMILIES:
        raise ValueError("WATI credential family is unsupported")
    try:
        shaped = WATIApiAccessTokenCredential.model_validate({**data, "credential_type": FAMILIES[0]}).model_dump()
    except Exception:
        raise ValueError("WATI native access token is invalid") from None
    return {**data, **shaped}


def _binding(data):
    return (data["credential_type"], data["api_token"], data.get("owner_id"), data.get("token_version"), data.get("updated_at"), data.get("approval_revision"))

def _original_family(data):
    if not isinstance(data, dict):
        raise ValueError("WATI configuration is invalid")
    creds = data.get("credentials")
    saved = data.get("credential_id") or data.get("credentialIds")
    if saved and not isinstance(creds, dict) or isinstance(creds, dict) and (creds.get("credential_type") is not None or saved) and creds.get("credential_type") not in FAMILIES:
        raise ValueError("WATI saved credential family is missing or unsupported")


def _bounded(value, depth=0):
    if type(value) is int and value.bit_length() > 256:
        raise ValueError("Unverified JSON integer bound")
    if depth > 32 or isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Unverified JSON depth or non-finite number")
    if isinstance(value, dict):
        for key, child in value.items():
            if len(key) > 512:
                raise ValueError("Unverified JSON key")
            _bounded(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_ROWS:
            raise ValueError("Unverified JSON row bound")
        for child in value:
            _bounded(child, depth + 1)


def _redact(value, secret):
    if isinstance(value, str):
        variants = (secret, quote(secret, safe=""), quote_plus(secret, safe=""), base64.b64encode(secret.encode()).decode(), base64.b64encode((secret + ":").encode()).decode())
        for variant in variants:
            pattern = re.sub(r"%([0-9A-Fa-f]{2})", lambda m: '%' + ''.join('[' + c.lower() + c.upper() + ']' for c in m[1]), re.escape(variant))
            value = re.sub(pattern, "[redacted]", value)
        return re.sub(r"(?i)([?&](?:access_token|api_key|token|signature|auth|key)=)[^&#\s]+", r"\1[redacted]", value)
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


# Narrow reuse of utils.meta_subscriptions._TransportPrivacy: context-local
# masking leaves concurrent unrelated requests untouched and resets on failure.
_PRIVATE_REQUEST = ContextVar("wati_private_request", default=False)


class _TransportPrivacy(logging.Filter):
    def filter(self, record):
        if _PRIVATE_REQUEST.get():
            record.msg, record.args = "WATI private transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_TRANSPORT_PRIVACY = _TransportPrivacy()


def _protect_transport_logs():
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.connection_pool", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"}
    names.update(name for name in tuple(logging.Logger.manager.loggerDict) if name.startswith(("httpx.", "httpcore.")))
    for name in names:
        logging.getLogger(name).addFilter(_TRANSPORT_PRIVACY)


def _route(method, parts):
    allowed = ()
    if not isinstance(parts, tuple) or not parts:
        raise ValueError("Unsupported native WATI route")
    if parts[0] == "contacts":
        if len(parts) == 1:
            allowed = ("GET", "POST", "PUT")
        elif len(parts) == 2:
            if parts[1] != "count":
                _id(parts[1])
            allowed = ("GET",) if parts[1] == "count" else ("GET", "DELETE")
    elif parts[0] in ("messageTemplates", "broadcasts", "segments"):
        if len(parts) == 1:
            allowed = ("GET",)
        elif len(parts) == 2:
            _id(parts[1]); allowed = ("GET",)
    elif parts == ("channels",):
        allowed = ("GET",)
    elif len(parts) == 3 and parts[0] == "conversations" and parts[2] == "messages":
        _id(parts[1]); allowed = ("GET",)
    if method not in allowed:
        raise ValueError("Unsupported native WATI method or route")
    return "/".join(parts)


async def _request(data, context, method, parts, *, params=None, body=None):
    route = _route(method, parts)
    if params is not None and (not isinstance(params, dict) or any(key not in ("page_number", "page_size", "channel", "source", "sort_field") for key in params)):
        raise ValueError("Unsupported WATI native query")
    current = _shape(data)
    if body is not None:
        _bounded(body)
        if len(json.dumps(body, allow_nan=False).encode()) > 128 * 1024:
            raise ValueError("WATI native body exceeds the local input bound")
    _protect_transport_logs()
    private = _PRIVATE_REQUEST.set(True)
    try:
        async with guarded_async_client( timeout=20, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, API_BASE + "/" + route, params=params, json=body, headers={"Authorization": "Bearer " + current["api_token"], "Accept": "application/json", "Content-Type": "application/json"}) as response:
                status = response.status_code
                # Auth refusals may be empty/nonJSON: status itself is authoritative.
                if status in (401, 403):
                    raise WATIAPIError(f"WATI HTTP {status}: current authorization was refused; inspect token, endpoint scopes, role, workspace and plan", authority_rejected=True)
                payload = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(payload) + len(chunk) > MAX_BYTES:
                        raise WATIAPIError("WATI response exceeds the local byte bound; a contact change may have applied; no automatic retry")
                    payload.extend(chunk)
                if status != 200:
                    raise WATIAPIError(f"WATI HTTP {status}: documented V3 success is unverified; a contact change may have applied; no retry")
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise WATIAPIError("WATI JSON success is unverified; a contact change may have applied; no replay")
                try:
                    raw = json.loads(payload, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    _bounded(raw)
                except (ValueError, UnicodeError, RecursionError):
                    raise WATIAPIError("WATI JSON response is unverified; a contact change may have applied; no replay") from None
                if isinstance(raw, dict) and (raw.get("ok") is False or "error" in raw):
                    raise WATIAPIError("WATI returned a V3 error envelope; outcome is unverified; no provider error or token echo; no replay")
                return _redact(raw, current["api_token"])
    except WATIAPIError:
        raise
    except (httpx.HTTPError, OSError, ValueError, UnicodeError):
        raise WATIAPIError("WATI transport outcome is unverified; a contact change may have applied; no retry") from None
    finally:
        _PRIVATE_REQUEST.reset(private)


# Closed fields from current endpoint component schemas, omitting PII/content.
PROJECT_FIELDS = {
    "contact": {"created": "date", "last_updated": "date", "contact_status": "nullable_string", "source": "nullable_string", "channel_id": "nullable_id", "channel_type": "nullable_string"},
    "channel": {"channel": "nullable_string"},
    "template": {"name": "nullable_string", "category": "nullable_string", "sub_category": "nullable_string", "status": "nullable_string", "last_modified": "date", "type": "nullable_string", "quality": "nullable_string", "creation_method": "nullable_string"},
    "campaign": {"channel_id": "nullable_id", "name": "nullable_string", "status": "nullable_string", "template_id": "nullable_id", "created": "date", "last_updated": "date", "scheduled_at": "date"},
    "segment": {"name": "string", "tag": "string", "hitCount": "count", "status": "segment_status", "created": "date", "lastUpdated": "date", "source": "segment_source", "refreshType": "integer", "deletedAt": "nullable_date", "useUploadedContact": "boolean", "totalContactCount": "count", "hitCountPercentage": "nullable_number"},
    "message": {"conversation_id": "nullable_id", "created": "date", "event_type": "nullable_string"},
}
# Detail schemas add different fields; list schemas do not attest those fields.
PROJECT_FIELDS["campaign_detail"] = PROJECT_FIELDS["campaign"]
PROJECT_FIELDS["segment_detail"] = {key: value for key, value in PROJECT_FIELDS["segment"].items() if key != "deletedAt"}
PROJECT_FIELDS["segment"] = {key: value for key, value in PROJECT_FIELDS["segment"].items() if key not in ("totalContactCount", "hitCountPercentage")}


def _value(value, kind):
    if value is None and kind.startswith("nullable_"):
        return None
    kind = kind.removeprefix("nullable_")
    if kind == "id":
        try:
            return _id(value)
        except ValueError:
            raise WATIAPIError("WATI returned an unverified resource identifier") from None
    valid = False
    if kind == "string":
        valid = isinstance(value, str) and len(value) <= 512
    elif kind == "date":
        if isinstance(value, str) and len(value) <= 64:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                valid = parsed.tzinfo is not None
            except ValueError:
                pass
    elif kind in ("count", "integer", "segment_status", "segment_source"):
        valid = type(value) is int
        if kind == "count": valid = valid and value >= 0
        if kind == "segment_status": valid = valid and value in (0, 1, 2, 3, 4)
        if kind == "segment_source": valid = valid and value in (0, 1, 2)
    elif kind == "number":
        valid = type(value) in (int, float) and math.isfinite(value)
    elif kind == "boolean":
        valid = type(value) is bool
    if not valid:
        raise WATIAPIError("WATI documented metadata field is unverified")
    return value


def _project(raw, kind, wanted=None, *, names=False):
    if not isinstance(raw, dict):
        raise WATIAPIError("WATI documented resource object is unverified")
    identifier = _value(raw.get("id"), "id")
    if wanted is not None and identifier != wanted:
        raise WATIAPIError("WATI returned another resource identifier")
    result = {"id": identifier}
    for key, field_type in PROJECT_FIELDS[kind].items():
        if key in raw:
            result[key] = _value(raw[key], field_type)
    if names and kind in ("contact", "channel") and "name" in raw:
        result["name"] = _value(raw["name"], "nullable_string")
    if kind == "template" and "language_option" in raw:
        language = raw["language_option"]
        if not isinstance(language, dict):
            raise WATIAPIError("WATI template language shape is unverified")
        result["language_option"] = {key: _value(language[key], "nullable_string") for key in ("key", "value", "text") if key in language}
    if kind == "campaign_detail" and "statistics" in raw:
        stats = raw["statistics"]
        if not isinstance(stats, dict):
            raise WATIAPIError("WATI campaign statistics shape is unverified")
        result["statistics"] = {key: _value(stats[key], "count") for key in ("total_recipients", "total_pending", "total_queued", "total_sending", "total_sent", "total_delivered", "total_read", "total_replied", "total_failed", "total_stopped") if key in stats}
    return result


def _page(raw, key, kind, page, size, *, names=False, camel=False, no_echo=False, nullable=True, total_expected=False):
    if not isinstance(raw, dict) or key not in raw:
        raise WATIAPIError("WATI documented page envelope is unverified")
    if not no_echo:
        for field, expected in (("pageNumber" if camel else "page_number", page), ("pageSize" if camel else "page_size", size)):
            if type(raw.get(field)) is not int or raw[field] != expected:
                raise WATIAPIError("WATI returned another page or unverified page size")
    rows = raw[key]
    has_total = total_expected and "total" in raw
    total = raw.get("total") if has_total else None
    if has_total:
        _value(total, "count")
    if rows is None and nullable:
        return {"results": None, "collection_exhausted": None, "continuation_unknown": True, "next_page_number": None, "page_number": page, "page_size": size, "nullable_collection": True, **({"total": total} if has_total else {}), "page_scope_source": "request_only" if no_echo else "response_echo_and_request"}
    if not isinstance(rows, list) or len(rows) > size:
        raise WATIAPIError("WATI page rows exceed the requested bound or have an unverified shape")
    result = [_project(row, kind, names=names) for row in rows]
    ids = [row["id"] for row in result]
    if len(ids) != len(set(ids)):
        raise WATIAPIError("WATI page repeats resource IDs")
    if has_total:
        offset = (page - 1) * size
        if result and offset + len(result) > total or not result and offset < total:
            raise WATIAPIError("WATI page total is inconsistent with returned rows")
        exhausted = offset + len(result) >= total
    else:
        exhausted = True if not result else None
    capped = page >= 1000 and exhausted is not True
    return {"results": result, "page_number": page, "page_size": size, **({"total": total} if has_total else {}), "collection_exhausted": exhausted, "continuation_unknown": exhausted is None, "next_page_number": page + 1 if exhausted is not True and not capped else None, "local_page_limit_reached": capped, "page_scope_source": "request_only" if no_echo else "response_echo_and_request"}


async def _get_contact(data, context, identifier, *, names=False):
    return _project(await _request(data, context, "GET", ("contacts", identifier)), "contact", identifier, names=names)


async def _find_channel(data, context, identifier):
    seen = set()
    for page in range(1, 6):
        raw = await _request(data, context, "GET", ("channels",), params={"page_number": page, "page_size": 20})
        result = _page(raw, "channels", "channel", page, 20, names=True, no_echo=True)
        if result["results"] is None:
            raise WATIAPIError("WATI nullable channel list did not establish parent membership or exhaustion")
        ids = [row["id"] for row in result["results"]]
        if seen.intersection(ids):
            raise WATIAPIError("WATI channel pages repeat IDs before parent scope was established")
        seen.update(ids)
        if identifier in ids:
            name = result["results"][ids.index(identifier)].get("name")
            if not isinstance(name, str) or not name.strip() or len(name) > 256 or any(ord(c) < 32 for c in name):
                raise WATIAPIError("WATI channel name required by the documented query is unverified")
            return name
        if result["collection_exhausted"] is True:
            raise ValueError("Selected WATI channel was not found in current protected discovery; the default channel is excluded")
    raise WATIAPIError("WATI channel parent membership was not established within five pages; no child read executed")


class WATINode(WorkflowNode):
    integration_type = "automation-wati"
    connection_evidence = ConnectionEvidence(operation="test_connection", noun="WATI contact identifiers", proves="reachability", label_keys=("id",))
    edit_examples = ["List current contact metadata", "Read a selected template without sending it", "Read existing campaign status", "Update explicit attributes of a selected contact"]

    @classmethod
    def get_config_model(cls):
        return WATINodeConfig

    @classmethod
    def parse_config(cls, config_data):
        data = config_data
        _original_family(data)
        shaped = dict(data)
        if data.get("credentials") is not None:
            shaped["credentials"] = _shape(data["credentials"])
        try:
            WATINodeConfig.model_validate(runtime_config_view(shaped, WATINodeConfig))
        except ValueError:
            raise ValueError("WATI native configuration or selected credential scope is invalid") from None
        return super().parse_config(shaped)

    @classmethod
    def validate_config(cls, config_data):
        data = config_data
        try:
            _original_family(data)
            shaped = dict(data)
            if data.get("credentials") is not None:
                shaped["credentials"] = _shape(data["credentials"])
            WATINodeConfig.model_validate(runtime_config_view(shaped, WATINodeConfig))
        except (ValueError, TypeError):
            return ValidationResult(valid=False, errors=["WATI native configuration or credential family is invalid"], satisfied_set=None)
        return super().validate_config(shaped)

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, WATINodeConfig) or self.config.credentials is None:
            raise ValueError("WATI requires an explicit issued native API access token")
        cfg = self.config.config
        if cfg.operation in WRITE_OPS and not cfg.confirm_changes:
            raise ValueError("Confirm the explicit WATI contact data effects before any provider request")
        context = {"_approval_pool": (self.node_data or {}).get("_approval_pool"), "_credential_id": (self.node_data or {}).get("credential_id"), "_user_id": self.user_id, "_organization_id": self.organization_id, "_workflow_id": self.workflow_id}
        data = _shape(self.config.credentials.model_dump())
        result = await self._operation(cfg, data, context)
        return {"status": "success", "operation": cfg.operation, "data": _redact(result, data["api_token"])}

    @staticmethod
    async def _operation(cfg, data, context):
        op = cfg.operation
        if op in WRITE_OPS and not cfg.confirm_changes:
            raise ValueError("Confirm the explicit WATI contact data effects before any provider request")
        if op in ("test_connection", "list_contacts"):
            page, size = (1, 10) if op == "test_connection" else (cfg.page_number, cfg.page_size)
            raw = await _request(data, context, "GET", ("contacts",), params={"page_number": page, "page_size": size})
            result = _page(raw, "contact_list", "contact", page, size, names=getattr(cfg, "include_names", False))
            if op == "test_connection":
                result.update({"protected_read_completed": True, "account_identity_verified": False, "write_permissions_verified": False})
            return result
        if op == "get_contact":
            return {"contact": await _get_contact(data, context, cfg.contact_id, names=cfg.include_names), "independent_get_completed": True, "physical_erasure_verified": False}
        if op == "get_contact_count":
            raw = await _request(data, context, "GET", ("contacts", "count"))
            if not isinstance(raw, dict) or "contact_count" not in raw:
                raise WATIAPIError("WATI contact_count envelope is unverified")
            return {"contact_count": _value(raw["contact_count"], "count")}
        if op == "create_contact":
            body = {"whatsapp_number": cfg.whatsapp_number, "name": cfg.name}
            if cfg.custom_params_json is not None and cfg.custom_params_json.strip():
                body["custom_params"] = _custom_params(cfg.custom_params_json)
            raw = await _request(data, context, "POST", ("contacts",), body=body)
            result = _project(raw, "contact")
            if raw.get("wa_id") != cfg.whatsapp_number:
                raise WATIAPIError("WATI returned contact target is unverified; a change may have applied; inspect independently without replay")
            return {"contact": result, "acknowledged": True, "independent_readback_verified": False, "atomic_new_creation_verified": False, "notification_absence_verified": False}
        if op in ("update_contact_attributes", "soft_delete_contact"):
            await _get_contact(data, context, cfg.contact_id)
            if op == "update_contact_attributes":
                body = {"contacts": [{"target": cfg.contact_id, "customParams": _custom_params(cfg.custom_params_json)}]}
                raw = await _request(data, context, "PUT", ("contacts",), body=body)
                rows = raw.get("contact_list") if isinstance(raw, dict) else None
                if not isinstance(rows, list) or len(rows) != 1:
                    raise WATIAPIError("WATI updated contact acknowledgement is unverified; a change may have applied; no replay")
                return {"contact": _project(rows[0], "contact", cfg.contact_id), "acknowledged": True, "independent_readback_verified": False, "notification_absence_verified": False}
            raw = await _request(data, context, "DELETE", ("contacts", cfg.contact_id))
            if not isinstance(raw, dict) or raw.get("contactId") != cfg.contact_id or type(raw.get("deleted")) is not bool or type(raw.get("cleanupCompleted")) is not bool:
                raise WATIAPIError("WATI soft-delete receipt is unverified; effects may have applied; inspect independently without replay")
            return {"contact_id": cfg.contact_id, "acknowledged": True, "provider_reported_deleted": raw["deleted"], "provider_reported_cleanup_completed": raw["cleanupCompleted"], "physical_erasure_verified": False, "independent_readback_verified": False, "notification_absence_verified": False}
        if op in ("list_channels", "list_templates", "list_campaigns", "list_segments", "list_message_metadata"):
            params = {"page_number": cfg.page_number, "page_size": cfg.page_size}
            collection = {"list_channels": ("channels", "channels", "channel"), "list_templates": ("messageTemplates", "templates", "template"), "list_campaigns": ("broadcasts", "broadcasts", "campaign"), "list_segments": ("segments", "segments", "segment"), "list_message_metadata": ("conversations", "message_list", "message")}[op]
            route, key, kind = collection
            channel_id = getattr(cfg, "channel_id", None)
            if channel_id is not None:
                params["channel"] = await _find_channel(data, context, channel_id)
            if op == "list_segments":
                params.update({"source": cfg.source, "sort_field": cfg.sort_field})
            parts = ("conversations", cfg.conversation_id, "messages") if op == "list_message_metadata" else (route,)
            raw = await _request(data, context, "GET", parts, params=params)
            result = _page(raw, key, kind, cfg.page_number, cfg.page_size, camel=op == "list_segments", no_echo=op == "list_channels", nullable=op != "list_segments", total_expected=op in ("list_templates", "list_campaigns", "list_segments"))
            if op == "list_campaigns" and channel_id is not None and result["results"] is not None and any(row.get("channel_id") != channel_id for row in result["results"]):
                raise WATIAPIError("WATI returned campaign outside the selected protected channel")
            if channel_id is not None:
                result.update({"channel_id": channel_id, "channel_scope_source": "protected_channel_name_and_request"})
            if op == "list_message_metadata":
                rows = result["results"]
                if rows is not None and any(row.get("conversation_id") != cfg.conversation_id for row in rows):
                    raise WATIAPIError("WATI returned event outside the exact selected conversation")
                result.update({"requested_conversation_id": cfg.conversation_id, "returned_conversation_scope_verified": bool(rows)})
            return result
        scopes = {"get_template": ("messageTemplates", "template", "template_id"), "get_campaign": ("broadcasts", "campaign_detail", "campaign_id"), "get_segment": ("segments", "segment_detail", "segment_id")}
        if op in scopes:
            route, kind, field = scopes[op]
            identifier = getattr(cfg, field)
            return _project(await _request(data, context, "GET", (route, identifier)), kind, identifier)
        raise ValueError("Unsupported native WATI operation")

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        operations = {"contact_id": WATIListContactsConfig, "channel_id": WATIListChannelsConfig, "template_id": WATIListTemplatesConfig, "campaign_id": WATIListCampaignsConfig, "segment_id": WATIListSegmentsConfig}
        if field_name not in operations:
            return {"options": [], "next_page_token": None}
        context = context or {}
        query = (search or "").strip() if isinstance(search, str) or search is None else None
        if query is None or len(query) > 128 or any(ord(c) < 32 for c in query):
            raise ValueError("Use a bounded WATI identifier picker search")
        data = _shape(credential_data)
        binding = hashlib.sha256(json.dumps([field_name, query, _binding(data), context.get("_user_id"), context.get("_credential_id"), context.get("_organization_id"), context.get("_workflow_id")], separators=(",", ":")).encode()).hexdigest()
        page, seen = 1, []
        if page_token:
            try:
                if not isinstance(page_token, str) or len(page_token) > 8192:
                    raise ValueError()
                saved = json.loads(base64.urlsafe_b64decode(page_token + "=" * (-len(page_token) % 4)))
                if not isinstance(saved, dict) or set(saved) != {"binding", "page", "seen"} or saved["binding"] != binding or type(saved["page"]) is not int or not 2 <= saved["page"] <= 5 or not isinstance(saved["seen"], list) or len(saved["seen"]) > 80 or any(_id(v) != v for v in saved["seen"]) or len(set(saved["seen"])) != len(saved["seen"]):
                    raise ValueError()
                page, seen = saved["page"], saved["seen"]
            except (ValueError, TypeError, UnicodeError, RecursionError):
                raise ValueError("WATI picker continuation belongs to another current actor, token, resource family or search") from None
        while page <= 5:
            cfg = operations[field_name](page_number=page, page_size=20)
            result = await cls._operation(cfg, data, context)
            if result["results"] is None:
                raise WATIAPIError("WATI nullable collection did not establish picker exhaustion; no empty-match claim")
            ids = [row["id"] for row in result["results"]]
            if set(seen).intersection(ids):
                raise WATIAPIError("WATI picker repeats resource IDs across pages")
            seen += ids
            more = result["collection_exhausted"] is not True
            if more and (page >= 5 or len(seen) > 80):
                raise WATIAPIError("WATI picker reached its five-page/80-ID bound before exhaustion; supply an exact currently accessible ID")
            options = [{"value": uid, "label": uid} for uid in ids if not query or query.casefold() in uid.casefold()]
            page += 1
            token = base64.urlsafe_b64encode(json.dumps({"binding": binding, "page": page, "seen": seen}, separators=(",", ":")).encode()).decode().rstrip("=") if more else None
            if options or not more:
                return {"options": options, "next_page_token": token}
        raise WATIAPIError("WATI picker exhaustion was not established within its bound")
