"""Damoov User Service v1, using the provider's published OpenAPI contract.

Paste an existing JWT. Admin operations require an admin JWT; the provider
enforces the token's account and permissions. This node never signs in.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://user.telematicssdk.com"
DOCS = "https://docs.damoov.com/docs/platform-layout-and-authentication"


class TelematicsSDKToken(BaseModel):
    model_config = ConfigDict(title="Telematics SDK JWT", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": DOCS,
            "x-credential-instructions": "Paste an existing Damoov JWT without the Bearer prefix. Use an admin JWT for user searches, counts and instance administration. Tokens expire; replace an expired JWT with one refreshed outside NoClick."})
    credential_type: Literal["telematicssdk_token"] = Field("telematicssdk_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="JWT Access Token", repr=False,
        json_schema_extra={"ui:widget": "password"})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetProfile(_Input):
    """Read the profile belonging to the JWT."""
    operation: Literal["get_profile"] = Field("get_profile", title="Get Current User Profile")


class FindUsers(_Input):
    """Find users accessible to an admin JWT."""
    operation: Literal["find_users"] = Field("find_users", title="Find Users (Admin)")
    device_token: UUID | None = None
    email: str | None = None
    phone: str | None = None
    client_id: str | None = None
    country: str | None = None
    full_name: str | None = None
    include_account_info: bool = False
    show_inactive_users: bool = False


class ListUsers(_Input):
    """Read one page of users, ordered by creation date."""
    operation: Literal["list_users"] = Field("list_users", title="List Users (Admin)")
    instance_ids: list[UUID] | None = None
    page_number: int = Field(1, ge=1)
    page_size: int = Field(100, ge=1, le=1000)
    date_created_from: datetime | None = None
    date_created_to: datetime | None = None
    search_term: str | None = None
    show_inactive_users: bool = False


class SearchUsers(_Input):
    operation: Literal["search_users"] = Field("search_users", title="Quick Search Users (Admin)")
    search_term: str = Field(..., min_length=1)
    instance_id: UUID | None = None
    show_inactive_users: bool = False


class UpdateProfile(_Input):
    """Update a user profile; verification messages are never requested."""
    operation: Literal["update_profile"] = Field("update_profile", title="Update User Profile")
    user_device_token: UUID | None = Field(None, description="Admin JWTs may target another user; omit for the current user.")
    first_name: str | None = None
    last_name: str | None = None
    nickname: str | None = None
    email: str | None = None
    phone: str | None = None
    country: str | None = None
    city: str | None = None
    address: str | None = None
    status: Literal["Active", "Deactivated", "Deleted"] | None = None


class DeleteUser(_Input):
    """Permanently delete the user and associated telematics data."""
    operation: Literal["delete_user"] = Field("delete_user", title="Delete User Permanently")
    device_token: UUID


class UpdateSDK(_Input):
    operation: Literal["update_sdk_settings"] = Field("update_sdk_settings", title="Update Instance SDK Settings")
    instance_id: UUID
    enable_tracking: bool | None = None
    enable_logging: bool | None = None
    enable_real_time_location: bool | None = Field(None, description="Real-time location increases battery use.")
    enabled: bool | None = None


class CreateInstance(_Input):
    operation: Literal["create_instance"] = Field("create_instance", title="Create Instance")
    name: str = Field(..., min_length=1)
    description: str | None = None


class GetInstance(_Input):
    operation: Literal["get_instance"] = Field("get_instance", title="Get Instance")
    instance_id: UUID


class UpdateInstance(_Input):
    operation: Literal["update_instance"] = Field("update_instance", title="Update Instance")
    instance_id: UUID
    name: str | None = None
    description: str | None = None


class JoinInstance(_Input):
    operation: Literal["join_instance"] = Field("join_instance", title="Join Instance by Invite Code")
    invite_code: str = Field(..., min_length=1)


class CountUsers(_Input):
    operation: Literal["count_users"] = Field("count_users", title="Count Users (Admin)")
    instance_ids: list[UUID] | None = None
    include_deactivated: bool = False
    is_rtd_enabled: bool | None = None
    is_enabled: bool | None = None
    is_tracking_enabled: bool | None = None


class GetWallets(_Input):
    operation: Literal["get_wallets"] = Field("get_wallets", title="Get User Wallets")
    blockchain_id: UUID | None = None


class OnNewUser(PollTriggerConfigBase):
    """Baseline existing users, then emit newly created users in this scope."""
    operation: Literal["on_new_user"] = Field("on_new_user", title="On New User", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "ui:hidden": True})
    instance_ids: list[UUID] | None = None
    date_created_from: datetime | None = Field(None, description="Optional fixed creation-date lower bound. Existing matching users form the initial baseline.")
    show_inactive_users: bool = False


TelematicsSDKConfig = Annotated[Union[GetProfile, FindUsers, ListUsers, SearchUsers, UpdateProfile,
    DeleteUser, UpdateSDK, CreateInstance, GetInstance, UpdateInstance, JoinInstance,
    CountUsers, GetWallets, OnNewUser], Field(discriminator="operation")]


class TelematicsSDKFullConfig(NodeConfig[TelematicsSDKConfig, TelematicsSDKToken]):
    pass


def _wire(values):
    return {"".join(part.title() for part in key.split("_")): value for key, value in values.items()}


class TelematicsSDKNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-telematicssdk"
    connection_evidence = ConnectionEvidence(operation="find_users", noun="Damoov users", label_keys=("DeviceToken",))

    @classmethod
    def get_config_model(cls):
        return TelematicsSDKFullConfig

    async def _request(self, method, path, *, params=None, body=None, headers=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Telematics SDK JWT")
        async with guarded_async_client(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"Authorization": "Bearer " + credential.access_token,
                         "Accept": "application/json", **(headers or {})})
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected a Damoov response object")
        if data.get("Status", 200) >= 400 or data.get("Errors"):
            raise ValueError(data.get("Title") or "Damoov rejected the request")
        return data

    @staticmethod
    def _page_body(config, page_number, page_size):
        body = {"PageNumber": page_number, "PageSize": page_size, "Sort": "DateCreatedDesc",
                "ShowInactiveUsers": config.show_inactive_users}
        for name in ("instance_ids", "date_created_from", "date_created_to", "search_term"):
            value = config.model_dump(mode="json").get(name)
            if value is not None:
                body.update(_wire({name: value}))
        return body

    async def _poll(self, config):
        users = []
        for page_number in range(1, 101):
            data = await self._request("POST", "/v1/Management/users/GetFilteredPage",
                body=self._page_body(config, page_number, 100))
            page = data.get("Result")
            if not isinstance(page, dict) or not isinstance(page.get("Users"), list):
                raise ValueError("Expected a Damoov users page")
            for user in page["Users"]:
                if not isinstance(user, dict) or not user.get("DeviceToken"):
                    raise ValueError("Damoov user is missing DeviceToken")
            users.extend(page["Users"])
            if not page.get("HasNextPage"):
                break
        else:
            raise ValueError("More than 10,000 users match; narrow the instance or creation-date scope")
        users = list({str(user["DeviceToken"]): user for user in users}.values())
        fresh = await self._filter_unseen(users, lambda user: str(user["DeviceToken"]))
        return {"users": fresh, "new_user_count": len(fresh)}

    @classmethod
    def resolve_agent_event(cls, output):
        users = output.get("users") if isinstance(output, dict) else None
        if users is None:
            return super().resolve_agent_event(output)
        if not users:
            return None
        lines = []
        for user in users[:10]:
            profile = user.get("UserProfile") or {}
            name = " ".join(filter(None, [profile.get("FirstName"), profile.get("LastName")]))
            lines.append(f"- {name or profile.get('Email') or 'User'} (DeviceToken {user['DeviceToken']}, created {user.get('DateCreated', 'unknown')})")
        return {"text": f"Damoov: {len(users)} new user(s):\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        config = self.config.config
        if isinstance(config, OnNewUser):
            return await self._poll(config)
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        op = config.operation
        if op == "get_profile":
            return await self._request("GET", "/v1/Management/users")
        if op == "find_users":
            data = await self._request("GET", "/v1/Management/users/find", params=_wire(values))
            if not isinstance(data.get("Result"), list):
                raise ValueError("Expected a Damoov user list")
            return data
        if op == "list_users":
            return await self._request("POST", "/v1/Management/users/GetFilteredPage",
                body=self._page_body(config, config.page_number, config.page_size))
        if op == "search_users":
            return await self._request("GET", "/v1/Management/users/quicksearch", params=_wire(values))
        if op == "update_profile":
            target = values.pop("user_device_token", None)
            body = {**_wire(values), "SendVerificationCodeForEmailPhone": False}
            return await self._request("PUT", "/v1/Management/users", body=body,
                headers={"UserDeviceToken": target} if target else None)
        if op == "delete_user":
            return await self._request("DELETE", "/v1/Management/users/" + quote(values["device_token"], safe=""))
        if op == "update_sdk_settings":
            instance = values.pop("instance_id")
            return await self._request("PATCH", f"/v1/Management/users/instances/{instance}/sdk", body=_wire(values))
        if op == "create_instance":
            return await self._request("POST", "/v1/Management/users/instances", body=_wire(values))
        if op in {"get_instance", "update_instance"}:
            instance = values.pop("instance_id")
            return await self._request("GET" if op == "get_instance" else "PUT",
                f"/v1/Management/users/instances/{instance}", body=_wire(values) if op == "update_instance" else None)
        if op == "join_instance":
            return await self._request("POST", "/v1/Management/users/instances/change/" + quote(values["invite_code"], safe=""))
        if op == "count_users":
            ids = values.pop("instance_ids", None)
            # The provider deliberately spells this IncludeDeacivated.
            included = values.pop("include_deactivated")
            return await self._request("POST", "/v1/Management/users/count", body={
                **_wire(values), "IncludeDeacivated": included,
                **({"Identifiers": {"InstanceIds": ids}} if ids is not None else {})})
        if op == "get_wallets":
            return await self._request("GET", "/v1/Wallets", params={"blockchainId": values["blockchain_id"]} if values else {})
        raise ValueError("Unknown Telematics SDK operation")
