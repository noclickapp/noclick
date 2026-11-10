"""Nylas v3: explicitly bound grants, private metadata and ordinary draft CRUD.

Issued credentials only. No provider OAuth mint, send, invitation, bot, attachment
download or arbitrary endpoint. Provider-backed writes change the connected account.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from copy import deepcopy
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret, is_placeholder, is_url_shaped
from uuid import UUID

CURRENT_ORGANIZATION = object()
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-nylas"
FAMILIES = ("nylas_api_key", "nylas_access_token")
HOSTS = {"us": "https://api.us.nylas.com", "eu": "https://api.eu.nylas.com"}
PROVIDERS = {"ews", "google", "icloud", "imap", "microsoft", "virtual-calendar", "yahoo", "zoom", "nylas"}


def resource_id(value: Any) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > 2048
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or is_url_shaped(value) or is_placeholder(value)
            or value.strip() in {"me", "primary", ".", ".."}):
        raise ValueError("Use the actual Nylas resource ID, without a URL or alias.")
    return value.strip()


class _Credential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    region: Literal["us", "eu"] = Field("us", title="Nylas Region")
    grant_id: str = Field(..., title="Connected Grant ID", description="Actual v3 grant ID. Every operation stays bound to this grant.")
    _id = field_validator("grant_id", mode="before")(resource_id)

    @field_validator("api_key", "access_token", mode="before", check_fields=False)
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the issued Nylas credential.")
        value = clean_secret(value, field_name="Nylas credential")
        if not value or len(value) > 8192 or any(c.isspace() for c in value):
            raise ValueError("Paste the issued Nylas credential without the Bearer prefix.")
        return value


class NylasAPIKeyCredential(_Credential):
    model_config = ConfigDict(title="Nylas API Key", hide_input_in_errors=True,
                              json_schema_extra={"x-credential-url": "https://dashboard-v3.nylas.com/"})
    credential_type: Literal["nylas_api_key"] = Field("nylas_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"},
                         description="Issued Nylas v3 application API key. Provider grant permissions still apply.")


class NylasAccessTokenCredential(_Credential):
    model_config = ConfigDict(title="Nylas Access Token", hide_input_in_errors=True,
                              json_schema_extra={"x-credential-url": "https://developer.nylas.com/docs/v3/auth/hosted-oauth-accesstoken/"})
    credential_type: Literal["nylas_access_token"] = Field("nylas_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Issued Access Token", json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[int] = Field(None, title="Known Expiry (Unix Seconds)", strict=True, ge=1,
                                     description="Only enter an expiry supplied by your authorization system. Reconnect when expired; this node does not refresh tokens.")


NylasCredential = Union[NylasAPIKeyCredential, NylasAccessTokenCredential]
CREDENTIAL_ADAPTER = TypeAdapter(NylasCredential)


def shape_credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") not in FAMILIES:
        raise ValueError("Connect a Nylas API Key or issued Nylas Access Token credential.")
    model = NylasAPIKeyCredential if raw["credential_type"] == FAMILIES[0] else NylasAccessTokenCredential
    try:
        data = model.model_validate(raw).model_dump()
    except Exception:
        raise ValueError("Nylas credential shape or grant binding is invalid.") from None
    if data.get("expires_at") is not None and data["expires_at"] <= int(time.time()):
        raise ValueError("Nylas access token expired; reconnect with a current token.")
    for key in ("token_version", "updated_at"):
        if key in raw:
            data[key] = raw[key]
    return data


def picker(field, parent=None):
    meta = {"field_name": field, "searchable": True, "allow_custom": True}
    if parent:
        meta["depends_on"] = [parent]
    return {"x-dynamic-options": meta, "x-resource-type": "nylas_" + field.removesuffix("_id")}


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    include_content: bool = Field(False, title="Include Private Content", description="Opt in to names, subjects, message bodies or contact fields in this operation's output. Treat output as private.")

    @field_validator("message_id", "thread_id", "folder_id", "calendar_id", "event_id", "contact_id", "draft_id", mode="before", check_fields=False)
    @classmethod
    def ids(cls, value):
        return resource_id(value)


class _Page(_Operation):
    limit: int = Field(50, strict=True, ge=1, le=100, description="Local page cap 100; provider supports up to 200.")
    page_token: Optional[str] = Field(None, title="Bound Next Page Token", description="Use only the token returned by this same operation, credential and filters.")


class GetGrantConfig(_Operation):
    operation: Literal["get_grant"] = "get_grant"


class ListEventsConfig(_Page):
    operation: Literal["list_events"] = "list_events"
    calendar_id: str = Field(..., json_schema_extra=picker("calendar_id"))
    start: int = Field(..., strict=True, ge=0, description="Unix seconds; explicit bounded time window.")
    end: int = Field(..., strict=True, ge=1)

    @model_validator(mode="after")
    def window(self):
        if self.end <= self.start or self.end - self.start > 31 * 86400:
            raise ValueError("Choose an event window between 1 second and 31 days.")
        return self


class GetEventConfig(_Operation):
    operation: Literal["get_event"] = "get_event"
    calendar_id: str = Field(..., json_schema_extra=picker("calendar_id"))
    event_id: str = Field(..., json_schema_extra={"x-resource-type": "nylas_event", "x-dynamic-options": {
        "field_name": "event_id", "allow_custom": True, "searchable": True, "depends_on": ["calendar_id", "start", "end"]}})
    start: Optional[int] = Field(None, strict=True, ge=0, description="Optional event picker window start in Unix seconds; not sent by Get Event.")
    end: Optional[int] = Field(None, strict=True, ge=1, description="Optional event picker window end; at most 31 days after start.")


class Recipient(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    email: str = Field(..., min_length=3, max_length=255, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    name: Optional[str] = Field(None, max_length=255)


class _DraftFields(_Operation):
    subject: str = Field(..., min_length=1, max_length=998)
    body: str = Field(..., max_length=100000, json_schema_extra={"ui:widget": "textarea"}, description="HTML draft content. This operation never sends it.")
    to: list[Recipient] = Field(default_factory=list, max_length=50)
    cc: list[Recipient] = Field(default_factory=list, max_length=50)
    bcc: list[Recipient] = Field(default_factory=list, max_length=50)


class CreateDraftConfig(_DraftFields):
    operation: Literal["create_draft"] = "create_draft"


class UpdateDraftConfig(_DraftFields):
    operation: Literal["update_draft"] = "update_draft"
    draft_id: str = Field(..., json_schema_extra=picker("draft_id"))


class ContactEmail(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    email: str = Field(..., min_length=3, max_length=255, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    type: Optional[Literal["work", "home", "other"]] = None


class _ContactFields(_Operation):
    given_name: str = Field(..., min_length=1, max_length=255)
    surname: Optional[str] = Field(None, max_length=255)
    company_name: Optional[str] = Field(None, max_length=255)
    job_title: Optional[str] = Field(None, max_length=255)
    emails: Optional[list[ContactEmail]] = Field(None, max_length=20)


class CreateContactConfig(_ContactFields):
    operation: Literal["create_contact"] = "create_contact"


class UpdateContactConfig(_ContactFields):
    operation: Literal["update_contact"] = "update_contact"
    contact_id: str = Field(..., json_schema_extra=picker("contact_id"))


class _CalendarFields(_Operation):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=4000, description="Unsupported for iCloud and EWS.")
    location: Optional[str] = Field(None, max_length=1000, description="Unsupported for iCloud and EWS.")


class CreateCalendarConfig(_CalendarFields):
    operation: Literal["create_calendar"] = "create_calendar"


class UpdateCalendarConfig(_CalendarFields):
    operation: Literal["update_calendar"] = "update_calendar"
    calendar_id: str = Field(..., json_schema_extra=picker("calendar_id"))


# Concrete operation classes and the discriminated config union follow below.


class ListMessagesConfig(_Page):
    operation: Literal["list_messages"] = "list_messages"


class GetMessageConfig(_Operation):
    operation: Literal["get_message"] = "get_message"
    message_id: str = Field(..., json_schema_extra=picker("message_id"))


class ListThreadsConfig(_Page):
    operation: Literal["list_threads"] = "list_threads"


class GetThreadConfig(_Operation):
    operation: Literal["get_thread"] = "get_thread"
    thread_id: str = Field(..., json_schema_extra=picker("thread_id"))


class ListFoldersConfig(_Page):
    operation: Literal["list_folders"] = "list_folders"


class GetFolderConfig(_Operation):
    operation: Literal["get_folder"] = "get_folder"
    folder_id: str = Field(..., json_schema_extra=picker("folder_id"))


class ListCalendarsConfig(_Page):
    operation: Literal["list_calendars"] = "list_calendars"


class GetCalendarConfig(_Operation):
    operation: Literal["get_calendar"] = "get_calendar"
    calendar_id: str = Field(..., json_schema_extra=picker("calendar_id"))


class ListContactsConfig(_Page):
    operation: Literal["list_contacts"] = "list_contacts"


class GetContactConfig(_Operation):
    operation: Literal["get_contact"] = "get_contact"
    contact_id: str = Field(..., json_schema_extra=picker("contact_id"))


class ListDraftsConfig(_Page):
    operation: Literal["list_drafts"] = "list_drafts"


class GetDraftConfig(_Operation):
    operation: Literal["get_draft"] = "get_draft"
    draft_id: str = Field(..., json_schema_extra=picker("draft_id"))


class ListContactGroupsConfig(_Page):
    operation: Literal["list_contact_groups"] = "list_contact_groups"


class DeleteDraftConfig(_Operation):
    operation: Literal["delete_draft"] = "delete_draft"
    draft_id: str = Field(..., json_schema_extra=picker("draft_id"))


class DeleteContactConfig(_Operation):
    operation: Literal["delete_contact"] = "delete_contact"
    contact_id: str = Field(..., json_schema_extra=picker("contact_id"))


class DeleteCalendarConfig(_Operation):
    operation: Literal["delete_calendar"] = "delete_calendar"
    calendar_id: str = Field(..., json_schema_extra=picker("calendar_id"))


NylasOperation = Annotated[Union[
    GetGrantConfig, ListEventsConfig, GetEventConfig, CreateDraftConfig, UpdateDraftConfig, CreateContactConfig, UpdateContactConfig, CreateCalendarConfig, UpdateCalendarConfig, ListMessagesConfig, GetMessageConfig, ListThreadsConfig, GetThreadConfig, ListFoldersConfig, GetFolderConfig, ListCalendarsConfig, GetCalendarConfig, ListContactsConfig, GetContactConfig, ListDraftsConfig, GetDraftConfig, ListContactGroupsConfig, DeleteDraftConfig, DeleteContactConfig, DeleteCalendarConfig
], Field(discriminator="operation")]


class NylasNodeConfig(NodeConfig[NylasOperation, NylasCredential]):
    credentials: Optional[NylasCredential] = Field(None, description="Connect a Nylas API Key or issued Access Token credential.")


class _LoadedCredential(dict):
    """Current authority travels in memory, never in a credential export."""
    pass


def _canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _same_submitted(submitted, current):
    shaped = shape_credential(submitted)
    if any(shaped.get(k) != v for k, v in current.items()
           if k not in {"token_version", "updated_at"}):
        raise ValueError("Nylas saved grant changed; reconnect or reload the credential.")
    for key in ("token_version", "updated_at"):
        if key in shaped and shaped[key] != current.get(key):
            raise ValueError("Nylas saved credential authority changed.")


class _NylasAuthorityStore:
    """Load-only Nylas authority; use staging's access and workflow grant policy."""

    def __init__(self, raw, *, pool, user_id, credential_id,
                 organization_id=CURRENT_ORGANIZATION, workflow_id=None):
        self.pool = pool
        self.user_id = str(UUID(str(user_id)))
        self.credential_id = str(UUID(str(credential_id)))
        self.credential_type = shape_credential(raw)["credential_type"]
        self.organization_id = organization_id
        self.workflow_id = str(UUID(str(workflow_id))) if workflow_id else None
        self.current = None

    async def _load_principal(self, principal_id, org):
        from repositories.credentials import credential_access_predicate
        from utils.encryption import get_encryption

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(f"""
                SELECT c.credential, c.owner_id, c.credential_type, c.token_version,
                       c.updated_at, c.revoked_at
                FROM credentials c
                WHERE c.id = $1::uuid AND {credential_access_predicate()}
            """, self.credential_id, principal_id, org)
        if row is None:
            return None
        version = row["token_version"]
        if (row["revoked_at"] is not None or row["credential_type"] != self.credential_type
                or type(version) is not int or version < 1):
            raise ValueError("Nylas saved credential authority changed or is unavailable.")
        try:
            owner = str(UUID(str(row["owner_id"])))
            data = get_encryption().decrypt_credential(row["credential"])
            data["credential_type"] = row["credential_type"]
            data = shape_credential(data)
        except Exception:
            raise ValueError("Nylas saved credential shape or binding is invalid.") from None
        self.current = (self.credential_id, self.user_id, str(principal_id), org,
                        self.workflow_id, owner, self.credential_type, version)
        data["token_version"] = version
        if row["updated_at"] is not None:
            data["updated_at"] = row["updated_at"].isoformat()
        return data

    async def load(self):
        from utils.credentials import (get_workflow_owner_id,
            is_credential_authorized_for_workflow, credential_lender)
        if self.pool is None:
            from utils.database_pool import get_native_pool
            self.pool = get_native_pool()
        self.current = None
        org = self.organization_id
        if org is CURRENT_ORGANIZATION:
            from repositories.organization import OrgRepo
            async with self.pool.acquire() as conn:
                org = await OrgRepo(self.pool).get_primary_org_id(conn, self.user_id)
        data = await self._load_principal(self.user_id, org)
        # Same runner, authorized workflow owner, then authorized lender order as
        # staging's resolve_credential_with_owner_fallback. Rechecked per request.
        if data is None and self.workflow_id:
            owner = await get_workflow_owner_id(self.pool, self.workflow_id)
            if (owner and owner != self.user_id and
                    await is_credential_authorized_for_workflow(
                        self.pool, self.workflow_id, self.credential_id)):
                data = await self._load_principal(owner, org)
        if data is None and self.workflow_id:
            lender = await credential_lender(self.pool, self.workflow_id, self.credential_id)
            if lender and lender != self.user_id:
                data = await self._load_principal(lender, org)
        if data is None:
            raise ValueError("Nylas credential not found or current access denied.")
        return data


def _store(raw, **context):
    return _NylasAuthorityStore(raw, **context)


class NylasNotFound(ValueError):
    pass


class NylasDenied(ValueError):
    pass


SAFE_FIELDS = {
    "message": ("id", "grant_id", "object", "thread_id", "date", "unread", "starred", "size", "folders"),
    "thread": ("id", "grant_id", "object", "unread", "starred", "message_ids", "draft_ids", "earliest_message_date", "latest_message_received_date", "latest_message_sent_date"),
    "draft": ("id", "grant_id", "object", "thread_id", "starred", "folders"),
    "folder": ("id", "grant_id", "object", "parent_id", "total_count", "unread_count", "system_folder"),
    "calendar": ("id", "grant_id", "object", "read_only", "is_owned_by_user", "is_primary", "timezone"),
    "event": ("id", "grant_id", "object", "calendar_id", "busy", "read_only", "status", "when"),
    "contact": ("id", "grant_id", "object", "source", "group_ids"),
    "contact_group": ("id", "grant_id", "object", "group_type"),
    "grant": ("id", "provider", "grant_status", "created_at", "updated_at", "blocked"),
}
CONTENT_FIELDS = {
    "message": ("subject", "snippet", "body", "from", "to", "cc", "bcc", "reply_to"),
    "thread": ("subject", "snippet", "participants"),
    "draft": ("subject", "body", "to", "cc", "bcc"),
    "folder": ("name",), "calendar": ("name", "description", "location"),
    "event": ("title", "description", "location"),
    "contact": ("given_name", "surname", "company_name", "job_title", "emails"),
    "contact_group": ("name",), "grant": (),
}
_BOOL_FIELDS = {"unread", "starred", "read_only", "is_owned_by_user", "is_primary", "busy", "blocked"}
_INT_FIELDS = {"date", "size", "total_count", "unread_count", "created_at", "updated_at", "earliest_message_date", "latest_message_received_date", "latest_message_sent_date"}
_ID_LIST_FIELDS = {"folders", "message_ids", "draft_ids", "group_ids"}


def _selected(kind, include_content=False, extra=()):
    return ",".join(dict.fromkeys((*SAFE_FIELDS[kind], *(CONTENT_FIELDS[kind] if include_content else ()), *extra)))


def _projection(row, kind, include_content, secret):
    out = {}
    for key in SAFE_FIELDS[kind]:
        value = row.get(key)
        if key in _BOOL_FIELDS:
            if type(value) is bool:
                out[key] = value
        elif key in _INT_FIELDS:
            if type(value) is int:
                out[key] = value
        elif key in _ID_LIST_FIELDS:
            if isinstance(value, list) and len(value) <= 1000 and all(isinstance(v, str) and v.strip() for v in value):
                out[key] = [v.replace(secret, "[redacted]") for v in value]
        elif key == "when" and isinstance(value, dict):
            out[key] = {k: (v[:2048].replace(secret, "[redacted]") if isinstance(v, str) else v) for k, v in value.items() if
                        (k in {"start_time", "end_time", "time"} and type(v) is int) or
                        (k in {"object", "date", "start_date", "end_date", "start_timezone", "end_timezone"} and isinstance(v, str))}
        elif isinstance(value, str):
            out[key] = value[:2048].replace(secret, "[redacted]")
    if include_content:
        for key in CONTENT_FIELDS[kind]:
            value = row.get(key)
            if isinstance(value, str):
                out[key] = value[:100000].replace(secret, "[redacted]")
            elif key in {"from", "to", "cc", "bcc", "reply_to", "participants", "emails"} and isinstance(value, list):
                out[key] = [{k: v[:255].replace(secret, "[redacted]") for k, v in item.items()
                             if k in {"email", "name", "type"} and isinstance(v, str)}
                            for item in value[:50] if isinstance(item, dict)]
    return out


def _scope_check(grant, kind, write=False):
    """Use actual provider-returned grant scopes; alternatives are disjunctions.

    Non-OAuth providers retain provider-side permissions. No invented Nylas
    scope names or claims that an application key grants mailbox permissions.
    Contacts are restricted to address_book, so inbox/domain scopes aren't needed.
    """
    scopes, provider = set(grant["scope"]), grant["provider"]
    choices = None
    if provider == "google":
        table = {
            "message": ("gmail.modify",) if write else ("gmail.readonly", "gmail.modify"),
            "thread": ("gmail.readonly", "gmail.modify"),
            "draft": ("gmail.compose",) if write else ("gmail.readonly", "gmail.compose"),
            "folder": ("gmail.labels", "gmail.modify"),
            "contact": ("contacts",) if write else ("contacts.readonly", "contacts"),
            "contact_group": ("contacts.readonly", "contacts"),
            "calendar": ("calendar",) if write else ("calendar.readonly", "calendar"),
            "event": ("calendar.events.readonly", "calendar.events", "calendar", "calendar.readonly"),
        }
        choices = {"https://www.googleapis.com/auth/" + s for s in table[kind]}
    elif provider == "microsoft":
        table = {
            "message": {"Mail.Read", "Mail.ReadWrite", "Mail.Read.Shared", "Mail.ReadWrite.Shared"},
            "thread": {"Mail.Read", "Mail.ReadWrite", "Mail.Read.Shared", "Mail.ReadWrite.Shared"},
            "folder": {"Mail.Read", "Mail.ReadWrite", "Mail.Read.Shared", "Mail.ReadWrite.Shared"},
            "draft": {"Mail.ReadWrite", "Mail.ReadWrite.Shared"} if write else {"Mail.Read", "Mail.ReadWrite", "Mail.Read.Shared", "Mail.ReadWrite.Shared"},
            "contact": {"Contacts.ReadWrite"} if write else {"Contacts.Read", "Contacts.ReadWrite"},
            "contact_group": {"Contacts.Read", "Contacts.ReadWrite"},
            "calendar": {"Calendars.ReadWrite"} if write else {"Calendars.Read", "Calendars.ReadWrite"},
            "event": {"Calendars.Read", "Calendars.ReadWrite"},
        }
        choices = table[kind]
    if choices is not None and not scopes.intersection(choices):
        raise ValueError("Nylas grant is missing provider permissions for this operation; reconnect with the required access.")


class _Client:
    def __init__(self, raw, store=None):
        self.data = shape_credential(raw)
        self.store = store
        self.authority = deepcopy(store.current) if store else None
        self.secret = self.data.get("api_key") or self.data["access_token"]
        self.base = HOSTS[self.data["region"]] + "/v3/grants/" + (quote(self.data["grant_id"], safe="") if self.data["credential_type"] == FAMILIES[0] else "me")

    async def guard(self):
        if self.store:
            current = await self.store.load()
            if self.store.current != self.authority or _canonical(current) != _canonical(self.data):
                raise ValueError("Nylas current credential authority or grant changed; retry after reconnecting.")
        else:
            shape_credential(self.data)

    async def request(self, method, path="", *, params=None, body=None):
        await self.guard()
        try:
            async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, self.base + path, params=params,
                                                json=body, headers={"Authorization": "Bearer " + self.secret,
                                                "Accept": "application/json", "Content-Type": "application/json"})
        except Exception:
            raise ValueError("Nylas transport did not complete; write outcome may be unknown. No request was replayed.") from None
        await self.guard()
        if response.status_code == 404:
            raise NylasNotFound("Nylas resource not found (HTTP 404).")
        if response.status_code in (401, 403):
            raise NylasDenied("Nylas authorization refused (HTTP " + str(response.status_code) + "); reconnect or check provider permissions.")
        if response.status_code != 200:
            raise ValueError("Nylas request did not complete (HTTP " + str(response.status_code) + "). Write outcome may be unknown; no automatic retry.")
        if len(response.content) > 2_000_000:
            raise ValueError("Nylas response exceeds the local size limit; request a smaller page.")
        try:
            payload = response.json()
        except Exception:
            raise ValueError("Nylas returned a malformed JSON response.") from None
        if not isinstance(payload, dict) or payload.get("error") is not None:
            raise ValueError("Nylas returned an unsuccessful or malformed response.")
        return payload

    async def grant(self):
        payload = await self.request("GET")
        row = payload.get("data")
        if (not isinstance(row, dict) or row.get("id") != self.data["grant_id"]
                or not isinstance(row.get("provider"), str) or row["provider"] not in PROVIDERS
                or not isinstance(row.get("scope"), list)
                or not all(isinstance(s, str) and s.strip() for s in row["scope"])):
            raise ValueError("Nylas did not return the configured grant and documented permission metadata.")
        if row.get("grant_status") not in ("valid", "invalid") or ("blocked" in row and type(row["blocked"]) is not bool):
            raise ValueError("Nylas grant status response is malformed.")
        if row["grant_status"] == "invalid" or row.get("blocked") is True:
            raise NylasDenied("Nylas grant is invalid or blocked; reconnect the connected account.")
        return row

    def entity(self, row, kind, expected_id=None, calendar_id=None):
        if not isinstance(row, dict):
            raise ValueError("Nylas resource response is malformed.")
        actual = resource_id(row.get("id"))
        if row.get("grant_id") != self.data["grant_id"] or (expected_id and actual != expected_id):
            raise ValueError("Nylas resource is outside the configured grant or requested ID.")
        if calendar_id and row.get("calendar_id") != calendar_id:
            raise ValueError("Nylas event is outside the selected calendar.")
        # Grant/ID/parent bindings are required. No guessed object/entity discriminator.
        return row

    async def get(self, kind, rid, *, calendar_id=None, content=False, extra=()):
        params = {"select": _selected(kind, content, extra)}
        if calendar_id:
            params["calendar_id"] = calendar_id
        payload = await self.request("GET", "/" + kind + "s/" + quote(resource_id(rid), safe=""), params=params)
        return self.entity(payload.get("data"), kind, rid, calendar_id)

    def token(self, scope, cursor, seen):
        data = base64.urlsafe_b64encode(_canonical({"scope": scope, "cursor": cursor, "seen": seen, "expires": int(time.time()) + 1800}).encode()).decode()
        signature = hmac.new(self.secret.encode(), data.encode(), hashlib.sha256).hexdigest()
        token = data + "." + signature
        if len(token) > 100000:
            raise ValueError("Nylas page token exceeds the local size limit; narrow the selection.")
        return token

    def unseal(self, token, scope):
        if not isinstance(token, str) or len(token) > 100000:
            raise ValueError("Nylas page token is invalid.")
        try:
            data, signature = token.rsplit(".", 1)
            expected = hmac.new(self.secret.encode(), data.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError()
            row = json.loads(base64.urlsafe_b64decode(data))
            if row["scope"] != scope or type(row["expires"]) is not int or row["expires"] < time.time():
                raise ValueError()
            if not isinstance(row["cursor"], str) or not row["cursor"] or len(row["cursor"]) > 16384:
                raise ValueError()
            if not isinstance(row["seen"], list) or len(row["seen"]) > 1000 or not all(isinstance(v, str) for v in row["seen"]):
                raise ValueError()
            return row["cursor"], row["seen"]
        except Exception:
            raise ValueError("Nylas page token expired or belongs to different credentials, filters or parent scope.") from None

    async def page(self, kind, *, limit=50, token=None, calendar_id=None, start=None, end=None, content=False, search=None):
        params = {"limit": limit, "select": _selected(kind, content)}
        if kind == "contact":
            params["source"] = "address_book"
        if calendar_id:
            params.update(calendar_id=calendar_id, start=start, end=end)
        scope = hashlib.sha256(_canonical({"data": self.data, "authority": self.authority,
                                          "kind": kind, "params": params, "search": search}).encode()).hexdigest()
        seen, cursor = [], None
        if token:
            cursor, seen = self.unseal(token, scope)
            params["page_token"] = cursor
        path = "/contacts/groups" if kind == "contact_group" else "/" + kind + "s"
        payload = await self.request("GET", path, params=params)
        rows, next_cursor = payload.get("data"), payload.get("next_cursor")
        if not isinstance(rows, list) or len(rows) > limit:
            raise ValueError("Nylas collection response is malformed or exceeds the requested page.")
        if next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor or len(next_cursor) > 16384):
            raise ValueError("Nylas collection cursor is malformed.")
        ids = []
        for row in rows:
            self.entity(row, kind, calendar_id=calendar_id)
            if kind == "contact" and row.get("source") != "address_book":
                raise ValueError("Nylas contact is outside the selected address-book source.")
            ids.append(row["id"])
        if len(set(ids)) != len(ids) or set(ids).intersection(seen) or (next_cursor and (not rows or next_cursor == cursor)):
            raise ValueError("Nylas pagination repeated resources or failed to advance.")
        if len(seen) + len(ids) > 1000:
            raise ValueError("Nylas pagination exceeds 1,000 resources; narrow the selection.")
        next_token = self.token(scope, next_cursor, seen + ids) if next_cursor else None
        return rows, next_token


class NylasNode(WorkflowNode):
    integration_type = "automation-nylas"
    credential_provider_labels = {"nylas": "Nylas Account"}
    auto_select_credential = False
    connection_evidence = ConnectionEvidence(operation="get_grant", noun="connected grant", proves="reachability", label_keys=("id",))

    @classmethod
    def get_config_model(cls):
        return NylasNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._freshen_credential(credential_data, pool=pool, user_id=user_id,
                                            credential_id=credential_id)

    @classmethod
    async def _freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None,
                                 organization_id=CURRENT_ORGANIZATION, workflow_id=None):
        shape_credential(credential_data)
        if not credential_id:
            return credential_data
        store = _store(credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
                       organization_id=organization_id, workflow_id=workflow_id)
        if organization_id is CURRENT_ORGANIZATION and workflow_id is None:
            # Staging's dropdown freshener receives no workflow context. Carry
            # this private store until the loader receives trusted server context.
            loaded = _LoadedCredential(credential_data)
            loaded._pending_store = store
            return loaded
        current = await store.load()
        _same_submitted(credential_data, current)
        if not isinstance(current.get("updated_at"), str) or not current["updated_at"]:
            raise ValueError("Nylas current credential timestamp is unavailable.")
        loaded = _LoadedCredential(current)
        loaded._store = store
        return loaded

    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            await _Client(credential_data).grant()
        except NylasDenied:
            return {"valid": False, "message": "Nylas refused access to the configured grant."}
        except Exception:
            return {"valid": None, "message": "Configured Nylas grant access could not be verified."}
        return {"valid": True, "message": "Configured Nylas grant is reachable; this does not prove application ownership or all operation permissions."}

    async def _client(self):
        if "credentials" in self.node_data:
            raw = self.node_data["credentials"]
        else:
            raw = self.config.credentials.model_dump() if self.config.credentials else None
        shape_credential(raw)  # Original stored family before base reconciliation.
        credential_id = self.node_data.get("credential_id")
        if credential_id:
            raw = await self._freshen_credential(raw, pool=self.node_data.get("_approval_pool"), user_id=self.user_id,
                                               credential_id=credential_id, organization_id=self.organization_id,
                                               workflow_id=self.workflow_id)
        return _Client(raw, getattr(raw, "_store", None))

    async def execute(self, inputs):
        client = await self._client()
        config = self.config.config
        op = config.operation
        grant = await client.grant()
        if op == "get_grant":
            return {"data": _projection(grant, "grant", False, client.secret), "proves": "reachability"}
        action, kind = op.split("_", 1)
        kind = "contact_group" if kind == "contact_groups" else kind.removesuffix("s")
        write = action in {"create", "update", "delete"}
        _scope_check(grant, kind, write)
        if (kind == "event" and grant["provider"] == "icloud") or (kind == "calendar" and grant["provider"] == "imap") or (kind == "contact_group" and grant["provider"] == "ews"):
            raise ValueError("This Nylas provider does not support the selected API or calendar-scoped contract.")
        calendar_id = getattr(config, "calendar_id", None) if kind == "event" else None
        if calendar_id:
            _scope_check(grant, "calendar")
            await client.get("calendar", calendar_id)
        if action == "list":
            rows, token = await client.page(kind, limit=config.limit, token=config.page_token, calendar_id=calendar_id,
                                            start=getattr(config, "start", None), end=getattr(config, "end", None), content=config.include_content)
            return {"items": [_projection(row, kind, config.include_content, client.secret) for row in rows], "next_page_token": token}
        rid = getattr(config, kind + "_id", None)
        if action == "get":
            row = await client.get(kind, rid, calendar_id=calendar_id, content=config.include_content)
            if kind == "contact" and row.get("source") != "address_book":
                raise ValueError("Nylas contact is outside the address-book source.")
            return {"data": _projection(row, kind, config.include_content, client.secret)}
        # Readback requires genuine read permission as well as write permission.
        _scope_check(grant, kind)
        if kind == "calendar" and grant["provider"] in {"icloud", "ews"} and any(getattr(config, k, None) is not None for k in ("description", "location")):
            raise ValueError("This provider does not support calendar description/location writes.")
        if action != "create":
            before = await client.get(kind, rid)
            if kind == "calendar" and (before.get("read_only") is not False or before.get("is_owned_by_user") is not True):
                raise ValueError("Calendar mutation requires a writable calendar owned by the configured grant.")
            if kind == "calendar" and action == "delete" and before.get("is_primary") is not False:
                raise ValueError("Only a confirmed nonprimary calendar may be deleted.")
            if kind == "contact" and before.get("source") != "address_book":
                raise ValueError("Only address-book contacts may be changed.")
        path = "/" + kind + "s" + ("/" + quote(rid, safe="") if rid else "")
        if action == "delete":
            payload = await client.request("DELETE", path)
            if not isinstance(payload.get("request_id"), str) or not payload["request_id"].strip():
                raise ValueError("Nylas deletion acknowledgement is malformed; cleanup remains unverified.")
            try:
                await client.get(kind, rid)
            except NylasNotFound:
                await client.grant()  # Separate protected read proves the grant remains usable.
                return {"deleted": True, "id": rid.replace(client.secret, "[redacted]"), "grant_id": client.data["grant_id"], "absence_verified": True, "permanent_erasure": "unverified"}
            raise ValueError("Nylas deletion was acknowledged but resource absence was not verified.")
        keys = {"draft": ("subject", "body", "to", "cc", "bcc"),
                "contact": ("given_name", "surname", "company_name", "job_title", "emails"),
                "calendar": ("name", "description", "location")}[kind]
        body = config.model_dump(include=set(keys), exclude_none=True)
        payload = await client.request("POST" if action == "create" else "PUT", path, body=body)
        row = client.entity(payload.get("data"), kind, rid)
        readback = await client.get(kind, row["id"], content=True, extra=keys)
        for key, value in body.items():
            actual = readback.get(key)
            if isinstance(value, list):
                # Provider may add optional name/type keys or reorder recipients.
                candidates = deepcopy(actual or []) if actual is None or isinstance(actual, list) else None
                equal = candidates is not None and len(candidates) == len(value) and all(isinstance(item, dict) for item in candidates)
                if equal:
                    for expected in value:
                        match = next((i for i, item in enumerate(candidates) if all(item.get(k) == v for k, v in expected.items())), None)
                        if match is None:
                            equal = False
                            break
                        candidates.pop(match)
            else:
                equal = actual == value
            if not equal:
                raise ValueError("Nylas write completed but submitted fields were not verified by separate readback; do not replay the write.")
        return {"data": _projection(readback, kind, config.include_content, client.secret), "readback_verified": True, "action": action}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        context = context or {}
        kinds = {"message_id": "message", "thread_id": "thread", "folder_id": "folder", "calendar_id": "calendar", "event_id": "event", "contact_id": "contact", "draft_id": "draft"}
        if field_name not in kinds:
            return {"options": [], "next_page_token": None}
        pending = getattr(credential_data, "_pending_store", None)
        if pending is not None:
            if context.get("_user_id") != pending.user_id:
                raise ValueError("Nylas options require the current caller context.")
            workflow_id = context.get("_workflow_id")
            pending.workflow_id = str(UUID(str(workflow_id))) if workflow_id else None
            current = await pending.load()
            _same_submitted(credential_data, current)
            if not isinstance(current.get("updated_at"), str) or not current["updated_at"]:
                raise ValueError("Nylas current credential timestamp is unavailable.")
            credential_data = _LoadedCredential(current)
            credential_data._store = pending
        client = _Client(credential_data, getattr(credential_data, "_store", None))
        await client.guard()
        kind = kinds[field_name]
        if kind == "event":
            calendar_id = resource_id(context.get("calendar_id"))
            # Picker date window is stable across pages; callers can supply explicit Unix seconds.
            start = context.get("start")
            end = context.get("end")
            if type(start) is not int or type(end) is not int or start < 0 or end <= start or end - start > 31 * 86400:
                raise ValueError("Set an explicit event picker start/end window of at most 31 days.")
        else:
            calendar_id, start, end = None, None, None
        # Validate token binding before making even the grant metadata request.
        grant = None
        if page_token:
            # page() verifies the identical full scope before its collection request.
            params = {"limit": 100, "select": _selected(kind)}
            if kind == "contact":
                params["source"] = "address_book"
            if calendar_id:
                params.update(calendar_id=calendar_id, start=start, end=end)
            scope = hashlib.sha256(_canonical({"data": client.data, "authority": client.authority,
                                              "kind": kind, "params": params, "search": search}).encode()).hexdigest()
            client.unseal(page_token, scope)
        grant = await client.grant()
        _scope_check(grant, kind)
        if calendar_id:
            _scope_check(grant, "calendar")
            await client.get("calendar", calendar_id)
        rows, token = await client.page(kind, limit=100, token=page_token, calendar_id=calendar_id, start=start, end=end, search=search)
        options = [{"value": row["id"], "label": row["id"], "metadata": {"grant_id": client.data["grant_id"], **({"calendar_id": calendar_id} if calendar_id else {})}} for row in rows]
        if search:
            options = [option for option in options if search.casefold() in option["value"].casefold()]
        return {"options": options, "next_page_token": token}
