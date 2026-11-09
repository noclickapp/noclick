"""Assembly.com client portal automation using the published v1 API.

Each operation performs one documented request. Lists return one page and the
opaque nextToken; tasks require the workspace's Tasks app. No automatic retries
are made, so a timed-out write must be inspected before it is repeated.
Contract: https://assembly.com/docs/api-reference/openapi.json
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, AwareDatetime, EmailStr, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.assembly.com"
CREDENTIAL_TYPE = "assemblycom_api_key"

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]
Text = Annotated[str, StringConstraints(min_length=1, max_length=1000)]
UUIDText = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")]


def picker(field):
    return {"x-dynamic-options": {"field_name": field, "allow_custom": True,
        "searchable": False, "placeholder": "Choose a resource", "custom_placeholder": "Paste the Assembly ID"}}


class AssemblyComAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Assembly.com API Key",
        json_schema_extra={"x-credential-url": "https://assembly.com/docs/api-reference/introduction",
            "x-credential-instructions": "In your Assembly workspace, copy an API key and paste it here. NoClick sends it in the X-API-KEY header to api.assembly.com. Use a key with permissions for your selected actions; Tasks operations also need the Tasks app installed."})
    credential_type: Literal["assemblycom_api_key"] = Field("assemblycom_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(20, ge=1, le=100, strict=True, description="Return one page, up to 100 items. Pass nextToken from the previous response for the next page.")
    nextToken: str | None = Field(None, max_length=8192, description="Opaque cursor returned by Assembly; leave empty for the first page.")


class Address(_Input):
    addressLine1: str | None = None
    addressLine2: str | None = None
    city: str | None = None
    country: str | None = None
    fullAddress: str | None = None
    postalCode: str | None = None
    region: str | None = None


CustomFields = dict[str, str | list[str] | Address | None]


class _TaskFields(_Input):
    name: Text | None = None
    description: str | None = Field(None, max_length=100000)
    status: Literal["todo", "inProgress", "completed"] | None = None
    dueDate: AwareDatetime | None = None
    clientId: Identifier | None = Field(None, json_schema_extra=picker("client_id"))
    companyId: Identifier | None = Field(None, json_schema_extra=picker("company_id"))
    internalUserId: Identifier | None = None
    parentTaskId: Identifier | None = Field(None, json_schema_extra=picker("task_id"))
    isArchived: bool | None = None

    @model_validator(mode="after")
    def assignment(self):
        if self.clientId and not self.companyId:
            raise ValueError("Set companyId when assigning a task to a client")
        return self


class AssemblyComGetCurrentUserConfig(_Input):
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})


class AssemblyComListClientsConfig(_Page):
    operation: Literal["list_clients"] = Field("list_clients", json_schema_extra={"ui:hidden": True})
    companyId: Identifier | None = Field(None, json_schema_extra=picker("company_id"))
    givenName: Text | None = None
    familyName: Text | None = None
    email: EmailStr | None = None


class AssemblyComGetClientConfig(_Input):
    operation: Literal["get_client"] = Field("get_client", json_schema_extra={"ui:hidden": True})
    client_id: Identifier = Field(..., json_schema_extra=picker("client_id"))


class AssemblyComCreateClientConfig(_Input):
    operation: Literal["create_client"] = Field("create_client", json_schema_extra={"ui:hidden": True})
    givenName: Text
    familyName: Text
    companyId: UUIDText = Field(..., description="Company association required by Assembly", json_schema_extra=picker("company_id"))
    email: EmailStr | None = Field(None, description="Required unless your workspace allows clients without an email")
    customFields: CustomFields | None = None
    sendInvite: bool = Field(False, description="Explicitly send the client an invitation email")


class AssemblyComUpdateClientConfig(_Input):
    operation: Literal["update_client"] = Field("update_client", json_schema_extra={"ui:hidden": True})
    client_id: Identifier = Field(..., json_schema_extra=picker("client_id"))
    givenName: Text | None = None
    familyName: Text | None = None
    companyId: UUIDText | None = Field(None, json_schema_extra=picker("company_id"))
    email: EmailStr | None = Field(None, description="Only adds a first email; cannot change an existing email")
    customFields: CustomFields | None = None
    status: Literal["archived", "active"] | None = Field(None, description="Archive or restore, sent alone without other profile edits")
    sendInvite: bool = Field(False, description="Explicitly send or resend an invitation email")

    @model_validator(mode="after")
    def status_alone(self):
        if self.status is not None and (self.sendInvite or any(getattr(self, k) is not None for k in ("givenName", "familyName", "companyId", "email", "customFields"))):
            raise ValueError("Send status alone to archive or restore a client")
        return self


class AssemblyComListCompaniesConfig(_Page):
    operation: Literal["list_companies"] = Field("list_companies", json_schema_extra={"ui:hidden": True})
    name: Text | None = None
    isPlaceholder: bool | None = None


class AssemblyComGetCompanyConfig(_Input):
    operation: Literal["get_company"] = Field("get_company", json_schema_extra={"ui:hidden": True})
    company_id: Identifier = Field(..., json_schema_extra=picker("company_id"))


class AssemblyComCreateCompanyConfig(_Input):
    operation: Literal["create_company"] = Field("create_company", json_schema_extra={"ui:hidden": True})
    name: Text
    customFields: CustomFields | None = None
    isPlaceholder: bool | None = None
    fallbackColor: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")


class AssemblyComUpdateCompanyConfig(_Input):
    operation: Literal["update_company"] = Field("update_company", json_schema_extra={"ui:hidden": True})
    company_id: Identifier = Field(..., json_schema_extra=picker("company_id"))
    name: Text | None = None
    customFields: CustomFields | None = None


class AssemblyComListTasksConfig(_Page):
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"ui:hidden": True})
    createdBy: Identifier | None = None
    parentTaskId: Identifier | None = None
    status: Literal["todo", "inProgress", "completed"] | None = None
    clientId: Identifier | None = Field(None, json_schema_extra=picker("client_id"))
    internalUserId: Identifier | None = None
    companyId: Identifier | None = Field(None, json_schema_extra=picker("company_id"))


class AssemblyComGetTaskConfig(_Input):
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"ui:hidden": True})
    task_id: Identifier = Field(..., json_schema_extra=picker("task_id"))


class AssemblyComCreateTaskConfig(_TaskFields):
    operation: Literal["create_task"] = Field("create_task", json_schema_extra={"ui:hidden": True})
    name: Text
    templateId: Identifier | None = None


class AssemblyComUpdateTaskConfig(_TaskFields):
    operation: Literal["update_task"] = Field("update_task", json_schema_extra={"ui:hidden": True})
    task_id: Identifier = Field(..., json_schema_extra=picker("task_id"))


class AssemblyComDeleteTaskConfig(_Input):
    operation: Literal["delete_task"] = Field("delete_task", json_schema_extra={"ui:hidden": True})
    task_id: Identifier = Field(..., json_schema_extra=picker("task_id"))


class AssemblyComListNotesConfig(_Page):
    operation: Literal["list_notes"] = Field("list_notes", json_schema_extra={"ui:hidden": True})
    entityId: Identifier | None = None
    entityType: Literal["client", "company"] | None = None

    @model_validator(mode="after")
    def paired_entity(self):
        if bool(self.entityId) != bool(self.entityType):
            raise ValueError("Supply both entityId and entityType to filter notes")
        return self


class AssemblyComGetNoteConfig(_Input):
    operation: Literal["get_note"] = Field("get_note", json_schema_extra={"ui:hidden": True})
    note_id: Identifier = Field(..., json_schema_extra=picker("note_id"))


class AssemblyComCreateNoteConfig(_Input):
    operation: Literal["create_note"] = Field("create_note", json_schema_extra={"ui:hidden": True})
    entityId: Identifier
    entityType: Literal["client", "company"]
    title: Text
    content: str | None = Field(None, max_length=100000)


class AssemblyComUpdateNoteConfig(_Input):
    operation: Literal["update_note"] = Field("update_note", json_schema_extra={"ui:hidden": True})
    note_id: Identifier = Field(..., json_schema_extra=picker("note_id"))
    title: Text | None = None
    content: str | None = Field(None, max_length=100000)


class AssemblyComDeleteNoteConfig(_Input):
    operation: Literal["delete_note"] = Field("delete_note", json_schema_extra={"ui:hidden": True})
    note_id: Identifier = Field(..., json_schema_extra=picker("note_id"))


class AssemblyComListMessageChannelsConfig(_Page):
    operation: Literal["list_message_channels"] = Field("list_message_channels", json_schema_extra={"ui:hidden": True})
    clientId: Identifier | None = Field(None, json_schema_extra=picker("client_id"))
    companyId: Identifier | None = Field(None, json_schema_extra=picker("company_id"))
    membershipEntityId: Identifier | None = None
    memberId: Identifier | None = None
    membershipType: Literal["company", "individual", "group"] | None = None
    includeUnread: bool | None = None


class AssemblyComCreateMessageChannelConfig(_Input):
    operation: Literal["create_message_channel"] = Field("create_message_channel", json_schema_extra={"ui:hidden": True})
    membershipType: Literal["company", "individual", "group"]
    membershipEntityId: Identifier | None = None
    clientId: Identifier | None = Field(None, json_schema_extra=picker("client_id"))
    companyId: Identifier | None = Field(None, json_schema_extra=picker("company_id"))
    memberIds: list[Identifier] | None = Field(None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def members(self):
        if self.membershipType == "group" and not self.memberIds:
            raise ValueError("Group channels require memberIds")
        if self.membershipType == "company" and not (self.membershipEntityId or self.companyId):
            raise ValueError("Company channels require companyId or membershipEntityId")
        if self.membershipType == "individual" and not (self.membershipEntityId or self.clientId):
            raise ValueError("Individual channels require clientId or membershipEntityId")
        return self


class AssemblyComListMessagesConfig(_Page):
    operation: Literal["list_messages"] = Field("list_messages", json_schema_extra={"ui:hidden": True})
    channelId: UUIDText = Field(..., description="Bare channel UUID without the messaging: prefix", json_schema_extra=picker("channel_id"))


class AssemblyComSendMessageConfig(_Input):
    operation: Literal["send_message"] = Field("send_message", json_schema_extra={"ui:hidden": True})
    channelId: UUIDText = Field(..., json_schema_extra=picker("channel_id"))
    text: str = Field(..., min_length=1, max_length=5000)
    senderId: UUIDText | None = Field(None, description="Optional channel member UUID; leave empty to use the authenticated user")


AssemblyComConfig = Annotated[Union[
    AssemblyComGetCurrentUserConfig,
    AssemblyComListClientsConfig,
    AssemblyComGetClientConfig,
    AssemblyComCreateClientConfig,
    AssemblyComUpdateClientConfig,
    AssemblyComListCompaniesConfig,
    AssemblyComGetCompanyConfig,
    AssemblyComCreateCompanyConfig,
    AssemblyComUpdateCompanyConfig,
    AssemblyComListTasksConfig,
    AssemblyComGetTaskConfig,
    AssemblyComCreateTaskConfig,
    AssemblyComUpdateTaskConfig,
    AssemblyComDeleteTaskConfig,
    AssemblyComListNotesConfig,
    AssemblyComGetNoteConfig,
    AssemblyComCreateNoteConfig,
    AssemblyComUpdateNoteConfig,
    AssemblyComDeleteNoteConfig,
    AssemblyComListMessageChannelsConfig,
    AssemblyComCreateMessageChannelConfig,
    AssemblyComListMessagesConfig,
    AssemblyComSendMessageConfig
], Field(discriminator="operation")]


class AssemblyComFullConfig(NodeConfig[AssemblyComConfig, AssemblyComAPIKeyCredential]):
    pass


# Explicit, bounded routes: no arbitrary URL, method or body operation.
ROUTES = {
    'get_current_user': ('GET', '/v1/me', None, ()),
    'list_clients': ('GET', '/v1/clients', None, ('limit', 'nextToken', 'companyId', 'givenName', 'familyName', 'email')),
    'get_client': ('GET', '/v1/clients/{id}', 'client_id', ()),
    'create_client': ('POST', '/v1/clients', None, ('sendInvite',)),
    'update_client': ('PATCH', '/v1/clients/{id}', 'client_id', ('sendInvite',)),
    'list_companies': ('GET', '/v1/companies', None, ('limit', 'nextToken', 'name', 'isPlaceholder')),
    'get_company': ('GET', '/v1/companies/{id}', 'company_id', ()),
    'create_company': ('POST', '/v1/companies', None, ()),
    'update_company': ('PATCH', '/v1/companies/{id}', 'company_id', ()),
    'list_tasks': ('GET', '/v1/tasks', None, ('limit', 'nextToken', 'createdBy', 'parentTaskId', 'status', 'clientId', 'internalUserId', 'companyId')),
    'get_task': ('GET', '/v1/tasks/{id}', 'task_id', ()),
    'create_task': ('POST', '/v1/tasks', None, ()),
    'update_task': ('PATCH', '/v1/tasks/{id}', 'task_id', ()),
    'delete_task': ('DELETE', '/v1/tasks/{id}', 'task_id', ()),
    'list_notes': ('GET', '/v1/notes', None, ('limit', 'nextToken', 'entityId', 'entityType')),
    'get_note': ('GET', '/v1/notes/{id}', 'note_id', ()),
    'create_note': ('POST', '/v1/notes', None, ()),
    'update_note': ('PATCH', '/v1/notes/{id}', 'note_id', ()),
    'delete_note': ('DELETE', '/v1/notes/{id}', 'note_id', ()),
    'list_message_channels': ('GET', '/v1/message-channels', None, ('limit', 'nextToken', 'clientId', 'companyId', 'membershipEntityId', 'memberId', 'membershipType', 'includeUnread')),
    'create_message_channel': ('POST', '/v1/message-channels', None, ()),
    'list_messages': ('GET', '/v1/messages', None, ('limit', 'nextToken', 'channelId')),
    'send_message': ('POST', '/v1/messages', None, ()),
}
PICKERS = {"client_id": "list_clients", "company_id": "list_companies",
    "task_id": "list_tasks", "note_id": "list_notes", "channel_id": "list_message_channels"}


class AssemblyComNode(WorkflowNode):
    integration_type = "automation-assemblycom"
    connection_evidence = ConnectionEvidence(noun="Assembly clients", field="client_id",
        identity_operation="get_current_user", label_keys=("name", "email", "id"),
        identity_keys=("email", "givenName", "id"))

    @classmethod
    def get_config_model(cls):
        return AssemblyComFullConfig

    @staticmethod
    def _config_view(data):
        if not isinstance(data.get("config"), dict):
            return data
        # Picker labels and credential attachments belong to the editor, not
        # the provider request. All other unknown operation fields still fail.
        labels = {field + "__label" for field in (*PICKERS, "companyId", "clientId", "parentTaskId", "channelId")}
        return {**data, "config": {k: v for k, v in data["config"].items()
            if k != "credentialIds" and k not in labels}}

    @classmethod
    def parse_config(cls, config_data):
        return super().parse_config(cls._config_view(config_data))

    @classmethod
    def validate_config(cls, config_data):
        return super().validate_config(cls._config_view(config_data))

    @staticmethod
    def _redact(value, key):
        if isinstance(value, str):
            return value.replace(key, "[redacted]")
        if isinstance(value, list):
            return [AssemblyComNode._redact(item, key) for item in value]
        if isinstance(value, dict):
            return {AssemblyComNode._redact(k, key): AssemblyComNode._redact(v, key) for k, v in value.items()}
        return value

    @classmethod
    async def _perform(cls, op, credential):
        method, route, identifier, query_fields = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        values.pop("operation")
        if identifier:
            route = route.replace("{id}", quote(values.pop(identifier), safe=""))
        params = {field: values.pop(field) for field in query_fields if field in values}
        # Assembly treats status as an exclusive archive/restore action.
        if op.operation == "update_client" and op.status is not None:
            params.pop("sendInvite", None)
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        if method in {"POST", "PATCH"} and not values:
            raise ValueError("Provide at least one field to write")
        key = credential.api_key
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + route, params=params,
                headers={"X-API-KEY": key, "Accept": "application/json"},
                **({"json": values} if method in {"POST", "PATCH"} else {}))
        if response.status_code != 200:
            # Keep provider rejections recognisable by the shared connect seam.
            message = "Assembly request failed"
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = str(error.get("message") or error.get("error") or message)[:1000]
            except ValueError:
                message = response.text[:1000] or message
            raise ValueError(cls._redact(f"Assembly HTTP {response.status_code}: {message}", key))
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if mime != "application/json" or len(response.content) > 10_000_000:
            raise ValueError("Expected a bounded Assembly JSON response")
        body = response.json()
        if not isinstance(body, dict) or "error" in body or "errors" in body:
            raise ValueError("Unexpected Assembly response")
        if op.operation == "get_current_user" and (not isinstance(body.get("id"), str) or not body["id"]):
            raise ValueError("Assembly did not return the API key owner's identity")
        if op.operation.startswith("list_"):
            items = body.get("data")
            # The published list schema permits null for an empty result.
            if items is None and "data" in body:
                items = []
            if not isinstance(items, list):
                raise ValueError("Expected Assembly list data")
            token = body.get("nextToken")
            if token is not None and not isinstance(token, str):
                raise ValueError("Expected an opaque Assembly pagination cursor")
            result = {"status": "success", "data": items, "nextToken": token or None,
                "has_more": bool(token), "http_status": 200}
        else:
            result = {"status": "success", "data": body, "http_status": 200}
        return cls._redact(result, key)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Assembly.com API key")
        try:
            return await self._perform(self.config.config, self.config.credentials)
        except httpx.HTTPError:
            raise ValueError("Assembly transport failed; inspect any write before retrying") from None

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        if field_name not in PICKERS:
            raise ValueError("Unknown Assembly resource picker")
        if search:
            raise ValueError("Choose from the current page or paste an Assembly ID")
        credential = AssemblyComAPIKeyCredential.model_validate(credential_data)
        config = {"operation": PICKERS[field_name], "limit": 100}
        if page_token:
            config["nextToken"] = page_token
        parsed = cls.parse_config({"config": config, "credentials": credential.model_dump()})
        result = await cls._perform(parsed.config, credential)
        options = []
        for row in result["data"]:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                continue
            label = row.get("name") or row.get("title") or " ".join(str(row.get(k) or "") for k in ("givenName", "familyName")).strip() or row.get("email") or row["id"]
            options.append({"value": row["id"], "label": label})
        return {"options": options, "next_page_token": result["nextToken"]}
