"""Moxo REST API v3: personal-token flow, step, template and chat automation.

Contract: https://developers.moxo.com/v1/openapi.json (3.0.0).
Personal tokens act with the person's permissions; writes can notify participants.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class MoxoCredential(BaseModel):
    model_config = ConfigDict(title="Moxo Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.moxo.com/docs#section/Introduction/Authentication",
            "x-credential-instructions": "Create a personal access token in Moxo Settings → API keys. Paste the token without Bearer and select your organization's region. Personal tokens act as you and expire by default. Organization API keys cannot perform all these operations; use a personal token.",
        })
    credential_type: Literal["moxo_api_token"] = Field("moxo_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Personal access token", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})
    api_base_url: Literal["https://api.moxo.com", "https://api.eu.moxo.com", "https://api.au.moxo.com", "https://api.sg.moxo.com"] = Field(
        "https://api.moxo.com", title="API region", description="Use the region where your Moxo organization lives; tokens work only there.")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if not isinstance(value, str) or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the token without Bearer or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(50, ge=1, le=100, description="Maximum records in this page; request the next page with its returned cursor.")
    cursor: str | None = Field(None, min_length=1, max_length=2000)


class _Flow(_Input):
    flow_id: str = Field(..., min_length=1, max_length=256, description="The flow id from List Flows.")

    @field_validator("flow_id")
    @classmethod
    def identifier(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:+-]*", value) or value in {".", ".."}:
            raise ValueError("Use a single Moxo resource identifier")
        return value


class _Step(_Flow):
    step_id: str = Field(..., min_length=1, max_length=256, description="The step run's id from List Steps, including the run inside a loop.")
    _step = field_validator("step_id")(_Flow.identifier.__func__)


class _Template(_Input):
    template_id: str = Field(..., min_length=1, max_length=256)
    _template = field_validator("template_id")(_Flow.identifier.__func__)


class GetMe(_Input):
    operation: Literal["get_me"] = Field("get_me", title="Get My Profile", json_schema_extra={"ui:hidden": True})


class ListUsers(_Page):
    operation: Literal["list_users"] = Field("list_users", title="List Users", json_schema_extra={"ui:hidden": True})
    kind: Literal["internal", "external"] | None = None
    search: str | None = None
    status: str | None = Field(None, description="ACTIVE, INVITED, DEACTIVATED, or comma-separated values.")
    account_id: str | None = None


class GetUser(_Input):
    operation: Literal["get_user"] = Field("get_user", title="Get User", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, max_length=256, description="User id, partner unique id or email address.")
    _user = field_validator("user_id")(_Flow.identifier.__func__)


class ListTemplates(_Page):
    operation: Literal["list_templates"] = Field("list_templates", title="List Templates", json_schema_extra={"ui:hidden": True})
    status: Literal["DRAFT", "ACTIVE", "ARCHIVED"] | None = None
    search: str | None = None
    kind: Literal["process", "action"] = "process"
    updated_since: AwareDatetime | None = None


class GetTemplate(_Template):
    operation: Literal["get_template"] = Field("get_template", title="Get Template", json_schema_extra={"ui:hidden": True})
    copy: Literal["published", "working"] = "published"
    expand: Literal["dependencies"] | None = None


class RoleAssignment(_Input):
    role_id: str = Field(..., min_length=1, alias="roleId")
    user_id: str | None = Field(None, alias="userId")
    email: str | None = None
    unique_id: str | None = Field(None, alias="uniqueId")

    @model_validator(mode="after")
    def one_person(self):
        if sum(bool(v) for v in (self.user_id, self.email, self.unique_id)) != 1:
            raise ValueError("Assign exactly one of userId, email or uniqueId")
        return self


class CustomField(_Input):
    key: str = Field(..., min_length=1, description="Field key from the template, rather than its id or label.")
    value: str | float | bool | list[str | float | bool]


class StartFlow(_Template):
    operation: Literal["start_flow"] = Field("start_flow", title="Start Flow", description="Starts real work from a process template; participants can be notified and new external users can be invited.", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, max_length=255)
    role_assignments: list[RoleAssignment] = Field(default_factory=list, description="Assign roles by key, id or name. Each entry names exactly one person.")
    custom_fields: list[CustomField] | None = None
    due_at: AwareDatetime | None = None
    idempotency_key: str | None = Field(None, min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_\-:.]+$", description="A unique request key. Same-key retries return the first response for 10 minutes; later retries run again.")


class ListFlows(_Page):
    cursor: str | None = Field(None, min_length=1, max_length=2000, description="Only with Updated Since: return pagination.nextCursor unchanged.")
    offset: int | None = Field(None, ge=0, description="Ordinary lists: the previous pagination.offset plus pagination.limit. Do not combine with Updated Since.")
    operation: Literal["list_flows"] = Field("list_flows", title="List Flows", json_schema_extra={"ui:hidden": True})
    status: str | None = Field(None, description="For example IN_PROGRESS,PAUSED.")
    template_id: str | None = None
    account_id: str | None = None
    search: str | None = None
    lifecycle: Literal["active", "archived", "all"] | None = None
    updated_since: AwareDatetime | None = None
    sort: Literal["recent", "newest", "oldest", "due-date", "due-date-latest", "completed-newest", "completed-oldest", "auto-number"] | None = None


    @model_validator(mode="after")
    def paging_mode(self):
        if self.updated_since is not None and self.offset is not None:
            raise ValueError("Updated Since uses a cursor, not an offset")
        if self.updated_since is None and self.cursor is not None:
            raise ValueError("A cursor requires Updated Since; ordinary lists use an offset")
        return self


class GetFlow(_Flow):
    operation: Literal["get_flow"] = Field("get_flow", title="Get Flow", json_schema_extra={"ui:hidden": True})


class UpdateFlow(_Flow):
    operation: Literal["update_flow"] = Field("update_flow", title="Update Flow", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, max_length=255)
    custom_fields: list[CustomField] | None = None
    due_at: AwareDatetime | None = None
    clear_due_date: bool = Field(False, description="Remove the flow due date by sending dueAt: null.")

    @model_validator(mode="after")
    def due_date_choice(self):
        if self.clear_due_date and self.due_at is not None:
            raise ValueError("Choose a due date or clear it")
        return self


class CancelFlow(_Flow):
    operation: Literal["cancel_flow"] = Field("cancel_flow", title="Cancel Flow", json_schema_extra={"ui:hidden": True})
    reason: str | None = Field(None, max_length=500)


class ArchiveFlow(_Flow):
    operation: Literal["archive_flow"] = Field("archive_flow", title="Archive Flow", json_schema_extra={"ui:hidden": True})


class UnarchiveFlow(_Flow):
    operation: Literal["unarchive_flow"] = Field("unarchive_flow", title="Unarchive Flow", json_schema_extra={"ui:hidden": True})


class PauseFlow(_Flow):
    operation: Literal["pause_flow"] = Field("pause_flow", title="Pause Flow", json_schema_extra={"ui:hidden": True})
    reason: str = Field(..., min_length=1, max_length=500, description="Required pause reason, shown to participants and kept in the audit trail.")


class ResumeFlow(_Flow):
    operation: Literal["resume_flow"] = Field("resume_flow", title="Resume Flow", json_schema_extra={"ui:hidden": True})


class ListSteps(_Flow, _Page):
    operation: Literal["list_steps"] = Field("list_steps", title="List Flow Steps", json_schema_extra={"ui:hidden": True})
    status: str | None = None


class GetStep(_Step):
    operation: Literal["get_step"] = Field("get_step", title="Get Flow Step", json_schema_extra={"ui:hidden": True})


class TimeEntry(_Input):
    minutes: int = Field(..., ge=1, le=1439)
    billable: bool
    description: str | None = Field(None, max_length=500)


class CompleteStep(_Step):
    operation: Literal["complete_step"] = Field("complete_step", title="Complete Step", description="Completes work as you. Use field ids for forms, question ids for questionnaires, or decision: APPROVED for approvals.", json_schema_extra={"ui:hidden": True})
    result_data: dict[str, Any] | None = Field(None, description="Step-specific resultData; use the exact schema for the step type in Moxo's Steps reference.")
    note: str | None = Field(None, max_length=4000)
    time_entry: TimeEntry | None = None
    time_prompt: bool | None = None


class ListFlowMessages(_Flow, _Page):
    operation: Literal["list_flow_messages"] = Field("list_flow_messages", title="List Flow Chat Messages", json_schema_extra={"ui:hidden": True})


class PostFlowMessage(_Flow):
    operation: Literal["post_flow_message"] = Field("post_flow_message", title="Post Flow Chat Message", description="Posts a message and can notify mentioned people. A mention can add an organization member as a viewer when Moxo permits it.", json_schema_extra={"ui:hidden": True})
    body: str = Field(..., min_length=1, max_length=10000, title="Message")
    target_step_execution_id: str | None = Field(None, min_length=1)
    mentions: list[Annotated[str, Field(min_length=1)]] | None = Field(None, max_length=10)


class GetFlowSummary(_Flow):
    operation: Literal["get_flow_summary"] = Field("get_flow_summary", title="Get Flow AI Summary", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[GetMe, ListUsers, GetUser, ListTemplates, GetTemplate, StartFlow,
    ListFlows, GetFlow, UpdateFlow, CancelFlow, ArchiveFlow, UnarchiveFlow, PauseFlow,
    ResumeFlow, ListSteps, GetStep, CompleteStep, ListFlowMessages, PostFlowMessage, GetFlowSummary], Field(discriminator="operation")]


class MoxoConfig(NodeConfig[Operation, MoxoCredential]):
    pass


# Each public operation issues exactly one documented REST request.
ROUTES = {
    "get_me": ("GET", "/v1/users/me"),
    "list_users": ("GET", "/v1/users"),
    "get_user": ("GET", "/v1/users/{user_id}"),
    "list_templates": ("GET", "/v1/templates"),
    "get_template": ("GET", "/v1/templates/{template_id}"),
    "start_flow": ("POST", "/v1/templates/{template_id}/start"),
    "list_flows": ("GET", "/v1/flows"),
    "get_flow": ("GET", "/v1/flows/{flow_id}"),
    "update_flow": ("PATCH", "/v1/flows/{flow_id}"),
    "cancel_flow": ("POST", "/v1/flows/{flow_id}/cancel"),
    "archive_flow": ("POST", "/v1/flows/{flow_id}/archive"),
    "unarchive_flow": ("POST", "/v1/flows/{flow_id}/unarchive"),
    "pause_flow": ("POST", "/v1/flows/{flow_id}/pause"),
    "resume_flow": ("POST", "/v1/flows/{flow_id}/resume"),
    "list_steps": ("GET", "/v1/flows/{flow_id}/steps"),
    "get_step": ("GET", "/v1/flows/{flow_id}/steps/{step_id}"),
    "complete_step": ("POST", "/v1/flows/{flow_id}/steps/{step_id}/complete"),
    "list_flow_messages": ("GET", "/v1/flows/{flow_id}/messages"),
    "post_flow_message": ("POST", "/v1/flows/{flow_id}/messages"),
    "get_flow_summary": ("GET", "/v1/flows/{flow_id}/summary"),
}
WIRE_NAMES = {"account_id": "accountId", "template_id": "templateId", "updated_since": "updatedSince",
    "role_assignments": "roleAssignments", "custom_fields": "customFields", "due_at": "dueAt",
    "result_data": "resultData", "time_entry": "timeEntry", "time_prompt": "timePrompt",
    "target_step_execution_id": "targetStepExecutionId"}


class MoxoNode(WorkflowNode):
    integration_type = "automation-moxo"
    connection_evidence = ConnectionEvidence(operation="list_templates", identity_operation="get_me",
        noun="templates", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return MoxoConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Moxo personal access token")
        config = self.config.config
        method, template = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, by_alias=True)
        path_keys = re.findall(r"{(\w+)}", template)
        path = template.format(**{key: quote(values.pop(key), safe="") for key in path_keys})
        values.pop("operation")
        key = values.pop("idempotency_key", None)
        clear_due = values.pop("clear_due_date", False)
        payload = {WIRE_NAMES.get(k, k): v for k, v in values.items()}
        if clear_due:
            payload["dueAt"] = None
        headers = {"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"}
        if key:
            headers["Idempotency-Key"] = key
        kwargs = {"params": payload} if method == "GET" else {"json": payload} if payload or config.operation in {"start_flow", "update_flow", "complete_step"} else {}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, credential.api_base_url + path, headers=headers, **kwargs)
        try:
            body = response.json()
        except ValueError:
            raise ValueError(f"Moxo returned HTTP {response.status_code} without a JSON response") from None
        if not 200 <= response.status_code < 300 or not isinstance(body, dict) or body.get("success") is not True:
            error = body.get("error", {}) if isinstance(body, dict) else {}
            message = error.get("message") if isinstance(error, dict) else str(error)
            message = str(message or f"Moxo request failed (HTTP {response.status_code})").replace(credential.api_token, "[redacted]")
            raise ValueError(message)
        result = {**body, "status": "success", "operation": config.operation, "http_status": response.status_code}
        await self.emit(result)
        return result
