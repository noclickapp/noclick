"""Zigpoll v1 survey automation using a pasted private API key.

Each operation performs one documented request. Cursor operations return one page;
pass endCursor as startCursor when hasNextPage is true.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://v1.zigpoll.com"


class ZigpollAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Zigpoll API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://apidocs.zigpoll.com/reference/authentication-1",
            "x-credential-instructions": "In the Zigpoll Dashboard, open Integrations, scroll to Private Keys, add a key and copy it here. API access requires an Advanced plan or higher. NoClick sends the key directly in the Authorization header to v1.zigpoll.com.",
        })
    credential_type: Literal["zigpoll_api_key"] = Field("zigpoll_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the Zigpoll private API key")
        value = clean_secret(value, field_name="API key")
        if any(ord(c) < 33 or ord(c) == 127 for c in value) or not value.isascii():
            raise ValueError("Paste only the Zigpoll private key, without a header or prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Account(_Input):
    accountId: str = Field(..., min_length=1, title="Account ID")


class _Poll(_Input):
    pollId: str = Field(..., min_length=1, title="Survey ID")


class _Slide(_Input):
    slideId: str = Field(..., min_length=1, title="Question ID")


class _Window(_Poll):
    createdAfter: str | None = Field(None, pattern=r"^[0-9]+$", title="Created on or after", description="JavaScript timestamp in milliseconds.")
    createdBefore: str | None = Field(None, pattern=r"^[0-9]+$", title="Created on or before", description="JavaScript timestamp in milliseconds.")


class _Page(_Poll):
    startCursor: str | None = Field(None, title="Start cursor", description="Previous page's endCursor. Omit for the first page.")
    limit: int = Field(50, ge=1, le=5000, title="Page size")


class _DatedPage(_Page):
    createdAfter: str | None = Field(None, pattern=r"^[0-9]+$", title="Created on or after", description="JavaScript timestamp in milliseconds.")
    createdBefore: str | None = Field(None, pattern=r"^[0-9]+$", title="Created on or before", description="JavaScript timestamp in milliseconds.")


class Answer(_Input):
    title: str = Field(..., min_length=1)


class ZigpollGetMeConfig(_Input):
    """Get current user."""
    operation: Literal["get_me"] = Field("get_me", json_schema_extra={"ui:hidden": True})


class ZigpollListAccountsConfig(_Input):
    """Get all accounts."""
    operation: Literal["list_accounts"] = Field("list_accounts", json_schema_extra={"ui:hidden": True})


class ZigpollGetAccountConfig(_Account):
    """Get account."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class ZigpollListPollsConfig(_Account):
    """Get all polls."""
    operation: Literal["list_polls"] = Field("list_polls", json_schema_extra={"ui:hidden": True})


class ZigpollGetPollConfig(_Poll):
    """Get poll."""
    operation: Literal["get_poll"] = Field("get_poll", json_schema_extra={"ui:hidden": True})


class ZigpollListSlidesConfig(_Window):
    """Get all slides."""
    operation: Literal["list_slides"] = Field("list_slides", json_schema_extra={"ui:hidden": True})


class ZigpollGetSlideConfig(_Slide):
    """Get slide."""
    operation: Literal["get_slide"] = Field("get_slide", json_schema_extra={"ui:hidden": True})


class ZigpollListResponsesConfig(_DatedPage):
    """Get all responses."""
    operation: Literal["list_responses"] = Field("list_responses", json_schema_extra={"ui:hidden": True})
    filter: Literal["fixed-choice", "open-ended"] | None = None
    order: Literal["newest", "oldest"] = "newest"


class ZigpollListParticipantsConfig(_DatedPage):
    """Get all participants."""
    operation: Literal["list_participants"] = Field("list_participants", json_schema_extra={"ui:hidden": True})


class ZigpollListEmailsConfig(_DatedPage):
    """Get all emails."""
    operation: Literal["list_emails"] = Field("list_emails", json_schema_extra={"ui:hidden": True})


class ZigpollListInsightsConfig(_Page):
    """Get all insights."""
    operation: Literal["list_insights"] = Field("list_insights", json_schema_extra={"ui:hidden": True})


class ZigpollGetMetadataConfig(_Window):
    """Response metadata breakdown."""
    operation: Literal["get_metadata"] = Field("get_metadata", json_schema_extra={"ui:hidden": True})
    key: str | None = Field(None, title="Metadata key", description="Omit to discover available metadata keys.")


class ZigpollGetLocationsConfig(_Poll):
    """Geographic breakdown."""
    operation: Literal["get_locations"] = Field("get_locations", json_schema_extra={"ui:hidden": True})


class ZigpollGetDevicesConfig(_Poll):
    """Device, browser and OS breakdown."""
    operation: Literal["get_devices"] = Field("get_devices", json_schema_extra={"ui:hidden": True})


class ZigpollGetTrendsConfig(_Window):
    """Responses over time."""
    operation: Literal["get_trends"] = Field("get_trends", json_schema_extra={"ui:hidden": True})


class ZigpollCreatePollConfig(_Account):
    """Create poll."""
    operation: Literal["create_poll"] = Field("create_poll", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1, title="Survey title")
    pageRules: list[str] | None = Field(None, title="Page rules")
    pageExcludeRules: list[str] | None = Field(None, title="Excluded page rules")
    isSynthetic: StrictBool = Field(False, title="Synthetic research survey")


class ZigpollUpdatePollConfig(_Poll):
    """Update poll."""
    operation: Literal["update_poll"] = Field("update_poll", json_schema_extra={"ui:hidden": True})
    title: str | None = Field(None, min_length=1, title="Survey title")
    isVisible: StrictBool | None = Field(None, title="Visible", description="Requires at least one question and an unarchived survey.")
    isArchived: StrictBool | None = Field(None, title="Archived")
    pageRules: list[str] | None = Field(None, title="Page rules", description="Replaces the complete page rules array.")
    pageExcludeRules: list[str] | None = Field(None, title="Excluded page rules", description="Replaces the complete exclusion array.")


class ZigpollCreateSlideConfig(_Poll):
    """Create slide."""
    operation: Literal["create_slide"] = Field("create_slide", json_schema_extra={"ui:hidden": True})
    type: Literal['question', 'checkbox', 'dropdown', 'autocomplete', 'image-choice', 'binary', 'legal-consent', 'inline-multiple-choice', 'star-rating', 'range', 'satisfaction', 'slider', 'short-answer', 'long-answer', 'email-capture', 'phone-capture', 'date', 'file-upload', 'country', 'rank', 'form', 'copy', 'thank-you', 'reward', 'action', 'matrix'] = Field(..., title="Question type")
    title: str | None = Field(None, title="Question title")
    copy: str | None = Field(None, title="Body copy")
    answers: list[Answer] | None = Field(None, title="Answer options")
    rows: list[Answer] | None = Field(None, title="Matrix rows")


class ZigpollUpdateSlideConfig(_Slide):
    """Update slide."""
    operation: Literal["update_slide"] = Field("update_slide", json_schema_extra={"ui:hidden": True})
    title: str | None = Field(None, title="Question title")
    copy: str | None = Field(None, title="Body copy")
    answers: list[Answer] | None = Field(None, title="Answer options", description="Replaces the complete options array.")
    nextSlide: str | None = Field(None, title="Next question ID", description="Use -1 to end the survey.")


class ZigpollSendEmailConfig(_Poll):
    """Send email campaign."""
    operation: Literal["send_email"] = Field("send_email", json_schema_extra={"ui:hidden": True})
    recipients: list[str] = Field(..., min_length=1, title="Recipient email addresses", description="Zigpoll skips invalid and placeholder addresses and reports sent and skipped recipients. Acknowledgement does not prove delivery.")


class ZigpollSendSmsConfig(_Poll):
    """Send SMS campaign."""
    operation: Literal["send_sms"] = Field("send_sms", json_schema_extra={"ui:hidden": True})
    recipients: list[str] = Field(..., min_length=1, title="Recipient phone numbers", description="E.164 or domestic numbers. Acknowledgement does not prove delivery.")
    message: str | None = Field(None, title="Message override")


class ZigpollGenerateSurveyLinkConfig(_Poll):
    """Generate a unique survey link."""
    operation: Literal["generate_survey_link"] = Field("generate_survey_link", json_schema_extra={"ui:hidden": True})
    metadata: dict[str, Any] | None = Field(None, title="Tracking metadata")
    expiresAt: str | None = Field(None, title="Expires at", json_schema_extra={"format": "date-time"}, description="ISO 8601 datetime.")


ZigpollOperation = Annotated[Union[
    ZigpollGetMeConfig,
    ZigpollListAccountsConfig,
    ZigpollGetAccountConfig,
    ZigpollListPollsConfig,
    ZigpollGetPollConfig,
    ZigpollListSlidesConfig,
    ZigpollGetSlideConfig,
    ZigpollListResponsesConfig,
    ZigpollListParticipantsConfig,
    ZigpollListEmailsConfig,
    ZigpollListInsightsConfig,
    ZigpollGetMetadataConfig,
    ZigpollGetLocationsConfig,
    ZigpollGetDevicesConfig,
    ZigpollGetTrendsConfig,
    ZigpollCreatePollConfig,
    ZigpollUpdatePollConfig,
    ZigpollCreateSlideConfig,
    ZigpollUpdateSlideConfig,
    ZigpollSendEmailConfig,
    ZigpollSendSmsConfig,
    ZigpollGenerateSurveyLinkConfig,
], Field(discriminator="operation")]


class ZigpollNodeConfig(NodeConfig[ZigpollOperation, ZigpollAPIKeyCredential]):
    pass


ROUTES = {
    "get_me": ("GET", "/me"),
    "list_accounts": ("GET", "/accounts"),
    "get_account": ("GET", "/account"),
    "list_polls": ("GET", "/polls"),
    "get_poll": ("GET", "/poll"),
    "list_slides": ("GET", "/slides"),
    "get_slide": ("GET", "/slide"),
    "list_responses": ("GET", "/responses"),
    "list_participants": ("GET", "/participants"),
    "list_emails": ("GET", "/emails"),
    "list_insights": ("GET", "/insights"),
    "get_metadata": ("GET", "/poll/metadata"),
    "get_locations": ("GET", "/poll/locations"),
    "get_devices": ("GET", "/poll/devices"),
    "get_trends": ("GET", "/poll/trends"),
    "create_poll": ("POST", "/poll"),
    "update_poll": ("POST", "/poll/update"),
    "create_slide": ("POST", "/slide"),
    "update_slide": ("POST", "/slide/update"),
    "send_email": ("POST", "/send-email"),
    "send_sms": ("POST", "/send-sms"),
    "generate_survey_link": ("POST", "/generate-survey-link"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()}
    return value


class ZigpollNode(WorkflowNode):
    integration_type = "automation-zigpoll"
    connection_evidence = ConnectionEvidence(
        operation="list_accounts", identity_operation="get_me", noun="accounts",
        label_keys=("title", "name", "email", "_id"),
    )

    @classmethod
    def get_config_model(cls):
        return ZigpollNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Zigpoll API key")
        token = self.config.credentials.api_key
        config = self.config.config
        method, path = ROUTES[config.operation]
        data = config.model_dump(exclude={"operation"}, exclude_none=True)
        # These pagination fields are strings in the published v1 contract.
        if method == "GET" and "limit" in data:
            data["limit"] = str(data["limit"])
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": token, "Accept": "application/json"},
                    **({"params": data} if method == "GET" else {"json": data}))
        except httpx.HTTPError:
            raise ValueError("Zigpoll request did not complete; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            detail = _redact(response.text, token)[:2000]
            raise ValueError(f"Zigpoll HTTP {response.status_code}: {detail}")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Zigpoll returned a non-JSON response; inspect writes before retrying") from None
        if not isinstance(payload, (dict, list)):
            raise ValueError("Zigpoll returned an unexpected response shape")
        if isinstance(payload, dict) and (payload.get("error") or payload.get("success") is False):
            raise ValueError("Zigpoll rejected the request: " + str(_redact(payload, token)))
        expected = list if config.operation in {"list_accounts", "list_polls", "list_slides"} else dict
        if not isinstance(payload, expected):
            raise ValueError("Zigpoll returned an unexpected response shape")
        if isinstance(payload, list) and any(not isinstance(row, dict) for row in payload):
            raise ValueError("Zigpoll returned an invalid resource list")
        if isinstance(config, _Page) and (
            not isinstance(payload.get("data"), list) or type(payload.get("hasNextPage")) is not bool
        ):
            raise ValueError("Zigpoll returned an invalid cursor page")
        if config.operation == "get_me" and not any(
            isinstance(payload.get(key), str) and payload[key].strip() for key in ("name", "email", "_id")
        ):
            raise ValueError("Zigpoll returned an unrecognizable account identity")
        output = {"data": _redact(payload, token)}
        await self.emit(output)
        return output
