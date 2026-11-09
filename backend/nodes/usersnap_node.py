"""Usersnap REST API v0.1 feedback submission and project reporting.

Each action performs one published API operation. Email and state searches
are convenient typed configurations of the documented feedback filter route.
"""
from __future__ import annotations

import base64
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://platform.usersnap.com/v0.1"
DOCS = "https://help.usersnap.com/reference/platform-rest-api"


class UsersnapTokenCredential(BaseModel):
    model_config = ConfigDict(title="Usersnap API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.usersnap.com/#/settings/rest-api",
        "x-credential-instructions": "Requires a Usersnap Enterprise plan with REST API access. Paste a JWT you have signed using HS256 and the JWT secret from Settings > REST API, with the generated JWT ID in the kid header. Paste the finished token, without Bearer; do not paste the signing secret. NoClick sends it only to platform.usersnap.com. See https://help.usersnap.com/reference/platform-rest-api.",
    })
    credential_type: Literal["usersnap_api_token"] = Field("usersnap_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=16384, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the finished JWT without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListProjects(_Input):
    operation: Literal["list_projects"] = Field("list_projects", title="List Projects")


class _Project(_Input):
    project_id: str = Field(..., title="Project ID", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Project ID returned by List Projects; this is different from its API key.")


class _ProjectKey(_Input):
    project_api_key: str = Field(..., title="Project API key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Project api_key returned by List Projects or the widget settings; this is different from its project ID.")


class GetProjectMetrics(_ProjectKey):
    operation: Literal["get_project_metrics"] = Field("get_project_metrics", title="Get Project Metrics")


class ListProjectAssignees(_ProjectKey):
    operation: Literal["list_project_assignees"] = Field("list_project_assignees", title="List Project Assignees")


class ClientInfo(_Input):
    url: str | None = None
    screen_width: int | None = Field(None, ge=0, le=2147483647)
    screen_height: int | None = Field(None, ge=0, le=2147483647)


class Attachment(_Input):
    content: str = Field(..., description="Base64 file content, at most 20 MiB decoded.", json_schema_extra={"contentEncoding": "base64"})
    filename: str = Field(..., min_length=1)
    mime_type: str = Field(..., min_length=1)

    @field_validator("content")
    @classmethod
    def bounded_file(cls, value):
        try:
            if len(value) > 27962028 or len(base64.b64decode(value, validate=True)) > 20 * 1024 * 1024:
                raise ValueError()
        except ValueError:
            raise ValueError("Use base64 file content of at most 20 MiB") from None
        return value


class SubmitFeedback(_ProjectKey):
    operation: Literal["submit_feedback"] = Field("submit_feedback", title="Submit Feedback")
    visitor: str | None = Field(None, title="Visitor email")
    comment: str | None = Field(None, title="Comment")
    assignee: str | None = Field(None, description="User ID or email; omit to use the default assignee. Explicit null leaves the feedback unassigned.")
    rating: int | None = Field(None, ge=-1, le=10, description="Use the project's scale: NPS 1–10; stars/smileys 1–5; thumbs 1 or -1.")
    client: ClientInfo | None = None
    attachments: list[Attachment] | None = None


class ListFeedback(_Project):
    operation: Literal["list_feedback"] = Field("list_feedback", title="List Feedback", description="Returns one provider page, including has_more and next when present. The pinned contract does not define continuation request parameters.")


class CountFeedback(_Project):
    operation: Literal["count_feedback"] = Field("count_feedback", title="Count Feedback")


class FeedbackFilter(_Input):
    filter_type: Literal["assignee", "created_at", "email", "feedback_number", "nps", "one_to_five", "state", "thumb"]
    operator: Literal["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "like", "ilike"]
    value: str


class FeedbackOrder(_Input):
    order_by_type: Literal["created_at", "rating", "updated_at", "likes"] = "created_at"
    direction: Literal["asc", "desc"] = "desc"


class _Filter(_Project):
    query: list[FeedbackFilter] = Field(default_factory=list, title="Filters")
    order_by: FeedbackOrder | None = Field(None, title="Sort order")


class FilterFeedback(_Filter):
    operation: Literal["filter_feedback"] = Field("filter_feedback", title="Filter Feedback")


class CountFilteredFeedback(_Filter):
    operation: Literal["count_filtered_feedback"] = Field("count_filtered_feedback", title="Count Filtered Feedback")


class FindFeedbackByEmail(_Project):
    operation: Literal["find_feedback_by_email"] = Field("find_feedback_by_email", title="Find Feedback by Email")
    email: str = Field(..., min_length=1, title="Visitor email", description="Exact email match using the documented email eq filter.")


class FindFeedbackByState(_Project):
    operation: Literal["find_feedback_by_state"] = Field("find_feedback_by_state", title="Find Feedback by State")
    state: str = Field(..., min_length=1, title="State", description="State value using the documented state eq filter; for example done.")


UsersnapOperation = Annotated[Union[ListProjects, GetProjectMetrics, ListProjectAssignees, SubmitFeedback,
    ListFeedback, CountFeedback, FilterFeedback, CountFilteredFeedback, FindFeedbackByEmail, FindFeedbackByState], Field(discriminator="operation")]


class UsersnapConfig(NodeConfig[UsersnapOperation, UsersnapTokenCredential]):
    pass


# Published operationId, method, route and response collection. Search shortcuts
# deliberately share filterProjectFeedbacks; neither invents an API endpoint.
OPERATIONS = {
    "list_projects": ("getProjects", "GET", "/projects", "projects"),
    "get_project_metrics": ("getProjectMetrics", "GET", "/projects/{api_key}/metrics", "metrics"),
    "list_project_assignees": ("getProjectAssignees", "GET", "/projects/{api_key}/assignees", "users"),
    "submit_feedback": ("submitFeedback", "POST", "/projects/{api_key}/feedbacks", "feedback"),
    "list_feedback": ("getProjectFeedbacks", "GET", "/projects/{project_id}/feedbacks", "feedbacks"),
    "count_feedback": ("getProjectFeedbacksCount", "GET", "/projects/{project_id}/feedbacks/count", "total_count"),
    "filter_feedback": ("filterProjectFeedbacks", "POST", "/projects/{project_id}/feedbacks/filter", "feedbacks"),
    "count_filtered_feedback": ("filterProjectFeedbacksCount", "POST", "/projects/{project_id}/feedbacks/filter/count", "total_count"),
    "find_feedback_by_email": ("filterProjectFeedbacks", "POST", "/projects/{project_id}/feedbacks/filter", "feedbacks"),
    "find_feedback_by_state": ("filterProjectFeedbacks", "POST", "/projects/{project_id}/feedbacks/filter", "feedbacks"),
}


class UsersnapNode(WorkflowNode):
    integration_type = "automation-usersnap"
    connection_evidence = ConnectionEvidence(operation="list_projects", noun="projects", label_keys=("name", "project_id"))

    @classmethod
    def get_config_model(cls):
        return UsersnapConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Usersnap API token")
        op = self.config.config
        token = self.config.credentials.api_token
        _, method, route, collection = OPERATIONS[op.operation]
        if isinstance(op, _Project):
            route = route.replace("{project_id}", quote(op.project_id, safe=""))
        if isinstance(op, _ProjectKey):
            route = route.replace("{api_key}", quote(op.project_api_key, safe=""))
        body = None
        if isinstance(op, SubmitFeedback):
            body = op.model_dump(exclude={"operation", "project_api_key"}, exclude_none=True)
            if "assignee" in op.model_fields_set:
                body["assignee"] = op.assignee
        elif isinstance(op, _Filter):
            body = op.model_dump(include={"query", "order_by"}, exclude_none=True)
        elif isinstance(op, (FindFeedbackByEmail, FindFeedbackByState)):
            by_email = isinstance(op, FindFeedbackByEmail)
            body = {"query": [{"filter_type": "email" if by_email else "state", "operator": "eq", "value": op.email if by_email else op.state}]}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
            raw = response.json()
            if response.status_code != (201 if isinstance(op, SubmitFeedback) else 200) or not isinstance(raw, dict) or raw.get("status") is not True:
                message = raw.get("msg") if isinstance(raw, dict) else None
                return {"status": "error", "http_status": response.status_code,
                    "error": (message if isinstance(message, str) else "Usersnap did not confirm the request").replace(token, "[redacted]")}
            data = raw.get("data")
            if not isinstance(data, dict) or collection not in data:
                raise ValueError("Usersnap returned an incomplete response")
            value = data[collection]
            result = {"status": "success", "operation": op.operation, "data": data}
            if collection in {"projects", "metrics", "users", "feedbacks"}:
                if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
                    raise ValueError("Usersnap returned an invalid collection")
                result["items"] = value
            elif collection == "total_count":
                if type(value) is not int or value < 0:
                    raise ValueError("Usersnap returned an invalid count")
                result["total_count"] = value
            elif not isinstance(value, dict) or not isinstance(value.get("feedback_id"), str) or not value["feedback_id"]:
                raise ValueError("Usersnap did not return the submitted feedback ID")
            else:
                result["feedback_id"] = value["feedback_id"]
            # Preserve provider pagination without claiming to have read all pages.
            if "has_more" in data:
                result["has_more"] = data["has_more"]
            if "next" in data:
                result["next"] = data["next"]
            return result
        except (ValueError, httpx.HTTPError):
            return {"status": "error", "error": "Usersnap request failed or returned an invalid response; a submission may have succeeded. Check Usersnap before retrying a write."}
