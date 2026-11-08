"""Heartbeat v0 community automation. Contract: https://heartbeat.readme.io/openapi/5f2d14b7c051e4da5496c59e (1.0.0)."""
from __future__ import annotations
from typing import Annotated, Literal, Union
from uuid import UUID
import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, EmailStr, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.heartbeat.chat/v0"

class HeartbeatAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Heartbeat API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://heartbeat.readme.io/reference/authentication",
        "x-credential-instructions": "Paste a Heartbeat community API key. NoClick sends it as a Bearer token to api.heartbeat.chat. Listing community users verifies access; it does not identify the person who created the key."})
    credential_type: Literal["heartbeat_api_key"] = Field("heartbeat_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(x.isspace() for x in value):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class GetUser(_Input):
    """Get a user by id"""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    userID: UUID = Field(..., description='')


class GetUsers(_Input):
    """Return an array of all users within a Heartbeat community"""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    pass


class CreateUser(_Input):
    """Create a new user in a Heartbeat community"""
    operation: Literal["create_user"] = Field("create_user", json_schema_extra={"ui:hidden": True})
    email: EmailStr = Field(..., description="The user's email. Must be unique to the community")
    name: str = Field(..., max_length=10000, description="The user's full name")
    roleID: UUID = Field(..., description='The id of the role the user should have')
    groupIDs: list[UUID] | None = Field(None, description='A list of the ids of the groups that the user should belong to')
    bio: str | None = Field(None, description="The user's bio")
    status: str | None = Field(None, description="The user's status")
    linkedin: str | None = Field(None, description="A link to the user's LinkedIn profile")
    twitter: str | None = Field(None, description="A link to the user's Twitter profile")
    instagram: str | None = Field(None, description="A link to the user's Instagram profile")
    website: str | None = Field(None, description="A link to the user's website")
    createIntroductionThread: StrictBool | None = Field(None, description="If true and a value for bio is provided, an introduction thread for the user will be created in the channel designated for introductions in your community settings. The introduction thread will include the user's bio")


class UpdateUser(_Input):
    """Update a user's profile information"""
    operation: Literal["update_user"] = Field("update_user", json_schema_extra={"ui:hidden": True})
    email: EmailStr = Field(..., description='The email of the user that will be updated. If no user with the provided email exists, will return a 404 response.')
    name: str | None = Field(None, description="The user's full name")
    bio: str | None = Field(None, description="The user's bio")
    status: str | None = Field(None, description="The user's status")
    linkedin: str | None = Field(None, description="A link to the user's LinkedIn profile")
    twitter: str | None = Field(None, description="A link to the user's Twitter profile")
    instagram: str | None = Field(None, description="A link to the user's Instagram profile")


class DeleteUser(_Input):
    """Remove a user from a Heartbeat community. The user will no longer be able to access the community. Threads, comments & messages from the user will not be removed"""
    operation: Literal["delete_user"] = Field("delete_user", json_schema_extra={"ui:hidden": True})
    email: EmailStr = Field(..., description='The email of the user to be deleted. If no user with the provided email exists, will return a 404 response.')


class FindUser(_Input):
    """Get a user by email"""
    operation: Literal["find_user"] = Field("find_user", json_schema_extra={"ui:hidden": True})
    email: EmailStr = Field(..., description='The email of the user')


class GetInvitations(_Input):
    """Return an array of all the invitations within a Heartbeat community"""
    operation: Literal["list_invitations"] = Field("list_invitations", json_schema_extra={"ui:hidden": True})
    pass


class CreateInvitation(_Input):
    """Create a new invitation link within a Heartbeat community"""
    operation: Literal["create_invitation"] = Field("create_invitation", json_schema_extra={"ui:hidden": True})
    roleID: UUID = Field(..., description='Members joining via this invitation link will join as this role')
    groupIDs: list[UUID] = Field(..., description='Members joining via this invitation link will automatically be in these groups')


class GetRoles(_Input):
    """Returns an array of all the roles in a Heartbeat community"""
    operation: Literal["list_roles"] = Field("list_roles", json_schema_extra={"ui:hidden": True})
    pass


class GetGroups(_Input):
    """Returns an array of all Groups within a Heartbeat community"""
    operation: Literal["list_groups"] = Field("list_groups", json_schema_extra={"ui:hidden": True})
    pass


class CreateGroup(_Input):
    """Create a new Group in a Heartbeat community"""
    operation: Literal["create_group"] = Field("create_group", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., max_length=10000, description='')
    description: str | None = Field(None, description='')
    members: list[EmailStr] | None = Field(None, description='The email addresses of the users that should be added to the group')
    parentGroupID: UUID | None = Field(None, description='The id of the parent group')
    isIsolated: StrictBool | None = Field(None, description='Whether the group is isolated. Refer to Heartbeat docs to learn more about what this entails')
    isJoinable: StrictBool | None = Field(None, description='Whether the group is joinable. Refer to Heartbeat docs to learn more about what this entails')


class GetGroup(_Input):
    """Get a group"""
    operation: Literal["get_group"] = Field("get_group", json_schema_extra={"ui:hidden": True})
    groupID: UUID = Field(..., description='')


class UpdateGroup(_Input):
    """Edit a group. All fields are optional, only fields that are provided will be changed."""
    operation: Literal["update_group"] = Field("update_group", json_schema_extra={"ui:hidden": True})
    groupID: UUID = Field(..., description='The id of the group')
    name: str | None = Field(None, description='')
    description: str | None = Field(None, description='')
    isIsolated: StrictBool | None = Field(None, description='Whether the group is isolated. Refer to Heartbeat docs to learn more about what this entails')
    isJoinable: StrictBool | None = Field(None, description='Whether the group is joinable. Refer to Heartbeat docs to learn more about what this entails')


class AddToGroup(_Input):
    """Add users to a group"""
    operation: Literal["add_group_members"] = Field("add_group_members", json_schema_extra={"ui:hidden": True})
    groupID: UUID = Field(..., description='')
    emails: list[EmailStr] = Field(..., description='The emails of the users that should be added to the group')
    shouldRemoveFromSiblingGroups: StrictBool | None = Field(None, description='If true, the users will be removed from any other groups that share a parent group with the selected group. Useful when moving users between different stages')


class RemoveFromGroup(_Input):
    """Remove users from a group"""
    operation: Literal["remove_group_members"] = Field("remove_group_members", json_schema_extra={"ui:hidden": True})
    groupID: UUID = Field(..., description='')
    emails: list[EmailStr] = Field(..., description='The emails of the users that should be removed from the group')


class GetChannels(_Input):
    """Returns an array of all channels"""
    operation: Literal["list_channels"] = Field("list_channels", json_schema_extra={"ui:hidden": True})
    pass


class GetThreads(_Input):
    """Returns threads in a channel, newest first. Results are paginated using cursor-based pagination."""
    operation: Literal["list_threads"] = Field("list_threads", json_schema_extra={"ui:hidden": True})
    channelID: UUID = Field(..., description='')
    startingAfter: UUID | None = Field(None, description='Cursor for pagination - return results after this thread ID')
    limit: int | None = Field(None, ge=1, le=100, description='Number of results to return (1-100)')


class GetThread(_Input):
    """Get a thread"""
    operation: Literal["get_thread"] = Field("get_thread", json_schema_extra={"ui:hidden": True})
    threadID: UUID = Field(..., description='')


class CreateThread(_Input):
    """Create a new thread"""
    operation: Literal["create_thread"] = Field("create_thread", json_schema_extra={"ui:hidden": True})
    text: str = Field(..., min_length=1, max_length=100000, description='See the Rich Text page to learn more about formatting')
    channelID: UUID = Field(..., description='')
    userID: UUID | None = Field(None, description='The user that will be shown as the author of the thread. Only an admin user can be chosen. If this field is not provided, the user that created the API key will be used')


class CreateComment(_Input):
    """Create a new comment"""
    operation: Literal["create_comment"] = Field("create_comment", json_schema_extra={"ui:hidden": True})
    text: str = Field(..., min_length=1, max_length=100000, description='See the Rich Text page to learn more about formatting')
    threadID: UUID = Field(..., description='')
    parentCommentID: UUID | None = Field(..., description='Heartbeat comments have two levels of nesting. If null is provided, then the comment will be a direct reply to the thread. If a comment id is provided, then the comment will be a reply to that comment. The provided comment id must be a comment that is a direct reply to the thread.')
    userID: UUID | None = Field(None, description='The user that will be shown as the author of the comment. Only an admin user can be chosen. If this field is not provided, the user that created the API key will be used')


class GetEvents(_Input):
    """Return an array all Events within a Community"""
    operation: Literal["list_events"] = Field("list_events", json_schema_extra={"ui:hidden": True})
    groupID: UUID | None = Field(None, description='If provided, only events that have been assigned to this group will be returned')


class GetEvent(_Input):
    """Get an event"""
    operation: Literal["get_event"] = Field("get_event", json_schema_extra={"ui:hidden": True})
    eventID: UUID = Field(..., description='')


class GetCourses(_Input):
    """Get all of the courses in your community"""
    operation: Literal["list_courses"] = Field("list_courses", json_schema_extra={"ui:hidden": True})
    pass


class GetDocuments(_Input):
    """Return an array of all documents (wiki posts) within a Heartbeat community. Results are paginated using cursor-based pagination."""
    operation: Literal["list_documents"] = Field("list_documents", json_schema_extra={"ui:hidden": True})
    startingAfter: UUID | None = Field(None, description='Cursor for pagination - return results after this document ID')
    limit: int | None = Field(None, ge=1, le=100, description='Number of results to return (1-100)')


class GetDocument(_Input):
    """Get a document by ID, including its content"""
    operation: Literal["get_document"] = Field("get_document", json_schema_extra={"ui:hidden": True})
    documentID: UUID = Field(..., description='')


Operation = Annotated[Union[GetUser, GetUsers, CreateUser, UpdateUser, DeleteUser, FindUser, GetInvitations, CreateInvitation, GetRoles, GetGroups, CreateGroup, GetGroup, UpdateGroup, AddToGroup, RemoveFromGroup, GetChannels, GetThreads, GetThread, CreateThread, CreateComment, GetEvents, GetEvent, GetCourses, GetDocuments, GetDocument], Field(discriminator="operation")]

class HeartbeatConfig(NodeConfig[Operation, HeartbeatAPIKeyCredential]):
    pass

ROUTES = {'get_user': ('GET', '/users/{userID}', ['userID'], [], False, False, True),
 'list_users': ('GET', '/users', [], [], False, True, True),
 'create_user': ('PUT', '/users', [], [], True, False, False),
 'update_user': ('POST', '/users', [], [], True, False, False),
 'delete_user': ('DELETE', '/users', [], [], True, False, False),
 'find_user': ('GET', '/find/users', [], ['email'], False, True, True),
 'list_invitations': ('GET', '/invitations', [], [], False, True, True),
 'create_invitation': ('PUT', '/invitations', [], [], True, False, True),
 'list_roles': ('GET', '/roles', [], [], False, True, True),
 'list_groups': ('GET', '/groups', [], [], False, True, True),
 'create_group': ('PUT', '/groups', [], [], True, False, False),
 'get_group': ('GET', '/groups/{groupID}', ['groupID'], [], False, False, True),
 'update_group': ('POST', '/groups/{groupID}', ['groupID'], [], True, False, False),
 'add_group_members': ('PUT', '/groups/{groupID}/memberships', ['groupID'], [], True, False, False),
 'remove_group_members': ('DELETE', '/groups/{groupID}/memberships', ['groupID'], [], True, False, False),
 'list_channels': ('GET', '/channels', [], [], False, True, True),
 'list_threads': ('GET',
                  '/channels/{channelID}/threads',
                  ['channelID'],
                  ['startingAfter', 'limit'],
                  False,
                  True,
                  True),
 'get_thread': ('GET', '/threads/{threadID}', ['threadID'], [], False, False, True),
 'create_thread': ('PUT', '/threads', [], [], True, False, True),
 'create_comment': ('PUT', '/comments', [], [], True, False, True),
 'list_events': ('GET', '/events', [], ['groupID'], False, True, True),
 'get_event': ('GET', '/events/{eventID}', ['eventID'], [], False, False, True),
 'list_courses': ('GET', '/courses', [], [], False, True, True),
 'list_documents': ('GET', '/documents', [], ['startingAfter', 'limit'], False, True, True),
 'get_document': ('GET', '/documents/{documentID}', ['documentID'], [], False, False, True)}


class HeartbeatNode(WorkflowNode):
    integration_type = "automation-heartbeat"
    connection_evidence = ConnectionEvidence(noun="community users", operation="list_users")

    @classmethod
    def get_config_model(cls):
        return HeartbeatConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Heartbeat API key")
        op = self.config.config
        method, path, path_fields, query_fields, has_body, is_list, has_response = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for field in path_fields:
            path = path.replace("{" + field + "}", values.pop(field))
        params = {key: values.pop(key) for key in query_fields if key in values}
        # parentCommentID is required by the contract, including explicit null for a top-level reply.
        if op.operation == "create_comment" and op.parentCommentID is None:
            values["parentCommentID"] = None
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"Authorization": "Bearer " + self.config.credentials.api_key, "Accept": "application/json"},
                    **({"json": values} if has_body else {}))
        except httpx.HTTPError:
            raise ValueError("Heartbeat request could not be completed; inspect writes before retrying") from None
        def redact(value):
            if isinstance(value, str):
                return value.replace(self.config.credentials.api_key, "[redacted]")
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {redact(key): redact(item) for key, item in value.items()}
            return value
        if response.status_code != 200:
            message = "Heartbeat rejected the request"
            try:
                failure = response.json()
                if isinstance(failure, dict):
                    candidate = failure.get("message") or failure.get("error")
                    if isinstance(candidate, str):
                        message = redact(candidate[:2000])
            except ValueError:
                pass
            return {"status": "error", "success": False, "http_status": response.status_code,
                "message": message}
        if has_response:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Expected JSON from Heartbeat") from None
            if not isinstance(data, list if is_list else dict) or (isinstance(data, dict) and any(k in data for k in ("error", "errors"))):
                raise ValueError("Unexpected Heartbeat response shape")
            if is_list and any(not isinstance(row, dict) for row in data):
                raise ValueError("Unexpected Heartbeat list item")
        else:
            data = None
        output = {"status": "success", "success": True, "operation": op.operation,
            "http_status": response.status_code, "data": redact(data)}
        if method != "GET":
            output["write_acknowledged"] = True
        await self.emit(output)
        return output
