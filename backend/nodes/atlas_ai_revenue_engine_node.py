"""Atlas AI Revenue Engine v1 API-key actions.

Contract: https://docs.youratlas.com/openapi.json, version 1.0.0.
Each action makes one documented request. Scheduling can place a call or send
an SMS immediately when no date is supplied. Writes are never retried.
Provider response bodies (including Azure Table field names) are preserved.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.youratlas.com/v1/api"


class AtlasAIRevenueEngineAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Atlas AI Revenue Engine API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.youratlas.com/",
            "x-credential-instructions": "In Atlas Portal, open Settings > API Keys and paste your API key. NoClick sends it in the api-key header to api.youratlas.com. The connection check reads your campaigns and profile; write permissions depend on your Atlas account.",
        })
    credential_type: Literal["atlas_ai_revenue_engine_api_key"] = Field(
        "atlas_ai_revenue_engine_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


ResourceID = Annotated[str, Field(min_length=1, max_length=512)]
Phone = Annotated[str, Field(pattern=r"^\+[1-9][0-9]{1,14}$", description="Phone number in E.164 format, including + and country code.")]


class _Campaign(_Input):
    campaign_id: ResourceID


class _Contact(_Campaign):
    contact_id: ResourceID


class _Call(_Input):
    call_id: ResourceID


class ContactInput(BaseModel):
    """Atlas allows custom contact fields as additional key-value properties."""
    model_config = ConfigDict(extra="allow")
    firstName: str = Field(..., min_length=1, title="First Name")
    lastName: str = Field(..., min_length=1, title="Last Name")
    phoneNumber: Phone
    timezone: str | None = None


class _Schedule(_Campaign):
    customer_phone_number: Phone
    customer_name: str = Field(..., min_length=1)
    customer_last_name: str | None = None
    customer_info: str | None = Field(None, description="Additional key=value pairs, separated by newlines.")
    scheduled_date: AwareDatetime | None = Field(None, description="ISO 8601 time with timezone. Omit to send/place immediately unless respecting campaign windows.")
    respect_campaign_schedule: StrictBool = Field(False, description="When no date is given, wait for the next allowed campaign window. An open window permits immediate sending/calling.")


class GetProfileConfig(_Input):
    operation: Literal["get_profile"] = Field("get_profile", json_schema_extra={"ui:hidden": True})


class ListCampaignsConfig(_Input):
    operation: Literal["list_campaigns"] = Field("list_campaigns", json_schema_extra={"ui:hidden": True})


class GetCampaignConfig(_Campaign):
    operation: Literal["get_campaign"] = Field("get_campaign", json_schema_extra={"ui:hidden": True})


class SetCampaignStatusConfig(_Campaign):
    operation: Literal["set_campaign_status"] = Field("set_campaign_status", json_schema_extra={"ui:hidden": True})
    enabled: StrictBool = Field(..., description="Whether Atlas should enable the campaign.")


class DeleteCampaignConfig(_Campaign):
    operation: Literal["delete_campaign"] = Field("delete_campaign", json_schema_extra={"ui:hidden": True})


class ListContactsConfig(_Campaign):
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})


class GetContactConfig(_Contact):
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})


class CreateContactsConfig(_Input):
    operation: Literal["create_contacts"] = Field("create_contacts", json_schema_extra={"ui:hidden": True})
    campaign_id: ResourceID | None = Field(None, description="Omit to create global contacts that no campaign will dial.")
    contacts: list[ContactInput] = Field(..., min_length=1)


class UpdateContactConfig(_Contact):
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact: ContactInput


class DeleteContactConfig(_Contact):
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})


class ScheduleCallConfig(_Schedule):
    operation: Literal["schedule_call"] = Field("schedule_call", json_schema_extra={"ui:hidden": True})


class ListCallsConfig(_Input):
    operation: Literal["list_calls"] = Field("list_calls", json_schema_extra={"ui:hidden": True})
    campaign_id: str | None = None
    assistant_id: str | None = None
    call_type: str | None = None
    campaign_type: str | None = None
    success_result: str | None = None
    start_date: AwareDatetime | None = None
    end_date: AwareDatetime | None = None
    customer_phone_number: str | None = None


class GetCallConfig(_Call):
    operation: Literal["get_call"] = Field("get_call", json_schema_extra={"ui:hidden": True})


class DeleteCallConfig(_Call):
    operation: Literal["delete_call"] = Field("delete_call", json_schema_extra={"ui:hidden": True})


class ListScheduledCallsConfig(_Campaign):
    operation: Literal["list_scheduled_calls"] = Field("list_scheduled_calls", json_schema_extra={"ui:hidden": True})


class ListBookingsConfig(_Campaign):
    operation: Literal["list_bookings"] = Field("list_bookings", json_schema_extra={"ui:hidden": True})


class GetCampaignStatisticsConfig(_Campaign):
    operation: Literal["get_campaign_statistics"] = Field("get_campaign_statistics", json_schema_extra={"ui:hidden": True})


class ListChatSessionsConfig(_Campaign):
    operation: Literal["list_chat_sessions"] = Field("list_chat_sessions", json_schema_extra={"ui:hidden": True})


class ListChatMessagesConfig(_Input):
    operation: Literal["list_chat_messages"] = Field("list_chat_messages", json_schema_extra={"ui:hidden": True})
    session_id: ResourceID


class ScheduleSmsConfig(_Schedule):
    operation: Literal["schedule_sms"] = Field("schedule_sms", json_schema_extra={"ui:hidden": True})
    custom_message: str | None = None


class SendHumanResponseConfig(_Campaign):
    operation: Literal["send_human_response"] = Field("send_human_response", json_schema_extra={"ui:hidden": True})
    session_id: ResourceID = Field(..., description="Contact current session, already in human handoff state.")
    message: str = Field(..., min_length=1)
    agent_id: str | None = None


class SetHumanHandoffConfig(_Campaign):
    operation: Literal["set_human_handoff"] = Field("set_human_handoff", json_schema_extra={"ui:hidden": True})
    contact_identifier: ResourceID = Field(..., description="E.164 phone number or Apple ID email.")
    enabled: StrictBool = Field(..., description="True routes replies to a human; false resumes automation.")


class ListAgentsConfig(_Input):
    operation: Literal["list_agents"] = Field("list_agents", json_schema_extra={"ui:hidden": True})


class ListPhoneNumbersConfig(_Input):
    operation: Literal["list_phone_numbers"] = Field("list_phone_numbers", json_schema_extra={"ui:hidden": True})


class GetQuotaConfig(_Input):
    operation: Literal["get_quota"] = Field("get_quota", json_schema_extra={"ui:hidden": True})


AtlasConfig = Annotated[Union[
    GetProfileConfig,
    ListCampaignsConfig,
    GetCampaignConfig,
    SetCampaignStatusConfig,
    DeleteCampaignConfig,
    ListContactsConfig,
    GetContactConfig,
    CreateContactsConfig,
    UpdateContactConfig,
    DeleteContactConfig,
    ScheduleCallConfig,
    ListCallsConfig,
    GetCallConfig,
    DeleteCallConfig,
    ListScheduledCallsConfig,
    ListBookingsConfig,
    GetCampaignStatisticsConfig,
    ListChatSessionsConfig,
    ListChatMessagesConfig,
    ScheduleSmsConfig,
    SendHumanResponseConfig,
    SetHumanHandoffConfig,
    ListAgentsConfig,
    ListPhoneNumbersConfig,
    GetQuotaConfig
], Field(discriminator="operation")]


class AtlasAIRevenueEngineNodeConfig(NodeConfig[AtlasConfig, AtlasAIRevenueEngineAPIKeyCredential]):
    pass


ROUTES = {'get_profile': ('GET', '/account/profile'),
 'list_campaigns': ('GET', '/campaign'),
 'get_campaign': ('GET', '/campaign/{campaign_id}'),
 'set_campaign_status': ('PUT', '/campaign/{campaign_id}/status'),
 'delete_campaign': ('DELETE', '/campaign/{campaign_id}'),
 'list_contacts': ('GET', '/contactlist/{campaign_id}'),
 'get_contact': ('GET', '/contactlist/{campaign_id}/{contact_id}'),
 'create_contacts': ('POST', '/contactlist/contactlistmanual'),
 'update_contact': ('PUT', '/contactlist/{campaign_id}/{contact_id}'),
 'delete_contact': ('DELETE', '/contactlist/{campaign_id}/{contact_id}'),
 'schedule_call': ('POST', '/campaign/createSchedule'),
 'list_calls': ('GET', '/call'),
 'get_call': ('GET', '/call/{call_id}'),
 'delete_call': ('DELETE', '/call/{call_id}'),
 'list_scheduled_calls': ('GET', '/call/scheduled/{campaign_id}'),
 'list_bookings': ('GET', '/campaign/{campaign_id}/bookings'),
 'get_campaign_statistics': ('GET', '/call/stats/{campaign_id}'),
 'list_chat_sessions': ('GET', '/campaign-chat/{campaign_id}'),
 'list_chat_messages': ('GET', '/campaign-chat/sessions/{session_id}/messages'),
 'schedule_sms': ('POST', '/campaign-chat/{campaign_id}/sessions/sms/schedule'),
 'send_human_response': ('POST', '/campaign-chat/{campaign_id}/send-human-response'),
 'set_human_handoff': ('POST',
                       '/campaign-chat/{campaign_id}/contacts/{contact_identifier}/human-handoff'),
 'list_agents': ('GET', '/agent'),
 'list_phone_numbers': ('GET', '/phone-number'),
 'get_quota': ('GET', '/customer-quota')}


WIRE_FIELDS = {
    "campaign_id": "campaignId", "assistant_id": "assistantId", "call_type": "callType",
    "campaign_type": "campaignType", "success_result": "successResult", "start_date": "startDate",
    "end_date": "endDate", "customer_phone_number": "customerPhoneNumber", "customer_name": "customerName",
    "customer_last_name": "customerLastName", "customer_info": "customerInfo", "scheduled_date": "scheduledDate",
    "respect_campaign_schedule": "respectCampaignSchedule", "custom_message": "customMessage",
    "session_id": "sessionId", "agent_id": "agentId",
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value


def build_request(config):
    """Only the fixed action catalog controls methods, paths and wire names."""
    method, path = ROUTES[config.operation]
    data = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
    for key in re.findall(r"{(\w+)}", path):
        value = data.pop(key)
        if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use a resource identifier without dot segments or control characters")
        path = path.replace("{" + key + "}", quote(value, safe=""))
    if config.operation == "update_contact":
        body = data["contact"]
    else:
        body = {WIRE_FIELDS.get(key, key): value for key, value in data.items()}
    return method, path, (body if method == "GET" else None), (body if method not in {"GET", "DELETE"} else None)


class AtlasAIRevenueEngineNode(WorkflowNode):
    integration_type = "automation-atlas-ai-revenue-engine"
    connection_evidence = ConnectionEvidence(
        noun="campaigns", operation="list_campaigns", label_keys=("name", "RowKey"),
        identity_operation="get_profile", identity_keys=("full_name", "company"))

    @classmethod
    def get_config_model(cls):
        return AtlasAIRevenueEngineNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect your Atlas AI Revenue Engine API key")
        secret = self.config.credentials.api_key
        config = self.config.config
        method, path, params, body = build_request(config)
        # Code-owned origin, no redirects, no environment proxies, no retries.
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"api-key": secret, "Accept": "application/json"}, params=params, json=body)
        except httpx.RequestError:
            raise ValueError("Atlas request did not complete; inspect Atlas before retrying a write") from None
        try:
            payload = response.json() if response.content else {}
        except ValueError:
            raise ValueError("Atlas returned a non-JSON response") from None
        payload = _redact(payload, secret)
        if not 200 <= response.status_code < 300 or (isinstance(payload, dict) and payload.get("error")):
            error = payload.get("error", payload) if isinstance(payload, dict) else payload
            message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            raise ValueError(f"Atlas HTTP {response.status_code}: {message}")
        if not isinstance(payload, (dict, list)):
            raise ValueError("Atlas returned an unexpected JSON response")
        output = {"status": "success", "data": payload, "http_status": response.status_code}
        if config.operation == "create_contacts":
            if not isinstance(payload, dict) or not isinstance(payload.get("processed"), list) or not isinstance(payload.get("invalid"), list):
                raise ValueError("Atlas contact-create response must contain processed and invalid lists; inspect before retrying")
            if not payload["processed"]:
                output.update(status="error", success=False, message="Atlas rejected every contact")
            elif payload["invalid"]:
                output.update(status="partial", success=False, message="Atlas rejected some contacts; inspect invalid before retrying")
        await self.emit(output)
        return output
