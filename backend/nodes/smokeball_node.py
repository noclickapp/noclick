"""Smokeball US v1 user operations; writes acknowledge asynchronous acceptance.

Routes/DTOs: https://docs.smokeball.com/openapi.json (version 1.0).
No hypermedia link is followed and no write is retried automatically.
"""
from __future__ import annotations
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.oauth.smokeball_oauth import application_api_key
from nodes.scopes.smokeball import SMOKEBALL_SCOPES
from nodes.smokeball_operations import OPERATIONS
from utils.ssrf import guarded_async_client

BASE = "https://api.smokeball.com"


class SmokeballOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Smokeball Account", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "smokeball",
        "x-oauth-scopes": sorted(SMOKEBALL_SCOPES.declared_scopes()),
        "x-credential-url": "https://console.smokeball.com",
        "x-credential-instructions": "Connect your US Smokeball account. The instance administrator must configure the application's client ID, client secret, redirect URI and API key, and obtain production approval for the requested scopes.",
    })
    credential_type: Literal["smokeball_oauth"] = Field("smokeball_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = None
    # Normal OAuth connections use the instance's app key. A credential can
    # also carry its matching app key, including in offline contract fixtures.
    api_key: str | None = Field(None, repr=False, json_schema_extra={"ui:widget": "password", "ui:hidden": True})

    @field_validator("access_token", "refresh_token", "api_key", mode="before")
    @classmethod
    def secret(cls, value):
        if value is None:
            return value
        value = clean_secret(value, field_name="Token")
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste a token without a prefix or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("*", mode="after")
    @classmethod
    def bounded_id(cls, value, info):
        if info.field_name.endswith("_id") and isinstance(value, str):
            if not value or len(value) > 128 or any(c in value for c in "/\\?#%") or any(ord(c) < 33 for c in value) or value in {".", ".."}:
                raise ValueError("Use a single Smokeball resource ID")
        return value


class Page(Input):
    offset: int = Field(0, ge=0, le=2147483647, description="Zero-based Offset; use next_offset from the previous result.")
    limit: int = Field(100, ge=1, le=500, description="Maximum records in this page (1–500).")


class GetFirm(Input):
    operation: Literal["get_firm"] = "get_firm"


class ListStaff(Page):
    operation: Literal["list_staff"] = "list_staff"


class ListMatterTypes(Page):
    operation: Literal["list_matter_types"] = "list_matter_types"


class ListContacts(Page):
    operation: Literal["list_contacts"] = "list_contacts"
    exclude_deleted: bool = True
    updated_since: int | None = Field(None, description="UpdatedSince in .NET UTC ticks.")


class GetContact(Input):
    operation: Literal["get_contact"] = "get_contact"
    contact_id: UUID


class Person(Input):
    first_name: str = Field(..., min_length=1, max_length=500, alias="firstName")
    last_name: str = Field(..., min_length=1, max_length=500, alias="lastName")
    email: str | None = Field(None, max_length=500)
    notes: str | None = Field(None, max_length=100000)


class CreateContact(Input):
    operation: Literal["create_contact"] = "create_contact"
    person: Person = Field(..., description="Person contact details.")
    external_system_id: str | None = Field(None, max_length=500)


class UpdateContact(CreateContact):
    """PUT person details; include all supported details you want to retain."""
    operation: Literal["update_contact"] = "update_contact"
    contact_id: UUID


class ListMatters(Page):
    operation: Literal["list_matters"] = "list_matters"
    contact_id: str | None = None
    last_updated: datetime | None = None
    status: Literal["Open", "Pending", "Closed", "Deleted", "Cancelled"] | None = None


class GetMatter(Input):
    operation: Literal["get_matter"] = "get_matter"
    matter_id: UUID


class CreateMatter(Input):
    operation: Literal["create_matter"] = "create_matter"
    matter_type_id: str
    client_ids: list[str] = Field(..., min_length=1, max_length=100)
    status: Literal["Open", "Pending", "Closed", "Cancelled"] = "Open"
    description: str | None = Field(None, max_length=100000)
    number: str | None = Field(None, max_length=500)
    person_responsible_staff_id: str | None = None


class UpdateMatter(CreateMatter):
    """PUT matter details; supply the desired client, type and status values."""
    operation: Literal["update_matter"] = "update_matter"
    matter_id: UUID


class ListTasks(Page):
    operation: Literal["list_tasks"] = "list_tasks"
    matter_id: str | None = None
    is_completed: bool | None = None
    last_updated: datetime | None = None


class GetTask(Input):
    operation: Literal["get_task"] = "get_task"
    task_id: UUID


class CreateTask(Input):
    operation: Literal["create_task"] = "create_task"
    staff_id: str = Field(..., description="Staff member creating/updating the task.")
    subject: str = Field(..., min_length=1, max_length=2000)
    matter_id: str | None = None
    note: str | None = Field(None, max_length=100000)
    assignee_ids: list[str] | None = Field(None, max_length=100)
    is_completed: bool = False
    completed_by_staff_id: str | None = None
    due_date: datetime | None = Field(None, description="Sent as dueDateOnly; Smokeball uses the date portion.")


class UpdateTask(CreateTask):
    """PUT desired task details, including staff and completion state."""
    operation: Literal["update_task"] = "update_task"
    task_id: UUID


class ListEvents(Page):
    operation: Literal["list_events"] = "list_events"
    matter_id: str | None = None
    from_time: datetime | None = None
    to_time: datetime | None = None
    exclude_deleted: bool = True


class GetEvent(Input):
    operation: Literal["get_event"] = "get_event"
    event_id: UUID


class CreateEvent(Input):
    operation: Literal["create_event"] = "create_event"
    subject: str = Field(..., min_length=1, max_length=2000)
    start_time: datetime
    end_time: datetime
    time_zone: str = Field(..., min_length=1, max_length=100, description="IANA time zone, e.g. America/Chicago.")
    matter_id: str | None = None
    description: str | None = Field(None, max_length=100000)
    location: str | None = Field(None, max_length=2000)
    attendees: list[str] | None = Field(None, max_length=100)
    all_day: bool = False
    non_billable: bool = True

    @field_validator("time_zone")
    @classmethod
    def zone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Use an IANA time zone such as America/Chicago") from None
        return value

    @model_validator(mode="after")
    def times(self):
        if self.start_time.tzinfo != self.end_time.tzinfo or self.end_time < self.start_time:
            raise ValueError("Event end must be at or after start, using matching time zones")
        return self


class ListMemos(Page):
    operation: Literal["list_memos"] = "list_memos"
    matter_id: UUID


class CreateMemo(Input):
    operation: Literal["create_memo"] = "create_memo"
    matter_id: UUID
    title: str = Field(..., min_length=1, max_length=2000)
    text: str = Field(..., max_length=100000, description="Memo content in plain text or RTF.")


OperationConfig = Annotated[Union[GetFirm, ListStaff, ListMatterTypes, ListContacts, GetContact,
    CreateContact, UpdateContact, ListMatters, GetMatter, CreateMatter, UpdateMatter,
    ListTasks, GetTask, CreateTask, UpdateTask, ListEvents, GetEvent, CreateEvent,
    ListMemos, CreateMemo], Field(discriminator="operation")]


class SmokeballNodeConfig(NodeConfig[OperationConfig, SmokeballOAuthCredential]):
    pass


QUERY_FIELDS = {
    "offset": "Offset", "limit": "Limit", "updated_since": "UpdatedSince",
    "contact_id": "ContactId", "matter_id": "MatterId", "last_updated": "LastUpdated",
    "is_completed": "IsCompleted", "status": "Status", "from_time": "From", "to_time": "To",
}
BODY_FIELDS = {
    "external_system_id": "externalSystemId", "matter_type_id": "matterTypeId",
    "client_ids": "clientIds", "person_responsible_staff_id": "personResponsibleStaffId",
    "staff_id": "staffId", "matter_id": "matterId", "assignee_ids": "assigneeIds",
    "is_completed": "isCompleted", "completed_by_staff_id": "completedByStaffId",
    "due_date": "dueDateOnly", "start_time": "startTime", "end_time": "endTime",
    "time_zone": "timeZone", "all_day": "allDay", "non_billable": "nonBillable",
}


class SmokeballNode(WorkflowNode):
    integration_type = "automation-smokeball"
    scope_registry = SMOKEBALL_SCOPES
    connection_evidence = ConnectionEvidence(identity_operation="get_firm", noun="firm", identity_keys=("name", "id"))
    edit_examples = ["Create a Smokeball matter", "List unfinished Smokeball tasks", "Add a memo to this matter"]

    @classmethod
    def get_config_model(cls):
        return SmokeballNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.smokeball_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="smokeball")

    async def _access_token(self, credential):
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.smokeball_oauth import refresh_access_token
        return await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=credential.model_dump(), refresh=refresh_access_token,
            provider="smokeball", caller_path="execute")

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Smokeball account")
        config = self.config.config
        op = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", by_alias=True, exclude_none=True, exclude={"operation"})
        path = op.path
        for key in ("contact_id", "matter_id", "task_id", "event_id"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(values.pop(key), safe=""))
        params, body = {}, None
        if op.method == "GET":
            params = {QUERY_FIELDS[k]: v for k, v in values.items() if k != "exclude_deleted"}
            if "status" in values:
                params["Status"] = [values["status"]]
        else:
            body = {BODY_FIELDS.get(k, k): v for k, v in values.items()}
            if config.operation == "create_event":
                body["type"] = "Normal"
        if isinstance(config, ListContacts):
            params["ExcludeDeletedContacts"] = config.exclude_deleted
        if isinstance(config, ListEvents):
            params["ExcludeDeletedEvents"] = config.exclude_deleted
        headers = {"Authorization": "Bearer " + await self._access_token(credential),
                   "x-api-key": credential.api_key or application_api_key(), "Accept": "application/json"}
        async with guarded_async_client(timeout=30, follow_redirects=False) as client:
            response = await client.request(op.method, BASE + path, params=params, headers=headers,
                                            **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            message = response.text[:4000]
            for secret in (credential.access_token, credential.refresh_token, headers["x-api-key"]):
                message = message.replace(secret, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": message}
        data = response.json() if response.content else None
        result = {"status": "success", "operation": config.operation,
                  "http_status": response.status_code, "data": data}
        if op.method != "GET":
            result.update(accepted=True, completed=False)
        if config.operation.startswith("list_"):
            if not isinstance(data, dict) or data.get("value") is not None and not isinstance(data["value"], list):
                raise ValueError("Smokeball returned an invalid paged collection")
            # Preserve the envelope; continue by offset without following links.
            count = len(data.get("value") or [])
            result["next_offset"] = config.offset + count if data.get("next") and count else None
        return result
