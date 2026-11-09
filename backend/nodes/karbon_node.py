"""Karbon v3 practice-management operations using pasted API credentials.
Each operation maps to one published API endpoint and preserves its JSON data.
"""
from __future__ import annotations
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.karbonhq.com"

class KarbonCredential(BaseModel):
    model_config = ConfigDict(title="Karbon API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.karbonhq.com/guides/authentication/",
            "x-credential-instructions": "In Karbon, open Settings → Connected Apps → API Applications → your API application. Paste its Authorization token and tenant AccessKey. Omit the Bearer prefix. Both values are required.",
        })
    credential_type: Literal["karbon_api_key"] = Field("karbon_api_key", json_schema_extra={"ui:hidden": True})
    authorization_token: str = Field(..., min_length=1, title="Authorization Token", repr=False, json_schema_extra={"ui:widget": "password"})
    access_key: str = Field(..., min_length=1, title="AccessKey", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("authorization_token", "access_key", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="Karbon credential")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the credential without a Bearer prefix or whitespace")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class _Page(_Input):
    top: int = Field(100, ge=1, le=100, description="Page size; subsequent pages are not fetched automatically.")
    skip: int = Field(0, ge=0, le=100, description="Documented $skip offset (0–100).")
    filter: str | None = Field(None, description="OData $filter supported by this endpoint.")

class _Key(_Input):
    key: str = Field(..., min_length=1, description="Karbon-generated record key.")

    @field_validator("key")
    @classmethod
    def valid_key(cls, value):
        if value in {".", ".."} or any(c in value for c in "/?#") or any(ord(c) < 33 for c in value):
            raise ValueError("Use one Karbon record key, without path or query components")
        return value

class _ContactFields(_Input):
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    preferred_name: str | None = None
    salutation: str | None = None
    suffix: str | None = None

class _NonemptyPatch(_Input):
    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_dump(exclude={"operation", "key"}, exclude_none=True):
            raise ValueError("Supply at least one field to update")
        return self

class KarbonCreateContact(_ContactFields):
    operation: Literal["create_contact"] = "create_contact"
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    contact_type: str | None = None
    client_owner: str | None = None
    client_manager: str | None = None
    user_defined_identifier: str | None = None

class KarbonUpdateContact(_ContactFields, _Key, _NonemptyPatch):
    operation: Literal["update_contact"] = "update_contact"

class KarbonCreateOrganization(_Input):
    operation: Literal["create_organization"] = "create_organization"
    full_name: str = Field(..., min_length=1)
    contact_type: str | None = None
    client_owner: str | None = None
    client_manager: str | None = None
    user_defined_identifier: str | None = None

class KarbonUpdateOrganization(_Key):
    operation: Literal["update_organization"] = "update_organization"
    full_name: str = Field(..., min_length=1)

class _WorkFields(_Input):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    assignee_email_address: str | None = None
    start_date: datetime | None = None
    due_date: datetime | None = None
    deadline_date: datetime | None = None
    work_type: str | None = None
    primary_status: Literal["Planned", "ReadyToStart", "InProgress", "Waiting", "Completed"] | None = Field(None,
        description="PrimaryStatus without SecondaryStatus clears the existing secondary status.")
    secondary_status: str | None = None

    @model_validator(mode="after")
    def secondary_needs_primary(self):
        if self.secondary_status is not None and self.primary_status is None:
            raise ValueError("Secondary status requires primary status in the same request")
        return self

class KarbonCreateWorkItem(_WorkFields):
    operation: Literal["create_work_item"] = "create_work_item"
    title: str = Field(..., min_length=1, max_length=200)
    assignee_email_address: str = Field(..., min_length=1)
    client_key: str = Field(..., min_length=1)
    client_type: Literal["Contact", "Organization", "ClientGroup"]
    start_date: datetime
    work_template_key: str | None = None

class KarbonUpdateWorkItem(_WorkFields, _Key, _NonemptyPatch):
    operation: Literal["update_work_item"] = "update_work_item"

class KarbonNoteTimeline(_Input):
    entity_type: Literal["WorkItem", "Contact", "Organization", "ClientGroup"]
    entity_key: str = Field(..., min_length=1)

class KarbonCreateNote(_Input):
    operation: Literal["create_note"] = "create_note"
    subject: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1, description="Note body; accepts HTML.")
    author_email_address: str = Field(..., min_length=1)
    assignee_email_address: str | None = None
    due_date: datetime | None = None
    todo_date: datetime | None = None
    timelines: list[KarbonNoteTimeline] = Field(default_factory=list)

class KarbonListContacts(_Page):
    operation: Literal["list_contacts"] = "list_contacts"

class KarbonGetContact(_Key):
    operation: Literal["get_contact"] = "get_contact"

class KarbonListOrganizations(_Page):
    operation: Literal["list_organizations"] = "list_organizations"

class KarbonGetOrganization(_Key):
    operation: Literal["get_organization"] = "get_organization"

class KarbonListWorkItems(_Page):
    operation: Literal["list_work_items"] = "list_work_items"

class KarbonGetWorkItem(_Key):
    operation: Literal["get_work_item"] = "get_work_item"

class KarbonListUsers(_Page):
    operation: Literal["list_users"] = "list_users"

class KarbonGetUser(_Key):
    operation: Literal["get_user"] = "get_user"

class KarbonListWorkTemplates(_Page):
    operation: Literal["list_work_templates"] = "list_work_templates"

class KarbonGetWorkTemplate(_Key):
    operation: Literal["get_work_template"] = "get_work_template"

class KarbonListClientGroups(_Page):
    operation: Literal["list_client_groups"] = "list_client_groups"

class KarbonGetClientGroup(_Key):
    operation: Literal["get_client_group"] = "get_client_group"

class KarbonGetNote(_Key):
    operation: Literal["get_note"] = "get_note"

class KarbonGetTenantSettings(_Input):
    operation: Literal["get_tenant_settings"] = "get_tenant_settings"

KarbonOperation = Annotated[Union[
    KarbonCreateContact,
    KarbonUpdateContact,
    KarbonCreateOrganization,
    KarbonUpdateOrganization,
    KarbonCreateWorkItem,
    KarbonUpdateWorkItem,
    KarbonCreateNote,
    KarbonListContacts,
    KarbonGetContact,
    KarbonListOrganizations,
    KarbonGetOrganization,
    KarbonListWorkItems,
    KarbonGetWorkItem,
    KarbonListUsers,
    KarbonGetUser,
    KarbonListWorkTemplates,
    KarbonGetWorkTemplate,
    KarbonListClientGroups,
    KarbonGetClientGroup,
    KarbonGetNote,
    KarbonGetTenantSettings
], Field(discriminator="operation")]

class KarbonConfig(NodeConfig[KarbonOperation, KarbonCredential]):
    @model_validator(mode="before")
    @classmethod
    def editor_metadata(cls, value):
        if isinstance(value, dict) and isinstance(value.get("config"), dict):
            value = {**value, "config": {k: v for k, v in value["config"].items()
                if k not in {"credentialIds", "key__label"}}}
        return value

OPERATIONS = {'create_contact': ('POST', '/v3/Contacts'), 'update_contact': ('PATCH', '/v3/Contacts/{key}'), 'create_organization': ('POST', '/v3/Organizations'), 'update_organization': ('PATCH', '/v3/Organizations/{key}'), 'create_work_item': ('POST', '/v3/WorkItems'), 'update_work_item': ('PATCH', '/v3/WorkItems/{key}'), 'create_note': ('POST', '/v3/Notes'), 'list_contacts': ('GET', '/v3/Contacts'), 'get_contact': ('GET', '/v3/Contacts/{key}'), 'list_organizations': ('GET', '/v3/Organizations'), 'get_organization': ('GET', '/v3/Organizations/{key}'), 'list_work_items': ('GET', '/v3/WorkItems'), 'get_work_item': ('GET', '/v3/WorkItems/{key}'), 'list_users': ('GET', '/v3/Users'), 'get_user': ('GET', '/v3/Users/{key}'), 'list_work_templates': ('GET', '/v3/WorkTemplates'), 'get_work_template': ('GET', '/v3/WorkTemplates/{key}'), 'list_client_groups': ('GET', '/v3/ClientGroups'), 'get_client_group': ('GET', '/v3/ClientGroups/{key}'), 'get_note': ('GET', '/v3/Notes/{key}'), 'get_tenant_settings': ('GET', '/v3/TenantSettings')}


def _wire_name(name):
    return "".join(part.title() for part in name.split("_"))


def _body(config):
    values = config.model_dump(mode="json", exclude={"key", "operation"}, exclude_none=True)
    result = {_wire_name(k): v for k, v in values.items()}
    if "timelines" in values:
        result["Timelines"] = [{_wire_name(k): v for k, v in row.items()} for row in values["timelines"]]
    return result


class KarbonNode(WorkflowNode):
    integration_type = "automation-karbon"
    connection_evidence = ConnectionEvidence(operation="list_users", noun="Karbon users",
        label_keys=("Name", "EmailAddress", "UserKey"))

    @classmethod
    def get_config_model(cls):
        return KarbonConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect Karbon API credentials")
        method, path = OPERATIONS[config.operation]
        if isinstance(config, _Key):
            path = path.replace("{key}", quote(config.key, safe=""))
        params = {}
        if isinstance(config, _Page):
            params = {"$top": config.top, "$skip": config.skip}
            if config.filter is not None:
                params["$filter"] = config.filter
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + credential.authorization_token,
                    "AccessKey": credential.access_key, "Accept": "application/json"},
                params=params, **({"json": _body(config)} if method != "GET" else {}))
        if response.is_error:
            message = response.text
            for secret in (credential.authorization_token, credential.access_key):
                message = message.replace(secret, "[redacted]")
            raise ValueError(f"Karbon HTTP {response.status_code}: {message[:2000]}")
        if not 200 <= response.status_code < 300:
            raise ValueError(f"Unexpected Karbon HTTP {response.status_code}")
        if response.status_code == 204:
            return {"status": "success", "operation": config.operation, "data": None}
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Expected a Karbon JSON object")
        if "error" in body:
            raise ValueError("Karbon returned an API error")
        result = {"status": "success", "operation": config.operation, "data": body}
        if isinstance(config, _Page):
            rows = body.get("value")
            if not isinstance(rows, list):
                raise ValueError("Expected an OData value array")
            result.update(items=rows, next_page_url=body.get("@odata.nextLink"), total=body.get("@odata.count"))
        return result
