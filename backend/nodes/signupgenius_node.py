"""SignUpGenius key-based v2 API: one published endpoint per operation.

Contract: https://developer.signupgenius.com/swagger/spec/sug_api_apikey.json
Personal keys are enabled under Tools (https://developer.signupgenius.com/).
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote, quote_plus

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.signupgenius.com/v2/k"
CREDENTIAL_TYPE = "signupgenius_api_key"


class SignUpGeniusAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="SignUpGenius API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.signupgenius.com/",
            "x-credential-instructions": "Enable API access in your SignUpGenius account's Tools section, then paste your private API key. API access requires a Premium subscription and is subject to your plan's daily call limit.",
        },
    )
    credential_type: Literal["signupgenius_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    user_key: str = Field(..., title="API key", min_length=1, max_length=4096,
                          json_schema_extra={"ui:widget": "password"})

    @field_validator("user_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste only the private API key")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class ListGroups(_Operation):
    """List groups created by this account."""
    operation: Literal["list_groups"] = "list_groups"
    sort: Optional[Literal["asc", "desc"]] = None


class _Group(_Operation):
    group_id: int = Field(..., ge=1, le=2147483647, title="Group ID", description="groupid from List Groups.")


class ListGroupMembers(_Group):
    """List the members in a group."""
    operation: Literal["list_group_members"] = "list_group_members"
    sort: Optional[Literal["asc", "desc"]] = None


class GetGroupMember(_Group):
    """Get a group member's details, including supplied address and phone."""
    operation: Literal["get_group_member"] = "get_group_member"
    member_id: int = Field(..., ge=1, le=2147483647, description="memberid from List Group Members.")


class AddGroupMember(_Group):
    """Add a participant to a group using their email address."""
    operation: Literal["add_group_member"] = "add_group_member"
    emailaddress: str = Field(..., title="Email address", min_length=3, max_length=320,
                              pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    firstname: Optional[str] = Field(None, title="First name", max_length=200)
    lastname: Optional[str] = Field(None, title="Last name", max_length=200)


class ListActiveSignups(_Operation):
    """List active sign ups created by this account."""
    operation: Literal["list_active_signups"] = "list_active_signups"


class ListAllSignups(_Operation):
    """List active and expired sign ups created by this account."""
    operation: Literal["list_all_signups"] = "list_all_signups"


class ListExpiredSignups(_Operation):
    """List expired sign ups created by this account."""
    operation: Literal["list_expired_signups"] = "list_expired_signups"


class ListInvitedSignups(_Operation):
    """List active invitations; unavailable to subadmin credentials."""
    operation: Literal["list_invited_signups"] = "list_invited_signups"


class ListJoinedSignups(_Operation):
    """List active sign ups joined by this account; unavailable to subadmins."""
    operation: Literal["list_joined_signups"] = "list_joined_signups"


class _Report(_Operation):
    signup_id: int = Field(..., ge=1, le=2147483647, title="Sign up ID", description="signupid from a created sign up.")


class GetSignupReport(_Report):
    """Read participants and associated details for all slots."""
    operation: Literal["get_signup_report"] = "get_signup_report"


class GetAvailableSlotsReport(_Report):
    """Read report data for empty or available slots."""
    operation: Literal["get_available_slots_report"] = "get_available_slots_report"


class GetFilledSlotsReport(_Report):
    """Read report data for slots already filled."""
    operation: Literal["get_filled_slots_report"] = "get_filled_slots_report"


SignUpGeniusOperation = Annotated[Union[
    ListGroups, ListGroupMembers, GetGroupMember, AddGroupMember,
    ListActiveSignups, ListAllSignups, ListExpiredSignups, ListInvitedSignups,
    ListJoinedSignups, GetSignupReport, GetAvailableSlotsReport, GetFilledSlotsReport,
], Field(discriminator="operation")]


class SignUpGeniusConfig(NodeConfig[SignUpGeniusOperation, SignUpGeniusAPIKeyCredential]):
    pass


ROUTES = {
    "list_groups": ("GET", "/groups/"),
    "list_group_members": ("GET", "/groups/{group_id}/members/"),
    "get_group_member": ("GET", "/groups/{group_id}/members/{member_id}/details/"),
    "add_group_member": ("POST", "/groups/{group_id}/members/create/"),
    "list_active_signups": ("GET", "/signups/created/active/"),
    "list_all_signups": ("GET", "/signups/created/all/"),
    "list_expired_signups": ("GET", "/signups/created/expired/"),
    "list_invited_signups": ("GET", "/signups/invited/active/"),
    "list_joined_signups": ("GET", "/signups/signedupfor/active/"),
    "get_signup_report": ("GET", "/signups/report/all/{signup_id}/"),
    "get_available_slots_report": ("GET", "/signups/report/available/{signup_id}/"),
    "get_filled_slots_report": ("GET", "/signups/report/filled/{signup_id}/"),
}


def _redact(value, key):
    """Provider links and error strings may echo a query-authenticated URL."""
    if isinstance(value, dict):
        return {k: _redact(v, key) for k, v in value.items() if k != "user_key"}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    if isinstance(value, str):
        for secret in sorted({key, quote(key, safe=""), quote_plus(key)}, key=len, reverse=True):
            value = value.replace(secret, "[redacted]")
    return value


def _message(body):
    if isinstance(body, dict):
        value = body.get("message")
        if isinstance(value, list):
            return "; ".join(str(v) for v in value)
        if isinstance(value, str):
            return value
    return body if isinstance(body, str) else "SignUpGenius request was rejected"


class SignUpGeniusNode(WorkflowNode):
    integration_type = "automation-signupgenius"
    connection_evidence = ConnectionEvidence(noun="groups", operation="list_groups", label_keys=("title", "groupid"))

    @classmethod
    def get_config_model(cls):
        return SignUpGeniusConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a SignUpGenius API key")
        config = self.config.config
        key = self.config.credentials.user_key
        method, template = ROUTES[config.operation]
        path = template.format(**config.model_dump())
        params = {"user_key": key}
        if isinstance(config, (ListGroups, ListGroupMembers)) and config.sort is not None:
            params["sort"] = config.sort
        body = None
        if isinstance(config, AddGroupMember):
            body = config.model_dump(include={"emailaddress", "firstname", "lastname"}, exclude_none=True)
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, params=params,
                                                headers={"Accept": "application/json"},
                                                **({"json": body} if body is not None else {}))
        except httpx.TransportError:
            # A timed-out write may have succeeded; do not retry it automatically.
            raise ValueError("SignUpGenius could not be reached; inspect group membership before retrying a write") from None
        if len(response.content) > 10_000_000:
            raise ValueError("SignUpGenius response exceeded the size limit")
        try:
            payload = response.json()
        except ValueError:
            if response.status_code == 200:
                raise ValueError("SignUpGenius returned an unexpected non-JSON response") from None
            # The contract also publishes text/plain authentication errors.
            payload = response.text[:2000]
        if response.status_code != 200 or isinstance(payload, dict) and payload.get("success") is False:
            output = {"status": "error", "success": False, "http_status": response.status_code,
                      "message": _redact(_message(payload), key)}
        else:
            if not isinstance(payload, dict) or payload.get("success") is not True or "data" not in payload:
                raise ValueError("SignUpGenius returned an unexpected response envelope")
            data = payload["data"]
            if isinstance(config, (ListGroups, ListActiveSignups, ListAllSignups, ListExpiredSignups, ListInvitedSignups, ListJoinedSignups)):
                valid = isinstance(data, list) and all(isinstance(row, dict) for row in data)
            elif isinstance(config, ListGroupMembers):
                valid = isinstance(data, dict) and isinstance(data.get("members"), list)
            elif isinstance(config, _Report):
                valid = isinstance(data, dict) and isinstance(data.get("signups"), list)
            else:
                valid = isinstance(data, dict)
            if not valid:
                raise ValueError("SignUpGenius returned an unexpected data shape")
            # links.next is a documented endpoint template, not a pagination cursor.
            # Never follow provider links with a private query-string key.
            output = {"status": "success", "success": True, "data": _redact(data, key),
                      "message": _redact(payload.get("message", []), key), "http_status": response.status_code}
        await self.emit(output)
        return output
