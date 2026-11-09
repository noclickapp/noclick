"""Textline messaging and address-book actions against the published v1.3 contract.

Each action makes one fixed API request using a manually supplied access token.
Lists return one provider page; message acknowledgements do not prove delivery.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://application.textline.com"


class TextlineAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="Textline Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://application.textline.com/organization/api_settings",
            "x-credential-instructions": "In Textline, open Settings → Tools & Integrations → Developer API and copy your access token. Paste the access token here. Your agent's permissions determine which departments and actions are available.",
        })
    credential_type: Literal["textline_access_token"] = Field("textline_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the access token without a header or whitespace")
        return value


Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    page: int = Field(0, ge=0, description="Textline page number, starting at zero. Only this page is returned.")
    page_size: int = Field(30, ge=1, le=50)
    after_uuid: Identifier | None = None
    before_uuid: Identifier | None = None


class ListConversations(_Page):
    """Read one page of conversations, or a contact's conversation by phone."""
    operation: Literal["list_conversations"] = "list_conversations"
    group_uuid: Identifier | None = None
    phone_number: Text | None = None


class GetConversation(_Page):
    """Read a conversation and one page of its posts."""
    operation: Literal["get_conversation"] = "get_conversation"
    uuid: Identifier


class _Message(_Input):
    body: Text = Field(..., description="Message text. Customer-visible unless internal_whisper is selected.")
    internal_whisper: bool = Field(False, description="Send an internal agent note instead of a customer-visible message.")
    resolve: bool = Field(False, description="Resolve the conversation after sending.")


class SendMessage(_Message):
    """Send a message or internal whisper to a phone number."""
    operation: Literal["send_message"] = "send_message"
    phone_number: Text
    group_uuid: Identifier | None = None


class MessageConversation(_Message):
    """Send a message or internal whisper to an existing conversation."""
    operation: Literal["message_conversation"] = "message_conversation"
    uuid: Identifier


class ResolveConversation(_Input):
    """Resolve an existing conversation without changing its disposition."""
    operation: Literal["resolve_conversation"] = "resolve_conversation"
    uuid: Identifier


class _Schedule(_Input):
    body: Text
    timestamp: int = Field(..., ge=0, description="Unix timestamp in seconds at which Textline should send the message.")


class ScheduleConversation(_Schedule):
    """Schedule a customer-visible message to an existing conversation."""
    operation: Literal["schedule_conversation"] = "schedule_conversation"
    uuid: Identifier


class ScheduleMessage(_Schedule):
    """Schedule a customer-visible message to a phone number."""
    operation: Literal["schedule_message"] = "schedule_message"
    phone_number: Text
    group_uuid: Identifier | None = None


class ListCustomers(_Input):
    """Read the provider's default customer page or find a contact by phone."""
    operation: Literal["list_customers"] = "list_customers"
    phone_number: Text | None = None


class _Customer(_Input):
    email: str | None = None
    name: str | None = None
    notes: str | None = None
    tags: str | None = Field(None, description="Comma or space separated tags; use underscores within a tag.")


class CreateCustomer(_Customer):
    """Create an address-book customer with a phone number."""
    operation: Literal["create_customer"] = "create_customer"
    phone_number: Text


class GetCustomer(_Input):
    """Retrieve one customer by UUID."""
    operation: Literal["get_customer"] = "get_customer"
    uuid: Identifier


class UpdateCustomer(_Customer):
    """Update supplied contact fields, tags, and custom fields only."""
    operation: Literal["update_customer"] = "update_customer"
    uuid: Identifier
    tags_handling: Literal["add", "remove", "replace"] | None = None
    archived: bool | None = None
    blocked: bool | None = None
    unreachable: bool | None = None
    custom_fields: dict[str, str] | None = Field(None, description="Map Textline custom-field UUIDs to their new values.")

    @model_validator(mode="after")
    def changes(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "uuid"}):
            raise ValueError("Supply at least one customer field to update")
        return self


class ListCustomFields(_Input):
    """Read configured address-book custom field names and UUIDs."""
    operation: Literal["list_custom_fields"] = "list_custom_fields"


class ListSavedSearches(_Input):
    """Read the account's saved contact searches."""
    operation: Literal["list_saved_searches"] = "list_saved_searches"


class GetOrganization(_Input):
    """Read organization details, optionally including departments and agents."""
    operation: Literal["get_organization"] = "get_organization"
    include_groups: bool = False
    include_users: bool = False


class ListDepartments(_Input):
    """Read departments available to the connected agent."""
    operation: Literal["list_departments"] = "list_departments"


class GetAgent(_Input):
    """Read the agent details exposed by Textline's users endpoint."""
    operation: Literal["get_agent"] = "get_agent"


class EnableAvailability(_Input):
    """Turn on availability for an agent."""
    operation: Literal["enable_availability"] = "enable_availability"
    uuid: Identifier


class DisableAvailability(_Input):
    """Turn off availability for an agent."""
    operation: Literal["disable_availability"] = "disable_availability"
    uuid: Identifier


class ListDispositions(_Input):
    """Read conversation dispositions configured in the account."""
    operation: Literal["list_dispositions"] = "list_dispositions"


class ListSurveys(_Input):
    """Read survey names, types, and UUIDs."""
    operation: Literal["list_surveys"] = "list_surveys"


Operation = Annotated[Union[ListConversations, GetConversation, SendMessage,
    MessageConversation, ResolveConversation, ScheduleConversation, ScheduleMessage,
    ListCustomers, CreateCustomer, GetCustomer, UpdateCustomer, ListCustomFields,
    ListSavedSearches, GetOrganization, ListDepartments, GetAgent,
    EnableAvailability, DisableAvailability, ListDispositions, ListSurveys], Field(discriminator="operation")]


class TextlineConfig(NodeConfig[Operation, TextlineAccessTokenCredential]):
    pass


# Each entry is exactly one published operation; no caller-supplied URL is used.
ROUTES = {
    "list_conversations": ("GET", "/api/conversations.json"),
    "get_conversation": ("GET", "/api/conversation/{uuid}.json"),
    "send_message": ("POST", "/api/conversations.json"),
    "message_conversation": ("POST", "/api/conversation/{uuid}.json"),
    "resolve_conversation": ("POST", "/api/conversation/{uuid}/resolve.json"),
    "schedule_conversation": ("POST", "/api/conversation/{uuid}/schedule.json"),
    "schedule_message": ("POST", "/api/conversations/schedule.json"),
    "list_customers": ("GET", "/api/customers.json"),
    "create_customer": ("POST", "/api/customers.json"),
    "get_customer": ("GET", "/api/customer/{uuid}.json"),
    "update_customer": ("PUT", "/api/customer/{uuid}.json"),
    "list_custom_fields": ("GET", "/api/address_book/custom_fields.json"),
    "list_saved_searches": ("GET", "/api/address_book/saved_searches.json"),
    "get_organization": ("GET", "/api/organization.json"),
    "list_departments": ("GET", "/api/groups.json"),
    "get_agent": ("GET", "/api/users.json"),
    "enable_availability": ("POST", "/api/users/{uuid}/on_call.json"),
    "disable_availability": ("DELETE", "/api/users/{uuid}/on_call.json"),
    "list_dispositions": ("GET", "/api/dispositions.json"),
    "list_surveys": ("GET", "/api/surveys.json"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()}
    return value


class TextlineNode(WorkflowNode):
    integration_type = "automation-textline"
    connection_evidence = ConnectionEvidence(noun="departments", operation="list_departments", label_keys=("name", "uuid"))

    @classmethod
    def get_config_model(cls):
        return TextlineConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Textline access token")
        op = self.config.config
        token = self.config.credentials.access_token
        method, route = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation", "uuid"})
        if "{uuid}" in route:
            route = route.format(uuid=quote(op.uuid, safe=""))
        params, body = None, None
        if method == "GET":
            params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in values.items()}
        elif isinstance(op, (SendMessage, MessageConversation)):
            key = "whisper" if op.internal_whisper else "comment"
            body = {key: {"body": op.body}}
            for field in ("phone_number", "group_uuid"):
                if field in values:
                    body[field] = values[field]
            if op.resolve:
                body["resolve"] = "1"
        elif isinstance(op, (ScheduleConversation, ScheduleMessage)):
            body = {key: value for key, value in values.items() if key != "body"}
            body["comment"] = {"body": op.body}
        elif isinstance(op, (CreateCustomer, UpdateCustomer)):
            body = {"customer": values}
        result = {"operation": op.operation}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route,
                    headers={"X-TGP-ACCESS-TOKEN": token, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
            result["http_status"] = response.status_code
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if response.status_code != 200:
                result.update(status="error", error=payload if payload is not None else "Textline returned a non-JSON error")
            elif not isinstance(payload, (dict, list)):
                result.update(status="error", error="Textline returned an unexpected response")
            elif isinstance(payload, dict) and (payload.get("errors") or payload.get("error")):
                result.update(status="error", error=payload)
            else:
                result.update(status="success", data=payload)
                if op.operation == "list_departments":
                    departments = payload.get("departments") if isinstance(payload, dict) else None
                    if not isinstance(departments, list):
                        raise ValueError("Textline department list is missing")
                    result["items"] = departments
                if method != "GET":
                    result["delivery_verified"] = False
        except httpx.HTTPError:
            result.update(status="error", error="Textline request did not complete; inspect any write before retrying")
        return _redact(result, token)
