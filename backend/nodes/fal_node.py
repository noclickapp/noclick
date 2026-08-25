"""
fal (fal.ai) model-inference automation node.

Provides workflow integration with the fal.ai platform for operations including:
- Model run lifecycle: run synchronously, submit to queue, poll status,
  fetch result, cancel a queued request
- Storage: initiate a CDN upload (presigned URL handshake)
- Platform management: model search, pricing, cost estimate, usage, analytics,
  list requests by endpoint, delete stored request payloads
- Webhook Trigger: fire when a queued job completes (success or error)

Authentication: API Key (custom `Authorization: Key <FAL_KEY>` scheme — NOT Bearer)
API Base URLs:
- Sync run:    https://fal.run
- Queue:       https://queue.fal.run
- Platform:    https://api.fal.ai/platform-apis/v1
- Storage:     https://rest.fal.ai
Documentation: https://docs.fal.ai

Inbound webhook deliveries are signed by fal with ED25519. We verify the
signature against fal's published JWKS at
https://rest.fal.ai/.well-known/jwks.json. The signed message is
`request_id \n user_id \n timestamp \n SHA-256(body)`.
"""

import base64
import hashlib
import json
import logging
import time
from typing import Dict, Any, Optional, Literal, Union, Annotated
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

FAL_RUN_BASE = "https://fal.run"
FAL_QUEUE_BASE = "https://queue.fal.run"
FAL_PLATFORM_BASE = "https://api.fal.ai/v1"
FAL_REST_BASE = "https://rest.fal.ai"
FAL_JWKS_URL = "https://rest.fal.ai/.well-known/jwks.json"

# Cache the JWKS so we don't fetch fal's public keys on every webhook delivery.
_JWKS_CACHE: Dict[str, Any] = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL_SECONDS = 24 * 60 * 60  # fal recommends caching up to 24h


# ============================================================================
# Credential Schema
# ============================================================================


class FalApiKeyCredential(BaseModel):
    """API Key credential for fal.ai."""

    credential_type: Literal["fal_api_key"] = Field(
        "fal_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your fal API key from the dashboard. Sent as 'Authorization: Key <key>'.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://fal.ai/dashboard/keys"}
    )


FalCredential = FalApiKeyCredential


# ============================================================================
# Operation Configs
# ============================================================================


class FalRunModelConfig(BaseModel):
    """Run a model endpoint synchronously and get the result inline."""

    operation: Literal["run_model"] = Field(
        "run_model",
        json_schema_extra={
            "const": "run_model",
            "ui:hidden": True,
            "x-category": "Model Run",
            "x-is-trigger": False,
            "x-display-name": "Run Model (Sync)",
        },
        title="Run Model (Sync)",
    )
    model_id: str = Field(
        ...,
        title="Model ID",
        description="The model endpoint slug, e.g. fal-ai/flux/dev or fal-ai/fast-sdxl",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "model_id",
                "placeholder": "Select or search a model...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a model slug",
            },
            "x-resource-type": "fal_model",
        },
    )
    subpath: Optional[str] = Field(
        None,
        title="Subpath",
        description="Optional extra path segment for endpoints that expose one",
    )
    input: str = Field(
        "{}",
        title="Input (JSON)",
        description="The model's JSON input payload (schema is per-model)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class FalSubmitQueueConfig(BaseModel):
    """Submit an async request to the fal queue (best for long-running jobs)."""

    operation: Literal["submit_queue"] = Field(
        "submit_queue",
        json_schema_extra={
            "const": "submit_queue",
            "ui:hidden": True,
            "x-category": "Model Run",
            "x-is-trigger": False,
            "x-display-name": "Submit to Queue",
        },
        title="Submit to Queue",
    )
    model_id: str = Field(
        ...,
        title="Model ID",
        description="The model endpoint slug, e.g. fal-ai/flux/dev",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "model_id",
                "placeholder": "Select or search a model...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a model slug",
            },
            "x-resource-type": "fal_model",
        },
    )
    subpath: Optional[str] = Field(
        None,
        title="Subpath",
        description="Optional extra path segment for endpoints that expose one",
    )
    input: str = Field(
        "{}",
        title="Input (JSON)",
        description="The model's JSON input payload (schema is per-model)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    webhook_url: Optional[str] = Field(
        None,
        title="Webhook URL",
        description="Optional URL fal POSTs the result to on completion (fal_webhook query param)",
    )


class FalGetStatusConfig(BaseModel):
    """Poll the status of a queued request."""

    operation: Literal["get_status"] = Field(
        "get_status",
        json_schema_extra={
            "const": "get_status",
            "ui:hidden": True,
            "x-category": "Model Run",
            "x-is-trigger": False,
            "x-display-name": "Get Request Status",
        },
        title="Get Request Status",
    )
    model_id: str = Field(
        ..., title="Model ID", description="The model endpoint slug the request was submitted to"
    )
    request_id: str = Field(
        ..., title="Request ID", description="The request_id returned when submitting to the queue"
    )
    logs: str = Field(
        "false",
        title="Include Logs",
        description="Include runner logs in the status response",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class FalGetResultConfig(BaseModel):
    """Fetch the completed result payload of a queued request."""

    operation: Literal["get_result"] = Field(
        "get_result",
        json_schema_extra={
            "const": "get_result",
            "ui:hidden": True,
            "x-category": "Model Run",
            "x-is-trigger": False,
            "x-display-name": "Get Request Result",
        },
        title="Get Request Result",
    )
    model_id: str = Field(
        ..., title="Model ID", description="The model endpoint slug the request was submitted to"
    )
    request_id: str = Field(
        ..., title="Request ID", description="The request_id of the completed request"
    )


class FalCancelRequestConfig(BaseModel):
    """Cancel a queued or in-progress request."""

    operation: Literal["cancel_request"] = Field(
        "cancel_request",
        json_schema_extra={
            "const": "cancel_request",
            "ui:hidden": True,
            "x-category": "Model Run",
            "x-is-trigger": False,
            "x-display-name": "Cancel Request",
        },
        title="Cancel Request",
    )
    model_id: str = Field(
        ..., title="Model ID", description="The model endpoint slug the request was submitted to"
    )
    request_id: str = Field(
        ..., title="Request ID", description="The request_id to cancel"
    )


class FalInitiateUploadConfig(BaseModel):
    """Initiate a file upload to fal's CDN; returns a presigned upload URL."""

    operation: Literal["initiate_upload"] = Field(
        "initiate_upload",
        json_schema_extra={
            "const": "initiate_upload",
            "ui:hidden": True,
            "x-category": "Storage",
            "x-is-trigger": False,
            "x-display-name": "Initiate File Upload",
        },
        title="Initiate File Upload",
    )
    content_type: str = Field(
        "application/octet-stream",
        title="Content Type",
        description="MIME type of the file you will upload (e.g. image/png)",
        json_schema_extra={"ui:placeholder": "e.g. image/png, video/mp4, application/pdf"},
    )
    file_name: Optional[str] = Field(
        None, title="File Name", description="Optional original file name"
    )


class FalSearchModelsConfig(BaseModel):
    """Search and list available model endpoints."""

    operation: Literal["search_models"] = Field(
        "search_models",
        json_schema_extra={
            "const": "search_models",
            "ui:hidden": True,
            "x-category": "Platform",
            "x-is-trigger": False,
            "x-display-name": "Search Models",
        },
        title="Search Models",
    )
    query: Optional[str] = Field(
        None, title="Query", description="Search term to filter models by name/capability"
    )
    limit: Optional[str] = Field(
        "20", title="Limit", description="Max number of models to return"
    )


class FalUsageConfig(BaseModel):
    """Retrieve granular usage line items for the account."""

    operation: Literal["get_usage"] = Field(
        "get_usage",
        json_schema_extra={
            "const": "get_usage",
            "ui:hidden": True,
            "x-category": "Platform",
            "x-is-trigger": False,
            "x-display-name": "Get Usage",
        },
        title="Get Usage",
    )
    start_date: Optional[str] = Field(
        None,
        title="Start Date",
        description="ISO 8601 lower bound for usage records",
        json_schema_extra={"ui:widget": "datetime", "ui:placeholder": "2026-01-01T00:00:00Z"},
    )
    end_date: Optional[str] = Field(
        None,
        title="End Date",
        description="ISO 8601 upper bound for usage records",
        json_schema_extra={"ui:widget": "datetime", "ui:placeholder": "2026-12-31T23:59:59Z"},
    )


class FalListRequestsConfig(BaseModel):
    """List recent requests for a specific model endpoint."""

    operation: Literal["list_requests"] = Field(
        "list_requests",
        json_schema_extra={
            "const": "list_requests",
            "ui:hidden": True,
            "x-category": "Platform",
            "x-is-trigger": False,
            "x-display-name": "List Requests by Endpoint",
        },
        title="List Requests by Endpoint",
    )
    model_id: str = Field(
        ..., title="Model ID", description="The model endpoint slug to list requests for"
    )
    limit: Optional[str] = Field(
        "20", title="Limit", description="Max number of requests to return"
    )


class FalListKeysConfig(BaseModel):
    """List all API keys for the account."""

    operation: Literal["list_keys"] = Field(
        "list_keys",
        json_schema_extra={
            "const": "list_keys",
            "ui:hidden": True,
            "x-category": "Keys",
            "x-is-trigger": False,
            "x-display-name": "List API Keys",
        },
        title="List API Keys",
    )
    limit: Optional[str] = Field(
        "20", title="Limit", description="Max number of keys to return",
        json_schema_extra={
            "ui:help": "Lists keys created via the API (POST /v1/keys). Your root API key used for authentication does not appear here.",
        },
    )


class FalCreateKeyConfig(BaseModel):
    """Create a new API key for the account."""

    operation: Literal["create_key"] = Field(
        "create_key",
        json_schema_extra={
            "const": "create_key",
            "ui:hidden": True,
            "x-category": "Keys",
            "x-is-trigger": False,
            "x-display-name": "Create API Key",
        },
        title="Create API Key",
    )
    alias: str = Field(
        ..., title="Alias", description="Human-readable label for the new key (required by fal)"
    )


class FalDeleteKeyConfig(BaseModel):
    """Delete an API key by its ID."""

    operation: Literal["delete_key"] = Field(
        "delete_key",
        json_schema_extra={
            "const": "delete_key",
            "ui:hidden": True,
            "x-category": "Keys",
            "x-is-trigger": False,
            "x-display-name": "Delete API Key",
        },
        title="Delete API Key",
    )
    key_id: str = Field(
        ..., title="Key ID", description="The ID of the key to delete"
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class FalJobCompletedTriggerConfig(BaseModel):
    """Fire the workflow when a queued fal job completes (success or error).

    fal posts the completion event to whatever URL is passed as the queue
    submit's `webhook_url`. Wire this trigger and paste its URL into the
    Submit to Queue operation's Webhook URL field.
    """

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
        description="Pass this URL as the webhook_url when submitting a job to fal's queue.",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


FalConfig = Annotated[
    Union[
        FalRunModelConfig,
        FalSubmitQueueConfig,
        FalGetStatusConfig,
        FalGetResultConfig,
        FalCancelRequestConfig,
        FalInitiateUploadConfig,
        FalSearchModelsConfig,
        FalUsageConfig,
        FalListRequestsConfig,
        FalListKeysConfig,
        FalCreateKeyConfig,
        FalDeleteKeyConfig,
        FalJobCompletedTriggerConfig,
    ],
    Discriminator("operation"),
]


class FalNodeConfig(NodeConfig[FalConfig, FalCredential]):
    """Full configuration for the fal node including credentials."""

    pass


# ============================================================================
# HTTP Request Helper
# ============================================================================


def _parse_json_input(raw: Optional[str], field: str = "input") -> Dict[str, Any]:
    """Parse a free-form JSON input string into a dict; raise on malformed JSON."""
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"{field} must be valid JSON: {e}")
    if not isinstance(parsed, dict):
        raise ValueError(f"{field} must be a JSON object")
    return parsed


async def _fal_request(
    api_key: str,
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated fal request and return a structured result.

    fal uses a custom `Authorization: Key <key>` scheme (NOT Bearer).
    """
    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json",
    }
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

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
                    if isinstance(err, dict):
                        message = (
                            err.get("detail")
                            or err.get("message")
                            or err.get("error")
                            or str(err)
                        )
                    else:
                        message = str(err)
                except Exception:
                    message = response.text
                if isinstance(message, (dict, list)):
                    message = json.dumps(message)
                logger.error(f"[FalNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204 or not response.content:
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
            logger.error(f"[FalNode] Request failed ({action_name}): {msg}")
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


class FalNode(WorkflowNode):
    """fal.ai model-inference automation node."""

    edit_examples = [
        "Generate an image with fal-ai/flux/dev from a text prompt",
        "Submit a long video generation job to the fal queue",
        "Poll the status of a queued fal request",
        "Fetch the result of a completed fal job",
        "Trigger a workflow when a queued fal job finishes",
    ]

    @classmethod
    def get_config_model(cls):
        return FalNodeConfig

    # ------------------------------------------------------------------
    # Webhook URL provisioning (trigger) — fal webhooks are per-submit-request,
    # so we only mint the inbound URL; the user pastes it into Submit to Queue.
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Dynamic options (model search)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        user_id: str,
        config_data: Dict[str, Any],
        credential_ids: Optional[Dict[str, str]] = None,
        pool=None,
    ) -> Dict[str, Any]:
        if field_name != "model_id":
            return {"options": []}
        from utils.credential_loader import load_credential

        credential_id = next((cid for cid in (credential_ids or {}).values() if cid), None)
        credential = await load_credential(pool, user_id, credential_id) if credential_id else None
        if not credential:
            return {"options": []}
        api_key = credential.get("api_key")
        result = await _fal_request(
            api_key,
            "GET",
            f"{FAL_PLATFORM_BASE}/models",
            params={"limit": "50"},
            action_name="search_models",
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        models = data if isinstance(data, list) else data.get("models") or data.get("items") or []
        options = []
        for m in models:
            if not isinstance(m, dict):
                continue
            slug = m.get("id") or m.get("endpoint_id") or m.get("slug") or m.get("model_id")
            if not slug:
                continue
            title = m.get("title") or m.get("name") or slug
            label = f"{title} ({slug})" if title != slug else str(slug)
            options.append({"label": label, "value": str(slug)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Webhook signature verification (ED25519 against fal's JWKS)
    # ------------------------------------------------------------------
    @classmethod
    def _get_jwks_keys(cls) -> list:
        """Fetch (and cache) fal's ED25519 public keys from the JWKS endpoint.

        Synchronous on purpose: ``verify_webhook_signature`` runs inside the
        webhook route's sync signature hook, which is itself called from a
        running event loop — an async fetch would deadlock there.
        """
        now = time.time()
        if _JWKS_CACHE["keys"] is not None and (now - _JWKS_CACHE["fetched_at"]) < _JWKS_TTL_SECONDS:
            return _JWKS_CACHE["keys"]
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(FAL_JWKS_URL)
            resp.raise_for_status()
            jwks = resp.json()
        keys = jwks.get("keys", []) if isinstance(jwks, dict) else []
        _JWKS_CACHE["keys"] = keys
        _JWKS_CACHE["fetched_at"] = now
        return keys

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify a fal ED25519 webhook signature.

        The signed message is:
            request_id \n user_id \n timestamp \n SHA-256(body)
        signed with one of fal's published ED25519 keys (JWKS). The signature
        header carries the hex-encoded signature.
        """
        request_id = headers.get("x-fal-webhook-request-id")
        user_id = headers.get("x-fal-webhook-user-id")
        timestamp = headers.get("x-fal-webhook-timestamp")
        signature_hex = headers.get("x-fal-webhook-signature")
        if not (request_id and user_id and timestamp and signature_hex):
            return False

        # Reject stale deliveries (fal recommends a ±5 min window).
        try:
            if abs(time.time() - float(timestamp)) > 300:
                return False
        except (TypeError, ValueError):
            return False

        body_hash = hashlib.sha256(body).hexdigest()
        message = "\n".join([request_id, user_id, timestamp, body_hash]).encode()

        try:
            signature = bytes.fromhex(signature_hex)
        except ValueError:
            return False

        keys = cls._get_jwks_keys()

        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        for key in keys:
            x = key.get("x")
            if not x:
                continue
            try:
                # JWKS encodes the raw public key as base64url (unpadded).
                pub_bytes = base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))
                public_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
                public_key.verify(signature, message)
                return True
            except (InvalidSignature, ValueError):
                continue
        return False

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, FalNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, FalJobCompletedTriggerConfig):
            return {
                "status": "success",
                "action": "on_job_completed",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your fal API key.")
        api_key = credentials.api_key

        handlers = {
            "run_model": self._run_model,
            "submit_queue": self._submit_queue,
            "get_status": self._get_status,
            "get_result": self._get_result,
            "cancel_request": self._cancel_request,
            "initiate_upload": self._initiate_upload,
            "search_models": self._search_models,
            "get_usage": self._get_usage,
            "list_requests": self._list_requests,
            "list_keys": self._list_keys,
            "create_key": self._create_key,
            "delete_key": self._delete_key,
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
    def _model_path(self, model_id: str, subpath: Optional[str]) -> str:
        path = model_id.strip().strip("/")
        if subpath:
            path = f"{path}/{subpath.strip().strip('/')}"
        return path

    async def _run_model(self, c: FalRunModelConfig, api_key: str) -> Dict[str, Any]:
        body = _parse_json_input(c.input)
        url = f"{FAL_RUN_BASE}/{self._model_path(c.model_id, c.subpath)}"
        return await _fal_request(api_key, "POST", url, json_body=body, action_name="run_model")

    async def _submit_queue(self, c: FalSubmitQueueConfig, api_key: str) -> Dict[str, Any]:
        body = _parse_json_input(c.input)
        url = f"{FAL_QUEUE_BASE}/{self._model_path(c.model_id, c.subpath)}"
        params = {"fal_webhook": c.webhook_url} if c.webhook_url else None
        return await _fal_request(
            api_key, "POST", url, params=params, json_body=body, action_name="submit_queue"
        )

    async def _get_status(self, c: FalGetStatusConfig, api_key: str) -> Dict[str, Any]:
        url = f"{FAL_QUEUE_BASE}/{c.model_id.strip().strip('/')}/requests/{c.request_id}/status"
        params = {"logs": "1"} if c.logs == "true" else None
        return await _fal_request(api_key, "POST", url, params=params, action_name="get_status")

    async def _get_result(self, c: FalGetResultConfig, api_key: str) -> Dict[str, Any]:
        url = f"{FAL_QUEUE_BASE}/{c.model_id.strip().strip('/')}/requests/{c.request_id}"
        return await _fal_request(api_key, "POST", url, action_name="get_result")

    async def _cancel_request(self, c: FalCancelRequestConfig, api_key: str) -> Dict[str, Any]:
        url = f"{FAL_QUEUE_BASE}/{c.model_id.strip().strip('/')}/requests/{c.request_id}/cancel"
        return await _fal_request(api_key, "POST", url, action_name="cancel_request")

    async def _initiate_upload(self, c: FalInitiateUploadConfig, api_key: str) -> Dict[str, Any]:
        url = f"{FAL_REST_BASE}/storage/upload/initiate"
        body = {"content_type": c.content_type, "file_name": c.file_name}
        body = {k: v for k, v in body.items() if v is not None}
        return await _fal_request(
            api_key,
            "POST",
            url,
            params={"storage_type": "fal-cdn-v3"},
            json_body=body,
            action_name="initiate_upload",
        )

    async def _search_models(self, c: FalSearchModelsConfig, api_key: str) -> Dict[str, Any]:
        params = {"query": c.query, "limit": c.limit}
        return await _fal_request(
            api_key, "GET", f"{FAL_PLATFORM_BASE}/models", params=params, action_name="search_models"
        )

    async def _get_usage(self, c: FalUsageConfig, api_key: str) -> Dict[str, Any]:
        params = {"start_date": c.start_date, "end_date": c.end_date}
        return await _fal_request(
            api_key, "GET", f"{FAL_PLATFORM_BASE}/models/usage", params=params,
            action_name="get_usage",
        )

    async def _list_requests(self, c: FalListRequestsConfig, api_key: str) -> Dict[str, Any]:
        params = {"endpoint_id": c.model_id, "limit": c.limit}
        return await _fal_request(
            api_key, "GET", f"{FAL_PLATFORM_BASE}/models/requests/by-endpoint", params=params,
            action_name="list_requests",
        )

    async def _list_keys(self, c: FalListKeysConfig, api_key: str) -> Dict[str, Any]:
        return await _fal_request(
            api_key, "GET", f"{FAL_PLATFORM_BASE}/keys",
            params={"limit": c.limit}, action_name="list_keys",
        )

    async def _create_key(self, c: FalCreateKeyConfig, api_key: str) -> Dict[str, Any]:
        if not c.alias or not c.alias.strip():
            raise ValueError("Alias is required to create a fal API key.")
        body = {"alias": c.alias.strip()}
        return await _fal_request(
            api_key, "POST", f"{FAL_PLATFORM_BASE}/keys",
            json_body=body, action_name="create_key",
        )

    async def _delete_key(self, c: FalDeleteKeyConfig, api_key: str) -> Dict[str, Any]:
        return await _fal_request(
            api_key, "DELETE", f"{FAL_PLATFORM_BASE}/keys/{c.key_id}",
            action_name="delete_key",
        )
