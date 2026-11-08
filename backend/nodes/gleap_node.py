"""Gleap Conversations API, pinned to the provider's 2026-08-01 contract.

All actions run as the project service account on behalf of the contact.
Each operation makes one request; list cursors are explicit, never auto-drained.
Reference: https://docs.gleap.ai/en/articles/719-authentication
Contract: https://api.gleap.io/s2s-openapi.json
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.gleap.io/v3"
API_VERSION = "2026-08-01"


class GleapServiceAccountCredential(BaseModel):
    model_config = ConfigDict(title="Gleap Service Account Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.gleap.io",
            "x-help-url": "https://docs.gleap.ai/en/articles/719-authentication",
            "x-credential-instructions": "Open your Gleap project, then Settings → Developer → API keys. Create a service account and paste its token. Use a separate project for testing. The Project ID is not a credential. The token can read and write contacts and conversations in its project."})
    credential_type: Literal["gleap_service_account"] = Field("gleap_service_account", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Service account token", repr=False,
        json_schema_extra={"ui:widget": "password", "ui:help": "Paste the token without the Bearer prefix."})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Service account token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the service account token without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def safe_identifiers(cls, value, info):
        if info.field_name in {"user_id", "conversation_id", "message_id", "workflow_id", "webhook_id"}:
            if not value or value in {".", ".."} or len(value) > 1024 or any(ord(c) < 32 for c in value):
                raise ValueError("Use a nonempty Gleap identifier")
        return value


class _Post(_Input):
    idempotency_key: str | None = Field(None, min_length=1, max_length=255,
        description="Optional stable key for retrying this exact POST for 24 hours. Gleap provides at-least-once semantics; do not change the body when reusing a key.")

    @field_validator("idempotency_key")
    @classmethod
    def header(cls, value):
        if value is not None and (not value.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Use a printable ASCII idempotency key")
        return value


class Attachment(_Input):
    url: str = Field(..., description="Upload URL returned by Gleap; signed URLs expire. NoClick does not fetch this URL.")
    name: str | None = None
    contentType: str | None = None


class ContactEvent(_Input):
    name: str = Field(..., min_length=1)
    date: str | None = Field(None, description="ISO timestamp; omit for now.")
    data: dict[str, Any] | None = None


class GleapUpsertContactConfig(_Input):
    """Create or update a contact."""
    operation: Literal["upsert_contact"] = Field("upsert_contact", title='Upsert Contact', json_schema_extra={"ui:hidden": True})
    user_id: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    language: str | None = None
    companyId: str | None = None
    companyName: str | None = None
    plan: str | None = None
    value: float | None = None
    customData: dict[str, Any] | None = None


class GleapGetContactConfig(_Input):
    """Fetch a contact and its unread conversation count."""
    operation: Literal["get_contact"] = Field("get_contact", title='Get Contact', json_schema_extra={"ui:hidden": True})
    user_id: str


class GleapDeleteContactConfig(_Input):
    """Delete a contact and their conversations."""
    operation: Literal["delete_contact"] = Field("delete_contact", title='Delete Contact', json_schema_extra={"ui:hidden": True})
    user_id: str


class GleapTrackContactEventsConfig(_Post):
    """Track contact events that drive outbound messaging and workflows."""
    operation: Literal["track_contact_events"] = Field("track_contact_events", title='Track Contact Events', json_schema_extra={"ui:hidden": True})
    user_id: str
    events: list[ContactEvent] = Field(..., min_length=1)


class GleapCreateConversationConfig(_Post):
    """Open a conversation authored as the contact; creates the contact if absent."""
    operation: Literal["create_conversation"] = Field("create_conversation", title='Create Conversation', json_schema_extra={"ui:hidden": True})
    user_id: str
    message: str = Field(..., min_length=1)
    title: str | None = None
    attributes: dict[str, Any] | None = None
    source: str | None = None
    type: str | None = Field(None, description="Project ticket type; defaults to INQUIRY. FEATURE_REQUEST and CRASH are unsupported.")
    tags: list[str] | None = None
    attachments: list[Attachment] | None = None
    workflowId: str | None = None
    agentId: str | None = None

    @model_validator(mode="after")
    def routing(self):
        if self.workflowId and self.agentId:
            raise ValueError("Choose either a workflow or an AI agent")
        if self.type in {"FEATURE_REQUEST", "CRASH"}:
            raise ValueError("Gleap does not support this conversation type")
        return self


class GleapListConversationsConfig(_Input):
    """List contact conversations, most recent activity first; bot-only conversations are hidden."""
    operation: Literal["list_conversations"] = Field("list_conversations", title='List Conversations', json_schema_extra={"ui:hidden": True})
    user_id: str
    cursor: str | None = Field(None, description="next_cursor from the preceding page.")
    limit: int = Field(50, ge=1, le=100)


class GleapGetConversationConfig(_Input):
    """Fetch customer-visible conversation details."""
    operation: Literal["get_conversation"] = Field("get_conversation", title='Get Conversation', json_schema_extra={"ui:hidden": True})
    conversation_id: str


class GleapUpdateConversationConfig(_Input):
    """Update title and merge customer-visible attributes."""
    operation: Literal["update_conversation"] = Field("update_conversation", title='Update Conversation', json_schema_extra={"ui:hidden": True})
    conversation_id: str
    title: str | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def change(self):
        if self.title is None and self.attributes is None:
            raise ValueError("Provide a title or attributes to update")
        return self


class GleapCloseConversationConfig(_Post):
    """Close conversation; further contact messages are rejected until reopened."""
    operation: Literal["close_conversation"] = Field("close_conversation", title='Close Conversation', json_schema_extra={"ui:hidden": True})
    conversation_id: str


class GleapReopenConversationConfig(_Post):
    """Reopen a closed conversation."""
    operation: Literal["reopen_conversation"] = Field("reopen_conversation", title='Reopen Conversation', json_schema_extra={"ui:hidden": True})
    conversation_id: str


class GleapMarkConversationReadConfig(_Post):
    """Explicitly mark conversation read for the contact."""
    operation: Literal["mark_conversation_read"] = Field("mark_conversation_read", title='Mark Conversation Read', json_schema_extra={"ui:hidden": True})
    conversation_id: str


class GleapRateConversationConfig(_Post):
    """Submit a contact CSAT rating from zero through ten."""
    operation: Literal["rate_conversation"] = Field("rate_conversation", title='Rate Conversation', json_schema_extra={"ui:hidden": True})
    conversation_id: str
    rating: int = Field(..., ge=0, le=10)


class GleapSendMessageConfig(_Post):
    """Send a message authored as the contact."""
    operation: Literal["send_message"] = Field("send_message", title='Send Message', json_schema_extra={"ui:hidden": True})
    conversation_id: str
    text: str = Field(..., min_length=1)
    attachments: list[Attachment] | None = None
    replyToMessageId: str | None = None


class GleapListMessagesConfig(_Input):
    """Read messages oldest first; this does not mark the conversation read."""
    operation: Literal["list_messages"] = Field("list_messages", title='List Messages', json_schema_extra={"ui:hidden": True})
    conversation_id: str
    after: str | None = Field(None, description="next_after from the preceding page (last message ID).")
    limit: int = Field(50, ge=1, le=100)


class GleapGetMessageConfig(_Input):
    """Fetch a single message."""
    operation: Literal["get_message"] = Field("get_message", title='Get Message', json_schema_extra={"ui:hidden": True})
    message_id: str


class GleapRateMessageConfig(_Post):
    """Rate a message, typically an AI answer."""
    operation: Literal["rate_message"] = Field("rate_message", title='Rate Message', json_schema_extra={"ui:hidden": True})
    message_id: str
    rating: Literal["positive", "negative"]


class GleapGetPendingWorkflowStepConfig(_Input):
    """Read the workflow step waiting for the contact, if any."""
    operation: Literal["get_pending_workflow_step"] = Field("get_pending_workflow_step", title='Get Pending Workflow Step', json_schema_extra={"ui:hidden": True})
    conversation_id: str


class GleapAnswerWorkflowStepConfig(_Post):
    """Answer a pending workflow step or request human handoff."""
    operation: Literal["answer_workflow_step"] = Field("answer_workflow_step", title='Answer Workflow Step', json_schema_extra={"ui:hidden": True})
    conversation_id: str
    text: str | None = None
    selected: str | None = None
    rating: float | None = None
    attachments: list[Attachment] | None = None
    botAction: Literal["humanHandoff"] | None = None

    @model_validator(mode="after")
    def answer(self):
        if all(getattr(self, f) is None for f in ("text", "selected", "rating", "attachments", "botAction")):
            raise ValueError("Provide an answer or request human handoff")
        return self


class GleapRunWorkflowConfig(_Post):
    """Start this workflow, replacing any active one; acceptance does not prove completion."""
    operation: Literal["run_workflow"] = Field("run_workflow", title='Run Workflow', json_schema_extra={"ui:hidden": True})
    conversation_id: str
    workflow_id: str


class GleapListWorkflowsConfig(_Input):
    """List the project live workflows."""
    operation: Literal["list_workflows"] = Field("list_workflows", title='List Workflows', json_schema_extra={"ui:hidden": True})


class GleapListWebhooksConfig(_Input):
    """List project webhook endpoints with masked signing secrets."""
    operation: Literal["list_webhooks"] = Field("list_webhooks", title='List Webhooks', json_schema_extra={"ui:hidden": True})


class GleapCreateWebhookConfig(_Post):
    """Register an endpoint; its signing secret is returned once, so store it securely."""
    operation: Literal["create_webhook"] = Field("create_webhook", title='Create Webhook', json_schema_extra={"ui:hidden": True})
    url: str = Field(..., description="HTTPS endpoint to receive Gleap events. Gleap delivers the requests.")
    events: list[str] | None = None
    description: str | None = None

    @field_validator("url")
    @classmethod
    def https_url(cls, value):
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Provide an HTTPS webhook endpoint without credentials or fragment")
        return value


class GleapDeleteWebhookConfig(_Input):
    """Delete a project webhook endpoint."""
    operation: Literal["delete_webhook"] = Field("delete_webhook", title='Delete Webhook', json_schema_extra={"ui:hidden": True})
    webhook_id: str


GleapOperation = Annotated[Union[
    GleapUpsertContactConfig,
    GleapGetContactConfig,
    GleapDeleteContactConfig,
    GleapTrackContactEventsConfig,
    GleapCreateConversationConfig,
    GleapListConversationsConfig,
    GleapGetConversationConfig,
    GleapUpdateConversationConfig,
    GleapCloseConversationConfig,
    GleapReopenConversationConfig,
    GleapMarkConversationReadConfig,
    GleapRateConversationConfig,
    GleapSendMessageConfig,
    GleapListMessagesConfig,
    GleapGetMessageConfig,
    GleapRateMessageConfig,
    GleapGetPendingWorkflowStepConfig,
    GleapAnswerWorkflowStepConfig,
    GleapRunWorkflowConfig,
    GleapListWorkflowsConfig,
    GleapListWebhooksConfig,
    GleapCreateWebhookConfig,
    GleapDeleteWebhookConfig
], Field(discriminator="operation")]


class GleapNodeConfig(NodeConfig[GleapOperation, GleapServiceAccountCredential]):
    pass


# Explicit one-to-one mapping to the provider contract.
OPERATIONS = {
    "upsert_contact": ('PUT', '/s2s/contacts/{user_id}', ('name', 'email', 'phone', 'language', 'companyId', 'companyName', 'plan', 'value', 'customData')),
    "get_contact": ('GET', '/s2s/contacts/{user_id}', ()),
    "delete_contact": ('DELETE', '/s2s/contacts/{user_id}', ()),
    "track_contact_events": ('POST', '/s2s/contacts/{user_id}/events', ('events',)),
    "create_conversation": ('POST', '/s2s/contacts/{user_id}/conversations', ('message', 'title', 'attributes', 'source', 'type', 'tags', 'attachments', 'workflowId', 'agentId')),
    "list_conversations": ('GET', '/s2s/contacts/{user_id}/conversations', ()),
    "get_conversation": ('GET', '/s2s/conversations/{conversation_id}', ()),
    "update_conversation": ('PATCH', '/s2s/conversations/{conversation_id}', ('title', 'attributes')),
    "close_conversation": ('POST', '/s2s/conversations/{conversation_id}/close', ()),
    "reopen_conversation": ('POST', '/s2s/conversations/{conversation_id}/reopen', ()),
    "mark_conversation_read": ('POST', '/s2s/conversations/{conversation_id}/read', ()),
    "rate_conversation": ('POST', '/s2s/conversations/{conversation_id}/rating', ('rating',)),
    "send_message": ('POST', '/s2s/conversations/{conversation_id}/messages', ('text', 'attachments', 'replyToMessageId')),
    "list_messages": ('GET', '/s2s/conversations/{conversation_id}/messages', ()),
    "get_message": ('GET', '/s2s/messages/{message_id}', ()),
    "rate_message": ('POST', '/s2s/messages/{message_id}/rating', ('rating',)),
    "get_pending_workflow_step": ('GET', '/s2s/conversations/{conversation_id}/workflow', ()),
    "answer_workflow_step": ('POST', '/s2s/conversations/{conversation_id}/workflow/answer', ('text', 'selected', 'rating', 'attachments', 'botAction')),
    "run_workflow": ('POST', '/s2s/conversations/{conversation_id}/workflow/{workflow_id}/run', ()),
    "list_workflows": ('GET', '/s2s/workflows', ()),
    "list_webhooks": ('GET', '/s2s/webhooks', ()),
    "create_webhook": ('POST', '/s2s/webhooks', ('url', 'events', 'description')),
    "delete_webhook": ('DELETE', '/s2s/webhooks/{webhook_id}', ()),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {str(k).replace(token, "[redacted]"): _redact(v, token) for k, v in value.items()}
    return value


class GleapNode(WorkflowNode):
    integration_type = "automation-gleap"
    connection_evidence = ConnectionEvidence(
        noun="workflows", operation="list_workflows", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return GleapNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Gleap service account token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, template, body_fields = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True)
        path = template.format(**{k: quote(str(v), safe="") for k, v in values.items()})
        headers = {"Authorization": "Bearer " + token, "Gleap-Version": API_VERSION,
            "Accept": "application/json"}
        if values.get("idempotency_key"):
            headers["Idempotency-Key"] = values["idempotency_key"]
        params = {k: values[k] for k in ("cursor", "after", "limit") if k in values}
        body = {k: values[k] for k in body_fields if k in values}
        kwargs = {"headers": headers, "params": params}
        if body_fields:
            kwargs["json"] = body
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, **kwargs)
        except httpx.RequestError:
            return {"status": "error", "message": "Gleap could not be reached; a write may have been accepted. Inspect before retrying.",
                "operation": op.operation}
        status = response.status_code
        if not 200 <= status < 300:
            try:
                problem = response.json()
                message = problem.get("detail") or problem.get("title") or "Gleap rejected the request"
            except (ValueError, AttributeError):
                problem, message = {}, "Gleap returned a non-JSON error"
            result = {"status": "error", "http_status": status, "message": message,
                "code": problem.get("code"), "retry_after": response.headers.get("Retry-After")}
            return _redact(result, token)
        # 202 without a body means queued; 204 is a completed read receipt/rating.
        if status == 204 or (status == 202 and not response.content):
            return {"status": "success", "http_status": status, "accepted": True,
                "operation": op.operation, "completed": status != 202}
        try:
            data = response.json()
            self._validate_response(op.operation, data)
        except (ValueError, TypeError):
            return {"status": "error", "http_status": status,
                "message": "Gleap returned an unexpected response; inspect writes before retrying."}
        result = {"status": "success", "http_status": status, "operation": op.operation, "data": data}
        if op.operation in {"list_conversations", "list_messages"}:
            result.update({k: data[k] for k in data})
        return _redact(result, token)

    @staticmethod
    def _validate_response(operation, data):
        if operation in {"list_workflows", "list_webhooks"}:
            if not isinstance(data, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in data):
                raise ValueError("Expected project resources")
            return
        if not isinstance(data, dict) or data.get("error") or "errors" in data:
            raise ValueError("Expected Gleap object")
        if operation in {"list_conversations", "list_messages"}:
            cursor = "next_cursor" if operation == "list_conversations" else "next_after"
            if not isinstance(data.get("items"), list) or type(data.get("has_more")) is not bool or cursor not in data:
                raise ValueError("Expected paginated resources")
            if data[cursor] is not None and not isinstance(data[cursor], str):
                raise ValueError("Expected string cursor")
            if data["has_more"] and not data[cursor]:
                raise ValueError("Missing next-page cursor")
        elif operation in {"get_contact", "upsert_contact"}:
            if not isinstance(data.get("userId"), str):
                raise ValueError("Expected contact")
        elif operation in {"get_conversation", "create_conversation", "update_conversation", "close_conversation", "reopen_conversation", "get_message", "send_message", "create_webhook"}:
            if not isinstance(data.get("id"), str):
                raise ValueError("Expected resource")
        elif operation == "get_pending_workflow_step":
            if "step" not in data or (data["step"] is not None and not isinstance(data["step"], dict)):
                raise ValueError("Expected nullable workflow step")
        elif operation == "delete_webhook":
            if data.get("success") is not True:
                raise ValueError("Deletion was not acknowledged")
        elif operation == "delete_contact":
            if not isinstance(data.get("status"), str):
                raise ValueError("Deletion was not acknowledged")
        elif operation == "track_contact_events":
            if not isinstance(data.get("received"), (int, float)):
                raise ValueError("Expected event count")
