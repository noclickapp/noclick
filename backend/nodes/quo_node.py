"""Quo v1: text follow-ups, CRM contacts and call intelligence.

API contract: https://www.quo.com/docs/mdx/api-reference/openapi.md
Authentication uses the raw API key in Authorization, without a Bearer prefix.
Quo also supports webhooks; this request/response node does not register triggers.
"""
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote
import time

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, Json

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

QUO_API_BASE = "https://api.quo.com/v1"


class QuoAPIKeyCredential(BaseModel):
    credential_type: Literal["quo_api_key"] = Field(
        "quo_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        min_length=1,
        title="API Key",
        description="Your Quo workspace API key.",
        json_schema_extra={"ui:widget": "password"},
    )
    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://www.quo.com/docs/mdx/api-reference/authentication",
            "x-credential-instructions": "As a workspace owner or admin, open Quo workspace settings → API and generate an API key. Paste the key alone. Sending texts to US numbers requires completed US Carrier Registration.",
        }
    )


class QuoContactValue(BaseModel):
    name: str
    value: Optional[str]
    id: Optional[str] = None


class QuoContactCustomField(BaseModel):
    key: str
    value: Union[str, bool, float, list[str], None]
    id: Optional[str] = None


class QuoPagination(BaseModel):
    max_results: int = Field(
        10,
        ge=1,
        le=100,
        title="Page Size",
        description="Return one page; use nextPageToken from the result as Page Token for the next page.",
    )
    page_token: Optional[str] = Field(None, title="Page Token")


class QuoConversationFilter(QuoPagination):
    phone_number_id: str = Field(
        ...,
        min_length=1,
        title="Quo Phone Number ID",
        description="ID from List Phone Numbers, starting with PN.",
    )
    participants: str = Field(
        ...,
        min_length=1,
        title="Participants",
        description="Comma-separated participant phone numbers in E.164 format, excluding your Quo number. Calls support one participant; messages support up to ten.",
    )
    user_id: Optional[str] = Field(None, title="User ID")
    created_after: Optional[str] = Field(
        None, title="Created After", description="ISO 8601 timestamp."
    )
    created_before: Optional[str] = Field(
        None, title="Created Before", description="ISO 8601 timestamp."
    )


class QuoContactWriteFields(BaseModel):
    first_name: Optional[str] = Field(None, title="First Name")
    last_name: Optional[str] = Field(None, title="Last Name")
    company: Optional[str] = Field(None, title="Company")
    role: Optional[str] = Field(None, title="Role")
    emails_json: Optional[Json[list[QuoContactValue]]] = Field(
        None,
        title="Emails (JSON)",
        description='Full email list, e.g. [{"name":"work","value":"abc@example.com"}]. Updating a contact deletes existing emails if this list is omitted.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    phone_numbers_json: Optional[Json[list[QuoContactValue]]] = Field(
        None,
        title="Phone Numbers (JSON)",
        description='Full phone list, e.g. [{"name":"work","value":"+12345678901"}]. Updating a contact deletes existing phone numbers if this list is omitted.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    custom_fields_json: Optional[Json[list[QuoContactCustomField]]] = Field(
        None,
        title="Custom Fields (JSON)",
        description="Full custom-field list with key and value. Updating a contact deletes existing custom fields if this list is omitted. Use List Contact Custom Fields to find keys.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    external_id: Optional[str] = Field(
        None,
        title="CRM Record ID",
        description="Stable external ID to cross-reference with List Contacts.",
    )
    source: Optional[str] = Field(
        None,
        title="Source",
        description="Use your CRM source name. Quo reserves several names, including openphone, csv and zapier.",
    )
    source_url: Optional[str] = Field(None, title="CRM Record URL")


class QuoSendMessageConfig(BaseModel):
    operation: Literal["send_message"] = Field(
        "send_message",
        title="Send Message",
        json_schema_extra={
            "const": "send_message",
            "ui:hidden": True,
            "x-category": "Messages",
            "x-is-trigger": False,
            "x-display-name": "Send Message",
        },
    )
    content: str = Field(
        ..., min_length=1, max_length=1600, pattern=r".*\S.*", title="Message"
    )
    from_number: str = Field(
        ...,
        min_length=1,
        title="From",
        description="Quo number ID (PN…) or E.164 phone number.",
    )
    to: str = Field(
        ...,
        min_length=1,
        title="To",
        description="Comma-separated recipient phone numbers, up to ten.",
    )
    user_id: Optional[str] = Field(None, title="Sending User ID")
    set_inbox_status: Optional[Literal["done"]] = Field(
        None,
        title="Inbox Status",
        description="Select done to move the related conversation to Done.",
    )


class QuoListMessagesConfig(QuoConversationFilter):
    operation: Literal["list_messages"] = Field(
        "list_messages",
        title="List Messages",
        json_schema_extra={
            "const": "list_messages",
            "ui:hidden": True,
            "x-category": "Messages",
            "x-is-trigger": False,
            "x-display-name": "List Messages",
        },
    )


class QuoGetMessageConfig(BaseModel):
    operation: Literal["get_message"] = Field(
        "get_message",
        title="Get Message",
        json_schema_extra={
            "const": "get_message",
            "ui:hidden": True,
            "x-category": "Messages",
            "x-is-trigger": False,
            "x-display-name": "Get Message",
        },
    )
    message_id: str = Field(..., min_length=1, title="Message ID")


class QuoListContactsConfig(QuoPagination):
    operation: Literal["list_contacts"] = Field(
        "list_contacts",
        title="List Contacts",
        json_schema_extra={
            "const": "list_contacts",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "List Contacts",
        },
    )
    max_results: int = Field(10, ge=1, le=50, title="Page Size")
    external_ids: Optional[str] = Field(
        None,
        title="CRM Record IDs",
        description="Comma-separated external IDs supplied during contact creation.",
    )
    sources: Optional[str] = Field(
        None, title="Sources", description="Comma-separated contact sources."
    )


class QuoGetContactConfig(BaseModel):
    operation: Literal["get_contact"] = Field(
        "get_contact",
        title="Get Contact",
        json_schema_extra={
            "const": "get_contact",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Get Contact",
        },
    )
    contact_id: str = Field(..., min_length=1, title="Contact ID")


class QuoCreateContactConfig(QuoContactWriteFields):
    operation: Literal["create_contact"] = Field(
        "create_contact",
        title="Create Contact",
        json_schema_extra={
            "const": "create_contact",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Create Contact",
        },
    )
    first_name: str = Field(..., min_length=1, title="First Name")
    created_by_user_id: Optional[str] = Field(None, title="Created By User ID")


class QuoUpdateContactConfig(QuoContactWriteFields):
    """Replace contact lists: send every email, phone number and custom field to retain."""

    operation: Literal["update_contact"] = Field(
        "update_contact",
        title="Update Contact",
        json_schema_extra={
            "const": "update_contact",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Update Contact",
        },
    )
    contact_id: str = Field(..., min_length=1, title="Contact ID")


class QuoDeleteContactConfig(BaseModel):
    operation: Literal["delete_contact"] = Field(
        "delete_contact",
        title="Delete Contact",
        json_schema_extra={
            "const": "delete_contact",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Delete Contact",
        },
    )
    contact_id: str = Field(..., min_length=1, title="Contact ID")


class QuoListContactCustomFieldsConfig(BaseModel):
    operation: Literal["list_contact_custom_fields"] = Field(
        "list_contact_custom_fields",
        title="List Contact Custom Fields",
        json_schema_extra={
            "const": "list_contact_custom_fields",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "List Contact Custom Fields",
        },
    )


class QuoListCallsConfig(QuoConversationFilter):
    operation: Literal["list_calls"] = Field(
        "list_calls",
        title="List Calls",
        json_schema_extra={
            "const": "list_calls",
            "ui:hidden": True,
            "x-category": "Calls",
            "x-is-trigger": False,
            "x-display-name": "List Calls",
        },
    )


class QuoGetCallConfig(BaseModel):
    operation: Literal["get_call"] = Field(
        "get_call",
        title="Get Call",
        json_schema_extra={
            "const": "get_call",
            "ui:hidden": True,
            "x-category": "Calls",
            "x-is-trigger": False,
            "x-display-name": "Get Call",
        },
    )
    call_id: str = Field(..., min_length=1, title="Call ID")


class QuoGetCallRecordingsConfig(BaseModel):
    operation: Literal["get_call_recordings"] = Field(
        "get_call_recordings",
        title="Get Call Recordings",
        json_schema_extra={
            "const": "get_call_recordings",
            "ui:hidden": True,
            "x-category": "Calls",
            "x-is-trigger": False,
            "x-display-name": "Get Call Recordings",
        },
    )
    call_id: str = Field(..., min_length=1, title="Call ID")


class QuoGetCallTranscriptConfig(BaseModel):
    """Requires a Quo Business or Scale plan."""

    operation: Literal["get_call_transcript"] = Field(
        "get_call_transcript",
        title="Get Call Transcript",
        json_schema_extra={
            "const": "get_call_transcript",
            "ui:hidden": True,
            "x-category": "Calls",
            "x-is-trigger": False,
            "x-display-name": "Get Call Transcript",
        },
    )
    call_id: str = Field(..., min_length=1, title="Call ID")


class QuoGetCallSummaryConfig(BaseModel):
    """Requires a Quo Business or Scale plan."""

    operation: Literal["get_call_summary"] = Field(
        "get_call_summary",
        title="Get Call Summary",
        json_schema_extra={
            "const": "get_call_summary",
            "ui:hidden": True,
            "x-category": "Calls",
            "x-is-trigger": False,
            "x-display-name": "Get Call Summary",
        },
    )
    call_id: str = Field(..., min_length=1, title="Call ID")


class QuoGetCallVoicemailConfig(BaseModel):
    operation: Literal["get_call_voicemail"] = Field(
        "get_call_voicemail",
        title="Get Call Voicemail",
        json_schema_extra={
            "const": "get_call_voicemail",
            "ui:hidden": True,
            "x-category": "Calls",
            "x-is-trigger": False,
            "x-display-name": "Get Call Voicemail",
        },
    )
    call_id: str = Field(..., min_length=1, title="Call ID")


class QuoListConversationsConfig(QuoPagination):
    operation: Literal["list_conversations"] = Field(
        "list_conversations",
        title="List Conversations",
        json_schema_extra={
            "const": "list_conversations",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "List Conversations",
        },
    )
    phone_numbers: Optional[str] = Field(
        None,
        title="Quo Phone Numbers",
        description="Comma-separated Quo number IDs or E.164 numbers.",
    )
    user_id: Optional[str] = Field(None, title="User ID")
    created_after: Optional[str] = Field(
        None, title="Created After", description="ISO 8601 timestamp."
    )
    created_before: Optional[str] = Field(
        None, title="Created Before", description="ISO 8601 timestamp."
    )
    updated_after: Optional[str] = Field(
        None, title="Updated After", description="ISO 8601 timestamp."
    )
    updated_before: Optional[str] = Field(
        None, title="Updated Before", description="ISO 8601 timestamp."
    )
    exclude_inactive: Optional[bool] = Field(None, title="Exclude Inactive")


class QuoListPhoneNumbersConfig(BaseModel):
    operation: Literal["list_phone_numbers"] = Field(
        "list_phone_numbers",
        title="List Phone Numbers",
        json_schema_extra={
            "const": "list_phone_numbers",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "List Phone Numbers",
        },
    )
    user_id: Optional[str] = Field(None, title="User ID")


class QuoGetPhoneNumberConfig(BaseModel):
    operation: Literal["get_phone_number"] = Field(
        "get_phone_number",
        title="Get Phone Number",
        json_schema_extra={
            "const": "get_phone_number",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "Get Phone Number",
        },
    )
    phone_number_id: str = Field(..., min_length=1, title="Phone Number ID")


class QuoListUsersConfig(QuoPagination):
    operation: Literal["list_users"] = Field(
        "list_users",
        title="List Users",
        json_schema_extra={
            "const": "list_users",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "List Users",
        },
    )
    max_results: int = Field(10, ge=1, le=50, title="Page Size")


QuoConfig = Annotated[
    Union[
        QuoSendMessageConfig,
        QuoListMessagesConfig,
        QuoGetMessageConfig,
        QuoListContactsConfig,
        QuoGetContactConfig,
        QuoCreateContactConfig,
        QuoUpdateContactConfig,
        QuoDeleteContactConfig,
        QuoListContactCustomFieldsConfig,
        QuoListCallsConfig,
        QuoGetCallConfig,
        QuoGetCallRecordingsConfig,
        QuoGetCallTranscriptConfig,
        QuoGetCallSummaryConfig,
        QuoGetCallVoicemailConfig,
        QuoListConversationsConfig,
        QuoListPhoneNumbersConfig,
        QuoGetPhoneNumberConfig,
        QuoListUsersConfig,
    ],
    Discriminator("operation"),
]


class QuoNodeConfig(NodeConfig[QuoConfig, QuoAPIKeyCredential]):
    pass


# Each operation is exactly one documented Quo API request.
_REQUESTS = {
    "send_message": ("POST", "/messages"),
    "list_messages": ("GET", "/messages"),
    "get_message": ("GET", "/messages/{id}"),
    "list_contacts": ("GET", "/contacts"),
    "get_contact": ("GET", "/contacts/{id}"),
    "create_contact": ("POST", "/contacts"),
    "update_contact": ("PATCH", "/contacts/{id}"),
    "delete_contact": ("DELETE", "/contacts/{id}"),
    "list_contact_custom_fields": ("GET", "/contact-custom-fields"),
    "list_calls": ("GET", "/calls"),
    "get_call": ("GET", "/calls/{callId}"),
    "get_call_recordings": ("GET", "/call-recordings/{callId}"),
    "get_call_transcript": ("GET", "/call-transcripts/{id}"),
    "get_call_summary": ("GET", "/call-summaries/{callId}"),
    "get_call_voicemail": ("GET", "/call-voicemails/{callId}"),
    "list_conversations": ("GET", "/conversations"),
    "list_phone_numbers": ("GET", "/phone-numbers"),
    "get_phone_number": ("GET", "/phone-numbers/{phoneNumberId}"),
    "list_users": ("GET", "/users"),
}


_QUERY_NAMES = {
    "phone_number_id": "phoneNumberId",
    "user_id": "userId",
    "created_after": "createdAfter",
    "created_before": "createdBefore",
    "updated_after": "updatedAfter",
    "updated_before": "updatedBefore",
    "max_results": "maxResults",
    "page_token": "pageToken",
    "exclude_inactive": "excludeInactive",
}


def _split(value: Optional[str], maximum: int = 100) -> list[str]:
    items = [item.strip() for item in (value or "").split(",") if item.strip()]
    if not 1 <= len(items) <= maximum:
        raise ValueError(f"Supply between 1 and {maximum} nonempty values")
    return items


def _contact_body(config: QuoContactWriteFields) -> Dict[str, Any]:
    fields = {}
    for attr, wire in (
        ("first_name", "firstName"),
        ("last_name", "lastName"),
        ("company", "company"),
        ("role", "role"),
    ):
        value = getattr(config, attr)
        if value is not None:
            fields[wire] = value
    for attr, wire in (
        ("emails_json", "emails"),
        ("phone_numbers_json", "phoneNumbers"),
    ):
        values = getattr(config, attr)
        if values is not None:
            fields[wire] = [
                v.model_dump(exclude_none=True, exclude_unset=True) | {"value": v.value}
                for v in values
            ]
    body: Dict[str, Any] = {"defaultFields": fields}
    if config.custom_fields_json is not None:
        body["customFields"] = [
            v.model_dump(exclude_none=True, exclude_unset=True) | {"value": v.value}
            for v in config.custom_fields_json
        ]
    for attr, wire in (
        ("external_id", "externalId"),
        ("source", "source"),
        ("source_url", "sourceUrl"),
        ("created_by_user_id", "createdByUserId"),
    ):
        value = getattr(config, attr, None)
        if value is not None:
            body[wire] = value
    return body


class QuoNode(WorkflowNode):
    integration_type = "automation-quo"
    credential_provider_labels = {"quo": "Quo Account"}
    connection_evidence = ConnectionEvidence(
        operation="list_phone_numbers",
        noun="Quo phone numbers",
        label_keys=("name", "number", "id"),
    )
    edit_examples = [
        "Send a follow-up text to a lead after a call",
        "Sync CRM contacts to Quo using external IDs",
        "Retrieve a call recording, transcript and summary",
    ]

    @classmethod
    def get_config_model(cls):
        return QuoNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, QuoNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Quo API key in the credentials tab.")
        config = self.config.config
        operation = config.operation
        method, endpoint = _REQUESTS[operation]
        path_value = next(
            (
                getattr(config, attr)
                for attr in ("contact_id", "call_id", "message_id", "phone_number_id")
                if hasattr(config, attr)
            ),
            None,
        )
        if "{" in endpoint:
            endpoint = endpoint[: endpoint.index("{")] + quote(path_value, safe="")
        params: Dict[str, Any] = {}
        body = None
        if operation == "send_message":
            body = {
                "content": config.content,
                "from": config.from_number,
                "to": _split(config.to, 10),
            }
            if config.user_id:
                body["userId"] = config.user_id
            if config.set_inbox_status:
                body["setInboxStatus"] = config.set_inbox_status
        elif operation in ("create_contact", "update_contact"):
            body = _contact_body(config)
        elif method == "GET":
            for attr, wire in _QUERY_NAMES.items():
                value = getattr(config, attr, None)
                if (
                    value is not None
                    and value != ""
                    and not (
                        attr == "phone_number_id" and operation == "get_phone_number"
                    )
                ):
                    params[wire] = value
            if hasattr(config, "participants"):
                params["participants"] = _split(
                    config.participants, 1 if operation == "list_calls" else 10
                )
            for attr, wire in (
                ("external_ids", "externalIds"),
                ("sources", "sources"),
                ("phone_numbers", "phoneNumbers"),
            ):
                value = getattr(config, attr, None)
                if value and value.strip():
                    params[wire] = _split(value)
        started = time.monotonic()
        result = {"action": operation}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method,
                    QUO_API_BASE + endpoint,
                    headers={
                        "Authorization": self.config.credentials.api_key,
                        "Accept": "application/json",
                    },
                    params=params,
                    json=body,
                )
            result["status_code"] = response.status_code
            if not 200 <= response.status_code < 300:
                # Preserve provider rejection text for the shared connect seam.
                # Never return request headers or exception strings containing credentials.
                try:
                    error = response.json()
                    nested = error.get("error")
                    message = (
                        nested.get("message")
                        if isinstance(nested, dict)
                        else error.get("message")
                    )
                except (ValueError, AttributeError):
                    message = None
                message = str(
                    message or f"Quo API request failed (HTTP {response.status_code})"
                )
                result.update(
                    status="error",
                    error=message.replace(
                        self.config.credentials.api_key, "[redacted]"
                    ),
                )
            elif response.status_code == 204:
                result.update(status="success", data={"deleted": True})
            else:
                payload = response.json()
                if not isinstance(payload, dict) or "data" not in payload:
                    raise ValueError("Quo response is missing its data envelope")
                # Keep the provider's data objects and pagination metadata intact.
                result.update(status="success", data=payload["data"])
                for key in ("nextPageToken", "totalItems"):
                    if key in payload:
                        result[key] = payload[key]
        except httpx.TimeoutException:
            result.update(
                status="error", error="Quo request timed out", status_code=408
            )
        except httpx.RequestError:
            result.update(status="error", error="Could not reach the Quo API")
        except ValueError:
            result.update(
                status="error", error="Quo returned an invalid JSON data envelope"
            )
        result["timing_ms"] = {
            "api_request": round((time.monotonic() - started) * 1000, 2)
        }
        return result
