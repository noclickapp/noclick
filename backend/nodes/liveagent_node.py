"""LiveAgent API v4: published activity, availability and configuration endpoints.

Contract: https://support.liveagent.com/docs/api/v4/openapi.php (4.0.0).
The pinned API exposes no ticket CRUD or webhook registration. Polls watch
new or changed history records, baseline when armed, and refuse truncation.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client, normalize_provider_https_origin


class LiveAgentAPIKeyCredential(BaseModel):
    credential_type: Literal["liveagent_api_key"] = Field("liveagent_api_key", json_schema_extra={"ui:hidden": True})
    account_url: str = Field(..., title="LiveAgent account URL", description="Your hosted account URL, for example https://your.ladesk.com.")
    api_key: str = Field(..., title="API Key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="LiveAgent API Key", json_schema_extra={
        "x-credential-url": "https://support.liveagent.com/741982-API-key",
        "x-credential-instructions": "In LiveAgent, open Configuration > System > API and create an API key with permissions for the actions you will use. Paste the key and your hosted account URL. NoClick uses the apikey header with API v4.",
    })

    @field_validator("account_url", mode="before")
    @classmethod
    def account_origin(cls, value):
        return normalize_provider_https_origin(value, "ladesk.com", field_name="LiveAgent account URL")


OPERATIONS = {'list_agent_activity': {'method': 'GET',
                         'path': '/agents/{agentId}/activity',
                         'path_fields': ['agentId'],
                         'query': ['ticketId',
                                   'activityType',
                                   'activityFromStart',
                                   'activityFromEnd',
                                   'sortOrder'],
                         'body': []},
 'on_new_or_updated_agent_activity': {'method': 'GET',
                                      'path': '/agents/{agentId}/activity',
                                      'path_fields': ['agentId'],
                                      'query': ['ticketId',
                                                'activityType',
                                                'activityFromStart',
                                                'activityFromEnd',
                                                'sortOrder'],
                                      'body': [],
                                      'poll': True,
                                      'rows': 'results'},
 'list_agent_worktime': {'method': 'GET',
                         'path': '/agents/{agentId}/worktime',
                         'path_fields': ['agentId'],
                         'query': ['dateFrom', 'dateTo', 'status', 'sortDir'],
                         'body': []},
 'on_new_or_updated_agent_worktime': {'method': 'GET',
                                      'path': '/agents/{agentId}/worktime',
                                      'path_fields': ['agentId'],
                                      'query': ['dateFrom', 'dateTo', 'status', 'sortDir'],
                                      'body': [],
                                      'poll': True,
                                      'rows': 'data'},
 'list_agent_availability': {'method': 'GET',
                             'path': '/agents/availability',
                             'path_fields': [],
                             'query': ['agentId',
                                       'departmentId',
                                       'serviceType',
                                       'availableFrom',
                                       'availableTo',
                                       'sortDir',
                                       'limit',
                                       'cursor'],
                             'body': []},
 'rename_department': {'method': 'POST',
                       'path': '/department/rename/{departmentId}',
                       'path_fields': ['departmentId'],
                       'query': [],
                       'body': ['newName']},
 'get_department': {'method': 'GET',
                    'path': '/department/{departmentId}',
                    'path_fields': ['departmentId'],
                    'query': [],
                    'body': []},
 'list_ticket_field_definitions': {'method': 'GET',
                                   'path': '/ticket-field-definitions/',
                                   'path_fields': [],
                                   'query': ['includeArchived', 'filter'],
                                   'body': []},
 'get_ticket_field_definition': {'method': 'GET',
                                 'path': '/ticket-field-definitions/{id}',
                                 'path_fields': ['id'],
                                 'query': [],
                                 'body': []},
 'list_ticket_activity': {'method': 'GET',
                          'path': '/tickets/{ticketId}/activity',
                          'path_fields': ['ticketId'],
                          'query': ['agentId',
                                    'activityType',
                                    'activityFromStart',
                                    'activityFromEnd',
                                    'sortOrder'],
                          'body': []},
 'on_new_or_updated_ticket_activity': {'method': 'GET',
                                       'path': '/tickets/{ticketId}/activity',
                                       'path_fields': ['ticketId'],
                                       'query': ['agentId',
                                                 'activityType',
                                                 'activityFromStart',
                                                 'activityFromEnd',
                                                 'sortOrder'],
                                       'body': [],
                                       'poll': True,
                                       'rows': 'results'}}


class LiveAgentListAgentActivityConfig(BaseModel):
    operation: Literal['list_agent_activity'] = Field('list_agent_activity', title='Get ticket activity history for an agent', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get ticket activity history for an agent', "x-is-trigger": False})
    agentId: str = Field(..., title='agentId', description='Unique agent identifier', min_length=8, max_length=8, pattern='^[a-z0-9]+$')
    ticketId: list[str] | None = Field(None, title='ticketId', description='Filter by ticket ID(s). Multiple values narrow results to matching tickets.')
    activityType: list[Literal['solve', 'view', 'ring_chat', 'ring_call', 'ring_invite']] | None = Field(None, title='activityType', description='Filter by activity type(s)')
    activityFromStart: str | None = Field(None, title='activityFromStart', description='Filter activities starting from this date-time (inclusive), ISO 8601 UTC', json_schema_extra={"format": "date-time"})
    activityFromEnd: str | None = Field(None, title='activityFromEnd', description='Filter activities starting before this date-time (inclusive), ISO 8601 UTC', json_schema_extra={"format": "date-time"})
    sortOrder: Literal['asc', 'desc'] | None = Field(None, title='sortOrder', description='Sort direction for activityFrom (default desc)')


class LiveAgentOnNewOrUpdatedAgentActivityConfig(PollTriggerConfigBase):
    operation: Literal['on_new_or_updated_agent_activity'] = Field('on_new_or_updated_agent_activity', title='On New Or Updated Agent Activity', json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": 'On New Or Updated Agent Activity'})
    agentId: str = Field(..., title='agentId', description='Unique agent identifier', min_length=8, max_length=8, pattern='^[a-z0-9]+$')
    ticketId: list[str] | None = Field(None, title='ticketId', description='Filter by ticket ID(s). Multiple values narrow results to matching tickets.')
    activityType: list[Literal['solve', 'view', 'ring_chat', 'ring_call', 'ring_invite']] | None = Field(None, title='activityType', description='Filter by activity type(s)')
    activityFromStart: str | None = Field(None, title='activityFromStart', description='Filter activities starting from this date-time (inclusive), ISO 8601 UTC', json_schema_extra={"format": "date-time"})
    activityFromEnd: str | None = Field(None, title='activityFromEnd', description='Filter activities starting before this date-time (inclusive), ISO 8601 UTC', json_schema_extra={"format": "date-time"})
    sortOrder: Literal['asc', 'desc'] | None = Field(None, title='sortOrder', description='Sort direction for activityFrom (default desc)')


class LiveAgentListAgentWorktimeConfig(BaseModel):
    operation: Literal['list_agent_worktime'] = Field('list_agent_worktime', title='Get agent online status history', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get agent online status history', "x-is-trigger": False})
    agentId: str = Field(..., title='agentId', description='Unique agent identifier', min_length=8, max_length=8, pattern='^[a-z0-9]+$')
    dateFrom: str | None = Field(None, title='dateFrom', description='Start of the date range (inclusive), as an ISO 8601 date-time. An explicit timezone offset (for example Z or +02:00) is honored; UTC is assumed when omitted.', json_schema_extra={"format": "date-time"})
    dateTo: str | None = Field(None, title='dateTo', description='End of the date range (inclusive), as an ISO 8601 date-time. An explicit timezone offset (for example Z or +02:00) is honored; UTC is assumed when omitted.', json_schema_extra={"format": "date-time"})
    status: Literal['online', 'paused'] | None = Field(None, title='status', description='Filter by status.')
    sortDir: Literal['ASC', 'DESC'] | None = Field(None, title='sortDir', description='Sort direction by status start time (default DESC).')


class LiveAgentOnNewOrUpdatedAgentWorktimeConfig(PollTriggerConfigBase):
    operation: Literal['on_new_or_updated_agent_worktime'] = Field('on_new_or_updated_agent_worktime', title='On New Or Updated Agent Worktime', json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": 'On New Or Updated Agent Worktime'})
    agentId: str = Field(..., title='agentId', description='Unique agent identifier', min_length=8, max_length=8, pattern='^[a-z0-9]+$')
    dateFrom: str | None = Field(None, title='dateFrom', description='Start of the date range (inclusive), as an ISO 8601 date-time. An explicit timezone offset (for example Z or +02:00) is honored; UTC is assumed when omitted.', json_schema_extra={"format": "date-time"})
    dateTo: str | None = Field(None, title='dateTo', description='End of the date range (inclusive), as an ISO 8601 date-time. An explicit timezone offset (for example Z or +02:00) is honored; UTC is assumed when omitted.', json_schema_extra={"format": "date-time"})
    status: Literal['online', 'paused'] | None = Field(None, title='status', description='Filter by status.')
    sortDir: Literal['ASC', 'DESC'] | None = Field(None, title='sortDir', description='Sort direction by status start time (default DESC).')


class LiveAgentListAgentAvailabilityConfig(BaseModel):
    operation: Literal['list_agent_availability'] = Field('list_agent_availability', title='Retrieve agent availability history', json_schema_extra={"ui:hidden": True, "x-display-name": 'Retrieve agent availability history', "x-is-trigger": False})
    agentId: str | None = Field(None, title='agentId', description='Filter by agent ID. Supports comma-separated values for multiple agents.')
    departmentId: str | None = Field(None, title='departmentId', description='Filter by department ID. Supports comma-separated values for multiple departments.')
    serviceType: Literal['to_solve', 'chat', 'call'] | None = Field(None, title='serviceType', description='Filter by service type. Supports comma-separated values.')
    availableFrom: str | None = Field(None, title='availableFrom', description='Filter records active after this date-time (inclusive). RFC 3339 date-time; an explicit timezone offset (e.g. Z or +02:00) is honored, UTC is assumed when omitted.', json_schema_extra={"format": "date-time"})
    availableTo: str | None = Field(None, title='availableTo', description='Filter records active before this date-time (inclusive). RFC 3339 date-time; an explicit timezone offset (e.g. Z or +02:00) is honored, UTC is assumed when omitted.', json_schema_extra={"format": "date-time"})
    sortDir: Literal['ASC', 'DESC'] | None = Field(None, title='sortDir', description='Sort direction for available_from field. Default is DESC (newest first).')
    limit: int | None = Field(None, title='limit', description='Maximum number of records to return (1-1000). Default is 1000.', ge=1, le=1000)
    cursor: str | None = Field(None, title='cursor', description='Cursor token for paginated results. Use the value returned in the previous response to fetch the next page.\n')




class LiveAgentRenameDepartmentConfig(BaseModel):
    operation: Literal['rename_department'] = Field('rename_department', title='Rename a department', json_schema_extra={"ui:hidden": True, "x-display-name": 'Rename a department', "x-is-trigger": False})
    departmentId: str = Field(..., title='departmentId', description='', min_length=1, max_length=8, pattern='^[a-z0-9]+$')
    newName: str = Field(..., title='newName', description='New department name.', min_length=1, max_length=191)


class LiveAgentGetDepartmentConfig(BaseModel):
    operation: Literal['get_department'] = Field('get_department', title='Return a department by ID', json_schema_extra={"ui:hidden": True, "x-display-name": 'Return a department by ID', "x-is-trigger": False})
    departmentId: str = Field(..., title='departmentId', description='', min_length=1, max_length=8, pattern='^[a-z0-9]+$')


class LiveAgentListTicketFieldDefinitionsConfig(BaseModel):
    operation: Literal['list_ticket_field_definitions'] = Field('list_ticket_field_definitions', title='List ticket field definitions', json_schema_extra={"ui:hidden": True, "x-display-name": 'List ticket field definitions', "x-is-trigger": False})
    includeArchived: bool | None = Field(None, title='includeArchived', description='Include archived definitions in the result.')
    filter: str | None = Field(None, title='filter', description='Case-insensitive substring matched against the definition name.')


class LiveAgentGetTicketFieldDefinitionConfig(BaseModel):
    operation: Literal['get_ticket_field_definition'] = Field('get_ticket_field_definition', title='Get a ticket field definition by ID', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get a ticket field definition by ID', "x-is-trigger": False})
    id: int = Field(..., title='id', description='', ge=1)


class LiveAgentListTicketActivityConfig(BaseModel):
    operation: Literal['list_ticket_activity'] = Field('list_ticket_activity', title='Get agent activity history for a ticket', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get agent activity history for a ticket', "x-is-trigger": False})
    ticketId: str = Field(..., title='ticketId', description='Unique ticket identifier', min_length=1, max_length=8, pattern='^[a-z0-9]+$')
    agentId: list[str] | None = Field(None, title='agentId', description='Filter by agent ID(s). Multiple values narrow results to matching agents.')
    activityType: list[Literal['solve', 'view', 'ring_chat', 'ring_call', 'ring_invite']] | None = Field(None, title='activityType', description='Filter by activity type(s)')
    activityFromStart: str | None = Field(None, title='activityFromStart', description='Filter activities starting from this date-time (inclusive), ISO 8601 UTC', json_schema_extra={"format": "date-time"})
    activityFromEnd: str | None = Field(None, title='activityFromEnd', description='Filter activities starting before this date-time (inclusive), ISO 8601 UTC', json_schema_extra={"format": "date-time"})
    sortOrder: Literal['asc', 'desc'] | None = Field(None, title='sortOrder', description='Sort direction for activityFrom (default desc)')


class LiveAgentOnNewOrUpdatedTicketActivityConfig(PollTriggerConfigBase):
    operation: Literal['on_new_or_updated_ticket_activity'] = Field('on_new_or_updated_ticket_activity', title='On New Or Updated Ticket Activity', json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": 'On New Or Updated Ticket Activity'})
    ticketId: str = Field(..., title='ticketId', description='Unique ticket identifier', min_length=1, max_length=8, pattern='^[a-z0-9]+$')
    agentId: list[str] | None = Field(None, title='agentId', description='Filter by agent ID(s). Multiple values narrow results to matching agents.')
    activityType: list[Literal['solve', 'view', 'ring_chat', 'ring_call', 'ring_invite']] | None = Field(None, title='activityType', description='Filter by activity type(s)')
    activityFromStart: str | None = Field(None, title='activityFromStart', description='Filter activities starting from this date-time (inclusive), ISO 8601 UTC', json_schema_extra={"format": "date-time"})
    activityFromEnd: str | None = Field(None, title='activityFromEnd', description='Filter activities starting before this date-time (inclusive), ISO 8601 UTC', json_schema_extra={"format": "date-time"})
    sortOrder: Literal['asc', 'desc'] | None = Field(None, title='sortOrder', description='Sort direction for activityFrom (default desc)')


LiveAgentConfig = Annotated[Union[LiveAgentListAgentActivityConfig, LiveAgentOnNewOrUpdatedAgentActivityConfig, LiveAgentListAgentWorktimeConfig, LiveAgentOnNewOrUpdatedAgentWorktimeConfig, LiveAgentListAgentAvailabilityConfig, LiveAgentRenameDepartmentConfig, LiveAgentGetDepartmentConfig, LiveAgentListTicketFieldDefinitionsConfig, LiveAgentGetTicketFieldDefinitionConfig, LiveAgentListTicketActivityConfig, LiveAgentOnNewOrUpdatedTicketActivityConfig], Field(discriminator="operation")]


class LiveAgentNodeConfig(NodeConfig[LiveAgentConfig, LiveAgentAPIKeyCredential]):
    pass


class LiveAgentNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-liveagent"
    connection_evidence = ConnectionEvidence(operation="list_ticket_field_definitions", noun="ticket fields")
    edit_examples = ["Read LiveAgent ticket activity", "Monitor agent availability in LiveAgent", "Rename a LiveAgent department"]

    @classmethod
    def get_config_model(cls):
        return LiveAgentNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        origin = LiveAgentAPIKeyCredential.account_origin(credential.account_url)
        async with guarded_async_client(timeout=45, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, origin + "/api/v4" + path,
                headers={"apikey": credential.api_key, "Accept": "application/json"}, params=params, json=body)
        if not 200 <= response.status_code < 300:
            try:
                payload = response.json()
                detail = payload.get("error") or payload.get("detail") or payload.get("title") or response.reason_phrase
            except (ValueError, AttributeError):
                detail = response.reason_phrase
            raise ValueError(f"LiveAgent API error {response.status_code}: {str(detail).replace(credential.api_key, '[redacted]')}")
        data = response.json() if response.content else {}
        if not isinstance(data, dict):
            raise ValueError("LiveAgent returned an unexpected response shape")
        if "error" in data and data["error"]:
            raise ValueError("LiveAgent API error: " + str(data["error"]).replace(credential.api_key, "[redacted]"))
        return data

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("event_count")) if config.get("operation", "").startswith("on_") else True

    @classmethod
    def resolve_agent_event(cls, output):
        records = output.get("records")
        if not isinstance(records, list):
            return super().resolve_agent_event(output)
        if not records:
            return None
        kind = output["operation"]
        lines = []
        for row in records[:10]:
            if kind.endswith("worktime"):
                text = f"Agent {output.get('agent_id')}: {row.get('status')}, from {row.get('statusFrom')} to {row.get('statusTo')}"
            else:
                agent = row.get("agentId") if kind.endswith("ticket_activity") else output.get("agent_id")
                ticket = row.get("ticketId") if kind.endswith("agent_activity") else output.get("ticket_id")
                text = f"Agent {agent}: {row.get('activityType')} on ticket {ticket}, from {row.get('activityFrom')} to {row.get('activityTo')}"
            lines.append(text)
        return {"text": f"LiveAgent: {len(records)} new or updated history record(s) at {output.get('account_url')}:\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        cfg = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect LiveAgent with an API key")
        operation = cfg.operation
        spec = OPERATIONS[operation]
        values = cfg.model_dump(exclude_none=True)
        path = spec["path"]
        for field in spec["path_fields"]:
            path = path.replace("{" + field + "}", quote(str(values[field]), safe=""))
        params = {field: values[field] for field in spec["query"] if field in values}
        body = {field: values[field] for field in spec["body"] if field in values}
        if not spec.get("poll"):
            data = await self._request(credential, spec["method"], path, params=params or None, body=body or None)
            return {"status": "success", "operation": operation, "data": data}
        rows = []
        # Provider's descending time order keeps the most recent records in view.
        if "sortOrder" in spec["query"]:
            params["sortOrder"] = "desc"
        elif "sortDir" in spec["query"]:
            params["sortDir"] = "DESC"
        data = await self._request(credential, spec["method"], path, params=params or None)
        if data.get("truncated"):
            raise ValueError("LiveAgent history is truncated; narrow the trigger's date range before polling")
        rows = data.get(spec["rows"], [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("LiveAgent returned an unexpected history list")
        fresh = await self._filter_unseen(rows, lambda row: hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest())
        return {"status": "success", "operation": operation, "records": fresh, "event_count": len(fresh),
                "agent_id": values.get("agentId"), "ticket_id": values.get("ticketId"), "account_url": credential.account_url}
