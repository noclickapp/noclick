"""OnePageCRM v3: single-request CRM operations using a person's API credentials.

Contract: https://raw.githubusercontent.com/OnePageCRM/swagger/master/swagger.yaml
Partial PUTs: https://developer.onepagecrm.com/api/partial-updates/
List operations return one explicit page; no hidden writes or automatic retries.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.onepagecrm.com/api/v3"
CREDENTIAL = "onepage_crm_api_key"
ResourceID = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]
DateValue = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class OnePageCRMAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="OnePageCRM API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.onepagecrm.com/app/api",
            "x-credential-instructions": "Open OnePageCRM Settings > API > Configuration and copy your User ID and API key. Paste both values below. The API key grants access to your account; NoClick sends it only to app.onepagecrm.com using HTTP Basic authentication.",
            "x-help-url": "https://developer.onepagecrm.com/api/authentication/",
        })
    credential_type: Literal["onepage_crm_api_key"] = Field("onepage_crm_api_key", json_schema_extra={"ui:hidden": True})
    user_id: ResourceID = Field(..., title="User ID", description="User ID from the API Configuration tab.")
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without whitespace or an authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def dates(self):
        for key in ("date", "expected_close_date", "close_date"):
            value = getattr(self, key, None)
            if value is not None:
                date.fromisoformat(value)
        return self


class _Page(_Input):
    page: int = Field(1, ge=1, le=1000000, description="Page number, starting at 1. Use next_page from the previous result.")
    per_page: int = Field(10, ge=1, le=100, description="Records per page, at most 100.")


class ContactEmail(_Input):
    type: Literal["work", "home", "other"] = "work"
    value: str = Field(..., min_length=1, max_length=320)


class ContactPhone(_Input):
    type: Literal["work", "mobile", "home", "direct", "fax", "company", "other"] = "work"
    value: str = Field(..., min_length=1, max_length=100)


class _ContactFields(_Input):
    first_name: str | None = Field(None, max_length=25)
    last_name: str | None = Field(None, max_length=25)
    company_name: str | None = Field(None, max_length=55)
    job_title: str | None = Field(None, max_length=1000)
    background: str | None = Field(None, max_length=10240)
    owner_id: ResourceID | None = None
    status_id: ResourceID | None = None
    lead_source_id: ResourceID | None = None
    starred: bool | None = None
    emails: list[ContactEmail] | None = Field(None, max_length=100, description="Replaces all email addresses when supplied, even on partial updates.")
    phones: list[ContactPhone] | None = Field(None, max_length=100, description="Replaces all phone numbers when supplied.")
    tags: list[str] | None = Field(None, max_length=100, description="Replaces all tags when supplied; an empty list clears them.")


class _ActionFields(_Input):
    assignee_id: ResourceID | None = None
    text: str | None = Field(None, min_length=1, max_length=140)
    status: Literal["asap", "date", "date_time", "waiting", "queued", "queued_with_date", "done"] | None = None
    date: DateValue | None = None
    exact_time: int | None = Field(None, ge=0)
    position: int | None = Field(None, ge=0)


class _DealFields(_Input):
    name: str | None = Field(None, min_length=1, max_length=60)
    text: str | None = Field(None, max_length=7168)
    owner_id: ResourceID | None = None
    pipeline_id: ResourceID | None = None
    stage: int | None = None
    status: Literal["pending", "won", "lost"] | None = None
    amount: float | None = Field(None, allow_inf_nan=False)
    months: int | None = Field(None, ge=1)
    expected_close_date: DateValue | None = None
    close_date: DateValue | None = None


class _NoteFields(_Input):
    text: str | None = Field(None, min_length=1, max_length=7168)
    date: DateValue | None = None
    linked_deal_id: ResourceID | None = None

    @field_validator("linked_deal_id", mode="before")
    @classmethod
    def optional_link(cls, value):
        # Provider examples use an empty string for no linked deal.
        return None if value == "" else value


class OnePageCRMListContactsConfig(_Page):
    """List contacts in OnePageCRM."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, max_length=1000)
    email: str | None = Field(None, max_length=320)
    tag: str | None = Field(None, max_length=1000)

class OnePageCRMGetContactConfig(_Input):
    """Get a contact in OnePageCRM."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: ResourceID = Field(..., description="OnePageCRM contact ID.")

class OnePageCRMCreateContactConfig(_ContactFields):
    """Create a contact in OnePageCRM."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def name_required(self):
        if not (self.last_name and self.last_name.strip()) and not (self.company_name and self.company_name.strip()):
            raise ValueError("Supply a last name or company name")
        return self

class OnePageCRMUpdateContactConfig(_ContactFields):
    """Update a contact in OnePageCRM."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: ResourceID = Field(..., description="OnePageCRM contact ID.")

    @model_validator(mode="after")
    def changes_required(self):
        if not any(value is not None for key, value in self.model_dump().items() if key not in {"operation", "contact_id"}):
            raise ValueError("Supply at least one field to update")
        return self

class OnePageCRMDeleteContactConfig(_Input):
    """Delete a contact in OnePageCRM."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})
    contact_id: ResourceID = Field(..., description="OnePageCRM contact ID.")

class OnePageCRMListActionsConfig(_Page):
    """List actions in OnePageCRM."""
    operation: Literal["list_actions"] = Field("list_actions", json_schema_extra={"ui:hidden": True})
    contact_id: ResourceID | None = None
    done: bool | None = None
    assignee_id: ResourceID | None = None

class OnePageCRMGetActionConfig(_Input):
    """Get a action in OnePageCRM."""
    operation: Literal["get_action"] = Field("get_action", json_schema_extra={"ui:hidden": True})
    action_id: ResourceID = Field(..., description="OnePageCRM action ID.")

class OnePageCRMCreateActionConfig(_ActionFields):
    """Create a action in OnePageCRM."""
    operation: Literal["create_action"] = Field("create_action", json_schema_extra={"ui:hidden": True})
    contact_id: ResourceID
    text: str = Field(..., min_length=1, max_length=140)

class OnePageCRMUpdateActionConfig(_ActionFields):
    """Update a action in OnePageCRM."""
    operation: Literal["update_action"] = Field("update_action", json_schema_extra={"ui:hidden": True})
    action_id: ResourceID = Field(..., description="OnePageCRM action ID.")
    done: bool | None = Field(None, description="Mark this action complete via the documented done query parameter.")

    @model_validator(mode="after")
    def changes_required(self):
        if not any(value is not None for key, value in self.model_dump().items() if key not in {"operation", "action_id"}):
            raise ValueError("Supply at least one field to update")
        return self

class OnePageCRMDeleteActionConfig(_Input):
    """Delete a action in OnePageCRM."""
    operation: Literal["delete_action"] = Field("delete_action", json_schema_extra={"ui:hidden": True})
    action_id: ResourceID = Field(..., description="OnePageCRM action ID.")

class OnePageCRMListDealsConfig(_Page):
    """List deals in OnePageCRM."""
    operation: Literal["list_deals"] = Field("list_deals", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, max_length=1000)
    contact_id: ResourceID | None = None
    status: Literal["pending", "won", "lost", "closed"] | None = None
    pipeline_id: ResourceID | None = None

class OnePageCRMGetDealConfig(_Input):
    """Get a deal in OnePageCRM."""
    operation: Literal["get_deal"] = Field("get_deal", json_schema_extra={"ui:hidden": True})
    deal_id: ResourceID = Field(..., description="OnePageCRM deal ID.")

class OnePageCRMCreateDealConfig(_DealFields):
    """Create a deal in OnePageCRM."""
    operation: Literal["create_deal"] = Field("create_deal", json_schema_extra={"ui:hidden": True})
    contact_id: ResourceID
    name: str = Field(..., min_length=1, max_length=60)

class OnePageCRMUpdateDealConfig(_DealFields):
    """Update a deal in OnePageCRM."""
    operation: Literal["update_deal"] = Field("update_deal", json_schema_extra={"ui:hidden": True})
    deal_id: ResourceID = Field(..., description="OnePageCRM deal ID.")

    @model_validator(mode="after")
    def changes_required(self):
        if not any(value is not None for key, value in self.model_dump().items() if key not in {"operation", "deal_id"}):
            raise ValueError("Supply at least one field to update")
        return self

class OnePageCRMDeleteDealConfig(_Input):
    """Delete a deal in OnePageCRM."""
    operation: Literal["delete_deal"] = Field("delete_deal", json_schema_extra={"ui:hidden": True})
    deal_id: ResourceID = Field(..., description="OnePageCRM deal ID.")

class OnePageCRMListNotesConfig(_Page):
    """List notes in OnePageCRM."""
    operation: Literal["list_notes"] = Field("list_notes", json_schema_extra={"ui:hidden": True})
    contact_id: ResourceID | None = None

class OnePageCRMGetNoteConfig(_Input):
    """Get a note in OnePageCRM."""
    operation: Literal["get_note"] = Field("get_note", json_schema_extra={"ui:hidden": True})
    note_id: ResourceID = Field(..., description="OnePageCRM note ID.")

class OnePageCRMCreateNoteConfig(_NoteFields):
    """Create a note in OnePageCRM."""
    operation: Literal["create_note"] = Field("create_note", json_schema_extra={"ui:hidden": True})
    contact_id: ResourceID
    text: str = Field(..., min_length=1, max_length=7168)

class OnePageCRMUpdateNoteConfig(_NoteFields):
    """Update a note in OnePageCRM."""
    operation: Literal["update_note"] = Field("update_note", json_schema_extra={"ui:hidden": True})
    note_id: ResourceID = Field(..., description="OnePageCRM note ID.")

    @model_validator(mode="after")
    def changes_required(self):
        if not any(value is not None for key, value in self.model_dump().items() if key not in {"operation", "note_id"}):
            raise ValueError("Supply at least one field to update")
        return self

class OnePageCRMDeleteNoteConfig(_Input):
    """Delete a note in OnePageCRM."""
    operation: Literal["delete_note"] = Field("delete_note", json_schema_extra={"ui:hidden": True})
    note_id: ResourceID = Field(..., description="OnePageCRM note ID.")

class OnePageCRMListUsersConfig(_Input):
    """Read account users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})

class OnePageCRMListStatusesConfig(_Input):
    """Read account statuses."""
    operation: Literal["list_statuses"] = Field("list_statuses", json_schema_extra={"ui:hidden": True})

class OnePageCRMListLeadSourcesConfig(_Input):
    """Read account lead sources."""
    operation: Literal["list_lead_sources"] = Field("list_lead_sources", json_schema_extra={"ui:hidden": True})

class OnePageCRMListPipelinesConfig(_Input):
    """Read account pipelines."""
    operation: Literal["list_pipelines"] = Field("list_pipelines", json_schema_extra={"ui:hidden": True})


OnePageCRMConfig = Annotated[Union[
    OnePageCRMListContactsConfig,
    OnePageCRMGetContactConfig,
    OnePageCRMCreateContactConfig,
    OnePageCRMUpdateContactConfig,
    OnePageCRMDeleteContactConfig,
    OnePageCRMListActionsConfig,
    OnePageCRMGetActionConfig,
    OnePageCRMCreateActionConfig,
    OnePageCRMUpdateActionConfig,
    OnePageCRMDeleteActionConfig,
    OnePageCRMListDealsConfig,
    OnePageCRMGetDealConfig,
    OnePageCRMCreateDealConfig,
    OnePageCRMUpdateDealConfig,
    OnePageCRMDeleteDealConfig,
    OnePageCRMListNotesConfig,
    OnePageCRMGetNoteConfig,
    OnePageCRMCreateNoteConfig,
    OnePageCRMUpdateNoteConfig,
    OnePageCRMDeleteNoteConfig,
    OnePageCRMListUsersConfig,
    OnePageCRMListStatusesConfig,
    OnePageCRMListLeadSourcesConfig,
    OnePageCRMListPipelinesConfig
], Field(discriminator="operation")]


class OnePageCRMFullConfig(NodeConfig[OnePageCRMConfig, OnePageCRMAPIKeyCredential]):
    model_config = ConfigDict(title="OnePageCRM Configuration", hide_input_in_errors=True)


ROUTES = {'list_contacts': ('GET', '/contacts', 'contacts', 'contact'), 'get_contact': ('GET', '/contacts/{contact_id}', 'contacts', 'contact'), 'create_contact': ('POST', '/contacts', 'contacts', 'contact'), 'update_contact': ('PUT', '/contacts/{contact_id}', 'contacts', 'contact'), 'delete_contact': ('DELETE', '/contacts/{contact_id}', 'contacts', 'contact'), 'list_actions': ('GET', '/actions', 'actions', 'action'), 'get_action': ('GET', '/actions/{action_id}', 'actions', 'action'), 'create_action': ('POST', '/actions', 'actions', 'action'), 'update_action': ('PUT', '/actions/{action_id}', 'actions', 'action'), 'delete_action': ('DELETE', '/actions/{action_id}', 'actions', 'action'), 'list_deals': ('GET', '/deals', 'deals', 'deal'), 'get_deal': ('GET', '/deals/{deal_id}', 'deals', 'deal'), 'create_deal': ('POST', '/deals', 'deals', 'deal'), 'update_deal': ('PUT', '/deals/{deal_id}', 'deals', 'deal'), 'delete_deal': ('DELETE', '/deals/{deal_id}', 'deals', 'deal'), 'list_notes': ('GET', '/notes', 'notes', 'note'), 'get_note': ('GET', '/notes/{note_id}', 'notes', 'note'), 'create_note': ('POST', '/notes', 'notes', 'note'), 'update_note': ('PUT', '/notes/{note_id}', 'notes', 'note'), 'delete_note': ('DELETE', '/notes/{note_id}', 'notes', 'note'), 'list_users': ('GET', '/users', 'users', 'user'), 'list_statuses': ('GET', '/statuses', 'statuses', 'status'), 'list_lead_sources': ('GET', '/lead_sources', 'lead_sources', 'lead_source'), 'list_pipelines': ('GET', '/pipelines', 'pipelines', 'pipeline')}


def _record(value, singular):
    if not isinstance(value, dict):
        raise ValueError("OnePageCRM returned an invalid record")
    # Lead sources are bare records; the other collections use singular wrappers.
    record = value if singular == "lead_source" else value.get(singular)
    if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"]:
        raise ValueError("OnePageCRM returned a record without an ID")
    return record


class OnePageCRMNode(WorkflowNode):
    integration_type = "automation-onepage-crm"
    connection_evidence = ConnectionEvidence(operation="list_users", noun="OnePageCRM users", label_keys=("email", "first_name", "id"))

    @classmethod
    def get_config_model(cls):
        return OnePageCRMFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a OnePageCRM API key")
        config, credential = self.config.config, self.config.credentials
        operation = config.operation
        method, path, plural, singular = ROUTES[operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        id_field = singular + "_id"
        selected_id = values.pop(id_field) if "{" in path else None
        if selected_id is not None:
            path = path.replace("{" + id_field + "}", selected_id)
        params, body = {}, None
        if method == "GET":
            params = values
        elif method in {"POST", "PUT"}:
            body = values
            if method == "PUT":
                # Provider-wide partial-update convention preserves omitted fields.
                params["partial"] = "true"
                if operation == "update_action" and "done" in body:
                    params["done"] = body.pop("done")
        params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in params.items()}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                auth=httpx.BasicAuth(credential.user_id, credential.api_key),
                headers={"Accept": "application/json"}, params=params, json=body)
        # Never expose credentials if a server reflects them in an error or record.
        def redact(value):
            if isinstance(value, str):
                return value.replace(credential.api_key, "[redacted]")
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items() if key not in {"api_key", "auth_key", "password", "authorization"}}
            return value
        error_base = {"operation": operation, "status": "error", "http_status": response.status_code}
        if len(response.content) > 5 * 1024 * 1024:
            raise ValueError("OnePageCRM response exceeded the size limit")
        if method == "DELETE" and response.status_code == 200 and not response.content.strip():
            return {"operation": operation, "status": "success", "http_status": 200,
                "acknowledged": True, "resource_id": selected_id}
        try:
            payload = response.json()
        except (ValueError, UnicodeError):
            return {**error_base, "error": "OnePageCRM returned a non-JSON response"}
        if not isinstance(payload, dict):
            raise ValueError("OnePageCRM response envelope is invalid")
        if response.status_code not in {200, 201} or type(payload.get("status")) is not int or payload["status"] != 0:
            return {**error_base, "error": redact(str(payload.get("message") or "OnePageCRM rejected the request"))}
        data = payload.get("data")
        output = {"operation": operation, "status": "success", "http_status": response.status_code}
        if operation.startswith("list_"):
            rows = data if plural in {"users", "statuses", "lead_sources"} else data.get(plural) if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ValueError("OnePageCRM list response is missing its records")
            output["items"] = [_record(row, singular) for row in rows]
            if plural in {"contacts", "actions", "deals", "notes", "pipelines"}:
                for key in ("page", "per_page", "max_page", "total_count"):
                    value = data.get(key)
                    if type(value) is not int or value < 0:
                        raise ValueError("OnePageCRM pagination metadata is missing or invalid")
                    output[key] = value
                output["next_page"] = data["page"] + 1 if data["page"] < data["max_page"] else None
            return redact(output)
        if method == "DELETE":
            return {**output, "acknowledged": True, "resource_id": selected_id}
        record = _record(data, singular)
        if selected_id is not None and record["id"] != selected_id:
            raise ValueError("OnePageCRM returned a different resource ID")
        return redact({**output, "item": record})
