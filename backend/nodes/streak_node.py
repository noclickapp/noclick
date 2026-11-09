"""Streak v2 CRM actions, pinned to the provider's published API contract.

Authentication: https://streak.readme.io/docs/authentication
API keys carry the user's permissions. Writes issue a single request and are
never retried automatically. List responses preserve provider pagination.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.streak.com/api/v2"
CREDENTIAL_TYPE = "streak_api_key"


class StreakAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Streak API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://streak.readme.io/docs/authentication",
            "x-credential-instructions": "In Gmail, open Streak in the right sidebar, choose Integrations, then create a key under Streak API. Paste the API key here. It has the same permissions as your Streak account.",
        },
    )
    credential_type: Literal["streak_api_key"] = Field(
        "streak_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        title="API Key",
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your Streak API key")
        value = clean_secret(value, field_name="API key", key=True)
        if ":" in value or any(
            c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value
        ):
            raise ValueError(
                "Paste only the API key, without a Basic header or password"
            )
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Assignee(_Input):
    email: str = Field(..., min_length=3, max_length=254, title="Assignee Email")


class ListTeams(_Input):
    """Get my teams."""

    operation: Literal["list_teams"] = Field(
        "list_teams", title="List Teams", json_schema_extra={"ui:hidden": True}
    )


class GetTeam(_Input):
    """Get a team."""

    operation: Literal["get_team"] = Field(
        "get_team", title="Get Team", json_schema_extra={"ui:hidden": True}
    )
    teamKey: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        pattern=r"^[A-Za-z0-9_-]+$",
        title="Team Key",
    )


class CreateBox(_Input):
    """Create a box."""

    operation: Literal["create_box"] = Field(
        "create_box", title="Create Box", json_schema_extra={"ui:hidden": True}
    )
    pipelineKey: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        pattern=r"^[A-Za-z0-9_-]+$",
        title="Pipeline Key",
    )
    name: str = Field(
        ..., min_length=1, max_length=100000, description="The name of this box"
    )
    stageKey: str | None = Field(
        None, max_length=100000, description="The stage of this box"
    )
    notes: str | None = Field(
        None, max_length=100000, description="The notes on the box"
    )
    assignedToSharingEntries: str | None = Field(
        None,
        max_length=100000,
        description="JSON-encoded array of objects with email properties. Assignees must have pipeline access.",
    )

    @field_validator("assignedToSharingEntries")
    @classmethod
    def encoded_assignees(cls, value):
        if value is not None:
            rows = json.loads(value)
            if not isinstance(rows, list):
                raise ValueError("Use a JSON array of assignee email objects")
            for row in rows:
                Assignee.model_validate(row)
        return value


class GetContact(_Input):
    """Get a contact."""

    operation: Literal["get_contact"] = Field(
        "get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True}
    )
    contactKey: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        pattern=r"^[A-Za-z0-9_-]+$",
        title="Contact Key",
    )


class CreateContact(_Input):
    """Create a contact."""

    operation: Literal["create_contact"] = Field(
        "create_contact", title="Create Contact", json_schema_extra={"ui:hidden": True}
    )
    teamKey: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        pattern=r"^[A-Za-z0-9_-]+$",
        title="Team Key",
    )
    emailAddresses: list[str] = Field(
        ...,
        description="The only email addresses associated with the contact will be the ones you include here; make sure to include any previously associated addresses as well as the new one(s).",
    )
    givenName: str | None = Field(None, max_length=100000, description="First name")
    familyName: str | None = Field(None, max_length=100000, description="Last name")
    title: str | None = Field(
        None, max_length=100000, description="Contact's title/description"
    )
    other: str | None = Field(
        None, max_length=100000, description="Notes or other uncategorized information."
    )
    addresses: list[str] | None = Field(
        None,
        description="The only addresses associated with the contact will be the ones you include here; make sure to include any previously associated addresses as well as the new one(s).",
    )
    phoneNumbers: list[str] | None = Field(
        None,
        description="The only phone numbers associated with the contact will be the ones you include here; make sure to include any previously associated numbers as well as the new one(s).",
    )
    twitterHandle: str | None = Field(
        None, max_length=100000, description="twitterHandle"
    )
    facebookHandle: str | None = Field(
        None, max_length=100000, description="facebookHandle"
    )
    linkedinHandle: str | None = Field(
        None, max_length=100000, description="linkedinHandle"
    )
    photoUrl: str | None = Field(None, max_length=100000, description="photoUrl")


class UpdateContact(_Input):
    """Update a contact."""

    operation: Literal["update_contact"] = Field(
        "update_contact", title="Update Contact", json_schema_extra={"ui:hidden": True}
    )
    contactKey: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        pattern=r"^[A-Za-z0-9_-]+$",
        title="Contact Key",
    )
    givenName: str | None = Field(None, max_length=100000, description="First name")
    familyName: str | None = Field(None, max_length=100000, description="Last name")
    emailAddresses: list[str] | None = Field(
        None,
        description="The only email addresses associated with the contact will be the ones you include here; make sure to include any previously associated addresses as well as the new one(s).",
    )
    title: str | None = Field(
        None, max_length=100000, description="Contact's title/description"
    )
    other: str | None = Field(
        None, max_length=100000, description="Notes or other uncategorized information."
    )
    addresses: list[str] | None = Field(
        None,
        description="The only addresses associated with the contact will be the ones you include here; make sure to include any previously associated addresses as well as the new one(s).",
    )
    phoneNumbers: list[str] | None = Field(
        None,
        description="The only phone numbers associated with the contact will be the ones you include here; make sure to include any previously associated numbers as well as the new one(s).",
    )
    twitterHandle: str | None = Field(
        None, max_length=100000, description="twitterHandle"
    )
    facebookHandle: str | None = Field(
        None, max_length=100000, description="facebookHandle"
    )
    linkedinHandle: str | None = Field(
        None, max_length=100000, description="linkedinHandle"
    )
    photoUrl: str | None = Field(None, max_length=100000, description="photoUrl")

    @model_validator(mode="after")
    def changes(self):
        if not any(
            v is not None
            for k, v in self.model_dump().items()
            if k not in {"operation", "contactKey"}
        ):
            raise ValueError("Provide at least one field to update")
        return self


class DeleteContact(_Input):
    """Delete a contact."""

    operation: Literal["delete_contact"] = Field(
        "delete_contact", title="Delete Contact", json_schema_extra={"ui:hidden": True}
    )
    contactKey: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        pattern=r"^[A-Za-z0-9_-]+$",
        title="Contact Key",
    )


class GetContactBoxes(_Input):
    """Get contact boxes."""

    operation: Literal["get_contact_boxes"] = Field(
        "get_contact_boxes",
        title="Get Contact Boxes",
        json_schema_extra={"ui:hidden": True},
    )
    contactKey: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        pattern=r"^[A-Za-z0-9_-]+$",
        title="Contact Key",
    )


class GetOrganization(_Input):
    """Get an Organization."""

    operation: Literal["get_organization"] = Field(
        "get_organization",
        title="Get Organization",
        json_schema_extra={"ui:hidden": True},
    )
    organizationKey: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        pattern=r"^[A-Za-z0-9_-]+$",
        title="Organization Key",
    )


class UpdateOrganization(_Input):
    """Update an organization."""

    operation: Literal["update_organization"] = Field(
        "update_organization",
        title="Update Organization",
        json_schema_extra={"ui:hidden": True},
    )
    organizationKey: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        pattern=r"^[A-Za-z0-9_-]+$",
        title="Organization Key",
    )
    name: str | None = Field(None, max_length=100000, description="Organization name")
    industry: str | None = Field(
        None, max_length=100000, description="Organization industry"
    )
    employeeCount: str | None = Field(
        None, max_length=100000, description="Employee count at the organization"
    )
    other: str | None = Field(
        None, max_length=100000, description="Notes or other uncategorized information."
    )
    twitterHandle: str | None = Field(
        None, max_length=100000, description="twitterHandle"
    )
    facebookHandle: str | None = Field(
        None, max_length=100000, description="facebookHandle"
    )
    linkedinHandle: str | None = Field(
        None, max_length=100000, description="linkedinHandle"
    )

    @model_validator(mode="after")
    def changes(self):
        if not any(
            v is not None
            for k, v in self.model_dump().items()
            if k not in {"operation", "organizationKey"}
        ):
            raise ValueError("Provide at least one field to update")
        return self


class DeleteOrganization(_Input):
    """Delete an organization."""

    operation: Literal["delete_organization"] = Field(
        "delete_organization",
        title="Delete Organization",
        json_schema_extra={"ui:hidden": True},
    )
    organizationKey: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        pattern=r"^[A-Za-z0-9_-]+$",
        title="Organization Key",
    )


class GetTask(_Input):
    """Get a task."""

    operation: Literal["get_task"] = Field(
        "get_task", title="Get Task", json_schema_extra={"ui:hidden": True}
    )
    taskKey: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        pattern=r"^[A-Za-z0-9_-]+$",
        title="Task Key",
    )


class ListBoxTasks(_Input):
    """Get tasks in a box."""

    operation: Literal["list_box_tasks"] = Field(
        "list_box_tasks", title="List Box Tasks", json_schema_extra={"ui:hidden": True}
    )
    boxKey: str = Field(
        ..., min_length=1, max_length=2048, pattern=r"^[A-Za-z0-9_-]+$", title="Box Key"
    )


class CreateTask(_Input):
    """Create a task."""

    operation: Literal["create_task"] = Field(
        "create_task", title="Create Task", json_schema_extra={"ui:hidden": True}
    )
    boxKey: str = Field(
        ..., min_length=1, max_length=2048, pattern=r"^[A-Za-z0-9_-]+$", title="Box Key"
    )
    text: str = Field(
        ..., min_length=1, max_length=100000, description="Task description"
    )
    dueDate: int | None = Field(
        None, ge=0, description="Milliseconds since epoch (eg `1504213700003`)"
    )
    assignedToSharingEntries: list[Assignee] | None = Field(
        None,
        description="Each object needs a key of `email` and a value of the assignee's email.",
    )


class UpdateTask(_Input):
    """Update a task."""

    operation: Literal["update_task"] = Field(
        "update_task", title="Update Task", json_schema_extra={"ui:hidden": True}
    )
    taskKey: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        pattern=r"^[A-Za-z0-9_-]+$",
        title="Task Key",
    )
    text: str | None = Field(
        None, max_length=100000, description="Updated task description"
    )
    dueDate: int | None = Field(
        None, ge=0, description="Updated dueDate (in MS since epoch)"
    )
    status: Literal["DONE", "NOT_DONE"] | None = Field(
        None, description="Either `DONE` or `NOT_DONE`"
    )
    assignedToSharingEntries: list[Assignee] | None = Field(
        None,
        description="Each object needs a key of `email` and a value of the assignee's email.",
    )

    @model_validator(mode="after")
    def changes(self):
        if not any(
            v is not None
            for k, v in self.model_dump().items()
            if k not in {"operation", "taskKey"}
        ):
            raise ValueError("Provide at least one field to update")
        return self


class DeleteTask(_Input):
    """Delete a task."""

    operation: Literal["delete_task"] = Field(
        "delete_task", title="Delete Task", json_schema_extra={"ui:hidden": True}
    )
    taskKey: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        pattern=r"^[A-Za-z0-9_-]+$",
        title="Task Key",
    )


class GetComment(_Input):
    """Get a comment."""

    operation: Literal["get_comment"] = Field(
        "get_comment", title="Get Comment", json_schema_extra={"ui:hidden": True}
    )
    commentKey: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        pattern=r"^[A-Za-z0-9_-]+$",
        title="Comment Key",
    )


class CreateComment(_Input):
    """Create a comment."""

    operation: Literal["create_comment"] = Field(
        "create_comment", title="Create Comment", json_schema_extra={"ui:hidden": True}
    )
    boxKey: str = Field(
        ..., min_length=1, max_length=2048, pattern=r"^[A-Za-z0-9_-]+$", title="Box Key"
    )
    message: str = Field(
        ..., min_length=1, max_length=100000, description="The text of the comment."
    )


class UpdateComment(_Input):
    """Update a comment."""

    operation: Literal["update_comment"] = Field(
        "update_comment", title="Update Comment", json_schema_extra={"ui:hidden": True}
    )
    commentKey: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        pattern=r"^[A-Za-z0-9_-]+$",
        title="Comment Key",
    )
    message: str = Field(
        ..., min_length=1, max_length=100000, description="The updated message text"
    )

    @model_validator(mode="after")
    def changes(self):
        if not any(
            v is not None
            for k, v in self.model_dump().items()
            if k not in {"operation", "commentKey"}
        ):
            raise ValueError("Provide at least one field to update")
        return self


class DeleteComment(_Input):
    """Delete a comment."""

    operation: Literal["delete_comment"] = Field(
        "delete_comment", title="Delete Comment", json_schema_extra={"ui:hidden": True}
    )
    commentKey: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        pattern=r"^[A-Za-z0-9_-]+$",
        title="Comment Key",
    )


Operation = Annotated[
    Union[
        ListTeams,
        GetTeam,
        CreateBox,
        GetContact,
        CreateContact,
        UpdateContact,
        DeleteContact,
        GetContactBoxes,
        GetOrganization,
        UpdateOrganization,
        DeleteOrganization,
        GetTask,
        ListBoxTasks,
        CreateTask,
        UpdateTask,
        DeleteTask,
        GetComment,
        CreateComment,
        UpdateComment,
        DeleteComment,
    ],
    Field(discriminator="operation"),
]


class StreakConfig(NodeConfig[Operation, StreakAPIKeyCredential]):
    pass


ROUTES = {
    "list_teams": ("GET", "/users/me/teams"),
    "get_team": ("GET", "/teams/{teamKey}"),
    "create_box": ("POST", "/pipelines/{pipelineKey}/boxes"),
    "get_contact": ("GET", "/contacts/{contactKey}"),
    "create_contact": ("POST", "/teams/{teamKey}/contacts/"),
    "update_contact": ("POST", "/contacts/{contactKey}"),
    "delete_contact": ("DELETE", "/contacts/{contactKey}"),
    "get_contact_boxes": ("GET", "/contacts/{contactKey}/boxes"),
    "get_organization": ("GET", "/organizations/{organizationKey}"),
    "update_organization": ("POST", "/organizations/{organizationKey}"),
    "delete_organization": ("DELETE", "/organizations/{organizationKey}"),
    "get_task": ("GET", "/tasks/{taskKey}"),
    "list_box_tasks": ("GET", "/boxes/{boxKey}/tasks"),
    "create_task": ("POST", "/boxes/{boxKey}/tasks"),
    "update_task": ("POST", "/tasks/{taskKey}"),
    "delete_task": ("DELETE", "/tasks/{taskKey}"),
    "get_comment": ("GET", "/comments/{commentKey}"),
    "create_comment": ("POST", "/boxes/{boxKey}/comments"),
    "update_comment": ("POST", "/comments/{commentKey}"),
    "delete_comment": ("DELETE", "/comments/{commentKey}"),
}


class StreakNode(WorkflowNode):
    integration_type = "automation-streak"
    connection_evidence = ConnectionEvidence(
        operation="list_teams", noun="Streak teams"
    )

    @classmethod
    def get_config_model(cls):
        return StreakConfig

    async def execute(self, inputs):
        if not isinstance(self.config, StreakConfig) or not self.config.credentials:
            raise ValueError("Connect a Streak API key")
        config = self.config.config
        method, template = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        path_fields = [k for k in values if "{" + k + "}" in template]
        path = template
        for key in path_fields:
            path = path.replace("{" + key + "}", quote(values[key], safe=""))
        body = {k: v for k, v in values.items() if k not in {"operation", *path_fields}}
        if config.operation == "create_task":
            body["key"] = config.boxKey
        kwargs = {"json": body} if method == "POST" else {}
        # An API key is the Basic username; the password must be empty.
        auth = httpx.BasicAuth(self.config.credentials.api_key, "")
        async with guarded_async_client(
            timeout=30, trust_env=False, follow_redirects=False
        ) as client:
            response = await client.request(
                method,
                BASE_URL + path,
                auth=auth,
                headers={"Accept": "application/json"},
                **kwargs,
            )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("Streak returned an unexpected JSON response")
        if isinstance(data, dict) and (
            data.get("success") is False or data.get("error") or data.get("errors")
        ):
            raise ValueError("Streak did not confirm the operation")
        return {"status": "success", "operation": config.operation, "data": data}
