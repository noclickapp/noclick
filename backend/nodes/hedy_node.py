"""Hedy API 1.6.10: account, meeting content and organisation operations.

Contract: https://api.hedy.bot/docs. Each action makes one provider request.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret


class HedyAPICredential(BaseModel):
    model_config = ConfigDict(title="Hedy API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://www.hedy.ai/help/hedy-api/",
        "x-credential-instructions": "Paste your Hedy API key from Account Settings → API Access. An active Pro subscription is required. Choose the region where your account is stored. NoClick verifies the key by reading your own profile.",
    })
    credential_type: Literal["hedy_api_key"] = Field("hedy_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})
    region: Literal["us", "eu"] = Field("us", title="Account region")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the key without the Bearer prefix or whitespace")
        return value


ResourceID = Annotated[str, StringConstraints(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")]
SessionType = Literal["business_meetings", "lecture_class", "coaching_mentoring", "recruitment_call", "job_interview_candidate", "negotiation", "sales_meeting", "journalism", "spiritual_teaching", "solo_brainstorm", "group_brainstorm", "personal_conversation", "medical_consultation"]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetProfile(_Input):
    operation: Literal["get_profile"] = Field("get_profile", title="Get My Profile")


class GetVocabulary(_Input):
    operation: Literal["get_vocabulary"] = Field("get_vocabulary", title="Get Custom Vocabulary")


class ReplaceVocabulary(_Input):
    operation: Literal["replace_vocabulary"] = Field("replace_vocabulary", title="Replace Custom Vocabulary")
    terms: list[Annotated[str, StringConstraints(min_length=2, max_length=50)]] = Field(..., max_length=100, description="Complete replacement list; omitted terms are removed. An empty list removes all terms.")
    enabled: bool | None = Field(None, description="Omit to preserve whether vocabulary matching is enabled.")

    @field_validator("terms")
    @classmethod
    def valid_terms(cls, terms):
        if len({t.casefold() for t in terms}) != len(terms) or any(re.search(r'[<>{}\[\]\\|`~]', t) for t in terms):
            raise ValueError("Vocabulary terms must be unique ignoring case and contain no prohibited punctuation")
        return terms


class _Page(_Input):
    limit: int = Field(50, ge=1, le=100)
    after: str | None = Field(None, description="Use pagination.next from the preceding response.")


class ListSessions(_Page):
    operation: Literal["list_sessions"] = Field("list_sessions", title="List Sessions", description="Only cloud-synced sessions are returned, newest first.")


class _Session(_Input):
    session_id: ResourceID


class GetSession(_Session):
    operation: Literal["get_session"] = Field("get_session", title="Get Session Details")


class ReplaceSessionSummary(_Session):
    operation: Literal["replace_session_summary"] = Field("replace_session_summary", title="Replace Session Summary")
    recap: str | None = Field(None, min_length=1, max_length=60000, pattern=r"\S", description="Complete replacement recap. Omit to preserve.")
    meeting_minutes: str | None = Field(None, min_length=1, max_length=60000, pattern=r"\S", description="Complete replacement Details text. Omit to preserve. Session Notes cannot be edited.")

    @model_validator(mode="after")
    def supplied(self):
        body = {k: v for k, v in {"recap": self.recap, "meetingMinutes": self.meeting_minutes}.items() if v is not None}
        if not body:
            raise ValueError("Supply recap or meeting minutes")
        if len(json.dumps(body, ensure_ascii=False).encode()) >= 100000:
            raise ValueError("Summary request must be smaller than 100 KB; send long fields separately")
        return self


class AssignSessionTopic(_Session):
    operation: Literal["assign_session_topic"] = Field("assign_session_topic", title="Assign Session to Topic")
    topic_id: ResourceID | None = Field(None, description="Omit to unassign this cloud-synced session from its topic.")


class ListHighlights(_Page):
    operation: Literal["list_highlights"] = Field("list_highlights", title="List Highlights")


class GetHighlight(_Input):
    operation: Literal["get_highlight"] = Field("get_highlight", title="Get Highlight")
    highlight_id: ResourceID


class ListTodos(_Input):
    operation: Literal["list_todos"] = Field("list_todos", title="List All To-Dos", description="Eventually consistent across sessions; changes may be delayed, especially for large EU sessions.")


class ListSessionTodos(_Session):
    operation: Literal["list_session_todos"] = Field("list_session_todos", title="List Session To-Dos")


class ListSessionHighlights(_Session):
    operation: Literal["list_session_highlights"] = Field("list_session_highlights", title="List Session Highlights")


class GetTodo(_Session):
    operation: Literal["get_todo"] = Field("get_todo", title="Get Session To-Do")
    todo_id: ResourceID


class UpdateTodo(_Session):
    operation: Literal["update_todo"] = Field("update_todo", title="Update To-Do State")
    todo_id: ResourceID
    completed: bool | None = None
    due_date: str | None = Field(None, max_length=200)
    clear_due_date: bool = Field(False, description="Clear the due date. Cannot be combined with a due date.")

    @model_validator(mode="after")
    def supplied(self):
        if self.clear_due_date and self.due_date is not None:
            raise ValueError("Choose a due date or clear it")
        if self.completed is None and self.due_date is None and not self.clear_due_date:
            raise ValueError("Supply completion, a due date, or clear the due date")
        return self


class ListTopicSessions(_Input):
    operation: Literal["list_topic_sessions"] = Field("list_topic_sessions", title="List Topic Sessions")
    topic_id: ResourceID
    limit: int = Field(50, ge=1, le=100)
    start_after: str | None = Field(None, description="Use data.pagination.nextCursor from the preceding response.")


class ListTopics(_Input):
    operation: Literal["list_topics"] = Field("list_topics", title="List Topics")


class _TopicFields(_Input):
    description: str | None = Field(None, max_length=500)
    color: str | None = Field(None, pattern=r"^#?[0-9a-fA-F]{6}$")
    icon_name: str | None = Field(None, description="Icon codepoint, e.g. 59475 or 0xe853.")
    topic_context: str | None = Field(None, max_length=20000)
    dominant_session_type: SessionType | None = None


class CreateTopic(_TopicFields):
    operation: Literal["create_topic"] = Field("create_topic", title="Create Topic")
    name: str = Field(..., min_length=1, max_length=100, pattern=r"\S")


class GetTopic(_Input):
    operation: Literal["get_topic"] = Field("get_topic", title="Get Topic")
    topic_id: ResourceID


class UpdateTopic(_TopicFields):
    operation: Literal["update_topic"] = Field("update_topic", title="Update Topic")
    topic_id: ResourceID
    name: str | None = Field(None, min_length=1, max_length=100, pattern=r"\S")
    clear_topic_context: bool = False
    clear_dominant_session_type: bool = False

    @model_validator(mode="after")
    def supplied(self):
        for clear, value in [(self.clear_topic_context, self.topic_context), (self.clear_dominant_session_type, self.dominant_session_type)]:
            if clear and value is not None:
                raise ValueError("Do not supply and clear the same field")
        fields = [self.name, self.description, self.color, self.icon_name, self.topic_context, self.dominant_session_type]
        if all(v is None for v in fields) and not self.clear_topic_context and not self.clear_dominant_session_type:
            raise ValueError("Supply at least one topic change")
        return self


class DeleteTopic(_Input):
    operation: Literal["delete_topic"] = Field("delete_topic", title="Delete Topic", description="Unlinks all associated sessions; the sessions themselves remain.")
    topic_id: ResourceID


class ListContexts(_Input):
    operation: Literal["list_contexts"] = Field("list_contexts", title="List Session Contexts")


class _ContextFields(_Input):
    content: str | None = Field(None, max_length=20000)
    is_default: bool | None = Field(None, description="Setting true unsets any existing default context.")


class CreateContext(_ContextFields):
    operation: Literal["create_context"] = Field("create_context", title="Create Session Context", description="Free accounts are limited to one context.")
    title: str = Field(..., min_length=1, max_length=200, pattern=r"\S")


class GetContext(_Input):
    operation: Literal["get_context"] = Field("get_context", title="Get Session Context")
    context_id: ResourceID


class UpdateContext(_ContextFields):
    operation: Literal["update_context"] = Field("update_context", title="Update Session Context")
    context_id: ResourceID
    title: str | None = Field(None, min_length=1, max_length=200, pattern=r"\S")

    @model_validator(mode="after")
    def supplied(self):
        if self.title is None and self.content is None and self.is_default is None:
            raise ValueError("Supply at least one context change")
        return self


class DeleteContext(_Input):
    operation: Literal["delete_context"] = Field("delete_context", title="Delete Session Context", description="Deleting the default promotes the most recently updated remaining context.")
    context_id: ResourceID


HedyOperation = Annotated[Union[
    GetProfile, GetVocabulary, ReplaceVocabulary, ListSessions, GetSession, ReplaceSessionSummary,
    AssignSessionTopic, ListHighlights, GetHighlight, ListTodos, ListSessionTodos,
    ListSessionHighlights, GetTodo, UpdateTodo, ListTopicSessions, ListTopics, CreateTopic,
    GetTopic, UpdateTopic, DeleteTopic, ListContexts, CreateContext, GetContext,
    UpdateContext, DeleteContext,
], Field(discriminator="operation")]


class HedyConfig(NodeConfig[HedyOperation, HedyAPICredential]):
    pass


# Explicit endpoint and field mappings keep provider spelling out of user config.
ROUTES = {
    "get_profile": ("GET", "/me"),
    "get_vocabulary": ("GET", "/vocabulary"),
    "replace_vocabulary": ("PUT", "/vocabulary"),
    "list_sessions": ("GET", "/sessions"),
    "get_session": ("GET", "/sessions/{session_id}"),
    "replace_session_summary": ("PATCH", "/sessions/{session_id}/summary"),
    "assign_session_topic": ("PATCH", "/sessions/{session_id}"),
    "list_highlights": ("GET", "/highlights"),
    "get_highlight": ("GET", "/highlights/{highlight_id}"),
    "list_todos": ("GET", "/todos"),
    "list_session_todos": ("GET", "/sessions/{session_id}/todos"),
    "list_session_highlights": ("GET", "/sessions/{session_id}/highlights"),
    "get_todo": ("GET", "/sessions/{session_id}/todos/{todo_id}"),
    "update_todo": ("PATCH", "/sessions/{session_id}/todos/{todo_id}"),
    "list_topic_sessions": ("GET", "/topics/{topic_id}/sessions"),
    "list_topics": ("GET", "/topics"),
    "create_topic": ("POST", "/topics"),
    "get_topic": ("GET", "/topics/{topic_id}"),
    "update_topic": ("PATCH", "/topics/{topic_id}"),
    "delete_topic": ("DELETE", "/topics/{topic_id}"),
    "list_contexts": ("GET", "/contexts"),
    "create_context": ("POST", "/contexts"),
    "get_context": ("GET", "/contexts/{context_id}"),
    "update_context": ("PATCH", "/contexts/{context_id}"),
    "delete_context": ("DELETE", "/contexts/{context_id}"),
}
BODY_FIELDS = {
    "replace_vocabulary": {"terms": "terms", "enabled": "enabled"},
    "replace_session_summary": {"recap": "recap", "meeting_minutes": "meetingMinutes"},
    "assign_session_topic": {"topic_id": "topicId"},
    "update_todo": {"completed": "completed", "due_date": "dueDate"},
    "create_topic": {"name": "name", "description": "description", "color": "color", "icon_name": "iconName", "topic_context": "topicContext", "dominant_session_type": "dominantSessionType"},
    "create_context": {"title": "title", "content": "content", "is_default": "isDefault"},
}
BODY_FIELDS["update_topic"] = BODY_FIELDS["create_topic"]
BODY_FIELDS["update_context"] = BODY_FIELDS["create_context"]


class HedyNode(WorkflowNode):
    integration_type = "automation-hedy"
    connection_evidence = ConnectionEvidence(noun="Hedy profile", identity_operation="get_profile")

    @classmethod
    def get_config_model(cls):
        return HedyConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Hedy API key")
        op = self.config.config
        method, route = ROUTES[op.operation]
        values = op.model_dump()
        route = route.format(**{k: quote(v, safe="") for k, v in values.items() if k.endswith("_id") and v is not None})
        params = {}
        if op.operation in {"list_sessions", "list_highlights"}:
            params = {k: values[k] for k in ("limit", "after") if values[k] is not None}
        elif op.operation == "list_topic_sessions":
            params = {"limit": op.limit}
            if op.start_after is not None:
                params["startAfter"] = op.start_after
        body = None
        if op.operation in BODY_FIELDS:
            body = {target: values[source] for source, target in BODY_FIELDS[op.operation].items() if values[source] is not None}
            if op.operation == "assign_session_topic":
                body["topicId"] = op.topic_id
            for source, target in [("clear_due_date", "dueDate"), ("clear_topic_context", "topicContext"), ("clear_dominant_session_type", "dominantSessionType")]:
                if values.get(source):
                    body[target] = "" if source == "clear_due_date" else None
        base = "https://eu-api.hedy.bot" if credential.region == "eu" else "https://api.hedy.bot"
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, base + route, params=params,
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        try:
            payload = response.json()
        except ValueError:
            raise ValueError(f"Hedy returned non-JSON (HTTP {response.status_code})") from None
        if not 200 <= response.status_code < 300 or isinstance(payload, dict) and payload.get("success") is False:
            error = payload.get("error") if isinstance(payload, dict) else None
            message = error.get("message") if isinstance(error, dict) else error
            message = str(message or f"Hedy request rejected (HTTP {response.status_code})").replace(credential.api_key, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": message}
        if not isinstance(payload, (dict, list)):
            raise ValueError("Hedy returned an unexpected JSON response")
        if op.operation == "get_profile" and (not isinstance(payload, dict) or not payload.get("id")):
            raise ValueError("Hedy profile response lacks an account ID")
        # Keep both pagination layouts intact; never follow a response-supplied URL.
        output = {"data": payload} if isinstance(payload, list) else payload
        await self.emit(output)
        return output
