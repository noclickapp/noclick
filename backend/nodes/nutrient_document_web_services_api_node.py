"""Nutrient DWS API, pinned to the published 2026-05-25 contract.

Document operations accept public document URLs; list responses preserve provider
pagination cursors so workflows can explicitly request subsequent pages.
"""
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


class NutrientCredential(BaseModel):
    model_config = ConfigDict(title="Nutrient API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://www.nutrient.io/data-extraction/api_keys/",
        "x-credential-instructions": "Create an API key in your Nutrient Data Extraction dashboard and paste it here."})
    credential_type: Literal["nutrient_document_web_services_api_key"] = Field("nutrient_document_web_services_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", description="Paste your Nutrient API key without the Bearer prefix.", repr=False, json_schema_extra={"ui:widget": "password"})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetAccountInfoConfig(_Input):
    """Get account information."""
    operation: Literal["get_account_info"] = Field("get_account_info", json_schema_extra={"ui:hidden": True})


class GetAccountProductUsageConfig(_Input):
    """Get usage for a product."""
    operation: Literal["get_account_product_usage"] = Field("get_account_product_usage", json_schema_extra={"ui:hidden": True})
    product: Literal['processor', 'viewer', 'signing_workflow', 'accessibility', 'data_extraction', 'ai_gateway'] = Field(..., title='Product')


class ExtractionParseConfig(_Input):
    """Parse document structure."""
    operation: Literal["extraction_parse"] = Field("extraction_parse", json_schema_extra={"ui:hidden": True})
    body: dict[str, Any] = Field(..., title="Request Body", description="JSON request body for this operation from the Nutrient API reference. Document processing requests require a public document url and any processing settings.", json_schema_extra={"ui:widget": "json"})


class ExtractionParseAsyncConfig(_Input):
    """Parse document structure asynchronously."""
    operation: Literal["extraction_parse_async"] = Field("extraction_parse_async", json_schema_extra={"ui:hidden": True})
    body: dict[str, Any] = Field(..., title="Request Body", description="JSON request body for this operation from the Nutrient API reference. Document processing requests require a public document url and any processing settings.", json_schema_extra={"ui:widget": "json"})


class ExtractionExtractConfig(_Input):
    """Extract structured data from documents."""
    operation: Literal["extraction_extract"] = Field("extraction_extract", json_schema_extra={"ui:hidden": True})
    body: dict[str, Any] = Field(..., title="Request Body", description="JSON request body for this operation from the Nutrient API reference. Document processing requests require a public document url and any processing settings.", json_schema_extra={"ui:widget": "json"})


class ExtractionExtractAsyncConfig(_Input):
    """Extract structured data from documents asynchronously."""
    operation: Literal["extraction_extract_async"] = Field("extraction_extract_async", json_schema_extra={"ui:hidden": True})
    body: dict[str, Any] = Field(..., title="Request Body", description="JSON request body for this operation from the Nutrient API reference. Document processing requests require a public document url and any processing settings.", json_schema_extra={"ui:widget": "json"})


class ExtractionRunsGetConfig(_Input):
    """Retrieve a stored processing run."""
    operation: Literal["extraction_runs_get"] = Field("extraction_runs_get", json_schema_extra={"ui:hidden": True})
    runId: str = Field(..., title='Run ID', min_length=1, max_length=256)


class ExtractionRunsDeleteConfig(_Input):
    """Delete a stored processing run."""
    operation: Literal["extraction_runs_delete"] = Field("extraction_runs_delete", json_schema_extra={"ui:hidden": True})
    runId: str = Field(..., title='Run ID', min_length=1, max_length=256)


class ExtractionRunsCancelConfig(_Input):
    """Cancel a queued or running processing run."""
    operation: Literal["extraction_runs_cancel"] = Field("extraction_runs_cancel", json_schema_extra={"ui:hidden": True})
    runId: str = Field(..., title='Run ID', min_length=1, max_length=256)


class ExtractionSplitConfig(_Input):
    """Split a merged document into sub-documents."""
    operation: Literal["extraction_split"] = Field("extraction_split", json_schema_extra={"ui:hidden": True})
    body: dict[str, Any] = Field(..., title="Request Body", description="JSON request body for this operation from the Nutrient API reference. Document processing requests require a public document url and any processing settings.", json_schema_extra={"ui:widget": "json"})


class ExtractionSplitAsyncConfig(_Input):
    """Split a document asynchronously."""
    operation: Literal["extraction_split_async"] = Field("extraction_split_async", json_schema_extra={"ui:hidden": True})
    body: dict[str, Any] = Field(..., title="Request Body", description="JSON request body for this operation from the Nutrient API reference. Document processing requests require a public document url and any processing settings.", json_schema_extra={"ui:widget": "json"})


class ExtractionClassifyConfig(_Input):
    """Classify a document."""
    operation: Literal["extraction_classify"] = Field("extraction_classify", json_schema_extra={"ui:hidden": True})
    body: dict[str, Any] = Field(..., title="Request Body", description="JSON request body for this operation from the Nutrient API reference. Document processing requests require a public document url and any processing settings.", json_schema_extra={"ui:widget": "json"})


class ExtractionClassifyAsyncConfig(_Input):
    """Classify a document asynchronously."""
    operation: Literal["extraction_classify_async"] = Field("extraction_classify_async", json_schema_extra={"ui:hidden": True})
    body: dict[str, Any] = Field(..., title="Request Body", description="JSON request body for this operation from the Nutrient API reference. Document processing requests require a public document url and any processing settings.", json_schema_extra={"ui:widget": "json"})


class ExtractionBatchesListConfig(_Input):
    """List batches."""
    operation: Literal["extraction_batches_list"] = Field("extraction_batches_list", json_schema_extra={"ui:hidden": True})
    page_size: int | None = Field(None, title='Page Size', ge=1, le=100)
    cursor: str | None = Field(None, title='Cursor')


class ExtractionBatchesGetConfig(_Input):
    """Retrieve a batch."""
    operation: Literal["extraction_batches_get"] = Field("extraction_batches_get", json_schema_extra={"ui:hidden": True})
    batchId: str = Field(..., title='Batch ID', min_length=1, max_length=256)


class ExtractionBatchesCancelConfig(_Input):
    """Cancel a batch."""
    operation: Literal["extraction_batches_cancel"] = Field("extraction_batches_cancel", json_schema_extra={"ui:hidden": True})
    batchId: str = Field(..., title='Batch ID', min_length=1, max_length=256)


class ExtractionProcessorsListConfig(_Input):
    """List processors."""
    operation: Literal["extraction_processors_list"] = Field("extraction_processors_list", json_schema_extra={"ui:hidden": True})
    kind: Literal['parse', 'extract', 'classify', 'split'] | None = Field(None, title='Kind')


class ExtractionProcessorsCreateConfig(_Input):
    """Create a processor."""
    operation: Literal["extraction_processors_create"] = Field("extraction_processors_create", json_schema_extra={"ui:hidden": True})
    body: dict[str, Any] = Field(..., title="Request Body", description="JSON request body for this operation from the Nutrient API reference. Document processing requests require a public document url and any processing settings.", json_schema_extra={"ui:widget": "json"})


class ExtractionProcessorGetConfig(_Input):
    """Get a processor."""
    operation: Literal["extraction_processor_get"] = Field("extraction_processor_get", json_schema_extra={"ui:hidden": True})
    processorId: str = Field(..., title='Processor ID', min_length=1, max_length=256)


class ExtractionProcessorRenameConfig(_Input):
    """Rename a processor."""
    operation: Literal["extraction_processor_rename"] = Field("extraction_processor_rename", json_schema_extra={"ui:hidden": True})
    processorId: str = Field(..., title='Processor ID', min_length=1, max_length=256)
    body: dict[str, Any] = Field(..., title="Request Body", description="JSON request body for this operation from the Nutrient API reference. Document processing requests require a public document url and any processing settings.", json_schema_extra={"ui:widget": "json"})


class ExtractionProcessorDeleteConfig(_Input):
    """Delete a processor."""
    operation: Literal["extraction_processor_delete"] = Field("extraction_processor_delete", json_schema_extra={"ui:hidden": True})
    processorId: str = Field(..., title='Processor ID', min_length=1, max_length=256)


class ExtractionProcessorCreateVersionConfig(_Input):
    """Create a processor version."""
    operation: Literal["extraction_processor_create_version"] = Field("extraction_processor_create_version", json_schema_extra={"ui:hidden": True})
    processorId: str = Field(..., title='Processor ID', min_length=1, max_length=256)
    body: dict[str, Any] = Field(..., title="Request Body", description="JSON request body for this operation from the Nutrient API reference. Document processing requests require a public document url and any processing settings.", json_schema_extra={"ui:widget": "json"})


class ExtractionProcessorGetVersionConfig(_Input):
    """Get a processor version."""
    operation: Literal["extraction_processor_get_version"] = Field("extraction_processor_get_version", json_schema_extra={"ui:hidden": True})
    processorId: str = Field(..., title='Processor ID', min_length=1, max_length=256)
    version: int = Field(..., title='Version', ge=1)


class ExtractionProcessorPublishVersionConfig(_Input):
    """Publish a processor version."""
    operation: Literal["extraction_processor_publish_version"] = Field("extraction_processor_publish_version", json_schema_extra={"ui:hidden": True})
    processorId: str = Field(..., title='Processor ID', min_length=1, max_length=256)
    version: int = Field(..., title='Version', ge=1)


# Nutrient's own MCP server: agents get its tools through a person's Nutrient sign-in.
NutrientDocumentWebServicesApiMcpCredential = mcp_credential("nutrient_document_web_services_api", "https://mcp.nutrient.io/mcp", app="Nutrient")


NutrientOperation = Annotated[Union[GetAccountInfoConfig, GetAccountProductUsageConfig, ExtractionParseConfig, ExtractionParseAsyncConfig, ExtractionExtractConfig, ExtractionExtractAsyncConfig, ExtractionRunsGetConfig, ExtractionRunsDeleteConfig, ExtractionRunsCancelConfig, ExtractionSplitConfig, ExtractionSplitAsyncConfig, ExtractionClassifyConfig, ExtractionClassifyAsyncConfig, ExtractionBatchesListConfig, ExtractionBatchesGetConfig, ExtractionBatchesCancelConfig, ExtractionProcessorsListConfig, ExtractionProcessorsCreateConfig, ExtractionProcessorGetConfig, ExtractionProcessorRenameConfig, ExtractionProcessorDeleteConfig, ExtractionProcessorCreateVersionConfig, ExtractionProcessorGetVersionConfig, ExtractionProcessorPublishVersionConfig], Field(discriminator="operation")]


class NutrientFullConfig(NodeConfig[NutrientOperation, Union[NutrientCredential, NutrientDocumentWebServicesApiMcpCredential]]):
    pass


ROUTES = {'get_account_info': ('GET', '/account/info', [], False), 'get_account_product_usage': ('GET', '/account/{product}/usage', [('product', 'product', 'path')], False), 'extraction_parse': ('POST', '/extraction/parse', [], True), 'extraction_parse_async': ('POST', '/extraction/parse/async', [], True), 'extraction_extract': ('POST', '/extraction/extract', [], True), 'extraction_extract_async': ('POST', '/extraction/extract/async', [], True), 'extraction_runs_get': ('GET', '/extraction/runs/{runId}', [('runId', 'runId', 'path')], False), 'extraction_runs_delete': ('DELETE', '/extraction/runs/{runId}', [('runId', 'runId', 'path')], False), 'extraction_runs_cancel': ('POST', '/extraction/runs/{runId}/cancel', [('runId', 'runId', 'path')], False), 'extraction_split': ('POST', '/extraction/split', [], True), 'extraction_split_async': ('POST', '/extraction/split/async', [], True), 'extraction_classify': ('POST', '/extraction/classify', [], True), 'extraction_classify_async': ('POST', '/extraction/classify/async', [], True), 'extraction_batches_list': ('GET', '/extraction/batches', [('page_size', 'page_size', 'query'), ('cursor', 'cursor', 'query')], False), 'extraction_batches_get': ('GET', '/extraction/batches/{batchId}', [('batchId', 'batchId', 'path')], False), 'extraction_batches_cancel': ('POST', '/extraction/batches/{batchId}/cancel', [('batchId', 'batchId', 'path')], False), 'extraction_processors_list': ('GET', '/extraction/processors', [('kind', 'kind', 'query')], False), 'extraction_processors_create': ('POST', '/extraction/processors', [], True), 'extraction_processor_get': ('GET', '/extraction/processors/{processorId}', [('processorId', 'processorId', 'path')], False), 'extraction_processor_rename': ('PATCH', '/extraction/processors/{processorId}', [('processorId', 'processorId', 'path')], True), 'extraction_processor_delete': ('DELETE', '/extraction/processors/{processorId}', [('processorId', 'processorId', 'path')], False), 'extraction_processor_create_version': ('POST', '/extraction/processors/{processorId}/versions', [('processorId', 'processorId', 'path')], True), 'extraction_processor_get_version': ('GET', '/extraction/processors/{processorId}/versions/{version}', [('processorId', 'processorId', 'path'), ('version', 'version', 'path')], False), 'extraction_processor_publish_version': ('POST', '/extraction/processors/{processorId}/versions/{version}/publish', [('processorId', 'processorId', 'path'), ('version', 'version', 'path')], False)}


class NutrientDocumentWebServicesApiNode(WorkflowNode):
    integration_type = "automation-nutrient-document-web-services-api"
    credential_provider_labels = {"nutrient_document_web_services_api": "Nutrient Account"}
    connection_evidence = ConnectionEvidence(noun="Nutrient account", identity_operation="get_account_info")

    @classmethod
    def get_config_model(cls):
        return NutrientFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Nutrient API key")
        config = self.config.config
        method, path, parameters, has_body = ROUTES[config.operation]
        params = {}
        for field, name, location in parameters:
            value = getattr(config, field)
            if value is None:
                continue
            if location == "path":
                path = path.replace("{" + name + "}", quote(str(value), safe=""))
            else:
                params[name] = value
        kwargs = {"params": params, "headers": {
            "Authorization": "Bearer " + self.config.credentials.api_key,
            "Accept": "application/json", "x-nutrient-api-version": "2026-05-25"}}
        if has_body:
            kwargs["json"] = config.body
        async with guarded_async_client(timeout=180, follow_redirects=False) as client:
            response = await client.request(method, "https://api.nutrient.io" + path, **kwargs)
        response.raise_for_status()
        if response.status_code == 204:
            return {"deleted": True}
        return response.json()
