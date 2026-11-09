"""LINE Messaging API operations pinned to line/line-openapi messaging-api.yml 0.0.1.

One operation makes one provider request. Lists return a single page, including
LINE's next cursor. Writes report acceptance only and are never retried.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class LineTokenCredential(BaseModel):
    model_config = ConfigDict(title="LINE Channel Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.line.biz/console/",
            "x-credential-instructions": "Paste a channel access token from your Messaging API channel in the LINE Developers Console. A long-lived token is available on the Messaging API tab. Use a Messaging API token, not a LINE Login token. NoClick reads the bot profile to verify the connection. Tokens are not refreshed automatically; replace expired or revoked tokens here.",
        })
    credential_type: Literal["line_channel_access_token"] = Field("line_channel_access_token", json_schema_extra={"ui:hidden": True})
    channel_access_token: str = Field(..., min_length=1, max_length=8192, title="Channel access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("channel_access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Channel access token", key=True)
        if not value or any(c.isspace() for c in value):
            raise ValueError("Paste the channel access token without an Authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class LineGetBotInfoConfig(_Input):
    """Get the connected LINE Official Account profile."""
    operation: Literal["get_bot_info"] = Field("get_bot_info", json_schema_extra={"ui:hidden": True})


class LineGetProfileConfig(_Input):
    """Get a user profile using a webhook user ID."""
    operation: Literal["get_profile"] = Field("get_profile", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[^\s/?#\x00-\x1f\x7f]+$", description="Use the API ID from LINE webhook events or API results, not a display name or LINE ID.")


class LineListFollowersConfig(_Input):
    """Read one page of follower IDs; use next as start. Verified or premium accounts only."""
    operation: Literal["list_followers"] = Field("list_followers", json_schema_extra={"ui:hidden": True})
    start: str | None = Field(None, min_length=1, max_length=4096, description="Opaque next cursor from the previous page; omitted for the first page.")
    limit: int = Field(300, ge=1, le=1000)


class LineGetGroupSummaryConfig(_Input):
    """Get the name and picture of a group the bot has joined."""
    operation: Literal["get_group_summary"] = Field("get_group_summary", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[^\s/?#\x00-\x1f\x7f]+$", description="Use the API ID from LINE webhook events or API results, not a display name or LINE ID.")


class LineGetGroupMemberCountConfig(_Input):
    """Count group members, excluding the bot."""
    operation: Literal["get_group_member_count"] = Field("get_group_member_count", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[^\s/?#\x00-\x1f\x7f]+$", description="Use the API ID from LINE webhook events or API results, not a display name or LINE ID.")


class LineListGroupMembersConfig(_Input):
    """Read one page of group member IDs; verified or premium accounts only."""
    operation: Literal["list_group_members"] = Field("list_group_members", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[^\s/?#\x00-\x1f\x7f]+$", description="Use the API ID from LINE webhook events or API results, not a display name or LINE ID.")
    start: str | None = Field(None, min_length=1, max_length=4096, description="Opaque next cursor from the previous page; omitted for the first page.")


class LineGetGroupMemberProfileConfig(_Input):
    """Get a group member profile."""
    operation: Literal["get_group_member_profile"] = Field("get_group_member_profile", json_schema_extra={"ui:hidden": True})
    group_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[^\s/?#\x00-\x1f\x7f]+$", description="Use the API ID from LINE webhook events or API results, not a display name or LINE ID.")
    user_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[^\s/?#\x00-\x1f\x7f]+$", description="Use the API ID from LINE webhook events or API results, not a display name or LINE ID.")


class LineGetRoomMemberCountConfig(_Input):
    """Count members of a multi-person chat."""
    operation: Literal["get_room_member_count"] = Field("get_room_member_count", json_schema_extra={"ui:hidden": True})
    room_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[^\s/?#\x00-\x1f\x7f]+$", description="Use the API ID from LINE webhook events or API results, not a display name or LINE ID.")


class LineListRoomMembersConfig(_Input):
    """Read one page of room member IDs; verified or premium accounts only."""
    operation: Literal["list_room_members"] = Field("list_room_members", json_schema_extra={"ui:hidden": True})
    room_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[^\s/?#\x00-\x1f\x7f]+$", description="Use the API ID from LINE webhook events or API results, not a display name or LINE ID.")
    start: str | None = Field(None, min_length=1, max_length=4096, description="Opaque next cursor from the previous page; omitted for the first page.")


class LineGetRoomMemberProfileConfig(_Input):
    """Get a multi-person chat member profile."""
    operation: Literal["get_room_member_profile"] = Field("get_room_member_profile", json_schema_extra={"ui:hidden": True})
    room_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[^\s/?#\x00-\x1f\x7f]+$", description="Use the API ID from LINE webhook events or API results, not a display name or LINE ID.")
    user_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[^\s/?#\x00-\x1f\x7f]+$", description="Use the API ID from LINE webhook events or API results, not a display name or LINE ID.")


class LineGetMessageQuotaConfig(_Input):
    """Get the monthly message quota."""
    operation: Literal["get_message_quota"] = Field("get_message_quota", json_schema_extra={"ui:hidden": True})


class LineGetMessageQuotaConsumptionConfig(_Input):
    """Get this month's message usage."""
    operation: Literal["get_message_quota_consumption"] = Field("get_message_quota_consumption", json_schema_extra={"ui:hidden": True})


class LineListRichMenusConfig(_Input):
    """List rich menus created through the Messaging API."""
    operation: Literal["list_rich_menus"] = Field("list_rich_menus", json_schema_extra={"ui:hidden": True})


class LineGetRichMenuConfig(_Input):
    """Get a rich menu definition."""
    operation: Literal["get_rich_menu"] = Field("get_rich_menu", json_schema_extra={"ui:hidden": True})
    rich_menu_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[^\s/?#\x00-\x1f\x7f]+$", description="Use the API ID from LINE webhook events or API results, not a display name or LINE ID.")


class LineGetDefaultRichMenuConfig(_Input):
    """Get the default rich menu ID."""
    operation: Literal["get_default_rich_menu"] = Field("get_default_rich_menu", json_schema_extra={"ui:hidden": True})


class LineGetUserRichMenuConfig(_Input):
    """Get the rich menu assigned to a user."""
    operation: Literal["get_user_rich_menu"] = Field("get_user_rich_menu", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[^\s/?#\x00-\x1f\x7f]+$", description="Use the API ID from LINE webhook events or API results, not a display name or LINE ID.")


class LineLinkUserRichMenuConfig(_Input):
    """Assign an existing rich menu to one user."""
    operation: Literal["link_user_rich_menu"] = Field("link_user_rich_menu", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[^\s/?#\x00-\x1f\x7f]+$", description="Use the API ID from LINE webhook events or API results, not a display name or LINE ID.")
    rich_menu_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[^\s/?#\x00-\x1f\x7f]+$", description="Use the API ID from LINE webhook events or API results, not a display name or LINE ID.")


class LineUnlinkUserRichMenuConfig(_Input):
    """Remove a user-specific rich menu assignment."""
    operation: Literal["unlink_user_rich_menu"] = Field("unlink_user_rich_menu", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[^\s/?#\x00-\x1f\x7f]+$", description="Use the API ID from LINE webhook events or API results, not a display name or LINE ID.")


class LineSetDefaultRichMenuConfig(_Input):
    """Set an existing rich menu as the default."""
    operation: Literal["set_default_rich_menu"] = Field("set_default_rich_menu", json_schema_extra={"ui:hidden": True})
    rich_menu_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[^\s/?#\x00-\x1f\x7f]+$", description="Use the API ID from LINE webhook events or API results, not a display name or LINE ID.")


class LineCancelDefaultRichMenuConfig(_Input):
    """Cancel the default rich menu assignment."""
    operation: Literal["cancel_default_rich_menu"] = Field("cancel_default_rich_menu", json_schema_extra={"ui:hidden": True})


class LineReplyMessageConfig(_Input):
    """Reply with a text message using a short-lived, single-use webhook reply token. Acceptance does not prove delivery."""
    operation: Literal["reply_message"] = Field("reply_message", json_schema_extra={"ui:hidden": True})
    reply_token: str = Field(..., min_length=1, max_length=256, pattern=r"^[^\s/?#\x00-\x1f\x7f]+$", description="Use the API ID from LINE webhook events or API results, not a display name or LINE ID.")
    text: str = Field(..., min_length=1, max_length=5000, description="Text message, up to 5000 UTF-16 code units.")
    notification_disabled: bool = Field(False, description="Send without a push notification.")

    @field_validator("text")
    @classmethod
    def text_length(cls, value):
        if len(value.encode("utf-16-le")) // 2 > 5000:
            raise ValueError("Text must fit within 5000 UTF-16 code units")
        return value


class LinePushMessageConfig(_Input):
    """Send one text message to a user, group or room. Acceptance does not prove delivery."""
    operation: Literal["push_message"] = Field("push_message", json_schema_extra={"ui:hidden": True})
    to: str = Field(..., min_length=1, max_length=256, pattern=r"^[^\s/?#\x00-\x1f\x7f]+$", description="Use the API ID from LINE webhook events or API results, not a display name or LINE ID.")
    text: str = Field(..., min_length=1, max_length=5000, description="Text message, up to 5000 UTF-16 code units.")
    notification_disabled: bool = Field(False, description="Send without a push notification.")

    @field_validator("text")
    @classmethod
    def text_length(cls, value):
        if len(value.encode("utf-16-le")) // 2 > 5000:
            raise ValueError("Text must fit within 5000 UTF-16 code units")
        return value


class LineMulticastMessageConfig(_Input):
    """Send one text message to up to 500 user IDs. Acceptance does not prove delivery."""
    operation: Literal["multicast_message"] = Field("multicast_message", json_schema_extra={"ui:hidden": True})
    to: list[str] = Field(..., min_length=1, max_length=500, description="LINE user IDs from webhook events, not LINE display IDs.")
    text: str = Field(..., min_length=1, max_length=5000, description="Text message, up to 5000 UTF-16 code units.")
    notification_disabled: bool = Field(False, description="Send without a push notification.")

    @field_validator("text")
    @classmethod
    def text_length(cls, value):
        if len(value.encode("utf-16-le")) // 2 > 5000:
            raise ValueError("Text must fit within 5000 UTF-16 code units")
        return value


class LineBroadcastMessageConfig(_Input):
    """Send one text message to all friends of this Official Account. Acceptance does not prove delivery."""
    operation: Literal["broadcast_message"] = Field("broadcast_message", json_schema_extra={"ui:hidden": True})
    text: str = Field(..., min_length=1, max_length=5000, description="Text message, up to 5000 UTF-16 code units.")
    notification_disabled: bool = Field(False, description="Send without a push notification.")

    @field_validator("text")
    @classmethod
    def text_length(cls, value):
        if len(value.encode("utf-16-le")) // 2 > 5000:
            raise ValueError("Text must fit within 5000 UTF-16 code units")
        return value


LineConfig = Annotated[Union[LineGetBotInfoConfig, LineGetProfileConfig, LineListFollowersConfig, LineGetGroupSummaryConfig, LineGetGroupMemberCountConfig, LineListGroupMembersConfig, LineGetGroupMemberProfileConfig, LineGetRoomMemberCountConfig, LineListRoomMembersConfig, LineGetRoomMemberProfileConfig, LineGetMessageQuotaConfig, LineGetMessageQuotaConsumptionConfig, LineListRichMenusConfig, LineGetRichMenuConfig, LineGetDefaultRichMenuConfig, LineGetUserRichMenuConfig, LineLinkUserRichMenuConfig, LineUnlinkUserRichMenuConfig, LineSetDefaultRichMenuConfig, LineCancelDefaultRichMenuConfig, LineReplyMessageConfig, LinePushMessageConfig, LineMulticastMessageConfig, LineBroadcastMessageConfig], Field(discriminator="operation")]


class LineFullConfig(NodeConfig[LineConfig, LineTokenCredential]):
    pass


ROUTES = {'get_bot_info': ('GET', '/v2/bot/info'),
 'get_profile': ('GET', '/v2/bot/profile/{user_id}'),
 'list_followers': ('GET', '/v2/bot/followers/ids'),
 'get_group_summary': ('GET', '/v2/bot/group/{group_id}/summary'),
 'get_group_member_count': ('GET', '/v2/bot/group/{group_id}/members/count'),
 'list_group_members': ('GET', '/v2/bot/group/{group_id}/members/ids'),
 'get_group_member_profile': ('GET', '/v2/bot/group/{group_id}/member/{user_id}'),
 'get_room_member_count': ('GET', '/v2/bot/room/{room_id}/members/count'),
 'list_room_members': ('GET', '/v2/bot/room/{room_id}/members/ids'),
 'get_room_member_profile': ('GET', '/v2/bot/room/{room_id}/member/{user_id}'),
 'get_message_quota': ('GET', '/v2/bot/message/quota'),
 'get_message_quota_consumption': ('GET', '/v2/bot/message/quota/consumption'),
 'list_rich_menus': ('GET', '/v2/bot/richmenu/list'),
 'get_rich_menu': ('GET', '/v2/bot/richmenu/{rich_menu_id}'),
 'get_default_rich_menu': ('GET', '/v2/bot/user/all/richmenu'),
 'get_user_rich_menu': ('GET', '/v2/bot/user/{user_id}/richmenu'),
 'link_user_rich_menu': ('POST', '/v2/bot/user/{user_id}/richmenu/{rich_menu_id}'),
 'unlink_user_rich_menu': ('DELETE', '/v2/bot/user/{user_id}/richmenu'),
 'set_default_rich_menu': ('POST', '/v2/bot/user/all/richmenu/{rich_menu_id}'),
 'cancel_default_rich_menu': ('DELETE', '/v2/bot/user/all/richmenu'),
 'reply_message': ('POST', '/v2/bot/message/reply'),
 'push_message': ('POST', '/v2/bot/message/push'),
 'multicast_message': ('POST', '/v2/bot/message/multicast'),
 'broadcast_message': ('POST', '/v2/bot/message/broadcast')}


class LineNode(WorkflowNode):
    integration_type = "automation-line"
    connection_evidence = ConnectionEvidence(noun="LINE Official Account", identity_operation="get_bot_info", identity_keys=("displayName", "basicId", "userId"))

    @classmethod
    def get_config_model(cls):
        return LineFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a LINE channel access token")
        credential = self.config.credentials
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(exclude={"operation"}, exclude_none=True)
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        body = None
        params = None
        sending = config.operation in {"reply_message", "push_message", "multicast_message", "broadcast_message"}
        if sending:
            body = {"messages": [{"type": "text", "text": values.pop("text")}],
                    "notificationDisabled": values.pop("notification_disabled")}
            if "reply_token" in values:
                body["replyToken"] = values.pop("reply_token")
            body.update(values)
        elif values:
            params = values
        token = credential.channel_access_token
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://api.line.me" + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            raise ValueError("LINE request could not be confirmed; inspect any write before retrying") from None
        if response.status_code != 200:
            try:
                message = response.json().get("message", "LINE request rejected")
            except (ValueError, AttributeError):
                message = "LINE returned an unexpected response"
            message = str(message).replace(token, "[redacted]")[:2000]
            result = {"status": "error", "success": False, "http_status": response.status_code,
                      "message": message, "write_outcome": "unverified" if method != "GET" else None}
        else:
            try:
                data = response.json() if response.content else {}
                if not isinstance(data, dict):
                    raise ValueError()
                if config.operation == "get_bot_info" and not all(isinstance(data.get(k), str) and data[k] for k in ("userId", "displayName", "basicId")):
                    raise ValueError()
            except ValueError:
                raise ValueError("LINE response could not be read; inspect any write before retrying") from None
            # Never return a credential even if a provider accidentally echoes it.
            def redact(value):
                if isinstance(value, str): return value.replace(token, "[redacted]")
                if isinstance(value, list): return [redact(item) for item in value]
                if isinstance(value, dict): return {key: redact(item) for key, item in value.items()}
                return value
            result = {"status": "success", "success": True, "data": redact(data), "http_status": 200}
            if method != "GET":
                result.update(accepted=True, effect_verified=False)
            if config.operation in {"list_followers", "list_group_members", "list_room_members"}:
                result["next_page_token"] = result["data"].get("next")
        await self.emit(result)
        return result
