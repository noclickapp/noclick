"""
Extend (extend.ai) document AI automation node.

Full coverage of the modern Extend REST API (api version 2026-02-09). Operations
are grouped by resource:

- Files: upload, get, list, delete
- Sync one-shots (≤5 min): parse, extract, classify, split, edit
- Parse / Extract / Classify / Split runs: create, get, list, cancel, delete, batch
- Edit runs: create, get, delete; edit schema generation; edit templates
- Extractors / Classifiers / Splitters: CRUD + versioning (create/list/get version)
- Workflows: CRUD + versioning; Workflow runs: create, get, list, update, cancel,
  delete, batch
- Webhook endpoints + subscriptions: CRUD
- Evaluation sets + items + runs
- Batch run status (batch_runs, batch_processor_runs)
- Webhook Trigger: fire when a run (parse/extract/classify/split/edit/workflow)
  completes or fails

The legacy ``processor*`` endpoints (pre-2026-02-09, superseded by extractors /
classifiers / splitters / workflows) are intentionally not exposed.

Authentication: API Key (Bearer token) + required ``x-extend-api-version`` header.
Organization-scoped keys also send ``X-Extend-Workspace-Id``.

API Base URL: https://api.extend.ai
Documentation: https://docs.extend.ai/api-reference

All ``*_run`` create endpoints are asynchronous: they return a run object with a
``status`` to poll (GET /{resource}_runs/{id}) or subscribe to via webhooks. The
sync one-shots (/parse, /extract, …) block up to 5 minutes and are intended for
onboarding / simple cases.
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from utils.ssrf import guarded_async_client
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin

logger = logging.getLogger(__name__)

EXTEND_API_BASE = "https://api.extend.ai"

# Raw HTTP requires this dated version header on every call (omitting it defaults
# server-side, but pinning keeps payload shapes stable).
EXTEND_API_VERSION = "2026-02-09"

# Run lifecycle events the trigger subscribes to on the GLOBAL webhook endpoint.
# Extend uses "processed"/"failed" (not "completed"). NOTE: workflow_run.* events
# are NOT valid on a global endpoint (the API rejects them — verified live); they
# are delivered only via resource-scoped webhook_subscriptions. So a global
# trigger fires on document-processing run completion (parse/extract/classify/
# split/edit) plus batch completion — not individual workflow runs.
RUN_COMPLETED_EVENTS = [
    "parse_run.processed",
    "parse_run.failed",
    "extract_run.processed",
    "extract_run.failed",
    "classify_run.processed",
    "classify_run.failed",
    "split_run.processed",
    "split_run.failed",
    "edit_run.processed",
    "edit_run.failed",
    "batch_processor_run.processed",
    "batch_processor_run.failed",
    "batch_parse_run.processed",
    "batch_parse_run.failed",
]


# ============================================================================
# Credential Schema
# ============================================================================


class ExtendApiKeyCredential(BaseModel):
    """API Key credential for Extend."""

    credential_type: Literal["extend_api_key"] = Field(
        "extend_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Extend API key from Dashboard -> Developer settings (https://dashboard.extend.ai/developers)",
        json_schema_extra={"ui:widget": "password"},
    )
    workspace_id: Optional[str] = Field(
        None,
        title="Workspace ID (org keys only)",
        description="Required only for organization-scoped keys (ws_...). Leave blank for workspace keys.",
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://dashboard.extend.ai/developers"}
    )


ExtendCredential = ExtendApiKeyCredential


# ============================================================================
# Shared field helpers
# ============================================================================


def _op(value: str, display: str, category: str, *, trigger: bool = False,
        creates: Optional[str] = None, id_path: Optional[str] = None) -> Any:
    extra: Dict[str, Any] = {
        "const": value,
        "ui:hidden": True,
        "x-category": category,
        "x-is-trigger": trigger,
        "x-display-name": display,
    }
    if creates:
        extra["x-creates-resource"] = True
        extra["x-resource-type"] = creates
        extra["x-resource-id-path"] = id_path
    return Field(value, title=display, json_schema_extra=extra)


def _page_size() -> Any:
    return Field("20", title="Page Size", description="Max number of results per page")


def _page_token() -> Any:
    return Field(None, title="Next Page Token", description="Cursor from a previous response")


def _sort_dir() -> Any:
    return Field(
        None, title="Sort Direction",
        json_schema_extra={"enum": ["asc", "desc"], "enumNames": ["Ascending", "Descending"],
                           "x-enum-searchable": True},
    )


def _json_field(title: str, description: str, *, required: bool = False) -> Any:
    return Field(
        ... if required else None,
        title=title,
        description=description,
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


def _file_id_field(desc: str = "An Extend file id (from Upload File). Takes precedence over File URL.") -> Any:
    return Field(None, title="File ID", description=desc)


def _file_url_field() -> Any:
    return Field(None, title="File URL", description="A publicly reachable URL to fetch the document from (used when File ID is empty).")


def _plain_text_field(title: str, description: str, *, required: bool = False) -> Any:
    return Field(... if required else None, title=title, description=description)


def _name_field(subject: str, *, required: bool = False, action: str = "use") -> Any:
    verb = "Use" if action == "use" else "Set"
    return _plain_text_field("Name", f"{verb} a human-readable name for this {subject}.", required=required)


def _run_id_field(run_type: str) -> Any:
    return _plain_text_field(f"{run_type} Run ID", f"The ID of the {run_type.lower()} run.", required=True)


def _batch_id_field(title: str = "Batch ID") -> Any:
    return _plain_text_field(title, f"Filter by the {title.lower()} returned from a batch request.")


def _version_id_field(subject: str = "version") -> Any:
    return _plain_text_field("Version ID", f"The ID of the {subject} to retrieve.", required=True)


def _endpoint_id_field() -> Any:
    return _plain_text_field("Webhook Endpoint ID", "The ID of the webhook endpoint.", required=True)


def _subscription_id_field() -> Any:
    return _plain_text_field("Webhook Subscription ID", "The ID of the webhook subscription.", required=True)


def _evaluation_set_id_field() -> Any:
    return _plain_text_field("Evaluation Set ID", "The ID of the evaluation set.", required=True)


def _item_id_field() -> Any:
    return _plain_text_field("Item ID", "The ID of the evaluation set item.", required=True)


def _template_id_field() -> Any:
    return _plain_text_field("Edit Template ID", "The ID of the edit template.", required=True)


def _resource_type_field() -> Any:
    return _plain_text_field("Resource Type", "The Extend resource type to subscribe to, for example workflow or extractor.", required=True)


def _resource_id_field(*, required: bool = True) -> Any:
    return _plain_text_field("Resource ID", "The ID of the Extend resource for this subscription.", required=required)


# Inline "Create new <resource>" builder affordances: picker field -> resource.
_FIELD_RESOURCE_TYPE = {"classifier_id": "extend_classifier"}


def _dyn(field_name: str, placeholder: str) -> Dict[str, Any]:
    label = field_name.replace("_id", "").replace("_", " ").strip()
    article = "an" if label[:1].lower() in "aeiou" else "a"
    extra: Dict[str, Any] = {
        "x-dynamic-options": {
            "field_name": field_name,
            "placeholder": placeholder,
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": f"Or paste {article} {label} ID",
        }
    }
    rt = _FIELD_RESOURCE_TYPE.get(field_name)
    if rt:
        extra["x-resource-type"] = rt
    return extra


# ============================================================================
# Files
# ============================================================================


class ExtendUploadFileConfig(BaseModel):
    """Upload a document to Extend (multipart) and get a fileId for processing."""

    operation: Literal["upload_file"] = _op("upload_file", "Upload File", "Files")
    file_url: str = Field(..., title="File URL", description="A publicly reachable URL of the document to upload")
    file_name: Optional[str] = Field(None, title="File Name", description="Optional name to store the file under")
    password: Optional[str] = Field(None, title="PDF Password", description="Password to unlock a protected PDF")
    convert_to_pdf: Optional[str] = Field(
        "false", title="Convert To PDF",
        description="Convert images/Office/HTML to PDF on upload",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class ExtendGetFileConfig(BaseModel):
    """Retrieve a file's metadata, and optionally its parsed text/markdown/html."""

    operation: Literal["get_file"] = _op("get_file", "Get File", "Files")
    file_id: str = Field(..., title="File ID", description="The id of the file to retrieve")
    raw_text: Optional[str] = Field("false", title="Include Raw Text",
                                    json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    markdown: Optional[str] = Field("false", title="Include Markdown",
                                    json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    html: Optional[str] = Field("false", title="Include HTML",
                                json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})


class ExtendListFilesConfig(BaseModel):
    """List uploaded files (cursor pagination)."""

    operation: Literal["list_files"] = _op("list_files", "List Files", "Files")
    name_contains: Optional[str] = Field(None, title="Name Contains", description="Filter by filename substring")
    sort_dir: Optional[str] = _sort_dir()
    max_page_size: Optional[str] = _page_size()
    next_page_token: Optional[str] = _page_token()


class ExtendDeleteFileConfig(BaseModel):
    """Delete an uploaded file."""

    operation: Literal["delete_file"] = _op("delete_file", "Delete File", "Files")
    file_id: str = Field(..., title="File ID", description="The id of the file to delete")


# ============================================================================
# Sync one-shots (≤5 min, onboarding / simple cases)
# ============================================================================


class ExtendParseSyncConfig(BaseModel):
    """Parse a document synchronously into clean markdown + blocks (≤5 min)."""

    operation: Literal["parse"] = _op("parse", "Parse (Sync)", "Sync")
    file_id: Optional[str] = _file_id_field()
    file_url: Optional[str] = _file_url_field()
    config: Optional[str] = _json_field("Parse Config", "Optional parse configuration (target format, chunking, etc.)")
    metadata: Optional[str] = _json_field("Metadata", "Optional run metadata (max 10KB)")
    response_type: Optional[str] = Field(
        None, title="Response Type",
        json_schema_extra={"enum": ["url", "raw"], "x-enum-searchable": True},
    )


class ExtendExtractSyncConfig(BaseModel):
    """Run structured extraction synchronously (≤5 min)."""

    operation: Literal["extract"] = _op("extract", "Extract (Sync)", "Sync")
    extractor_id: Optional[str] = Field(None, title="Extractor", json_schema_extra=_dyn("extractor_id", "Select an extractor..."))
    config: Optional[str] = _json_field("Inline Config", "Inline extract config (mutually exclusive with Extractor)")
    file_id: Optional[str] = _file_id_field()
    file_url: Optional[str] = _file_url_field()
    metadata: Optional[str] = _json_field("Metadata", "Optional run metadata")


class ExtendClassifySyncConfig(BaseModel):
    """Classify a document synchronously (≤5 min)."""

    operation: Literal["classify"] = _op("classify", "Classify (Sync)", "Sync")
    classifier_id: Optional[str] = Field(None, title="Classifier", json_schema_extra=_dyn("classifier_id", "Select a classifier..."))
    config: Optional[str] = _json_field("Inline Config", "Inline classify config (mutually exclusive with Classifier)")
    file_id: str = Field(..., title="File ID", description="The Extend file id to classify")
    metadata: Optional[str] = _json_field("Metadata", "Optional run metadata")


class ExtendSplitSyncConfig(BaseModel):
    """Split a multi-document file synchronously (≤5 min)."""

    operation: Literal["split"] = _op("split", "Split (Sync)", "Sync")
    splitter_id: Optional[str] = Field(None, title="Splitter", json_schema_extra=_dyn("splitter_id", "Select a splitter..."))
    config: Optional[str] = _json_field("Inline Config", "Inline split config (mutually exclusive with Splitter)")
    file_id: str = Field(..., title="File ID", description="The Extend file id to split")
    metadata: Optional[str] = _json_field("Metadata", "Optional run metadata")


class ExtendEditSyncConfig(BaseModel):
    """Edit a document synchronously (≤5 min)."""

    operation: Literal["edit"] = _op("edit", "Edit (Sync)", "Sync")
    file_id: str = Field(..., title="File ID", description="The Extend file id to edit")
    config: Optional[str] = _json_field("Edit Config", "Edit config: schema + instructions")


# ============================================================================
# Parse Runs
# ============================================================================


class ExtendCreateParseRunConfig(BaseModel):
    """Parse a file into clean, chunked, LLM-ready markdown + structured blocks."""

    operation: Literal["create_parse_run"] = _op("create_parse_run", "Create Parse Run", "Parse")
    file_id: Optional[str] = _file_id_field()
    file_url: Optional[str] = _file_url_field()
    config: Optional[str] = _json_field("Parse Config", "Optional parse configuration")
    metadata: Optional[str] = _json_field("Metadata", "Optional run metadata")


class ExtendGetParseRunConfig(BaseModel):
    """Poll a parse run for status and parsed output."""

    operation: Literal["get_parse_run"] = _op("get_parse_run", "Get Parse Run", "Parse")
    run_id: str = Field(..., title="Parse Run ID", description="The parse run to poll")
    response_type: Optional[str] = Field(None, title="Response Type",
                                         json_schema_extra={"enum": ["url", "raw"], "x-enum-searchable": True})


class ExtendListParseRunsConfig(BaseModel):
    """List parse runs (cursor pagination)."""

    operation: Literal["list_parse_runs"] = _op("list_parse_runs", "List Parse Runs", "Parse")
    status: Optional[str] = Field(None, title="Status", description="Filter by run status")
    file_name_contains: Optional[str] = Field(None, title="File Name Contains", description="Filter by a substring in the source file name.")
    batch_id: Optional[str] = _batch_id_field()
    source: Optional[str] = Field(None, title="Source", description="Filter by the source that created the run.")
    source_id: Optional[str] = Field(None, title="Source ID", description="Filter by the source object ID that created the run.")
    max_page_size: Optional[str] = _page_size()
    next_page_token: Optional[str] = _page_token()


class ExtendCancelParseRunConfig(BaseModel):
    """Cancel an in-progress parse run."""

    operation: Literal["cancel_parse_run"] = _op("cancel_parse_run", "Cancel Parse Run", "Parse")
    run_id: str = _run_id_field("Parse")


class ExtendDeleteParseRunConfig(BaseModel):
    """Delete a parse run."""

    operation: Literal["delete_parse_run"] = _op("delete_parse_run", "Delete Parse Run", "Parse")
    run_id: str = _run_id_field("Parse")


class ExtendBatchParseRunsConfig(BaseModel):
    """Create many parse runs in one batch."""

    operation: Literal["batch_parse_runs"] = _op("batch_parse_runs", "Batch Parse Runs", "Parse")
    inputs: str = _json_field("Inputs", "JSON array of file inputs, e.g. [{\"file\":{\"id\":\"...\"}}]", required=True)
    config: Optional[str] = _json_field("Parse Config", "Optional parse config applied to all inputs")
    priority: Optional[str] = Field(None, title="Priority", description="Run priority (default 50)")


# ============================================================================
# Extract Runs
# ============================================================================


class ExtendCreateExtractRunConfig(BaseModel):
    """Run structured data extraction on a file using an extractor."""

    operation: Literal["create_extract_run"] = _op("create_extract_run", "Create Extract Run", "Extract")
    extractor_id: Optional[str] = Field(None, title="Extractor", json_schema_extra=_dyn("extractor_id", "Select an extractor..."))
    config: Optional[str] = _json_field("Inline Config", "Inline extract config (mutually exclusive with Extractor)")
    file_id: Optional[str] = _file_id_field()
    file_url: Optional[str] = _file_url_field()
    priority: Optional[str] = Field(None, title="Priority")
    metadata: Optional[str] = _json_field("Metadata", "Optional run metadata")


class ExtendGetExtractRunConfig(BaseModel):
    """Poll an extract run for status and extracted JSON."""

    operation: Literal["get_extract_run"] = _op("get_extract_run", "Get Extract Run", "Extract")
    run_id: str = _run_id_field("Extract")


class ExtendListExtractRunsConfig(BaseModel):
    """List extract runs (cursor pagination)."""

    operation: Literal["list_extract_runs"] = _op("list_extract_runs", "List Extract Runs", "Extract")
    status: Optional[str] = Field(None, title="Status", description="Filter by run status.")
    extractor_id: Optional[str] = Field(None, title="Extractor ID", description="Filter by extractor ID.")
    file_name_contains: Optional[str] = Field(None, title="File Name Contains", description="Filter by a substring in the source file name.")
    batch_id: Optional[str] = _batch_id_field()
    source: Optional[str] = Field(None, title="Source", description="Filter by the source that created the run.")
    source_id: Optional[str] = Field(None, title="Source ID", description="Filter by the source object ID that created the run.")
    sort_dir: Optional[str] = _sort_dir()
    max_page_size: Optional[str] = _page_size()
    next_page_token: Optional[str] = _page_token()


class ExtendCancelExtractRunConfig(BaseModel):
    operation: Literal["cancel_extract_run"] = _op("cancel_extract_run", "Cancel Extract Run", "Extract")
    run_id: str = _run_id_field("Extract")


class ExtendDeleteExtractRunConfig(BaseModel):
    operation: Literal["delete_extract_run"] = _op("delete_extract_run", "Delete Extract Run", "Extract")
    run_id: str = _run_id_field("Extract")


class ExtendBatchExtractRunsConfig(BaseModel):
    operation: Literal["batch_extract_runs"] = _op("batch_extract_runs", "Batch Extract Runs", "Extract")
    extractor_id: str = Field(..., title="Extractor", json_schema_extra=_dyn("extractor_id", "Select an extractor..."))
    inputs: str = _json_field("Inputs", "JSON array of file inputs", required=True)
    priority: Optional[str] = Field(None, title="Priority")


# ============================================================================
# Extractors (+ versions)
# ============================================================================


class ExtendCreateExtractorConfig(BaseModel):
    """Create a reusable extractor (schema + prompt config)."""

    operation: Literal["create_extractor"] = _op("create_extractor", "Create Extractor", "Extractors")
    name: str = Field(..., title="Name", description="Display name for the extractor")
    config: Optional[str] = _json_field("Config", "Extractor config (schema, instructions, options)")
    clone_extractor_id: Optional[str] = Field(None, title="Clone From Extractor ID", description="Seed from an existing extractor")
    generate: Optional[str] = _json_field("Generate", "Optional auto-generation instructions")


class ExtendGetExtractorConfig(BaseModel):
    operation: Literal["get_extractor"] = _op("get_extractor", "Get Extractor", "Extractors")
    extractor_id: str = Field(..., title="Extractor", json_schema_extra=_dyn("extractor_id", "Select an extractor..."))


class ExtendUpdateExtractorConfig(BaseModel):
    operation: Literal["update_extractor"] = _op("update_extractor", "Update Extractor", "Extractors")
    extractor_id: str = Field(..., title="Extractor", json_schema_extra=_dyn("extractor_id", "Select an extractor..."))
    name: Optional[str] = _name_field("extractor", action="set")
    config: Optional[str] = _json_field("Config", "Updated extractor config")


class ExtendListExtractorsConfig(BaseModel):
    operation: Literal["list_extractors"] = _op("list_extractors", "List Extractors", "Extractors")
    sort_by: Optional[str] = Field(None, title="Sort By")
    sort_dir: Optional[str] = _sort_dir()
    max_page_size: Optional[str] = _page_size()
    next_page_token: Optional[str] = _page_token()


class ExtendCreateExtractorVersionConfig(BaseModel):
    operation: Literal["create_extractor_version"] = _op("create_extractor_version", "Create Extractor Version", "Extractors")
    extractor_id: str = Field(..., title="Extractor", json_schema_extra=_dyn("extractor_id", "Select an extractor..."))
    release_type: str = Field(..., title="Release Type",
                              json_schema_extra={"enum": ["major", "minor", "patch"], "x-enum-searchable": True})
    description: Optional[str] = Field(None, title="Description")
    config: Optional[str] = _json_field("Config", "Version config override")


class ExtendListExtractorVersionsConfig(BaseModel):
    operation: Literal["list_extractor_versions"] = _op("list_extractor_versions", "List Extractor Versions", "Extractors")
    extractor_id: str = Field(..., title="Extractor", json_schema_extra=_dyn("extractor_id", "Select an extractor..."))
    sort_dir: Optional[str] = _sort_dir()
    max_page_size: Optional[str] = _page_size()
    next_page_token: Optional[str] = _page_token()


class ExtendGetExtractorVersionConfig(BaseModel):
    operation: Literal["get_extractor_version"] = _op("get_extractor_version", "Get Extractor Version", "Extractors")
    extractor_id: str = Field(..., title="Extractor", json_schema_extra=_dyn("extractor_id", "Select an extractor..."))
    version_id: str = _version_id_field("extractor version")


# ============================================================================
# Classify Runs
# ============================================================================


class ExtendCreateClassifyRunConfig(BaseModel):
    """Classify a file into one of a configured set of document types."""

    operation: Literal["create_classify_run"] = _op("create_classify_run", "Create Classify Run", "Classify")
    classifier_id: Optional[str] = Field(None, title="Classifier", json_schema_extra=_dyn("classifier_id", "Select a classifier..."))
    config: Optional[str] = _json_field("Inline Config", "Inline classify config (mutually exclusive with Classifier)")
    file_id: str = Field(..., title="File ID", description="The file to classify")
    priority: Optional[str] = Field(None, title="Priority")
    metadata: Optional[str] = _json_field("Metadata", "Optional run metadata")


class ExtendGetClassifyRunConfig(BaseModel):
    operation: Literal["get_classify_run"] = _op("get_classify_run", "Get Classify Run", "Classify")
    run_id: str = _run_id_field("Classify")


class ExtendListClassifyRunsConfig(BaseModel):
    operation: Literal["list_classify_runs"] = _op("list_classify_runs", "List Classify Runs", "Classify")
    status: Optional[str] = Field(None, title="Status", description="Filter by run status.")
    classifier_id: Optional[str] = Field(None, title="Classifier ID", description="Filter by classifier ID.")
    file_name_contains: Optional[str] = Field(None, title="File Name Contains", description="Filter by a substring in the source file name.")
    batch_id: Optional[str] = _batch_id_field()
    source: Optional[str] = Field(None, title="Source", description="Filter by the source that created the run.")
    source_id: Optional[str] = Field(None, title="Source ID", description="Filter by the source object ID that created the run.")
    sort_dir: Optional[str] = _sort_dir()
    max_page_size: Optional[str] = _page_size()
    next_page_token: Optional[str] = _page_token()


class ExtendCancelClassifyRunConfig(BaseModel):
    operation: Literal["cancel_classify_run"] = _op("cancel_classify_run", "Cancel Classify Run", "Classify")
    run_id: str = _run_id_field("Classify")


class ExtendDeleteClassifyRunConfig(BaseModel):
    operation: Literal["delete_classify_run"] = _op("delete_classify_run", "Delete Classify Run", "Classify")
    run_id: str = _run_id_field("Classify")


class ExtendBatchClassifyRunsConfig(BaseModel):
    operation: Literal["batch_classify_runs"] = _op("batch_classify_runs", "Batch Classify Runs", "Classify")
    classifier_id: str = Field(..., title="Classifier", json_schema_extra=_dyn("classifier_id", "Select a classifier..."))
    inputs: str = _json_field("Inputs", "JSON array of file inputs", required=True)
    priority: Optional[str] = Field(None, title="Priority")


# ============================================================================
# Classifiers (+ versions)
# ============================================================================


class ExtendCreateClassifierConfig(BaseModel):
    operation: Literal["create_classifier"] = _op("create_classifier", "Create Classifier", "Classifiers", creates="extend_classifier", id_path="data.id")
    name: str = _name_field("classifier", required=True)
    config: Optional[str] = _json_field("Config", "Classifier config (types/options)")
    clone_classifier_id: Optional[str] = Field(None, title="Clone From Classifier ID")


class ExtendGetClassifierConfig(BaseModel):
    operation: Literal["get_classifier"] = _op("get_classifier", "Get Classifier", "Classifiers")
    classifier_id: str = Field(..., title="Classifier", json_schema_extra=_dyn("classifier_id", "Select a classifier..."))


class ExtendUpdateClassifierConfig(BaseModel):
    operation: Literal["update_classifier"] = _op("update_classifier", "Update Classifier", "Classifiers")
    classifier_id: str = Field(..., title="Classifier", json_schema_extra=_dyn("classifier_id", "Select a classifier..."))
    name: Optional[str] = _name_field("classifier", action="set")
    config: Optional[str] = _json_field("Config", "Updated classifier config")


class ExtendListClassifiersConfig(BaseModel):
    operation: Literal["list_classifiers"] = _op("list_classifiers", "List Classifiers", "Classifiers")
    sort_by: Optional[str] = Field(None, title="Sort By")
    sort_dir: Optional[str] = _sort_dir()
    max_page_size: Optional[str] = _page_size()
    next_page_token: Optional[str] = _page_token()


class ExtendCreateClassifierVersionConfig(BaseModel):
    operation: Literal["create_classifier_version"] = _op("create_classifier_version", "Create Classifier Version", "Classifiers")
    classifier_id: str = Field(..., title="Classifier", json_schema_extra=_dyn("classifier_id", "Select a classifier..."))
    release_type: str = Field(..., title="Release Type",
                              json_schema_extra={"enum": ["major", "minor", "patch"], "x-enum-searchable": True})
    description: Optional[str] = Field(None, title="Description")
    config: Optional[str] = _json_field("Config", "Version config override")


class ExtendListClassifierVersionsConfig(BaseModel):
    operation: Literal["list_classifier_versions"] = _op("list_classifier_versions", "List Classifier Versions", "Classifiers")
    classifier_id: str = Field(..., title="Classifier", json_schema_extra=_dyn("classifier_id", "Select a classifier..."))
    sort_dir: Optional[str] = _sort_dir()
    max_page_size: Optional[str] = _page_size()
    next_page_token: Optional[str] = _page_token()


class ExtendGetClassifierVersionConfig(BaseModel):
    operation: Literal["get_classifier_version"] = _op("get_classifier_version", "Get Classifier Version", "Classifiers")
    classifier_id: str = Field(..., title="Classifier", json_schema_extra=_dyn("classifier_id", "Select a classifier..."))
    version_id: str = _version_id_field("classifier version")


# ============================================================================
# Split Runs
# ============================================================================


class ExtendCreateSplitRunConfig(BaseModel):
    """Split a multi-document file into logical sub-documents."""

    operation: Literal["create_split_run"] = _op("create_split_run", "Create Split Run", "Split")
    splitter_id: Optional[str] = Field(None, title="Splitter", json_schema_extra=_dyn("splitter_id", "Select a splitter..."))
    config: Optional[str] = _json_field("Inline Config", "Inline split config (mutually exclusive with Splitter)")
    file_id: str = Field(..., title="File ID", description="The multi-document file to split")
    priority: Optional[str] = Field(None, title="Priority")
    metadata: Optional[str] = _json_field("Metadata", "Optional run metadata")


class ExtendGetSplitRunConfig(BaseModel):
    operation: Literal["get_split_run"] = _op("get_split_run", "Get Split Run", "Split")
    run_id: str = _run_id_field("Split")


class ExtendListSplitRunsConfig(BaseModel):
    operation: Literal["list_split_runs"] = _op("list_split_runs", "List Split Runs", "Split")
    status: Optional[str] = Field(None, title="Status", description="Filter by run status.")
    splitter_id: Optional[str] = Field(None, title="Splitter ID", description="Filter by splitter ID.")
    file_name_contains: Optional[str] = Field(None, title="File Name Contains", description="Filter by a substring in the source file name.")
    batch_id: Optional[str] = _batch_id_field()
    source: Optional[str] = Field(None, title="Source", description="Filter by the source that created the run.")
    source_id: Optional[str] = Field(None, title="Source ID", description="Filter by the source object ID that created the run.")
    sort_dir: Optional[str] = _sort_dir()
    max_page_size: Optional[str] = _page_size()
    next_page_token: Optional[str] = _page_token()


class ExtendCancelSplitRunConfig(BaseModel):
    operation: Literal["cancel_split_run"] = _op("cancel_split_run", "Cancel Split Run", "Split")
    run_id: str = _run_id_field("Split")


class ExtendDeleteSplitRunConfig(BaseModel):
    operation: Literal["delete_split_run"] = _op("delete_split_run", "Delete Split Run", "Split")
    run_id: str = _run_id_field("Split")


class ExtendBatchSplitRunsConfig(BaseModel):
    operation: Literal["batch_split_runs"] = _op("batch_split_runs", "Batch Split Runs", "Split")
    splitter_id: str = Field(..., title="Splitter", json_schema_extra=_dyn("splitter_id", "Select a splitter..."))
    inputs: str = _json_field("Inputs", "JSON array of file inputs", required=True)
    priority: Optional[str] = Field(None, title="Priority")


# ============================================================================
# Splitters (+ versions)
# ============================================================================


class ExtendCreateSplitterConfig(BaseModel):
    operation: Literal["create_splitter"] = _op("create_splitter", "Create Splitter", "Splitters")
    name: str = _name_field("splitter", required=True)
    config: Optional[str] = _json_field("Config", "Splitter config")
    clone_splitter_id: Optional[str] = Field(None, title="Clone From Splitter ID")


class ExtendGetSplitterConfig(BaseModel):
    operation: Literal["get_splitter"] = _op("get_splitter", "Get Splitter", "Splitters")
    splitter_id: str = Field(..., title="Splitter", json_schema_extra=_dyn("splitter_id", "Select a splitter..."))


class ExtendUpdateSplitterConfig(BaseModel):
    operation: Literal["update_splitter"] = _op("update_splitter", "Update Splitter", "Splitters")
    splitter_id: str = Field(..., title="Splitter", json_schema_extra=_dyn("splitter_id", "Select a splitter..."))
    name: Optional[str] = _name_field("splitter", action="set")
    config: Optional[str] = _json_field("Config", "Updated splitter config")


class ExtendListSplittersConfig(BaseModel):
    operation: Literal["list_splitters"] = _op("list_splitters", "List Splitters", "Splitters")
    sort_by: Optional[str] = Field(None, title="Sort By")
    sort_dir: Optional[str] = _sort_dir()
    max_page_size: Optional[str] = _page_size()
    next_page_token: Optional[str] = _page_token()


class ExtendCreateSplitterVersionConfig(BaseModel):
    operation: Literal["create_splitter_version"] = _op("create_splitter_version", "Create Splitter Version", "Splitters")
    splitter_id: str = Field(..., title="Splitter", json_schema_extra=_dyn("splitter_id", "Select a splitter..."))
    release_type: str = Field(..., title="Release Type",
                              json_schema_extra={"enum": ["major", "minor", "patch"], "x-enum-searchable": True})
    description: Optional[str] = Field(None, title="Description")
    config: Optional[str] = _json_field("Config", "Version config override")


class ExtendListSplitterVersionsConfig(BaseModel):
    operation: Literal["list_splitter_versions"] = _op("list_splitter_versions", "List Splitter Versions", "Splitters")
    splitter_id: str = Field(..., title="Splitter", json_schema_extra=_dyn("splitter_id", "Select a splitter..."))
    sort_dir: Optional[str] = _sort_dir()
    max_page_size: Optional[str] = _page_size()
    next_page_token: Optional[str] = _page_token()


class ExtendGetSplitterVersionConfig(BaseModel):
    operation: Literal["get_splitter_version"] = _op("get_splitter_version", "Get Splitter Version", "Splitters")
    splitter_id: str = Field(..., title="Splitter", json_schema_extra=_dyn("splitter_id", "Select a splitter..."))
    version_id: str = _version_id_field("splitter version")


# ============================================================================
# Edit Runs / Schemas / Templates
# ============================================================================


class ExtendCreateEditRunConfig(BaseModel):
    """Run a programmatic document edit (config = schema + instructions)."""

    operation: Literal["create_edit_run"] = _op("create_edit_run", "Create Edit Run", "Edit")
    file_id: Optional[str] = _file_id_field()
    file_url: Optional[str] = _file_url_field()
    config: Optional[str] = _json_field("Edit Config", "Edit config: schema, instructions, advancedOptions")


class ExtendGetEditRunConfig(BaseModel):
    operation: Literal["get_edit_run"] = _op("get_edit_run", "Get Edit Run", "Edit")
    run_id: str = _run_id_field("Edit")


class ExtendDeleteEditRunConfig(BaseModel):
    operation: Literal["delete_edit_run"] = _op("delete_edit_run", "Delete Edit Run", "Edit")
    run_id: str = _run_id_field("Edit")


class ExtendGenerateEditSchemaConfig(BaseModel):
    """Analyze a document and auto-generate an edit schema."""

    operation: Literal["generate_edit_schema"] = _op("generate_edit_schema", "Generate Edit Schema", "Edit")
    file_id: Optional[str] = _file_id_field()
    file_url: Optional[str] = _file_url_field()
    config: Optional[str] = _json_field("Config", "Optional generation config / instructions")


class ExtendGetEditTemplateConfig(BaseModel):
    operation: Literal["get_edit_template"] = _op("get_edit_template", "Get Edit Template", "Edit")
    template_id: str = _template_id_field()


# ============================================================================
# Workflows (+ versions)
# ============================================================================


class ExtendCreateWorkflowConfig(BaseModel):
    operation: Literal["create_workflow"] = _op("create_workflow", "Create Workflow", "Workflows")
    name: str = _name_field("workflow", required=True)
    steps: Optional[str] = _json_field("Steps", "JSON array of workflow steps")


class ExtendGetWorkflowConfig(BaseModel):
    operation: Literal["get_workflow"] = _op("get_workflow", "Get Workflow", "Workflows")
    workflow_id: str = Field(..., title="Workflow", json_schema_extra=_dyn("workflow_id", "Select a workflow..."))


class ExtendUpdateWorkflowConfig(BaseModel):
    operation: Literal["update_workflow"] = _op("update_workflow", "Update Workflow", "Workflows")
    workflow_id: str = Field(..., title="Workflow", json_schema_extra=_dyn("workflow_id", "Select a workflow..."))
    name: Optional[str] = _name_field("workflow", action="set")
    steps: Optional[str] = _json_field("Steps", "Updated JSON array of workflow steps")


class ExtendListWorkflowsConfig(BaseModel):
    operation: Literal["list_workflows"] = _op("list_workflows", "List Workflows", "Workflows")
    sort_by: Optional[str] = Field(None, title="Sort By")
    sort_dir: Optional[str] = _sort_dir()
    max_page_size: Optional[str] = _page_size()
    next_page_token: Optional[str] = _page_token()


class ExtendCreateWorkflowVersionConfig(BaseModel):
    operation: Literal["create_workflow_version"] = _op("create_workflow_version", "Create Workflow Version", "Workflows")
    workflow_id: str = Field(..., title="Workflow", json_schema_extra=_dyn("workflow_id", "Select a workflow..."))
    name: Optional[str] = _name_field("workflow version", action="set")
    steps: Optional[str] = _json_field("Steps", "JSON array of workflow steps")


class ExtendListWorkflowVersionsConfig(BaseModel):
    operation: Literal["list_workflow_versions"] = _op("list_workflow_versions", "List Workflow Versions", "Workflows")
    workflow_id: str = Field(..., title="Workflow", json_schema_extra=_dyn("workflow_id", "Select a workflow..."))
    sort_dir: Optional[str] = _sort_dir()
    max_page_size: Optional[str] = _page_size()
    next_page_token: Optional[str] = _page_token()


class ExtendGetWorkflowVersionConfig(BaseModel):
    operation: Literal["get_workflow_version"] = _op("get_workflow_version", "Get Workflow Version", "Workflows")
    workflow_id: str = Field(..., title="Workflow", json_schema_extra=_dyn("workflow_id", "Select a workflow..."))
    version_id: str = _version_id_field("workflow version")


# ============================================================================
# Workflow Runs
# ============================================================================


class ExtendCreateWorkflowRunConfig(BaseModel):
    """Run a configured Extend workflow on a file."""

    operation: Literal["create_workflow_run"] = _op("create_workflow_run", "Create Workflow Run", "Workflow Runs")
    workflow_id: str = Field(..., title="Workflow", json_schema_extra=_dyn("workflow_id", "Select a workflow..."))
    file_id: Optional[str] = _file_id_field()
    file_url: Optional[str] = _file_url_field()
    version: Optional[str] = Field(None, title="Workflow Version", description="Specific version or 'draft'")
    outputs: Optional[str] = _json_field("Outputs", "Optional predetermined processor outputs (override)")
    priority: Optional[str] = Field(None, title="Priority")
    metadata: Optional[str] = _json_field("Metadata", "Optional run metadata")
    secrets: Optional[str] = _json_field("Secrets", "Optional secrets for processor use")


class ExtendGetWorkflowRunConfig(BaseModel):
    operation: Literal["get_workflow_run"] = _op("get_workflow_run", "Get Workflow Run", "Workflow Runs")
    run_id: str = _run_id_field("Workflow")


class ExtendListWorkflowRunsConfig(BaseModel):
    operation: Literal["list_workflow_runs"] = _op("list_workflow_runs", "List Workflow Runs", "Workflow Runs")
    status: Optional[str] = Field(None, title="Status", description="Filter by run status.")
    workflow_id: Optional[str] = Field(None, title="Workflow ID", description="Filter by workflow ID.")
    file_name_contains: Optional[str] = Field(None, title="File Name Contains", description="Filter by a substring in the source file name.")
    batch_id: Optional[str] = _batch_id_field()
    sort_dir: Optional[str] = _sort_dir()
    max_page_size: Optional[str] = _page_size()
    next_page_token: Optional[str] = _page_token()


class ExtendUpdateWorkflowRunConfig(BaseModel):
    operation: Literal["update_workflow_run"] = _op("update_workflow_run", "Update Workflow Run", "Workflow Runs")
    run_id: str = _run_id_field("Workflow")
    name: Optional[str] = _name_field("workflow run", action="set")
    metadata: Optional[str] = _json_field("Metadata", "Updated run metadata")


class ExtendCancelWorkflowRunConfig(BaseModel):
    operation: Literal["cancel_workflow_run"] = _op("cancel_workflow_run", "Cancel Workflow Run", "Workflow Runs")
    run_id: str = _run_id_field("Workflow")


class ExtendDeleteWorkflowRunConfig(BaseModel):
    operation: Literal["delete_workflow_run"] = _op("delete_workflow_run", "Delete Workflow Run", "Workflow Runs")
    run_id: str = _run_id_field("Workflow")


class ExtendBatchWorkflowRunsConfig(BaseModel):
    operation: Literal["batch_workflow_runs"] = _op("batch_workflow_runs", "Batch Workflow Runs", "Workflow Runs")
    workflow_id: str = Field(..., title="Workflow", json_schema_extra=_dyn("workflow_id", "Select a workflow..."))
    inputs: str = _json_field("Inputs", "JSON array of file inputs", required=True)
    priority: Optional[str] = Field(None, title="Priority")


# ============================================================================
# Webhook Endpoints
# ============================================================================


class ExtendCreateWebhookEndpointConfig(BaseModel):
    operation: Literal["create_webhook_endpoint"] = _op("create_webhook_endpoint", "Create Webhook Endpoint", "Webhooks")
    url: str = Field(..., title="URL", description="HTTPS URL to deliver events to")
    name: str = _name_field("webhook endpoint", required=True)
    enabled_events: str = _json_field("Enabled Events", "JSON array of event types, e.g. [\"workflow_run.completed\"]", required=True)
    status: Optional[str] = Field(None, title="Status",
                                  json_schema_extra={"enum": ["enabled", "disabled"], "x-enum-searchable": True})
    advanced_options: Optional[str] = _json_field("Advanced Options", "Custom headers / delivery settings")


class ExtendListWebhookEndpointsConfig(BaseModel):
    operation: Literal["list_webhook_endpoints"] = _op("list_webhook_endpoints", "List Webhook Endpoints", "Webhooks")
    status: Optional[str] = Field(None, title="Status")
    sort_dir: Optional[str] = _sort_dir()
    max_page_size: Optional[str] = _page_size()
    next_page_token: Optional[str] = _page_token()


class ExtendGetWebhookEndpointConfig(BaseModel):
    operation: Literal["get_webhook_endpoint"] = _op("get_webhook_endpoint", "Get Webhook Endpoint", "Webhooks")
    endpoint_id: str = _endpoint_id_field()


class ExtendUpdateWebhookEndpointConfig(BaseModel):
    operation: Literal["update_webhook_endpoint"] = _op("update_webhook_endpoint", "Update Webhook Endpoint", "Webhooks")
    endpoint_id: str = _endpoint_id_field()
    url: Optional[str] = Field(None, title="URL", description="The HTTPS URL to deliver events to.")
    name: Optional[str] = _name_field("webhook endpoint", action="set")
    enabled_events: Optional[str] = _json_field("Enabled Events", "JSON array of event types")
    status: Optional[str] = Field(None, title="Status",
                                  json_schema_extra={"enum": ["enabled", "disabled"], "x-enum-searchable": True})
    advanced_options: Optional[str] = _json_field("Advanced Options", "Custom headers / delivery settings")


class ExtendDeleteWebhookEndpointConfig(BaseModel):
    operation: Literal["delete_webhook_endpoint"] = _op("delete_webhook_endpoint", "Delete Webhook Endpoint", "Webhooks")
    endpoint_id: str = _endpoint_id_field()


# ============================================================================
# Webhook Subscriptions
# ============================================================================


class ExtendCreateWebhookSubscriptionConfig(BaseModel):
    operation: Literal["create_webhook_subscription"] = _op("create_webhook_subscription", "Create Webhook Subscription", "Webhooks")
    webhook_endpoint_id: str = _plain_text_field("Webhook Endpoint ID", "The webhook endpoint that should receive these events.", required=True)
    resource_type: str = _resource_type_field()
    resource_id: str = _resource_id_field()
    enabled_events: str = _json_field("Enabled Events", "JSON array of event types", required=True)


class ExtendListWebhookSubscriptionsConfig(BaseModel):
    operation: Literal["list_webhook_subscriptions"] = _op("list_webhook_subscriptions", "List Webhook Subscriptions", "Webhooks")
    webhook_endpoint_id: Optional[str] = _plain_text_field("Webhook Endpoint ID", "Filter by the webhook endpoint ID.")
    resource_id: Optional[str] = _resource_id_field(required=False)
    sort_dir: Optional[str] = _sort_dir()
    max_page_size: Optional[str] = _page_size()
    next_page_token: Optional[str] = _page_token()


class ExtendGetWebhookSubscriptionConfig(BaseModel):
    operation: Literal["get_webhook_subscription"] = _op("get_webhook_subscription", "Get Webhook Subscription", "Webhooks")
    subscription_id: str = _subscription_id_field()


class ExtendUpdateWebhookSubscriptionConfig(BaseModel):
    operation: Literal["update_webhook_subscription"] = _op("update_webhook_subscription", "Update Webhook Subscription", "Webhooks")
    subscription_id: str = _subscription_id_field()
    enabled_events: str = _json_field("Enabled Events", "JSON array of event types", required=True)


class ExtendDeleteWebhookSubscriptionConfig(BaseModel):
    operation: Literal["delete_webhook_subscription"] = _op("delete_webhook_subscription", "Delete Webhook Subscription", "Webhooks")
    subscription_id: str = _subscription_id_field()


# ============================================================================
# Evaluation Sets / Items / Runs
# ============================================================================


class ExtendCreateEvaluationSetConfig(BaseModel):
    operation: Literal["create_evaluation_set"] = _op("create_evaluation_set", "Create Evaluation Set", "Evaluation")
    name: str = _name_field("evaluation set", required=True)
    entity_id: str = Field(..., title="Entity ID", description="The processor/workflow this set evaluates")
    description: Optional[str] = Field(None, title="Description")


class ExtendListEvaluationSetsConfig(BaseModel):
    operation: Literal["list_evaluation_sets"] = _op("list_evaluation_sets", "List Evaluation Sets", "Evaluation")
    entity_id: Optional[str] = Field(None, title="Entity ID")
    sort_by: Optional[str] = Field(None, title="Sort By")
    sort_dir: Optional[str] = _sort_dir()
    max_page_size: Optional[str] = _page_size()
    next_page_token: Optional[str] = _page_token()


class ExtendGetEvaluationSetConfig(BaseModel):
    operation: Literal["get_evaluation_set"] = _op("get_evaluation_set", "Get Evaluation Set", "Evaluation")
    evaluation_set_id: str = _evaluation_set_id_field()


class ExtendCreateEvaluationSetItemsConfig(BaseModel):
    operation: Literal["create_evaluation_set_items"] = _op("create_evaluation_set_items", "Create Evaluation Set Items", "Evaluation")
    evaluation_set_id: str = _evaluation_set_id_field()
    items: str = _json_field("Items", "JSON array of items to add", required=True)


class ExtendListEvaluationSetItemsConfig(BaseModel):
    operation: Literal["list_evaluation_set_items"] = _op("list_evaluation_set_items", "List Evaluation Set Items", "Evaluation")
    evaluation_set_id: str = _evaluation_set_id_field()
    sort_by: Optional[str] = Field(None, title="Sort By")
    sort_dir: Optional[str] = _sort_dir()
    max_page_size: Optional[str] = _page_size()
    next_page_token: Optional[str] = _page_token()


class ExtendGetEvaluationSetItemConfig(BaseModel):
    operation: Literal["get_evaluation_set_item"] = _op("get_evaluation_set_item", "Get Evaluation Set Item", "Evaluation")
    evaluation_set_id: str = _evaluation_set_id_field()
    item_id: str = _item_id_field()


class ExtendUpdateEvaluationSetItemConfig(BaseModel):
    operation: Literal["update_evaluation_set_item"] = _op("update_evaluation_set_item", "Update Evaluation Set Item", "Evaluation")
    evaluation_set_id: str = _evaluation_set_id_field()
    item_id: str = _item_id_field()
    expected_output: str = _json_field("Expected Output", "The corrected expected output JSON", required=True)


class ExtendDeleteEvaluationSetItemConfig(BaseModel):
    operation: Literal["delete_evaluation_set_item"] = _op("delete_evaluation_set_item", "Delete Evaluation Set Item", "Evaluation")
    evaluation_set_id: str = _evaluation_set_id_field()
    item_id: str = _item_id_field()


class ExtendCreateEvaluationSetRunConfig(BaseModel):
    operation: Literal["create_evaluation_set_run"] = _op("create_evaluation_set_run", "Create Evaluation Set Run", "Evaluation")
    evaluation_set_id: str = _evaluation_set_id_field()
    entity: Optional[str] = _json_field("Entity", "Entity (processor/workflow version) to evaluate")
    evaluation_set_item_ids: Optional[str] = _json_field("Item IDs", "JSON array of specific item ids to run")


class ExtendGetEvaluationSetRunConfig(BaseModel):
    operation: Literal["get_evaluation_set_run"] = _op("get_evaluation_set_run", "Get Evaluation Set Run", "Evaluation")
    run_id: str = _plain_text_field("Evaluation Set Run ID", "The ID of the evaluation set run.", required=True)


# ============================================================================
# Batch run status
# ============================================================================


class ExtendGetBatchRunConfig(BaseModel):
    operation: Literal["get_batch_run"] = _op("get_batch_run", "Get Batch Run", "Batch")
    batch_id: str = _plain_text_field("Batch Run ID", "The ID of the batch run.", required=True)


class ExtendGetBatchProcessorRunConfig(BaseModel):
    operation: Literal["get_batch_processor_run"] = _op("get_batch_processor_run", "Get Batch Processor Run", "Batch")
    batch_id: str = _plain_text_field("Batch Processor Run ID", "The ID of the batch processor run.", required=True)


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class ExtendRunCompletedTriggerConfig(BaseModel):
    """Fire when an Extend document-processing run (parse/extract/classify/split/edit or batch) completes or fails.

    (Workflow-run events are not deliverable to a global webhook endpoint by the
    Extend API; use a webhook subscription for those.)"""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_run_completed"] = Field(
        "on_run_completed",
        json_schema_extra={
            "const": "on_run_completed", "ui:hidden": True, "x-category": None,
            "x-is-trigger": True, "x-display-name": "On Run Completed",
        },
        title="On Run Completed",
    )
    webhook_url: Optional[str] = Field(
        default=None, title="Webhook URL",
        description="Extend posts run events here. Registered automatically when you connect credentials.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


ExtendConfig = Annotated[
    Union[
        # Files
        ExtendUploadFileConfig, ExtendGetFileConfig, ExtendListFilesConfig, ExtendDeleteFileConfig,
        # Sync
        ExtendParseSyncConfig, ExtendExtractSyncConfig, ExtendClassifySyncConfig, ExtendSplitSyncConfig, ExtendEditSyncConfig,
        # Parse runs
        ExtendCreateParseRunConfig, ExtendGetParseRunConfig, ExtendListParseRunsConfig,
        ExtendCancelParseRunConfig, ExtendDeleteParseRunConfig, ExtendBatchParseRunsConfig,
        # Extract runs
        ExtendCreateExtractRunConfig, ExtendGetExtractRunConfig, ExtendListExtractRunsConfig,
        ExtendCancelExtractRunConfig, ExtendDeleteExtractRunConfig, ExtendBatchExtractRunsConfig,
        # Extractors
        ExtendCreateExtractorConfig, ExtendGetExtractorConfig, ExtendUpdateExtractorConfig, ExtendListExtractorsConfig,
        ExtendCreateExtractorVersionConfig, ExtendListExtractorVersionsConfig, ExtendGetExtractorVersionConfig,
        # Classify runs
        ExtendCreateClassifyRunConfig, ExtendGetClassifyRunConfig, ExtendListClassifyRunsConfig,
        ExtendCancelClassifyRunConfig, ExtendDeleteClassifyRunConfig, ExtendBatchClassifyRunsConfig,
        # Classifiers
        ExtendCreateClassifierConfig, ExtendGetClassifierConfig, ExtendUpdateClassifierConfig, ExtendListClassifiersConfig,
        ExtendCreateClassifierVersionConfig, ExtendListClassifierVersionsConfig, ExtendGetClassifierVersionConfig,
        # Split runs
        ExtendCreateSplitRunConfig, ExtendGetSplitRunConfig, ExtendListSplitRunsConfig,
        ExtendCancelSplitRunConfig, ExtendDeleteSplitRunConfig, ExtendBatchSplitRunsConfig,
        # Splitters
        ExtendCreateSplitterConfig, ExtendGetSplitterConfig, ExtendUpdateSplitterConfig, ExtendListSplittersConfig,
        ExtendCreateSplitterVersionConfig, ExtendListSplitterVersionsConfig, ExtendGetSplitterVersionConfig,
        # Edit
        ExtendCreateEditRunConfig, ExtendGetEditRunConfig, ExtendDeleteEditRunConfig,
        ExtendGenerateEditSchemaConfig, ExtendGetEditTemplateConfig,
        # Workflows
        ExtendCreateWorkflowConfig, ExtendGetWorkflowConfig, ExtendUpdateWorkflowConfig, ExtendListWorkflowsConfig,
        ExtendCreateWorkflowVersionConfig, ExtendListWorkflowVersionsConfig, ExtendGetWorkflowVersionConfig,
        # Workflow runs
        ExtendCreateWorkflowRunConfig, ExtendGetWorkflowRunConfig, ExtendListWorkflowRunsConfig,
        ExtendUpdateWorkflowRunConfig, ExtendCancelWorkflowRunConfig, ExtendDeleteWorkflowRunConfig,
        ExtendBatchWorkflowRunsConfig,
        # Webhook endpoints
        ExtendCreateWebhookEndpointConfig, ExtendListWebhookEndpointsConfig, ExtendGetWebhookEndpointConfig,
        ExtendUpdateWebhookEndpointConfig, ExtendDeleteWebhookEndpointConfig,
        # Webhook subscriptions
        ExtendCreateWebhookSubscriptionConfig, ExtendListWebhookSubscriptionsConfig, ExtendGetWebhookSubscriptionConfig,
        ExtendUpdateWebhookSubscriptionConfig, ExtendDeleteWebhookSubscriptionConfig,
        # Evaluation
        ExtendCreateEvaluationSetConfig, ExtendListEvaluationSetsConfig, ExtendGetEvaluationSetConfig,
        ExtendCreateEvaluationSetItemsConfig, ExtendListEvaluationSetItemsConfig, ExtendGetEvaluationSetItemConfig,
        ExtendUpdateEvaluationSetItemConfig, ExtendDeleteEvaluationSetItemConfig,
        ExtendCreateEvaluationSetRunConfig, ExtendGetEvaluationSetRunConfig,
        # Batch status
        ExtendGetBatchRunConfig, ExtendGetBatchProcessorRunConfig,
        # Trigger
        ExtendRunCompletedTriggerConfig,
    ],
    Discriminator("operation"),
]


class ExtendNodeConfig(NodeConfig[ExtendConfig, ExtendCredential]):
    """Full configuration for the Extend node including credentials."""

    pass


# ============================================================================
# HTTP Request Helper
# ============================================================================


async def _extend_request(
    api_key: str,
    method: str,
    endpoint: str,
    workspace_id: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Extend request and return a structured result."""
    url = f"{EXTEND_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "x-extend-api-version": EXTEND_API_VERSION,
    }
    if workspace_id:
        headers["X-Extend-Workspace-Id"] = workspace_id
    if json_body:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            return _shape_response(response, action_name, start)
        except httpx.TimeoutException:
            return _err_result(action_name, "Request timed out", 408, start)
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[ExtendNode] Request failed ({action_name}): {msg}")
            return _err_result(action_name, msg, 500, start)


def _shape_response(response: httpx.Response, action_name: str, start: float) -> Dict[str, Any]:
    api_ms = round((time.time() - start) * 1000, 2)
    if response.status_code >= 400:
        try:
            err = response.json()
            # Extend returns {code, message, requestId} at the top level; older /
            # nested shapes use {error: {message}}. Handle both, with the request
            # id appended when present for debuggability.
            if isinstance(err, dict):
                nested = err.get("error")
                if isinstance(nested, dict):
                    message = nested.get("message") or str(nested)
                else:
                    message = err.get("message") or nested or str(err)
                req_id = err.get("requestId")
                if req_id and isinstance(message, str):
                    message = f"{message} (requestId: {req_id})"
            else:
                message = str(err)
        except Exception:
            message = response.text
        if isinstance(message, str):
            message = message.encode("ascii", errors="replace").decode("ascii")
        logger.error(f"[ExtendNode] API error ({action_name}): {message}")
        return {"status": "error", "action": action_name, "error": message,
                "status_code": response.status_code, "timing_ms": {"api_request": api_ms}}
    if response.status_code == 204:
        data: Any = {"success": True}
    else:
        try:
            payload = response.json()
            data = payload.get("data", payload) if isinstance(payload, dict) else payload
        except Exception:
            data = {"raw": response.text}
    return {"status": "success", "action": action_name, "data": data,
            "status_code": response.status_code, "timing_ms": {"api_request": api_ms}}


def _err_result(action_name: str, message: str, code: int, start: float) -> Dict[str, Any]:
    return {"status": "error", "action": action_name, "error": message,
            "status_code": code, "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)}}


# ============================================================================
# Node Implementation
# ============================================================================


class ExtendNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Extend document AI automation node."""

    edit_examples = [
        "Parse an uploaded PDF into clean markdown",
        "Extract structured fields from an invoice using an extractor",
        "Classify a document into one of my configured types",
        "Split a multi-document PDF into logical sub-documents",
        "Run a multi-step Extend workflow on a file",
        "Trigger a workflow whenever an Extend run completes",
    ]

    @classmethod
    def get_config_model(cls):
        return ExtendNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (extractors / classifiers / splitters / workflows)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        endpoint_map = {
            "extractor_id": "/extractors",
            "classifier_id": "/classifiers",
            "splitter_id": "/splitters",
            "workflow_id": "/workflows",
        }
        endpoint = endpoint_map.get(field_name)
        if not endpoint:
            return {"options": [], "next_page_token": None}

        api_key = (credential_data or {}).get("api_key")
        if not api_key:
            return {"options": [], "next_page_token": None}

        workspace_id = credential_data.get("workspace_id")
        params: Dict[str, str] = {"maxPageSize": "100"}
        if page_token:
            params["pageToken"] = page_token

        result = await _extend_request(
            api_key,
            "GET",
            endpoint,
            workspace_id=workspace_id,
            params=params,
            action_name=f"list_{field_name}",
        )
        if result.get("status") != "success":
            return {"options": [], "next_page_token": None}
        data = result.get("data") or []
        if isinstance(data, list):
            items = data
            next_page = None
        else:
            items = data.get("items") or []
            next_page = data.get("nextPageToken")

        search_lower = (search or "").strip().lower()
        options = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            name = item.get("name") or item.get("title") or item_id
            if item_id is not None:
                option = {"label": str(name), "value": str(item_id)}
                if search_lower and (
                    search_lower not in option["label"].lower()
                    and search_lower not in option["value"].lower()
                ):
                    continue
                options.append(option)
        return {"options": options, "next_page_token": str(next_page) if next_page else None}

    # ------------------------------------------------------------------
    # Webhook trigger registration
    # ------------------------------------------------------------------
    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        api_key = credential.get("api_key")
        if not api_key:
            raise ValueError("An Extend API key is required to register the trigger")
        workspace_id = credential.get("workspace_id")
        # Drop a stale endpoint from a prior registration first (not idempotent).
        existing = (config or {}).get("external_webhook_id")
        if existing:
            try:
                await _extend_request(api_key, "DELETE", f"/webhook_endpoints/{existing}",
                                      workspace_id=workspace_id, action_name="unregister_webhook")
            except Exception as e:
                logger.warning(f"[ExtendNode] Could not remove stale webhook endpoint: {e}")
        result = await _extend_request(
            api_key, "POST", "/webhook_endpoints", workspace_id=workspace_id,
            json_body={
                "url": webhook_url,
                "name": f"noclick-trigger-{node_id}",
                "apiVersion": EXTEND_API_VERSION,
                "enabledEvents": RUN_COMPLETED_EVENTS,
            },
            action_name="register_webhook",
        )
        if result.get("status") != "success":
            raise ValueError(f"Extend webhook registration failed: {result.get('error')}")
        data = result.get("data") or {}
        external_id = data.get("id") if isinstance(data, dict) else None
        signing_secret = (data.get("signingSecret") or data.get("secret")) if isinstance(data, dict) else None
        return {
            "external_webhook_id": str(external_id) if external_id else None,
            "signing_secret": signing_secret,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        api_key = (credential or {}).get("api_key")
        if not external_id or not api_key:
            return
        await _extend_request(api_key, "DELETE", f"/webhook_endpoints/{external_id}",
                              workspace_id=(credential or {}).get("workspace_id"),
                              action_name="unregister_webhook")

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]) -> bool:
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no secret stored -> accept (trigger not yet armed)
        # Extend signs with HMAC-SHA256 over "v0:{timestamp}:{body}".
        ts = headers.get("x-extend-request-timestamp")
        sig = headers.get("x-extend-request-signature")
        if not ts or not sig:
            return False
        signed = f"v0:{ts}:".encode() + body
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, ExtendNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, ExtendRunCompletedTriggerConfig):
            return {
                "status": "success", "action": "on_run_completed",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Extend API key.")
        api_key = credentials.api_key
        ws = credentials.workspace_id

        handler = self._HANDLERS.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(self, op, api_key, ws)
        result["timing_ms"] = {**result.get("timing_ms", {}),
                               "total": round((time.time() - start_time) * 1000, 2)}
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _q(c) -> Dict[str, Any]:
        """Build query params from whatever filter/pagination attrs a config has."""
        mapping = {
            "max_page_size": "maxPageSize", "next_page_token": "nextPageToken",
            "sort_dir": "sortDir", "sort_by": "sortBy", "status": "status",
            "file_name_contains": "fileNameContains", "name_contains": "nameContains",
            "batch_id": "batchId", "source": "source", "source_id": "sourceId",
            "extractor_id": "extractorId", "classifier_id": "classifierId",
            "splitter_id": "splitterId", "workflow_id": "workflowId",
            "entity_id": "entityId", "webhook_endpoint_id": "webhookEndpointId",
            "resource_id": "resourceId", "response_type": "responseType",
        }
        out: Dict[str, Any] = {}
        for attr, key in mapping.items():
            v = getattr(c, attr, None)
            if v not in (None, ""):
                out[key] = v
        return out

    @staticmethod
    def _jl(value: Optional[str]) -> Any:
        """Parse a JSON string field; None/empty -> None."""
        if value is None or value == "":
            return None
        return json.loads(value)

    @staticmethod
    def _file_ref(c) -> Optional[Dict[str, Any]]:
        fid = getattr(c, "file_id", None)
        if fid:
            return {"id": fid}
        furl = getattr(c, "file_url", None)
        if furl:
            return {"url": furl}
        return None

    @staticmethod
    def _bool(value: Optional[str]) -> Optional[bool]:
        if value is None or value == "":
            return None
        return value == "true"

    async def _req(self, api_key, ws, method, endpoint, *, params=None, body=None, action):
        return await _extend_request(api_key, method, endpoint, workspace_id=ws,
                                     params=params, json_body=body, action_name=action)

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------
    async def _upload_file(self, c, api_key, ws):
        start = time.time()
        url = f"{EXTEND_API_BASE}/files/upload"
        headers = {"Authorization": f"Bearer {api_key}", "x-extend-api-version": EXTEND_API_VERSION}
        if ws:
            headers["X-Extend-Workspace-Id"] = ws
        params = {}
        if self._bool(c.convert_to_pdf):
            params["convertToPdf"] = "true"
        data = {}
        if c.password:
            data["password"] = c.password
        async with guarded_async_client(timeout=300.0) as client:
            try:
                dl = await client.get(c.file_url, follow_redirects=True, timeout=120.0)
                dl.raise_for_status()
                filename = c.file_name or c.file_url.rstrip("/").split("/")[-1] or "upload"
                response = await client.post(
                    url, headers=headers, params=params or None, data=data or None,
                    files={"file": (filename, dl.content, "application/octet-stream")},
                )
                return _shape_response(response, "upload_file", start)
            except httpx.HTTPStatusError as e:
                return _err_result("upload_file", f"Failed to download source file: {e}", 400, start)
            except httpx.TimeoutException:
                return _err_result("upload_file", "Request timed out", 408, start)
            except Exception as e:
                msg = str(e).encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[ExtendNode] upload_file failed: {msg}")
                return _err_result("upload_file", msg, 500, start)

    async def _get_file(self, c, api_key, ws):
        params = {}
        if self._bool(c.raw_text):
            params["rawText"] = "true"
        if self._bool(c.markdown):
            params["markdown"] = "true"
        if self._bool(c.html):
            params["html"] = "true"
        return await self._req(api_key, ws, "GET", f"/files/{c.file_id}", params=params, action="get_file")

    async def _list_files(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", "/files", params=self._q(c), action="list_files")

    async def _delete_file(self, c, api_key, ws):
        return await self._req(api_key, ws, "DELETE", f"/files/{c.file_id}", action="delete_file")

    # ------------------------------------------------------------------
    # Sync one-shots
    # ------------------------------------------------------------------
    async def _parse(self, c, api_key, ws):
        body = {"file": self._file_ref(c), "config": self._jl(c.config), "metadata": self._jl(c.metadata)}
        return await self._req(api_key, ws, "POST", "/parse", params=self._q(c), body=body, action="parse")

    async def _extract(self, c, api_key, ws):
        body = {"file": self._file_ref(c), "config": self._jl(c.config), "metadata": self._jl(c.metadata)}
        if c.extractor_id:
            body["extractor"] = {"id": c.extractor_id}
        return await self._req(api_key, ws, "POST", "/extract", body=body, action="extract")

    async def _classify(self, c, api_key, ws):
        body = {"file": {"id": c.file_id}, "config": self._jl(c.config), "metadata": self._jl(c.metadata)}
        if c.classifier_id:
            body["classifier"] = {"id": c.classifier_id}
        return await self._req(api_key, ws, "POST", "/classify", body=body, action="classify")

    async def _split(self, c, api_key, ws):
        body = {"file": {"id": c.file_id}, "config": self._jl(c.config), "metadata": self._jl(c.metadata)}
        if c.splitter_id:
            body["splitter"] = {"id": c.splitter_id}
        return await self._req(api_key, ws, "POST", "/split", body=body, action="split")

    async def _edit(self, c, api_key, ws):
        body = {"file": {"id": c.file_id}, "config": self._jl(c.config)}
        return await self._req(api_key, ws, "POST", "/edit", body=body, action="edit")

    # ------------------------------------------------------------------
    # Run helpers (generic create/get/list/cancel/delete/batch)
    # ------------------------------------------------------------------
    async def _create_run(self, c, api_key, ws, resource, action, *, processor_field=None, processor_key=None,
                          file_required_id=False, extra_keys=()):
        file_ref = {"id": c.file_id} if file_required_id else self._file_ref(c)
        body: Dict[str, Any] = {"file": file_ref}
        if processor_field and getattr(c, processor_field, None):
            body[processor_key] = {"id": getattr(c, processor_field)}
        for k in ("config", "metadata", "outputs", "secrets"):
            if hasattr(c, k):
                body[k] = self._jl(getattr(c, k))
        if getattr(c, "priority", None):
            body["priority"] = c.priority
        return await self._req(api_key, ws, "POST", f"/{resource}", body=body, action=action)

    async def _batch_runs(self, c, api_key, ws, resource, action, processor_key=None, processor_field=None):
        body: Dict[str, Any] = {"inputs": self._jl(c.inputs)}
        if processor_key and getattr(c, processor_field, None):
            body[processor_key] = {"id": getattr(c, processor_field)}
        if getattr(c, "config", None) is not None:
            body["config"] = self._jl(c.config)
        if getattr(c, "priority", None):
            body["priority"] = c.priority
        return await self._req(api_key, ws, "POST", f"/{resource}/batch", body=body, action=action)

    # Parse runs
    async def _create_parse_run(self, c, api_key, ws):
        body = {"file": self._file_ref(c), "config": self._jl(c.config), "metadata": self._jl(c.metadata)}
        return await self._req(api_key, ws, "POST", "/parse_runs", body=body, action="create_parse_run")

    async def _get_parse_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/parse_runs/{c.run_id}", params=self._q(c), action="get_parse_run")

    async def _list_parse_runs(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", "/parse_runs", params=self._q(c), action="list_parse_runs")

    async def _cancel_parse_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "POST", f"/parse_runs/{c.run_id}/cancel", action="cancel_parse_run")

    async def _delete_parse_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "DELETE", f"/parse_runs/{c.run_id}", action="delete_parse_run")

    async def _batch_parse_runs(self, c, api_key, ws):
        return await self._batch_runs(c, api_key, ws, "parse_runs", "batch_parse_runs")

    # Extract runs
    async def _create_extract_run(self, c, api_key, ws):
        return await self._create_run(c, api_key, ws, "extract_runs", "create_extract_run",
                                      processor_field="extractor_id", processor_key="extractor")

    async def _get_extract_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/extract_runs/{c.run_id}", action="get_extract_run")

    async def _list_extract_runs(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", "/extract_runs", params=self._q(c), action="list_extract_runs")

    async def _cancel_extract_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "POST", f"/extract_runs/{c.run_id}/cancel", action="cancel_extract_run")

    async def _delete_extract_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "DELETE", f"/extract_runs/{c.run_id}", action="delete_extract_run")

    async def _batch_extract_runs(self, c, api_key, ws):
        return await self._batch_runs(c, api_key, ws, "extract_runs", "batch_extract_runs",
                                      processor_key="extractor", processor_field="extractor_id")

    # Classify runs
    async def _create_classify_run(self, c, api_key, ws):
        return await self._create_run(c, api_key, ws, "classify_runs", "create_classify_run",
                                      processor_field="classifier_id", processor_key="classifier",
                                      file_required_id=True)

    async def _get_classify_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/classify_runs/{c.run_id}", action="get_classify_run")

    async def _list_classify_runs(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", "/classify_runs", params=self._q(c), action="list_classify_runs")

    async def _cancel_classify_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "POST", f"/classify_runs/{c.run_id}/cancel", action="cancel_classify_run")

    async def _delete_classify_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "DELETE", f"/classify_runs/{c.run_id}", action="delete_classify_run")

    async def _batch_classify_runs(self, c, api_key, ws):
        return await self._batch_runs(c, api_key, ws, "classify_runs", "batch_classify_runs",
                                      processor_key="classifier", processor_field="classifier_id")

    # Split runs
    async def _create_split_run(self, c, api_key, ws):
        return await self._create_run(c, api_key, ws, "split_runs", "create_split_run",
                                      processor_field="splitter_id", processor_key="splitter",
                                      file_required_id=True)

    async def _get_split_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/split_runs/{c.run_id}", action="get_split_run")

    async def _list_split_runs(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", "/split_runs", params=self._q(c), action="list_split_runs")

    async def _cancel_split_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "POST", f"/split_runs/{c.run_id}/cancel", action="cancel_split_run")

    async def _delete_split_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "DELETE", f"/split_runs/{c.run_id}", action="delete_split_run")

    async def _batch_split_runs(self, c, api_key, ws):
        return await self._batch_runs(c, api_key, ws, "split_runs", "batch_split_runs",
                                      processor_key="splitter", processor_field="splitter_id")

    # ------------------------------------------------------------------
    # Processor CRUD helpers (extractors / classifiers / splitters)
    # ------------------------------------------------------------------
    async def _create_processor(self, c, api_key, ws, resource, action, clone_field):
        body = {"name": c.name, "config": self._jl(getattr(c, "config", None))}
        if getattr(c, clone_field, None):
            body[_camel(clone_field)] = getattr(c, clone_field)
        if getattr(c, "generate", None) is not None:
            body["generate"] = self._jl(c.generate)
        return await self._req(api_key, ws, "POST", f"/{resource}", body=body, action=action)

    async def _update_processor(self, c, api_key, ws, resource, pid, action):
        body = {"name": getattr(c, "name", None), "config": self._jl(getattr(c, "config", None))}
        return await self._req(api_key, ws, "POST", f"/{resource}/{pid}", body=body, action=action)

    async def _create_processor_version(self, c, api_key, ws, resource, pid, action):
        body = {"releaseType": c.release_type, "description": getattr(c, "description", None),
                "config": self._jl(getattr(c, "config", None))}
        return await self._req(api_key, ws, "POST", f"/{resource}/{pid}/versions", body=body, action=action)

    # Extractors
    async def _create_extractor(self, c, api_key, ws):
        return await self._create_processor(c, api_key, ws, "extractors", "create_extractor", "clone_extractor_id")

    async def _get_extractor(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/extractors/{c.extractor_id}", action="get_extractor")

    async def _update_extractor(self, c, api_key, ws):
        return await self._update_processor(c, api_key, ws, "extractors", c.extractor_id, "update_extractor")

    async def _list_extractors(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", "/extractors", params=self._q(c), action="list_extractors")

    async def _create_extractor_version(self, c, api_key, ws):
        return await self._create_processor_version(c, api_key, ws, "extractors", c.extractor_id, "create_extractor_version")

    async def _list_extractor_versions(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/extractors/{c.extractor_id}/versions", params=self._q(c), action="list_extractor_versions")

    async def _get_extractor_version(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/extractors/{c.extractor_id}/versions/{c.version_id}", action="get_extractor_version")

    # Classifiers
    async def _create_classifier(self, c, api_key, ws):
        return await self._create_processor(c, api_key, ws, "classifiers", "create_classifier", "clone_classifier_id")

    async def _get_classifier(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/classifiers/{c.classifier_id}", action="get_classifier")

    async def _update_classifier(self, c, api_key, ws):
        return await self._update_processor(c, api_key, ws, "classifiers", c.classifier_id, "update_classifier")

    async def _list_classifiers(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", "/classifiers", params=self._q(c), action="list_classifiers")

    async def _create_classifier_version(self, c, api_key, ws):
        return await self._create_processor_version(c, api_key, ws, "classifiers", c.classifier_id, "create_classifier_version")

    async def _list_classifier_versions(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/classifiers/{c.classifier_id}/versions", params=self._q(c), action="list_classifier_versions")

    async def _get_classifier_version(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/classifiers/{c.classifier_id}/versions/{c.version_id}", action="get_classifier_version")

    # Splitters
    async def _create_splitter(self, c, api_key, ws):
        return await self._create_processor(c, api_key, ws, "splitters", "create_splitter", "clone_splitter_id")

    async def _get_splitter(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/splitters/{c.splitter_id}", action="get_splitter")

    async def _update_splitter(self, c, api_key, ws):
        return await self._update_processor(c, api_key, ws, "splitters", c.splitter_id, "update_splitter")

    async def _list_splitters(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", "/splitters", params=self._q(c), action="list_splitters")

    async def _create_splitter_version(self, c, api_key, ws):
        return await self._create_processor_version(c, api_key, ws, "splitters", c.splitter_id, "create_splitter_version")

    async def _list_splitter_versions(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/splitters/{c.splitter_id}/versions", params=self._q(c), action="list_splitter_versions")

    async def _get_splitter_version(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/splitters/{c.splitter_id}/versions/{c.version_id}", action="get_splitter_version")

    # ------------------------------------------------------------------
    # Edit runs / schemas / templates
    # ------------------------------------------------------------------
    async def _create_edit_run(self, c, api_key, ws):
        body = {"file": self._file_ref(c), "config": self._jl(c.config)}
        return await self._req(api_key, ws, "POST", "/edit_runs", body=body, action="create_edit_run")

    async def _get_edit_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/edit_runs/{c.run_id}", action="get_edit_run")

    async def _delete_edit_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "DELETE", f"/edit_runs/{c.run_id}", action="delete_edit_run")

    async def _generate_edit_schema(self, c, api_key, ws):
        body = {"file": self._file_ref(c), "config": self._jl(c.config)}
        return await self._req(api_key, ws, "POST", "/edit_schemas/generate", body=body, action="generate_edit_schema")

    async def _get_edit_template(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/edit_templates/{c.template_id}", action="get_edit_template")

    # ------------------------------------------------------------------
    # Workflows (+ versions)
    # ------------------------------------------------------------------
    async def _create_workflow(self, c, api_key, ws):
        body = {"name": c.name, "steps": self._jl(c.steps)}
        return await self._req(api_key, ws, "POST", "/workflows", body=body, action="create_workflow")

    async def _get_workflow(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/workflows/{c.workflow_id}", action="get_workflow")

    async def _update_workflow(self, c, api_key, ws):
        body = {"name": c.name, "steps": self._jl(c.steps)}
        return await self._req(api_key, ws, "POST", f"/workflows/{c.workflow_id}", body=body, action="update_workflow")

    async def _list_workflows(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", "/workflows", params=self._q(c), action="list_workflows")

    async def _create_workflow_version(self, c, api_key, ws):
        body = {"name": c.name, "steps": self._jl(c.steps)}
        return await self._req(api_key, ws, "POST", f"/workflows/{c.workflow_id}/versions", body=body, action="create_workflow_version")

    async def _list_workflow_versions(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/workflows/{c.workflow_id}/versions", params=self._q(c), action="list_workflow_versions")

    async def _get_workflow_version(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/workflows/{c.workflow_id}/versions/{c.version_id}", action="get_workflow_version")

    # ------------------------------------------------------------------
    # Workflow runs
    # ------------------------------------------------------------------
    async def _create_workflow_run(self, c, api_key, ws):
        workflow = {"id": c.workflow_id}
        if c.version:
            workflow["version"] = c.version
        body = {"workflow": workflow, "file": self._file_ref(c),
                "outputs": self._jl(c.outputs), "metadata": self._jl(c.metadata),
                "secrets": self._jl(c.secrets)}
        if c.priority:
            body["priority"] = c.priority
        return await self._req(api_key, ws, "POST", "/workflow_runs", body=body, action="create_workflow_run")

    async def _get_workflow_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/workflow_runs/{c.run_id}", action="get_workflow_run")

    async def _list_workflow_runs(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", "/workflow_runs", params=self._q(c), action="list_workflow_runs")

    async def _update_workflow_run(self, c, api_key, ws):
        body = {"name": c.name, "metadata": self._jl(c.metadata)}
        return await self._req(api_key, ws, "POST", f"/workflow_runs/{c.run_id}", body=body, action="update_workflow_run")

    async def _cancel_workflow_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "POST", f"/workflow_runs/{c.run_id}/cancel", action="cancel_workflow_run")

    async def _delete_workflow_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "DELETE", f"/workflow_runs/{c.run_id}", action="delete_workflow_run")

    async def _batch_workflow_runs(self, c, api_key, ws):
        return await self._batch_runs(c, api_key, ws, "workflow_runs", "batch_workflow_runs",
                                      processor_key="workflow", processor_field="workflow_id")

    # ------------------------------------------------------------------
    # Webhook endpoints
    # ------------------------------------------------------------------
    async def _create_webhook_endpoint(self, c, api_key, ws):
        body = {"url": c.url, "name": c.name, "apiVersion": EXTEND_API_VERSION,
                "enabledEvents": self._jl(c.enabled_events), "status": c.status,
                "advancedOptions": self._jl(c.advanced_options)}
        return await self._req(api_key, ws, "POST", "/webhook_endpoints", body=body, action="create_webhook_endpoint")

    async def _list_webhook_endpoints(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", "/webhook_endpoints", params=self._q(c), action="list_webhook_endpoints")

    async def _get_webhook_endpoint(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/webhook_endpoints/{c.endpoint_id}", action="get_webhook_endpoint")

    async def _update_webhook_endpoint(self, c, api_key, ws):
        body = {"url": c.url, "name": c.name, "status": c.status,
                "enabledEvents": self._jl(c.enabled_events), "advancedOptions": self._jl(c.advanced_options)}
        return await self._req(api_key, ws, "POST", f"/webhook_endpoints/{c.endpoint_id}", body=body, action="update_webhook_endpoint")

    async def _delete_webhook_endpoint(self, c, api_key, ws):
        return await self._req(api_key, ws, "DELETE", f"/webhook_endpoints/{c.endpoint_id}", action="delete_webhook_endpoint")

    # ------------------------------------------------------------------
    # Webhook subscriptions
    # ------------------------------------------------------------------
    async def _create_webhook_subscription(self, c, api_key, ws):
        body = {"webhookEndpointId": c.webhook_endpoint_id, "resourceType": c.resource_type,
                "resourceId": c.resource_id, "enabledEvents": self._jl(c.enabled_events)}
        return await self._req(api_key, ws, "POST", "/webhook_subscriptions", body=body, action="create_webhook_subscription")

    async def _list_webhook_subscriptions(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", "/webhook_subscriptions", params=self._q(c), action="list_webhook_subscriptions")

    async def _get_webhook_subscription(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/webhook_subscriptions/{c.subscription_id}", action="get_webhook_subscription")

    async def _update_webhook_subscription(self, c, api_key, ws):
        body = {"enabledEvents": self._jl(c.enabled_events)}
        return await self._req(api_key, ws, "POST", f"/webhook_subscriptions/{c.subscription_id}", body=body, action="update_webhook_subscription")

    async def _delete_webhook_subscription(self, c, api_key, ws):
        return await self._req(api_key, ws, "DELETE", f"/webhook_subscriptions/{c.subscription_id}", action="delete_webhook_subscription")

    # ------------------------------------------------------------------
    # Evaluation sets / items / runs
    # ------------------------------------------------------------------
    async def _create_evaluation_set(self, c, api_key, ws):
        body = {"name": c.name, "entityId": c.entity_id, "description": c.description}
        return await self._req(api_key, ws, "POST", "/evaluation_sets", body=body, action="create_evaluation_set")

    async def _list_evaluation_sets(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", "/evaluation_sets", params=self._q(c), action="list_evaluation_sets")

    async def _get_evaluation_set(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/evaluation_sets/{c.evaluation_set_id}", action="get_evaluation_set")

    async def _create_evaluation_set_items(self, c, api_key, ws):
        body = {"items": self._jl(c.items)}
        return await self._req(api_key, ws, "POST", f"/evaluation_sets/{c.evaluation_set_id}/items", body=body, action="create_evaluation_set_items")

    async def _list_evaluation_set_items(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/evaluation_sets/{c.evaluation_set_id}/items", params=self._q(c), action="list_evaluation_set_items")

    async def _get_evaluation_set_item(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/evaluation_sets/{c.evaluation_set_id}/items/{c.item_id}", action="get_evaluation_set_item")

    async def _update_evaluation_set_item(self, c, api_key, ws):
        body = {"expectedOutput": self._jl(c.expected_output)}
        return await self._req(api_key, ws, "POST", f"/evaluation_sets/{c.evaluation_set_id}/items/{c.item_id}", body=body, action="update_evaluation_set_item")

    async def _delete_evaluation_set_item(self, c, api_key, ws):
        return await self._req(api_key, ws, "DELETE", f"/evaluation_sets/{c.evaluation_set_id}/items/{c.item_id}", action="delete_evaluation_set_item")

    async def _create_evaluation_set_run(self, c, api_key, ws):
        body = {"evaluationSetId": c.evaluation_set_id, "entity": self._jl(c.entity),
                "evaluationSetItemIds": self._jl(c.evaluation_set_item_ids)}
        return await self._req(api_key, ws, "POST", "/evaluation_set_runs", body=body, action="create_evaluation_set_run")

    async def _get_evaluation_set_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/evaluation_set_runs/{c.run_id}", action="get_evaluation_set_run")

    # ------------------------------------------------------------------
    # Batch status
    # ------------------------------------------------------------------
    async def _get_batch_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/batch_runs/{c.batch_id}", action="get_batch_run")

    async def _get_batch_processor_run(self, c, api_key, ws):
        return await self._req(api_key, ws, "GET", f"/batch_processor_runs/{c.batch_id}", action="get_batch_processor_run")

    # Built lazily below the class definition.
    _HANDLERS: Dict[str, Any] = {}


def _camel(snake: str) -> str:
    parts = snake.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


# Wire operation -> handler method once (avoids a 90-line dict literal in execute).
ExtendNode._HANDLERS = {
    name[1:]: getattr(ExtendNode, name)
    for name in dir(ExtendNode)
    if name.startswith("_") and not name.startswith("__")
    and callable(getattr(ExtendNode, name))
    and name[1:] in {
        "upload_file", "get_file", "list_files", "delete_file",
        "parse", "extract", "classify", "split", "edit",
        "create_parse_run", "get_parse_run", "list_parse_runs", "cancel_parse_run", "delete_parse_run", "batch_parse_runs",
        "create_extract_run", "get_extract_run", "list_extract_runs", "cancel_extract_run", "delete_extract_run", "batch_extract_runs",
        "create_extractor", "get_extractor", "update_extractor", "list_extractors",
        "create_extractor_version", "list_extractor_versions", "get_extractor_version",
        "create_classify_run", "get_classify_run", "list_classify_runs", "cancel_classify_run", "delete_classify_run", "batch_classify_runs",
        "create_classifier", "get_classifier", "update_classifier", "list_classifiers",
        "create_classifier_version", "list_classifier_versions", "get_classifier_version",
        "create_split_run", "get_split_run", "list_split_runs", "cancel_split_run", "delete_split_run", "batch_split_runs",
        "create_splitter", "get_splitter", "update_splitter", "list_splitters",
        "create_splitter_version", "list_splitter_versions", "get_splitter_version",
        "create_edit_run", "get_edit_run", "delete_edit_run", "generate_edit_schema", "get_edit_template",
        "create_workflow", "get_workflow", "update_workflow", "list_workflows",
        "create_workflow_version", "list_workflow_versions", "get_workflow_version",
        "create_workflow_run", "get_workflow_run", "list_workflow_runs", "update_workflow_run",
        "cancel_workflow_run", "delete_workflow_run", "batch_workflow_runs",
        "create_webhook_endpoint", "list_webhook_endpoints", "get_webhook_endpoint", "update_webhook_endpoint", "delete_webhook_endpoint",
        "create_webhook_subscription", "list_webhook_subscriptions", "get_webhook_subscription", "update_webhook_subscription", "delete_webhook_subscription",
        "create_evaluation_set", "list_evaluation_sets", "get_evaluation_set",
        "create_evaluation_set_items", "list_evaluation_set_items", "get_evaluation_set_item",
        "update_evaluation_set_item", "delete_evaluation_set_item",
        "create_evaluation_set_run", "get_evaluation_set_run",
        "get_batch_run", "get_batch_processor_run",
    }
}
