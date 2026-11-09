"""Bloom Growth v1: one published API request per operation.

Contract: https://app-next.bloomgrowth.com/swagger/v1/swagger.json
Token instructions: https://help.bloomgrowth.com/en/all-about-the-bloom-growth-api
Bearer tokens are pasted by the account holder and expire after two weeks.
"""
from __future__ import annotations
from datetime import datetime
from typing import Annotated, Literal, Optional, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app-next.bloomgrowth.com"
CREDENTIAL_TYPE = "bloom_growth_api_token"
ResourceId = Annotated[int, Field(ge=1, le=9223372036854775807)]
Title = Annotated[str, Field(min_length=1, max_length=2000)]


class BloomGrowthTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Bloom Growth API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "api_key",
            "x-credential-url": "https://help.bloomgrowth.com/en/all-about-the-bloom-growth-api",
            "x-credential-instructions": "Generate an access_token using Bloom Growth's API instructions and paste the token here without the Bearer prefix. Tokens expire after two weeks; replace an expired token with a newly generated one. NoClick sends it only to app-next.bloomgrowth.com.",
        },
    )
    credential_type: Literal["bloom_growth_api_token"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=16384, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the Bloom Growth access token")
        token = clean_secret(value, field_name="API token", key=True)
        if any(c.isspace() for c in token):
            raise ValueError("Paste the token without the Bearer prefix or spaces")
        return token


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def timezone_required(cls, value):
        if isinstance(value, datetime) and value.utcoffset() is None:
            raise ValueError("Use an ISO 8601 date and time including a timezone")
        return value


class GetMe(_Input):
    """Get the user represented by the token; also proves the connection."""
    operation: Literal["get_me"] = "get_me"


class ListUsers(_Input):
    """List all users visible to the connected account."""
    operation: Literal["list_users"] = "list_users"


class ListTodos(_Input):
    """List your personal to-dos."""
    operation: Literal["list_todos"] = "list_todos"


class GetTodo(_Input):
    """Get a to-do by its ID."""
    operation: Literal["get_todo"] = "get_todo"
    todo_id: ResourceId


class CreateTodo(_Input):
    """Create a personal to-do; the provider defaults the due date to seven days."""
    operation: Literal["create_todo"] = "create_todo"
    title: Title
    notes: Optional[str] = Field(None, max_length=100000)
    due_date: Optional[datetime] = None


class UpdateTodo(_Input):
    """Change a to-do's title or due date; omitted fields are not sent."""
    operation: Literal["update_todo"] = "update_todo"
    todo_id: ResourceId
    title: Optional[Title] = None
    due_date: Optional[datetime] = None

    @model_validator(mode="after")
    def changed(self):
        if self.title is None and self.due_date is None:
            raise ValueError("Provide a title or due date to update")
        return self


class CompleteTodo(_Input):
    """Complete or reopen a to-do using the documented status query parameter."""
    operation: Literal["complete_todo"] = "complete_todo"
    todo_id: ResourceId
    completed: bool = True


class ListGoals(_Input):
    """List your goals (called rocks in the API)."""
    operation: Literal["list_goals"] = "list_goals"


class GetGoal(_Input):
    """Get one goal."""
    operation: Literal["get_goal"] = "get_goal"
    goal_id: ResourceId


class CreateGoal(_Input):
    """Create a goal, optionally assigning its accountable owner."""
    operation: Literal["create_goal"] = "create_goal"
    title: Title
    accountable_user_id: Optional[ResourceId] = None


class UpdateGoal(_Input):
    """Update a goal's title or accountable owner."""
    operation: Literal["update_goal"] = "update_goal"
    goal_id: ResourceId
    title: Optional[Title] = None
    accountable_user_id: Optional[ResourceId] = None

    @model_validator(mode="after")
    def changed(self):
        if self.title is None and self.accountable_user_id is None:
            raise ValueError("Provide a title or accountable user to update")
        return self


class ArchiveGoal(_Input):
    """Archive a goal."""
    operation: Literal["archive_goal"] = "archive_goal"
    goal_id: ResourceId


class ListMilestones(_Input):
    """List a goal's milestones."""
    operation: Literal["list_milestones"] = "list_milestones"
    goal_id: ResourceId


class CreateMilestone(_Input):
    """Add a milestone with a title and due date to a goal."""
    operation: Literal["create_milestone"] = "create_milestone"
    goal_id: ResourceId
    title: Title
    due_date: datetime


class ListIssues(_Input):
    """List issues you own."""
    operation: Literal["list_issues"] = "list_issues"


class GetIssue(_Input):
    """Get one issue."""
    operation: Literal["get_issue"] = "get_issue"
    issue_id: ResourceId


class CreateIssue(_Input):
    """Create an issue in a weekly meeting."""
    operation: Literal["create_issue"] = "create_issue"
    meeting_id: ResourceId
    title: Title
    owner_id: Optional[ResourceId] = None
    notes: Optional[str] = Field(None, max_length=100000)


class ListMeetingIssues(_Input):
    """List issues in a weekly meeting."""
    operation: Literal["list_meeting_issues"] = "list_meeting_issues"
    meeting_id: ResourceId


class ListMeetingTodos(_Input):
    """List a weekly meeting's to-dos, optionally including closed items."""
    operation: Literal["list_meeting_todos"] = "list_meeting_todos"
    meeting_id: ResourceId
    include_closed: bool = False


class ListMeetingHeadlines(_Input):
    """List headlines in a weekly meeting."""
    operation: Literal["list_meeting_headlines"] = "list_meeting_headlines"
    meeting_id: ResourceId


class ListMeasurables(_Input):
    """List metrics you own."""
    operation: Literal["list_measurables"] = "list_measurables"


class GetMeasurable(_Input):
    """Get one metric."""
    operation: Literal["get_measurable"] = "get_measurable"
    measurable_id: ResourceId


class GetScorecard(_Input):
    """Get your scorecard."""
    operation: Literal["get_scorecard"] = "get_scorecard"


class UpdateScore(_Input):
    """Set a score's value. Null, which deletes a score, is not accepted."""
    operation: Literal["update_score"] = "update_score"
    score_id: ResourceId
    value: float = Field(..., allow_inf_nan=False)


class GetCurrentWeek(_Input):
    """Get the current scorecard week."""
    operation: Literal["get_current_week"] = "get_current_week"


BloomGrowthConfig = Annotated[Union[
    GetMe, ListUsers, ListTodos, GetTodo, CreateTodo, UpdateTodo, CompleteTodo,
    ListGoals, GetGoal, CreateGoal, UpdateGoal, ArchiveGoal, ListMilestones,
    CreateMilestone, ListIssues, GetIssue, CreateIssue, ListMeetingIssues,
    ListMeetingTodos, ListMeetingHeadlines, ListMeasurables, GetMeasurable,
    GetScorecard, UpdateScore, GetCurrentWeek,
], Field(discriminator="operation")]


class BloomGrowthFullConfig(NodeConfig[BloomGrowthConfig, BloomGrowthTokenCredential]):
    pass


# Method, published route with local field placeholders, expected JSON type.
# None means the contract documents an empty success response.
OPERATIONS = {
    "get_me": ("GET", "/api/v1/users/mine", dict),
    "list_users": ("GET", "/api/v1/users/mineviewable", list),
    "list_todos": ("GET", "/api/v1/todo/users/mine", list),
    "get_todo": ("GET", "/api/v1/todo/{todo_id}", dict),
    "create_todo": ("POST", "/api/v1/todo/create", dict),
    "update_todo": ("PUT", "/api/v1/todo/{todo_id}", None),
    "complete_todo": ("POST", "/api/v1/todo/{todo_id}/complete", bool),
    "list_goals": ("GET", "/api/v1/rocks/user/mine", list),
    "get_goal": ("GET", "/api/v1/rocks/{goal_id}", dict),
    "create_goal": ("POST", "/api/v1/rocks/create", dict),
    "update_goal": ("PUT", "/api/v1/rocks/{goal_id}", None),
    "archive_goal": ("PUT", "/api/v1/rocks/{goal_id}/archive", None),
    "list_milestones": ("GET", "/api/v1/rocks/{goal_id}/milestones", list),
    "create_milestone": ("POST", "/api/v1/rocks/{goal_id}/milestones", dict),
    "list_issues": ("GET", "/api/v1/issues/users/mine", list),
    "get_issue": ("GET", "/api/v1/issues/{issue_id}", dict),
    "create_issue": ("POST", "/api/v1/issues/create", dict),
    "list_meeting_issues": ("GET", "/api/v1/l10/{meeting_id}/issues", list),
    "list_meeting_todos": ("GET", "/api/v1/l10/{meeting_id}/todos", list),
    "list_meeting_headlines": ("GET", "/api/v1/l10/{meeting_id}/headlines", list),
    "list_measurables": ("GET", "/api/v1/measurables/user/mine", list),
    "get_measurable": ("GET", "/api/v1/measurables/{measurable_id}", dict),
    "get_scorecard": ("GET", "/api/v1/scorecard/user/mine", dict),
    "update_score": ("PUT", "/api/v1/scores/{score_id}", None),
    "get_current_week": ("GET", "/api/v1/weeks/current", dict),
}
BODY_FIELDS = {
    "create_todo": {"title": "title", "notes": "notes", "due_date": "dueDate"},
    "update_todo": {"title": "title", "due_date": "dueDate"},
    "create_goal": {"title": "title", "accountable_user_id": "accountableUserId"},
    "update_goal": {"title": "title", "accountable_user_id": "accountableUserId"},
    "create_milestone": {"title": "title", "due_date": "dueDate"},
    "create_issue": {"meeting_id": "meetingId", "title": "title", "owner_id": "ownerId", "notes": "notes"},
    "update_score": {"value": "value"},
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    return value


class BloomGrowthNode(WorkflowNode):
    integration_type = "automation-bloom-growth"
    connection_evidence = ConnectionEvidence(
        noun="Bloom Growth account", identity_operation="get_me", identity_keys=("Name",),
    )

    @classmethod
    def get_config_model(cls):
        return BloomGrowthFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Bloom Growth API token")
        op = self.config.config
        values = op.model_dump(mode="json", exclude_none=True)
        method, route, expected = OPERATIONS[op.operation]
        kwargs = {"headers": {"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"}}
        if op.operation in BODY_FIELDS:
            kwargs["json"] = {target: values[source] for source, target in BODY_FIELDS[op.operation].items() if source in values}
        if op.operation == "complete_todo":
            kwargs["params"] = {"status": str(op.completed).lower()}
        elif op.operation == "list_meeting_todos":
            kwargs["params"] = {"INCLUDE_CLOSED": str(op.include_closed).lower()}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route.format(**values), **kwargs)
        except httpx.RequestError:
            return {"status": "error", "error": "Bloom Growth could not be reached; inspect the provider before retrying a write"}
        if response.status_code != 200:
            detail = response.text[:2000].replace(credential.api_token, "[redacted]")
            return {"status": "error", "status_code": response.status_code, "error": detail or f"Bloom Growth returned HTTP {response.status_code}"}
        if expected is None:
            return {"status": "success", "http_status": 200, "acknowledged": True}
        if len(response.content) > 10_000_000:
            raise ValueError("Bloom Growth response exceeds the supported size")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Bloom Growth returned an unexpected non-JSON response") from None
        if not isinstance(data, expected) or (expected is list and any(not isinstance(row, dict) for row in data)):
            raise ValueError("Bloom Growth returned an unexpected response shape")
        if isinstance(data, dict) and any(k in data for k in ("error", "errors", "Error", "Errors")):
            raise ValueError("Bloom Growth returned an error response")
        if op.operation == "get_me" and (type(data.get("Id")) is not int or not data.get("Name")):
            raise ValueError("Bloom Growth did not return an identifiable account")
        return {"status": "success", "http_status": 200, "data": _redact(data, credential.api_token)}
