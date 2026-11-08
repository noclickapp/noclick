"""Raisely v3 fundraising and supporter automation.

Contract: https://api.raisely.com/v3/api-docs (version 3.0).
Every operation issues one documented request; list operations return one page.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.raisely.com/v3"


class RaiselyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Raisely API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.raisely.com/reference/getauthenticate",
            "x-credential-instructions": "Paste an existing Raisely API key with access to the campaigns and records you want to automate. NoClick sends it as a Bearer token to api.raisely.com and verifies it with the read-only authenticate endpoint.",
        },
    )
    credential_type: Literal["raisely_api_key"] = Field("raisely_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_segment(cls, value, info):
        if value is not None and info.field_name in {"campaign", "user_id", "donation_id", "profile_path", "subscription_id", "tag_id", "record_id"}:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", value) or value in {".", ".."}:
                raise ValueError("Use a single Raisely resource ID or path")
        return value


class _Page(_Input):
    limit: int = Field(50, ge=1, le=100, description="Records in this page; use next_offset for the following page.")
    offset: int = Field(0, ge=0, le=10000000)
    q: Optional[str] = Field(None, max_length=500, title="Search")
    private: StrictBool = Field(True, description="Request full authenticated records; requires the corresponding key permissions.")


class CheckConnection(_Input):
    """Check connection."""
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra={"ui:hidden": True})


class ListCampaigns(_Page):
    """List campaigns."""
    operation: Literal["list_campaigns"] = Field("list_campaigns", json_schema_extra={"ui:hidden": True})


class GetCampaign(_Input):
    """Get campaign."""
    operation: Literal["get_campaign"] = Field("get_campaign", json_schema_extra={"ui:hidden": True})
    campaign: str
    private: StrictBool = True


class ListUsers(_Page):
    """List users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    email: Optional[str] = None


class GetUser(_Input):
    """Get user."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    user_id: str
    private: StrictBool = True


class _UserFields(_Input):
    email: Optional[str] = Field(None, max_length=320)
    first_name: Optional[str] = Field(None, max_length=500)
    last_name: Optional[str] = Field(None, max_length=500)
    full_name: Optional[str] = Field(None, max_length=1000)
    phone_number: Optional[str] = Field(None, max_length=100)
    preferred_name: Optional[str] = Field(None, max_length=500)


class CreateUser(_UserFields):
    """Create user."""
    operation: Literal["create_user"] = Field("create_user", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=3, max_length=320)


class UpdateUser(_UserFields):
    """Update user."""
    operation: Literal["update_user"] = Field("update_user", json_schema_extra={"ui:hidden": True})
    user_id: str


class UpsertUser(_UserFields):
    """Upsert user."""
    operation: Literal["upsert_user"] = Field("upsert_user", json_schema_extra={"ui:hidden": True})
    campaign: str
    email: str = Field(..., min_length=3, max_length=320)


class ListDonations(_Page):
    """List donations."""
    operation: Literal["list_donations"] = Field("list_donations", json_schema_extra={"ui:hidden": True})
    campaign: Optional[str] = None
    user: Optional[str] = None
    status: Optional[str] = None


class GetDonation(_Input):
    """Get donation."""
    operation: Literal["get_donation"] = Field("get_donation", json_schema_extra={"ui:hidden": True})
    donation_id: str


class UpdateDonation(_Input):
    """Update donation."""
    operation: Literal["update_donation"] = Field("update_donation", json_schema_extra={"ui:hidden": True})
    donation_id: str
    message: Optional[str] = Field(None, max_length=10000)
    anonymous: Optional[StrictBool] = None
    preferred_name: Optional[str] = Field(None, max_length=500)


class ListProfiles(_Page):
    """List profiles."""
    operation: Literal["list_profiles"] = Field("list_profiles", json_schema_extra={"ui:hidden": True})
    campaign: str


class GetProfile(_Input):
    """Get profile."""
    operation: Literal["get_profile"] = Field("get_profile", json_schema_extra={"ui:hidden": True})
    profile_path: str
    campaign: Optional[str] = None
    private: StrictBool = True


class UpdateProfile(_Input):
    """Update profile."""
    operation: Literal["update_profile"] = Field("update_profile", json_schema_extra={"ui:hidden": True})
    profile_path: str
    campaign: Optional[str] = None
    name: Optional[str] = Field(None, max_length=1000)
    description: Optional[str] = Field(None, max_length=10000)
    goal: Optional[int] = Field(None, ge=0, description="Fundraising goal in cents.")


class ListSubscriptions(_Page):
    """List subscriptions."""
    operation: Literal["list_subscriptions"] = Field("list_subscriptions", json_schema_extra={"ui:hidden": True})
    campaign: Optional[str] = None
    user: Optional[str] = None
    status: Optional[str] = None


class GetSubscription(_Input):
    """Get subscription."""
    operation: Literal["get_subscription"] = Field("get_subscription", json_schema_extra={"ui:hidden": True})
    subscription_id: str
    private: StrictBool = True


class ListTags(_Page):
    """List tags."""
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})
    record_type: Optional[str] = Field(None, description="Record type accepted by Raisely, for example user.")


class GetTag(_Input):
    """Get tag."""
    operation: Literal["get_tag"] = Field("get_tag", json_schema_extra={"ui:hidden": True})
    tag_id: str
    private: StrictBool = True


class AddTagRecord(_Input):
    """Add tag record."""
    operation: Literal["add_tag_record"] = Field("add_tag_record", json_schema_extra={"ui:hidden": True})
    tag_id: str
    record_id: str


class RemoveTagRecord(_Input):
    """Remove tag record."""
    operation: Literal["remove_tag_record"] = Field("remove_tag_record", json_schema_extra={"ui:hidden": True})
    tag_id: str
    record_id: str


class ListCampaignProfiles(_Page):
    """List campaign profiles."""
    operation: Literal["list_campaign_profiles"] = Field("list_campaign_profiles", json_schema_extra={"ui:hidden": True})
    campaign: str


class ListCampaignDonations(_Page):
    """List campaign donations."""
    operation: Literal["list_campaign_donations"] = Field("list_campaign_donations", json_schema_extra={"ui:hidden": True})
    campaign: str


RaiselyConfig = Annotated[Union[
    CheckConnection, ListCampaigns, GetCampaign, ListUsers, GetUser, CreateUser, UpdateUser, UpsertUser, ListDonations, GetDonation, UpdateDonation, ListProfiles, GetProfile, UpdateProfile, ListSubscriptions, GetSubscription, ListTags, GetTag, AddTagRecord, RemoveTagRecord, ListCampaignProfiles, ListCampaignDonations
], Field(discriminator="operation")]


class RaiselyFullConfig(NodeConfig[RaiselyConfig, RaiselyAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


OPERATIONS = {
    'check_connection': ('GET', '/authenticate', (), None),
    'list_campaigns': ('GET', '/campaigns', ('q', 'limit', 'offset', 'private'), None),
    'get_campaign': ('GET', '/campaigns/{campaign}', ('private',), None),
    'list_users': ('GET', '/users', ('q', 'limit', 'offset', 'private', 'email'), None),
    'get_user': ('GET', '/users/{user_id}', ('private',), None),
    'create_user': ('POST', '/users', (), 'user'),
    'update_user': ('PATCH', '/users/{user_id}', (), 'user'),
    'upsert_user': ('POST', '/users/upsert', ('campaign',), 'user'),
    'list_donations': ('GET', '/donations', ('q', 'limit', 'offset', 'private', 'campaign', 'user', 'status'), None),
    'get_donation': ('GET', '/donations/{donation_id}', (), None),
    'update_donation': ('PATCH', '/donations/{donation_id}', (), 'donation'),
    'list_profiles': ('GET', '/profiles', ('q', 'limit', 'offset', 'private', 'campaign'), None),
    'get_profile': ('GET', '/profiles/{profile_path}', ('campaign', 'private'), None),
    'update_profile': ('PATCH', '/profiles/{profile_path}', ('campaign',), 'profile'),
    'list_subscriptions': ('GET', '/subscriptions', ('q', 'limit', 'offset', 'private', 'campaign', 'user', 'status'), None),
    'get_subscription': ('GET', '/subscriptions/{subscription_id}', ('private',), None),
    'list_tags': ('GET', '/tags', ('q', 'limit', 'offset', 'private', 'record_type'), None),
    'get_tag': ('GET', '/tags/{tag_id}', ('private',), None),
    'add_tag_record': ('POST', '/tags/{tag_id}/records', (), 'tag'),
    'remove_tag_record': ('DELETE', '/tags/{tag_id}/records/{record_id}', (), None),
    'list_campaign_profiles': ('GET', '/campaigns/{campaign}/profiles', ('q', 'limit', 'offset', 'private'), None),
    'list_campaign_donations': ('GET', '/campaigns/{campaign}/donations', ('q', 'limit', 'offset', 'private'), None),
}

BODY_FIELDS = {
    "user": {"email": "email", "first_name": "firstName", "last_name": "lastName", "full_name": "fullName", "phone_number": "phoneNumber", "preferred_name": "preferredName"},
    "donation": {"message": "message", "anonymous": "anonymous", "preferred_name": "preferredName"},
    "profile": {"name": "name", "description": "description", "goal": "goal"},
}


def _redact(value, secret):
    """User responses may contain accessToken: never emit credential material."""
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()
                if not any(word in re.sub(r"[^a-z]", "", k.lower()) for word in ("token", "password", "secret", "apikey"))}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value.replace(secret, "[redacted]") if isinstance(value, str) else value


class RaiselyNode(WorkflowNode):
    integration_type = "automation-raisely"
    connection_evidence = ConnectionEvidence(
        noun="Raisely account", identity_operation="check_connection",
        identity_keys=("fullName", "email", "organisationUuid", "uuid"),
    )

    @classmethod
    def get_config_model(cls):
        return RaiselyFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Raisely API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        method, route, query_fields, body_kind = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True)
        for key, value in values.items():
            route = route.replace("{" + key + "}", quote(str(value), safe=""))
        params = {("recordType" if key == "record_type" else key): values[key]
                  for key in query_fields if key in values}
        body = None
        if body_kind == "tag":
            body = {"data": [{"uuid": op.record_id}]}
        elif body_kind:
            data = {target: values[source] for source, target in BODY_FIELDS[body_kind].items() if source in values}
            if not data:
                raise ValueError("Provide at least one field to update")
            body = {"data": data}
        headers = {"Authorization": "Bearer " + secret, "Accept": "application/json"}
        kwargs = {"headers": headers, "params": params}
        if body is not None:
            kwargs["json"] = body
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + route, **kwargs)
        if not 200 <= response.status_code < 300:
            # Preserve the provider's rejection text for connection evidence, redacted.
            text = response.text[:4000]
            raise ValueError(f"Raisely HTTP {response.status_code}: " + _redact(text, secret))
        if len(response.content) > 10000000:
            raise ValueError("Raisely response exceeded the JSON size limit")
        payload = response.json()
        if not isinstance(payload, dict) or "data" not in payload or payload.get("error") or payload.get("errors"):
            raise ValueError("Raisely returned an unexpected response envelope")
        data = payload["data"]
        list_result = op.operation.startswith("list_") or op.operation in {"add_tag_record", "remove_tag_record"}
        if not isinstance(data, list if list_result else dict):
            raise ValueError("Raisely returned an unexpected data shape")
        result = {"operation": op.operation, "data": _redact(data, secret)}
        if op.operation.startswith("list_"):
            pagination = payload.get("pagination")
            if not isinstance(pagination, dict):
                raise ValueError("Raisely response is missing pagination")
            # Never follow response URLs: callers advance the documented offset.
            has_more = bool(pagination.get("nextUrl"))
            result.update(pagination=_redact(pagination, secret), has_more=has_more,
                          next_offset=op.offset + op.limit if has_more else None)
        return result
