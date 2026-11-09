"""Sendbird Chat Platform API v3: one documented request per operation.

Contract: sendbird/sendbird-platform-sdk-java api/openapi.yaml, version 1.0.0.
Auth: https://docs.sendbird.com/docs/chat/platform-api/v3/prepare-to-use-api
No pagination is followed automatically and writes are never retried.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client


class SendbirdAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Sendbird API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.sendbird.com/",
            "x-credential-instructions": "In Sendbird Dashboard, select your application and open Settings > Application > General. Copy its case-sensitive Application ID and a master or secondary API token. Prefer a secondary token with the permissions your operations need. NoClick sends it only to that application's Sendbird Chat API. This is not a user access token. A user-list read checks access; write permissions are not verified.",
        })
    credential_type: Literal["sendbird_api_token"] = Field("sendbird_api_token", json_schema_extra={"ui:hidden": True})
    app_id: str = Field(..., title="Application ID", min_length=1, max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,99}$",
        description="The application ID, without a URL or api- prefix.")
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("app_id", mode="before")
    @classmethod
    def application(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the Application ID")
        return value.strip()

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API token without a header or whitespace")
        return value


Identifier = Annotated[str, Field(min_length=1, max_length=100,
    pattern=r"^[^/\\?#\s]+$", description="Sendbird ID; copied exactly from your application.")]
ChannelURL = Annotated[str, Field(min_length=4, max_length=100, pattern=r"^[A-Za-z0-9_-]+$",
    description="Channel URL identifier, not a full web URL.")]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def safe_user_segments(cls, value, info):
        if info.field_name in {"user_id", "user_ids"}:
            for identifier in value if isinstance(value, list) else [value]:
                if identifier in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in identifier):
                    raise ValueError("Use a user ID without path traversal or control characters")
        return value


class _Page(_Input):
    limit: int = Field(20, ge=1, le=100, description="One page only; use the returned next token to continue.")
    token: str | None = Field(None, max_length=4096, description="The previous response's next token, for the same application and query.")


class ListUsers(_Page):
    """List users in the connected Sendbird application."""
    operation: Literal["list_users"] = Field("list_users", title="List Users", json_schema_extra={"ui:hidden": True})


class GetUser(_Input):
    """Get user in the connected Sendbird application."""
    operation: Literal["get_user"] = Field("get_user", title="Get User", json_schema_extra={"ui:hidden": True})
    user_id: Identifier


class CreateUser(_Input):
    """Create user in the connected Sendbird application."""
    operation: Literal["create_user"] = Field("create_user", title="Create User", json_schema_extra={"ui:hidden": True})
    user_id: Identifier
    nickname: str = Field(..., min_length=1, max_length=80)
    profile_url: str = Field("", max_length=2048, description="Profile image URL; empty uses no image.")


class UpdateUser(_Input):
    """Update user in the connected Sendbird application."""
    operation: Literal["update_user"] = Field("update_user", title="Update User", json_schema_extra={"ui:hidden": True})
    user_id: Identifier
    nickname: str = Field(..., min_length=1, max_length=80)


class DeleteUser(_Input):
    """Delete user in the connected Sendbird application."""
    operation: Literal["delete_user"] = Field("delete_user", title="Delete User", description="Permanently delete this user from the application.", json_schema_extra={"ui:hidden": True})
    user_id: Identifier


class ListGroupChannels(_Page):
    """List group channels in the connected Sendbird application."""
    operation: Literal["list_group_channels"] = Field("list_group_channels", title="List Group Channels", json_schema_extra={"ui:hidden": True})


class GetGroupChannel(_Input):
    """Get group channel in the connected Sendbird application."""
    operation: Literal["get_group_channel"] = Field("get_group_channel", title="Get Group Channel", json_schema_extra={"ui:hidden": True})
    channel_url: ChannelURL


class CreateGroupChannel(_Input):
    """Create group channel in the connected Sendbird application."""
    operation: Literal["create_group_channel"] = Field("create_group_channel", title="Create Group Channel", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=191)
    user_ids: list[Identifier] = Field(..., min_length=1, max_length=100, description="Existing users to invite; sent as the documented users objects.")
    is_distinct: bool = Field(False, description="Reuse a channel for the same members when true.")


class UpdateGroupChannel(_Input):
    """Update group channel in the connected Sendbird application."""
    operation: Literal["update_group_channel"] = Field("update_group_channel", title="Update Group Channel", json_schema_extra={"ui:hidden": True})
    channel_url: ChannelURL
    name: str = Field(..., min_length=1, max_length=191)


class DeleteGroupChannel(_Input):
    """Delete group channel in the connected Sendbird application."""
    operation: Literal["delete_group_channel"] = Field("delete_group_channel", title="Delete Group Channel", description="Delete this channel and its messages permanently.", json_schema_extra={"ui:hidden": True})
    channel_url: ChannelURL


class ListMembers(_Page):
    """List members in the connected Sendbird application."""
    operation: Literal["list_members"] = Field("list_members", title="List Members", json_schema_extra={"ui:hidden": True})
    channel_url: ChannelURL


class InviteMembers(_Input):
    """Invite members in the connected Sendbird application."""
    operation: Literal["invite_members"] = Field("invite_members", title="Invite Members", json_schema_extra={"ui:hidden": True})
    channel_url: ChannelURL
    user_ids: list[Identifier] = Field(..., min_length=1, max_length=100)


class SendMessage(_Input):
    """Send message in the connected Sendbird application."""
    operation: Literal["send_message"] = Field("send_message", title="Send Text Message", description="Send as an existing user; Sendbird push-notification settings apply.", json_schema_extra={"ui:hidden": True})
    channel_type: Literal["group_channels", "open_channels"] = "group_channels"
    channel_url: ChannelURL
    user_id: Identifier
    message: str = Field(..., min_length=1, max_length=5000)


class GetMessage(_Input):
    """Get message in the connected Sendbird application."""
    operation: Literal["get_message"] = Field("get_message", title="Get Message", json_schema_extra={"ui:hidden": True})
    channel_type: Literal["group_channels", "open_channels"] = "group_channels"
    channel_url: ChannelURL
    message_id: int = Field(..., ge=1)


class UpdateMessage(_Input):
    """Update message in the connected Sendbird application."""
    operation: Literal["update_message"] = Field("update_message", title="Update Text Message", json_schema_extra={"ui:hidden": True})
    channel_type: Literal["group_channels", "open_channels"] = "group_channels"
    channel_url: ChannelURL
    message_id: int = Field(..., ge=1)
    message: str = Field(..., min_length=1, max_length=5000)


class DeleteMessage(_Input):
    """Delete message in the connected Sendbird application."""
    operation: Literal["delete_message"] = Field("delete_message", title="Delete Message", json_schema_extra={"ui:hidden": True})
    channel_type: Literal["group_channels", "open_channels"] = "group_channels"
    channel_url: ChannelURL
    message_id: int = Field(..., ge=1)


class ListOpenChannels(_Page):
    """List open channels in the connected Sendbird application."""
    operation: Literal["list_open_channels"] = Field("list_open_channels", title="List Open Channels", json_schema_extra={"ui:hidden": True})


class GetOpenChannel(_Input):
    """Get open channel in the connected Sendbird application."""
    operation: Literal["get_open_channel"] = Field("get_open_channel", title="Get Open Channel", json_schema_extra={"ui:hidden": True})
    channel_url: ChannelURL


SendbirdConfig = Annotated[Union[
    ListUsers,
    GetUser,
    CreateUser,
    UpdateUser,
    DeleteUser,
    ListGroupChannels,
    GetGroupChannel,
    CreateGroupChannel,
    UpdateGroupChannel,
    DeleteGroupChannel,
    ListMembers,
    InviteMembers,
    SendMessage,
    GetMessage,
    UpdateMessage,
    DeleteMessage,
    ListOpenChannels,
    GetOpenChannel,
], Field(discriminator="operation")]


class SendbirdNodeConfig(NodeConfig[SendbirdConfig, SendbirdAPITokenCredential]):
    pass


OPERATIONS = {
    'list_users': ('GET', '/v3/users', 'users', (), ('token', 'limit')),
    'get_user': ('GET', '/v3/users/{user_id}', 'user', (), ()),
    'create_user': ('POST', '/v3/users', 'user', ('user_id', 'nickname', 'profile_url'), ()),
    'update_user': ('PUT', '/v3/users/{user_id}', 'user', ('nickname',), ()),
    'delete_user': ('DELETE', '/v3/users/{user_id}', 'empty', (), ()),
    'list_group_channels': ('GET', '/v3/group_channels', 'channels', (), ('token', 'limit')),
    'get_group_channel': ('GET', '/v3/group_channels/{channel_url}', 'channel', (), ()),
    'create_group_channel': ('POST', '/v3/group_channels', 'channel', ('name', 'user_ids', 'is_distinct'), ()),
    'update_group_channel': ('PUT', '/v3/group_channels/{channel_url}', 'channel', ('name',), ()),
    'delete_group_channel': ('DELETE', '/v3/group_channels/{channel_url}', 'empty', (), ()),
    'list_members': ('GET', '/v3/group_channels/{channel_url}/members', 'members', (), ('token', 'limit')),
    'invite_members': ('POST', '/v3/group_channels/{channel_url}/invite', 'channel', ('user_ids',), ()),
    'send_message': ('POST', '/v3/{channel_type}/{channel_url}/messages', 'message', ('user_id', 'message'), ()),
    'get_message': ('GET', '/v3/{channel_type}/{channel_url}/messages/{message_id}', 'message', (), ()),
    'update_message': ('PUT', '/v3/{channel_type}/{channel_url}/messages/{message_id}', 'message', ('message',), ()),
    'delete_message': ('DELETE', '/v3/{channel_type}/{channel_url}/messages/{message_id}', 'empty', (), ()),
    'list_open_channels': ('GET', '/v3/open_channels', 'channels', (), ('token', 'limit')),
    'get_open_channel': ('GET', '/v3/open_channels/{channel_url}', 'channel', (), ()),
}


# Never expose API/user tokens returned by user/channel resources.
_SECRET_KEYS = frozenset({"api_token", "access_token", "session_token", "token", "password", "secret"})


def _redact(value, token):
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items() if k.lower() not in _SECRET_KEYS}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    return value


class SendbirdNode(WorkflowNode):
    integration_type = "automation-sendbird"
    connection_evidence = ConnectionEvidence(noun="Sendbird users", operation="list_users",
        label_keys=("nickname", "user_id"))

    @classmethod
    def get_config_model(cls):
        return SendbirdNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Sendbird application API token")
        config, credential = self.config.config, self.config.credentials
        method, template, kind, body_fields, query_fields = OPERATIONS[config.operation]
        path = re.sub(r"\{(\w+)\}", lambda m: quote(str(getattr(config, m[1])), safe=""), template)
        query = {k: getattr(config, k) for k in query_fields if getattr(config, k) is not None}
        body = {k: getattr(config, k) for k in body_fields} if body_fields else None
        if config.operation == "create_group_channel":
            body["users"] = [{"user_id": identifier} for identifier in body.pop("user_ids")]
        if config.operation in {"send_message", "update_message"}:
            body["message_type"] = "MESG"
        url = f"https://api-{credential.app_id}.sendbird.com" + path
        headers = {"Api-Token": credential.api_token, "Content-Type": "application/json", "Accept": "application/json"}
        writing = method != "GET"
        try:
            async with guarded_async_client(verify=True, trust_env=False, follow_redirects=False,
                    timeout=httpx.Timeout(30.0)) as client:
                async with client.stream(method, url, headers=headers, params=query,
                        **({"json": body} if body is not None else {})) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 4 * 1024 * 1024:
                            raise ValueError("Sendbird response exceeds 4 MiB; inspect before retrying a write")
                    status = response.status_code
                    try:
                        payload = json.loads(raw)
                    except (ValueError, UnicodeError):
                        payload = None
                    if status != 200 or (isinstance(payload, dict) and payload.get("error")):
                        message = payload.get("message", "Request was not confirmed") if isinstance(payload, dict) else "Request was not confirmed"
                        output = {"status": "error", "http_status": status,
                            "message": f"Sendbird HTTP {status}: {str(message)[:1000]}",
                            "write_outcome": "unverified" if writing else None}
                    else:
                        if response.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json" or not isinstance(payload, dict):
                            raise ValueError("Sendbird returned an invalid JSON object; inspect before retrying a write")
                        if kind in {"users", "channels", "members"}:
                            if not isinstance(payload.get(kind), list) or any(not isinstance(row, dict) for row in payload[kind]):
                                raise ValueError("Sendbird returned an invalid list envelope")
                            following = payload.get("next")
                            if following is not None and not isinstance(following, str):
                                raise ValueError("Sendbird returned an invalid continuation token")
                        elif kind != "empty":
                            key = {"user": "user_id", "channel": "channel_url", "message": "message_id"}[kind]
                            if key not in payload:
                                raise ValueError("Sendbird returned a resource without its identifier")
                        elif payload:
                            raise ValueError("Sendbird deletion returned an unexpected acknowledgement")
                        output = {"status": "success", "http_status": status, "data": payload}
                        if kind in {"users", "channels", "members"}:
                            output["next_page_token"] = payload.get("next") or None
                            output["has_more"] = bool(payload.get("next"))
                        if writing:
                            output["write_acknowledged"] = True
                            output["readback_verified"] = False
        except (httpx.HTTPError, OSError, SSRFError):
            raise ValueError("Sendbird request did not complete; inspect before retrying a write") from None
        output = _redact(output, credential.api_token)
        await self.emit(output)
        return output
