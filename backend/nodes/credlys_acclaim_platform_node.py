"""Credly v1 badge automation using organization authorization tokens.

Each operation sends one documented request; callers control pagination and
writes are never retried. Credential evidence lists this token's organizations.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class CredlyTokenCredential(BaseModel):
    model_config = ConfigDict(title="Credly Authorization Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.credly.com/browse/docs/authentication-methods",
            "x-credential-instructions": "In Credly Organization Management, open Developers and copy an authorization token. Paste the token here. NoClick sends it as the HTTP Basic username with a blank password to api.credly.com. Tokens expire after 180 days by default; replace an expired token here. Write operations need a token with write permissions.",
        })
    credential_type: Literal["credly_api_token"] = Field("credly_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Authorization token", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Authorization token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 or c == ":" for c in value):
            raise ValueError("Paste only the authorization token, without a Basic prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Organization(_Input):
    organization_id: UUID = Field(..., title="Organization ID", description="UUID from List Organizations.")


class _Template(_Organization):
    badge_template_id: UUID = Field(..., title="Badge template ID")


class _Badge(_Organization):
    badge_id: UUID = Field(..., title="Badge ID")


class ListOrganizations(_Input):
    """List organizations accessible to the authorization token."""
    operation: Literal["list_organizations"] = Field("list_organizations", json_schema_extra={"ui:hidden": True})


class GetOrganization(_Organization):
    """Get an organization's profile."""
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"ui:hidden": True})


class UpdateOrganization(_Organization):
    """Update the organization's display name and optional public profile."""
    operation: Literal["update_organization"] = Field("update_organization", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=10000)
    website_url: str | None = Field(None, pattern=r"^https?://[^\s]+$", max_length=2048)


class ListBadgeTemplates(_Organization):
    """Read one page of badge templates. Increment page for further results."""
    operation: Literal["list_badge_templates"] = Field("list_badge_templates", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    per: int = Field(20, ge=1, le=50)
    name: str | None = Field(None, description="Partial template name match.", min_length=1, max_length=255)
    state: Literal["active", "draft", "archived"] | None = None


class GetBadgeTemplate(_Template):
    """Get one badge template."""
    operation: Literal["get_badge_template"] = Field("get_badge_template", json_schema_extra={"ui:hidden": True})


class DeleteBadgeTemplate(_Template):
    """Permanently delete a badge template; Credly rejects templates with children."""
    operation: Literal["delete_badge_template"] = Field("delete_badge_template", json_schema_extra={"ui:hidden": True})


class Activity(_Input):
    activity_type: Literal["Application", "Assessment", "Award", "Badge", "Course", "Credential", "Education Experience", "Leadership", "Member", "Other", "Participant", "Payment", "Portfolio", "Presenter", "Project", "Professional Experience", "Schedule / Registration", "Volunteer"]
    title: str = Field(..., min_length=1, max_length=500)
    activity_url: str | None = Field(None, pattern=r"^https?://[^\s]+$", max_length=255)
    required_badge_template_id: UUID | None = None


class TemplateImage(_Input):
    remote_upload_url: str = Field(..., pattern=r"^https?://[^\s]+$", max_length=2048,
        description="Public PNG URL, at least 600 by 600 pixels. Credly fetches the image.")


class CreateBadgeTemplate(_Organization):
    """Create a badge template with criteria, skills and an image URL."""
    operation: Literal["create_badge_template"] = Field("create_badge_template", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1, max_length=500)
    badge_template_activities: list[Activity] = Field(..., min_length=1, max_length=100)
    image: TemplateImage
    global_activity_url: str = Field(..., pattern=r"^https?://[^\s]+$", max_length=255)
    skills: list[str] = Field(..., min_length=3, max_length=100)
    state: Literal["active", "draft", "archived"] | None = None
    reporting_tags: list[str] | None = None
    allow_duplicate_badges: bool | None = None


class UpdateBadgeTemplate(_Template):
    """Update a template's name and selected template settings."""
    operation: Literal["update_badge_template"] = Field("update_badge_template", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, min_length=1, max_length=500)
    badge_template_activities: list[Activity] | None = Field(None, min_length=1, max_length=100)
    image: TemplateImage | None = None
    skills: list[str] | None = Field(None, min_length=3, max_length=100)
    state: Literal["active", "draft", "archived"] | None = None
    reporting_tags: list[str] | None = None
    allow_duplicate_badges: bool | None = None


class ListIssuedBadges(_Organization):
    """Read one page of issued badges with optional recipient and state filters."""
    operation: Literal["list_issued_badges"] = Field("list_issued_badges", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    per: int = Field(20, ge=1, le=50)
    recipient_email: str | None = Field(None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)
    badge_template_id: UUID | None = None
    state: Literal["accepted", "rejected", "revoked", "pending", "replaced"] | None = None


class GetIssuedBadge(_Badge):
    """Read one issued badge."""
    operation: Literal["get_issued_badge"] = Field("get_issued_badge", json_schema_extra={"ui:hidden": True})


class DeleteIssuedBadge(_Badge):
    """Permanently delete an issued badge."""
    operation: Literal["delete_issued_badge"] = Field("delete_issued_badge", json_schema_extra={"ui:hidden": True})


class _Issuance(_Organization):
    badge_template_id: UUID
    issued_at: AwareDatetime = Field(..., description="Date and time the earner earned the badge, with time zone.")
    issued_to_first_name: str = Field(..., min_length=1, max_length=255)
    issued_to_last_name: str = Field(..., min_length=1, max_length=255)
    expires_at: AwareDatetime | None = None
    issuer_earner_id: str | None = Field(None, max_length=1024)
    issued_to_middle_name: str | None = Field(None, max_length=255)


class IssueBadge(_Issuance):
    """Issue a badge; Credly normally sends an earner notification."""
    operation: Literal["issue_badge"] = Field("issue_badge", json_schema_extra={"ui:hidden": True})
    recipient_email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)
    suppress_badge_notification_email: bool | None = None


class ReplaceBadge(_Issuance):
    """Replace a badge with corrected fields; an optional message notifies the earner."""
    operation: Literal["replace_badge"] = Field("replace_badge", json_schema_extra={"ui:hidden": True})
    badge_id: UUID
    notification_message: str | None = Field(None, max_length=10000)


class RevokeBadge(_Badge):
    """Revoke a badge and record the reason; optionally suppress notification."""
    operation: Literal["revoke_badge"] = Field("revoke_badge", json_schema_extra={"ui:hidden": True})
    reason: str = Field(..., min_length=1, max_length=10000)
    suppress_revoke_notification_email: bool | None = None


CredlyOperation = Annotated[Union[ListOrganizations, GetOrganization, UpdateOrganization,
    ListBadgeTemplates, GetBadgeTemplate, CreateBadgeTemplate, UpdateBadgeTemplate, DeleteBadgeTemplate,
    ListIssuedBadges, GetIssuedBadge, IssueBadge, ReplaceBadge, RevokeBadge, DeleteIssuedBadge], Field(discriminator="operation")]


class CredlyConfig(NodeConfig[CredlyOperation, CredlyTokenCredential]):
    pass


ORG = "/v1/organizations/{organization_id}"
ROUTES = {
    "list_organizations": ("GET", "/v1/organizations"),
    "get_organization": ("GET", ORG),
    "update_organization": ("PUT", ORG),
    "list_badge_templates": ("GET", ORG + "/badge_templates"),
    "get_badge_template": ("GET", ORG + "/badge_templates/{badge_template_id}"),
    "create_badge_template": ("POST", ORG + "/badge_templates"),
    "update_badge_template": ("PUT", ORG + "/badge_templates/{badge_template_id}"),
    "delete_badge_template": ("DELETE", ORG + "/badge_templates/{badge_template_id}"),
    "list_issued_badges": ("GET", ORG + "/badges"),
    "get_issued_badge": ("GET", ORG + "/badges/{badge_id}"),
    "issue_badge": ("POST", ORG + "/badges"),
    "replace_badge": ("POST", ORG + "/badges/{badge_id}/replace"),
    "revoke_badge": ("PUT", ORG + "/badges/{badge_id}/revoke"),
    "delete_issued_badge": ("DELETE", ORG + "/badges/{badge_id}"),
}


class CredlysAcclaimPlatformNode(WorkflowNode):
    integration_type = "automation-credlys-acclaim-platform"
    connection_evidence = ConnectionEvidence(noun="organizations", operation="list_organizations")

    @classmethod
    def get_config_model(cls):
        return CredlyConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Credly authorization token")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for key in ("organization_id", "badge_template_id", "badge_id"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", values.pop(key))
        if config.operation.startswith("list_"):
            for key in tuple(values):
                if key not in {"page", "per"}:
                    values["filter[" + key + "]"] = values.pop(key)
        kwargs = {"json": values} if method in {"POST", "PUT"} else {"params": values}
        token = self.config.credentials.api_token
        auth = httpx.BasicAuth(token, "")
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://api.credly.com" + path,
                    auth=auth, headers={"Accept": "application/json"}, **kwargs)
        except httpx.HTTPError:
            raise ValueError("Credly request could not be confirmed; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            try:
                message = response.json()["data"]["message"]
            except (ValueError, KeyError, TypeError):
                message = "Credly rejected the request"
            message = str(message).replace(response.request.headers.get("Authorization", token), "[redacted]").replace(token, "[redacted]")
            raise ValueError(f"Credly HTTP {response.status_code}: {message}")
        if response.status_code == 204 or (config.operation == "replace_badge" and not response.content):
            output = {"http_status": response.status_code, "acknowledged": True}
            if config.operation == "replace_badge" and response.headers.get("Location"):
                output["location"] = response.headers["Location"]
        else:
            try:
                output = response.json()
            except ValueError:
                raise ValueError("Credly returned an invalid JSON response") from None
            if not isinstance(output, dict) or "data" not in output or "error" in output:
                raise ValueError("Credly returned an unexpected response")
        await self.emit(output)
        return output
