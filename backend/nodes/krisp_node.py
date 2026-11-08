"""Krisp Meeting Assistant metadata and existing meeting-content reads.

Personal scoped keys use staging credential loading and actual user/team context.
Native outputs exclude media capabilities and preserve processed-record visibility.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import re
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.credential_loader import load_credential
from utils.ssrf import guarded_async_client

API_ROOT = "https://meeting-api.krisp.ai/v1"
HIDDEN = {"ui:hidden": True}
ME_FIELDS = "email,first_name,last_name,team_id,workspace_id"
MEETING_FIELDS = "title,started_at,duration,status,source,tags,ownership"
DETAIL_FIELDS = MEETING_FIELDS + ",meeting_type,language"
ACTION_FIELDS = "title,completed,due_date,meeting_id,meeting_title,meeting_started_at"


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Enter one Krisp resource ID without URL or traversal characters.")
    return value


def _identity_id(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", value):
        raise ValueError("Use a positive Krisp user, team or workspace ID.")
    return value


def _aware(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed
    except (TypeError, AttributeError, ValueError):
        raise ValueError("Use a timezone-aware ISO 8601 datetime.") from None


def _selector(field):
    return {"x-dynamic-options": {"field_name": field, "searchable": True, "allow_custom": True},
        "x-resource-type": "krisp_" + field.removesuffix("_id")}


class KrispAPIKeyCredential(BaseModel):
    credential_type: Literal["krisp_api_key"] = Field("krisp_api_key", json_schema_extra=HIDDEN)
    api_key: str = Field(..., min_length=103, max_length=103, pattern=r"^krsp_u_[0-9a-fA-F]{96}$",
        title="Personal API Key", description="Krisp Settings → Integrations → API. A Read scope and an eligible paid/trial plan are required.",
        json_schema_extra={"ui:widget": "password"})
    scopes: list[Literal["read", "write"]] = Field(default_factory=lambda: ["read"], min_length=1, max_length=2,
        title="Configured Key Scopes", description="Copy the key's configured Read/Write scopes. This form does not grant permissions. These operations require Read.")
    expires_at: Optional[str] = Field(None, title="Actual Key Expiry",
        description="Optional actual aware ISO 8601 expiry. Leave unset for a no-expiration key; do not invent a new 90-day lifetime.")
    expected_user_id: Optional[str] = Field(None, title="Expected Krisp User ID")
    expected_team_id: Optional[str] = Field(None, title="Expected Team ID")
    expected_workspace_id: Optional[str] = Field(None, title="Expected Workspace ID",
        description="Optional expected IDs from /me. A mismatch fails before meeting data is requested.")
    model_config = ConfigDict(title="Krisp API Key", extra="ignore", json_schema_extra={
        "x-credential-url": "https://meeting-api-docs.krisp.ai/docs/getting-started"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key_value(cls, value):
        return clean_secret(value)

    @field_validator("scopes")
    @classmethod
    def scopes_value(cls, value):
        return sorted(set(value))

    @field_validator("expires_at")
    @classmethod
    def expiry_value(cls, value):
        if value is not None:
            _aware(value)
        return value

    @field_validator("expected_user_id", "expected_team_id", "expected_workspace_id", mode="before")
    @classmethod
    def expected_value(cls, value):
        return _identity_id(value) if value is not None else None


def _credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != "krisp_api_key":
        raise ValueError("Use a current Krisp personal API-key connection.")
    try:
        shaped = KrispAPIKeyCredential.model_validate({key: data[key] for key in
            KrispAPIKeyCredential.model_fields if key in data}).model_dump(mode="json")
    except Exception:
        raise ValueError("Krisp credential fields or expected account context are invalid.") from None
    if "read" not in shaped["scopes"]:
        raise ValueError("A Krisp key configured with Read scope is required.")
    if shaped["expires_at"] and _aware(shaped["expires_at"]) <= datetime.now(timezone.utc):
        raise ValueError("The supplied Krisp key has expired; replace it with a current key.")
    return {**data, **shaped}


class KrispOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KrispPage(KrispOperation):
    page_token: Optional[str] = Field(None, max_length=16000,
        description="Continuation from this exact key, account context, endpoint, parent and filters. No automatic page drain.")


class KrispMeeting(KrispOperation):
    meeting_id: str = Field(..., title="Processed Meeting", json_schema_extra=_selector("meeting_id"))
    _meeting_value = field_validator("meeting_id", mode="before")(_id)


class KrispGetIdentityConfig(KrispOperation):
    operation: Literal["get_identity"] = Field("get_identity", json_schema_extra={"x-display-name": "Get Key Holder Identity", "x-category": "Account"})


class KrispListMeetingsConfig(KrispPage):
    operation: Literal["list_meetings"] = Field("list_meetings", json_schema_extra={"x-display-name": "List Processed Meetings", "x-category": "Meetings"})
    limit: int = Field(20, ge=1, le=100)
    ownership: Literal["all", "mine", "shared"] = "all"
    sort_by: Literal["date", "duration", "last_modified"] = "date"
    order: Literal["newest", "oldest"] = "newest"
    query: Optional[str] = Field(None, max_length=200, description="Provider search across titles, notes and participants; transcript text is not searched.")
    from_time: Optional[str] = Field(None, title="From (ISO 8601)")
    to_time: Optional[str] = Field(None, title="To (ISO 8601)")
    tag_id: Optional[str] = Field(None, title="Tag", json_schema_extra=_selector("tag_id"))
    _tag_value = field_validator("tag_id", mode="before")(lambda value: _id(value) if value is not None else None)

    @model_validator(mode="after")
    def time_bounds(self):
        start = _aware(self.from_time) if self.from_time is not None else None
        end = _aware(self.to_time) if self.to_time is not None else None
        if start and end and start > end:
            raise ValueError("From must precede To.")
        return self


class KrispGetMeetingConfig(KrispMeeting):
    operation: Literal["get_meeting"] = Field("get_meeting", json_schema_extra={"x-display-name": "Get Meeting Metadata", "x-category": "Meetings"})


class KrispGetNotesConfig(KrispMeeting):
    operation: Literal["get_meeting_notes"] = Field("get_meeting_notes", json_schema_extra={"x-display-name": "Get Existing Meeting Notes", "x-category": "Meeting Content"})


class KrispGetTranscriptConfig(KrispMeeting):
    operation: Literal["get_meeting_transcript"] = Field("get_meeting_transcript", json_schema_extra={"x-display-name": "Get Existing Transcript", "x-category": "Meeting Content"})
    include_speaker_names: bool = Field(False, description="Include the existing diarization-index name map. Photos and media URLs remain excluded.")


class KrispGetParticipantsConfig(KrispMeeting):
    operation: Literal["get_meeting_participants"] = Field("get_meeting_participants", json_schema_extra={"x-display-name": "Get Meeting Participants", "x-category": "Meeting Content"})


class KrispGetMeetingTagsConfig(KrispMeeting):
    operation: Literal["get_meeting_tags"] = Field("get_meeting_tags", json_schema_extra={"x-display-name": "Get Meeting Tag Names", "x-category": "Tags"})


class KrispActionPage(KrispPage):
    limit: int = Field(50, ge=1, le=200)
    completed: Optional[bool] = Field(None, description="False means incomplete only; unset means all statuses.")
    assigned_to_me: bool = False
    include_assignee: bool = Field(False, description="Explicitly include existing assignee names/email; avatar and media URLs are excluded.")


class KrispListActionItemsConfig(KrispActionPage):
    operation: Literal["list_action_items"] = Field("list_action_items", json_schema_extra={"x-display-name": "List Action Items", "x-category": "Action Items"})


class KrispListMeetingActionItemsConfig(KrispMeeting, KrispActionPage):
    operation: Literal["list_meeting_action_items"] = Field("list_meeting_action_items", json_schema_extra={"x-display-name": "List Meeting Action Items From Page", "x-category": "Action Items"})


class KrispListTagsConfig(KrispOperation):
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"x-display-name": "List Tags", "x-category": "Tags"})
    query: Optional[str] = Field(None, max_length=200, description="Provider prefix search over tag names; at most 100 tags.")


KrispConfig = Annotated[Union[KrispGetIdentityConfig, KrispListMeetingsConfig, KrispGetMeetingConfig,
    KrispGetNotesConfig, KrispGetTranscriptConfig, KrispGetParticipantsConfig, KrispGetMeetingTagsConfig,
    KrispListActionItemsConfig, KrispListMeetingActionItemsConfig, KrispListTagsConfig], Field(discriminator="operation")]


class KrispNodeConfig(NodeConfig[KrispConfig, KrispAPIKeyCredential]):
    pass


class KrispProcessingError(RuntimeError):
    http_status = 409


async def _request(data, path, *, params):
    data = _credential(data)
    allowed = {"/me": {"fields"}, "/tags": {"fields", "q"},
        "/meetings": {"limit", "cursor", "ownership", "sort_by", "order", "q", "from", "to", "tags", "fields"},
        "/action-items": {"limit", "cursor", "completed", "assigned_to_me", "fields"}}
    permitted = allowed.get(path)
    if permitted is None and re.fullmatch(r"/meetings/[A-Za-z0-9_-]{1,128}", path):
        permitted = {"fields"}
    if permitted is None or set(params) - permitted:
        raise ValueError("Unsupported Krisp resource or query fields.")
    try:
        async with guarded_async_client(timeout=20.0, trust_env=False, follow_redirects=False) as client:
            response = await client.get(API_ROOT + path, headers={"Authorization": "Bearer " + data["api_key"],
                "Accept": "application/json"}, params=params)
    except Exception:
        raise RuntimeError("Krisp request could not complete.") from None
    if response.status_code == 409:
        raise KrispProcessingError("Krisp meeting is still processing (HTTP 409); notes and transcript availability are unverified.")
    if response.status_code != 200:
        messages = {400: "Krisp rejected the documented filters or fields.",
            401: "Krisp access is unverified; check the key's current expiry, revocation and plan entitlement.",
            403: "Krisp access is unverified; check the key's Read scope and current meeting visibility.",
            404: "Krisp meeting is unavailable or not visible to this key holder.",
            429: "Krisp account rate limit reached; retry later. All keys share this limit; no automatic retry occurred."}
        raise RuntimeError(messages.get(response.status_code, "Krisp returned an unexpected status."))
    if not response.content or len(response.content) > 8000000:
        raise RuntimeError("Krisp returned empty or excessive meeting data.")
    try:
        payload = response.json()
    except Exception:
        raise RuntimeError("Krisp returned malformed resource JSON.") from None
    if not isinstance(payload, (dict, list)):
        raise RuntimeError("Krisp returned malformed resource JSON.")
    if isinstance(payload, dict) and (payload.get("success") is False or any(
            key in payload and payload[key] not in (None, "", [], {}) for key in ("error", "errors"))):
        raise RuntimeError("Krisp returned an error envelope; resource access is unverified.")
    return payload


def _strings(item, fields):
    if not isinstance(item, dict):
        raise RuntimeError("Krisp returned malformed metadata.")
    out = {key: item[key] for key in fields if key in item}
    if any(value is not None and (not isinstance(value, str) or len(value) > 100000)
            for value in out.values()):
        raise RuntimeError("Krisp returned invalid text metadata.")
    return out


def _resource_id(value):
    try:
        return _id(value)
    except ValueError:
        raise RuntimeError("Krisp returned an invalid resource reference.") from None


def _person(item, *, names_only=False):
    if item is None:
        return None
    return _strings(item, ("first_name", "last_name") if names_only else ("email", "first_name", "last_name", "status"))


async def _identity(data):
    raw = await _request(data, "/me", params={"fields": ME_FIELDS})
    out = _strings(raw, ("email", "first_name", "last_name"))
    try:
        for field, expected in (("id", "expected_user_id"), ("team_id", "expected_team_id"), ("workspace_id", "expected_workspace_id")):
            out[field] = _identity_id(raw.get(field))
            if data.get(expected) is not None and data[expected] != out[field]:
                raise ValueError()
    except ValueError:
        raise RuntimeError("Krisp returned an unexpected or incomplete user/team/workspace identity.") from None
    return out


def _meeting(item, *, identity=None):
    out = _strings(item, ("title", "started_at", "status", "source", "ownership", "meeting_type", "language"))
    out["id"] = _resource_id(item.get("id"))
    if identity is not None and out["id"] != identity:
        raise RuntimeError("Krisp returned another meeting's data.")
    if "ownership" in out and out["ownership"] not in {"owned", "shared"}:
        raise RuntimeError("Krisp returned an unexpected meeting visibility class.")
    if "duration" in item:
        if item["duration"] is not None and (type(item["duration"]) is not int or item["duration"] < 0):
            raise RuntimeError("Krisp returned invalid duration seconds.")
        out["duration"] = item["duration"]
    if "tags" in item:
        if not isinstance(item["tags"], list) or len(item["tags"]) > 100 or any(
                not isinstance(tag, str) or len(tag) > 1000 for tag in item["tags"]):
            raise RuntimeError("Krisp returned invalid meeting tag names.")
        out["tags"] = item["tags"]
    return out


async def _one(data, meeting_id, *, fields=DETAIL_FIELDS):
    raw = await _request(data, "/meetings/" + meeting_id, params={"fields": fields})
    _meeting(raw, identity=meeting_id)
    return raw


def _transcript(item, *, include_names):
    if item is None:
        return None
    out = _strings(item, ("language",))
    segments = item.get("segments")
    if not isinstance(segments, list) or len(segments) > 20000:
        raise RuntimeError("Krisp transcript exceeds its bounded segment limit.")
    out["segments"] = []
    for segment in segments:
        safe = _strings(segment, ("text",))
        speaker, start, end = (segment.get(key) for key in ("speaker", "start", "end"))
        if type(speaker) is not int or type(start) not in (int, float) or type(end) not in (int, float) or not (
                math.isfinite(start) and math.isfinite(end) and 0 <= start <= end) or "text" not in safe:
            raise RuntimeError("Krisp returned invalid transcript segment data.")
        safe.update(speaker=speaker, start=start, end=end)
        out["segments"].append(safe)
    if include_names and "speakers" in item:
        speakers = item["speakers"]
        if not isinstance(speakers, dict) or len(speakers) > 1000 or any(
                not isinstance(key, str) or not re.fullmatch(r"-?[0-9]{1,10}", key) for key in speakers):
            raise RuntimeError("Krisp returned invalid diarization metadata.")
        out["speakers"] = {key: _person(value, names_only=True) for key, value in speakers.items()}
    return out


def _notes(item):
    if item is None:
        return None
    if not isinstance(item, dict):
        raise RuntimeError("Krisp returned malformed notes.")
    count = [0]
    def blocks(rows, depth=0):
        if not isinstance(rows, list) or len(rows) > 5000 or depth > 12:
            raise RuntimeError("Krisp notes exceed the nested block limit.")
        out = []
        for row in rows:
            count[0] += 1
            if count[0] > 5000:
                raise RuntimeError("Krisp notes exceed the total block limit.")
            safe = _strings(row, ("type", "text", "due_date"))
            if not isinstance(safe.get("type"), str) or not safe["type"]:
                raise RuntimeError("Krisp returned a note block without a type.")
            if "completed" in row:
                if row["completed"] is not None and type(row["completed"]) is not bool:
                    raise RuntimeError("Krisp returned invalid note action-item status.")
                safe["completed"] = row["completed"]
            if "assignee" in row:
                safe["assignee"] = _person(row["assignee"])
            if "children" in row:
                safe["children"] = blocks(row["children"], depth + 1)
            out.append(safe)
        return out
    return {"blocks": blocks(item.get("blocks"))}


def _action(item, *, include_assignee):
    out = _strings(item, ("title", "due_date", "meeting_title", "meeting_started_at"))
    out["id"] = _resource_id(item.get("id"))
    out["meeting_id"] = _resource_id(item.get("meeting_id"))
    if "completed" in item:
        if item["completed"] is not None and type(item["completed"]) is not bool:
            raise RuntimeError("Krisp returned invalid action-item status.")
        out["completed"] = item["completed"]
    if include_assignee and "assignee" in item:
        out["assignee"] = _person(item["assignee"])
    return out


async def _tags(data, query=None):
    raw = await _request(data, "/tags", params={"fields": "name,color,created_at", **({"q": query} if query else {})})
    if not isinstance(raw, list) or len(raw) > 100:
        raise RuntimeError("Krisp returned an invalid bounded tag catalog.")
    items = []
    for row in raw:
        out = _strings(row, ("name", "color", "created_at"))
        out["id"] = _resource_id(row.get("id"))
        items.append(out)
    if len({row["id"] for row in items}) != len(items):
        raise RuntimeError("Krisp returned duplicate tag IDs.")
    return items


def _page_anchor(data, path, params, parent, search):
    return {"v": 1, "path": path, "params": params, "parent": parent, "search": search,
        "scopes": data["scopes"], "expires_at": data["expires_at"],
        "expected": {key: data[key] for key in ("expected_user_id", "expected_team_id", "expected_workspace_id")}}


def _cursor(data, path, params, parent, search, *, token=None, cursor=None, identity=None):
    anchor = _page_anchor(data, path, params, parent, search)
    key = hashlib.sha256(data["api_key"].encode()).digest()
    if token is not None:
        try:
            if not isinstance(token, str) or len(token) > 16000:
                raise ValueError()
            encoded, signature = token.split(".")
            if not hmac.compare_digest(hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest(), signature):
                raise ValueError()
            value = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            current, previous_identity = value.pop("cursor"), value.pop("identity")
            if value != anchor or not isinstance(current, str) or not 1 <= len(current) <= 8000 or not isinstance(previous_identity, dict):
                raise ValueError()
            if set(previous_identity) != {"id", "team_id", "workspace_id"}:
                raise ValueError()
            for identifier in previous_identity.values():
                _identity_id(identifier)
            return current, previous_identity
        except Exception:
            raise ValueError("Krisp page token does not match the current key, account, resource, parent or filters.") from None
    encoded = base64.urlsafe_b64encode(json.dumps({**anchor, "cursor": cursor,
        "identity": {name: identity[name] for name in ("id", "team_id", "workspace_id")}},
        sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    return encoded + "." + hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()


async def _page(data, path, config, *, params, parent=None, search=None):
    current, previous_identity = _cursor(data, path, params, parent, search, token=config.page_token) if config.page_token else (None, None)
    identity = await _identity(data)
    if previous_identity is not None and previous_identity != {name: identity[name] for name in ("id", "team_id", "workspace_id")}:
        raise RuntimeError("Krisp account context changed since this page token was issued.")
    if parent is not None:
        await _one(data, parent)
    if path == "/meetings" and params.get("tags"):
        tags = await _tags(data)
        if not any(row["id"] == params["tags"] for row in tags):
            raise ValueError("The selected tag does not belong to this current key holder.")
    raw = await _request(data, path, params={**params, **({"cursor": current} if current else {})})
    field = "meetings" if path == "/meetings" else "action_items"
    if not isinstance(raw, dict) or not isinstance(raw.get(field), list) or len(raw[field]) > config.limit:
        raise RuntimeError("Krisp returned an invalid bounded resource page.")
    total = raw.get("total")
    next_cursor = raw.get("next_cursor")
    if type(total) is not int or not 0 <= total <= 100000000 or "next_cursor" not in raw or next_cursor is not None and (
            not isinstance(next_cursor, str) or not 1 <= len(next_cursor) <= 8000 or next_cursor == current):
        raise RuntimeError("Krisp returned invalid pagination metadata.")
    items = [_meeting(row) for row in raw[field]] if path == "/meetings" else [
        _action(row, include_assignee=config.include_assignee) for row in raw[field]]
    if len({row["id"] for row in items}) != len(items):
        raise RuntimeError("Krisp returned duplicate resource IDs in a page.")
    if parent is not None:
        items = [row for row in items if row["meeting_id"] == parent]
    if search:
        items = [row for row in items if search.casefold() in str(row.get("title") or row["id"]).casefold()]
    return {"items": items, "limit": config.limit, "reported_total": total,
        "next_page_token": _cursor(data, path, params, parent, search, cursor=next_cursor, identity=identity) if next_cursor else None,
        "complete": config.page_token is None and next_cursor is None and parent is None,
        **({"coverage": "Matching action items from this global page only; reported_total is across visible meetings."} if parent else {})}


class KrispNode(WorkflowNode):
    integration_type = "automation-krisp"
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="list_meetings", operation_arguments={"limit": 3},
        noun="meetings", label_keys=("title",), identity_operation="get_identity", identity_keys=("email",), proves="account")

    @classmethod
    def get_config_model(cls):
        return KrispNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_id:
            return _credential(credential_data)
        if not user_id:
            raise ValueError("A signed-in user is required for a saved Krisp connection.")
        current = await load_credential(pool, user_id, credential_id, raise_on_error=True)
        return _credential(current)

    @classmethod
    async def validate_credential_access(cls, credential_data):
        await _identity(_credential(credential_data))
        return {"valid": True}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        data = _credential(credential_data)
        search = search.strip() if isinstance(search, str) and search.strip() else None
        if search and len(search) > 200:
            raise ValueError("Krisp selector search exceeds the limit.")
        if field_name == "tag_id":
            if page_token:
                raise ValueError("Krisp tags are a bounded single-response selector.")
            await _identity(data)
            tags = await _tags(data, search)
            return {"options": [{"value": row["id"], "label": row.get("name") or row["id"]} for row in tags], "next_page_token": None}
        if field_name != "meeting_id":
            raise ValueError("Unsupported Krisp selector.")
        config = KrispListMeetingsConfig(limit=50, page_token=page_token, query=search)
        params = {"limit": 50, "ownership": "all", "sort_by": "date", "order": "newest", "fields": MEETING_FIELDS}
        if search:
            params["q"] = search
        result = await _page(data, "/meetings", config, params=params)
        return {"options": [{"value": row["id"], "label": row.get("title") or row["id"]} for row in result["items"]],
            "next_page_token": result["next_page_token"]}

    async def execute(self, inputs):
        if not isinstance(self.config, KrispNodeConfig) or not self.config.credentials:
            raise ValueError("Krisp configuration and a connection are required.")
        c = self.config.config
        data = await self.freshen_credential(self.config.credentials.model_dump(mode="json"),
            pool=(self.node_data or {}).get("_approval_pool"), user_id=self.user_id,
            credential_id=(self.node_data or {}).get("credential_id"))
        op = c.operation
        if op == "list_meetings":
            params = {"limit": c.limit, "ownership": c.ownership, "sort_by": c.sort_by, "order": c.order, "fields": MEETING_FIELDS}
            for key, value in (("q", c.query), ("from", c.from_time), ("to", c.to_time), ("tags", c.tag_id)):
                if value is not None:
                    params[key] = value
            return await _page(data, "/meetings", c, params=params)
        if op in {"list_action_items", "list_meeting_action_items"}:
            params = {"limit": c.limit, "assigned_to_me": str(c.assigned_to_me).lower(),
                "fields": ACTION_FIELDS + (",assignee" if c.include_assignee else "")}
            if c.completed is not None:
                params["completed"] = str(c.completed).lower()
            return await _page(data, "/action-items", c, params=params,
                parent=c.meeting_id if op == "list_meeting_action_items" else None)
        identity = await _identity(data)
        if op == "get_identity":
            return identity
        if op == "list_tags":
            return {"items": await _tags(data, c.query), "next_page_token": None, "coverage": "Provider returns at most 100 tags."}
        fields = {"get_meeting": DETAIL_FIELDS, "get_meeting_notes": DETAIL_FIELDS + ",notes",
            "get_meeting_transcript": DETAIL_FIELDS + ",transcript", "get_meeting_participants": DETAIL_FIELDS + ",participants",
            "get_meeting_tags": DETAIL_FIELDS}[op]
        raw = await _one(data, c.meeting_id, fields=fields)
        if op == "get_meeting":
            return {"meeting": _meeting(raw)}
        if op == "get_meeting_notes":
            if "notes" not in raw:
                raise RuntimeError("Krisp omitted explicitly requested notes; content availability is unverified.")
            return {"meeting_id": c.meeting_id, "notes": _notes(raw["notes"])}
        if op == "get_meeting_transcript":
            if "transcript" not in raw:
                raise RuntimeError("Krisp omitted the explicitly requested transcript; content availability is unverified.")
            return {"meeting_id": c.meeting_id, "transcript": _transcript(raw["transcript"], include_names=c.include_speaker_names), "time_unit": "seconds"}
        if op == "get_meeting_participants":
            participants = raw.get("participants")
            if not isinstance(participants, list) or len(participants) > 1000:
                raise RuntimeError("Krisp returned an invalid bounded participant list.")
            return {"meeting_id": c.meeting_id, "participants": [_person(row) for row in participants]}
        if "tags" not in raw:
            raise RuntimeError("Krisp omitted explicitly requested tag names; tag availability is unverified.")
        return {"meeting_id": c.meeting_id, "tag_names": _meeting(raw)["tags"]}
