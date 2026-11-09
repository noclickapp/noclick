"""Ninety Public API v1: personal-token operations against its published contract."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.public.ninety.io"


class NinetyPersonalTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Ninety Personal Access Token",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.ninety.io/settings/user/developer-settings",
            "x-credential-instructions": "In Ninety, open Settings → User → Developer Settings and generate a personal access token. Paste it here. The token acts with your Ninety permissions; company-wide reads may require an Owner or Admin. NoClick checks the connection by reading your Teams.",
        },
    )
    credential_type: Literal["ninety_personal_token"] = Field(
        "ninety_personal_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., min_length=1, title="Personal access token", json_schema_extra={"ui:widget": "password"}
    )

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if any(char.isspace() for char in value):
            raise ValueError("Paste only the token, without a Bearer prefix")
        return value


class NinetyInput(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def dates(cls, value, info):
        if value is not None and info.field_name in {
            "dueDate",
            "completedDate",
            "periodStartDate",
            "rockQuarterYearDueDate",
            "scoresFrom",
            "scoresTo",
        }:
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("Use a real ISO 8601 date or datetime") from None
        return value

    @model_validator(mode="after")
    def related_fields(self):
        if bool(getattr(self, "linkedItemId", None)) != bool(getattr(self, "linkedItemType", None)):
            raise ValueError("Provide linkedItemId and linkedItemType together")
        if getattr(self, "isDone", False) and not getattr(self, "completedDate", None):
            raise ValueError("Provide completedDate when marking a Milestone done")
        if getattr(self, "scoresFrom", None) and getattr(self, "scoresTo", None):
            start, end = date.fromisoformat(self.scoresFrom), date.fromisoformat(self.scoresTo)
            if not 0 <= (end - start).days <= 366:
                raise ValueError("Score dates must be ordered and span at most 366 days")
        return self


class NinetyRockData(NinetyInput):
    teamId: str = Field(
        ..., min_length=1, description="The Id of the team the Rock belongs to", examples=["507f1f77bcf86cd799439011"]
    )
    title: str = Field(
        ..., min_length=1, description="The title of the Rock", examples=["Launch new customer onboarding flow"]
    )
    dueDate: str = Field(
        ..., min_length=1, description="The due date of the Rock (ISO 8601)", examples=["2026-06-30T23:59:59.000Z"]
    )
    statusCode: Literal["OFF_TRACK", "ON_TRACK", "DONE", "CANCELED", "DRAFT"] = Field(
        ...,
        min_length=1,
        description="The status of the Rock — `OFF_TRACK` · `ON_TRACK` · `DONE` · `CANCELED` · `DRAFT`",
        examples=["ON_TRACK"],
    )
    levelCode: Literal["USER", "COMPANY_AND_DEPARTMENT", "COMPANY", "DEPARTMENT"] = Field(
        ...,
        min_length=1,
        description="The level of the Rock — `USER` · `COMPANY_AND_DEPARTMENT` · `COMPANY` · `DEPARTMENT`",
        examples=["USER"],
    )
    quarter: Literal["Q1", "Q2", "Q3", "Q4", "None"] = Field(
        ...,
        min_length=1,
        description="The quarter associated with the Rock — `Q1` · `Q2` · `Q3` · `Q4` · `None`",
        examples=["Q2"],
    )
    description: str | None = Field(
        None,
        description="The description of the Rock",
        examples=["Redesign the onboarding wizard to reduce drop-off by 20%"],
    )
    additionalTeamIds: list[str] | None = Field(
        None,
        description="Array of additional team Ids that can also view this Rock",
        examples=[["507f1f77bcf86cd799439022", "507f1f77bcf86cd799439033"]],
    )
    futureScope: Literal["Current", "Next", "Later", "Future"] | None = Field(
        None, description="The future scope of the Rock — `Current` · `Next` · `Later` · `Future`", examples=["Current"]
    )
    rockQuarterYearDueDate: str | None = Field(
        None,
        description="The quarter-aligned year due date of the Rock (ISO 8601)",
        examples=["2026-06-30T23:59:59.999Z"],
    )


class NinetyListTeamsConfig(NinetyInput):
    """Get Teams."""

    operation: Literal["list_teams"] = Field("list_teams", json_schema_extra={"ui:hidden": True})


class NinetyListUsersConfig(NinetyInput):
    """List Users in your company."""

    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    includeInactive: StrictBool | None = Field(
        None,
        description="Include deactivated Users in the response. Defaults to `false`, so only active Users are returned.",
        examples=[False],
    )
    email: str | None = Field(
        None,
        description="Return only the User at this email address, matched case-insensitively against the `primaryEmail` in the response. An address nobody in the company uses returns an empty array, not an error.",
        examples=["jane.doe@example.com"],
    )


class NinetyListTodosConfig(NinetyInput):
    """List company To-Dos."""

    operation: Literal["list_todos"] = Field("list_todos", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=100, description="Maximum number of items to return")
    nextToken: str | None = Field(
        None,
        description="Opaque cursor from a previous response's `pagination.nextToken`. Omit to fetch the first page.",
    )
    completed: StrictBool | None = Field(None, description="Filter by completed status", examples=[False])
    archived: StrictBool | None = Field(None, description="Include archived To-Dos (excluded by default)")
    deleted: StrictBool | None = Field(None, description="Include deleted To-Dos (excluded by default)")
    searchText: str | None = Field(
        None, description="Search text to match against title, description, and comments", examples=["follow up"]
    )
    title: str | None = Field(None, description="Filter by title match", examples=["Follow up with client"])
    sortBy: Literal["createdDate", "completedDate", "title"] | None = Field(
        None, description="Field to sort results by. Defaults to insertion order when omitted."
    )
    sortOrder: Literal["asc", "desc"] | None = Field(None, description="Sort direction")


class NinetyGetTodoConfig(NinetyInput):
    """Get a To-Do by Id."""

    operation: Literal["get_todo"] = Field("get_todo", json_schema_extra={"ui:hidden": True})
    todo_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="The To-Do Id",
        examples=["507f1f77bcf86cd799439011"],
    )


class NinetyCreateTodoConfig(NinetyInput):
    """Create a To-Do."""

    operation: Literal["create_todo"] = Field("create_todo", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1, description="The title of the To-Do", examples=["Follow up with client"])
    description: str | None = Field(None, description="The description of the To-Do", examples=["Send the Q2 proposal"])
    dueDate: str | None = Field(None, description="Due date in YYYY-MM-DD format", examples=["2024-03-15"])
    teamId: str | None = Field(
        None,
        description="The Id of the team to assign this To-Do to. Omit or pass an empty string for a personal To-Do.",
        examples=["507f1f77bcf86cd799439011"],
    )
    repeat: str | None = Field(
        None, description="Recurrence pattern for the To-Do (e.g., `weekly`, `monthly`)", examples=["weekly"]
    )
    userId: str | None = Field(
        None,
        description="Id of the user to assign the To-Do to. Defaults to the authenticated user.",
        examples=["507f1f77bcf86cd799439013"],
    )
    linkedItemId: str | None = Field(
        None,
        description="The Id of a Rock, Issue, or Milestone to link this To-Do to. Must be provided together with `linkedItemType`. The linked item must belong to the same company as the authenticated caller.",
        examples=["507f1f77bcf86cd799439015"],
    )
    linkedItemType: Literal["rock", "issue", "milestone"] | None = Field(
        None, description="The type of item `linkedItemId` refers to.", examples=["rock"]
    )


class NinetyUpdateTodoConfig(NinetyInput):
    """Update a To-Do."""

    operation: Literal["update_todo"] = Field("update_todo", json_schema_extra={"ui:hidden": True})
    todo_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="The To-Do Id",
        examples=["507f1f77bcf86cd799439011"],
    )
    completed: StrictBool | None = Field(None, description="Whether the todo is completed")
    archived: StrictBool | None = Field(None, description="Whether the todo is archived")
    dueDate: str | None = Field(None, description="Due date in ISO format")
    teamId: str | None = Field(None, description="The team Id")
    title: str | None = Field(None, description="The title of the todo")
    description: str | None = Field(None, description="The description of the todo")
    repeat: str | None = Field(None, description="Repeat pattern")
    userId: str | None = Field(None, description="User Id to assign the To-Do to")
    linkedItemId: str | None = Field(
        None,
        description="The Id of a Rock, Issue, or Milestone to link this existing To-Do to. Must be provided together with `linkedItemType`. The linked item must belong to the same company as the authenticated caller.",
        examples=["507f1f77bcf86cd799439015"],
    )
    linkedItemType: Literal["rock", "issue", "milestone"] | None = Field(
        None, description="The type of item `linkedItemId` refers to.", examples=["rock"]
    )


class NinetyDeleteTodoConfig(NinetyInput):
    """Delete a To-Do."""

    operation: Literal["delete_todo"] = Field("delete_todo", json_schema_extra={"ui:hidden": True})
    todo_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="The To-Do Id",
        examples=["507f1f77bcf86cd799439011"],
    )


class NinetyCommentTodoConfig(NinetyInput):
    """Add a comment to a To-Do."""

    operation: Literal["comment_todo"] = Field("comment_todo", json_schema_extra={"ui:hidden": True})
    todo_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="The To-Do Id",
        examples=["507f1f77bcf86cd799439011"],
    )
    text: str = Field(
        ...,
        min_length=1,
        description="The comment text. HTML is sanitized upstream, so send plain text unless you specifically need formatting.",
        examples=["Agreed - lets revisit this next week."],
    )


class NinetyListIssuesConfig(NinetyInput):
    """List company Issues."""

    operation: Literal["list_issues"] = Field("list_issues", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=100, description="Maximum number of items to return")
    nextToken: str | None = Field(
        None,
        description="Opaque cursor from a previous response's `pagination.nextToken`. Omit to fetch the first page.",
    )
    completed: StrictBool | None = Field(None, description="Filter by completed status", examples=[False])
    archived: StrictBool | None = Field(None, description="Include archived Issues (excluded by default)")
    deleted: StrictBool | None = Field(None, description="Include deleted Issues (excluded by default)")
    searchText: str | None = Field(
        None, description="Search text to match against title, description, and comments", examples=["follow up"]
    )
    title: str | None = Field(None, description="Filter by title match", examples=["Cash flow projections are off"])
    sortBy: Literal["createdDate", "completedDate", "title", "id"] | None = Field(
        None,
        description="Field to sort results by. `id` sorts by creation order and is the default when omitted. `_id` is a deprecated alias for `id`, still accepted for existing callers.",
    )
    sortOrder: Literal["asc", "desc"] | None = Field(None, description="Sort direction")


class NinetyGetIssueConfig(NinetyInput):
    """Get an Issue by Id."""

    operation: Literal["get_issue"] = Field("get_issue", json_schema_extra={"ui:hidden": True})
    issue_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="The Issue Id",
        examples=["507f1f77bcf86cd799439011"],
    )


class NinetyCreateIssueConfig(NinetyInput):
    """Create an Issue."""

    operation: Literal["create_issue"] = Field("create_issue", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1, description="Title of the Issue", examples=["Cash flow projections are off"])
    teamId: str = Field(
        ..., min_length=1, description="Id of the team that owns the Issue", examples=["507f1f77bcf86cd799439011"]
    )
    interval: Literal["SHORT_TERM", "LONG_TERM"] | None = Field(
        None, description="Issue classification. Defaults to `SHORT_TERM` if not provided.", examples=["SHORT_TERM"]
    )
    description: str | None = Field(
        None,
        description="HTML description of the Issue",
        examples=["<p>Revenue projections are inconsistent with actuals.</p>"],
    )
    priority: float | None = Field(
        None,
        ge=0,
        le=5,
        description="Priority of the Issue on a 0-5 scale where **5 is the highest** priority and 1 the lowest. Omit or pass `0` for no priority.",
        examples=[3],
    )
    linkedItemId: str | None = Field(
        None,
        description="The Id of a To-Do, Rock, or Milestone to link the new Issue to. Must be provided together with `linkedItemType`. The linked item must belong to the same company as the authenticated caller.",
        examples=["507f1f77bcf86cd799439015"],
    )
    linkedItemType: Literal["todo", "rock", "milestone"] | None = Field(
        None, description="The type of item `linkedItemId` refers to.", examples=["rock"]
    )
    userId: str | None = Field(
        None,
        description="Id of the user to assign the Issue to. Defaults to the authenticated user. Must be a user in the authenticated user's company - assigning outside it is rejected.",
        examples=["507f1f77bcf86cd799439013"],
    )


class NinetyUpdateIssueConfig(NinetyInput):
    """Update an Issue."""

    operation: Literal["update_issue"] = Field("update_issue", json_schema_extra={"ui:hidden": True})
    issue_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="The Issue Id",
        examples=["507f1f77bcf86cd799439011"],
    )
    title: str | None = Field(None, description="Title of the Issue")
    teamId: str | None = Field(None, description="Id of the team that owns the Issue")
    interval: Literal["SHORT_TERM", "LONG_TERM"] | None = Field(
        None, description="Interval classification for the Issue"
    )
    description: str | None = Field(None, description="HTML description of the Issue")
    priority: float | None = Field(
        None,
        ge=0,
        le=5,
        description="Priority of the Issue on a 0-5 scale where **5 is the highest** priority and 1 the lowest. Pass `0` to clear the priority.",
    )
    completed: StrictBool | None = Field(None, description="Whether the Issue is completed")
    linkedItemId: str | None = Field(
        None,
        description="The Id of a To-Do, Rock, or Milestone to link this existing Issue to. Must be provided together with `linkedItemType`. The linked item must belong to the same company as the authenticated caller.",
        examples=["507f1f77bcf86cd799439015"],
    )
    linkedItemType: Literal["todo", "rock", "milestone"] | None = Field(
        None, description="The type of item `linkedItemId` refers to.", examples=["rock"]
    )


class NinetyDeleteIssueConfig(NinetyInput):
    """Delete an Issue."""

    operation: Literal["delete_issue"] = Field("delete_issue", json_schema_extra={"ui:hidden": True})
    issue_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="The Issue Id",
        examples=["507f1f77bcf86cd799439011"],
    )


class NinetyCommentIssueConfig(NinetyInput):
    """Add a comment to an Issue."""

    operation: Literal["comment_issue"] = Field("comment_issue", json_schema_extra={"ui:hidden": True})
    issue_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="The Issue Id",
        examples=["507f1f77bcf86cd799439011"],
    )
    text: str = Field(
        ...,
        min_length=1,
        description="The comment text. HTML is sanitized upstream, so send plain text unless you specifically need formatting.",
        examples=["Agreed - lets revisit this next week."],
    )


class NinetyListRocksConfig(NinetyInput):
    """List company Rocks."""

    operation: Literal["list_rocks"] = Field("list_rocks", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=100, description="Maximum number of items to return")
    nextToken: str | None = Field(
        None,
        description="Opaque cursor from a previous response's `pagination.nextToken`. Omit to fetch the first page.",
    )
    completed: StrictBool | None = Field(None, description="Filter by completed status", examples=[False])
    archived: StrictBool | None = Field(None, description="Include archived Rocks (excluded by default)")
    deleted: StrictBool | None = Field(None, description="Include deleted Rocks (excluded by default)")
    searchText: str | None = Field(
        None, description="Search text to match against title and description", examples=["onboarding"]
    )
    title: str | None = Field(
        None, description="Filter by title match", examples=["Launch new customer onboarding flow"]
    )
    sortBy: Literal["createdDate", "completedDate", "title", "dueDate", "id"] | None = Field(
        None, description="Field to sort results by. Defaults to `dueDate`."
    )
    sortOrder: Literal["asc", "desc"] | None = Field(None, description="Sort direction")


class NinetyGetRockConfig(NinetyInput):
    """Get a Rock by Id."""

    operation: Literal["get_rock"] = Field("get_rock", json_schema_extra={"ui:hidden": True})
    rock_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="The Rock Id",
        examples=["507f1f77bcf86cd799439013"],
    )


class NinetyCreateRockConfig(NinetyInput):
    """Create a Rock."""

    operation: Literal["create_rock"] = Field("create_rock", json_schema_extra={"ui:hidden": True})
    rock: NinetyRockData = Field(..., description="The Rock data")
    addCreatorToFollowersList: StrictBool | None = Field(
        None, description="When true, the authenticated user is added to the Rock's followers list", examples=[False]
    )
    linkedItemId: str | None = Field(
        None,
        description="The Id of a To-Do, Issue, or Milestone to link the new Rock to. Must be provided together with `linkedItemType`. The linked item must belong to the same company as the authenticated caller.",
        examples=["507f1f77bcf86cd799439015"],
    )
    linkedItemType: Literal["todo", "issue", "milestone"] | None = Field(
        None, description="The type of item `linkedItemId` refers to.", examples=["issue"]
    )


class NinetyUpdateRockConfig(NinetyInput):
    """Update a Rock."""

    operation: Literal["update_rock"] = Field("update_rock", json_schema_extra={"ui:hidden": True})
    rock_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="The Rock Id",
        examples=["507f1f77bcf86cd799439013"],
    )
    userId: str | None = Field(
        None, description="The Id of the user who owns the Rock", examples=["507f1f77bcf86cd799439012"]
    )
    teamId: str | None = Field(
        None, description="The Id of the team the Rock belongs to", examples=["507f1f77bcf86cd799439011"]
    )
    title: str | None = Field(
        None, description="The title of the Rock", examples=["Launch new customer onboarding flow"]
    )
    description: str | None = Field(
        None,
        description="The description of the Rock",
        examples=["Redesign the onboarding wizard to reduce drop-off by 20%"],
    )
    statusCode: Literal["OFF_TRACK", "ON_TRACK", "DONE", "CANCELED", "DRAFT"] | None = Field(
        None,
        description="The status of the Rock — `OFF_TRACK` · `ON_TRACK` · `DONE` · `CANCELED` · `DRAFT`",
        examples=["ON_TRACK"],
    )
    levelCode: Literal["USER", "COMPANY_AND_DEPARTMENT", "COMPANY", "DEPARTMENT"] | None = Field(
        None,
        description="The level of the Rock — `USER` · `COMPANY_AND_DEPARTMENT` · `COMPANY` · `DEPARTMENT`",
        examples=["USER"],
    )
    quarter: Literal["Q1", "Q2", "Q3", "Q4", "None"] | None = Field(
        None, description="The quarter associated with the Rock — `Q1` · `Q2` · `Q3` · `Q4` · `None`", examples=["Q2"]
    )
    dueDate: str | None = Field(
        None, description="The due date of the Rock (ISO 8601)", examples=["2026-06-30T23:59:59.000Z"]
    )
    rockQuarterYearDueDate: str | None = Field(
        None,
        description="The quarter-aligned year due date of the Rock (ISO 8601)",
        examples=["2026-06-30T23:59:59.999Z"],
    )
    archived: StrictBool | None = Field(
        None, description="Set to true to archive the Rock, false to unarchive it", examples=[False]
    )
    futureScope: Literal["Current", "Next", "Later", "Future"] | None = Field(
        None, description="The future scope of the Rock — `Current` · `Next` · `Later` · `Future`", examples=["Current"]
    )
    additionalTeamIds: list[str] | None = Field(
        None,
        description="Array of additional team Ids that can also view this Rock",
        examples=[["507f1f77bcf86cd799439022"]],
    )
    linkedItemId: str | None = Field(
        None,
        description="The Id of a To-Do, Issue, or Milestone to link this existing Rock to. Must be provided together with `linkedItemType`. The linked item must belong to the same company as the authenticated caller.",
        examples=["507f1f77bcf86cd799439015"],
    )
    linkedItemType: Literal["todo", "issue", "milestone"] | None = Field(
        None, description="The type of item `linkedItemId` refers to.", examples=["issue"]
    )


class NinetyGetMilestoneConfig(NinetyInput):
    """Get a Milestone by Id."""

    operation: Literal["get_milestone"] = Field("get_milestone", json_schema_extra={"ui:hidden": True})
    milestone_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="The Milestone Id",
        examples=["507f1f77bcf86cd799439014"],
    )


class NinetyCreateMilestoneConfig(NinetyInput):
    """Create a Milestone."""

    operation: Literal["create_milestone"] = Field("create_milestone", json_schema_extra={"ui:hidden": True})
    rockId: str = Field(
        ...,
        min_length=1,
        description="The Id of the Rock this Milestone belongs to",
        examples=["507f1f77bcf86cd799439013"],
    )
    title: str = Field(..., min_length=1, description="The title of the Milestone", examples=["Complete UX wireframes"])
    dueDate: str = Field(
        ..., min_length=1, description="The due date of the Milestone (ISO 8601)", examples=["2026-05-15T23:59:59.000Z"]
    )
    teamId: str = Field(
        ...,
        min_length=1,
        description="The Id of the team the Milestone belongs to",
        examples=["507f1f77bcf86cd799439011"],
    )
    description: str | None = Field(
        None, description="The description of the Milestone", examples=["Deliver final wireframes for review in Figma"]
    )
    userOrdinal: float | None = Field(
        None, description="The ordinal position of this Milestone for the user (0-based)", examples=[0]
    )
    toDoId: str | None = Field(
        None, description="The Id of a related To-Do item, if any", examples=["507f1f77bcf86cd799439099"]
    )
    isDone: StrictBool | None = Field(
        None, description="True if the Milestone is already done at creation time", examples=[False]
    )
    completedDate: str | None = Field(
        None,
        description="The date the Milestone was completed (ISO 8601). Required when isDone is true.",
        examples=["2026-05-10T16:00:00.000Z"],
    )


class NinetyUpdateMilestoneConfig(NinetyInput):
    """Update a Milestone."""

    operation: Literal["update_milestone"] = Field("update_milestone", json_schema_extra={"ui:hidden": True})
    milestone_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="The Milestone Id",
        examples=["507f1f77bcf86cd799439014"],
    )
    title: str | None = Field(None, description="The title of the Milestone", examples=["Complete UX wireframes"])
    description: str | None = Field(
        None, description="The description of the Milestone", examples=["Deliver final wireframes for review in Figma"]
    )
    dueDate: str | None = Field(
        None, description="The due date of the Milestone (ISO 8601)", examples=["2026-05-15T23:59:59.000Z"]
    )
    isDone: StrictBool | None = Field(None, description="Set to true to mark the Milestone as done", examples=[True])
    ownedByUserId: str | None = Field(
        None, description="The Id of the user who owns this Milestone", examples=["507f1f77bcf86cd799439012"]
    )
    completedDate: str | None = Field(
        None,
        description="The date the Milestone was completed (ISO 8601). Provide when setting isDone to true.",
        examples=["2026-05-10T16:00:00.000Z"],
    )
    followers: list[str] | None = Field(
        None,
        description="Array of user Ids who are following this Milestone",
        examples=[["507f1f77bcf86cd799439012", "507f1f77bcf86cd799439016"]],
    )


class NinetyListMeasurablesConfig(NinetyInput):
    """List company Measurables."""

    operation: Literal["list_measurables"] = Field("list_measurables", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=100, description="Maximum number of items to return")
    nextToken: str | None = Field(
        None,
        description="Opaque cursor from a previous response's `pagination.nextToken`. Omit to fetch the first page.",
    )
    scoresFrom: str | None = Field(
        None,
        description="The earliest `periodDisplayDate` of the scores returned with each Measurable. Inclusive. Defaults to 365 days before `scoresTo`, and may be at most 366 days before it.",
        examples=["2025-10-06"],
    )
    scoresTo: str | None = Field(
        None,
        description="The latest `periodDisplayDate` of the scores returned with each Measurable. Inclusive. Defaults to today in UTC.",
        examples=["2026-10-05"],
    )


class NinetyPutScoreConfig(NinetyInput):
    """Create or update a Measurable score."""

    operation: Literal["put_score"] = Field("put_score", json_schema_extra={"ui:hidden": True})
    kpi_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="The Id of the Measurable",
        examples=["64d6a32564d6a32564d6a325"],
    )
    value: float = Field(..., description="The score value", examples=[100])
    periodStartDate: str = Field(
        ..., min_length=1, description="The period start date in ISO 8601 format", examples=["2024-01-01T00:00:00.000Z"]
    )


class NinetyPutNoteConfig(NinetyInput):
    """Create or update a Measurable note."""

    operation: Literal["put_note"] = Field("put_note", json_schema_extra={"ui:hidden": True})
    kpi_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="The Id of the Measurable",
        examples=["64d6a32564d6a32564d6a325"],
    )
    note: str = Field(..., min_length=1, description="The note text", examples=["Great progress this week!"])
    periodStartDate: str = Field(
        ..., min_length=1, description="The period start date in ISO 8601 format", examples=["2024-01-01T00:00:00.000Z"]
    )


class NinetyCreateHeadlineConfig(NinetyInput):
    """Create a Headline."""

    operation: Literal["create_headline"] = Field("create_headline", json_schema_extra={"ui:hidden": True})
    title: str = Field(
        ...,
        min_length=1,
        description="The Headline itself, as one line of plain text",
        examples=["Acme renewed for another year"],
    )
    teamId: str = Field(
        ...,
        min_length=1,
        description="Id of the Team the Headline is for. Discoverable via `GET /teams/available`.",
        examples=["507f1f77bcf86cd799439011"],
    )
    description: str | None = Field(
        None, description="HTML body of the Headline", examples=["<p>Three-year term, up 20% on the last contract.</p>"]
    )
    userId: str | None = Field(
        None,
        description="Id of the User the Headline is about or owned by. Defaults to the authenticated User, who is recorded as the creator either way. Must be in the same company - anyone else is rejected with a 403.",
        examples=["507f1f77bcf86cd799439012"],
    )
    isCascadedMessage: StrictBool | None = Field(None, description="Create a Cascading Message rather than a Headline")


NinetyOperation = Annotated[
    Union[
        NinetyListTeamsConfig,
        NinetyListUsersConfig,
        NinetyListTodosConfig,
        NinetyGetTodoConfig,
        NinetyCreateTodoConfig,
        NinetyUpdateTodoConfig,
        NinetyDeleteTodoConfig,
        NinetyCommentTodoConfig,
        NinetyListIssuesConfig,
        NinetyGetIssueConfig,
        NinetyCreateIssueConfig,
        NinetyUpdateIssueConfig,
        NinetyDeleteIssueConfig,
        NinetyCommentIssueConfig,
        NinetyListRocksConfig,
        NinetyGetRockConfig,
        NinetyCreateRockConfig,
        NinetyUpdateRockConfig,
        NinetyGetMilestoneConfig,
        NinetyCreateMilestoneConfig,
        NinetyUpdateMilestoneConfig,
        NinetyListMeasurablesConfig,
        NinetyPutScoreConfig,
        NinetyPutNoteConfig,
        NinetyCreateHeadlineConfig,
    ],
    Field(discriminator="operation"),
]


class NinetyFullConfig(NodeConfig[NinetyOperation, NinetyPersonalTokenCredential]):
    pass


# Each operation performs exactly this one documented request; cursors stay caller controlled.
ROUTES = {
    "list_teams": ("GET", "/v1/teams", {}, [], 200, "array"),
    "list_users": ("GET", "/v1/users", {}, ["includeInactive", "email"], 200, "array"),
    "list_todos": (
        "GET",
        "/v1/todos/company",
        {},
        ["limit", "nextToken", "completed", "archived", "deleted", "searchText", "title", "sortBy", "sortOrder"],
        200,
        "page",
    ),
    "get_todo": ("GET", "/v1/todos/{id}", {"id": "todo_id"}, [], 200, "object"),
    "create_todo": ("POST", "/v1/todos", {}, [], 201, "object"),
    "update_todo": ("PATCH", "/v1/todos/{id}", {"id": "todo_id"}, [], 200, "object"),
    "delete_todo": ("DELETE", "/v1/todos/{id}", {"id": "todo_id"}, [], 204, "empty"),
    "comment_todo": ("POST", "/v1/todos/{id}/comments", {"id": "todo_id"}, [], 201, "array"),
    "list_issues": (
        "GET",
        "/v1/issues/company",
        {},
        ["limit", "nextToken", "completed", "archived", "deleted", "searchText", "title", "sortBy", "sortOrder"],
        200,
        "page",
    ),
    "get_issue": ("GET", "/v1/issues/{issueId}", {"issueId": "issue_id"}, [], 200, "object"),
    "create_issue": ("POST", "/v1/issues", {}, [], 201, "object"),
    "update_issue": ("PATCH", "/v1/issues/{issueId}", {"issueId": "issue_id"}, [], 200, "object"),
    "delete_issue": ("DELETE", "/v1/issues/{issueId}", {"issueId": "issue_id"}, [], 204, "empty"),
    "comment_issue": ("POST", "/v1/issues/{issueId}/comments", {"issueId": "issue_id"}, [], 201, "array"),
    "list_rocks": (
        "GET",
        "/v1/rocks/company",
        {},
        ["limit", "nextToken", "completed", "archived", "deleted", "searchText", "title", "sortBy", "sortOrder"],
        200,
        "page",
    ),
    "get_rock": ("GET", "/v1/rocks/{id}", {"id": "rock_id"}, [], 200, "object"),
    "create_rock": ("POST", "/v1/rocks", {}, [], 201, "array"),
    "update_rock": ("PATCH", "/v1/rocks/{id}", {"id": "rock_id"}, [], 200, "object"),
    "get_milestone": ("GET", "/v1/milestones/{id}", {"id": "milestone_id"}, [], 200, "object"),
    "create_milestone": ("POST", "/v1/milestones", {}, [], 201, "object"),
    "update_milestone": ("PATCH", "/v1/milestones/{id}", {"id": "milestone_id"}, [], 200, "object"),
    "list_measurables": (
        "GET",
        "/v1/scorecard/kpis/company",
        {},
        ["limit", "nextToken", "scoresFrom", "scoresTo"],
        200,
        "page",
    ),
    "put_score": ("POST", "/v1/scorecard/kpis/{kpiId}/scores", {"kpiId": "kpi_id"}, [], 200, "object"),
    "put_note": ("POST", "/v1/scorecard/kpis/{kpiId}/notes", {"kpiId": "kpi_id"}, [], 200, "object"),
    "create_headline": ("POST", "/v1/headlines", {}, [], 201, "object"),
}


class NinetyNode(WorkflowNode):
    integration_type = "automation-ninety"
    connection_evidence = ConnectionEvidence(operation="list_teams", noun="Teams")

    @classmethod
    def get_config_model(cls):
        return NinetyFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Ninety personal access token")
        operation = self.config.config
        token = self.config.credentials.access_token
        method, path, path_fields, query_fields, expected_status, kind = ROUTES[operation.operation]
        values = operation.model_dump(exclude_none=True, mode="json")
        for parameter, field in path_fields.items():
            path = path.replace("{" + parameter + "}", quote(values.pop(field), safe=""))
        values.pop("operation")
        params = {
            key: (str(values[key]).lower() if isinstance(values[key], bool) else values[key])
            for key in query_fields
            if key in values
        }
        body = values if method in {"POST", "PATCH"} else None
        if method == "PATCH" and not body:
            raise ValueError("Provide at least one field to update")
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(
                method,
                BASE_URL + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                params=params,
                **({"json": body} if body is not None else {}),
            )
        if response.status_code != expected_status:
            # Do not retry writes: Ninety documents partial updates on link failures.
            message = response.text[:4000].replace(token, "[redacted]")
            raise ValueError(f"Ninety HTTP {response.status_code}: {message}")
        if kind == "empty":
            return {"operation": operation.operation, "http_status": response.status_code, "deleted": True}
        data = response.json()
        if kind == "array" and not isinstance(data, list):
            raise ValueError("Ninety returned an invalid list response")
        if kind in {"object", "page"} and not isinstance(data, dict):
            raise ValueError("Ninety returned an invalid object response")
        if isinstance(data, dict) and ("error" in data or "errors" in data):
            raise ValueError("Ninety returned an error response")
        result = {"operation": operation.operation, "http_status": response.status_code, "data": data}
        if kind == "page":
            if not isinstance(data.get("data"), list) or not isinstance(data.get("pagination"), dict):
                raise ValueError("Ninety returned an invalid pagination envelope")
            result["data"] = data["data"]
            result["pagination"] = data["pagination"]
        return result
