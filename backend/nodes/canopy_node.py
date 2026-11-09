"""Canopy Public API v4: fixed CRM, client note and task operations.

Contract: https://portal.dev.canopytax.com/ (Canopy Public API, version 4).
Each operation makes one request to the published server. Lists return one
page and provider pagination metadata; no pagination URL is followed.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.dev.canopytax.com/public/v4"
RESOURCE_ID = Annotated[str, StringConstraints(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]


class CanopyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Canopy API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://support.getcanopy.com/en/articles/9376222-how-do-i-access-and-use-the-canopy-api",
            "x-credential-instructions": "In Canopy, open Settings > API Management and copy your API key. API access requires Plus or Premium. Paste the key alone. NoClick uses the published Canopy v4 API server and sends it in the x-canopy-api-key header.",
        })
    credential_type: Literal["canopy_api_key"] = Field("canopy_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key alone, without whitespace or a header")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CursorPage(Input):
    limit: int = Field(100, ge=1, le=1000, description="Maximum records in this page.")
    next_cursor: Optional[str] = Field(None, max_length=4096, description="Copy next_cursor from the previous response. Omit for the first page.")


class Email(Input):
    email: str = Field(..., min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    is_primary: bool = False
    type: Literal["PERSONAL", "WORK", "OTHER"] = "WORK"


class ContactEmail(Input):
    # Contact writes use key/value; client writes and contact reads use type/email.
    value: str = Field(..., min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    is_primary: bool = False
    key: Literal["PERSONAL", "WORK", "OTHER"] = "WORK"


class ClientContact(Input):
    id: RESOURCE_ID
    is_primary: bool


class IndividualClient(Input):
    is_business: Literal[False] = False
    name: str = Field(..., min_length=1, max_length=1000)
    contacts: list[ClientContact] = Field(..., min_length=1, max_length=100)
    type: Literal["CLIENT", "PROSPECT", "OTHER"] = "CLIENT"
    emails: Optional[list[Email]] = Field(None, max_length=100)
    external_id: Optional[str] = Field(None, max_length=1000)

    @model_validator(mode="after")
    def primary_contact(self):
        if not any(c.is_primary for c in self.contacts):
            raise ValueError("An individual client needs an existing primary contact")
        return self


class BusinessClient(Input):
    is_business: Literal[True] = True
    name: str = Field(..., min_length=1, max_length=1000)
    business_name: str = Field(..., min_length=1, max_length=1000)
    type: Literal["CLIENT", "PROSPECT", "OTHER"] = "CLIENT"
    emails: Optional[list[Email]] = Field(None, max_length=100)
    external_id: Optional[str] = Field(None, max_length=1000)


class ClientChanges(Input):
    name: Optional[str] = Field(None, min_length=1, max_length=1000)
    business_name: Optional[str] = Field(None, min_length=1, max_length=1000)
    is_active: Optional[bool] = None
    is_archived: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=100000)
    external_id: Optional[str] = Field(None, max_length=1000)
    type: Optional[Literal["CLIENT", "PROSPECT", "OTHER"]] = None
    emails: Optional[list[Email]] = Field(None, max_length=100)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("Provide at least one client change")
        return self


class ContactFields(Input):
    first_name: str = Field(..., min_length=1, max_length=1000)
    last_name: str = Field(..., min_length=1, max_length=1000)
    middle_name: Optional[str] = Field(None, max_length=1000)
    employer: Optional[str] = Field(None, max_length=1000)
    occupation: Optional[str] = Field(None, max_length=1000)
    emails: Optional[list[ContactEmail]] = Field(None, max_length=100)


class ContactChanges(Input):
    first_name: Optional[str] = Field(None, min_length=1, max_length=1000)
    last_name: Optional[str] = Field(None, min_length=1, max_length=1000)
    middle_name: Optional[str] = Field(None, max_length=1000)
    employer: Optional[str] = Field(None, max_length=1000)
    occupation: Optional[str] = Field(None, max_length=1000)
    is_archived: Optional[bool] = None
    emails: Optional[list[ContactEmail]] = Field(None, max_length=100)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("Provide at least one contact change")
        return self


class NoteFields(Input):
    title: str = Field(..., max_length=30000)
    body: str = Field(..., max_length=2000000)


class NoteChanges(Input):
    title: Optional[str] = Field(None, max_length=30000)
    body: Optional[str] = Field(None, max_length=2000000)
    is_archived: Optional[bool] = None
    is_pinned: Optional[bool] = None

    @model_validator(mode="after")
    def one_update(self):
        fields = self.model_dump(exclude_none=True)
        if not fields:
            raise ValueError("Provide a note change")
        if len(fields) > 1 and ({"is_archived", "is_pinned"} & fields.keys()):
            raise ValueError("Update archive or pin separately; Canopy ignores other fields when either is supplied")
        return self


class TaskFields(Input):
    name: str = Field(..., min_length=1, max_length=255, pattern=r"^[^\s]+(\s+[^\s]+)*$")
    status_id: RESOURCE_ID = Field(..., description="Use an ID from List Task Statuses.")
    description: str = Field("", max_length=500000)
    client_id: Optional[int] = Field(None, ge=1)
    priority: Optional[Literal["Low", "Medium", "High"]] = None


class TaskChanges(Input):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    status_id: Optional[RESOURCE_ID] = Field(None, description="Use an ID from List Task Statuses. WITH_CLIENT can re-notify a client on an already sent request.")
    description: Optional[str] = Field(None, max_length=500000)
    client_id: Optional[int] = Field(None, ge=1, description="Can only set a client on a task that has none; an existing client cannot be changed.")
    priority: Optional[Literal["Low", "Medium", "High"]] = None
    budgeted_hours: Optional[float] = Field(None, ge=0, le=99999)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("Provide at least one task change")
        return self


class CanopyListClientsConfig(CursorPage):
    operation: Literal["list_clients"] = Field("list_clients", json_schema_extra={"ui:hidden": True})
    updated_at: Optional[str] = Field(None, max_length=128, description="Provider updated_at filter for incremental sync.")


class CanopySearchClientsConfig(CursorPage):
    operation: Literal["search_clients"] = Field("search_clients", json_schema_extra={"ui:hidden": True})
    q: str = Field(..., min_length=1, max_length=1000)
    query_field: Literal["name", "email", "phone"]


class CanopyGetClientConfig(Input):
    operation: Literal["get_client"] = Field("get_client", json_schema_extra={"ui:hidden": True})
    client_id: RESOURCE_ID


class CanopyCreateClientConfig(Input):
    operation: Literal["create_client"] = Field("create_client", json_schema_extra={"ui:hidden": True})
    client: Annotated[Union[IndividualClient, BusinessClient], Field(discriminator="is_business")]


class CanopyUpdateClientConfig(Input):
    operation: Literal["update_client"] = Field("update_client", json_schema_extra={"ui:hidden": True})
    client_id: RESOURCE_ID
    client: ClientChanges


class CanopyListContactsConfig(CursorPage):
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    updated_at: Optional[str] = Field(None, max_length=128, description="Provider updated_at filter for incremental sync.")


class CanopySearchContactsConfig(CursorPage):
    operation: Literal["search_contacts"] = Field("search_contacts", json_schema_extra={"ui:hidden": True})
    q: str = Field(..., min_length=1, max_length=1000)
    query_field: Literal["name", "email", "phone"]


class CanopyGetContactConfig(Input):
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: RESOURCE_ID


class CanopyCreateContactConfig(Input):
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    contact: ContactFields


class CanopyUpdateContactConfig(Input):
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: RESOURCE_ID
    contact: ContactChanges


class CanopyListClientNotesConfig(Input):
    operation: Literal["list_client_notes"] = Field("list_client_notes", json_schema_extra={"ui:hidden": True})
    client_id: int = Field(..., ge=1)
    limit: int = Field(100, ge=1, le=1000)
    page: int = Field(1, ge=1)
    only_archived: Optional[bool] = None
    only_pinned: Optional[bool] = None


class CanopyGetClientNoteConfig(Input):
    operation: Literal["get_client_note"] = Field("get_client_note", json_schema_extra={"ui:hidden": True})
    client_id: int = Field(..., ge=1)
    note_id: int = Field(..., ge=1)


class CanopyCreateClientNoteConfig(Input):
    operation: Literal["create_client_note"] = Field("create_client_note", json_schema_extra={"ui:hidden": True})
    client_id: int = Field(..., ge=1)
    notes: NoteFields


class CanopyUpdateClientNoteConfig(Input):
    operation: Literal["update_client_note"] = Field("update_client_note", json_schema_extra={"ui:hidden": True})
    client_id: int = Field(..., ge=1)
    note_id: int = Field(..., ge=1)
    notes: NoteChanges


class CanopyListTasksConfig(Input):
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=1000)
    page: int = Field(0, ge=0)
    client_id: Optional[RESOURCE_ID] = None
    name_filter: Optional[str] = Field(None, max_length=1000)
    is_client_request: Optional[bool] = None
    service_type: Literal["generic", "notice", "tax_return"] = "generic"


class CanopyGetTaskConfig(Input):
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"ui:hidden": True})
    task_id: RESOURCE_ID


class CanopyCreateTaskConfig(Input):
    operation: Literal["create_task"] = Field("create_task", json_schema_extra={"ui:hidden": True})
    tasks: TaskFields


class CanopyUpdateTaskConfig(Input):
    operation: Literal["update_task"] = Field("update_task", json_schema_extra={"ui:hidden": True})
    task_id: RESOURCE_ID
    task: TaskChanges = Field(..., title="Task changes", description="Fields are sent directly in the PATCH body, as required by Canopy.")


class CanopyListTaskStatusesConfig(Input):
    operation: Literal["list_task_statuses"] = Field("list_task_statuses", json_schema_extra={"ui:hidden": True})


class CanopyListTaskTagsConfig(Input):
    operation: Literal["list_task_tags"] = Field("list_task_tags", json_schema_extra={"ui:hidden": True})
    sort_count: Optional[Literal["asc", "desc"]] = None
    sort_name: Optional[Literal["asc", "desc"]] = None


class CanopyListTaskTemplatesConfig(Input):
    operation: Literal["list_task_templates"] = Field("list_task_templates", json_schema_extra={"ui:hidden": True})


class CanopyGetTaskTemplateConfig(Input):
    operation: Literal["get_task_template"] = Field("get_task_template", json_schema_extra={"ui:hidden": True})
    template_id: RESOURCE_ID


CanopyConfig = Annotated[Union[
    CanopyListClientsConfig,
    CanopySearchClientsConfig,
    CanopyGetClientConfig,
    CanopyCreateClientConfig,
    CanopyUpdateClientConfig,
    CanopyListContactsConfig,
    CanopySearchContactsConfig,
    CanopyGetContactConfig,
    CanopyCreateContactConfig,
    CanopyUpdateContactConfig,
    CanopyListClientNotesConfig,
    CanopyGetClientNoteConfig,
    CanopyCreateClientNoteConfig,
    CanopyUpdateClientNoteConfig,
    CanopyListTasksConfig,
    CanopyGetTaskConfig,
    CanopyCreateTaskConfig,
    CanopyUpdateTaskConfig,
    CanopyListTaskStatusesConfig,
    CanopyListTaskTagsConfig,
    CanopyListTaskTemplatesConfig,
    CanopyGetTaskTemplateConfig
], Field(discriminator="operation")]


class CanopyFullConfig(NodeConfig[CanopyConfig, CanopyAPIKeyCredential]):
    pass


# method, fixed path, response envelope, expected collection shape
ROUTES = {
    "list_clients": ("GET", "/clients", "clients", list),
    "search_clients": ("GET", "/clients/search", "clients", list),
    "get_client": ("GET", "/clients/{client_id}", "client", dict),
    "create_client": ("POST", "/clients", "client", dict),
    "update_client": ("PATCH", "/clients/{client_id}", "client", dict),
    "list_contacts": ("GET", "/contacts", "contacts", list),
    "search_contacts": ("GET", "/contacts/search", "contacts", list),
    "get_contact": ("GET", "/contacts/{contact_id}", "contact", dict),
    "create_contact": ("POST", "/contacts", "contact", dict),
    "update_contact": ("PATCH", "/contacts/{contact_id}", "contact", dict),
    "list_client_notes": ("GET", "/clients/{client_id}/notes", "notes", list),
    "get_client_note": ("GET", "/clients/{client_id}/notes/{note_id}", "notes", dict),
    "create_client_note": ("POST", "/clients/{client_id}/notes", "notes", dict),
    "update_client_note": ("PATCH", "/clients/{client_id}/notes/{note_id}", "notes", dict),
    "list_tasks": ("GET", "/tasks", "tasks", list),
    "get_task": ("GET", "/tasks/{task_id}", "tasks", dict),
    "create_task": ("POST", "/tasks", "tasks", dict),
    "update_task": ("PATCH", "/tasks/{task_id}", "tasks", dict),
    "list_task_statuses": ("GET", "/task-statuses", "task_statuses", list),
    "list_task_tags": ("GET", "/tasks/tags", "tags", list),
    "list_task_templates": ("GET", "/template-tasks", "template_tasks", list),
    "get_task_template": ("GET", "/template-tasks/{template_id}", "template_tasks", dict),
}


class CanopyNode(WorkflowNode):
    integration_type = "automation-canopy"
    connection_evidence = ConnectionEvidence(noun="Canopy clients", operation="list_clients")

    @classmethod
    def get_config_model(cls):
        return CanopyFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, CanopyFullConfig) or not self.config.credentials:
            raise ValueError("Connect a Canopy API key")
        config, credential = self.config.config, self.config.credentials
        method, path, envelope, shape = ROUTES[config.operation]
        fields = config.model_dump(mode="json", exclude_none=True)
        fields.pop("operation")
        for field in ("client_id", "contact_id", "note_id", "task_id", "template_id"):
            marker = "{" + field + "}"
            if marker in path:
                path = path.replace(marker, quote(str(fields.pop(field)), safe=""))
        params, body = None, None
        if method == "GET":
            params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in fields.items()}
        else:
            body = fields["task"] if config.operation == "update_task" else fields
        # Never retry writes automatically: a timeout may follow a completed write.
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"x-canopy-api-key": credential.api_key, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if response.status_code not in ({201} if method == "POST" else {200}):
            # Preserve provider rejection text for connection evidence, but redact
            # a reflected key. Never expose request headers or transport objects.
            text = response.text[:2000].replace(credential.api_key, "[redacted]")
            return {"status": "error", "http_status": response.status_code,
                "error": f"Canopy HTTP {response.status_code}: {text}"}
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if mime != "application/json" or len(response.content) > 10000000:
            raise ValueError("Canopy returned an unexpected or oversized JSON response")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Canopy returned invalid JSON") from None
        if not isinstance(payload, dict) or not isinstance(payload.get(envelope), shape) or "error" in payload or "errors" in payload:
            raise ValueError("Canopy returned an unexpected response envelope")
        # Keep provider pagination (next_cursor, pagination or next_page) intact.
        # In particular a next_page URL is metadata, never a destination to fetch.
        return {"status": "success", "data": payload, "http_status": response.status_code}
