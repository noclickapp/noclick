"""VolunteerHub Public API 1.0.0: one documented request per operation.

REST authentication: https://support.volunteerhub.com/support/solutions/articles/60000610783-introduction-to-the-volunteerhub-api
Endpoint semantics: https://support.volunteerhub.com/support/solutions/articles/60000610784-endpoints
Contract: https://sandbox.volunteerhub.com/api/v2/openapi.json
"""
from __future__ import annotations

import base64
from datetime import datetime
from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, normalize_provider_https_origin


class VolunteerHubBasicCredential(BaseModel):
    model_config = ConfigDict(title="VolunteerHub Account", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://support.volunteerhub.com/support/solutions/articles/60000610783-introduction-to-the-volunteerhub-api",
            "x-credential-instructions": "Enter your VolunteerHub site address and an existing Superuser's username and password. VolunteerHub's REST API uses HTTP Basic authentication over HTTPS. Its API guide requires a username and a password shorter than 16 characters. The account must have permission for the selected operation; donations also require Volunteer Fundraising."
        })
    credential_type: Literal["volunteerhub_basic"] = Field("volunteerhub_basic", json_schema_extra={"ui:hidden": True})
    site_url: str = Field(..., title="Site address", description="Your site subdomain or HTTPS address, such as https://myorganization.volunteerhub.com.")
    username: str = Field(..., min_length=1, max_length=256, title="Username")
    password: str = Field(..., min_length=1, max_length=4096, title="Password", json_schema_extra={"ui:widget": "password"})

    @field_validator("site_url", mode="before")
    @classmethod
    def site(cls, value):
        return normalize_provider_https_origin(value, "volunteerhub.com", field_name="Site address")

    @field_validator("username")
    @classmethod
    def user(cls, value):
        if ":" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Enter a username without a colon or control characters")
        return value

    @field_validator("password", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="Password")
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Enter a password without control characters")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(Input):
    page: int = Field(0, strict=True, ge=0, le=2_147_483_647, description="Zero-based page number. Each run reads one page.")
    page_size: int = Field(50, strict=True, ge=1, le=50, description="Maximum 50 records per page.")


class ListDonations(Page):
    """Read donations for selected users (Volunteer Fundraising required)."""
    operation: Literal["list_donations"] = Field("list_donations", json_schema_extra={"ui:hidden": True})
    query: Literal["UserUids"] = Field("UserUids", json_schema_extra={"ui:hidden": True})
    uids: list[UUID] = Field(..., min_length=1, max_length=100, title="User IDs")


class ListEventGroups(Page):
    """Read event groups in hierarchical order."""
    operation: Literal["list_event_groups"] = Field("list_event_groups", json_schema_extra={"ui:hidden": True})
    query: Literal["Hierarchical"] = Field("Hierarchical", json_schema_extra={"ui:hidden": True})


class ListEvents(Page):
    """Read events by version or time window."""
    operation: Literal["list_events"] = Field("list_events", json_schema_extra={"ui:hidden": True})
    query: Literal["Version", "Time"] = "Version"
    earliest_version: int | None = Field(0, strict=True, ge=0, le=18_446_744_073_709_551_615, description="Required for a Version query; events with a greater version are returned.")
    earliest_time: datetime | None = Field(None, description="Required for a Time query; include events ending on or after this ISO 8601 time.")
    latest_time: datetime | None = Field(None, description="Optional exclusive upper bound on event start time.")

    @model_validator(mode="after")
    def query_fields(self):
        if self.query == "Version" and self.earliest_version is None:
            raise ValueError("Version queries require earliest_version")
        if self.query == "Time" and self.earliest_time is None:
            raise ValueError("Time queries require earliest_time")
        return self


class GetEvent(Input):
    """Read an event by its unique ID, including registrations and hours."""
    operation: Literal["get_event"] = Field("get_event", json_schema_extra={"ui:hidden": True})
    event_id: UUID


class GetOrganization(Input):
    """Read the connected organization's name, forms and configuration."""
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"ui:hidden": True})


class ListUserGroups(Page):
    """Read user groups in hierarchical order."""
    operation: Literal["list_user_groups"] = Field("list_user_groups", json_schema_extra={"ui:hidden": True})
    query: Literal["Hierarchical"] = Field("Hierarchical", json_schema_extra={"ui:hidden": True})


class ListUsers(Page):
    """Read volunteer profiles by update time or version."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    query: Literal["LastUpdate", "Version"] = "Version"
    earliest_last_update: datetime | None = Field(None, description="Required for LastUpdate queries (ISO 8601).")
    earliest_version: int | None = Field(0, strict=True, ge=0, le=18_446_744_073_709_551_615, description="Required for Version queries; return users with a greater version.")

    @model_validator(mode="after")
    def query_fields(self):
        if self.query == "Version" and self.earliest_version is None:
            raise ValueError("Version queries require earliest_version")
        if self.query == "LastUpdate" and self.earliest_last_update is None:
            raise ValueError("LastUpdate queries require earliest_last_update")
        return self


class GetUser(Input):
    """Read a volunteer's profile, form answers and user group memberships."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    user_id: UUID


class Memberships(Input):
    user_id: UUID
    user_group_uids: list[UUID] = Field(..., min_length=1, max_length=100, title="User group IDs")


class AddUserGroupMemberships(Memberships):
    """Add a user to the selected user groups."""
    operation: Literal["add_user_group_memberships"] = Field("add_user_group_memberships", json_schema_extra={"ui:hidden": True})


class RemoveUserGroupMemberships(Memberships):
    """Remove a user from the selected user groups."""
    operation: Literal["remove_user_group_memberships"] = Field("remove_user_group_memberships", json_schema_extra={"ui:hidden": True})


VolunteerHubConfig = Annotated[Union[ListDonations, ListEventGroups, ListEvents, GetEvent, GetOrganization,
    ListUserGroups, ListUsers, GetUser, AddUserGroupMemberships, RemoveUserGroupMemberships], Field(discriminator="operation")]


class VolunteerHubFullConfig(NodeConfig[VolunteerHubConfig, VolunteerHubBasicCredential]):
    pass


# Every entry maps to exactly one operation in the pinned provider contract.
ROUTES = {
    "list_donations": ("GET", "/api/v1/Donations"),
    "list_event_groups": ("GET", "/api/v1/EventGroups"),
    "list_events": ("GET", "/api/v1/Events"),
    "get_event": ("GET", "/api/v1/Events/{event_id}"),
    "get_organization": ("GET", "/api/v1/Organization"),
    "list_user_groups": ("GET", "/api/v1/UserGroups"),
    "list_users": ("GET", "/api/v2/Users"),
    "get_user": ("GET", "/api/v2/Users/{user_id}"),
    "add_user_group_memberships": ("POST", "/api/v2/Users/{user_id}/UserGroupMemberships"),
    "remove_user_group_memberships": ("DELETE", "/api/v2/Users/{user_id}/UserGroupMemberships"),
}


class VolunteerHubNode(WorkflowNode):
    integration_type = "automation-volunteerhub"
    connection_evidence = ConnectionEvidence(noun="VolunteerHub organization", identity_operation="get_organization", identity_keys=("Name",))

    @classmethod
    def get_config_model(cls):
        return VolunteerHubFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a VolunteerHub account")
        credential = self.config.credentials
        config = self.config.config
        method, path = ROUTES[config.operation]
        fields = config.model_dump(mode="json", exclude_none=True)
        path = path.format(**fields)
        params = {}
        if isinstance(config, Page):
            params = {"page": config.page, "pageSize": config.page_size, "query": config.query}
        if isinstance(config, ListDonations):
            # OpenAPI's default query array style is form + explode (repeated uids).
            params["uids"] = fields["uids"]
        if isinstance(config, ListEvents):
            if config.query == "Version":
                params["earliestVersion"] = config.earliest_version
            else:
                params["earliestTime"] = fields["earliest_time"]
            if config.latest_time is not None:
                params["latestTime"] = fields["latest_time"]
        if isinstance(config, ListUsers):
            name = "earliestVersion" if config.query == "Version" else "earliestLastUpdate"
            params[name] = config.earliest_version if config.query == "Version" else fields["earliest_last_update"]
        kwargs = {"params": params}
        if isinstance(config, Memberships):
            kwargs["json"] = {"UserGroupUids": fields["user_group_uids"]}
        auth = "Basic " + base64.b64encode((credential.username + ":" + credential.password).encode()).decode()
        origin = normalize_provider_https_origin(credential.site_url, "volunteerhub.com", field_name="Site address")
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, origin + path,
                headers={"Authorization": auth, "Accept": "application/json"}, **kwargs)
        if response.status_code != 200:
            # Preserve provider rejection text for connect, without reflecting credentials.
            detail = "VolunteerHub request failed"
            if "json" in response.headers.get("content-type", ""):
                try:
                    problem = response.json()
                    if isinstance(problem, dict):
                        detail = str(problem.get("detail") or problem.get("title") or detail)
                except ValueError:
                    pass
            for secret in (auth, credential.password, credential.username):
                detail = detail.replace(secret, "[redacted]")
            return {"status": "error", "status_code": response.status_code,
                "http_status": response.status_code, "error": detail[:2000]}
        if "json" not in response.headers.get("content-type", ""):
            raise ValueError("VolunteerHub returned a non-JSON response; check the site address")
        data = response.json()
        if isinstance(config, Page):
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError("VolunteerHub returned an unexpected list response")
            return {"data": data, "page": config.page,
                "next_page": config.page + 1 if len(data) == config.page_size else None}
        if not isinstance(data, dict) or any(k in data for k in ("error", "errors", "detail", "status")):
            raise ValueError("VolunteerHub returned an unexpected object response")
        return {"data": data}
