"""Current Xata control-plane metadata; closed read-only resource contracts."""
from __future__ import annotations
import re
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

API_ROOT = "https://api.xata.tech"
HIDDEN = {"ui:hidden": True}
ROUTES = {"organizations": "/organizations", "organization": "/organizations/{organization}",
    "projects": "/organizations/{organization}/projects", "project": "/organizations/{organization}/projects/{project}",
    "branches": "/organizations/{organization}/projects/{project}/branches",
    "backups": "/organizations/{organization}/projects/{project}/backups",
    "backup": "/organizations/{organization}/projects/{project}/backups/{backup}"}
ROUTE_SCOPES = {k: ("org:read" if k in {"organizations", "organization"} else "branch:read" if k == "branches" else "project:read") for k in ROUTES}
XATA_SCOPES = ScopeRegistry("xata", {k: ScopeRequirement((s,), credential_types=("xata_issued_oauth",)) for k, s in ROUTE_SCOPES.items()})

def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_~:-][A-Za-z0-9_.~:-]{0,255}", value):
        raise ValueError("Use an existing bounded Xata resource ID, not a URL or path.")
    return value

def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 512 or re.search(r"[\x00-\x1f\x7f]|://|www\.", value, re.I):
        raise ValueError("Use bounded text without URLs or control characters.")
    return value.strip()

def _time(value):
    if not isinstance(value, str) or len(value) > 64 or datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
        raise ValueError("Use the documented timestamp with a time zone.")
    return value

class XataIssuedOAuthCredential(BaseModel):
    credential_type: Literal["xata_issued_oauth"] = Field("xata_issued_oauth", json_schema_extra=HIDDEN)
    access_token: str = Field(..., min_length=1, max_length=8192, title="Existing Xata OAuth Access Token",
        json_schema_extra={"ui:widget": "password"}, description="Issued OAuth token for current api.xata.tech. No API-key fallback, exchange or refresh.")
    granted_scopes: list[Literal["org:read", "project:read", "branch:read"]] = Field(..., min_length=1, max_length=3,
        description="Actual existing grant scopes. Parent catalog checks additionally require org:read and project:read. Provider permission remains authoritative.")
    expires_at: Optional[str] = Field(None, max_length=64, description="Actual issued expiry when available, with time zone. No assumed lifetime or renewal.")
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://xata.io/docs/api-reference/organizations/get-list-of-organizations",
        "x-credential-instructions": "Enter an existing scoped OAuth Bearer token and actual granted scopes. Selected current routes declare OAuth-only security despite a global API-key component. No popup, minting, refresh, API-key fallback or legacy Xata API."})
    @field_validator("access_token", mode="before")
    @classmethod
    def issued_token(cls, value):
        if not isinstance(value, str) or not value or re.search(r"[\x00-\x20\x7f]|://", value):
            raise ValueError("Supply the issued token without a prefix, whitespace or URL.")
        return value
    @field_validator("granted_scopes")
    @classmethod
    def unique_scopes(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("List each actually granted scope once.")
        return value
    @field_validator("expires_at")
    @classmethod
    def actual_expiry(cls, value):
        return _time(value) if value is not None else None

def _credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != "xata_issued_oauth":
        raise ValueError("Use the current Xata issued OAuth credential.")
    try:
        model = XataIssuedOAuthCredential.model_validate({k: data[k] for k in XataIssuedOAuthCredential.model_fields if k in data})
        if model.expires_at is not None and datetime.fromisoformat(model.expires_at.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            raise ValueError()
    except Exception:
        raise ValueError("The Xata issued token or grant metadata is incomplete, invalid or expired.") from None
    return {**data, **model.model_dump(mode="json")}

def _picker(field):
    options = {"field_name": field}
    if field == "project_id":
        options["depends_on"] = "organization_id"
    elif field in {"branch_id", "backup_id"}:
        options["depends_on"] = "project_id"
    return {"x-dynamic-options": options}

class XataReadConfig(BaseModel):
    include_names: bool = Field(False, strict=True, description="Opt in to organization/project/branch names. Descriptions and configuration remain excluded.")
    max_items: int = Field(100, strict=True, ge=1, le=1000, description="Local output bound only; no documented pagination, total or completion guarantee.")
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
class XataCheckConfig(XataReadConfig):
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra=HIDDEN)
class XataOrganizationsConfig(XataReadConfig):
    operation: Literal["list_organizations"] = Field("list_organizations", json_schema_extra=HIDDEN)
class XataOrganizationConfig(XataReadConfig):
    organization_id: str = Field(..., min_length=1, max_length=256, json_schema_extra=_picker("organization_id"))
    _organization_value = field_validator("organization_id", mode="before")(_id)
class XataGetOrganizationConfig(XataOrganizationConfig):
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra=HIDDEN)
class XataProjectsConfig(XataOrganizationConfig):
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra=HIDDEN)
class XataProjectConfig(XataOrganizationConfig):
    project_id: str = Field(..., min_length=1, max_length=256, json_schema_extra=_picker("project_id"))
    _project_value = field_validator("project_id", mode="before")(_id)
class XataGetProjectConfig(XataProjectConfig):
    operation: Literal["get_project"] = Field("get_project", json_schema_extra=HIDDEN)
class XataBranchesConfig(XataProjectConfig):
    operation: Literal["list_branches"] = Field("list_branches", json_schema_extra=HIDDEN)
class XataBackupsConfig(XataProjectConfig):
    operation: Literal["list_backups"] = Field("list_backups", json_schema_extra=HIDDEN)
class XataGetBackupConfig(XataProjectConfig):
    operation: Literal["get_backup"] = Field("get_backup", json_schema_extra=HIDDEN)
    backup_id: str = Field(..., min_length=1, max_length=256, json_schema_extra=_picker("backup_id"))
    _backup_value = field_validator("backup_id", mode="before")(_id)
XataConfig = Annotated[Union[XataCheckConfig, XataOrganizationsConfig, XataGetOrganizationConfig,
    XataProjectsConfig, XataGetProjectConfig, XataBranchesConfig, XataBackupsConfig, XataGetBackupConfig], Field(discriminator="operation")]
class XataNodeConfig(NodeConfig[XataConfig, XataIssuedOAuthCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)

async def _request(data, kind, *, organization=None, project=None, backup=None):
    data = _credential(data)
    if kind not in ROUTES:
        raise ValueError("Unsupported Xata metadata route.")
    XATA_SCOPES.enforce_credential_type(kind, data["credential_type"])
    if ROUTE_SCOPES[kind] not in data["granted_scopes"]:
        raise ValueError("The existing Xata grant does not declare the scope required for this route.")
    path = ROUTES[kind]
    for key, value in (("organization", organization), ("project", project), ("backup", backup)):
        if "{"+key+"}" in path:
            value = _id(value)
            if key == "organization" and not re.fullmatch(r"[a-zA-Z0-9_~:-]+", value):
                raise ValueError("Use the documented Xata organization ID.")
            path = path.replace("{"+key+"}", quote(value, safe=""))
        elif value is not None:
            raise ValueError("This Xata route does not accept that parent.")
    try:
        async with guarded_async_client( trust_env=False, follow_redirects=False, timeout=25) as client:
            response = await client.get(API_ROOT+path, headers={"Authorization": "Bearer "+data["access_token"],
                "Accept": "application/json", "User-Agent": "NoClick-Xata/1.0 (+https://noclick.com)"})
    except Exception:
        raise RuntimeError("Xata could not be reached; access remains unverified.") from None
    if response.status_code != 200:
        messages = {400: "Xata refused the metadata parameters.", 401: "Xata did not confirm token or grant access.",
            403: "Xata did not confirm access to this resource.", 404: "The selected Xata resource is unavailable.",
            429: "Xata throttled the metadata request; try again later."}
        raise RuntimeError(messages.get(response.status_code, "Xata did not return usable metadata."))
    if len(response.content) > 2000000:
        raise RuntimeError("Xata metadata exceeded the client response bound.")
    try:
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        body = response.json()
        if (mime != "application/json" and not mime.endswith("+json")) or not isinstance(body, dict) or any(k in body for k in ("error", "errors")):
            raise ValueError()
        return body
    except Exception:
        raise RuntimeError("Xata returned an unsupported metadata envelope.") from None

def _row(raw, kind, names=False, expected_id=None):
    try:
        if not isinstance(raw, dict):
            raise ValueError()
        result = {"id": _id(raw.get("id"))}
        if expected_id is not None and result["id"] != expected_id:
            raise ValueError()
        if kind == "organizations":
            status = raw["status"]
            if not isinstance(status, dict) or status.get("status") not in {"enabled", "disabled"}:
                raise ValueError()
            result["status"] = {"status": status["status"], "last_updated": _time(status["last_updated"])}
            if "created_at" in status:
                result["status"]["created_at"] = _time(status["created_at"])
        elif kind in {"projects", "branches"}:
            result.update(createdAt=_time(raw["createdAt"]), updatedAt=_time(raw["updatedAt"]))
        elif kind == "backups":
            result["branchID"] = _id(raw["branchID"])
            for key in ("earliestRestore", "latestRestore"):
                if key in raw:
                    result[key] = _time(raw[key])
        else:
            raise ValueError()
        if names and kind != "backups":
            result["name"] = _text(raw["name"])
        return result
    except Exception:
        raise RuntimeError("Xata returned metadata outside the selected resource contract.") from None

async def _catalog(data, kind, *, organization=None, project=None, names=False):
    body = await _request(data, kind, organization=organization, project=project)
    raw = body.get(kind)
    if not isinstance(raw, list) or len(raw) > 1000:
        raise RuntimeError("Xata returned an unsupported or excessive unpaged catalog.")
    rows = [_row(item, kind, names) for item in raw]
    if len({row["id"] for row in rows}) != len(rows):
        raise RuntimeError("Xata returned duplicate IDs in the selected catalog.")
    return rows

def _witness(rows, resource_id):
    if not any(row["id"] == resource_id for row in rows):
        raise ValueError("The selected Xata resource was not witnessed in the bounded current parent catalog; access remains unverified.")

async def _parents(data, organization, project=None):
    _witness(await _catalog(data, "organizations"), organization)
    if project is not None:
        _witness(await _catalog(data, "projects", organization=organization), project)

async def _backups(data, organization, project):
    branches = await _catalog(data, "branches", organization=organization, project=project)
    rows = await _catalog(data, "backups", organization=organization, project=project)
    for row in rows:
        _witness(branches, row["branchID"])
    return rows

def _bounded(rows, maximum):
    return {"items": rows[:maximum], "returned": min(len(rows), maximum), "provider_returned": len(rows),
        "local_truncated": len(rows) > maximum, "completion": "unknown; unpaged provider array, no documented total or continuation"}

class XataNode(WorkflowNode):
    integration_type = "automation-xata"
    credential_provider_labels = {"xata": "Xata Account"}
    auto_select_credential = False
    scope_registry = XATA_SCOPES
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="accessible organization IDs", label_keys=("id",), proves="reachability")
    @classmethod
    def get_config_model(cls):
        return XataNodeConfig
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Staging's loaders resolve the current saved row before this hook.
        return _credential(credential_data)
    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            _credential(credential_data)
        except ValueError:
            return {"valid": False, "error": "The Xata issued token or grant metadata is invalid or expired."}
        # This legacy hook has no admission context; connection evidence runs the probe.
        return {"valid": None, "error": "Run Check connection to verify current Xata catalog reachability."}
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        data = _credential(credential_data)
        if page_token is not None:
            raise ValueError("Xata documents no continuation for these catalogs.")
        if field_name not in {"organization_id", "project_id", "branch_id", "backup_id"} or context is not None and not isinstance(context, dict):
            raise ValueError("Use a supported Xata resource selector.")
        search = _text(search).casefold() if search is not None else None
        context = context or {}
        organization = _id(context.get("organization_id")) if field_name != "organization_id" else None
        project = _id(context.get("project_id")) if field_name in {"branch_id", "backup_id"} else None
        if organization is not None:
            await _parents(data, organization, project)
        kind = {"organization_id": "organizations", "project_id": "projects", "branch_id": "branches", "backup_id": "backups"}[field_name]
        rows = await _backups(data, organization, project) if kind == "backups" else await _catalog(data, kind, organization=organization, project=project)
        return {"options": [{"value": row["id"], "label": row["id"]} for row in rows if search is None or search in row["id"].casefold()], "next_page_token": None}
    async def execute(self, inputs):
        if not isinstance(self.config, XataNodeConfig) or not self.config.credentials:
            raise ValueError("Xata configuration and an existing issued OAuth token are required.")
        raw = (self.node_data or {}).get("credentials")
        data = _credential(raw if isinstance(raw, dict) else self.config.credentials.model_dump(mode="json"))
        c, op = self.config.config, self.config.config.operation
        common = {"proof": "Protected current organization/project catalogs provide access ancestry; no principal, ownership or tenant identity is inferred."}
        if op in {"check_connection", "list_organizations"}:
            return {**common, **_bounded(await _catalog(data, "organizations", names=c.include_names), c.max_items),
                **({"protected_catalog": True} if op == "check_connection" else {})}
        await _parents(data, c.organization_id, getattr(c, "project_id", None))
        common["selected_organization_id"] = c.organization_id
        if op == "get_organization":
            return {**common, "organization": _row(await _request(data, "organization", organization=c.organization_id), "organizations", c.include_names, c.organization_id)}
        if op == "list_projects":
            return {**common, **_bounded(await _catalog(data, "projects", organization=c.organization_id, names=c.include_names), c.max_items)}
        common["selected_project_id"] = c.project_id
        if op == "get_project":
            return {**common, "project": _row(await _request(data, "project", organization=c.organization_id, project=c.project_id), "projects", c.include_names, c.project_id)}
        if op == "list_branches":
            return {**common, **_bounded(await _catalog(data, "branches", organization=c.organization_id, project=c.project_id, names=c.include_names), c.max_items)}
        backups = await _backups(data, c.organization_id, c.project_id)
        if op == "list_backups":
            return {**common, **_bounded(backups, c.max_items)}
        if op == "get_backup":
            _witness(backups, c.backup_id)
            row = _row(await _request(data, "backup", organization=c.organization_id, project=c.project_id, backup=c.backup_id), "backups", False, c.backup_id)
            _witness(await _catalog(data, "branches", organization=c.organization_id, project=c.project_id), row["branchID"])
            return {**common, "backup": row}
        raise ValueError("Unsupported Xata metadata operation.")
