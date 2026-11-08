"""Pipeline CRM v3 operations, pinned to https://app.pipelinecrm.com/openapi.json."""
from __future__ import annotations

from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.pipelinecrm.com/api/v3"


class PipelineCrmAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Pipeline CRM API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.pipelinecrm.com/user/api_tokens",
            "x-credential-instructions": "In Pipeline CRM, open your profile > API tokens and create a token. Paste the token shown once. Choose a read-write token for writes, or a read-only token for reads. Tokens are being enabled account by account; contact Pipeline CRM support if the page is unavailable. No app key is needed.",
        })
    credential_type: Literal["pipeline_crm_api_token"] = Field("pipeline_crm_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() or ord(c) < 33 for c in value):
            raise ValueError("Paste the API token without a Bearer header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListInput(Input):
    page: int = Field(1, ge=1, description="Page number; use next_page from the preceding result.")
    per_page: int = Field(50, ge=1, le=200, description="Records per page, at most 200.")


class DealFields(Input):
    name: str | None = Field(None, min_length=1)
    summary: str | None = None
    value: str | None = Field(None, pattern=r"^-?\d+(?:\.\d+)?$", description="Decimal amount as a string.")
    user_id: int | None = Field(None, ge=1)
    company_id: int | None = Field(None, ge=1)
    primary_contact_id: int | None = Field(None, ge=1)
    deal_stage_id: int | None = Field(None, ge=1)
    probability: int | None = Field(None, ge=0, le=100, description="0 or 100 closes the deal; 1–99 reopens it.")
    expected_close_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    custom_fields: dict | None = None


class PersonFields(Input):
    full_name: str | None = Field(None, min_length=1)
    email: str | None = None
    phone: str | None = None
    position: str | None = None
    company_id: int | None = Field(None, ge=1)
    user_id: int | None = Field(None, ge=1)
    lead_status_id: int | None = Field(None, ge=1)
    lead_source_id: int | None = Field(None, ge=1)
    type: Literal["Contact", "Lead"] | None = None
    custom_fields: dict | None = None


class CompanyFields(Input):
    name: str | None = Field(None, min_length=1)
    description: str | None = None
    email: str | None = None
    web: str | None = None
    phone1: str | None = None
    owner_id: int | None = Field(None, ge=1)
    custom_fields: dict | None = None


class NoteFields(Input):
    content: str | None = Field(None, min_length=1)
    title: str | None = None
    deal_id: int | None = Field(None, ge=1)
    company_id: int | None = Field(None, ge=1)
    person_id: int | None = Field(None, ge=1)
    note_category_id: int | None = Field(None, ge=1)


class CalendarEntryFields(Input):
    name: str | None = Field(None, min_length=1)
    category_id: int | None = Field(None, ge=1)
    type: Literal["CalendarTask", "CalendarEvent"] | None = None
    description: str | None = None
    due_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str | None = Field(None, description="Event start in the user's time zone, YYYY-MM-DD HH:MM:SS.")
    end_time: str | None = Field(None, description="Event end in the user's time zone, YYYY-MM-DD HH:MM:SS.")
    complete: bool | None = None
    association_type: Literal["Deal", "Company", "Person"] | None = None
    association_id: int | None = Field(None, ge=1)


class GetProfile(Input):
    """Read the authenticated user's profile without returning their legacy API key."""
    operation: Literal["get_profile"] = "get_profile"


class ListDeal(ListInput):
    """List deals in Pipeline CRM."""
    operation: Literal["list_deals"] = "list_deals"

    name: str | None = Field(None, description="Filter by name using conditions[deal_name].")


class GetDeal(Input):
    """Get deal in Pipeline CRM."""
    operation: Literal["get_deal"] = "get_deal"
    deal_id: int = Field(..., ge=1)


class CreateDeal(DealFields):
    """Create deal in Pipeline CRM."""
    operation: Literal["create_deal"] = "create_deal"
    name: str = Field(..., min_length=1)


class UpdateDeal(DealFields):
    """Update deal in Pipeline CRM."""
    operation: Literal["update_deal"] = "update_deal"
    deal_id: int = Field(..., ge=1)


class DeleteDeal(Input):
    """Delete deal in Pipeline CRM."""
    operation: Literal["delete_deal"] = "delete_deal"
    deal_id: int = Field(..., ge=1)


class ListPerson(ListInput):
    """List people in Pipeline CRM."""
    operation: Literal["list_people"] = "list_people"

    name: str | None = Field(None, description="Filter by name using conditions[person_full_name].")


class GetPerson(Input):
    """Get person in Pipeline CRM."""
    operation: Literal["get_person"] = "get_person"
    person_id: int = Field(..., ge=1)


class CreatePerson(PersonFields):
    """Create person in Pipeline CRM."""
    operation: Literal["create_person"] = "create_person"
    full_name: str = Field(..., min_length=1)


class UpdatePerson(PersonFields):
    """Update person in Pipeline CRM."""
    operation: Literal["update_person"] = "update_person"
    person_id: int = Field(..., ge=1)


class DeletePerson(Input):
    """Delete person in Pipeline CRM."""
    operation: Literal["delete_person"] = "delete_person"
    person_id: int = Field(..., ge=1)


class ListCompany(ListInput):
    """List companies in Pipeline CRM."""
    operation: Literal["list_companies"] = "list_companies"

    name: str | None = Field(None, description="Filter by name using conditions[company_name].")


class GetCompany(Input):
    """Get company in Pipeline CRM."""
    operation: Literal["get_company"] = "get_company"
    company_id: int = Field(..., ge=1)


class CreateCompany(CompanyFields):
    """Create company in Pipeline CRM."""
    operation: Literal["create_company"] = "create_company"
    name: str = Field(..., min_length=1)


class UpdateCompany(CompanyFields):
    """Update company in Pipeline CRM."""
    operation: Literal["update_company"] = "update_company"
    company_id: int = Field(..., ge=1)


class DeleteCompany(Input):
    """Delete company in Pipeline CRM."""
    operation: Literal["delete_company"] = "delete_company"
    company_id: int = Field(..., ge=1)


class GetNote(Input):
    """Get note in Pipeline CRM."""
    operation: Literal["get_note"] = "get_note"
    note_id: int = Field(..., ge=1)


class CreateNote(NoteFields):
    """Create note in Pipeline CRM."""
    operation: Literal["create_note"] = "create_note"
    content: str = Field(..., min_length=1)
    deal_id: int = Field(..., ge=1)


class UpdateNote(NoteFields):
    """Update note in Pipeline CRM."""
    operation: Literal["update_note"] = "update_note"
    note_id: int = Field(..., ge=1)


class ListCalendarEntry(ListInput):
    """List tasks and events in Pipeline CRM."""
    operation: Literal["list_calendar_entries"] = "list_calendar_entries"


class GetCalendarEntry(Input):
    """Get calendar entry in Pipeline CRM."""
    operation: Literal["get_calendar_entry"] = "get_calendar_entry"
    calendar_entry_id: int = Field(..., ge=1)


class CreateCalendarEntry(CalendarEntryFields):
    """Create calendar entry in Pipeline CRM."""
    operation: Literal["create_calendar_entry"] = "create_calendar_entry"
    name: str = Field(..., min_length=1)
    category_id: int = Field(..., ge=1)
    type: Literal["CalendarTask", "CalendarEvent"] = Field(...)


class UpdateCalendarEntry(CalendarEntryFields):
    """Update calendar entry in Pipeline CRM."""
    operation: Literal["update_calendar_entry"] = "update_calendar_entry"
    calendar_entry_id: int = Field(..., ge=1)


PipelineCrmConfig = Annotated[
    Union[
        GetProfile,
        ListDeal,
        GetDeal,
        CreateDeal,
        UpdateDeal,
        DeleteDeal,
        ListPerson,
        GetPerson,
        CreatePerson,
        UpdatePerson,
        DeletePerson,
        ListCompany,
        GetCompany,
        CreateCompany,
        UpdateCompany,
        DeleteCompany,
        GetNote,
        CreateNote,
        UpdateNote,
        ListCalendarEntry,
        GetCalendarEntry,
        CreateCalendarEntry,
        UpdateCalendarEntry,
    ],
    Field(discriminator="operation"),
]


class PipelineCrmFullConfig(NodeConfig[PipelineCrmConfig, PipelineCrmAPITokenCredential]):
    pass


ROUTES = {
    "get_profile": ('GET', 'profile', None),
    "list_deals": ('GET', 'deals', None),
    "get_deal": ('GET', 'deals', None),
    "create_deal": ('POST', 'deals', 'deal'),
    "update_deal": ('PUT', 'deals', 'deal'),
    "delete_deal": ('DELETE', 'deals', None),
    "list_people": ('GET', 'people', None),
    "get_person": ('GET', 'people', None),
    "create_person": ('POST', 'people', 'person'),
    "update_person": ('PUT', 'people', 'person'),
    "delete_person": ('DELETE', 'people', None),
    "list_companies": ('GET', 'companies', None),
    "get_company": ('GET', 'companies', None),
    "create_company": ('POST', 'companies', 'company'),
    "update_company": ('PUT', 'companies', 'company'),
    "delete_company": ('DELETE', 'companies', None),
    "get_note": ('GET', 'notes', None),
    "create_note": ('POST', 'notes', 'note'),
    "update_note": ('PUT', 'notes', 'note'),
    "list_calendar_entries": ('GET', 'calendar_entries', None),
    "get_calendar_entry": ('GET', 'calendar_entries', None),
    "create_calendar_entry": ('POST', 'calendar_entries', 'calendar_entry'),
    "update_calendar_entry": ('PUT', 'calendar_entries', 'calendar_entry'),
}


class ProviderError(ValueError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()
                if k.lower() not in {"api_key", "app_key", "api_token", "token", "password", "authorization"}}
    return value


class PipelineCrmNode(WorkflowNode):
    integration_type = "automation-pipeline-crm"
    connection_evidence = ConnectionEvidence(noun="deals", operation="list_deals", identity_operation="get_profile")

    @classmethod
    def get_config_model(cls):
        return PipelineCrmFullConfig

    async def execute(self, input_data):
        if not self.config.credentials:
            raise ValueError("Connect a Pipeline CRM API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, resource, root = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        identifier = None
        if method in {"PUT", "DELETE"} or (op.operation.startswith("get_") and resource != "profile"):
            id_field = op.operation.split("_", 1)[1] + "_id"
            identifier = values.pop(id_field)
        path = "/" + resource + ("/" + str(identifier) if identifier is not None else "")
        params = values.copy() if op.operation.startswith("list_") else {}
        if "name" in params:
            filter_key = {"deals": "deal_name", "people": "person_full_name", "companies": "company_name"}[resource]
            params["conditions[" + filter_key + "]"] = params.pop("name")
        body = None
        if root:
            if not values:
                raise ValueError("Provide at least one field to update")
            body = {root: values}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
            if response.status_code not in ({200, 204} if method == "DELETE" else {200}):
                message = "Pipeline CRM request failed"
                try:
                    error = response.json()
                    if isinstance(error, dict) and isinstance(error.get("error"), str):
                        message = _redact(error["error"], token)
                except ValueError:
                    pass
                raise ProviderError(response.status_code, message)
            if method == "DELETE":
                return {"status": "success", "deleted_id": identifier, "http_status": response.status_code}
            if len(response.content) > 10_000_000:
                raise ValueError("Pipeline CRM response exceeds 10 MB")
            payload = response.json()
            if not isinstance(payload, dict) or "error" in payload or "errors" in payload:
                raise ValueError("Pipeline CRM returned an unexpected response")
            if op.operation.startswith("list_"):
                entries, pagination = payload.get("entries"), payload.get("pagination")
                if not isinstance(entries, list) or not all(isinstance(row, dict) for row in entries) or not isinstance(pagination, dict):
                    raise ValueError("Pipeline CRM returned an invalid list")
                page, per_page, total = (pagination.get(k) for k in ("page", "per_page", "total"))
                if any(type(n) is not int for n in (page, per_page, total)) or page < 1 or per_page < 1 or total < 0:
                    raise ValueError("Pipeline CRM returned invalid pagination")
                has_more = page * per_page < total
                return {"status": "success", "data": _redact(entries, token), "pagination": _redact(pagination, token),
                    "has_more": has_more, "next_page": page + 1 if has_more else None}
            if type(payload.get("id")) is not int or payload["id"] < 1:
                raise ValueError("Pipeline CRM returned an invalid record")
            if identifier is not None and payload.get("id") != identifier:
                raise ValueError("Pipeline CRM returned a different record")
            return {"status": "success", "data": _redact(payload, token)}
        except ProviderError as exc:
            return {"status": "error", "error": str(exc), "http_status": exc.status,
                    "write_may_have_occurred": method != "GET" and (exc.status < 400 or exc.status >= 500)}
        except (httpx.HTTPError, ValueError):
            return {"status": "error", "error": "Pipeline CRM response could not be confirmed",
                    "write_may_have_occurred": method != "GET"}
