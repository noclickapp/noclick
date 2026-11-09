"""Bitwarden Public API organization administration.

Contract: https://bitwarden.com/help/api/ (latest OpenAPI).
Paste a prepared api.organization bearer token; tokens expire after 60 minutes.
This API does not expose passwords or decrypted vault items.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.scopes.bitwarden import BITWARDEN_SCOPES


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class BitwardenAccessTokenCredential(Closed):
    model_config = ConfigDict(title="Bitwarden Access Token", extra="forbid", json_schema_extra={
        "x-credential-url": "https://bitwarden.com/help/public-api/",
        "x-credential-instructions": "Paste an organization bearer access token obtained with your organization API key and scope api.organization. Tokens expire after 60 minutes; replace an expired token. This is not a Secrets Manager access token or a personal vault session."})
    credential_type: Literal["bitwarden_access_token"] = Field("bitwarden_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})
    region: Literal["US", "EU", "Gov"] = Field("US", title="Server Region")

    @field_validator("access_token")
    @classmethod
    def token(cls, value):
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the access token without the Bearer prefix")
        return value

class GetCollection(Closed):
    operation: Literal['get_collection'] = Field('get_collection', title='Retrieve a collection', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)


class AssociationWithPermissionsRequestModel(Closed):
    id: UUID = Field(..., description="The associated object's unique identifier.")
    readOnly: bool = Field(..., description='When true, the read only permission will not allow the user or group to make changes to items.')
    hidePasswords: bool | None = Field(None, description='When true, the hide passwords permission will not allow the user or group to view passwords.\nThis prevents easy copy-and-paste of hidden items, however it may not completely prevent user access.')
    manage: bool | None = Field(None, description='When true, the manage permission allows a user to both edit the ciphers within a collection and edit the users/groups that are assigned to the collection.\nThis field will not affect behavior until your organization is using the latest collection enhancements (Releasing Q1, 2024)')


class CollectionUpdateRequestModel(Closed):
    externalId: str | None = Field(None, min_length=0, max_length=300, description='External identifier for reference or linking this collection to another system.')
    groups: list[AssociationWithPermissionsRequestModel] | None = Field(None, description='The associated groups that this collection is assigned to.')


class UpdateCollection(Closed):
    operation: Literal['update_collection'] = Field('update_collection', title='Update a collection', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)
    body: CollectionUpdateRequestModel = Field(..., title="Request Body", description="Complete replacement fields as documented by Bitwarden. Membership and permission changes apply immediately.")


class DeleteCollection(Closed):
    operation: Literal['delete_collection'] = Field('delete_collection', title='Delete a collection', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)


class ListCollections(Closed):
    operation: Literal['list_collections'] = Field('list_collections', title='List all collections', json_schema_extra={"ui:hidden": True})
    continuationToken: str | None = Field(None, title="Continuation Token", description="Copy the cursor returned by the previous page; omit for the first page.")


class ListEvents(Closed):
    operation: Literal['list_events'] = Field('list_events', title='List all events', json_schema_extra={"ui:hidden": True})
    start: datetime | None = Field(None)
    end: datetime | None = Field(None)
    actingUserId: UUID | None = Field(None)
    itemId: UUID | None = Field(None)
    secretId: UUID | None = Field(None)
    projectId: UUID | None = Field(None)
    continuationToken: str | None = Field(None)


class GetGroup(Closed):
    operation: Literal['get_group'] = Field('get_group', title='Retrieve a group', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)


class GroupCreateUpdateRequestModel(Closed):
    name: str = Field(..., min_length=0, max_length=100, description='The name of the group.')
    externalId: str | None = Field(None, min_length=0, max_length=300, description='External identifier for reference or linking this group to another system, such as a user directory.')
    collections: list[AssociationWithPermissionsRequestModel] | None = Field(None, description='The associated collections that this group can access.')


class UpdateGroup(Closed):
    operation: Literal['update_group'] = Field('update_group', title='Update a group', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)
    body: GroupCreateUpdateRequestModel = Field(..., title="Request Body", description="Complete replacement fields as documented by Bitwarden. Membership and permission changes apply immediately.")


class DeleteGroup(Closed):
    operation: Literal['delete_group'] = Field('delete_group', title='Delete a group', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)


class GetMemberIdsGroup(Closed):
    operation: Literal['get_member_ids_group'] = Field('get_member_ids_group', title="Retrieve a groups's member ids", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)


class UpdateMemberIdsRequestModel(Closed):
    memberIds: list[UUID] | None = Field(None, description='The associated member ids that have access to this object.')


class UpdateMemberIdsGroup(Closed):
    operation: Literal['update_member_ids_group'] = Field('update_member_ids_group', title="Update a group's members", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)
    body: UpdateMemberIdsRequestModel = Field(..., title="Request Body", description="Complete replacement fields as documented by Bitwarden. Membership and permission changes apply immediately.")


class ListGroups(Closed):
    operation: Literal['list_groups'] = Field('list_groups', title='List all groups', json_schema_extra={"ui:hidden": True})
    continuationToken: str | None = Field(None, title="Continuation Token", description="Copy the cursor returned by the previous page; omit for the first page.")


class CreateGroup(Closed):
    operation: Literal['create_group'] = Field('create_group', title='Create a group', json_schema_extra={"ui:hidden": True})
    body: GroupCreateUpdateRequestModel = Field(..., title="Request Body", description="Complete replacement fields as documented by Bitwarden. Membership and permission changes apply immediately.")


class GetMember(Closed):
    operation: Literal['get_member'] = Field('get_member', title='Retrieve a member', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)


OrganizationUserType = Literal[0, 1, 2, 4]

class PermissionsModel(Closed):
    accessEventLogs: bool = Field(False)
    accessImportExport: bool = Field(False)
    accessReports: bool = Field(False)
    createNewCollections: bool = Field(False)
    editAnyCollection: bool = Field(False)
    deleteAnyCollection: bool = Field(False)
    manageGroups: bool = Field(False)
    managePolicies: bool = Field(False)
    manageSso: bool = Field(False)
    manageUsers: bool = Field(False)
    manageResetPassword: bool = Field(False)
    manageScim: bool = Field(False)
    manageAccessRules: bool = Field(False)
    manageRotation: bool = Field(False)


class MemberUpdateRequestModel(Closed):
    type: OrganizationUserType = Field(...)
    externalId: str | None = Field(None, min_length=0, max_length=300, description='External identifier for reference or linking this member to another system, such as a user directory.')
    permissions: PermissionsModel = Field(default_factory=PermissionsModel)
    collections: list[AssociationWithPermissionsRequestModel] | None = Field(None, description='The associated collections that this member can access.')
    groups: list[UUID] | None = Field(None, description='Ids of the associated groups that this member will belong to')
    email: str | None = Field(None, min_length=0, max_length=256, description="The member's email address. Can only be changed for a claimed member without a master password when the\nnew address is on a domain verified by the organization.")
    name: str | None = Field(None, min_length=0, max_length=50, description="The member's name. Can only be changed for a claimed member.")


class UpdateMember(Closed):
    operation: Literal['update_member'] = Field('update_member', title='Update a member', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)
    body: MemberUpdateRequestModel = Field(..., title="Request Body", description="Complete replacement fields as documented by Bitwarden. Membership and permission changes apply immediately.")


class RemoveMember(Closed):
    operation: Literal['remove_member'] = Field('remove_member', title='Remove a member', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)


class GetGroupIdsMember(Closed):
    operation: Literal['get_group_ids_member'] = Field('get_group_ids_member', title="Retrieve a member's group ids", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)


class UpdateGroupIdsRequestModel(Closed):
    groupIds: list[UUID] | None = Field(None, description='The associated group ids that this object can access.')


class UpdateGroupIdsMember(Closed):
    operation: Literal['update_group_ids_member'] = Field('update_group_ids_member', title="Update a member's groups", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)
    body: UpdateGroupIdsRequestModel = Field(..., title="Request Body", description="Complete replacement fields as documented by Bitwarden. Membership and permission changes apply immediately.")


class ListMembers(Closed):
    operation: Literal['list_members'] = Field('list_members', title='List all members', json_schema_extra={"ui:hidden": True})
    continuationToken: str | None = Field(None, title="Continuation Token", description="Copy the cursor returned by the previous page; omit for the first page.")


class MemberCreateRequestModel(Closed):
    type: OrganizationUserType = Field(...)
    externalId: str | None = Field(None, min_length=0, max_length=300, description='External identifier for reference or linking this member to another system, such as a user directory.')
    permissions: PermissionsModel = Field(default_factory=PermissionsModel)
    collections: list[AssociationWithPermissionsRequestModel] | None = Field(None, description='The associated collections that this member can access.')
    groups: list[UUID] | None = Field(None, description='Ids of the associated groups that this member will belong to')
    name: str | None = Field(None, min_length=0, max_length=50, description="The member's name. Can only be changed for a claimed member.")
    email: str = Field(..., min_length=0, max_length=256, description="The member's email address.")


class CreateMember(Closed):
    operation: Literal['create_member'] = Field('create_member', title='Create a member', json_schema_extra={"ui:hidden": True})
    body: MemberCreateRequestModel = Field(..., title="Request Body", description="Complete replacement fields as documented by Bitwarden. Membership and permission changes apply immediately.")


class ReinviteMember(Closed):
    operation: Literal['reinvite_member'] = Field('reinvite_member', title='Re-invite a member', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)


class RevokeMember(Closed):
    operation: Literal['revoke_member'] = Field('revoke_member', title="Revoke a member's access to an organization", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)


class RestoreMember(Closed):
    operation: Literal['restore_member'] = Field('restore_member', title='Restore a member', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)


class GetSubscriptionOrganization(Closed):
    operation: Literal['get_subscription_organization'] = Field('get_subscription_organization', title='Retrieves the subscription details for the current organization', json_schema_extra={"ui:hidden": True})


PolicyType = Literal[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]

class GetPolicy(Closed):
    operation: Literal['get_policy'] = Field('get_policy', title='Retrieve a policy', json_schema_extra={"ui:hidden": True})
    policy_type: PolicyType = Field(...)


class ListPolicies(Closed):
    operation: Literal['list_policies'] = Field('list_policies', title='List all policies', json_schema_extra={"ui:hidden": True})
    continuationToken: str | None = Field(None, title="Continuation Token", description="Copy the cursor returned by the previous page; omit for the first page.")


class OnNewEvent(PollTriggerConfigBase):
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_new_event"] = Field("on_new_event", title="On New Organization Event", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers",
        "x-display-name": "On New Organization Event",
    })
    event_kind: Literal["all", "item_created", "item_updated", "member_invited", "member_updated",
                        "member_removed", "access_revoked", "access_restored", "login_failed"] = Field(
        "all", title="Event", description="Watch all organization events, or a common item, member, or security event.")
    actingUserId: UUID | None = Field(None, title="Acting User ID")
    itemId: UUID | None = Field(None, title="Item ID")
    secretId: UUID | None = Field(None, title="Secret ID")
    projectId: UUID | None = Field(None, title="Project ID")
    lookback_hours: int = Field(24, ge=1, le=720, title="Lookback Hours",
        description="Poll this recent window, including delayed logs. Existing events are baselined when enabled. "
                    "Events older than the window after a pause cannot be recovered; use a window longer than the schedule interval. "
                    "Keep the window below 10,000 matching events. Organization bearer tokens expire after 60 minutes.")


# EventType enum from the pinned Bitwarden Public API OpenAPI document.
EVENT_KINDS = {"item_created": 1100, "item_updated": 1101, "member_invited": 1500,
               "member_updated": 1502, "member_removed": 1503, "access_revoked": 1511,
               "access_restored": 1512, "login_failed": 1005}
EVENT_LABELS = {1000: "logged in", 1005: "failed to log in", 1100: "created an item", 1101: "updated an item",
                1500: "invited a member", 1502: "updated a member", 1503: "removed a member",
                1511: "revoked a member's access", 1512: "restored a member's access"}


Operation = Annotated[Union[GetCollection, UpdateCollection, DeleteCollection, ListCollections, ListEvents, GetGroup, UpdateGroup, DeleteGroup, GetMemberIdsGroup, UpdateMemberIdsGroup, ListGroups, CreateGroup, GetMember, UpdateMember, RemoveMember, GetGroupIdsMember, UpdateGroupIdsMember, ListMembers, CreateMember, ReinviteMember, RevokeMember, RestoreMember, GetSubscriptionOrganization, GetPolicy, ListPolicies, OnNewEvent], Field(discriminator="operation")]

class BitwardenNodeConfig(NodeConfig[Operation, BitwardenAccessTokenCredential]):
    pass


ROUTES = {'get_collection': ('GET', '/public/collections/{id}'), 'update_collection': ('PUT', '/public/collections/{id}'), 'delete_collection': ('DELETE', '/public/collections/{id}'), 'list_collections': ('GET', '/public/collections'), 'list_events': ('GET', '/public/events'), 'get_group': ('GET', '/public/groups/{id}'), 'update_group': ('PUT', '/public/groups/{id}'), 'delete_group': ('DELETE', '/public/groups/{id}'), 'get_member_ids_group': ('GET', '/public/groups/{id}/member-ids'), 'update_member_ids_group': ('PUT', '/public/groups/{id}/member-ids'), 'list_groups': ('GET', '/public/groups'), 'create_group': ('POST', '/public/groups'), 'get_member': ('GET', '/public/members/{id}'), 'update_member': ('PUT', '/public/members/{id}'), 'remove_member': ('DELETE', '/public/members/{id}'), 'get_group_ids_member': ('GET', '/public/members/{id}/group-ids'), 'update_group_ids_member': ('PUT', '/public/members/{id}/group-ids'), 'list_members': ('GET', '/public/members'), 'create_member': ('POST', '/public/members'), 'reinvite_member': ('POST', '/public/members/{id}/reinvite'), 'revoke_member': ('POST', '/public/members/{id}/revoke'), 'restore_member': ('POST', '/public/members/{id}/restore'), 'get_subscription_organization': ('GET', '/public/organization/subscription'), 'get_policy': ('GET', '/public/policies/{type}'), 'list_policies': ('GET', '/public/policies')}

class BitwardenNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-bitwarden"
    scope_registry = BITWARDEN_SCOPES
    connection_evidence = ConnectionEvidence(noun="groups", operation="list_groups", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return BitwardenNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        return BitwardenNodeConfig.model_validate(runtime_config_view(config_data, BitwardenNodeConfig))

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") == "on_new_event":
            return bool(output.get("new_event_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        events = output.get("events") if isinstance(output, dict) else None
        if not isinstance(events, list):
            return super().resolve_agent_event(output)
        if not events:
            return None
        lines = []
        for event in events[:10]:
            actor = event.get("actingUserId") or event.get("installationId") or "Unknown actor"
            action = EVENT_LABELS.get(event.get("type"), f"performed event type {event.get('type')}")
            ids = ", ".join(f"{key}={event[key]}" for key in (
                "itemId", "collectionId", "groupId", "policyId", "memberId",
                "secretId", "projectId", "serviceAccountId") if event.get(key))
            lines.append(f"- {actor} {action} at {event.get('date')}" + (f" ({ids})" if ids else ""))
        if len(events) > 10:
            lines.append(f"- … and {len(events) - 10} more events in the workflow output")
        return {"text": f"Bitwarden organization: {len(events)} new event(s):\n" + "\n".join(lines),
                "conversation_key": None}

    @staticmethod
    def _event_key(event):
        # Public API events have no id. Hash their documented fields instead of inventing one.
        return hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    async def _poll_events(self, credential, op):
        end = datetime.now(timezone.utc)
        params = {"start": (end - timedelta(hours=op.lookback_hours)).isoformat(), "end": end.isoformat()}
        params.update({key: str(getattr(op, key)) for key in (
            "actingUserId", "itemId", "secretId", "projectId") if getattr(op, key) is not None})
        events = []
        cursors = set()
        for _ in range(200):
            result = await self._request(credential, "GET", "/public/events", params=params)
            if not isinstance(result, dict) or not isinstance(result.get("data"), list):
                raise ValueError("Bitwarden returned an invalid event list")
            for event in result["data"]:
                if not isinstance(event, dict) or "date" not in event or "type" not in event:
                    raise ValueError("Bitwarden returned an invalid event")
                if op.event_kind == "all" or event["type"] == EVENT_KINDS[op.event_kind]:
                    events.append(event)
            if len(events) > 10000:
                raise ValueError("Bitwarden poll exceeds 10,000 matching events; narrow the filters or lookback window")
            cursor = result.get("continuationToken")
            if not cursor:
                break
            if cursor in cursors:
                raise ValueError("Bitwarden repeated an event continuation token")
            cursors.add(cursor)
            params["continuationToken"] = cursor
        else:
            raise ValueError("Bitwarden poll exceeds 200 pages; narrow the filters or lookback window")
        # Deduplicate within the complete window too, before updating the shared seen-set.
        unique = {self._event_key(event): event for event in events}
        fresh = await self._filter_unseen(sorted(unique.values(), key=lambda event: event["date"]), self._event_key)
        return {"events": fresh, "new_event_count": len(fresh)}

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        host = {"US": "https://api.bitwarden.com", "EU": "https://api.bitwarden.eu", "Gov": "https://api.bitwarden-gov.com"}[credential.region]
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, host + path,
                headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            try:
                message = response.json().get("message", "Bitwarden request failed")
            except (ValueError, AttributeError):
                message = "Bitwarden request failed"
            raise ValueError(f"Bitwarden HTTP {response.status_code}: {str(message).replace(credential.access_token, '[redacted]')}")
        return response.json() if response.content else {"acknowledged": True}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Bitwarden organization access token")
        credential = self.config.credentials
        op = self.config.config
        if isinstance(op, OnNewEvent):
            output = await self._poll_events(credential, op)
            await self.emit(output)
            return output
        method, path = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_unset=True)
        if "{id}" in path:
            path = path.replace("{id}", str(op.id))
        if "{type}" in path:
            path = path.replace("{type}", str(op.policy_type))
        params = {k: v for k, v in values.items() if k not in {"operation", "id", "policy_type", "body"} and v is not None}
        result = await self._request(credential, method, path, params=params,
            body=op.body.model_dump(mode="json", exclude_unset=True) if hasattr(op, "body") else None)
        output = {"data": result.get("data", result) if isinstance(result, dict) else result}
        if isinstance(result, dict) and "continuationToken" in result:
            output["continuationToken"] = result["continuationToken"]
        await self.emit(output)
        return output
