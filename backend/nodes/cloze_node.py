"""Cloze CRM operations using a person's pasted API key.

Each operation sends one request to a fixed, documented endpoint. Provider
error envelopes remain failures even when Cloze returns HTTP 200.
"""
from __future__ import annotations

from datetime import date as Date, datetime as DateTime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class ClozeAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Cloze API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://help.cloze.com/article/2176-api-key",
            "x-credential-instructions": "Paste your Cloze API key from More > Settings > Accounts and Services > API Access. NoClick sends it as a bearer token to api.cloze.com. API availability depends on your Cloze plan and permissions. Cloze requires OAuth for publishing a public integration; this connection uses your own API key.",
        })
    credential_type: Literal["cloze_api_key"] = Field("cloze_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Feed(_Input):
    cursor: str | None = Field(None, description="Cursor returned by the previous feed page. Omit on the initial request.")
    pagesize: int = Field(25, ge=1, le=1000, description="Set on the initial request; Cloze defaults to 10, maximum 1000.")
    modifiedafter: str | None = Field(None, description="Initial request: UTC milliseconds or now; omit to first retrieve all matching records.")
    freeformquery: str | None = None
    segment: str | None = None
    scope: Literal["local", "team"] | None = None



class _Get(_Input):
    id: str = Field(..., min_length=1, description="Cloze syncKey, portableId, unique ID or documented app-link ID.")
    team: bool = False
    format: bool | None = None


class _Delete(_Input):
    id: str = Field(..., min_length=1, description="Identifier of the record to permanently delete.")
    team: bool = False


class _Record(_Input):
    name: str | None = None
    segment: str | None = None
    step: str | None = None
    notes: str | None = None
    keywords: list[str] | None = None
    dryrun: bool = Field(False, description="Validate without creating or updating the record.")


class _Email(_Input):
    value: EmailStr
    work: bool | None = None


class _Person(_Record):
    first: str | None = None
    last: str | None = None
    headline: str | None = None
    stage: Literal["lead", "future", "current", "past", "out"] | None = None
    emails: list[_Email] | None = None


class _Company(_Record):
    description: str | None = None
    domains: list[str] | None = None
    stage: Literal["lead", "future", "current", "past", "out"] | None = None


class _Project(_Record):
    summary: str | None = None
    stage: Literal["future", "current", "pending", "won", "lost"] | None = None
    createdDate: Date | None = Field(None, description="ISO date (YYYY-MM-DD).")
    startDate: Date | None = Field(None, description="ISO date (YYYY-MM-DD).")
    endDate: Date | None = Field(None, description="ISO date (YYYY-MM-DD).")


class ClozeListPeopleConfig(_Feed):
    """List people in Cloze."""
    operation: Literal["list_people"] = Field("list_people", json_schema_extra={"ui:hidden": True})


class ClozeGetPersonConfig(_Get):
    """Get person in Cloze."""
    operation: Literal["get_person"] = Field("get_person", json_schema_extra={"ui:hidden": True})


class ClozeCreatePersonConfig(_Person):
    """Create person in Cloze."""
    operation: Literal["create_person"] = Field("create_person", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)


class ClozeUpdatePersonConfig(_Person):
    """Update person in Cloze."""
    operation: Literal["update_person"] = Field("update_person", json_schema_extra={"ui:hidden": True})
    syncKey: str = Field(..., min_length=1, description="Existing record syncKey returned by Cloze; included with the changes.")


class ClozeDeletePersonConfig(_Delete):
    """Delete person in Cloze."""
    operation: Literal["delete_person"] = Field("delete_person", json_schema_extra={"ui:hidden": True})


class ClozeListCompaniesConfig(_Feed):
    """List companies in Cloze."""
    operation: Literal["list_companies"] = Field("list_companies", json_schema_extra={"ui:hidden": True})


class ClozeGetCompanyConfig(_Get):
    """Get company in Cloze."""
    operation: Literal["get_company"] = Field("get_company", json_schema_extra={"ui:hidden": True})


class ClozeCreateCompanyConfig(_Company):
    """Create company in Cloze."""
    operation: Literal["create_company"] = Field("create_company", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)


class ClozeUpdateCompanyConfig(_Company):
    """Update company in Cloze."""
    operation: Literal["update_company"] = Field("update_company", json_schema_extra={"ui:hidden": True})
    syncKey: str = Field(..., min_length=1, description="Existing record syncKey returned by Cloze; included with the changes.")


class ClozeDeleteCompanyConfig(_Delete):
    """Delete company in Cloze."""
    operation: Literal["delete_company"] = Field("delete_company", json_schema_extra={"ui:hidden": True})


class ClozeListProjectsConfig(_Feed):
    """List projects in Cloze."""
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})


class ClozeGetProjectConfig(_Get):
    """Get project in Cloze."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})


class ClozeCreateProjectConfig(_Project):
    """Create project in Cloze."""
    operation: Literal["create_project"] = Field("create_project", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)


class ClozeUpdateProjectConfig(_Project):
    """Update project in Cloze."""
    operation: Literal["update_project"] = Field("update_project", json_schema_extra={"ui:hidden": True})
    syncKey: str = Field(..., min_length=1, description="Existing record syncKey returned by Cloze; included with the changes.")


class ClozeDeleteProjectConfig(_Delete):
    """Delete project in Cloze."""
    operation: Literal["delete_project"] = Field("delete_project", json_schema_extra={"ui:hidden": True})


class ClozeGetProfileConfig(_Input):
    """Get the account that accepts this API key."""
    operation: Literal["get_profile"] = Field("get_profile", json_schema_extra={"ui:hidden": True})


class ClozeGetTagsConfig(_Input):
    """Get account tags."""
    operation: Literal["get_tags"] = Field("get_tags", json_schema_extra={"ui:hidden": True})


class ClozeGetCustomFieldsConfig(_Input):
    """Get custom field definitions."""
    operation: Literal["get_custom_fields"] = Field("get_custom_fields", json_schema_extra={"ui:hidden": True})


class ClozeGetStepsConfig(_Input):
    """Get configured next steps."""
    operation: Literal["get_steps"] = Field("get_steps", json_schema_extra={"ui:hidden": True})


class ClozeCreateTodoConfig(_Input):
    """Create a task for the current user or an assignee."""
    operation: Literal["create_todo"] = Field("create_todo", json_schema_extra={"ui:hidden": True})
    subject: str = Field(..., min_length=1)
    when: DateTime | None = Field(None, description="ISO date/time for the reminder; omitted means someday.")
    preview: str | None = Field(None, max_length=1024)
    assignee: EmailStr | None = None
    dryrun: bool = False


class ClozeCreateNoteConfig(_Input):
    """Add a note with a stable external ID and source domain."""
    operation: Literal["create_note"] = Field("create_note", json_schema_extra={"ui:hidden": True})
    style: Literal["note"] = Field("note", json_schema_extra={"ui:hidden": True})
    uniqueid: str = Field(..., min_length=1, description="Stable external note identifier.")
    source: str = Field(..., min_length=1, description="Source domain, for example example.org.")
    subject: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    bodytype: Literal["text", "html"] = "text"
    date: DateTime | None = Field(None, description="ISO date/time for the timeline entry.")
    dryrun: bool = False


ClozeConfig = Annotated[Union[
    ClozeListPeopleConfig,
    ClozeGetPersonConfig,
    ClozeCreatePersonConfig,
    ClozeUpdatePersonConfig,
    ClozeDeletePersonConfig,
    ClozeListCompaniesConfig,
    ClozeGetCompanyConfig,
    ClozeCreateCompanyConfig,
    ClozeUpdateCompanyConfig,
    ClozeDeleteCompanyConfig,
    ClozeListProjectsConfig,
    ClozeGetProjectConfig,
    ClozeCreateProjectConfig,
    ClozeUpdateProjectConfig,
    ClozeDeleteProjectConfig,
    ClozeGetProfileConfig,
    ClozeGetTagsConfig,
    ClozeGetCustomFieldsConfig,
    ClozeGetStepsConfig,
    ClozeCreateTodoConfig,
    ClozeCreateNoteConfig
], Field(discriminator="operation")]


class ClozeFullConfig(NodeConfig[ClozeConfig, ClozeAPIKeyCredential]):
    pass


ROUTES = {
    'list_people': ('GET', '/v1/people/feed'),
    'get_person': ('GET', '/v1/people/get'),
    'create_person': ('POST', '/v1/people/create'),
    'update_person': ('POST', '/v1/people/update'),
    'delete_person': ('DELETE', '/v1/people/delete'),
    'list_companies': ('GET', '/v1/companies/feed'),
    'get_company': ('GET', '/v1/companies/get'),
    'create_company': ('POST', '/v1/companies/create'),
    'update_company': ('POST', '/v1/companies/update'),
    'delete_company': ('DELETE', '/v1/companies/delete'),
    'list_projects': ('GET', '/v1/projects/feed'),
    'get_project': ('GET', '/v1/projects/get'),
    'create_project': ('POST', '/v1/projects/create'),
    'update_project': ('POST', '/v1/projects/update'),
    'delete_project': ('DELETE', '/v1/projects/delete'),
    'get_profile': ('GET', '/v1/user/profile'),
    'get_tags': ('GET', '/v1/user/keywords'),
    'get_custom_fields': ('GET', '/v1/user/fields'),
    'get_steps': ('GET', '/v1/user/steps'),
    'create_todo': ('POST', '/v1/timeline/todo/create'),
    'create_note': ('POST', '/v1/timeline/content/create'),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items() if k.lower() not in {"api_key", "access_token", "refresh_token", "authorization"}}
    return value


class ClozeNode(WorkflowNode):
    integration_type = "automation-cloze"
    connection_evidence = ConnectionEvidence(noun="Cloze account", identity_operation="get_profile")

    @classmethod
    def get_config_model(cls):
        return ClozeFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect your Cloze API key")
        op = self.config.config
        credential = self.config.credentials
        method, path = ROUTES[op.operation]
        payload = op.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        params = None if method == "POST" else {k: str(v).lower() if isinstance(v, bool) else v for k, v in payload.items()}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://api.cloze.com" + path,
                    headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"},
                    params=params, **({"json": payload} if method == "POST" else {}))
        except httpx.RequestError:
            return {"status": "error", "error": "Cloze request could not be completed; inspect Cloze before retrying a write"}
        try:
            body = response.json()
        except ValueError:
            return {"status": "error", "status_code": response.status_code, "error": "Cloze returned a non-JSON response"}
        if not isinstance(body, dict) or not isinstance(body.get("errorcode"), (int, float)) or isinstance(body.get("errorcode"), bool):
            return {"status": "error", "status_code": response.status_code, "error": "Cloze returned an unexpected response envelope"}
        body = _redact(body, credential.api_key)
        if not 200 <= response.status_code < 300 or body["errorcode"] != 0:
            message = body.get("message")
            return {"status": "error", "status_code": response.status_code, "errorcode": body["errorcode"],
                "error": message if isinstance(message, str) and message else "Cloze rejected the request"}
        if op.operation == "get_profile":
            profile = body.get("profile")
            if not isinstance(profile, dict) or not any(isinstance(profile.get(k), str) and profile[k].strip() for k in ("email", "name")):
                return {"status": "error", "error": "Cloze returned no recognizable account profile"}
        return {**body, "status": "success"}
