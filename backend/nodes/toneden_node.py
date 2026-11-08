"""ToneDen links, advertising, social unlocks, contests and playbook campaigns.

Contract: https://developers.toneden.io/openapi/5ef41061b8704e003bc8b8c5
List operations return one offset/limit page; writes return the provider's
acknowledgement, without claiming independent readback or downstream delivery.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.toneden import TONEDEN_SCOPES
from nodes.toneden_operations import TONEDEN_OPERATIONS
from utils.ssrf import guarded_async_client

BASE_URL = "https://www.toneden.io/api/v1"
TargetType = Literal[
    "music",
    "podcast",
    "livestream",
    "event",
    "tour",
    "biglink",
    "fundraiser",
    "smartlink",
    "custom",
]
ID = Annotated[int, Field(gt=0)]


class TonedenOAuthCredential(BaseModel):
    model_config = ConfigDict(
        title="Toneden OAuth",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "toneden",
            "x-oauth-scopes": TONEDEN_SCOPES.declared_scopes(),
            "x-credential-url": "https://developers.toneden.io/docs/getting-started",
            "x-credential-instructions": "Connect your ToneDen account. The instance administrator must register a ToneDen app in Developer Settings and obtain ToneDen review before API access. Reconnect if the access token is revoked; ToneDen documents no refresh-token flow.",
        },
    )
    credential_type: Literal["toneden_oauth"] = Field(
        "toneden_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        min_length=1,
        repr=False,
        title="Access token",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(c.isspace() for c in value):
            raise ValueError("An access token without whitespace is required")
        return value


class Fields(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class LinkID(Fields):
    link_id: ID


class CampaignID(Fields):
    campaign_id: ID


class AttachmentID(Fields):
    attachment_id: ID


class PageUser(Fields):
    user_id: ID = Field(
        ...,
        description="Numeric ToneDen profile ID. Use Get Current User to find your account ID.",
    )
    offset: int = Field(0, ge=0)
    limit: int = Field(
        100,
        ge=1,
        description="Number of results in this page; increase offset explicitly for the next page.",
    )
    target_type: TargetType | None = None


class LinkContent(Fields):
    title: str | None = None
    target_url: str | None = None
    target_type: TargetType | None = None
    shortened_path: str | None = None
    subdomain: str | None = None
    custom_domain: str | None = None
    header: str | None = None
    metadata_title: str | None = None
    metadata_description: str | None = None
    metadata_image_url: str | None = None
    image_url: str | None = None
    show_socials: bool | None = None
    skip_landing_page: bool | None = None


class CreateLinkFields(LinkContent):
    user_id: ID
    title: str = Field(..., min_length=1)
    target_type: TargetType
    target_url: str = Field(..., min_length=1)


class UpdateLinkFields(LinkID, LinkContent):
    title: str = Field(
        ...,
        min_length=1,
        description="New link title. Other supplied fields are updated in the same request.",
    )


class ExpandLinkFields(Fields):
    target_type: TargetType
    url: str | None = None
    upc: str | None = None
    isrc: str | None = None


class CheckPathFields(Fields):
    path: str = Field(..., min_length=1)
    subdomain: str | None = None
    link_id: ID | None = None


class LinkInsightsFields(LinkID):
    metric: Literal["clicks", "clickthroughs", "rsvps"] = Field(
        "clicks", description="RSVPs are supported for livestream links only."
    )
    start_date: str | None = Field(None, description="ISO 8601 start date.")
    end_date: str | None = Field(None, description="ISO 8601 end date.")
    aggregate_interval: Literal["day", "hour", "week"] | None = None
    aggregate_geo: Literal["city", "country", "region"] | None = None
    aggregate_by_referrer: bool | None = None
    aggregate_by_service: bool | None = None
    for_distinct_fans: bool | None = None


class ListAdFields(Fields):
    user_id: ID
    offset: int = Field(0, ge=0)
    limit: int = Field(100, ge=1)
    status: Literal[
        "active", "live", "recent", "paused", "error", "inactive", "scheduled"
    ] = "active"


class UpdateAdFields(CampaignID):
    title: str = Field(..., min_length=1)
    status: Literal[
        "active",
        "inactive",
        "draft",
        "error",
        "pending",
        "pending-update",
        "paused",
        "pending-review",
    ] | None = Field(
        None, description="Changing campaign status can start or stop paid advertising."
    )
    budget_type: Literal["daily", "lifetime"] | None = None
    budget_amount: float | None = Field(
        None, gt=0, description="Changing the budget affects advertising spend."
    )
    is_archived: bool | None = None
    disable_all_notifications: bool | None = None


class ListAttachmentFields(Fields):
    user_id: ID
    type: Literal["unlock", "contest"]
    offset: int = Field(0, ge=0)
    limit: int = Field(100, ge=1)


class AttachmentContent(Fields):
    artwork_url: str | None = None
    message: str | None = None
    is_private: bool | None = None
    is_hidden: bool | None = None
    link_path: str | None = None


class CreateAttachmentFields(AttachmentContent):
    owner_id: ID
    type: Literal["unlock", "contest"]
    title: str = Field(..., min_length=1)


class UpdateAttachmentFields(AttachmentID, AttachmentContent):
    title: str = Field(..., min_length=1)


class AttachmentStatsFields(AttachmentID):
    aggregate_interval: Literal["day", "hour", "week"] = "day"
    start_date: str | None = None


class UpdatePlaybookFields(CampaignID):
    title: str = Field(..., min_length=1)
    status: Literal[
        "active", "paused", "inactive", "draft", "error", "pending"
    ] | None = Field(
        None, description="Activating a playbook can run its configured campaigns."
    )
    is_archived: bool | None = None


def _operation(name):
    return Field(
        name,
        title=name.replace("_", " ").title(),
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": name.replace("_", " ").title(),
        },
    )


class GetCurrentUser(Fields):
    operation: Literal["get_current_user"] = _operation("get_current_user")


class ListLinks(PageUser):
    operation: Literal["list_links"] = _operation("list_links")


class GetLink(LinkID):
    operation: Literal["get_link"] = _operation("get_link")


class CreateLink(CreateLinkFields):
    operation: Literal["create_link"] = _operation("create_link")


class UpdateLink(UpdateLinkFields):
    operation: Literal["update_link"] = _operation("update_link")


class DeleteLink(LinkID):
    operation: Literal["delete_link"] = _operation("delete_link")


class ExpandLink(ExpandLinkFields):
    operation: Literal["expand_link"] = _operation("expand_link")


class CheckLinkPath(CheckPathFields):
    operation: Literal["check_link_path"] = _operation("check_link_path")


class GetLinkInsights(LinkInsightsFields):
    operation: Literal["get_link_insights"] = _operation("get_link_insights")


class GetLinkOverview(LinkID):
    operation: Literal["get_link_overview"] = _operation("get_link_overview")


class ListAdCampaigns(ListAdFields):
    operation: Literal["list_ad_campaigns"] = _operation("list_ad_campaigns")


class GetAdCampaign(CampaignID):
    operation: Literal["get_ad_campaign"] = _operation("get_ad_campaign")


class UpdateAdCampaign(UpdateAdFields):
    operation: Literal["update_ad_campaign"] = _operation("update_ad_campaign")


class GetAdCampaignInsights(CampaignID):
    operation: Literal["get_ad_campaign_insights"] = _operation(
        "get_ad_campaign_insights"
    )


class GetAdCreativeInsights(CampaignID):
    operation: Literal["get_ad_creative_insights"] = _operation(
        "get_ad_creative_insights"
    )


class ListAttachments(ListAttachmentFields):
    operation: Literal["list_attachments"] = _operation("list_attachments")


class GetAttachment(AttachmentID):
    operation: Literal["get_attachment"] = _operation("get_attachment")


class CreateAttachment(CreateAttachmentFields):
    operation: Literal["create_attachment"] = _operation("create_attachment")


class UpdateAttachment(UpdateAttachmentFields):
    operation: Literal["update_attachment"] = _operation("update_attachment")


class DeleteAttachment(AttachmentID):
    operation: Literal["delete_attachment"] = _operation("delete_attachment")


class GetAttachmentEntries(AttachmentStatsFields):
    operation: Literal["get_attachment_entries"] = _operation("get_attachment_entries")


class GetAttachmentUnlocks(AttachmentStatsFields):
    operation: Literal["get_attachment_unlocks"] = _operation("get_attachment_unlocks")


class GetPlaybookCampaign(CampaignID):
    operation: Literal["get_playbook_campaign"] = _operation("get_playbook_campaign")


class UpdatePlaybookCampaign(UpdatePlaybookFields):
    operation: Literal["update_playbook_campaign"] = _operation(
        "update_playbook_campaign"
    )


Operation = Annotated[
    Union[
        GetCurrentUser,
        ListLinks,
        GetLink,
        CreateLink,
        UpdateLink,
        DeleteLink,
        ExpandLink,
        CheckLinkPath,
        GetLinkInsights,
        GetLinkOverview,
        ListAdCampaigns,
        GetAdCampaign,
        UpdateAdCampaign,
        GetAdCampaignInsights,
        GetAdCreativeInsights,
        ListAttachments,
        GetAttachment,
        CreateAttachment,
        UpdateAttachment,
        DeleteAttachment,
        GetAttachmentEntries,
        GetAttachmentUnlocks,
        GetPlaybookCampaign,
        UpdatePlaybookCampaign,
    ],
    Field(discriminator="operation"),
]


class TonedenNodeConfig(NodeConfig[Operation, TonedenOAuthCredential]):
    pass


def _check_credential_type(config_data):
    credentials = (
        config_data.get("credentials") if isinstance(config_data, dict) else None
    )
    if (
        isinstance(credentials, dict)
        and credentials.get("credential_type", "toneden_oauth") != "toneden_oauth"
    ):
        raise ValueError("A ToneDen OAuth credential is required")


class TonedenNode(WorkflowNode):
    integration_type = "automation-toneden"
    scope_registry = TONEDEN_SCOPES
    connection_evidence = ConnectionEvidence(
        noun="ToneDen account", identity_operation="get_current_user"
    )

    @classmethod
    def get_config_model(cls):
        return TonedenNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        _check_credential_type(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _check_credential_type(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a ToneDen account")
        config = self.config.config
        spec = TONEDEN_OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec["path"]
        # Route identifiers are positive integers, never caller-controlled paths.
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", str(values.pop(key)))
        params = {key: values.pop(key) for key in spec["query"] if key in values}
        token = self.config.credentials.access_token
        async with guarded_async_client(
            timeout=30.0, follow_redirects=False, trust_env=False
        ) as client:
            async with client.stream(
                spec["method"],
                BASE_URL + path,
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/json",
                },
                params=params,
                **({"json": values} if spec["method"] in {"POST", "PUT"} else {}),
            ) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 8 * 1024 * 1024:
                        raise ValueError("ToneDen response exceeds 8 MiB")
                if response.status_code != 200:
                    message = (
                        bytes(raw)
                        .decode("utf-8", errors="replace")
                        .replace(token, "[redacted]")[:2000]
                    )
                    raise ValueError(f"ToneDen HTTP {response.status_code}: {message}")
                if (
                    "application/json"
                    not in response.headers.get("content-type", "").lower()
                ):
                    raise ValueError("ToneDen did not return JSON")
                try:
                    result = json.loads(raw)
                except (ValueError, UnicodeError):
                    raise ValueError("ToneDen returned invalid JSON") from None
        if (
            not isinstance(result, dict)
            or result.get("error")
            or result.get("success") is False
        ):
            raise ValueError("ToneDen returned an error or invalid response")
        key = spec["response_key"]
        if key not in result:
            raise ValueError(f"ToneDen response is missing {key}")
        expected = (
            list
            if key in {"links", "campaigns", "attachments", "ads", "unlocks"}
            or config.operation == "get_link_insights"
            else bool
            if key in {"valid", "success"}
            else dict
        )
        if not isinstance(result[key], expected):
            raise ValueError(f"ToneDen response has invalid {key}")
        return result
