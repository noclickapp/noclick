"""CloudZero native read-only cost, dimension and saved-view workflows."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import logging
import math
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote, quote_plus
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, ValidationResult, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from repositories.credentials import credential_access_predicate
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-cloudzero"
FAMILIES = ("cloudzero_api_key",)
BASE = "https://api.cloudzero.com"
MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 10000
SAFE_INTEGER = 9007199254740991
COST_TYPES = ("billed_cost", "discounted_cost", "amortized_cost", "discounted_amortized_cost", "real_cost", "on_demand_cost", "invoiced_amortized_cost", "usage_amount")


def _token(value):
    if not isinstance(value, str) or not 8 <= len(value) <= 4096 or any(ord(c) <= 32 or ord(c) >= 127 for c in value):
        raise ValueError("Supply an existing opaque CloudZero API key within the local text bound")
    return value


def _text(value, *, maximum=512):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError("Supply nonempty metadata text within the local bound")
    return value


def _view_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
        raise ValueError("Supply the exact view ID using the local path-safe subset")
    return value


def _whole(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,5}", value): value = int(value)
    if type(value) is not int: raise ValueError("Supply a whole numeric count")
    return value


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2}))?", value):
        raise ValueError("Supply YYYY-MM-DD or an ISO8601 timestamp with explicit timezone")
    try: datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError: raise ValueError("CloudZero date is invalid") from None
    return value


def _instant(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _response_date(value):
    if not isinstance(value, str) or len(value) > 64 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?", value):
        raise ValueError("CloudZero usage timestamp is outside the published ISO8601 shape")
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def _filters(value):
    if value is None or isinstance(value, str) and not value.strip(): return None
    try: parsed = _parse_json(value)
    except (ValueError, TypeError, UnicodeError, RecursionError): raise ValueError("Filters must be a finite JSON object of dimension IDs to string arrays") from None
    if not isinstance(parsed, dict) or len(parsed) > 32: raise ValueError("Filters must be a JSON object with at most 32 dimensions")
    for key, values in parsed.items():
        _text(key)
        if not isinstance(values, list) or not 1 <= len(values) <= 100 or len(set(v for v in values if isinstance(v, str))) != len(values):
            raise ValueError("Each dimension filter requires 1–100 unique string values")
        for item in values: _text(item, maximum=4096)
    if len(_json(parsed)) > 65536: raise ValueError("Filters exceed the local 64KiB JSON bound")
    return parsed


class CloudZeroAPIKeyCredential(BaseModel):
    credential_type: Literal["cloudzero_api_key"] = Field("cloudzero_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Existing API Key", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(extra="ignore", json_schema_extra={
        "x-credential-url": "https://docs.cloudzero.com/reference/authorization",
        "x-credential-instructions": "Supply an existing CloudZero key with fixed read scopes: billing:read_dimensions, billing:read_costs, views:read_views and views:read_view for the operations used. Raw Authorization header without Bearer on fixed api.cloudzero.com. Managed send-only telemetry keys do not imply read access. The protected dimensions check proves reachability only, never principal/organization identity, all scopes or plan entitlement. HTTP403 is a request refusal with unknown key/scope/role/plan cause. No key issuance, environment fallback, OAuth, ingestion or account action.",
    })
    _native_key = field_validator("api_key")(_token)


def _op(name, label, category):
    return Field(name, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})


class CloudZeroOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CloudZeroCheckConfig(CloudZeroOperation):
    operation: Literal["test_connection"] = _op("test_connection", "Check Dimensions Read Access", "Connection")


class CloudZeroDimensionsConfig(CloudZeroOperation):
    operation: Literal["list_dimensions"] = _op("list_dimensions", "List Available Dimensions", "Dimensions")
    include_hidden: bool = Field(False, description="Explicitly include dimensions hidden in CostFormation; omitted by default.")


class CloudZeroDimensionConfig(CloudZeroOperation):
    operation: Literal["get_dimension"] = _op("get_dimension", "Read One Dimension Metadata", "Dimensions")
    dimension_id: str = Field(..., title="Dimension", description="Exact dimension ID from the protected dimensions read, including dynamic CostFormation IDs.", json_schema_extra={"x-dynamic-options": {"field_name": "dimension_id", "searchable": True, "allow_custom": True, "placeholder": "Select an available dimension"}, "x-resource-type": "cloudzero_dimension", "x-resource-id-path": "dimension_id"})
    include_hidden: bool = Field(False, description="Include hidden dimensions in this lookup only when explicitly requested.")
    _dimension = field_validator("dimension_id")(_text)


class CloudZeroCostsConfig(CloudZeroOperation):
    operation: Literal["get_costs"] = _op("get_costs", "Read One Cost or Usage Page", "Costs")
    start_date: str = Field(..., title="Start Date", description="YYYY-MM-DD or ISO8601 date and time with explicit timezone; exact value is encoded by the HTTP client.")
    end_date: Optional[str] = Field(None, title="End Date", description="Omit for the documented current-time default. Native continuations retain the original cached query.")
    granularity: Literal["hourly", "daily", "weekly", "monthly", "yearly"] = "daily"
    group_by: list[str] = Field(default_factory=list, max_length=32, description="Dynamic dimension IDs; each sends a separate group_by query parameter. Use List Available Dimensions to discover current IDs.", json_schema_extra={"ui:widget": "list", "default": []})
    filters_json: Optional[str] = Field(None, max_length=65536, title="Dimension Filters (JSON)", description='Optional mapping of exact dimension IDs to string arrays, e.g. {"Region":["us-east-1"],"!Account":["123456789012"]}. Blank omits filters; ! negates a dimension.', json_schema_extra={"ui:widget": "textarea"})
    cost_type: Literal["billed_cost", "discounted_cost", "amortized_cost", "discounted_amortized_cost", "real_cost", "on_demand_cost", "invoiced_amortized_cost", "usage_amount"] = "real_cost"
    align_to_granularity: bool = Field(True, description="Provider default expands dates to period boundaries. False requests the exact date range.")
    include_projected_row_count: bool = Field(False, description="Include documented underlying-record count where supplied; omitted for hourly granularity.")
    page_token: Optional[str] = Field(None, max_length=8192, title="Next Page Token", description="Native token from this exact saved credential/query. Cost cache expires after 24 hours; no automatic rerun, retry or traversal.")
    confirm_query_quota: bool = Field(False, description="Confirm this cost query against the documented 60-query/day allowance and 30-second timeout. Cursor reads use the existing 24-hour cache and do not count as new queries. Account entitlement is unverified.")
    _start = field_validator("start_date")(_date)
    @field_validator("end_date")
    @classmethod
    def end(cls, value): return _date(value) if value is not None else None
    @field_validator("group_by")
    @classmethod
    def groups(cls, value):
        if len(set(value)) != len(value): raise ValueError("Group-by dimension IDs must be unique")
        for item in value:
            _text(item)
            if item in ("usage_date", "cost", "projected_row_count"): raise ValueError("A group-by ID cannot shadow core cost fields")
        return value
    @field_validator("filters_json")
    @classmethod
    def filters(cls, value): _filters(value); return value
    @model_validator(mode="after")
    def dates(self):
        if self.end_date and _instant(self.end_date) < _instant(self.start_date): raise ValueError("End date must not precede start date")
        return self


class CloudZeroViewsConfig(CloudZeroOperation):
    operation: Literal["list_views"] = _op("list_views", "List Saved View Metadata", "Views")
    limit: int = Field(100, ge=1, le=100, description="Local bounded page size; public API does not publish a maximum.")
    sort_order: Literal["asc", "desc"] = "asc"
    page_token: Optional[str] = Field(None, max_length=8192, title="Next Page Token", description="Native continuation bound to current credential and this page configuration.")
    include_filters: bool = Field(False, description="Opt in to private saved-view filter values. Email/Slack connections and unknown fields remain omitted.")
    _count = field_validator("limit", mode="before")(_whole)


class CloudZeroViewConfig(CloudZeroOperation):
    operation: Literal["get_view"] = _op("get_view", "Read Saved View Metadata", "Views")
    view_id: str = Field(..., title="Saved View", json_schema_extra={"x-dynamic-options": {"field_name": "view_id", "searchable": True, "allow_custom": True, "placeholder": "Select a saved view"}, "x-resource-type": "cloudzero_view", "x-resource-id-path": "view_id"})
    include_filters: bool = Field(False, description="Opt in to private dimension filter values. Notification destinations and connection details are never returned.")
    _id = field_validator("view_id")(_view_id)


CloudZeroConfig = Annotated[Union[CloudZeroCheckConfig, CloudZeroDimensionsConfig, CloudZeroDimensionConfig, CloudZeroCostsConfig, CloudZeroViewsConfig, CloudZeroViewConfig], Field(discriminator="operation")]


class CloudZeroNodeConfig(NodeConfig[CloudZeroConfig, CloudZeroAPIKeyCredential]):
    pass


class CloudZeroAPIError(ValueError):
    def __init__(self, message, *, authority_rejected=False, http_status=None):
        super().__init__(message)
        self.authority_rejected = authority_rejected
        self.http_status = http_status


def _shape(data):
    if not isinstance(data, dict) or data.get("credential_type", FAMILIES[0]) not in FAMILIES: raise ValueError("CloudZero credential family is unsupported")
    try: shaped = CloudZeroAPIKeyCredential.model_validate({**data, "credential_type": FAMILIES[0]}).model_dump()
    except ValueError: raise ValueError("CloudZero native credential is invalid") from None
    return {**data, **shaped}

def _binding(data):
    return (data["credential_type"], data["api_key"], data.get("owner_id"), data.get("token_version"), data.get("updated_at"), data.get("approval_revision"))

def _bound_matches(bound, current):
    return all(bound.get(key) == current.get(key) for key in ("credential_type", "api_key")) and all(bound[key] == current.get(key) for key in ("owner_id", "token_version", "updated_at", "approval_revision") if key in bound)

def _original_family(data):
    if not isinstance(data, dict):
        raise ValueError("CloudZero configuration is invalid")
    creds = data.get("credentials")
    saved = data.get("credential_id") or data.get("credentialIds")
    if saved and not isinstance(creds, dict) or isinstance(creds, dict) and (creds.get("credential_type") is not None or saved) and creds.get("credential_type") not in FAMILIES:
        raise ValueError("CloudZero saved credential family is missing or unsupported")


@dataclass(frozen=True, repr=False)
class _LookupAuthority:
    pool: Any
    user_id: str
    credential_id: str
    organization_id: Optional[str]
    workflow_id: Optional[str]


@dataclass(frozen=True, repr=False)
class _CredentialAuthority:
    credential_type: str
    owner_id: str
    token_version: int
    updated_at: Any
    approval_revision: int
    revoked_at: Any
    credential: str


async def _fetch_authority(pool, credential_id, user_id, organization_id):
    # CloudZero binds cached cursors to current authority using staging's ACL.
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT c.credential_type,c.owner_id,c.token_version,c.updated_at,"
            f"c.approval_revision,c.revoked_at,c.credential FROM credentials c "
            f"WHERE c.id=$1 AND {credential_access_predicate()}",
            credential_id, user_id, organization_id,
        )
    return _CredentialAuthority(
        row["credential_type"], str(row["owner_id"]), row["token_version"],
        row["updated_at"], row["approval_revision"], row["revoked_at"], row["credential"],
    ) if row else None


async def _current_data(data, *, pool=None, user_id=None, credential_id=None, organization_id=None, workflow_id=None):
    if not credential_id:
        return _shape(data)
    from utils.credentials import get_workflow_owner_id, is_credential_authorized_for_workflow, credential_lender
    from utils.encryption import get_encryption
    if pool is None:
        from utils.database_pool import get_native_pool
        pool = get_native_pool()
    if organization_id is None:
        from wss.handlers.workflow_handler import get_user_org_context
        async with pool.acquire() as conn:
            organization_id = await get_user_org_context(conn, user_id)
    async def load(cid, principal, actual_pool, org_id):
        row = await _fetch_authority(actual_pool, cid, principal, org_id)
        if row is None:
            return None
        if row.revoked_at is not None or row.credential_type not in FAMILIES or not isinstance(row.owner_id, str) or not row.owner_id or type(row.token_version) is not int or row.token_version < 1 or type(row.approval_revision) is not int or row.approval_revision < 0:
            raise ValueError("CloudZero current credential is unavailable, revoked or its family is unsupported")
        try:
            blob = get_encryption().decrypt_credential(row.credential)
        except Exception:
            raise ValueError("CloudZero current credential could not be decrypted") from None
        if not isinstance(blob, dict):
            raise ValueError("CloudZero current credential data is invalid")
        return _shape({**blob, "credential_type": row.credential_type, "owner_id": row.owner_id, "token_version": row.token_version, "updated_at": row.updated_at.isoformat() if row.updated_at else None, "approval_revision": row.approval_revision})
    result = await load(credential_id, user_id, pool, organization_id)
    if result is None and workflow_id:
        owner_id = await get_workflow_owner_id(pool, workflow_id)
        if owner_id and owner_id != user_id and await is_credential_authorized_for_workflow(pool, workflow_id, credential_id):
            result = await load(credential_id, owner_id, pool, organization_id)
    if result is None and workflow_id:
        lender = await credential_lender(pool, workflow_id, credential_id)
        if lender and lender != str(user_id):
            result = await load(credential_id, lender, pool, organization_id)
    if result is None:
        raise ValueError("CloudZero current credential is unavailable or access denied")
    return {**result, "_cloudzero_authority": _LookupAuthority(pool, user_id, credential_id, organization_id, workflow_id)}


def _context(data, context):
    result = {k: v for k, v in context.items() if not k.startswith("_")}
    result["_user_id"] = context.get("_user_id")
    bound = data.get("_cloudzero_authority") if isinstance(data, dict) else None
    if type(bound) is _LookupAuthority:
        if bound.user_id != context.get("_user_id"):
            raise ValueError("CloudZero picker actor does not match saved authority")
        result.update({"_approval_pool": bound.pool, "_user_id": bound.user_id, "_credential_id": bound.credential_id, "_organization_id": bound.organization_id, "_workflow_id": bound.workflow_id})
    return result


def _authority(context):
    return {"pool": context.get("_approval_pool"), "user_id": context.get("_user_id"), "credential_id": context.get("_credential_id"), "organization_id": context.get("_organization_id"), "workflow_id": context.get("_workflow_id")}


def _bounded(value, depth=0):
    if type(value) is int and value.bit_length() > 256:
        raise ValueError("Unverified JSON integer bound")
    if depth > 32 or isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Unverified JSON depth or non-finite number")
    if isinstance(value, dict):
        for key, child in value.items():
            if len(key) > 512:
                raise ValueError("Unverified JSON key")
            _bounded(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_ROWS:
            raise ValueError("Unverified JSON row bound")
        for child in value:
            _bounded(child, depth + 1)


def _redact(value, secret):
    if isinstance(value, str):
        variants = (secret, quote(secret, safe=""), quote_plus(secret, safe=""), base64.b64encode(secret.encode()).decode(), base64.b64encode((secret + ":").encode()).decode())
        for variant in variants:
            pattern = re.sub(r"%([0-9A-Fa-f]{2})", lambda m: '%' + ''.join('[' + c.lower() + c.upper() + ']' for c in m[1]), re.escape(variant))
            value = re.sub(pattern, "[redacted]", value)
        return re.sub(r"(?i)([?&](?:access_token|api_key|token|signature|auth|key)=)[^&#\s]+", r"[redacted]", value)
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


# Narrow reuse of utils.meta_subscriptions._TransportPrivacy: context-local
# masking leaves concurrent unrelated requests untouched and resets on failure.
_PRIVATE_REQUEST = ContextVar("cloudzero_private_request", default=False)


class _TransportPrivacy(logging.Filter):
    def filter(self, record):
        if _PRIVATE_REQUEST.get():
            record.msg, record.args = "CloudZero private transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_TRANSPORT_PRIVACY = _TransportPrivacy()


def _protect_transport_logs():
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.connection_pool", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"}
    names.update(name for name in tuple(logging.Logger.manager.loggerDict) if name.startswith(("httpx.", "httpcore.")))
    for name in names:
        logging.getLogger(name).addFilter(_TRANSPORT_PRIVACY)



def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")

def _pairs(items):
    result = {}
    for key, value in items:
        if key in result: raise ValueError("Duplicate JSON field")
        result[key] = value
    return result

def _parse_json(value):
    result = json.loads(value, object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    _bounded(result)
    return result

async def _stable(data, context):
    try: current = await _current_data(data, **_authority(context))
    except ValueError: raise CloudZeroAPIError("CloudZero current credential authority is unavailable or revoked", authority_rejected=True) from None
    if _binding(current) != _binding(data): raise CloudZeroAPIError("CloudZero current key, owner, version or approval revision changed; result is not accepted", authority_rejected=True)
    return current


def _opaque(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096 or any(ord(c) <= 32 or ord(c) >= 127 for c in value) or value.startswith(("http:", "https:")):
        raise ValueError("CloudZero cursor is outside the local opaque-text bound")
    return value


def _cursor_scope(data, context, route, query):
    return hashlib.sha256(_json([_binding(data), context.get("_credential_id"), context.get("_user_id"), context.get("_organization_id"), context.get("_workflow_id"), route, query])).hexdigest()


def _encode_cursor(data, context, route, query, cursor, seen, issued):
    payload = base64.urlsafe_b64encode(_json({"cursor": cursor, "seen": seen, "issued": issued, "scope": _cursor_scope(data, context, route, query)})).decode().rstrip("=")
    return payload + "." + hmac.new(data["api_key"].encode(), payload.encode(), hashlib.sha256).hexdigest()


def _decode_cursor(value, data, context, route, query):
    try:
        if not isinstance(value, str) or len(value) > 8192 or not re.fullmatch(r"[A-Za-z0-9_-]+\.[0-9a-f]{64}", value): raise ValueError()
        payload, signature = value.split(".")
        expected = hmac.new(data["api_key"].encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected): raise ValueError()
        decoded = _parse_json(base64.urlsafe_b64decode(payload + "="*((-len(payload)) % 4)))
        if not isinstance(decoded, dict) or set(decoded) != {"cursor", "seen", "issued", "scope"} or decoded["scope"] != _cursor_scope(data, context, route, query): raise ValueError()
        if type(decoded["seen"]) is not int or not 0 <= decoded["seen"] <= SAFE_INTEGER or type(decoded["issued"]) is not int or not 0 <= int(time.time()) - decoded["issued"] < 86400: raise ValueError()
        return _opaque(decoded["cursor"]), decoded["seen"], decoded["issued"]
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("CloudZero continuation expired or belongs to different key/current authority/query; no query rerun") from None


async def _request(data, context, route, *, params=None):
    if route not in ("/v2/billing/dimensions", "/v2/billing/costs", "/v2/views"):
        if not route.startswith("/v2/views/"): raise ValueError("Unsupported native CloudZero route")
        _view_id(route[len("/v2/views/"):])
    current = await _stable(data, context)
    _protect_transport_logs(); private_token = _PRIVATE_REQUEST.set(True)
    try:
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", BASE+route, params=params, headers={"Authorization": current["api_key"], "Accept": "application/json"}) as response:
                code = response.status_code
                # Keep the actual code typed; shared evidence text classifiers must
                # not turn this ambiguous scope/role/plan refusal into a key verdict.
                if code == 403: raise CloudZeroAPIError("CloudZero refused this protected read; key, scope, role and plan status remain unverified", http_status=403)
                if code == 410: raise CloudZeroAPIError("CloudZero cached query expired (HTTP410); no automatic query rerun")
                if code == 429: raise CloudZeroAPIError("CloudZero request quota or rate limit refused this read (HTTP429); no retry")
                if code != 200: raise CloudZeroAPIError("CloudZero returned HTTP"+str(code)+"; protected read is unverified")
                if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json": raise CloudZeroAPIError("CloudZero response is not documented JSON")
                chunks = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    chunks.extend(chunk)
                    if len(chunks) > MAX_BYTES: raise CloudZeroAPIError("CloudZero response exceeds the local 8MiB bound; no truncated success")
                try:
                    raw = _parse_json(chunks)
                    cursors = raw.get("pagination", {}).get("cursor", {}) if isinstance(raw, dict) and isinstance(raw.get("pagination"), dict) else {}
                    if isinstance(cursors, dict) and any(isinstance(v, str) and _redact(v, current["api_key"]) != v for v in cursors.values()): raise ValueError()
                    raw = _redact(raw, current["api_key"])
                except (ValueError, TypeError, UnicodeError, RecursionError): raise CloudZeroAPIError("CloudZero JSON or cursor metadata is unverified") from None
        await _stable(data, context)
        if not isinstance(raw, dict) or "error" in raw or raw.get("status") in ("error", "rejected", "pending_approval", "not_executed", "forbidden"):
            raise CloudZeroAPIError("CloudZero did not return a documented successful read envelope")
        return raw
    except CloudZeroAPIError: raise
    except Exception: raise CloudZeroAPIError("CloudZero transport did not establish a read result; no retry or query replay") from None
    finally: _PRIVATE_REQUEST.reset(private_token)


def _dimensions(raw):
    rows = raw.get("dimensions")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS: raise CloudZeroAPIError("CloudZero dimensions array is unverified")
    result = []; seen = set()
    for row in rows:
        if not isinstance(row, dict): raise CloudZeroAPIError("CloudZero dimension metadata is unverified")
        try: identifier = _text(row.get("id")); name = _text(row.get("name"), maximum=4096)
        except ValueError: raise CloudZeroAPIError("CloudZero dimension ID/name is unverified") from None
        if identifier in seen: raise CloudZeroAPIError("CloudZero returned duplicate dimension IDs")
        seen.add(identifier); result.append({"id": identifier, "name": name})
    return result


def _view(raw, *, expected=None, include_filters=False):
    if not isinstance(raw, dict): raise CloudZeroAPIError("CloudZero view metadata is unverified")
    try:
        identifier = _view_id(raw.get("id")); name = _text(raw.get("name"), maximum=4096); principal = _text(raw.get("principal_dimension"))
    except ValueError: raise CloudZeroAPIError("CloudZero view ID/name/principal dimension is unverified") from None
    stamp = raw.get("last_updated")
    if not isinstance(stamp, str) or not re.fullmatch(r"\d{1,16}(?:\.\d{1,12})?", stamp) or expected is not None and identifier != expected:
        raise CloudZeroAPIError("CloudZero returned another view or unverified update timestamp")
    result = {"id": identifier, "name": name, "principal_dimension": principal, "last_updated": stamp}
    if include_filters:
        value = raw.get("filter")
        if not isinstance(value, dict) or len(value) > 32: raise CloudZeroAPIError("CloudZero saved-view filter object is missing or exceeds the local bound")
        for key, values in value.items():
            if not isinstance(key, str) or not 1 <= len(key) <= 512 or any(ord(c) < 32 for c in key) or not isinstance(values, list) or len(values) > 100 or any(not isinstance(item, str) or len(item) > 4096 or '\x00' in item for item in values):
                raise CloudZeroAPIError("CloudZero saved-view filters are outside the published string-array shape or local bounds")
        result["filter"] = value
    return result


def _cost_rows(raw, cfg):
    rows = raw.get("costs")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS: raise CloudZeroAPIError("CloudZero cost page exceeds the documented 10000-row contract or lacks a costs array")
    result = []
    for row in rows:
        if not isinstance(row, dict): raise CloudZeroAPIError("CloudZero cost row is unverified")
        try: _response_date(row.get("usage_date"))
        except ValueError: raise CloudZeroAPIError("CloudZero usage date is unverified") from None
        cost = row.get("cost")
        if type(cost) not in (int, float) or not math.isfinite(cost): raise CloudZeroAPIError("CloudZero cost or usage amount is not finite numeric data")
        item = {"usage_date": row["usage_date"], "cost": cost}
        for dimension in cfg.group_by:
            if dimension in row:
                value = row[dimension]
                if value is not None and type(value) not in (str, int, float, bool): raise CloudZeroAPIError("CloudZero dynamic dimension column is outside the local scalar contract")
                if isinstance(value, str) and (len(value) > 4096 or '\x00' in value): raise CloudZeroAPIError("CloudZero dimension value exceeds the local text bound")
                item[dimension] = value
        if cfg.include_projected_row_count and "projected_row_count" in row:
            count = row["projected_row_count"]
            if type(count) is not int or not 0 <= count <= SAFE_INTEGER: raise CloudZeroAPIError("CloudZero projected record count is unverified")
            item["projected_row_count"] = count
        result.append(item)
    return result


def _pagination(raw, rows, data, context, route, query, *, seen=0, issued=None, previous=None):
    page = raw.get("pagination")
    if not isinstance(page, dict): raise CloudZeroAPIError("CloudZero paginated response lacks documented pagination")
    for key in ("page_count", "item_count", "total_count"):
        if type(page.get(key)) is not int or not 0 <= page[key] <= SAFE_INTEGER: raise CloudZeroAPIError("CloudZero pagination count is unverified")
    if page["item_count"] != len(rows) or page["total_count"] < seen+len(rows) or (page["page_count"] == 0 and (rows or page["total_count"])):
        raise CloudZeroAPIError("CloudZero pagination counts conflict with this observed page")
    cursor = page.get("cursor")
    if not isinstance(cursor, dict): raise CloudZeroAPIError("CloudZero pagination cursor object is missing")
    for flag, key in (("has_next", "next_cursor"), ("has_previous", "previous_cursor")):
        if type(cursor.get(flag)) is not bool or key not in cursor: raise CloudZeroAPIError("CloudZero cursor flags are unverified")
        value = cursor[key]
        if cursor[flag]:
            try: _opaque(value)
            except ValueError: raise CloudZeroAPIError("CloudZero returned cursor is unverified") from None
        elif value is not None: raise CloudZeroAPIError("CloudZero cursor and availability flag disagree")
    if cursor["has_next"] and (not rows or cursor["next_cursor"] == previous): raise CloudZeroAPIError("CloudZero next cursor did not advance; no page replay")
    if not cursor["has_next"] and page["total_count"] != seen+len(rows): raise CloudZeroAPIError("CloudZero exhaustion disagrees with the forward observed count")
    next_token = _encode_cursor(data, context, route, query, cursor["next_cursor"], seen+len(rows), issued if issued is not None else int(time.time())) if cursor["has_next"] else None
    return {"page_count": page["page_count"], "item_count": page["item_count"], "total_count": page["total_count"], "has_next": cursor["has_next"], "has_previous": cursor["has_previous"], "next_page_token": next_token, "provider_reported_complete": not cursor["has_next"], "observed_chain_count": seen+len(rows), "completion_scope": "provider-reported cached forward pages; no independent total-data audit", "one_page_only": True}


def _cost_query(cfg):
    params = [("start_date", cfg.start_date), ("granularity", cfg.granularity), ("cost_type", cfg.cost_type), ("align_to_granularity", str(cfg.align_to_granularity).lower()), ("include_projected_row_count", str(cfg.include_projected_row_count).lower())]
    if cfg.end_date is not None: params.append(("end_date", cfg.end_date))
    params += [("group_by", dimension) for dimension in cfg.group_by]
    filters = _filters(cfg.filters_json)
    if filters is not None: params.append(("filters", _json(filters).decode()))
    return params


async def _paged(data, context, route, query, token, projector):
    cursor, seen, issued = _decode_cursor(token, data, context, route, query) if token else (None, 0, int(time.time()))
    # Official pagination sends only cursor; cached query parameters are retained by the provider.
    params = [("cursor", cursor)] if cursor else query["params"]
    raw = await _request(data, context, route, params=params)
    rows = projector(raw)
    page = _pagination(raw, rows, data, context, route, query, seen=seen, issued=issued, previous=cursor)
    return rows, page


class CloudZeroNode(WorkflowNode):
    integration_type = "automation-cloudzero"
    credential_provider_labels = {"cloudzero": "Cloudzero Account"}
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="test_connection", noun="protected dimensions", proves="reachability", label_keys=("dimension_count",))
    edit_examples = ["Read monthly costs grouped by current dimensions", "List saved-view metadata without notification destinations", "Continue one cached cost page with the same query"]
    @classmethod
    def get_config_model(cls): return CloudZeroNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        _original_family(config_data); shaped = dict(config_data)
        if config_data.get("credentials") is not None: shaped["credentials"] = _shape(config_data["credentials"])
        try: CloudZeroNodeConfig.model_validate(runtime_config_view(shaped, CloudZeroNodeConfig))
        except ValueError: raise ValueError("CloudZero native configuration, date/filter scope or credential is invalid") from None
        return super().parse_config(shaped)
    @classmethod
    def validate_config(cls, config_data):
        try:
            _original_family(config_data); shaped = dict(config_data)
            if config_data.get("credentials") is not None: shaped["credentials"] = _shape(config_data["credentials"])
            CloudZeroNodeConfig.model_validate(runtime_config_view(shaped, CloudZeroNodeConfig))
        except (ValueError, TypeError): return ValidationResult(valid=False, errors=["CloudZero native configuration or credential family is invalid"], satisfied_set=None)
        return super().validate_config(shaped)
    @classmethod
    async def freshen_credential(
        cls,
        credential_data: Optional[Dict[str, Any]],
        *,
        pool=None,
        user_id: Optional[str] = None,
        credential_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        return await _current_data(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id
        )
    @classmethod
    async def validate_credential_access(cls, data):
        # Staging's legacy hook supplies a blob without trusted saved-row context.
        # The declared connection evidence runs the protected native operation.
        return {"valid": None, "error": "Use the protected dimensions read to verify CloudZero reachability"}
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, CloudZeroNodeConfig) or self.config.credentials is None: raise ValueError("CloudZero requires an existing native API key")
        cfg = self.config.config
        if cfg.operation == "get_costs" and not cfg.confirm_query_quota: raise ValueError("Confirm the documented cost-query allowance before transport")
        node_data = self.node_data or {}; raw = node_data.get("credentials")
        data = _shape(raw if isinstance(raw, dict) else self.config.credentials.model_dump())
        context = {"_approval_pool": node_data.get("_approval_pool"), "_credential_id": node_data.get("credential_id"), "_user_id": self.user_id, "_organization_id": self.organization_id, "_workflow_id": self.workflow_id}
        current = await _current_data(data, **_authority(context))
        if node_data.get("credential_id") and not _bound_matches(data, current): raise CloudZeroAPIError("CloudZero saved-row binding changed before transport", authority_rejected=True)
        result = await self._operation(cfg, current, context)
        await _stable(current, context)
        return {"status": "success", "operation": cfg.operation, "data": result}
    @staticmethod
    async def _operation(cfg, data, context):
        if cfg.operation in ("test_connection", "list_dimensions", "get_dimension"):
            rows = _dimensions(await _request(data, context, "/v2/billing/dimensions", params=[("include_hidden", str(getattr(cfg, "include_hidden", False)).lower())]))
            common = {"account_identity_verified": False, "protected_read_completed": True, "dimension_count": len(rows)}
            if cfg.operation == "test_connection": return {**common, "results": [{"dimension_count": len(rows)}], "cost_view_permissions_verified": False, "entitlement_verified": False}
            if cfg.operation == "get_dimension":
                found = next((row for row in rows if row["id"] == cfg.dimension_id), None)
                if found is None: raise CloudZeroAPIError("CloudZero selected dimension is absent from the protected include-hidden scope")
                return {**common, "dimension": found, "returned_dimension_id_verified": True}
            return {**common, "dimensions": rows, "include_hidden": cfg.include_hidden, "unpaged_array_observed": True}
        if cfg.operation == "get_costs":
            if not cfg.confirm_query_quota: raise ValueError("Confirm the documented cost-query allowance before transport")
            query = {"params": _cost_query(cfg)}
            rows, page = await _paged(data, context, "/v2/billing/costs", query, cfg.page_token, lambda raw: _cost_rows(raw, cfg))
            return {"costs": rows, "pagination": page, "next_page_token": page["next_page_token"], "group_by": cfg.group_by, "cost_type": cfg.cost_type, "account_identity_verified": False, "quota_terms": "60 new queries/day; cursor pages use a static 24-hour cache", "entitlement_verified": False, "currency_verified": False}
        if cfg.operation == "list_views":
            query = {"params": [("limit", str(cfg.limit)), ("sort_key", "last_updated"), ("sort_order", cfg.sort_order)], "include_filters": cfg.include_filters}
            def project(raw):
                rows = raw.get("views")
                if not isinstance(rows, list) or len(rows) > cfg.limit: raise CloudZeroAPIError("CloudZero saved-view page is unverified")
                result = [_view(row, include_filters=cfg.include_filters) for row in rows]
                if len({r["id"] for r in result}) != len(result): raise CloudZeroAPIError("CloudZero returned duplicate view IDs")
                return result
            rows, page = await _paged(data, context, "/v2/views", query, cfg.page_token, project)
            return {"views": rows, "pagination": page, "next_page_token": page["next_page_token"], "account_identity_verified": False, "notification_destinations_omitted": True}
        if cfg.operation == "get_view":
            raw = await _request(data, context, "/v2/views/"+cfg.view_id)
            return {"view": _view(raw.get("view"), expected=cfg.view_id, include_filters=cfg.include_filters), "returned_view_id_verified": True, "account_identity_verified": False, "notification_destinations_omitted": True}
        raise ValueError("Unsupported native CloudZero operation")
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        if field_name not in ("dimension_id", "view_id"): return {"options": [], "next_page_token": None}
        context = _context(credential_data, context or {}); data = await _current_data(credential_data, **_authority(context))
        if search is not None and search != "": _text(search)
        if field_name == "dimension_id":
            if page_token: raise ValueError("CloudZero dimensions are an unpaged documented array")
            include = context.get("include_hidden", False)
            if type(include) is not bool: raise ValueError("Include-hidden picker scope must be boolean")
            rows = _dimensions(await _request(data, context, "/v2/billing/dimensions", params=[("include_hidden", str(include).lower())])); next_token = None
        else:
            query = {"params": [("limit", "100"), ("sort_key", "last_updated"), ("sort_order", "asc")], "picker_search": search or ""}
            def project(raw):
                values = raw.get("views")
                if not isinstance(values, list) or len(values) > 100: raise CloudZeroAPIError("CloudZero saved-view picker page is unverified")
                selected = [_view(value) for value in values]
                if len({r["id"] for r in selected}) != len(selected): raise CloudZeroAPIError("CloudZero returned duplicate view IDs")
                return selected
            rows, page = await _paged(data, context, "/v2/views", query, page_token, project)
            next_token = page["next_page_token"]
        await _stable(data, context)
        if search: rows = [row for row in rows if search.casefold() in (row["id"]+" "+row["name"]).casefold()]
        return {"options": [{"value": row["id"], "label": row["name"]+" ("+row["id"]+")"} for row in rows], "next_page_token": next_token}
