"""SalesRabbit+ API Gateway v1: bounded JSON:API reads and single-resource writes.

Routes and write attributes follow the provider's published OpenAPI 1.0 contract.
Each operation sends one request; pagination is explicit and writes are never retried.
"""
from typing import Annotated, Literal, Optional, Union
from uuid import UUID
from datetime import datetime
from urllib.parse import parse_qs, urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class SalesRabbitAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="SalesRabbit API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://developers.salesrabbit.com/",
            "x-credential-instructions": "Copy your API key from SalesRabbit account settings and paste it here. Choose your account's data region. NoClick sends it as a Bearer token to SalesRabbit only."})
    credential_type: Literal["salesrabbit_api_key"] = Field("salesrabbit_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})
    region: Literal["US", "Ireland"] = Field("US", title="Data region")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetLeadConfig(_Input):
    """Get lead by ID."""
    operation: Literal["get_lead"] = Field("get_lead", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Resource ID")


class CreateLeadConfig(_Input):
    """Create lead with relationships."""
    operation: Literal["create_lead"] = Field("create_lead", json_schema_extra={"ui:hidden": True})
    assignee_id: UUID = Field(...)
    city: Optional[str] = Field(None)
    country: Optional[str] = Field(None)
    lead_status_id: UUID = Field(...)
    postal_code: Optional[str] = Field(None)
    region: Optional[str] = Field(None)
    street1: Optional[str] = Field(None)
    street2: Optional[str] = Field(None)
    team_id: UUID = Field(...)
    title: Optional[str] = Field(None)


class UpdateLeadConfig(_Input):
    """Update lead with relationships."""
    operation: Literal["update_lead"] = Field("update_lead", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Resource ID")
    assignee_id: Optional[UUID] = Field(None)
    city: Optional[str] = Field(None)
    country: Optional[str] = Field(None)
    lead_status_id: Optional[UUID] = Field(None)
    postal_code: Optional[str] = Field(None)
    region: Optional[str] = Field(None)
    street1: Optional[str] = Field(None)
    street2: Optional[str] = Field(None)
    title: Optional[str] = Field(None)


class DeleteLeadConfig(_Input):
    """Delete lead."""
    operation: Literal["delete_lead"] = Field("delete_lead", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Resource ID")


class GetAppointmentConfig(_Input):
    """Get appointment by ID."""
    operation: Literal["get_appointment"] = Field("get_appointment", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Resource ID")


class CreateAppointmentConfig(_Input):
    """Create appointment."""
    operation: Literal["create_appointment"] = Field("create_appointment", json_schema_extra={"ui:hidden": True})
    cal_event_id: Optional[str] = Field(None)
    lead_id: UUID = Field(...)
    scheduler_event_id: Optional[str] = Field(None)
    time: datetime = Field(...)


class UpdateAppointmentConfig(_Input):
    """Update appointment."""
    operation: Literal["update_appointment"] = Field("update_appointment", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Resource ID")
    cal_event_id: Optional[str] = Field(None)
    lead_id: Optional[UUID] = Field(None)
    scheduler_event_id: Optional[str] = Field(None)
    time: Optional[datetime] = Field(None)


class DeleteAppointmentConfig(_Input):
    """Delete appointment."""
    operation: Literal["delete_appointment"] = Field("delete_appointment", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Resource ID")


class GetContactConfig(_Input):
    """Get contact by ID."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Resource ID")


class CreateContactConfig(_Input):
    """Create contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    lead_id: UUID = Field(...)
    name: Optional[str] = Field(None)


class UpdateContactConfig(_Input):
    """Update contact."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Resource ID")
    first_name: Optional[str] = Field(None)
    last_name: Optional[str] = Field(None)
    lead_id: Optional[UUID] = Field(None)
    name: Optional[str] = Field(None)


class DeleteContactConfig(_Input):
    """Delete contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Resource ID")


class GetLeadNoteConfig(_Input):
    """Get lead note by ID."""
    operation: Literal["get_lead_note"] = Field("get_lead_note", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Resource ID")


class CreateLeadNoteConfig(_Input):
    """Create lead note."""
    operation: Literal["create_lead_note"] = Field("create_lead_note", json_schema_extra={"ui:hidden": True})
    lead_id: UUID = Field(...)
    profile_id: UUID = Field(...)
    text: str = Field(...)


class UpdateLeadNoteConfig(_Input):
    """Update lead note."""
    operation: Literal["update_lead_note"] = Field("update_lead_note", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Resource ID")
    lead_id: Optional[UUID] = Field(None)
    profile_id: Optional[UUID] = Field(None)
    text: Optional[str] = Field(None)


class DeleteLeadNoteConfig(_Input):
    """Delete lead note."""
    operation: Literal["delete_lead_note"] = Field("delete_lead_note", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., title="Resource ID")


class ListLeadsConfig(_Input):
    """Get leads."""
    operation: Literal["list_leads"] = Field("list_leads", json_schema_extra={"ui:hidden": True})
    limit: int = Field(25, ge=1, le=250, description="Results per page (maximum 250).")
    offset: int = Field(0, ge=0, description="Page offset; use next_offset from the prior page.")


class ListLeadStatusesConfig(_Input):
    """Get statuses."""
    operation: Literal["list_lead_statuses"] = Field("list_lead_statuses", json_schema_extra={"ui:hidden": True})
    limit: int = Field(25, ge=1, le=250, description="Results per page (maximum 250).")
    offset: int = Field(0, ge=0, description="Page offset; use next_offset from the prior page.")


class ListProfilesConfig(_Input):
    """Get profiles."""
    operation: Literal["list_profiles"] = Field("list_profiles", json_schema_extra={"ui:hidden": True})
    limit: int = Field(25, ge=1, le=250, description="Results per page (maximum 250).")
    offset: int = Field(0, ge=0, description="Page offset; use next_offset from the prior page.")


class ListTeamsConfig(_Input):
    """Get teams."""
    operation: Literal["list_teams"] = Field("list_teams", json_schema_extra={"ui:hidden": True})
    limit: int = Field(25, ge=1, le=250, description="Results per page (maximum 250).")
    offset: int = Field(0, ge=0, description="Page offset; use next_offset from the prior page.")


class ListAreasConfig(_Input):
    """Get areas."""
    operation: Literal["list_areas"] = Field("list_areas", json_schema_extra={"ui:hidden": True})
    limit: int = Field(25, ge=1, le=250, description="Results per page (maximum 250).")
    offset: int = Field(0, ge=0, description="Page offset; use next_offset from the prior page.")


SalesRabbitOperation = Annotated[Union[GetLeadConfig, CreateLeadConfig, UpdateLeadConfig, DeleteLeadConfig, GetAppointmentConfig, CreateAppointmentConfig, UpdateAppointmentConfig, DeleteAppointmentConfig, GetContactConfig, CreateContactConfig, UpdateContactConfig, DeleteContactConfig, GetLeadNoteConfig, CreateLeadNoteConfig, UpdateLeadNoteConfig, DeleteLeadNoteConfig, ListLeadsConfig, ListLeadStatusesConfig, ListProfilesConfig, ListTeamsConfig, ListAreasConfig], Field(discriminator="operation")]


class SalesRabbitConfig(NodeConfig[SalesRabbitOperation, SalesRabbitAPIKeyCredential]):
    pass


OPERATIONS = {'get_lead': ('GET', '/v1/leads/{id}'), 'create_lead': ('POST', '/v1/leads'), 'update_lead': ('PATCH', '/v1/leads/{id}'), 'delete_lead': ('DELETE', '/v1/leads/{id}'), 'get_appointment': ('GET', '/v1/appointments/{id}'), 'create_appointment': ('POST', '/v1/appointments'), 'update_appointment': ('PATCH', '/v1/appointments/{id}'), 'delete_appointment': ('DELETE', '/v1/appointments/{id}'), 'get_contact': ('GET', '/v1/contacts/{id}'), 'create_contact': ('POST', '/v1/contacts'), 'update_contact': ('PATCH', '/v1/contacts/{id}'), 'delete_contact': ('DELETE', '/v1/contacts/{id}'), 'get_lead_note': ('GET', '/v1/lead_notes/{id}'), 'create_lead_note': ('POST', '/v1/lead_notes'), 'update_lead_note': ('PATCH', '/v1/lead_notes/{id}'), 'delete_lead_note': ('DELETE', '/v1/lead_notes/{id}'), 'list_leads': ('GET', '/v1/leads'), 'list_lead_statuses': ('GET', '/v1/lead_statuses'), 'list_profiles': ('GET', '/v1/profiles'), 'list_teams': ('GET', '/v1/teams'), 'list_areas': ('GET', '/v1/areas')}


class SalesRabbitNode(WorkflowNode):
    integration_type = "automation-salesrabbit"
    connection_evidence = ConnectionEvidence(noun="sales representatives", operation="list_profiles", label_keys=("name", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return SalesRabbitConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a SalesRabbit API key")
        credential = self.config.credentials
        op = self.config.config
        method, route = OPERATIONS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        identifier = values.pop("id", None)
        route = route.replace("{id}", identifier or "")
        params = None
        body = None
        if op.operation.startswith("list_"):
            params = {"page[limit]": op.limit, "page[offset]": op.offset}
        if method in {"POST", "PATCH"}:
            if method == "PATCH" and not values:
                raise ValueError("Supply at least one field to update")
            body = {"data": {"attributes": values}}
            # Lead updates use attributes only; other PATCH contracts require data.id.
            if method == "PATCH" and op.operation != "update_lead":
                body["data"]["id"] = identifier
        base = "https://integrate.salesrabbit.com" if credential.region == "US" else "https://integrate.ireland.salesrabbit.com"
        content_type = "application/vnd.api+json" if op.operation in {"create_lead", "update_lead"} else "application/json"
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, base + route, params=params,
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json", "Content-Type": content_type},
                **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection text for connection evidence, with the token removed.
            detail = response.text[:2000].replace(credential.api_key, "[redacted]")
            raise ValueError(f"SalesRabbit HTTP {response.status_code}: {detail}")
        if response.status_code == 204 or not response.content:
            if method != "DELETE":
                raise ValueError("SalesRabbit returned an empty resource response")
            result = {"deleted_id": identifier, "deletion_acknowledged": True}
        else:
            payload = response.json()
            if not isinstance(payload, dict) or "errors" in payload or "error" in payload or "data" not in payload:
                raise ValueError("SalesRabbit returned an invalid JSON:API response")
            rows = payload["data"]
            listing = op.operation.startswith("list_")
            if not isinstance(rows, list if listing else dict):
                raise ValueError("SalesRabbit returned an unexpected resource shape")
            result = {"data": rows}
            for key in ("included", "meta", "links"):
                if key in payload:
                    result[key] = payload[key]
            if listing:
                result["items"] = [{**row.get("attributes", {}), "id": row.get("id")} for row in rows]
                # Links are returned as data only, never fetched. Every next call stays on the fixed API origin.
                next_link = payload.get("links", {}).get("next")
                next_offset = None
                if next_link:
                    query = parse_qs(urlsplit(next_link).query)
                    raw_offset = query.get("page[offset]", [])
                    if len(raw_offset) != 1 or not raw_offset[0].isdigit():
                        raise ValueError("SalesRabbit returned an invalid next-page offset")
                    next_offset = int(raw_offset[0])
                    if next_offset <= op.offset:
                        raise ValueError("SalesRabbit returned a nonadvancing page")
                result.update(has_more=bool(next_link), next_offset=next_offset)
        # Tokens must never escape through a provider's echoed payload.
        def redact(value):
            if isinstance(value, str):
                return value.replace(credential.api_key, "[redacted]")
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {redact(key): redact(item) for key, item in value.items()}
            return value
        result = redact(result)
        output = {"status": "success", "operation": op.operation, **result}
        await self.emit(output)
        return output
