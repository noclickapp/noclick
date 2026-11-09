"""BotConversa webhook API BETA. Each operation makes one documented request."""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE_URL = "https://backend.botconversa.com.br/api/v1/webhook"
DOCS_URL = "https://backend.botconversa.com.br/swagger/"


class BotConversaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="BotConversa API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": DOCS_URL,
            "x-credential-instructions": "Copy your API key from BotConversa. Paste the key without a header name or prefix; the API documentation describes API-KEY authentication."})
    credential_type: Literal["botconversa_api_key"] = Field("botconversa_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False,
        description="Your BotConversa API key, sent in the API-KEY header.", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste a valid API key without spaces or control characters")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("subscriber_id", "campaign_id", "tag_id", "sequence_id", "custom_field_id", "bot_variable_id", check_fields=False)
    @classmethod
    def identifier(cls, value):
        if isinstance(value, int):
            return value
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Use a single BotConversa resource ID")
        return value


class ListBotFieldsConfig(_Config):
    operation: Literal["list_bot_fields"] = Field("list_bot_fields", title="List Bot Fields", json_schema_extra={"ui:hidden": True})

class ListCampaignsConfig(_Config):
    operation: Literal["list_campaigns"] = Field("list_campaigns", title="List Campaigns", json_schema_extra={"ui:hidden": True})

class ListCustomFieldsConfig(_Config):
    operation: Literal["list_custom_fields"] = Field("list_custom_fields", title="List Custom Fields", json_schema_extra={"ui:hidden": True})

class ListFlowsConfig(_Config):
    operation: Literal["list_flows"] = Field("list_flows", title="List Flows", json_schema_extra={"ui:hidden": True})

class ListManagersConfig(_Config):
    operation: Literal["list_managers"] = Field("list_managers", title="List Managers", json_schema_extra={"ui:hidden": True})

class ListSequencesConfig(_Config):
    operation: Literal["list_sequences"] = Field("list_sequences", title="List Sequences", json_schema_extra={"ui:hidden": True})

class ListTagsConfig(_Config):
    operation: Literal["list_tags"] = Field("list_tags", title="List Tags", json_schema_extra={"ui:hidden": True})

class ListSubscribersConfig(_Config):
    operation: Literal["list_subscribers"] = Field("list_subscribers", title="List Subscribers", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, title="Page", description="One page per execution; use next/previous in the returned data to select a page.")

class GetCampaignConfig(_Config):
    operation: Literal["get_campaign"] = Field("get_campaign", title="Get Campaign", json_schema_extra={"ui:hidden": True})
    campaign_id: int = Field(..., ge=1, title="Campaign ID")

class FindSubscriberByPhoneConfig(_Config):
    operation: Literal["find_subscriber_by_phone"] = Field("find_subscriber_by_phone", title="Find Subscriber By Phone", json_schema_extra={"ui:hidden": True})
    phone: str = Field(..., min_length=1, title="Phone")

    @field_validator("phone")
    @classmethod
    def phone_segment(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value):
            raise ValueError("Use a phone number")
        return value

class CreateSubscriberConfig(_Config):
    operation: Literal["create_subscriber"] = Field("create_subscriber", title="Create Subscriber", json_schema_extra={"ui:hidden": True})
    phone: str = Field(..., min_length=1, title="Phone", description="Full phone number including country code.")
    first_name: str = Field(..., min_length=1, title="First Name")
    last_name: str = Field(..., min_length=1, title="Last Name")
    has_opt_in_whatsapp: bool = Field(..., title="WhatsApp Opt In", description="Whether this contact has opted in to WhatsApp messages.")

class SendMessageConfig(_Config):
    operation: Literal["send_message"] = Field("send_message", title="Send Message", json_schema_extra={"ui:hidden": True})
    subscriber_id: str = Field(..., min_length=1, title="Subscriber Id")
    type: Literal["text", "file"] = Field("text", title="Message Type")
    value: str = Field(..., min_length=1, title="Message or File URL")

class SendFlowConfig(_Config):
    operation: Literal["send_flow"] = Field("send_flow", title="Send Flow", json_schema_extra={"ui:hidden": True})
    subscriber_id: str = Field(..., min_length=1, title="Subscriber Id")
    flow: int = Field(..., ge=1, title="Flow ID")

class ChangeConversationStatusConfig(_Config):
    operation: Literal["change_conversation_status"] = Field("change_conversation_status", title="Change Conversation Status", json_schema_extra={"ui:hidden": True})
    subscriber_id: str = Field(..., min_length=1, title="Subscriber Id")
    open_conversation: bool = Field(..., title="Open Conversation")
    manager: int | None = Field(None, ge=1, title="Manager ID")

class SetCustomFieldConfig(_Config):
    operation: Literal["set_custom_field"] = Field("set_custom_field", title="Set Custom Field", json_schema_extra={"ui:hidden": True})
    subscriber_id: str = Field(..., min_length=1, title="Subscriber Id")
    custom_field_id: str = Field(..., min_length=1, title="Custom Field Id")
    value: str = Field(..., title="Value", description="Text, a number, a date dd.mm.yyyy, or datetime dd.mm.yyyy HH:MM:SS.")

class ClearCustomFieldConfig(_Config):
    operation: Literal["clear_custom_field"] = Field("clear_custom_field", title="Clear Custom Field", json_schema_extra={"ui:hidden": True})
    subscriber_id: str = Field(..., min_length=1, title="Subscriber Id")
    custom_field_id: str = Field(..., min_length=1, title="Custom Field Id")

class SetBotFieldConfig(_Config):
    operation: Literal["set_bot_field"] = Field("set_bot_field", title="Set Bot Field", json_schema_extra={"ui:hidden": True})
    bot_variable_id: str = Field(..., min_length=1, title="Bot Variable Id")
    value: str = Field(..., title="Value")

class DeleteSubscriberConfig(_Config):
    operation: Literal["delete_subscriber"] = Field("delete_subscriber", title="Delete Subscriber", json_schema_extra={"ui:hidden": True})
    subscriber_id: str = Field(..., min_length=1, title="Subscriber Id")

class AddSubscriberTagConfig(_Config):
    operation: Literal["add_subscriber_tag"] = Field("add_subscriber_tag", title="Add Subscriber Tag", json_schema_extra={"ui:hidden": True})
    subscriber_id: str = Field(..., min_length=1, title="Subscriber Id")
    tag_id: str = Field(..., min_length=1, title="Tag Id")

class RemoveSubscriberTagConfig(_Config):
    operation: Literal["remove_subscriber_tag"] = Field("remove_subscriber_tag", title="Remove Subscriber Tag", json_schema_extra={"ui:hidden": True})
    subscriber_id: str = Field(..., min_length=1, title="Subscriber Id")
    tag_id: str = Field(..., min_length=1, title="Tag Id")

class AddSubscriberCampaignConfig(_Config):
    operation: Literal["add_subscriber_campaign"] = Field("add_subscriber_campaign", title="Add Subscriber Campaign", json_schema_extra={"ui:hidden": True})
    subscriber_id: str = Field(..., min_length=1, title="Subscriber Id")
    campaign_id: str = Field(..., min_length=1, title="Campaign Id")

class RemoveSubscriberCampaignConfig(_Config):
    operation: Literal["remove_subscriber_campaign"] = Field("remove_subscriber_campaign", title="Remove Subscriber Campaign", json_schema_extra={"ui:hidden": True})
    subscriber_id: str = Field(..., min_length=1, title="Subscriber Id")
    campaign_id: str = Field(..., min_length=1, title="Campaign Id")

class AddSubscriberSequenceConfig(_Config):
    operation: Literal["add_subscriber_sequence"] = Field("add_subscriber_sequence", title="Add Subscriber Sequence", json_schema_extra={"ui:hidden": True})
    subscriber_id: str = Field(..., min_length=1, title="Subscriber Id")
    sequence_id: str = Field(..., min_length=1, title="Sequence Id")

class RemoveSubscriberSequenceConfig(_Config):
    operation: Literal["remove_subscriber_sequence"] = Field("remove_subscriber_sequence", title="Remove Subscriber Sequence", json_schema_extra={"ui:hidden": True})
    subscriber_id: str = Field(..., min_length=1, title="Subscriber Id")
    sequence_id: str = Field(..., min_length=1, title="Sequence Id")


Operation = Annotated[Union[ListBotFieldsConfig, ListCampaignsConfig, ListCustomFieldsConfig, ListFlowsConfig, ListManagersConfig, ListSequencesConfig, ListTagsConfig, ListSubscribersConfig, GetCampaignConfig, FindSubscriberByPhoneConfig, CreateSubscriberConfig, SendMessageConfig, SendFlowConfig, ChangeConversationStatusConfig, SetCustomFieldConfig, ClearCustomFieldConfig, SetBotFieldConfig, DeleteSubscriberConfig, AddSubscriberTagConfig, RemoveSubscriberTagConfig, AddSubscriberCampaignConfig, RemoveSubscriberCampaignConfig, AddSubscriberSequenceConfig, RemoveSubscriberSequenceConfig], Field(discriminator="operation")]


class BotConversaNodeConfig(NodeConfig[Operation, BotConversaAPIKeyCredential]):
    pass


ROUTES = {'list_bot_fields': ('GET', '/bot_fields/', []),
 'list_campaigns': ('GET', '/campaigns/', []),
 'list_custom_fields': ('GET', '/custom_fields/', []),
 'list_flows': ('GET', '/flows/', []),
 'list_managers': ('GET', '/managers/', []),
 'list_sequences': ('GET', '/sequences/', []),
 'list_tags': ('GET', '/tags/', []),
 'list_subscribers': ('GET', '/subscribers/', ['page']),
 'get_campaign': ('GET', '/campaigns/{campaign_id}/', []),
 'find_subscriber_by_phone': ('GET', '/subscriber/get_by_phone/{phone}/', []),
 'create_subscriber': ('POST',
                       '/subscriber/',
                       ['phone', 'first_name', 'last_name', 'has_opt_in_whatsapp']),
 'send_message': ('POST', '/subscriber/{subscriber_id}/send_message/', ['type', 'value']),
 'send_flow': ('POST', '/subscriber/{subscriber_id}/send_flow/', ['flow']),
 'change_conversation_status': ('POST',
                                '/subscriber/{subscriber_id}/change_conversation_status/',
                                ['open_conversation', 'manager']),
 'set_custom_field': ('POST',
                      '/subscriber/{subscriber_id}/custom_fields/{custom_field_id}/',
                      ['value']),
 'clear_custom_field': ('DELETE',
                        '/subscriber/{subscriber_id}/custom_fields/{custom_field_id}/',
                        []),
 'set_bot_field': ('POST', '/bot_fields/{bot_variable_id}/', ['value']),
 'delete_subscriber': ('DELETE', '/subscriber/{subscriber_id}/delete/', []),
 'add_subscriber_tag': ('POST', '/subscriber/{subscriber_id}/tags/{tag_id}/', []),
 'remove_subscriber_tag': ('DELETE', '/subscriber/{subscriber_id}/tags/{tag_id}/', []),
 'add_subscriber_campaign': ('POST', '/subscriber/{subscriber_id}/campaigns/{campaign_id}/', []),
 'remove_subscriber_campaign': ('DELETE',
                                '/subscriber/{subscriber_id}/campaigns/{campaign_id}/',
                                []),
 'add_subscriber_sequence': ('POST', '/subscriber/{subscriber_id}/sequences/{sequence_id}/', []),
 'remove_subscriber_sequence': ('DELETE',
                                '/subscriber/{subscriber_id}/sequences/{sequence_id}/',
                                [])}


class BotConversaNode(WorkflowNode):
    integration_type = "automation-botconversa"
    connection_evidence = ConnectionEvidence(operation="list_tags", noun="tags", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return BotConversaNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a BotConversa API key")
        config = self.config.config
        values = config.model_dump(exclude_none=True)
        method, template, body_fields = ROUTES[config.operation]
        path = template
        for field in re.findall(r"{(\w+)}", template):
            path = path.replace("{" + field + "}", quote(str(values[field]), safe=""))
        params = {"page": values["page"]} if config.operation == "list_subscribers" else None
        body = {k: values[k] for k in body_fields if k in values} if method != "GET" else None
        key = self.config.credentials.api_key
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"API-KEY": key, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            try:
                error = response.json().get("error_message")
            except (ValueError, AttributeError):
                error = None
            message = error if isinstance(error, str) else f"BotConversa returned HTTP {response.status_code}"
            message = message.replace(key, "[redacted]")
            raise ValueError(f"{message} (HTTP {response.status_code})")
        data = response.json() if response.content else {}
        if isinstance(data, dict) and data.get("error_message"):
            raise ValueError(str(data["error_message"]).replace(key, "[redacted]"))
        if not isinstance(data, (dict, list)):
            raise ValueError("BotConversa returned an unexpected JSON response")
        result = {"status": "success", "data": data}
        await self.emit(result)
        return result
