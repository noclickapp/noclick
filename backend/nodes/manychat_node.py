"""Manychat Account Public API (Page API beta), using a pasted bearer token.

Each operation makes one request to the provider's published endpoint. Search
limits are provider limits; sending a flow reports acceptance, not delivery.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.manychat.com"


class ManychatAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Manychat API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://help.manychat.com/hc/en-us/articles/14959510331420-API-Manychat",
        "x-credential-instructions": "In your Manychat account, open Settings → API and generate an Account Public API key (requires a supported paid plan). Paste the key without Bearer. Use the account key, not the Profile Public API key. NoClick reads your page information to check the connection.",
    })
    credential_type: Literal["manychat_api_token"] = Field("manychat_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a header prefix or whitespace")
        return value


FieldValue = Union[StrictStr, StrictInt, StrictFloat, StrictBool]


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)

    @model_validator(mode="after")
    def conditional_requirements(self):
        if self.operation == "find_subscriber_by_system_field" and not (self.email or self.phone):
            raise ValueError("Supply email or phone to find a contact")
        if self.operation in {"create_subscriber", "update_subscriber"}:
            if self.operation == "create_subscriber" and not (self.email or self.phone or self.whatsapp_phone):
                raise ValueError("Supply email, phone or WhatsApp phone to create a contact")
            if self.email and self.has_opt_in_email is None:
                raise ValueError("Specify the contact's email opt-in status")
            if self.phone and self.has_opt_in_sms is None:
                raise ValueError("Specify the contact's SMS opt-in status")
            if self.has_opt_in_sms and not self.consent_phrase:
                raise ValueError("Supply the SMS consent phrase")
            if self.operation == "update_subscriber" and not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "subscriber_id"}):
                raise ValueError("Supply at least one contact field to update")
        return self


class GetPageInfo(_Config):
    operation: Literal["get_page_info"] = Field("get_page_info", title='Get Page Info', description='', json_schema_extra={"ui:hidden": True})

class ListTags(_Config):
    operation: Literal["list_tags"] = Field("list_tags", title='List Tags', description='', json_schema_extra={"ui:hidden": True})

class CreateTag(_Config):
    operation: Literal["create_tag"] = Field("create_tag", title='Create Tag', description='', json_schema_extra={"ui:hidden": True})
    name: str = Field(... ,min_length=1)

class DeleteTag(_Config):
    operation: Literal["delete_tag"] = Field("delete_tag", title='Delete Tag', description='Permanently removes the tag from the page and all its contacts.', json_schema_extra={"ui:hidden": True})
    tag_id: int = Field(... ,ge=1)

class ListFlows(_Config):
    operation: Literal["list_flows"] = Field("list_flows", title='List Flows', description='', json_schema_extra={"ui:hidden": True})

class ListCustomFields(_Config):
    operation: Literal["list_custom_fields"] = Field("list_custom_fields", title='List Custom Fields', description='', json_schema_extra={"ui:hidden": True})

class CreateCustomField(_Config):
    operation: Literal["create_custom_field"] = Field("create_custom_field", title='Create Custom Field', description='', json_schema_extra={"ui:hidden": True})
    caption: str = Field(... ,min_length=1)
    type: Literal["text", "number", "date", "datetime", "boolean"] = Field(... ,min_length=1, description='Value from list: text, number, date, datetime, boolean')
    description: str | None = Field(None ,min_length=1)

class ListBotFields(_Config):
    operation: Literal["list_bot_fields"] = Field("list_bot_fields", title='List Bot Fields', description='', json_schema_extra={"ui:hidden": True})

class CreateBotField(_Config):
    operation: Literal["create_bot_field"] = Field("create_bot_field", title='Create Bot Field', description='', json_schema_extra={"ui:hidden": True})
    name: str = Field(... ,min_length=1)
    type: Literal["text", "number", "date", "datetime", "boolean"] = Field(... ,min_length=1, description='Value from list: text, number, date, datetime, boolean')
    description: str | None = Field(None ,min_length=1)
    value: FieldValue | None = Field(None ,description='string, integer or boolean (see method description for setBotField)')

class SetBotField(_Config):
    operation: Literal["set_bot_field"] = Field("set_bot_field", title='Set Bot Field', description='', json_schema_extra={"ui:hidden": True})
    field_id: int = Field(... ,ge=1)
    field_value: FieldValue = Field(... ,description='string, integer or boolean (see method description)')

class SetBotFieldByName(_Config):
    operation: Literal["set_bot_field_by_name"] = Field("set_bot_field_by_name", title='Set Bot Field By Name', description='', json_schema_extra={"ui:hidden": True})
    field_name: str = Field(... ,min_length=1)
    field_value: FieldValue = Field(... ,description='string, integer or boolean (see method description)')

class ListGrowthTools(_Config):
    operation: Literal["list_growth_tools"] = Field("list_growth_tools", title='List Growth Tools', description='', json_schema_extra={"ui:hidden": True})

class GetSubscriber(_Config):
    operation: Literal["get_subscriber"] = Field("get_subscriber", title='Get Subscriber', description='', json_schema_extra={"ui:hidden": True})
    subscriber_id: int = Field(... ,ge=1)

class FindSubscribersByName(_Config):
    operation: Literal["find_subscribers_by_name"] = Field("find_subscribers_by_name", title='Find Subscribers By Name', description='Returns at most 100 matches; Manychat provides no pagination for this search.', json_schema_extra={"ui:hidden": True})
    name: str = Field(... ,min_length=1)

class FindSubscribersByCustomField(_Config):
    operation: Literal["find_subscribers_by_custom_field"] = Field("find_subscribers_by_custom_field", title='Find Subscribers By Custom Field', description='Returns at most 100 matches; Manychat provides no pagination for this search.', json_schema_extra={"ui:hidden": True})
    field_id: int = Field(... ,ge=1)
    search_value: str = Field(..., min_length=1, serialization_alias="field_value", description="Text value to find in the custom field.")

class FindSubscriberBySystemField(_Config):
    operation: Literal["find_subscriber_by_system_field"] = Field("find_subscriber_by_system_field", title='Find Subscriber By System Field', description='', json_schema_extra={"ui:hidden": True})
    email: str | None = Field(None ,min_length=1)
    phone: str | None = Field(None ,min_length=1)

class AddSubscriberTag(_Config):
    operation: Literal["add_subscriber_tag"] = Field("add_subscriber_tag", title='Add Subscriber Tag', description='', json_schema_extra={"ui:hidden": True})
    subscriber_id: int = Field(... ,ge=1)
    tag_id: int = Field(... ,ge=1)

class AddSubscriberTagByName(_Config):
    operation: Literal["add_subscriber_tag_by_name"] = Field("add_subscriber_tag_by_name", title='Add Subscriber Tag By Name', description='', json_schema_extra={"ui:hidden": True})
    subscriber_id: int = Field(... ,ge=1)
    tag_name: str = Field(... ,min_length=1)

class RemoveSubscriberTag(_Config):
    operation: Literal["remove_subscriber_tag"] = Field("remove_subscriber_tag", title='Remove Subscriber Tag', description='', json_schema_extra={"ui:hidden": True})
    subscriber_id: int = Field(... ,ge=1)
    tag_id: int = Field(... ,ge=1)

class RemoveSubscriberTagByName(_Config):
    operation: Literal["remove_subscriber_tag_by_name"] = Field("remove_subscriber_tag_by_name", title='Remove Subscriber Tag By Name', description='', json_schema_extra={"ui:hidden": True})
    subscriber_id: int = Field(... ,ge=1)
    tag_name: str = Field(... ,min_length=1)

class SetSubscriberCustomField(_Config):
    operation: Literal["set_subscriber_custom_field"] = Field("set_subscriber_custom_field", title='Set Subscriber Custom Field', description='', json_schema_extra={"ui:hidden": True})
    subscriber_id: int = Field(... ,ge=1)
    field_id: int = Field(... ,ge=1)
    field_value: FieldValue = Field(... ,description='string, integer or boolean (see method description)')

class SetSubscriberCustomFieldByName(_Config):
    operation: Literal["set_subscriber_custom_field_by_name"] = Field("set_subscriber_custom_field_by_name", title='Set Subscriber Custom Field By Name', description='', json_schema_extra={"ui:hidden": True})
    subscriber_id: int = Field(... ,ge=1)
    field_name: str = Field(... ,min_length=1, description='not case sensitive')
    field_value: FieldValue = Field(... ,description='string, integer or boolean (see method description)')

class CreateSubscriber(_Config):
    operation: Literal["create_subscriber"] = Field("create_subscriber", title='Create Subscriber', description='', json_schema_extra={"ui:hidden": True})
    first_name: str | None = Field(None ,min_length=1, description='First Name')
    last_name: str | None = Field(None ,min_length=1, description='Last Name')
    phone: str | None = Field(None ,min_length=1, description='Phone Number is required if Email and Whatsapp Phone properties are empty')
    whatsapp_phone: str | None = Field(None ,min_length=1, description='Whatsapp Phone Number is required if Email and Phone Number properties are empty')
    email: str | None = Field(None ,min_length=1, description='Email is required if Phone Number and Whatsapp Phone properties are empty')
    gender: str | None = Field(None ,min_length=1, description='Gender')
    has_opt_in_sms: StrictBool | None = Field(None ,description='Has opt-in SMS is required if property Phone Number is not empty')
    has_opt_in_email: StrictBool | None = Field(None ,description='Has opt-in Email is required if property Email is not empty')
    consent_phrase: str | None = Field(None ,min_length=1, description='Consent phrase is required if property `has_opt_in_sms` equal true')

class UpdateSubscriber(_Config):
    operation: Literal["update_subscriber"] = Field("update_subscriber", title='Update Subscriber', description='', json_schema_extra={"ui:hidden": True})
    subscriber_id: int = Field(... ,ge=1)
    first_name: str | None = Field(None ,min_length=1, description='First Name')
    last_name: str | None = Field(None ,min_length=1, description='Last Name')
    phone: str | None = Field(None ,min_length=1, description='Phone Number')
    email: str | None = Field(None ,min_length=1, description='Email')
    gender: str | None = Field(None ,min_length=1, description='Gender')
    has_opt_in_sms: StrictBool | None = Field(None ,description='Has opt-in SMS is required if property Phone Number is not empty')
    has_opt_in_email: StrictBool | None = Field(None ,description='Has opt-in Email is required if property Email is not empty')
    consent_phrase: str | None = Field(None ,min_length=1, description='Consent phrase is required if property Has Opt In SMS equal true')

class SendFlow(_Config):
    operation: Literal["send_flow"] = Field("send_flow", title='Send Flow', description='Ask Manychat to send an existing flow to a contact; acceptance does not prove delivery.', json_schema_extra={"ui:hidden": True})
    subscriber_id: int = Field(... ,ge=1)
    flow_ns: str = Field(... ,min_length=1)


ManychatConfig = Annotated[Union[GetPageInfo, ListTags, CreateTag, DeleteTag, ListFlows, ListCustomFields, CreateCustomField, ListBotFields, CreateBotField, SetBotField, SetBotFieldByName, ListGrowthTools, GetSubscriber, FindSubscribersByName, FindSubscribersByCustomField, FindSubscriberBySystemField, AddSubscriberTag, AddSubscriberTagByName, RemoveSubscriberTag, RemoveSubscriberTagByName, SetSubscriberCustomField, SetSubscriberCustomFieldByName, CreateSubscriber, UpdateSubscriber, SendFlow], Field(discriminator="operation")]


class ManychatFullConfig(NodeConfig[ManychatConfig, ManychatAPITokenCredential]):
    pass


ROUTES = {'get_page_info': ('GET', '/fb/page/getInfo'), 'list_tags': ('GET', '/fb/page/getTags'), 'create_tag': ('POST', '/fb/page/createTag'), 'delete_tag': ('POST', '/fb/page/removeTag'), 'list_flows': ('GET', '/fb/page/getFlows'), 'list_custom_fields': ('GET', '/fb/page/getCustomFields'), 'create_custom_field': ('POST', '/fb/page/createCustomField'), 'list_bot_fields': ('GET', '/fb/page/getBotFields'), 'create_bot_field': ('POST', '/fb/page/createBotField'), 'set_bot_field': ('POST', '/fb/page/setBotField'), 'set_bot_field_by_name': ('POST', '/fb/page/setBotFieldByName'), 'list_growth_tools': ('GET', '/fb/page/getGrowthTools'), 'get_subscriber': ('GET', '/fb/subscriber/getInfo'), 'find_subscribers_by_name': ('GET', '/fb/subscriber/findByName'), 'find_subscribers_by_custom_field': ('GET', '/fb/subscriber/findByCustomField'), 'find_subscriber_by_system_field': ('GET', '/fb/subscriber/findBySystemField'), 'add_subscriber_tag': ('POST', '/fb/subscriber/addTag'), 'add_subscriber_tag_by_name': ('POST', '/fb/subscriber/addTagByName'), 'remove_subscriber_tag': ('POST', '/fb/subscriber/removeTag'), 'remove_subscriber_tag_by_name': ('POST', '/fb/subscriber/removeTagByName'), 'set_subscriber_custom_field': ('POST', '/fb/subscriber/setCustomField'), 'set_subscriber_custom_field_by_name': ('POST', '/fb/subscriber/setCustomFieldByName'), 'create_subscriber': ('POST', '/fb/subscriber/createSubscriber'), 'update_subscriber': ('POST', '/fb/subscriber/updateSubscriber'), 'send_flow': ('POST', '/fb/sending/sendFlow')}


def _check_family(config_data):
    credentials = config_data.get("credentials")
    if isinstance(credentials, dict) and "credential_type" in credentials and credentials["credential_type"] != "manychat_api_token":
        raise ValueError("Attach a Manychat API token credential")


class ManychatNode(WorkflowNode):
    integration_type = "automation-manychat"
    connection_evidence = ConnectionEvidence(identity_operation="get_page_info", noun="Manychat page")

    @classmethod
    def get_config_model(cls):
        return ManychatFullConfig

    @classmethod
    def parse_config(cls, config_data):
        _check_family(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _check_family(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Manychat API token")
        token = self.config.credentials.api_token
        config = self.config.config
        method, path = ROUTES[config.operation]
        payload = config.model_dump(mode="json", by_alias=True, exclude={"operation"}, exclude_none=True)
        kwargs = {"params" if method == "GET" else "json": payload}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        if response.is_redirect:
            raise ValueError("Manychat redirected the request")
        mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if mime != "application/json" or len(response.content) > 5_000_000:
            raise ValueError(f"Expected bounded JSON from Manychat (HTTP {response.status_code})")
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Unexpected Manychat response envelope")
        if not response.is_success or body.get("status") != "success" or body.get("error") or body.get("errors"):
            message = str(body.get("message") or body.get("error") or "Manychat did not confirm the request").replace(token, "[redacted]")
            raise ValueError(f"HTTP {response.status_code}: {message}")
        result = {"operation": config.operation, "status": "success"}
        if "data" in body:
            if not isinstance(body["data"], (dict, list)):
                raise ValueError("Unexpected Manychat data shape")
            result["data"] = body["data"]
        if method == "GET" or config.operation in {"create_tag", "create_custom_field", "create_bot_field", "create_subscriber", "update_subscriber"}:
            if "data" not in result:
                raise ValueError("Manychat response did not include data")
        if config.operation == "get_page_info":
            if not isinstance(result["data"], dict) or not result["data"].get("name") or not result["data"].get("id"):
                raise ValueError("Manychat did not return a page identity")
        if config.operation == "send_flow":
            result["accepted"] = True
            result["delivery_verified"] = False
        return result
