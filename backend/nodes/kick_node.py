"""Kick Public API actions, pinned to the provider's Swagger 1.0.0 contract."""
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_refresh import ensure_fresh_oauth_token, freshen_oauth_credential
from nodes.kick_operations import OPERATIONS
from nodes.oauth.kick_oauth import refresh_access_token
from nodes.scopes.kick import KICK_SCOPES


class KickOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Kick OAuth", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "kick",
        "x-oauth-scopes": sorted(KICK_SCOPES.declared_scopes()),
        "x-credential-url": "https://kick.com/settings/developer",
        "x-credential-instructions": "Connect your Kick account, or paste an existing user access token with the required scopes. Refresh token and expiry are optional when connecting by hand.",
    })
    credential_type: Literal["kick_oauth"] = Field("kick_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Access Token", json_schema_extra={"ui:widget": "password"})
    refresh_token: Optional[str] = Field(None, title="Refresh Token", json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    scope: Optional[str] = Field(None, title="Granted Scopes")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KickGetUsersConfig(_Input):
    """Get Users. Returns the provider response."""
    operation: Literal['get_users'] = Field('get_users', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Users', "x-is-trigger": False})
    id: Optional[list[int]] = Field(None, min_length=1, description='User IDs')


class KickSearchCategoriesConfig(_Input):
    """Get Categories. Returns the provider response."""
    operation: Literal['search_categories'] = Field('search_categories', json_schema_extra={"ui:hidden": True, "x-display-name": 'Search Categories', "x-is-trigger": False})
    q: str = Field(..., min_length=1, description='Search query')
    page: int = Field(1, ge=1, description='Page (defaults to 1 if not provided)')


class KickGetCategoryConfig(_Input):
    """Get Category. Returns the provider response."""
    operation: Literal['get_category'] = Field('get_category', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Category', "x-is-trigger": False})
    category_id: int = Field(..., ge=1, description='Category ID')


class KickGetChannelsConfig(_Input):
    """Get Channels. Returns the provider response."""
    operation: Literal['get_channels'] = Field('get_channels', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Channels', "x-is-trigger": False})
    broadcaster_user_id: Optional[list[int]] = Field(None, min_length=1, max_length=50, description='Broadcaster User IDs (cannot be used with slug)')
    slug: Optional[list[Annotated[str, Field(min_length=1, max_length=25)]]] = Field(None, min_length=1, max_length=50, description='Channel slugs (cannot be used with broadcaster_user_id)')

    @model_validator(mode="after")
    def exclusive_filters(self):
        if self.slug is not None and self.broadcaster_user_id is not None:
            raise ValueError("Use slugs or broadcaster user IDs, not both")
        return self


class KickUpdateChannelConfig(_Input):
    """Patch Channels. Returns the provider response."""
    operation: Literal['update_channel'] = Field('update_channel', json_schema_extra={"ui:hidden": True, "x-display-name": 'Update Channel', "x-is-trigger": False})
    category_id: Optional[int] = Field(None, ge=1)
    custom_tags: Optional[list[str]] = Field(None, max_length=10)
    stream_title: Optional[str] = Field(None, min_length=1)

    @model_validator(mode="after")
    def nonempty_update(self):
        if not any(getattr(self, k) is not None for k in ['category_id', 'custom_tags', 'stream_title']):
            raise ValueError("Set at least one field to update")
        return self


class KickListRewardsConfig(_Input):
    """Get Channel Rewards. Returns the provider response."""
    operation: Literal['list_rewards'] = Field('list_rewards', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Rewards', "x-is-trigger": False})


class KickCreateRewardConfig(_Input):
    """Create Channel Reward. Returns the provider response."""
    operation: Literal['create_reward'] = Field('create_reward', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create Reward', "x-is-trigger": False})
    background_color: Annotated[str, Field(pattern='^#[0-9a-fA-F]{6}$')] = Field('#00e701')
    cost: int = Field(..., ge=1)
    description: Optional[str] = Field(None, max_length=200, min_length=1)
    is_enabled: bool = Field(True)
    is_user_input_required: bool = Field(False)
    should_redemptions_skip_request_queue: bool = Field(False)
    title: str = Field(..., max_length=50, min_length=1)


class KickUpdateRewardConfig(_Input):
    """Update Channel Reward. Returns the provider response."""
    operation: Literal['update_reward'] = Field('update_reward', json_schema_extra={"ui:hidden": True, "x-display-name": 'Update Reward', "x-is-trigger": False})
    id: Annotated[str, Field(pattern='^[0-9A-HJKMNP-TV-Z]{26}$')] = Field(..., min_length=1, description='Reward ID')
    background_color: Optional[Annotated[str, Field(pattern='^#[0-9a-fA-F]{6}$')]] = Field(None, min_length=1)
    cost: Optional[int] = Field(None, ge=1)
    description: Optional[str] = Field(None, max_length=200, min_length=1)
    is_enabled: Optional[bool] = Field(None)
    is_paused: Optional[bool] = Field(None)
    is_user_input_required: Optional[bool] = Field(None)
    should_redemptions_skip_request_queue: Optional[bool] = Field(None)
    title: Optional[str] = Field(None, max_length=50, min_length=1)

    @model_validator(mode="after")
    def nonempty_update(self):
        if not any(getattr(self, k) is not None for k in ['background_color', 'cost', 'description', 'is_enabled', 'is_paused', 'is_user_input_required', 'should_redemptions_skip_request_queue', 'title']):
            raise ValueError("Set at least one field to update")
        return self


class KickDeleteRewardConfig(_Input):
    """Delete Channel Reward. Returns the provider response."""
    operation: Literal['delete_reward'] = Field('delete_reward', json_schema_extra={"ui:hidden": True, "x-display-name": 'Delete Reward', "x-is-trigger": False})
    id: Annotated[str, Field(pattern='^[0-9A-HJKMNP-TV-Z]{26}$')] = Field(..., min_length=1, description='Reward ID')


class KickListRedemptionsConfig(_Input):
    """Get Channel Reward Redemptions. Returns the provider response."""
    operation: Literal['list_redemptions'] = Field('list_redemptions', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Redemptions', "x-is-trigger": False})
    reward_id: Optional[Annotated[str, Field(pattern='^[0-9A-HJKMNP-TV-Z]{26}$')]] = Field(None, min_length=1, description='Optionally provide a reward ID to list redemptions for that specific reward.')
    status: Optional[Literal['pending', 'accepted', 'rejected']] = Field(None, min_length=1, description='Optionally provide a specific status to filter by. Defaults to pending.')
    id: Optional[list[str]] = Field(None, min_length=1, description='Optionally provide a list of redemption IDs to filter by. You cannot provide any other filters if you filter by redemption IDs.')
    cursor: Optional[str] = Field(None, min_length=1, description='Optionally provide a cursor to paginate through the results.')

    @model_validator(mode="after")
    def exclusive_filters(self):
        if self.id is not None and any(v is not None for v in (self.reward_id, self.status, self.cursor)):
            raise ValueError("Redemption IDs cannot be combined with other filters")
        return self


class KickAcceptRedemptionsConfig(_Input):
    """Accept Channel Reward Redemptions. Returns the provider response."""
    operation: Literal['accept_redemptions'] = Field('accept_redemptions', json_schema_extra={"ui:hidden": True, "x-display-name": 'Accept Redemptions', "x-is-trigger": False})
    ids: list[Annotated[str, Field(pattern='^[0-9A-HJKMNP-TV-Z]{26}$')]] = Field(..., min_length=1, max_length=25, description='List of redemption IDs to accept. A maximum of 25 redemptions can be accepted per request. IDs must be unique.')

    @field_validator("ids")
    @classmethod
    def unique_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Redemption IDs must be unique")
        return value


class KickRejectRedemptionsConfig(_Input):
    """Reject Channel Reward Redemptions. Returns the provider response."""
    operation: Literal['reject_redemptions'] = Field('reject_redemptions', json_schema_extra={"ui:hidden": True, "x-display-name": 'Reject Redemptions', "x-is-trigger": False})
    ids: list[Annotated[str, Field(pattern='^[0-9A-HJKMNP-TV-Z]{26}$')]] = Field(..., min_length=1, max_length=25, description='List of redemption IDs to reject. A maximum of 25 redemptions can be rejected per request. IDs must be unique.')

    @field_validator("ids")
    @classmethod
    def unique_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Redemption IDs must be unique")
        return value


class KickSendMessageConfig(_Input):
    """Post Chat Message. Returns the provider response."""
    operation: Literal['send_message'] = Field('send_message', json_schema_extra={"ui:hidden": True, "x-display-name": 'Send Message', "x-is-trigger": False})
    broadcaster_user_id: Optional[int] = Field(None, ge=1)
    content: str = Field(..., max_length=500, min_length=1)
    reply_to_message_id: Optional[Annotated[str, Field(pattern='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')]] = Field(None, min_length=1)
    type: Literal['user', 'bot'] = Field(..., min_length=1)

    @model_validator(mode="after")
    def user_target(self):
        if self.type == "user" and self.broadcaster_user_id is None:
            raise ValueError("User messages require a broadcaster user ID")
        return self


class KickDeleteMessageConfig(_Input):
    """Delete Chat Message. Returns the provider response."""
    operation: Literal['delete_message'] = Field('delete_message', json_schema_extra={"ui:hidden": True, "x-display-name": 'Delete Message', "x-is-trigger": False})
    message_id: str = Field(..., min_length=1, description='Message ID')


class KickListLivestreamsConfig(_Input):
    """Get Livestreams. Returns the provider response."""
    operation: Literal['list_livestreams'] = Field('list_livestreams', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Livestreams', "x-is-trigger": False})
    category_id: Optional[list[int]] = Field(None, min_length=1, max_length=25, description='Filter for livestreams in a specific category. A maximum of 25 category IDs can be provided.')
    language_code: Optional[list[str]] = Field(None, min_length=1, max_length=25, description='Filter for livestreams in a specific language. Language code must be a valid BCP 47 language tag. A maximum of 25 languages can be provided.')
    limit: int = Field(100, ge=1, le=1000, description='Limit the number of results per page')
    cursor: Optional[str] = Field(None, min_length=1, description='Pagination cursor')


class KickGetLivestreamStatsConfig(_Input):
    """Get Livestreams Stats. Returns the provider response."""
    operation: Literal['get_livestream_stats'] = Field('get_livestream_stats', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Livestream Stats', "x-is-trigger": False})


class KickListUserLivestreamsConfig(_Input):
    """Get Livestreams for Users. Returns the provider response."""
    operation: Literal['list_user_livestreams'] = Field('list_user_livestreams', json_schema_extra={"ui:hidden": True, "x-display-name": 'List User Livestreams', "x-is-trigger": False})
    user_id: list[int] = Field(..., min_length=1, max_length=100, description='Broadcaster User IDs. A maximum of 100 user IDs can be provided.')


class KickBanUserConfig(_Input):
    """Post Moderation Bans. Returns the provider response."""
    operation: Literal['ban_user'] = Field('ban_user', json_schema_extra={"ui:hidden": True, "x-display-name": 'Ban User', "x-is-trigger": False})
    broadcaster_user_id: int = Field(..., ge=1)
    duration: Optional[int] = Field(None, ge=1, le=10080, description="To ban a user, don't include this field. To put a user in a timeout, include the timeout period in minutes.")
    reason: Optional[str] = Field(None, max_length=100, min_length=1)
    user_id: int = Field(..., ge=1)


class KickUnbanUserConfig(_Input):
    """Delete Moderation Bans. Returns the provider response."""
    operation: Literal['unban_user'] = Field('unban_user', json_schema_extra={"ui:hidden": True, "x-display-name": 'Unban User', "x-is-trigger": False})
    broadcaster_user_id: int = Field(..., ge=1)
    user_id: int = Field(..., ge=1)


class KickGetLeaderboardConfig(_Input):
    """Get KICKs Leaderboard. Returns the provider response."""
    operation: Literal['get_leaderboard'] = Field('get_leaderboard', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Leaderboard', "x-is-trigger": False})
    top: int = Field(10, ge=1, le=100, description='The number of entries from the top of the leaderboard to return. For example, 10 will fetch the top 10 entries.')

KickConfig = Annotated[Union[
    KickGetUsersConfig,
    KickSearchCategoriesConfig,
    KickGetCategoryConfig,
    KickGetChannelsConfig,
    KickUpdateChannelConfig,
    KickListRewardsConfig,
    KickCreateRewardConfig,
    KickUpdateRewardConfig,
    KickDeleteRewardConfig,
    KickListRedemptionsConfig,
    KickAcceptRedemptionsConfig,
    KickRejectRedemptionsConfig,
    KickSendMessageConfig,
    KickDeleteMessageConfig,
    KickListLivestreamsConfig,
    KickGetLivestreamStatsConfig,
    KickListUserLivestreamsConfig,
    KickBanUserConfig,
    KickUnbanUserConfig,
    KickGetLeaderboardConfig,
], Field(discriminator="operation")]


class KickNodeConfig(NodeConfig[KickConfig, KickOAuthCredential]):
    pass


class KickNode(WorkflowNode):
    integration_type = "automation-kick"
    scope_registry = KICK_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_users", noun="account", identity_operation="get_users")

    @classmethod
    def get_config_model(cls):
        return KickNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="kick",
        )

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your Kick account")
        auth = credential.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=auth, refresh=refresh_access_token, provider="kick", caller_path="execute",
        )
        credential.access_token = auth["access_token"]
        credential.refresh_token = auth.get("refresh_token")
        credential.expires_at = auth.get("expires_at")
        config = self.config.config
        descriptor = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True)
        path = descriptor["path"]
        for key in descriptor["path_params"]:
            path = path.replace("{" + key + "}", quote(str(values[key]), safe=""))
        query = {key: values[key] for key in descriptor["query"] if key in values}
        body = {key: values[key] for key in descriptor["body"] if key in values}
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(
                descriptor["method"], "https://api.kick.com" + path,
                headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"},
                params=query or None, json=body if descriptor["body"] else None,
            )
        response.raise_for_status()
        # DELETE endpoints can acknowledge success with an empty response.
        payload = response.json() if response.content else {}
        if not isinstance(payload, dict):
            raise ValueError("Expected a Kick JSON response object")
        if payload.get("error") or payload.get("errors"):
            raise ValueError("Kick rejected the request: " + str(payload.get("error") or payload["errors"]))
        return {**payload, "status": "success", "action": config.operation}
