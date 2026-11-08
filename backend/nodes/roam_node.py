"""Roam v1 chat, directory, group and meeting operations.

Contract: https://developer.ro.am/chat-v1.json, API version 2026-08-25.
Each operation performs one request; cursors remain opaque and caller-controlled.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.ro.am/v1"
API_VERSION = "2026-08-25"


class RoamTokenCredential(BaseModel):
    model_config = ConfigDict(title="Roam Personal Access Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developer.ro.am/docs/guides/oauth#personal-access-tokens",
        "x-credential-instructions": "In Roam, open User Settings → Developer and create a Personal Access Token if your workspace permits it. Paste the token alone. Enable the PAT groups for the chat, user, group and meeting operations you need. NoClick sends it only to api.ro.am. PATs have a daily quota of 1,000 requests. Connection testing reads token.info; it does not prove every operation is permitted.",
    })
    credential_type: Literal["roam_token"] = Field("roam_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Personal access token", min_length=1, max_length=4096,
                           json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token alone without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    cursor: str | None = Field(None, min_length=1, max_length=4096,
                               description="Opaque nextCursor from the previous response; omit for the first page.")
    limit: int = Field(10, ge=1, le=100)


class GetTokenInfo(_Input):
    """Inspect the connected principal, workspace and token grant; needs no scope."""
    operation: Literal["get_token_info"] = "get_token_info"


class ListChats(_Page):
    """List one page of accessible chats. Requires chat:read."""
    operation: Literal["list_chats"] = "list_chats"
    limit: int = Field(10, ge=1, le=50)


class _Chat(_Input):
    chatId: UUID = Field(..., title="Chat ID")


class PostMessage(_Input):
    """Send a text message to one chat, group or set of DM recipients. Requires chat:send_message."""
    operation: Literal["post_message"] = "post_message"
    chatId: UUID | None = Field(None, title="Chat ID")
    groupId: UUID | None = Field(None, title="Group ID")
    userIds: list[UUID] | None = Field(None, min_length=1, title="DM recipient IDs")
    text: str = Field(..., min_length=1, title="Message text")
    markdown: StrictBool = True
    threadTimestamp: StrictInt | None = Field(None, title="Parent thread timestamp (microseconds)")
    threadKey: str | None = Field(None, min_length=1, max_length=64)
    replyTimestamp: StrictInt | None = Field(None, title="DM reply timestamp (microseconds)")

    @model_validator(mode="after")
    def destination(self):
        if sum(v is not None for v in (self.chatId, self.groupId, self.userIds)) != 1:
            raise ValueError("Choose exactly one of chatId, groupId or userIds")
        if self.threadTimestamp is not None and self.threadKey is not None:
            raise ValueError("Choose threadTimestamp or threadKey")
        return self


class _Message(_Chat):
    timestamp: StrictInt = Field(..., title="Message timestamp (microseconds)")
    threadTimestamp: StrictInt | None = Field(None, title="Parent thread timestamp (microseconds)")


class UpdateMessage(_Message):
    """Replace a message's text. Requires chat:send_message and edit access."""
    operation: Literal["update_message"] = "update_message"
    text: str = Field(..., min_length=1)
    markdown: StrictBool = True


class DeleteMessage(_Message):
    """Delete a message the connected principal can delete. Requires chat:send_message."""
    operation: Literal["delete_message"] = "delete_message"


class GetChatHistory(_Page, _Chat):
    """Read one page of messages in a chat. Requires chat:history."""
    operation: Literal["get_chat_history"] = "get_chat_history"
    limit: int = Field(10, ge=1, le=200)
    threadTimestamp: StrictInt | None = None
    after: datetime | None = Field(None, description="RFC3339 timestamp")
    before: datetime | None = Field(None, description="RFC3339 timestamp")
    ascending: StrictBool | None = None


class SearchMessages(_Page):
    """Search one page of accessible messages. Requires chat:history."""
    operation: Literal["search_messages"] = "search_messages"
    query: str | None = Field(None, title="Search query", description="Omit to list recent messages.")
    after: date | None = None
    before: date | None = None
    has: list[Literal["mention", "item"]] | None = None
    limit: int = Field(10, ge=1, le=200)
    sort: Literal["relevant", "recent"] = "relevant"


class _Reaction(_Message):
    name: str = Field(..., min_length=1, description="Roam reaction name, e.g. thumbs_up or heart")


class AddReaction(_Reaction):
    """Add a message reaction. Requires chat:send_message and chat membership."""
    operation: Literal["add_reaction"] = "add_reaction"


class RemoveReaction(_Reaction):
    """Remove a message reaction. Requires chat:send_message."""
    operation: Literal["remove_reaction"] = "remove_reaction"


class ListUsers(_Page):
    """List one page of workspace members. Requires user:read."""
    operation: Literal["list_users"] = "list_users"
    q: str | None = Field(None, title="Search name")


class GetUser(_Input):
    """Get a principal by ID. Requires user:read."""
    operation: Literal["get_user"] = "get_user"
    id: str = Field(..., min_length=1, title="User or principal ID")


class ListGroups(_Page):
    """List one page of visible groups. Requires group:read."""
    operation: Literal["list_groups"] = "list_groups"
    query: str | None = None
    type: Literal["roam", "standard"] | None = None


class _Group(_Input):
    id: UUID = Field(..., title="Group ID")


class GetGroup(_Group):
    """Read a visible group's details. Requires group:read."""
    operation: Literal["get_group"] = "get_group"


class GroupMember(_Input):
    userId: str = Field(..., min_length=1, description="User ID or email address")
    role: Literal["member", "admin"]


class CreateGroup(_Input):
    """Create a group with explicit initial members. Requires group:write."""
    operation: Literal["create_group"] = "create_group"
    name: str = Field(..., min_length=1, max_length=64)
    description: str | None = Field(None, max_length=1024)
    private: StrictBool = False
    enforceThreads: StrictBool | None = None
    members: list[GroupMember] = Field(..., min_length=1)


class JoinGroup(_Group):
    """Join a public group as the token owner. Requires group:write."""
    operation: Literal["join_group"] = "join_group"


class SearchMeetings(_Input):
    """Search meeting transcripts and summaries using a personal token. Requires meetings:read."""
    operation: Literal["search_meetings"] = "search_meetings"
    query: str = Field(..., min_length=1)
    after: date | None = None
    before: date | None = None
    timezone: str | None = Field(None, description="IANA timezone, e.g. America/New_York")


class ListMeetings(_Page):
    """List one page of meetings available to this token. Requires meetings:read."""
    operation: Literal["list_meetings"] = "list_meetings"
    before: datetime | None = None
    after: datetime | None = None


class _Meeting(_Input):
    id: UUID = Field(..., title="Meeting ID")


class GetMeeting(_Meeting):
    """Read a meeting, its summary and action items. Requires meetings:read."""
    operation: Literal["get_meeting"] = "get_meeting"
    maxParticipants: int = Field(10, ge=0, le=100)


class GetMeetingTranscript(_Meeting):
    """Read the structured JSON transcript. Requires meetings:read."""
    operation: Literal["get_meeting_transcript"] = "get_meeting_transcript"


class CreateMeetingShareLink(_Meeting):
    """Get or create a shareable meeting link. Requires meetings:read.shareLink."""
    operation: Literal["create_meeting_share_link"] = "create_meeting_share_link"


RoamOperation = Annotated[Union[
    GetTokenInfo, ListChats, PostMessage, UpdateMessage, DeleteMessage, GetChatHistory,
    SearchMessages, AddReaction, RemoveReaction, ListUsers, GetUser, ListGroups,
    GetGroup, CreateGroup, JoinGroup, SearchMeetings, ListMeetings, GetMeeting,
    GetMeetingTranscript, CreateMeetingShareLink,
], Field(discriminator="operation")]


class RoamNodeConfig(NodeConfig[RoamOperation, RoamTokenCredential]):
    pass


# One native operation maps to one documented provider operation.
ROUTES = {
    "get_token_info": ("GET", "/token.info"),
    "list_chats": ("GET", "/chat.list"),
    "post_message": ("POST", "/chat.post"),
    "update_message": ("POST", "/chat.update"),
    "delete_message": ("POST", "/chat.delete"),
    "get_chat_history": ("GET", "/chat.history"),
    "search_messages": ("POST", "/chat.search"),
    "add_reaction": ("POST", "/reaction.add"),
    "remove_reaction": ("POST", "/reaction.remove"),
    "list_users": ("GET", "/user.list"),
    "get_user": ("GET", "/user.info"),
    "list_groups": ("GET", "/group.list"),
    "get_group": ("GET", "/group.info"),
    "create_group": ("POST", "/group.create"),
    "join_group": ("POST", "/group.join"),
    "search_meetings": ("GET", "/meeting.search"),
    "list_meetings": ("GET", "/meeting.list"),
    "get_meeting": ("GET", "/meeting.info"),
    "get_meeting_transcript": ("GET", "/meeting.transcript"),
    "create_meeting_share_link": ("POST", "/meeting.shareLink"),
}
LIST_KEYS = {"list_chats": "chats", "get_chat_history": "messages", "search_messages": "messages",
             "list_users": "users", "list_groups": "groups", "list_meetings": "meetings", "search_meetings": "results"}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class RoamNode(WorkflowNode):
    integration_type = "automation-roam"
    connection_evidence = ConnectionEvidence(noun="account", identity_operation="get_token_info")

    @classmethod
    def get_config_model(cls):
        return RoamNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if isinstance(raw, dict) and raw.get("credential_type", "roam_token") != "roam_token":
            raise ValueError("Attach a Roam personal access token")
        return super().parse_config(config_data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Roam personal access token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, path = ROUTES[op.operation]
        payload = op.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        if isinstance(op, PostMessage):
            payload["sync"] = True
        if method == "GET":
            payload = {k: str(v).lower() if isinstance(v, bool) else v for k, v in payload.items()}
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + token, "Roam-Version": API_VERSION, "Accept": "application/json"},
                    **({"params": payload} if method == "GET" else {"json": payload}))
        except httpx.RequestError:
            raise ValueError("Roam request could not be completed; inspect any write before retrying") from None
        if not 200 <= response.status_code < 300:
            try:
                body = response.json()
                error = body.get("error") if isinstance(body, dict) else None
            except ValueError:
                error = None
            result = {"status": "error", "http_status": response.status_code,
                      "error": error or "Roam rejected the request", "retry_after": response.headers.get("Retry-After")}
        else:
            if not response.content and op.operation in {"add_reaction", "remove_reaction"}:
                body = {}
            else:
                try:
                    body = response.json()
                except ValueError:
                    raise ValueError("Roam returned an unexpected response; inspect any write before retrying") from None
            if not isinstance(body, dict):
                raise ValueError("Roam returned an unexpected JSON envelope")
            if body.get("ok") is False or body.get("error"):
                result = {"status": "error", "http_status": response.status_code, "error": body.get("error", "Roam rejected the request")}
            else:
                key = LIST_KEYS.get(op.operation)
                if key and not isinstance(body.get(key), list):
                    raise ValueError("Roam omitted the documented result list")
                if isinstance(op, GetTokenInfo) and not (isinstance(body.get("user"), dict) and isinstance(body.get("roam"), dict)):
                    raise ValueError("Roam omitted the connected principal or workspace")
                following = body.get("nextCursor")
                if following is not None and not isinstance(following, str):
                    raise ValueError("Roam returned an invalid nextCursor")
                result = {"status": "success", "data": body, "http_status": response.status_code}
                if key:
                    result.update(items=body[key], next_cursor=following, has_more=bool(following))
        result = _redact(result, token)
        await self.emit(result)
        return result
