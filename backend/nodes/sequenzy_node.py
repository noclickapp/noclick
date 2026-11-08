"""Sequenzy subscriber, audience and automation actions using a workspace API key.

Each operation maps to one published v1 endpoint. Provider envelopes and paging
metadata remain intact so callers can inspect partial results and continue pages.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.sequenzy.com/api/v1"
Email = Annotated[str, Field(min_length=3, max_length=320, pattern=r"^[^\s/@?#%]+@[^\s/@?#%]+\.[^\s/@?#%]+$", json_schema_extra={"format": "email"})]
Identifier = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=255)]
Emails = Annotated[list[Email], Field(min_length=1, max_length=500)]


class SequenzyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Sequenzy API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.sequenzy.com/dashboard",
            "x-credential-instructions": "In Sequenzy, open Settings → API Keys & SMTP and create a workspace API key. Paste the key only. Choose the permissions needed for your actions: subscriber reads/writes/deletes, tags, lists and sequences; event-triggering and enrollment need explicit delivery permissions. Use a workspace key (seq_live_ or legacy ek_), since account keys can implicitly select another workspace. Connection checks read account info and do not prove write permissions.",
        })
    credential_type: Literal["sequenzy_api_key"] = Field("sequenzy_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or value.lower().startswith("bearer"):
            raise ValueError("Paste the API key without the Bearer prefix")
        if value.startswith("seq_user_"):
            raise ValueError("Use a workspace API key from Settings → API Keys & SMTP")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetAccountInfo(_Input):
    """Read the workspace associated with this API key."""
    operation: Literal["get_account_info"] = "get_account_info"


class ListSubscribers(_Input):
    """Read one subscriber page; reuse pagination.nextCursor with identical filters."""
    operation: Literal["list_subscribers"] = "list_subscribers"
    limit: int = Field(20, ge=1, le=1000)
    page: Optional[int] = Field(None, ge=1)
    cursor: Optional[str] = Field(None, min_length=1, max_length=4096)
    status: Optional[Literal["active", "unsubscribed", "bounced", "all"]] = None
    query: Optional[str] = Field(None, max_length=1000)
    tags: Optional[str] = Field(None, max_length=1000, description="Comma-separated tag names; all must match.")
    list_id: Optional[Identifier] = None

    @model_validator(mode="after")
    def paging(self):
        if self.page is not None and self.cursor is not None:
            raise ValueError("Choose a page number or a cursor, not both")
        return self


class _Subscriber(_Input):
    email: Email


class GetSubscriber(_Subscriber):
    """Read one subscriber by email."""
    operation: Literal["get_subscriber"] = "get_subscriber"


class CreateSubscriber(_Subscriber):
    """Create or upsert an email contact using the explicit duplicate strategy."""
    operation: Literal["create_subscriber"] = "create_subscriber"
    first_name: Optional[str] = Field(None, max_length=255)
    last_name: Optional[str] = Field(None, max_length=255)
    external_id: Optional[Text] = None
    tags: Optional[list[Text]] = Field(None, max_length=100)
    lists: Optional[list[Identifier]] = Field(None, max_length=100, description="Omit for workspace defaults; [] joins no lists.")
    custom_attributes: Optional[dict[str, Any]] = None
    duplicate_strategy: Literal["skip", "merge", "overwrite"] = "skip"
    opt_in_mode: Literal["default", "confirmed", "double_opt_in"] = Field("default", description="Use confirmed only when you have verified consent.")
    enroll_in_sequences: bool = Field(False, description="Explicit opt-in to matching automations; may send emails and needs automations:trigger.")


class UpdateSubscriber(_Subscriber):
    """Update supplied fields; custom attribute merge preserves unspecified keys."""
    operation: Literal["update_subscriber"] = "update_subscriber"
    first_name: Optional[str] = Field(None, max_length=255)
    last_name: Optional[str] = Field(None, max_length=255)
    custom_attributes: Optional[dict[str, Any]] = None
    custom_attributes_strategy: Literal["replace", "merge"] = "merge"
    status: Optional[Literal["active", "unsubscribed", "bounced", "complained"]] = Field(None, description="Unsubscribed performs global unsubscribe; complained records suppression and unsubscribes.")


class DeleteSubscriber(_Subscriber):
    """Delete the email contact; requires subscribers:delete."""
    operation: Literal["delete_subscriber"] = "delete_subscriber"


class AddTag(_Subscriber):
    """Add a tag; the API may create a missing subscriber and trigger automations."""
    operation: Literal["add_tag"] = "add_tag"
    tag: Text


class RemoveTag(_Subscriber):
    """Remove one subscriber tag."""
    operation: Literal["remove_tag"] = "remove_tag"
    tag: Text


class TriggerEvent(_Subscriber):
    """Record a subscriber event, which may trigger live automations."""
    operation: Literal["trigger_event"] = "trigger_event"
    event: Text
    properties: Optional[dict[str, Any]] = None
    event_id: Optional[Text] = Field(None, description="Provider best-effort idempotency key; keep your own ledger for strict deduplication.")


class ListTags(_Input):
    """Read workspace tag definitions."""
    operation: Literal["list_tags"] = "list_tags"


class CreateTag(_Input):
    """Create a normalized tag definition."""
    operation: Literal["create_tag"] = "create_tag"
    name: Text
    color: Optional[Literal["gray", "red", "orange", "amber", "yellow", "lime", "green", "emerald", "teal", "cyan", "sky", "blue", "indigo", "violet", "purple", "fuchsia", "pink", "rose"]] = None


class ListLists(_Input):
    """Read subscriber lists and membership counts."""
    operation: Literal["list_lists"] = "list_lists"


class CreateList(_Input):
    """Create a subscriber list; descriptions are internal workspace metadata."""
    operation: Literal["create_list"] = "create_list"
    name: Text
    description: Optional[str] = Field(None, max_length=10000)
    is_private: bool = False
    allow_member_unsubscribe: bool = False


class AddSubscribersToList(_Input):
    """Add up to 500 emails to a list, retaining per-email processing outcomes."""
    operation: Literal["add_subscribers_to_list"] = "add_subscribers_to_list"
    list_id: Identifier
    emails: Emails
    duplicate_strategy: Literal["skip", "merge", "overwrite"] = "skip"
    opt_in_mode: Literal["default", "confirmed", "double_opt_in"] = "default"
    enroll_in_sequences: bool = False


class RemoveSubscribersFromList(_Input):
    """Remove list memberships without deleting the contacts."""
    operation: Literal["remove_subscribers_from_list"] = "remove_subscribers_from_list"
    list_id: Identifier
    emails: Emails


class ListSequences(_Input):
    """Read one sequence page; branch on effectiveStatus for its run state."""
    operation: Literal["list_sequences"] = "list_sequences"
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0)
    status: Optional[Literal["draft", "active", "paused", "archived"]] = None
    search: Optional[str] = Field(None, max_length=1000)


class GetSequence(_Input):
    """Read one sequence definition and lifecycle state."""
    operation: Literal["get_sequence"] = "get_sequence"
    sequence_id: Identifier


class EnrollSubscribers(_Input):
    """Enroll up to 500 emails; may send emails and needs sequences:enroll."""
    operation: Literal["enroll_subscribers"] = "enroll_subscribers"
    sequence_id: Identifier
    emails: Emails
    target_node_id: Optional[Identifier] = None


class ListCampaigns(_Input):
    """Read one campaign page with the provider's pagination metadata."""
    operation: Literal["list_campaigns"] = "list_campaigns"
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0)
    status: Optional[Literal["draft", "scheduled", "sent", "sending", "cancelled", "paused", "waiting_approval", "rejected"]] = None
    label: Optional[Text] = None


SequenzyOperation = Annotated[Union[GetAccountInfo, ListSubscribers, GetSubscriber,
    CreateSubscriber, UpdateSubscriber, DeleteSubscriber, AddTag, RemoveTag,
    TriggerEvent, ListTags, CreateTag, ListLists, CreateList, AddSubscribersToList,
    RemoveSubscribersFromList, ListSequences, GetSequence, EnrollSubscribers,
    ListCampaigns], Field(discriminator="operation")]


class SequenzyConfig(NodeConfig[SequenzyOperation, SequenzyAPIKeyCredential]):
    pass


# Fixed routes keep each action inside the provider's published API contract.
ROUTES = {
    "get_account_info": ("GET", "/subscribers/me"),
    "list_subscribers": ("GET", "/subscribers"),
    "get_subscriber": ("GET", "/subscribers/{email}"),
    "create_subscriber": ("POST", "/subscribers"),
    "update_subscriber": ("PATCH", "/subscribers/{email}"),
    "delete_subscriber": ("DELETE", "/subscribers/{email}"),
    "add_tag": ("POST", "/subscribers/tags"),
    "remove_tag": ("POST", "/subscribers/tags/remove"),
    "trigger_event": ("POST", "/subscribers/events"),
    "list_tags": ("GET", "/tags"),
    "create_tag": ("POST", "/tags"),
    "list_lists": ("GET", "/lists"),
    "create_list": ("POST", "/lists"),
    "add_subscribers_to_list": ("POST", "/lists/{list_id}/subscribers"),
    "remove_subscribers_from_list": ("POST", "/lists/{list_id}/subscribers/remove"),
    "list_sequences": ("GET", "/sequences"),
    "get_sequence": ("GET", "/sequences/{sequence_id}"),
    "enroll_subscribers": ("POST", "/sequences/{sequence_id}/enroll"),
    "list_campaigns": ("GET", "/campaigns"),
}
WIRE_NAMES = {
    "first_name": "firstName", "last_name": "lastName", "external_id": "externalId",
    "custom_attributes": "customAttributes", "custom_attributes_strategy": "customAttributesStrategy",
    "duplicate_strategy": "duplicateStrategy", "opt_in_mode": "optInMode",
    "enroll_in_sequences": "enrollInSequences", "is_private": "isPrivate",
    "allow_member_unsubscribe": "allowMemberUnsubscribe", "list_id": "listId",
    "target_node_id": "targetNodeId", "event_id": "eventId",
}


class SequenzyNode(WorkflowNode):
    integration_type = "automation-sequenzy"
    connection_evidence = ConnectionEvidence(noun="Sequenzy workspace",
        identity_operation="get_account_info", identity_keys=("companyName", "companyId"))

    @classmethod
    def get_config_model(cls):
        return SequenzyConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Sequenzy workspace API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for name in ("email", "list_id", "sequence_id"):
            marker = "{" + name + "}"
            if marker in path:
                path = path.replace(marker, quote(values.pop(name), safe=""))
        payload = {WIRE_NAMES.get(k, k): v for k, v in values.items()}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                    params=payload if method == "GET" else None,
                    json=payload if method in {"POST", "PATCH"} else None)
        except httpx.RequestError:
            result = {"status": "error" if method == "GET" else "unknown", "success": False,
                "error": "Sequenzy request did not complete" if method == "GET" else "Sequenzy write outcome is unknown; inspect before retrying"}
        else:
            try:
                body = response.json()
            except ValueError:
                raise ValueError("Sequenzy returned an unexpected response") from None
            if not isinstance(body, dict):
                raise ValueError("Sequenzy returned an unexpected response")
            if not 200 <= response.status_code < 300 or body.get("success") is False:
                message = body.get("error")
                result = {"status": "error", "success": False, "http_status": response.status_code,
                    "error": message.replace(key, "[redacted]") if isinstance(message, str) else "Sequenzy rejected the request"}
            elif body.get("success") is not True:
                raise ValueError("Sequenzy response did not confirm success")
            else:
                result = {**body, "status": "success", "http_status": response.status_code}
        await self.emit(result)
        return result
