"""
Webhook HTTP routes for receiving external webhook calls.

When a webhook is received:
1. Look up webhook config from database
2. Trigger workflow execution using WorkflowExecutionHandler with caller_user_id
3. Execution events are broadcast via the workflow relay to connected viewers

For form nodes (interface-form; legacy trigger-form-input):
- GET requests render an HTML form based on the node's field configuration
- POST requests parse form data and trigger the workflow
"""

import base64
import hmac
import hashlib
import inspect
import json
import logging
import uuid as uuid_module
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
import jwt
from pydantic import BaseModel

from utils.async_helpers import spawn
from utils.webhook_delivery import get_webhook_base_url
from utils.database_pool import get_native_pool
from utils.shopify_routes import compliance_router as shopify_compliance_router
from wss.receiver.client_events import WorkflowExecuteRequest
from wss.handlers.workflow_execution_handler import WorkflowExecutionResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhooks"])

# Shopify's mandatory privacy callbacks share the webhook worker and its
# single-origin front door. Keeping the provider route under this router also
# ensures local development mounts the exact same endpoint on the main app.
router.include_router(shopify_compliance_router)


class WebhookResponse(BaseModel):
    success: bool
    message: str
    execution_id: Optional[str] = None


class WebhookURLResponse(BaseModel):
    url: str
    webhook_id: str


# ============================================================================
# Form Input HTML Rendering
# ============================================================================

def _is_node_disabled(node: dict) -> bool:
    """
    Check if a node is disabled.

    Checks both node-level and config-level disabled flags since the disabled
    state can be stored at either location depending on how it was set.

    Args:
        node: The workflow node dict

    Returns:
        True if the node is disabled, False otherwise
    """
    node_disabled = node.get("disabled", False)
    config_disabled = _node_cfg(node).get("disabled", False)
    return node_disabled or config_disabled


def _get_form_node_config(workflow_config: dict, node_id: str) -> Optional[Dict[str, Any]]:
    """Get the form input node's inner config (fields, description) from workflow config.

    Normalizes `fields` to a list: AI-builder/MCP write paths may store it as a
    JSON-encoded string, which this read path bypasses the node's Pydantic model
    and so would otherwise hand straight to the renderer (iterating a string ->
    AttributeError -> 500).
    """
    from nodes.core.registry import resolve_node_type
    from nodes.interface.form_node import parse_form_fields
    nodes = workflow_config.get("nodes", [])
    for node in nodes:
        if node.get("id") == node_id and resolve_node_type(node.get("type")) == "interface-form":
            # Node structure: node.config.config.fields (outer config wraps inner config)
            outer_config = _node_cfg(node)
            inner = outer_config.get("config", outer_config)  # Handle both nested and flat
            if isinstance(inner, dict) and "fields" in inner:
                return {**inner, "fields": parse_form_fields(inner.get("fields"))}
            return inner
    return None



def _node_cfg(node: Any) -> Dict[str, Any]:
    """A node's config dict, tolerating malformed shapes. Transient saves have
    carried a list-shaped config; a delivery path must skip a malformed node
    loudly, never take down every webhook in the workflow."""
    config = node.get("config") if isinstance(node, dict) else None
    if isinstance(config, dict):
        return config
    if config is not None:
        logger.warning(
            f"[WEBHOOK] Node {node.get('id') if isinstance(node, dict) else '?'} has "
            f"non-dict config ({type(config).__name__}) — treating as empty"
        )
    return {}

def _normalize_header_map(headers: dict) -> Dict[str, str]:
    return {str(k).lower(): str(v) for k, v in (headers or {}).items()}


def _constant_time_eq(a: str, b: str) -> bool:
    """Constant-time string compare that tolerates non-ASCII.

    hmac.compare_digest raises TypeError on str containing non-ASCII chars, so
    compare the UTF-8 byte encodings instead — otherwise a non-ASCII credential
    or header value would crash auth with a 500 instead of failing closed.
    """
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


async def _claim_google_watch_delivery(
    workflow_id: str,
    node_id: str,
    trigger_node: Optional[dict],
    payload: Dict[str, Any],
) -> bool:
    """Return False when this Google watch delivery is a duplicate/stale wake-up.

    Google watch notifications include a monotonically increasing
    ``x-goog-message-number`` per watched resource. Claiming the newest seen
    number before enqueueing the workflow prevents redeliveries from creating
    extra execution rows. The per-node execute path still keeps its own
    processed-state lock to serialize adjacent wake-ups that legitimately make
    it through with newer message numbers.
    """
    if not trigger_node:
        return True

    node_type = trigger_node.get("type")
    if node_type not in {"automation-google-drive", "automation-google-calendar"}:
        return True

    headers = ((payload.get("_webhook") or {}).get("headers") or {})
    raw_message_number = headers.get("x-goog-message-number")
    resource_id = headers.get("x-goog-resource-id")
    # Dedup identity is the CHANNEL, not the resource. x-goog-message-number is
    # monotonic *per channel* and restarts for each new channel, while a single
    # resource_id is shared by every channel watching the same Drive changes
    # feed. Re-registration (each workflow save) mints a fresh channel whose low
    # message numbers were being rejected as "stale" against the previous
    # channel's high-water mark — the root cause of flaky, intermittent fires.
    channel_id = headers.get("x-goog-channel-id")
    if raw_message_number is None or not channel_id:
        return True

    try:
        message_number = int(raw_message_number)
    except (TypeError, ValueError):
        logger.warning(
            "[WEBHOOK] Invalid x-goog-message-number for %s/%s: %r",
            workflow_id,
            node_id,
            raw_message_number,
        )
        return True

    pool = get_native_pool()
    now = datetime.now(timezone.utc)
    previous = await pool.fetchrow(
        """
        SELECT
            state->>'last_google_enqueued_resource_id' AS resource_id,
            state->>'last_google_enqueued_at' AS enqueued_at
        FROM workflow_node_state
        WHERE workflow_id = $1 AND node_id = $2
        """,
        uuid_module.UUID(workflow_id),
        node_id,
    )
    if previous and previous.get("resource_id") == resource_id and previous.get("enqueued_at"):
        try:
            previous_at = datetime.fromisoformat(previous["enqueued_at"])
        except ValueError:
            previous_at = None
        if previous_at and (now - previous_at).total_seconds() < 10:
            # Bound to runs started recently: a genuinely active run that could
            # emit burst redeliveries began seconds ago. Stale 'running' rows
            # (backend killed mid-run) would otherwise coalesce away every
            # delivery within 10s of the last — a flaky-trigger source.
            running_row = await pool.fetchrow(
                """
                SELECT 1
                FROM workflow_executions
                WHERE workflow_id = $1 AND status = 'running'
                  AND started_at > NOW() - INTERVAL '2 minutes'
                LIMIT 1
                """,
                uuid_module.UUID(workflow_id),
            )
            if running_row:
                logger.info(
                    "[WEBHOOK] Coalescing Google watch burst for %s/%s: resource=%s message_number=%s",
                    workflow_id,
                    node_id,
                    resource_id,
                    message_number,
                )
                return False

    row = await pool.fetchrow(
        """
        INSERT INTO workflow_node_state (workflow_id, node_id, state, updated_at)
        VALUES (
            $1,
            $2,
            jsonb_build_object(
                'last_google_enqueued_message_number', $3::bigint,
                'last_google_enqueued_resource_id', $4::text,
                'last_google_enqueued_at', $5::text,
                'last_google_enqueued_channel_id', $6::text
            ),
            NOW()
        )
        ON CONFLICT (workflow_id, node_id) DO UPDATE
        SET state = jsonb_set(
                jsonb_set(
                    jsonb_set(
                        jsonb_set(
                            COALESCE(workflow_node_state.state, '{}'::jsonb),
                            '{last_google_enqueued_message_number}',
                            to_jsonb($3::bigint),
                            true
                        ),
                        '{last_google_enqueued_resource_id}',
                        to_jsonb($4::text),
                        true
                    ),
                    '{last_google_enqueued_at}',
                    to_jsonb($5::text),
                    true
                ),
                '{last_google_enqueued_channel_id}',
                to_jsonb($6::text),
                true
            ),
            updated_at = NOW()
        WHERE COALESCE(workflow_node_state.state->>'last_google_enqueued_channel_id', '') <> $6
           OR COALESCE(
                NULLIF(workflow_node_state.state->>'last_google_enqueued_message_number', '')::bigint,
                -1
           ) < $3
        RETURNING 1
        """,
        uuid_module.UUID(workflow_id),
        node_id,
        message_number,
        resource_id,
        now.isoformat(),
        channel_id,
    )
    if row:
        return True

    logger.info(
        "[WEBHOOK] Skipping duplicate/stale Google watch delivery for %s/%s: resource=%s message_number=%s",
        workflow_id,
        node_id,
        resource_id,
        message_number,
    )
    return False


def _is_google_watch_handshake(payload: Dict[str, Any]) -> bool:
    """True for Google's initial ``sync`` watch message.

    Google posts ``X-Goog-Resource-State: sync`` once when a channel is first
    created — a handshake that carries no change. It commonly arrives in the
    narrow window between webhook creation and the node config being persisted,
    where the node-by-webhook_id lookup fails and the orphan-cleanup path would
    otherwise delete the brand-new webhook (breaking watch-channel registration
    with an FK violation). It must never fire a workflow either.
    """
    headers = ((payload.get("_webhook") or {}).get("headers") or {})
    state = headers.get("x-goog-resource-state") or headers.get("X-Goog-Resource-State")
    return state == "sync"


def _validate_webhook_request_settings(
    trigger_node: Optional[dict],
    *,
    method: str,
    headers: dict,
) -> None:
    """Validate webhook method/auth settings stored on the trigger node."""
    if not trigger_node:
        return

    node_config = trigger_node.get("config", {}) or {}
    expected_method = str(node_config.get("http_method") or "").upper()
    if expected_method and method.upper() != expected_method:
        raise HTTPException(status_code=405, detail=f"Webhook only accepts {expected_method}")

    auth_mode = str(node_config.get("authentication") or "none").lower()
    if auth_mode in ("", "none"):
        return

    lower_headers = _normalize_header_map(headers)

    if auth_mode == "basic":
        expected_username = str(node_config.get("basic_auth_username") or "")
        expected_password = str(node_config.get("basic_auth_password") or "")
        auth_header = lower_headers.get("authorization", "")
        if not auth_header.lower().startswith("basic "):
            raise HTTPException(
                status_code=401,
                detail="Missing Basic Auth credentials",
                headers={"WWW-Authenticate": 'Basic realm="Webhook"'},
            )
        try:
            decoded = base64.b64decode(auth_header.split(" ", 1)[1]).decode("utf-8")
            username, password = decoded.split(":", 1)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid Basic Auth credentials") from None
        if not (_constant_time_eq(username, expected_username) and _constant_time_eq(password, expected_password)):
            raise HTTPException(status_code=401, detail="Invalid Basic Auth credentials")
        return

    if auth_mode == "header":
        header_name = str(node_config.get("header_auth_name") or "").lower()
        expected_value = str(node_config.get("header_auth_value") or "")
        if not header_name:
            raise HTTPException(status_code=500, detail="Webhook header auth is not configured")
        actual_value = lower_headers.get(header_name)
        if actual_value is None or not _constant_time_eq(actual_value, expected_value):
            raise HTTPException(status_code=401, detail="Invalid webhook header authentication")
        return

    if auth_mode == "jwt":
        header_name = str(node_config.get("jwt_auth_header") or "authorization").lower()
        secret = str(node_config.get("jwt_auth_secret") or "")
        if not secret:
            raise HTTPException(status_code=500, detail="Webhook JWT auth is not configured")
        token_header = lower_headers.get(header_name, "")
        token = token_header.split(" ", 1)[1] if token_header.lower().startswith("bearer ") else token_header
        if not token:
            raise HTTPException(status_code=401, detail="Missing JWT")
        try:
            jwt.decode(token, secret, algorithms=["HS256"])
        except jwt.PyJWTError:
            raise HTTPException(status_code=401, detail="Invalid JWT") from None
        return

    raise HTTPException(status_code=500, detail=f"Unsupported webhook authentication mode: {auth_mode}")


def _get_webhook_response_mode(trigger_node: Optional[dict]) -> str:
    node_config = (trigger_node or {}).get("config", {}) or {}
    response_mode = str(node_config.get("respond") or "immediately").lower()
    if response_mode == "last_node":
        return response_mode
    if response_mode != "immediately":
        logger.warning("[WEBHOOK] Unsupported response mode '%s'; defaulting to immediately", response_mode)
    return "immediately"


def _json_output_response(output: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(output), status_code=status_code)


def _relay_response_payload(
    *,
    status_code: int,
    body: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return {
        "status": status_code,
        "headers": {str(key): str(value) for key, value in (headers or {}).items()},
        "body": body,
    }


def _json_relay_response(content: Any, status_code: int = 200) -> Dict[str, Any]:
    return _relay_response_payload(
        status_code=status_code,
        body=json.dumps(jsonable_encoder(content)),
        headers={"content-type": "application/json"},
    )


def _response_to_relay_payload(response: Response) -> Dict[str, Any]:
    body = response.body or b""
    if not isinstance(body, (bytes, bytearray)):
        body = str(body).encode("utf-8")
    headers = {
        str(key): str(value)
        for key, value in response.headers.items()
        if str(key).lower() != "content-length"
    }
    return _relay_response_payload(
        status_code=response.status_code,
        body=body.decode("utf-8", errors="replace"),
        headers=headers,
    )


_RESPONSE_CONTRACT_KEYS = {"status", "headers", "body"}


def _shaped_response_from_output(output: Any) -> Optional[Response]:
    """The terminal node's HTTP response contract for `respond: last_node`.

    A terminal node shapes the response by producing `{status[, headers][,
    body]}` (int status): str body → that body verbatim (text/html unless
    headers say otherwise), any other body → JSON, no body → empty. Serverless
    envelopes are unwrapped to the function's return value first, and a bare
    string return serves as an HTML page. Anything else returns None and falls
    through to the raw JSON dump — before this contract existed, the raw node
    envelope ({"type": "serverless_function", "result": {...}, "stdout": ...})
    WAS the response body, so no webhook could serve a real REST payload or a
    web page (2026-08-14).
    """
    candidate = output
    from_serverless = (
        isinstance(candidate, dict)
        and candidate.get("type") == "serverless_function"
        and candidate.get("status") == "completed"
        and "result" in candidate
    )
    if from_serverless:
        candidate = candidate["result"]
        if isinstance(candidate, str):
            return Response(content=candidate, status_code=200, media_type="text/html")

    if not isinstance(candidate, dict):
        return None
    if "status" not in candidate or not set(candidate) <= _RESPONSE_CONTRACT_KEYS:
        return None
    status = candidate["status"]
    if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
        return None
    headers = candidate.get("headers")
    if headers is not None and not isinstance(headers, dict):
        return None
    header_map = {str(k): str(v) for k, v in (headers or {}).items()}

    body = candidate.get("body")
    if body is None:
        return Response(status_code=status, headers=header_map)
    if isinstance(body, str):
        # Explicit content-type in headers wins (starlette only appends
        # media_type when the header is absent).
        return Response(content=body, status_code=status, headers=header_map, media_type="text/html")
    return JSONResponse(content=jsonable_encoder(body), status_code=status, headers=header_map)


def _response_from_execution_result(
    trigger_node: dict,
    result: WorkflowExecutionResult,
) -> Response:
    if result.suspended:
        raise HTTPException(status_code=409, detail="Webhook workflow paused before it could return a response")
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error or "Webhook workflow execution failed")

    response_mode = _get_webhook_response_mode(trigger_node)
    if response_mode == "last_node":
        last_output_node_id = result.last_output_node_id
        if not last_output_node_id or last_output_node_id not in result.node_outputs:
            # Workflow succeeded but produced no terminal output (e.g. every
            # downstream node was skipped/disabled). Acknowledge instead of 500.
            logger.info("[WEBHOOK] last_node response requested but no final node output; returning ack")
            return _json_output_response(
                WebhookResponse(
                    success=True,
                    message="Webhook received and workflow triggered",
                    execution_id=result.execution_id,
                ).model_dump()
            )
        output = result.node_outputs[last_output_node_id]
        shaped = _shaped_response_from_output(output)
        if shaped is not None:
            return shaped
        return _json_output_response(output)

    raise HTTPException(status_code=500, detail=f"Unsupported webhook response mode: {response_mode}")


class _FormUploadError(Exception):
    """Raised when a form file upload can't be persisted (size cap exceeded,
    R2 PUT failed, or resource row creation failed). Surfaced to the submitter
    as an HTML error — never swallowed."""


async def _persist_form_upload(
    *,
    upload: Any,
    owner_id: str,
    workflow_id: str,
    node_id: Optional[str],
) -> Optional[Dict[str, str]]:
    """Persist a form-submitted file to R2 + a workflow_resources row.

    ``upload`` is a Starlette ``UploadFile``. Returns ``{"url", "filename"}``
    (the permanent public download URL + original filename) or ``None`` when
    the file input was left empty. Raises ``_FormUploadError`` on cap breach
    or any R2/DB failure — no silent fallbacks.
    """
    from wss.handlers.resource_handler import MAX_UPLOAD_SIZE_BYTES, RESOURCE_BUCKET
    from utils.r2_cloudflare import upload_bytes_to_r2_async, get_public_download_url
    from repositories.resources import ResourceRepo

    filename = getattr(upload, "filename", None) or "upload"
    content_type = getattr(upload, "content_type", None) or "application/octet-stream"

    data = await upload.read()
    if not data:
        return None

    if len(data) > MAX_UPLOAD_SIZE_BYTES:
        raise _FormUploadError(
            f"File too large. Maximum size is {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB"
        )

    pool = get_native_pool()
    repo = ResourceRepo(pool)
    try:
        org_id = await repo.get_workflow_organization_id(workflow_id)
        row = await repo.create_resource(
            owner_id=owner_id,
            organization_id=org_id,
            workflow_id=workflow_id,
            node_id=node_id,
            resource_type="file",
            name=filename,
            mime_type=content_type,
            size_bytes=len(data),
            storage_ref=None,
            metadata={},
        )
    except Exception as e:
        logger.error(f"[WEBHOOK] Failed to create resource row for form upload: {e}", exc_info=True)
        raise _FormUploadError("Failed to store uploaded file")

    resource_id = str(row["id"])
    storage_ref = f"{owner_id}/{workflow_id}/{resource_id}/{filename}"

    try:
        await upload_bytes_to_r2_async(
            bucket=RESOURCE_BUCKET,
            key=storage_ref,
            body=data,
            content_type=content_type,
        )
        await repo.update_storage_ref(resource_id, storage_ref, content_type)
    except Exception as e:
        logger.error(f"[WEBHOOK] Failed to upload form file to R2 ({storage_ref}): {e}", exc_info=True)
        # Roll back the orphaned row so it doesn't dangle without a blob.
        try:
            await repo.delete_resource(resource_id)
        except Exception:
            logger.error(f"[WEBHOOK] Failed to clean up orphaned resource {resource_id}", exc_info=True)
        raise _FormUploadError("Failed to upload file")

    return {"url": get_public_download_url(storage_ref), "filename": filename}


def _render_form_html(
    fields: List[Dict[str, Any]],
    form_title: str = "",
    form_description: str = "",
    webhook_id: str = "",
    error_message: str = "",
    success_message: str = "",
) -> str:
    """
    Render a minimal HTML form. Pure black, no borders, clean type.
    Text fields auto-expand with shift+enter.
    """
    # A file field requires multipart/form-data on the form tag so the
    # browser sends the raw bytes rather than just the filename.
    has_file_field = any(f.get("type") == "file" for f in fields)
    form_enctype_attr = ' enctype="multipart/form-data"' if has_file_field else ""

    # Build form fields HTML
    fields_html = ""
    for field in fields:
        field_name = field.get("name", "")
        field_type = field.get("type", "string")
        field_label = field.get("label", field_name)
        field_desc = field.get("description", "")
        required = field.get("required", False)
        options = field.get("options") or []

        required_attr = "required" if required else ""
        optional_marker = "" if required else '<span class="optional">optional</span>'

        # Build input based on type
        if field_type == "file":
            accept = field.get("accept")
            accept_attr = f' accept="{accept}"' if accept else ""
            input_html = f'<input type="file" name="{field_name}" id="{field_name}" {required_attr}{accept_attr}>'
        elif field_type == "select" and options:
            options_html = "".join(f'<option value="{opt}">{opt}</option>' for opt in options)
            input_html = f'''<select name="{field_name}" id="{field_name}" {required_attr}>
                <option value="">Select</option>
                {options_html}
            </select>'''
        elif field_type == "boolean":
            opt_text = " (optional)" if not required else ""
            input_html = f'''<label class="checkbox">
                <input type="checkbox" name="{field_name}" id="{field_name}" value="true">
                <span>{field_label}{opt_text}</span>
            </label>'''
        elif field_type == "number":
            input_html = f'<input type="number" name="{field_name}" id="{field_name}" placeholder="0" {required_attr} step="any">'
        elif field_type in ("object", "array"):
            input_html = f'<textarea name="{field_name}" id="{field_name}" placeholder="{{...}}" rows="3" {required_attr}></textarea>'
        else:
            # String fields use auto-expanding textarea
            input_html = f'<textarea name="{field_name}" id="{field_name}" rows="1" class="auto-expand" {required_attr}></textarea>'

        # Build field wrapper
        if field_type == "boolean":
            label_html = ""
        else:
            label_html = f'<label for="{field_name}">{field_label} {optional_marker}</label>'

        hint_html = f'<p class="hint">{field_desc}</p>' if field_desc else ""

        fields_html += f'''<div class="field">
            {label_html}
            {input_html}
            {hint_html}
        </div>'''

    # Message display
    message_html = ""
    if error_message:
        message_html = f'<p class="error">{error_message}</p>'
    elif success_message:
        message_html = f'<p class="success">{success_message}</p>'

    # Title and description
    display_title = form_title if form_title else "Submit"
    desc_html = f'<p class="desc">{form_description}</p>' if form_description else ""
    # Add extra margin to h1 when there's no description
    header_class = "no-desc" if not form_description else ""

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{display_title}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}

        html {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            -webkit-font-smoothing: antialiased;
        }}

        body {{
            background: #000;
            color: #fff;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 48px 24px;
        }}

        .container {{ width: 100%; max-width: 480px; }}

        h1 {{
            font-size: 2.5rem;
            font-weight: 600;
            letter-spacing: -0.04em;
            margin-bottom: 16px;
        }}

        h1.no-desc {{
            margin-bottom: 48px;
        }}

        .desc {{
            font-size: 1.25rem;
            color: rgba(255,255,255,0.5);
            line-height: 1.5;
            margin-bottom: 56px;
        }}

        .field {{ margin-bottom: 40px; }}

        label {{
            display: block;
            font-size: 1rem;
            color: rgba(255,255,255,0.5);
            margin-bottom: 12px;
        }}

        .optional {{
            color: rgba(255,255,255,0.25);
            font-size: 0.875rem;
            margin-left: 8px;
        }}

        input, select, textarea {{
            width: 100%;
            background: transparent;
            border: none;
            border-bottom: 1px solid rgba(255,255,255,0.2);
            border-radius: 0;
            padding: 16px 0;
            font-family: inherit;
            font-size: 1.25rem;
            color: #fff;
            outline: none;
            transition: border-color 0.2s;
        }}

        input::placeholder, textarea::placeholder {{ color: rgba(255,255,255,0.25); }}

        input:focus, select:focus, textarea:focus {{
            border-bottom-color: #fff;
        }}

        select {{
            appearance: none;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='rgba(255,255,255,0.5)' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 0 center;
            padding-right: 28px;
            cursor: pointer;
        }}

        select option {{ background: #000; color: #fff; }}

        textarea {{
            resize: none;
            line-height: 1.5;
            overflow: hidden;
        }}

        textarea.auto-expand {{
            min-height: 0;
        }}

        textarea:not(.auto-expand) {{
            min-height: 120px;
            overflow: auto;
            resize: vertical;
        }}

        .hint {{
            font-size: 0.875rem;
            color: rgba(255,255,255,0.35);
            margin-top: 12px;
        }}

        .checkbox {{
            display: flex;
            align-items: center;
            gap: 16px;
            cursor: pointer;
            padding: 16px 0;
        }}

        .checkbox input {{
            width: 24px;
            height: 24px;
            padding: 0;
            border: none;
            accent-color: #fff;
            cursor: pointer;
        }}

        .checkbox span {{
            font-size: 1.25rem;
            color: rgba(255,255,255,0.8);
        }}

        button {{
            width: 100%;
            background: #fff;
            color: #000;
            border: none;
            border-radius: 12px;
            padding: 20px 32px;
            font-family: inherit;
            font-size: 1.125rem;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s;
            margin-top: 16px;
        }}

        button:hover {{ opacity: 0.9; }}

        .error {{ color: #ff6b6b; font-size: 1rem; margin-bottom: 32px; }}
        .success {{ color: #69db7c; font-size: 1rem; margin-bottom: 32px; }}

        .footer {{
            text-align: center;
            margin-top: 64px;
            font-size: 0.875rem;
            color: rgba(255,255,255,0.25);
        }}

        .footer a {{
            color: rgba(255,255,255,0.4);
            text-decoration: none;
        }}

        .footer a:hover {{ color: rgba(255,255,255,0.6); }}

        input:-webkit-autofill {{
            -webkit-box-shadow: 0 0 0 1000px #000 inset !important;
            -webkit-text-fill-color: #fff !important;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1 class="{header_class}">{display_title}</h1>
        {desc_html}
        {message_html}
        <form method="POST"{form_enctype_attr}>
            {fields_html}
            <button type="submit">Submit</button>
        </form>
        <p class="footer">Powered by <a href="https://noclick.com" target="_blank">NoClick</a></p>
    </div>
    <script>
        // Auto-expand textareas on input
        document.querySelectorAll('textarea.auto-expand').forEach(el => {{
            const resize = () => {{
                el.style.height = 'auto';
                el.style.height = el.scrollHeight + 'px';
            }};
            el.addEventListener('input', resize);
            // Initial resize in case of pre-filled content
            resize();
        }});
    </script>
</body>
</html>'''


def _render_success_html(message: str = "Form submitted successfully!") -> str:
    """Render a minimal success page."""
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Success</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}

        html {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            -webkit-font-smoothing: antialiased;
        }}

        body {{
            background: #000;
            color: #fff;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 48px 24px;
            text-align: center;
        }}

        .container {{ width: 100%; max-width: 480px; }}

        .icon {{
            font-size: 4rem;
            margin-bottom: 32px;
        }}

        h1 {{
            font-size: 2.5rem;
            font-weight: 600;
            letter-spacing: -0.04em;
            margin-bottom: 16px;
        }}

        p {{
            font-size: 1.25rem;
            color: rgba(255,255,255,0.5);
            line-height: 1.5;
        }}

        .footer {{
            margin-top: 64px;
            font-size: 0.875rem;
            color: rgba(255,255,255,0.25);
        }}

        .footer a {{
            color: rgba(255,255,255,0.4);
            text-decoration: none;
        }}

        .footer a:hover {{ color: rgba(255,255,255,0.6); }}
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">✓</div>
        <h1>Submitted</h1>
        <p>{message}</p>
        <p class="footer">Powered by <a href="https://noclick.com" target="_blank">NoClick</a></p>
    </div>
</body>
</html>'''


def _render_error_html(message: str = "An error occurred") -> str:
    """Render a minimal error page."""
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Error</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}

        html {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            -webkit-font-smoothing: antialiased;
        }}

        body {{
            background: #000;
            color: #fff;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 48px 24px;
            text-align: center;
        }}

        .container {{ width: 100%; max-width: 480px; }}

        .icon {{
            font-size: 4rem;
            margin-bottom: 32px;
        }}

        h1 {{
            font-size: 2.5rem;
            font-weight: 600;
            letter-spacing: -0.04em;
            margin-bottom: 16px;
        }}

        p {{
            font-size: 1.25rem;
            color: rgba(255,255,255,0.5);
            line-height: 1.5;
        }}

        .footer {{
            margin-top: 64px;
            font-size: 0.875rem;
            color: rgba(255,255,255,0.25);
        }}

        .footer a {{
            color: rgba(255,255,255,0.4);
            text-decoration: none;
        }}

        .footer a:hover {{ color: rgba(255,255,255,0.6); }}
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">✗</div>
        <h1>Something went wrong</h1>
        <p>{message}</p>
        <p class="footer">Powered by <a href="https://noclick.com" target="_blank">NoClick</a></p>
    </div>
</body>
</html>'''


# ============================================================================
# Webhook Configuration
# ============================================================================

async def get_webhook_config(webhook_id: str) -> Optional[dict]:
    """Look up webhook configuration from database using the connection pool.

    Returns ``None`` ONLY when the webhook is *definitively* absent — an invalid
    id, or a successful query that found no matching row. A DB failure (timeout,
    connection error) RAISES instead of returning ``None``: callers must not treat
    a transient lookup failure as "the webhook is gone" and react destructively
    (e.g. deleting the cron schedule). Conflating the two previously turned a DB
    timeout into permanent schedule deletion.
    """
    try:
        webhook_uuid = uuid_module.UUID(webhook_id)
    except ValueError:
        logger.error(f"[WEBHOOK] Invalid webhook_id format: {webhook_id}")
        return None

    row = await get_native_pool().fetchrow(
        """
        SELECT w.id, w.user_id, w.workflow_id, w.node_id, w.secret, w.is_active,
               wf.workflow as workflow_config, wf.updated_at as workflow_updated_at
        FROM webhooks w
        JOIN workflows wf ON w.workflow_id = wf.id
        WHERE w.id = $1 AND wf.deleted_at IS NULL
        """,
        webhook_uuid
    )
    return dict(row) if row else None


def update_webhook_stats(webhook_id: str):
    """Update webhook trigger stats using the connection pool (fire-and-forget)."""
    try:
        webhook_uuid = uuid_module.UUID(webhook_id)
    except ValueError:
        logger.error(f"[WEBHOOK] Invalid webhook_id format for stats update: {webhook_id}")
        return

    try:
        # Deliberate fire-and-forget: stats update must not delay webhook delivery.
        spawn(get_native_pool().execute(
            """
            UPDATE webhooks
            SET last_triggered_at = NOW(),
                trigger_count = trigger_count + 1
            WHERE id = $1
            """,
            webhook_uuid
        ), name=f"webhook-stats:{webhook_id}")
    except Exception as e:
        logger.error(f"[WEBHOOK] Failed to update stats: {e}")


def _is_stale_schedule_tick(headers: dict, trigger_node: dict, is_alarm: bool) -> bool:
    """A cron-scheduler tick landing on a node whose CURRENT operation is not a
    trigger — a schedule that survived an operation change (or was provisioned
    against the wrong operation) and would run the node's action op on every
    tick. The workflow config loaded successfully and shows a non-trigger op,
    so this is a definitive signal: the caller may prune the schedule + webhook.
    """
    if is_alarm:
        return False
    if not (headers.get("x-cron-schedule-id") or headers.get("X-Cron-Schedule-Id")):
        return False
    node_type = trigger_node.get("type") or ""
    if node_type.startswith("trigger-"):
        return False
    from nodes.agent.node_op_tools import is_trigger_operation

    operation = (trigger_node.get("config") or {}).get("operation")
    return not is_trigger_operation(node_type, operation)


def _schedule_tick_config_error(
    headers: dict, trigger_node: dict, is_alarm: bool
) -> Optional[str]:
    """The trigger a cron-scheduler tick landed on has a SAVED config that
    won't parse — dispatching can only mint an error run. Returns the
    validation error, or ``None`` when the config is fine or this isn't a
    schedule tick: non-schedule deliveries (real provider events) always
    dispatch, since an error run is the only record of a lost event.

    The caller decides loud vs quiet with ``_trigger_ever_ran``: a trigger
    that never ran cleanly is still being set up (registration runs from the
    config panel's UNSAVED context, so a tick can land before the debounced
    graph save carries the required fields — 2026-08-04 Google Forms setup) →
    skip quietly, the next tick retries against a fresher save. A trigger
    that HAS run cleanly and now fails validation is a real regression (e.g.
    an AI edit broke it) → dispatch, so the failure stays visible.
    """
    if is_alarm:
        return None
    if not (headers.get("x-cron-schedule-id") or headers.get("X-Cron-Schedule-Id")):
        return None

    from nodes.core.registry import NODE_REGISTRY

    node_cls = NODE_REGISTRY.get(trigger_node.get("type") or "")
    if node_cls is None:
        return None
    # Judge the same dict the executor will parse (incl. the injected
    # _triggerPayload) so this verdict can't diverge from run-time behavior.
    result = node_cls.validate_saved_config(_node_cfg(trigger_node))
    if result["valid"]:
        return None
    return "; ".join(result["errors"]) or "config failed validation"


async def _trigger_ever_ran(workflow_id: str, node_id: str) -> bool:
    """Has this trigger node ever completed a clean run (a real fire or a
    no-event poll skip)? Definitive setup-vs-regression signal for
    ``_schedule_tick_config_error`` callers. Fails OPEN (True) on a DB error:
    a blip must surface the config failure loudly, never silence a
    previously-working trigger.
    """
    try:
        row = await get_native_pool().fetchrow(
            """
            SELECT 1 FROM cas_manifests
            WHERE workflow_id = $1 AND node_id = $2
              AND last_run_status IN ('completed', 'skipped')
            LIMIT 1
            """,
            uuid_module.UUID(workflow_id), node_id,
        )
        return row is not None
    except Exception as e:
        logger.warning(f"[WEBHOOK] ever-ran lookup failed for {node_id}: {e}")
        return True


def _cleanup_orphaned_webhook(webhook_id: str, workflow_id: str, node_id: Optional[str]):
    """Delete an orphaned webhook + cron schedule when the target node no longer
    exists in the workflow. Runs fire-and-forget so webhook delivery returns
    quickly."""
    from utils.async_helpers import spawn

    async def _do_cleanup():
        try:
            from utils.webhook_manager import WebhookManager
            from utils.cron_scheduler_client import delete_schedules_for_nodes

            pool = get_native_pool()

            # Grace period: a webhook created moments ago is mid-registration,
            # not an orphan. Deleting it here races the watch-channel insert and
            # fails it with an FK violation, so the trigger never activates.
            fresh = await pool.fetchrow(
                "SELECT 1 FROM webhooks WHERE id = $1 AND created_at > NOW() - INTERVAL '2 minutes'",
                uuid_module.UUID(webhook_id),
            )
            if fresh:
                logger.info(
                    f"[WEBHOOK] Skipping orphan cleanup for freshly-created webhook {webhook_id} "
                    f"(registration in progress)"
                )
                return

            if node_id:
                try:
                    await delete_schedules_for_nodes(workflow_id, [node_id])
                except Exception as e:
                    logger.warning(f"[WEBHOOK] Orphan cleanup: failed to delete cron for {node_id}: {e}")
            await WebhookManager.delete_webhook(pool, workflow_id, node_id or webhook_id)
            logger.info(f"[WEBHOOK] Orphan cleanup: deleted webhook {webhook_id} + cron for node {node_id}")
        except Exception as e:
            logger.warning(f"[WEBHOOK] Orphan cleanup failed for {webhook_id}: {e}")

    spawn(_do_cleanup(), name=f"orphan-webhook-cleanup:{webhook_id}")


async def handle_webhook_payload(
    webhook_id: str,
    body: str,
    headers: dict,
    query: dict,
    method: str = "POST",
    return_response: bool = False,
) -> Any:
    """
    Handle a webhook payload received through the configured relay transport.

    Args:
        webhook_id: The webhook UUID
        body: Raw request body string
        headers: Request headers dict
        query: Query parameters dict
        method: HTTP method (GET, POST, PUT, DELETE, etc.)

    Returns:
        ``True``/``False`` for legacy relay callers, or an HTTP response payload
        dict when ``return_response=True``.
    """
    import json

    logger.info(f"[WEBHOOK] Processing relayed webhook: {webhook_id}")

    # Get webhook config (uses connection pool). A DB failure must NOT be read as
    # "webhook gone" — return 503 so the cron scheduler retries, never delete.
    try:
        config = await get_webhook_config(webhook_id)
    except Exception as e:
        logger.error(f"[WEBHOOK] Config lookup failed for {webhook_id}; returning 503 (no schedule deletion): {e}")
        return _json_relay_response({"detail": "Webhook lookup temporarily unavailable"}, status_code=503) if return_response else False
    if not config:
        logger.error(f"[WEBHOOK] Webhook not found: {webhook_id}")
        cron_schedule_id = headers.get("x-cron-schedule-id") or headers.get("X-Cron-Schedule-Id")
        if cron_schedule_id:
            from utils.cron_scheduler_client import delete_schedule
            spawn(delete_schedule(cron_schedule_id), name=f"orphan-cron-cleanup:{cron_schedule_id}")
        return _json_relay_response({"detail": "Webhook not found"}, status_code=404) if return_response else False

    if not config.get("is_active"):
        logger.warning(f"[WEBHOOK] Webhook is disabled: {webhook_id}")
        return _json_relay_response({"detail": "Webhook is disabled"}, status_code=410) if return_response else False

    # Signature verification is the trigger node class's job — every provider
    # signs differently (Stripe-Signature, Linear-Signature, Mailgun in-body,
    # x-hub HMAC, …), so it runs in _apply_trigger_node_hooks once the node is
    # resolved, with the row's synchronously-persisted secret as the fallback
    # for configs the autosave hasn't reached.

    # Parse body as JSON if possible
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {"raw": body}

    # Add request metadata
    payload["_webhook"] = {
        "id": webhook_id,
        "method": method,
        "headers": headers,
        "query_params": query,
    }

    user_id = str(config["user_id"])
    workflow_id = str(config["workflow_id"])
    workflow_config = config.get("workflow_config", {})

    # Parse workflow_config if it's a JSON string (database may return it as string)
    if isinstance(workflow_config, str):
        try:
            workflow_config = json.loads(workflow_config)
        except json.JSONDecodeError:
            logger.error(f"[WEBHOOK] Failed to parse workflow_config as JSON")
            return False

    # Delay-resume callback from the cron scheduler — resume the paused run
    # instead of triggering a fresh workflow execution.
    delay_resume = _build_delay_resume_data(payload, workflow_id)
    if delay_resume is not None:
        logger.info(f"[WEBHOOK] Delay-resume callback for execution {delay_resume['execution_id']}")
        update_webhook_stats(webhook_id)
        spawn(
            _run_delay_resume(delay_resume, user_id),
            name=f"webhook-delay-resume:{delay_resume['execution_id']}",
        )
        if return_response:
            return _json_relay_response(
                WebhookResponse(
                    success=True,
                    message="Delay resume scheduled",
                    execution_id=delay_resume["execution_id"],
                ).model_dump()
            )
        return True

    # Google's initial watch handshake (sync) carries no change and races node
    # persistence — ACK it without node lookup, workflow fire, or orphan cleanup.
    if _is_google_watch_handshake(payload):
        logger.info(f"[WEBHOOK] Google watch sync handshake for {webhook_id}, acking")
        update_webhook_stats(webhook_id)
        return _json_relay_response(
            WebhookResponse(success=True, message="Google watch sync acknowledged", execution_id=None).model_dump()
        ) if return_response else True

    logger.info(f"[WEBHOOK] Triggering workflow {workflow_id} for user {user_id[:8]}...")

    # Find the webhook trigger node by matching webhook_id in config
    nodes = workflow_config.get("nodes", [])
    edges = workflow_config.get("edges", [])
    actual_node_id = None
    trigger_node = None
    is_alarm = False
    for node in nodes:
        node_config = _node_cfg(node)
        if node_config.get("webhook_id") == webhook_id:
            actual_node_id = node.get("id")
            trigger_node = node
            node["config"]["_triggerPayload"] = payload
            logger.info(f"[WEBHOOK] Set _triggerPayload on node {actual_node_id}, config keys: {list(node.get('config', {}).keys())}")
            break

    # Fallback: find node by node_id from webhooks table (for alarm nodes
    # whose webhook is created lazily and not stored in node config)
    if not actual_node_id:
        db_node_id = str(config.get("node_id", ""))
        for node in nodes:
            if node.get("id") == db_node_id and node.get("type") == "alarm":
                actual_node_id = db_node_id
                trigger_node = node
                is_alarm = True
                _inject_alarm_trigger_payload(node, payload)
                break

    if not actual_node_id:
        logger.error(f"[WEBHOOK] No node found with webhook_id={webhook_id}")
        _cleanup_orphaned_webhook(webhook_id, workflow_id, str(config.get("node_id", "")))
        return _json_relay_response({"detail": "Webhook trigger node not found in workflow"}, status_code=404) if return_response else False

    if _is_stale_schedule_tick(headers, trigger_node, is_alarm):
        logger.warning(
            f"[WEBHOOK] Schedule tick for node {actual_node_id} whose current operation is not a "
            f"trigger — pruning stale schedule + webhook {webhook_id}"
        )
        _cleanup_orphaned_webhook(webhook_id, workflow_id, actual_node_id)
        return _json_relay_response({"detail": "Node operation is not a trigger"}, status_code=410) if return_response else False

    if cfg_err := _schedule_tick_config_error(headers, trigger_node, is_alarm):
        if not await _trigger_ever_ran(workflow_id, actual_node_id):
            logger.info(
                f"[WEBHOOK] Schedule tick for node {actual_node_id} still being set up — saved "
                f"config not yet valid ({cfg_err}); skipping run until the config save lands"
            )
            update_webhook_stats(webhook_id)
            return _json_relay_response(
                WebhookResponse(
                    success=True,
                    message="Schedule tick skipped: trigger configuration not yet saved",
                    execution_id=None,
                ).model_dump()
            ) if return_response else True
        # Previously-working trigger now failing validation: dispatch so the
        # config error surfaces as a visible run failure.

    try:
        _validate_webhook_request_settings(
            trigger_node,
            method=method,
            headers=headers,
        )
    except HTTPException as exc:
        logger.warning(f"[WEBHOOK] Request rejected for {webhook_id}: {exc.detail}")
        return _json_relay_response({"detail": exc.detail}, status_code=exc.status_code) if return_response else False

    # Run the trigger node's handshake + signature hooks.
    try:
        hook_response = await _apply_trigger_node_hooks(
            trigger_node, body.encode(), headers,
            workflow_id=workflow_id,
            webhook_secret=config.get("secret"),
            method=method,
            query_params=query,
        )
    except HTTPException as exc:
        logger.error(f"[WEBHOOK] Signature verification failed for {webhook_id}")
        return _json_relay_response({"detail": exc.detail}, status_code=exc.status_code) if return_response else False
    if hook_response is not None:
        update_webhook_stats(webhook_id)
        if isinstance(hook_response, Response):
            return _response_to_relay_payload(hook_response) if return_response else True
        return _json_relay_response(hook_response) if return_response else True

    # Filter by action type — granular trigger nodes (e.g. Linear, GitHub) may
    # reject deliveries whose action field doesn't match the configured operation.
    from nodes.core.registry import NODE_REGISTRY

    node_cls = NODE_REGISTRY.get(trigger_node.get("type"))
    if control_msg := await _consume_control_event(node_cls, trigger_node, payload, workflow_id):
        update_webhook_stats(webhook_id)
        return _json_relay_response(
            WebhookResponse(success=True, message=control_msg, execution_id=None).model_dump()
        ) if return_response else True
    if node_cls is not None and not node_cls.filter_trigger_payload(payload, trigger_node.get("config", {})):
        logger.info(f"[WEBHOOK] Trigger node {actual_node_id} filtered out payload, skipping workflow execution")
        update_webhook_stats(webhook_id)
        return _json_relay_response(
            WebhookResponse(
                success=True,
                message="Webhook received but event action does not match trigger filter",
                execution_id=None,
            ).model_dump()
        ) if return_response else True

    if await _over_trigger_fire_budget(node_cls, trigger_node, payload, workflow_id):
        update_webhook_stats(webhook_id)
        return _json_relay_response(
            WebhookResponse(
                success=True,
                message="Webhook received but trigger is over its fire budget",
                execution_id=None,
            ).model_dump()
        ) if return_response else True

    if not await _claim_google_watch_delivery(workflow_id, actual_node_id, trigger_node, payload):
        update_webhook_stats(webhook_id)
        return _json_relay_response(
            WebhookResponse(
                success=True,
                message="Duplicate Google watch delivery ignored",
                execution_id=None,
            ).model_dump()
        ) if return_response else True

    payload = await _transform_trigger_payload(node_cls, trigger_node, payload, workflow_id)

    # Check if trigger node is disabled - skip execution if so
    if trigger_node and _is_node_disabled(trigger_node):
        logger.info(f"[WEBHOOK] Trigger node {actual_node_id} is disabled, skipping workflow execution")
        update_webhook_stats(webhook_id)
        if return_response:
            return _json_relay_response(
                WebhookResponse(
                    success=True,
                    message="Webhook received but trigger is disabled",
                    execution_id=None,
                ).model_dump()
            )
        return True  # Return success but don't execute

    # For alarm nodes, execute only the agent's subgraph to avoid side effects
    if is_alarm:
        agent_node_id = _find_connected_agent(nodes, edges, actual_node_id)
        if agent_node_id:
            subgraph_ids = _get_agent_subgraph(nodes, edges, agent_node_id)
            # Restore upstream context: mock upstream nodes with stored outputs
            # and override agent's message with alarm trigger message
            _restore_upstream_context(nodes, subgraph_ids, agent_node_id, payload)
            nodes = [n for n in nodes if n.get('id') in subgraph_ids]
            edges = [e for e in edges if e.get('source') in subgraph_ids and e.get('target') in subgraph_ids]
            logger.info(f"[WEBHOOK] Alarm trigger: executing agent subgraph ({len(nodes)} nodes) for agent {agent_node_id}")

    # Update stats only after the trigger node has accepted the request. This
    # avoids counting missing-node lookups or rejected provider signatures.
    update_webhook_stats(webhook_id)
    response_mode = _get_webhook_response_mode(trigger_node)

    if return_response and response_mode == "immediately":
        spawn(
            _execute_workflow_with_relay(
                user_id=user_id,
                workflow_id=workflow_id,
                nodes=nodes,
                edges=edges,
                start_node_id=actual_node_id,
            ),
            name=f"relay-webhook-execute:{workflow_id}:{actual_node_id}",
        )
        ack = _webhook_ack_for_node(trigger_node)
        if ack is not None:
            return _response_to_relay_payload(ack)
        return _json_relay_response(
            WebhookResponse(
                success=True,
                message="Webhook received and workflow triggered",
                execution_id=None,
            ).model_dump()
        )

    result = await _execute_workflow_with_relay(
        user_id=user_id,
        workflow_id=workflow_id,
        nodes=nodes,
        edges=edges,
        start_node_id=actual_node_id,
    )
    if return_response and response_mode == "last_node":
        # Map HTTPException to a relay payload like every other early-return here,
        # so the proper status code (e.g. 409 paused) and detail reach the caller
        # instead of collapsing to a generic 500 in the relay error handler.
        try:
            return _response_to_relay_payload(
                _response_from_execution_result(trigger_node, result)
            )
        except HTTPException as exc:
            logger.warning(f"[WEBHOOK] last_node response failed for {webhook_id}: {exc.detail}")
            return _json_relay_response({"detail": exc.detail}, status_code=exc.status_code)

    return True


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 signature."""
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


async def _persist_trigger_signing_secret(
    workflow_id: str, node_id: str, secret: str
) -> None:
    """Write a newly-received signing secret into the trigger node's config in the DB.

    Used after a provider handshake (e.g. Asana X-Hook-Secret) that delivers the
    secret asynchronously, after the initial webhook registration. Fire-and-forget
    from the webhook route; a failure is logged but does not affect the HTTP response.
    """
    try:
        pool = get_native_pool()
        row = await pool.fetchrow(
            "SELECT workflow FROM workflows WHERE id = $1",
            uuid_module.UUID(workflow_id),
        )
        if not row:
            logger.error(f"[WEBHOOK] _persist_signing_secret: workflow {workflow_id} not found")
            return
        workflow_json = dict(row["workflow"]) if row["workflow"] else {}
        updated = False
        for node in workflow_json.get("nodes", []):
            if node.get("id") == node_id:
                node.setdefault("config", {})["signing_secret"] = secret
                updated = True
                break
        if updated:
            await pool.execute(
                "UPDATE workflows SET workflow = $1, updated_at = NOW() WHERE id = $2",
                workflow_json,
                uuid_module.UUID(workflow_id),
            )
        # Mirror to the webhooks row — the system of record verification falls
        # back to when the config copy is missing or stale.
        await db.execute_async(
            "UPDATE webhooks SET secret = $1, updated_at = NOW() "
            "WHERE workflow_id = $2 AND node_id = $3",
            secret,
            uuid_module.UUID(workflow_id),
            node_id,
        )
    except Exception as e:
        logger.error(f"[WEBHOOK] Failed to persist signing secret for node {node_id}: {e}")


async def _apply_trigger_node_hooks(
    trigger_node: dict, raw_body: bytes, headers: dict,
    workflow_id: Optional[str] = None,
    webhook_secret: Optional[str] = None,
    method: Optional[str] = None,
    query_params: Optional[dict] = None,
) -> Optional[Any]:
    """Run a matched trigger node's webhook handshake + signature hooks.

    Returns a response to send back to the caller synchronously (a provider
    handshake/verification response), or ``None`` to proceed with normal
    workflow dispatch. The response may be a plain dict (serialised as JSON) or
    a ``Response`` object (used when custom HTTP headers must be set, e.g.
    Asana's X-Hook-Secret echo). Raises ``HTTPException(401)`` when the node
    rejects the request's signature. Safe to call for any node — non-trigger
    nodes inherit the no-op base hooks.

    ``method``/``query_params`` (when supplied) are surfaced to the handshake
    hook via the reserved ``__method__``/``__query_params__`` header keys — a
    GET-based verification (e.g. Meta's ``hub.challenge`` CRC) needs both, and
    the raw headers alone don't carry them.

    ``handle_webhook_handshake`` may return a ready ``Response`` when it needs
    full control over body/content-type (Meta's CRC echoes ``hub.challenge`` as
    raw ``text/plain``, which JSON serialisation would corrupt); it is passed
    through untouched.

    Special keys in the dict returned by ``handle_webhook_handshake``:
      ``__response_headers__``: dict of headers to include in the HTTP response
      ``__signing_secret__``: secret to persist into the trigger node's config

    ``webhook_secret`` is the ``webhooks.secret`` column value, written
    synchronously at registration. Verification tries the config's
    ``signing_secret`` first, then retries with this — covering both a config
    the autosave hasn't reached (first event after registering) and a config
    holding the pre-re-registration secret (stale after a guard-break).
    """
    from nodes.core.registry import NODE_REGISTRY

    node_cls = NODE_REGISTRY.get(trigger_node.get("type"))
    if node_cls is None:
        return None

    lower_headers = {k.lower(): v for k, v in (headers or {}).items()}
    if method is not None:
        lower_headers["__method__"] = method
    if query_params is not None:
        lower_headers["__query_params__"] = query_params

    node_config = trigger_node.get("config", {})
    handshake = node_cls.handle_webhook_handshake(raw_body, lower_headers, node_config)
    if handshake is not None:
        # A node may hand back a fully-formed Response when it needs total
        # control over the body/content-type (Meta CRC → raw text/plain).
        if isinstance(handshake, Response):
            return handshake
        response_headers = handshake.pop("__response_headers__", None)
        signing_secret = handshake.pop("__signing_secret__", None)
        if signing_secret and workflow_id and trigger_node.get("id"):
            # Persist the secret so subsequent events can be HMAC-verified.
            await _persist_trigger_signing_secret(
                workflow_id, trigger_node["id"], signing_secret
            )
        if response_headers:
            return Response(
                content=json.dumps(handshake) if handshake else "",
                media_type="application/json",
                headers=response_headers,
            )
        return handshake

    if not node_cls.verify_webhook_signature(raw_body, lower_headers, node_config):
        # The config blob's signing_secret lags the row: the debounced autosave
        # takes ~2s, and never lands at all if the tab closed right after a
        # (re-)registration. The row secret is written synchronously at
        # registration, so retry with it — config stays primary because
        # async-handshake providers (Asana) and pre-row-era registrations can
        # hold a config secret the row lacks.
        row_config = (
            {**node_config, "signing_secret": webhook_secret}
            if webhook_secret and webhook_secret != node_config.get("signing_secret")
            else None
        )
        if row_config is None or not node_cls.verify_webhook_signature(
            raw_body, lower_headers, row_config
        ):
            logger.warning(
                f"[WEBHOOK] Signature verification failed for node "
                f"{trigger_node.get('id')} ({trigger_node.get('type')})"
            )
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    return None


async def _over_trigger_fire_budget(
    node_cls, trigger_node: dict, payload: dict, workflow_id: str
) -> bool:
    """Per-(node, channel) fire budget for channel-like per-node webhook triggers.

    The node class opts in by returning a channel key from
    trigger_fire_budget_channel (e.g. WhatsApp's chat id); app-webhook
    providers get the same cap via APP_PROVIDERS in _fire_subscription.
    True = suppress this delivery.
    """
    if node_cls is None:
        return False
    channel = node_cls.trigger_fire_budget_channel(payload, trigger_node.get("config", {}))
    if channel is None:
        return False
    from utils.fire_budget import over_fire_budget

    if await over_fire_budget(workflow_id, trigger_node.get("id"), channel):
        logger.warning(
            f"[WEBHOOK] Trigger node {trigger_node.get('id')} ({trigger_node.get('type')}) "
            f"over fire budget for channel {channel} — suppressing delivery"
        )
        return True
    return False


async def _consume_control_event(
    node_cls, trigger_node: dict, payload: dict, workflow_id: str
) -> Optional[str]:
    """Give the node class a chance to consume a provider CONTROL-PLANE event
    (e.g. WAHooks session.status on a WhatsApp webhook) without executing the
    workflow. Returns the consumed-message for the 200 ack, or None to proceed
    with normal data delivery. Best-effort by contract — a broken control
    handler must never break data delivery."""
    from nodes.core.base import WorkflowNode

    # Fast path: this runs on EVERY per-node delivery, so classes that keep
    # the base no-op hook must cost nothing (no pool resolution, no coroutine).
    if node_cls is None or node_cls.handle_control_event.__func__ is WorkflowNode.handle_control_event.__func__:
        return None
    try:
        consumed = await node_cls.handle_control_event(
            payload,
            trigger_node.get("config", {}),
            pool=get_native_pool(),
            workflow_id=workflow_id,
            node_id=trigger_node.get("id"),
        )
    except Exception as e:
        logger.warning(
            f"[WEBHOOK] handle_control_event failed for node "
            f"{trigger_node.get('id')} ({trigger_node.get('type')}): {e}"
        )
        return None
    if consumed:
        logger.info(
            f"[WEBHOOK] Control event consumed by node {trigger_node.get('id')} "
            f"({trigger_node.get('type')}): {consumed}"
        )
    return consumed


async def _transform_trigger_payload(
    node_cls, trigger_node: dict, payload: dict, workflow_id: str
) -> dict:
    """Let the node class rewrite the delivery payload (e.g. rehost ephemeral
    provider media) and re-inject the result as the trigger's ``_triggerPayload``.
    Best-effort by contract — on any failure the original payload stands."""
    from nodes.core.base import WorkflowNode

    # Fast path — mirrors _consume_control_event: classes on the base no-op
    # must cost nothing per delivery.
    if node_cls is None or node_cls.transform_trigger_payload.__func__ is WorkflowNode.transform_trigger_payload.__func__:
        return payload
    try:
        transformed = await node_cls.transform_trigger_payload(
            payload,
            trigger_node.get("config", {}),
            pool=get_native_pool(),
            workflow_id=workflow_id,
            node_id=trigger_node.get("id"),
        )
    except Exception as e:
        logger.warning(
            f"[WEBHOOK] transform_trigger_payload failed for node "
            f"{trigger_node.get('id')} ({trigger_node.get('type')}): {e}"
        )
        return payload
    if transformed is None:
        return payload
    trigger_node.setdefault("config", {})["_triggerPayload"] = transformed
    return transformed


def _webhook_ack_for_node(trigger_node: dict) -> Optional[Response]:
    """Provider-specific acknowledgement response for a trigger node.

    Returns a ``Response`` to send back instead of the default JSON ack (e.g.
    Twilio's TwiML), or ``None`` to use the default.
    """
    from nodes.core.registry import NODE_REGISTRY

    node_cls = NODE_REGISTRY.get(trigger_node.get("type"))
    if node_cls is None:
        return None
    ack = node_cls.webhook_ack_response()
    if not ack:
        return None
    return Response(
        content=ack.get("content", ""),
        media_type=ack.get("media_type", "text/plain"),
    )


def _webhook_trigger_source(nodes: list, start_node_id: Optional[str]) -> str:
    """'cron'/'email' by the firing trigger node's type, else 'webhook'. Cron-scheduled
    and inbound-email runs reach this execution path too, distinguished by node type."""
    if start_node_id:
        start = next((n for n in (nodes or []) if n.get("id") == start_node_id), None)
        node_type = start.get("type") if start else None
        if node_type == "trigger-cron":
            return "cron"
        if node_type == "trigger-email":
            return "email"
    return "webhook"


async def _execute_workflow_with_relay(
    user_id: str,
    workflow_id: str,
    nodes: list,
    edges: list,
    start_node_id: Optional[str] = None,
) -> WorkflowExecutionResult:
    """
    Execute workflow using WorkflowExecutionHandler with relay mode.

    This function is called in a background task to execute workflows triggered
    by webhooks. Events are routed via Event Relay to the user's connected frontends.

    Args:
        user_id: User ID for routing events via relay
        workflow_id: Workflow to execute
        nodes: Workflow nodes
        edges: Workflow edges
        start_node_id: Optional starting node ID (for webhook triggers)
    """
    # Lazy import to avoid circular dependency (api.py imports webhook_routes)
    from server import sio
    from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

    try:
        # Create handler instance with sio
        handler = WorkflowExecutionHandler(sio)
        await handler.setup_user("")  # Initialize database pool

        # Create request with workflow data. A cron-trigger run also arrives via
        # this path; tag it 'cron' (vs 'webhook') by the start node's type.
        request = WorkflowExecuteRequest(
            event_name="workflow:execute",
            request_id=f"webhook-{workflow_id}",
            workflow_id=workflow_id,
            nodes=nodes,
            edges=edges,
            start_node_id=start_node_id,
            trigger_source=_webhook_trigger_source(nodes, start_node_id),
        )

        # Execute with caller_user_id to resolve user_id (no socket session in webhook mode)
        result = await handler.handle_execute(
            sid="",  # No direct socket connection
            request=request,
            caller_user_id=user_id,
        )

        logger.info(f"[WEBHOOK] Workflow {workflow_id} execution completed")
        return result

    except Exception as e:
        # Return a failed result rather than re-raising: fire-and-forget callers
        # (immediately mode via spawn / background_tasks) must not surface an
        # unhandled task exception, and synchronous last_node callers turn this
        # into a clean 500 via _response_from_execution_result.
        logger.error(f"[WEBHOOK] Workflow execution failed: {e}", exc_info=True)
        return WorkflowExecutionResult(
            execution_id="unknown",
            workflow_id=workflow_id,
            success=False,
            nodes_executed=0,
            duration=0,
            error=f"Workflow execution failed: {e}",
        )


async def _fire_subscription(
    background_tasks,
    sub: dict,
    payload: dict,
    event_channel: Optional[str] = None,
) -> bool:
    """Load a subscribed workflow, inject the event payload on its trigger node,
    and queue execution. Returns True if a run was queued.

    A trigger node with a channel configured (the adapter's
    ``channel_config_key``, ``channel`` by default) fires only for events in
    that channel, and an adapter ``node_filter`` can veto on any other config
    predicate; both read the node's LIVE config so an edit takes effect on the
    next event with no re-registration.
    """
    from utils.app_webhooks import APP_PROVIDERS

    adapter = APP_PROVIDERS.get(str(sub.get("provider")), {})
    workflow_id = str(sub["workflow_id"])
    node_id = sub["node_id"]
    user_id = str(sub["user_id"])

    try:
        row = await get_native_pool().fetchrow(
            "SELECT workflow FROM workflows WHERE id = $1", sub["workflow_id"]
        )
    except Exception as e:
        logger.error(f"[APP-WEBHOOK] Failed to load workflow {workflow_id}: {e}")
        return False
    if not row or not row.get("workflow"):
        return False

    workflow_config = row["workflow"]
    if isinstance(workflow_config, str):
        try:
            workflow_config = json.loads(workflow_config)
        except json.JSONDecodeError:
            return False

    nodes = workflow_config.get("nodes", [])
    edges = workflow_config.get("edges", [])
    trigger_node = None
    for node in nodes:
        if node.get("id") == node_id:
            trigger_node = node
            node.setdefault("config", {})["_triggerPayload"] = payload
            break
    if trigger_node is None:
        return False
    if _is_node_disabled(trigger_node):
        logger.info(f"[APP-WEBHOOK] Trigger node {node_id} disabled, skipping")
        return False

    trigger_config = _node_cfg(trigger_node)
    configured_channel = _resolve_app_webhook_config_value(
        trigger_config.get(adapter.get("channel_config_key", "channel")),
        workflow_config,
    )
    if configured_channel and configured_channel != event_channel:
        logger.info(
            f"[APP-WEBHOOK] Trigger node {node_id} scoped to channel "
            f"{configured_channel}; event in {event_channel} — skipping"
        )
        return False

    node_filter = adapter.get("node_filter")
    skip_reason = node_filter(trigger_config, payload) if node_filter else None
    if skip_reason:
        logger.info(f"[APP-WEBHOOK] Trigger node {node_id} skipped: {skip_reason}")
        return False

    scope_filter = adapter.get("scope_filter")
    if scope_filter:
        try:
            skip_reason = await scope_filter(get_native_pool(), sub, payload)
        except Exception as e:
            # Fail closed: an event whose owner cannot be established must not
            # run as someone else's.
            logger.error(f"[APP-WEBHOOK] Scope check failed for trigger {node_id}: {e}")
            return False
        if skip_reason:
            logger.info(f"[APP-WEBHOOK] Trigger node {node_id} out of scope: {skip_reason}")
            return False

    # Blast-radius bound: no authorship check can see a two-party echo
    # (NoClick posts → an external bot auto-replies → the foreign reply
    # re-triggers this node). Suppress a trigger firing over budget, loudly.
    # Opt-in per provider (APP_PROVIDERS fire_budget capability): applies to
    # channel-conversation providers where echo loops close, never to
    # burst-legitimate ones (HubSpot bulk imports fire thousands of events).
    from utils.fire_budget import (
        FIRE_BUDGET_MAX,
        FIRE_BUDGET_WINDOW_SECONDS,
        over_fire_budget,
    )
    if adapter.get("fire_budget") and await over_fire_budget(workflow_id, node_id, event_channel):
        logger.error(
            f"[APP-WEBHOOK] FIRE BUDGET EXCEEDED: trigger {node_id} in workflow "
            f"{workflow_id} fired >{FIRE_BUDGET_MAX} times in "
            f"{FIRE_BUDGET_WINDOW_SECONDS}s for channel {event_channel or 'any'} "
            f"— suppressing run (possible feedback loop with an external responder)"
        )
        return False

    background_tasks.add_task(
        _execute_workflow_with_relay,
        user_id=user_id,
        workflow_id=workflow_id,
        nodes=nodes,
        edges=edges,
        start_node_id=node_id,
    )
    return True


def _resolve_app_webhook_config_value(value: Any, workflow_config: dict) -> Any:
    """Resolve simple ``{{vars.name}}`` references before webhook filtering.

    App-level webhooks are routed before normal workflow execution, so the
    standard node interpolation pass has not run yet. Channel-scoped Slack
    triggers can still use workflow variables as long as we resolve them here.
    """
    if not isinstance(value, str):
        return value

    stripped = value.strip()
    if not (stripped.startswith("{{") and stripped.endswith("}}")):
        return value

    expr = stripped[2:-2].strip()
    if not expr.startswith("vars."):
        return value

    var_name = expr.split(".", 1)[1]
    variables = workflow_config.get("variables") or {}
    if var_name in variables:
        return variables[var_name]

    for node in workflow_config.get("nodes", []):
        if node.get("type") != "set-variable":
            continue
        for assignment in _node_cfg(node).get("assignments", []):
            if assignment.get("variable_name") == var_name:
                return assignment.get("value")

    return value


class _SpawnBackgroundTasks:
    """BackgroundTasks-compatible shim for non-HTTP trigger-test injection."""

    def add_task(self, func, *args, **kwargs) -> None:
        result = func(*args, **kwargs)
        if hasattr(result, "__await__"):
            from utils.async_helpers import spawn

            spawn(result, name=f"app-webhook:{getattr(func, '__name__', 'task')}")


async def handle_app_webhook_payload(
    provider: str,
    body: bytes,
    headers: Dict[str, str],
    request_url: str,
    background_tasks=None,
) -> WebhookResponse:
    """Verify, parse, and fan out an app-level webhook payload.

    Used by the HTTP route and by local trigger tests that synthesize signed
    Slack/HubSpot events without running the separate webhook ASGI app.
    """
    from utils.app_webhooks import APP_PROVIDERS

    adapter = APP_PROVIDERS.get(provider)
    if not adapter:
        raise HTTPException(
            status_code=404, detail=f"Unknown app webhook provider: {provider}"
        )

    lower_headers = {str(k).lower(): str(v) for k, v in headers.items()}
    pool = get_native_pool()
    verify_result = adapter["verify"](pool, body, lower_headers, request_url)
    if inspect.isawaitable(verify_result):
        verify_result = await verify_result
    if not verify_result:
        logger.warning(f"[APP-WEBHOOK] Signature verification failed for {provider}")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    handshake = adapter["handshake"](body)
    if handshake is not None:
        if isinstance(handshake, Response):
            return handshake
        return JSONResponse(content=handshake)

    await dispatch_app_events(provider, body, background_tasks)

    ack = adapter.get("ack")
    if ack:
        response = ack(body)
        if isinstance(response, Response):
            return response
        return JSONResponse(content=response)
    return WebhookResponse(
        success=True, message="Event received", execution_id=None
    )


async def dispatch_app_events(provider: str, body: bytes, background_tasks=None) -> int:
    """Parse an already-trusted app-level body and fan its events out to every
    subscribed workflow; returns the number of runs queued.

    The post-verification half of ``handle_app_webhook_payload``, callable on
    its own by in-process producers — the open edition's Discord Gateway
    listener hands its envelopes here without an HTTP hop or a signature.
    """
    from nodes.core.webhook_subscriptions import find_subscriptions
    from utils.app_event_dedup import mark_delivered, was_delivered
    from utils.app_webhooks import APP_PROVIDERS

    adapter = APP_PROVIDERS[provider]
    pool = get_native_pool()
    tasks = background_tasks or _SpawnBackgroundTasks()
    events = adapter["parse"](body)
    drop_event = adapter.get("drop_event")
    extract_event_id = adapter.get("event_id")
    fired = 0
    for tenant_id, event_type, payload, event_channel in events:
        # Redelivery dedup (providers redeliver on slow ACK, double-firing
        # every subscription). Best-effort at-least-once: marked delivered
        # only after this event's fan-out was ENQUEUED, so a crash before
        # that lets the provider's retry recover the event. Keyed with the
        # event type: one payload can legitimately parse into several events
        # (a Discord message is MESSAGE_CREATE and, if it mentions the bot,
        # MESSAGE_MENTION too).
        raw_event_id = extract_event_id(payload) if extract_event_id else None
        event_id = f"{event_type}:{raw_event_id}" if raw_event_id else None
        if event_id and await was_delivered(provider, event_id):
            logger.info(
                f"[APP-WEBHOOK] {provider}: dropped duplicate delivery of {event_id}"
            )
            continue
        if drop_event:
            drop_reason = await drop_event(payload)
            if drop_reason:
                logger.info(
                    f"[APP-WEBHOOK] {provider}: dropped {event_type} event ({drop_reason})"
                )
                # A drop is a final decision — mark it delivered so a
                # redelivery doesn't depend on the drop signal (e.g. the
                # self-post fingerprint) still being present later.
                if event_id:
                    await mark_delivered(provider, event_id)
                continue
        subscriptions = await find_subscriptions(
            pool, provider, tenant_id, event_type
        )
        for sub in subscriptions:
            if await _fire_subscription(tasks, sub, payload, event_channel):
                fired += 1
        if event_id:
            await mark_delivered(provider, event_id)

    logger.info(
        f"[APP-WEBHOOK] {provider}: {len(events)} event(s) -> {fired} workflow run(s)"
    )
    return fired


@router.post("/app/{provider}")
async def receive_app_webhook(
    provider: str, request: Request, background_tasks: BackgroundTasks
):
    """Receive an app-level event webhook (Slack, HubSpot) and fan it out to
    every workflow subscribed to the (tenant, event type).

    Unlike per-workflow webhooks, Slack/HubSpot send all events for the whole
    NoClick app to this one URL; the request is verified against the app secret
    and routed via the ``webhook_subscriptions`` table.
    """
    body = await request.body()
    return await handle_app_webhook_payload(
        provider,
        body,
        dict(request.headers.items()),
        str(request.url),
        background_tasks,
    )


def _build_delay_resume_data(payload: dict, workflow_id: str) -> Optional[dict]:
    """If a webhook payload is a delay-resume callback from the cron scheduler,
    return the generic resume data for handle_resume; otherwise None.

    The cron scheduler wraps the alarm payload under a "payload" key, so a
    delay-resume callback looks like {..., "payload": {"type": "delay_resume",
    "execution_id": ..., "resume_node_id": ...}}.
    """
    inner = payload.get("payload")
    if not isinstance(inner, dict) or inner.get("type") != "delay_resume":
        return None
    execution_id = inner.get("execution_id")
    resume_node_id = inner.get("resume_node_id")
    if not execution_id or not resume_node_id:
        logger.error("[WEBHOOK] delay_resume payload missing execution_id/resume_node_id")
        return None
    return {
        "execution_id": execution_id,
        "workflow_id": workflow_id,
        "resume_node_id": resume_node_id,
        "from_status": "awaiting_delay",
        "decision": None,
    }


async def _run_delay_resume(data: dict, user_id: str) -> None:
    """Resume a workflow run that was paused on a long delay."""
    from server import sio
    from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler
    try:
        handler = WorkflowExecutionHandler(sio)
        await handler.handle_resume(sid="", data=data, caller_user_id=user_id)
        logger.info(f"[WEBHOOK] Delay resume completed for execution {data['execution_id']}")
    except Exception as e:
        logger.error(f"[WEBHOOK] Delay resume failed: {e}", exc_info=True)


def _inject_alarm_trigger_payload(node: dict, payload: dict) -> None:
    """Build and inject alarm trigger payload onto an alarm node."""
    from nodes.alarm_node import get_all_tool_definitions

    # The payload from CF scheduler wraps the alarm data in a 'payload' field
    alarm_data = payload.get("payload") or payload
    node.setdefault("config", {})["_triggerPayload"] = {
        'type': 'alarm_trigger',
        'message': alarm_data.get('message', ''),
        'alarm_node_id': alarm_data.get('alarm_node_id', node.get('id')),
        'agent_node_id': alarm_data.get('agent_node_id'),
        'conversation_key': alarm_data.get('conversation_key'),
        'triggered_at': payload.get('triggered_at'),
        'tool_definitions': get_all_tool_definitions(),
    }


def _find_connected_agent(
    nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]], alarm_node_id: str
) -> Optional[str]:
    """Find the agent node connected to an alarm node via top→bottom edge."""
    for edge in edges:
        if edge.get("source") == alarm_node_id and edge.get("sourceHandle") == "top":
            target_id = edge.get("target")
            for node in nodes:
                if node.get("id") == target_id and node.get("type") == "agent":
                    return target_id
    return None


def _get_agent_subgraph(
    nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]], agent_node_id: str
) -> set:
    """
    Get all node IDs in the agent's execution subgraph:
    1. Tool/alarm nodes connected to agent's bottom handle
    2. The agent node itself
    3. All nodes downstream of the agent (BFS)
    """
    node_ids = {agent_node_id}

    # 1. Tool nodes connected to agent's bottom handle
    for edge in edges:
        if edge.get("target") == agent_node_id and edge.get("targetHandle") == "bottom":
            node_ids.add(edge.get("source"))

    # 2. All nodes downstream of agent (BFS via outgoing edges)
    queue = [agent_node_id]
    visited = {agent_node_id}
    while queue:
        current = queue.pop(0)
        for edge in edges:
            if edge.get("source") == current:
                target = edge.get("target")
                if target and target not in visited:
                    visited.add(target)
                    queue.append(target)
                    node_ids.add(target)

    return node_ids


def _restore_upstream_context(
    nodes: List[Dict[str, Any]], subgraph_ids: set, agent_node_id: str, payload: dict
) -> None:
    """
    Inject stored upstream outputs as mockedOutput on upstream nodes.

    At schedule time, the agent stores outputs of upstream nodes that are
    referenced by subgraph configs. At trigger time, we mock those upstream
    nodes so the execution handler's reference resolution works naturally:
    reachability from the alarm excludes them (upstream, not a provider), and
    ``_preload_excluded_node_outputs`` serves the mock as their preloaded output.

    The wake-up message is NOT written into the agent's config here — it is
    delivered (with conversation_key) via the generalized trigger-event path
    (AlarmNode.resolve_agent_event → AgentNode._resolve_trigger_event), which
    appends it to the agent's standing message. Overriding config.message here
    too would deliver it twice.
    """
    alarm_data = payload.get("payload") or payload

    upstream_outputs = alarm_data.get('upstream_node_outputs')
    if not upstream_outputs:
        return  # Backward compatible with old alarms

    # Add upstream nodes with mockedOutput to the subgraph
    for node in nodes:
        nid = node.get('id')
        if nid in upstream_outputs and nid not in subgraph_ids:
            node.setdefault('config', {})['mockedOutput'] = upstream_outputs[nid]
            subgraph_ids.add(nid)


def _get_node_type_for_webhook(workflow_config: dict, webhook_id: str) -> Optional[tuple[str, str]]:
    """
    Find the node type and ID for a webhook.

    Returns:
        Tuple of (node_type, node_id) or None if not found
    """
    nodes = workflow_config.get("nodes", [])
    for node in nodes:
        node_config = _node_cfg(node)
        if node_config.get("webhook_id") == webhook_id:
            return (node.get("type"), node.get("id"))
    return None


@router.api_route("/{webhook_id}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def receive_webhook(
    webhook_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Receive an external webhook and trigger the associated workflow.

    For form-input nodes:
    - GET: Render HTML form based on field configuration
    - POST: Parse form data and trigger workflow, return success page

    For regular webhooks:
    - The webhook payload is passed to the webhook trigger node as input data.
    - Workflow execution runs in the background so the webhook response is immediate.
    """
    logger.info(f"[WEBHOOK] Received webhook: {webhook_id} (method: {request.method})")

    # Get webhook config (uses connection pool). A DB failure must NOT be read as
    # "webhook gone" — return 503 so the cron scheduler retries, never delete.
    try:
        config = await get_webhook_config(webhook_id)
    except Exception as e:
        logger.error(f"[WEBHOOK] Config lookup failed for {webhook_id}; returning 503 (no schedule deletion): {e}")
        raise HTTPException(status_code=503, detail="Webhook lookup temporarily unavailable")
    if not config:
        # Definitively absent (unknown/invalid id): a cron delivery to a gone
        # target is a genuine orphan, so clean it up to stop it firing forever.
        cron_schedule_id = request.headers.get("X-Cron-Schedule-Id")
        if cron_schedule_id:
            from utils.cron_scheduler_client import delete_schedule
            spawn(delete_schedule(cron_schedule_id), name=f"orphan-cron-cleanup:{cron_schedule_id}")
        raise HTTPException(status_code=404, detail="Webhook not found")

    # Microsoft Graph change-notification subscription validation handshake.
    # On subscription create/renew, Graph calls the notification URL with a
    # ``validationToken`` query param and requires the URL-decoded token echoed
    # back as text/plain (HTTP 200) within 10s, or it refuses to create/renew
    # the subscription. This arrives BEFORE the row is activated and before the
    # node config carries the webhook_id, so it must be answered here, up front.
    # No other provider uses this parameter, so handling it generically is safe.
    validation_token = request.query_params.get("validationToken")
    if validation_token is not None:
        from fastapi.responses import PlainTextResponse

        logger.info(f"[WEBHOOK] Microsoft Graph subscription validation for {webhook_id}")
        return PlainTextResponse(content=validation_token, status_code=200)

    if not config.get("is_active"):
        raise HTTPException(status_code=410, detail="Webhook is disabled")

    # Read body once for methods that can carry payloads (needed for signature check and payload parsing)
    body: bytes = b""
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        body = await request.body()

    # Signature verification happens in _apply_trigger_node_hooks once the
    # trigger node is resolved: providers each sign differently (Stripe-
    # Signature, Linear-Signature, Mailgun in-body, x-hub HMAC, …), so a
    # generic header gate here would 401 legitimate deliveries.

    user_id = str(config["user_id"])
    workflow_id = str(config["workflow_id"])
    node_id = config.get("node_id")
    workflow_config = config.get("workflow_config", {})

    # Parse workflow_config if it's a JSON string
    if isinstance(workflow_config, str):
        try:
            workflow_config = json.loads(workflow_config)
        except json.JSONDecodeError:
            logger.error(f"[WEBHOOK] Failed to parse workflow_config as JSON")
            raise HTTPException(status_code=500, detail="Invalid workflow configuration")

    # Check if this is a form node (unified interface-form; legacy trigger-form-input)
    from nodes.core.registry import resolve_node_type
    node_info = _get_node_type_for_webhook(workflow_config, webhook_id)
    is_form_input = node_info and resolve_node_type(node_info[0]) == "interface-form"

    if node_info:
        trigger_node = next(
            (node for node in workflow_config.get("nodes", []) if node.get("id") == node_info[1]),
            None,
        )
        _validate_webhook_request_settings(
            trigger_node,
            method=request.method,
            headers=dict(request.headers),
        )

    # =========================================================================
    # Handle Form Input Nodes
    # =========================================================================
    if is_form_input:
        form_node_config = _get_form_node_config(workflow_config, node_info[1])

        # GET: Render form
        if request.method == "GET":
            if not form_node_config:
                return HTMLResponse(_render_error_html("Form configuration not found"))

            fields = form_node_config.get("fields", [])
            title = form_node_config.get("title", "")
            description = form_node_config.get("description", "")

            return HTMLResponse(_render_form_html(
                fields=fields,
                form_title=title,
                form_description=description,
                webhook_id=webhook_id,
            ))

        # POST: Handle form submission
        if request.method == "POST":
            content_type = request.headers.get("content-type", "")

            # Parse form data
            if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
                form_data = await request.form()
                form_fields = (form_node_config or {}).get("fields", [])
                boolean_fields = [f.get("name") for f in form_fields if f.get("type") == "boolean"]
                file_fields = {f.get("name") for f in form_fields if f.get("type") == "file"}

                payload = {}
                for key, value in form_data.items():
                    if key in file_fields:
                        # value is a Starlette UploadFile — persist to R2 and
                        # yield its public URL (raw bytes stay out of payload).
                        try:
                            file_result = await _persist_form_upload(
                                upload=value,
                                owner_id=user_id,
                                workflow_id=workflow_id,
                                node_id=node_info[1],
                            )
                        except _FormUploadError as e:
                            logger.error(f"[WEBHOOK] Form file upload failed for field '{key}': {e}")
                            # The exception can wrap storage/DB failures. Never
                            # reflect its detail into this unauthenticated form
                            # response, even if today's call sites use constants.
                            return HTMLResponse(
                                _render_error_html(
                                    "The uploaded file could not be accepted. "
                                    "Please check its size and try again."
                                ),
                                status_code=400,
                            )
                        if file_result is None:
                            # Empty file input — treat as unprovided.
                            continue
                        payload[key] = file_result["url"]
                        payload[f"{key}_filename"] = file_result["filename"]
                    # Convert checkbox "true" string to boolean
                    elif value == "true":
                        payload[key] = True
                    elif value == "false" or value == "":
                        # Unchecked checkboxes don't submit, but handle edge cases
                        payload[key] = False if key in boolean_fields else value
                    else:
                        # Try to parse JSON for object/array fields
                        try:
                            payload[key] = json.loads(value)
                        except (json.JSONDecodeError, TypeError):
                            payload[key] = value
            else:
                # Fallback to JSON parsing
                body = await request.body()
                try:
                    payload = json.loads(body) if body else {}
                except json.JSONDecodeError:
                    payload = {"raw": body.decode("utf-8", errors="replace")}

            # Find and inject payload into form input node
            nodes = workflow_config.get("nodes", [])
            actual_node_id = None
            trigger_node = None
            for node in nodes:
                if node.get("id") == node_info[1]:
                    actual_node_id = node.get("id")
                    trigger_node = node
                    node["config"]["_triggerPayload"] = payload
                    break

            if not actual_node_id:
                return HTMLResponse(_render_error_html("Form trigger node not found"))

            # Check if trigger node is disabled - show message if so
            if trigger_node and _is_node_disabled(trigger_node):
                logger.info(f"[WEBHOOK] Form trigger node {actual_node_id} is disabled, skipping workflow execution")
                return HTMLResponse(_render_error_html("This form is currently disabled"))

            edges = workflow_config.get("edges", [])

            # Update webhook stats
            update_webhook_stats(webhook_id)

            # Execute workflow in background
            background_tasks.add_task(
                _execute_workflow_with_relay,
                user_id=user_id,
                workflow_id=workflow_id,
                nodes=nodes,
                edges=edges,
                start_node_id=actual_node_id,
            )

            logger.info(f"[WEBHOOK] Form submitted, workflow {workflow_id} triggered")
            return HTMLResponse(_render_success_html("Your form has been submitted successfully!"))

    # =========================================================================
    # Handle Regular Webhooks
    # =========================================================================

    # Parse body as JSON if possible (body already read earlier)
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {"raw": body.decode("utf-8", errors="replace")}

    # Add request metadata
    payload["_webhook"] = {
        "id": webhook_id,
        "method": request.method,
        "headers": dict(request.headers),
        "query_params": dict(request.query_params),
    }

    # Delay-resume callback from the cron scheduler — resume the paused run
    # instead of triggering a fresh workflow execution.
    delay_resume = _build_delay_resume_data(payload, workflow_id)
    if delay_resume is not None:
        logger.info(f"[WEBHOOK] Delay-resume callback for execution {delay_resume['execution_id']}")
        update_webhook_stats(webhook_id)
        background_tasks.add_task(_run_delay_resume, delay_resume, user_id)
        return WebhookResponse(
            success=True,
            message="Delay resume scheduled",
            execution_id=delay_resume["execution_id"],
        )

    # Google's initial watch handshake (sync) carries no change and races node
    # persistence — ACK it without node lookup, workflow fire, or orphan cleanup.
    if _is_google_watch_handshake(payload):
        logger.info(f"[WEBHOOK] Google watch sync handshake for {webhook_id}, acking")
        update_webhook_stats(webhook_id)
        return WebhookResponse(success=True, message="Google watch sync acknowledged", execution_id=None)

    logger.info(f"[WEBHOOK] Triggering workflow {workflow_id} for user {user_id[:8]}...")

    # Find the webhook trigger node by matching webhook_id in config
    nodes = workflow_config.get("nodes", [])
    edges = workflow_config.get("edges", [])
    actual_node_id = None
    trigger_node = None
    is_alarm = False
    for node in nodes:
        node_config = _node_cfg(node)
        if node_config.get("webhook_id") == webhook_id:
            actual_node_id = node.get("id")
            trigger_node = node
            node["config"]["_triggerPayload"] = payload
            break

    # Fallback: find node by node_id from webhooks table (for alarm nodes
    # whose webhook is created lazily and not stored in node config)
    if not actual_node_id:
        db_node_id = str(config.get("node_id", ""))
        for node in nodes:
            if node.get("id") == db_node_id and node.get("type") == "alarm":
                actual_node_id = db_node_id
                trigger_node = node
                is_alarm = True
                _inject_alarm_trigger_payload(node, payload)
                break

    # Handshake-only fallback: url_verification (and similar provider challenges)
    # arrive during webhook registration BEFORE the frontend saves webhook_id into
    # the node config.  Find the node via the DB-stored node_id and run just the
    # handshake hook so the provider gets its challenge echo back immediately.
    if not actual_node_id:
        db_node_id = str(config.get("node_id", ""))
        handshake_node = next((n for n in nodes if n.get("id") == db_node_id), None)
        if handshake_node:
            hook_response = await _apply_trigger_node_hooks(
                handshake_node, body, dict(request.headers),
                method=request.method, query_params=dict(request.query_params),
            )
            if hook_response is not None:
                update_webhook_stats(webhook_id)
                if isinstance(hook_response, Response):
                    return hook_response
                return JSONResponse(content=hook_response)

    if not actual_node_id:
        logger.error(f"[WEBHOOK] No node found with webhook_id={webhook_id}")
        _cleanup_orphaned_webhook(webhook_id, workflow_id, str(config.get("node_id", "")))
        raise HTTPException(status_code=404, detail="Webhook trigger node not found in workflow")

    if _is_stale_schedule_tick(dict(request.headers), trigger_node, is_alarm):
        logger.warning(
            f"[WEBHOOK] Schedule tick for node {actual_node_id} whose current operation is not a "
            f"trigger — pruning stale schedule + webhook {webhook_id}"
        )
        _cleanup_orphaned_webhook(webhook_id, workflow_id, actual_node_id)
        raise HTTPException(status_code=410, detail="Node operation is not a trigger")

    if cfg_err := _schedule_tick_config_error(dict(request.headers), trigger_node, is_alarm):
        if not await _trigger_ever_ran(workflow_id, actual_node_id):
            logger.info(
                f"[WEBHOOK] Schedule tick for node {actual_node_id} still being set up — saved "
                f"config not yet valid ({cfg_err}); skipping run until the config save lands"
            )
            update_webhook_stats(webhook_id)
            return WebhookResponse(
                success=True,
                message="Schedule tick skipped: trigger configuration not yet saved",
                execution_id=None,
            )
        # Previously-working trigger now failing validation: dispatch so the
        # config error surfaces as a visible run failure.

    # Run the trigger node's handshake + signature hooks. A handshake response
    # is returned synchronously without firing the workflow; a bad signature
    # raises 401.
    hook_response = await _apply_trigger_node_hooks(
        trigger_node, body, dict(request.headers),
        workflow_id=workflow_id,
        webhook_secret=config.get("secret"),
        method=request.method,
        query_params=dict(request.query_params),
    )
    if hook_response is not None:
        update_webhook_stats(webhook_id)
        if isinstance(hook_response, Response):
            return hook_response
        return JSONResponse(content=hook_response)

    # Check if trigger node is disabled - skip execution if so
    if trigger_node and _is_node_disabled(trigger_node):
        logger.info(f"[WEBHOOK] Trigger node {actual_node_id} is disabled, skipping workflow execution")
        update_webhook_stats(webhook_id)
        return WebhookResponse(
            success=True,
            message="Webhook received but trigger is disabled",
            execution_id=None,
        )

    # Filter by action type for granular trigger nodes (e.g. GitHub, Linear).
    # Must run in both the direct HTTP path (here) and the relay path (handle_webhook_payload).
    from nodes.core.registry import NODE_REGISTRY as _NODE_REGISTRY
    _node_cls = _NODE_REGISTRY.get(trigger_node.get("type"))
    if _control_msg := await _consume_control_event(_node_cls, trigger_node, payload, workflow_id):
        update_webhook_stats(webhook_id)
        return WebhookResponse(success=True, message=_control_msg, execution_id=None)
    if _node_cls is not None and not _node_cls.filter_trigger_payload(payload, trigger_node.get("config", {})):
        logger.info(f"[WEBHOOK] Trigger node {actual_node_id} filtered out payload, skipping workflow execution")
        update_webhook_stats(webhook_id)
        return WebhookResponse(
            success=True,
            message="Webhook received but event action does not match trigger filter",
            execution_id=None,
        )

    if await _over_trigger_fire_budget(_node_cls, trigger_node, payload, workflow_id):
        update_webhook_stats(webhook_id)
        return WebhookResponse(
            success=True,
            message="Webhook received but trigger is over its fire budget",
            execution_id=None,
        )

    if not await _claim_google_watch_delivery(workflow_id, actual_node_id, trigger_node, payload):
        update_webhook_stats(webhook_id)
        return WebhookResponse(
            success=True,
            message="Duplicate Google watch delivery ignored",
            execution_id=None,
        )

    payload = await _transform_trigger_payload(_node_cls, trigger_node, payload, workflow_id)

    # For alarm nodes, execute only the agent's subgraph to avoid side effects
    if is_alarm:
        agent_node_id = _find_connected_agent(nodes, edges, actual_node_id)
        if agent_node_id:
            subgraph_ids = _get_agent_subgraph(nodes, edges, agent_node_id)
            # Restore upstream context: mock upstream nodes with stored outputs
            # and override agent's message with alarm trigger message
            _restore_upstream_context(nodes, subgraph_ids, agent_node_id, payload)
            nodes = [n for n in nodes if n.get('id') in subgraph_ids]
            edges = [e for e in edges if e.get('source') in subgraph_ids and e.get('target') in subgraph_ids]
            logger.info(f"[WEBHOOK] Alarm trigger: executing agent subgraph ({len(nodes)} nodes) for agent {agent_node_id}")

    # Update stats only after the trigger node has accepted the request. This
    # avoids counting missing-node lookups or rejected provider signatures.
    update_webhook_stats(webhook_id)
    response_mode = _get_webhook_response_mode(trigger_node)

    if response_mode == "immediately":
        background_tasks.add_task(
            _execute_workflow_with_relay,
            user_id=user_id,
            workflow_id=workflow_id,
            nodes=nodes,
            edges=edges,
            start_node_id=actual_node_id,
        )

        logger.info(f"[WEBHOOK] Workflow {workflow_id} triggered for user {user_id[:8]}")

        # Some providers (e.g. Twilio) require a specific response body/content-type.
        ack = _webhook_ack_for_node(trigger_node)
        if ack is not None:
            return ack

        return WebhookResponse(
            success=True,
            message="Webhook received and workflow triggered",
            execution_id=None,
        )

    logger.info(f"[WEBHOOK] Waiting for workflow {workflow_id} before responding")
    result = await _execute_workflow_with_relay(
        user_id=user_id,
        workflow_id=workflow_id,
        nodes=nodes,
        edges=edges,
        start_node_id=actual_node_id,
    )
    return _response_from_execution_result(trigger_node, result)
