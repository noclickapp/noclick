"""Active Merge document automation using the published API v1.0.0.

API reference: https://app.activemerge.com/docs?api-docs.json
JSON operations return provider data unchanged; jobs are submitted once and never
retried or polled implicitly. Download URLs remain URLs and are not followed.
"""
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class ActiveMergeAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Active Merge API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.activemerge.com/docs",
            "x-credential-instructions": "Paste your Active Merge API key. NoClick sends it in the API-KEY header to app.activemerge.com. The connection check reads your account credits."})
    credential_type: Literal["active_merge_api_key"] = Field("active_merge_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without whitespace or a header")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class SignerInput(Input):
    email: str = Field(..., description="Signer's email. Use {{ColumnName}} to reference a data field, or 'me' for the authenticated user.", json_schema_extra={'format': 'email', 'examples': ['{{ClientEmail}}']})
    first_name: str | None = Field(None, description="First name. Supports {{ColumnName}} and 'me'.", json_schema_extra={'examples': ['{{ClientFirstName}}']})
    last_name: str | None = Field(None, description="Last name. Supports {{ColumnName}} and 'me'.", json_schema_extra={'examples': ['{{ClientLastName}}']})


class StandaloneSignerInput(Input):
    email: str = Field(..., description='', json_schema_extra={'format': 'email', 'examples': ['jane@acme.com']})
    first_name: str | None = Field(None, description='', json_schema_extra={'examples': ['Jane']})
    last_name: str | None = Field(None, description='', json_schema_extra={'examples': ['Smith']})


class SignConfigInput(Input):
    signers: list[SignerInput] = Field(..., description='List of signers. Order in array determines signing order when sequential=true.', min_length=1)
    title: str | None = Field(None, description='Signing request title. Supports {{ColumnName}} references.', json_schema_extra={'examples': ['Agreement — {{ClientName}}']})
    message: str | None = Field(None, description='Optional message shown to signers.', json_schema_extra={'examples': ['Please review and sign.']})
    expires_days: int | None = Field(None, description='Days until signing links expire. Default: 30.', json_schema_extra={'examples': [14]})
    sequential: bool | None = Field(None, description='When true, each signer is notified only after the previous has signed.', json_schema_extra={'examples': [False]})


class GenerateDocument(Input):
    """Generate a document based on the provided request data."""
    operation: Literal['generate_document'] = Field('generate_document', json_schema_extra={"ui:hidden": True})
    template_id: str = Field(..., description='The unique ID of the template to be used for document generation.', json_schema_extra={'examples': ['abc123']})
    data: dict[str, Any] = Field(..., description='An associative array of data to populate the template placeholders.', json_schema_extra={'examples': [{'ClientName': 'Acme Corp', 'ClientEmail': 'legal@acme.com'}]})
    format: Literal['pdf', 'docx', 'pptx'] = Field(..., description='The format of the document to be generated.', json_schema_extra={'examples': ['pdf']})
    sign_config: SignConfigInput | None = Field(None, description='Optional. When provided, the document is sent for e-signature immediately after generation.')


class GetGenerationStatus(Input):
    """Get the status of a single generation job."""
    operation: Literal['get_generation_status'] = Field('get_generation_status', json_schema_extra={"ui:hidden": True})
    job_id: str = Field(..., description='The job_id returned by POST /generate.')


class ListGenerationHistory(Input):
    """List generation history with optional filters."""
    operation: Literal['list_generation_history'] = Field('list_generation_history', json_schema_extra={"ui:hidden": True})
    job_id: str | None = Field(None, description='Filter by a specific job_id.')
    status: Literal['in_progress', 'completed', 'failed', 'expired'] | None = Field(None, description='Filter by status.')
    template_id: str | None = Field(None, description='Filter by template unique_id.')
    date_from: str | None = Field(None, description='Filter jobs created on or after this date (YYYY-MM-DD).', json_schema_extra={'format': 'date'})
    date_to: str | None = Field(None, description='Filter jobs created on or before this date (YYYY-MM-DD).', json_schema_extra={'format': 'date'})
    per_page: int | None = Field(None, description='Results per page (1-100, default 20).', ge=1)
    page: int | None = Field(None, description='Page number.', ge=1)


class MergeDocuments(Input):
    """Merge multiple documents into a single file."""
    operation: Literal['merge_documents'] = Field('merge_documents', json_schema_extra={"ui:hidden": True})
    file_urls: list[str] = Field(..., description='Alternative to files for JSON clients such as Airtable Automations. Public HTTPS file URLs only; do not send both files and file_urls.', min_length=2)
    format: Literal['pdf', 'docx', 'epub'] = Field(..., description="Output format. Use 'docx' or 'epub' to merge Word files without conversion. 'epub' requires Pandoc on the server.", json_schema_extra={'examples': ['pdf']})
    output_filename: str | None = Field(None, description="Optional filename for the output file (without extension). Max 100 characters. Only applies to 'docx' and 'epub' formats.", json_schema_extra={'examples': ['my_merged_document']})
    page_break: bool | None = Field(None, description="Insert an explicit page break between each merged document. Only applies to 'docx' and 'epub' formats.", json_schema_extra={'examples': [True]})
    continuous_numbering: bool | None = Field(None, description="Run page numbers continuously across all merged documents instead of restarting per section. Only applies to 'docx' and 'epub' formats.", json_schema_extra={'examples': [True]})
    strip_headers_footers: bool | None = Field(None, description="Use the first document's header and footer throughout, removing headers/footers from subsequent documents. Only applies to 'docx' and 'epub' formats.", json_schema_extra={'examples': [False]})

    @field_validator("file_urls")
    @classmethod
    def public_urls(cls, values):
        for value in values:
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Use public HTTPS document URLs")
        return values


class ListFiles(Input):
    """List files and folders for the authenticated user."""
    operation: Literal['list_files'] = Field('list_files', json_schema_extra={"ui:hidden": True})
    id: int | None = Field(None, description='Parent folder id to list (optional)')


class SaveFiles(Input):
    """Save a generated document to permanent file storage."""
    operation: Literal['save_files'] = Field('save_files', json_schema_extra={"ui:hidden": True})
    job_id: str = Field(..., description='The job_id returned from the document generation endpoint.', json_schema_extra={'examples': ['bd95b875-78f7-4bc6-b5cf-96bf520ac317']})
    folder_id: int | None = Field(None, description='ID of the folder to save into. Omit or null for root folder.')
    filename: str | None = Field(None, description='Optional custom filename (only applies to single-file jobs). Defaults to the generated filename.', json_schema_extra={'examples': ['contract_signed.pdf']})


class GetFileDownloadUrl(Input):
    """Get a temporary download URL for a file."""
    operation: Literal['get_file_download_url'] = Field('get_file_download_url', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='ID of the file to download')


class GenerateImages(Input):
    """Generate images."""
    operation: Literal['generate_images'] = Field('generate_images', json_schema_extra={"ui:hidden": True})
    template_id: int = Field(..., description='The ID of the image template to use.', json_schema_extra={'examples': [1]}, ge=1)
    field_mapping: dict[str, Any] = Field(..., description='Maps each template placeholder name to a data column name.', json_schema_extra={'examples': [{'Full_Name': 'name', 'Title': 'job_title'}]})
    data: list[dict[str, Any]] = Field(..., description="JSON array of data rows. Each row is an object with column names as keys. Provide either 'data' or 'data_file', not both.", min_length=1, max_length=2000)


class GetImageJob(Input):
    """Get job status."""
    operation: Literal['get_image_job'] = Field('get_image_job', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='The image generation job ID.', json_schema_extra={'examples': [42]})


class ListImageTemplates(Input):
    """List image templates."""
    operation: Literal['list_image_templates'] = Field('list_image_templates', json_schema_extra={"ui:hidden": True})


class GetImageTemplate(Input):
    """Get image template details."""
    operation: Literal['get_image_template'] = Field('get_image_template', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='The image template ID.', json_schema_extra={'examples': [1]})


class ListSignatureRequests(Input):
    """List signature requests."""
    operation: Literal['list_signature_requests'] = Field('list_signature_requests', json_schema_extra={"ui:hidden": True})
    status: Literal['draft', 'sent', 'partially_signed', 'completed', 'declined', 'expired', 'cancelled'] | None = Field(None, description='Filter by status')
    page: int | None = Field(None, description='', json_schema_extra={'examples': [1]}, ge=1)


class CreateSignatureRequest(Input):
    """Send an existing document for signing."""
    operation: Literal['create_signature_request'] = Field('create_signature_request', json_schema_extra={"ui:hidden": True})
    document_url: str | None = Field(None, description='Publicly accessible URL to a PDF. Required if job_id is not provided.', json_schema_extra={'format': 'url', 'examples': ['https://yourstorage.com/contracts/nda-v3.pdf']})
    job_id: str | None = Field(None, description='job_id from a previous document generation. Required if document_url is not provided.', json_schema_extra={'examples': ['018e9f2a-3b7c-7000-8c4d-1e2f3a4b5c6d']})
    signers: list[StandaloneSignerInput] = Field(..., description='List of signers. Literal values only — no {{Column}} references.', min_length=1)
    title: str | None = Field(None, description='', json_schema_extra={'examples': ['NDA — Acme Corp']})
    message: str | None = Field(None, description='', json_schema_extra={'examples': ['Please review and sign.']})
    expires_days: int | None = Field(None, description='', json_schema_extra={'examples': [14]})
    sequential: bool | None = Field(None, description='', json_schema_extra={'examples': [False]})

    @model_validator(mode="after")
    def document_source(self):
        if bool(self.document_url) == bool(self.job_id):
            raise ValueError("Provide exactly one document URL or generation job ID")
        return self


class GetSignatureRequest(Input):
    """Get a signature request."""
    operation: Literal['get_signature_request'] = Field('get_signature_request', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='UUID of the signature request', json_schema_extra={'format': 'uuid'})


class CancelSignatureRequest(Input):
    """Cancel a signature request."""
    operation: Literal['cancel_signature_request'] = Field('cancel_signature_request', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='UUID of the signature request', json_schema_extra={'format': 'uuid'})


class ListTemplates(Input):
    """List all templates for the authenticated user."""
    operation: Literal['list_templates'] = Field('list_templates', json_schema_extra={"ui:hidden": True})


class GetTemplatePlaceholders(Input):
    """Get placeholders from a template."""
    operation: Literal['get_template_placeholders'] = Field('get_template_placeholders', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Unique ID of the template')


class GetCredits(Input):
    """Returns the credits details for the authenticated user.."""
    operation: Literal['get_credits'] = Field('get_credits', json_schema_extra={"ui:hidden": True})


class ListWorkflows(Input):
    """List all workflows for the authenticated user."""
    operation: Literal['list_workflows'] = Field('list_workflows', json_schema_extra={"ui:hidden": True})


class GenerateWorkflowDocuments(Input):
    """Generate documents for a workflow based on the provided request data."""
    operation: Literal['generate_workflow_documents'] = Field('generate_workflow_documents', json_schema_extra={"ui:hidden": True})
    workflow_id: str = Field(..., description='The unique ID of the workflow to be used for document generation.', json_schema_extra={'examples': ['workflow_abc123']})
    data: dict[str, Any] = Field(..., description='An associative array of data to populate the template placeholders.', json_schema_extra={'examples': [{'placeholder1': 'value1', 'placeholder2': 'value2'}]})
    format: Literal['pdf', 'original'] = Field(..., description='The format of the documents to be generated (e.g., PDF, Original Format).', json_schema_extra={'examples': ['pdf']})


class GetWorkflowPlaceholders(Input):
    """Get placeholders from a workflow."""
    operation: Literal['get_workflow_placeholders'] = Field('get_workflow_placeholders', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Unique ID of the workflow')


ActiveMergeConfig = Annotated[Union[GenerateDocument, GetGenerationStatus, ListGenerationHistory, MergeDocuments, ListFiles, SaveFiles, GetFileDownloadUrl, GenerateImages, GetImageJob, ListImageTemplates, GetImageTemplate, ListSignatureRequests, CreateSignatureRequest, GetSignatureRequest, CancelSignatureRequest, ListTemplates, GetTemplatePlaceholders, GetCredits, ListWorkflows, GenerateWorkflowDocuments, GetWorkflowPlaceholders], Field(discriminator="operation")]


ROUTES = {'generate_document': ('POST', '/api/document-generation/generate', [], [], True), 'get_generation_status': ('GET', '/api/document-generation/status/{job_id}', ['job_id'], [], False), 'list_generation_history': ('GET', '/api/document-generation/history', [], ['job_id', 'status', 'template_id', 'date_from', 'date_to', 'per_page', 'page'], False), 'merge_documents': ('POST', '/api/document-merge/merge', [], [], True), 'list_files': ('GET', '/api/files', [], ['id'], False), 'save_files': ('POST', '/api/files/save', [], [], True), 'get_file_download_url': ('GET', '/api/files/download/{id}', ['id'], [], False), 'generate_images': ('POST', '/api/image-generation/generate', [], [], True), 'get_image_job': ('GET', '/api/image-generation/jobs/{id}', ['id'], [], False), 'list_image_templates': ('GET', '/api/image-templates', [], [], False), 'get_image_template': ('GET', '/api/image-templates/{id}', ['id'], [], False), 'list_signature_requests': ('GET', '/api/signature-requests', [], ['status', 'page'], False), 'create_signature_request': ('POST', '/api/signature-requests', [], [], True), 'get_signature_request': ('GET', '/api/signature-requests/{id}', ['id'], [], False), 'cancel_signature_request': ('POST', '/api/signature-requests/{id}/cancel', ['id'], [], False), 'list_templates': ('GET', '/api/templates', [], [], False), 'get_template_placeholders': ('GET', '/api/templates/{id}/placeholders', ['id'], [], False), 'get_credits': ('GET', '/api/user/credits', [], [], False), 'list_workflows': ('GET', '/api/workflows', [], [], False), 'generate_workflow_documents': ('POST', '/api/workflows/generate', [], [], True), 'get_workflow_placeholders': ('GET', '/api/workflows/{id}/placeholders', ['id'], [], False)}


class ActiveMergeNodeConfig(NodeConfig[ActiveMergeConfig, ActiveMergeAPIKeyCredential]):
    pass


class ActiveMergeNode(WorkflowNode):
    integration_type = "automation-active-merge"
    connection_evidence = ConnectionEvidence(noun="account credits", operation="get_credits")

    @classmethod
    def get_config_model(cls):
        return ActiveMergeNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Active Merge API key")
        config = self.config.config
        method, path, path_fields, query_fields, has_body = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for name in path_fields:
            value = str(values.pop(name))
            if not value or value in {".", ".."} or any(c in value for c in "/\\?#"):
                raise ValueError("Use a single resource ID")
            path = path.replace("{" + name + "}", quote(value, safe=""))
        params = {name: values.pop(name) for name in query_fields if name in values}
        credential = self.config.credentials
        try:
            async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, "https://app.activemerge.com" + path,
                    headers={"API-KEY": credential.api_key, "Accept": "application/json"},
                    params=params, **({"json": values} if has_body else {}))
            if not 200 <= response.status_code < 300:
                output = {"status": "error", "http_status": response.status_code,
                    "message": "Active Merge request failed; check permissions and configuration"}
            else:
                data = response.json()
                if not isinstance(data, (dict, list)):
                    raise ValueError("Expected a JSON object or list")
                if config.operation == "get_credits" and (
                    not isinstance(data, dict)
                    or any(type(data.get(key)) is not int for key in ("total", "used", "left"))
                ):
                    raise ValueError("Account credit response is incomplete")
                if isinstance(data, dict) and (data.get("success") is False or data.get("error")):
                    output = {"status": "error", "message": "Active Merge did not complete the request"}
                else:
                    output = {"status": "success", "data": data, "http_status": response.status_code}
        except Exception:
            raise ValueError("Active Merge request could not be confirmed; inspect writes before retrying") from None
        await self.emit(output)
        return output
