"""Sendspark campaigns, prospects, webhooks and transcripts via the public API."""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api-gw.sendspark.com"
ResourceID = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=1000)]
WebhookEvent = Literal["video_watched", "video_played", "video_cta_clicked", "video_viewed", "video_liked",
    "video_request_received", "video_generated_dv", "video_mp4_ready", "video_generated_error"]


def _url(value):
    if value is None:
        return value
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or any(c.isspace() for c in value):
        raise ValueError("Enter a complete HTTP or HTTPS URL without embedded credentials")
    return value


class SendsparkAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Sendspark API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://help.sendspark.com/how-to-create-api-keys",
        "x-credential-instructions": "Copy your API key and API secret from Sendspark's API Credentials page (account menu → API Credentials). Paste the values without header names. NoClick uses them to identify your workspace and run the operations you select.",
    })
    credential_type: Literal["sendspark_api_key"] = Field("sendspark_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", repr=False, json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., min_length=1, max_length=4096, title="API secret", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the credential value as text")
        value = clean_secret(value, field_name="API key or secret", key=True)
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the credential value without a header name")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)


class _Workspace(_Input):
    workspace_id: ResourceID = Field(..., title="Workspace ID", description="Use Get Workspace Identifier to find your workspace ID.")


class _Dynamic(_Workspace):
    dynamic_id: ResourceID = Field(..., title="Dynamic campaign ID")

    @field_validator("dynamic_id")
    @classmethod
    def campaign_id(cls, value):
        if value == "settings":
            raise ValueError("Use a campaign ID; settings is a reserved API route")
        return value


class _Webhook(_Workspace):
    webhook_id: ResourceID = Field(..., title="Webhook ID")


class ListWorkspaces(_Input):
    """Read workspaces available to the supplied credentials."""
    operation: Literal["list_workspaces"] = "list_workspaces"
    dropdown_rendering: bool | None = Field(None, alias="dropdownRendering", strict=True)


class GetWorkspaceIdentifier(_Input):
    """Identify the workspace that owns this API key."""
    operation: Literal["get_workspace_identifier"] = "get_workspace_identifier"


class ListWebhooks(_Workspace):
    """Read workspace webhooks; the contract also permits an empty 204 response."""
    operation: Literal["list_webhooks"] = "list_webhooks"


class GetWebhook(_Webhook):
    operation: Literal["get_webhook"] = "get_webhook"


class CreateWebhook(_Workspace):
    """Register a webhook URL for Sendspark events."""
    operation: Literal["create_webhook"] = "create_webhook"
    name: Text
    url: str = Field(..., max_length=8192)
    module: Literal["global", "dynamics"]
    description: str | None = Field(None, max_length=10000)
    extra_headers: list[Text] | None = Field(None, alias="extraHeaders", max_length=100, json_schema_extra={"ui:widget": "list"})
    identifiers: list[ResourceID] | None = Field(None, max_length=1000, json_schema_extra={"ui:widget": "list"})
    events: list[WebhookEvent] | None = Field(None, max_length=9)

    @field_validator("url")
    @classmethod
    def url_value(cls, value):
        return _url(value)


class UpdateWebhook(_Webhook):
    operation: Literal["update_webhook"] = "update_webhook"
    name: Text | None = None
    url: str | None = Field(None, max_length=8192)
    module: Literal["global", "dynamics"] | None = None
    description: str | None = Field(None, max_length=10000)
    extra_headers: list[Text] | None = Field(None, alias="extraHeaders", max_length=100, json_schema_extra={"ui:widget": "list"})
    identifiers: list[ResourceID] | None = Field(None, max_length=1000, json_schema_extra={"ui:widget": "list"})
    events: list[WebhookEvent] | None = Field(None, max_length=9)
    enabled: bool | None = Field(None, strict=True)

    @field_validator("url")
    @classmethod
    def url_value(cls, value):
        return _url(value)

    @model_validator(mode="after")
    def patch_present(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "workspace_id", "webhook_id"}):
            raise ValueError("Choose at least one webhook field to update")
        return self


class DeleteWebhook(_Webhook):
    """Remove the selected webhook subscription."""
    operation: Literal["delete_webhook"] = "delete_webhook"


class GetDynamicCampaign(_Dynamic):
    operation: Literal["get_dynamic_campaign"] = "get_dynamic_campaign"


class GetDynamicSettings(_Workspace):
    operation: Literal["get_dynamic_settings"] = "get_dynamic_settings"


class CreateDynamicCampaign(_Workspace):
    """Create a campaign using Sendspark's v2 campaign setup endpoint."""
    operation: Literal["create_dynamic_campaign"] = "create_dynamic_campaign"
    name: Text
    voice_cloning: bool | None = Field(None, alias="voiceCloning", strict=True)
    language_code: Text | None = Field(None, alias="languageCode")
    video_url: str | None = Field(None, alias="videoUrl", max_length=8192)
    version: float | None = Field(None, allow_inf_nan=False)
    multivariable: bool | None = Field(None, strict=True)

    @field_validator("video_url")
    @classmethod
    def url_value(cls, value):
        return _url(value)


class UpdateDynamicCampaign(_Dynamic):
    """Update the campaign's name and share page copy without processing prospects."""
    operation: Literal["update_dynamic_campaign"] = "update_dynamic_campaign"
    name: Text | None = None
    title: Text | None = None
    message: str | None = Field(None, max_length=10000)
    video_url: str | None = Field(None, alias="videoUrl", max_length=8192)

    @field_validator("video_url")
    @classmethod
    def url_value(cls, value):
        return _url(value)

    @model_validator(mode="after")
    def patch_present(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "workspace_id", "dynamic_id"}):
            raise ValueError("Choose at least one campaign field to update")
        return self


class GetProspect(_Dynamic):
    operation: Literal["get_prospect"] = "get_prospect"
    contact_email: str = Field(..., min_length=3, max_length=254, title="Contact email")
    include: str | None = Field(None, pattern=r"^(emailEmbedHTML|fields)(,(emailEmbedHTML|fields))*$")

    @field_validator("contact_email")
    @classmethod
    def email(cls, value):
        if not re.fullmatch(r"[^\s@/]+@[^\s@/]+\.[^\s@/]+", value):
            raise ValueError("Enter a valid contact email")
        return value


class Prospect(_Input):
    contact_email: str = Field(..., alias="contactEmail", min_length=3, max_length=254)
    contact_name: Text | None = Field(None, alias="contactName")
    company: Text | None = None
    job_title: Text | None = Field(None, alias="jobTitle")
    custom_field: Text | None = Field(None, alias="customField")
    background_url: str | None = Field(None, alias="backgroundUrl", max_length=8192)
    original_background_url: str | None = Field(None, alias="originalBackgroundUrl", max_length=8192)
    screenshot_url: str | None = Field(None, alias="screenshotUrl", max_length=8192)
    webhook_url: str | None = Field(None, alias="webhookUrl", max_length=8192)
    webhook_events: list[WebhookEvent] | None = Field(None, alias="webhookEvents", max_length=9)
    audio_url: str | None = Field(None, alias="audioUrl", max_length=8192)
    fields: dict[str, str] | None = Field(None, json_schema_extra={"ui:widget": "state_editor"}, description="Custom fields as a JSON object with string values.")

    @field_validator("contact_email")
    @classmethod
    def email(cls, value):
        return GetProspect.email(value)

    @field_validator("background_url", "original_background_url", "screenshot_url", "webhook_url", "audio_url")
    @classmethod
    def url_value(cls, value):
        return _url(value)


class _ProcessOptions(_Dynamic):
    process_and_authorize_charge: bool = Field(..., alias="processAndAuthorizeCharge", strict=True,
        description="Must be true: generate prospect videos and authorize Sendspark's usage charges above your plan limit.")
    callback_id: Text | None = Field(None, alias="callbackId")

    @field_validator("process_and_authorize_charge")
    @classmethod
    def authorize_charge(cls, value):
        if value is not True:
            raise ValueError("Sendspark requires explicit authorization of video generation charges")
        return value


class AddProspect(_ProcessOptions):
    """Add a prospect and generate their video with explicitly authorized usage charges."""
    operation: Literal["add_prospect"] = "add_prospect"
    prospect: Prospect
    fallback_to_email_domain_for_background: bool | None = Field(None, alias="fallbackToEmailDomainForBackground", strict=True)


class BulkAddProspects(_ProcessOptions):
    """Add prospects and generate their videos with explicitly authorized usage charges."""
    operation: Literal["bulk_add_prospects"] = "bulk_add_prospects"
    prospect_list: list[Prospect] = Field(..., alias="prospectList", min_length=1, max_length=10000,
        description="A JSON array of prospect objects, each with a contactEmail.",
        json_schema_extra={"ui:widget": "state_editor", "placeholder": '[{"contactEmail": "johndoe@example.com", "contactName": "John Doe"}]'})


class UpdateDynamicSettings(_Dynamic):
    operation: Literal["update_dynamic_settings"] = "update_dynamic_settings"
    use_fallback_data: bool = Field(..., alias="useFallbackData", strict=True)


class UpdateProspectBackgroundURLs(_Dynamic):
    """Set or remove prospect background URLs derived from their email domains."""
    operation: Literal["update_prospect_background_urls"] = "update_prospect_background_urls"
    extract_url_from_email: bool = Field(..., alias="extractUrlFromEmail", strict=True)


class _Campaign(_Workspace):
    campaign_id: ResourceID = Field(..., title="Campaign ID")


class GetCampaignTranscript(_Campaign):
    """Read a campaign transcript as JSON, including timed segments."""
    operation: Literal["get_campaign_transcript"] = "get_campaign_transcript"


class GetCampaignTranscriptStatus(_Campaign):
    operation: Literal["get_campaign_transcript_status"] = "get_campaign_transcript_status"


SendsparkConfig = Annotated[Union[ListWorkspaces, GetWorkspaceIdentifier, ListWebhooks, GetWebhook,
    CreateWebhook, UpdateWebhook, DeleteWebhook, GetDynamicCampaign, GetDynamicSettings, CreateDynamicCampaign,
    UpdateDynamicCampaign, GetProspect, AddProspect, BulkAddProspects, UpdateDynamicSettings,
    UpdateProspectBackgroundURLs, GetCampaignTranscript, GetCampaignTranscriptStatus], Field(discriminator="operation")]


class SendsparkFullConfig(NodeConfig[SendsparkConfig, SendsparkAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {
    "list_workspaces": ("GET", "/v1/workspaces"),
    "get_workspace_identifier": ("GET", "/v1/workspaces/identifier"),
    "list_webhooks": ("GET", "/v1/workspaces/{workspace_id}/webhooks"),
    "get_webhook": ("GET", "/v1/workspaces/{workspace_id}/webhooks/{webhook_id}"),
    "create_webhook": ("POST", "/v1/workspaces/{workspace_id}/webhooks"),
    "update_webhook": ("PATCH", "/v1/workspaces/{workspace_id}/webhooks/{webhook_id}"),
    "delete_webhook": ("DELETE", "/v1/workspaces/{workspace_id}/webhooks/{webhook_id}"),
    "get_dynamic_campaign": ("GET", "/v1/workspaces/{workspace_id}/dynamics/{dynamic_id}"),
    "get_dynamic_settings": ("GET", "/v1/workspaces/{workspace_id}/dynamics/settings"),
    "create_dynamic_campaign": ("POST", "/v2/workspaces/{workspace_id}/dynamics"),
    "update_dynamic_campaign": ("PATCH", "/v2/workspaces/{workspace_id}/dynamics/{dynamic_id}"),
    "get_prospect": ("GET", "/v1/workspaces/{workspace_id}/dynamics/{dynamic_id}/prospects/{contact_email}"),
    "add_prospect": ("POST", "/v1/workspaces/{workspace_id}/dynamics/{dynamic_id}/prospect"),
    "bulk_add_prospects": ("POST", "/v1/workspaces/{workspace_id}/dynamics/{dynamic_id}/prospects/bulk"),
    "update_dynamic_settings": ("PATCH", "/v1/workspaces/{workspace_id}/dynamics/{dynamic_id}/settings"),
    "update_prospect_background_urls": ("PATCH", "/v1/workspaces/{workspace_id}/dynamics/{dynamic_id}/prospects/urls/bulk"),
    "get_campaign_transcript": ("GET", "/v1/workspaces/{workspace_id}/campaigns/{campaign_id}/transcript"),
    "get_campaign_transcript_status": ("GET", "/v1/workspaces/{workspace_id}/campaigns/{campaign_id}/transcript/status"),
}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secrets): _redact(item, secrets) for key, item in value.items()}
    return value


class SendsparkNode(WorkflowNode):
    integration_type = "automation-sendspark"
    connection_evidence = ConnectionEvidence(noun="Sendspark workspace", identity_operation="get_workspace_identifier", identity_keys=("workspaceId",))

    @classmethod
    def get_config_model(cls):
        return SendsparkFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, SendsparkFullConfig) or not self.config.credentials:
            raise ValueError("Attach a Sendspark API key and API secret")
        config, credential = self.config.config, self.config.credentials
        method, template = ROUTES[config.operation]
        path_fields = re.findall(r"\{(\w+)\}", template)
        path = template.format(**{field: quote(getattr(config, field), safe="") for field in path_fields})
        values = config.model_dump(by_alias=True, exclude_none=True, exclude={"operation", *path_fields})
        kwargs = {}
        if method == "GET":
            if config.operation == "get_campaign_transcript":
                values["format"] = "json"
            if values:
                kwargs["params"] = {key: str(value).lower() if type(value) is bool else value for key, value in values.items()}
        elif method in {"POST", "PATCH"}:
            kwargs["json"] = values
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, headers={
                "x-api-key": credential.api_key, "x-api-secret": credential.api_secret,
                "Accept": "application/json"}, **kwargs)
        secrets = (credential.api_key, credential.api_secret)
        if len(response.content) > 10_000_000:
            raise ValueError("Sendspark response exceeds the size limit")
        if response.status_code == 204:
            if config.operation not in {"list_webhooks", "get_webhook", "delete_webhook"}:
                raise ValueError("Sendspark returned an empty response for an operation that requires JSON")
            return {"status": "success", "operation": config.operation, "http_status": 204, "data": None}
        if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Expected a JSON response from Sendspark")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Sendspark returned invalid JSON") from None
        if not isinstance(body, (dict, list)):
            raise ValueError("Sendspark returned an unexpected response envelope")
        if response.status_code >= 300 or (isinstance(body, dict) and (body.get("error") or body.get("errors") or body.get("success") is False)):
            message = (body.get("message") or body.get("error") or body.get("errors")) if isinstance(body, dict) else None
            return {"status": "error", "http_status": response.status_code, "status_code": response.status_code,
                "error": _redact(message or "Sendspark rejected the request", secrets)}
        if not 200 <= response.status_code < 300:
            raise ValueError("Sendspark did not confirm the operation")
        if config.operation == "get_workspace_identifier" and (not isinstance(body, dict) or not isinstance(body.get("workspaceId"), str) or not body["workspaceId"].strip()):
            raise ValueError("Sendspark did not return a workspace identity")
        return _redact({"status": "success", "operation": config.operation,
            "http_status": response.status_code, "data": body}, secrets)
