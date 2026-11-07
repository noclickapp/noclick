"""Staffbase tenant API operations with explicit invitation/email effects.

No publish, notification-channel, membership or permission changes. Page writes
require an explicit space and news writes require an explicit channel.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client, SSRFError

TYPE = "staffbase_api_token"
FIELDS = ("credential_type", "api_base_url", "api_token")
PROFILE = {"first_name": "firstName", "last_name": "lastName", "department": "department", "location": "location", "position": "position"}
VENDOR = "application/vnd.staffbase.accessors."
MEDIA = {
    "user_list": VENDOR + "users.v2+json", "user": VENDOR + "user.v3+json",
    "user_create": VENDOR + "user-invite.v2+json", "user_update": VENDOR + "user-update.v1+json",
    "user_delete": VENDOR + "user-delete.v2+json",
    "group_list": VENDOR + "groups.v2+json", "group": VENDOR + "group.v3+json",
    "group_create": VENDOR + "group-create.v2+json", "group_update": VENDOR + "group-update.v1+json",
    "group_delete": VENDOR + "group-delete.v2+json", "members": VENDOR + "group.members-search.v1+json",
}


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("A canonical Staffbase resource ID is required")
    return value


def _text(value, maximum=500):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("A bounded single-line value without controls is required")
    return value


def _paragraph(value, maximum=100000):
    if not isinstance(value, str) or len(value) > maximum or any((ord(c) < 32 and c not in "\n\r\t") or ord(c) == 127 for c in value):
        raise ValueError("Bounded text or HTML without unsafe controls is required")
    return value


def _name(value):
    value = _text(value)
    if not value.strip():
        raise ValueError("A nonempty name or title is required")
    return value


def _locale(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z]{2,3}_[A-Z]{2}", value):
        raise ValueError("A Staffbase locale such as en_US is required")
    return value


def _base(value):
    if not isinstance(value, str) or len(value) > 512 or not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
        raise ValueError("Copy the public HTTPS API root from Staffbase Studio")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if parsed.scheme != "https" or parsed.username is not None or parsed.password is not None or parsed.port not in {None, 443} or parsed.query or parsed.fragment or parsed.path not in {"/api", "/api/"}:
            raise ValueError()
        if not host or len(host) > 253 or "." not in host or not re.fullmatch(r"[a-zA-Z0-9.-]+", host) or host.endswith(".") or all(c.isdigit() or c == "." for c in host):
            raise ValueError()
        if any(not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label) for label in host.split(".")):
            raise ValueError()
    except ValueError:
        raise ValueError("A public HTTPS tenant API root ending in /api is required") from None
    return "https://" + host.lower() + "/api"


def _api_token(value):
    if not isinstance(value, str) or not 4 <= len(value) <= 4096 or not value.isascii() or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", value):
        raise ValueError("Paste the already encoded API token, without the Basic prefix")
    try:
        if not base64.b64decode(value, validate=True):
            raise ValueError()
    except Exception:
        raise ValueError("An already base64-encoded Staffbase API token is required") from None
    return value


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class StaffbaseApiTokenCredential(_Closed):
    model_config = ConfigDict(title="Staffbase Prepared API Token", extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://developers.staffbase.com/concepts/authentication/"})
    credential_type: Literal["staffbase_api_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_base_url: str = Field(..., title="Tenant API Root", description="Copy the HTTPS root from Studio, for example https://exampleapp.staffbase.com/api. Private hosts and redirects are refused.")
    api_token: str = Field(..., title="Prepared API Token", description="Paste the API token from Studio. It is already encoded and is sent once as Authorization: Basic token; omit the Basic prefix.", repr=False, json_schema_extra={"ui:widget": "password"})
    _url = field_validator("api_base_url", mode="before")(_base)
    _token = field_validator("api_token", mode="before")(_api_token)

    @model_validator(mode="before")
    @classmethod
    def manual_tag(cls, value):
        return {"credential_type": TYPE, **value} if isinstance(value, dict) and "credential_type" not in value else value


def credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != TYPE:
        raise ValueError("A canonical Staffbase API token credential is required")
    try:
        return StaffbaseApiTokenCredential.model_validate({k: data[k] for k in FIELDS if k in data}).model_dump()
    except Exception:
        raise ValueError("The Staffbase tenant credential is invalid") from None


def _dynamic(kind, parent=None):
    return {"x-resource-type": "staffbase_" + kind, "x-dynamic-options": {"field_name": kind + "_id", "searchable": True, "allow_custom": True, **({"depends_on": parent} if parent else {})}}


class _Page(_Closed):
    page_size: int = Field(100, ge=1, le=100, strict=True, title="Page Size")
    page_token: str | None = Field(None, max_length=8192, title="Continuation")


class _User(_Closed):
    user_id: str = Field(..., title="User", json_schema_extra=_dynamic("user"))
    _identifier = field_validator("user_id", mode="before")(_id)


class _Group(_Closed):
    group_id: str = Field(..., title="Group", json_schema_extra=_dynamic("group"))
    _identifier = field_validator("group_id", mode="before")(_id)


class _Channel(_Closed):
    channel_id: str = Field(..., title="News Channel", json_schema_extra=_dynamic("channel"))
    _identifier = field_validator("channel_id", mode="before")(_id)


class _Post(_Channel):
    post_id: str = Field(..., title="News Post", json_schema_extra=_dynamic("post", "channel_id"))
    _post_identifier = field_validator("post_id", mode="before")(_id)


class _Space(_Closed):
    space_id: str = Field(..., title="Page Space ID", description="An explicit existing space. Omitting it would target the All Employees space.")
    _identifier = field_validator("space_id", mode="before")(_id)


class _PageResource(_Space):
    page_id: str = Field(..., title="Page", json_schema_extra=_dynamic("page", "space_id"))
    _page_identifier = field_validator("page_id", mode="before")(_id)


class _Profile(_Closed):
    first_name: str | None = Field(None, title="First Name", max_length=500)
    last_name: str | None = Field(None, title="Last Name", max_length=500)
    department: str | None = Field(None, title="Department", max_length=500)
    location: str | None = Field(None, title="Location", max_length=500)
    position: str | None = Field(None, title="Position", max_length=500)
    _strings = field_validator("first_name", "last_name", "department", "location", "position", mode="before")(lambda v: _text(v) if v is not None else None)


class _Localized(_Closed):
    locale: str = Field("en_US", title="Locale", description="A Staffbase locale such as en_US.")
    title: str = Field(..., title="Title", max_length=500)
    content: str | None = Field(None, title="Text or HTML Content", max_length=100000, json_schema_extra={"ui:widget": "textarea"})
    _language = field_validator("locale", mode="before")(_locale)
    _title = field_validator("title", mode="before")(_name)
    _content = field_validator("content", mode="before")(lambda v: _paragraph(v) if v is not None else None)


class ListUsers(_Page):
    operation: Literal["list_users"] = Field("list_users", title="List Users", json_schema_extra={"ui:hidden": True})


class GetUser(_User):
    operation: Literal["get_user"] = Field("get_user", title="Get User", json_schema_extra={"ui:hidden": True})


class CreateUser(_Profile):
    operation: Literal["create_user"] = Field("create_user", title="Create Pending Reader User", description="Uses InviteUser v2. Creation and invitation effects follow Staffbase; this is not a silent-user guarantee.", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., title="Email", max_length=254)
    locale: str = Field("en_US", title="User Locale")
    _email = field_validator("email", mode="before")(_text)
    _locale = field_validator("locale", mode="before")(_locale)

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("A valid user email is required")
        return value


class UpdateUser(_User, _Profile):
    operation: Literal["update_user"] = Field("update_user", title="Update User Profile", json_schema_extra={"ui:hidden": True})
    send_mail: bool = Field(False, strict=True, title="Send Signup Email", description="True requests a signup email for a pending user. This has an outbound effect; delivery cannot be proven by readback.")


class DeleteUser(_User):
    operation: Literal["delete_user"] = Field("delete_user", title="Delete Reader User Permanently", description="Permanent user deletion cannot be restored. Native code refuses users whose role is not reader.", json_schema_extra={"ui:hidden": True})


class ListGroups(_Page):
    operation: Literal["list_groups"] = Field("list_groups", title="List Groups", json_schema_extra={"ui:hidden": True})


class GetGroup(_Group):
    operation: Literal["get_group"] = Field("get_group", title="Get Group", json_schema_extra={"ui:hidden": True})


class _GroupText(_Closed):
    locale: str = Field("en_US", title="Locale")
    name: str = Field(..., title="Group Name", max_length=500)
    description: str | None = Field(None, title="Description", max_length=2000)
    _language = field_validator("locale", mode="before")(_locale)
    _name = field_validator("name", mode="before")(_name)
    _description = field_validator("description", mode="before")(lambda v: _paragraph(v, 2000) if v is not None else None)


class CreateGroup(_GroupText):
    operation: Literal["create_group"] = Field("create_group", title="Create Group Metadata", description="No membership or administrator IDs are supplied; vendor defaults and visibility still apply.", json_schema_extra={"ui:hidden": True})


class UpdateGroup(_Group, _GroupText):
    operation: Literal["update_group"] = Field("update_group", title="Update Group Name and Description", json_schema_extra={"ui:hidden": True})


class DeleteGroup(_Group):
    operation: Literal["delete_group"] = Field("delete_group", title="Delete Group", description="Deletion may affect access through this group; no quiet or reversible deletion guarantee.", json_schema_extra={"ui:hidden": True})


class ListGroupMembers(_Group, _Page):
    operation: Literal["list_group_members"] = Field("list_group_members", title="List Group Members", json_schema_extra={"ui:hidden": True})


class ListChannels(_Page):
    operation: Literal["list_channels"] = Field("list_channels", title="List Manageable News Channels", json_schema_extra={"ui:hidden": True})


class GetChannel(_Channel):
    operation: Literal["get_channel"] = Field("get_channel", title="Get News Channel", json_schema_extra={"ui:hidden": True})


class ListPosts(_Channel, _Page):
    operation: Literal["list_posts"] = Field("list_posts", title="List Channel Posts", json_schema_extra={"ui:hidden": True})


class GetPost(_Post):
    operation: Literal["get_post"] = Field("get_post", title="Get Channel Post", json_schema_extra={"ui:hidden": True})


class CreateDraftPost(_Channel, _Localized):
    operation: Literal["create_draft_post"] = Field("create_draft_post", title="Create Draft News Post", description="Does not supply publish dates or notification channels. No blanket silence guarantee.", json_schema_extra={"ui:hidden": True})
    teaser: str | None = Field(None, title="Teaser", max_length=500)
    _teaser = field_validator("teaser", mode="before")(lambda v: _text(v) if v is not None else None)


class UpdateDraftPost(_Post, _Localized):
    operation: Literal["update_draft_post"] = Field("update_draft_post", title="Update Draft News Post", description="Requires explicit null planned/published dates; text-only localized content. Scheduled or unknown states are refused.", json_schema_extra={"ui:hidden": True})
    teaser: str | None = Field(None, title="Teaser", max_length=500)
    _teaser = field_validator("teaser", mode="before")(lambda v: _text(v) if v is not None else None)


class DeleteDraftPost(_Post):
    operation: Literal["delete_draft_post"] = Field("delete_draft_post", title="Delete Draft News Post", description="Staffbase may move a post to trash. Exact absence is checked; restoration and hard deletion are not promised.", json_schema_extra={"ui:hidden": True})


class ListPages(_Space, _Page):
    operation: Literal["list_pages"] = Field("list_pages", title="List Space Pages", json_schema_extra={"ui:hidden": True})
    status: Literal["DRAFT", "PUBLISHED"] | None = Field(None, title="Publication Filter")


class GetPage(_PageResource):
    operation: Literal["get_page"] = Field("get_page", title="Get Space Page", json_schema_extra={"ui:hidden": True})


class CreateDraftPage(_Space, _Localized):
    operation: Literal["create_draft_page"] = Field("create_draft_page", title="Create Draft Page", description="Sends published=false and an explicit existing space. Vendor access defaults still apply.", json_schema_extra={"ui:hidden": True})


class UpdateDraftPage(_PageResource, _Localized):
    operation: Literal["update_draft_page"] = Field("update_draft_page", title="Update Draft Page", description="Requires current membership in this space's DRAFT-filtered list; preserves other text locales.", json_schema_extra={"ui:hidden": True})


class DeleteDraftPage(_PageResource):
    operation: Literal["delete_draft_page"] = Field("delete_draft_page", title="Delete Draft Page", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[ListUsers, GetUser, CreateUser, UpdateUser, DeleteUser, ListGroups, GetGroup, CreateGroup, UpdateGroup, DeleteGroup, ListGroupMembers, ListChannels, GetChannel, ListPosts, GetPost, CreateDraftPost, UpdateDraftPost, DeleteDraftPost, ListPages, GetPage, CreateDraftPage, UpdateDraftPage, DeleteDraftPage], Field(discriminator="operation")]


class StaffbaseNodeConfig(NodeConfig[Operation, StaffbaseApiTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class ProviderError(ValueError):
    def __init__(self, status=None, message="Staffbase response could not be verified", *, ambiguous=False):
        self.status, self.ambiguous = status, ambiguous
        super().__init__(message)


class Session:
    def __init__(self, data):
        self.data = credential(data)
        self.base = self.data["api_base_url"]

    async def request(self, method, route, *, params=None, body=None, accept="application/json", content_type="application/json"):
        allowed = re.fullmatch(r"/(?:users(?:/[A-Za-z0-9][A-Za-z0-9_-]{0,127})?|groups(?:/[A-Za-z0-9][A-Za-z0-9_-]{0,127}(?:/members/search)?)?|branch/channels|channels/[A-Za-z0-9][A-Za-z0-9_-]{0,127}(?:/posts)?|posts/[A-Za-z0-9][A-Za-z0-9_-]{0,127}|pages(?:/[A-Za-z0-9][A-Za-z0-9_-]{0,127})?)", route)
        if method not in {"GET", "POST", "PATCH", "PUT", "DELETE"} or not allowed or accept not in {"application/json", *MEDIA.values()} or content_type not in {"application/json", *MEDIA.values()}:
            raise ValueError("Unsupported Staffbase route or media type")
        methods = {"GET"}
        if route in {"/users", "/groups", "/pages"} or re.fullmatch(r"/channels/[^/]+/posts", route):
            methods.add("POST")
        elif re.fullmatch(r"/(?:users|groups)/[^/]+", route):
            methods.update({"PATCH", "DELETE"})
        elif re.fullmatch(r"/(?:posts|pages)/[^/]+", route):
            methods.update({"PUT", "DELETE"})
        if method not in methods:
            raise ValueError("Unsupported Staffbase method for this route")
        if params and set(params) - {"limit", "cursor", "offset", "includeProfile", "status", "spaceIds"}:
            raise ValueError("Unsupported Staffbase query")
        if method != "GET" and (route.startswith("/branch/") or re.fullmatch(r"/channels/[^/]+", route) or route.endswith("/members/search")):
            raise ValueError("Channel, membership and permission mutations are unsupported")
        try:
            result = await asyncio.wait_for(self._request(method, route, params, body, accept, content_type), timeout=25)
        except (TimeoutError, httpx.HTTPError, OSError, SSRFError):
            raise ProviderError(None, "Staffbase request did not complete; inspect before retrying a write", ambiguous=method != "GET") from None
        return result

    async def _request(self, method, route, params, body, accept, content_type):
        headers = {"Authorization": "Basic " + self.data["api_token"], "Accept": accept}
        if body is not None:
            headers["Content-Type"] = content_type
        expected = 204 if method == "DELETE" else 201 if method == "POST" and route != "/pages" else 200
        async with guarded_async_client(verify=True, trust_env=False, follow_redirects=False, timeout=httpx.Timeout(20.0)) as client:
            async with client.stream(method, self.base + route, headers=headers, params=params, **({"json": body} if body is not None else {})) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2 * 1024 * 1024:
                        raise ProviderError(response.status_code, "Staffbase response exceeds the supported size", ambiguous=method != "GET" and 200 <= response.status_code < 300)
                if response.status_code != expected:
                    message = "Staffbase did not return the documented completed status"
                    try:
                        error = json.loads(raw)
                        if isinstance(error, dict):
                            candidate = error.get("message") or error.get("error")
                            if isinstance(candidate, str):
                                message += ": " + _text(candidate, 1000)
                    except (ValueError, TypeError, UnicodeError):
                        pass
                    raise ProviderError(response.status_code, message, ambiguous=method != "GET" and (response.status_code < 400 or response.status_code >= 500))
                if expected == 204:
                    if raw.strip():
                        raise ProviderError(204, "Staffbase deletion returned an unexpected body", ambiguous=True)
                    return {"data": None, "http_status": 204}
                media = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if media != "application/json" and not (media.startswith("application/") and media.endswith("+json")):
                    raise ProviderError(expected, "Staffbase returned an unsupported representation", ambiguous=method != "GET")
                try:
                    payload = json.loads(raw)
                    if not isinstance(payload, dict) or payload.get("errors") or payload.get("error") or payload.get("success") is False:
                        raise ValueError()
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    raise ProviderError(expected, "Staffbase JSON envelope could not be verified", ambiguous=method != "GET") from None
                return {"data": payload, "http_status": expected}


def _contents(value, *, write=False, page=False):
    if not isinstance(value, dict) or not value or len(value) > 100:
        raise ValueError("Staffbase localized content is invalid")
    out = {}
    for locale, fields in value.items():
        _locale(locale)
        if not isinstance(fields, dict) or not isinstance(fields.get("title"), str):
            raise ValueError("Staffbase localized title is invalid")
        allowed = {"title", "content"} if page else {"title", "teaser", "content"}
        if write and set(fields) - allowed:
            raise ValueError("Updating content with media or unsupported localized fields is refused")
        out[locale] = {"title": _name(fields["title"])}
        if isinstance(fields.get("teaser"), str) and not page:
            out[locale]["teaser"] = _text(fields["teaser"])
        if write and fields.get("content") is not None:
            out[locale]["content"] = _paragraph(fields["content"])
    return out


def _project(raw, kind, *, expected=None, parent=None):
    if not isinstance(raw, dict):
        raise ValueError("Staffbase resource is invalid")
    identifier = _id(raw.get("id"))
    if expected is not None and identifier != expected:
        raise ValueError("Staffbase returned a different resource")
    out = {"id": identifier}
    if kind == "user":
        if raw.get("status") not in {"pending", "activated", "deactivated", "contact", "deleted"}:
            raise ValueError("Staffbase user status is invalid")
        out["status"] = raw["status"]
        for key in ("role", "email", "userName", "externalId", "createdAt", "activatedAt"):
            if raw.get(key) is not None:
                out[key] = _text(raw[key], 1000)
        profile = raw.get("profile", {})
        if not isinstance(profile, dict):
            raise ValueError("Staffbase user profile is invalid")
        out["profile"] = {key: _text(profile[key]) for key in PROFILE.values() if key in profile and profile[key] is not None}
        out["name"] = " ".join(out["profile"].get(k, "") for k in ("firstName", "lastName")).strip() or out.get("email") or "User " + identifier
    elif kind == "group":
        if raw.get("type") not in {"conditional", "internal", "open"}:
            raise ValueError("Staffbase group type is invalid")
        out["type"] = raw["type"]
        config = raw.get("config")
        localized = config.get("localization") if isinstance(config, dict) else None
        if not isinstance(localized, dict) or not localized:
            raise ValueError("Staffbase group localization is invalid")
        out["localization"] = {}
        for locale, fields in localized.items():
            _locale(locale)
            if not isinstance(fields, dict) or not isinstance(fields.get("name"), str):
                raise ValueError("Staffbase group name is invalid")
            out["localization"][locale] = {"name": _name(fields["name"]), **({"description": _paragraph(fields["description"], 2000)} if fields.get("description") is not None else {})}
        out["name"] = next(iter(out["localization"].values()))["name"]
    elif kind == "channel":
        config = raw.get("config")
        localized = config.get("localization") if isinstance(config, dict) else None
        if not isinstance(localized, dict) or not localized:
            raise ValueError("Staffbase channel localization is invalid")
        out["localization"] = {}
        for locale, fields in localized.items():
            _locale(locale)
            if not isinstance(fields, dict):
                raise ValueError("Staffbase channel metadata is invalid")
            out["localization"][locale] = {"title": _name(fields.get("title"))}
        out["title"] = next(iter(out["localization"].values()))["title"]
    else:
        key = "channelID" if kind == "post" else "spaceId"
        out[key] = _id(raw.get(key))
        if parent is not None and out[key] != parent:
            raise ValueError("Staffbase resource belongs to another parent")
        out["contents"] = _contents(raw.get("contents"), page=kind == "page")
        out["title"] = next(iter(out["contents"].values()))["title"]
        for key in (("planned", "published", "created", "updated", "externalID") if kind == "post" else ("branchId", "createdAt", "updatedAt", "publishedAt", "externalId")):
            if key in raw:
                out[key] = _text(raw[key], 1000) if raw[key] is not None else None
    return out


def _redact(value, data):
    secrets = [data["api_token"]]
    try:
        decoded = base64.b64decode(data["api_token"]).decode("utf-8")
        secrets.extend([decoded, decoded.split(":", 1)[-1]])
    except (ValueError, UnicodeError):
        pass
    secrets = [s for s in secrets if len(s) >= 4]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, dict):
        return {_redact(k, data): _redact(v, data) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, data) for v in value]
    return value


def _signature(session, scope):
    wire = json.dumps({"tenant": session.base, "scope": scope}, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(session.data["api_token"].encode(), wire, hashlib.sha256).hexdigest()


def _token(session, scope, position):
    payload = json.dumps({"scope": _signature(session, scope), "position": position}, sort_keys=True, separators=(",", ":")).encode()
    mac = hmac.new(session.data["api_token"].encode(), payload, hashlib.sha256).hexdigest().encode()
    return base64.urlsafe_b64encode(payload + b"." + mac).decode()


def _position(session, scope, token, *, offset=False):
    if token is None:
        return 0 if offset else None
    try:
        if not isinstance(token, str) or len(token) > 8192 or not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", token):
            raise ValueError()
        raw = base64.b64decode(token, altchars=b"-_", validate=True)
        payload, mac = raw.rsplit(b".", 1)
        if not hmac.compare_digest(mac, hmac.new(session.data["api_token"].encode(), payload, hashlib.sha256).hexdigest().encode()):
            raise ValueError()
        decoded = json.loads(payload)
        if set(decoded) != {"scope", "position"} or not hmac.compare_digest(decoded["scope"], _signature(session, scope)):
            raise ValueError()
        value = decoded["position"]
        if offset:
            if type(value) is not int or not 0 <= value <= 10000000:
                raise ValueError()
        else:
            _cursor(value)
        return value
    except Exception:
        raise ValueError("Staffbase continuation does not belong to this tenant, credential, parent and request") from None


def _cursor(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096 or not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise ValueError("Staffbase returned an invalid cursor")
    return value


class StaffbaseNode(WorkflowNode):
    integration_type = "automation-staffbase"
    connection_evidence = ConnectionEvidence(noun="users", operation="list_users", label_keys=("name", "email", "id"), proves="reachability")
    edit_examples = ["Find users in this tenant", "Update this group description", "Create a draft page in this space"]

    @classmethod
    def get_config_model(cls):
        return StaffbaseNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        if not isinstance(config_data, dict):
            raise ValueError("Staffbase configuration is required")
        if config_data.get("credentials") is not None:
            config_data = {**config_data, "credentials": credential(config_data["credentials"])}
        try:
            return TypeAdapter(StaffbaseNodeConfig).validate_python(runtime_config_view(config_data, StaffbaseNodeConfig))
        except Exception:
            raise ValueError("Staffbase configuration or credential is invalid") from None

    @classmethod
    async def validate_credential_access(cls, credential_data):
        data = credential(credential_data)
        try:
            await cls._list(Session(data), ListUsers())
        except ProviderError as exc:
            return {"valid": False if exc.status in {401, 403} else None,
                    "identity_verified": False, "message": _redact(str(exc), data)}
        except ValueError:
            return {"valid": None, "identity_verified": False,
                    "message": "Staffbase user-list access could not be verified"}
        return {"valid": True, "identity_verified": False,
                "message": "Staffbase accepted the token for listing users; identity and write grants remain unverified"}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Staffbase tenant API token")
        data = credential(self.config.credentials.model_dump())
        session = Session(data)
        try:
            result = await self._perform(session, self.config.config)
            output = {"status": "success", "success": True, "action": self.config.config.operation, "identity_verified": False, **result}
        except ProviderError as exc:
            output = {"status": "unknown" if exc.ambiguous else "error", "success": False, "http_status": exc.status, "identity_verified": False, "message": str(exc), "write_outcome": "unverified" if exc.ambiguous else None}
        except Exception:
            raise ValueError("Staffbase response could not be verified") from None
        output = _redact(output, data)
        await self.emit(output)
        return output

    @classmethod
    async def _get(cls, session, kind, identifier, *, parent=None, raw=False):
        accept = MEDIA[kind] if kind in {"user", "group"} else "application/json"
        route = "/" + {"user": "users", "group": "groups", "channel": "channels", "post": "posts", "page": "pages"}[kind] + "/" + identifier
        result = await session.request("GET", route, accept=accept, params={"includeProfile": "true"} if kind == "user" else None)
        projected = _project(result["data"], kind, expected=identifier, parent=parent)
        return (result["data"], projected) if raw else projected

    @classmethod
    async def _list(cls, session, op, *, scope_extra=None):
        action = op.operation
        scope = {"config": op.model_dump(exclude={"page_token"}), **(scope_extra or {})}
        offset_mode = action == "list_posts"
        position = _position(session, scope, op.page_token, offset=offset_mode)
        params = {"limit": op.page_size}
        if position is not None:
            params["offset" if offset_mode else "cursor"] = position
        if action in {"list_users", "list_group_members"}:
            params["includeProfile"] = "true"
        if action == "list_users":
            kind, route, accept = "user", "/users", MEDIA["user_list"]
        elif action == "list_groups":
            kind, route, accept = "group", "/groups", MEDIA["group_list"]
        elif action == "list_group_members":
            await cls._get(session, "group", op.group_id)
            kind, route, accept = "user", "/groups/" + op.group_id + "/members/search", MEDIA["members"]
        elif action == "list_channels":
            kind, route, accept = "channel", "/branch/channels", "application/json"
        elif action == "list_posts":
            await cls._get(session, "channel", op.channel_id)
            kind, route, accept = "post", "/channels/" + op.channel_id + "/posts", "application/json"
        elif action == "list_pages":
            kind, route, accept = "page", "/pages", "application/json"
            params["spaceIds"] = op.space_id
            if op.status is not None:
                params["status"] = op.status
        else:
            raise ValueError("Unsupported Staffbase list operation")
        result = await session.request("GET", route, params=params, accept=accept)
        payload = result["data"]
        if action in {"list_users", "list_groups"}:
            rows = payload.get("entries")
            following = payload.get("nextCursor")
        elif action == "list_group_members":
            entries = payload.get("entries")
            rows = entries.get("data") if isinstance(entries, dict) else None
            following = payload.get("nextCursor")
        else:
            rows = payload.get("data")
            following = payload.get("cursor") if not offset_mode else None
        if not isinstance(rows, list) or len(rows) > op.page_size:
            raise ValueError("Staffbase list envelope is invalid")
        parent = getattr(op, "channel_id", None) if kind == "post" else getattr(op, "space_id", None) if kind == "page" else None
        data = [_project(row, kind, parent=parent) for row in rows]
        if len({row["id"] for row in data}) != len(data):
            raise ValueError("Staffbase repeats a resource in the page")
        total = payload.get("total")
        if total is not None and (type(total) is not int or total < len(data) or total < 0):
            raise ValueError("Staffbase list total is invalid")
        if action not in {"list_users", "list_groups"}:
            if type(total) is not int:
                raise ValueError("Staffbase list total is missing")
        if action in {"list_channels", "list_posts", "list_pages"} and (type(payload.get("limit")) is not int or payload["limit"] != op.page_size):
            raise ValueError("Staffbase list limit differs from this request")
        if offset_mode:
            if type(payload.get("offset")) is not int or payload["offset"] != position or position + len(data) > total:
                raise ValueError("Staffbase list offset or total differs from this request")
            has_more = position + len(data) < total
            if has_more and len(data) != op.page_size:
                raise ValueError("Staffbase returned an incomplete nonterminal offset page")
            next_position = position + op.page_size if has_more and position + op.page_size <= 10000000 else None
        else:
            if following is not None:
                _cursor(following)
                if not rows or following == position:
                    raise ValueError("Staffbase returned a nonadvancing cursor")
            has_more, next_position = following is not None, following
        return {"data": data, "pagination": {"limit": op.page_size, "total": total, "has_more": has_more, "bounded_stop": has_more and next_position is None}, "next_page_token": _token(session, scope, next_position) if next_position is not None else None, "http_status": 200}

    @classmethod
    async def _draft_page(cls, session, identifier, parent):
        listing = ListPages(space_id=parent, status="DRAFT")
        seen = set()
        for _ in range(20):
            result = await cls._list(session, listing)
            if any(row["id"] == identifier for row in result["data"]):
                raw, row = await cls._get(session, "page", identifier, parent=parent, raw=True)
                if raw.get("publishedAt") is not None:
                    raise ValueError("Staffbase page is published or its draft state changed")
                return raw, row
            token = result["next_page_token"]
            if token is None:
                break
            if token in seen:
                raise ValueError("Staffbase repeats a page-draft cursor")
            seen.add(token)
            listing = listing.model_copy(update={"page_token": token})
        raise ValueError("The page's draft state could not be proven in this explicit space")

    @classmethod
    async def _perform(cls, session, op):
        action = op.operation
        if action.startswith("list_"):
            return await cls._list(session, op)
        kind = "post" if action.endswith("_post") else "page" if action.endswith("_page") else action.split("_")[-1]
        identifier = getattr(op, kind + "_id", None)
        parent = getattr(op, "channel_id", None) if kind == "post" else getattr(op, "space_id", None) if kind == "page" else None
        if kind == "post":
            await cls._get(session, "channel", parent)
        if action.startswith("get_"):
            return {"data": await cls._get(session, kind, identifier, parent=parent), "http_status": 200}
        creating, deleting = action.startswith("create_"), action.startswith("delete_")
        previous = None
        if not creating:
            if kind == "page":
                previous, _ = await cls._draft_page(session, identifier, parent)
            else:
                previous, projected = await cls._get(session, kind, identifier, parent=parent, raw=True)
                if kind == "post" and not ("planned" in previous and "published" in previous and previous["planned"] is None and previous["published"] is None):
                    raise ValueError("Staffbase news writes require an explicit unscheduled, unpublished draft")
                if kind == "user" and deleting and projected.get("role") != "reader":
                    raise ValueError("Native Staffbase user deletion is limited to reader users")
        body = None if deleting else cls._body(op, kind, previous)
        route = "/channels/" + parent + "/posts" if creating and kind == "post" else "/" + {"user": "users", "group": "groups", "post": "posts", "page": "pages"}[kind] + ("/" + identifier if identifier else "")
        method = "DELETE" if deleting else "POST" if creating else "PATCH" if kind in {"user", "group"} else "PUT"
        accept = MEDIA[kind + "_delete"] if deleting and kind in {"user", "group"} else MEDIA[kind] if kind in {"user", "group"} else "application/json"
        content_type = MEDIA[kind + ("_create" if creating else "_update")] if kind in {"user", "group"} and not deleting else "application/json"
        result = await session.request(method, route, body=body, accept=accept, content_type=content_type)
        if deleting:
            try:
                await cls._get(session, kind, identifier, parent=parent)
            except ProviderError as exc:
                if exc.status == 404:
                    return {"deleted_id": identifier, "deletion_acknowledged": True, "absence_verified": True, "http_status": 204, "hard_delete_verified": False}
                raise ProviderError(exc.status, "Staffbase acknowledged deletion, but absence could not be verified", ambiguous=True) from None
            except Exception:
                raise ProviderError(204, "Staffbase acknowledged deletion, but exact resource absence could not be verified", ambiguous=True) from None
            raise ProviderError(204, "Staffbase acknowledged deletion, but the resource remains visible", ambiguous=True)
        try:
            written = _project(result["data"], kind, expected=identifier, parent=parent)
            identifier = written["id"]
            raw, row = await cls._get(session, kind, identifier, parent=parent, raw=True)
            if kind == "user":
                expected = body.get("profile", {})
                if any(raw.get("profile", {}).get(k) != v for k, v in expected.items()):
                    raise ValueError()
                if creating and (raw.get("email") != op.email or raw.get("role") != "reader" or raw.get("status") != "pending" or raw.get("config", {}).get("locale") != op.locale):
                    raise ValueError()
            elif kind == "group":
                if raw.get("config", {}).get("localization") != body["config"]["localization"]:
                    raise ValueError()
            else:
                if kind == "post" and not ("planned" in raw and "published" in raw and raw["planned"] is None and raw["published"] is None):
                    raise ValueError()
                if kind == "page":
                    raw, row = await cls._draft_page(session, identifier, parent)
                if raw.get("contents") != body["contents"]:
                    raise ValueError()
        except Exception:
            raise ProviderError(result["http_status"], "Staffbase acknowledged the write, but exact resource, parent, fields or draft state could not be verified; inspect before retrying", ambiguous=True) from None
        return {"data": row, "written_id": identifier, "readback_verified": True, "http_status": result["http_status"], **({"send_mail_requested": op.send_mail, "mail_delivery_verified": False} if isinstance(op, UpdateUser) else {}), **({"invitation_effects_verified": False} if isinstance(op, CreateUser) else {})}

    @classmethod
    def _body(cls, op, kind, previous):
        if kind == "user":
            profile = {target: getattr(op, source) for source, target in PROFILE.items() if getattr(op, source) is not None}
            if isinstance(op, CreateUser):
                return {"email": op.email, "role": "reader", "status": "pending", "config": {"locale": op.locale}, **({"profile": profile} if profile else {})}
            if not profile and not op.send_mail:
                raise ValueError("Provide a profile field or explicitly request the signup email")
            return {**({"profile": profile} if profile else {}), "sendMail": op.send_mail}
        if kind == "group":
            localized = {}
            if previous is not None:
                value = previous.get("config", {}).get("localization")
                if not isinstance(value, dict):
                    raise ValueError("Staffbase group localization is unavailable")
                for locale, fields in value.items():
                    _locale(locale)
                    if not isinstance(fields, dict) or set(fields) - {"name", "description"}:
                        raise ValueError("Updating unsupported group localization fields is refused")
                    localized[locale] = {"name": _name(fields.get("name")), **({"description": _paragraph(fields["description"], 2000)} if fields.get("description") is not None else {})}
            localized[op.locale] = {**localized.get(op.locale, {}), "name": op.name, **({"description": op.description} if op.description is not None else {})}
            return {"config": {"localization": localized}}
        contents = _contents(previous["contents"], write=True, page=kind == "page") if previous is not None else {}
        contents[op.locale] = {**contents.get(op.locale, {}), "title": op.title, **({"content": op.content} if op.content is not None else {})}
        if kind == "post" and op.teaser is not None:
            contents[op.locale]["teaser"] = op.teaser
        return {"contents": contents, **({"spaceId": op.space_id, "published": False} if kind == "page" else {})}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        if field_name not in {"user_id", "group_id", "channel_id", "post_id", "page_id"}:
            return []
        data = credential(credential_data)
        session = Session(data)
        context = context or {}
        listing = {"user_id": ListUsers, "group_id": ListGroups, "channel_id": ListChannels}.get(field_name)
        if listing is not None:
            listing = listing()
        elif field_name == "post_id":
            listing = ListPosts(channel_id=_id(context.get("channel_id")))
        else:
            listing = ListPages(space_id=_id(context.get("space_id")))
        query = search if search is not None else context.get("search")
        query = _text(query, 200).casefold() if query else None
        extra = {"purpose": field_name + "_options", "search": query}
        listing = listing.model_copy(update={"page_token": page_token})
        out, seen_ids, seen_tokens, next_token = [], set(), set(), None
        for _ in range(20):
            result = await cls._list(session, listing, scope_extra=extra)
            for row in result["data"]:
                if row["id"] in seen_ids:
                    raise ValueError("Staffbase repeats a resource across lookup pages")
                seen_ids.add(row["id"])
                label = row.get("name") or row.get("title") or field_name[:-3].title() + " " + row["id"]
                if query is None or query in label.casefold():
                    out.append({"value": row["id"], "label": label, "metadata": {k: row[k] for k in ("channelID", "spaceId") if k in row}})
            next_token = result["next_page_token"]
            if len(out) >= 1000 or next_token is None:
                break
            if next_token in seen_tokens:
                raise ValueError("Staffbase repeats a lookup continuation")
            seen_tokens.add(next_token)
            listing = listing.model_copy(update={"page_token": next_token})
        return {"options": _redact(out, data), "next_page_token": next_token}
