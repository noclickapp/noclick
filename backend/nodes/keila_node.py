"""Keila project-context campaign and template metadata reads.

The supplied key remains bound to one public HTTPS instance. Message content,
contacts, sender configuration and all control/write operations are excluded.
"""
from __future__ import annotations
import base64
import json
import logging
import math
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote, quote_plus, urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, ValidationResult, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-keila"
FAMILIES = ("keila_api_key",)
MAX_BYTES = 4 * 1024 * 1024
MAX_ROWS = 1000
MAX_OUTPUT = 100
SAFE_INTEGER = 9007199254740991
ID_PATTERN = r"[A-Za-z0-9_-]{1,128}"
LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"

def _key(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 8192 or any(ord(c) <= 32 or ord(c) >= 127 for c in value): raise ValueError("Supply an existing private Keila API key without a Bearer prefix")
    return value

def _origin(value):
    try:
        if not isinstance(value, str) or len(value) > 270: raise ValueError()
        p = urlsplit(value); host = p.hostname
        if p.scheme != "https" or p.username is not None or p.password is not None or p.port not in (None, 443) or p.path not in ("", "/") or p.query or p.fragment: raise ValueError()
        if not isinstance(host, str) or len(host) > 253 or not re.fullmatch(LABEL + r"(?:\." + LABEL + r")+", host) or re.fullmatch(r"[0-9.]+", host) or host.endswith((".localhost", ".local", ".internal", ".lan")) or host in ("keila.io", "www.keila.io"): raise ValueError()
        return "https://" + host
    except ValueError: raise ValueError("Supply one public HTTPS Keila instance origin without a path, IP, credentials, query or alternate port") from None

def _id(value):
    if not isinstance(value, str) or not re.fullmatch(ID_PATTERN, value): raise ValueError("Supply a bounded opaque Keila resource ID, not a URL or path")
    return value

def _integer(value, minimum=0, maximum=SAFE_INTEGER):
    if type(value) is not int or not minimum <= value <= maximum: raise ValueError("Unverified bounded Keila integer")
    return value

def _limit(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,3}", value): value = int(value)
    return _integer(value, 1, MAX_OUTPUT)

def _text(value, maximum=256):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value): raise ValueError("Unverified bounded Keila text")
    return value

class KeilaAPIKeyCredential(BaseModel):
    credential_type: Literal["keila_api_key"] = Field("keila_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Existing Keila Private API Key", json_schema_extra={"ui:widget": "password"})
    instance_origin: str = Field(..., title="Keila Instance Origin", description="One public HTTPS origin, such as Keila Cloud or an existing self-hosted instance. No API path. Self-hosted version parity is unverified.")
    model_config = ConfigDict(extra="ignore", json_schema_extra={"x-credential-url": "https://www.keila.io/docs/api/authentication/", "x-credential-instructions": "Supply an existing private API key. Bearer HEADER only on one public HTTPS instance and fixed /api/v1. Catalog resources are project-context access witnesses, not actor/project/account ownership. No OAuth, key mint, refresh, signup, host/version fallback or account identity endpoint."})
    _token = field_validator("api_key")(_key)
    _host = field_validator("instance_origin")(_origin)

def _op(name, label, category): return Field(name, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})

class KeilaOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

class KeilaCheckConfig(KeilaOperation):
    operation: Literal["test_connection"] = _op("test_connection", "Check Protected Campaign Catalog", "Connection")

class KeilaCatalogConfig(KeilaOperation):
    output_limit: int = Field(100, ge=1, le=100, description="Local output cap only; never a provider query argument. The default provider page size is undocumented.")
    _size = field_validator("output_limit", mode="before")(_limit)

class KeilaCampaignsConfig(KeilaCatalogConfig):
    operation: Literal["list_campaigns"] = _op("list_campaigns", "List Campaign Metadata", "Campaigns")

class KeilaCampaignConfig(KeilaOperation):
    operation: Literal["get_campaign"] = _op("get_campaign", "Read Selected Campaign Metadata", "Campaigns")
    campaign_id: str = Field(..., title="Campaign", description="Must appear in the current default campaign catalog page; subjects and message content are never included.", json_schema_extra={"x-dynamic-options": {"field_name": "campaign_id", "searchable": True, "allow_custom": True}, "x-resource-type": "keila_campaign", "x-resource-id-path": "campaign_id"})
    _campaign = field_validator("campaign_id", mode="before")(_id)

class KeilaTemplatesConfig(KeilaCatalogConfig):
    operation: Literal["list_templates"] = _op("list_templates", "List Template Metadata", "Templates")
    include_names: bool = Field(False, description="Opt in to template.name only. All bodies, assigns, content slots and styles remain omitted.")

class KeilaTemplateConfig(KeilaOperation):
    operation: Literal["get_template"] = _op("get_template", "Read Selected Template Metadata", "Templates")
    template_id: str = Field(..., title="Template", description="Independent current template-catalog selection; no campaign parent is inferred.", json_schema_extra={"x-dynamic-options": {"field_name": "template_id", "searchable": True, "allow_custom": True}, "x-resource-type": "keila_template", "x-resource-id-path": "template_id"})
    include_names: bool = Field(False, description="Opt in to template.name only; no template rendering or content output.")
    _template = field_validator("template_id", mode="before")(_id)

KeilaConfig = Annotated[Union[KeilaCheckConfig, KeilaCampaignsConfig, KeilaCampaignConfig, KeilaTemplatesConfig, KeilaTemplateConfig], Field(discriminator="operation")]
class KeilaNodeConfig(NodeConfig[KeilaConfig, KeilaAPIKeyCredential]): pass

class KeilaMetadata(BaseModel): model_config = ConfigDict(extra="forbid")
class KeilaCampaignMetadata(KeilaMetadata):
    id: str
    inserted_at: Optional[str] = None
    updated_at: Optional[str] = None
    scheduled_for: Optional[str] = None
    sent_at: Optional[str] = None
    format: Optional[Literal["markdown", "text", "block", "mjml", "html"]] = None
class KeilaTemplateMetadata(KeilaMetadata):
    id: str
    inserted_at: Optional[str] = None
    updated_at: Optional[str] = None
    type: Optional[Literal["text", "html", "mjml", "hybrid"]] = None
    name: Optional[str] = None
class KeilaPageMetadata(KeilaMetadata):
    page: Optional[int] = None
    page_count: Optional[int] = None
    page_size: Optional[int] = None
    returned_page_count: int
    emitted_count: int
    locally_truncated: bool
    more_pages_by_metadata: Optional[bool] = None
    observed_page_last_by_metadata: Optional[bool] = None
    request_scope: Literal["default_page"] = "default_page"
    query_pagination_supported: Literal[False] = False
    entire_catalog_completion_verified: Literal[False] = False
    returned_links_followed: Literal[False] = False
class KeilaResult(KeilaMetadata):
    account_identity_verified: Literal[False] = False
    user_identity_verified: Literal[False] = False
    project_identity_verified: Literal[False] = False
    ownership_verified: Literal[False] = False
    all_permissions_verified: Literal[False] = False
    entitlement_verified: Literal[False] = False
    message_content_and_private_fields_omitted: Literal[True] = True
    names_included: bool = False
    results: Optional[list[KeilaCampaignMetadata]] = None
    campaigns: Optional[list[KeilaCampaignMetadata]] = None
    campaign: Optional[KeilaCampaignMetadata] = None
    templates: Optional[list[KeilaTemplateMetadata]] = None
    template: Optional[KeilaTemplateMetadata] = None
    pagination: Optional[KeilaPageMetadata] = None
    selected_resource_in_current_catalog: Optional[Literal[True]] = None
    optional_template_reference_verified: Optional[Literal[True]] = None
    protected_read_completed: Optional[Literal[True]] = None
    proves: Optional[Literal["reachability"]] = None

class KeilaAPIError(ValueError):
    def __init__(self, message, *, authority_rejected=False, http_status=None):
        super().__init__(message); self.authority_rejected = authority_rejected; self.http_status = http_status

async def _request(data, context, route):
    if not re.fullmatch(r"/(?:campaigns|templates)(?:/" + ID_PATTERN + r")?", route): raise ValueError("Unsupported Keila native GET route")
    current = await _stable(data, context); _protect_transport_logs(); privacy = _PRIVATE_REQUEST.set(True)
    try:
        try:
            async with guarded_async_client(timeout=20.0, follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", current["instance_origin"] + "/api/v1" + route, headers={"Authorization": "Bearer " + current["api_key"], "Content-Type": "application/json", "Accept": "application/json"}) as response:
                    status = response.status_code
                    if status == 403: raise KeilaAPIError("Keila protected read was refused; credential, role, plan or resource cause remains unverified", http_status=403)
                    if status == 429: raise KeilaAPIError("Keila rate limit refused the read; no retry", http_status=429)
                    if status != 200: raise KeilaAPIError("Keila returned HTTP" + str(status) + "; protected read is unverified", http_status=status)
                    if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json": raise KeilaAPIError("Keila response is not documented JSON")
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        chunks.extend(chunk)
                        if len(chunks) > MAX_BYTES: raise KeilaAPIError("Keila response exceeds local 4 MiB bound; no truncated success")
                    try: raw = _redact(_parse_json(bytes(chunks).decode("utf-8")), current["api_key"])
                    except (ValueError, TypeError, UnicodeError, RecursionError): raise KeilaAPIError("Keila JSON metadata is unverified") from None
        finally: await _stable(data, context)
        if not isinstance(raw, dict) or raw.get("error") is not None or raw.get("errors") is not None or raw.get("status") in ("error", "rejected", "pending_approval", "not_executed", "forbidden"): raise KeilaAPIError("Keila did not return a documented successful protected resource")
        return raw
    except KeilaAPIError: raise
    except Exception: raise KeilaAPIError("Keila transport did not establish a protected read; no replay") from None
    finally: _PRIVATE_REQUEST.reset(privacy)

def _metadata(raw, kind, *, expected=None, include_names=False):
    try:
        if not isinstance(raw, dict): raise ValueError()
        item = {"id": _id(raw.get("id"))}
        if expected is not None and item["id"] != expected: raise ValueError()
        for key in ("inserted_at", "updated_at") + (("scheduled_for", "sent_at") if kind == "campaigns" else ()):
            if key in raw: item[key] = _text(raw[key])
        if kind == "campaigns":
            if "settings" in raw:
                if not isinstance(raw["settings"], dict): raise ValueError()
                if "type" in raw["settings"]:
                    if raw["settings"]["type"] is None: raise ValueError()
                    item["format"] = raw["settings"]["type"]
            if "template_id" in raw: _id(raw["template_id"])
            return KeilaCampaignMetadata.model_validate(item).model_dump(exclude_none=True)
        if "type" in raw: item["type"] = raw["type"]
        if "type" in raw and raw["type"] is None: raise ValueError()
        if include_names and "name" in raw: item["name"] = _text(raw["name"], 512)
        return KeilaTemplateMetadata.model_validate(item).model_dump(exclude_none=True)
    except (ValueError, TypeError): raise KeilaAPIError("Keila resource ID, optional scalar metadata or documented format is unverified") from None

def _page(raw, received, emitted):
    try:
        item = {"returned_page_count": received, "emitted_count": emitted, "locally_truncated": emitted < received}
        if "meta" in raw:
            if not isinstance(raw["meta"], dict): raise ValueError()
            for key in ("page", "page_count", "page_size"):
                if key in raw["meta"]: item[key] = _integer(raw["meta"][key])
            if "page" in item and "page_count" in item and item["page_count"] > 0:
                if item["page"] >= item["page_count"]: raise ValueError()
                item["more_pages_by_metadata"] = item["page"] + 1 < item["page_count"]
                item["observed_page_last_by_metadata"] = item["page"] + 1 == item["page_count"]
        return KeilaPageMetadata.model_validate(item).model_dump(exclude_none=True)
    except (ValueError, TypeError): raise KeilaAPIError("Keila optional zero-indexed page metadata is unverified; no guessed continuation") from None

async def _catalog(data, context, kind, *, include_names=False, output_limit=MAX_OUTPUT):
    raw = await _request(data, context, "/" + kind)
    if not isinstance(raw.get("data"), list) or len(raw["data"]) > MAX_ROWS: raise KeilaAPIError("Keila catalog requires the documented data array within the local response bound")
    rows = [_metadata(row, kind, include_names=include_names) for row in raw["data"]]
    if len({row["id"] for row in rows}) != len(rows): raise KeilaAPIError("Keila current catalog contains duplicate resource IDs")
    await _stable(data, context)
    emitted = rows[:output_limit]
    return emitted, _page(raw, len(rows), len(emitted)), raw["data"][:output_limit]

async def _campaign_template_witness(data, context, campaigns):
    ids = {_id(row["template_id"]) for row in campaigns if "template_id" in row}
    if not ids: return False
    templates, _, _ = await _catalog(data, context, "templates")
    if not ids <= {row["id"] for row in templates}: raise KeilaAPIError("Keila optional template reference is outside the current bounded template catalog; no missing-page or parent inference")
    return True

async def _detail(data, context, kind, selected, *, include_names=False):
    rows, _, _ = await _catalog(data, context, kind)
    if selected not in {row["id"] for row in rows}: raise KeilaAPIError("Keila selected resource is outside the current bounded default catalog page; no guessed paging")
    raw = await _request(data, context, "/" + kind + "/" + selected)
    detail = _metadata(raw.get("data"), kind, expected=selected, include_names=include_names)
    linked = await _campaign_template_witness(data, context, [raw["data"]]) if kind == "campaigns" else False
    await _stable(data, context)
    return detail, linked

class KeilaNode(WorkflowNode):
    integration_type = "automation-keila"
    credential_provider_labels = {"keila": "Keila Account"}
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="test_connection", noun="Keila accessible campaign metadata", proves="reachability", label_keys=("id",))
    edit_examples = ["List campaign IDs and resource times without newsletter content", "Read a current selected campaign's documented format", "List template IDs/types or explicitly opt into template names"]
    @classmethod
    def get_config_model(cls): return KeilaNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        _original_family(config_data); shaped = dict(config_data)
        if config_data.get("credentials") is not None: shaped["credentials"] = _shape(config_data["credentials"])
        try: KeilaNodeConfig.model_validate(runtime_config_view(shaped, KeilaNodeConfig))
        except ValueError: raise ValueError("Keila native configuration, resource scope or credential is invalid") from None
        return super().parse_config(shaped)
    @classmethod
    def validate_config(cls, config_data):
        try:
            _original_family(config_data); shaped = dict(config_data)
            if config_data.get("credentials") is not None: shaped["credentials"] = _shape(config_data["credentials"])
            KeilaNodeConfig.model_validate(runtime_config_view(shaped, KeilaNodeConfig))
        except (ValueError, TypeError): return ValidationResult(valid=False, errors=["Keila native configuration or credential family is invalid"], satisfied_set=None)
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
        # Staging supplies trusted workflow context at the loader after this hook.
        if credential_id:
            return {**_shape(credential_data), "_keila_authority": _LookupAuthority(
                pool, user_id, credential_id, None, None,
            )}
        return await _current_data(credential_data, pool=pool, user_id=user_id)
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, KeilaNodeConfig) or self.config.credentials is None: raise ValueError("Keila requires an existing key and fixed instance origin")
        node_data = self.node_data or {}; raw = node_data.get("credentials"); data = _shape(raw if isinstance(raw, dict) else self.config.credentials.model_dump())
        context = {"_approval_pool": node_data.get("_approval_pool"), "_credential_id": node_data.get("credential_id"), "_user_id": self.user_id, "_organization_id": self.organization_id, "_workflow_id": self.workflow_id}
        current = await _current_data(data, **_authority(context))
        if node_data.get("credential_id") and not _bound_matches(data, current): raise KeilaAPIError("Keila saved-row key/origin binding changed before transport", authority_rejected=True)
        result = await self._operation(self.config.config, current, context); await _stable(current, context)
        return {"status": "success", "operation": self.config.config.operation, "data": KeilaResult.model_validate(result).model_dump(exclude_none=True)}
    @staticmethod
    async def _operation(cfg, data, context):
        if cfg.operation in ("test_connection", "list_campaigns", "list_templates"):
            kind = "templates" if cfg.operation == "list_templates" else "campaigns"
            rows, page, raw_rows = await _catalog(data, context, kind, include_names=getattr(cfg, "include_names", False), output_limit=getattr(cfg, "output_limit", MAX_OUTPUT))
            if cfg.operation == "test_connection": return {"results": rows, "pagination": page, "protected_read_completed": True, "proves": "reachability"}
            result = {kind: rows, "pagination": page, "names_included": getattr(cfg, "include_names", False)}
            if kind == "campaigns" and await _campaign_template_witness(data, context, raw_rows): result["optional_template_reference_verified"] = True
            return result
        kind = "campaigns" if cfg.operation == "get_campaign" else "templates"
        selected = cfg.campaign_id if kind == "campaigns" else cfg.template_id
        detail, linked = await _detail(data, context, kind, selected, include_names=getattr(cfg, "include_names", False))
        result = {"campaign" if kind == "campaigns" else "template": detail, "selected_resource_in_current_catalog": True, "names_included": getattr(cfg, "include_names", False)}
        if linked: result["optional_template_reference_verified"] = True
        return result
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        if field_name not in ("campaign_id", "template_id"): return {"options": [], "next_page_token": None}
        if page_token is not None: raise ValueError("Keila catalog query pagination is undocumented; no guessed continuation")
        if search not in (None, "") and (not isinstance(search, str) or not re.fullmatch(ID_PATTERN, search)): raise ValueError("Keila picker searches bounded opaque ID text only")
        context = _context(credential_data, context or {}); data = await _current_data(credential_data, **_authority(context))
        if context.get("_credential_id") and not _bound_matches(credential_data, data): raise KeilaAPIError("Keila picker saved-row key/origin binding changed", authority_rejected=True)
        if context.get("_credential_id"):
            from utils.credential_approval import admit_lookup
            pending = await admit_lookup(
                credential_id=context["_credential_id"], user_id=context["_user_id"],
                node_type=NODE_TYPE, arguments={"field_name": field_name, "search": search, "page_token": page_token},
                pool=context.get("_approval_pool"), organization_id=context.get("_organization_id"),
                workflow_id=context.get("_workflow_id"),
            )
            if pending:
                raise KeilaAPIError("Keila catalog lookup is awaiting approval or was rejected; no protected read was executed")
        rows, page, _ = await _catalog(data, context, "campaigns" if field_name == "campaign_id" else "templates")
        if page["locally_truncated"] or page.get("more_pages_by_metadata") is True: raise KeilaAPIError("Keila picker is bounded to the default page and current catalog has additional rows/pages; query continuation is undocumented")
        await _stable(data, context)
        return {"options": [{"value": row["id"], "label": row["id"]} for row in rows if not search or search in row["id"]], "next_page_token": None}

def _shape(data):
    if not isinstance(data, dict) or data.get("credential_type", FAMILIES[0]) not in FAMILIES: raise ValueError("Keila credential family is unsupported")
    try: shaped = KeilaAPIKeyCredential.model_validate({**data, "credential_type": FAMILIES[0]}).model_dump()
    except ValueError: raise ValueError("Keila native credential is invalid") from None
    return {**data, **shaped}

def _binding(data):
    return (data["credential_type"], data["api_key"], data["instance_origin"], data.get("owner_id"), data.get("token_version"), data.get("updated_at"), data.get("approval_revision"))

def _bound_matches(bound, current):
    return all(bound.get(key) == current.get(key) for key in ("credential_type", "api_key", "instance_origin")) and all(bound[key] == current.get(key) for key in ("owner_id", "token_version", "updated_at", "approval_revision") if key in bound)

def _original_family(data):
    if not isinstance(data, dict):
        raise ValueError("Keila configuration is invalid")
    creds = data.get("credentials")
    saved = data.get("credential_id") or data.get("credentialIds")
    if saved and not isinstance(creds, dict) or isinstance(creds, dict) and (creds.get("credential_type") is not None or saved) and creds.get("credential_type") not in FAMILIES:
        raise ValueError("Keila saved credential family is missing or unsupported")


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
    from repositories.credential_approvals import CredentialApprovalRepo
    from utils.credential_loader import load_credential
    from utils.credentials import (
        resolve_credential_with_owner_fallback, get_workflow_owner_id,
        is_credential_authorized_for_workflow, credential_lender,
    )
    if pool is None:
        from utils.database_pool import get_native_pool
        pool = get_native_pool()
    if organization_id is None:
        from wss.handlers.workflow_handler import get_user_org_context
        async with pool.acquire() as conn:
            organization_id = await get_user_org_context(conn, user_id)
    resolved = await resolve_credential_with_owner_fallback(
        credential_id, user_id, pool, org_id=organization_id, workflow_id=workflow_id,
    )
    if resolved is None:
        raise ValueError("Keila current credential is unavailable or access denied")
    resolved = _shape(resolved)
    principal = user_id
    repo = CredentialApprovalRepo(pool)
    try:
        policy = await repo.policy(credential_id, principal, organization_id)
    except PermissionError:
        if not workflow_id:
            raise ValueError("Keila current credential authority is unavailable") from None
        owner = await get_workflow_owner_id(pool, workflow_id)
        if owner and owner != user_id and await is_credential_authorized_for_workflow(pool, workflow_id, credential_id):
            principal = owner
        else:
            principal = await credential_lender(pool, workflow_id, credential_id)
        if not principal:
            raise ValueError("Keila current credential authority is unavailable") from None
        policy = await repo.policy(credential_id, principal, organization_id)
    if policy["credential_type"] not in FAMILIES:
        raise ValueError("Keila current credential family is unsupported")
    current = await load_credential(pool, principal, credential_id, raise_on_error=True)
    if current is None:
        raise ValueError("Keila current credential is unavailable or revoked")
    current = _shape(current)
    if not _bound_matches(resolved, current):
        raise ValueError("Keila current credential binding changed while loading")
    current.update(owner_id=str(policy["owner_id"]), approval_revision=policy["approval_revision"])
    return {**current, "_keila_authority": _LookupAuthority(pool, user_id, credential_id, organization_id, workflow_id)}


def _context(data, context):
    result = {k: v for k, v in context.items() if not k.startswith("_")}
    result["_user_id"] = context.get("_user_id")
    bound = data.get("_keila_authority") if isinstance(data, dict) else None
    if type(bound) is _LookupAuthority:
        if bound.user_id != context.get("_user_id"):
            raise ValueError("Keila picker actor does not match saved authority")
        result.update({"_approval_pool": bound.pool, "_user_id": bound.user_id, "_credential_id": bound.credential_id, "_organization_id": bound.organization_id, "_workflow_id": bound.workflow_id or context.get("_workflow_id")})
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
        return re.sub(r"(?i)([?&](?:access_token|api_key|auth_token|token|signature|auth|key)=)[^&#\s]+", r"[redacted]", value)
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


# Narrow reuse of utils.meta_subscriptions._TransportPrivacy: context-local
# masking leaves concurrent unrelated requests untouched and resets on failure.
_PRIVATE_REQUEST = ContextVar("keila_private_request", default=False)


class _TransportPrivacy(logging.Filter):
    def filter(self, record):
        if _PRIVATE_REQUEST.get():
            record.msg, record.args = "Keila private transport activity", ()
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
    except ValueError: raise KeilaAPIError("Keila current credential authority is unavailable or revoked", authority_rejected=True) from None
    if _binding(current) != _binding(data): raise KeilaAPIError("Keila current key, owner, version or approval revision changed; result is not accepted", authority_rejected=True)
    return current
