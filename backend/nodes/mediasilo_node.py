"""MediaSilo current v3 protected project/folder metadata reads."""
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

NODE_TYPE = "automation-mediasilo"
FAMILIES = ("mediasilo_api_key",)
BASE = "https://api.mediasilo.com/v3"
MAX_BYTES = 4 * 1024 * 1024
MAX_ROWS = 1000
SAFE_INTEGER = 9007199254740991
ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}"

def _token(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096 or any(ord(c) <= 32 or ord(c) >= 127 for c in value): raise ValueError("Supply an existing opaque MediaSilo key/secret without whitespace")
    return value

def _id(value):
    # The current OAS declares string IDs, not a UUID format. Bound path segments locally.
    if not isinstance(value, str) or not re.fullmatch(ID_PATTERN, value): raise ValueError("Supply the exact bounded MediaSilo resource ID, not a path or URL")
    return value

def _integer(value, maximum=SAFE_INTEGER, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum: raise ValueError("Unverified MediaSilo integer metadata")
    return value

def _text(value):
    if not isinstance(value, str) or not value or len(value) > 512 or any(ord(c) < 32 for c in value): raise ValueError("Unverified bounded MediaSilo name")
    return value

def _date(value):
    if not isinstance(value, str) or len(value) > 64 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})", value): raise ValueError("Unverified MediaSilo date-time")
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value

class MediaSiloAPIKeyCredential(BaseModel):
    credential_type: Literal["mediasilo_api_key"] = Field("mediasilo_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Existing MediaSilo API Key", json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., title="Existing MediaSilo API Secret", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(extra="ignore", json_schema_extra={
        "x-credential-url": "https://docs.mediasilo.com/docs/authentication",
        "x-credential-instructions": "Supply an existing user-tied API key and secret. They are sent only as x-key/x-secret headers to the current reference host api.mediasilo.com. The older guide uses api.shift.io; this node does not silently fall back. Protected project/folder access proves resource reachability, not principal identity, account ownership, all permissions, plan or entitlement. No credential acquisition, refresh or environment fallback.",
    })
    _keys = field_validator("api_key", "api_secret")(_token)

def _op(name, label, category):
    return Field(name, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})

def _resource(field, kind, parent=None):
    options = {"field_name": field, "searchable": True, "allow_custom": True}
    if parent: options["depends_on"] = parent
    return {"x-dynamic-options": options, "x-resource-type": kind, "x-resource-id-path": field}

class MediaSiloOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

class MediaSiloCheckConfig(MediaSiloOperation):
    operation: Literal["test_connection"] = _op("test_connection", "Check Protected Project Catalog Read Access", "Connection")

class MediaSiloNames(MediaSiloOperation):
    include_names: bool = Field(False, description="Opt in to project/folder names. Owner/profile/contact, descriptions, media, links, settings, credentials and capabilities are always omitted.")

class MediaSiloProjectsConfig(MediaSiloNames):
    operation: Literal["list_projects"] = _op("list_projects", "List Project Metadata", "Projects")

class MediaSiloProjectScope(MediaSiloNames):
    project_id: str = Field(..., title="Project", description="Exact returned project ID in the protected catalog. One bounded response; no published request pagination contract. IDs only in picker labels.", json_schema_extra=_resource("project_id", "mediasilo_project"))
    _project = field_validator("project_id")(_id)

class MediaSiloProjectConfig(MediaSiloProjectScope):
    operation: Literal["get_project"] = _op("get_project", "Read Selected Project Metadata", "Projects")

class MediaSiloFoldersConfig(MediaSiloProjectScope):
    operation: Literal["list_folders"] = _op("list_folders", "List Selected Project Folder Metadata", "Folders")

class MediaSiloFolderConfig(MediaSiloProjectScope):
    operation: Literal["get_folder"] = _op("get_folder", "Read Selected Folder Metadata", "Folders")
    folder_id: str = Field(..., title="Folder", description="Exact folder ID in the selected project's protected folder catalog. Returned folder.projectId must match the project.", json_schema_extra=_resource("folder_id", "mediasilo_folder", "project_id"))
    _folder = field_validator("folder_id")(_id)

MediaSiloConfig = Annotated[Union[MediaSiloCheckConfig, MediaSiloProjectsConfig, MediaSiloProjectConfig, MediaSiloFoldersConfig, MediaSiloFolderConfig], Field(discriminator="operation")]
class MediaSiloNodeConfig(NodeConfig[MediaSiloConfig, MediaSiloAPIKeyCredential]):
    pass

class MediaSiloMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

class MediaSiloProjectMetadata(MediaSiloMetadata):
    id: str
    accountId: Optional[int] = None
    dateCreated: Optional[str] = None
    created: Optional[str] = None
    lastActivity: Optional[int] = None
    folderCount: Optional[int] = None
    name: Optional[str] = None

class MediaSiloFolderMetadata(MediaSiloMetadata):
    id: str
    projectId: str
    parentId: Optional[str] = None
    folderCount: Optional[int] = None
    assetsCount: Optional[int] = None
    size: Optional[int] = None
    name: Optional[str] = None

class MediaSiloObservation(MediaSiloMetadata):
    returned_count: int
    one_response_only: Literal[True] = True
    pagination_contract_documented: Literal[False] = False
    completion_verified: Literal[False] = False
    continuation_supported: Literal[False] = False

class MediaSiloResult(MediaSiloMetadata):
    account_identity_verified: Literal[False] = False
    user_identity_verified: Literal[False] = False
    account_ownership_verified: Literal[False] = False
    private_configuration_fields_omitted: Literal[True] = True
    names_included: bool = False
    results: Optional[list[MediaSiloProjectMetadata]] = None
    projects: Optional[list[MediaSiloProjectMetadata]] = None
    project: Optional[MediaSiloProjectMetadata] = None
    folders: Optional[list[MediaSiloFolderMetadata]] = None
    folder: Optional[MediaSiloFolderMetadata] = None
    pagination: Optional[MediaSiloObservation] = None
    protected_read_completed: Optional[Literal[True]] = None
    protected_project_scope_verified: Optional[Literal[True]] = None
    returned_folder_project_id_verified: Optional[Literal[True]] = None
    all_permissions_verified: Optional[Literal[False]] = None
    entitlement_verified: Optional[Literal[False]] = None
    proves: Optional[Literal["reachability"]] = None

class MediaSiloAPIError(ValueError):
    def __init__(self, message, *, authority_rejected=False, http_status=None):
        super().__init__(message)
        self.authority_rejected = authority_rejected
        self.http_status = http_status

async def _request(data, context, route):
    if not re.fullmatch(r"/projects(?:/" + ID_PATTERN + r"(?:/folders)?)?|/folders/" + ID_PATTERN, route): raise ValueError("Unsupported native MediaSilo protected GET route")
    current = await _stable(data, context)
    _protect_transport_logs(); private_token = _PRIVATE_REQUEST.set(True)
    try:
        try:
            async with guarded_async_client(timeout=20.0, follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", BASE + route, headers={"x-key": current["api_key"], "x-secret": current["api_secret"], "Accept": "application/json"}) as response:
                    code = response.status_code
                    if code == 403: raise MediaSiloAPIError("MediaSilo refused the protected read; credential, role, plan or resource cause remains unverified", http_status=403)
                    if code == 429: raise MediaSiloAPIError("MediaSilo rate limit refused this read; no retry", http_status=429)
                    if code != 200: raise MediaSiloAPIError("MediaSilo returned HTTP" + str(code) + "; protected read is unverified", http_status=code)
                    if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json": raise MediaSiloAPIError("MediaSilo response is not documented JSON")
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        chunks.extend(chunk)
                        if len(chunks) > MAX_BYTES: raise MediaSiloAPIError("MediaSilo response exceeds local 4 MiB bound; no truncated success")
                    try: raw = _redact(_redact(_parse_json(bytes(chunks).decode("utf-8")), current["api_key"]), current["api_secret"])
                    except (ValueError, TypeError, UnicodeError, RecursionError): raise MediaSiloAPIError("MediaSilo JSON metadata is unverified") from None
        finally: await _stable(data, context)
        if isinstance(raw, dict) and (raw.get("error") is not None or raw.get("errors") is not None or raw.get("status") in ("error", "rejected", "pending_approval", "not_executed", "forbidden")):
            raise MediaSiloAPIError("MediaSilo did not return a documented successful protected resource")
        return raw
    except MediaSiloAPIError: raise
    except Exception: raise MediaSiloAPIError("MediaSilo transport did not establish a protected read result; no retry") from None
    finally: _PRIVATE_REQUEST.reset(private_token)

def _project_metadata(raw, *, expected=None, include_names=False):
    try:
        if not isinstance(raw, dict): raise ValueError()
        identifier = _id(raw.get("id")); name = _text(raw.get("name"))
        if expected is not None and identifier != expected: raise ValueError()
        item = {"id": identifier}
        if raw.get("accountId") is not None: item["accountId"] = _integer(raw["accountId"], 2147483647, 1)
        for key in ("dateCreated", "created"):
            if raw.get(key) is not None: item[key] = _date(raw[key])
        if raw.get("lastActivity") is not None: item["lastActivity"] = _integer(raw["lastActivity"])
        if raw.get("folderCount") is not None: item["folderCount"] = _integer(raw["folderCount"], 2147483647)
        if include_names: item["name"] = name
        return MediaSiloProjectMetadata.model_validate(item).model_dump(exclude_none=True)
    except (ValueError, TypeError): raise MediaSiloAPIError("MediaSilo returned another project ID or unverified project metadata") from None

def _folder_metadata(raw, project_id, *, expected=None, include_names=False):
    try:
        if not isinstance(raw, dict): raise ValueError()
        identifier = _id(raw.get("id")); name = _text(raw.get("name")); parent_project = _id(raw.get("projectId"))
        if parent_project != project_id or expected is not None and identifier != expected: raise ValueError()
        item = {"id": identifier, "projectId": parent_project}
        if raw.get("parentId") is not None:
            item["parentId"] = _id(raw["parentId"])
            if item["parentId"] == identifier: raise ValueError()
        for key in ("folderCount", "assetsCount", "size"):
            if raw.get(key) is not None: item[key] = _integer(raw[key], 2147483647 if key == "folderCount" else SAFE_INTEGER)
        if include_names: item["name"] = name
        return MediaSiloFolderMetadata.model_validate(item).model_dump(exclude_none=True)
    except (ValueError, TypeError): raise MediaSiloAPIError("MediaSilo returned another folder/project ID or unverified folder metadata") from None

def _rows(raw, parser):
    if not isinstance(raw, list) or len(raw) > MAX_ROWS: raise MediaSiloAPIError("MediaSilo did not return the documented bounded bare array")
    items = [parser(row) for row in raw]
    if len({item["id"] for item in items}) != len(items): raise MediaSiloAPIError("MediaSilo repeats a resource ID in the observed catalog")
    return items

async def _projects(data, context, *, include_names=False):
    raw = await _request(data, context, "/projects")
    rows = _rows(raw, lambda row: _project_metadata(row, include_names=include_names))
    await _stable(data, context)
    return rows

def _same_project(before, after):
    if before["id"] != after["id"] or "accountId" in before and "accountId" in after and before["accountId"] != after["accountId"]: raise MediaSiloAPIError("MediaSilo protected project resource scope changed during the read")

async def _project_witness(data, context, project_id, *, include_names=False):
    project_id = _id(project_id)
    catalog = await _projects(data, context)
    selected = next((row for row in catalog if row["id"] == project_id), None)
    if selected is None: raise MediaSiloAPIError("MediaSilo selected project is absent from the bounded protected catalog; access remains unverified")
    raw = await _request(data, context, "/projects/" + project_id)
    item = _project_metadata(raw, expected=project_id, include_names=include_names)
    _same_project(selected, item)
    await _stable(data, context)
    return item

async def _folders(data, context, project_id, *, include_names=False):
    before = await _project_witness(data, context, project_id)
    raw = await _request(data, context, "/projects/" + project_id + "/folders")
    rows = _rows(raw, lambda row: _folder_metadata(row, project_id, include_names=include_names))
    after = _project_metadata(await _request(data, context, "/projects/" + project_id), expected=project_id)
    _same_project(before, after)
    await _stable(data, context)
    return rows

class MediaSiloNode(WorkflowNode):
    integration_type = "automation-mediasilo"
    credential_provider_labels = {"mediasilo": "Mediasilo Account"}
    auto_select_credential = False
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="test_connection", noun="MediaSilo protected project catalog read access", proves="reachability", label_keys=("id",))
    edit_examples = ["Read project identifiers, times and folder counts", "Read folder counts within an accessible selected project", "Opt in to names while omitting media, owners, links and settings"]
    @classmethod
    def get_config_model(cls): return MediaSiloNodeConfig
    @classmethod
    def parse_config(cls, config_data: Dict[str, Any]):
        _original_family(config_data); _original_ids(config_data); shaped = dict(config_data)
        if config_data.get("credentials") is not None: shaped["credentials"] = _shape(config_data["credentials"])
        try: MediaSiloNodeConfig.model_validate(runtime_config_view(shaped, MediaSiloNodeConfig))
        except ValueError: raise ValueError("MediaSilo native configuration, resource scope or credential is invalid") from None
        return super().parse_config(shaped)
    @classmethod
    def validate_config(cls, config_data: Dict[str, Any]):
        try:
            _original_family(config_data); _original_ids(config_data); shaped = dict(config_data)
            if config_data.get("credentials") is not None: shaped["credentials"] = _shape(config_data["credentials"])
            MediaSiloNodeConfig.model_validate(runtime_config_view(shaped, MediaSiloNodeConfig))
        except (ValueError, TypeError): return ValidationResult(valid=False, errors=["MediaSilo native configuration or credential family is invalid"], satisfied_set=None)
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
        # Staging invokes this hook with the supplied credential only. Saved-row
        # authority is checked by execute/freshen, where actor and row ID exist.
        try:
            await _projects(_shape(data), {})
        except (MediaSiloAPIError, ValueError):
            return {"valid": None, "error": "MediaSilo protected catalog read was not executed or verified"}
        return {"valid": True, "proves": "reachability", "account_identity_verified": False, "user_identity_verified": False, "account_ownership_verified": False, "all_permissions_verified": False, "entitlement_verified": False}
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, MediaSiloNodeConfig) or self.config.credentials is None: raise ValueError("MediaSilo requires an existing native key and secret")
        node_data = self.node_data or {}; raw = node_data.get("credentials")
        data = _shape(raw if isinstance(raw, dict) else self.config.credentials.model_dump())
        context = {"_approval_pool": node_data.get("_approval_pool"), "_credential_id": node_data.get("credential_id"), "_user_id": self.user_id, "_organization_id": self.organization_id, "_workflow_id": self.workflow_id}
        current = await _current_data(data, **_authority(context))
        if node_data.get("credential_id") and not _bound_matches(data, current): raise MediaSiloAPIError("MediaSilo saved-row key/secret binding changed before transport", authority_rejected=True)
        result = await self._operation(self.config.config, current, context); await _stable(current, context)
        return {"status": "success", "operation": self.config.config.operation, "data": MediaSiloResult.model_validate(result).model_dump(exclude_none=True)}
    @staticmethod
    async def _operation(cfg, data, context):
        if cfg.operation in ("test_connection", "list_projects"):
            names = cfg.include_names if cfg.operation == "list_projects" else False
            rows = await _projects(data, context, include_names=names)
            result = {"results" if cfg.operation == "test_connection" else "projects": rows, "names_included": names, "pagination": MediaSiloObservation(returned_count=len(rows)).model_dump()}
            if cfg.operation == "test_connection": result.update(protected_read_completed=True, all_permissions_verified=False, entitlement_verified=False, proves="reachability")
            return result
        if cfg.operation == "get_project":
            return {"project": await _project_witness(data, context, cfg.project_id, include_names=cfg.include_names), "protected_project_scope_verified": True, "names_included": cfg.include_names}
        rows = await _folders(data, context, cfg.project_id, include_names=cfg.include_names if cfg.operation == "list_folders" else False)
        if cfg.operation == "list_folders": return {"folders": rows, "pagination": MediaSiloObservation(returned_count=len(rows)).model_dump(), "protected_project_scope_verified": True, "returned_folder_project_id_verified": True, "names_included": cfg.include_names}
        if not any(row["id"] == cfg.folder_id for row in rows): raise MediaSiloAPIError("MediaSilo selected folder is absent from the selected project's bounded protected catalog")
        raw = await _request(data, context, "/folders/" + cfg.folder_id)
        item = _folder_metadata(raw, cfg.project_id, expected=cfg.folder_id, include_names=cfg.include_names)
        observed = next(row for row in rows if row["id"] == cfg.folder_id)
        if observed.get("parentId") != item.get("parentId"): raise MediaSiloAPIError("MediaSilo selected folder hierarchy changed during the read")
        await _project_witness(data, context, cfg.project_id)
        return {"folder": item, "protected_project_scope_verified": True, "returned_folder_project_id_verified": True, "names_included": cfg.include_names}
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        if field_name not in ("project_id", "folder_id"): return {"options": [], "next_page_token": None}
        if page_token is not None: raise ValueError("MediaSilo request continuation contract is unspecified; no cursor/URL transport")
        context = _context(credential_data, context or {})
        if search not in (None, "") and (not isinstance(search, str) or len(search) > 128 or not re.fullmatch(r"[A-Za-z0-9_-]+", search)): raise ValueError("MediaSilo picker search supports bounded local resource ID characters only")
        data = await _current_data(credential_data, **_authority(context))
        if context.get("_credential_id") and not _bound_matches(credential_data, data): raise MediaSiloAPIError("MediaSilo picker saved-row key/secret binding changed", authority_rejected=True)
        rows = await _projects(data, context) if field_name == "project_id" else await _folders(data, context, _id(context.get("project_id")))
        if search: rows = [row for row in rows if search in row["id"]]
        await _stable(data, context)
        return {"options": [{"value": row["id"], "label": row["id"]} for row in rows], "next_page_token": None}

def _shape(data):
    if not isinstance(data, dict) or data.get("credential_type", FAMILIES[0]) not in FAMILIES: raise ValueError("MediaSilo credential family is unsupported")
    try: shaped = MediaSiloAPIKeyCredential.model_validate({**data, "credential_type": FAMILIES[0]}).model_dump()
    except ValueError: raise ValueError("MediaSilo native credential is invalid") from None
    return {**data, **shaped}

def _binding(data):
    return (data["credential_type"], data["api_key"], data["api_secret"], data.get("owner_id"), data.get("token_version"), data.get("updated_at"), data.get("approval_revision"))

def _bound_matches(bound, current):
    return all(bound.get(key) == current.get(key) for key in ("credential_type", "api_key", "api_secret")) and all(bound[key] == current.get(key) for key in ("owner_id", "token_version", "updated_at", "approval_revision") if key in bound)

def _original_family(data):
    if not isinstance(data, dict):
        raise ValueError("MediaSilo configuration is invalid")
    creds = data.get("credentials")
    saved = data.get("credential_id") or data.get("credentialIds")
    if saved and not isinstance(creds, dict) or isinstance(creds, dict) and (creds.get("credential_type") is not None or saved) and creds.get("credential_type") not in FAMILIES:
        raise ValueError("MediaSilo saved credential family is missing or unsupported")


def _original_ids(data):
    # Check resource IDs before the shared runtime view coerces values to strings.
    config = data.get("config")
    if isinstance(config, dict):
        for field in ("project_id", "folder_id"):
            if field in config:
                _id(config[field])


@dataclass(frozen=True, repr=False)
class _LookupAuthority:
    pool: Any
    user_id: str
    credential_id: str
    organization_id: Optional[str]
    workflow_id: Optional[str]


@dataclass(frozen=True, repr=False)
class _MediaSiloCredentialRow:
    credential_type: Optional[str]
    owner_id: str
    token_version: int
    updated_at: datetime
    approval_revision: int
    revoked_at: Optional[datetime]
    credential: Any


async def _fetch_authority(pool, credential_id, user_id, organization_id):
    from repositories.credentials import credential_access_predicate
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT c.credential_type,c.owner_id,c.token_version,c.updated_at,"
            "c.approval_revision,c.revoked_at,c.credential FROM credentials c "
            f"WHERE c.id=$1 AND {credential_access_predicate()}",
            credential_id, user_id, organization_id,
        )
    return _MediaSiloCredentialRow(
        credential_type=row["credential_type"], owner_id=str(row["owner_id"]),
        token_version=row["token_version"], updated_at=row["updated_at"],
        approval_revision=row["approval_revision"], revoked_at=row["revoked_at"],
        credential=row["credential"],
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
            raise ValueError("MediaSilo current credential is unavailable, revoked or its family is unsupported")
        try:
            blob = get_encryption().decrypt_credential(row.credential)
        except Exception:
            raise ValueError("MediaSilo current credential could not be decrypted") from None
        if not isinstance(blob, dict):
            raise ValueError("MediaSilo current credential data is invalid")
        return _shape({**blob, "credential_type": row.credential_type, "owner_id": row.owner_id, "token_version": row.token_version, "updated_at": row.updated_at.isoformat() if row.updated_at else None, "approval_revision": row.approval_revision})
    # Follow staging's runner/authorized-owner/lender policy, using this node's
    # current-row read so metadata and the decrypted keys stay bound together.
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
        raise ValueError("MediaSilo current credential is unavailable or access denied")
    return {**result, "_mediasilo_authority": _LookupAuthority(pool, user_id, credential_id, organization_id, workflow_id)}


def _context(data, context):
    result = {k: v for k, v in context.items() if not k.startswith("_")}
    result["_user_id"] = context.get("_user_id")
    bound = data.get("_mediasilo_authority") if isinstance(data, dict) else None
    if type(bound) is _LookupAuthority:
        if bound.user_id != context.get("_user_id"):
            raise ValueError("MediaSilo picker actor does not match saved authority")
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
_PRIVATE_REQUEST = ContextVar("mediasilo_private_request", default=False)


class _TransportPrivacy(logging.Filter):
    def filter(self, record):
        if _PRIVATE_REQUEST.get():
            record.msg, record.args = "MediaSilo private transport activity", ()
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
    except ValueError: raise MediaSiloAPIError("MediaSilo current credential authority is unavailable or revoked", authority_rejected=True) from None
    if _binding(current) != _binding(data): raise MediaSiloAPIError("MediaSilo current key, owner, version or approval revision changed; result is not accepted", authority_rejected=True)
    return current


