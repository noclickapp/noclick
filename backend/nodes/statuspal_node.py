"""StatusPal v2 protected organization status-page and service metadata reads."""
from __future__ import annotations
import base64
import json
import logging
import math
import re
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote, quote_plus
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, ValidationResult, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-statuspal"
FAMILIES = ("statuspal_api_key",)
BASES = {"us": "https://statuspal.io/api/v2", "eu": "https://statuspal.eu/api/v2"}
MAX_BYTES = 4 * 1024 * 1024
MAX_ROWS = 1000
SAFE_INTEGER = 9007199254740991

def _token(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096 or any(ord(c) <= 32 or ord(c) >= 127 for c in value): raise ValueError("Supply an existing opaque StatusPal API key without a Bearer prefix")
    return value

def _whole(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,16}", value): value = int(value)
    if type(value) is not int: raise ValueError("Supply a whole resource ID")
    return value

def _id(value):
    value = _whole(value)
    if not 1 <= value <= SAFE_INTEGER: raise ValueError("Unverified positive StatusPal resource ID")
    return value

def _subdomain(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value): raise ValueError("Supply the exact status-page subdomain label, not a hostname or URL")
    return value

def _text(value):
    if not isinstance(value, str) or not value or len(value) > 256 or any(ord(c) < 32 for c in value): raise ValueError("Unverified bounded metadata text")
    return value

def _date(value):
    if not isinstance(value, str) or len(value) > 64 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})?", value): raise ValueError("Unverified StatusPal ISO date-time")
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value  # Current introduction documents UTC; retain actual representation.

class StatusPalAPIKeyCredential(BaseModel):
    credential_type: Literal["statuspal_api_key"] = Field("statuspal_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Existing StatusPal API Key", json_schema_extra={"ui:widget": "password"})
    region: Literal["us", "eu"] = Field("us", title="StatusPal Region", description="Fixed US statuspal.io or EU statuspal.eu API host. No arbitrary URL.")
    organization_id: int = Field(..., ge=1, le=SAFE_INTEGER, title="Selected StatusPal Organization ID", description="Existing organization numeric ID used for protected page catalog/detail. Resource reachability is not organization ownership.")
    model_config = ConfigDict(extra="ignore", json_schema_extra={
        "x-credential-url": "https://docs.statuspal.io/platform/api-reference/authentication",
        "x-credential-instructions": "Supply an existing API key, region and selected organization ID. Authorization contains the raw key, without Bearer. Only protected organization status-page/service reads are exposed. Parsed catalog access, including an empty page, proves reachability; it does not identify a principal or prove organization ownership, all permissions, plan or private access. No key creation/exchange/refresh or environment fallback.",
    })
    _key = field_validator("api_key")(_token)
    _org = field_validator("organization_id", mode="before")(_whole)

def _op(name, label, category):
    return Field(name, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})

def _resource(field, kind, parent=None):
    options = {"field_name": field, "searchable": True, "allow_custom": True}
    if parent: options["depends_on"] = parent
    return {"x-dynamic-options": options, "x-resource-type": kind, "x-resource-id-path": field}

class StatusPalOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

class StatusPalCheckConfig(StatusPalOperation):
    operation: Literal["test_connection"] = _op("test_connection", "Check Selected Organization Catalog Read Access", "Connection")

class StatusPalNames(StatusPalOperation):
    include_names: bool = Field(False, description="Opt in to page/service name text. Domains, descriptions, recipients, monitoring configuration, keys, URLs and capabilities are always omitted.")

class StatusPalPagesConfig(StatusPalNames):
    operation: Literal["list_status_pages"] = _op("list_status_pages", "List Organization Status-Page Metadata", "Status Pages")

class StatusPalPageScope(StatusPalNames):
    subdomain: str = Field(..., title="Status Page Subdomain", description="Exact page label under the credential's selected organization. Picker observes one bounded page only; completion is unknown. Paste exact owned label if absent.", json_schema_extra=_resource("subdomain", "statuspal_status_page"))
    _page = field_validator("subdomain")(_subdomain)

class StatusPalPageConfig(StatusPalPageScope):
    operation: Literal["get_status_page"] = _op("get_status_page", "Read Selected Status-Page Metadata", "Status Pages")

class StatusPalServicesConfig(StatusPalPageScope):
    operation: Literal["list_services"] = _op("list_services", "List Selected Page Service Metadata", "Services")

class StatusPalServiceConfig(StatusPalPageScope):
    operation: Literal["get_service"] = _op("get_service", "Read Selected Service Metadata", "Services")
    service_id: int = Field(..., ge=1, le=SAFE_INTEGER, title="Service", description="Exact returned service ID in the scoped page route. Service.parent_id means service hierarchy, not a status-page or organization ID.", json_schema_extra=_resource("service_id", "statuspal_service", "subdomain"))
    _service = field_validator("service_id", mode="before")(_whole)

StatusPalConfig = Annotated[Union[StatusPalCheckConfig, StatusPalPagesConfig, StatusPalPageConfig, StatusPalServicesConfig, StatusPalServiceConfig], Field(discriminator="operation")]
class StatusPalNodeConfig(NodeConfig[StatusPalConfig, StatusPalAPIKeyCredential]):
    pass

class StatusPalMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

class StatusPalPageMetadata(StatusPalMetadata):
    organization_id: int
    subdomain: str
    time_zone: Optional[str] = None
    inserted_at: Optional[str] = None
    updated_at: Optional[str] = None
    name: Optional[str] = None

class StatusPalServiceMetadata(StatusPalMetadata):
    id: int
    parent_id: Optional[int] = None
    children_ids: Optional[list[int]] = None
    current_incident_type: Optional[Literal["major", "minor", "scheduled"]] = None
    is_up: Optional[bool] = None
    name: Optional[str] = None

class StatusPalPageObservation(StatusPalMetadata):
    returned_count: int
    provider_total_count: int
    provider_reports_next: Optional[bool] = None
    one_page_only: Literal[True] = True
    completion_verified: Literal[False] = False
    continuation_supported: Literal[False] = False
    returned_links_followed: Literal[False] = False

class StatusPalAPIError(ValueError):
    def __init__(self, message, *, authority_rejected=False, http_status=None):
        super().__init__(message)
        self.authority_rejected = authority_rejected
        self.http_status = http_status
def _shape(data):
    if not isinstance(data, dict) or data.get("credential_type", FAMILIES[0]) not in FAMILIES: raise ValueError("StatusPal credential family is unsupported")
    try: shaped = StatusPalAPIKeyCredential.model_validate({**data, "credential_type": FAMILIES[0]}).model_dump()
    except ValueError: raise ValueError("StatusPal native credential is invalid") from None
    return {**data, **shaped}

def _binding(data):
    return (data["credential_type"], data["api_key"], data["region"], data["organization_id"], data.get("owner_id"), data.get("token_version"), data.get("updated_at"), data.get("approval_revision"))

def _bound_matches(bound, current):
    return all(bound.get(key) == current.get(key) for key in ("credential_type", "api_key", "region", "organization_id")) and all(bound[key] == current.get(key) for key in ("owner_id", "token_version", "updated_at", "approval_revision") if key in bound)

def _original_family(data):
    if not isinstance(data, dict):
        raise ValueError("StatusPal configuration is invalid")
    creds = data.get("credentials")
    saved = data.get("credential_id") or data.get("credentialIds")
    if saved and not isinstance(creds, dict) or isinstance(creds, dict) and (creds.get("credential_type") is not None or saved) and creds.get("credential_type") not in FAMILIES:
        raise ValueError("StatusPal saved credential family is missing or unsupported")


@dataclass(frozen=True, repr=False)
class _LookupAuthority:
    pool: Any
    user_id: str
    credential_id: str
    organization_id: Optional[str]
    workflow_id: Optional[str]


async def _current_data(data, *, pool=None, user_id=None, credential_id=None, organization_id=None, workflow_id=None):
    if not credential_id:
        return _shape(data)
    from nodes.statuspal_authority import StatusPalCredentialsRepo
    from utils.encryption import get_encryption
    if pool is None:
        from utils.database_pool import get_native_pool
        pool = get_native_pool()
    if organization_id is None:
        from wss.handlers.workflow_handler import get_user_org_context
        async with pool.acquire() as conn:
            organization_id = await get_user_org_context(conn, user_id)
    async def load(cid, principal, actual_pool, org_id):
        row = await StatusPalCredentialsRepo(actual_pool).fetch_validation_authority(cid, principal, org_id)
        if row is None:
            return None
        if row.revoked_at is not None or row.credential_type not in FAMILIES or not isinstance(row.owner_id, str) or not row.owner_id or type(row.token_version) is not int or row.token_version < 1 or type(row.approval_revision) is not int or row.approval_revision < 0:
            raise ValueError("StatusPal current credential is unavailable, revoked or its family is unsupported")
        try:
            blob = get_encryption().decrypt_credential(row.credential)
        except Exception:
            raise ValueError("StatusPal current credential could not be decrypted") from None
        if not isinstance(blob, dict):
            raise ValueError("StatusPal current credential data is invalid")
        return _shape({**blob, "credential_type": row.credential_type, "owner_id": row.owner_id, "token_version": row.token_version, "updated_at": row.updated_at.isoformat() if row.updated_at else None, "approval_revision": row.approval_revision})
    from utils.credentials import (get_workflow_owner_id,
        is_credential_authorized_for_workflow, credential_lender)
    result = await load(credential_id, user_id, pool, organization_id)
    if result is None and workflow_id:
        owner = await get_workflow_owner_id(pool, workflow_id)
        if (owner and owner != user_id and
                await is_credential_authorized_for_workflow(pool, workflow_id, credential_id)):
            result = await load(credential_id, owner, pool, organization_id)
        if result is None:
            lender = await credential_lender(pool, workflow_id, credential_id)
            if lender and lender != str(user_id):
                result = await load(credential_id, lender, pool, organization_id)
    if result is None:
        raise ValueError("StatusPal current credential is unavailable or access denied")
    return {**result, "_statuspal_authority": _LookupAuthority(pool, user_id, credential_id, organization_id, workflow_id)}


def _context(data, context):
    result = {k: v for k, v in context.items() if not k.startswith("_")}
    result["_user_id"] = context.get("_user_id")
    bound = data.get("_statuspal_authority") if isinstance(data, dict) else None
    if type(bound) is _LookupAuthority:
        if bound.user_id != context.get("_user_id"):
            raise ValueError("StatusPal picker actor does not match saved authority")
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
        return re.sub(r"(?i)([?&](?:access_token|api_key|api_key|auth_token|token|signature|auth|key)=)[^&#\s]+", r"[redacted]", value)
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


# Narrow reuse of utils.meta_subscriptions._TransportPrivacy: context-local
# masking leaves concurrent unrelated requests untouched and resets on failure.
_PRIVATE_REQUEST = ContextVar("statuspal_private_request", default=False)


class _TransportPrivacy(logging.Filter):
    def filter(self, record):
        if _PRIVATE_REQUEST.get():
            record.msg, record.args = "StatusPal private transport activity", ()
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
    except ValueError: raise StatusPalAPIError("StatusPal current credential authority is unavailable or revoked", authority_rejected=True) from None
    if _binding(current) != _binding(data): raise StatusPalAPIError("StatusPal current key, owner, version or approval revision changed; result is not accepted", authority_rejected=True)
    return current



async def _request(data, context, route):
    org = str(data["organization_id"])
    if not (route == "/orgs/" + org + "/status_pages" or re.fullmatch(r"/orgs/" + org + r"/status_pages/[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", route) or re.fullmatch(r"/status_pages/[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?/services(?:/[1-9][0-9]{0,15})?", route)):
        raise ValueError("Unsupported native StatusPal protected GET route")
    current = await _stable(data, context)
    _protect_transport_logs(); private_token = _PRIVATE_REQUEST.set(True)
    try:
        try:
            async with guarded_async_client(timeout=20.0, follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", BASES[current["region"]] + route, headers={"Authorization": current["api_key"], "Accept": "application/json", "Content-Type": "application/json"}) as response:
                    code = response.status_code
                    if code == 403: raise StatusPalAPIError("StatusPal refused the protected read; key, role, plan or resource cause remains unverified", http_status=403)
                    if code == 429: raise StatusPalAPIError("StatusPal rate limit refused this read; no retry", http_status=429)
                    if code != 200: raise StatusPalAPIError("StatusPal returned HTTP" + str(code) + "; protected read is unverified", http_status=code)
                    if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json": raise StatusPalAPIError("StatusPal response is not documented JSON")
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        chunks.extend(chunk)
                        if len(chunks) > MAX_BYTES: raise StatusPalAPIError("StatusPal response exceeds local4MiB bound; no truncated success")
                    try: raw = _redact(_parse_json(bytes(chunks).decode("utf-8")), current["api_key"])
                    except (ValueError, TypeError, UnicodeError, RecursionError): raise StatusPalAPIError("StatusPal JSON metadata is unverified") from None
        finally: await _stable(data, context)
        if not isinstance(raw, dict) or raw.get("error") is not None or raw.get("errors") is not None or raw.get("status") in ("error", "rejected", "pending_approval", "not_executed", "forbidden"):
            raise StatusPalAPIError("StatusPal did not return a documented successful protected resource envelope")
        return raw
    except StatusPalAPIError: raise
    except Exception: raise StatusPalAPIError("StatusPal transport did not establish a protected read result; no retry") from None
    finally: _PRIVATE_REQUEST.reset(private_token)

def _page_metadata(raw, organization_id, *, expected=None, include_names=False):
    try:
        if not isinstance(raw, dict) or type(raw.get("organization_id")) is not int or _id(raw["organization_id"]) != organization_id: raise ValueError()
        subdomain = _subdomain(raw.get("subdomain"))
        if expected is not None and subdomain != expected: raise ValueError()
        timezone = _text(raw.get("time_zone"))
        if not re.fullmatch(r"[A-Za-z0-9/_+-]{1,128}", timezone): raise ValueError()
        item = {"organization_id": organization_id, "subdomain": subdomain, "time_zone": timezone}
        for key in ("inserted_at", "updated_at"):
            if key in raw and raw[key] is not None: item[key] = _date(raw[key])
        if include_names and "name" in raw: item["name"] = _text(raw["name"])
        return StatusPalPageMetadata.model_validate(item).model_dump(exclude_none=True)
    except (ValueError, TypeError): raise StatusPalAPIError("StatusPal returned another organization/subdomain or unverified page metadata") from None

def _service_metadata(raw, *, expected=None, include_names=False):
    try:
        if not isinstance(raw, dict) or type(raw.get("id")) is not int: raise ValueError()
        identifier = _id(raw["id"])
        if expected is not None and identifier != expected: raise ValueError()
        item = {"id": identifier}
        if "parent_id" in raw and raw["parent_id"] is not None:
            if type(raw["parent_id"]) is not int or _id(raw["parent_id"]) == identifier: raise ValueError()
            item["parent_id"] = raw["parent_id"]
        if "children_ids" in raw:
            children = raw["children_ids"]
            if not isinstance(children, list) or len(children) > MAX_ROWS or any(type(v) is not int or _id(v) == identifier for v in children) or len(set(children)) != len(children): raise ValueError()
            item["children_ids"] = children
        if "current_incident_type" in raw and raw["current_incident_type"] is not None:
            if raw["current_incident_type"] not in ("major", "minor", "scheduled"): raise ValueError()
            item["current_incident_type"] = raw["current_incident_type"]
        if "is_up" in raw:
            if type(raw["is_up"]) is not bool: raise ValueError()
            item["is_up"] = raw["is_up"]
        if include_names and "name" in raw: item["name"] = _text(raw["name"])
        return StatusPalServiceMetadata.model_validate(item).model_dump(exclude_none=True)
    except (ValueError, TypeError): raise StatusPalAPIError("StatusPal returned another service ID or unverified hierarchy/state metadata") from None

def _envelope(raw, key):
    rows, meta, links = raw.get(key), raw.get("meta"), raw.get("links")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS or not isinstance(meta, dict) or not isinstance(links, dict): raise StatusPalAPIError("StatusPal collection wrapper/meta/links is unverified")
    total = meta.get("total_count")
    if type(total) is not int or not len(rows) <= total <= SAFE_INTEGER: raise StatusPalAPIError("StatusPal total_count conflicts with observed rows")
    for name in ("next", "prev"):
        if name in links and links[name] is not None and (not isinstance(links[name], str) or not links[name] or len(links[name]) > 8192): raise StatusPalAPIError("StatusPal returned an unverified pagination-link shape")
    if total == 0 and links.get("next"): raise StatusPalAPIError("StatusPal empty catalog conflicts with next-page metadata")
    observation = StatusPalPageObservation(returned_count=len(rows), provider_total_count=total, provider_reports_next=(bool(links["next"]) if "next" in links else None)).model_dump(exclude_none=True)
    return rows, observation

async def _page_witness(data, context, subdomain, *, include_names=False):
    subdomain = _subdomain(subdomain)
    raw = await _request(data, context, "/orgs/" + str(data["organization_id"]) + "/status_pages/" + subdomain)
    return _page_metadata(raw.get("status_page"), data["organization_id"], expected=subdomain, include_names=include_names)

async def _catalog(data, context, cfg):
    services = cfg.operation == "list_services"
    before = await _page_witness(data, context, cfg.subdomain) if services else None
    route = "/status_pages/" + cfg.subdomain + "/services" if services else "/orgs/" + str(data["organization_id"]) + "/status_pages"
    raw = await _request(data, context, route)
    rows, observation = _envelope(raw, "services" if services else "status_pages")
    items = [_service_metadata(row, include_names=cfg.include_names) if services else _page_metadata(row, data["organization_id"], include_names=cfg.include_names) for row in rows]
    key = "id" if services else "subdomain"
    if len({item[key] for item in items}) != len(items): raise StatusPalAPIError("StatusPal repeats a resource identifier in the observed page")
    if services:
        by_id = {item["id"]: item for item in items}
        for item in items:
            parent = by_id.get(item.get("parent_id"))
            if parent is not None and "children_ids" in parent and item["id"] not in parent["children_ids"]: raise StatusPalAPIError("StatusPal observed service hierarchy is inconsistent")
            for child_id in item.get("children_ids", []):
                child = by_id.get(child_id)
                if child is not None and "parent_id" in child and child["parent_id"] != item["id"]: raise StatusPalAPIError("StatusPal observed service hierarchy is inconsistent")
        after = await _page_witness(data, context, cfg.subdomain)
        if (after["organization_id"], after["subdomain"]) != (before["organization_id"], before["subdomain"]): raise StatusPalAPIError("StatusPal selected page scope changed around service read")
    await _stable(data, context)
    return items, observation

class StatusPalNode(WorkflowNode):
    integration_type = "automation-statuspal"
    credential_provider_labels = {"statuspal": "Statuspal Account"}
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="test_connection", noun="StatusPal selected organization catalog read access", proves="reachability", label_keys=("subdomain",))
    edit_examples = ["Read organization status-page identifiers/time zones without DNS settings", "Read service state/hierarchy under a protected selected page", "Observe one bounded page without following returned links"]
    @classmethod
    def get_config_model(cls): return StatusPalNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        _original_family(config_data); shaped = dict(config_data)
        if config_data.get("credentials") is not None: shaped["credentials"] = _shape(config_data["credentials"])
        try: StatusPalNodeConfig.model_validate(runtime_config_view(shaped, StatusPalNodeConfig))
        except ValueError: raise ValueError("StatusPal native configuration, page scope or credential is invalid") from None
        return super().parse_config(shaped)
    @classmethod
    def validate_config(cls, config_data):
        try:
            _original_family(config_data); shaped = dict(config_data)
            if config_data.get("credentials") is not None: shaped["credentials"] = _shape(config_data["credentials"])
            StatusPalNodeConfig.model_validate(runtime_config_view(shaped, StatusPalNodeConfig))
        except (ValueError, TypeError): return ValidationResult(valid=False, errors=["StatusPal native configuration or credential family is invalid"], satisfied_set=None)
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
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
        )
    @classmethod
    async def validate_credential_access(cls, data):
        try: _shape(data)
        except ValueError: return {"valid": False, "error": "Complete the native StatusPal credential form"}
        # Staging's post-connect hook has no trusted saved-row context. The
        # registered connection-evidence operation performs the protected probe.
        return {"valid": None, "error": "Save and check current StatusPal catalog read access"}
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, StatusPalNodeConfig) or self.config.credentials is None: raise ValueError("StatusPal requires an existing native API key and selected organization")
        node_data = self.node_data or {}; raw = node_data.get("credentials")
        data = _shape(raw if isinstance(raw, dict) else self.config.credentials.model_dump())
        context = {"_approval_pool": node_data.get("_approval_pool"), "_credential_id": node_data.get("credential_id"), "_user_id": self.user_id, "_organization_id": self.organization_id, "_workflow_id": self.workflow_id}
        current = await _current_data(data, **_authority(context))
        if node_data.get("credential_id") and not _bound_matches(data, current): raise StatusPalAPIError("StatusPal saved-row key/region/organization binding changed before transport", authority_rejected=True)
        result = await self._operation(self.config.config, current, context); await _stable(current, context)
        return {"status": "success", "operation": self.config.config.operation, "data": result}
    @staticmethod
    async def _operation(cfg, data, context):
        common = {"account_identity_verified": False, "user_identity_verified": False, "organization_ownership_verified": False, "private_configuration_fields_omitted": True, "requested_organization_id": data["organization_id"]}
        if cfg.operation == "test_connection":
            rows, observation = await _catalog(data, context, StatusPalPagesConfig())
            return {**common, "results": rows, "returned_count": len(rows), "pagination": observation, "protected_read_completed": True, "all_permissions_verified": False, "entitlement_verified": False, "proves": "reachability"}
        if cfg.operation in ("list_status_pages", "list_services"):
            rows, observation = await _catalog(data, context, cfg)
            return {**common, "services" if cfg.operation == "list_services" else "status_pages": rows, "pagination": observation, "names_included": cfg.include_names, **({"subdomain": cfg.subdomain, "protected_page_scope_verified": True, "service_page_id_returned": False} if cfg.operation == "list_services" else {})}
        if cfg.operation == "get_status_page":
            item = await _page_witness(data, context, cfg.subdomain, include_names=cfg.include_names)
            return {**common, "status_page": item, "returned_organization_and_subdomain_verified": True, "names_included": cfg.include_names}
        before = await _page_witness(data, context, cfg.subdomain)
        raw = await _request(data, context, "/status_pages/" + cfg.subdomain + "/services/" + str(cfg.service_id))
        item = _service_metadata(raw.get("service"), expected=cfg.service_id, include_names=cfg.include_names)
        after = await _page_witness(data, context, cfg.subdomain)
        if (after["organization_id"], after["subdomain"]) != (before["organization_id"], before["subdomain"]): raise StatusPalAPIError("StatusPal selected page scope changed around service read")
        return {**common, "service": item, "subdomain": cfg.subdomain, "protected_page_scope_verified": True, "returned_service_id_verified": True, "service_page_id_returned": False, "names_included": cfg.include_names}
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        if field_name not in ("subdomain", "service_id"): return {"options": [], "next_page_token": None}
        if page_token is not None: raise ValueError("StatusPal request continuation contract is unspecified; no cursor/URL transport")
        context = _context(credential_data, context or {})
        if search not in (None, "") and (not isinstance(search, str) or len(search) > 63 or not re.fullmatch(r"[a-z0-9-]+", search)): raise ValueError("StatusPal picker search supports bounded local subdomain/ID characters only")
        data = await _current_data(credential_data, **_authority(context))
        if context.get("_credential_id") and not _bound_matches(credential_data, data): raise StatusPalAPIError("StatusPal picker saved-row key/region/organization binding changed", authority_rejected=True)
        cfg = StatusPalPagesConfig() if field_name == "subdomain" else StatusPalServicesConfig(subdomain=_subdomain(context.get("subdomain")))
        rows, observation = await _catalog(data, context, cfg)
        if observation.get("provider_reports_next") or observation["provider_total_count"] > len(rows): raise StatusPalAPIError("StatusPal bounded picker observed an incomplete catalog; remaining matches are unknown, supply exact owned subdomain/ID")
        key = "subdomain" if field_name == "subdomain" else "id"
        if search: rows = [row for row in rows if search in str(row[key])]
        await _stable(data, context)
        return {"options": [{"value": str(row[key]), "label": str(row[key])} for row in rows], "next_page_token": None}
