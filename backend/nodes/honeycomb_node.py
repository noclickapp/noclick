"""Honeycomb observability automation node (REST v1 + v2 Management).

Single-file node (matches the repo convention). Integrates the Honeycomb REST API:
events, datasets/columns/derived-columns, boards, queries, markers, triggers (alerts),
SLOs + burn alerts, recipients, and the v2 Management API - plus a raw rest_request
passthrough and native webhook triggers. Auth is API-key only (no OAuth):
honeycomb_api_key (v1 X-Honeycomb-Team) and honeycomb_management_key (v2 Bearer);
a region (US/EU) selects the base URL.
"""

import hmac
import httpx
import json
import logging
import secrets
import time
from nodes.core.base import NodeConfig
from nodes.core.base import WorkflowNode
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from nodes.core.webhook_trigger import WebhookTriggerConfigBase
from pydantic import BaseModel, ConfigDict, Field
from pydantic import BaseModel, Discriminator, Field
from pydantic import BaseModel, Field
from pydantic import ConfigDict, Field
from pydantic import Field
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from typing import Any, Dict
from typing import Any, Dict, List, Literal, Optional
from typing import Any, Dict, Optional
from typing import Any, Optional
from typing import Literal
from typing import Literal, Optional
from typing import Literal, Optional, Union

logger = logging.getLogger(__name__)


# ==========================================================================
# from client.py
# ==========================================================================

_BASE_URLS = {
    "us": "https://api.honeycomb.io",
    "eu": "https://api.eu1.honeycomb.io",
}


def base_url(credential: Dict[str, Any]) -> str:
    region = (credential or {}).get("region") or "us"
    return _BASE_URLS.get(str(region).lower(), _BASE_URLS["us"])


def _v1_key(credential: Dict[str, Any]) -> Optional[str]:
    return (credential or {}).get("api_key")


def _v2_bearer(credential: Dict[str, Any]) -> Optional[str]:
    key_id = (credential or {}).get("key_id")
    secret = (credential or {}).get("secret")
    if key_id and secret:
        return f"{key_id}:{secret}"
    return None


def _drop_none(mapping: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not mapping:
        return {}
    return {k: v for k, v in mapping.items() if v is not None}


async def honeycomb_request(
    credential: Dict[str, Any],
    method: str,
    path: str,
    *,
    version: str = "1",
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    extra_headers: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Honeycomb REST request and return a structured result.

    ``version`` selects the auth scheme + content type. v1 needs an
    ``X-Honeycomb-Team`` API key; v2 needs a Management key (``key_id``/``secret``).
    A missing key of the required type returns a clean error rather than a 401.
    ``extra_headers`` forwards per-request headers (e.g. the events API's
    ``X-Honeycomb-Event-Time`` / ``X-Honeycomb-Samplerate``); ``None`` values are
    dropped.
    """
    headers: Dict[str, str] = {"Accept": "application/json"}
    if version == "2":
        bearer = _v2_bearer(credential)
        if not bearer:
            return {"status": "error", "action": action_name, "status_code": 401,
                    "error": "This operation needs a Honeycomb Management key (key id + secret)."}
        headers["Authorization"] = f"Bearer {bearer}"
        headers["Content-Type"] = "application/vnd.api+json"
        headers["Accept"] = "application/vnd.api+json"
    else:
        key = _v1_key(credential)
        if not key:
            return {"status": "error", "action": action_name, "status_code": 401,
                    "error": "This operation needs a Honeycomb API key (Configuration or Ingest key)."}
        headers["X-Honeycomb-Team"] = key
        headers["Content-Type"] = "application/json"

    for hk, hv in (extra_headers or {}).items():
        if hv is not None:
            headers[hk] = str(hv)

    url = base_url(credential) + path
    if isinstance(json_body, dict):
        json_body = _drop_none(json_body)
    params = _drop_none(params) if params else None

    start = time.time()
    async with httpx.AsyncClient(timeout=45.0) as client:
        try:
            response = await client.request(method=method, url=url, headers=headers, params=params, json=json_body)
            api_ms = round((time.time() - start) * 1000, 2)

            if response.status_code >= 400:
                message: Any = response.text
                details = None
                try:
                    err = response.json()
                    # v1 RFC7807 (title/detail) or v2 JSON:API (errors[].detail).
                    if isinstance(err, dict):
                        if err.get("errors"):
                            first = err["errors"][0] if err["errors"] else {}
                            message = first.get("detail") or first.get("title") or message
                        else:
                            message = err.get("detail") or err.get("title") or err.get("error") or message
                        details = err
                except Exception:
                    pass
                logger.error(f"[HoneycombNode] API error ({action_name}): {response.status_code} {message}")
                return {"status": "error", "action": action_name, "error": message,
                        "details": details, "status_code": response.status_code,
                        "timing_ms": {"api_request": api_ms}}

            if response.status_code == 204 or not response.content:
                data: Any = {"success": True}
            else:
                try:
                    data = response.json()
                except Exception:
                    data = {"raw": response.text}
            return {"status": "success", "action": action_name, "data": data,
                    "status_code": response.status_code, "timing_ms": {"api_request": api_ms}}
        except httpx.TimeoutException:
            return {"status": "error", "action": action_name, "error": "Request timed out", "status_code": 408,
                    "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)}}
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[HoneycombNode] Request failed ({action_name}): {msg}")
            return {"status": "error", "action": action_name, "error": msg, "status_code": 500,
                    "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)}}


# ==========================================================================
# from common.py
# ==========================================================================
# Operation categories surfaced in the config UI's operation picker (x-category).
CATEGORY_EVENTS = "Events"
CATEGORY_DATASETS = "Datasets & Columns"
CATEGORY_BOARDS = "Boards"
CATEGORY_QUERIES = "Queries"
CATEGORY_MARKERS = "Markers"
CATEGORY_TRIGGERS = "Triggers (Alerts)"
CATEGORY_SLOS = "SLOs & Burn Alerts"
CATEGORY_RECIPIENTS = "Recipients"
CATEGORY_MANAGEMENT = "Management (v2)"
CATEGORY_AUTH = "Auth"
CATEGORY_PASSTHROUGH = "Advanced"
CATEGORY_WEBHOOK_TRIGGERS = "Triggers"


def _op_field(op: str, category: str, display: str, keywords: Optional[Any] = None) -> Any:
    """Build the ``operation`` discriminator Field for an action operation."""
    extra: dict = {
        "const": op,
        "ui:hidden": True,
        "x-category": category,
        "x-is-trigger": False,
        "x-display-name": display,
    }
    if keywords:
        extra["x-keywords"] = keywords
    return Field(op, json_schema_extra=extra, title=display)


def _trigger_op(op: str, display: str, keywords: Optional[Any] = None) -> Any:
    """Build the ``operation`` discriminator Field for a webhook-trigger operation."""
    extra: dict = {
        "const": op,
        "ui:hidden": True,
        "x-category": CATEGORY_WEBHOOK_TRIGGERS,
        "x-is-trigger": True,
        "x-display-name": display,
    }
    if keywords:
        extra["x-keywords"] = keywords
    return Field(op, json_schema_extra=extra, title=display)


def _dataset_field(required: bool = True) -> Any:
    """A dataset-slug field (most v1 resources are dataset-scoped).

    Use ``__all__`` for environment-wide markers. Backed by a dynamic dropdown
    that lists the environment's datasets.
    """
    extra = {
        "x-dynamic-options": {
            "field_name": "dataset",
            "placeholder": "Select a dataset...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or type a dataset slug (__all__ for all)",
        }
    }
    if required:
        return Field(..., title="Dataset", description="Dataset slug (or __all__).", json_schema_extra=extra)
    return Field(None, title="Dataset", description="Dataset slug (or __all__).", json_schema_extra=extra)


def _body_json_field(title: str = "Body (JSON)", description: str = "Request body as a JSON object.") -> Any:
    """A JSON-object body field for endpoints with complex/nested payloads."""
    return Field(
        "{}", title=title, description=description,
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "ui:rows": 8},
    )


# ==========================================================================
# from credentials.py
# ==========================================================================
_REGION_FIELD = Field(
    "us", title="Region",
    description="Honeycomb region (US or EU) — selects the API base URL.",
    json_schema_extra={"enum": ["us", "eu"], "enumNames": ["US", "EU"], "x-enum-searchable": True},
)


class HoneycombApiKeyCredential(BaseModel):
    """v1 API key (X-Honeycomb-Team). Use a Configuration key for CRUD."""

    credential_type: Literal["honeycomb_api_key"] = Field(
        "honeycomb_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., title="API Key",
        description="Honeycomb Configuration or Ingest key (sent as X-Honeycomb-Team).",
        json_schema_extra={"ui:widget": "password"},
    )
    region: Literal["us", "eu"] = _REGION_FIELD

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://docs.honeycomb.io/configure/environments/manage-api-keys",
            "x-help-text": "Environment Settings → API Keys. A Configuration key is needed for resource CRUD.",
        }
    )


class HoneycombManagementKeyCredential(BaseModel):
    """v2 Management key (Authorization: Bearer <key_id>:<secret>)."""

    credential_type: Literal["honeycomb_management_key"] = Field(
        "honeycomb_management_key", json_schema_extra={"ui:hidden": True}
    )
    key_id: str = Field(
        ..., title="Management Key ID",
        description="Honeycomb Management key ID.",
    )
    secret: str = Field(
        ..., title="Management Key Secret",
        description="Honeycomb Management key secret (shown once at creation).",
        json_schema_extra={"ui:widget": "password"},
    )
    region: Literal["us", "eu"] = _REGION_FIELD

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://docs.honeycomb.io/configure/teams/manage-api-keys",
            "x-help-text": "Team Settings → Manage Team API Keys. Needed only for the v2 Management API.",
        }
    )


HoneycombCredential = Union[HoneycombApiKeyCredential, HoneycombManagementKeyCredential]


# ==========================================================================
# from events.py
# ==========================================================================
class HoneycombSendEventConfig(BaseModel):
    """Send a single event to a dataset (arbitrary fields as a JSON object)."""
    operation: Literal["send_event"] = _op_field(
        "send_event", CATEGORY_EVENTS, "Send Event",
        ["send event", "ingest", "create event", "post event"],
    )
    dataset: str = _dataset_field()
    body_json: str = _body_json_field(
        title="Event (JSON)",
        description="A single event as a JSON object of arbitrary fields (e.g. {\"method\": \"GET\", \"duration_ms\": 32}).",
    )
    event_time: Optional[str] = Field(
        None, title="Event Time",
        description="RFC3339 timestamp for the event (X-Honeycomb-Event-Time). Defaults to server time.",
    )
    samplerate: Optional[int] = Field(
        None, title="Sample Rate",
        description="Sample rate for the event (X-Honeycomb-Samplerate). Defaults to 1.",
    )


class HoneycombSendBatchEventsConfig(BaseModel):
    """Send a batch of events to a dataset (a JSON array of event wrappers)."""
    operation: Literal["send_batch_events"] = _op_field(
        "send_batch_events", CATEGORY_EVENTS, "Send Batch Events",
        ["batch events", "bulk ingest", "send events", "create events"],
    )
    dataset: str = _dataset_field()
    body_json: str = _body_json_field(
        title="Events (JSON array)",
        description=(
            "A JSON array of event wrappers, each {\"time\": <rfc3339>?, "
            "\"samplerate\": <int>?, \"data\": {<event fields>}}."
        ),
    )


class HoneycombSendKinesisEventsConfig(BaseModel):
    """Send events via an AWS Kinesis Firehose payload to a dataset."""
    operation: Literal["send_kinesis_events"] = _op_field(
        "send_kinesis_events", CATEGORY_EVENTS, "Send Kinesis Events",
        ["kinesis", "firehose", "stream events", "cloudwatch"],
    )
    dataset: str = _dataset_field()
    body_json: str = _body_json_field(
        title="Kinesis Firehose Payload (JSON)",
        description=(
            "AWS Kinesis Firehose payload as a JSON object with base64-encoded "
            "record data (e.g. {\"requestId\": ..., \"records\": [{\"data\": \"<base64>\"}]})."
        ),
    )
    firehose_request_id: str = Field(
        ..., title="Firehose Request Id",
        description="AWS Firehose request id (X-Amz-Firehose-Request-Id header).",
    )


async def op_send_event(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    extra_headers = {
        "X-Honeycomb-Event-Time": config.event_time,
        "X-Honeycomb-Samplerate": config.samplerate,
    }
    return await honeycomb_request(
        cred, "POST", f"/1/events/{config.dataset}", json_body=body,
        extra_headers=extra_headers, action_name="send_event",
    )


async def op_send_batch_events(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else []
    return await honeycomb_request(
        cred, "POST", f"/1/batch/{config.dataset}", json_body=body, action_name="send_batch_events",
    )


async def op_send_kinesis_events(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    # The Kinesis Firehose endpoint authenticates via X-Amz-Firehose-Access-Key
    # (NOT X-Honeycomb-Team), and carries the delivery id in X-Amz-Firehose-Request-Id.
    extra_headers = {
        "X-Amz-Firehose-Access-Key": (cred or {}).get("api_key"),
        "X-Amz-Firehose-Request-Id": config.firehose_request_id,
    }
    return await honeycomb_request(
        cred, "POST", f"/1/kinesis_events/{config.dataset}", json_body=body,
        extra_headers=extra_headers, action_name="send_kinesis_events",
    )


_OPS_events = [
    {"op": "send_event", "config": HoneycombSendEventConfig, "handler": op_send_event, "method": "POST", "version": "1", "category": CATEGORY_EVENTS, "verified": True},
    {"op": "send_batch_events", "config": HoneycombSendBatchEventsConfig, "handler": op_send_batch_events, "method": "POST", "version": "1", "category": CATEGORY_EVENTS, "verified": True},
    {"op": "send_kinesis_events", "config": HoneycombSendKinesisEventsConfig, "handler": op_send_kinesis_events, "method": "POST", "version": "1", "category": CATEGORY_EVENTS, "verified": True},
]


# ==========================================================================
# from datasets.py
# ==========================================================================
# --------------------------------------------------------------------------- #
# Datasets
# --------------------------------------------------------------------------- #
class HoneycombListDatasetsConfig(BaseModel):
    """List all datasets in the environment."""
    operation: Literal["list_datasets"] = _op_field(
        "list_datasets", CATEGORY_DATASETS, "List Datasets", ["datasets", "list datasets"]
    )


async def op_list_datasets(node, config, cred):
    return await honeycomb_request(cred, "GET", "/1/datasets", action_name="list_datasets")


class HoneycombCreateDatasetConfig(BaseModel):
    """Create a new dataset."""
    operation: Literal["create_dataset"] = _op_field(
        "create_dataset", CATEGORY_DATASETS, "Create Dataset", ["new dataset", "add dataset"]
    )
    name: str = Field(..., title="Name", description="Name of the new dataset.")
    description: Optional[str] = Field(None, title="Description", description="Description of the dataset.")
    expand_json_depth: Optional[int] = Field(
        None, title="Expand JSON Depth", description="Depth to which nested JSON fields are unpacked (0-10)."
    )


async def op_create_dataset(node, config, cred):
    body = {
        "name": config.name,
        "description": config.description,
        "expand_json_depth": config.expand_json_depth,
    }
    return await honeycomb_request(cred, "POST", "/1/datasets", json_body=body, action_name="create_dataset")


class HoneycombGetDatasetConfig(BaseModel):
    """Get a single dataset by slug."""
    operation: Literal["get_dataset"] = _op_field(
        "get_dataset", CATEGORY_DATASETS, "Get Dataset", ["dataset details", "fetch dataset"]
    )
    dataset: str = _dataset_field()


async def op_get_dataset(node, config, cred):
    return await honeycomb_request(cred, "GET", f"/1/datasets/{config.dataset}", action_name="get_dataset")


class HoneycombUpdateDatasetConfig(BaseModel):
    """Update a dataset's settings. Complex settings go in the JSON body."""
    operation: Literal["update_dataset"] = _op_field(
        "update_dataset", CATEGORY_DATASETS, "Update Dataset", ["edit dataset", "modify dataset"]
    )
    dataset: str = _dataset_field()
    body_json: str = _body_json_field(
        description='Update fields, e.g. {"description": "...", "expand_json_depth": 3, "settings": {"delete_protected": true}}.'
    )


async def op_update_dataset(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(
        cred, "PUT", f"/1/datasets/{config.dataset}", json_body=body, action_name="update_dataset"
    )


class HoneycombDeleteDatasetConfig(BaseModel):
    """Delete a dataset by slug (must not be delete-protected)."""
    operation: Literal["delete_dataset"] = _op_field(
        "delete_dataset", CATEGORY_DATASETS, "Delete Dataset", ["remove dataset", "drop dataset"]
    )
    dataset: str = _dataset_field()


async def op_delete_dataset(node, config, cred):
    return await honeycomb_request(cred, "DELETE", f"/1/datasets/{config.dataset}", action_name="delete_dataset")


# --------------------------------------------------------------------------- #
# Dataset Definitions
# --------------------------------------------------------------------------- #
class HoneycombGetDatasetDefinitionsConfig(BaseModel):
    """Get the definition mappings (trace id, span name, etc.) for a dataset."""
    operation: Literal["get_dataset_definitions"] = _op_field(
        "get_dataset_definitions", CATEGORY_DATASETS, "Get Dataset Definitions",
        ["definitions", "dataset definitions", "trace fields"]
    )
    dataset: str = _dataset_field()


async def op_get_dataset_definitions(node, config, cred):
    return await honeycomb_request(
        cred, "GET", f"/1/dataset_definitions/{config.dataset}", action_name="get_dataset_definitions"
    )


class HoneycombUpdateDatasetDefinitionsConfig(BaseModel):
    """Update dataset definition mappings. Body maps definition types to {name}."""
    operation: Literal["update_dataset_definitions"] = _op_field(
        "update_dataset_definitions", CATEGORY_DATASETS, "Update Dataset Definitions",
        ["set definitions", "map trace fields"]
    )
    dataset: str = _dataset_field()
    body_json: str = _body_json_field(
        description='Definition map, e.g. {"duration_ms": {"name": "duration_ms"}, "error": {"name": ""}}.'
    )


async def op_update_dataset_definitions(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(
        cred, "PATCH", f"/1/dataset_definitions/{config.dataset}", json_body=body,
        action_name="update_dataset_definitions",
    )


# --------------------------------------------------------------------------- #
# Columns
# --------------------------------------------------------------------------- #
class HoneycombListColumnsConfig(BaseModel):
    """List all columns in a dataset (or across all datasets with __all__)."""
    operation: Literal["list_columns"] = _op_field(
        "list_columns", CATEGORY_DATASETS, "List Columns", ["columns", "list columns", "fields"]
    )
    dataset: str = _dataset_field()


async def op_list_columns(node, config, cred):
    return await honeycomb_request(cred, "GET", f"/1/columns/{config.dataset}", action_name="list_columns")


class HoneycombCreateColumnConfig(BaseModel):
    """Create a new column in a dataset."""
    operation: Literal["create_column"] = _op_field(
        "create_column", CATEGORY_DATASETS, "Create Column", ["new column", "add column", "add field"]
    )
    dataset: str = _dataset_field()
    key_name: str = Field(..., title="Key Name", description="The column's key name (1-255 characters).")
    type: Literal["string", "float", "integer", "boolean"] = Field(
        "string", title="Type", description="Column data type.",
        json_schema_extra={"x-enum-searchable": True},
    )
    description: Optional[str] = Field(None, title="Description", description="Column description (max 255 chars).")
    hidden: Optional[Literal["true", "false"]] = Field(
        None, title="Hidden", description="Whether the column is hidden.",
        json_schema_extra={"enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def op_create_column(node, config, cred):
    body = {
        "key_name": config.key_name,
        "type": config.type,
        "description": config.description,
        "hidden": (config.hidden == "true") if config.hidden is not None else None,
    }
    return await honeycomb_request(
        cred, "POST", f"/1/columns/{config.dataset}", json_body=body, action_name="create_column"
    )


class HoneycombGetColumnConfig(BaseModel):
    """Get a single column by key name (query) or by column id (path)."""
    operation: Literal["get_column"] = _op_field(
        "get_column", CATEGORY_DATASETS, "Get Column", ["column details", "fetch column", "get field"]
    )
    dataset: str = _dataset_field()
    key_name: Optional[str] = Field(
        None, title="Key Name", description="Look up the column by key name (leave Column ID blank)."
    )
    column_id: Optional[str] = Field(
        None, title="Column ID", description="Look up the column by its id (takes precedence over Key Name)."
    )


async def op_get_column(node, config, cred):
    if config.column_id:
        return await honeycomb_request(
            cred, "GET", f"/1/columns/{config.dataset}/{config.column_id}", action_name="get_column"
        )
    return await honeycomb_request(
        cred, "GET", f"/1/columns/{config.dataset}", params={"key_name": config.key_name},
        action_name="get_column",
    )


class HoneycombUpdateColumnConfig(BaseModel):
    """Update an existing column by id."""
    operation: Literal["update_column"] = _op_field(
        "update_column", CATEGORY_DATASETS, "Update Column", ["edit column", "modify column"]
    )
    dataset: str = _dataset_field()
    column_id: str = Field(..., title="Column ID", description="The id of the column to update.", json_schema_extra={"x-dynamic-options": {"field_name": 'column_id', "placeholder": 'Select a column...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})
    key_name: str = Field(..., title="Key Name", description="The column's key name (1-255 characters).")
    type: Literal["string", "float", "integer", "boolean"] = Field(
        "string", title="Type", description="Column data type.",
        json_schema_extra={"x-enum-searchable": True},
    )
    description: Optional[str] = Field(None, title="Description", description="Column description (max 255 chars).")
    hidden: Optional[Literal["true", "false"]] = Field(
        None, title="Hidden", description="Whether the column is hidden.",
        json_schema_extra={"enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def op_update_column(node, config, cred):
    body = {
        "key_name": config.key_name,
        "type": config.type,
        "description": config.description,
        "hidden": (config.hidden == "true") if config.hidden is not None else None,
    }
    return await honeycomb_request(
        cred, "PUT", f"/1/columns/{config.dataset}/{config.column_id}", json_body=body,
        action_name="update_column",
    )


class HoneycombDeleteColumnConfig(BaseModel):
    """Delete a column by id."""
    operation: Literal["delete_column"] = _op_field(
        "delete_column", CATEGORY_DATASETS, "Delete Column", ["remove column", "drop column"]
    )
    dataset: str = _dataset_field()
    column_id: str = Field(..., title="Column ID", description="The id of the column to delete.", json_schema_extra={"x-dynamic-options": {"field_name": 'column_id', "placeholder": 'Select a column...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})


async def op_delete_column(node, config, cred):
    return await honeycomb_request(
        cred, "DELETE", f"/1/columns/{config.dataset}/{config.column_id}", action_name="delete_column"
    )


_OPS_datasets = [
    {"op": "list_datasets", "config": HoneycombListDatasetsConfig, "handler": op_list_datasets, "method": "GET", "version": "1", "category": CATEGORY_DATASETS, "verified": True},
    {"op": "create_dataset", "config": HoneycombCreateDatasetConfig, "handler": op_create_dataset, "method": "POST", "version": "1", "category": CATEGORY_DATASETS, "verified": True},
    {"op": "get_dataset", "config": HoneycombGetDatasetConfig, "handler": op_get_dataset, "method": "GET", "version": "1", "category": CATEGORY_DATASETS, "verified": True},
    {"op": "update_dataset", "config": HoneycombUpdateDatasetConfig, "handler": op_update_dataset, "method": "PUT", "version": "1", "category": CATEGORY_DATASETS, "verified": True},
    {"op": "delete_dataset", "config": HoneycombDeleteDatasetConfig, "handler": op_delete_dataset, "method": "DELETE", "version": "1", "category": CATEGORY_DATASETS, "verified": True},
    {"op": "get_dataset_definitions", "config": HoneycombGetDatasetDefinitionsConfig, "handler": op_get_dataset_definitions, "method": "GET", "version": "1", "category": CATEGORY_DATASETS, "verified": True},
    {"op": "update_dataset_definitions", "config": HoneycombUpdateDatasetDefinitionsConfig, "handler": op_update_dataset_definitions, "method": "PATCH", "version": "1", "category": CATEGORY_DATASETS, "verified": True},
    {"op": "list_columns", "config": HoneycombListColumnsConfig, "handler": op_list_columns, "method": "GET", "version": "1", "category": CATEGORY_DATASETS, "verified": True},
    {"op": "create_column", "config": HoneycombCreateColumnConfig, "handler": op_create_column, "method": "POST", "version": "1", "category": CATEGORY_DATASETS, "verified": True},
    {"op": "get_column", "config": HoneycombGetColumnConfig, "handler": op_get_column, "method": "GET", "version": "1", "category": CATEGORY_DATASETS, "verified": True},
    {"op": "update_column", "config": HoneycombUpdateColumnConfig, "handler": op_update_column, "method": "PUT", "version": "1", "category": CATEGORY_DATASETS, "verified": True},
    {"op": "delete_column", "config": HoneycombDeleteColumnConfig, "handler": op_delete_column, "method": "DELETE", "version": "1", "category": CATEGORY_DATASETS, "verified": True},
]


# ==========================================================================
# from derived_columns.py
# ==========================================================================
class HoneycombListDerivedColumnsConfig(BaseModel):
    """List all derived columns in a dataset (or __all__ for environment-wide)."""
    operation: Literal["list_derived_columns"] = _op_field(
        "list_derived_columns", CATEGORY_DATASETS, "List Derived Columns",
        ["calculated fields", "list derived columns", "derived columns"],
    )
    dataset: str = _dataset_field()
    alias: Optional[str] = Field(
        None, title="Alias filter",
        description="Optional exact alias to filter the returned derived columns.",
    )


class HoneycombCreateDerivedColumnConfig(BaseModel):
    """Create a derived column in a dataset (or __all__ for environment-wide)."""
    operation: Literal["create_derived_column"] = _op_field(
        "create_derived_column", CATEGORY_DATASETS, "Create Derived Column",
        ["calculated field", "create derived column", "add derived column"],
    )
    dataset: str = _dataset_field()
    alias: str = Field(..., title="Alias", description="Human-readable name used in queries (1-255 chars).")
    expression: str = Field(..., title="Expression", description="The derived-column formula (1-4095 chars).")
    description: Optional[str] = Field(
        None, title="Description", description="Optional UI description (max 255 chars).",
    )


class HoneycombGetDerivedColumnConfig(BaseModel):
    """Get a single derived column by id."""
    operation: Literal["get_derived_column"] = _op_field(
        "get_derived_column", CATEGORY_DATASETS, "Get Derived Column",
        ["calculated field", "get derived column"],
    )
    dataset: str = _dataset_field()
    derived_column_id: str = Field(..., title="Derived Column ID", description="The derived column's unique id.", json_schema_extra={"x-dynamic-options": {"field_name": 'derived_column_id', "placeholder": 'Select a derived column...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})


class HoneycombUpdateDerivedColumnConfig(BaseModel):
    """Update an existing derived column by id."""
    operation: Literal["update_derived_column"] = _op_field(
        "update_derived_column", CATEGORY_DATASETS, "Update Derived Column",
        ["calculated field", "update derived column", "edit derived column"],
    )
    dataset: str = _dataset_field()
    derived_column_id: str = Field(..., title="Derived Column ID", description="The derived column's unique id.", json_schema_extra={"x-dynamic-options": {"field_name": 'derived_column_id', "placeholder": 'Select a derived column...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})
    alias: str = Field(..., title="Alias", description="Human-readable name used in queries (1-255 chars).")
    expression: str = Field(..., title="Expression", description="The derived-column formula (1-4095 chars).")
    description: Optional[str] = Field(
        None, title="Description", description="Optional UI description (max 255 chars).",
    )


class HoneycombDeleteDerivedColumnConfig(BaseModel):
    """Delete a derived column by id."""
    operation: Literal["delete_derived_column"] = _op_field(
        "delete_derived_column", CATEGORY_DATASETS, "Delete Derived Column",
        ["calculated field", "delete derived column", "remove derived column"],
    )
    dataset: str = _dataset_field()
    derived_column_id: str = Field(..., title="Derived Column ID", description="The derived column's unique id.", json_schema_extra={"x-dynamic-options": {"field_name": 'derived_column_id', "placeholder": 'Select a derived column...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})


async def op_list_derived_columns(node, config, cred):
    params = {"alias": config.alias}
    return await honeycomb_request(
        cred, "GET", f"/1/derived_columns/{config.dataset}",
        params=params, action_name="list_derived_columns",
    )


async def op_create_derived_column(node, config, cred):
    body = {"alias": config.alias, "expression": config.expression, "description": config.description}
    return await honeycomb_request(
        cred, "POST", f"/1/derived_columns/{config.dataset}",
        json_body=body, action_name="create_derived_column",
    )


async def op_get_derived_column(node, config, cred):
    return await honeycomb_request(
        cred, "GET", f"/1/derived_columns/{config.dataset}/{config.derived_column_id}",
        action_name="get_derived_column",
    )


async def op_update_derived_column(node, config, cred):
    body = {"alias": config.alias, "expression": config.expression, "description": config.description}
    return await honeycomb_request(
        cred, "PUT", f"/1/derived_columns/{config.dataset}/{config.derived_column_id}",
        json_body=body, action_name="update_derived_column",
    )


async def op_delete_derived_column(node, config, cred):
    return await honeycomb_request(
        cred, "DELETE", f"/1/derived_columns/{config.dataset}/{config.derived_column_id}",
        action_name="delete_derived_column",
    )


_OPS_derived_columns = [
    {"op": "list_derived_columns", "config": HoneycombListDerivedColumnsConfig, "handler": op_list_derived_columns, "method": "GET", "version": "1", "category": CATEGORY_DATASETS, "verified": True},
    {"op": "create_derived_column", "config": HoneycombCreateDerivedColumnConfig, "handler": op_create_derived_column, "method": "POST", "version": "1", "category": CATEGORY_DATASETS, "verified": True},
    {"op": "get_derived_column", "config": HoneycombGetDerivedColumnConfig, "handler": op_get_derived_column, "method": "GET", "version": "1", "category": CATEGORY_DATASETS, "verified": True},
    {"op": "update_derived_column", "config": HoneycombUpdateDerivedColumnConfig, "handler": op_update_derived_column, "method": "PUT", "version": "1", "category": CATEGORY_DATASETS, "verified": True},
    {"op": "delete_derived_column", "config": HoneycombDeleteDerivedColumnConfig, "handler": op_delete_derived_column, "method": "DELETE", "version": "1", "category": CATEGORY_DATASETS, "verified": True},
]


# ==========================================================================
# from boards.py
# ==========================================================================
class HoneycombListBoardsConfig(BaseModel):
    """List all non-secret Boards in the environment."""
    operation: Literal["list_boards"] = _op_field(
        "list_boards", CATEGORY_BOARDS, "List Boards", ["boards", "list boards", "dashboards"]
    )


class HoneycombCreateBoardConfig(BaseModel):
    """Create a new Board.

    Provide the full Board object as JSON (``type`` and ``name`` are required;
    ``description``, ``panels``, ``layout_generation``, ``tags``,
    ``preset_filters`` are optional).
    """
    operation: Literal["create_board"] = _op_field(
        "create_board", CATEGORY_BOARDS, "Create Board", ["boards", "create board", "new dashboard"]
    )
    body_json: str = _body_json_field(description="Board object as JSON (requires type + name).")


class HoneycombGetBoardConfig(BaseModel):
    """Get a single Board by id."""
    operation: Literal["get_board"] = _op_field(
        "get_board", CATEGORY_BOARDS, "Get Board", ["boards", "get board", "read dashboard"]
    )
    board_id: str = Field(..., title="Board ID", description="The Board identifier.", json_schema_extra={"x-dynamic-options": {"field_name": 'board_id', "placeholder": 'Select a board...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id'}})


class HoneycombUpdateBoardConfig(BaseModel):
    """Update an existing Board by id (full replacement)."""
    operation: Literal["update_board"] = _op_field(
        "update_board", CATEGORY_BOARDS, "Update Board", ["boards", "update board", "edit dashboard"]
    )
    board_id: str = Field(..., title="Board ID", description="The Board identifier.", json_schema_extra={"x-dynamic-options": {"field_name": 'board_id', "placeholder": 'Select a board...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id'}})
    body_json: str = _body_json_field(description="Full Board object as JSON (requires type + name).")


class HoneycombDeleteBoardConfig(BaseModel):
    """Delete a Board by id."""
    operation: Literal["delete_board"] = _op_field(
        "delete_board", CATEGORY_BOARDS, "Delete Board", ["boards", "delete board", "remove dashboard"]
    )
    board_id: str = Field(..., title="Board ID", description="The Board identifier.", json_schema_extra={"x-dynamic-options": {"field_name": 'board_id', "placeholder": 'Select a board...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id'}})


async def op_list_boards(node, config, cred):
    return await honeycomb_request(cred, "GET", "/1/boards", action_name="list_boards")


async def op_create_board(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(cred, "POST", "/1/boards", json_body=body, action_name="create_board")


async def op_get_board(node, config, cred):
    return await honeycomb_request(cred, "GET", f"/1/boards/{config.board_id}", action_name="get_board")


async def op_update_board(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(cred, "PUT", f"/1/boards/{config.board_id}", json_body=body, action_name="update_board")


async def op_delete_board(node, config, cred):
    return await honeycomb_request(cred, "DELETE", f"/1/boards/{config.board_id}", action_name="delete_board")


_OPS_boards = [
    {"op": "list_boards", "config": HoneycombListBoardsConfig, "handler": op_list_boards, "method": "GET", "version": "1", "category": CATEGORY_BOARDS, "verified": True},
    {"op": "create_board", "config": HoneycombCreateBoardConfig, "handler": op_create_board, "method": "POST", "version": "1", "category": CATEGORY_BOARDS, "verified": True},
    {"op": "get_board", "config": HoneycombGetBoardConfig, "handler": op_get_board, "method": "GET", "version": "1", "category": CATEGORY_BOARDS, "verified": True},
    {"op": "update_board", "config": HoneycombUpdateBoardConfig, "handler": op_update_board, "method": "PUT", "version": "1", "category": CATEGORY_BOARDS, "verified": True},
    {"op": "delete_board", "config": HoneycombDeleteBoardConfig, "handler": op_delete_board, "method": "DELETE", "version": "1", "category": CATEGORY_BOARDS, "verified": True},
]


# ==========================================================================
# from queries.py
# ==========================================================================
class HoneycombCreateQueryConfig(BaseModel):
    """Create a query specification in a dataset (returns a reusable query id)."""
    operation: Literal["create_query"] = _op_field(
        "create_query", CATEGORY_QUERIES, "Create Query",
        ["run query", "query spec", "calculations", "create query"],
    )
    dataset: str = _dataset_field()
    body_json: str = _body_json_field(
        description="Query spec JSON (calculations required; breakdowns, filters, orders, "
                    "time_range, start_time, end_time, limit optional).",
    )


class HoneycombGetQueryConfig(BaseModel):
    """Retrieve a query specification by id."""
    operation: Literal["get_query"] = _op_field(
        "get_query", CATEGORY_QUERIES, "Get Query", ["fetch query", "get query"],
    )
    dataset: str = _dataset_field()
    query_id: str = Field(..., title="Query ID", description="ID of the query to retrieve.")


class HoneycombCreateQueryResultConfig(BaseModel):
    """Kick off asynchronous execution of a query and get a query result id."""
    operation: Literal["create_query_result"] = _op_field(
        "create_query_result", CATEGORY_QUERIES, "Create Query Result",
        ["run query", "execute query", "query data", "create query result"],
    )
    dataset: str = _dataset_field()
    body_json: str = _body_json_field(
        description='Request body JSON, e.g. {"query_id": "..."} or {"query": {...}}. '
                    "Time range limited to the last 7 days.",
    )


class HoneycombGetQueryResultConfig(BaseModel):
    """Poll for the result of a previously created query result."""
    operation: Literal["get_query_result"] = _op_field(
        "get_query_result", CATEGORY_QUERIES, "Get Query Result",
        ["poll query", "query results", "get query result"],
    )
    dataset: str = _dataset_field()
    query_result_id: str = Field(..., title="Query Result ID", description="ID of the query result to poll.")


class HoneycombCreateQueryAnnotationConfig(BaseModel):
    """Create a query annotation (name/description for a saved query)."""
    operation: Literal["create_query_annotation"] = _op_field(
        "create_query_annotation", CATEGORY_QUERIES, "Create Query Annotation",
        ["name query", "annotate query", "create query annotation"],
    )
    dataset: str = _dataset_field()
    name: str = Field(..., title="Name", description="Display name for the annotated query.")
    query_id: str = Field(..., title="Query ID", description="ID of the query to annotate.")
    description: Optional[str] = Field(None, title="Description", description="Optional description.")


class HoneycombListQueryAnnotationsConfig(BaseModel):
    """List all query annotations in a dataset."""
    operation: Literal["list_query_annotations"] = _op_field(
        "list_query_annotations", CATEGORY_QUERIES, "List Query Annotations",
        ["query annotations", "list query annotations"],
    )
    dataset: str = _dataset_field()


class HoneycombGetQueryAnnotationConfig(BaseModel):
    """Retrieve a single query annotation by id."""
    operation: Literal["get_query_annotation"] = _op_field(
        "get_query_annotation", CATEGORY_QUERIES, "Get Query Annotation",
        ["fetch query annotation", "get query annotation"],
    )
    dataset: str = _dataset_field()
    annotation_id: str = Field(..., title="Annotation ID", description="ID of the query annotation.", json_schema_extra={"x-dynamic-options": {"field_name": 'annotation_id', "placeholder": 'Select a annotation...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})


class HoneycombUpdateQueryAnnotationConfig(BaseModel):
    """Update a query annotation's name/description."""
    operation: Literal["update_query_annotation"] = _op_field(
        "update_query_annotation", CATEGORY_QUERIES, "Update Query Annotation",
        ["edit query annotation", "rename query", "update query annotation"],
    )
    dataset: str = _dataset_field()
    annotation_id: str = Field(..., title="Annotation ID", description="ID of the query annotation to update.", json_schema_extra={"x-dynamic-options": {"field_name": 'annotation_id', "placeholder": 'Select a annotation...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})
    name: str = Field(..., title="Name", description="Updated display name.")
    query_id: str = Field(..., title="Query ID", description="ID of the annotated query (cannot be changed).")
    description: str = Field(..., title="Description", description="Updated description.")


class HoneycombDeleteQueryAnnotationConfig(BaseModel):
    """Delete a query annotation."""
    operation: Literal["delete_query_annotation"] = _op_field(
        "delete_query_annotation", CATEGORY_QUERIES, "Delete Query Annotation",
        ["remove query annotation", "delete query annotation"],
    )
    dataset: str = _dataset_field()
    annotation_id: str = Field(..., title="Annotation ID", description="ID of the query annotation to delete.", json_schema_extra={"x-dynamic-options": {"field_name": 'annotation_id', "placeholder": 'Select a annotation...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})


async def op_create_query(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(
        cred, "POST", f"/1/queries/{config.dataset}", json_body=body, action_name="create_query",
    )


async def op_get_query(node, config, cred):
    return await honeycomb_request(
        cred, "GET", f"/1/queries/{config.dataset}/{config.query_id}", action_name="get_query",
    )


async def op_create_query_result(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(
        cred, "POST", f"/1/query_results/{config.dataset}", json_body=body, action_name="create_query_result",
    )


async def op_get_query_result(node, config, cred):
    return await honeycomb_request(
        cred, "GET", f"/1/query_results/{config.dataset}/{config.query_result_id}",
        action_name="get_query_result",
    )


async def op_create_query_annotation(node, config, cred):
    body = {"name": config.name, "query_id": config.query_id, "description": config.description}
    return await honeycomb_request(
        cred, "POST", f"/1/query_annotations/{config.dataset}", json_body=body,
        action_name="create_query_annotation",
    )


async def op_list_query_annotations(node, config, cred):
    return await honeycomb_request(
        cred, "GET", f"/1/query_annotations/{config.dataset}", action_name="list_query_annotations",
    )


async def op_get_query_annotation(node, config, cred):
    return await honeycomb_request(
        cred, "GET", f"/1/query_annotations/{config.dataset}/{config.annotation_id}",
        action_name="get_query_annotation",
    )


async def op_update_query_annotation(node, config, cred):
    body = {
        "id": config.annotation_id,
        "name": config.name,
        "query_id": config.query_id,
        "description": config.description,
    }
    return await honeycomb_request(
        cred, "PUT", f"/1/query_annotations/{config.dataset}/{config.annotation_id}", json_body=body,
        action_name="update_query_annotation",
    )


async def op_delete_query_annotation(node, config, cred):
    return await honeycomb_request(
        cred, "DELETE", f"/1/query_annotations/{config.dataset}/{config.annotation_id}",
        action_name="delete_query_annotation",
    )


_OPS_queries = [
    {"op": "create_query", "config": HoneycombCreateQueryConfig, "handler": op_create_query, "method": "POST", "version": "1", "category": CATEGORY_QUERIES, "verified": True},
    {"op": "get_query", "config": HoneycombGetQueryConfig, "handler": op_get_query, "method": "GET", "version": "1", "category": CATEGORY_QUERIES, "verified": True},
    {"op": "create_query_result", "config": HoneycombCreateQueryResultConfig, "handler": op_create_query_result, "method": "POST", "version": "1", "category": CATEGORY_QUERIES, "verified": True},
    {"op": "get_query_result", "config": HoneycombGetQueryResultConfig, "handler": op_get_query_result, "method": "GET", "version": "1", "category": CATEGORY_QUERIES, "verified": True},
    {"op": "create_query_annotation", "config": HoneycombCreateQueryAnnotationConfig, "handler": op_create_query_annotation, "method": "POST", "version": "1", "category": CATEGORY_QUERIES, "verified": True},
    {"op": "list_query_annotations", "config": HoneycombListQueryAnnotationsConfig, "handler": op_list_query_annotations, "method": "GET", "version": "1", "category": CATEGORY_QUERIES, "verified": True},
    {"op": "get_query_annotation", "config": HoneycombGetQueryAnnotationConfig, "handler": op_get_query_annotation, "method": "GET", "version": "1", "category": CATEGORY_QUERIES, "verified": True},
    {"op": "update_query_annotation", "config": HoneycombUpdateQueryAnnotationConfig, "handler": op_update_query_annotation, "method": "PUT", "version": "1", "category": CATEGORY_QUERIES, "verified": True},
    {"op": "delete_query_annotation", "config": HoneycombDeleteQueryAnnotationConfig, "handler": op_delete_query_annotation, "method": "DELETE", "version": "1", "category": CATEGORY_QUERIES, "verified": True},
]


# ==========================================================================
# from markers.py
# ==========================================================================
class HoneycombCreateMarkerConfig(BaseModel):
    """Create a marker on a dataset (or __all__ for the environment)."""
    operation: Literal["create_marker"] = _op_field(
        "create_marker", CATEGORY_MARKERS, "Create Marker", ["add marker", "deploy marker", "annotate"]
    )
    dataset: str = _dataset_field()
    message: Optional[str] = Field(None, title="Message", description="Description shown on the marker.")
    type: Optional[str] = Field(None, title="Type", description="Groups markers; shared type shares a color.")
    url: Optional[str] = Field(None, title="URL", description="Clickable link associated with the marker.")
    start_time: Optional[int] = Field(None, title="Start Time", description="Marker placement time (Unix seconds).")
    end_time: Optional[int] = Field(None, title="End Time", description="Optional end time for a time range (Unix seconds).")


class HoneycombListMarkersConfig(BaseModel):
    """List all markers on a dataset (or __all__ for the environment)."""
    operation: Literal["list_markers"] = _op_field(
        "list_markers", CATEGORY_MARKERS, "List Markers", ["get markers", "list markers"]
    )
    dataset: str = _dataset_field()


class HoneycombUpdateMarkerConfig(BaseModel):
    """Update an existing marker by id."""
    operation: Literal["update_marker"] = _op_field(
        "update_marker", CATEGORY_MARKERS, "Update Marker", ["edit marker", "modify marker"]
    )
    dataset: str = _dataset_field()
    marker_id: str = Field(..., title="Marker ID", description="Id of the marker to update.", json_schema_extra={"x-dynamic-options": {"field_name": 'marker_id', "placeholder": 'Select a marker...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})
    message: Optional[str] = Field(None, title="Message", description="Description shown on the marker.")
    type: Optional[str] = Field(None, title="Type", description="Groups markers; shared type shares a color.")
    url: Optional[str] = Field(None, title="URL", description="Clickable link associated with the marker.")
    start_time: Optional[int] = Field(None, title="Start Time", description="Marker placement time (Unix seconds).")
    end_time: Optional[int] = Field(None, title="End Time", description="Optional end time for a time range (Unix seconds).")


class HoneycombDeleteMarkerConfig(BaseModel):
    """Delete a marker by id."""
    operation: Literal["delete_marker"] = _op_field(
        "delete_marker", CATEGORY_MARKERS, "Delete Marker", ["remove marker"]
    )
    dataset: str = _dataset_field()
    marker_id: str = Field(..., title="Marker ID", description="Id of the marker to delete.", json_schema_extra={"x-dynamic-options": {"field_name": 'marker_id', "placeholder": 'Select a marker...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})


class HoneycombCreateMarkerSettingConfig(BaseModel):
    """Create a marker setting (color for a marker type) on a dataset."""
    operation: Literal["create_marker_setting"] = _op_field(
        "create_marker_setting", CATEGORY_MARKERS, "Create Marker Setting", ["marker color", "marker type color"]
    )
    dataset: str = _dataset_field()
    type: str = Field(..., title="Type", description="Marker type this setting applies to (required).")
    color: Optional[str] = Field(None, title="Color", description="Hex color for markers of this type (e.g. #7b1fa2).")


class HoneycombListMarkerSettingsConfig(BaseModel):
    """List all marker settings on a dataset."""
    operation: Literal["list_marker_settings"] = _op_field(
        "list_marker_settings", CATEGORY_MARKERS, "List Marker Settings", ["get marker settings", "marker colors"]
    )
    dataset: str = _dataset_field()


class HoneycombUpdateMarkerSettingConfig(BaseModel):
    """Update a marker setting by id (type cannot be changed after creation)."""
    operation: Literal["update_marker_setting"] = _op_field(
        "update_marker_setting", CATEGORY_MARKERS, "Update Marker Setting", ["edit marker color", "change marker color"]
    )
    dataset: str = _dataset_field()
    marker_setting_id: str = Field(..., title="Marker Setting ID", description="Id of the marker setting to update.", json_schema_extra={"x-dynamic-options": {"field_name": 'marker_setting_id', "placeholder": 'Select a marker setting...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})
    type: str = Field(..., title="Type", description="Marker type (required; cannot change after creation).")
    color: Optional[str] = Field(None, title="Color", description="Hex color for markers of this type (e.g. #7b1fa2).")


class HoneycombDeleteMarkerSettingConfig(BaseModel):
    """Delete a marker setting by id."""
    operation: Literal["delete_marker_setting"] = _op_field(
        "delete_marker_setting", CATEGORY_MARKERS, "Delete Marker Setting", ["remove marker color"]
    )
    dataset: str = _dataset_field()
    marker_setting_id: str = Field(..., title="Marker Setting ID", description="Id of the marker setting to delete.", json_schema_extra={"x-dynamic-options": {"field_name": 'marker_setting_id', "placeholder": 'Select a marker setting...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})


async def op_create_marker(node, config, cred):
    body = {
        "message": config.message,
        "type": config.type,
        "url": config.url,
        "start_time": config.start_time,
        "end_time": config.end_time,
    }
    return await honeycomb_request(
        cred, "POST", f"/1/markers/{config.dataset}", json_body=body, action_name="create_marker"
    )


async def op_list_markers(node, config, cred):
    return await honeycomb_request(
        cred, "GET", f"/1/markers/{config.dataset}", action_name="list_markers"
    )


async def op_update_marker(node, config, cred):
    body = {
        "message": config.message,
        "type": config.type,
        "url": config.url,
        "start_time": config.start_time,
        "end_time": config.end_time,
    }
    return await honeycomb_request(
        cred, "PUT", f"/1/markers/{config.dataset}/{config.marker_id}", json_body=body, action_name="update_marker"
    )


async def op_delete_marker(node, config, cred):
    return await honeycomb_request(
        cred, "DELETE", f"/1/markers/{config.dataset}/{config.marker_id}", action_name="delete_marker"
    )


async def op_create_marker_setting(node, config, cred):
    body = {"type": config.type, "color": config.color}
    return await honeycomb_request(
        cred, "POST", f"/1/marker_settings/{config.dataset}", json_body=body, action_name="create_marker_setting"
    )


async def op_list_marker_settings(node, config, cred):
    return await honeycomb_request(
        cred, "GET", f"/1/marker_settings/{config.dataset}", action_name="list_marker_settings"
    )


async def op_update_marker_setting(node, config, cred):
    body = {"type": config.type, "color": config.color}
    return await honeycomb_request(
        cred, "PUT", f"/1/marker_settings/{config.dataset}/{config.marker_setting_id}",
        json_body=body, action_name="update_marker_setting",
    )


async def op_delete_marker_setting(node, config, cred):
    return await honeycomb_request(
        cred, "DELETE", f"/1/marker_settings/{config.dataset}/{config.marker_setting_id}",
        action_name="delete_marker_setting",
    )


_OPS_markers = [
    {"op": "create_marker", "config": HoneycombCreateMarkerConfig, "handler": op_create_marker, "method": "POST", "version": "1", "category": CATEGORY_MARKERS, "verified": True},
    {"op": "list_markers", "config": HoneycombListMarkersConfig, "handler": op_list_markers, "method": "GET", "version": "1", "category": CATEGORY_MARKERS, "verified": True},
    {"op": "update_marker", "config": HoneycombUpdateMarkerConfig, "handler": op_update_marker, "method": "PUT", "version": "1", "category": CATEGORY_MARKERS, "verified": True},
    {"op": "delete_marker", "config": HoneycombDeleteMarkerConfig, "handler": op_delete_marker, "method": "DELETE", "version": "1", "category": CATEGORY_MARKERS, "verified": True},
    {"op": "create_marker_setting", "config": HoneycombCreateMarkerSettingConfig, "handler": op_create_marker_setting, "method": "POST", "version": "1", "category": CATEGORY_MARKERS, "verified": True},
    {"op": "list_marker_settings", "config": HoneycombListMarkerSettingsConfig, "handler": op_list_marker_settings, "method": "GET", "version": "1", "category": CATEGORY_MARKERS, "verified": True},
    {"op": "update_marker_setting", "config": HoneycombUpdateMarkerSettingConfig, "handler": op_update_marker_setting, "method": "PUT", "version": "1", "category": CATEGORY_MARKERS, "verified": True},
    {"op": "delete_marker_setting", "config": HoneycombDeleteMarkerSettingConfig, "handler": op_delete_marker_setting, "method": "DELETE", "version": "1", "category": CATEGORY_MARKERS, "verified": True},
]


# ==========================================================================
# from triggers.py
# ==========================================================================
class HoneycombCreateTriggerConfig(BaseModel):
    """Create a trigger (alert) in a dataset."""
    operation: Literal["create_trigger"] = _op_field(
        "create_trigger", CATEGORY_TRIGGERS, "Create Trigger", ["alert", "create trigger", "new alert"]
    )
    dataset: str = _dataset_field()
    body_json: str = _body_json_field(
        description="Trigger definition JSON (name, query/query_id, threshold, frequency, recipients, ...).",
    )


class HoneycombListTriggersConfig(BaseModel):
    """List all triggers in a dataset."""
    operation: Literal["list_triggers"] = _op_field(
        "list_triggers", CATEGORY_TRIGGERS, "List Triggers", ["alerts", "list triggers"]
    )
    dataset: str = _dataset_field()


class HoneycombGetTriggerConfig(BaseModel):
    """Get a single trigger by ID."""
    operation: Literal["get_trigger"] = _op_field(
        "get_trigger", CATEGORY_TRIGGERS, "Get Trigger", ["alert", "get trigger"]
    )
    dataset: str = _dataset_field()
    trigger_id: str = Field(..., title="Trigger ID", description="The ID of the trigger.", json_schema_extra={"x-dynamic-options": {"field_name": 'trigger_id', "placeholder": 'Select a trigger...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})


class HoneycombUpdateTriggerConfig(BaseModel):
    """Update a trigger by ID (full replacement of trigger fields)."""
    operation: Literal["update_trigger"] = _op_field(
        "update_trigger", CATEGORY_TRIGGERS, "Update Trigger", ["alert", "update trigger", "edit alert"]
    )
    dataset: str = _dataset_field()
    trigger_id: str = Field(..., title="Trigger ID", description="The ID of the trigger.", json_schema_extra={"x-dynamic-options": {"field_name": 'trigger_id', "placeholder": 'Select a trigger...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})
    body_json: str = _body_json_field(
        description="Full trigger definition JSON (same fields used to create the trigger).",
    )


class HoneycombDeleteTriggerConfig(BaseModel):
    """Delete a trigger by ID."""
    operation: Literal["delete_trigger"] = _op_field(
        "delete_trigger", CATEGORY_TRIGGERS, "Delete Trigger", ["alert", "delete trigger", "remove alert"]
    )
    dataset: str = _dataset_field()
    trigger_id: str = Field(..., title="Trigger ID", description="The ID of the trigger.", json_schema_extra={"x-dynamic-options": {"field_name": 'trigger_id', "placeholder": 'Select a trigger...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})


async def op_create_trigger(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(
        cred, "POST", f"/1/triggers/{config.dataset}", json_body=body, action_name="create_trigger"
    )


async def op_list_triggers(node, config, cred):
    return await honeycomb_request(
        cred, "GET", f"/1/triggers/{config.dataset}", action_name="list_triggers"
    )


async def op_get_trigger(node, config, cred):
    return await honeycomb_request(
        cred, "GET", f"/1/triggers/{config.dataset}/{config.trigger_id}", action_name="get_trigger"
    )


async def op_update_trigger(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(
        cred, "PUT", f"/1/triggers/{config.dataset}/{config.trigger_id}",
        json_body=body, action_name="update_trigger",
    )


async def op_delete_trigger(node, config, cred):
    return await honeycomb_request(
        cred, "DELETE", f"/1/triggers/{config.dataset}/{config.trigger_id}", action_name="delete_trigger"
    )


_OPS_triggers_ops = [
    {"op": "create_trigger", "config": HoneycombCreateTriggerConfig, "handler": op_create_trigger, "method": "POST", "version": "1", "category": CATEGORY_TRIGGERS, "verified": True},
    {"op": "list_triggers", "config": HoneycombListTriggersConfig, "handler": op_list_triggers, "method": "GET", "version": "1", "category": CATEGORY_TRIGGERS, "verified": True},
    {"op": "get_trigger", "config": HoneycombGetTriggerConfig, "handler": op_get_trigger, "method": "GET", "version": "1", "category": CATEGORY_TRIGGERS, "verified": True},
    {"op": "update_trigger", "config": HoneycombUpdateTriggerConfig, "handler": op_update_trigger, "method": "PUT", "version": "1", "category": CATEGORY_TRIGGERS, "verified": True},
    {"op": "delete_trigger", "config": HoneycombDeleteTriggerConfig, "handler": op_delete_trigger, "method": "DELETE", "version": "1", "category": CATEGORY_TRIGGERS, "verified": True},
]


# ==========================================================================
# from slos.py
# ==========================================================================
class HoneycombCreateSloConfig(BaseModel):
    """Create an SLO in a dataset."""
    operation: Literal["create_slo"] = _op_field(
        "create_slo", CATEGORY_SLOS, "Create SLO",
        ["slo", "service level objective", "create slo"],
    )
    dataset: str = _dataset_field()
    body_json: str = _body_json_field(
        description=(
            "SLO object as JSON. Required: name, sli ({\"alias\": \"...\"}), "
            "time_period_days, target_per_million. Optional: description, dataset_slugs."
        ),
    )


async def op_create_slo(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(
        cred, "POST", f"/1/slos/{config.dataset}", json_body=body, action_name="create_slo",
    )


class HoneycombListSlosConfig(BaseModel):
    """List all SLOs in a dataset."""
    operation: Literal["list_slos"] = _op_field(
        "list_slos", CATEGORY_SLOS, "List SLOs",
        ["slo", "service level objective", "list slos"],
    )
    dataset: str = _dataset_field()


async def op_list_slos(node, config, cred):
    return await honeycomb_request(
        cred, "GET", f"/1/slos/{config.dataset}", action_name="list_slos",
    )


class HoneycombGetSloConfig(BaseModel):
    """Get a single SLO, optionally with budget/compliance detail."""
    operation: Literal["get_slo"] = _op_field(
        "get_slo", CATEGORY_SLOS, "Get SLO",
        ["slo", "service level objective", "get slo", "budget remaining", "compliance"],
    )
    dataset: str = _dataset_field()
    slo_id: str = Field(..., title="SLO ID", description="ID of the SLO to fetch.", json_schema_extra={"x-dynamic-options": {"field_name": 'slo_id', "placeholder": 'Select a SLO...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})
    detailed: Optional[str] = Field(
        None, title="Detailed",
        description="Set to 'true' to include budget_remaining and compliance.",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


async def op_get_slo(node, config, cred):
    params = {"detailed": config.detailed} if config.detailed else None
    return await honeycomb_request(
        cred, "GET", f"/1/slos/{config.dataset}/{config.slo_id}",
        params=params, action_name="get_slo",
    )


class HoneycombUpdateSloConfig(BaseModel):
    """Update an SLO (full replace — send all fields)."""
    operation: Literal["update_slo"] = _op_field(
        "update_slo", CATEGORY_SLOS, "Update SLO",
        ["slo", "service level objective", "update slo", "edit slo"],
    )
    dataset: str = _dataset_field()
    slo_id: str = Field(..., title="SLO ID", description="ID of the SLO to update.", json_schema_extra={"x-dynamic-options": {"field_name": 'slo_id', "placeholder": 'Select a SLO...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})
    body_json: str = _body_json_field(
        description=(
            "Full SLO object as JSON (partial updates not supported). "
            "Include name, sli, time_period_days, target_per_million."
        ),
    )


async def op_update_slo(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(
        cred, "PUT", f"/1/slos/{config.dataset}/{config.slo_id}",
        json_body=body, action_name="update_slo",
    )


class HoneycombDeleteSloConfig(BaseModel):
    """Delete an SLO from a dataset."""
    operation: Literal["delete_slo"] = _op_field(
        "delete_slo", CATEGORY_SLOS, "Delete SLO",
        ["slo", "service level objective", "delete slo", "remove slo"],
    )
    dataset: str = _dataset_field()
    slo_id: str = Field(..., title="SLO ID", description="ID of the SLO to delete.", json_schema_extra={"x-dynamic-options": {"field_name": 'slo_id', "placeholder": 'Select a SLO...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})


async def op_delete_slo(node, config, cred):
    return await honeycomb_request(
        cred, "DELETE", f"/1/slos/{config.dataset}/{config.slo_id}", action_name="delete_slo",
    )


class HoneycombCreateBurnAlertConfig(BaseModel):
    """Create a burn alert for an SLO."""
    operation: Literal["create_burn_alert"] = _op_field(
        "create_burn_alert", CATEGORY_SLOS, "Create Burn Alert",
        ["burn alert", "slo alert", "create burn alert", "exhaustion", "budget rate"],
    )
    dataset: str = _dataset_field()
    body_json: str = _body_json_field(
        description=(
            "Burn alert object as JSON. Required: slo_id, alert_type "
            "('exhaustion_time' or 'budget_rate'). For exhaustion_time: exhaustion_minutes. "
            "For budget_rate: budget_rate_window_minutes, "
            "budget_rate_decrease_threshold_per_million. Optional: description, recipients."
        ),
    )


async def op_create_burn_alert(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(
        cred, "POST", f"/1/burn_alerts/{config.dataset}",
        json_body=body, action_name="create_burn_alert",
    )


class HoneycombListBurnAlertsConfig(BaseModel):
    """List burn alerts for a specific SLO in a dataset."""
    operation: Literal["list_burn_alerts"] = _op_field(
        "list_burn_alerts", CATEGORY_SLOS, "List Burn Alerts",
        ["burn alert", "slo alert", "list burn alerts"],
    )
    dataset: str = _dataset_field()
    slo_id: str = Field(..., title="SLO ID", description="Filter burn alerts by this SLO ID.", json_schema_extra={"x-dynamic-options": {"field_name": 'slo_id', "placeholder": 'Select a SLO...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})


async def op_list_burn_alerts(node, config, cred):
    return await honeycomb_request(
        cred, "GET", f"/1/burn_alerts/{config.dataset}",
        params={"slo_id": config.slo_id}, action_name="list_burn_alerts",
    )


class HoneycombGetBurnAlertConfig(BaseModel):
    """Get a single burn alert."""
    operation: Literal["get_burn_alert"] = _op_field(
        "get_burn_alert", CATEGORY_SLOS, "Get Burn Alert",
        ["burn alert", "slo alert", "get burn alert"],
    )
    dataset: str = _dataset_field()
    burn_alert_id: str = Field(..., title="Burn Alert ID", description="ID of the burn alert to fetch.")


async def op_get_burn_alert(node, config, cred):
    return await honeycomb_request(
        cred, "GET", f"/1/burn_alerts/{config.dataset}/{config.burn_alert_id}",
        action_name="get_burn_alert",
    )


class HoneycombUpdateBurnAlertConfig(BaseModel):
    """Update a burn alert (full replace — send all fields)."""
    operation: Literal["update_burn_alert"] = _op_field(
        "update_burn_alert", CATEGORY_SLOS, "Update Burn Alert",
        ["burn alert", "slo alert", "update burn alert", "edit burn alert"],
    )
    dataset: str = _dataset_field()
    burn_alert_id: str = Field(..., title="Burn Alert ID", description="ID of the burn alert to update.")
    body_json: str = _body_json_field(
        description=(
            "Full burn alert object as JSON (same fields as create): slo_id, alert_type, "
            "and the alert_type-specific threshold fields."
        ),
    )


async def op_update_burn_alert(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(
        cred, "PUT", f"/1/burn_alerts/{config.dataset}/{config.burn_alert_id}",
        json_body=body, action_name="update_burn_alert",
    )


class HoneycombDeleteBurnAlertConfig(BaseModel):
    """Delete a burn alert from a dataset."""
    operation: Literal["delete_burn_alert"] = _op_field(
        "delete_burn_alert", CATEGORY_SLOS, "Delete Burn Alert",
        ["burn alert", "slo alert", "delete burn alert", "remove burn alert"],
    )
    dataset: str = _dataset_field()
    burn_alert_id: str = Field(..., title="Burn Alert ID", description="ID of the burn alert to delete.")


async def op_delete_burn_alert(node, config, cred):
    return await honeycomb_request(
        cred, "DELETE", f"/1/burn_alerts/{config.dataset}/{config.burn_alert_id}",
        action_name="delete_burn_alert",
    )


_OPS_slos = [
    {"op": "create_slo", "config": HoneycombCreateSloConfig, "handler": op_create_slo, "method": "POST", "version": "1", "category": CATEGORY_SLOS, "verified": True},
    {"op": "list_slos", "config": HoneycombListSlosConfig, "handler": op_list_slos, "method": "GET", "version": "1", "category": CATEGORY_SLOS, "verified": True},
    {"op": "get_slo", "config": HoneycombGetSloConfig, "handler": op_get_slo, "method": "GET", "version": "1", "category": CATEGORY_SLOS, "verified": True},
    {"op": "update_slo", "config": HoneycombUpdateSloConfig, "handler": op_update_slo, "method": "PUT", "version": "1", "category": CATEGORY_SLOS, "verified": True},
    {"op": "delete_slo", "config": HoneycombDeleteSloConfig, "handler": op_delete_slo, "method": "DELETE", "version": "1", "category": CATEGORY_SLOS, "verified": True},
    {"op": "create_burn_alert", "config": HoneycombCreateBurnAlertConfig, "handler": op_create_burn_alert, "method": "POST", "version": "1", "category": CATEGORY_SLOS, "verified": True},
    {"op": "list_burn_alerts", "config": HoneycombListBurnAlertsConfig, "handler": op_list_burn_alerts, "method": "GET", "version": "1", "category": CATEGORY_SLOS, "verified": True},
    {"op": "get_burn_alert", "config": HoneycombGetBurnAlertConfig, "handler": op_get_burn_alert, "method": "GET", "version": "1", "category": CATEGORY_SLOS, "verified": True},
    {"op": "update_burn_alert", "config": HoneycombUpdateBurnAlertConfig, "handler": op_update_burn_alert, "method": "PUT", "version": "1", "category": CATEGORY_SLOS, "verified": True},
    {"op": "delete_burn_alert", "config": HoneycombDeleteBurnAlertConfig, "handler": op_delete_burn_alert, "method": "DELETE", "version": "1", "category": CATEGORY_SLOS, "verified": True},
]


# ==========================================================================
# from recipients.py
# ==========================================================================
class HoneycombListRecipientsConfig(BaseModel):
    """List all recipients for the team/environment."""
    operation: Literal["list_recipients"] = _op_field(
        "list_recipients", CATEGORY_RECIPIENTS, "List Recipients",
        ["recipients", "notification targets", "list recipients", "alert destinations"],
    )


class HoneycombCreateRecipientConfig(BaseModel):
    """Create a recipient (notification target).

    Body carries ``type`` (email, slack, pagerduty, webhook, msteams_workflow)
    and a type-specific ``details`` object, so it is supplied as JSON.
    """
    operation: Literal["create_recipient"] = _op_field(
        "create_recipient", CATEGORY_RECIPIENTS, "Create Recipient",
        ["recipients", "add recipient", "create notification target", "new alert destination"],
    )
    body_json: str = _body_json_field(
        description='Recipient body: {"type": "email", "details": {"email_address": "..."}}',
    )


class HoneycombGetRecipientConfig(BaseModel):
    """Get a single recipient by ID."""
    operation: Literal["get_recipient"] = _op_field(
        "get_recipient", CATEGORY_RECIPIENTS, "Get Recipient",
        ["recipients", "get recipient", "read notification target"],
    )
    recipient_id: str = Field(..., title="Recipient ID", description="The recipient's unique ID.", json_schema_extra={"x-dynamic-options": {"field_name": 'recipient_id', "placeholder": 'Select a recipient...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id'}})


class HoneycombUpdateRecipientConfig(BaseModel):
    """Update a recipient (full object replace)."""
    operation: Literal["update_recipient"] = _op_field(
        "update_recipient", CATEGORY_RECIPIENTS, "Update Recipient",
        ["recipients", "update recipient", "edit notification target"],
    )
    recipient_id: str = Field(..., title="Recipient ID", description="The recipient's unique ID.", json_schema_extra={"x-dynamic-options": {"field_name": 'recipient_id', "placeholder": 'Select a recipient...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id'}})
    body_json: str = _body_json_field(
        description='Full recipient body: {"type": "email", "details": {"email_address": "..."}}',
    )


class HoneycombDeleteRecipientConfig(BaseModel):
    """Delete a recipient by ID."""
    operation: Literal["delete_recipient"] = _op_field(
        "delete_recipient", CATEGORY_RECIPIENTS, "Delete Recipient",
        ["recipients", "delete recipient", "remove notification target"],
    )
    recipient_id: str = Field(..., title="Recipient ID", description="The recipient's unique ID.", json_schema_extra={"x-dynamic-options": {"field_name": 'recipient_id', "placeholder": 'Select a recipient...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id'}})


async def op_list_recipients(node, config, cred):
    return await honeycomb_request(cred, "GET", "/1/recipients", action_name="list_recipients")


async def op_create_recipient(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(cred, "POST", "/1/recipients", json_body=body, action_name="create_recipient")


async def op_get_recipient(node, config, cred):
    return await honeycomb_request(cred, "GET", f"/1/recipients/{config.recipient_id}", action_name="get_recipient")


async def op_update_recipient(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(cred, "PUT", f"/1/recipients/{config.recipient_id}", json_body=body, action_name="update_recipient")


async def op_delete_recipient(node, config, cred):
    return await honeycomb_request(cred, "DELETE", f"/1/recipients/{config.recipient_id}", action_name="delete_recipient")


_OPS_recipients = [
    {"op": "list_recipients", "config": HoneycombListRecipientsConfig, "handler": op_list_recipients, "method": "GET", "version": "1", "category": CATEGORY_RECIPIENTS, "verified": True},
    {"op": "create_recipient", "config": HoneycombCreateRecipientConfig, "handler": op_create_recipient, "method": "POST", "version": "1", "category": CATEGORY_RECIPIENTS, "verified": True},
    {"op": "get_recipient", "config": HoneycombGetRecipientConfig, "handler": op_get_recipient, "method": "GET", "version": "1", "category": CATEGORY_RECIPIENTS, "verified": True},
    {"op": "update_recipient", "config": HoneycombUpdateRecipientConfig, "handler": op_update_recipient, "method": "PUT", "version": "1", "category": CATEGORY_RECIPIENTS, "verified": True},
    {"op": "delete_recipient", "config": HoneycombDeleteRecipientConfig, "handler": op_delete_recipient, "method": "DELETE", "version": "1", "category": CATEGORY_RECIPIENTS, "verified": True},
]


# ==========================================================================
# from management.py
# ==========================================================================
def _team_slug_field():
    return Field(..., title="Team Slug", description="Your Honeycomb team slug (from GET /2/auth `included[].attributes.slug`, or the UI URL).")


# --- Auth (no team scope) ----------------------------------------------------
class HoneycombGetAuthConfig(BaseModel):
    """Return metadata about the v1 API key in use (X-Honeycomb-Team)."""
    operation: Literal["get_auth"] = _op_field(
        "get_auth", CATEGORY_MANAGEMENT, "Get Auth (v1)", ["whoami", "auth", "api key info", "team"]
    )


async def op_get_auth(node, config, cred):
    return await honeycomb_request(cred, "GET", "/1/auth", version="1", action_name="get_auth")


class HoneycombGetAuthV2Config(BaseModel):
    """Return metadata about the v2 Management key in use (Bearer key_id:secret)."""
    operation: Literal["get_auth_v2"] = _op_field(
        "get_auth_v2", CATEGORY_MANAGEMENT, "Get Auth (v2)", ["whoami", "management key info", "auth v2", "team slug"]
    )


async def op_get_auth_v2(node, config, cred):
    return await honeycomb_request(cred, "GET", "/2/auth", version="2", params={"include": "team"}, action_name="get_auth_v2")


# --- Environments (/2/teams/{teamSlug}/environments) -------------------------
class HoneycombListEnvironmentsConfig(BaseModel):
    """List environments for the team (v2 Management API)."""
    operation: Literal["list_environments"] = _op_field(
        "list_environments", CATEGORY_MANAGEMENT, "List Environments", ["environments", "list environments", "envs"]
    )
    team_slug: str = _team_slug_field()
    page_size: Optional[int] = Field(None, title="Page Size", description="Entries per page (1-100).")
    page_after: Optional[str] = Field(None, title="Page After", description="Pagination cursor from a previous response.")


async def op_list_environments(node, config, cred):
    params = {"page[size]": config.page_size, "page[after]": config.page_after}
    return await honeycomb_request(cred, "GET", f"/2/teams/{config.team_slug}/environments", version="2", params=params, action_name="list_environments")


class HoneycombCreateEnvironmentConfig(BaseModel):
    """Create an environment (v2 JSON:API envelope: data.type=environments)."""
    operation: Literal["create_environment"] = _op_field(
        "create_environment", CATEGORY_MANAGEMENT, "Create Environment", ["environments", "new environment", "add env"]
    )
    team_slug: str = _team_slug_field()
    body_json: str = _body_json_field(
        description='JSON:API body, e.g. {"data": {"type": "environments", "attributes": {"name": "...", "description": "...", "color": "blue"}}}'
    )


async def op_create_environment(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(cred, "POST", f"/2/teams/{config.team_slug}/environments", version="2", json_body=body, action_name="create_environment")


class HoneycombGetEnvironmentConfig(BaseModel):
    """Get a single environment by id (v2 Management API)."""
    operation: Literal["get_environment"] = _op_field(
        "get_environment", CATEGORY_MANAGEMENT, "Get Environment", ["environments", "get environment", "read env"]
    )
    team_slug: str = _team_slug_field()
    environment_id: str = Field(..., title="Environment ID", description="The environment id.", json_schema_extra={"x-dynamic-options": {"field_name": 'environment_id', "placeholder": 'Select a environment...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'team_slug'}})


async def op_get_environment(node, config, cred):
    return await honeycomb_request(cred, "GET", f"/2/teams/{config.team_slug}/environments/{config.environment_id}", version="2", action_name="get_environment")


class HoneycombUpdateEnvironmentConfig(BaseModel):
    """Update an environment by id (v2 JSON:API envelope; PATCH)."""
    operation: Literal["update_environment"] = _op_field(
        "update_environment", CATEGORY_MANAGEMENT, "Update Environment", ["environments", "edit environment", "modify env"]
    )
    team_slug: str = _team_slug_field()
    environment_id: str = Field(..., title="Environment ID", description="The environment id.", json_schema_extra={"x-dynamic-options": {"field_name": 'environment_id', "placeholder": 'Select a environment...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'team_slug'}})
    body_json: str = _body_json_field(
        description='JSON:API body, e.g. {"data": {"type": "environments", "id": "<id>", "attributes": {"description": "...", "settings": {"delete_protected": false}}}}'
    )


async def op_update_environment(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(cred, "PATCH", f"/2/teams/{config.team_slug}/environments/{config.environment_id}", version="2", json_body=body, action_name="update_environment")


class HoneycombDeleteEnvironmentConfig(BaseModel):
    """Delete an environment by id (v2 Management API)."""
    operation: Literal["delete_environment"] = _op_field(
        "delete_environment", CATEGORY_MANAGEMENT, "Delete Environment", ["environments", "delete environment", "remove env"]
    )
    team_slug: str = _team_slug_field()
    environment_id: str = Field(..., title="Environment ID", description="The environment id.", json_schema_extra={"x-dynamic-options": {"field_name": 'environment_id', "placeholder": 'Select a environment...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'team_slug'}})


async def op_delete_environment(node, config, cred):
    return await honeycomb_request(cred, "DELETE", f"/2/teams/{config.team_slug}/environments/{config.environment_id}", version="2", action_name="delete_environment")


# --- API keys (/2/teams/{teamSlug}/api-keys) --------------------------------
class HoneycombListApiKeysConfig(BaseModel):
    """List API keys for the team (v2 Management API)."""
    operation: Literal["list_api_keys"] = _op_field(
        "list_api_keys", CATEGORY_MANAGEMENT, "List API Keys", ["api keys", "list keys", "ingest key", "configuration key"]
    )
    team_slug: str = _team_slug_field()
    page_size: Optional[int] = Field(None, title="Page Size", description="Entries per page (1-100).")
    page_after: Optional[str] = Field(None, title="Page After", description="Pagination cursor from a previous response.")


async def op_list_api_keys(node, config, cred):
    params = {"page[size]": config.page_size, "page[after]": config.page_after}
    return await honeycomb_request(cred, "GET", f"/2/teams/{config.team_slug}/api-keys", version="2", params=params, action_name="list_api_keys")


class HoneycombCreateApiKeyConfig(BaseModel):
    """Create an API key (v2 JSON:API: data.type=api-keys, attributes + environment relationship)."""
    operation: Literal["create_api_key"] = _op_field(
        "create_api_key", CATEGORY_MANAGEMENT, "Create API Key", ["api keys", "new key", "create ingest key", "create configuration key"]
    )
    team_slug: str = _team_slug_field()
    body_json: str = _body_json_field(
        description='JSON:API body, e.g. {"data": {"type": "api-keys", "attributes": {"name": "...", "key_type": "ingest", "permissions": {"create_datasets": true}}, "relationships": {"environment": {"data": {"type": "environments", "id": "<env-id>"}}}}}'
    )


async def op_create_api_key(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(cred, "POST", f"/2/teams/{config.team_slug}/api-keys", version="2", json_body=body, action_name="create_api_key")


class HoneycombGetApiKeyConfig(BaseModel):
    """Get a single API key by id (v2 Management API)."""
    operation: Literal["get_api_key"] = _op_field(
        "get_api_key", CATEGORY_MANAGEMENT, "Get API Key", ["api keys", "get key", "read key"]
    )
    team_slug: str = _team_slug_field()
    api_key_id: str = Field(..., title="API Key ID", description="The API key id.", json_schema_extra={"x-dynamic-options": {"field_name": 'api_key_id', "placeholder": 'Select a API key...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'team_slug'}})


async def op_get_api_key(node, config, cred):
    return await honeycomb_request(cred, "GET", f"/2/teams/{config.team_slug}/api-keys/{config.api_key_id}", version="2", action_name="get_api_key")


class HoneycombUpdateApiKeyConfig(BaseModel):
    """Update an API key by id (v2 JSON:API envelope; PATCH; e.g. disable/rename)."""
    operation: Literal["update_api_key"] = _op_field(
        "update_api_key", CATEGORY_MANAGEMENT, "Update API Key", ["api keys", "edit key", "disable key", "rename key"]
    )
    team_slug: str = _team_slug_field()
    api_key_id: str = Field(..., title="API Key ID", description="The API key id.", json_schema_extra={"x-dynamic-options": {"field_name": 'api_key_id', "placeholder": 'Select a API key...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'team_slug'}})
    body_json: str = _body_json_field(
        description='JSON:API body, e.g. {"data": {"type": "api-keys", "id": "<id>", "attributes": {"disabled": true}}}'
    )


async def op_update_api_key(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(cred, "PATCH", f"/2/teams/{config.team_slug}/api-keys/{config.api_key_id}", version="2", json_body=body, action_name="update_api_key")


class HoneycombDeleteApiKeyConfig(BaseModel):
    """Delete an API key by id (v2 Management API)."""
    operation: Literal["delete_api_key"] = _op_field(
        "delete_api_key", CATEGORY_MANAGEMENT, "Delete API Key", ["api keys", "delete key", "revoke key", "remove key"]
    )
    team_slug: str = _team_slug_field()
    api_key_id: str = Field(..., title="API Key ID", description="The API key id.", json_schema_extra={"x-dynamic-options": {"field_name": 'api_key_id', "placeholder": 'Select a API key...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'team_slug'}})


async def op_delete_api_key(node, config, cred):
    return await honeycomb_request(cred, "DELETE", f"/2/teams/{config.team_slug}/api-keys/{config.api_key_id}", version="2", action_name="delete_api_key")


_OPS_management = [
    {"op": "get_auth", "config": HoneycombGetAuthConfig, "handler": op_get_auth, "method": "GET", "version": "1", "category": CATEGORY_MANAGEMENT, "verified": True},
    {"op": "get_auth_v2", "config": HoneycombGetAuthV2Config, "handler": op_get_auth_v2, "method": "GET", "version": "2", "category": CATEGORY_MANAGEMENT, "verified": True},
    {"op": "list_environments", "config": HoneycombListEnvironmentsConfig, "handler": op_list_environments, "method": "GET", "version": "2", "category": CATEGORY_MANAGEMENT, "verified": True},
    {"op": "create_environment", "config": HoneycombCreateEnvironmentConfig, "handler": op_create_environment, "method": "POST", "version": "2", "category": CATEGORY_MANAGEMENT, "verified": True},
    {"op": "get_environment", "config": HoneycombGetEnvironmentConfig, "handler": op_get_environment, "method": "GET", "version": "2", "category": CATEGORY_MANAGEMENT, "verified": True},
    {"op": "update_environment", "config": HoneycombUpdateEnvironmentConfig, "handler": op_update_environment, "method": "PATCH", "version": "2", "category": CATEGORY_MANAGEMENT, "verified": True},
    {"op": "delete_environment", "config": HoneycombDeleteEnvironmentConfig, "handler": op_delete_environment, "method": "DELETE", "version": "2", "category": CATEGORY_MANAGEMENT, "verified": True},
    {"op": "list_api_keys", "config": HoneycombListApiKeysConfig, "handler": op_list_api_keys, "method": "GET", "version": "2", "category": CATEGORY_MANAGEMENT, "verified": True},
    {"op": "create_api_key", "config": HoneycombCreateApiKeyConfig, "handler": op_create_api_key, "method": "POST", "version": "2", "category": CATEGORY_MANAGEMENT, "verified": True},
    {"op": "get_api_key", "config": HoneycombGetApiKeyConfig, "handler": op_get_api_key, "method": "GET", "version": "2", "category": CATEGORY_MANAGEMENT, "verified": True},
    {"op": "update_api_key", "config": HoneycombUpdateApiKeyConfig, "handler": op_update_api_key, "method": "PATCH", "version": "2", "category": CATEGORY_MANAGEMENT, "verified": True},
    {"op": "delete_api_key", "config": HoneycombDeleteApiKeyConfig, "handler": op_delete_api_key, "method": "DELETE", "version": "2", "category": CATEGORY_MANAGEMENT, "verified": True},
]


# ==========================================================================
# from extra.py
# ==========================================================================
# --- Boards: saved views ---------------------------------------------------

class HoneycombListBoardViewsConfig(BaseModel):
    """List all saved views for a board (max 50 per board)."""
    operation: Literal["list_board_views"] = _op_field(
        "list_board_views", CATEGORY_BOARDS, "List Board Views",
        ["board views", "list views", "saved views"],
    )
    board_id: str = Field(..., title="Board ID", description="The Board identifier.", json_schema_extra={"x-dynamic-options": {"field_name": 'board_id', "placeholder": 'Select a board...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id'}})


class HoneycombCreateBoardViewConfig(BaseModel):
    """Create a saved filter view on a board."""
    operation: Literal["create_board_view"] = _op_field(
        "create_board_view", CATEGORY_BOARDS, "Create Board View",
        ["board view", "create view", "saved filter view"],
    )
    board_id: str = Field(..., title="Board ID", description="The Board identifier.", json_schema_extra={"x-dynamic-options": {"field_name": 'board_id', "placeholder": 'Select a board...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id'}})
    body_json: str = _body_json_field(description="Board view object as JSON (name + filters).")


class HoneycombGetBoardViewConfig(BaseModel):
    """Get a single board view by id."""
    operation: Literal["get_board_view"] = _op_field(
        "get_board_view", CATEGORY_BOARDS, "Get Board View",
        ["board view", "get view", "read view"],
    )
    board_id: str = Field(..., title="Board ID", description="The Board identifier.", json_schema_extra={"x-dynamic-options": {"field_name": 'board_id', "placeholder": 'Select a board...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id'}})
    view_id: str = Field(..., title="View ID", description="The board view identifier.", json_schema_extra={"x-dynamic-options": {"field_name": 'view_id', "placeholder": 'Select a view...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'board_id'}})


class HoneycombUpdateBoardViewConfig(BaseModel):
    """Update a board view's name and filters."""
    operation: Literal["update_board_view"] = _op_field(
        "update_board_view", CATEGORY_BOARDS, "Update Board View",
        ["board view", "update view", "edit view"],
    )
    board_id: str = Field(..., title="Board ID", description="The Board identifier.", json_schema_extra={"x-dynamic-options": {"field_name": 'board_id', "placeholder": 'Select a board...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id'}})
    view_id: str = Field(..., title="View ID", description="The board view identifier.", json_schema_extra={"x-dynamic-options": {"field_name": 'view_id', "placeholder": 'Select a view...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'board_id'}})
    body_json: str = _body_json_field(description="Board view object as JSON (name + filters).")


class HoneycombDeleteBoardViewConfig(BaseModel):
    """Delete a board view."""
    operation: Literal["delete_board_view"] = _op_field(
        "delete_board_view", CATEGORY_BOARDS, "Delete Board View",
        ["board view", "delete view", "remove view"],
    )
    board_id: str = Field(..., title="Board ID", description="The Board identifier.", json_schema_extra={"x-dynamic-options": {"field_name": 'board_id', "placeholder": 'Select a board...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id'}})
    view_id: str = Field(..., title="View ID", description="The board view identifier.", json_schema_extra={"x-dynamic-options": {"field_name": 'view_id', "placeholder": 'Select a view...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'board_id'}})


# --- SLOs & Burn Alerts ----------------------------------------------------

class HoneycombGetSloHistoryConfig(BaseModel):
    """Get a weekly breakdown of historical data for a list of SLOs (up to 24 ids)."""
    operation: Literal["get_slo_history"] = _op_field(
        "get_slo_history", CATEGORY_SLOS, "Get SLO History",
        ["slo history", "historical slo", "slo report", "weekly slo"],
    )
    ids: str = Field(
        ..., title="SLO IDs",
        description="Comma-separated SLO ids (up to 24), or a JSON array of ids.",
    )
    start_time: int = Field(..., title="Start Time", description="Unix timestamp (seconds).")
    end_time: int = Field(..., title="End Time", description="Unix timestamp (seconds).")


class HoneycombGetSloHourlyCountsHistoryConfig(BaseModel):
    """Get hourly-bucketed total and error event counts for an SLO over a time range."""
    operation: Literal["get_slo_hourly_counts_history"] = _op_field(
        "get_slo_hourly_counts_history", CATEGORY_SLOS, "Get SLO Hourly Counts History",
        ["slo counts", "hourly counts", "slo history counts"],
    )
    dataset: str = _dataset_field()
    slo_id: str = Field(..., title="SLO ID", description="The SLO identifier.", json_schema_extra={"x-dynamic-options": {"field_name": 'slo_id', "placeholder": 'Select a SLO...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})
    start_time: Optional[int] = Field(None, title="Start Time", description="Unix timestamp (seconds).")
    end_time: Optional[int] = Field(None, title="End Time", description="Unix timestamp (seconds).")


class HoneycombGetSloRealtimeCountsConfig(BaseModel):
    """Get per-minute success/failure event counts for an SLO from a rolling 24h window."""
    operation: Literal["get_slo_realtime_counts"] = _op_field(
        "get_slo_realtime_counts", CATEGORY_SLOS, "Get SLO Realtime Counts",
        ["slo counts", "realtime counts", "per-minute counts"],
    )
    dataset: str = _dataset_field()
    slo_id: str = Field(..., title="SLO ID", description="The SLO identifier.", json_schema_extra={"x-dynamic-options": {"field_name": 'slo_id', "placeholder": 'Select a SLO...', "searchable": True, "allow_custom": True, "custom_placeholder": 'Or paste an id', "depends_on": 'dataset'}})
    start_time: Optional[int] = Field(None, title="Start Time", description="Unix timestamp (seconds).")
    end_time: Optional[int] = Field(None, title="End Time", description="Unix timestamp (seconds).")


# --- Queries: service map dependencies -------------------------------------

class HoneycombCreateMapDependencyRequestConfig(BaseModel):
    """Create a service-map dependency request (async computation of service dependencies)."""
    operation: Literal["create_map_dependency_request"] = _op_field(
        "create_map_dependency_request", CATEGORY_QUERIES, "Create Map Dependency Request",
        ["service map", "dependencies", "map request"],
    )
    body_json: str = _body_json_field(
        description="Request body as JSON (start_time, end_time, time_range, filters — all optional)."
    )
    limit: Optional[int] = Field(None, title="Limit", description="Max number of dependencies.")


class HoneycombGetMapDependenciesConfig(BaseModel):
    """Get results of a service-map dependency request (paginated dependencies)."""
    operation: Literal["get_map_dependencies"] = _op_field(
        "get_map_dependencies", CATEGORY_QUERIES, "Get Map Dependencies",
        ["service map", "dependencies", "map results"],
    )
    request_id: str = Field(..., title="Request ID", description="The dependency request identifier.")
    page_after: Optional[str] = Field(None, title="Page After", description="Pagination cursor (page[after]).")
    page_size: Optional[int] = Field(None, title="Page Size", description="Page size (page[size]).")


# --- Recipients ------------------------------------------------------------

class HoneycombGetTriggersAssociatedWithRecipientConfig(BaseModel):
    """List all triggers that notify a given recipient."""
    operation: Literal["get_triggers_associated_with_recipient"] = _op_field(
        "get_triggers_associated_with_recipient", CATEGORY_RECIPIENTS,
        "Get Triggers For Recipient",
        ["recipient triggers", "triggers for recipient", "recipient alerts"],
    )
    recipient_id: str = Field(..., title="Recipient ID", description="The recipient identifier.")


# NOTE: v2 environment/api-key create ops live in operations/management.py
# (team-scoped /2/teams/{teamSlug}/... paths). Earlier _v2 duplicates removed.

# --- Handlers --------------------------------------------------------------

async def op_list_board_views(node, config, cred):
    return await honeycomb_request(
        cred, "GET", f"/1/boards/{config.board_id}/views",
        version="1", action_name="list_board_views",
    )


async def op_create_board_view(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(
        cred, "POST", f"/1/boards/{config.board_id}/views",
        version="1", json_body=body, action_name="create_board_view",
    )


async def op_get_board_view(node, config, cred):
    return await honeycomb_request(
        cred, "GET", f"/1/boards/{config.board_id}/views/{config.view_id}",
        version="1", action_name="get_board_view",
    )


async def op_update_board_view(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    return await honeycomb_request(
        cred, "PUT", f"/1/boards/{config.board_id}/views/{config.view_id}",
        version="1", json_body=body, action_name="update_board_view",
    )


async def op_delete_board_view(node, config, cred):
    return await honeycomb_request(
        cred, "DELETE", f"/1/boards/{config.board_id}/views/{config.view_id}",
        version="1", action_name="delete_board_view",
    )


async def op_get_slo_history(node, config, cred):
    raw = config.ids.strip()
    if raw.startswith("["):
        ids = json.loads(raw)
    else:
        ids = [i.strip() for i in raw.split(",") if i.strip()]
    body: Dict[str, Any] = {
        "ids": ids,
        "start_time": config.start_time,
        "end_time": config.end_time,
    }
    return await honeycomb_request(
        cred, "POST", "/1/reporting/slos/historical",
        version="1", json_body=body, action_name="get_slo_history",
    )


async def op_get_slo_hourly_counts_history(node, config, cred):
    params = {"start_time": config.start_time, "end_time": config.end_time}
    return await honeycomb_request(
        cred, "GET", f"/1/slos/{config.dataset}/{config.slo_id}/counts/history",
        version="1", params=params, action_name="get_slo_hourly_counts_history",
    )


async def op_get_slo_realtime_counts(node, config, cred):
    params = {"start_time": config.start_time, "end_time": config.end_time}
    return await honeycomb_request(
        cred, "GET", f"/1/slos/{config.dataset}/{config.slo_id}/counts",
        version="1", params=params, action_name="get_slo_realtime_counts",
    )


async def op_create_map_dependency_request(node, config, cred):
    body = json.loads(config.body_json) if config.body_json else {}
    params = {"limit": config.limit}
    return await honeycomb_request(
        cred, "POST", "/1/maps/dependencies/requests",
        version="1", params=params, json_body=body,
        action_name="create_map_dependency_request",
    )


async def op_get_map_dependencies(node, config, cred):
    params = {"page[after]": config.page_after, "page[size]": config.page_size}
    return await honeycomb_request(
        cred, "GET", f"/1/maps/dependencies/requests/{config.request_id}",
        version="1", params=params, action_name="get_map_dependencies",
    )


async def op_get_triggers_associated_with_recipient(node, config, cred):
    return await honeycomb_request(
        cred, "GET", f"/1/recipients/{config.recipient_id}/triggers",
        version="1", action_name="get_triggers_associated_with_recipient",
    )


_OPS_extra = [
    {"op": "list_board_views", "config": HoneycombListBoardViewsConfig, "handler": op_list_board_views, "method": "GET", "version": "1", "category": CATEGORY_BOARDS, "verified": True},
    {"op": "create_board_view", "config": HoneycombCreateBoardViewConfig, "handler": op_create_board_view, "method": "POST", "version": "1", "category": CATEGORY_BOARDS, "verified": True},
    {"op": "get_board_view", "config": HoneycombGetBoardViewConfig, "handler": op_get_board_view, "method": "GET", "version": "1", "category": CATEGORY_BOARDS, "verified": True},
    {"op": "update_board_view", "config": HoneycombUpdateBoardViewConfig, "handler": op_update_board_view, "method": "PUT", "version": "1", "category": CATEGORY_BOARDS, "verified": True},
    {"op": "delete_board_view", "config": HoneycombDeleteBoardViewConfig, "handler": op_delete_board_view, "method": "DELETE", "version": "1", "category": CATEGORY_BOARDS, "verified": True},
    {"op": "get_slo_history", "config": HoneycombGetSloHistoryConfig, "handler": op_get_slo_history, "method": "POST", "version": "1", "category": CATEGORY_SLOS, "verified": True},
    {"op": "get_slo_hourly_counts_history", "config": HoneycombGetSloHourlyCountsHistoryConfig, "handler": op_get_slo_hourly_counts_history, "method": "GET", "version": "1", "category": CATEGORY_SLOS, "verified": True},
    {"op": "get_slo_realtime_counts", "config": HoneycombGetSloRealtimeCountsConfig, "handler": op_get_slo_realtime_counts, "method": "GET", "version": "1", "category": CATEGORY_SLOS, "verified": True},
    {"op": "create_map_dependency_request", "config": HoneycombCreateMapDependencyRequestConfig, "handler": op_create_map_dependency_request, "method": "POST", "version": "1", "category": CATEGORY_QUERIES, "verified": True},
    {"op": "get_map_dependencies", "config": HoneycombGetMapDependenciesConfig, "handler": op_get_map_dependencies, "method": "GET", "version": "1", "category": CATEGORY_QUERIES, "verified": True},
    {"op": "get_triggers_associated_with_recipient", "config": HoneycombGetTriggersAssociatedWithRecipientConfig, "handler": op_get_triggers_associated_with_recipient, "method": "GET", "version": "1", "category": CATEGORY_RECIPIENTS, "verified": True},
]


# ==========================================================================
# from triggers.py
# ==========================================================================

WEBHOOK_TOKEN_HEADER = "x-honeycomb-webhook-token"
WEBHOOK_DELIVERY_HEADER = "x-honeycomb-webhook-delivery-id"


class _HoneycombTriggerBase(WebhookTriggerConfigBase):
    """Shared visible fields for Honeycomb webhook triggers."""

    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Register this URL as a Honeycomb webhook recipient (done automatically).",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )
    attach_dataset: Optional[str] = Field(
        default=None,
        title="Attach to Dataset (optional)",
        description="If set with 'Attach to ID', auto-attach the recipient to that Honeycomb trigger/burn alert.",
    )
    attach_id: Optional[str] = Field(
        default=None,
        title="Attach to Trigger/Burn Alert ID (optional)",
        description="An existing Honeycomb trigger id (or burn alert id) to attach this recipient to.",
    )


class HoneycombOnTriggerFiredConfig(_HoneycombTriggerBase):
    """Fires when a Honeycomb Trigger notifies this webhook recipient."""
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_trigger_fired"] = Field(
        "on_trigger_fired", title="On Trigger Fired",
        json_schema_extra={
            "const": "on_trigger_fired", "ui:hidden": True, "x-is-trigger": True,
            "x-category": "Triggers", "x-display-name": "On Trigger Fired",
            "x-keywords": ["alert fired", "trigger fired", "honeycomb alert"],
        },
    )


class HoneycombOnBurnAlertConfig(_HoneycombTriggerBase):
    """Fires when a Honeycomb SLO Burn Alert notifies this webhook recipient."""
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_burn_alert"] = Field(
        "on_burn_alert", title="On Burn Alert",
        json_schema_extra={
            "const": "on_burn_alert", "ui:hidden": True, "x-is-trigger": True,
            "x-category": "Triggers", "x-display-name": "On Burn Alert",
            "x-keywords": ["slo burn", "burn alert", "error budget"],
        },
    )


TRIGGER_CONFIGS = (HoneycombOnTriggerFiredConfig, HoneycombOnBurnAlertConfig)
TRIGGER_OPS = {c.model_fields["operation"].default for c in TRIGGER_CONFIGS}


# ---------------------------------------------------------------------------
# Recipient lifecycle helpers (called by the node's mixin methods)
# ---------------------------------------------------------------------------
async def create_webhook_recipient(cred: Dict[str, Any], webhook_url: str, name: str, secret: str) -> str:
    """Create a Honeycomb webhook recipient; return its id."""
    body = {
        "type": "webhook",
        "details": {
            "webhook_name": name,
            "webhook_url": webhook_url,
            "webhook_secret": secret,
        },
    }
    result = await honeycomb_request(cred, "POST", "/1/recipients", json_body=body, action_name="create_recipient")
    if result.get("status") != "success":
        raise ValueError(f"Honeycomb recipient creation failed: {result.get('error')}")
    rid = (result.get("data") or {}).get("id")
    if not rid:
        raise ValueError("Honeycomb did not return a recipient id")
    return str(rid)


async def delete_webhook_recipient(cred: Dict[str, Any], recipient_id: str) -> None:
    await honeycomb_request(cred, "DELETE", f"/1/recipients/{recipient_id}", action_name="delete_recipient")


async def attach_recipient_to_trigger(cred: Dict[str, Any], dataset: str, trigger_id: str, recipient_id: str) -> None:
    """Best-effort: append the recipient to an existing trigger's recipients."""
    got = await honeycomb_request(cred, "GET", f"/1/triggers/{dataset}/{trigger_id}", action_name="get_trigger")
    if got.get("status") != "success":
        raise ValueError(f"Could not load trigger {trigger_id}: {got.get('error')}")
    trigger = got.get("data") or {}
    recipients = trigger.get("recipients") or []
    if not any((r or {}).get("id") == recipient_id for r in recipients):
        recipients.append({"id": recipient_id})
    body = {"recipients": recipients}
    put = await honeycomb_request(cred, "PUT", f"/1/triggers/{dataset}/{trigger_id}",
                                  json_body=body, action_name="update_trigger")
    if put.get("status") != "success":
        raise ValueError(f"Could not attach recipient to trigger: {put.get('error')}")


def verify_webhook_token(headers: Dict[str, str], secret: Optional[str]) -> bool:
    """Constant-time compare of the X-Honeycomb-Webhook-Token header to the secret.

    Honeycomb custom webhooks send the shared secret verbatim (no HMAC). If no
    secret was stored, accept (an unsigned recipient) — the URL itself is the
    capability.
    """
    if not secret:
        return True
    token = headers.get(WEBHOOK_TOKEN_HEADER) or headers.get("X-Honeycomb-Webhook-Token")
    if not token:
        return False
    return hmac.compare_digest(str(token), str(secret))


# ==========================================================================
# from registry.py
# ==========================================================================
_ACTION_MODULES = (
    _OPS_events, _OPS_datasets, _OPS_derived_columns, _OPS_boards, _OPS_queries,
    _OPS_markers, _OPS_triggers_ops, _OPS_slos, _OPS_recipients, _OPS_management, _OPS_extra,
)


# ---------------------------------------------------------------------------
# Raw REST passthrough — 100% long-tail coverage.
# ---------------------------------------------------------------------------
class HoneycombRestRequestConfig(BaseModel):
    """Make an arbitrary Honeycomb REST request (v1 or v2)."""

    operation: Literal["rest_request"] = _op_field(
        "rest_request", CATEGORY_PASSTHROUGH, "REST Request (Raw)",
        ["raw", "custom request", "passthrough", "any endpoint"],
    )
    method: str = Field(
        "GET", title="Method",
        json_schema_extra={"enum": ["GET", "POST", "PUT", "PATCH", "DELETE"], "x-enum-searchable": True},
    )
    path: str = Field(..., title="Path", description="e.g. /1/triggers/my-dataset  or  /2/environments")
    version: str = Field(
        "1", title="API Version",
        json_schema_extra={"enum": ["1", "2"], "enumNames": ["v1", "v2 (Management)"], "x-enum-searchable": True},
    )
    params_json: Optional[str] = Field(
        None, title="Query Params (JSON)",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "ui:rows": 3},
    )
    body_json: Optional[str] = Field(
        None, title="Body (JSON)",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "ui:rows": 6},
    )


async def op_rest_request(node, config, cred):
    params = json.loads(config.params_json) if config.params_json else None
    body = json.loads(config.body_json) if config.body_json else None
    return await honeycomb_request(
        cred, config.method, config.path, version=config.version,
        params=params, json_body=body, action_name="rest_request",
    )


# ---------------------------------------------------------------------------
# Aggregate action operations from the generated domain modules.
# ---------------------------------------------------------------------------
_ACTION_CONFIG_CLASSES: List[type] = []
HANDLERS: Dict[str, Any] = {"rest_request": op_rest_request}
OP_META: Dict[str, Dict[str, Any]] = {
    "rest_request": {"method": "*", "version": "*", "category": CATEGORY_PASSTHROUGH, "verified": True},
}

for _mod in _ACTION_MODULES:
    for _entry in _mod:
        _op = _entry["op"]
        if _op in HANDLERS:
            raise ValueError(f"Duplicate Honeycomb operation id: {_op}")
        _ACTION_CONFIG_CLASSES.append(_entry["config"])
        HANDLERS[_op] = _entry["handler"]
        OP_META[_op] = {
            "method": _entry.get("method"),
            "version": _entry.get("version", "1"),
            "category": _entry.get("category"),
            "verified": _entry.get("verified", True),
        }

_ACTION_CONFIG_CLASSES.append(HoneycombRestRequestConfig)

TRIGGER_OPS = set(TRIGGER_OPS)

_ALL_CONFIG_CLASSES = tuple(_ACTION_CONFIG_CLASSES) + tuple(TRIGGER_CONFIGS)

CONFIGS_BY_OP: Dict[str, type] = {
    cls.model_fields["operation"].default: cls for cls in _ALL_CONFIG_CLASSES
}

HoneycombConfig = Annotated[
    Union[_ALL_CONFIG_CLASSES],
    Discriminator("operation"),
]


class HoneycombNodeConfig(NodeConfig[HoneycombConfig, HoneycombCredential]):
    """Full configuration for the Honeycomb node including credentials."""
    pass


# ==========================================================================
# from honeycomb_node.py
# ==========================================================================


# Dynamic-dropdown sources: field_name -> how to list its options. `dep` is the
# parent config field whose value scopes the list (dataset / board_id / team_slug);
# a dependent dropdown returns nothing until its parent is set. v2 entries read the
# Management API (JSON:API rows). Keep in sync with the x-dynamic-options markers on
# the id fields in the operation modules.
_DROPDOWNS = {
    "dataset": {"path": "/1/datasets", "value": "slug", "label": ["name", "slug"]},
    "trigger_id": {"path": "/1/triggers/{dataset}", "dep": "dataset", "value": "id", "label": ["name"]},
    "marker_id": {"path": "/1/markers/{dataset}", "dep": "dataset", "value": "id", "label": ["message", "type"]},
    "marker_setting_id": {"path": "/1/marker_settings/{dataset}", "dep": "dataset", "value": "id", "label": ["type"]},
    "column_id": {"path": "/1/columns/{dataset}", "dep": "dataset", "value": "id", "label": ["key_name"]},
    "derived_column_id": {"path": "/1/derived_columns/{dataset}", "dep": "dataset", "value": "id", "label": ["alias"]},
    "annotation_id": {"path": "/1/query_annotations/{dataset}", "dep": "dataset", "value": "id", "label": ["name"]},
    "slo_id": {"path": "/1/slos/{dataset}", "dep": "dataset", "value": "id", "label": ["name"]},
    "board_id": {"path": "/1/boards", "value": "id", "label": ["name"]},
    "recipient_id": {"path": "/1/recipients", "value": "id", "label": ["name", "details.webhook_name", "type"]},
    "view_id": {"path": "/1/boards/{board_id}/views", "dep": "board_id", "value": "id", "label": ["name"]},
    "environment_id": {"path": "/2/teams/{team_slug}/environments", "dep": "team_slug", "version": "2", "value": "id", "label": ["name"]},
    "api_key_id": {"path": "/2/teams/{team_slug}/api-keys", "dep": "team_slug", "version": "2", "value": "id", "label": ["name"]},
}


def _first_present(row, keys):
    """Return the first present (possibly dotted) key value from a row."""
    for key in keys:
        cur = row
        for part in key.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        if cur:
            return cur
    return None


class HoneycombNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Honeycomb observability automation node (REST + native webhook triggers)."""

    edit_examples = [
        "Create a Honeycomb marker when a deploy finishes",
        "List the triggers in my dataset",
        "Run a Honeycomb query and get the results",
        "Create an SLO burn alert",
        "When a Honeycomb trigger fires, notify my team",
    ]

    @classmethod
    def get_config_model(cls):
        return HoneycombNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options — dataset dropdown
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        spec = _DROPDOWNS.get(field_name)
        if not spec:
            return {"options": [], "next_page_token": None}
        credential = credential_data or {}
        ctx = context or {}
        version = spec.get("version", "1")

        # A dependent dropdown can't load until its parent field is set.
        dep = spec.get("dep")
        if dep and not ctx.get(dep):
            return {"options": [], "next_page_token": None}

        if version == "2":
            if not (credential.get("key_id") and credential.get("secret")):
                raise ValueError("Connect a Honeycomb Management key to load these options")
        elif not credential.get("api_key"):
            raise ValueError("Connect a Honeycomb API key to load these options")

        path = spec["path"].format(**{dep: ctx.get(dep)}) if dep else spec["path"]
        result = await honeycomb_request(credential, "GET", path, version=version, action_name=f"load_{field_name}")
        if result.get("status") != "success":
            raise ValueError(f"Failed to load options: {result.get('error')}")

        data = result.get("data")
        rows = (data.get("data") if version == "2" and isinstance(data, dict) else data) or []
        options = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            if version == "2":
                value = r.get("id")
                label = (r.get("attributes") or {}).get("name") or value
            else:
                value = r.get(spec["value"])
                label = _first_present(r, spec["label"]) or value
            if value is not None:
                options.append({"label": str(label), "value": str(value)})

        from nodes.core.dynamic_options import filter_options_by_search
        return {
            "options": filter_options_by_search(options, search, fields=("label", "value")),
            "next_page_token": None,
        }

    # ------------------------------------------------------------------
    # Webhook trigger lifecycle
    # ------------------------------------------------------------------
    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Re-register if the auto-attach target changes.
        return {
            "attach_dataset": (config or {}).get("attach_dataset"),
            "attach_id": (config or {}).get("attach_id"),
        }

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id) -> Dict[str, Any]:
        if not (credential or {}).get("api_key"):
            raise ValueError("Honeycomb webhook triggers need a v1 API key (X-Honeycomb-Team)")

        secret = secrets.token_hex(24)
        name = f"NoClick {node_id}"[:255]
        recipient_id = await create_webhook_recipient(credential, webhook_url, name, secret)

        # Optionally auto-attach to an existing trigger/burn alert.
        attach_dataset = (config or {}).get("attach_dataset")
        attach_id = (config or {}).get("attach_id")
        if attach_dataset and attach_id:
            try:
                await attach_recipient_to_trigger(credential, attach_dataset, attach_id, recipient_id)
            except Exception as e:
                logger.warning(f"[HoneycombNode] Could not auto-attach recipient: {e}")

        return {"external_webhook_id": recipient_id, "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id) -> None:
        recipient_id = (config or {}).get("external_webhook_id")
        if not credential or not (credential or {}).get("api_key") or not recipient_id:
            return
        await delete_webhook_recipient(credential, str(recipient_id))

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]) -> bool:
        """Honeycomb sends the shared secret verbatim in X-Honeycomb-Webhook-Token
        (plaintext token, NOT HMAC) — constant-time compare it to the stored secret."""
        return verify_webhook_token(headers or {}, (config or {}).get("signing_secret"))

    @classmethod
    def resolve_agent_event(cls, output):
        payload = output if isinstance(output, dict) else {}
        data = payload.get("data", payload)
        name = data.get("name") or data.get("trigger_description") if isinstance(data, dict) else None
        text = json.dumps(data, default=str)[:6000]
        return {"text": f"Honeycomb alert {name}:\n{text}" if name else text, "conversation_key": None}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, HoneycombNodeConfig):
            raise ValueError("Valid configuration is required")
        op_config = config.config
        operation = op_config.operation

        # Triggers: the webhook delivery IS the data — pass the fired payload through.
        if operation in TRIGGER_OPS:
            return {
                "status": "success", "action": operation, "data": inputs or {},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add a Honeycomb API key (or Management key).")
        cred = credentials.model_dump()

        handler = HANDLERS.get(operation)
        if not handler:
            raise ValueError(f"Unknown Honeycomb operation: {operation}")
        try:
            return await handler(self, op_config, cred)
        except json.JSONDecodeError as e:
            return {"status": "error", "action": operation,
                    "error": f"A JSON argument is invalid: {e.msg}"}
