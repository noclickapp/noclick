"""Kisi access-management operations pinned to the official apps OpenAPI contract.

Each operation makes one request to api.kisi.io. Lists return one offset page;
mutations never prefetch or automatically retry a physical unlock.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.kisi.io"
CREDENTIAL_TYPE = "kisi_api_key"


class KisiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Kisi API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.kisi.io/platform/apis/get_started/setup_kisi_account",
            "x-credential-instructions": "Create an API key in Kisi, then paste the key without the KISI-LOGIN prefix. Use an account with permission to manage the places, groups and members needed by your workflow.",
        })
    credential_type: Literal["kisi_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        description="Paste your Kisi API key, without the Authorization header or KISI-LOGIN prefix.",
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the Kisi API key")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(50, ge=1, le=100, description="Maximum records in this page (up to 100).")
    offset: int = Field(0, ge=0, le=20000, description="Records to skip. Use next_offset to request another page.")
    query: str | None = Field(None, max_length=1000, description="Provider free-text search.")


class KisiListPlacesConfig(_Page):
    """List one page of places visible to the connected account."""
    operation: Literal["list_places"] = Field("list_places", json_schema_extra={"ui:hidden": True})


class KisiGetPlaceConfig(_Input):
    """Read a single place by its Kisi ID."""
    operation: Literal["get_place"] = Field("get_place", json_schema_extra={"ui:hidden": True})
    place_id: int = Field(..., ge=1, title="Place ID")


class KisiListLocksConfig(_Page):
    """List one page of locks visible to the connected account."""
    operation: Literal["list_locks"] = Field("list_locks", json_schema_extra={"ui:hidden": True})
    place_id: int | None = Field(None, ge=1)


class KisiGetLockConfig(_Input):
    """Read a single lock by its Kisi ID."""
    operation: Literal["get_lock"] = Field("get_lock", json_schema_extra={"ui:hidden": True})
    lock_id: int = Field(..., ge=1, title="Lock ID")


class KisiListGroupsConfig(_Page):
    """List one page of groups visible to the connected account."""
    operation: Literal["list_groups"] = Field("list_groups", json_schema_extra={"ui:hidden": True})
    place_id: str | None = Field(None, description="Filter by place ID.")


class KisiGetGroupConfig(_Input):
    """Read a single group by its Kisi ID."""
    operation: Literal["get_group"] = Field("get_group", json_schema_extra={"ui:hidden": True})
    group_id: int = Field(..., ge=1, title="Group ID")


class KisiListMembersConfig(_Page):
    """List one page of members visible to the connected account."""
    operation: Literal["list_members"] = Field("list_members", json_schema_extra={"ui:hidden": True})
    place_id: int | None = Field(None, ge=1)
    group_id: int | None = Field(None, ge=1)


class KisiGetMemberConfig(_Input):
    """Read a single member by its Kisi ID."""
    operation: Literal["get_member"] = Field("get_member", json_schema_extra={"ui:hidden": True})
    member_id: int = Field(..., ge=1, title="Member ID")


class KisiCreateGroupConfig(_Input):
    """Create a Kisi group."""
    operation: Literal["create_group"] = Field("create_group", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(None, max_length=10000)
    login_enabled: bool | None = None
    place_id: int | None = Field(None, ge=1)


class KisiUpdateGroupConfig(_Input):
    """Update a Kisi group."""
    operation: Literal["update_group"] = Field("update_group", json_schema_extra={"ui:hidden": True})
    group_id: int = Field(..., ge=1, title="Group ID")
    name: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = Field(None, max_length=10000)
    login_enabled: bool | None = None


class KisiDeleteGroupConfig(_Input):
    """Delete a Kisi group."""
    operation: Literal["delete_group"] = Field("delete_group", json_schema_extra={"ui:hidden": True})
    group_id: int = Field(..., ge=1, title="Group ID")


class KisiCreateMemberConfig(_Input):
    """Create a Kisi member."""
    operation: Literal["create_member"] = Field("create_member", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=320)
    send_emails: bool = Field(False, description="Explicitly opt in to Kisi sending member emails.")
    name: str | None = Field(None, max_length=500)
    notes: str | None = Field(None, max_length=10000)
    access_enabled: bool | None = Field(None, description="Enable or disable the member access to locks and elevators.")


class KisiUpdateMemberConfig(_Input):
    """Update a Kisi member."""
    operation: Literal["update_member"] = Field("update_member", json_schema_extra={"ui:hidden": True})
    member_id: int = Field(..., ge=1, title="Member ID")
    name: str | None = Field(None, max_length=500)
    notes: str | None = Field(None, max_length=10000)
    access_enabled: bool | None = Field(None, description="Enable or disable the member access to locks and elevators.")


class KisiDeleteMemberConfig(_Input):
    """Delete a Kisi member."""
    operation: Literal["delete_member"] = Field("delete_member", json_schema_extra={"ui:hidden": True})
    member_id: int = Field(..., ge=1, title="Member ID")


class KisiListRoleAssignmentsConfig(_Page):
    """List access rights for users, teams or guests."""
    operation: Literal["list_role_assignments"] = Field("list_role_assignments", json_schema_extra={"ui:hidden": True})
    assignee_type: Literal["User", "Team", "Guest"] | None = None
    assignee_id: int | None = Field(None, ge=1)
    applies_to_type: Literal["Organization", "Place", "Group"] | None = None
    applies_to_id: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def paired_filters(self):
        if self.assignee_id is not None and self.assignee_type is None:
            raise ValueError("Assignee ID requires an assignee type")
        if self.applies_to_id is not None and self.applies_to_type is None:
            raise ValueError("Scope ID requires a scope type")
        return self


class KisiGetRoleAssignmentConfig(_Input):
    """Read one access right."""
    operation: Literal["get_role_assignment"] = Field("get_role_assignment", json_schema_extra={"ui:hidden": True})
    role_assignment_id: int = Field(..., ge=1)


class KisiCreateRoleAssignmentConfig(_Input):
    """Assign a group access role to a user, team or guest."""
    operation: Literal["create_role_assignment"] = Field("create_role_assignment", json_schema_extra={"ui:hidden": True})
    applies_to_id: int = Field(..., ge=1, title="Group ID")
    assignee_type: Literal["User", "Team", "Guest"] = "User"
    assignee_id: int = Field(..., ge=0, title="Assignee ID")
    role_id: Literal["group_basic", "group_manager"] = Field("group_basic", description="Basic grants door access; manager grants elevated group permissions.")
    notify: bool = Field(False, description="Opt in to Kisi sending an access assignment email.")
    valid_from: datetime | None = Field(None, description="Optional ISO 8601 access start time, with timezone.")
    valid_until: datetime | None = Field(None, description="Optional ISO 8601 access expiration, with timezone.")

    @model_validator(mode="after")
    def dates(self):
        for value in (self.valid_from, self.valid_until):
            if value is not None and value.tzinfo is None:
                raise ValueError("Access times must include a timezone")
        if self.valid_from and self.valid_until and self.valid_from >= self.valid_until:
            raise ValueError("Access expiration must follow the start")
        return self


class KisiDeleteRoleAssignmentConfig(_Input):
    """Revoke a specific access right."""
    operation: Literal["delete_role_assignment"] = Field("delete_role_assignment", json_schema_extra={"ui:hidden": True})
    role_assignment_id: int = Field(..., ge=1)


class KisiCreateGroupLockConfig(_Input):
    """Add a door to a group's access set."""
    operation: Literal["create_group_lock"] = Field("create_group_lock", json_schema_extra={"ui:hidden": True})
    group_id: int = Field(..., ge=1)
    lock_id: int = Field(..., ge=1)


class KisiDeleteGroupLockConfig(_Input):
    """Remove a door from a group's access set."""
    operation: Literal["delete_group_lock"] = Field("delete_group_lock", json_schema_extra={"ui:hidden": True})
    group_lock_id: int = Field(..., ge=1)


class KisiUnlockLockConfig(_Input):
    """Unlock a physical door once. Subject to the account's access restrictions."""
    operation: Literal["unlock_lock"] = Field("unlock_lock", json_schema_extra={"ui:hidden": True})
    lock_id: int = Field(..., ge=1, title="Lock ID")
    proximity_proof: str | None = Field(None, description="Provider proximity proof when required. Null requests a remote unlock subject to Kisi policy.")


KisiOperation = Annotated[Union[
    KisiListPlacesConfig,
    KisiGetPlaceConfig,
    KisiListLocksConfig,
    KisiGetLockConfig,
    KisiListGroupsConfig,
    KisiGetGroupConfig,
    KisiListMembersConfig,
    KisiGetMemberConfig,
    KisiCreateGroupConfig,
    KisiUpdateGroupConfig,
    KisiDeleteGroupConfig,
    KisiCreateMemberConfig,
    KisiUpdateMemberConfig,
    KisiDeleteMemberConfig,
    KisiUnlockLockConfig,
    KisiListRoleAssignmentsConfig, KisiGetRoleAssignmentConfig,
    KisiCreateRoleAssignmentConfig, KisiDeleteRoleAssignmentConfig,
    KisiCreateGroupLockConfig, KisiDeleteGroupLockConfig
], Field(discriminator="operation")]


class KisiConfig(NodeConfig[KisiOperation, KisiAPIKeyCredential]):
    pass


# Fixed routes only: input values can never select an API origin or method.
OPERATIONS = {
    "list_places": ('GET', '/places', None),
    "get_place": ('GET', '/places/{id}', None),
    "list_locks": ('GET', '/locks', None),
    "get_lock": ('GET', '/locks/{id}', None),
    "list_groups": ('GET', '/groups', None),
    "get_group": ('GET', '/groups/{id}', None),
    "list_members": ('GET', '/members', None),
    "get_member": ('GET', '/members/{id}', None),
    "create_group": ('POST', '/groups', 'group'),
    "update_group": ('PATCH', '/groups/{id}', 'group'),
    "delete_group": ('DELETE', '/groups/{id}', None),
    "create_member": ('POST', '/members', 'member'),
    "update_member": ('PATCH', '/members/{id}', 'member'),
    "delete_member": ('DELETE', '/members/{id}', None),
    "list_role_assignments": ('GET', '/role_assignments', None),
    "get_role_assignment": ('GET', '/role_assignments/{id}', None),
    "create_role_assignment": ('POST', '/role_assignments', 'role_assignment'),
    "delete_role_assignment": ('DELETE', '/role_assignments/{id}', None),
    "create_group_lock": ('POST', '/group_locks', 'group_lock'),
    "delete_group_lock": ('DELETE', '/group_locks/{id}', None),
    "unlock_lock": ('POST', '/locks/{id}/unlock', 'lock'),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    return value


class KisiNode(WorkflowNode):
    integration_type = "automation-kisi"
    connection_evidence = ConnectionEvidence(noun="Kisi places", operation="list_places")

    @classmethod
    def get_config_model(cls):
        return KisiConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Kisi API key")
        config = self.config.config
        credential = self.config.credentials
        method, path, body_key = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        values.pop("operation")
        if "{id}" in path:
            resource = path.split("/")[1][:-1]
            path = path.replace("{id}", str(values.pop(resource + "_id")))
        params, body = None, None
        if config.operation.startswith("list_"):
            params = values
        elif body_key:
            # Updates preserve omission. Nullable fields can explicitly clear a
            # description or notes without clearing other fields.
            if method == "PATCH":
                values = {k: v for k, v in config.model_dump(mode="json", exclude_unset=True).items()
                          if k not in {"operation", body_key + "_id"}}
                nullable = {"description", "notes"}
                if any(v is None and k not in nullable for k, v in values.items()):
                    raise ValueError("Only nullable Kisi fields may be cleared")
                if not values:
                    raise ValueError("Provide at least one field to update")
            if config.operation == "unlock_lock":
                values = {"proximity_proof": config.proximity_proof}
            if config.operation == "create_role_assignment":
                values["applies_to_type"] = "Group"
            body = {body_key: values}
        headers = {
            "Authorization": "KISI-LOGIN " + credential.api_key,
            "Accept": "application/json", "Content-Type": "application/json",
            "X-Kisi-Integration-Identifier": "NoClick",
            "X-Kisi-Integration-Contact": "support@noclick.com",
        }
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, params=params, json=body)
        if response.status_code >= 300:
            # Keep provider rejection words for connect diagnostics; never expose a key.
            message = response.text[:4000]
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = error.get("message") or error.get("error") or error.get("errors") or message
            except ValueError:
                pass
            return {"status": "error", "operation": config.operation,
                    "http_status": response.status_code, "error": _redact(message, credential.api_key)}
        if response.status_code == 204:
            return {"status": "success", "operation": config.operation, "success": True}
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Kisi returned a non-JSON response") from None
        data = _redact(data, credential.api_key)
        if config.operation.startswith("list_"):
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError("Kisi returned an invalid list response")
            next_offset = config.offset + len(data)
            has_more = len(data) == config.limit and next_offset <= 20000
            return {"status": "success", "operation": config.operation, "items": data,
                    "offset": config.offset, "next_offset": next_offset if has_more else None,
                    "has_more": has_more}
        if not isinstance(data, dict):
            raise ValueError("Kisi returned an invalid resource response")
        return {"status": "success", "operation": config.operation, "data": data}
