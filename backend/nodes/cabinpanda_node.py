"""Cabinpanda v0.1.9; contract: https://api.cabinpanda.com/api/docs/swagger.yaml.

Each operation makes one request to the contract's production server.
The contract leaves response bodies unspecified; preserve JSON without guessing envelopes.
"""
from __future__ import annotations
from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://dashboard.cabinpanda.com/api/v1"
DOCS_URL = "https://api.cabinpanda.com/api/docs/swagger.yaml"

class CabinpandaAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Cabinpanda API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://dashboard.cabinpanda.com",
            "x-help-url": DOCS_URL,
            "x-credential-instructions": "In Cabinpanda, open Profile > API and create a token. Paste the token without the Bearer prefix. Connecting reads your forms from the production account."})
    credential_type: Literal["cabinpanda_api_token"] = Field("cabinpanda_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=8192, repr=False, json_schema_extra={"ui:widget": "password"})
    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste only the API token without a Bearer prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class _Form(_Input):
    form_key: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$", description="Form key from List Forms or the Cabinpanda form URL.")

class _Page(_Input):
    page: int = Field(1, ge=1, le=1000000)
    per_page: int = Field(25, ge=1, le=100, description="Page size; request subsequent pages explicitly.")

class ListForms(_Page):
    operation: Literal["list_forms"] = "list_forms"


class GetForm(_Form):
    operation: Literal["get_form"] = "get_form"


class CreateForm(_Input):
    operation: Literal["create_form"] = "create_form"
    name: str = Field(..., min_length=1, max_length=255)
    template_id: int = Field(..., ge=1)
    type_id: int = Field(..., ge=1)


class UpdateForm(_Form):
    operation: Literal["update_form"] = "update_form"
    name: str = Field(..., min_length=1, max_length=255)
    publish: StrictBool | None = None


class DeleteForm(_Form):
    operation: Literal["delete_form"] = "delete_form"


class ListSubmissions(_Form, _Page):
    operation: Literal["list_submissions"] = "list_submissions"
    search: str | None = Field(None, min_length=3, max_length=500)
    start: date | None = None
    finish: date | None = None


class SubmitForm(_Form):
    operation: Literal["submit_form"] = "submit_form"
    fields: dict[str, str] = Field(..., description="Map form field keys to submitted string values. Use an empty object for a form without input fields.")


class DeleteSubmission(_Input):
    operation: Literal["delete_submission"] = "delete_submission"
    submission_id: int = Field(..., ge=1)


class ListFormReceivers(_Form):
    operation: Literal["list_form_receivers"] = "list_form_receivers"


class ListFormTypes(_Input):
    operation: Literal["list_form_types"] = "list_form_types"


class ListFieldTypes(_Input):
    operation: Literal["list_field_types"] = "list_field_types"


class ListTemplates(_Input):
    operation: Literal["list_templates"] = "list_templates"


class ListPublicTemplates(_Input):
    operation: Literal["list_public_templates"] = "list_public_templates"


class CreateTemplate(_Input):
    operation: Literal["create_template"] = "create_template"
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    is_public: StrictBool = False
    variables: dict | None = None


class UpdateTemplate(_Input):
    operation: Literal["update_template"] = "update_template"
    template_id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    is_public: StrictBool = False
    variables: dict | None = None


class SetNotifyRespondent(_Form):
    operation: Literal["set_notify_respondent"] = "set_notify_respondent"
    notify_respondent: StrictBool


class GetRespondentEmailTemplate(_Form):
    operation: Literal["get_respondent_email_template"] = "get_respondent_email_template"


class ListTeamMembers(_Input):
    operation: Literal["list_team_members"] = "list_team_members"


class ListTeams(_Input):
    operation: Literal["list_teams"] = "list_teams"


CabinpandaConfig = Annotated[Union[
    ListForms,
    GetForm,
    CreateForm,
    UpdateForm,
    DeleteForm,
    ListSubmissions,
    SubmitForm,
    DeleteSubmission,
    ListFormReceivers,
    ListFormTypes,
    ListFieldTypes,
    ListTemplates,
    ListPublicTemplates,
    CreateTemplate,
    UpdateTemplate,
    SetNotifyRespondent,
    GetRespondentEmailTemplate,
    ListTeamMembers,
    ListTeams,
], Field(discriminator="operation")]

class CabinpandaFullConfig(NodeConfig[CabinpandaConfig, CabinpandaAPITokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)

ROUTES = {'list_forms': ('GET', '/forms'),
 'get_form': ('GET', '/forms/{form_key}'),
 'create_form': ('POST', '/forms'),
 'update_form': ('PUT', '/forms/{form_key}'),
 'delete_form': ('DELETE', '/forms/{form_key}'),
 'list_submissions': ('GET', '/forms/{form_key}/submissions'),
 'submit_form': ('POST', '/forms/{form_key}/submit'),
 'delete_submission': ('DELETE', '/submissions/{submission_id}'),
 'list_form_receivers': ('GET', '/forms/{form_key}/receivers'),
 'list_form_types': ('GET', '/forms/types'),
 'list_field_types': ('GET', '/forms/field_types'),
 'list_templates': ('GET', '/forms/templates'),
 'list_public_templates': ('GET', '/public-templates'),
 'create_template': ('POST', '/forms/templates'),
 'update_template': ('PATCH', '/forms/templates/{template_id}'),
 'set_notify_respondent': ('PATCH', '/forms/{form_key}/notify-respondent'),
 'get_respondent_email_template': ('GET', '/forms/{form_key}/respondent-email-template'),
 'list_team_members': ('GET', '/team-members'),
 'list_teams': ('GET', '/teams')}
QUERY_FIELDS = {'list_forms': ('page', 'per_page'),
 'list_submissions': ('page', 'per_page', 'search', 'start', 'finish')}
BODY_FIELDS = {'create_form': ('name', 'template_id', 'type_id'),
 'update_form': ('name', 'publish'),
 'submit_form': ('fields',),
 'create_template': ('name', 'description', 'is_public', 'variables'),
 'update_template': ('name', 'description', 'is_public', 'variables'),
 'set_notify_respondent': ('notify_respondent',)}

def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()}
    return value

class CabinpandaNode(WorkflowNode):
    integration_type = "automation-cabinpanda"
    connection_evidence = ConnectionEvidence(noun="forms", operation="list_forms", label_keys=("name", "key", "id"))
    @classmethod
    def get_config_model(cls):
        return CabinpandaFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, CabinpandaFullConfig) or self.config.credentials is None:
            raise ValueError("Attach your Cabinpanda API token")
        config, credential = self.config.config, self.config.credentials
        values = config.model_dump(mode="json", exclude_none=True)
        method, route = ROUTES[config.operation]
        path = route.format(**{key: quote(str(value), safe="") for key, value in values.items()})
        params = {key: values[key] for key in QUERY_FIELDS.get(config.operation, ()) if key in values}
        body_fields = BODY_FIELDS.get(config.operation)
        body = {key: values[key] for key in body_fields if key in values} if body_fields else None
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("Cabinpanda request could not be completed; inspect provider state before retrying a write") from None
        if len(response.content) > 10_000_000:
            raise ValueError("Cabinpanda response exceeds the size limit")
        if not 200 <= response.status_code < 300:
            return _redact({"status": "error", "http_status": response.status_code,
                "error": response.text[:2000] or "Cabinpanda did not confirm the request"}, credential.api_token)
        payload = None
        if response.content:
            if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError("Expected a JSON response from Cabinpanda")
            try:
                payload = response.json()
            except ValueError:
                raise ValueError("Cabinpanda returned invalid JSON") from None
            if isinstance(payload, dict) and (payload.get("success") is False or payload.get("error") or payload.get("errors")):
                return _redact({"status": "error", "http_status": response.status_code, "error": payload}, credential.api_token)
        return _redact({"status": "success", "operation": config.operation,
            "http_status": response.status_code, "data": payload}, credential.api_token)
