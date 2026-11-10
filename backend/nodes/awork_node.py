"""awork v1 operations and authenticated workspace project webhooks.

Contract: https://api.awork.com/openapi/v1 (1.3.0).
API keys: https://developers.awork.com/authentication
Webhook delivery: https://developers.awork.com/webhooks
"""
from __future__ import annotations

import hmac
import secrets
from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union
from uuid import UUID
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.scopes.awork import AWORK_SCOPES
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE_URL = "https://api.awork.com/api/v1"
AUTH_HEADER = "X-NoClick-Awork-Key"

class AworkAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="awork API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://developers.awork.com/authentication",
            "x-credential-instructions": "In awork, open Settings > Integrations, choose an API client, then Manage API Keys and copy a key. API keys grant workspace admin access. Paste the key without the Bearer prefix."})
    credential_type: Literal["awork_api_key"] = Field("awork_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @model_validator(mode="after")
    def clean_key(self):
        self.api_key = clean_secret(self.api_key, field_name="API key")
        if any(c.isspace() for c in self.api_key):
            raise ValueError("Paste the API key without a header or whitespace")
        return self

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def validate_task(self):
        if getattr(self, "baseType", None) == "projecttask" and not getattr(self, "entityId", None):
            raise ValueError("Project tasks require entityId, the project ID")
        return self

OPERATIONS = {'list_projects': ('GET', '/projects', ()),
 'get_project': ('GET', '/projects/{projectId}', ()),
 'create_project': ('POST',
                    '/projects',
                    ('name',
                     'description',
                     'isPrivate',
                     'companyId',
                     'startDate',
                     'dueDate',
                     'timeBudget',
                     'isBillableByDefault')),
 'update_project': ('PUT',
                    '/projects/{projectId}',
                    ('name',
                     'description',
                     'isPrivate',
                     'companyId',
                     'startDate',
                     'dueDate',
                     'timeBudget',
                     'isBillableByDefault')),
 'list_tasks': ('GET', '/me/allavailabletasks', ()),
 'list_project_tasks': ('GET', '/projects/{projectId}/projecttasks', ()),
 'get_task': ('GET', '/tasks/{taskId}', ()),
 'create_task': ('POST',
                 '/tasks',
                 ('name',
                  'description',
                  'baseType',
                  'entityId',
                  'taskStatusId',
                  'typeOfWorkId',
                  'isPrio',
                  'dueOn',
                  'plannedDuration')),
 'update_task': ('PUT',
                 '/tasks/{taskId}',
                 ('name', 'description', 'isPrio', 'startOn', 'dueOn', 'plannedDuration')),
 'list_task_comments': ('GET', '/tasks/{taskId}/comments', ()),
 'create_task_comment': ('POST', '/tasks/{taskId}/comments', ('message',)),
 'list_project_comments': ('GET', '/projects/{projectId}/comments', ()),
 'create_project_comment': ('POST', '/projects/{projectId}/comments', ('message',)),
 'list_companies': ('GET', '/companies', ()),
 'get_company': ('GET', '/companies/{companyId}', ()),
 'create_company': ('POST', '/companies', ('name', 'description', 'industry')),
 'update_company': ('PUT', '/companies/{companyId}', ('name', 'description', 'industry')),
 'list_users': ('GET', '/users', ()),
 'list_time_entries': ('GET', '/timeentries', ()),
 'get_time_entry': ('GET', '/timeentries/{timeEntryId}', ()),
 'create_time_entry': ('POST',
                       '/timeentries',
                       ('timezone',
                        'typeOfWorkId',
                        'userId',
                        'projectId',
                        'taskId',
                        'note',
                        'startDateUtc',
                        'startTimeUtc',
                        'duration',
                        'isBillable')),
 'list_types_of_work': ('GET', '/typeofwork', ())}

class AworkListProjectsConfig(Input):
    operation: Literal["list_projects"] = Field("list_projects", title="List Projects", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    page: int = Field(1, description='Page number for pagination', ge=1)
    pageSize: int = Field(10, description='Number of items per page', ge=1, le=100)
    orderby: Optional[str] = Field(None, description='The properties to order by')
    filterby: Optional[str] = Field(None, description='The filter expression to filter by')

class AworkGetProjectConfig(Input):
    operation: Literal["get_project"] = Field("get_project", title="Get Project", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    projectId: UUID = Field(..., description='The id of the project.')

class AworkCreateProjectConfig(Input):
    operation: Literal["create_project"] = Field("create_project", title="Create Project", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    name: str = Field(..., description='The name of the Project. Max allowed length: 1000 characters.', max_length=1000, min_length=1)
    description: Optional[str] = Field(None, description='The project description. Max allowed length: 25000 characters.', max_length=25000)
    isPrivate: Optional[bool] = Field(None, description='Whether this is a private project only visible to members and the creator.\nDefaults to false.\nCan only be changed from public to private if no times have been tracked on this project.\nCan always be made public.')
    companyId: Optional[UUID] = Field(None, description='The id of the company.')
    startDate: Optional[datetime] = Field(None, description='The start date of the project.')
    dueDate: Optional[datetime] = Field(None, description='The due date of the project.')
    timeBudget: Optional[int] = Field(None, description='The time budget the project has, in seconds.', ge=0)
    isBillableByDefault: Optional[bool] = Field(None, description='Whether project times should be billable by default.')

class AworkUpdateProjectConfig(Input):
    operation: Literal["update_project"] = Field("update_project", title="Update Project", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    projectId: UUID = Field(..., description='The id of the project.')
    name: str = Field(..., description='The name of the Project. Max allowed length: 1000 characters.', max_length=1000, min_length=1)
    description: Optional[str] = Field(None, description='The project description. Max allowed length: 25000 characters.', max_length=25000)
    isPrivate: Optional[bool] = Field(None, description='Whether this is a private project only visible to members and the creator.\nDefaults to false.\nCan only be changed from public to private if no times have been tracked on this project.\nCan always be made public.')
    companyId: Optional[UUID] = Field(None, description='The id of the company.')
    startDate: Optional[datetime] = Field(None, description='The start date of the project.')
    dueDate: Optional[datetime] = Field(None, description='The due date of the project.')
    timeBudget: Optional[int] = Field(None, description='The time budget the project has, in seconds.', ge=0)
    isBillableByDefault: Optional[bool] = Field(None, description='Whether project times should be billable by default.')

class AworkListTasksConfig(Input):
    operation: Literal["list_tasks"] = Field("list_tasks", title="List Tasks", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    page: int = Field(1, description='Page number for pagination', ge=1)
    pageSize: int = Field(10, description='Number of items per page', ge=1, le=100)
    orderby: Optional[str] = Field(None, description='The properties to order by')
    filterby: Optional[str] = Field(None, description='The filter expression to filter by')

class AworkListProjectTasksConfig(Input):
    operation: Literal["list_project_tasks"] = Field("list_project_tasks", title="List Project Tasks", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    projectId: UUID = Field(..., description='The id of the project.')
    page: int = Field(1, description='Page number for pagination', ge=1)
    pageSize: int = Field(10, description='Number of items per page', ge=1, le=100)
    orderby: Optional[str] = Field(None, description='The properties to order by')
    filterby: Optional[str] = Field(None, description='The filter expression to filter by')

class AworkGetTaskConfig(Input):
    operation: Literal["get_task"] = Field("get_task", title="Get Task", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    taskId: UUID = Field(..., description='The id of the task.')

class AworkCreateTaskConfig(Input):
    operation: Literal["create_task"] = Field("create_task", title="Create Task", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    name: str = Field(..., description='The name of the task. Max allowed length: 1000 characters.', max_length=1000, min_length=1)
    description: Optional[str] = Field(None, description='The description of the task. Max allowed length: 25000 characters.')
    baseType: Literal['private', 'projecttask'] = Field(..., description="The base type of the task. Can be 'private' for a private task or 'projecttask' for a project task.")
    entityId: Optional[UUID] = Field(None, description="The id of the entity the task is related to.\nFor private tasks, this is optional and will default to the current user's ID if not provided.\nFor project tasks, this is required and must be the project ID.")
    taskStatusId: Optional[UUID] = Field(None, description="The id of the status for this task.\nIf not provided, defaults to the first status of type 'todo'.")
    typeOfWorkId: Optional[UUID] = Field(None, description='The id of the type of work for this task.\nIf not provided, defaults to the first type of work in the workspace.')
    isPrio: Optional[bool] = Field(None, description='Whether this task is marked as priority.')
    dueOn: Optional[datetime] = Field(None, description='The expected due date and time of the task.')
    plannedDuration: Optional[int] = Field(None, description='The expected planned workload of the task, in seconds.', ge=0)

class AworkUpdateTaskConfig(Input):
    operation: Literal["update_task"] = Field("update_task", title="Update Task", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    taskId: UUID = Field(..., description='The id of the task.')
    name: str = Field(..., description='The name of the task. Max allowed length: 1000 characters.', max_length=1000, min_length=1)
    description: Optional[str] = Field(None, description='The description of the task. Max allowed length: 25000 characters.')
    isPrio: Optional[bool] = Field(None, description='Whether this task is marked as priority.')
    startOn: Optional[datetime] = Field(None, description='The expected start date and time of the task.')
    dueOn: Optional[datetime] = Field(None, description='The expected due date and time of the task.')
    plannedDuration: Optional[int] = Field(None, description='The expected planned workload of the task, in seconds.', ge=0)

class AworkListTaskCommentsConfig(Input):
    operation: Literal["list_task_comments"] = Field("list_task_comments", title="List Task Comments", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    taskId: UUID = Field(..., description='The id of the task.')
    page: int = Field(1, description='Page number for pagination', ge=1)
    pageSize: int = Field(10, description='Number of items per page', ge=1, le=100)
    orderby: Optional[str] = Field(None, description='The properties to order by')
    filterby: Optional[str] = Field(None, description='The filter expression to filter by')

class AworkCreateTaskCommentConfig(Input):
    operation: Literal["create_task_comment"] = Field("create_task_comment", title="Create Task Comment", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    taskId: UUID = Field(..., description='The id of the task to create the comment for.')
    message: str = Field(..., description='The message of the comment.', max_length=65000, min_length=1)

class AworkListProjectCommentsConfig(Input):
    operation: Literal["list_project_comments"] = Field("list_project_comments", title="List Project Comments", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    projectId: UUID = Field(..., description='The id of the project.')
    page: int = Field(1, description='Page number for pagination', ge=1)
    pageSize: int = Field(10, description='Number of items per page', ge=1, le=100)
    orderby: Optional[str] = Field(None, description='The properties to order by')
    filterby: Optional[str] = Field(None, description='The filter expression to filter by')

class AworkCreateProjectCommentConfig(Input):
    operation: Literal["create_project_comment"] = Field("create_project_comment", title="Create Project Comment", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    projectId: UUID = Field(..., description='The id of the project to create the comment for.')
    message: str = Field(..., description='The message of the comment.', max_length=65000, min_length=1)

class AworkListCompaniesConfig(Input):
    operation: Literal["list_companies"] = Field("list_companies", title="List Companies", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    page: int = Field(1, description='Page number for pagination', ge=1)
    pageSize: int = Field(10, description='Number of items per page', ge=1, le=100)
    orderby: Optional[str] = Field(None, description='The properties to order by')
    filterby: Optional[str] = Field(None, description='The filter expression to filter by')

class AworkGetCompanyConfig(Input):
    operation: Literal["get_company"] = Field("get_company", title="Get Company", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    companyId: UUID = Field(..., description='The id of the company.')

class AworkCreateCompanyConfig(Input):
    operation: Literal["create_company"] = Field("create_company", title="Create Company", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    name: str = Field(..., description='The company name.', max_length=1000, min_length=1)
    description: Optional[str] = Field(None, description='The company description.', max_length=25000)
    industry: Optional[str] = Field(None, description="The company's industry.", max_length=1000)

class AworkUpdateCompanyConfig(Input):
    operation: Literal["update_company"] = Field("update_company", title="Update Company", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    companyId: UUID = Field(..., description='The id of the company to update.')
    name: str = Field(..., description='The company name.', max_length=1000, min_length=1)
    description: Optional[str] = Field(None, description='The company description.', max_length=25000)
    industry: Optional[str] = Field(None, description="The company's industry.", max_length=1000)

class AworkListUsersConfig(Input):
    operation: Literal["list_users"] = Field("list_users", title="List Users", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    page: int = Field(1, description='Page number for pagination', ge=1)
    pageSize: int = Field(10, description='Number of items per page', ge=1, le=100)
    orderby: Optional[str] = Field(None, description='The properties to order by')
    filterby: Optional[str] = Field(None, description='The filter expression to filter by')

class AworkListTimeEntriesConfig(Input):
    operation: Literal["list_time_entries"] = Field("list_time_entries", title="List Time Entries", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    page: int = Field(1, description='Page number for pagination', ge=1)
    pageSize: int = Field(10, description='Number of items per page', ge=1, le=100)
    orderby: Optional[str] = Field(None, description='The properties to order by')
    filterby: Optional[str] = Field(None, description='The filter expression to filter by')

class AworkGetTimeEntryConfig(Input):
    operation: Literal["get_time_entry"] = Field("get_time_entry", title="Get Time Entry", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    timeEntryId: UUID = Field(..., description='The id of the time entry.')

class AworkCreateTimeEntryConfig(Input):
    operation: Literal["create_time_entry"] = Field("create_time_entry", title="Create Time Entry", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    timezone: str = Field(..., description='The original timezone of the time tracking.\nThe format of the timezone is the IANA standard.', min_length=1)
    typeOfWorkId: UUID = Field(..., description='The id of the type of work.')
    userId: UUID = Field(..., description='The id of the user.')
    projectId: Optional[UUID] = Field(None, description='The id of the project.')
    taskId: Optional[UUID] = Field(None, description='The id of the task.')
    note: Optional[str] = Field(None, description='The note of the time tracking.')
    startDateUtc: datetime = Field(..., description='The date (in UTC) when the time tracking was started.')
    startTimeUtc: str = Field(..., pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]$", description='The time (in UTC) when the time tracking was started.')
    duration: int = Field(..., description='The duration of the time tracking in seconds.\nRequired when the time tracking has already been completed and EndTime has not been set.', ge=0)
    isBillable: Optional[bool] = Field(None, description='Whether the time tracking is billable or not.')

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Use an IANA timezone such as Europe/Berlin") from None
        return value

class AworkListTypesOfWorkConfig(Input):
    operation: Literal["list_types_of_work"] = Field("list_types_of_work", title="List Types Of Work", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    page: int = Field(1, description='Page number for pagination', ge=1)
    pageSize: int = Field(10, description='Number of items per page', ge=1, le=100)
    orderby: Optional[str] = Field(None, description='The properties to order by')
    filterby: Optional[str] = Field(None, description='The filter expression to filter by')

class AworkOnProjectCreatedConfig(WebhookTriggerConfigBase):
    operation: Literal["on_project_created"] = Field("on_project_created", title="On Project Created", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    webhook_url: Optional[str] = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})

AworkConfig = Annotated[Union[AworkListProjectsConfig, AworkGetProjectConfig, AworkCreateProjectConfig, AworkUpdateProjectConfig, AworkListTasksConfig, AworkListProjectTasksConfig, AworkGetTaskConfig, AworkCreateTaskConfig, AworkUpdateTaskConfig, AworkListTaskCommentsConfig, AworkCreateTaskCommentConfig, AworkListProjectCommentsConfig, AworkCreateProjectCommentConfig, AworkListCompaniesConfig, AworkGetCompanyConfig, AworkCreateCompanyConfig, AworkUpdateCompanyConfig, AworkListUsersConfig, AworkListTimeEntriesConfig, AworkGetTimeEntryConfig, AworkCreateTimeEntryConfig, AworkListTypesOfWorkConfig, AworkOnProjectCreatedConfig], Field(discriminator="operation")]

class AworkNodeConfig(NodeConfig[AworkConfig, AworkAPIKeyCredential]):
    pass


class AworkNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-awork"
    scope_registry = AWORK_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_projects", noun="projects", label_keys=("name", "id"))
    edit_examples = ["Create a project in awork", "Add a task to a project", "Log time spent on a task", "Start when a project is created"]

    @classmethod
    def get_config_model(cls):
        return AworkNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        key = AworkAPIKeyCredential.model_validate(credential).api_key
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, params=params, json=body,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
        except httpx.RequestError:
            raise ValueError("awork request could not be completed; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            # Preserve the provider's rejection text for connection evidence, removing the secret.
            raise ValueError(f"awork API {response.status_code}: " + response.text.replace(key, "[redacted]")[:2000])
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            raise ValueError("awork returned an invalid JSON response") from None

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an awork API key")
        op = self.config.config
        if isinstance(op, AworkOnProjectCreatedConfig):
            return self.no_event_output(op.operation)
        self.scope_registry.require(op.operation)
        method, path, body_fields = OPERATIONS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        body = {k: values.pop(k) for k in body_fields if k in values} if body_fields else None
        result = await self._request(self.config.credentials.model_dump(), method, path, params=values or None, body=body)
        output = {"status": "success", "operation": op.operation, "data": result}
        if isinstance(result, list):
            output["pagination"] = {"page": getattr(op, "page", 1), "page_size": getattr(op, "pageSize", 10),
                "next_page": op.page + 1 if hasattr(op, "page") and len(result) == op.pageSize else None}
        await self.emit(output)
        return output

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        cls.scope_registry.require("on_project_created")
        secret = secrets.token_urlsafe(32)
        data = await cls._request(credential, "POST", "/webhooks", body={
            "name": "NoClick " + node_id, "uri": webhook_url, "events": "project_added", "isActive": True,
            "authenticationType": "header", "authentication": AUTH_HEADER + "=" + secret})
        if not isinstance(data, dict) or not data.get("id"):
            raise ValueError("awork did not return a webhook ID")
        return {"external_webhook_id": str(UUID(data["id"])), "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if credential and config.get("external_webhook_id"):
            identifier = str(UUID(str(config["external_webhook_id"])))
            await cls._request(credential, "DELETE", "/webhooks/" + identifier)

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # awork sends the configured static header; it does not sign the body.
        secret = (config or {}).get("signing_secret")
        received = next((v for k, v in headers.items() if k.lower() == AUTH_HEADER.lower()), "")
        return bool(secret and isinstance(received, str) and hmac.compare_digest(str(secret).encode(), received.encode()))

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return isinstance(payload, dict) and payload.get("eventType") == "project_added"

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict):
            return None
        payload = output if "eventType" in output else output.get("data")
        if not isinstance(payload, dict) or payload.get("eventType") != "project_added":
            return None
        entity = payload.get("entity") or {}
        actor = payload.get("triggeredBy") or {}
        identifier = payload.get("entityId")
        if not identifier:
            return None
        name = entity.get("name") or identifier
        who = " ".join(str(actor.get(k) or "") for k in ("firstName", "lastName")).strip()
        text = f"awork project created: {name}"
        if who:
            text += f"\nCreated by {who} (user {actor.get('id')})."
        text += f"\nAt {payload.get('timestamp')}.\nProject: {payload.get('entityLink')}\nTo act: get_project projectId={identifier}."
        return {"text": text, "title": str(name), "conversation_key": str(identifier)}
