"""
Reducto document intelligence automation node.

Provides workflow integration with Reducto (REST API) for operations including:
- Documents: upload
- Parse: parse (sync), parse (async)
- Extract: extract (sync), extract (async)
- Split: split (sync), split (async)
- Classify: classify
- Edit: edit (sync), edit (async)
- Pipeline: pipeline (sync), pipeline (async)
- Jobs: get job, list jobs, cancel job
- Webhooks: configure webhook
- Account: get API version
- Webhook Trigger: fire when an async job completes (Svix-signed delivery)

Authentication: API Key (Bearer token)
API Base URL: https://platform.reducto.ai
Documentation: https://docs.reducto.ai/

A single API key grants full account access (no scopes). Inbound job-completion
webhooks are delivered via Svix and signed with a whsec_... secret managed in
the Svix portal returned by /configure_webhook.
"""

import json
import logging
import re
import time
from typing import Dict, Any, Optional, Literal, Union, Annotated
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

REDUCTO_API_BASE = "https://platform.reducto.ai"


_DOCUMENT_ACCEPT = (
    ".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.csv,.txt,"
    "image/jpeg,image/png,image/webp,image/tiff"
)


# ============================================================================
# Credential Schema
# ============================================================================


class ReductoApiKeyCredential(BaseModel):
    """API Key credential for Reducto."""

    credential_type: Literal["reducto_api_key"] = Field(
        "reducto_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Reducto API key from Reducto Studio (studio.reducto.ai -> API Keys -> Create new API key)",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://studio.reducto.ai"}
    )


ReductoCredential = ReductoApiKeyCredential


# ============================================================================
# Operation Configs
# ============================================================================


class ReductoUploadConfig(BaseModel):
    """Upload a file by URL to Reducto storage; returns a reducto:// id reusable as document URL."""

    operation: Literal["upload"] = Field(
        "upload",
        json_schema_extra={
            "const": "upload",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Upload Document",
        },
        title="Upload Document",
    )
    file_url: str = Field(
        ...,
        title="File URL",
        description="Public URL or local file upload to store in Reducto. Use the Upload button to pick a file from your computer.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": _DOCUMENT_ACCEPT},
    )


class ReductoParseConfig(BaseModel):
    """Convert a document into layout-aware structured JSON/markdown (synchronous)."""

    operation: Literal["parse"] = Field(
        "parse",
        json_schema_extra={
            "const": "parse",
            "ui:hidden": True,
            "x-category": "Parse",
            "x-is-trigger": False,
            "x-display-name": "Parse Document",
        },
        title="Parse Document",
    )
    document_url: str = Field(
        ...,
        title="Document URL",
        description="Public URL, a reducto:// id from Upload, a jobid://<id> reference, or upload a local file via the Upload button.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": _DOCUMENT_ACCEPT},
    )
    page_range: Optional[str] = Field(
        None,
        title="Page Range",
        description='Pages to process as JSON, e.g. {"start": 1, "end": 5}. Leave empty for all pages.',
        json_schema_extra={"ui:placeholder": '{"start": 1, "end": 5}'},
    )
    table_output_format: Optional[Literal["html", "json", "md", "jsonbbox", "dynamic", "csv"]] = Field(
        None,
        title="Table Output Format",
        description="Controls how tables appear in output (default: dynamic)",
    )
    chunk_mode: Optional[Literal["variable", "section", "page", "disabled", "block", "page_sections"]] = Field(
        None,
        title="Chunking Mode",
        description="Chunk the output for RAG pipelines (default: disabled). Use 'variable' for most RAG use cases.",
    )


class ReductoParseAsyncConfig(BaseModel):
    """Enqueue a parse job and return a job_id immediately (asynchronous)."""

    operation: Literal["parse_async"] = Field(
        "parse_async",
        json_schema_extra={
            "const": "parse_async",
            "ui:hidden": True,
            "x-category": "Parse",
            "x-is-trigger": False,
            "x-display-name": "Parse Document (Async)",
        },
        title="Parse Document (Async)",
    )
    document_url: str = Field(
        ...,
        title="Document URL",
        description="Public URL, a reducto:// id from Upload, a jobid://<id> reference, or upload a local file via the Upload button.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": _DOCUMENT_ACCEPT},
    )
    page_range: Optional[str] = Field(
        None,
        title="Page Range",
        description='Pages to process as JSON, e.g. {"start": 1, "end": 5}. Leave empty for all pages.',
        json_schema_extra={"ui:placeholder": '{"start": 1, "end": 5}'},
    )
    table_output_format: Optional[Literal["html", "json", "md", "jsonbbox", "dynamic", "csv"]] = Field(
        None,
        title="Table Output Format",
        description="Controls how tables appear in output (default: dynamic)",
    )
    chunk_mode: Optional[Literal["variable", "section", "page", "disabled", "block", "page_sections"]] = Field(
        None,
        title="Chunking Mode",
        description="Chunk the output for RAG pipelines (default: disabled). Use 'variable' for most RAG use cases.",
    )
    queue_priority: Optional[Literal["auto", "standard", "batch"]] = Field(
        None,
        title="Queue Priority",
        description="Job queue priority (default: auto). Use 'batch' for large non-urgent jobs.",
    )


class ReductoExtractConfig(BaseModel):
    """Pull specific structured fields from a document using a JSON schema (synchronous)."""

    operation: Literal["extract"] = Field(
        "extract",
        json_schema_extra={
            "const": "extract",
            "ui:hidden": True,
            "x-category": "Extract",
            "x-is-trigger": False,
            "x-display-name": "Extract Fields",
        },
        title="Extract Fields",
    )
    document_url: str = Field(
        ...,
        title="Document URL",
        description="Public URL, a reducto:// id from Upload, a jobid://<id> reference, or upload a local file via the Upload button.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": _DOCUMENT_ACCEPT},
    )
    output_schema: str = Field(
        ...,
        title="JSON Schema",
        description="JSON Schema describing the fields to extract",
        json_schema_extra={"ui:widget": "textarea"},
    )
    system_prompt: Optional[str] = Field(
        None,
        title="System Prompt",
        description="Custom instructions to guide the extraction model (optional)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    page_range: Optional[str] = Field(
        None,
        title="Page Range",
        description='Pages to process as JSON, e.g. {"start": 1, "end": 5}. Leave empty for all pages.',
        json_schema_extra={"ui:placeholder": '{"start": 1, "end": 5}'},
    )


class ReductoExtractAsyncConfig(BaseModel):
    """Asynchronous schema-based field extraction; returns a job_id."""

    operation: Literal["extract_async"] = Field(
        "extract_async",
        json_schema_extra={
            "const": "extract_async",
            "ui:hidden": True,
            "x-category": "Extract",
            "x-is-trigger": False,
            "x-display-name": "Extract Fields (Async)",
        },
        title="Extract Fields (Async)",
    )
    document_url: str = Field(
        ...,
        title="Document URL",
        description="Public URL, a reducto:// id from Upload, a jobid://<id> reference, or upload a local file via the Upload button.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": _DOCUMENT_ACCEPT},
    )
    output_schema: str = Field(
        ...,
        title="JSON Schema",
        description="JSON Schema describing the fields to extract",
        json_schema_extra={"ui:widget": "textarea"},
    )
    system_prompt: Optional[str] = Field(
        None,
        title="System Prompt",
        description="Custom instructions to guide the extraction model (optional)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    page_range: Optional[str] = Field(
        None,
        title="Page Range",
        description='Pages to process as JSON, e.g. {"start": 1, "end": 5}. Leave empty for all pages.',
        json_schema_extra={"ui:placeholder": '{"start": 1, "end": 5}'},
    )
    queue_priority: Optional[Literal["auto", "standard", "batch"]] = Field(
        None,
        title="Queue Priority",
        description="Job queue priority (default: auto). Use 'batch' for large non-urgent jobs.",
    )


class ReductoSplitConfig(BaseModel):
    """Divide a multi-document file into labeled sections (synchronous)."""

    operation: Literal["split"] = Field(
        "split",
        json_schema_extra={
            "const": "split",
            "ui:hidden": True,
            "x-category": "Split",
            "x-is-trigger": False,
            "x-display-name": "Split Document",
        },
        title="Split Document",
    )
    document_url: str = Field(
        ...,
        title="Document URL",
        description="Public URL, a reducto:// id from Upload, a jobid://<id> reference, or upload a local file via the Upload button.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": _DOCUMENT_ACCEPT},
    )
    split_description: str = Field(
        ...,
        title="Split Categories",
        description='JSON array of categories, e.g. [{"name": "invoice", "description": "invoice section"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    split_rules: Optional[str] = Field(
        None,
        title="Split Rules",
        description="Custom prompt/rules to guide the splitting logic (optional)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ReductoSplitAsyncConfig(BaseModel):
    """Asynchronous document splitting; returns a job_id."""

    operation: Literal["split_async"] = Field(
        "split_async",
        json_schema_extra={
            "const": "split_async",
            "ui:hidden": True,
            "x-category": "Split",
            "x-is-trigger": False,
            "x-display-name": "Split Document (Async)",
        },
        title="Split Document (Async)",
    )
    document_url: str = Field(
        ...,
        title="Document URL",
        description="Public URL, a reducto:// id from Upload, a jobid://<id> reference, or upload a local file via the Upload button.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": _DOCUMENT_ACCEPT},
    )
    split_description: str = Field(
        ...,
        title="Split Categories",
        description='JSON array of categories, e.g. [{"name": "invoice", "description": "invoice section"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    split_rules: Optional[str] = Field(
        None,
        title="Split Rules",
        description="Custom prompt/rules to guide the splitting logic (optional)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    queue_priority: Optional[Literal["auto", "standard", "batch"]] = Field(
        None,
        title="Queue Priority",
        description="Job queue priority (default: auto). Use 'batch' for large non-urgent jobs.",
    )


class ReductoClassifyConfig(BaseModel):
    """Categorize a document into one of a provided set of document types/labels."""

    operation: Literal["classify"] = Field(
        "classify",
        json_schema_extra={
            "const": "classify",
            "ui:hidden": True,
            "x-category": "Classify",
            "x-is-trigger": False,
            "x-display-name": "Classify Document",
        },
        title="Classify Document",
    )
    document_url: str = Field(
        ...,
        title="Document URL",
        description="Public URL, a reducto:// id from Upload, a jobid://<id> reference, or upload a local file via the Upload button.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": _DOCUMENT_ACCEPT},
    )
    categories: str = Field(
        ...,
        title="Classification Schema",
        description='JSON array of categories with criteria, e.g. [{"category": "invoice", "criteria": ["contains line items", "has total amount"]}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    page_range: Optional[str] = Field(
        None,
        title="Page Range",
        description="Pages to examine for classification (1-indexed, default: first 5 pages, max 25). JSON e.g. {\"start\": 1, \"end\": 3}",
        json_schema_extra={"ui:placeholder": '{"start": 1, "end": 5}'},
    )
    document_metadata: Optional[str] = Field(
        None,
        title="Document Metadata",
        description="Optional context about the document to improve classification accuracy",
    )


class ReductoEditConfig(BaseModel):
    """Programmatically modify a PDF/DOCX - fill forms, write field values, redact (synchronous)."""

    operation: Literal["edit"] = Field(
        "edit",
        json_schema_extra={
            "const": "edit",
            "ui:hidden": True,
            "x-category": "Edit",
            "x-is-trigger": False,
            "x-display-name": "Edit Document",
        },
        title="Edit Document",
    )
    document_url: str = Field(
        ...,
        title="Document URL",
        description="Public URL, a reducto:// id from Upload, a jobid://<id> reference, or upload a local file via the Upload button.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": _DOCUMENT_ACCEPT},
    )
    edit_instructions: str = Field(
        ...,
        title="Edit Instructions",
        description="Natural language instructions describing the edits to apply, e.g. 'Fill the Name field with John Doe and check the Agree checkbox'",
        json_schema_extra={"ui:widget": "textarea"},
    )
    form_schema: Optional[str] = Field(
        None,
        title="Form Schema",
        description='JSON array of EditWidget objects for precise PDF form filling, e.g. [{"type": "text", "description": "Name field", "value": "John Doe"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    edit_options: Optional[str] = Field(
        None,
        title="Edit Options",
        description='JSON object of edit options, e.g. {"color": "#FF0000", "font_size": 12, "flatten": true}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ReductoEditAsyncConfig(BaseModel):
    """Asynchronous document editing / form write-back; returns a job_id."""

    operation: Literal["edit_async"] = Field(
        "edit_async",
        json_schema_extra={
            "const": "edit_async",
            "ui:hidden": True,
            "x-category": "Edit",
            "x-is-trigger": False,
            "x-display-name": "Edit Document (Async)",
        },
        title="Edit Document (Async)",
    )
    document_url: str = Field(
        ...,
        title="Document URL",
        description="Public URL, a reducto:// id from Upload, a jobid://<id> reference, or upload a local file via the Upload button.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": _DOCUMENT_ACCEPT},
    )
    edit_instructions: str = Field(
        ...,
        title="Edit Instructions",
        description="Natural language instructions describing the edits to apply, e.g. 'Fill the Name field with John Doe and check the Agree checkbox'",
        json_schema_extra={"ui:widget": "textarea"},
    )
    form_schema: Optional[str] = Field(
        None,
        title="Form Schema",
        description='JSON array of EditWidget objects for precise PDF form filling, e.g. [{"type": "text", "description": "Name field", "value": "John Doe"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    edit_options: Optional[str] = Field(
        None,
        title="Edit Options",
        description='JSON object of edit options, e.g. {"color": "#FF0000", "font_size": 12, "flatten": true}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ReductoPipelineConfig(BaseModel):
    """Run a composed multi-step pipeline (split -> parse -> extract) in one call (synchronous)."""

    operation: Literal["pipeline"] = Field(
        "pipeline",
        json_schema_extra={
            "const": "pipeline",
            "ui:hidden": True,
            "x-category": "Pipeline",
            "x-is-trigger": False,
            "x-display-name": "Run Pipeline",
        },
        title="Run Pipeline",
    )
    document_url: str = Field(
        ...,
        title="Document URL",
        description="Public URL, a reducto:// id from Upload, a jobid://<id> reference, or upload a local file via the Upload button.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": _DOCUMENT_ACCEPT},
    )
    pipeline_id: str = Field(
        ...,
        title="Pipeline ID",
        description="The ID of the pipeline to run",
    )


class ReductoPipelineAsyncConfig(BaseModel):
    """Asynchronous pipeline execution; returns a job_id."""

    operation: Literal["pipeline_async"] = Field(
        "pipeline_async",
        json_schema_extra={
            "const": "pipeline_async",
            "ui:hidden": True,
            "x-category": "Pipeline",
            "x-is-trigger": False,
            "x-display-name": "Run Pipeline (Async)",
        },
        title="Run Pipeline (Async)",
    )
    document_url: str = Field(
        ...,
        title="Document URL",
        description="Public URL, a reducto:// id from Upload, a jobid://<id> reference, or upload a local file via the Upload button.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": _DOCUMENT_ACCEPT},
    )
    pipeline_id: str = Field(
        ...,
        title="Pipeline ID",
        description="The ID of the pipeline to run",
    )
    queue_priority: Optional[Literal["auto", "standard", "batch"]] = Field(
        None,
        title="Queue Priority",
        description="Job queue priority (default: auto). Use 'batch' for large non-urgent jobs.",
    )


class ReductoGetJobConfig(BaseModel):
    """Retrieve status and results of an async job."""

    operation: Literal["get_job"] = Field(
        "get_job",
        json_schema_extra={
            "const": "get_job",
            "ui:hidden": True,
            "x-category": "Jobs",
            "x-is-trigger": False,
            "x-display-name": "Get Job",
        },
        title="Get Job",
    )
    job_id: str = Field(
        ..., title="Job ID", description="The job_id returned by an async operation"
    )
    timeout: Optional[str] = Field(
        None,
        title="Long-Poll Timeout (seconds)",
        description="On-premise deployments only: wait up to N seconds for the job to complete before returning. Leave empty to return immediately (cloud API ignores this parameter).",
    )


class ReductoListJobsConfig(BaseModel):
    """List async jobs for the account with cursor-based pagination."""

    operation: Literal["list_jobs"] = Field(
        "list_jobs",
        json_schema_extra={
            "const": "list_jobs",
            "ui:hidden": True,
            "x-category": "Jobs",
            "x-is-trigger": False,
            "x-display-name": "List Jobs",
        },
        title="List Jobs",
    )
    cursor: Optional[str] = Field(
        None,
        title="Cursor",
        description="Pagination cursor from the previous response's next_cursor field",
    )
    limit: Optional[str] = Field(
        None, title="Limit", description="Number of jobs per page"
    )
    api_key_prefix: Optional[str] = Field(
        None,
        title="API Key Prefix",
        description="Filter jobs by API key prefix (optional)",
    )


class ReductoCancelJobConfig(BaseModel):
    """Cancel a running or queued async job."""

    operation: Literal["cancel_job"] = Field(
        "cancel_job",
        json_schema_extra={
            "const": "cancel_job",
            "ui:hidden": True,
            "x-category": "Jobs",
            "x-is-trigger": False,
            "x-display-name": "Cancel Job",
        },
        title="Cancel Job",
    )
    job_id: str = Field(
        ..., title="Job ID", description="The job_id of the job to cancel"
    )


class ReductoConfigureWebhookConfig(BaseModel):
    """Get the Svix portal URL where webhook delivery endpoints are managed."""

    operation: Literal["configure_webhook"] = Field(
        "configure_webhook",
        json_schema_extra={
            "const": "configure_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Configure Webhook",
        },
        title="Configure Webhook",
    )


class ReductoGetVersionConfig(BaseModel):
    """Return the running Reducto API version string."""

    operation: Literal["get_version"] = Field(
        "get_version",
        json_schema_extra={
            "const": "get_version",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get API Version",
        },
        title="Get API Version",
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class ReductoJobCompletedTriggerConfig(BaseModel):
    """Fire the workflow when an async job completes (Svix-signed delivery)."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_job_completed"] = Field(
        "on_job_completed",
        json_schema_extra={
            "const": "on_job_completed",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Job Completed",
        },
        title="On Job Completed",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Add this URL as a Svix endpoint via Configure Webhook, then async jobs deliver completion events here",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        default=None,
        title="Signing Secret",
        description="The Svix signing secret (whsec_...) from your endpoint, used to verify inbound events",
        json_schema_extra={"ui:widget": "password"},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


ReductoConfig = Annotated[
    Union[
        ReductoUploadConfig,
        ReductoParseConfig,
        ReductoParseAsyncConfig,
        ReductoExtractConfig,
        ReductoExtractAsyncConfig,
        ReductoSplitConfig,
        ReductoSplitAsyncConfig,
        ReductoClassifyConfig,
        ReductoEditConfig,
        ReductoEditAsyncConfig,
        ReductoPipelineConfig,
        ReductoPipelineAsyncConfig,
        ReductoGetJobConfig,
        ReductoListJobsConfig,
        ReductoCancelJobConfig,
        ReductoConfigureWebhookConfig,
        ReductoGetVersionConfig,
        ReductoJobCompletedTriggerConfig,
    ],
    Discriminator("operation"),
]


class ReductoNodeConfig(NodeConfig[ReductoConfig, ReductoCredential]):
    """Full configuration for the Reducto node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _parse_json_field(value: str, field_name: str) -> Any:
    """Parse a JSON string config field. Raise a clear error on malformed JSON."""
    try:
        return json.loads(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid JSON in '{field_name}': {e}")


def _parse_page_range(value: Optional[str]) -> Optional[Any]:
    """Parse page_range - accepts JSON object or leaves as-is."""
    if not value:
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


# ============================================================================
# HTTP Request Helper
# ============================================================================


async def _reducto_request(
    api_key: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Reducto request and return a structured result."""
    url = f"{REDUCTO_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if json_body is not None:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: str(v) for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = err.get("detail", err.get("message", err.get("error", str(err))))
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[ReductoNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                data: Any = {"success": True}
            else:
                try:
                    data = response.json()
                except Exception:
                    data = {"raw": response.text}
            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[ReductoNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ============================================================================
# Node Implementation
# ============================================================================


class ReductoNode(WorkflowNode):
    """Reducto document intelligence automation node."""

    edit_examples = [
        "Parse a PDF into structured markdown with tables and figures",
        "Extract invoice number, date, and total from a document using a JSON schema",
        "Split a multi-document scan into labeled sections",
        "Classify an uploaded document into a set of document types",
        "Trigger a workflow when an async parse job completes",
    ]

    @classmethod
    def get_config_model(cls):
        return ReductoNodeConfig

    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id: UUID,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Provision the internal webhook URL for the on_job_completed trigger."""
        if field_name != "webhook_url":
            return {"value": None}

        from utils.webhook_manager import WebhookManager

        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
        )
        return {
            "values": {
                "webhook_id": webhook_data.get("webhook_id"),
                "webhook_url": webhook_data.get("webhook_url"),
                "relay_connected": webhook_data.get("relay_connected"),
                "is_production": webhook_data.get("is_production"),
            }
        }

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify a Svix-signed inbound webhook.

        Svix signs with HMAC-SHA256 over "{id}.{timestamp}.{body}" keyed by the
        base64-decoded portion of the whsec_ secret, sending a space-delimited
        list of "v1,<base64sig>" entries in the svix-signature header.
        """
        import base64
        import hashlib
        import hmac

        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no secret stored - accept (trigger not yet armed)

        svix_id = headers.get("svix-id") or headers.get("webhook-id")
        svix_timestamp = headers.get("svix-timestamp") or headers.get("webhook-timestamp")
        svix_signature = headers.get("svix-signature") or headers.get("webhook-signature")
        if not (svix_id and svix_timestamp and svix_signature):
            return False

        key_b64 = secret.split("_", 1)[1] if secret.startswith("whsec_") else secret
        try:
            key = base64.b64decode(key_b64)
        except Exception:
            return False

        signed_content = f"{svix_id}.{svix_timestamp}.".encode() + body
        expected = base64.b64encode(
            hmac.new(key, signed_content, hashlib.sha256).digest()
        ).decode()

        for part in svix_signature.split(" "):
            if "," not in part:
                continue
            _, sent = part.split(",", 1)
            if hmac.compare_digest(sent, expected):
                return True
        return False

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, ReductoNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, ReductoJobCompletedTriggerConfig):
            return {
                "status": "success",
                "action": "on_job_completed",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Reducto API key.")
        api_key = credentials.api_key

        handlers = {
            "upload": self._upload,
            "parse": self._parse,
            "parse_async": self._parse_async,
            "extract": self._extract,
            "extract_async": self._extract_async,
            "split": self._split,
            "split_async": self._split_async,
            "classify": self._classify,
            "edit": self._edit,
            "edit_async": self._edit_async,
            "pipeline": self._pipeline,
            "pipeline_async": self._pipeline_async,
            "get_job": self._get_job,
            "list_jobs": self._list_jobs,
            "cancel_job": self._cancel_job,
            "configure_webhook": self._configure_webhook,
            "get_version": self._get_version,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_key)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _upload(self, c: ReductoUploadConfig, api_key: str) -> Dict[str, Any]:
        return await _reducto_request(
            api_key, "POST", "/upload", json_body={"file": c.file_url}, action_name="upload"
        )

    async def _parse(self, c: ReductoParseConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"input": c.document_url}
        if c.table_output_format:
            body.setdefault("formatting", {})["table_output_format"] = c.table_output_format
        if c.chunk_mode:
            body.setdefault("retrieval", {})["chunking"] = {"chunk_mode": c.chunk_mode}
        page_range = _parse_page_range(c.page_range)
        if page_range is not None:
            body.setdefault("settings", {})["page_range"] = page_range
        return await _reducto_request(api_key, "POST", "/parse", json_body=body, action_name="parse")

    async def _parse_async(self, c: ReductoParseAsyncConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"input": c.document_url}
        if c.table_output_format:
            body.setdefault("formatting", {})["table_output_format"] = c.table_output_format
        if c.chunk_mode:
            body.setdefault("retrieval", {})["chunking"] = {"chunk_mode": c.chunk_mode}
        page_range = _parse_page_range(c.page_range)
        if page_range is not None:
            body.setdefault("settings", {})["page_range"] = page_range
        if c.queue_priority:
            body["queue_priority"] = c.queue_priority
        return await _reducto_request(
            api_key, "POST", "/parse_async", json_body=body, action_name="parse_async"
        )

    async def _extract(self, c: ReductoExtractConfig, api_key: str) -> Dict[str, Any]:
        instructions: Dict[str, Any] = {"schema": _parse_json_field(c.output_schema, "JSON Schema")}
        if c.system_prompt:
            instructions["system_prompt"] = c.system_prompt
        body: Dict[str, Any] = {"input": c.document_url, "instructions": instructions}
        page_range = _parse_page_range(c.page_range)
        if page_range is not None:
            body.setdefault("settings", {})["page_range"] = page_range
        return await _reducto_request(api_key, "POST", "/extract", json_body=body, action_name="extract")

    async def _extract_async(self, c: ReductoExtractAsyncConfig, api_key: str) -> Dict[str, Any]:
        instructions: Dict[str, Any] = {"schema": _parse_json_field(c.output_schema, "JSON Schema")}
        if c.system_prompt:
            instructions["system_prompt"] = c.system_prompt
        body: Dict[str, Any] = {"input": c.document_url, "instructions": instructions}
        page_range = _parse_page_range(c.page_range)
        if page_range is not None:
            body.setdefault("settings", {})["page_range"] = page_range
        if c.queue_priority:
            body["queue_priority"] = c.queue_priority
        return await _reducto_request(
            api_key, "POST", "/extract_async", json_body=body, action_name="extract_async"
        )

    async def _split(self, c: ReductoSplitConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "input": c.document_url,
            "split_description": _parse_json_field(c.split_description, "Split Categories"),
        }
        if c.split_rules:
            body["split_rules"] = c.split_rules
        return await _reducto_request(api_key, "POST", "/split", json_body=body, action_name="split")

    async def _split_async(self, c: ReductoSplitAsyncConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "input": c.document_url,
            "split_description": _parse_json_field(c.split_description, "Split Categories"),
        }
        if c.split_rules:
            body["split_rules"] = c.split_rules
        if c.queue_priority:
            body["queue_priority"] = c.queue_priority
        return await _reducto_request(
            api_key, "POST", "/split_async", json_body=body, action_name="split_async"
        )

    async def _classify(self, c: ReductoClassifyConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "input": c.document_url,
            "classification_schema": _parse_json_field(c.categories, "Classification Schema"),
        }
        page_range = _parse_page_range(c.page_range)
        if page_range is not None:
            body["page_range"] = page_range
        if c.document_metadata:
            body["document_metadata"] = c.document_metadata
        return await _reducto_request(
            api_key, "POST", "/classify", json_body=body, action_name="classify"
        )

    async def _edit(self, c: ReductoEditConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "document_url": c.document_url,
            "edit_instructions": c.edit_instructions,
        }
        if c.form_schema:
            body["form_schema"] = _parse_json_field(c.form_schema, "Form Schema")
        if c.edit_options:
            body["edit_options"] = _parse_json_field(c.edit_options, "Edit Options")
        return await _reducto_request(api_key, "POST", "/edit", json_body=body, action_name="edit")

    async def _edit_async(self, c: ReductoEditAsyncConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "document_url": c.document_url,
            "edit_instructions": c.edit_instructions,
        }
        if c.form_schema:
            body["form_schema"] = _parse_json_field(c.form_schema, "Form Schema")
        if c.edit_options:
            body["edit_options"] = _parse_json_field(c.edit_options, "Edit Options")
        return await _reducto_request(
            api_key, "POST", "/edit_async", json_body=body, action_name="edit_async"
        )

    async def _pipeline(self, c: ReductoPipelineConfig, api_key: str) -> Dict[str, Any]:
        return await _reducto_request(
            api_key, "POST", "/pipeline",
            json_body={"input": c.document_url, "pipeline_id": c.pipeline_id},
            action_name="pipeline",
        )

    async def _pipeline_async(self, c: ReductoPipelineAsyncConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"input": c.document_url, "pipeline_id": c.pipeline_id}
        if c.queue_priority:
            body["queue_priority"] = c.queue_priority
        return await _reducto_request(
            api_key, "POST", "/pipeline_async", json_body=body, action_name="pipeline_async"
        )

    async def _get_job(self, c: ReductoGetJobConfig, api_key: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if c.timeout:
            params["timeout"] = c.timeout
        return await _reducto_request(
            api_key, "GET", f"/job/{c.job_id}", params=params or None, action_name="get_job"
        )

    async def _list_jobs(self, c: ReductoListJobsConfig, api_key: str) -> Dict[str, Any]:
        # API uses cursor-based pagination (cursor, not page number)
        return await _reducto_request(
            api_key, "GET", "/jobs",
            params={"cursor": c.cursor, "limit": c.limit, "api_key_prefix": c.api_key_prefix},
            action_name="list_jobs",
        )

    async def _cancel_job(self, c: ReductoCancelJobConfig, api_key: str) -> Dict[str, Any]:
        return await _reducto_request(
            api_key, "POST", f"/cancel/{c.job_id}", action_name="cancel_job"
        )

    async def _configure_webhook(self, c: ReductoConfigureWebhookConfig, api_key: str) -> Dict[str, Any]:
        return await _reducto_request(
            api_key, "POST", "/configure_webhook", action_name="configure_webhook"
        )

    async def _get_version(self, c: ReductoGetVersionConfig, api_key: str) -> Dict[str, Any]:
        return await _reducto_request(
            api_key, "GET", "/version", action_name="get_version"
        )
