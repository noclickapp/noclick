"""Nimbata Web API v2: account, call and lead automation.

Contract: https://api.nimbata.com/openapi.json (2.0.0).
Each operation makes one request; collection results retain provider paging.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Literal, Union
from uuid import UUID
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE = "https://api.nimbata.com"


class NimbataAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Nimbata API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.nimbata.com/",
            "x-credential-instructions": "Paste your Nimbata API token without the Bearer prefix. The token must allow the selected project and operation. NoClick checks the current user to verify the connection.",
        })
    credential_type: Literal["nimbata_api_token"] = Field("nimbata_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value) or any(ord(c) > 126 or ord(c) < 33 for c in value):
            raise ValueError("Paste the API token without a Bearer prefix or spaces")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Org(_Input):
    org_id: UUID = Field(..., title="Organization ID", description="The org_id returned by Get Current User.")


class _Project(_Org):
    project_id: UUID = Field(..., title="Project ID", description="Project UUID from List Projects.")


class _Page(_Input):
    page_size: int = Field(25, ge=1, le=100, description="Return one page of up to 100 records.")
    cursor: str | None = Field(None, max_length=4096, description="Opaque cursor from page.next. Preserve the same filters when continuing.")


class _Call(_Project):
    call_id: str = Field(..., min_length=1, max_length=45, pattern=r"^[A-Za-z0-9._:-]+$", description="Inbound uu_id_a or outbound report-row ID.")

    @field_validator("call_id")
    @classmethod
    def call_segment(cls, value):
        if value in {".", ".."}:
            raise ValueError("Use a call report ID")
        return value


class _EditableCall(_Call):
    call_direction: Literal["inbound", "outbound"] = "inbound"
    uu_id_b: str | None = Field(None, min_length=1, max_length=45, pattern=r"^[A-Za-z0-9._:-]+$", description="Optional destination leg ID.")


class _Lead(_Project):
    lead_id: UUID


class GetCurrentUser(_Input):
    """Identify the token owner and primary organization."""
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})


class ListProjects(_Org, _Page):
    """List projects."""
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})


class GetProject(_Project):
    """Get project."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})


class ListCalls(_Project, _Page):
    """List calls."""
    operation: Literal["list_calls"] = Field("list_calls", json_schema_extra={"ui:hidden": True})
    start_date: date | None = Field(None, description="Start day in the project time zone; supply with end_date.")
    end_date: date | None = None
    caller_num: str | None = Field(None, max_length=255)
    utm_source: str | None = Field(None, max_length=255)
    utm_medium: str | None = Field(None, max_length=255)
    utm_campaign: str | None = Field(None, max_length=255)

    @model_validator(mode="after")
    def window(self):
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("Supply both start and end dates")
        if self.start_date and self.start_date > self.end_date:
            raise ValueError("End date must be on or after start date")
        return self


class GetCall(_Call):
    """Get call."""
    operation: Literal["get_call"] = Field("get_call", json_schema_extra={"ui:hidden": True})
    uu_id_b: str | None = Field(None, max_length=45)
    call_outcome: str | None = Field(None, max_length=40)


class ListLeads(_Project, _Page):
    """List leads."""
    operation: Literal["list_leads"] = Field("list_leads", json_schema_extra={"ui:hidden": True})
    phone: str | None = Field(None, max_length=255, description="Exact lead phone filter.")
    email: EmailStr | None = Field(None, max_length=255, description="Exact lead email filter.")


class GetLead(_Lead):
    """Get lead."""
    operation: Literal["get_lead"] = Field("get_lead", json_schema_extra={"ui:hidden": True})


class GetLeadTimeline(_Lead, _Page):
    """Get lead timeline."""
    operation: Literal["get_lead_timeline"] = Field("get_lead_timeline", json_schema_extra={"ui:hidden": True})


class GetCallActivity(_EditableCall):
    """Get call activity."""
    operation: Literal["get_call_activity"] = Field("get_call_activity", json_schema_extra={"ui:hidden": True})


class ListTagCategories(_Project, _Page):
    """List tag categories."""
    operation: Literal["list_tag_categories"] = Field("list_tag_categories", json_schema_extra={"ui:hidden": True})


class ListTags(_Project, _Page):
    """List tags."""
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})
    tag_category_id: UUID


class AddCallTags(_EditableCall):
    """Update call tags. Changes may trigger Nimbata call-update workflows. Existing tags are preserved."""
    operation: Literal["add_call_tags"] = Field("add_call_tags", json_schema_extra={"ui:hidden": True})
    tag_ids: list[UUID] = Field(..., min_length=1, max_length=1000)


class ReplaceCallTags(_EditableCall):
    """Update call tags. Changes may trigger Nimbata call-update workflows. An empty list removes all tags."""
    operation: Literal["replace_call_tags"] = Field("replace_call_tags", json_schema_extra={"ui:hidden": True})
    tag_ids: list[UUID] = Field(..., min_length=0, max_length=1000)


class RemoveCallTag(_EditableCall):
    """Remove one call tag. Changes may trigger Nimbata call-update workflows."""
    operation: Literal["remove_call_tag"] = Field("remove_call_tag", json_schema_extra={"ui:hidden": True})
    tag_id: UUID


class SetCallRating(_EditableCall):
    """Rating from zero to five, kept to two decimals. Changes may run call-update workflows."""
    operation: Literal["set_call_rating"] = Field("set_call_rating", json_schema_extra={"ui:hidden": True})
    value: float = Field(..., ge=0, le=5, allow_inf_nan=False, description='Rating from zero to five, kept to two decimals.')


class ClearCallRating(_EditableCall):
    """Clear the call rating. Changes may run call-update workflows."""
    operation: Literal["clear_call_rating"] = Field("clear_call_rating", json_schema_extra={"ui:hidden": True})


class SetCallValue(_EditableCall):
    """Amount in the project currency, kept to two decimals. Changes may run call-update workflows."""
    operation: Literal["set_call_value"] = Field("set_call_value", json_schema_extra={"ui:hidden": True})
    value: float = Field(..., ge=0, le=99999999.99, allow_inf_nan=False, description='Amount in the project currency, kept to two decimals.')


class ClearCallValue(_EditableCall):
    """Clear the call value. Changes may run call-update workflows."""
    operation: Literal["clear_call_value"] = Field("clear_call_value", json_schema_extra={"ui:hidden": True})


class SetCallComments(_EditableCall):
    """Call comments saved as sent. Changes may run call-update workflows."""
    operation: Literal["set_call_comments"] = Field("set_call_comments", json_schema_extra={"ui:hidden": True})
    value: str = Field(..., min_length=1, max_length=65535, description='Call comments saved as sent.')


class ClearCallComments(_EditableCall):
    """Clear the call comments. Changes may run call-update workflows."""
    operation: Literal["clear_call_comments"] = Field("clear_call_comments", json_schema_extra={"ui:hidden": True})


class SetCallFollowupDate(_EditableCall):
    """Follow-up day in YYYY-MM-DD."""
    operation: Literal["set_call_followup_date"] = Field("set_call_followup_date", json_schema_extra={"ui:hidden": True})
    value: date = Field(..., description='Follow-up day in YYYY-MM-DD.')


class ClearCallFollowupDate(_EditableCall):
    """Clear the call followup date. Changes may run call-update workflows."""
    operation: Literal["clear_call_followup_date"] = Field("clear_call_followup_date", json_schema_extra={"ui:hidden": True})


class SetCallCallerName(_EditableCall):
    """Sets the caller name across all calls from that number in this project. Inbound calls only; no workflows run."""
    operation: Literal["set_call_caller_name"] = Field("set_call_caller_name", json_schema_extra={"ui:hidden": True})
    value: str = Field(..., min_length=1, max_length=100, description='Sets the caller name across all calls from that number in this project. Inbound calls only; no workflows run.')


class ClearCallCallerName(_EditableCall):
    """Clear the call caller name. Applies to the caller number across the project; inbound calls only."""
    operation: Literal["clear_call_caller_name"] = Field("clear_call_caller_name", json_schema_extra={"ui:hidden": True})


# Nimbata's own MCP server: agents get its tools through a person's Nimbata sign-in.
NimbataMcpCredential = mcp_credential("nimbata", "https://mcp.nimbata.com/mcp", app="Nimbata")
NimbataCredential = Union[NimbataAPITokenCredential, NimbataMcpCredential]


NimbataConfig = Annotated[Union[
    GetCurrentUser,
    ListProjects,
    GetProject,
    ListCalls,
    GetCall,
    ListLeads,
    GetLead,
    GetLeadTimeline,
    GetCallActivity,
    ListTagCategories,
    ListTags,
    AddCallTags,
    ReplaceCallTags,
    RemoveCallTag,
    SetCallRating,
    ClearCallRating,
    SetCallValue,
    ClearCallValue,
    SetCallComments,
    ClearCallComments,
    SetCallFollowupDate,
    ClearCallFollowupDate,
    SetCallCallerName,
    ClearCallCallerName
], Field(discriminator="operation")]


class NimbataNodeConfig(NodeConfig[NimbataConfig, NimbataCredential]):
    pass


ROUTES = {'get_current_user': ('GET', '/users/me'),
 'list_projects': ('GET', '/orgs/{org_id}/projects'),
 'get_project': ('GET', '/orgs/{org_id}/projects/{project_id}'),
 'list_calls': ('GET', '/orgs/{org_id}/projects/{project_id}/calls'),
 'get_call': ('GET', '/orgs/{org_id}/projects/{project_id}/calls/{call_id}'),
 'list_leads': ('GET', '/orgs/{org_id}/projects/{project_id}/leads'),
 'get_lead': ('GET', '/orgs/{org_id}/projects/{project_id}/leads/{lead_id}'),
 'get_lead_timeline': ('GET', '/orgs/{org_id}/projects/{project_id}/leads/{lead_id}/timeline'),
 'get_call_activity': ('GET', '/orgs/{org_id}/projects/{project_id}/calls/{call_id}/activity'),
 'list_tag_categories': ('GET', '/orgs/{org_id}/projects/{project_id}/tag-categories'),
 'list_tags': ('GET', '/orgs/{org_id}/projects/{project_id}/tag-categories/{tag_category_id}/tags'),
 'add_call_tags': ('POST', '/orgs/{org_id}/projects/{project_id}/calls/{call_id}/tags'),
 'replace_call_tags': ('PUT', '/orgs/{org_id}/projects/{project_id}/calls/{call_id}/tags'),
 'remove_call_tag': ('DELETE',
                     '/orgs/{org_id}/projects/{project_id}/calls/{call_id}/tags/{tag_id}'),
 'set_call_rating': ('PUT', '/orgs/{org_id}/projects/{project_id}/calls/{call_id}/rating'),
 'clear_call_rating': ('DELETE', '/orgs/{org_id}/projects/{project_id}/calls/{call_id}/rating'),
 'set_call_value': ('PUT', '/orgs/{org_id}/projects/{project_id}/calls/{call_id}/value'),
 'clear_call_value': ('DELETE', '/orgs/{org_id}/projects/{project_id}/calls/{call_id}/value'),
 'set_call_comments': ('PUT', '/orgs/{org_id}/projects/{project_id}/calls/{call_id}/comments'),
 'clear_call_comments': ('DELETE', '/orgs/{org_id}/projects/{project_id}/calls/{call_id}/comments'),
 'set_call_followup_date': ('PUT',
                            '/orgs/{org_id}/projects/{project_id}/calls/{call_id}/action_date'),
 'clear_call_followup_date': ('DELETE',
                              '/orgs/{org_id}/projects/{project_id}/calls/{call_id}/action_date'),
 'set_call_caller_name': ('PUT', '/orgs/{org_id}/projects/{project_id}/calls/{call_id}/name'),
 'clear_call_caller_name': ('DELETE', '/orgs/{org_id}/projects/{project_id}/calls/{call_id}/name')}


class NimbataNode(WorkflowNode):
    integration_type = "automation-nimbata"
    credential_provider_labels = {"nimbata": "Nimbata Account"}
    connection_evidence = ConnectionEvidence(
        noun="Nimbata account", identity_operation="get_current_user",
        identity_keys=("full_name", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return NimbataNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Nimbata API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, template = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        path = template
        for name, value in values.items():
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
        params = {}
        for name in ("page_size", "cursor", "caller_num", "utm_source", "utm_medium", "utm_campaign", "uu_id_b", "call_outcome", "call_direction"):
            if name in values:
                params[name] = values[name]
        for name in ("phone", "email"):
            if name in values:
                params["filter[" + name + "]"] = values[name]
        if values.get("start_date"):
            params["dateRange"] = json.dumps({"startDate": values["start_date"], "endDate": values["end_date"]})
        body = {"tag_ids": values["tag_ids"]} if "tag_ids" in values else {"value": values["value"]} if "value" in values else None
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            return {"status": "error", "message": "Nimbata request could not be completed", "write_outcome": "unverified" if method != "GET" else None}
        status = response.status_code
        if status not in {200, 204}:
            message = "Nimbata returned HTTP " + str(status)
            try:
                problem = response.json()
                if isinstance(problem, dict):
                    message = problem.get("detail") or problem.get("title") or message
            except ValueError:
                pass
            return {"status": "error", "http_status": status, "message": str(message).replace(token, "[redacted]")}
        if status == 204:
            result = {"status": "success", "http_status": status, "data": None,
                "message": "No content returned" if method == "GET" else "Nimbata acknowledged the request; no updated record returned"}
        else:
            try:
                if len(response.content) > 10_000_000:
                    raise ValueError("Response too large")
                data = response.json()
                if not isinstance(data, (dict, list)):
                    raise ValueError("Expected an object or list")
                if isinstance(data, dict) and ("errors" in data or data.get("type") == "about:blank" or (isinstance(data.get("status"), int) and data["status"] >= 400)):
                    raise ValueError("Problem response")
                if op.operation == "get_current_user" and (not all(data.get(k) for k in ("id", "org_id", "email")) or not isinstance(data.get("full_name"), str)):
                    raise ValueError("Incomplete user profile")
                result = {"status": "success", "http_status": status, "data": data}
                if op.operation.startswith("list_"):
                    if not isinstance(data, dict) or not isinstance(data.get("items"), list) or not isinstance(data.get("page"), dict) or "next" not in data["page"]:
                        raise ValueError("Incomplete collection response")
                    result.update(items=data["items"], page=data["page"], has_more=data["page"]["next"] is not None)
                elif op.operation == "get_lead_timeline":
                    if not isinstance(data, dict) or not all(k in data for k in ("lead", "pages", "calls", "forms", "page")):
                        raise ValueError("Incomplete lead timeline")
            except (ValueError, AttributeError):
                return {"status": "error", "http_status": status, "message": "Nimbata returned an unexpected response"}
        # Avoid reflecting the connected token even if a provider error echoes it.
        def redact(value):
            if isinstance(value, str): return value.replace(token, "[redacted]")
            if isinstance(value, list): return [redact(v) for v in value]
            if isinstance(value, dict): return {k: redact(v) for k, v in value.items()}
            return value
        result = redact(result)
        await self.emit(result)
        return result
