"""Simpro v1.0 operations using a user-supplied API key and build URL.

Routes and write fields are explicit so every operation corresponds to one
published endpoint. Company listing supplies account-specific connection evidence.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class SimproAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Simpro API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.simprogroup.com/apidoc/#tag/API-key-workflow",
            "x-credential-instructions": "In Simpro, open System > Setup > API > Applications and request API Key access. Paste the access token from the key file and your build URL. The key's application permissions must allow the operations you use. Company listing verifies the connection."
        })
    credential_type: Literal["simpro_api_key"] = Field("simpro_api_key", json_schema_extra={"ui:hidden": True})
    build_url: str = Field(..., title="Build URL", description="Your HTTPS Simpro build, for example https://example.simprosuite.com or https://example.simprocloud.com.")
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("build_url", mode="before")
    @classmethod
    def build(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your HTTPS Simpro build URL")
        value = value.strip()
        if not re.fullmatch(r"https://[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.(?:simprosuite|simprocloud)\.com/?", value):
            raise ValueError("Use an HTTPS build on simprosuite.com or simprocloud.com without a path, port or query")
        return value.rstrip("/").lower()

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Company(_Input):
    company_id: int = Field(..., ge=0, description="Company ID from List Companies; single-company builds use 0.")


class _Page(_Company):
    page: int = Field(1, ge=1, description="One-based page to fetch. Follow next_page in the output.")
    page_size: int = Field(30, ge=1, le=250, description="Maximum records in this page, up to 250.")


class _Write(_Company):
    @model_validator(mode="after")
    def nonempty_patch(self):
        if self.operation.startswith("update_"):
            values = self.model_dump(exclude_none=True)
            if not (values.keys() - {"operation", "company_id", "customer_id", "contact_id", "site_id", "job_id", "quote_id"}):
                raise ValueError("Supply at least one field to update")
        return self


class SimproListCompaniesConfig(_Input):
    """List companies with one Simpro API request."""
    operation: Literal["list_companies"] = Field("list_companies", json_schema_extra={"ui:hidden": True})


class SimproGetCompanyConfig(_Company):
    """Get company with one Simpro API request."""
    operation: Literal["get_company"] = Field("get_company", json_schema_extra={"ui:hidden": True})


class SimproListCustomersConfig(_Page):
    """List customers with one Simpro API request."""
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})


class SimproListCompanyCustomersConfig(_Page):
    """List company customers with one Simpro API request."""
    operation: Literal["list_company_customers"] = Field("list_company_customers", json_schema_extra={"ui:hidden": True})


class SimproGetCompanyCustomerConfig(_Company):
    """Get company customer with one Simpro API request."""
    operation: Literal["get_company_customer"] = Field("get_company_customer", json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1)


class SimproCreateCompanyCustomerConfig(_Write):
    """Create company customer with one Simpro API request."""
    operation: Literal["create_company_customer"] = Field("create_company_customer", json_schema_extra={"ui:hidden": True})
    company_name: str = Field(..., min_length=1)
    email: str | None = Field(None)
    phone: str | None = Field(None)
    website: str | None = Field(None)


class SimproUpdateCompanyCustomerConfig(_Write):
    """Update company customer with one Simpro API request."""
    operation: Literal["update_company_customer"] = Field("update_company_customer", json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1)
    company_name: str | None = Field(None)
    email: str | None = Field(None)
    phone: str | None = Field(None)
    website: str | None = Field(None)


class SimproListContactsConfig(_Page):
    """List contacts with one Simpro API request."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})


class SimproGetContactConfig(_Company):
    """Get contact with one Simpro API request."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., ge=1)


class SimproCreateContactConfig(_Write):
    """Create contact with one Simpro API request."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    given_name: str = Field(..., min_length=1)
    family_name: str | None = Field(None)
    email: str | None = Field(None)
    work_phone: str | None = Field(None)
    cell_phone: str | None = Field(None)
    position: str | None = Field(None)


class SimproUpdateContactConfig(_Write):
    """Update contact with one Simpro API request."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., ge=1)
    given_name: str | None = Field(None)
    family_name: str | None = Field(None)
    email: str | None = Field(None)
    work_phone: str | None = Field(None)
    cell_phone: str | None = Field(None)
    position: str | None = Field(None)


class SimproListSitesConfig(_Page):
    """List sites with one Simpro API request."""
    operation: Literal["list_sites"] = Field("list_sites", json_schema_extra={"ui:hidden": True})


class SimproGetSiteConfig(_Company):
    """Get site with one Simpro API request."""
    operation: Literal["get_site"] = Field("get_site", json_schema_extra={"ui:hidden": True})
    site_id: int = Field(..., ge=1)


class SimproCreateSiteConfig(_Write):
    """Create site with one Simpro API request."""
    operation: Literal["create_site"] = Field("create_site", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    public_notes: str | None = Field(None)
    private_notes: str | None = Field(None)


class SimproUpdateSiteConfig(_Write):
    """Update site with one Simpro API request."""
    operation: Literal["update_site"] = Field("update_site", json_schema_extra={"ui:hidden": True})
    site_id: int = Field(..., ge=1)
    name: str | None = Field(None)
    public_notes: str | None = Field(None)
    private_notes: str | None = Field(None)


class SimproListJobsConfig(_Page):
    """List jobs with one Simpro API request."""
    operation: Literal["list_jobs"] = Field("list_jobs", json_schema_extra={"ui:hidden": True})


class SimproGetJobConfig(_Company):
    """Get job with one Simpro API request."""
    operation: Literal["get_job"] = Field("get_job", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., ge=1)


class SimproCreateJobConfig(_Write):
    """Create job with one Simpro API request."""
    operation: Literal["create_job"] = Field("create_job", json_schema_extra={"ui:hidden": True})
    job_type: Literal["Project", "Service", "Prepaid"] = Field(...)
    site: int = Field(..., ge=1)
    customer: int | None = Field(None, ge=1)
    name: str | None = Field(None)
    description: str | None = Field(None)
    notes: str | None = Field(None)
    order_no: str | None = Field(None)
    stage: Literal["Pending", "Progress", "Complete", "Archived"] | None = Field(None)
    status_id: int | None = Field(None, ge=1)


class SimproUpdateJobConfig(_Write):
    """Update job with one Simpro API request."""
    operation: Literal["update_job"] = Field("update_job", json_schema_extra={"ui:hidden": True})
    job_id: int = Field(..., ge=1)
    site: int | None = Field(None, ge=1)
    customer: int | None = Field(None, ge=1)
    name: str | None = Field(None)
    description: str | None = Field(None)
    notes: str | None = Field(None)
    order_no: str | None = Field(None)
    stage: Literal["Pending", "Progress", "Complete", "Archived"] | None = Field(None)
    status_id: int | None = Field(None, ge=1)


class SimproListQuotesConfig(_Page):
    """List quotes with one Simpro API request."""
    operation: Literal["list_quotes"] = Field("list_quotes", json_schema_extra={"ui:hidden": True})


class SimproGetQuoteConfig(_Company):
    """Get quote with one Simpro API request."""
    operation: Literal["get_quote"] = Field("get_quote", json_schema_extra={"ui:hidden": True})
    quote_id: int = Field(..., ge=1)


class SimproCreateQuoteConfig(_Write):
    """Create quote with one Simpro API request."""
    operation: Literal["create_quote"] = Field("create_quote", json_schema_extra={"ui:hidden": True})
    quote_type: Literal["Project", "Service", "Prepaid"] = Field(...)
    customer: int = Field(..., ge=1)
    site: int = Field(..., ge=1)
    name: str | None = Field(None)
    description: str | None = Field(None)
    notes: str | None = Field(None)
    order_no: str | None = Field(None)
    stage: Literal["InProgress", "Complete", "Approved"] | None = Field(None)
    status_id: int | None = Field(None, ge=1)


class SimproUpdateQuoteConfig(_Write):
    """Update quote with one Simpro API request."""
    operation: Literal["update_quote"] = Field("update_quote", json_schema_extra={"ui:hidden": True})
    quote_id: int = Field(..., ge=1)
    customer: int | None = Field(None, ge=1)
    site: int | None = Field(None, ge=1)
    name: str | None = Field(None)
    description: str | None = Field(None)
    notes: str | None = Field(None)
    order_no: str | None = Field(None)
    stage: Literal["InProgress", "Complete", "Approved"] | None = Field(None)
    status_id: int | None = Field(None, ge=1)


class SimproListInvoicesConfig(_Page):
    """List invoices with one Simpro API request."""
    operation: Literal["list_invoices"] = Field("list_invoices", json_schema_extra={"ui:hidden": True})


class SimproGetInvoiceConfig(_Company):
    """Get invoice with one Simpro API request."""
    operation: Literal["get_invoice"] = Field("get_invoice", json_schema_extra={"ui:hidden": True})
    invoice_id: int = Field(..., ge=1)


SimproConfig = Annotated[Union[
    SimproListCompaniesConfig,
    SimproGetCompanyConfig,
    SimproListCustomersConfig,
    SimproListCompanyCustomersConfig,
    SimproGetCompanyCustomerConfig,
    SimproCreateCompanyCustomerConfig,
    SimproUpdateCompanyCustomerConfig,
    SimproListContactsConfig,
    SimproGetContactConfig,
    SimproCreateContactConfig,
    SimproUpdateContactConfig,
    SimproListSitesConfig,
    SimproGetSiteConfig,
    SimproCreateSiteConfig,
    SimproUpdateSiteConfig,
    SimproListJobsConfig,
    SimproGetJobConfig,
    SimproCreateJobConfig,
    SimproUpdateJobConfig,
    SimproListQuotesConfig,
    SimproGetQuoteConfig,
    SimproCreateQuoteConfig,
    SimproUpdateQuoteConfig,
    SimproListInvoicesConfig,
    SimproGetInvoiceConfig
], Field(discriminator="operation")]


class SimproFullConfig(NodeConfig[SimproConfig, SimproAPIKeyCredential]):
    pass


ROUTES = {'list_companies': ('GET', '/api/v1.0/companies/', {}),
 'get_company': ('GET', '/api/v1.0/companies/{company_id}', {}),
 'list_customers': ('GET', '/api/v1.0/companies/{company_id}/customers/', {}),
 'list_company_customers': ('GET', '/api/v1.0/companies/{company_id}/customers/companies/', {}),
 'get_company_customer': ('GET',
                          '/api/v1.0/companies/{company_id}/customers/companies/{customer_id}',
                          {}),
 'create_company_customer': ('POST',
                             '/api/v1.0/companies/{company_id}/customers/companies/',
                             {'company_name': 'CompanyName',
                              'email': 'Email',
                              'phone': 'Phone',
                              'website': 'Website'}),
 'update_company_customer': ('PATCH',
                             '/api/v1.0/companies/{company_id}/customers/companies/{customer_id}',
                             {'company_name': 'CompanyName',
                              'email': 'Email',
                              'phone': 'Phone',
                              'website': 'Website'}),
 'list_contacts': ('GET', '/api/v1.0/companies/{company_id}/contacts/', {}),
 'get_contact': ('GET', '/api/v1.0/companies/{company_id}/contacts/{contact_id}', {}),
 'create_contact': ('POST',
                    '/api/v1.0/companies/{company_id}/contacts/',
                    {'given_name': 'GivenName',
                     'family_name': 'FamilyName',
                     'email': 'Email',
                     'work_phone': 'WorkPhone',
                     'cell_phone': 'CellPhone',
                     'position': 'Position'}),
 'update_contact': ('PATCH',
                    '/api/v1.0/companies/{company_id}/contacts/{contact_id}',
                    {'given_name': 'GivenName',
                     'family_name': 'FamilyName',
                     'email': 'Email',
                     'work_phone': 'WorkPhone',
                     'cell_phone': 'CellPhone',
                     'position': 'Position'}),
 'list_sites': ('GET', '/api/v1.0/companies/{company_id}/sites/', {}),
 'get_site': ('GET', '/api/v1.0/companies/{company_id}/sites/{site_id}', {}),
 'create_site': ('POST',
                 '/api/v1.0/companies/{company_id}/sites/',
                 {'name': 'Name', 'public_notes': 'PublicNotes', 'private_notes': 'PrivateNotes'}),
 'update_site': ('PATCH',
                 '/api/v1.0/companies/{company_id}/sites/{site_id}',
                 {'name': 'Name', 'public_notes': 'PublicNotes', 'private_notes': 'PrivateNotes'}),
 'list_jobs': ('GET', '/api/v1.0/companies/{company_id}/jobs/', {}),
 'get_job': ('GET', '/api/v1.0/companies/{company_id}/jobs/{job_id}', {}),
 'create_job': ('POST',
                '/api/v1.0/companies/{company_id}/jobs/',
                {'job_type': 'Type',
                 'site': 'Site',
                 'customer': 'Customer',
                 'name': 'Name',
                 'description': 'Description',
                 'notes': 'Notes',
                 'order_no': 'OrderNo',
                 'stage': 'Stage',
                 'status_id': 'Status'}),
 'update_job': ('PATCH',
                '/api/v1.0/companies/{company_id}/jobs/{job_id}',
                {'site': 'Site',
                 'customer': 'Customer',
                 'name': 'Name',
                 'description': 'Description',
                 'notes': 'Notes',
                 'order_no': 'OrderNo',
                 'stage': 'Stage',
                 'status_id': 'Status'}),
 'list_quotes': ('GET', '/api/v1.0/companies/{company_id}/quotes/', {}),
 'get_quote': ('GET', '/api/v1.0/companies/{company_id}/quotes/{quote_id}', {}),
 'create_quote': ('POST',
                  '/api/v1.0/companies/{company_id}/quotes/',
                  {'quote_type': 'Type',
                   'customer': 'Customer',
                   'site': 'Site',
                   'name': 'Name',
                   'description': 'Description',
                   'notes': 'Notes',
                   'order_no': 'OrderNo',
                   'stage': 'Stage',
                   'status_id': 'Status'}),
 'update_quote': ('PATCH',
                  '/api/v1.0/companies/{company_id}/quotes/{quote_id}',
                  {'customer': 'Customer',
                   'site': 'Site',
                   'name': 'Name',
                   'description': 'Description',
                   'notes': 'Notes',
                   'order_no': 'OrderNo',
                   'stage': 'Stage',
                   'status_id': 'Status'}),
 'list_invoices': ('GET', '/api/v1.0/companies/{company_id}/invoices/', {}),
 'get_invoice': ('GET', '/api/v1.0/companies/{company_id}/invoices/{invoice_id}', {})}


class SimproNode(WorkflowNode):
    integration_type = "automation-simpro"
    connection_evidence = ConnectionEvidence(noun="companies", operation="list_companies", label_keys=("Name", "ID"))

    @classmethod
    def get_config_model(cls):
        return SimproFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Simpro API key")
        credential = self.config.credentials
        config = self.config.config
        values = config.model_dump(exclude_none=True)
        method, template, fields = ROUTES[config.operation]
        path = template.format(**values)
        params = {}
        if isinstance(config, _Page):
            params = {"page": config.page, "pageSize": config.page_size}
        body = {wire: values[key] for key, wire in fields.items() if key in values}
        headers = {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json", "Content-Type": "application/json"}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, credential.build_url + path, params=params,
                headers=headers, **({"json": body} if method in {"POST", "PATCH"} else {}))
        expected_status = {"GET": 200, "POST": 201, "PATCH": 204}[method]
        if response.status_code != expected_status:
            # Preserve provider diagnostics for connect while removing an echoed key.
            message = response.text[:2000].replace(credential.api_key, "[redacted]")
            raise ValueError(f"Simpro HTTP {response.status_code}: {message}")
        if response.status_code == 204:
            return {"success": True, "operation": config.operation, "http_status": 204}
        if len(response.content) > 10_000_000 or "json" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("Expected a bounded Simpro JSON response")
        data = response.json()
        if isinstance(data, dict) and any(key in data for key in ("errors", "error")):
            raise ValueError("Simpro returned an error response")
        output = {"success": True, "operation": config.operation, "data": data}
        if config.operation.startswith("list_"):
            if not isinstance(data, list) or any(not isinstance(row, dict) or "ID" not in row for row in data):
                raise ValueError("Expected a Simpro resource list")
            output["items"] = data
            pages = response.headers.get("Result-Pages")
            total = response.headers.get("Result-Total")
            output["total"] = int(total) if total is not None else None
            output["next_page"] = config.page + 1 if isinstance(config, _Page) and pages is not None and config.page < int(pages) else None
        elif not isinstance(data, dict):
            raise ValueError("Expected a Simpro resource object")
        return output
