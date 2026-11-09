"""Mobile Text Alerts v8 operations using the provider's v3 HTTPS API.

Requests follow the published Postman collection; lists return one default page.
Saved response examples are pinned separately in this integration's fixtures.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-mobile-text-alerts"
CREDENTIAL_TYPE = "mobile_text_alerts_api_key"
BASE_URL = "https://api.mobile-text-alerts.com/v3"
DOCS = "https://docs.mobile-text-alerts.com/"


class MobileTextAlertsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Mobile Text Alerts API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": DOCS + "#authentication",
            "x-credential-instructions": "Paste the API key assigned to your Mobile Text Alerts account. NoClick sends it as a Bearer token to api.mobile-text-alerts.com and reads your groups to check the connection.",
        })
    credential_type: Literal["mobile_text_alerts_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_api_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(char.isspace() for char in value):
            raise ValueError("Paste the API key without the Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)


class _SubscriberFields(_Input):
    firstName: Optional[str] = Field(None, max_length=1000)
    lastName: Optional[str] = Field(None, max_length=1000)
    number: Optional[int] = Field(None, ge=1)
    email: Optional[str] = Field(None, min_length=3, max_length=320)
    groupIds: Optional[list[int]] = Field(None, max_length=10000, description="Replaces group membership on update; omit to keep provider behavior.")


class _GroupFields(_Input):
    name: Optional[str] = Field(None, min_length=1, max_length=1000)
    hidden: Optional[Literal[0, 1]] = None
    displayName: Optional[str] = Field(None, max_length=1000)
    welcomeMessage: Optional[str] = Field(None, max_length=10000)
    sortOrder: Optional[int] = None


class _TemplateFields(_Input):
    name: Optional[str] = Field(None, max_length=1000)
    attachment: Optional[str] = Field(None, max_length=4000)
    isMMS: Optional[bool] = None


class ListSubscribersConfig(_Input):
    """List Subscribers. Returns the provider default page and pagination metadata; no automatic pagination."""
    operation: Literal["list_subscribers"] = Field("list_subscribers", json_schema_extra={"ui:hidden": True})

class GetSubscriberConfig(_Input):
    """Get Subscriber."""
    operation: Literal["get_subscriber"] = Field("get_subscriber", json_schema_extra={"ui:hidden": True})
    idOrNumber: str = Field(..., min_length=1, max_length=32, pattern=r"^[0-9]+$")

class CreateSubscriberConfig(_SubscriberFields):
    """Create Subscriber. Existing phone numbers or emails are updated by the provider."""
    operation: Literal["create_subscriber"] = Field("create_subscriber", json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def check_fields(self):
        if self.number is None and self.email is None:
            raise ValueError("Provide a phone number or email")
        return self

class UpdateSubscriberConfig(_SubscriberFields):
    """Update Subscriber."""
    operation: Literal["update_subscriber"] = Field("update_subscriber", json_schema_extra={"ui:hidden": True})
    idOrNumber: str = Field(..., min_length=1, max_length=32, pattern=r"^[0-9]+$")

    @model_validator(mode="after")
    def check_fields(self):
        if not self.model_fields_set.difference({"operation", "idOrNumber"}):
            raise ValueError("Provide at least one subscriber field")
        return self

class DeleteSubscriberConfig(_Input):
    """Delete Subscriber. Provider acknowledges even invalid IDs; this does not prove deletion."""
    operation: Literal["delete_subscriber"] = Field("delete_subscriber", json_schema_extra={"ui:hidden": True})
    idOrNumber: str = Field(..., min_length=1, max_length=32, pattern=r"^[0-9]+$")

class ListGroupsConfig(_Input):
    """List Groups. Returns the provider default page and pagination metadata; no automatic pagination."""
    operation: Literal["list_groups"] = Field("list_groups", json_schema_extra={"ui:hidden": True})

class CreateGroupConfig(_GroupFields):
    """Create Group."""
    operation: Literal["create_group"] = Field("create_group", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)

class UpdateGroupConfig(_GroupFields):
    """Update Group."""
    operation: Literal["update_group"] = Field("update_group", json_schema_extra={"ui:hidden": True})
    groupId: int = Field(..., ge=1)

    @model_validator(mode="after")
    def check_fields(self):
        if not self.model_fields_set.difference({"operation", "groupId"}):
            raise ValueError("Provide at least one group field")
        return self

class DeleteGroupConfig(_Input):
    """Delete Group."""
    operation: Literal["delete_group"] = Field("delete_group", json_schema_extra={"ui:hidden": True})
    groupId: int = Field(..., ge=1)

class AddGroupMemberConfig(_Input):
    """Add Group Member."""
    operation: Literal["add_group_member"] = Field("add_group_member", json_schema_extra={"ui:hidden": True})
    groupId: int = Field(..., ge=1)
    subscriberId: int = Field(..., ge=1)
    addToDripCampaigns: bool = Field(True, description="Provider default is true: adding a member can start drip campaigns.")

class DeleteGroupMemberConfig(_Input):
    """Delete Group Member."""
    operation: Literal["delete_group_member"] = Field("delete_group_member", json_schema_extra={"ui:hidden": True})
    groupId: int = Field(..., ge=1)
    subscriberId: int = Field(..., ge=1)

class ListTemplatesConfig(_Input):
    """List Templates. Returns the provider default page and pagination metadata; no automatic pagination."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})

class GetTemplateConfig(_Input):
    """Get Template. Uses the provider default template namespace."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})
    templateId: int = Field(..., ge=1)

class CreateTemplateConfig(_TemplateFields):
    """Create Template."""
    operation: Literal["create_template"] = Field("create_template", json_schema_extra={"ui:hidden": True})
    message: str = Field(..., min_length=1, max_length=10000)

class UpdateTemplateConfig(_TemplateFields):
    """Update Template."""
    operation: Literal["update_template"] = Field("update_template", json_schema_extra={"ui:hidden": True})
    templateId: int = Field(..., ge=1)
    message: str = Field(..., min_length=1, max_length=10000)

class DeleteTemplateConfig(_Input):
    """Delete Template."""
    operation: Literal["delete_template"] = Field("delete_template", json_schema_extra={"ui:hidden": True})
    templateId: int = Field(..., ge=1)
    isMMS: bool = False

class SendMessageConfig(_Input):
    """Send Message. Sends now, or schedules when scheduledDate is supplied; acceptance does not prove delivery."""
    operation: Literal["send_message"] = Field("send_message", json_schema_extra={"ui:hidden": True})
    message: str = Field(..., min_length=1, max_length=10000)
    subscribers: Optional[list[Union[int, str]]] = Field(None, min_length=1, max_length=10000)
    groups: Optional[list[int]] = Field(None, min_length=1, max_length=10000)
    allSubscribers: bool = False
    scheduledDate: Optional[str] = Field(None, description="ISO8601 scheduled send time; omit to send now.")
    isMMS: Optional[bool] = None
    image: Optional[str] = Field(None, max_length=4000)
    externalId: Optional[str] = Field(None, max_length=1000)
    request_id: Optional[str] = Field(None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9]+$", description="X-Request-Id for duplicate detection. Reuse only for the same logical send.")

    @model_validator(mode="after")
    def check_fields(self):
        if not (self.subscribers or self.groups or self.allSubscribers):
            raise ValueError("Choose subscribers, groups, or all subscribers")
        if self.allSubscribers and (self.subscribers or self.groups):
            raise ValueError("All subscribers cannot be combined with other recipient fields")
        return self

class GetMessageCostConfig(_Input):
    """Get Message Cost."""
    operation: Literal["get_message_cost"] = Field("get_message_cost", json_schema_extra={"ui:hidden": True})
    from_number: str = Field(..., alias="from", min_length=1, max_length=32)
    to: str = Field(..., min_length=1, max_length=32)
    message: Optional[str] = Field(None, max_length=10000)
    isMMS: bool = False

class ListScheduledMessagesConfig(_Input):
    """List Scheduled Messages. Returns the provider default page and pagination metadata; no automatic pagination."""
    operation: Literal["list_scheduled_messages"] = Field("list_scheduled_messages", json_schema_extra={"ui:hidden": True})

class GetScheduledMessageConfig(_Input):
    """Get Scheduled Message."""
    operation: Literal["get_scheduled_message"] = Field("get_scheduled_message", json_schema_extra={"ui:hidden": True})
    scheduledMessageId: int = Field(..., ge=1)

class ListKeywordsConfig(_Input):
    """List Keywords. Returns the provider default page and pagination metadata; no automatic pagination."""
    operation: Literal["list_keywords"] = Field("list_keywords", json_schema_extra={"ui:hidden": True})

class ListDeliveriesConfig(_Input):
    """List Deliveries. Returns the provider default page and pagination metadata; no automatic pagination."""
    operation: Literal["list_deliveries"] = Field("list_deliveries", json_schema_extra={"ui:hidden": True})

class UnsubscribePhoneNumberConfig(_Input):
    """Unsubscribe Phone Number."""
    operation: Literal["unsubscribe_phone_number"] = Field("unsubscribe_phone_number", json_schema_extra={"ui:hidden": True})
    number: str = Field(..., min_length=1, max_length=32, pattern=r"^[0-9]+$")

class GetUnsubscribeStatusConfig(_Input):
    """Get Unsubscribe Status."""
    operation: Literal["get_unsubscribe_status"] = Field("get_unsubscribe_status", json_schema_extra={"ui:hidden": True})
    number: str = Field(..., min_length=1, max_length=32, pattern=r"^[0-9]+$")

class ListUnsubscribesConfig(_Input):
    """List Unsubscribes. Returns the provider default page and pagination metadata; no automatic pagination."""
    operation: Literal["list_unsubscribes"] = Field("list_unsubscribes", json_schema_extra={"ui:hidden": True})

MobileTextAlertsConfig = Annotated[Union[
    ListSubscribersConfig,
    GetSubscriberConfig,
    CreateSubscriberConfig,
    UpdateSubscriberConfig,
    DeleteSubscriberConfig,
    ListGroupsConfig,
    CreateGroupConfig,
    UpdateGroupConfig,
    DeleteGroupConfig,
    AddGroupMemberConfig,
    DeleteGroupMemberConfig,
    ListTemplatesConfig,
    GetTemplateConfig,
    CreateTemplateConfig,
    UpdateTemplateConfig,
    DeleteTemplateConfig,
    SendMessageConfig,
    GetMessageCostConfig,
    ListScheduledMessagesConfig,
    GetScheduledMessageConfig,
    ListKeywordsConfig,
    ListDeliveriesConfig,
    UnsubscribePhoneNumberConfig,
    GetUnsubscribeStatusConfig,
    ListUnsubscribesConfig
], Field(discriminator="operation")]


class MobileTextAlertsFullConfig(NodeConfig[MobileTextAlertsConfig, MobileTextAlertsAPIKeyCredential]):
    pass


OPERATIONS = {'list_subscribers': ('GET', '/subscribers'),
 'get_subscriber': ('GET', '/subscribers/{idOrNumber}'),
 'create_subscriber': ('POST', '/subscribers'),
 'update_subscriber': ('PATCH', '/subscribers/{idOrNumber}'),
 'delete_subscriber': ('DELETE', '/subscribers/{idOrNumber}'),
 'list_groups': ('GET', '/groups'),
 'create_group': ('POST', '/groups'),
 'update_group': ('PATCH', '/groups/{groupId}'),
 'delete_group': ('DELETE', '/groups/{groupId}'),
 'add_group_member': ('POST', '/groups/{groupId}/subscribers'),
 'delete_group_member': ('DELETE', '/groups/{groupId}/subscribers/{subscriberId}'),
 'list_templates': ('GET', '/templates'),
 'get_template': ('GET', '/templates/{templateId}'),
 'create_template': ('POST', '/templates'),
 'update_template': ('PATCH', '/templates/{templateId}'),
 'delete_template': ('DELETE', '/templates/{templateId}'),
 'send_message': ('POST', '/send'),
 'get_message_cost': ('POST', '/send/cost'),
 'list_scheduled_messages': ('GET', '/scheduled'),
 'get_scheduled_message': ('GET', '/scheduled/{scheduledMessageId}'),
 'list_keywords': ('GET', '/keywords'),
 'list_deliveries': ('GET', '/deliveries'),
 'unsubscribe_phone_number': ('POST', '/unsubscribes'),
 'get_unsubscribe_status': ('GET', '/unsubscribes/{number}'),
 'list_unsubscribes': ('GET', '/unsubscribes')}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    return value


class MobileTextAlertsNode(WorkflowNode):
    integration_type = "automation-mobile-text-alerts"
    connection_evidence = ConnectionEvidence(operation="list_groups", noun="groups", label_keys=("displayName", "name"))

    @classmethod
    def get_config_model(cls):
        return MobileTextAlertsFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Mobile Text Alerts API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        method, route = OPERATIONS[op.operation]
        values = op.model_dump(by_alias=True, exclude_none=True, exclude={"operation", "request_id"})
        for key in re.findall(r"\{(\w+)\}", route):
            route = route.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        headers = {"Authorization": "Bearer " + secret, "Accept": "application/json"}
        if op.operation == "send_message" and op.request_id:
            headers["X-Request-Id"] = op.request_id
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route, headers=headers,
                    **({"json": values} if method != "GET" and values else {}))
        except httpx.RequestError:
            # A write may have reached the provider. Do not retry automatically.
            raise ValueError("Mobile Text Alerts request could not be completed; check the provider before retrying writes") from None
        if len(response.content) > 5_000_000:
            raise ValueError("Mobile Text Alerts response exceeds the size limit")
        if response.status_code >= 400:
            try:
                error = response.json()
            except ValueError:
                error = {"message": "Provider returned an HTTP error"}
            result = {"status": "error", "http_status": response.status_code, "error": error}
        else:
            if not 200 <= response.status_code < 300:
                raise ValueError("Mobile Text Alerts returned an unexpected redirect or status")
            try:
                body = response.json()
            except ValueError:
                raise ValueError("Mobile Text Alerts returned invalid JSON") from None
            if not isinstance(body, dict) or not any(key in body for key in ("data", "message", "success")):
                raise ValueError("Mobile Text Alerts returned an unexpected response envelope")
            if body.get("success") is False or body.get("error") or body.get("errors"):
                result = {"status": "error", "http_status": response.status_code, "error": body}
            else:
                data = body.get("data")
                if op.operation.startswith("list_"):
                    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
                        raise ValueError("Mobile Text Alerts returned an unexpected list envelope")
                    if any(not isinstance(row, dict) for row in data["rows"]):
                        raise ValueError("Mobile Text Alerts returned invalid list rows")
                    if any(type(data.get(key)) is not int for key in ("page", "pageSize", "total")):
                        raise ValueError("Mobile Text Alerts returned invalid pagination metadata")
                elif "data" in body and not isinstance(data, dict):
                    raise ValueError("Mobile Text Alerts returned invalid resource data")
                result = {**body, "status": "success", "http_status": response.status_code}
        result = _redact(result, secret)
        await self.emit(result)
        return result
