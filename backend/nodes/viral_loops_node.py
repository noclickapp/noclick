"""Viral Loops v3 campaign, participant and reward automation.

Contract: https://dash.readme.com/api/v1/api-registry/50lm8pdmtrlsk5g
Each operation performs one request using a campaign-scoped API token.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.viral-loops.com/api/v3"


class ViralLoopsCredential(BaseModel):
    model_config = ConfigDict(title="Viral Loops API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.viral-loops.com/",
            "x-credential-instructions": "Open your Viral Loops campaign's API settings and paste its API token. Each token selects one campaign. Use the private API token, not the public token. NoClick reads the campaign name to verify the connection.",
        })
    credential_type: Literal["viral_loops_api_token"] = Field("viral_loops_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, title="API Token", repr=False, json_schema_extra={"ui:widget": "password"})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Participant(_Input):
    email: str | None = Field(None, description="Participant email; supply this or the referral code.")
    referralCode: str | None = Field(None, title="Referral Code")

    @model_validator(mode="after")
    def identified(self):
        if not self.email and not self.referralCode:
            raise ValueError("Supply the participant email or referral code")
        return self


class Page(_Input):
    limit: int = Field(50, ge=1, le=1000)
    skip: int = Field(0, ge=0)


class GetCampaignConfig(_Input):
    """Read the campaign selected by the API token."""
    operation: Literal["get_campaign"] = "get_campaign"


class GetCampaignStatsConfig(_Input):
    """Read campaign lead and referral totals."""
    operation: Literal["get_campaign_stats"] = "get_campaign_stats"


class GetParticipantConfig(Participant):
    """Read participant profile, referrals, points and rewards."""
    operation: Literal["get_participant"] = "get_participant"


class GetParticipantReferralsConfig(Participant):
    """Read one page of a participant's referrals."""
    operation: Literal["get_participant_referrals"] = "get_participant_referrals"
    limit: int = Field(50, ge=1, le=1000)
    offset: int = Field(0, ge=0)
    conversionStatus: int | None = Field(None, description="Numeric conversion status as documented by the v3 referrals endpoint.")


class GetParticipantOrderConfig(Participant):
    """Read the participant's registration order and campaign lead count."""
    operation: Literal["get_participant_order"] = "get_participant_order"


class GetParticipantRankConfig(Participant):
    """Read the participant's leaderboard rank and referral totals."""
    operation: Literal["get_participant_rank"] = "get_participant_rank"


class GetParticipantReferrerConfig(Participant):
    """Read who referred a participant."""
    operation: Literal["get_participant_referrer"] = "get_participant_referrer"


class GetPendingRewardsConfig(_Input):
    """Read pending rewards for a participant or a campaign page."""
    operation: Literal["get_pending_rewards"] = "get_pending_rewards"
    email: str | None = None
    referralCode: str | None = None


class GetGivenRewardsConfig(_Input):
    """Read given rewards for a participant or a campaign page."""
    operation: Literal["get_given_rewards"] = "get_given_rewards"
    email: str | None = None
    referralCode: str | None = None


class QueryParticipantsConfig(_Input):
    """Query participants and/or referrers with limit/skip pagination."""
    operation: Literal["query_participants"] = "query_participants"
    referrers: list[Participant] | None = Field(None, max_length=100)
    participants: list[Participant] | None = Field(None, max_length=100)
    filter: Page = Field(default_factory=Page, title="Pagination")


class SearchFilters(_Input):
    conversionStatus: Literal["all", "pending", "converted"] = "all"
    source: Literal["referred", "organic", "all"] = "all"
    searchTerm: str | None = None


class SearchPagination(_Input):
    offset: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=1000)


class SearchParticipantsConfig(_Input):
    """Search participants by text, conversion status and referral source."""
    operation: Literal["search_participants"] = "search_participants"
    filters: SearchFilters = Field(default_factory=SearchFilters)
    pagination: SearchPagination = Field(default_factory=SearchPagination)


class ConversionOptions(_Input):
    value: float | None = Field(None, description="Optional conversion value.")


class RegistrationUser(_Input):
    email: str = Field(..., min_length=1)
    firstname: str | None = None
    lastname: str | None = None
    consents: dict | None = None
    extraData: dict | None = None


class RegistrationReferrer(_Input):
    referralCode: str = Field(..., min_length=1)


class RegisterParticipantConfig(_Input):
    """Register a participant, optionally crediting a referrer; campaign emails and integrations may run."""
    operation: Literal["register_participant"] = "register_participant"
    user: RegistrationUser
    referrer: RegistrationReferrer | None = None
    refSource: str | None = None
    acquiredFrom: str | None = None


class ConvertParticipantConfig(_Input):
    """Record a participant conversion, optionally with a value."""
    operation: Literal["convert_participant"] = "convert_participant"
    user: Participant
    options: ConversionOptions | None = None


class RedeemRewardConfig(_Input):
    """Move a participant's pending reward to given rewards."""
    operation: Literal["redeem_reward"] = "redeem_reward"
    rewardId: str = Field(..., min_length=1, title="Reward ID")
    user: Participant


ViralLoopsConfig = Annotated[Union[
    GetCampaignConfig, GetCampaignStatsConfig, GetParticipantConfig,
    GetParticipantReferralsConfig, GetParticipantOrderConfig, GetParticipantRankConfig,
    GetParticipantReferrerConfig, GetPendingRewardsConfig, GetGivenRewardsConfig,
    QueryParticipantsConfig, SearchParticipantsConfig, RegisterParticipantConfig, ConvertParticipantConfig, RedeemRewardConfig,
], Field(discriminator="operation")]


class ViralLoopsFullConfig(NodeConfig[ViralLoopsConfig, ViralLoopsCredential]):
    pass


ROUTES = {
    "get_campaign": ("GET", "/campaign/data"),
    "get_campaign_stats": ("GET", "/campaign/stats"),
    "get_participant": ("GET", "/campaign/participant/data"),
    "get_participant_referrals": ("GET", "/campaign/participant/referrals"),
    "get_participant_order": ("GET", "/campaign/participant/order"),
    "get_participant_rank": ("GET", "/campaign/participant/rank"),
    "get_participant_referrer": ("GET", "/campaign/participant/referrer"),
    "get_pending_rewards": ("GET", "/campaign/participant/rewards/pending"),
    "get_given_rewards": ("GET", "/campaign/participant/rewards/given"),
    "query_participants": ("POST", "/campaign/participant/query"),
    "search_participants": ("POST", "/campaign/participant/search"),
    "register_participant": ("POST", "/campaign/participant"),
    "convert_participant": ("POST", "/campaign/participant/convert"),
    "redeem_reward": ("POST", "/campaign/participant/rewards/redeem"),
}


class ViralLoopsNode(WorkflowNode):
    integration_type = "automation-viral-loops"
    connection_evidence = ConnectionEvidence(
        noun="campaign", identity_operation="get_campaign", identity_keys=("campaignName", "companyName"),
    )

    @classmethod
    def get_config_model(cls):
        return ViralLoopsFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Viral Loops API token")
        config = self.config.config
        method, path = ROUTES[config.operation]
        payload = config.model_dump(exclude={"operation"}, exclude_none=True)
        headers = {"apiToken": credential.api_token, "Accept": "application/json"}
        kwargs = {"params": payload} if method == "GET" else {"json": payload}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, **kwargs)
        try:
            body = response.json()
        except ValueError:
            raise ValueError(f"Viral Loops returned non-JSON (HTTP {response.status_code})") from None
        if response.is_error or (isinstance(body, dict) and (body.get("error") or body.get("success") is False or body.get("status") is False)) or body is False:
            message = (body.get("message") or body.get("error")) if isinstance(body, dict) else None
            message = str(message or "Viral Loops request failed")
            if response.is_error:
                message += f" (HTTP {response.status_code})"
            raise ValueError(message.replace(credential.api_token, "[redacted]"))
        response.raise_for_status()
        return {"status": "success", "data": body}
