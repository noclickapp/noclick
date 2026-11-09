"""Glofox branch metadata, member names, classes, bookings and lead notes.

Contracts: vendor OpenAPI 2.3.0, retrieved 2026-10-06. Supplied integration
key/token/branch only. No login, billing, booking mutation or consent changes.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE = "https://gf-api.aws.glofox.com/prod"
TYPE = "glofox_api_key_token"
FIELDS = ("credential_type", "api_key", "api_token", "branch_id")


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{24}", value):
        raise ValueError("A lowercase 24-character Glofox resource ID is required")
    return value


def _line(value, maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("A nonempty single-line value is required")
    return value


def _int(value, minimum=0, maximum=10**12):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Glofox returned an invalid integer")
    return value


def _note(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 500 or any((ord(c) < 32 and c not in "\r\n\t") or ord(c) == 127 for c in value):
        raise ValueError("A nonempty note of at most 500 characters is required")
    return value


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secrets): _redact(v, secrets) for k, v in value.items()}
    return value


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GlofoxApiKeyTokenCredential(_Closed):
    model_config = ConfigDict(title="Glofox API Key and Token", extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-type": "api_key", "x-credential-url": "https://api-portal.glofox.com/api-portal/glofox/api/openapi-reference.html"})
    credential_type: Literal["glofox_api_key_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})
    api_token: str = Field(..., title="API Token", repr=False, json_schema_extra={"ui:widget": "password"})
    branch_id: str = Field(..., pattern=r"^[a-f0-9]{24}$", title="Branch ID", description="The branch granted to this integration. Every request uses this saved branch.")

    _identifier = field_validator("branch_id", mode="before")(_id)

    @field_validator("api_key", "api_token", mode="before")
    @classmethod
    def header(cls, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 4096 or not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("A nonempty ASCII integration header value is required")
        return value

    @model_validator(mode="before")
    @classmethod
    def shaped_default(cls, data):
        # Concrete unsaved form shaping supports omitted tags. The external
        # native boundary checks its original tag independently before parsing.
        if isinstance(data, dict) and "credential_type" not in data:
            return {**data, "credential_type": TYPE}
        return data


def credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != TYPE:
        raise ValueError("An explicit Glofox API Key and Token credential is required")
    try:
        return GlofoxApiKeyTokenCredential.model_validate({k: data[k] for k in FIELDS if k in data}).model_dump()
    except Exception:
        raise ValueError("Glofox credential is invalid") from None


class CheckConnection(_Closed):
    operation: Literal["check_connection"] = Field("check_connection", title="Check Connection", json_schema_extra={"ui:hidden": True})


class GetBranch(_Closed):
    operation: Literal["get_branch"] = Field("get_branch", title="Get Connected Branch", json_schema_extra={"ui:hidden": True})


class _Paged(_Closed):
    page_size: int = Field(50, ge=1, le=100, strict=True, title="Page Size")
    page_token: str | None = Field(None, max_length=4096, title="Next Page Token", description="Use a continuation from this operation with the same credential, branch and filters.")


class ListMembers(_Paged):
    operation: Literal["list_members"] = Field("list_members", title="List Members and Leads", description="Includes active and inactive users of the connected branch. Excludes membership and contact details.", json_schema_extra={"ui:hidden": True})

    modified_since: int | None = Field(None, ge=0, strict=True, title="Modified Since", description="UTC Unix seconds; inclusive modified-time filter.")


class _Member(_Closed):
    member_id: str = Field(..., pattern=r"^[a-f0-9]{24}$", title="Member or Lead", json_schema_extra={"x-resource-type": "glofox_member", "x-dynamic-options": {"field_name": "member_id", "searchable": True, "allow_custom": True, "placeholder": "Select a branch member or lead"}})
    _identifier = field_validator("member_id", mode="before")(_id)


class GetMember(_Member):
    operation: Literal["get_member"] = Field("get_member", title="Get Member", json_schema_extra={"ui:hidden": True})


class UpdateMember(_Member):
    operation: Literal["update_member"] = Field("update_member", title="Update Member Name", description="Partial update of first/last name only; current names and connected-branch membership are checked before sending.", json_schema_extra={"ui:hidden": True})
    expected_first_name: str = Field(..., title="Current First Name", min_length=1, max_length=200)
    expected_last_name: str = Field(..., title="Current Last Name", min_length=1, max_length=200)
    first_name: str | None = Field(None, title="New First Name", min_length=1, max_length=200)
    last_name: str | None = Field(None, title="New Last Name", min_length=1, max_length=200)

    @field_validator("expected_first_name", "expected_last_name", "first_name", "last_name")
    @classmethod
    def name(cls, value):
        return _line(value) if value is not None else None

    @model_validator(mode="after")
    def changed(self):
        if self.first_name is None and self.last_name is None:
            raise ValueError("Supply at least one new name")
        return self


class FindMemberByEmail(_Closed):
    operation: Literal["find_member_by_email"] = Field("find_member_by_email", title="Find Member by Exact Email", description="Uses the documented single user response, not partial email search or a list envelope.", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., title="Exact Email", max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

    @field_validator("email")
    @classmethod
    def email_value(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", _line(value, 254)):
            raise ValueError("A full email address is required")
        return value


class ListClasses(_Paged):
    operation: Literal["list_classes"] = Field("list_classes", title="List Classes", json_schema_extra={"ui:hidden": True})
    start_utc_seconds: int = Field(..., ge=0, le=10**11, strict=True, title="Start UTC Timestamp", description="UTC Unix seconds, not milliseconds.")
    end_utc_seconds: int = Field(..., ge=0, le=10**11, strict=True, title="End UTC Timestamp")
    private_classes: bool = Field(False, strict=True, title="Private Classes")
    active: bool = Field(True, strict=True, title="Active Classes")

    @model_validator(mode="after")
    def interval(self):
        if not 0 < self.end_utc_seconds - self.start_utc_seconds <= 366 * 86400:
            raise ValueError("The class range must be ordered and no longer than 366 days")
        return self


class GetClass(_Closed):
    operation: Literal["get_class"] = Field("get_class", title="Get Class", json_schema_extra={"ui:hidden": True})
    class_id: str = Field(..., pattern=r"^[a-f0-9]{24}$", title="Class ID", description="Paste a class ID from List Classes. Courses and time slots are separate resource types.")
    _identifier = field_validator("class_id", mode="before")(_id)


class ListMemberBookings(_Member, _Paged):
    operation: Literal["list_member_bookings"] = Field("list_member_bookings", title="List Member Bookings", description="Metadata only. Does not create, cancel, charge or confirm bookings.", json_schema_extra={"ui:hidden": True})


class ListBranchBookings(_Paged):
    operation: Literal["list_branch_bookings"] = Field("list_branch_bookings", title="List Branch Bookings", description="Branch booking start/finish values are local datetime strings; financial fields are excluded.", json_schema_extra={"ui:hidden": True})
    booking_status: Literal["BOOKED", "WAITING", "CANCELED", "RESERVED", "FAILED"] | None = Field(None, title="Status Filter")

    modified_since: int | None = Field(None, ge=0, strict=True, title="Modified Since", description="UTC Unix seconds; inclusive modified-time filter.")


class ListNotes(_Member):
    operation: Literal["list_notes"] = Field("list_notes", title="List Lead Notes", description="Returns NOTE interactions only. Paging totals describe all provider interactions, not just filtered notes.", json_schema_extra={"ui:hidden": True})
    page_token: str | None = Field(None, max_length=4096, title="Next Page Token")


class AddNote(_Member):
    operation: Literal["add_note"] = Field("add_note", title="Add Lead Note", description="Adds a NOTE, never a MANUAL_EMAIL interaction. The documented acknowledgement does not provide a created ID or deletion contract.", json_schema_extra={"ui:hidden": True})
    description: str = Field(..., min_length=1, max_length=500, title="Note", json_schema_extra={"ui:widget": "textarea"})
    _description = field_validator("description")(_note)


class ListContactSources(_Closed):
    operation: Literal["list_contact_sources"] = Field("list_contact_sources", title="List Contact Sources", json_schema_extra={"ui:hidden": True})


class ListMarketingSources(_Closed):
    operation: Literal["list_marketing_sources"] = Field("list_marketing_sources", title="List Marketing Sources", json_schema_extra={"ui:hidden": True})


class OnUpdatedMember(PollTriggerConfigBase):
    operation: Literal["on_updated_member"] = Field("on_updated_member", title="New or Updated Member", json_schema_extra={"ui:hidden": True, "x-is-trigger": True})
    modified_since: int = Field(0, ge=0, strict=True, title="Modified Since", description="UTC Unix seconds; includes members modified at or after this time. The first poll establishes a baseline.")


class OnUpdatedBooking(PollTriggerConfigBase):
    operation: Literal["on_updated_booking"] = Field("on_updated_booking", title="New or Updated Booking", json_schema_extra={"ui:hidden": True, "x-is-trigger": True})
    modified_since: int = Field(0, ge=0, strict=True, title="Modified Since", description="UTC Unix seconds; includes bookings modified at or after this time. The first poll establishes a baseline.")


Operation = Annotated[Union[CheckConnection, GetBranch, ListMembers, GetMember, UpdateMember, FindMemberByEmail, ListClasses, GetClass, ListMemberBookings, ListBranchBookings, ListNotes, AddNote, ListContactSources, ListMarketingSources, OnUpdatedMember, OnUpdatedBooking], Field(discriminator="operation")]


class GlofoxNodeConfig(NodeConfig[Operation, GlofoxApiKeyTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class ProviderError(ValueError):
    def __init__(self, status=None, message="Glofox response could not be verified", rejected=False):
        self.status = status
        self.rejected = rejected
        super().__init__(message)


class Session:
    def __init__(self, data):
        self.data = credential(data)
        self.write_attempted = False
        self.acknowledgement = None
        self.branch = None

    async def request(self, method, route, *, params=None, body=None, write=False, acknowledgement=False):
        try:
            return await asyncio.wait_for(self._request(method, route, params=params, body=body, write=write, acknowledgement=acknowledgement), timeout=25)
        except TimeoutError:
            raise ProviderError(None, "Glofox request deadline exceeded; inspect writes before retrying") from None

    async def _request(self, method, route, *, params=None, body=None, write=False, acknowledgement=False):
        # Only internally constructed documented paths. No credentialed redirect,
        # caller URL, namespace route, dot segment or arbitrary REST wrapper.
        if not re.fullmatch(r"/2\.[0123]/(?:branches/[a-f0-9]{24}(?:/(?:events|bookings|users|leads)(?:/[a-f0-9]{24})?(?:/(?:interactions|contact-sources|marketing-sources))?)?|members(?:/[a-f0-9]{24})?|bookings)", route):
            raise ValueError("Unsupported Glofox route")
        if write:
            self.write_attempted = True
        try:
            async with httpx.AsyncClient(verify=True, trust_env=False, follow_redirects=False, timeout=httpx.Timeout(20.0)) as client:
                async with client.stream(method, BASE + route, headers={"x-api-key": self.data["api_key"], "x-glofox-api-token": self.data["api_token"], "x-glofox-branch-id": self.data["branch_id"], "Accept": "application/json"}, params=params, json=body) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 2 * 1024 * 1024:
                            raise ProviderError(response.status_code, "Glofox response exceeds the supported size")
                    status = response.status_code
                    if status != 200:
                        raise ProviderError(status, "Glofox request was rejected or did not return a documented completed response")
                    payload = None
                    if raw:
                        try:
                            payload = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                        except (ValueError, TypeError, UnicodeError):
                            if not acknowledgement:
                                raise ProviderError(status, "Glofox returned an unsupported JSON response") from None
                    if isinstance(payload, dict) and (payload.get("success") is False or any(payload.get(k) is not None for k in ("error", "errors", "message_code", "code"))):
                        raise ProviderError(status, "Glofox returned an error in a successful HTTP response", rejected=True)
                    if write:
                        self.acknowledgement = {"http_status": status}
                    if acknowledgement:
                        # POST NOTE documents no body/schema. Preserve only its
                        # HTTP acknowledgement; never emit arbitrary text/links.
                        return {"http_status": status, "body_kind": "empty" if not raw else "json" if payload is not None else "text"}
                    if not isinstance(payload, (dict, list)):
                        raise ProviderError(status, "Glofox returned an unsupported response shape")
                    return payload
        except (httpx.HTTPError, OSError):
            raise ProviderError(None, "Glofox request outcome is unknown; inspect writes before retrying") from None

    async def bind_branch(self):
        if self.branch is None:
            row = await self.request("GET", f"/2.0/branches/{self.data['branch_id']}")
            if not isinstance(row, dict) or _id(row.get("_id")) != self.data["branch_id"]:
                raise ValueError("Glofox returned a different branch")
            self.branch = {"_id": row["_id"], "name": _line(row.get("name")), "namespace": _line(row.get("namespace"))}
            address = row.get("address")
            if isinstance(address, dict):
                self.branch["address"] = {k: _line(address[k]) for k in ("city", "country_code", "currency", "timezone_id") if address.get(k) is not None}
        return self.branch


def _scope(session, row, *, require_branch=False):
    if not isinstance(row, dict):
        raise ValueError("Glofox resource must be an object")
    if require_branch or row.get("branch_id") is not None:
        if _id(row.get("branch_id")) != session.data["branch_id"]:
            raise ValueError("Glofox resource belongs to a different branch")
    if row.get("namespace") is not None and row["namespace"] != session.branch["namespace"]:
        raise ValueError("Glofox resource belongs to a different namespace")


def _project(session, row, kind, *, expected=None, member_id=None):
    _scope(session, row, require_branch=kind in {"class", "booking", "note"})
    identifier = _id(row.get("_id"))
    if expected is not None and identifier != expected:
        raise ValueError("Glofox returned a different resource")
    out = {"_id": identifier}
    fields = {"member": ("first_name", "last_name", "type", "lead_status", "active", "created", "modified"), "class": ("type", "name", "status", "time_start", "duration", "size", "booked", "waiting", "private", "active", "is_online", "program_id"), "booking": ("user_id", "status", "type", "model", "model_id", "model_name", "event_id", "event_name", "course_id", "session_id", "time_slot_id", "attended", "guest_bookings", "duration", "time_start", "time_finish", "created", "modified"), "note": ("user_id", "type", "description", "created")}[kind]
    if kind == "class" and row.get("type") != "event":
        raise ValueError("The requested resource is not a class")
    if kind in {"booking", "note"}:
        user = _id(row.get("user_id"))
        if member_id is not None and user != member_id:
            raise ValueError("Glofox resource belongs to a different member")
    if kind == "note" and row.get("type") != "NOTE":
        raise ValueError("The requested interaction is not a note")
    for key in fields:
        value = row.get(key)
        if value is None:
            continue
        if key.endswith("_id"):
            out[key] = _id(value)
        elif type(value) is bool:
            if key not in {"active", "private", "is_online", "attended"}:
                raise ValueError("Glofox metadata type is invalid")
            out[key] = value
        elif type(value) is int:
            if key not in {"created", "modified", "time_start", "duration", "size", "booked", "waiting", "guest_bookings"}:
                raise ValueError("Glofox metadata type is invalid")
            out[key] = _int(value)
        elif isinstance(value, str):
            out[key] = _note(value) if key == "description" else _line(value)
        else:
            raise ValueError("Glofox metadata type is invalid")
    if kind != "member":
        out["branch_id"] = session.data["branch_id"]
    # The two booking routes deliberately retain the provider's distinct time
    # types: member UTC integers versus branch local start/finish strings.
    return out


def _scope_key(session, op):
    return {"branch": session.data["branch_id"], "namespace": session.branch["namespace"], "token_binding": hashlib.sha256(session.data["api_token"].encode()).hexdigest(), "config": op.model_dump(exclude={"page_token"})}


def _token(session, scope, page):
    raw = json.dumps({"scope": scope, "page": page}, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw + hmac.new(session.data["api_key"].encode(), raw, hashlib.sha256).digest()).decode().rstrip("=")


def _page(session, scope, token):
    if token is None:
        return 1
    try:
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        data, mac = raw[:-32], raw[-32:]
        if not hmac.compare_digest(mac, hmac.new(session.data["api_key"].encode(), data, hashlib.sha256).digest()):
            raise ValueError()
        result = json.loads(data)
        if result["scope"] != scope or type(result["page"]) is not int or not 2 <= result["page"] <= 100000:
            raise ValueError()
        return result["page"]
    except Exception:
        raise ValueError("Glofox continuation does not match the credential, branch, operation or filters") from None


def _paging(payload, page, requested, family):
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Glofox paginated data is missing")
    rows = payload["data"]
    if family == "base":
        total, size, actual = payload.get("total_count"), payload.get("limit"), payload.get("page")
        more = payload.get("has_more")
        if payload.get("object") != "list" or type(more) is not bool:
            raise ValueError("Glofox list pagination is invalid")
    else:
        if payload.get("success") is not True or not isinstance(payload.get("meta"), dict):
            raise ValueError("Glofox success/pagination metadata is missing")
        meta = payload["meta"]
        if family == "notes":
            meta = meta.get("pagination")
            if not isinstance(meta, dict):
                raise ValueError("Glofox interaction pagination is missing")
            total, size, actual = meta.get("count"), meta.get("perPage"), meta.get("currentPage")
        else:
            total, size, actual = meta.get("totalCount"), meta.get("limit"), meta.get("page")
        more = page * _int(size, 1, 1000) < _int(total)
    total, size, actual = _int(total), _int(size, 1, 1000), _int(actual, 1, 100000)
    if actual != page or (requested is not None and size != requested) or len(rows) > size or total < (page - 1) * size + len(rows):
        raise ValueError("Glofox pagination contradicts the requested page")
    if more != (page * size < total) or (more and not rows):
        raise ValueError("Glofox continuation contradicts the total count")
    return rows, {"page": page, "page_size": size, "total_count": total, "has_more": more, "raw_count": len(rows), "total_scope": "all_interactions" if family == "notes" else "provider_results"}


class GlofoxNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-glofox"
    connection_evidence = ConnectionEvidence(noun="branches", operation="check_connection", proves="account", label_keys=("name",))
    edit_examples = ["List members of my connected branch", "Show this week's classes", "Update this member's last name"]

    @classmethod
    def get_config_model(cls):
        return GlofoxNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        if not isinstance(config_data, dict):
            raise ValueError("Glofox configuration is required")
        if config_data.get("credentials") is not None:
            config_data = {**config_data, "credentials": credential(config_data["credentials"])}
        try:
            return TypeAdapter(GlofoxNodeConfig).validate_python(runtime_config_view(config_data, GlofoxNodeConfig))
        except Exception:
            raise ValueError("Glofox configuration or credential is invalid") from None

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Glofox credential")
        data = self.config.credentials.model_dump()
        session = Session(data)
        try:
            if isinstance(self.config.config, (OnUpdatedMember, OnUpdatedBooking)):
                result = await self._poll(session, self.config.config)
            else:
                result = await self._perform(session, self.config.config)
            output = {"status": "success", "success": True, "action": self.config.config.operation, **result}
        except Exception as exc:
            if session.acknowledgement is not None or (session.write_attempted and (not isinstance(exc, ProviderError) or (not exc.rejected and (exc.status is None or exc.status >= 500 or 200 <= exc.status < 300)))):
                output = {"status": "unknown", "success": False, "action": self.config.config.operation, "acknowledgement": session.acknowledgement, "message": "Glofox write outcome could not be verified. Inspect the member or notes before retrying."}
            elif isinstance(exc, ProviderError):
                output = {"status": "error", "success": False, "http_status": exc.status, "message": str(exc)}
            else:
                raise ValueError("Glofox response could not be verified") from None
        output = _redact(output, (data["api_key"], data["api_token"]))
        await self.emit(output)
        return output

    async def _poll(self, session, op):
        await session.bind_branch()
        token, rows = None, []
        listing = ListMembers if isinstance(op, OnUpdatedMember) else ListBranchBookings
        for _ in range(100):
            page = await self._list(session, listing(page_size=100, page_token=token, modified_since=op.modified_since))
            rows.extend(page["data"])
            token = page["next_page_token"]
            if token is None:
                break
        else:
            raise ValueError("Glofox poll exceeded 100 pages; choose a more recent Modified Since")
        fresh = await self._filter_unseen(rows, self._revision)
        return {"data": fresh, "branch_id": session.data["branch_id"], "new_count": len(fresh)}

    @staticmethod
    def _revision(row):
        # The documented member-list example omits optional created/modified.
        # In that case track changes to the exposed metadata without claiming a time.
        stamp = row.get("modified", row.get("created"))
        if stamp is None:
            stamp = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return f"{row['_id']}:{stamp}"

    @classmethod
    def resolve_agent_event(cls, output):
        if output.get("action") not in {"on_updated_member", "on_updated_booking"}:
            return super().resolve_agent_event(output)
        rows = output.get("data", [])
        if not rows:
            return None
        kind = "member" if output["action"] == "on_updated_member" else "booking"
        lines = []
        for row in rows[:10]:
            if kind == "member":
                detail = " ".join(row.get(k, "") for k in ("first_name", "last_name")).strip()
            else:
                detail = f"member {row.get('user_id', '')}, {row.get('event_name') or row.get('model_name') or ''}, status {row.get('status', '')}"
            lines.append(f"- {detail} ({kind} id {row['_id']}, modified {row.get('modified', row.get('created', 'not supplied'))})")
        return {"text": f"Glofox: {len(rows)} new or updated {kind}(s) in branch {output['branch_id']}:\n" + "\n".join(lines), "conversation_key": None}

    @classmethod
    async def _perform(cls, session, op):
        branch = await session.bind_branch()
        branch_id = session.data["branch_id"]
        name = op.operation
        if name in {"get_branch", "check_connection"}:
            return {"data": [branch] if name == "check_connection" else branch, "identity_verified": False, "proof": "account", "message": "Connected branch read access verified; API-key user identity and write permissions are not established"}
        if name in {"list_members", "list_classes", "list_member_bookings", "list_branch_bookings", "list_notes"}:
            if name in {"list_member_bookings", "list_notes"}:
                member = await cls._member(session, op.member_id)
                if name == "list_notes" and member.get("lead_status") not in {"LEAD", "COLD", "TRIAL", "NO_SALE_TRIAL", "TOUR", "NO_SALE_TOUR"}:
                    raise ValueError("This operation requires a current branch lead")
            return await cls._list(session, op)
        if name in {"get_member", "update_member", "add_note"}:
            member = await cls._member(session, op.member_id)
            if name == "get_member":
                return {"data": member, "scope_proof": "connected_branch_member_listing"}
            if name == "update_member":
                if member.get("first_name") != op.expected_first_name or member.get("last_name") != op.expected_last_name:
                    raise ValueError("The member's current names differ from the configured values")
                patch = {k: getattr(op, k) for k in ("first_name", "last_name") if getattr(op, k) is not None}
                row = await session.request("PUT", f"/2.0/members/{op.member_id}", body=patch, write=True)
                written = _project(session, row, "member", expected=op.member_id)
                current = await cls._member(session, op.member_id)
                if any(written.get(k) != v or current.get(k) != v for k, v in patch.items()):
                    raise ValueError("The member update could not be verified")
                return {"data": current, "readback_verified": True, "scope_proof": "connected_branch_member_listing"}
            if member.get("lead_status") not in {"LEAD", "COLD", "TRIAL", "NO_SALE_TRIAL", "TOUR", "NO_SALE_TOUR"}:
                raise ValueError("Notes require a current branch lead")
            ack = await session.request("POST", f"/2.1/branches/{branch_id}/leads/{op.member_id}/interactions", body={"user_id": op.member_id, "type": "NOTE", "description": op.description}, write=True, acknowledgement=True)
            return {"acknowledgement": ack, "member_id": op.member_id, "acknowledged": True, "readback_verified": False, "cleanup_supported": False, "message": "NOTE request acknowledged. The API does not document a returned note ID or deletion endpoint. List notes to inspect before retrying."}
        if name == "find_member_by_email":
            row = await session.request("GET", f"/2.1/branches/{branch_id}/users", params={"filters[email]": op.email})
            if not isinstance(row, dict) or not isinstance(row.get("email"), str) or row["email"].casefold() != op.email.casefold():
                raise ValueError("Glofox returned a different email match")
            return {"data": _project(session, row, "member"), "scope_proof": "explicit_branch_search_route"}
        if name == "get_class":
            row = await session.request("GET", f"/2.0/branches/{branch_id}/events/{op.class_id}")
            return {"data": _project(session, row, "class", expected=op.class_id)}
        if name == "list_contact_sources":
            rows = await session.request("GET", f"/2.3/branches/{branch_id}/leads/contact-sources")
            if not isinstance(rows, list) or len(rows) > 1000:
                raise ValueError("Glofox contact sources must be an array")
            return {"data": [{"name": _line(v)} for v in rows], "pagination": None}
        if name == "list_marketing_sources":
            rows = await session.request("GET", f"/2.3/branches/{branch_id}/leads/marketing-sources")
            if not isinstance(rows, list) or len(rows) > 1000:
                raise ValueError("Glofox marketing sources must be an array")
            out = []
            for row in rows:
                _scope(session, row)
                if type(row.get("active")) is not bool:
                    raise ValueError("Glofox source active flag is invalid")
                out.append({"_id": _id(row.get("_id")), "name": _line(row.get("name")), "code": _line(row.get("code")), "active": row["active"], "branch_id": row.get("branch_id"), "source_scope": "branch" if row.get("branch_id") is not None else "corporate_or_default"})
            return {"data": out, "pagination": None}
        raise ValueError("Unsupported Glofox operation")

    @classmethod
    async def _member(cls, session, identifier):
        # Legacy GET /members/{id} documents no branch field. First prove actual
        # presence in the authenticated branch listing, including inactive users.
        token = None
        seen = set()
        for _ in range(20):
            page = await cls._list(session, ListMembers(page_size=100, page_token=token))
            matches = [row for row in page["data"] if row["_id"] == identifier]
            if len(matches) == 1:
                row = await session.request("GET", f"/2.0/members/{identifier}")
                return _project(session, row, "member", expected=identifier)
            if len(matches) > 1:
                raise ValueError("Glofox branch listing contains duplicate member IDs")
            token = page["next_page_token"]
            if token is None:
                break
            if token in seen:
                raise ValueError("Glofox branch listing repeats its continuation")
            seen.add(token)
        raise ValueError("Member scope could not be established within the connected-branch listing bound")

    @classmethod
    async def _list(cls, session, op):
        scope = _scope_key(session, op)
        page = _page(session, scope, op.page_token)
        branch = session.data["branch_id"]
        family, kind = "base", "member"
        params = {"page": page}
        if hasattr(op, "page_size"):
            params["limit"] = op.page_size
        if op.operation == "list_members":
            route = "/2.0/members"
            params["active"] = "any"
            if op.modified_since is not None:
                params["utc_modified_start_date"] = op.modified_since
        elif op.operation == "list_classes":
            route, kind = f"/2.0/branches/{branch}/events", "class"
            params.update({"filter": "event", "start": str(op.start_utc_seconds), "end": str(op.end_utc_seconds), "active": str(op.active).lower(), "private": str(op.private_classes).lower(), "sort_by": "time_start"})
        elif op.operation == "list_member_bookings":
            route, kind = "/2.0/bookings", "booking"
            params.update({"branchId": branch, "user_id": op.member_id})
        elif op.operation == "list_branch_bookings":
            route, kind, family = f"/2.2/branches/{branch}/bookings", "booking", "branch"
            if op.modified_since is not None:
                params["modified_start_date"] = op.modified_since
            if op.booking_status is not None:
                params["status"] = op.booking_status
        else:
            route, kind, family = f"/2.1/branches/{branch}/leads/{op.member_id}/interactions", "note", "notes"
        payload = await session.request("GET", route, params=params)
        rows, pagination = _paging(payload, page, getattr(op, "page_size", None), family)
        out, identifiers = [], set()
        for row in rows:
            if family == "notes":
                _scope(session, row, require_branch=True)
                if _id(row.get("user_id")) != op.member_id:
                    raise ValueError("Glofox returned interactions for a different member")
                if row.get("type") not in {"NOTE", "MANUAL_EMAIL", "CALLED_AND_CONNECTED", "CALLED_AND_NO_ANSWER"}:
                    raise ValueError("Glofox returned an unsupported interaction type")
                if row["type"] != "NOTE":
                    continue
            projected = _project(session, row, kind, member_id=getattr(op, "member_id", None))
            if projected["_id"] in identifiers:
                raise ValueError("Glofox page contains duplicate resource IDs")
            identifiers.add(projected["_id"])
            if kind == "booking":
                if family == "branch":
                    for key in ("time_start", "time_finish"):
                        if key in projected:
                            if not isinstance(projected[key], str):
                                raise ValueError("Branch booking times must remain local strings")
                            projected[key + "_local"] = projected.pop(key)
                    for key in ("created", "modified"):
                        if key in projected and not isinstance(projected[key], str):
                            raise ValueError("Branch booking creation/modification times must be UTC strings")
                elif "time_start" in projected:
                    if type(projected["time_start"]) is not int:
                        raise ValueError("Member booking time must be UTC seconds")
                    projected["time_start_utc_seconds"] = projected.pop("time_start")
            out.append(projected)
        pagination["returned_count"] = len(out)
        return {"data": out, "pagination": pagination, "next_page_token": _token(session, scope, page + 1) if pagination["has_more"] else None}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        if field_name != "member_id":
            return []
        data = credential(credential_data)
        session = Session(data)
        await session.bind_branch()
        context = context or {}
        query = search if search is not None else context.get("search")
        search = _line(query, 200).casefold() if query else None
        operation = ListMembers(page_size=100)
        listing_scope = _scope_key(session, operation)
        lookup_scope = {**listing_scope, "purpose": "member_id_options", "search": search}
        number = _page(session, lookup_scope, page_token)
        out, identifiers, next_token = [], set(), None
        for _ in range(20):
            native_token = _token(session, listing_scope, number) if number > 1 else None
            page = await cls._list(session, ListMembers(page_size=100, page_token=native_token))
            for row in page["data"]:
                if row["_id"] in identifiers:
                    raise ValueError("Glofox lookup repeats a member ID across pages")
                identifiers.add(row["_id"])
                label = " ".join(row.get(k, "") for k in ("first_name", "last_name")).strip() or row["_id"]
                if search is None or search in label.casefold():
                    out.append({"value": row["_id"], "label": label, "metadata": {"branch_id": data["branch_id"], "lead_status": row.get("lead_status")}})
            next_token = _token(session, lookup_scope, number + 1) if page["pagination"]["has_more"] else None
            if len(out) >= 1000 or next_token is None:
                break
            number += 1
        return {"options": _redact(out[:1000], (data["api_key"], data["api_token"])), "next_page_token": next_token}
