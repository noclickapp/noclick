"""Native Qwilr page workflows. API calls affect the token's live account."""
import base64
from contextvars import ContextVar
from datetime import datetime
import hashlib
import json
import logging
import re
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, TypeAdapter, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import normalize_search, filter_options_by_search
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from utils.ssrf import assert_exact_url_origin, guarded_async_client

FAMILY = "qwilr_api_token"
NODE_TYPE = "automation-qwilr"
ORIGIN = "https://api.qwilr.com"
BASE = ORIGIN + "/v1"
MAX_BYTES = 2 * 1024 * 1024
MAX_LIBRARY = 1000  # Local safety bound; the library endpoints do not document pagination.
_PRIVATE = ContextVar("qwilr_private_transport", default=False)
Status = Literal["draft", "live", "accepting", "accepted", "disabled", "declined"]


def token(value):
    if not isinstance(value, str):
        raise ValueError("Use a genuine Qwilr account access token")
    value = clean_secret(value, field_name="Qwilr access token")
    if not value or len(value) > 8192 or not re.fullmatch(r"[!-~]+", value) or value.lower().startswith("bearer"):
        raise ValueError("Paste the Qwilr access token itself without whitespace or a Bearer prefix")
    return value


class QwilrAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Qwilr Account Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.qwilr.com/#/settings/api",
        "x-credential-instructions": "Supply your existing Qwilr account access token from API Settings. All calls use your live account and the token owner's accessible pages. API entitlement is account dependent. No OAuth exchange, refresh or identity endpoint is assumed; reconnect with an existing replacement token when needed.",
    })
    credential_type: Literal["qwilr_api_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Qwilr Account Access Token", json_schema_extra={"ui:widget": "password", "ui:sensitive": True})
    _token = field_validator("api_token", mode="before")(token)


# Qwilr's own MCP server: agents get its tools through a person's Qwilr sign-in.
QwilrMcpCredential = mcp_credential("qwilr", "https://mcp.qwilr.com", app="Qwilr")
QwilrCredential = Union[QwilrAPITokenCredential, QwilrMcpCredential]


def credential(data):
    try:
        if not isinstance(data, dict) or data.get("credential_type") != FAMILY:
            raise ValueError()
        if any(data.get(key) not in (None, "") for key in ("access_token", "refresh_token", "client_secret", "api_key", "password", "server_url", "account_id")):
            raise ValueError()
        return QwilrAPITokenCredential.model_validate(data).model_dump()
    except Exception:
        raise ValueError("Connect a native Qwilr account-token credential") from None


async def current_credential(data):
    return credential(data)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9]{24}", value):
        raise ValueError("Use the exact 24-character Qwilr page or user ID")
    return value


def block_identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{30}", value):
        raise ValueError("Use the exact 30-character Qwilr saved-block ID")
    return value


def plain(value, *, limit=500, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()) or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise ValueError("Use bounded plain text")
    return value


def mapping(value, *, metadata=False):
    if not isinstance(value, dict) or len(value) > (500 if metadata else 100):
        raise ValueError("Use a bounded variable or metadata object")
    for key, item in value.items():
        if not isinstance(key, str) or not key or len(key) > 500 or any(ord(c) < 32 for c in key) or key in {"__proto__", "constructor", "prototype"}:
            raise ValueError("Use bounded variable or metadata names")
        if isinstance(item, str):
            plain(item, limit=500 if metadata else 5000, empty=True)
        elif not metadata and isinstance(item, list) and len(item) <= 100:
            for row in item:
                if not isinstance(row, dict) or len(row) > 100:
                    raise ValueError("Repeating variables require bounded objects of text values")
                mapping(row, metadata=True)
        else:
            raise ValueError("Variables require text values or repeating text objects; metadata requires text values")
    return value


def tag_list(value):
    if not isinstance(value, list) or len(value) > 50:
        raise ValueError("Use a bounded tag list")
    for item in value:
        plain(item, limit=200)
        if "," in item or any(ord(c) < 32 for c in item):
            raise ValueError("Tags cannot contain commas or control characters in this node")
    return value


def resource(name):
    return {"x-resource-type": "qwilr_" + name, "x-dynamic-options": {"field_name": name + "_id", "searchable": True, "allow_custom": True}}


class _Operation(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, extra="ignore")
    _ids = field_validator("page_id", "template_id", "owner_id", "folder_id", mode="before", check_fields=False)(lambda v: identifier(v) if v is not None else v)
    _block = field_validator("saved_block_id", mode="before", check_fields=False)(block_identifier)
    @field_validator("acknowledge_live_account_effects", "saved_block_page_confirmed", mode="before", check_fields=False)
    @classmethod
    def acknowledge(cls, value):
        if value is not True:
            raise ValueError("Explicitly confirm this live-account draft workflow")
        return value


class ListPages(_Operation):
    operation: Literal["list_pages"] = Field("list_pages", title="List Page Metadata")
    limit: int = Field(25, ge=1, le=100, strict=True, title="Page Size")
    cursor: Optional[str] = Field(None, max_length=2048, title="Provider Cursor", description="Use next_cursor from the last result; retain all filters and sort order.")
    statuses: list[Status] = Field(default_factory=list, title="Statuses")
    tags: list[str] = Field(default_factory=list, title="All Tags")
    folder_id: Optional[str] = Field(None, title="Folder ID", description="Direct children only. Qwilr does not document a folder-list API here.")
    owner_id: Optional[str] = Field(None, title="Owner", json_schema_extra=resource("owner"))
    sort_direction: Literal["asc", "desc"] = Field("desc", title="Created Time Order")
    _tags = field_validator("tags", mode="before")(tag_list)


class GetPage(_Operation):
    operation: Literal["get_page"] = Field("get_page", title="Get Page Metadata")
    page_id: str = Field(..., title="Page", json_schema_extra=resource("page"))


class GetAcceptanceSummary(GetPage):
    operation: Literal["get_acceptance_summary"] = Field("get_acceptance_summary", title="Get Acceptance Counts", description="Reads real acceptance counts only; does not accept, sign, pay, return signer details or request preview acceptance.")


class ListSavedBlocks(_Operation):
    operation: Literal["list_saved_blocks"] = Field("list_saved_blocks", title="List Saved Block Metadata")


class ListUsers(_Operation):
    operation: Literal["list_users"] = Field("list_users", title="List Account User Metadata", description="ID, name, creation date and team names only. No email, roles or current-user identity claim.")


class _Draft(_Operation):
    acknowledge_live_account_effects: bool = Field(..., title="Confirm Live Account Draft Changes", description="Qwilr has no assumed sandbox. Draft creation persists content and may inherit quote/accept/payment settings or account automation. No publish, send, sign, accept or pay request is made.")


class _CreateDraft(_Draft):
    name: str = Field(..., max_length=500, title="Draft Name")
    owner_id: Optional[str] = Field(None, title="Owner", json_schema_extra=resource("owner"))
    tags: list[str] = Field(default_factory=list, title="Tags", description="Add an owned test tag for manual cleanup; no page DELETE API is documented.")
    substitutions: dict[str, Union[str, list[dict[str, str]]]] = Field(default_factory=dict, title="Variable Values", json_schema_extra={"ui:widget": "json"})
    metadata: dict[str, str] = Field(default_factory=dict, title="Page Metadata", description="May be returned by existing account webhooks. Do not put secrets here.", json_schema_extra={"ui:widget": "json"})
    _name = field_validator("name", mode="before")(plain)
    _tags = field_validator("tags", mode="before")(tag_list)
    _variables = field_validator("substitutions", mode="before")(mapping)
    _metadata = field_validator("metadata", mode="before")(lambda v: mapping(v, metadata=True))


class CreateDraftFromTemplate(_CreateDraft):
    operation: Literal["create_draft_from_template"] = Field("create_draft_from_template", title="Create Draft From Template", json_schema_extra={"x-creates-resource": True, "x-resource-type": "qwilr_page", "x-resource-id-path": "record.id"})
    template_id: str = Field(..., title="Template ID", description="Copy the existing template's ID from the Qwilr editor. No template listing or conversion is assumed.")


class _Blocks(_Operation):
    saved_block_id: str = Field(..., title="First Saved Block", json_schema_extra=resource("saved_block"))
    additional_saved_block_ids: list[str] = Field(default_factory=list, max_length=49, title="Additional Saved Block IDs In Order", description="Existing accessible IDs only; this replaces page content for replacement operations.")
    @field_validator("additional_saved_block_ids", mode="before")
    @classmethod
    def more_blocks(cls, value):
        if not isinstance(value, list) or len(value) > 49:
            raise ValueError("Use a bounded saved-block list")
        return [block_identifier(item) for item in value]


class CreateDraftFromBlocks(_CreateDraft, _Blocks):
    operation: Literal["create_draft_from_blocks"] = Field("create_draft_from_blocks", title="Create Draft From Saved Blocks", json_schema_extra={"x-creates-resource": True, "x-resource-type": "qwilr_page", "x-resource-id-path": "record.id"})


class ReplaceDraftBlocks(_Draft, _Blocks):
    operation: Literal["replace_draft_blocks"] = Field("replace_draft_blocks", title="Replace Draft Content From Saved Blocks", description="Full content replacement, supported by Qwilr only for pages originally created from saved blocks. No provider CAS contract is documented; concurrent edits remain possible.")
    page_id: str = Field(..., title="Draft Page", json_schema_extra=resource("page"))
    saved_block_page_confirmed: bool = Field(..., title="Confirm Page Was Created From Saved Blocks", description="Confirm the source method from your owned workflow. The API response does not expose a documented source-method marker.")
    substitutions: dict[str, Union[str, list[dict[str, str]]]] = Field(default_factory=dict, title="Variable Values", json_schema_extra={"ui:widget": "json"})
    _variables = field_validator("substitutions", mode="before")(mapping)


class UpdateDraftExpiry(_Draft):
    operation: Literal["update_draft_expiry"] = Field("update_draft_expiry", title="Set Draft Link Expiry", description="Stores expiry on an existing draft. The countdown starts when someone later publishes; expiry can then disable its link and decline the page.")
    page_id: str = Field(..., title="Draft Page", json_schema_extra=resource("page"))
    expire_after_days: int = Field(..., strict=True, ge=1, le=365, title="Expire After Days")


QwilrOperation = Annotated[Union[ListPages, GetPage, GetAcceptanceSummary, ListSavedBlocks, ListUsers, CreateDraftFromTemplate, CreateDraftFromBlocks, ReplaceDraftBlocks, UpdateDraftExpiry], Discriminator("operation")]
OPS = ("list_pages", "get_page", "get_acceptance_summary", "list_saved_blocks", "list_users", "create_draft_from_template", "create_draft_from_blocks", "replace_draft_blocks", "update_draft_expiry")


class QwilrNodeConfig(NodeConfig[QwilrOperation, QwilrCredential]):
    pass


class _Privacy(logging.Filter):
    def filter(self, record):
        return not _PRIVATE.get()


def _privacy():
    for name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"):
        log = logging.getLogger(name)
        if not any(isinstance(f, _Privacy) for f in log.filters):
            log.addFilter(_Privacy())


def _json(payload):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError()
            out[key] = value
        return out
    return json.loads(payload, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


class _RequestRefused(ValueError):
    pass


class _AuthenticationRefused(_RequestRefused):
    pass


async def request(data, method, path, *, params=None, body=None):
    current = await current_credential(data)
    if not ((path in {"/pages", "/blocks/saved", "/users"} and method == "GET") or (path == "/pages" and method == "POST") or (re.fullmatch(r"/pages/[a-z0-9]{24}", path or "") and method in {"GET", "PUT"})):
        raise ValueError("Unsupported native Qwilr resource path")
    url = BASE + path
    assert_exact_url_origin(url, ORIGIN)
    _privacy()
    marker = _PRIVATE.set(True)
    try:
        async with guarded_async_client(timeout=25.0, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, url, params=params, json=body, headers={"Authorization": "Bearer " + current["api_token"], "Accept": "application/json"}) as response:
                await current_credential(data)
                code = response.status_code
                if code in {401, 403}:
                    raise _AuthenticationRefused("Qwilr refused the account token or current access; reconnect or check existing permission")
                if code in {400, 404, 409, 422}:
                    raise _RequestRefused("Qwilr refused the selected resource or request; inspect current state before retrying a write")
                if code == 429:
                    raise RuntimeError("Qwilr rate limited the request; retry later")
                if code != (201 if method == "POST" else 200):
                    raise RuntimeError("Qwilr did not confirm the documented request status; inspect current state before retrying a write")
                payload = bytearray()
                async for chunk in response.aiter_bytes():
                    payload.extend(chunk)
                    if len(payload) > MAX_BYTES:
                        raise RuntimeError("Qwilr response exceeded the native metadata limit")
                await current_credential(data)
                if "json" not in response.headers.get("content-type", "").lower():
                    raise RuntimeError("Qwilr did not return JSON metadata")
                raw = _json(bytes(payload))
                if not isinstance(raw, (dict, list)) or (isinstance(raw, dict) and "statusCode" in raw):
                    raise RuntimeError("Qwilr returned an invalid or error response")
                return raw
    except _RequestRefused:
        raise
    except ValueError:
        raise ValueError("Qwilr request was refused by current credential, resource or public-origin policy") from None
    except Exception as exc:
        if isinstance(exc, RuntimeError) and str(exc).startswith("Qwilr "):
            raise
        raise RuntimeError("Qwilr request could not be completed; inspect current state before retrying a write") from None
    finally:
        _PRIVATE.reset(marker)


def project_page(raw, *, summary=False):
    if not isinstance(raw, dict) or not {"id", "name", "status", "tags"}.issubset(raw):
        raise RuntimeError("Qwilr returned invalid page metadata")
    out = {"id": identifier(raw.get("id")), "name": plain(raw.get("name"), limit=2000, empty=True)}
    if raw.get("status") not in {"draft", "live", "accepting", "accepted", "disabled", "declined"}:
        raise RuntimeError("Qwilr returned an unknown page status")
    out["status"] = raw["status"]
    out["tags"] = tag_list(raw.get("tags", []))
    for key in ("ownerId", "folderId"):
        if raw.get(key) is not None:
            out[key] = identifier(raw[key])
    if "createdAt" in raw:
        try:
            stamp = raw["createdAt"]
            if not isinstance(stamp, str) or datetime.fromisoformat(stamp.replace("Z", "+00:00")).tzinfo is None:
                raise ValueError()
            out["createdAt"] = stamp
        except Exception:
            raise RuntimeError("Qwilr returned an invalid page timestamp") from None
    if not summary:
        out["ownerId"] = identifier(raw.get("ownerId"))
        expiry = raw.get("expiry")
        if not isinstance(expiry, dict) or type(expiry.get("enabled")) is not bool:
            raise RuntimeError("Qwilr returned invalid page expiry metadata")
        out["expiry"] = {"enabled": expiry["enabled"]}
        if "expireAfterDays" in expiry:
            days = expiry["expireAfterDays"]
            if type(days) is not int or not 1 <= days <= 365:
                raise RuntimeError("Qwilr returned invalid page expiry metadata")
            out["expiry"]["expireAfterDays"] = days
        payment = raw.get("paymentSettings")
        if isinstance(payment, dict) and type(payment.get("enabled")) is bool:
            out["payment_enabled"] = payment["enabled"]
    # Links, blocks, metadata, substitution values, signer data, audit PDFs,
    # quote amounts and payment gateway/settings are deliberately not returned.
    return out


async def get_page(data, rid, *, acceptance=False):
    raw = await request(data, "GET", "/pages/" + rid, params={"expand": "acceptance"} if acceptance else None)
    out = project_page(raw)
    if out["id"] != rid:
        raise ValueError("Qwilr page did not match the selected page")
    return raw, out


async def library(data, kind):
    raw = await request(data, "GET", "/blocks/saved" if kind == "block" else "/users")
    if not isinstance(raw, list) or len(raw) > MAX_LIBRARY or any(not isinstance(row, dict) for row in raw):
        raise RuntimeError("Qwilr returned an invalid or oversized unpaged library")
    records = []
    for row in raw:
        rid = block_identifier(row.get("id")) if kind == "block" else identifier(row.get("id"))
        out = {"id": rid}
        if kind == "block":
            out["name"] = plain(row.get("name", rid), limit=2000, empty=True)
            if isinstance(row.get("type"), str):
                out["type"] = plain(row["type"], limit=100, empty=True)
        else:
            for key in ("firstName", "lastName", "createdAt"):
                if isinstance(row.get(key), str):
                    out[key] = plain(row[key], limit=500, empty=True)
            teams = row.get("teams")
            if not isinstance(teams, list) or len(teams) > 100 or any(not isinstance(team, dict) or not isinstance(team.get("name"), str) for team in teams):
                raise RuntimeError("Qwilr returned invalid user team metadata")
            out["teams"] = [plain(team["name"], limit=200, empty=True) for team in teams]
        records.append(out)
    if len({row["id"] for row in records}) != len(records):
        raise RuntimeError("Qwilr returned duplicate library IDs")
    return records


async def saved_blocks(data, cfg):
    ids = [cfg["saved_block_id"], *cfg["additional_saved_block_ids"]]
    existing = {row["id"] for row in await library(data, "block")}
    if any(rid not in existing for rid in ids):
        raise ValueError("Qwilr saved block is not in the current accessible bounded library")
    return [{"id": rid} for rid in ids]


async def records(data, args):
    cfg = TypeAdapter(QwilrOperation).validate_python(args).model_dump()
    op = cfg["operation"]
    if op == "list_pages":
        params = {"limit": cfg["limit"], "sortDirection": cfg["sort_direction"]}
        for source, dest in (("cursor", "cursor"), ("folder_id", "folderId"), ("owner_id", "ownerId")):
            if cfg[source] is not None:
                params[dest] = cfg[source]
        if cfg["statuses"]:
            params["status"] = ",".join(cfg["statuses"])
        if cfg["tags"]:
            params["tags"] = ",".join(cfg["tags"])
        raw = await request(data, "GET", "/pages", params=params)
        if not isinstance(raw, dict) or not isinstance(raw.get("data"), list) or "nextCursor" not in raw or len(raw["data"]) > cfg["limit"]:
            raise RuntimeError("Qwilr returned an invalid cursor page")
        cursor = raw["nextCursor"]
        if cursor is not None and (not isinstance(cursor, str) or not cursor or len(cursor) > 2048):
            raise RuntimeError("Qwilr returned an invalid next cursor")
        rows = [project_page(row, summary=True) for row in raw["data"]]
        if len({row["id"] for row in rows}) != len(rows):
            raise RuntimeError("Qwilr returned duplicate page IDs")
        return {"records": rows, "next_cursor": cursor, "read_completed": True, "identity_verified": False}
    if op in {"list_saved_blocks", "list_users"}:
        return {"records": await library(data, "block" if op == "list_saved_blocks" else "user"), "read_completed": True}
    if op in {"get_page", "get_acceptance_summary"}:
        raw, out = await get_page(data, cfg["page_id"], acceptance=op == "get_acceptance_summary")
        if op == "get_acceptance_summary":
            acceptance = raw.get("acceptance")
            counts = None
            if acceptance is not None:
                if not isinstance(acceptance, dict) or any(type(acceptance.get(key)) is not int or acceptance[key] < 0 for key in ("acceptersCount", "acceptersTotal")) or acceptance["acceptersCount"] > acceptance["acceptersTotal"]:
                    raise RuntimeError("Qwilr returned invalid acceptance counts")
                counts = {key: acceptance[key] for key in ("acceptersCount", "acceptersTotal")}
            return {"record": out, "acceptance_counts": counts}
        return {"record": out}
    if op.startswith("create_draft_"):
        if cfg["owner_id"] is not None and cfg["owner_id"] not in {row["id"] for row in await library(data, "user")}:
            raise ValueError("Qwilr owner is not in the current accessible bounded user library")
        body = {"name": cfg["name"], "published": False, "tags": cfg["tags"], "substitutions": cfg["substitutions"], "metadata": cfg["metadata"]}
        if cfg["owner_id"] is not None:
            body["ownerId"] = cfg["owner_id"]
        if op == "create_draft_from_template":
            body["templateId"] = cfg["template_id"]
        else:
            body["blocks"] = await saved_blocks(data, cfg)
        created = project_page(await request(data, "POST", "/pages", body=body))
        if created["status"] != "draft":
            raise RuntimeError("Qwilr creation may have applied without draft status; inspect before retrying")
        _, after = await get_page(data, created["id"])
        if after["status"] != "draft" or after["name"] != cfg["name"] or after["tags"] != cfg["tags"] or (cfg["owner_id"] is not None and after.get("ownerId") != cfg["owner_id"]):
            raise RuntimeError("Qwilr creation may have applied; draft metadata readback did not match, inspect before retrying")
        return {"record": after, "readback_verified": True, "content_verified": False, "cleanup": "Manual deletion in owned Qwilr UI; no page DELETE API is documented"}
    _, before = await get_page(data, cfg["page_id"])
    if before["status"] != "draft":
        raise ValueError("Qwilr writes here require a current draft page")
    body = {"published": False}
    if op == "replace_draft_blocks":
        body["blocks"] = await saved_blocks(data, cfg)
        body["substitutions"] = cfg["substitutions"]
    else:
        body["expiry"] = {"enabled": True, "expireAfterDays": cfg["expire_after_days"]}
    updated = project_page(await request(data, "PUT", "/pages/" + cfg["page_id"], body=body))
    if updated["id"] != cfg["page_id"] or updated["status"] != "draft":
        raise RuntimeError("Qwilr update may have applied; response did not confirm the selected draft")
    _, after = await get_page(data, cfg["page_id"])
    if after["status"] != "draft" or after.get("ownerId") != before.get("ownerId") or (op == "update_draft_expiry" and after["expiry"] != body["expiry"]):
        raise RuntimeError("Qwilr update may have applied; draft readback did not match, inspect before retrying")
    return {"record": after, "readback_verified": True, "content_verified": False, "concurrent_edits_not_excluded": True}


class QwilrNode(WorkflowNode):
    integration_type = "automation-qwilr"
    credential_provider_labels = {"qwilr": "Qwilr Account"}
    scope_registry = ScopeRegistry(provider="qwilr", enforcement=Enforcement.STRICT, requirements={op: ScopeRequirement(scopes=(), credential_types=(FAMILY,)) for op in OPS})
    connection_evidence = ConnectionEvidence(noun="Qwilr pages", operation="list_pages", label_keys=("name", "id"))
    edit_examples = ["List proposal page statuses", "Create an unpublished proposal draft from an existing template", "Create or replace a draft from saved blocks", "Read acceptance counts without signer details"]
    @classmethod
    def get_config_model(cls):
        return QwilrNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            credential(config_data["credentials"])
        return super().parse_config(config_data)
    @classmethod
    def validate_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try:
                credential(config_data["credentials"])
            except ValueError:
                return {"valid": False, "errors": ["Connect a native Qwilr account token"], "satisfied_set": None}
        return super().validate_config(config_data)
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"page_id", "owner_id", "saved_block_id"}:
            raise ValueError("Unsupported Qwilr picker")
        search = normalize_search(search) or ""
        if len(search) > 200 or any(ord(c) < 32 for c in search):
            raise ValueError("Use a bounded Qwilr picker search")
        current = await current_credential(credential_data)
        scope = hashlib.sha256(json.dumps({"credential": current, "field": field_name, "search": search}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        cursor = None
        if page_token is not None:
            try:
                if field_name != "page_id" or not isinstance(page_token, str) or len(page_token) > 4096:
                    raise ValueError()
                payload = _json(base64.urlsafe_b64decode(page_token + "=" * ((-len(page_token)) % 4)))
                if set(payload) != {"scope", "cursor"} or payload["scope"] != scope or not isinstance(payload["cursor"], str) or not payload["cursor"] or len(payload["cursor"]) > 2048:
                    raise ValueError()
                cursor = payload["cursor"]
            except Exception:
                raise ValueError("Qwilr picker cursor does not match its current token, field and search") from None
        op = {"page_id": "list_pages", "owner_id": "list_users", "saved_block_id": "list_saved_blocks"}[field_name]
        result = await records(credential_data, {"operation": op, **({"cursor": cursor} if field_name == "page_id" else {})})
        options = [{"value": row["id"], "label": row.get("name") or " ".join(filter(None, (row.get("firstName"), row.get("lastName")))) or row["id"]} for row in result["records"]]
        next_cursor = result.get("next_cursor")
        next_token = None if next_cursor is None else base64.urlsafe_b64encode(json.dumps({"scope": scope, "cursor": next_cursor}, separators=(",", ":")).encode()).decode().rstrip("=")
        return {"options": filter_options_by_search(options, search), "next_page_token": next_token}
    async def execute(self, inputs):
        if not isinstance(self.config, QwilrNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a native Qwilr account token")
        return await records(self.config.credentials.model_dump(), self.config.config.model_dump())
