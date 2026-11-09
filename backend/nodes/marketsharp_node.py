"""MarketSharp CRM API 1.0: one documented request per operation.

Paste an existing /token bearer access token. No login/token creation or refresh
is performed. Search endpoints require an employee identity in the token.
List/filter operations return one provider page, with the original JSON shape.
Contract: https://restapi.marketsharpm.com/swagger/docs/1.0
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://restapi.marketsharpm.com"
CREDENTIAL_TYPE = "marketsharp_api_token"


class MarketSharpAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="MarketSharp API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://restapi.marketsharpm.com/swagger/ui/index",
            "x-credential-instructions": "Paste an existing MarketSharp access token returned by /token, without Bearer. MarketSharp provides API credentials; use Employee Authentication for contact searches. NoClick does not sign in, create or refresh tokens. Replace the token when it expires.",
        })
    credential_type: Literal["marketsharp_api_token"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=16384, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def valid_token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the access token without Bearer or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_value(cls, value, info):
        if info.field_name.endswith("_id") and isinstance(value, str):
            if not value.strip() or value in {".", ".."} or len(value) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("Use a nonempty MarketSharp resource ID without controls")
        return value


class _Company(_Input):
    company_id: str = Field(..., min_length=1, max_length=256, description="MarketSharp company ID from List Companies.")


class _Inquiry(_Company):
    inquiry_id: str = Field(..., min_length=1, max_length=256)


class _Filter(_Company):
    start_modified_datetime: datetime | None = None
    start_appointment_datetime: datetime | None = None
    end_appointment_datetime: datetime | None = None
    appointment_salesperson_id: str | None = None
    pageNumber: int = Field(1, ge=1, description="One-based provider page. Increment to retrieve another page; no automatic pagination.")
    rowsPerPage: int = Field(100, ge=1, le=1000)


class EstimateLineItem(_Input):
    id: str | None = None
    sku: str | None = None
    position: int | None = None
    estimateId: int | None = None
    quantity: int | None = None
    unitOfMeasure: int | None = None
    retailPrice: float | None = None
    cost: float | None = None
    notes: str | None = None


class _Estimate(_Company):
    appointmentId: str = Field(..., min_length=1, description="Appointment associated with this estimate.")
    name: str = Field(..., min_length=1)
    estimateDateTime: datetime | None = None
    estimateStatus: str | None = None
    estimateType: str | None = None
    proposalDeliveryDate: datetime | None = None
    taxAmount: float | None = None
    notes: str | None = None
    lineItems: list[EstimateLineItem] | None = None


class ListCompanies(_Input):
    """Read companies available to the supplied token."""
    operation: Literal["list_companies"] = "list_companies"


class GetCompany(_Company):
    operation: Literal["get_company"] = "get_company"


class GetContact(_Company):
    operation: Literal["get_contact"] = "get_contact"
    contact_id: str = Field(..., min_length=1, max_length=256)


class SearchContacts(_Company):
    """QuickFind contact search; requires an employee identity in the bearer token."""
    operation: Literal["search_contacts"] = "search_contacts"
    numberOfRecords: int = Field(100, ge=1, le=1000)
    business_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    address_line_one: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    email_address: str | None = None
    phone_number: str | None = None
    contactType: int | None = None


class FilterContacts(_Filter):
    operation: Literal["filter_contacts"] = "filter_contacts"


class GetInquiry(_Inquiry):
    operation: Literal["get_inquiry"] = "get_inquiry"


class GetOpportunity(_Inquiry):
    operation: Literal["get_opportunity"] = "get_opportunity"
    job_id: str | None = None


class ListOpportunityNotes(_Inquiry):
    operation: Literal["list_opportunity_notes"] = "list_opportunity_notes"
    note_type: Literal["Inquiry", "Job"] = "Inquiry"


class SaveOpportunityNote(_Company):
    """Insert a note, or update it when note_id is provided."""
    operation: Literal["save_opportunity_note"] = "save_opportunity_note"
    inquiry_id: str = Field(..., min_length=1, max_length=256)
    note: str = Field(..., min_length=1)
    note_type: Literal["Inquiry", "Job"] = "Inquiry"
    note_id: int | None = Field(None, ge=1)


class DeleteOpportunityNote(_Inquiry):
    operation: Literal["delete_opportunity_note"] = "delete_opportunity_note"
    note_id: int = Field(..., ge=1)


class QualifyOpportunity(_Inquiry):
    """Set the inquiry Qualified_By and Qualified_Date_Utc fields."""
    operation: Literal["qualify_opportunity"] = "qualify_opportunity"


class GetAppointment(_Company):
    operation: Literal["get_appointment"] = "get_appointment"
    appointment_id: str = Field(..., min_length=1, max_length=256)


class FilterAppointments(_Filter):
    operation: Literal["filter_appointments"] = "filter_appointments"


class ResultAppointment(_Company):
    operation: Literal["result_appointment"] = "result_appointment"
    appointment_id: str = Field(..., min_length=1, max_length=256)
    result_id: str = Field(..., min_length=1)
    result_reason: str | None = None
    notes: str | None = None
    employee_id: str = Field(..., min_length=1)


class CreateEstimate(_Estimate):
    operation: Literal["create_estimate"] = "create_estimate"


class UpdateEstimate(_Estimate):
    operation: Literal["update_estimate"] = "update_estimate"
    estimate_id: str = Field(..., min_length=1, max_length=256)


class ListPricebook(_Company):
    operation: Literal["list_pricebook"] = "list_pricebook"


class ListPrimaryLeadSources(_Company):
    operation: Literal["list_primary_lead_sources"] = "list_primary_lead_sources"


class ListSecondaryLeadSources(_Company):
    operation: Literal["list_secondary_lead_sources"] = "list_secondary_lead_sources"
    primary_lead_source_id: str = Field(..., min_length=1, max_length=256)


class ListAppointmentResults(_Company):
    operation: Literal["list_appointment_results"] = "list_appointment_results"


MarketSharpOperation = Annotated[Union[
    ListCompanies, GetCompany, GetContact, SearchContacts, FilterContacts,
    GetInquiry, GetOpportunity, ListOpportunityNotes, SaveOpportunityNote,
    DeleteOpportunityNote, QualifyOpportunity, GetAppointment, FilterAppointments,
    ResultAppointment, CreateEstimate, UpdateEstimate, ListPricebook,
    ListPrimaryLeadSources, ListSecondaryLeadSources, ListAppointmentResults,
], Field(discriminator="operation")]


class MarketSharpConfig(NodeConfig[MarketSharpOperation, MarketSharpAPITokenCredential]):
    pass


# Each entry is exactly one operation in the pinned provider contract.
ROUTES = {
    "list_companies": ("GET", "/companies"),
    "get_company": ("GET", "/companies/{company_id}"),
    "get_contact": ("GET", "/companies/{company_id}/contacts/{contact_id}"),
    "search_contacts": ("POST", "/companies/{company_id}/contacts/search"),
    "filter_contacts": ("POST", "/companies/{company_id}/contacts/filter"),
    "get_inquiry": ("GET", "/companies/{company_id}/inquiries/{inquiry_id}"),
    "get_opportunity": ("GET", "/companies/{company_id}/opportunities/{inquiry_id}"),
    "list_opportunity_notes": ("GET", "/companies/{company_id}/opportunities/{inquiry_id}/notes/{note_type}"),
    "save_opportunity_note": ("POST", "/companies/{company_id}/opportunities/notes"),
    "delete_opportunity_note": ("DELETE", "/companies/{company_id}/opportunities/{inquiry_id}/notes/{note_id}"),
    "qualify_opportunity": ("PUT", "/companies/{company_id}/opportunities/qualification/{inquiry_id}"),
    "get_appointment": ("GET", "/companies/{company_id}/appointments/{appointment_id}"),
    "filter_appointments": ("POST", "/companies/{company_id}/appointments/filter"),
    "result_appointment": ("POST", "/companies/{company_id}/appointments/{appointment_id}/result"),
    "create_estimate": ("POST", "/companies/{company_id}/estimates"),
    "update_estimate": ("PUT", "/companies/{company_id}/estimates/{estimate_id}"),
    "list_pricebook": ("GET", "/companies/{company_id}/pricebook"),
    "list_primary_lead_sources": ("GET", "/companies/{company_id}/primaryleadsources/active"),
    "list_secondary_lead_sources": ("GET", "/companies/{company_id}/primaryleadsources/{primary_lead_source_id}/secondaryleadsources/active"),
    "list_appointment_results": ("GET", "/companies/{company_id}/appointments/results/active"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class MarketSharpNode(WorkflowNode):
    integration_type = "automation-marketsharp"
    connection_evidence = ConnectionEvidence(operation="list_companies", noun="companies", label_keys=("companyName", "oid"))

    @classmethod
    def get_config_model(cls):
        return MarketSharpConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a MarketSharp API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, template = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = template.format(**{key: quote(str(value), safe="") for key, value in values.items()})
        params = {"api-version": "1.0"}
        if isinstance(op, GetOpportunity) and op.job_id is not None:
            params["jobId"] = op.job_id
        body = None
        if isinstance(op, (SearchContacts, FilterContacts, FilterAppointments, CreateEstimate, UpdateEstimate)):
            body = {k: v for k, v in values.items() if k not in {"company_id", "estimate_id"}}
        elif isinstance(op, SaveOpportunityNote):
            body = {"inquiryId": op.inquiry_id, "note": op.note, "opportunityNoteType": op.note_type}
            if op.note_id is not None:
                body["id"] = op.note_id
        elif isinstance(op, ResultAppointment):
            body = {"appt_id": op.appointment_id, "result_id": op.result_id, "employee_id": op.employee_id}
            body.update({k: values[k] for k in ("result_reason", "notes") if k in values})
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            kwargs = {"params": params, "headers": {"Authorization": "Bearer " + token, "Accept": "application/json"}}
            if body is not None:
                kwargs["json"] = body
            try:
                response = await client.request(method, BASE_URL + path, **kwargs)
            except httpx.HTTPError:
                raise ValueError("MarketSharp request could not be completed; inspect writes before retrying") from None
        try:
            data = response.json()
        except ValueError:
            if response.status_code >= 400:
                data = response.text[:2000]
            else:
                raise ValueError("MarketSharp returned a non-JSON response; inspect writes before retrying") from None
        data = _redact(data, token)
        if not 200 <= response.status_code < 300:
            return {"status": "error", "http_status": response.status_code, "status_code": response.status_code,
                    "error": data or f"MarketSharp returned HTTP {response.status_code}"}
        if isinstance(data, dict) and (data.get("error") or data.get("errors") or data.get("success") is False):
            return {"status": "error", "http_status": response.status_code, "error": data}
        output = {"status": "success", "operation": op.operation, "http_status": response.status_code, "data": data}
        if isinstance(op, ListCompanies):
            # The published schema is a company object. Also preserve array
            # responses, exposing both shapes to the shared evidence reader.
            output["items"] = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        return output
