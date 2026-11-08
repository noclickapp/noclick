"""ChatBotKit v1 bots, conversations, knowledge records and contacts.

Wire contract: https://api.chatbotkit.com/v1/spec
Authentication and cursor pagination: https://chatbotkit.com/docs/api
Every operation issues one request; list results contain one page and the
provider's cursor. Mutations are never retried automatically.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.chatbotkit.com/v1"


class ChatBotKitAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Chatbotkit API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://chatbotkit.com/tokens",
            "x-credential-instructions": "Create an API token in ChatBotKit developer tools and paste it here without the Bearer prefix. Use a token allowed to access the bots, conversations, datasets and contacts your workflow needs. NoClick checks the connection by listing your bots.",
        })
    credential_type: Literal["chatbotkit_api_token"] = Field("chatbotkit_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", repr=False,
        json_schema_extra={"ui:widget": "password", "ui:help": "Copy the token from ChatBotKit developer tools."})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() for c in value) or value.lower().startswith("bearer "):
            raise ValueError("Paste the API token without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    cursor: str | None = Field(None, max_length=1024, description="The cursor returned by the previous page. Omit for the first page.")
    take: int = Field(20, ge=1, le=100, description="Maximum items on this page.")
    order: Literal["asc", "desc"] = "desc"


class _Named(_Input):
    name: str | None = Field(None, max_length=1000)
    description: str | None = Field(None, max_length=100000)


class _BotFields(_Named):
    model: str | None = Field(None, max_length=1000, description="ChatBotKit model identifier; omit to use the provider default.")
    backstory: str | None = Field(None, max_length=100000)
    dataset_id: str | None = Field(None, max_length=512)
    skillset_id: str | None = Field(None, max_length=512)
    privacy: bool | None = None
    moderation: bool | None = None


class _ContactFields(_Named):
    email: str | None = Field(None, max_length=1000)
    phone: str | None = Field(None, max_length=1000)
    nick: str | None = Field(None, max_length=1000)
    preferences: str | None = Field(None, max_length=100000)


class ListBots(_Page):
    """List one page of bots; reuse the returned cursor for the next page."""
    operation: Literal["list_bots"] = Field("list_bots", json_schema_extra={"ui:hidden": True})


class GetBot(_Input):
    """Fetch a bot by its ID."""
    operation: Literal["get_bot"] = Field("get_bot", json_schema_extra={"ui:hidden": True})
    bot_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Bot Id")


class CreateBot(_BotFields):
    """Create a bot with optional model and knowledge configuration."""
    operation: Literal["create_bot"] = Field("create_bot", json_schema_extra={"ui:hidden": True})


class UpdateBot(_BotFields):
    """Update supplied bot fields; omitted fields stay unchanged."""
    operation: Literal["update_bot"] = Field("update_bot", json_schema_extra={"ui:hidden": True})
    bot_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Bot Id")


class DeleteBot(_Input):
    """Delete the specified bot."""
    operation: Literal["delete_bot"] = Field("delete_bot", json_schema_extra={"ui:hidden": True})
    bot_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Bot Id")


class ListConversations(_Page):
    """List one page of conversations; reuse the returned cursor for the next page."""
    operation: Literal["list_conversations"] = Field("list_conversations", json_schema_extra={"ui:hidden": True})


class GetConversation(_Input):
    """Fetch a conversation by its ID."""
    operation: Literal["get_conversation"] = Field("get_conversation", json_schema_extra={"ui:hidden": True})
    conversation_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Conversation Id")


class CreateConversation(_Named):
    """Create a conversation initialized from an existing bot."""
    operation: Literal["create_conversation"] = Field("create_conversation", json_schema_extra={"ui:hidden": True})
    contact_id: str | None = Field(None, max_length=512, description="Optional contact associated with this conversation.")
    bot_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Bot Id")


class CompleteConversation(_Input):
    """Send a user message and receive the generated response; may use ChatBotKit credits."""
    operation: Literal["complete_conversation"] = Field("complete_conversation", json_schema_extra={"ui:hidden": True})
    conversation_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Conversation Id")
    text: str = Field(..., min_length=1, max_length=100000, description="Send this user message and generate the next response.")


class ListConversationMessages(_Page):
    """List one page of messages from a conversation."""
    operation: Literal["list_conversation_messages"] = Field("list_conversation_messages", json_schema_extra={"ui:hidden": True})
    conversation_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Conversation Id")


class DeleteConversation(_Input):
    """Delete the specified conversation."""
    operation: Literal["delete_conversation"] = Field("delete_conversation", json_schema_extra={"ui:hidden": True})
    conversation_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Conversation Id")


class ListDatasets(_Page):
    """List one page of datasets; reuse the returned cursor for the next page."""
    operation: Literal["list_datasets"] = Field("list_datasets", json_schema_extra={"ui:hidden": True})


class GetDataset(_Input):
    """Fetch a dataset by its ID."""
    operation: Literal["get_dataset"] = Field("get_dataset", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Dataset Id")


class CreateDataset(_Named):
    """Create a knowledge dataset."""
    operation: Literal["create_dataset"] = Field("create_dataset", json_schema_extra={"ui:hidden": True})


class SearchDataset(_Input):
    """Search a dataset for matching knowledge records."""
    operation: Literal["search_dataset"] = Field("search_dataset", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Dataset Id")
    search: str = Field(..., min_length=1, max_length=100000, description="Search query for the knowledge dataset.")


class ListContacts(_Page):
    """List one page of contacts; reuse the returned cursor for the next page."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})


class GetContact(_Input):
    """Fetch a contact by its ID."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Contact Id")


class CreateContact(_ContactFields):
    """Create a contact with the supplied profile fields."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})


class UpdateContact(_ContactFields):
    """Update supplied contact fields; omitted fields stay unchanged."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Contact Id")


class DeleteContact(_Input):
    """Delete the specified contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})
    contact_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Contact Id")


class ListDatasetRecords(_Page):
    """List one page of records in a dataset."""
    operation: Literal["list_dataset_records"] = Field("list_dataset_records", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Dataset Id")


class GetDatasetRecord(_Input):
    """Fetch a record from the selected dataset."""
    operation: Literal["get_dataset_record"] = Field("get_dataset_record", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Dataset Id")
    record_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Record Id")


class CreateDatasetRecord(_Input):
    """Add text to a dataset as a knowledge record."""
    operation: Literal["create_dataset_record"] = Field("create_dataset_record", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Dataset Id")
    text: str = Field(..., min_length=1, max_length=100000)
    source: str | None = Field(None, max_length=10000)


class UpdateDatasetRecord(_Input):
    """Replace the text and optional source of a knowledge record."""
    operation: Literal["update_dataset_record"] = Field("update_dataset_record", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Dataset Id")
    record_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Record Id")
    text: str = Field(..., min_length=1, max_length=100000)
    source: str | None = Field(None, max_length=10000)


class DeleteDatasetRecord(_Input):
    """Delete a record from the selected dataset."""
    operation: Literal["delete_dataset_record"] = Field("delete_dataset_record", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Dataset Id")
    record_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Record Id")


ChatBotKitConfig = Annotated[Union[
    ListBots,
    GetBot,
    CreateBot,
    UpdateBot,
    DeleteBot,
    ListConversations,
    GetConversation,
    CreateConversation,
    CompleteConversation,
    ListConversationMessages,
    DeleteConversation,
    ListDatasets,
    GetDataset,
    CreateDataset,
    SearchDataset,
    ListContacts,
    GetContact,
    CreateContact,
    UpdateContact,
    DeleteContact,
    ListDatasetRecords,
    GetDatasetRecord,
    CreateDatasetRecord,
    UpdateDatasetRecord,
    DeleteDatasetRecord
], Field(discriminator="operation")]


class ChatBotKitFullConfig(NodeConfig[ChatBotKitConfig, ChatBotKitAPITokenCredential]):
    pass


ROUTES = {
    "list_bots": ("GET", "/bot/list"),
    "get_bot": ("GET", "/bot/{bot_id}/fetch"),
    "create_bot": ("POST", "/bot/create"),
    "update_bot": ("POST", "/bot/{bot_id}/update"),
    "delete_bot": ("POST", "/bot/{bot_id}/delete"),
    "list_conversations": ("GET", "/conversation/list"),
    "get_conversation": ("GET", "/conversation/{conversation_id}/fetch"),
    "create_conversation": ("POST", "/conversation/create"),
    "complete_conversation": ("POST", "/conversation/{conversation_id}/complete"),
    "list_conversation_messages": ("GET", "/conversation/{conversation_id}/message/list"),
    "delete_conversation": ("POST", "/conversation/{conversation_id}/delete"),
    "list_datasets": ("GET", "/dataset/list"),
    "get_dataset": ("GET", "/dataset/{dataset_id}/fetch"),
    "create_dataset": ("POST", "/dataset/create"),
    "search_dataset": ("POST", "/dataset/{dataset_id}/search"),
    "list_contacts": ("GET", "/contact/list"),
    "get_contact": ("GET", "/contact/{contact_id}/fetch"),
    "create_contact": ("POST", "/contact/create"),
    "update_contact": ("POST", "/contact/{contact_id}/update"),
    "delete_contact": ("POST", "/contact/{contact_id}/delete"),
    "list_dataset_records": ("GET", "/dataset/{dataset_id}/record/list"),
    "get_dataset_record": ("GET", "/dataset/{dataset_id}/record/{record_id}/fetch"),
    "create_dataset_record": ("POST", "/dataset/{dataset_id}/record/create"),
    "update_dataset_record": ("POST", "/dataset/{dataset_id}/record/{record_id}/update"),
    "delete_dataset_record": ("POST", "/dataset/{dataset_id}/record/{record_id}/delete"),
}

WIRE_NAMES = {"bot_id": "botId", "conversation_id": "conversationId", "dataset_id": "datasetId",
              "record_id": "recordId", "contact_id": "contactId", "skillset_id": "skillsetId"}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class ChatBotKitNode(WorkflowNode):
    integration_type = "automation-chatbotkit"
    connection_evidence = ConnectionEvidence(operation="list_bots", noun="bots", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return ChatBotKitFullConfig

    async def execute(self, inputs):
        op = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Attach a ChatBotKit API token")
        token = credential.api_token
        method, route = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for key in list(values):
            if "{" + key + "}" in route:
                route = route.replace("{" + key + "}", quote(values.pop(key), safe=""))
        values = {WIRE_NAMES.get(k, k): v for k, v in values.items()}
        http_status = None
        try:
            async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + route,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    **({"params": values} if method == "GET" else {"json": values}))
            http_status = response.status_code
            if http_status != 200:
                message = "ChatBotKit returned HTTP " + str(http_status)
                try:
                    error = response.json()
                    if isinstance(error, dict) and isinstance(error.get("message"), str):
                        message = error["message"]
                except ValueError:
                    pass
                return {"status": "error", "http_status": http_status, "message": _redact(message, token)}
            if response.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
                raise ValueError("Expected a JSON response from ChatBotKit")
            data = response.json()
            if not isinstance(data, dict) or data.get("error") or data.get("code"):
                raise ValueError("ChatBotKit returned an invalid response envelope")
            if op.operation.startswith("list_"):
                if not isinstance(data.get("items"), list):
                    raise ValueError("ChatBotKit did not return an items page")
            elif op.operation == "search_dataset":
                if not isinstance(data.get("records"), list):
                    raise ValueError("ChatBotKit did not return search records")
            elif not isinstance(data.get("id"), str):
                raise ValueError("ChatBotKit did not return a resource ID")
            return {"status": "success", "data": _redact(data, token), "http_status": http_status}
        except (httpx.HTTPError, ValueError) as exc:
            return {"status": "error", "http_status": http_status,
                    "message": _redact(str(exc), token),
                    "write_outcome": "unverified" if method == "POST" else None}
