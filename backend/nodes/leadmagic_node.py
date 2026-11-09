"""LeadMagic API integration, pinned to the provider's OpenAPI 1.4.35 contract.

Each operation makes one request. Batch listing exposes explicit limit/offset;
submission returns the acceptance response and does not imply completed work.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, Json, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.leadmagic.io"


class LeadmagicAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Leadmagic API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.leadmagic.io/",
            "x-credential-instructions": "Paste your LeadMagic API key from your account dashboard. NoClick sends it in the X-API-Key header. Enrichment and batch operations consume provider credits; checking credits is read-only.",
        })
    credential_type: Literal["leadmagic_api_key"] = Field("leadmagic_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(char.isspace() for char in value):
            raise ValueError("Paste the API key without whitespace or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def nonblank(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("Provide a non-empty value")
        return value

    @model_validator(mode="after")
    def required_combinations(self):
        op = self.operation
        def has(*keys):
            return any(getattr(self, key, None) for key in keys)
        if op == "find_email" and not (has("profile_url") or (has("first_name", "full_name") and has("domain", "company_name"))):
            raise ValueError("Provide a profile URL, or a name and company domain/name")
        if op == "get_email_profile" and not has("work_email", "personal_email"):
            raise ValueError("Provide a work or personal email")
        if op == "find_mobile" and not has("profile_url", "work_email", "personal_email"):
            raise ValueError("Provide a profile URL or email")
        if op in {"detect_job_change", "get_company_funding", "find_role", "find_employees"} and not has("company_name", "company_domain"):
            raise ValueError("Provide a company name or domain")
        if op == "find_role" and not has("job_title"):
            raise ValueError("Provide the job title")
        if op == "get_company" and not has("company_name", "company_domain", "profile_url"):
            raise ValueError("Provide a company name, domain or profile")
        if op == "find_competitors" and not has("company_name", "company_domain", "company_url"):
            raise ValueError("Provide a company name, domain or URL")
        return self


class BatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product: str = Field(..., min_length=1, description="Enrichment product slug, for example email_validation.")
    input: dict[str, Any] = Field(..., description="Product-specific input fields, for example {\"email\": \"alex.rivera@example.com\"}.")
    client_id: str | None = None
    client_name: str | None = None
    metadata: dict[str, Any] | None = None


class CheckCreditsConfig(_Input):
    """Check your current credit balance."""
    operation: Literal["check_credits"] = Field("check_credits", json_schema_extra={"ui:hidden": True})

class ValidateEmailConfig(_Input):
    """Validate an email address for deliverability and get company enrichment data."""
    operation: Literal["validate_email"] = Field("validate_email", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., description='Email address to validate', min_length=1)

class FindEmailConfig(_Input):
    """Find a person's work email address using their name and company information."""
    operation: Literal["find_email"] = Field("find_email", json_schema_extra={"ui:hidden": True})
    first_name: str | None = Field(None, description='First name of the person (optional if full_name provided). A single initial (`J`) is accepted when `last_name` is a full surname.\n', min_length=1)
    last_name: str | None = Field(None, description='Last name of the person (optional)', min_length=1)
    full_name: str | None = Field(None, description='Full name of the person (alternative to first_name + last_name). An initial plus a surname (`J Orjuela`) is accepted.\n', min_length=1)
    domain: str | None = Field(None, description='Company domain name (required if company_name not provided; aliases company_domain, website, url accepted)', min_length=1)
    company_name: str | None = Field(None, description='Company name (required if domain not provided; aliases company, organization, employer accepted)', min_length=1)
    profile_url: str | None = Field(None, description='B2B profile URL or username. Identifies the person and their company on its own, then the email is validated the same way as a name plus domain.\n', min_length=1)
    allow_domain_mismatch: bool | None = Field(None, description='By default, an email found on a domain unrelated to the requested one is returned as a free not-found (`domain_mismatch: true`, `credits_consumed: 0`). Set to `true` to return that email instead, flagged `domain_mismatch: true` and charged like any other valid find.\n')

class FindPersonalEmailConfig(_Input):
    """Provide a B2B Profile URL and get back the personal emails of the person."""
    operation: Literal["find_personal_email"] = Field("find_personal_email", json_schema_extra={"ui:hidden": True})
    profile_url: str = Field(..., description='Professional profile URL or identifier', min_length=1)

class FindProfileEmailConfig(_Input):
    """Provide a B2B person profile and get back the work email of the person."""
    operation: Literal["find_profile_email"] = Field("find_profile_email", json_schema_extra={"ui:hidden": True})
    profile_url: str = Field(..., description='B2B person profile URL or slug', min_length=1)

class GetPersonProfileConfig(_Input):
    """Retrieve comprehensive B2B person profile information including work history, education, certifications, and more."""
    operation: Literal["get_person_profile"] = Field("get_person_profile", json_schema_extra={"ui:hidden": True})
    profile_url: str = Field(..., description='B2B person profile URL or slug', min_length=1)

class GetEmailProfileConfig(_Input):
    """Use this endpoint to find a B2B person profile based on the provided email."""
    operation: Literal["get_email_profile"] = Field("get_email_profile", json_schema_extra={"ui:hidden": True})
    work_email: str | None = Field(None, description='Provide the Work Email of the person', min_length=1)
    personal_email: str | None = Field(None, description='Provide the Personal Email of the person', min_length=1)

class FindMobileConfig(_Input):
    """Find a person's mobile phone number using their profile URL or email address."""
    operation: Literal["find_mobile"] = Field("find_mobile", json_schema_extra={"ui:hidden": True})
    profile_url: str | None = Field(None, description='Provide their Social Media URL', min_length=1)
    work_email: str | None = Field(None, description='Provide the Work Email of the person', min_length=1)
    personal_email: str | None = Field(None, description='Provide the Personal Email of the person', min_length=1)

class DetectJobChangeConfig(_Input):
    """Job Change Detector."""
    operation: Literal["detect_job_change"] = Field("detect_job_change", json_schema_extra={"ui:hidden": True})
    profile_url: str = Field(..., description='Professional profile URL or identifier', min_length=1)
    company_name: str | None = Field(None, description='Expected company name (either company_name or company_domain is required)', min_length=1)
    company_domain: str | None = Field(None, description='Expected company domain (either company_name or company_domain is required)', min_length=1)

class GetCompanyConfig(_Input):
    """Search for companies and retrieve comprehensive company intelligence including funding, employees, industry, and more."""
    operation: Literal["get_company"] = Field("get_company", json_schema_extra={"ui:hidden": True})
    profile_url: str | None = Field(None, description='Business company profile URL or identifier', min_length=1)
    company_domain: str | None = Field(None, description='Provide Company Domain', min_length=1)
    company_name: str | None = Field(None, description='Provide Company Name', min_length=1)

class GetCompanyFundingConfig(_Input):
    """Provide the Company Domain or Company Name and get back the complete funding details of the company."""
    operation: Literal["get_company_funding"] = Field("get_company_funding", json_schema_extra={"ui:hidden": True})
    company_name: str | None = Field(None, description='Provide Company Name', min_length=1)
    company_domain: str | None = Field(None, description='Provide Company Domain', min_length=1)

class FindCompetitorsConfig(_Input):
    """Find competitors of a company by analyzing market position and industry data."""
    operation: Literal["find_competitors"] = Field("find_competitors", json_schema_extra={"ui:hidden": True})
    company_domain: str | None = Field(None, description='Company website domain', min_length=1)
    company_url: str | None = Field(None, description='Company profile URL or identifier (optional)', min_length=1)
    company_name: str | None = Field(None, description='Company name', min_length=1)

class GetTechnographicsConfig(_Input):
    """Get detailed technology stack information for any company by providing their domain."""
    operation: Literal["get_technographics"] = Field("get_technographics", json_schema_extra={"ui:hidden": True})
    company_domain: str = Field(..., description='The domain of the company to analyze', min_length=1)

class FindRoleConfig(_Input):
    """Provide the company name or domain and the required job title, and retrieve the corresponding person."""
    operation: Literal["find_role"] = Field("find_role", json_schema_extra={"ui:hidden": True})
    company_name: str | None = Field(None, description='Business Profile URL (with url or public_identifier)', min_length=1)
    company_domain: str | None = Field(None, description='Company domain', min_length=1)
    job_title: str | None = Field(None, description='Enter the job title you want to find in the company.', min_length=1)

class FindEmployeesConfig(_Input):
    """Find employees at a company. Returns a list of employees with their profiles, titles, and locations. Costs 0.05 credits per employee returned: free when no employees are found."""
    operation: Literal["find_employees"] = Field("find_employees", json_schema_extra={"ui:hidden": True})
    company_domain: str | None = Field(None, description='Company website domain (preferred: more accurate than company_name)', min_length=1)
    company_name: str | None = Field(None, description='Company name. Use if domain is not available.', min_length=1)
    limit: int | None = Field(None, description='Maximum number of employees to return')

class ListBatchesConfig(_Input):
    """List batches across all products for the authenticated organization."""
    operation: Literal["list_batches"] = Field("list_batches", json_schema_extra={"ui:hidden": True})
    product: str | None = Field(None, min_length=1)
    status: str | None = Field(None, min_length=1)
    client_id: str | None = Field(None, min_length=1)
    limit: int | None = Field(None, ge=1, le=200)
    offset: int | None = Field(None, ge=0)

class GetBatchConfig(_Input):
    """Return status, progress, cost, and metadata for a mixed-product batch."""
    operation: Literal["get_batch"] = Field("get_batch", json_schema_extra={"ui:hidden": True})
    batchId: str = Field(..., description='Identifier of the batch returned when it was submitted.', min_length=1)

class SubmitBatchConfig(_Input):
    """Submit a batch containing items for one or more enrichment products."""
    operation: Literal["submit_batch"] = Field("submit_batch", json_schema_extra={"ui:hidden": True})
    items: Json[list[BatchItem]] = Field(..., json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}, description='Batch items. Each item carries `product` (required for mixed-product batches), `input`, and optional `client_id`, `client_name`, and `metadata`.', min_length=1, max_length=500)
    idempotencyKey: str | None = Field(None, description='Submitting the same key twice returns the original batch instead of creating a duplicate.', min_length=1)
    metadata: Json[dict[str, Any]] | None = Field(None, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}, description='Arbitrary metadata stored with the batch.')
    client_id: str | None = Field(None, description='Associate the whole batch with a client record.', min_length=1)
    client_name: str | None = Field(None, description='Client name recorded alongside the batch.', min_length=1)
    budget_user_id: str | None = Field(None, description="Charge the batch against this member's credit budget.", min_length=1)
    webhook_url: str | None = Field(None, json_schema_extra={"format": "uri"}, description='HTTPS URL notified when the batch completes. SSRF-validated: must resolve to a public IP.', min_length=1)
    priority: Literal['normal', 'low'] | None = Field(None, description='Queue priority for this batch.', min_length=1)

class ListClientsConfig(_Input):
    """List client records for the authenticated organization."""
    operation: Literal["list_clients"] = Field("list_clients", json_schema_extra={"ui:hidden": True})

class CreateClientConfig(_Input):
    """Create an organization-scoped client for segmenting downstream batch work."""
    operation: Literal["create_client"] = Field("create_client", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='Unique client identifier (slug). Lowercase, alphanumeric with hyphens.', min_length=1)
    display_name: str | None = Field(None, description='Human-readable display name.', min_length=1)
    contact_email: str | None = Field(None, description='Contact email for notifications.', min_length=1)
    billing_rate: float | None = Field(None, description='Optional billing rate applied to this client.')
    notes: str | None = Field(None, description='Internal notes.', min_length=1)
    industry: str | None = Field(None, description='Industry classification.', min_length=1)
    website: str | None = Field(None, description='Client website.', min_length=1)
    phone: str | None = Field(None, description='Phone number.', min_length=1)
    address: Json[dict[str, Any]] | None = Field(None, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}, description='Physical address object.')
    custom_fields: Json[dict[str, Any]] | None = Field(None, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}, description='Arbitrary custom fields stored with the client.')


LeadmagicOperation = Annotated[Union[
    CheckCreditsConfig,
    ValidateEmailConfig,
    FindEmailConfig,
    FindPersonalEmailConfig,
    FindProfileEmailConfig,
    GetPersonProfileConfig,
    GetEmailProfileConfig,
    FindMobileConfig,
    DetectJobChangeConfig,
    GetCompanyConfig,
    GetCompanyFundingConfig,
    FindCompetitorsConfig,
    GetTechnographicsConfig,
    FindRoleConfig,
    FindEmployeesConfig,
    ListBatchesConfig,
    GetBatchConfig,
    SubmitBatchConfig,
    ListClientsConfig,
    CreateClientConfig
], Field(discriminator="operation")]


class LeadmagicConfig(NodeConfig[LeadmagicOperation, LeadmagicAPIKeyCredential]):
    pass


ROUTES = {'check_credits': ('GET', '/v1/credits'),
 'validate_email': ('POST', '/v1/people/email-validation'),
 'find_email': ('POST', '/v1/people/email-finder'),
 'find_personal_email': ('POST', '/v1/people/personal-email-finder'),
 'find_profile_email': ('POST', '/v1/people/b2b-profile-email'),
 'get_person_profile': ('POST', '/v1/people/profile-search'),
 'get_email_profile': ('POST', '/v1/people/b2b-profile'),
 'find_mobile': ('POST', '/v1/people/mobile-finder'),
 'detect_job_change': ('POST', '/v1/people/job-change-detector'),
 'get_company': ('POST', '/v1/companies/company-search'),
 'get_company_funding': ('POST', '/v1/companies/company-funding'),
 'find_competitors': ('POST', '/v1/companies/competitors-search'),
 'get_technographics': ('POST', '/v1/companies/technographics'),
 'find_role': ('POST', '/v1/people/role-finder'),
 'find_employees': ('POST', '/v1/people/employee-finder'),
 'list_batches': ('GET', '/v1/batch'),
 'get_batch': ('GET', '/v1/batch/{batchId}'),
 'submit_batch': ('POST', '/v1/batch'),
 'list_clients': ('GET', '/v1/batch/clients'),
 'create_client': ('POST', '/v1/batch/clients')}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items() if key.lower() not in {"api_key", "x-api-key", "authorization"}}
    return value


class LeadmagicNode(WorkflowNode):
    integration_type = "automation-leadmagic"
    connection_evidence = ConnectionEvidence(operation="check_credits", noun="credit balance")

    @classmethod
    def get_config_model(cls):
        return LeadmagicConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a LeadMagic API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        payload = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "{batchId}" in path:
            path = path.replace("{batchId}", quote(payload.pop("batchId"), safe=""))
        # No retries: enrichment can consume credits and batch creation writes data.
        async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path,
                headers={"X-API-Key": credential.api_key, "Accept": "application/json"},
                **({"params": payload} if method == "GET" else {"json": payload}))
        try:
            body = response.json()
        except ValueError:
            raise ValueError(f"LeadMagic returned non-JSON (HTTP {response.status_code})") from None
        body = _redact(body, credential.api_key)
        if not 200 <= response.status_code < 300:
            return {"status": "error", "http_status": response.status_code, "error": body}
        if not isinstance(body, (dict, list)):
            raise ValueError("LeadMagic returned an unexpected response shape")
        if isinstance(body, dict) and (body.get("error") or body.get("success") is False):
            return {"status": "error", "http_status": response.status_code, "error": body}
        if config.operation == "check_credits" and (not isinstance(body, dict) or type(body.get("credits")) not in (int, float)):
            raise ValueError("LeadMagic did not return a credit balance")
        return {"status": "success", "operation": config.operation, "http_status": response.status_code, "data": body}
