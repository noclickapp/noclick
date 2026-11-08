"""Affinda v3 document processing and account resources.

Contract: https://api.affinda.com/static/v3/api_spec.yaml (v3).
Each operation makes one request. Lists return one provider page; next URLs are
metadata only and are never followed with the credential.
"""
from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret


Identifier = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")]


class AffindaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Affinda API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.affinda.com/",
            "x-credential-instructions": "Paste your API key from Settings in the Affinda web app. Choose the region matching your account's app URL: Global (app.affinda.com), US (app.us1.affinda.com), or EU (app.eu1.affinda.com). NoClick sends the key as a Bearer token only to that region's Affinda API. Document parsing consumes your Affinda credits."})
    credential_type: Literal["affinda_api_key"] = Field("affinda_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})
    region: Literal["api", "api.us1", "api.eu1"] = Field("api", title="Region", description="api = Global / Australia; api.us1 = US; api.eu1 = EU")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste only the Affinda API key")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListDocuments(Input):
    """Return one page of documents, optionally including parsed data."""
    operation: Literal["list_documents"] = "list_documents"
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0)
    workspace: Identifier | None = None
    collection: Identifier | None = None
    state: Literal["uploaded", "review", "validated", "archived", "rejected"] | None = None
    search: str | None = None
    custom_identifier: str | None = None
    include_data: bool | None = None
    ready: bool | None = None
    failed: bool | None = None


class GetDocument(Input):
    operation: Literal["get_document"] = "get_document"
    identifier: Identifier
    compact: bool | None = None


class CreateDocument(Input):
    """Have Affinda fetch and parse a document URL; consumes parsing credits."""
    operation: Literal["create_document"] = "create_document"
    url: HttpUrl = Field(..., description="Public document URL fetched by Affinda, for example https://api.affinda.com/static/sample_resumes/example.docx")
    workspace: Identifier = Field(..., description="Workspace to receive the document")
    collection: Identifier | None = None
    document_type: Identifier | None = None
    file_name: str | None = None
    custom_identifier: str | None = None


class UpdateDocument(Input):
    operation: Literal["update_document"] = "update_document"
    identifier: Identifier
    workspace: Identifier | None = None
    collection: Identifier | None = None
    document_type: Identifier | None = None
    file_name: str | None = None
    custom_identifier: str | None = None
    is_confirmed: bool | None = None
    is_rejected: bool | None = None
    is_archived: bool | None = None

    @model_validator(mode="after")
    def changes(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "identifier"}):
            raise ValueError("Provide at least one document field to update")
        return self


class DeleteDocument(Input):
    """Permanently delete the selected document."""
    operation: Literal["delete_document"] = "delete_document"
    identifier: Identifier


class ListWorkspaces(Input):
    operation: Literal["list_workspaces"] = "list_workspaces"
    organization: Identifier
    name: str | None = None


class GetWorkspace(Input):
    operation: Literal["get_workspace"] = "get_workspace"
    identifier: Identifier


class ListCollections(Input):
    operation: Literal["list_collections"] = "list_collections"
    workspace: Identifier


class GetCollection(Input):
    operation: Literal["get_collection"] = "get_collection"
    identifier: Identifier


class ListDocumentTypes(Input):
    operation: Literal["list_document_types"] = "list_document_types"
    organization: Identifier | None = None
    workspace: Identifier | None = None


class GetDocumentType(Input):
    operation: Literal["get_document_type"] = "get_document_type"
    identifier: Identifier


class ListTags(Input):
    operation: Literal["list_tags"] = "list_tags"
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0)
    workspace: Identifier | None = None
    name: str | None = None


class GetTag(Input):
    operation: Literal["get_tag"] = "get_tag"
    id: int = Field(..., ge=1)


class CreateTag(Input):
    operation: Literal["create_tag"] = "create_tag"
    name: str = Field(..., min_length=1)
    workspace: Identifier


class UpdateTag(Input):
    operation: Literal["update_tag"] = "update_tag"
    id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1)
    workspace: Identifier | None = None


class DeleteTag(Input):
    operation: Literal["delete_tag"] = "delete_tag"
    id: int = Field(..., ge=1)


class AddTagToDocuments(Input):
    operation: Literal["add_tag_to_documents"] = "add_tag_to_documents"
    identifiers: list[Identifier] = Field(..., min_length=1, max_length=100)
    tag: int = Field(..., ge=1)


class RemoveTagFromDocuments(Input):
    operation: Literal["remove_tag_from_documents"] = "remove_tag_from_documents"
    identifiers: list[Identifier] = Field(..., min_length=1, max_length=100)
    tag: int = Field(..., ge=1)


class ListOrganizations(Input):
    operation: Literal["list_organizations"] = "list_organizations"


class GetOrganization(Input):
    operation: Literal["get_organization"] = "get_organization"
    identifier: Identifier


class GetUsage(Input):
    operation: Literal["get_usage"] = "get_usage"
    organization: Identifier
    workspace: Identifier | None = None
    document_type: Identifier | None = None
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def dates(self):
        if self.start and self.end and self.start > self.end:
            raise ValueError("End must be on or after start")
        return self


Operation = Annotated[Union[ListDocuments, GetDocument, CreateDocument, UpdateDocument,
    DeleteDocument, ListWorkspaces, GetWorkspace, ListCollections, GetCollection,
    ListDocumentTypes, GetDocumentType, ListTags, GetTag, CreateTag, UpdateTag,
    DeleteTag, AddTagToDocuments, RemoveTagFromDocuments, ListOrganizations,
    GetOrganization, GetUsage], Field(discriminator="operation")]


class AffindaNodeConfig(NodeConfig[Operation, AffindaAPIKeyCredential]):
    pass


# Fixed routes mirror the pinned v3 operation catalog, including numeric tag IDs.
ROUTES = {
    "list_documents": ("GET", "/documents"),
    "get_document": ("GET", "/documents/{identifier}"),
    "create_document": ("POST", "/documents"),
    "update_document": ("PATCH", "/documents/{identifier}"),
    "delete_document": ("DELETE", "/documents/{identifier}"),
    "list_workspaces": ("GET", "/workspaces"),
    "get_workspace": ("GET", "/workspaces/{identifier}"),
    "list_collections": ("GET", "/collections"),
    "get_collection": ("GET", "/collections/{identifier}"),
    "list_document_types": ("GET", "/document_types"),
    "get_document_type": ("GET", "/document_types/{identifier}"),
    "list_tags": ("GET", "/tags"),
    "get_tag": ("GET", "/tags/{id}"),
    "create_tag": ("POST", "/tags"),
    "update_tag": ("PATCH", "/tags/{id}"),
    "delete_tag": ("DELETE", "/tags/{id}"),
    "add_tag_to_documents": ("POST", "/documents/batch_add_tag"),
    "remove_tag_from_documents": ("POST", "/documents/batch_remove_tag"),
    "list_organizations": ("GET", "/organizations"),
    "get_organization": ("GET", "/organizations/{identifier}"),
    "get_usage": ("GET", "/usage"),
}
WIRE_NAMES = {"document_type": "documentType", "file_name": "fileName",
    "custom_identifier": "customIdentifier", "is_confirmed": "isConfirmed",
    "is_rejected": "isRejected", "is_archived": "isArchived"}


def _public_data(value):
    # Organization responses include a webhook signing secret, including when
    # nested in other resources. It is never a workflow output.
    if isinstance(value, dict):
        return {k: _public_data(v) for k, v in value.items() if k != "resthookSignatureKey"}
    if isinstance(value, list):
        return [_public_data(v) for v in value]
    return value


class AffindaNode(WorkflowNode):
    integration_type = "automation-affinda"
    connection_evidence = ConnectionEvidence(operation="list_organizations", noun="Affinda organizations", label_keys=("name", "identifier"))

    @classmethod
    def get_config_model(cls):
        return AffindaNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Affinda API key")
        credential = self.config.credentials
        op = self.config.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for key in ("identifier", "id"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        params, body, files = None, None, None
        if method == "GET":
            # Query parameters are snake_case, unlike JSON/multipart properties.
            params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
            if op.operation == "get_document":
                params["format"] = "json"
        elif method != "DELETE":
            body = {WIRE_NAMES.get(k, k): v for k, v in values.items()}
            if op.operation == "create_document":
                # Tuple fields without filenames force multipart even for URL uploads.
                files = {k: (None, str(v).lower() if isinstance(v, bool) else str(v)) for k, v in body.items()}
                body = None
        async with httpx.AsyncClient(timeout=120, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, f"https://{credential.region}.affinda.com/v3" + path,
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"},
                params=params, json=body, files=files)
        if not 200 <= response.status_code < 300:
            message = response.text.replace(credential.api_key, "[redacted]")[:1000]
            raise ValueError(f"Affinda HTTP {response.status_code}: {message}")
        if response.status_code == 204:
            data = {"acknowledged": True}
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Affinda returned an invalid JSON response") from None
            if not isinstance(data, (dict, list)):
                raise ValueError("Affinda returned an unexpected response shape")
        output = {"status": "success", "data": _public_data(data)}
        await self.emit(output)
        return output
