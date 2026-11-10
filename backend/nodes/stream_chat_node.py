"""Native Stream Chat server operations, with bounded metadata projections.

Pinned public Chat OpenAPI and official server SDK contracts are recorded in
public integration docs. Server JWTs are minted only at the request boundary.
"""
from __future__ import annotations

import base64
from contextvars import ContextVar
import hashlib
import hmac
import json
import logging
import re
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret


class StreamChatCredentialUnavailable(ValueError):
    pass


class _StoredCredential:
    """Recheck staging's resolver and the saved row around each provider call."""

    def __init__(self, pool, user_id, credential_id):
        self.pool, self.user_id, self.credential_id = pool, user_id, credential_id
        self.current = None

    async def load(self):
        from utils.credentials import resolve_credential_with_owner_fallback
        from utils.database_pool import get_native_pool
        from wss.handlers.workflow_handler import get_user_org_context

        if self.pool is None:
            self.pool = get_native_pool()
        async with self.pool.acquire() as conn:
            org = await get_user_org_context(conn, self.user_id)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT owner_id, credential_type, token_version, updated_at, revoked_at "
                "FROM credentials WHERE id = $1", self.credential_id,
            )
        if (not row or row["revoked_at"] is not None or row["credential_type"] != FAMILY
                or type(row["token_version"]) is not int or row["token_version"] < 1):
            raise ValueError("Stream Chat saved credential is unavailable.")
        data = await resolve_credential_with_owner_fallback(
            self.credential_id, self.user_id, self.pool, org_id=org,
        )
        shaped = _shape(data)
        self.current = (org, *(row[k] for k in ("owner_id", "credential_type", "token_version", "updated_at")))
        return {**shaped, "token_version": row["token_version"],
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None}

NODE = "automation-stream-chat"
FAMILY = "stream_chat_api_key"
BASE = "https://chat.stream-io-api.com"
_ID = re.compile(r"[A-Za-z0-9_@.-]{1,64}\Z")
_PRIVATE_REQUEST = ContextVar("stream_chat_private_request", default=False)


class _TransportPrivacy(logging.Filter):
    def filter(self, record):
        if _PRIVATE_REQUEST.get():
            record.msg, record.args = "Stream Chat transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_PRIVACY = _TransportPrivacy()


def _id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value) or value in (".", ".."):
        raise ValueError("Use a Stream Chat ID, without a URL or path.")
    return value


class StreamChatServerCredential(BaseModel):
    credential_type: Literal["stream_chat_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., title="API Secret", description="Server secret from the same Stream Chat application.", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Stream Chat Server Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://dashboard.getstream.io/", "x-credential-instructions": "Use your application's API key and server secret. These are server credentials, not a user token or an OAuth grant."})

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste a Stream Chat key or secret.")
        value = clean_secret(value, field_name="Stream Chat key or secret")
        if not value or len(value) > 1024 or any(c.isspace() for c in value) or value.lower().startswith(("bearer", "basic")):
            raise ValueError("Paste the key or secret itself, without an authorization scheme.")
        return value


def _shape(data):
    if not isinstance(data, dict) or data.get("credential_type") != FAMILY:
        raise ValueError("Connect a Stream Chat Server Key credential.")
    try:
        return StreamChatServerCredential.model_validate(data).model_dump()
    except Exception:
        raise ValueError("Stream Chat server credentials have an invalid shape.") from None


class _LoadedCredential(dict):
    def __init__(self, data, store):
        super().__init__(data)
        self.store = store


class StreamChatAccessDenied(ValueError):
    pass


class StreamChatNotFound(ValueError):
    pass


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("name", check_fields=False, mode="before")
    @classmethod
    def normalize_name(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Use a nonblank display name.")
        return value.strip()


class _Page(_Operation):
    limit: int = Field(25, ge=1, le=100, strict=True, title="Page Size")
    offset: int = Field(0, ge=0, le=1000, strict=True, description="One bounded page; a full page does not prove complete coverage.")


class ListUsersConfig(_Page):
    operation: Literal["list_users"] = Field("list_users", title="List Users")


class _User(_Operation):
    user_id: str = Field(..., title="User", json_schema_extra={"x-dynamic-options": True, "x-resource-type": "stream_chat_user"})
    _validate_id = field_validator("user_id")(_id)


class GetUserConfig(_User):
    operation: Literal["get_user"] = Field("get_user", title="Get User")


class UpsertUserConfig(_User):
    operation: Literal["upsert_user"] = Field("upsert_user", title="Upsert User", description="Creates or updates the display name; Stream emits user.updated events.")
    name: str = Field(..., min_length=1, max_length=256, title="Display Name")


class ListChannelTypesConfig(_Operation):
    operation: Literal["list_channel_types"] = Field("list_channel_types", title="List Channel Types")


class _ChannelType(_Operation):
    channel_type: str = Field(..., title="Channel Type", json_schema_extra={"x-dynamic-options": True, "x-resource-type": "stream_chat_channel_type"})
    _validate_type = field_validator("channel_type")(_id)


class GetChannelTypeConfig(_ChannelType):
    operation: Literal["get_channel_type"] = Field("get_channel_type", title="Get Channel Type")


class ListChannelsConfig(_ChannelType, _Page):
    operation: Literal["list_channels"] = Field("list_channels", title="List Channels")
    member_user_id: Optional[str] = Field(None, title="Member Filter", json_schema_extra={"x-dynamic-options": True, "x-resource-type": "stream_chat_user"})

    @field_validator("member_user_id")
    @classmethod
    def member(cls, value):
        return _id(value) if value is not None else None


class _Channel(_ChannelType):
    channel_id: str = Field(..., title="Channel", json_schema_extra={"x-dynamic-options": {"depends_on": "channel_type"}, "x-resource-type": "stream_chat_channel"})
    _validate_channel = field_validator("channel_id")(_id)


class GetChannelConfig(_Channel):
    operation: Literal["get_channel"] = Field("get_channel", title="Get Channel", description="GET only; a missing channel is not created.")


class ListChannelMembersConfig(_Channel):
    operation: Literal["list_channel_members"] = Field("list_channel_members", title="List Channel Members")
    limit: int = Field(50, ge=1, le=100, strict=True)


class GetOrCreatePrivateChannelConfig(_Channel):
    operation: Literal["get_or_create_private_channel"] = Field("get_or_create_private_channel", title="Get or Create Private Channel", description="Existing membership must match exactly. Creation subscribes members and can emit channel/member events; it is not silent.")
    created_by_id: str = Field(..., title="Creator", json_schema_extra={"x-dynamic-options": True, "x-resource-type": "stream_chat_user"})
    member_user_ids: list[str] = Field(..., min_length=1, max_length=100, title="Member User IDs", description="Explicit IDs only; the creator must be included.")
    name: str = Field(..., min_length=1, max_length=256, title="Channel Name")
    member_restricted_type_confirmed: Literal[True] = Field(..., title="Member Access Confirmed", description="Confirm this app's current channel type and overrides restrict ordinary client reads to members. Membership alone cannot prove effective app permissions.")
    _validate_creator = field_validator("created_by_id")(_id)

    @field_validator("member_restricted_type_confirmed", mode="before")
    @classmethod
    def confirm_private_type(cls, value):
        if type(value) is not bool or value is not True:
            raise ValueError("Confirm current member access explicitly.")
        return value

    @model_validator(mode="after")
    def members(self):
        for value in self.member_user_ids:
            _id(value)
        if len(set(self.member_user_ids)) != len(self.member_user_ids) or self.created_by_id not in self.member_user_ids:
            raise ValueError("Use unique members and include the creator.")
        return self


class RenameChannelConfig(_Channel):
    operation: Literal["rename_channel"] = Field("rename_channel", title="Rename Channel", description="Partial metadata update; Stream emits channel.updated events.")
    name: str = Field(..., min_length=1, max_length=256, title="Channel Name")


class ListMessagesConfig(_Channel):
    operation: Literal["list_messages"] = Field("list_messages", title="List Message Metadata")
    limit: int = Field(25, ge=1, le=100, strict=True)
    before_message_id: Optional[str] = Field(None, title="Before Message", json_schema_extra={"x-dynamic-options": {"depends_on": "channel_id"}, "x-resource-type": "stream_chat_message"})

    @field_validator("before_message_id")
    @classmethod
    def before(cls, value):
        return _id(value) if value is not None else None


class _Message(_Channel):
    message_id: str = Field(..., title="Message", json_schema_extra={"x-dynamic-options": {"depends_on": "channel_id"}, "x-resource-type": "stream_chat_message"})
    _validate_message = field_validator("message_id")(_id)


class GetMessageConfig(_Message):
    operation: Literal["get_message"] = Field("get_message", title="Get Message Metadata")


class ListMessageHistoryConfig(_Message):
    operation: Literal["list_message_history"] = Field("list_message_history", title="List Message History Metadata")
    limit: int = Field(25, ge=1, le=100, strict=True)
    page_token: Optional[str] = Field("", max_length=8192, title="Next Page Token", description="Use only a token returned for this credential, channel, message and page size.")


StreamChatOperation = Annotated[Union[ListUsersConfig, GetUserConfig, UpsertUserConfig,
    ListChannelTypesConfig, GetChannelTypeConfig, ListChannelsConfig, GetChannelConfig,
    ListChannelMembersConfig, GetOrCreatePrivateChannelConfig, RenameChannelConfig,
    ListMessagesConfig, GetMessageConfig, ListMessageHistoryConfig], Field(discriminator="operation")]


class StreamChatNodeConfig(NodeConfig[StreamChatOperation, StreamChatServerCredential]):
    credentials: Optional[StreamChatServerCredential] = Field(None, description="Connect a Stream Chat Server Key credential.")


def _object(value):
    if not isinstance(value, dict):
        raise ValueError("Stream Chat returned invalid metadata.")
    return value


def _rows(value, limit=None):
    if not isinstance(value, list) or (limit is not None and len(value) > limit):
        raise ValueError("Stream Chat returned an invalid or oversized page.")
    return [_object(row) for row in value]


def _scalars(row, fields):
    out = {}
    for key, kind in fields.items():
        value = row.get(key)
        if value is None:
            continue
        if type(value) is not kind or (kind is str and len(value) > 1024):
            raise ValueError("Stream Chat returned invalid metadata fields.")
        out[key] = value
    return out


def _user(row):
    row = _object(row)
    result = {"id": _id(row.get("id"))}
    result.update(_scalars(row, {"name": str, "created_at": str, "updated_at": str, "deleted_at": str}))
    return result


def _channel(row, channel_type=None, channel_id=None):
    row = _object(row)
    typ, ident = _id(row.get("type")), _id(row.get("id"))
    if row.get("cid") != f"{typ}:{ident}" or (channel_type and typ != channel_type) or (channel_id and ident != channel_id):
        raise ValueError("Stream Chat channel does not match its selected parent.")
    result = {"id": ident, "type": typ, "cid": row["cid"]}
    result.update(_scalars(row, {"created_at": str, "updated_at": str, "deleted_at": str, "last_message_at": str,
        "member_count": int, "message_count": int, "frozen": bool, "disabled": bool}))
    if any(result.get(k, 0) < 0 for k in ("member_count", "message_count")):
        raise ValueError("Stream Chat returned invalid counts.")
    custom = row.get("custom")
    if custom is not None:
        custom = _object(custom)
    name = row.get("name", (custom or {}).get("name"))
    if name is not None:
        result.update(_scalars({"name": name}, {"name": str}))
    return result


def _message(row, cid, message_id=None):
    row = _object(row)
    ident = _id(row.get("id"))
    if row.get("cid") != cid or (message_id and ident != message_id):
        raise ValueError("Stream Chat message does not belong to the selected channel.")
    if row.get("channel") is not None:
        typ, channel_id = cid.split(":", 1)
        _channel(row["channel"], typ, channel_id)
    result = {"id": ident, "cid": cid}
    result.update(_scalars(row, {"type": str, "created_at": str, "updated_at": str, "deleted_at": str,
        "reply_count": int, "pinned": bool, "silent": bool}))
    if result.get("reply_count", 0) < 0:
        raise ValueError("Stream Chat returned invalid counts.")
    if row.get("user") is not None:
        result["user_id"] = _id(_object(row["user"]).get("id"))
    if row.get("parent_id") is not None:
        result["parent_id"] = _id(row["parent_id"])
    return result


def _channel_type(row, name):
    row = _object(row)
    if row.get("name") != name:
        raise ValueError("Stream Chat returned the wrong channel type.")
    return {"id": _id(name), **_scalars(row, {"name": str, "created_at": str, "updated_at": str,
        "message_retention": str, "max_message_length": int, "typing_events": bool,
        "read_events": bool, "push_notifications": bool, "replies": bool})}


def _unique(rows):
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Stream Chat returned repeated IDs.")
    return rows


def _b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class _Client:
    def __init__(self, data):
        self.credential = _shape(data)
        self.store = getattr(data, "store", None)
        self.authority = self.store.current if self.store else None
        self.stamps = {key: data.get(key) for key in ("token_version", "updated_at")}
        self.secrets = [self.credential["api_key"], self.credential["api_secret"]]

    async def current(self):
        if not self.store:
            return
        try:
            data = await self.store.load()
            if (self.store.current != self.authority or _shape(data) != self.credential
                    or any(data.get(k) != v for k, v in self.stamps.items())):
                raise ValueError("changed")
        except Exception:
            raise StreamChatCredentialUnavailable("Stream Chat credential authority changed; reconnect or retry.") from None

    def _server_jwt(self):
        header, claims = _b64(b'{"alg":"HS256","typ":"JWT"}'), _b64(b'{"server":true}')
        signing = f"{header}.{claims}"
        signature = hmac.new(self.credential["api_secret"].encode(), signing.encode(), hashlib.sha256).digest()
        return f"{signing}.{_b64(signature)}"

    def scrub(self, value):
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[REDACTED]")
            return value
        if isinstance(value, dict):
            return {k: self.scrub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.scrub(v) for v in value]
        return value

    def cursor(self, next_value, scope):
        if not isinstance(next_value, str) or not next_value or len(next_value) > 4096 or "://" in next_value or any(c.isspace() for c in next_value):
            raise ValueError("Stream Chat returned invalid pagination.")
        binding = hashlib.sha256(json.dumps([self.credential["api_key"], *scope], separators=(",", ":")).encode()).hexdigest()
        raw = _b64(json.dumps({"binding": binding, "next": next_value}, separators=(",", ":")).encode())
        return raw + "." + _b64(hmac.new(self.credential["api_secret"].encode(), raw.encode(), hashlib.sha256).digest())

    def uncursor(self, token, scope):
        if not token:
            return None
        try:
            raw, signature = token.split(".")
            expected = _b64(hmac.new(self.credential["api_secret"].encode(), raw.encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(signature, expected):
                raise ValueError()
            data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
            if set(data) != {"binding", "next"} or self.cursor(data["next"], scope) != token:
                raise ValueError()
            return data["next"]
        except Exception:
            raise ValueError("Use the returned Stream Chat page token in its original scope.") from None

    async def request(self, method, path, *, params=None, body=None, success=200):
        if any(secret in path for secret in self.secrets):
            raise ValueError("Resource IDs must not contain credential values.")
        await self.current()
        jwt = self._server_jwt()
        self.secrets.append(jwt)
        # Current server instrumentation removes query/header/body attributes
        # before samplers and processors (utils.outbound_trace_privacy).
        for name in set(logging.Logger.manager.loggerDict) | {"httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"}:
            if name == "httpx" or name == "httpcore" or name.startswith(("httpx.", "httpcore.")):
                logging.getLogger(name).addFilter(_PRIVACY)
        context = _PRIVATE_REQUEST.set(True)
        try:
            async with httpx.AsyncClient(timeout=20.0, trust_env=False, follow_redirects=False) as transport:
                response = await transport.request(method, BASE + path,
                    params={**(params or {}), "api_key": self.credential["api_key"]}, json=body,
                    headers={"Accept": "application/json", "Content-Type": "application/json",
                             "Stream-Auth-Type": "jwt", "Authorization": jwt})
        except httpx.HTTPError:
            await self.current()
            raise ValueError("Stream Chat request failed; a write may have completed. No automatic replay was attempted.") from None
        finally:
            _PRIVATE_REQUEST.reset(context)
        await self.current()
        if response.status_code in (401, 403):
            raise StreamChatAccessDenied(f"Stream Chat returned HTTP {response.status_code}; check this application's server key and secret.")
        if response.status_code == 404:
            raise StreamChatNotFound("Stream Chat returned HTTP 404; the selected resource is unavailable.")
        if response.status_code != success:
            raise ValueError(f"Stream Chat returned HTTP {response.status_code}; the operation was not confirmed.")
        if len(response.content) > 2_000_000:
            raise ValueError("Stream Chat response exceeded the metadata size limit.")
        try:
            data = _object(response.json())
            if not isinstance(data.get("duration"), str):
                raise ValueError("Stream Chat returned an incomplete response.")
            return data
        except ValueError:
            raise ValueError("Stream Chat returned invalid JSON metadata.") from None

    async def users(self, *, limit=25, offset=0, ids=None):
        payload = {"filter_conditions": {"id": {"$in": ids}} if ids else {}, "limit": limit,
            "offset": offset, "presence": False, "sort": [{"field": "id", "direction": 1}]}
        data = await self.request("GET", "/users", params={"payload": json.dumps(payload, separators=(",", ":"))})
        rows = _unique([_user(row) for row in _rows(data.get("users"), limit)])
        if ids and (len(rows) != len(ids) or {r["id"] for r in rows} != set(ids)):
            raise ValueError("Stream Chat did not confirm the selected users.")
        return rows

    async def get_channel(self, typ, ident, *, messages=0, members=0, before=None):
        params = {"state": "true" if messages or members else "false", "messages_limit": messages,
                  "members_limit": members, "watchers_limit": 0}
        if before:
            params["messages_id_lt"] = before
        data = await self.request("GET", f"/channels/{typ}/{ident}", params=params)
        _channel(data.get("channel"), typ, ident)
        return data

    async def get_message(self, typ, channel_id, ident):
        data = await self.request("GET", f"/messages/{ident}")
        return _message(data.get("message"), f"{typ}:{channel_id}", ident)

    @staticmethod
    def members(data, limit):
        out = []
        for row in _rows(data.get("members"), limit):
            ident = _id(row.get("user_id") if row.get("user_id") is not None else _object(row.get("user")).get("id"))
            if row.get("user") is not None and _id(_object(row["user"]).get("id")) != ident:
                raise ValueError("Stream Chat returned mismatched membership.")
            if row.get("user_id") is not None and row["user_id"] != ident:
                raise ValueError("Stream Chat returned mismatched membership.")
            out.append({"id": ident})
        return _unique(out)

    async def run(self, config):
        op = config.operation
        if op == "list_users":
            rows = await self.users(limit=config.limit, offset=config.offset)
            return {"items": rows, "page_size": config.limit, "offset": config.offset, "may_have_more": len(rows) == config.limit}
        if op == "get_user":
            return {"user": (await self.users(limit=1, ids=[config.user_id]))[0]}
        if op == "upsert_user":
            data = await self.request("POST", "/users", body={"users": {config.user_id: {"id": config.user_id, "name": config.name}}}, success=201)
            rows = _object(data.get("users"))
            if set(rows) != {config.user_id} or _user(rows[config.user_id])["id"] != config.user_id:
                raise ValueError("Stream Chat did not confirm the upserted user.")
            readback = (await self.users(limit=1, ids=[config.user_id]))[0]
            if readback.get("name") != config.name:
                raise ValueError("Stream Chat user write could not be confirmed by readback.")
            return {"user": readback, "readback_confirmed": True}
        if op == "list_channel_types":
            data = await self.request("GET", "/channeltypes")
            values = _object(data.get("channel_types"))
            if len(values) > 100:
                raise ValueError("Stream Chat channel types exceeded the metadata bound.")
            return {"items": [_channel_type(row, _id(name)) for name, row in values.items()]}
        if op == "get_channel_type":
            data = await self.request("GET", f"/channeltypes/{config.channel_type}")
            return {"channel_type": _channel_type(data, config.channel_type)}
        if op == "list_channels":
            filters = {"type": config.channel_type}
            if config.member_user_id:
                filters["members"] = {"$in": [config.member_user_id]}
            data = await self.request("POST", "/channels", body={"filter_conditions": filters,
                "limit": config.limit, "offset": config.offset, "state": False,
                "message_limit": 0, "member_limit": 0, "sort": [{"field": "id", "direction": 1}]}, success=201)
            rows = _unique([_channel(row.get("channel"), config.channel_type) for row in _rows(data.get("channels"), config.limit)])
            return {"items": rows, "page_size": config.limit, "offset": config.offset, "may_have_more": len(rows) == config.limit}
        typ, ident = config.channel_type, config.channel_id
        if op == "get_channel":
            return {"channel": _channel((await self.get_channel(typ, ident))["channel"], typ, ident)}
        if op == "list_channel_members":
            data = await self.get_channel(typ, ident, members=config.limit)
            rows = self.members(data, config.limit)
            return {"items": rows, "cid": f"{typ}:{ident}", "may_have_more": len(rows) == config.limit}
        if op == "get_or_create_private_channel":
            type_data = await self.request("GET", f"/channeltypes/{typ}")
            _channel_type(type_data, typ)
            await self.users(limit=len(config.member_user_ids), ids=config.member_user_ids)
            created = False
            try:
                data = await self.get_channel(typ, ident, members=100)
            except StreamChatNotFound:
                data = await self.request("POST", f"/channels/{typ}/{ident}/query", body={
                    "data": {"created_by_id": config.created_by_id, "members": [{"user_id": u} for u in config.member_user_ids], "name": config.name},
                    "state": False, "messages": {"limit": 0}, "members": {"limit": 100}, "watchers": {"limit": 0}}, success=201)
                _channel(data.get("channel"), typ, ident)
                created = True
                data = await self.get_channel(typ, ident, members=100)
            channel = _channel(data.get("channel"), typ, ident)
            members = self.members(data, 100)
            creator = _id(_object(data["channel"].get("created_by")).get("id"))
            if (channel.get("member_count") != len(members) or {u["id"] for u in members} != set(config.member_user_ids)
                    or creator != config.created_by_id or channel.get("name") != config.name):
                raise ValueError("Stream Chat channel creator, name or complete membership differs; no further write was attempted.")
            return {"channel": channel, "members": members, "creation_request_sent": created,
                    "readback_confirmed": True, "privacy": "operator-confirmed member-restricted configuration; not independently verified"}
        if op == "rename_channel":
            await self.get_channel(typ, ident)
            data = await self.request("PATCH", f"/channels/{typ}/{ident}", body={"set": {"name": config.name}})
            _channel(data.get("channel"), typ, ident)
            channel = _channel((await self.get_channel(typ, ident))["channel"], typ, ident)
            if channel.get("name") != config.name:
                raise ValueError("Stream Chat channel write could not be confirmed by readback.")
            return {"channel": channel, "readback_confirmed": True}
        if op == "list_messages":
            if config.before_message_id:
                await self.get_message(typ, ident, config.before_message_id)
            data = await self.get_channel(typ, ident, messages=config.limit, before=config.before_message_id)
            rows = _unique([_message(row, f"{typ}:{ident}") for row in _rows(data.get("messages"), config.limit)])
            return {"items": rows, "cid": f"{typ}:{ident}", "before_message_id": rows[0]["id"] if rows else None,
                    "may_have_more": len(rows) == config.limit}
        if op == "get_message":
            return {"message": await self.get_message(typ, ident, config.message_id)}
        if op == "list_message_history":
            scope = [op, typ, ident, config.message_id, config.limit]
            next_value = self.uncursor(config.page_token, scope)
            await self.get_message(typ, ident, config.message_id)
            body = {"filter": {"message_id": {"$eq": config.message_id}}, "limit": config.limit}
            if next_value:
                body["next"] = next_value
            data = await self.request("POST", "/messages/history", body=body, success=201)
            rows = []
            for row in _rows(data.get("message_history"), config.limit):
                if row.get("message_id") != config.message_id:
                    raise ValueError("Stream Chat history does not match the selected message.")
                item = {"message_id": config.message_id, **_scalars(row, {
                    "message_updated_at": str, "message_updated_by_id": str, "is_deleted": bool})}
                if not {"message_updated_at", "message_updated_by_id", "is_deleted"} <= item.keys():
                    raise ValueError("Stream Chat returned incomplete history metadata.")
                _id(item["message_updated_by_id"])
                rows.append(item)
            if data.get("next") is not None and not isinstance(data["next"], str):
                raise ValueError("Stream Chat returned invalid pagination.")
            token = self.cursor(data["next"], scope) if data.get("next") else None
            if token and token == config.page_token:
                raise ValueError("Stream Chat repeated its history page token.")
            return {"items": rows, "next_page_token": token, "cid": f"{typ}:{ident}", "message_id": config.message_id}
        raise ValueError("Unsupported Stream Chat operation.")


class StreamChatNode(WorkflowNode):
    integration_type = "automation-stream-chat"
    credential_provider_labels = {"stream_chat": "Stream Chat Account"}
    auto_select_credential = False
    agent_tool_provider = True
    connection_evidence = ConnectionEvidence(operation="list_channel_types", noun="channel types", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return StreamChatNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        shaped = _shape(credential_data)
        if not credential_id:
            return shaped
        if not user_id:
            raise StreamChatCredentialUnavailable("Stream Chat credential caller is unavailable.")
        try:
            store = _StoredCredential(pool, user_id, credential_id)
            current = await store.load()
            if shaped != _shape(current) or any(k in credential_data and credential_data[k] != current.get(k) for k in ("token_version", "updated_at")):
                raise ValueError("changed")
            return _LoadedCredential(current, store)
        except Exception:
            raise StreamChatCredentialUnavailable("Stream Chat credential is unavailable or its current authority changed.") from None

    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            await _Client(credential_data).run(ListChannelTypesConfig())
            return {"valid": True, "identity_verified": False}
        except StreamChatAccessDenied as exc:
            return {"valid": False, "message": str(exc)}
        except Exception:
            return {"valid": None, "message": "Stream Chat access could not be verified; retry later."}

    async def execute(self, input_data):
        raw = (self.node_data["credentials"] if "credentials" in self.node_data else
               self.config.credentials.model_dump() if self.config.credentials is not None else None)
        data = await self.freshen_credential(raw, pool=self.node_data.get("_approval_pool"),
            user_id=self.user_id, credential_id=self.node_data.get("credential_id"))
        client = _Client(data)
        result = await client.run(self.config.config)
        await client.current()
        return {"status": "success", "data": client.scrub(result), "identity_verified": False}

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        context = context or {}
        if search and len(search) > 256:
            raise ValueError("Stream Chat option search is too long.")
        client = _Client(credential_data)
        if field_name == "channel_type":
            result = await client.run(ListChannelTypesConfig())
        elif field_name in ("user_id", "member_user_id", "created_by_id"):
            if page_token is not None:
                raise ValueError("Stream Chat user picker covers one bounded page; use an explicit ID for other users.")
            result = await client.run(ListUsersConfig(limit=100))
        elif field_name == "channel_id":
            typ = _id(context.get("channel_type"))
            if page_token is not None:
                raise ValueError("Stream Chat channel picker covers one bounded page; use an explicit ID for other channels.")
            result = await client.run(ListChannelsConfig(channel_type=typ, limit=100))
        elif field_name in ("message_id", "before_message_id"):
            typ, ident = _id(context.get("channel_type")), _id(context.get("channel_id"))
            if page_token is not None:
                raise ValueError("Stream Chat message picker covers one bounded page; use an explicit ID for older messages.")
            result = await client.run(ListMessagesConfig(channel_type=typ, channel_id=ident, limit=100))
        else:
            raise ValueError("Unsupported Stream Chat field.")
        await client.current()
        rows = result["items"]
        needle = (search or "").casefold()
        options = [{"value": row["id"], "label": row.get("name") or row["id"]} for row in rows
                   if not needle or needle in (row.get("name") or row["id"]).casefold()]
        return {"options": client.scrub(options), "has_more": False,
                "coverage_limited": result.get("may_have_more", False)}
