"""Invofox document processing and company collections, API contract v1.0.0.

Each operation issues one request to the published api.invofox.com endpoint.
URL uploads are asynchronous: their acknowledgement is returned unchanged;
get_file/get_import track processing rather than claiming an extraction finished.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.invofox.com"


class InvofoxAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Invofox API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.invofox.com/",
            "x-credential-instructions": "In Invofox, open your environment's API and Webhooks and create or copy an API key. Paste the key here. The key selects the account and environment; NoClick sends it in the x-api-key header.",
        })
    credential_type: Literal["invofox_api_key"] = Field("invofox_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without header names or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def ids(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
                raise ValueError("Use a single Invofox resource ID")
        return value


class Page(Input):
    skip: int = Field(0, ge=0, description="Number of records to skip. This operation returns one page.")
    limit: int = Field(50, ge=1, le=500, description="Maximum records on this page.")


class DocumentID(Input):
    document_id: str = Field(..., min_length=1, description="Invofox document ID.")


class CompanyID(Input):
    company_id: str = Field(..., min_length=1, description="Invofox company ID.")


class Enterprise(Input):
    country_code: str = Field(..., pattern=r"^[A-Z]{2}$", description="ISO 3166-1 alpha-2 country code.")
    tax_id: str = Field(..., min_length=1, description="Tax ID number.")
    name: str = Field(..., min_length=1, description="Business name.")


class ListDocuments(Page):
    """Read a page of documents, optionally filtering the extracted fields."""
    operation: Literal["list_documents"] = "list_documents"
    filter: str | None = Field(None, description="JSON-encoded Invofox document filter.")
    sort: str | None = Field(None, description="JSON-encoded sort expression.")
    select: list[str] | None = Field(None, description="Document fields to select.")


class GetDocument(DocumentID):
    """Get structured extraction data and processing state for one document."""
    operation: Literal["get_document"] = "get_document"


class UpdateDocument(DocumentID):
    """Correct extracted values or merge custom client metadata."""
    operation: Literal["update_document"] = "update_document"
    data: dict[str, dict[str, str]] | None = Field(None, description='Corrected fields, each containing a string value, e.g. {"invoiceNumber": {"value": "INV-001"}}.')
    client_data: dict[str, Any] | None = Field(None, description="Metadata merged recursively; arrays replace, null values are stored, omitted keys remain.")

    @model_validator(mode="after")
    def changed(self):
        if self.data is None and self.client_data is None:
            raise ValueError("Supply corrected data or client metadata")
        if self.data is not None and any(set(v) != {"value"} for v in self.data.values()):
            raise ValueError("Each corrected field must contain a value")
        return self


class GetDocumentOCR(DocumentID):
    """Get OCR geometry and text per page."""
    operation: Literal["get_document_ocr"] = "get_document_ocr"


class GetDocumentText(DocumentID):
    """Get plain OCR text per page."""
    operation: Literal["get_document_text"] = "get_document_text"


class ChangeDocumentType(DocumentID):
    """Set the document type by ID or environment alias."""
    operation: Literal["change_document_type"] = "change_document_type"
    document_type: str = Field(..., min_length=1, description="Document type ID or alias, such as invoice or receipt.")


class ChangeDocumentState(DocumentID):
    """Change the document's public review or export state."""
    operation: Literal["change_document_state"] = "change_document_state"
    public_state: Literal["pendingCorrection", "discarded", "approved", "exported"]


class ListCompanies(Page):
    """Read a page of companies managed by this account."""
    operation: Literal["list_companies"] = "list_companies"
    country_code: str | None = None
    tax_id: str | None = None
    name: str | None = None


class CreateCompany(Enterprise):
    """Create a managed company."""
    operation: Literal["create_company"] = "create_company"
    client_data: dict[str, Any] | None = None


class UpdateCompany(Enterprise, CompanyID):
    """Replace the company name, country and tax ID."""
    operation: Literal["update_company"] = "update_company"


class DeleteCompany(CompanyID):
    """Delete the selected managed company."""
    operation: Literal["delete_company"] = "delete_company"


class ListProviders(Page, CompanyID):
    """Read a page of providers linked to a company."""
    operation: Literal["list_providers"] = "list_providers"
    tax_id: str | None = None
    name: str | None = None


class CreateProvider(Enterprise, CompanyID):
    """Create a provider linked to a company."""
    operation: Literal["create_provider"] = "create_provider"


class UpdateProvider(Enterprise, CompanyID):
    """Update the selected provider's business details."""
    operation: Literal["update_provider"] = "update_provider"
    provider_id: str = Field(..., min_length=1)


class DeleteProvider(CompanyID):
    """Delete the selected provider from a company."""
    operation: Literal["delete_provider"] = "delete_provider"
    provider_id: str = Field(..., min_length=1)


class ListClients(CompanyID):
    """Read clients linked to a company; this endpoint has no paging parameters."""
    operation: Literal["list_clients"] = "list_clients"


class CreateClient(CompanyID):
    """Create a client linked to a company."""
    operation: Literal["create_client"] = "create_client"
    country_code: str = Field(..., pattern=r"^[A-Z]{2}$")
    name: str = Field(..., min_length=1)
    tax_id: str | None = None


class UpdateClient(Enterprise, CompanyID):
    """Update the selected client's business details."""
    operation: Literal["update_client"] = "update_client"
    client_id: str = Field(..., min_length=1)


class DeleteClient(CompanyID):
    """Delete the selected client from a company."""
    operation: Literal["delete_client"] = "delete_client"
    client_id: str = Field(..., min_length=1)


class FileMetadata(Input):
    useSplitter: bool | None = None
    type: str | None = Field(None, description="Required unless the environment has a classifier or default type.")
    data: dict[str, Any] | None = None
    clientData: dict[str, Any] | None = None
    company: str | None = Field(None, description="Company context applies to the whole batch.")


class FileURL(Input):
    url: str = Field(..., description="HTTPS URL of the file Invofox should download.")
    filename: str | None = None

    @field_validator("url")
    @classmethod
    def https(cls, value):
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError("Use an HTTPS file URL without embedded credentials")
        return value


class PerFileMetadata(Input):
    useSplitter: bool | None = None
    type: str | None = None
    data: dict[str, Any] | None = None
    clientData: dict[str, Any] | None = None


class BatchFile(FileURL):
    info: PerFileMetadata | None = None


class UploadFilesByURL(Input):
    """Queue files for download and processing, with batch company context."""
    operation: Literal["upload_files_by_url"] = "upload_files_by_url"
    files: list[BatchFile] = Field(..., min_length=1)
    info: FileMetadata | None = None


class UploadSingleByURL(FileURL):
    """Queue a single document without splitting (deprecated by Invofox; prefer batch URL upload)."""
    operation: Literal["upload_single_by_url"] = "upload_single_by_url"
    info: FileMetadata | None = None


class GetFile(Input):
    """Get file status and extracted document IDs."""
    operation: Literal["get_file"] = "get_file"
    file_id: str = Field(..., min_length=1)


class ListImports(Input):
    """Read one page of imports for this environment."""
    operation: Literal["list_imports"] = "list_imports"
    environment_id: str | None = None
    skip: int = Field(0, ge=0, le=10)
    limit: int = Field(5, ge=1, le=15)


class GetImport(Input):
    """Get import progress, files and extracted document count."""
    operation: Literal["get_import"] = "get_import"
    import_id: str = Field(..., min_length=1)


InvofoxConfig = Annotated[Union[
    ListDocuments, GetDocument, UpdateDocument, GetDocumentOCR, GetDocumentText,
    ChangeDocumentType, ChangeDocumentState, ListCompanies, CreateCompany,
    UpdateCompany, DeleteCompany, ListProviders, CreateProvider, UpdateProvider,
    DeleteProvider, ListClients, CreateClient, UpdateClient, DeleteClient,
    UploadFilesByURL, UploadSingleByURL, GetFile, ListImports, GetImport,
], Field(discriminator="operation")]


class InvofoxNodeConfig(NodeConfig[InvofoxConfig, InvofoxAPIKeyCredential]):
    pass


# Closed route table: every node operation corresponds to one published operation.
ROUTES = {
    "list_documents": ("GET", "/documents"),
    "get_document": ("GET", "/documents/{document_id}"),
    "update_document": ("PUT", "/documents/{document_id}"),
    "get_document_ocr": ("GET", "/documents/{document_id}/ocr"),
    "get_document_text": ("GET", "/documents/{document_id}/text"),
    "change_document_type": ("PUT", "/documents/{document_id}/type"),
    "change_document_state": ("PUT", "/documents/{document_id}/publicState"),
    "list_companies": ("GET", "/companies"),
    "create_company": ("POST", "/companies"),
    "update_company": ("PUT", "/companies/{company_id}"),
    "delete_company": ("DELETE", "/companies/{company_id}"),
    "list_providers": ("GET", "/companies/{company_id}/providers"),
    "create_provider": ("POST", "/companies/{company_id}/providers"),
    "update_provider": ("PUT", "/companies/{company_id}/providers/{provider_id}"),
    "delete_provider": ("DELETE", "/companies/{company_id}/providers/{provider_id}"),
    "list_clients": ("GET", "/companies/{company_id}/clients"),
    "create_client": ("POST", "/companies/{company_id}/clients"),
    "update_client": ("PUT", "/companies/{company_id}/clients/{client_id}"),
    "delete_client": ("DELETE", "/companies/{company_id}/clients/{client_id}"),
    "upload_files_by_url": ("POST", "/v1/ingest/by-url"),
    "upload_single_by_url": ("POST", "/v1/ingest/single-url"),
    "get_file": ("GET", "/v1/ingest/files/{file_id}"),
    "list_imports": ("GET", "/v1/ingest/imports"),
    "get_import": ("GET", "/v1/ingest/imports/{import_id}"),
}
WIRE_FIELDS = {"country_code": "countryCode", "tax_id": "taxId", "client_data": "clientData",
    "document_type": "type", "public_state": "publicState", "environment_id": "environmentId"}


class InvofoxNode(WorkflowNode):
    integration_type = "automation-invofox"
    connection_evidence = ConnectionEvidence(operation="list_companies", noun="companies", label_keys=("name", "taxId", "_id"))

    @classmethod
    def get_config_model(cls):
        return InvofoxNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Invofox API key")
        config = self.config.config
        method, template = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        values.pop("operation")
        for key in re.findall(r"{(\w+)}", template):
            template = template.replace("{" + key + "}", quote(values.pop(key), safe=""))
        payload = {WIRE_FIELDS.get(k, k): v for k, v in values.items()}
        key = self.config.credentials.api_key
        async with guarded_async_client(timeout=60.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + template,
                headers={"x-api-key": key, "Accept": "application/json"},
                params=payload if method == "GET" else None,
                json=payload if method in {"POST", "PUT"} else None)
        if response.is_redirect:
            raise ValueError("Invofox redirected the API request")
        if response.is_error:
            # Keep provider rejection text available to the connection seam; redact keys.
            text = response.text[:2000].replace(key, "[redacted]")
            raise ValueError(f"Invofox HTTP {response.status_code}: {text}")
        if "application/json" not in response.headers.get("content-type", "").lower():
            raise ValueError("Invofox returned a non-JSON response")
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Invofox returned an unexpected response shape")
        # File status has a documented 'error' property, which is domain data.
        if result.get("code") or (result.get("error") and config.operation != "get_file"):
            raise ValueError("Invofox rejected the request: " + json.dumps(result)[:2000].replace(key, "[redacted]"))
        return {"file": result} if config.operation == "get_file" else result
