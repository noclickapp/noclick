"""Userback REST API v1 feedback management using a workspace API token.

Contract: https://dash.readme.com/api/v1/api-registry/p1t0f1vm86v0j4v
Documentation: https://docs.userback.io/reference/overview
Each operation makes one documented request; list operations return one page.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://rest.userback.io/1.0"
ID = Annotated[int, Field(ge=0, le=2147483647)]


class UserbackAPITokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Userback API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.userback.io/reference/authentication",
            "x-credential-instructions": "Paste your Userback REST API token from the token page linked in the authentication documentation. An API-enabled account and Admin permissions are required. NoClick sends it as a Bearer token to rest.userback.io and lists projects to check the connection.",
        },
    )
    credential_type: Literal["userback_api_token"] = Field("userback_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def validate_token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 for c in value):
            raise ValueError("Paste the API token without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _List(_Input):
    page: int = Field(1, ge=1, le=2147483647, description="Page number; each execution reads one page.")
    limit: int = Field(25, ge=1, le=50, description="Maximum records per page.")
    sort: str | None = Field(None, min_length=4, max_length=255, pattern=r"^[a-zA-Z0-9_]+,(asc|desc)$", description="Field and direction, for example id,desc.")
    filter: str | None = Field(None, min_length=1, max_length=1000, description="Userback OData filter expression.")


class _Update(_Input):
    @model_validator(mode="after")
    def require_change(self):
        if not any(value is not None for key, value in self.model_dump().items() if key not in {"operation", "id"}):
            raise ValueError("Provide at least one field to update")
        return self


class UserbackGetCommentConfig(_Input):
    """Get a comment."""
    operation: Literal["get_comment"] = Field("get_comment", json_schema_extra={"ui:hidden": True})
    id: ID = Field(..., description="Userback comment ID.")


class UserbackUpdateCommentConfig(_Update):
    """Update a comment."""
    operation: Literal["update_comment"] = Field("update_comment", json_schema_extra={"ui:hidden": True})
    id: ID = Field(..., description="Userback comment ID.")
    userId: ID | None = Field(None, description='ID is a generic type that is used to represent a unique identifier')
    isPublic: bool | None = Field(None, description='If true, the comment is public and visible to all users.')
    comment: str | None = Field(None, max_length=65535, pattern='.*', description='The contents of the comment.')


class UserbackDeleteCommentConfig(_Input):
    """Delete a comment."""
    operation: Literal["delete_comment"] = Field("delete_comment", json_schema_extra={"ui:hidden": True})
    id: ID = Field(..., description="Userback comment ID.")


class UserbackListCommentsConfig(_List):
    """List comments from a feedback."""
    operation: Literal["list_comments"] = Field("list_comments", json_schema_extra={"ui:hidden": True})


class UserbackCreateCommentConfig(_Input):
    """Comment on a feedback."""
    operation: Literal["create_comment"] = Field("create_comment", json_schema_extra={"ui:hidden": True})
    feedbackId: ID = Field(..., description='ID is a generic type that is used to represent a unique identifier')
    replyCommentId: ID | None = Field(None, description='ID is a generic type that is used to represent a unique identifier')
    comment: str = Field(..., max_length=65535, pattern='.*', description='The contents of the comment.')
    userId: ID | None = Field(None, description='ID is a generic type that is used to represent a unique identifier')
    isPublic: bool | None = Field(None, description='If true, the comment is public and visible to all users.')
    guestEmail: str | None = Field(None, max_length=255, description='The email of the ananymous user who created the comment, if defined.', pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    guestName: str | None = Field(None, max_length=255, pattern='.*', description='The name of the ananymous user who created the comment, if defined.')


class UserbackGetFeedbackConfig(_Input):
    """Get a feedback."""
    operation: Literal["get_feedback"] = Field("get_feedback", json_schema_extra={"ui:hidden": True})
    id: ID = Field(..., description="Userback feedback ID.")


class UserbackUpdateFeedbackConfig(_Update):
    """Update a feedback."""
    operation: Literal["update_feedback"] = Field("update_feedback", json_schema_extra={"ui:hidden": True})
    id: ID = Field(..., description="Userback feedback ID.")
    feedbackType: Literal['General', 'Bug', 'Idea'] | None = Field(None, description='The type of feedback that was given.')
    title: str | None = Field(None, min_length=0, max_length=255, pattern='.*', description='The title provided by the user submitting the Feedback')
    description: str | None = Field(None, min_length=0, max_length=65535, pattern='.*', description='The description provided by the user submitting the Feedback')
    pageUrl: str | None = Field(None, max_length=65535, description='The url of the page where the feedback was submitted', pattern=r'^[a-zA-Z][a-zA-Z0-9+.-]*://[^\s]+$')
    isShared: bool | None = Field(None)
    allowPublicComment: bool | None = Field(None, description='If true, public comments are allowed to be posted on the feedback')
    priority: Literal['low', 'neutral', 'high', 'urgent'] | None = Field(None)
    category: str | None = Field(None, min_length=1, max_length=255, pattern='.*', description='If defined, the category the feedback was assigned to')
    rating: str | None = Field(None, max_length=255, pattern='^star_[1-5]$', description='Defines the rating given by the user submitting the feedback')
    assigneeId: ID | None = Field(None, description='ID is a generic type that is used to represent a unique identifier')
    dueDate: str | None = Field(None, max_length=255, pattern='^\\d{4}-\\d{2}-\\d{2}$', description='Define the due date of the feedback')
    notify: bool | None = Field(None, description='If set to false, notifications to Email, Instant Messengers and Auto-Reply will be supressed.')


class UserbackDeleteFeedbackConfig(_Input):
    """Delete a feedback."""
    operation: Literal["delete_feedback"] = Field("delete_feedback", json_schema_extra={"ui:hidden": True})
    id: ID = Field(..., description="Userback feedback ID.")


class UserbackListFeedbackConfig(_List):
    """List feedbacks."""
    operation: Literal["list_feedback"] = Field("list_feedback", json_schema_extra={"ui:hidden": True})


class UserbackCreateFeedbackConfig(_Input):
    """Create a feedback."""
    operation: Literal["create_feedback"] = Field("create_feedback", json_schema_extra={"ui:hidden": True})
    projectId: ID = Field(..., description='ID is a generic type that is used to represent a unique identifier')
    email: str = Field(..., min_length=3, max_length=255, description='The email of the user who submitted the Feedback', pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    feedbackType: Literal['General', 'Bug', 'Idea'] = Field(..., description='The type of feedback that was given.')
    title: str = Field(..., min_length=0, max_length=255, pattern='.*', description='The title provided by the user submitting the Feedback')
    description: str = Field(..., min_length=0, max_length=65535, pattern='.*', description='The description provided by the user submitting the Feedback')
    name: str | None = Field(None, min_length=0, max_length=255, pattern='.*', description='The name of the user who submitted the Feedback')
    pageUrl: str | None = Field(None, max_length=65535, description='The url of the page where the feedback was submitted', pattern=r'^[a-zA-Z][a-zA-Z0-9+.-]*://[^\s]+$')
    isShared: bool | None = Field(None)
    allowPublicComment: bool | None = Field(None, description='If true, public comments are allowed to be posted on the feedback')
    priority: Literal['low', 'neutral', 'high', 'urgent'] | None = Field(None)
    category: str | None = Field(None, min_length=1, max_length=255, pattern='.*', description='If defined, the category the feedback was assigned to')
    rating: str | None = Field(None, max_length=255, pattern='^star_[1-5]$', description='Defines the rating given by the user submitting the feedback')
    assigneeId: ID | None = Field(None, description='ID is a generic type that is used to represent a unique identifier')
    dueDate: str | None = Field(None, max_length=255, pattern='^\\d{4}-\\d{2}-\\d{2}$', description='Define the due date of the feedback')
    notify: bool | None = Field(None, description='If set to false, notifications to Email, Instant Messengers and Auto-Reply will be supressed.')


class UserbackGetMemberConfig(_Input):
    """Retrieve a Member by Id."""
    operation: Literal["get_member"] = Field("get_member", json_schema_extra={"ui:hidden": True})
    id: ID = Field(..., description="Userback member ID.")


class UserbackUpdateMemberConfig(_Update):
    """Update member information."""
    operation: Literal["update_member"] = Field("update_member", json_schema_extra={"ui:hidden": True})
    id: ID = Field(..., description="Userback member ID.")
    name: str = Field(..., min_length=1, max_length=255, pattern='.*', description='The name of the user.')


class UserbackListMembersConfig(_List):
    """List available members."""
    operation: Literal["list_members"] = Field("list_members", json_schema_extra={"ui:hidden": True})


class UserbackGetProjectConfig(_Input):
    """Retrieve a project by Id."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})
    id: ID = Field(..., description="Userback project ID.")


class UserbackUpdateProjectConfig(_Update):
    """Update project information."""
    operation: Literal["update_project"] = Field("update_project", json_schema_extra={"ui:hidden": True})
    id: ID = Field(..., description="Userback project ID.")
    name: str | None = Field(None, max_length=255, pattern='.*', description='Project name')
    url: str | None = Field(None, max_length=65535, description='Project url', pattern=r'^[a-zA-Z][a-zA-Z0-9+.-]*://[^\s]+$')


class UserbackListProjectsConfig(_List):
    """List available projects."""
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})


class UserbackGetSessionRecordingConfig(_Input):
    """Get a SessionRecording."""
    operation: Literal["get_session_recording"] = Field("get_session_recording", json_schema_extra={"ui:hidden": True})
    id: ID = Field(..., description="Userback session recording ID.")


class UserbackListSessionRecordingsConfig(_List):
    """List SessionRecordings."""
    operation: Literal["list_session_recordings"] = Field("list_session_recordings", json_schema_extra={"ui:hidden": True})


class UserbackListWorkflowsConfig(_List):
    """List workflows."""
    operation: Literal["list_workflows"] = Field("list_workflows", json_schema_extra={"ui:hidden": True})


class UserbackCreateWorkflowConfig(_Input):
    """Create a workflow."""
    operation: Literal["create_workflow"] = Field("create_workflow", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255, pattern='^[\\w\\-\\s\\.\\!\\#]+$', description='The name of the workflow')
    color: str = Field(..., max_length=7, pattern='^#([A-F0-9]{6}|[A-F0-9]{3})$', description='The color of the workflow in a hex format')
    projectId: ID = Field(..., description='ID is a generic type that is used to represent a unique identifier')


class UserbackUpdateWorkflowConfig(_Update):
    """Update a workflow."""
    operation: Literal["update_workflow"] = Field("update_workflow", json_schema_extra={"ui:hidden": True})
    id: ID = Field(..., description="Userback workflow ID.")
    name: str | None = Field(None, min_length=1, max_length=255, pattern='^[\\w\\-\\s\\.\\!\\#]+$', description='The name of the workflow')
    color: str | None = Field(None, max_length=7, pattern='^#([A-F0-9]{6}|[A-F0-9]{3})$', description='The color of the workflow in a hex format')


class UserbackDeleteWorkflowConfig(_Input):
    """Delete a workflow."""
    operation: Literal["delete_workflow"] = Field("delete_workflow", json_schema_extra={"ui:hidden": True})
    id: ID = Field(..., description="Userback workflow ID.")


# Userback's own MCP server: agents get its tools through a person's Userback sign-in.
UserbackMcpCredential = mcp_credential("userback", "https://mcp.userback.io/v1/mcp/", app="Userback")
UserbackCredential = Union[UserbackAPITokenCredential, UserbackMcpCredential]


UserbackOperation = Annotated[Union[
    UserbackGetCommentConfig,
    UserbackUpdateCommentConfig,
    UserbackDeleteCommentConfig,
    UserbackListCommentsConfig,
    UserbackCreateCommentConfig,
    UserbackGetFeedbackConfig,
    UserbackUpdateFeedbackConfig,
    UserbackDeleteFeedbackConfig,
    UserbackListFeedbackConfig,
    UserbackCreateFeedbackConfig,
    UserbackGetMemberConfig,
    UserbackUpdateMemberConfig,
    UserbackListMembersConfig,
    UserbackGetProjectConfig,
    UserbackUpdateProjectConfig,
    UserbackListProjectsConfig,
    UserbackGetSessionRecordingConfig,
    UserbackListSessionRecordingsConfig,
    UserbackListWorkflowsConfig,
    UserbackCreateWorkflowConfig,
    UserbackUpdateWorkflowConfig,
    UserbackDeleteWorkflowConfig
], Field(discriminator="operation")]


class UserbackConfig(NodeConfig[UserbackOperation, UserbackCredential]):
    pass


ROUTES = {
    'get_comment': ('GET', '/feedback/comment/{id}'),
    'update_comment': ('PATCH', '/feedback/comment/{id}'),
    'delete_comment': ('DELETE', '/feedback/comment/{id}'),
    'list_comments': ('GET', '/feedback/comment'),
    'create_comment': ('POST', '/feedback/comment'),
    'get_feedback': ('GET', '/feedback/{id}'),
    'update_feedback': ('PATCH', '/feedback/{id}'),
    'delete_feedback': ('DELETE', '/feedback/{id}'),
    'list_feedback': ('GET', '/feedback'),
    'create_feedback': ('POST', '/feedback'),
    'get_member': ('GET', '/member/{id}'),
    'update_member': ('PATCH', '/member/{id}'),
    'list_members': ('GET', '/member'),
    'get_project': ('GET', '/project/{id}'),
    'update_project': ('PATCH', '/project/{id}'),
    'list_projects': ('GET', '/project'),
    'get_session_recording': ('GET', '/sessionRecording/{id}'),
    'list_session_recordings': ('GET', '/sessionRecording'),
    'list_workflows': ('GET', '/workflow'),
    'create_workflow': ('POST', '/workflow'),
    'update_workflow': ('PATCH', '/workflow/{id}'),
    'delete_workflow': ('DELETE', '/workflow/{id}'),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {str(key).replace(token, "[redacted]"): _redact(item, token) for key, item in value.items()}
    return value


class UserbackNode(WorkflowNode):
    integration_type = "automation-userback"
    credential_provider_labels = {"userback": "Userback Account"}
    connection_evidence = ConnectionEvidence(noun="projects", operation="list_projects", label_keys=("name", "id"))
    edit_examples = ["Create feedback from a support ticket", "Add a comment to feedback", "List projects", "Update feedback priority"]

    @classmethod
    def get_config_model(cls):
        return UserbackConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Userback API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, route = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation", "id"})
        route = route.replace("{id}", str(getattr(config, "id", "")))
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False) as client:
                response = await client.request(
                    method, BASE_URL + route,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    params=values if method == "GET" else None,
                    json=values if method in {"POST", "PATCH"} else None,
                )
        except httpx.HTTPError:
            return {"status": "unknown" if method != "GET" else "error", "operation": config.operation,
                    "error": "Userback request did not complete; inspect writes before retrying"}
        try:
            payload = response.json()
        except ValueError:
            return {"status": "error", "operation": config.operation, "http_status": response.status_code,
                    "error": "Userback returned a non-JSON response"}
        payload = _redact(payload, token)
        if not 200 <= response.status_code < 300:
            return {"status": "error", "operation": config.operation, "http_status": response.status_code,
                    "status_code": response.status_code,
                    "error": payload.get("message", str(payload)) if isinstance(payload, dict) else str(payload),
                    "details": payload}
        if method == "DELETE":
            if payload is not True:
                raise ValueError("Userback did not accept the deletion")
            return {"status": "success", "operation": config.operation, "http_status": response.status_code,
                    "accepted": True, "deletion_verified": False, "id": config.id}
        if not isinstance(payload, dict):
            raise ValueError("Userback returned an unexpected response shape")
        if config.operation.startswith("list_"):
            if not isinstance(payload.get("data"), list) or not isinstance(payload.get("_pagination"), dict):
                raise ValueError("Userback returned an invalid list page")
            return {"status": "success", "operation": config.operation, "http_status": response.status_code,
                    **payload}
        if not isinstance(payload.get("id"), int) or isinstance(payload.get("id"), bool):
            raise ValueError("Userback response is missing its resource ID")
        if getattr(config, "id", payload["id"]) != payload["id"]:
            raise ValueError("Userback returned a different resource ID")
        return {"status": "success", "operation": config.operation, "http_status": response.status_code, "data": payload}
