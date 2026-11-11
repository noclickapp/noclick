"""Houzz Pro API v0.2.0: one published API operation per workflow action.

Authentication: https://developer.houzz.com/docs/guides/authentication
Paste a short-lived service-account Bearer token; replace it when it expires.
"""
from __future__ import annotations

import hashlib
import hmac
import json

from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.core.credential_fields import clean_secret
from nodes.scopes.houzz_pro import HOUZZ_PRO_SCOPES
from utils.ssrf import guarded_async_client

BASE_URL = "https://pro-api.houzz.com/api"
FAMILY = "houzz_pro_access_token"
ResourceID = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


class HouzzProAccessToken(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Houzz Pro Access Token", json_schema_extra={
        "x-credential-url": "https://developer.houzz.com/docs/guides/authentication",
        "x-credential-instructions": "Request a company service account from your Houzz representative. Follow the authentication guide to exchange its client ID and secret using grant_type=client_credentials and audience=https://pro-api.houzz.com, then paste the access_token here. Include read:projects for the connection check and the scopes required by your actions. Tokens expire: replace the token here when its expires_in lifetime ends. NoClick sends it only to pro-api.houzz.com and does not obtain or refresh it. Listing projects checks this company's project read access, not all write permissions.",
    })
    credential_type: Literal["houzz_pro_access_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=8192, title="Access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your Houzz Pro access token")
        value = clean_secret(value, field_name="Access token", key=True)
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste only the token, without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class _Page(_Input):
    limit: int = Field(20, ge=1, le=300, description="Maximum items in this page.")
    offset: int = Field(0, ge=0, description="Items to skip; use next_offset from the previous result.")


class _Write(_Input):
    idempotency_key: str | None = Field(None, min_length=1, max_length=128, pattern=r"^[ -~]+$", description="Optional Idempotency-Key. Reuse only for a retry of the exact same write within 24 hours.")

    @model_validator(mode="after")
    def nonempty_update(self):
        if self.operation.startswith("update_") and not any(v is not None for k,v in self.model_dump().items() if k not in {"operation", "resource_id", "idempotency_key"}):
            raise ValueError("Provide at least one field to update")
        return self

class ListProjectsConfig(_Page):
    """List projects."""
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})
    status_id: int | None = Field(None, description='Filter by project status ID (comma-separated for multiple)')
    archived: StrictBool | None = Field(None, description='Filter by archived state (true/false)')
    contact_id: int | None = Field(None, description='Filter by contact ID')


class GetProjectConfig(_Input):
    """Get Project."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})
    resource_id: ResourceID = Field(..., title="Resource Id")


class CreateProjectConfig(_Write):
    """Create Project."""
    operation: Literal["create_project"] = Field("create_project", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='Project name')
    contact_id: int | None = Field(None, description='Contact ID')
    status_id: int | None = Field(None, description='Status ID')
    owner_id: int | None = Field(None, description='Owner user ID')
    budget: float | None = Field(None, description='Project budget')
    project_type: int | None = Field(None, description='Project type ID')
    project_type_name: str | None = Field(None, description='Project type name')
    archived: StrictBool | None = Field(None, description='Whether the project is archived')
    notes: str | None = Field(None, description='Project notes')


class UpdateProjectConfig(_Write):
    """Update Project."""
    operation: Literal["update_project"] = Field("update_project", json_schema_extra={"ui:hidden": True})
    resource_id: ResourceID = Field(..., title="Resource Id")
    name: str | None = Field(None, description='Project name')
    contact_id: int | None = Field(None, description='Contact ID')
    status_id: int | None = Field(None, description='Status ID')
    owner_id: int | None = Field(None, description='Owner user ID')
    budget: float | None = Field(None, description='Project budget')
    project_type: int | None = Field(None, description='Project type ID')
    project_type_name: str | None = Field(None, description='Project type name')
    archived: StrictBool | None = Field(None, description='Whether the project is archived')
    notes: str | None = Field(None, description='Project notes')


class ListLeadsConfig(_Page):
    """List Leads."""
    operation: Literal["list_leads"] = Field("list_leads", json_schema_extra={"ui:hidden": True})
    contact_id: int | None = Field(None, description='Filter by contact ID')
    phase_id: int | None = Field(None, description="Lead pipeline phase ID. List the account's phases, built-in and custom, with the Lead Phase resource.")


class GetLeadConfig(_Input):
    """Get Lead."""
    operation: Literal["get_lead"] = Field("get_lead", json_schema_extra={"ui:hidden": True})
    resource_id: ResourceID = Field(..., title="Resource Id")


class CreateLeadConfig(_Write):
    """Create Lead."""
    operation: Literal["create_lead"] = Field("create_lead", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='Lead name')
    contact_id: int | None = Field(None, description='Contact ID')
    description: str | None = Field(None, description='Lead description')
    budget: float | None = Field(None, description='Lead budget')
    type: str | None = Field(None, description='Project type label')
    service_type_id: int | None = Field(None, description='Service type ID')
    source_code: int | None = Field(None, description='Source code')
    source: str | None = Field(None, description='Source label')
    expected_start_date: str | None = Field(None, description='Expected start date')
    phase_id: int | None = Field(None, description="Lead pipeline phase ID. List the account's phases, built-in and custom, with the Lead Phase resource. Omit to use the company default phase.")


class UpdateLeadConfig(_Write):
    """Update Lead."""
    operation: Literal["update_lead"] = Field("update_lead", json_schema_extra={"ui:hidden": True})
    resource_id: ResourceID = Field(..., title="Resource Id")
    name: str | None = Field(None, description='Lead name')
    contact_id: int | None = Field(None, description='Contact ID')
    description: str | None = Field(None, description='Lead description')
    budget: float | None = Field(None, description='Lead budget')
    type: str | None = Field(None, description='Project type label')
    service_type_id: int | None = Field(None, description='Service type ID')
    source_code: int | None = Field(None, description='Source code')
    source: str | None = Field(None, description='Source label')
    expected_start_date: str | None = Field(None, description='Expected start date')


class ListContactsConfig(_Page):
    """List contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    search_text: str | None = Field(None, description='Search contacts by name, email, or phone (partial match). The total reflects the same search.')


class GetContactConfig(_Input):
    """Get Contact."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    resource_id: ResourceID = Field(..., title="Resource Id")


class CreateContactConfig(_Write):
    """Create Contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='Contact name')
    company_name: str | None = Field(None, description='Company name')
    email: str | None = Field(None, description='Primary email')
    email2: str | None = Field(None, description='Secondary email')
    phone: str | None = Field(None, description='Primary phone')
    phone2: str | None = Field(None, description='Secondary phone')
    notes: str | None = Field(None, description='Notes')
    contact_group_name: str | None = Field(None, description='Contact group name (creates or assigns to existing group)')


class UpdateContactConfig(_Write):
    """Update Contact."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    resource_id: ResourceID = Field(..., title="Resource Id")
    name: str | None = Field(None, description='Contact name')
    company_name: str | None = Field(None, description='Company name')
    email: str | None = Field(None, description='Primary email')
    email2: str | None = Field(None, description='Secondary email')
    phone: str | None = Field(None, description='Primary phone')
    phone2: str | None = Field(None, description='Secondary phone')
    notes: str | None = Field(None, description='Notes')
    contact_group_name: str | None = Field(None, description='Contact group name (creates or assigns to existing group)')


class ConvertLeadConfig(_Write):
    """Convert lead to project."""
    operation: Literal["convert_lead"] = Field("convert_lead", json_schema_extra={"ui:hidden": True})
    resource_id: ResourceID = Field(..., title="Resource Id")


class RetireLeadConfig(_Write):
    """Retire lead."""
    operation: Literal["retire_lead"] = Field("retire_lead", json_schema_extra={"ui:hidden": True})
    resource_id: ResourceID = Field(..., title="Resource Id")


class ReactivateLeadConfig(_Write):
    """Reactivate lead."""
    operation: Literal["reactivate_lead"] = Field("reactivate_lead", json_schema_extra={"ui:hidden": True})
    resource_id: ResourceID = Field(..., title="Resource Id")


class UpdateLeadPhaseConfig(_Write):
    """Update lead phase."""
    operation: Literal["update_lead_phase"] = Field("update_lead_phase", json_schema_extra={"ui:hidden": True})
    resource_id: ResourceID = Field(..., title="Resource Id")
    phase_id: int = Field(..., description="Lead pipeline phase ID. List the account's phases, built-in and custom, with the Lead Phase resource.")


class ListProjectTasksConfig(_Page):
    """List project tasks."""
    operation: Literal["list_project_tasks"] = Field("list_project_tasks", json_schema_extra={"ui:hidden": True})
    project_id: ResourceID = Field(..., title="Project Id")


class CreateProjectTaskConfig(_Write):
    """Create project task."""
    operation: Literal["create_project_task"] = Field("create_project_task", json_schema_extra={"ui:hidden": True})
    project_id: ResourceID = Field(..., title="Project Id")
    title: str = Field(..., description='Task title')
    description: str | None = Field(None, description='Task description')
    due_date: float | None = Field(None, description='Due date (epoch ms)')
    done: StrictBool | None = Field(None, description='Completed flag')
    visibility: Literal['Private', 'Shared'] | None = Field(None, description='Visibility')
    photos_required: StrictBool | None = Field(None, description='Photos required flag')
    punchlist_id: int | None = Field(None, description='Punchlist ID — when set, creates a punchlist task')
    milestone_id: int | None = Field(None, description='Milestone ID to link this task to')


class GetTaskConfig(_Input):
    """Get Task."""
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"ui:hidden": True})
    resource_id: ResourceID = Field(..., title="Resource Id")


class UpdateTaskConfig(_Write):
    """Update Task."""
    operation: Literal["update_task"] = Field("update_task", json_schema_extra={"ui:hidden": True})
    resource_id: ResourceID = Field(..., title="Resource Id")
    title: str | None = Field(None, description='Task title')
    description: str | None = Field(None, description='Task description')
    due_date: float | None = Field(None, description='Due date (epoch ms)')
    done: StrictBool | None = Field(None, description='Completed flag')
    visibility: Literal['Private', 'Shared'] | None = Field(None, description='Visibility')
    photos_required: StrictBool | None = Field(None, description='Photos required flag')
    milestone_id: int | None = Field(None, description='Milestone ID to link this task to')


class ListProjectNotesConfig(_Page):
    """List project notes."""
    operation: Literal["list_project_notes"] = Field("list_project_notes", json_schema_extra={"ui:hidden": True})
    project_id: ResourceID = Field(..., title="Project Id")
    archived: StrictBool | None = Field(None, description='Return archived notes instead of active ones')


class CreateProjectNoteConfig(_Write):
    """Create project note."""
    operation: Literal["create_project_note"] = Field("create_project_note", json_schema_extra={"ui:hidden": True})
    project_id: ResourceID = Field(..., title="Project Id")
    content: str = Field(..., description='Note body text')
    type: Literal['DEFAULT', 'CALL_LOG'] | None = Field(None, description='Note type')
    sub_type: Literal['NOT_AVAILABLE', 'GOOD_DISCUSSION', 'NO_ANSWER', 'CALL_LATER', 'NOT_INTERESTED'] | None = Field(None, description='Note sub-type (used with CALL_LOG)')
    source: str | None = Field(None, description='Originating system; defaults to "api" when omitted')


class ListProjectStatusesConfig(_Page):
    """List Project Statuses."""
    operation: Literal["list_project_statuses"] = Field("list_project_statuses", json_schema_extra={"ui:hidden": True})


class ListLeadPhasesConfig(_Page):
    """List Lead Phases."""
    operation: Literal["list_lead_phases"] = Field("list_lead_phases", json_schema_extra={"ui:hidden": True})


class OnProjectUpdatedConfig(WebhookTriggerConfigBase):
    """Start when a Houzz Pro project changes, including status and budget updates."""
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    operation: Literal["on_project_updated"] = Field("on_project_updated", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers",
        "x-display-name": "Project Updated",
    })
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered with Houzz Pro automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


HouzzProConfig = Annotated[Union[
    ListProjectsConfig,
    GetProjectConfig,
    CreateProjectConfig,
    UpdateProjectConfig,
    ListLeadsConfig,
    GetLeadConfig,
    CreateLeadConfig,
    UpdateLeadConfig,
    ListContactsConfig,
    GetContactConfig,
    CreateContactConfig,
    UpdateContactConfig,
    ConvertLeadConfig,
    RetireLeadConfig,
    ReactivateLeadConfig,
    UpdateLeadPhaseConfig,
    ListProjectTasksConfig,
    CreateProjectTaskConfig,
    GetTaskConfig,
    UpdateTaskConfig,
    ListProjectNotesConfig,
    CreateProjectNoteConfig,
    ListProjectStatusesConfig,
    ListLeadPhasesConfig,
    OnProjectUpdatedConfig
], Field(discriminator="operation")]


class HouzzProFullConfig(NodeConfig[HouzzProConfig, HouzzProAccessToken]):
    model_config = ConfigDict(hide_input_in_errors=True)


OPERATIONS = {'list_projects': ('GET',
                   '/v1/projects',
                   {},
                   [('status_id', 'statusId'), ('archived', 'archived'), ('contact_id', 'contactId')],
                   []),
 'get_project': ('GET', '/v1/projects/{id}', {'resource_id': 'id'}, [], []),
 'create_project': ('POST',
                    '/v1/projects',
                    {},
                    [],
                    [('name', 'name'),
                     ('contact_id', 'contactId'),
                     ('status_id', 'statusId'),
                     ('owner_id', 'ownerId'),
                     ('budget', 'budget'),
                     ('project_type', 'projectType'),
                     ('project_type_name', 'projectTypeName'),
                     ('archived', 'archived'),
                     ('notes', 'notes')]),
 'update_project': ('PATCH',
                    '/v1/projects/{id}',
                    {'resource_id': 'id'},
                    [],
                    [('name', 'name'),
                     ('contact_id', 'contactId'),
                     ('status_id', 'statusId'),
                     ('owner_id', 'ownerId'),
                     ('budget', 'budget'),
                     ('project_type', 'projectType'),
                     ('project_type_name', 'projectTypeName'),
                     ('archived', 'archived'),
                     ('notes', 'notes')]),
 'list_leads': ('GET', '/v1/leads', {}, [('contact_id', 'contactId'), ('phase_id', 'phaseId')], []),
 'get_lead': ('GET', '/v1/leads/{id}', {'resource_id': 'id'}, [], []),
 'create_lead': ('POST',
                 '/v1/leads',
                 {},
                 [],
                 [('name', 'name'),
                  ('contact_id', 'contactId'),
                  ('description', 'description'),
                  ('budget', 'budget'),
                  ('type', 'type'),
                  ('service_type_id', 'serviceTypeId'),
                  ('source_code', 'sourceCode'),
                  ('source', 'source'),
                  ('expected_start_date', 'expectedStartDate'),
                  ('phase_id', 'phaseId')]),
 'update_lead': ('PATCH',
                 '/v1/leads/{id}',
                 {'resource_id': 'id'},
                 [],
                 [('name', 'name'),
                  ('contact_id', 'contactId'),
                  ('description', 'description'),
                  ('budget', 'budget'),
                  ('type', 'type'),
                  ('service_type_id', 'serviceTypeId'),
                  ('source_code', 'sourceCode'),
                  ('source', 'source'),
                  ('expected_start_date', 'expectedStartDate')]),
 'list_contacts': ('GET', '/v1/contacts', {}, [('search_text', 'searchText')], []),
 'get_contact': ('GET', '/v1/contacts/{id}', {'resource_id': 'id'}, [], []),
 'create_contact': ('POST',
                    '/v1/contacts',
                    {},
                    [],
                    [('name', 'name'),
                     ('company_name', 'companyName'),
                     ('email', 'email'),
                     ('email2', 'email2'),
                     ('phone', 'phone'),
                     ('phone2', 'phone2'),
                     ('notes', 'notes'),
                     ('contact_group_name', 'contactGroupName')]),
 'update_contact': ('PATCH',
                    '/v1/contacts/{id}',
                    {'resource_id': 'id'},
                    [],
                    [('name', 'name'),
                     ('company_name', 'companyName'),
                     ('email', 'email'),
                     ('email2', 'email2'),
                     ('phone', 'phone'),
                     ('phone2', 'phone2'),
                     ('notes', 'notes'),
                     ('contact_group_name', 'contactGroupName')]),
 'convert_lead': ('POST', '/v1/leads/{id}/convertToProject', {'resource_id': 'id'}, [], []),
 'retire_lead': ('POST', '/v1/leads/{id}/retire', {'resource_id': 'id'}, [], []),
 'reactivate_lead': ('POST', '/v1/leads/{id}/reactivate', {'resource_id': 'id'}, [], []),
 'update_lead_phase': ('POST',
                       '/v1/leads/{id}/updatePhase',
                       {'resource_id': 'id'},
                       [],
                       [('phase_id', 'phaseId')]),
 'list_project_tasks': ('GET', '/v1/projects/{projectId}/tasks', {'project_id': 'projectId'}, [], []),
 'create_project_task': ('POST',
                         '/v1/projects/{projectId}/tasks',
                         {'project_id': 'projectId'},
                         [],
                         [('title', 'title'),
                          ('description', 'description'),
                          ('due_date', 'dueDate'),
                          ('done', 'done'),
                          ('visibility', 'visibility'),
                          ('photos_required', 'photosRequired'),
                          ('punchlist_id', 'punchlistId'),
                          ('milestone_id', 'milestoneId')]),
 'get_task': ('GET', '/v1/tasks/{id}', {'resource_id': 'id'}, [], []),
 'update_task': ('PATCH',
                 '/v1/tasks/{id}',
                 {'resource_id': 'id'},
                 [],
                 [('title', 'title'),
                  ('description', 'description'),
                  ('due_date', 'dueDate'),
                  ('done', 'done'),
                  ('visibility', 'visibility'),
                  ('photos_required', 'photosRequired'),
                  ('milestone_id', 'milestoneId')]),
 'list_project_notes': ('GET',
                        '/v1/projects/{projectId}/notes',
                        {'project_id': 'projectId'},
                        [('archived', 'archived')],
                        []),
 'create_project_note': ('POST',
                         '/v1/projects/{projectId}/notes',
                         {'project_id': 'projectId'},
                         [],
                         [('content', 'content'),
                          ('type', 'type'),
                          ('sub_type', 'subType'),
                          ('source', 'source')]),
 'list_project_statuses': ('GET', '/v1/project-statuses', {}, [], []),
 'list_lead_phases': ('GET', '/v1/lead-phases', {}, [], [])}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    return value


class HouzzProNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-houzz-pro"
    scope_registry = HOUZZ_PRO_SCOPES
    connection_evidence = ConnectionEvidence(noun="projects", operation="list_projects", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return HouzzProFullConfig

    @classmethod
    async def _webhook_request(cls, credential, method, path, *, body=None):
        token = HouzzProAccessToken.model_validate(credential).access_token
        kwargs = {"json": body} if body is not None else {}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        except httpx.RequestError:
            raise ValueError("Houzz Pro webhook request failed") from None
        if method == "DELETE" and response.status_code == 404:
            return {"deleted": True}
        expected = 201 if method == "POST" else 200
        if response.status_code != expected:
            raise ValueError(f"Houzz Pro webhook request returned HTTP {response.status_code}")
        if len(response.content) > 10_000_000 or response.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
            raise ValueError("Houzz Pro returned an unexpected webhook response")
        try:
            result = response.json()
        except ValueError:
            raise ValueError("Houzz Pro returned invalid webhook JSON") from None
        if not isinstance(result, dict) or "error" in result:
            raise ValueError("Houzz Pro did not confirm the webhook request")
        return result

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        # Registration and one-time secret: https://developer.houzz.com/docs/guides/webhooks
        result = await cls._webhook_request(credential, "POST", "/v1/webhookSubscriptions", body={
            "url": webhook_url, "description": f"NoClick {node_id}",
            "triggers": [{"resourceName": "project", "eventType": "update"}],
        })
        subscription = result.get("data")
        if not isinstance(subscription, dict):
            raise ValueError("Houzz Pro did not return a webhook subscription")
        sid, secret = subscription.get("id"), subscription.get("secret")
        if type(sid) is not int or sid <= 0 or not isinstance(secret, str) or not secret:
            raise ValueError("Houzz Pro did not return a subscription ID and signing secret")
        return {"external_webhook_id": str(sid), "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        sid = (config or {}).get("external_webhook_id")
        if sid is None or credential is None:
            return
        result = await cls._webhook_request(credential, "DELETE", "/v1/webhookSubscriptions/" + quote(str(sid), safe=""))
        if result.get("deleted") is not True:
            raise ValueError("Houzz Pro did not confirm webhook deletion")

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # The secret is used literally, including whsec_; it is not base64-decoded.
        # https://developer.houzz.com/docs/guides/webhooks#verifying-delivery-signatures
        secret = (config or {}).get("signing_secret")
        values = {key.lower(): value for key, value in headers.items()}
        timestamp, received = values.get("x-webhook-timestamp"), values.get("x-webhook-signature")
        if not isinstance(secret, str) or not secret or not isinstance(timestamp, str) or not timestamp.isascii() or not timestamp.isdigit():
            return False
        if not isinstance(received, str) or not received.isascii():
            return False
        expected = "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(received, expected)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return (isinstance(payload, dict) and payload.get("event_type") == "project.update"
            and payload.get("entity_type") == "project" and payload.get("entity_id") is not None)

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("event_type") != "project.update":
            return None
        pid, company = output.get("entity_id"), output.get("company_id")
        if pid is None or company is None:
            return None
        record = output.get("data") if isinstance(output.get("data"), dict) else {}
        actor = output.get("actor") if isinstance(output.get("actor"), dict) else {}
        who = f"user {actor['id']}" if actor.get("type") == "user" and actor.get("id") is not None else "an automated process"
        name = record.get("name") or f"Project {pid}"
        lines = [f"Houzz Pro project updated: {name}", f"Changed by {who} in company {company}.",
            f"Project ID: {pid}", f"Occurred at: {output.get('occurred_at')}",
            f"Updated fields: {json.dumps(output.get('updated_fields') or [], ensure_ascii=False)}",
            f"Delivery ID: {output.get('delivery_id')} (use this to identify retries)",
            f"Current project: {json.dumps(record, ensure_ascii=False)}",
            f"To fetch the current project, use get_project with resource_id={pid}; to change it, use update_project with resource_id={pid}."]
        if not record:
            lines.append("The delivery contains no project data; fetch the current project before acting.")
        return {"text": "\n".join(lines), "conversation_key": f"{company}:project:{pid}", "title": f"Project updated: {name}"}

    @staticmethod
    def _check_family(config_data):
        raw = config_data.get("credentials")
        if isinstance(raw, dict) and raw.get("credential_type", FAMILY) != FAMILY:
            raise ValueError("Attach a Houzz Pro access token")

    @classmethod
    def parse_config(cls, config_data):
        cls._check_family(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._check_family(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Houzz Pro access token")
        op = self.config.config
        if isinstance(op, OnProjectUpdatedConfig):
            return self.no_event_output(op.operation)
        token = self.config.credentials.access_token
        method, route, paths, query, body_fields = OPERATIONS[op.operation]
        for field, parameter in paths.items():
            route = route.replace("{" + parameter + "}", quote(getattr(op, field), safe=""))
        params = {parameter: getattr(op, field) for field, parameter in query if getattr(op, field) is not None}
        if isinstance(op, _Page):
            params.update(limit=op.limit, offset=op.offset)
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        kwargs = {"params": params}
        if method != "GET":
            if op.idempotency_key:
                headers["Idempotency-Key"] = op.idempotency_key
            if body_fields:
                kwargs["json"] = {parameter: getattr(op, field) for field, parameter in body_fields if getattr(op, field) is not None}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + route, headers=headers, **kwargs)
        except httpx.RequestError:
            raise ValueError("Houzz Pro request failed; inspect any write before retrying") from None
        expected_status = 201 if op.operation.startswith("create_") else 200
        if response.status_code != expected_status:
            message = "Houzz Pro returned HTTP " + str(response.status_code)
            try:
                error = response.json().get("error")
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message += ": " + error["message"][:2000]
            except (ValueError, AttributeError):
                pass
            raise ValueError(_redact(message, token))
        if len(response.content) > 10_000_000 or response.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
            raise ValueError("Houzz Pro returned an unexpected JSON response; inspect any write before retrying")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Houzz Pro returned invalid JSON; inspect any write before retrying") from None
        if not isinstance(payload, dict) or "data" not in payload or "error" in payload:
            raise ValueError("Houzz Pro did not confirm the operation; inspect any write before retrying")
        result = {"status": "success", "operation": op.operation, "http_status": response.status_code, "data": payload["data"]}
        if isinstance(op, _Page):
            if not isinstance(payload["data"], list) or any(not isinstance(row, dict) for row in payload["data"]):
                raise ValueError("Houzz Pro returned an unexpected page")
            # total is optional in the published contract. Without it, a full page
            # indicates that another page may exist; never claim completeness.
            limit, offset, total = payload.get("limit"), payload.get("offset"), payload.get("total")
            if type(limit) is not int or limit <= 0 or type(offset) is not int or offset < 0 or (total is not None and (type(total) is not int or total < 0)):
                raise ValueError("Houzz Pro returned invalid pagination")
            has_more = offset + len(payload["data"]) < total if total is not None else len(payload["data"]) >= limit
            result.update(limit=limit, offset=offset, total=total, has_more=has_more, next_offset=offset + limit if has_more else None)
        elif not isinstance(payload["data"], dict):
            raise ValueError("Houzz Pro returned an unexpected resource; inspect any write before retrying")
        result = _redact(result, token)
        await self.emit(result)
        return result
