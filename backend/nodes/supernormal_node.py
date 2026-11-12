"""Native Supernormal meeting-service reads with issued scoped header keys.

The fixed v1 API exposes a real user identity and protected calendar/recording
reads. Raw signed URLs, invites, capture toggles and agent actions are excluded;
spoken text/meeting notes are explicit opt-ins, never default output.
"""
from datetime import datetime, timedelta
import json
import math
import re
from typing import Annotated, Any, Dict, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.supernormal_authority import SupernormalAuthorityStore, CURRENT_ORGANIZATION
from utils.ssrf import SSRFError, guarded_async_client

FAMILY = "supernormal_api_key"
BASE_URL = "https://api.supernormal.com/api/v1"
MAX_BYTES, MAX_RECORDS, MAX_SEGMENTS = 2 * 1024 * 1024, 250, 2000
READ_SCOPES = {"user:read", "recordings:read", "calendar_events:read"}


def _text(value, *, maximum=500, empty=False, multiline=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()): raise ValueError("Use bounded Supernormal text")
    if any((ord(c) < 32 and not (multiline and c in "\n\r\t")) or ord(c) == 127 for c in value): raise ValueError("Supernormal text contains unsupported control characters")
    return value


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value): raise ValueError("Use an explicit Supernormal resource ID without a URL/path")
    return value


def _date(value):
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None: raise ValueError("Use a timezone-aware date")
        return value
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)", value): raise ValueError("Use a timezone-aware ISO8601 date")
    return value


def _safe_text(value, *, maximum=500):
    # Even opted-in prose cannot return a signed link copied into meeting text.
    return re.sub(r"https?://[^\s<>\"']+", "[link omitted]", _text(value, maximum=maximum, empty=True, multiline=True), flags=re.IGNORECASE)


class SupernormalAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Supernormal API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.supernormal.com/settings",
        "x-credential-instructions": "Supply an already-issued Supernormal scoped API key and its actual granted read scopes. The fixed v1 API sends X-API-TOKEN, not Bearer/Basic. user:read is required for the real identity probe; add recordings:read or calendar_events:read only when issued for those operations. API entitlement is account-dependent and not verified here. No OAuth/global client or key creation is automated."})
    credential_type: Literal["supernormal_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Existing Scoped Supernormal API Token", repr=False, json_schema_extra={"ui:widget": "password"})
    scopes: list[Literal["user:read", "recordings:read", "calendar_events:read"]] = Field(..., min_length=1, max_length=3, title="Actual Granted Read Scopes", description="Enter only these scopes actually issued to the key. This is not an API scope-grant request; unknown scope requires issuer clarification.")
    expected_user_id: str | None = Field(None, title="Expected User ID (if known)", description="Optional actual /user ID. If supplied, every operation refuses a different principal. Absence is unknown, not filled from the current app or a guessed account.")

    @model_validator(mode="before")
    @classmethod
    def issued_only(cls, raw):
        if isinstance(raw, dict) and any(raw.get(k) is not None for k in ("access_token", "refresh_token", "api_key", "token_type", "expires_at", "scope", "client_id", "client_secret", "base_url", "host", "headers", "organization_id", "account_id")):
            raise ValueError("Use only the issued Supernormal header-token family")
        return raw

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = _text(value, maximum=4096)
        if any(c.isspace() for c in value): raise ValueError("Use the raw issued API token")
        return clean_secret(value, field_name="Supernormal API token")

    @field_validator("expected_user_id", mode="before")
    @classmethod
    def principal(cls, value): return None if value is None else _id(value)

    @field_validator("scopes", mode="before")
    @classmethod
    def actual_scopes(cls, value):
        if not isinstance(value, list) or not value or any(type(v) is not str or v not in READ_SCOPES for v in value) or len(set(value)) != len(value) or "user:read" not in value:
            raise ValueError("Supply distinct actual read scopes including user:read")
        return sorted(value)


# Supernormal's own MCP server: agents get its tools through a person's Supernormal sign-in.
SupernormalMcpCredential = mcp_credential("supernormal", "https://api.supernormal.com/mcp", app="Supernormal")
SupernormalCredential = Union[SupernormalAPITokenCredential, SupernormalMcpCredential]


def _credential(raw):
    if isinstance(raw, SupernormalAPITokenCredential): raw = raw.model_dump(mode="json")
    if not isinstance(raw, dict) or raw.get("credential_type") != FAMILY: raise ValueError("Select the authoritative Supernormal API Token family")
    try: return SupernormalAPITokenCredential.model_validate(raw)
    except Exception: raise ValueError("Supernormal issued token, user binding or scope shape is unsupported") from None


def _stored(raw): return _credential(raw).model_dump(mode="json")


class _CurrentCredential(dict):
    def __init__(self, data, store):
        super().__init__(data)
        self.store, self.anchor = store, self.identity(store.current)

    @staticmethod
    def identity(row):
        return tuple(getattr(row, k) for k in ("credential_id", "caller_id", "principal_id", "organization_id", "current_organization", "workflow_id", "owner_id", "credential_type", "token_version"))

    async def reload(self):
        try:
            raw = await self.store.load()
            if self.identity(self.store.current) != self.anchor or _stored(raw) != _stored(self): raise ValueError()
        except Exception: raise ValueError("Supernormal current saved grant or authority changed") from None

    def __repr__(self): return "<Supernormal current credential>"


def _op(value, title, category):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": category, "x-is-trigger": False})


class _Config(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class SupernormalUserConfig(_Config):
    operation: Literal["get_user"] = _op("get_user", "Get Verified User Identity", "Account")


class SupernormalCalendarConfig(_Config):
    operation: Literal["list_upcoming_calendar_events"] = _op("list_upcoming_calendar_events", "List Upcoming Calendar Metadata", "Calendar")
    from_date: datetime = Field(..., title="From Date (ISO8601)", description="Explicit timezone-aware bounded calendar window; sent as the documented from parameter.")
    to_date: datetime = Field(..., title="Through Date (ISO8601)", description="Sent as to. Node window is at most31 days; this is a local privacy bound, not a claimed provider limit.")

    @field_validator("from_date", "to_date", mode="before")
    @classmethod
    def dates(cls, value): return _date(value)

    @model_validator(mode="after")
    def window(self):
        if self.to_date < self.from_date or self.to_date - self.from_date > timedelta(days=31): raise ValueError("Use an ordered calendar window of at most31 days")
        return self


class _Visibility(_Config):
    visibility: Literal["all", "organization", "shared_with_me"] = Field("all", title="Recording Picker Visibility", description="Documented list filter. all may include organization/shared recordings; it is not a private-only flag. The direct get route uses provider access to the selected ID, not a fabricated visibility parameter.")


class SupernormalRecordingsConfig(_Visibility):
    operation: Literal["list_recordings"] = _op("list_recordings", "List Recording Metadata", "Recordings")
    page: int = Field(1, strict=True, ge=1, le=10000, title="Numeric Page", description="One page; subsequent numeric page comes only from meta.next_page. No page-size parameter is documented.")
    include_meeting_text: bool = Field(False, strict=True, title="Include Meeting Summary", description="Explicit opt-in to summary text; URLs are omitted and text remains bounded. Owner email/avatar is always omitted.")


class SupernormalRecordingConfig(_Visibility):
    operation: Literal["get_recording"] = _op("get_recording", "Get Selected Recording Metadata", "Recordings")
    recording_id: str = Field(..., title="Explicit Accessible Recording ID", json_schema_extra={"x-resource-type": "recording_id", "x-dynamic-options": {"field_name": "recording_id", "depends_on": "visibility", "allow_custom": True, "auto_select_sole_option": False}})
    include_meeting_text: bool = Field(False, strict=True, title="Include Meeting Summary and Notes", description="False returns metadata only. True includes documented summary/notes/meeting_summary, with links omitted and bounded text.")

    @field_validator("recording_id", mode="before")
    @classmethod
    def resource(cls, value): return _id(value)


class SupernormalTranscriptConfig(_Visibility):
    operation: Literal["get_transcript"] = _op("get_transcript", "Read Selected Recording Transcript", "Recordings")
    recording_id: str = Field(..., title="Explicit Accessible Recording ID", json_schema_extra={"x-resource-type": "recording_id", "x-dynamic-options": {"field_name": "recording_id", "depends_on": "visibility", "allow_custom": True, "auto_select_sole_option": False}})
    include_text: bool = Field(False, strict=True, title="Include Spoken Text", description="False returns segment timing only. True deliberately returns bounded spoken content with links omitted.")
    include_speaker_names: bool = Field(False, strict=True, title="Include Speaker Labels/Names", description="Explicit opt-in to original_speaker, assigned_speaker_name and author_name. None are returned by default.")

    @field_validator("recording_id", mode="before")
    @classmethod
    def resource(cls, value): return _id(value)


SupernormalOperation = Annotated[Union[SupernormalUserConfig, SupernormalCalendarConfig, SupernormalRecordingsConfig, SupernormalRecordingConfig, SupernormalTranscriptConfig], Field(discriminator="operation")]


class SupernormalNodeConfig(NodeConfig[SupernormalOperation, SupernormalCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _error(operation, message, *, code="contract_or_authority_mismatch", status=None, executed=False):
    return {"status": "error", "action": operation, "error": message, "error_code": code, "executed": executed,
            **({"http_status": status, "status_code": status} if status is not None else {}), **({"_halt_downstream": True} if status not in {401, 403} else {})}


class _ProviderError(Exception):
    def __init__(self, result): self.result = result


class _Session:
    def __init__(self, raw, operation):
        self.raw, self.key, self.operation = raw, _credential(raw), operation
        self.attempted, self.status = False, None

    async def get(self, path, scope, *, params=None):
        try:
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            key = _credential(self.raw)
            if scope not in key.scopes: raise ValueError("Actual Supernormal grant lacks the required read scope")
            async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
                self.attempted = True
                async with client.stream("GET", BASE_URL + path, params=params, headers={"X-API-TOKEN": key.api_token, "Content-Type": "application/json", "Accept": "application/json"}) as response:
                    self.status = response.status_code
                    if self.status != 200:
                        raise _ProviderError(_error(self.operation, {400: "Supernormal rejected this request", 401: "Supernormal rejected this issued token", 403: "Supernormal refused this token scope or resource access", 404: "Supernormal did not find the selected recording", 429: "Supernormal rate limit was reached; no retry occurred"}.get(self.status, "Supernormal refused this request; no retry occurred"), code="provider_error", status=self.status, executed=True))
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > MAX_BYTES: raise ValueError()
                        raw.extend(chunk)
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            payload = json.loads(raw)
            if not isinstance(payload, (dict, list)): raise ValueError()
            return payload
        except _ProviderError: raise
        except (httpx.HTTPError, SSRFError):
            raise _ProviderError(_error(self.operation, "Supernormal transport could not be verified; no retry occurred", code="transport_error", executed=self.attempted)) from None


def _rows(rows, maximum=MAX_RECORDS):
    if not isinstance(rows, list) or len(rows) > maximum or any(not isinstance(row, dict) for row in rows): raise ValueError("Supernormal bounded collection differs from its contract")
    return rows


def _projection(raw, texts=(), integers=(), booleans=()):
    if not isinstance(raw, dict): raise ValueError()
    out = {}
    for name in texts:
        if raw.get(name) is not None: out[name] = _safe_text(raw[name])
    for name in integers:
        if raw.get(name) is not None:
            if type(raw[name]) is not int or not 0 <= raw[name] <= 2**63-1: raise ValueError()
            out[name] = raw[name]
    for name in booleans:
        if raw.get(name) is not None:
            if type(raw[name]) is not bool: raise ValueError()
            out[name] = raw[name]
    return out


def _user(raw):
    out = {"id": _id(raw.get("id")), **_projection(raw, ("first_name", "last_name"))}
    # Documented names form a display alias; verified ID remains authoritative.
    out["name"] = " ".join(filter(None, (out.get("first_name"), out.get("last_name")))).strip() or out["id"]
    return out


def _recording(raw, *, content=False, detail=False):
    out = {"id": _id(raw.get("id")), **_projection(raw, ("title", "status", "recorded_at", "completed_at"), ("duration_seconds", "participants_count"))}
    if raw.get("owner") is not None:
        if not isinstance(raw["owner"], dict): raise ValueError()
        out["owner_id"] = _id(raw["owner"].get("id"))
    if content:
        for name in (("summary", "notes", "meeting_summary") if detail else ("summary",)):
            if raw.get(name) is not None: out[name] = _safe_text(raw[name], maximum=20000)
    return out


class SupernormalNode(WorkflowNode):
    integration_type = "automation-supernormal"
    credential_provider_labels = {"supernormal": "Supernormal Account"}
    workflow_credential_refresh = True
    edit_examples = ["Show my verified Supernormal user", "Read recording metadata without notes or signed links", "Read transcript segment timings for a selected recording"]
    connection_evidence = ConnectionEvidence(identity_operation="get_user", noun="user", label_keys=("name", "id"), proves="account")

    @classmethod
    def get_config_model(cls): return SupernormalNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: _stored(config_data["credentials"])
            except ValueError as error: raise ConfigValidationError(str(error)) from None
        return super().parse_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data: Dict[str, Any] | None, *, pool=None, user_id: str | None = None, credential_id: str | None = None) -> Dict[str, Any] | None:
        if credential_data is None: return None
        return await cls._load_current_credential(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)

    @classmethod
    async def _load_current_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=CURRENT_ORGANIZATION):
        _credential(credential_data)
        if not credential_id: return credential_data
        if organization_id is None and not workflow_id: organization_id = CURRENT_ORGANIZATION
        store = SupernormalAuthorityStore(pool, user_id, credential_id, credential_type=FAMILY, validate=_stored, grant_fields=("api_token", "scopes", "expected_user_id"), organization_id=organization_id, workflow_id=workflow_id, allow_same_grant_retry=False)
        try: return _CurrentCredential(await store.load(), store)
        except Exception: raise ValueError("Supernormal saved scoped key is unavailable under current access") from None

    @classmethod
    async def validate_credential_access(cls, credential_data, *, validation_context=None):
        try: _stored(credential_data)
        except ValueError: return {"valid": False, "error": "Supernormal issued header-token family or actual scope shape is unsupported"}
        if validation_context is None: return {"valid": True, "provider_verified": False}
        await validation_context.revalidate()
        result = await validation_context.run_operation("get_user")
        await validation_context.revalidate()
        if result.get("status") == "success": return {"valid": True, "provider_verified": True}
        return {"valid": False if result.get("status_code") in {401, 403} else None, "error": result.get("error", "Supernormal access could not be verified")}

    @classmethod
    async def _dispatch(cls, credential, config):
        session = _Session(credential, config.operation)
        try:
            action = config.operation
            required = "calendar_events:read" if action == "list_upcoming_calendar_events" else "recordings:read" if action != "get_user" else "user:read"
            if required not in session.key.scopes: raise ValueError("Actual Supernormal scope is missing")
            user = _user(await session.get("/user", "user:read"))
            if session.key.expected_user_id is not None and user["id"] != session.key.expected_user_id: raise ValueError("Supernormal returned a different expected user")
            if action == "get_user": out = {"data": {"user": user}, "principal_identity_proven": True}
            elif action == "list_upcoming_calendar_events":
                rows = _rows(await session.get("/user/calendar_events", "calendar_events:read", params={"from": config.from_date.isoformat(), "to": config.to_date.isoformat()}))
                events = [{"id": _id(r.get("id")), **_projection(r, ("name", "start", "end", "platform_name"), booleans=("is_recurring", "is_blocked_from_capture", "scheduled_to_record"))} for r in rows]
                if len({r["id"] for r in events}) != len(events): raise ValueError()
                out = {"data": events, "pagination_documented": False}
            elif action == "list_recordings":
                raw = await session.get("/recordings", "recordings:read", params={"page": config.page, "visibility": config.visibility})
                if not isinstance(raw, dict) or not isinstance(raw.get("meta"), dict): raise ValueError()
                meta = raw["meta"]
                for name in ("current_page", "total_pages"):
                    if type(meta.get(name)) is not int or not 0 <= meta[name] <= 10000: raise ValueError()
                if meta["current_page"] != config.page: raise ValueError()
                next_page = meta.get("next_page")
                if "next_page" not in meta or (next_page is not None and (type(next_page) is not int or not config.page < next_page <= min(meta["total_pages"], 10000))): raise ValueError()
                rows = [_recording(r, content=config.include_meeting_text) for r in _rows(raw.get("recordings"))]
                if len({r["id"] for r in rows}) != len(rows): raise ValueError()
                out = {"data": rows, "meta": {k: meta[k] for k in ("current_page", "next_page", "total_pages")}, "visibility": config.visibility, "next_page_token": str(next_page) if next_page is not None else None, "has_more": next_page is not None}
            elif action in {"get_recording", "get_transcript"}:
                recording = _recording(await session.get(f"/recordings/{config.recording_id}", "recordings:read"), content=isinstance(config, SupernormalRecordingConfig) and config.include_meeting_text, detail=True)
                if recording["id"] != config.recording_id: raise ValueError("Selected recording differs from returned parent")
                if action == "get_recording": out = {"data": recording}
                else:
                    rows = _rows(await session.get(f"/recordings/{config.recording_id}/transcript", "recordings:read"), MAX_SEGMENTS)
                    segments, previous_start = [], -1
                    for row in rows:
                        start, end = row.get("start"), row.get("end")
                        if type(start) not in {int, float} or type(end) not in {int, float} or not math.isfinite(start) or not math.isfinite(end) or not 0 <= start <= end <= 604800 or start < previous_start: raise ValueError()
                        previous_start = start
                        segment = {"start": start, "end": end}
                        if config.include_text: segment["content"] = _safe_text(row.get("content"), maximum=20000)
                        if config.include_speaker_names: segment.update(_projection(row, ("original_speaker", "assigned_speaker_name", "author_name")))
                        segments.append(segment)
                    out = {"data": segments, "recording_id": config.recording_id, "text_included": config.include_text, "speaker_names_included": config.include_speaker_names, "pagination_documented": False}
            else: raise ValueError()
            encoded = json.dumps({"verified_user_id": user["id"], **out}, ensure_ascii=False, allow_nan=False)
            if session.key.api_token in encoded: raise ValueError()
            return {"status": "success", "action": action, "executed": True, "http_status": session.status, "verified_user_id": user["id"], **out}
        except _ProviderError as error: return error.result
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, SSRFError):
            return _error(config.operation, "Supernormal current authority, expected user, selected recording or bounded response could not be established; no retry occurred", executed=session.attempted)

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        if field_name != "recording_id": raise ValueError("Unsupported Supernormal selector")
        context = context or {}
        if context.get("visibility") not in {"all", "organization", "shared_with_me"}: raise ValueError("Select explicit recording visibility before lookup")
        if page_token is not None and (not isinstance(page_token, str) or not re.fullmatch(r"[1-9]\d{0,4}", page_token) or int(page_token) > 10000): raise ValueError("Invalid Supernormal numeric page token")
        if search is not None: _text(search, maximum=100, empty=True)
        result = await cls._dispatch(credential_data, SupernormalRecordingsConfig(visibility=context["visibility"], page=int(page_token or "1")))
        if result["status"] != "success": raise ValueError(result["error"])
        options = [{"value": r["id"], "label": r.get("title") or r["id"]} for r in result["data"]]
        if search: options = [r for r in options if search.casefold() in r["label"].casefold()]
        return {"options": options, "has_more": result["has_more"], "next_page_token": result["next_page_token"]}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        initial = _credential(self.node_data.get("credentials") if self.node_data.get("credentials") is not None else self.config.credentials)
        credential = await self._load_current_credential(initial.model_dump(mode="json"), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data["credential_id"], workflow_id=self.workflow_id, organization_id=self.organization_id) if self.node_data.get("credential_id") else initial
        return await self._dispatch(credential, self.config.config)
