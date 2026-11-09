"""SalesQL Public API v3.14.2: enrichment, verification and credit allowance.

Contract: https://api-public.salesql.com/openapi.json. API keys use Bearer auth.
All nine published operations are exposed; no documented webhook registration
or created/updated-time list endpoint supports a new-item trigger.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api-public.salesql.com/v1"


class SalesQLAPIKeyCredential(BaseModel):
    # Preserve the acronym in the shared credential label formatter. The
    # provider label below retains the official SalesQL brand spelling.
    model_config = ConfigDict(title="SALESQL API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "api_key",
            "x-credential-url": "https://app.salesql.com/dashboard/enrichment/api",
            "x-credential-instructions": "Create a REST API key in SalesQL Settings → API Access and paste it here. Use an API key, not an MCP key. Enable enrichment access and verify:verify for email verification. Account and plan limits apply; enrichment and verification use separate credits.",
        })
    credential_type: Literal["salesql_api_key"] = Field("salesql_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class OrganizationQuery(_Input):
    linkedin_url: str | None = Field(None, description="Company LinkedIn URL, for example https://linkedin.com/company/oracle")
    organization_name: str | None = None
    organization_domain: str | None = Field(None, description="Company website domain, for example oracle.com")

    @model_validator(mode="after")
    def matching_group(self):
        if not any((self.linkedin_url, self.organization_name, self.organization_domain)):
            raise ValueError("Provide a LinkedIn company URL, organization name or domain")
        return self


class PersonQuery(_Input):
    linkedin_url: str | None = Field(None, description="Person LinkedIn URL, for example https://linkedin.com/in/bob-christiaanse")
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    organization_name: str | None = None
    organization_domain: str | None = None

    @model_validator(mode="after")
    def matching_group(self):
        if not (self.linkedin_url or self.email or
                ((self.full_name or (self.first_name and self.last_name)) and
                 (self.organization_name or self.organization_domain))):
            raise ValueError("Provide a LinkedIn URL, email, or a complete name and organization group")
        return self


class GetAllowance(_Input):
    """Read the authenticated account's remaining credits without spending any."""
    operation: Literal["get_credit_allowance"] = Field("get_credit_allowance", json_schema_extra={"ui:hidden": True})


class EnrichOrganization(OrganizationQuery):
    """Enrich one company by LinkedIn URL, domain or name. Uses enrichment credits."""
    operation: Literal["enrich_organization"] = Field("enrich_organization", json_schema_extra={"ui:hidden": True})


class BulkEnrichOrganizations(_Input):
    """Enrich up to 100 organizations (10 on Free); returns one result per query."""
    operation: Literal["bulk_enrich_organizations"] = Field("bulk_enrich_organizations", json_schema_extra={"ui:hidden": True})
    organizations: list[OrganizationQuery] = Field(..., min_length=1, max_length=100)


class EnrichPerson(PersonQuery):
    """Enrich a person by a complete matching group. Uses enrichment credits."""
    operation: Literal["enrich_person"] = Field("enrich_person", json_schema_extra={"ui:hidden": True})
    match_if_direct_email: bool = Field(False, description="Require a direct (non-work) email")
    match_if_direct_phone: bool = Field(False, description="Require a direct phone; ignored on the Free plan")


class LookupPersonByEmail(_Input):
    """Find a person's enriched profile by email. Uses enrichment credits."""
    operation: Literal["lookup_person_by_email"] = Field("lookup_person_by_email", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)


class BulkEnrichPersons(_Input):
    """Enrich up to 100 people (10 on Free); returns one result per query."""
    operation: Literal["bulk_enrich_persons"] = Field("bulk_enrich_persons", json_schema_extra={"ui:hidden": True})
    persons: list[PersonQuery] = Field(..., min_length=1, max_length=100)


class VerifyEmail(_Input):
    """Verify one mailbox synchronously. Costs one verification credit, including cache hits."""
    operation: Literal["verify_email"] = Field("verify_email", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)


class BulkVerifyEmails(_Input):
    """Queue up to 500 emails (100 on Free). Only one job per account may run at a time."""
    operation: Literal["bulk_verify_emails"] = Field("bulk_verify_emails", json_schema_extra={"ui:hidden": True})
    emails: list[str] = Field(..., min_length=1, max_length=500)


class GetBulkVerificationJob(_Input):
    """Read a verification job. Follow retry_after seconds until status is completed."""
    operation: Literal["get_bulk_verification_job"] = Field("get_bulk_verification_job", json_schema_extra={"ui:hidden": True})
    job_id: str = Field(..., description="Job UUID returned by Bulk Verify Emails")

    @field_validator("job_id")
    @classmethod
    def job_uuid(cls, value):
        return str(UUID(value))


SalesQLConfig = Annotated[Union[GetAllowance, EnrichOrganization, BulkEnrichOrganizations,
    EnrichPerson, LookupPersonByEmail, BulkEnrichPersons, VerifyEmail,
    BulkVerifyEmails, GetBulkVerificationJob], Field(discriminator="operation")]


class SalesQLFullConfig(NodeConfig[SalesQLConfig, SalesQLAPIKeyCredential]):
    pass


ROUTES = {
    "get_credit_allowance": ("GET", "/allowance", 200),
    "enrich_organization": ("GET", "/organizations/enrich", 200),
    "bulk_enrich_organizations": ("POST", "/organizations/enrich/bulk", 200),
    "enrich_person": ("GET", "/persons/enrich", 200),
    "lookup_person_by_email": ("GET", "/persons/email_lookup", 200),
    "bulk_enrich_persons": ("POST", "/persons/enrich/bulk", 200),
    "verify_email": ("POST", "/emails/verify", 200),
    "bulk_verify_emails": ("POST", "/emails/verify/bulk", 202),
    "get_bulk_verification_job": ("GET", "/emails/verify/bulk/{job_id}", 200),
}


class SalesQLNode(WorkflowNode):
    integration_type = "automation-salesql"
    credential_provider_labels = {"salesql": "SalesQL"}
    connection_evidence = ConnectionEvidence(operation="get_credit_allowance",
        noun="SalesQL credit allowance", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return SalesQLFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a SalesQL API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, path, expected_status = ROUTES[config.operation]
        values = config.model_dump(exclude={"operation"}, exclude_none=True)
        params, body = None, None
        if isinstance(config, GetBulkVerificationJob):
            path = path.format(job_id=config.job_id)
        elif method == "GET":
            params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
        elif isinstance(config, BulkEnrichOrganizations):
            body = values["organizations"]
        elif isinstance(config, BulkEnrichPersons):
            body = values["persons"]
        else:
            body = values
        # No automatic retries: accepted bulk jobs and credit-consuming calls
        # must not be duplicated when a response is lost. Never follow redirects.
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    **({"json": body} if body is not None else {}),
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
        except httpx.HTTPError:
            raise ValueError("SalesQL request did not return a response; execution outcome is unverified") from None
        if response.status_code != expected_status:
            message = response.text[:2000].replace(key, "[redacted]")
            result = {"status": "error", "http_status": response.status_code, "message": message,
                      "retry_after": response.headers.get("Retry-After")}
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("SalesQL returned invalid JSON") from None
            bulk = isinstance(config, (BulkEnrichOrganizations, BulkEnrichPersons))
            if not isinstance(data, list if bulk else dict):
                raise ValueError("SalesQL returned an unexpected response shape")
            result = {"status": "success", "data": data}
            if response.headers.get("Retry-After") is not None:
                result["retry_after"] = response.headers["Retry-After"]
        await self.emit(result)
        return result
