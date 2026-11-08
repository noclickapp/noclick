"""Recruitee ATS operations using a company-scoped personal API token.

Contract: https://docs.recruitee.com/reference/getting-started
Each operation makes one request. List outputs preserve provider pagination.
"""
from datetime import datetime
from typing import Annotated, Literal, Optional, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

class RecruiteeCredential(BaseModel):
    model_config = ConfigDict(title="Recruitee Personal API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://docs.recruitee.com/reference/getting-started",
            "x-credential-instructions": "In Recruitee, open Settings > Apps and plugins > Personal API tokens. Paste an existing personal API token and its company ID. The token acts with your hiring role permissions."})
    credential_type: Literal["recruitee_api_token"] = Field("recruitee_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Personal API token", json_schema_extra={"ui:widget": "password"})
    company_id: int = Field(..., ge=1, le=2147483647, title="Company ID")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the token, without the Bearer prefix")
        return value

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class ListCandidates(Input):
    operation: Literal["list_candidates"] = "list_candidates"
    limit: int = Field(60, ge=1, le=1000)
    offset: int = Field(0, ge=0)
    query: Optional[str] = None
    offer_id: Optional[str] = None
    created_after: Optional[datetime] = Field(None, description="ISO date and time, e.g. 2021-09-01T13:51:27")
    sort: Literal["by_date", "by_last_message"] = "by_date"

class SearchCandidates(Input):
    operation: Literal["search_candidates"] = "search_candidates"
    limit: int = Field(60, ge=1, le=1000)
    page: int = Field(1, ge=1)
    sort_by: str = "created_at_desc"

class CandidateFields(Input):
    name: Optional[str] = Field(None, min_length=1)
    emails: Optional[list[str]] = None
    phones: Optional[list[str]] = None
    social_links: Optional[list[str]] = None
    links: Optional[list[str]] = None
    cover_letter: Optional[str] = None

class NewCandidate(CandidateFields):
    name: str = Field(..., min_length=1)
    sources: Optional[list[str]] = None

class CreateCandidate(Input):
    operation: Literal["create_candidate"] = "create_candidate"
    candidate: NewCandidate
    offers: Optional[list[int]] = None

class GetCandidate(Input):
    operation: Literal["get_candidate"] = "get_candidate"
    candidate_id: int = Field(..., ge=1, le=2147483647)

class UpdateCandidate(GetCandidate):
    operation: Literal["update_candidate"] = "update_candidate"
    candidate: CandidateFields

class DeleteCandidate(GetCandidate):
    operation: Literal["delete_candidate"] = "delete_candidate"

class ListNotes(GetCandidate):
    operation: Literal["list_candidate_notes"] = "list_candidate_notes"

class ListOffers(Input):
    operation: Literal["list_offers"] = "list_offers"
    scope: Optional[str] = Field(None, description="Provider offer scope")
    view_mode: str = "default"

class OfferFields(Input):
    title: str = Field(..., min_length=1)
    kind: Literal["job", "talent_pool"] = "job"
    location_ids: list[int] = Field(..., min_length=1)
    description: str
    requirements: str
    department_id: Optional[str] = None
    on_site: bool = True
    hybrid: bool = False
    remote: bool = False

class CreateOffer(Input):
    operation: Literal["create_offer"] = "create_offer"
    offer: OfferFields

class GetOffer(Input):
    operation: Literal["get_offer"] = "get_offer"
    offer_id: int = Field(..., ge=1, le=2147483647)

class DeleteOffer(GetOffer):
    operation: Literal["delete_offer"] = "delete_offer"

class ListDepartments(Input):
    operation: Literal["list_departments"] = "list_departments"

class ListMemberships(Input):
    operation: Literal["list_memberships"] = "list_memberships"

class ListLocations(Input):
    operation: Literal["list_locations"] = "list_locations"
    limit: int = Field(60, ge=1, le=1000)
    page: int = Field(1, ge=1)
    query: Optional[str] = None
    scope: Literal["all", "active", "archived"] = "all"
    view_mode: Literal["brief", "full"] = "brief"

RecruiteeOperation = Annotated[Union[ListCandidates, SearchCandidates, CreateCandidate,
    GetCandidate, UpdateCandidate, DeleteCandidate, ListNotes, ListOffers, CreateOffer,
    GetOffer, DeleteOffer, ListDepartments, ListMemberships, ListLocations], Field(discriminator="operation")]

class RecruiteeConfig(NodeConfig[RecruiteeOperation, RecruiteeCredential]):
    pass

# A fixed route/method for every exposed operation; no arbitrary API caller.
ROUTES = {
    "list_candidates": ("GET", "/candidates"),
    "search_candidates": ("GET", "/search/new/candidates"),
    "create_candidate": ("POST", "/candidates"),
    "get_candidate": ("GET", "/candidates/{candidate_id}"),
    "update_candidate": ("PATCH", "/candidates/{candidate_id}"),
    "delete_candidate": ("DELETE", "/candidates/{candidate_id}"),
    "list_candidate_notes": ("GET", "/candidates/{candidate_id}/notes"),
    "list_offers": ("GET", "/offers"),
    "create_offer": ("POST", "/offers"),
    "get_offer": ("GET", "/offers/{offer_id}"),
    "delete_offer": ("DELETE", "/offers/{offer_id}"),
    "list_departments": ("GET", "/departments"),
    "list_memberships": ("GET", "/memberships"),
    "list_locations": ("GET", "/locations"),
}

class RecruiteeNode(WorkflowNode):
    integration_type = "automation-recruitee"
    connection_evidence = ConnectionEvidence(operation="list_departments", noun="departments")

    @classmethod
    def get_config_model(cls):
        return RecruiteeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Recruitee personal API token")
        credential = self.config.credentials
        op = self.config.config
        method, route = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = route.format(**values)
        if "{candidate_id}" in route:
            values.pop("candidate_id")
        if "{offer_id}" in route:
            values.pop("offer_id")
        url = f"https://api.recruitee.com/c/{credential.company_id}{path}"
        headers = {"Authorization": f"Bearer {credential.api_token}", "Accept": "application/json"}
        kwargs = {"params": values} if method == "GET" else {"json": values} if method in {"POST", "PATCH"} else {}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError:
            raise ValueError("Recruitee request did not complete; check the provider before retrying a write") from None
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection text while removing the supplied secret.
            message = response.text.replace(credential.api_token, "[redacted]")[:2000]
            return {"status": "error", "http_status": response.status_code, "error": message}
        body = response.json() if response.content else {}
        if not isinstance(body, dict):
            raise ValueError("Expected a Recruitee JSON object")
        if "error" in body or "errors" in body:
            return {"status": "error", "error": str(body).replace(credential.api_token, "[redacted]")[:2000]}
        # Preserve the documented envelope and metadata, including list pagination.
        return {"status": "success", "operation": op.operation, "data": body}
