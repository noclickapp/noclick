"""Credas Connect v2-ci operations, pinned to the provider's published OpenAPI.

API host and key setup: https://apisupport.credas.com/support/solutions/articles/44002476031-credas-api-overview-api
No retries are performed: process creation and invitation delivery have side effects.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class CredasAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Credas API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://apisupport.credas.com/support/solutions/articles/44002476031-credas-api-overview-api",
            "x-credential-instructions": "Paste your Credas API key and choose the matching environment. Demo and production use different keys. Request API access from your Credas technical contact. Production checks may be chargeable.",
        },
    )
    credential_type: Literal["credas_api_key"] = Field(
        "credas_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"}
    )
    environment: Literal["production", "demo"] = Field(
        "production", title="Environment"
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without the header name")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Address(Input):
    addressLine1: str | None = Field(None, max_length=256)
    addressLine2: str | None = Field(None, max_length=256)
    town: str | None = Field(None, max_length=256)
    county: str | None = Field(None, max_length=256)
    postcode: str | None = Field(None, max_length=10)


class ProcessEntity(Input):
    id: UUID | None = None
    actorId: int = Field(..., description="Actor ID from the selected journey")
    firstName: str | None = None
    middleName: str | None = None
    surname: str | None = None
    emailAddress: str | None = None
    phoneNumber: str | None = None
    reference: str | None = None
    contactViaEmail: bool | None = None
    contactViaSms: bool | None = None
    inPerson: bool | None = None
    dateOfBirth: datetime | None = None


class SearchEntities(Input):
    """Search entities matching a name, email, reference or process."""

    operation: Literal["search_entities"] = Field(
        "search_entities", json_schema_extra={"ui:hidden": True}
    )
    searchText: str | None = None
    pageNumber: int = Field(
        1, ge=1, description="Page to read; call again for subsequent pages"
    )


class GetEntity(Input):
    """Read an entity profile."""

    operation: Literal["get_entity"] = Field(
        "get_entity", json_schema_extra={"ui:hidden": True}
    )
    entityId: UUID


class CreateEntity(Input):
    """Create an individual profile."""

    operation: Literal["create_entity"] = Field(
        "create_entity", json_schema_extra={"ui:hidden": True}
    )
    firstName: str
    surname: str
    emailAddress: EmailStr | None = None
    phoneNumber: str | None = None
    middleName: str | None = None
    reference: str | None = None
    dateOfBirth: datetime | None = None
    userGroupId: UUID | None = None
    address: Address | None = None
    folderId: int | None = None


class GetEntitySummary(Input):
    """Read the verification results summary."""

    operation: Literal["get_entity_summary"] = Field(
        "get_entity_summary", json_schema_extra={"ui:hidden": True}
    )
    entityId: UUID
    includeArchived: bool | None = None


class ListActiveChecks(Input):
    """Read current data checks."""

    operation: Literal["list_active_checks"] = Field(
        "list_active_checks", json_schema_extra={"ui:hidden": True}
    )
    entityId: UUID


class ListIdvEntries(Input):
    """List identity verification entries."""

    operation: Literal["list_idv_entries"] = Field(
        "list_idv_entries", json_schema_extra={"ui:hidden": True}
    )
    entityId: UUID


class GetIdvEntry(Input):
    """Read an identity verification entry."""

    operation: Literal["get_idv_entry"] = Field(
        "get_idv_entry", json_schema_extra={"ui:hidden": True}
    )
    entityId: UUID
    entryId: UUID


class ListEntityEvidence(Input):
    """List evidence attached to an entity."""

    operation: Literal["list_entity_evidence"] = Field(
        "list_entity_evidence", json_schema_extra={"ui:hidden": True}
    )
    entityId: UUID


class ListDocuments(Input):
    """List electronic signature documents."""

    operation: Literal["list_documents"] = Field(
        "list_documents", json_schema_extra={"ui:hidden": True}
    )
    entityId: UUID


class ListJourneys(Input):
    """List journeys available to this account."""

    operation: Literal["list_journeys"] = Field(
        "list_journeys", json_schema_extra={"ui:hidden": True}
    )


class GetJourney(Input):
    """Read journey configuration and actor IDs."""

    operation: Literal["get_journey"] = Field(
        "get_journey", json_schema_extra={"ui:hidden": True}
    )
    journeyId: UUID


class CreateProcess(Input):
    """Start a verification journey; invitations may be sent and checks may be chargeable."""

    operation: Literal["create_process"] = Field(
        "create_process", json_schema_extra={"ui:hidden": True}
    )
    journeyId: UUID
    title: str | None = None
    userGroupId: UUID | None = None
    processEntities: list[ProcessEntity] = Field(..., min_length=1, max_length=100)
    skipSendingEntityInvites: bool = Field(
        False, description="Suppress invitations when creating the process"
    )


class GetProcess(Input):
    """Read process status."""

    operation: Literal["get_process"] = Field(
        "get_process", json_schema_extra={"ui:hidden": True}
    )
    processId: UUID


class GetProcessDetails(Input):
    """Read detailed process results."""

    operation: Literal["get_process_details"] = Field(
        "get_process_details", json_schema_extra={"ui:hidden": True}
    )
    processId: UUID


class GetLatestProcess(Input):
    """Read the latest process for an entity."""

    operation: Literal["get_latest_process"] = Field(
        "get_latest_process", json_schema_extra={"ui:hidden": True}
    )
    entityId: UUID
    journeyId: UUID | None = None
    actorId: int | None = None


class LockProcess(Input):
    """Lock a process."""

    operation: Literal["lock_process"] = Field(
        "lock_process", json_schema_extra={"ui:hidden": True}
    )
    processId: UUID


class UnlockProcess(Input):
    """Unlock a process."""

    operation: Literal["unlock_process"] = Field(
        "unlock_process", json_schema_extra={"ui:hidden": True}
    )
    processId: UUID


class ApproveEntity(Input):
    """Set approval status to approved."""

    operation: Literal["approve_entity"] = Field(
        "approve_entity", json_schema_extra={"ui:hidden": True}
    )
    entityId: UUID


class RejectEntity(Input):
    """Set approval status to rejected."""

    operation: Literal["reject_entity"] = Field(
        "reject_entity", json_schema_extra={"ui:hidden": True}
    )
    entityId: UUID


class ResetEntityApproval(Input):
    """Reset an entity approval status."""

    operation: Literal["reset_entity_approval"] = Field(
        "reset_entity_approval", json_schema_extra={"ui:hidden": True}
    )
    entityId: UUID


class ExpireInvite(Input):
    """Expire an entity invitation."""

    operation: Literal["expire_invite"] = Field(
        "expire_invite", json_schema_extra={"ui:hidden": True}
    )
    entityId: UUID


class NewInvite(Input):
    """Create a new invitation and select email or SMS delivery."""

    operation: Literal["new_invite"] = Field(
        "new_invite", json_schema_extra={"ui:hidden": True}
    )
    entityId: UUID
    contactByEmail: bool = True
    contactBySms: bool = False


class ResendInvite(Input):
    """Resend an entity invitation."""

    operation: Literal["resend_invite"] = Field(
        "resend_invite", json_schema_extra={"ui:hidden": True}
    )
    entityId: UUID
    contactByEmail: bool = True
    contactBySms: bool = False


CredasOperation = Annotated[
    Union[
        SearchEntities,
        GetEntity,
        CreateEntity,
        GetEntitySummary,
        ListActiveChecks,
        ListIdvEntries,
        GetIdvEntry,
        ListEntityEvidence,
        ListDocuments,
        ListJourneys,
        GetJourney,
        CreateProcess,
        GetProcess,
        GetProcessDetails,
        GetLatestProcess,
        LockProcess,
        UnlockProcess,
        ApproveEntity,
        RejectEntity,
        ResetEntityApproval,
        ExpireInvite,
        NewInvite,
        ResendInvite,
    ],
    Field(discriminator="operation"),
]


class CredasConfig(NodeConfig[CredasOperation, CredasAPIKeyCredential]):
    pass


ROUTES = {
    "search_entities": ("GET", "entities/search"),
    "get_entity": ("GET", "entities/{entityId}"),
    "create_entity": ("POST", "entities"),
    "get_entity_summary": ("GET", "entities/{entityId}/summary"),
    "list_active_checks": ("GET", "entities/{entityId}/active-checks"),
    "list_idv_entries": ("GET", "entities/{entityId}/idv-entries"),
    "get_idv_entry": ("GET", "entities/{entityId}/idv-entries/{entryId}"),
    "list_entity_evidence": ("GET", "entities/{entityId}/evidence"),
    "list_documents": ("GET", "entities/{entityId}/documents"),
    "list_journeys": ("GET", "journeys"),
    "get_journey": ("GET", "journeys/{journeyId}"),
    "create_process": ("POST", "processes"),
    "get_process": ("GET", "processes/{processId}"),
    "get_process_details": ("GET", "processes/{processId}/details"),
    "get_latest_process": ("GET", "processes/latest-by-entity/{entityId}"),
    "lock_process": ("PUT", "processes/{processId}/lock"),
    "unlock_process": ("PUT", "processes/{processId}/unlock"),
    "approve_entity": ("PUT", "entities/{entityId}/approve"),
    "reject_entity": ("PUT", "entities/{entityId}/reject"),
    "reset_entity_approval": ("PUT", "entities/{entityId}/reset"),
    "expire_invite": ("PUT", "entities/{entityId}/expire-invite"),
    "new_invite": ("PUT", "entities/{entityId}/new-invite"),
    "resend_invite": ("PUT", "entities/{entityId}/resend-invite"),
}


class CredasNode(WorkflowNode):
    integration_type = "automation-credas"
    connection_evidence = ConnectionEvidence(
        noun="entities",
        operation="search_entities",
        label_keys=("name", "emailAddress", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return CredasConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Credas API key")
        op = self.config.config
        credential = self.config.credentials
        method, route = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        # Fixed routes and UUID-typed path fields prevent path or host injection.
        path_fields = [name for name in values if "{" + name + "}" in route]
        for name in path_fields:
            route = route.replace("{" + name + "}", str(values.pop(name)))
        host = (
            "portal.credasdemo.com"
            if credential.environment == "demo"
            else "portal.credas.com"
        )
        kwargs = (
            {"params": values}
            if method == "GET"
            else ({"json": values} if values else {})
        )
        async with guarded_async_client(
            timeout=httpx.Timeout(30), trust_env=False, follow_redirects=False
        ) as client:
            response = await client.request(
                method,
                "https://" + host + "/api/v2/ci/" + route,
                headers={"X-API-KEY": credential.api_key, "Accept": "application/json"},
                **kwargs,
            )
        if response.status_code not in (200, 204):
            # Keep the provider's rejection, while preventing accidental key disclosure.
            message = response.text[:2000].replace(credential.api_key, "[redacted]")
            result = {
                "status": "error",
                "http_status": response.status_code,
                "message": message or "Credas request failed",
            }
        elif response.status_code == 204 or not response.content:
            result = {
                "status": "success",
                "http_status": response.status_code,
                "data": None,
            }
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("Credas response exceeds the JSON size limit")
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Credas returned an invalid JSON response") from None
            if not isinstance(data, (dict, list)):
                raise ValueError("Credas returned an unexpected JSON response")
            result = {
                "status": "success",
                "http_status": response.status_code,
                "data": data,
            }
            if op.operation == "search_entities":
                if not isinstance(data, dict):
                    raise ValueError("Credas entity search must return an object")
                result.update(
                    entities=data.get("entities") or [],
                    total_entities=data.get("totalEntities"),
                    page_number=op.pageNumber,
                )
        await self.emit(result)
        return result
