"""Mihu Ai contact, call, agent, appointment and campaign operations.

Each operation performs one documented v1 request using a pasted workspace token.
Lists return one provider page, including its pagination metadata.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class MihuAiTokenCredential(BaseModel):
    model_config = ConfigDict(title="Mihu Ai API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.mihu.ai/docs",
            "x-credential-instructions": "Paste an existing workspace API token and the subdomain from your Mihu Ai workspace URL. NoClick sends the token only to https://<subdomain>.mihu.ai. Listing contacts verifies access; it does not prove every write permission.",
        })
    credential_type: Literal["mihu_ai_api_token"] = Field("mihu_ai_api_token", json_schema_extra={"ui:hidden": True})
    subdomain: str = Field(..., title="Workspace subdomain", description="Only the part before .mihu.ai in your workspace URL.")
    api_token: str = Field(..., title="API token", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("subdomain", mode="before")
    @classmethod
    def workspace(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", value.strip()):
            raise ValueError("Enter only your Mihu Ai workspace subdomain")
        return value.strip().lower()

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if len(value) > 4096 or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API token without the Bearer prefix")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CallPrompt(_Operation):
    overwrite: bool = False
    content: str | None = None


class CallParticipant(_Operation):
    number: str = Field(..., pattern=r"^\+[1-9][0-9]{6,14}$", description="Recipient phone number in E.164 format.")
    about: str | None = None


class CallMessage(_Operation):
    start: str | None = None


class ListAgentsConfig(_Operation):
    """List agents."""
    operation: Literal["list_agents"] = Field("list_agents", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, le=1000000)
    per_page: int = Field(25, le=100, ge=1)
    status: Literal['pending', 'ready', 'in_progress', 'paused', 'completed'] | None = Field(None)
    search: str | None = Field(None)

class GetAgentConfig(_Operation):
    """Get one agent."""
    operation: Literal["get_agent"] = Field("get_agent", json_schema_extra={"ui:hidden": True})
    uuid: UUID = Field(...)

class InitiateCallConfig(_Operation):
    """Initiate a new call."""
    operation: Literal["initiate_call"] = Field("initiate_call", json_schema_extra={"ui:hidden": True})
    agentId: UUID
    prompt: CallPrompt
    participant: CallParticipant
    message: CallMessage | None = None

class ListCallsConfig(_Operation):
    """Get paginated list of calls."""
    operation: Literal["list_calls"] = Field("list_calls", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, le=1000000, description='Page number')
    per_page: int = Field(15, ge=1, le=100, description='Number of items per page')
    agent_id: UUID | None = Field(None, description='Filter by agent UUID')
    status: Literal['in-progress', 'ended', 'missed', 'failed'] | None = Field(None, description='Filter by call status')
    direction: Literal['Inbound', 'Outbound', 'webCall'] | None = Field(None, description='Filter by call direction')

class GetCallConfig(_Operation):
    """Get call details by UUID."""
    operation: Literal["get_call"] = Field("get_call", json_schema_extra={"ui:hidden": True})
    uuid: UUID = Field(..., description='Call UUID')

class ListContactsConfig(_Operation):
    """Get paginated list of contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, le=1000000, description='Page number')
    per_page: int = Field(15, ge=1, le=100, description='Number of items per page')
    search: str | None = Field(None, description='Search term for name, email, or phone')
    status: Literal['Active', 'Inactive'] | None = Field(None, description='Filter by contact status')
    contact_channel: Literal['Call', 'SMS', 'WhatsApp'] | None = Field(None, description='Filter by preferred contact channel')
    stage_uuid: UUID | None = Field(None, description="Filter by the contact's current pipeline stage UUID")
    campaign_uuid: UUID | None = Field(None, description='Filter by campaign UUID (matches contacts whose pool is attached to this campaign)')
    tag_uuid: UUID | None = Field(None, description='Filter by tag UUID')
    pool_uuid: UUID | None = Field(None, description='Filter by contact pool UUID')
    date_from: date | None = Field(None, description='Filter contacts created on or after this date (Y-m-d)')
    date_to: date | None = Field(None, description='Filter contacts created on or before this date (Y-m-d)')

class CreateContactConfig(_Operation):
    """Create a new contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None)
    surname: str | None = Field(None)
    email: str | None = Field(None)
    phone_number: str | None = Field(None)
    number_type: str | None = Field(None)
    country_code: str | None = Field(None)
    timezone: str | None = Field(None)
    primary_language: str | None = Field(None)
    preferred_contact_channel: str | None = Field(None)
    preferred_contact_time: str | None = Field(None)
    status: Literal['Active', 'Inactive'] | None = Field(None)

    @model_validator(mode="after")
    def supplied_fields(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "uuid"}):
            raise ValueError("Provide at least one field to write")
        return self

class GetContactConfig(_Operation):
    """Get contact details."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    uuid: UUID = Field(..., description='UUID of the contact')

class UpdateContactConfig(_Operation):
    """Update a contact."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    uuid: UUID = Field(..., description='UUID of the contact to update')
    name: str | None = Field(None)
    surname: str | None = Field(None)
    email: str | None = Field(None)
    phone_number: str | None = Field(None)
    number_type: str | None = Field(None)
    country_code: str | None = Field(None)
    timezone: str | None = Field(None)
    primary_language: str | None = Field(None)
    preferred_contact_channel: str | None = Field(None)
    preferred_contact_time: str | None = Field(None)
    status: Literal['Active', 'Inactive'] | None = Field(None)

    @model_validator(mode="after")
    def supplied_fields(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "uuid"}):
            raise ValueError("Provide at least one field to write")
        return self

class DeleteContactConfig(_Operation):
    """Delete a contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})
    uuid: UUID = Field(..., description='UUID of the contact to delete')

class ListContactNotesConfig(_Operation):
    """List a contact's notes."""
    operation: Literal["list_contact_notes"] = Field("list_contact_notes", json_schema_extra={"ui:hidden": True})
    uuid: UUID = Field(...)

class AddContactNoteConfig(_Operation):
    """Add a note to a contact."""
    operation: Literal["add_contact_note"] = Field("add_contact_note", json_schema_extra={"ui:hidden": True})
    uuid: UUID = Field(...)
    content: str = Field(..., min_length=3, max_length=1000)

class ListTagsConfig(_Operation):
    """List contact tags."""
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})
    include: Literal['active', 'inactive', 'all'] | None = Field(None)

class AddContactTagConfig(_Operation):
    """Assign (or re-assign) a tag to a contact."""
    operation: Literal["add_contact_tag"] = Field("add_contact_tag", json_schema_extra={"ui:hidden": True})
    uuid: UUID = Field(..., description='UUID of the contact')
    tag_id: int | None = Field(None)
    tag_uuid: UUID | None = Field(None)

    @model_validator(mode="after")
    def supplied_tag(self):
        if self.tag_id is None and self.tag_uuid is None:
            raise ValueError("Provide a tag ID or tag UUID")
        return self

class ListAppointmentsConfig(_Operation):
    """Get all appointments (calendar)."""
    operation: Literal["list_appointments"] = Field("list_appointments", json_schema_extra={"ui:hidden": True})
    schedule_uuid: UUID | None = Field(None, description='Filter by schedule UUID')
    contact_uuid: UUID | None = Field(None, description='Filter by contact UUID')
    status: str | None = Field(None, description='Filter by status (approved, pending, rejected, cancelled)')
    start_date: date | None = Field(None, description='Filter from this date (YYYY-MM-DD)')
    end_date: date | None = Field(None, description='Filter until this date (YYYY-MM-DD)')

class CreateAppointmentConfig(_Operation):
    """Create a new appointment."""
    operation: Literal["create_appointment"] = Field("create_appointment", json_schema_extra={"ui:hidden": True})
    schedule_uuid: UUID = Field(...)
    contact_uuid: UUID | None = Field(None)
    title: str = Field(...)
    description: str | None = Field(None)
    start_time: datetime = Field(..., description='No offset = your timezone; with offset = that exact instant')
    end_time: datetime = Field(..., description='Same rule as start_time; must be after it')
    status: str | None = Field(None)
    notes: str | None = Field(None)
    custom_answers: dict | None = Field(None)

class GetAppointmentConfig(_Operation):
    """Get a specific appointment."""
    operation: Literal["get_appointment"] = Field("get_appointment", json_schema_extra={"ui:hidden": True})
    uuid: UUID = Field(...)

class UpdateAppointmentConfig(_Operation):
    """Update an appointment."""
    operation: Literal["update_appointment"] = Field("update_appointment", json_schema_extra={"ui:hidden": True})
    uuid: UUID = Field(...)
    title: str | None = Field(None)
    description: str | None = Field(None)
    start_time: datetime | None = Field(None, description='No offset = your timezone; with offset = that exact instant')
    end_time: datetime | None = Field(None, description='Same rule as start_time; must be after it')
    status: str | None = Field(None)

    @model_validator(mode="after")
    def supplied_fields(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "uuid"}):
            raise ValueError("Provide at least one field to write")
        return self

class DeleteAppointmentConfig(_Operation):
    """Delete an appointment."""
    operation: Literal["delete_appointment"] = Field("delete_appointment", json_schema_extra={"ui:hidden": True})
    uuid: UUID = Field(...)

class ListCampaignsConfig(_Operation):
    """Get all listings (campaigns with pools)."""
    operation: Literal["list_campaigns"] = Field("list_campaigns", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, le=1000000)
    per_page: int = Field(15, ge=1, le=100)
    search: str | None = Field(None)
    status: str | None = Field(None)

class StartCampaignConfig(_Operation):
    """Start/resume a listing campaign."""
    operation: Literal["start_campaign"] = Field("start_campaign", json_schema_extra={"ui:hidden": True})
    uuid: UUID = Field(...)

class StopCampaignConfig(_Operation):
    """Stop/pause a running listing campaign."""
    operation: Literal["stop_campaign"] = Field("stop_campaign", json_schema_extra={"ui:hidden": True})
    uuid: UUID = Field(...)

MihuAiOperation = Annotated[Union[
    ListAgentsConfig,
    GetAgentConfig,
    InitiateCallConfig,
    ListCallsConfig,
    GetCallConfig,
    ListContactsConfig,
    CreateContactConfig,
    GetContactConfig,
    UpdateContactConfig,
    DeleteContactConfig,
    ListContactNotesConfig,
    AddContactNoteConfig,
    ListTagsConfig,
    AddContactTagConfig,
    ListAppointmentsConfig,
    CreateAppointmentConfig,
    GetAppointmentConfig,
    UpdateAppointmentConfig,
    DeleteAppointmentConfig,
    ListCampaignsConfig,
    StartCampaignConfig,
    StopCampaignConfig
], Field(discriminator="operation")]


class MihuAiConfig(NodeConfig[MihuAiOperation, MihuAiTokenCredential]):
    pass


ROUTES = {'list_agents': ('GET', '/api/v1/agents', [], ['page', 'per_page', 'status', 'search']),
 'get_agent': ('GET', '/api/v1/agents/{uuid}', ['uuid'], []),
 'initiate_call': ('POST', '/api/v1/call', [], []),
 'list_calls': ('GET',
                '/api/v1/calls',
                [],
                ['page', 'per_page', 'agent_id', 'status', 'direction']),
 'get_call': ('GET', '/api/v1/calls/{uuid}', ['uuid'], []),
 'list_contacts': ('GET',
                   '/api/v1/contacts',
                   [],
                   ['page',
                    'per_page',
                    'search',
                    'status',
                    'contact_channel',
                    'stage_uuid',
                    'campaign_uuid',
                    'tag_uuid',
                    'pool_uuid',
                    'date_from',
                    'date_to']),
 'create_contact': ('POST', '/api/v1/contacts', [], []),
 'get_contact': ('GET', '/api/v1/contacts/{uuid}', ['uuid'], []),
 'update_contact': ('PUT', '/api/v1/contacts/{uuid}', ['uuid'], []),
 'delete_contact': ('DELETE', '/api/v1/contacts/{uuid}', ['uuid'], []),
 'list_contact_notes': ('GET', '/api/v1/contacts/{uuid}/notes', ['uuid'], []),
 'add_contact_note': ('POST', '/api/v1/contacts/{uuid}/notes', ['uuid'], []),
 'list_tags': ('GET', '/api/v1/contacts/tags', [], ['include']),
 'add_contact_tag': ('POST', '/api/v1/contacts/{uuid}/add-tag', ['uuid'], []),
 'list_appointments': ('GET',
                       '/api/v1/appointments',
                       [],
                       ['schedule_uuid', 'contact_uuid', 'status', 'start_date', 'end_date']),
 'create_appointment': ('POST', '/api/v1/appointments', [], []),
 'get_appointment': ('GET', '/api/v1/appointments/{uuid}', ['uuid'], []),
 'update_appointment': ('PUT', '/api/v1/appointments/{uuid}', ['uuid'], []),
 'delete_appointment': ('DELETE', '/api/v1/appointments/{uuid}', ['uuid'], []),
 'list_campaigns': ('GET', '/api/v1/listings', [], ['page', 'per_page', 'search', 'status']),
 'start_campaign': ('POST', '/api/v1/listings/{uuid}/run', ['uuid'], []),
 'stop_campaign': ('POST', '/api/v1/listings/{uuid}/stop', ['uuid'], [])}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value


class MihuAiNode(WorkflowNode):
    integration_type = "automation-mihu-ai"
    connection_evidence = ConnectionEvidence(
        noun="contacts", operation="list_contacts", label_keys=("name", "email", "uuid"))

    @classmethod
    def get_config_model(cls):
        return MihuAiConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Mihu Ai workspace API token")
        credential = self.config.credentials
        config = self.config.config
        method, route, path_fields, query_fields = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for name in path_fields:
            route = route.replace("{" + name + "}", values.pop(name))
        params = {name: values.pop(name) for name in query_fields if name in values}
        headers = {"Authorization": "Bearer " + credential.api_token,
                   "Accept": "application/json", "X-Timezone": "UTC"}
        url = "https://" + credential.subdomain + ".mihu.ai" + route
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, url, headers=headers,
                    params=params, **({"json": values} if method in {"POST", "PUT", "PATCH"} and values else {}))
        except Exception:
            raise ValueError("Mihu Ai request could not be confirmed; inspect writes before retrying") from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Mihu Ai returned a non-JSON response; check the workspace subdomain") from None
        payload = _redact(payload, credential.api_token)
        if response.status_code >= 300 or (isinstance(payload, dict) and payload.get("success") is False):
            message = payload.get("message") if isinstance(payload, dict) else None
            output = {"status": "error", "success": False, "http_status": response.status_code,
                      "message": message or "Mihu Ai rejected the request"}
        else:
            output = {"status": "success", "http_status": response.status_code, "data": payload}
        await self.emit(output)
        return output
