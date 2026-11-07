"""Atlassian Bamboo CI: five native metadata operations, four closed GET routes."""
from __future__ import annotations
import ipaddress
import re
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit, quote
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import allow_private_hosts, guarded_async_client, normalize_https_origin

HIDDEN = {"ui:hidden": True}
ROUTES = {"projects": "/project", "project": "/project/{project}", "plans": "/plan", "plan": "/plan/{plan}"}
BAMBOOCI_SCOPES = ScopeRegistry("bambooci", {k: ScopeRequirement((), credential_types=("bambooci_pat",),
    note="Existing PAT Bearer from the official guide; current server READ/VIEW permission, no invented OAuth scope.") for k in ROUTES})

def _instance(value):
    try:
        if not isinstance(value, str) or value != value.strip() or re.search(r"[\x00-\x20\x7f\\%]", value) or "?" in value or "#" in value:
            raise ValueError()
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.username is not None or parts.password is not None or parts.query or parts.fragment:
            raise ValueError()
        origin = normalize_https_origin("https://"+parts.netloc)
        host = urlsplit(origin).hostname
        if not host or "." not in host or host.endswith((".local", ".localhost", ".internal", ".invalid", ".test")):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
        if parts.path not in ("", "/") and not re.fullmatch(r"/[A-Za-z0-9][A-Za-z0-9_-]{0,63}/?", parts.path):
            raise ValueError()
        context = parts.path.rstrip("/")
        if context and (not re.fullmatch(r"/[A-Za-z0-9][A-Za-z0-9_-]{0,63}", context) or context.lower() in {"/rest", "/api", "/latest", "/admin", "/login"}):
            raise ValueError()
        return origin+context
    except Exception:
        raise ValueError("Use the actual public HTTPS Bamboo deployment URL, with at most one configured context segment; no IP, userinfo, query or API path.") from None

def _key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,128}", value):
        raise ValueError("Use an existing bounded Bamboo project key.")
    return value

def _plan_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,128}-[A-Za-z0-9_]{1,128}(?:-[A-Za-z0-9_]{1,128})?", value):
        raise ValueError("Use an existing project-prefixed Bamboo plan key, not a URL.")
    return value

def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 512 or re.search(r"[\x00-\x1f\x7f]|://|www\.", value, re.I):
        raise ValueError("Use bounded metadata text without URLs or control characters.")
    return value.strip()

class BambooPATCredential(BaseModel):
    credential_type: Literal["bambooci_pat"] = Field("bambooci_pat", json_schema_extra=HIDDEN)
    instance_url: str = Field(..., min_length=1, max_length=512, title="Public HTTPS Bamboo Deployment URL",
        description="Existing public DNS HTTPS origin, optionally its actual single context segment such as /bamboo. Do not include /rest/api/latest.")
    project_key: str = Field(..., min_length=1, max_length=128, title="Bound Existing Project Key",
        description="Independently supplied project binding, verified in the current catalog before metadata reads. This is an access witness, not ownership.")
    access_token: str = Field(..., min_length=1, max_length=8192, title="Existing Bamboo Personal Access Token",
        json_schema_extra={"ui:widget": "password"}, description="Issued PAT without Bearer prefix. No Basic login, OAuth flow, issuance or inferred lifetime.")
    model_config = ConfigDict(title="Bamboo CI Personal Access Token", extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developer.atlassian.com/server/bamboo/using-the-bamboo-rest-apis/",
        "x-credential-instructions": "Supply the existing PAT, public HTTPS deployment URL and independently known project key. Current READ/VIEW permissions apply. Catalog reachability does not identify the actor. Current OAS JSON deployment parity remains unverified."})
    _instance_value = field_validator("instance_url", mode="before")(_instance)
    _project_value = field_validator("project_key", mode="before")(_key)
    @field_validator("access_token", mode="before")
    @classmethod
    def issued_token(cls, value):
        if not isinstance(value, str) or not value or re.search(r"[\x00-\x20\x7f]|://", value):
            raise ValueError("Supply the existing raw PAT without whitespace, prefix or URL.")
        return value

def _credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != "bambooci_pat":
        raise ValueError("Use the current Bamboo CI PAT credential.")
    try:
        model = BambooPATCredential.model_validate({k: data[k] for k in BambooPATCredential.model_fields if k in data})
    except Exception:
        raise ValueError("The Bamboo PAT, public instance or project binding is invalid.") from None
    return {**data, **model.model_dump(mode="json")}

def _picker(field):
    options = {"field_name": field}
    if field == "plan_key":
        options["depends_on"] = "project_key"
    return {"x-dynamic-options": options}

class BambooCIReadConfig(BaseModel):
    include_names: bool = Field(False, strict=True, description="Opt in to project/plan names; private internal models and user/configuration data are always excluded.")
    max_items: int = Field(100, strict=True, ge=1, le=1000,
        description="Local bound on the default provider catalog page. No paging inputs, totals or completion guarantee are inferred.")
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
class BambooCICheckConfig(BambooCIReadConfig):
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra=HIDDEN)
class BambooCIProjectsConfig(BambooCIReadConfig):
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra=HIDDEN)
class BambooCIProjectConfig(BambooCIReadConfig):
    project_key: str = Field(..., min_length=1, max_length=128, json_schema_extra=_picker("project_key"),
        description="Must match the credential's independent project binding and current project catalog.")
    _project_value = field_validator("project_key", mode="before")(_key)
class BambooCIGetProjectConfig(BambooCIProjectConfig):
    operation: Literal["get_project"] = Field("get_project", json_schema_extra=HIDDEN)
class BambooCIPlansConfig(BambooCIProjectConfig):
    operation: Literal["list_plans"] = Field("list_plans", json_schema_extra=HIDDEN)
class BambooCIGetPlanConfig(BambooCIProjectConfig):
    operation: Literal["get_plan"] = Field("get_plan", json_schema_extra=HIDDEN)
    plan_key: str = Field(..., min_length=1, max_length=386, json_schema_extra=_picker("plan_key"),
        description="Exact JSON planKey witnessed in the current plan catalog with matching projectKey.")
    _plan_value = field_validator("plan_key", mode="before")(_plan_key)
BambooCIConfig = Annotated[Union[BambooCICheckConfig, BambooCIProjectsConfig, BambooCIGetProjectConfig,
    BambooCIPlansConfig, BambooCIGetPlanConfig], Field(discriminator="operation")]
class BambooCINodeConfig(NodeConfig[BambooCIConfig, BambooPATCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)

async def _request(data, kind, *, project=None, plan=None):
    data = _credential(data)
    if kind not in ROUTES:
        raise ValueError("Unsupported Bamboo metadata route.")
    BAMBOOCI_SCOPES.enforce_credential_type(kind, data["credential_type"])
    path = ROUTES[kind]
    if project is not None:
        if kind != "project" or _key(project) != data["project_key"]:
            raise ValueError("The selected Bamboo project does not match the current credential binding.")
        path = path.replace("{project}", quote(project, safe=""))
    elif kind == "project":
        raise ValueError("A bound Bamboo project is required.")
    if plan is not None:
        if kind != "plan" or _plan_key(plan).split("-", 1)[0] != data["project_key"]:
            raise ValueError("The selected Bamboo plan does not match the bound project.")
        path = path.replace("{plan}", quote(plan, safe=""))
    elif kind == "plan":
        raise ValueError("A bound Bamboo plan is required.")
    params = {"expand": kind} if kind in {"projects", "plans"} else {}
    try:
        if allow_private_hosts():
            raise ValueError("Bamboo requires public-only outbound transport.")
        async with guarded_async_client(trust_env=False, follow_redirects=False, timeout=25) as client:
            response = await client.get(data["instance_url"]+"/rest/api/latest"+path, params=params,
                headers={"Authorization": "Bearer "+data["access_token"], "Accept": "application/json",
                    "User-Agent": "NoClick-BambooCI/1.0 (+https://noclick.com)"})
    except Exception:
        raise RuntimeError("Bamboo could not be reached; access remains unverified.") from None
    if response.status_code != 200:
        messages = {401: "Bamboo did not confirm PAT access.", 403: "Bamboo did not confirm resource access.",
            404: "The selected Bamboo resource is unavailable.", 429: "Bamboo throttled the metadata request."}
        raise RuntimeError(messages.get(response.status_code, "Bamboo did not return usable metadata."))
    if len(response.content) > 2000000:
        raise RuntimeError("Bamboo metadata exceeded the response bound.")
    try:
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        body = response.json()
        if (mime != "application/json" and not mime.endswith("+json")) or not isinstance(body, dict) or any(k in body for k in ("error", "errors")):
            raise ValueError()
        return body
    except Exception:
        raise RuntimeError("Bamboo returned unsupported JSON metadata; deployment parity remains unverified.") from None

def _row(raw, kind, names=False, expected=None):
    try:
        if not isinstance(raw, dict):
            raise ValueError()
        if kind == "projects":
            row = {"key": _key(raw["key"])}
            identity = row["key"]
        else:
            row = {"planKey": _plan_key(raw["planKey"]), "projectKey": _key(raw["projectKey"])}
            if row["planKey"].split("-", 1)[0] != row["projectKey"]:
                raise ValueError()
            identity = row["planKey"]
            for flag in ("enabled", "active"):
                if flag in raw:
                    if type(raw[flag]) is not bool:
                        raise ValueError()
                    row[flag] = raw[flag]
            if "type" in raw:
                row["type"] = _text(raw["type"])
        if expected is not None and identity != expected:
            raise ValueError()
        if "id" in raw:
            if type(raw["id"]) is not int or not 0 <= raw["id"] < 2**63:
                raise ValueError()
            row["id"] = str(raw["id"])
        name_key = "name" if kind == "projects" else "planName"
        if names and name_key in raw:
            row[name_key] = _text(raw[name_key])
        return row
    except Exception:
        raise RuntimeError("Bamboo returned metadata outside the current JSON resource contract; XML aliases are not accepted.") from None

async def _catalog(data, kind, names=False):
    body = await _request(data, kind)
    container = body.get(kind)
    raw = container.get(kind) if isinstance(container, dict) else None
    if not isinstance(raw, list) or len(raw) > 1000:
        raise RuntimeError("Bamboo returned an unsupported current JSON catalog or excessive default page.")
    rows = [_row(item, kind, names) for item in raw]
    field = "key" if kind == "projects" else "planKey"
    if len({row[field] for row in rows}) != len(rows):
        raise RuntimeError("Bamboo returned duplicate resource keys.")
    page = {}
    for key in ("size", "startIndex", "maxResult"):
        if key in container:
            value = container[key]
            if type(value) is not int or not 0 <= value < 2**31:
                raise RuntimeError("Bamboo returned unsupported default-page metadata.")
            page[key] = value
    return rows, page

def _witness(rows, field, value):
    if not any(row[field] == value for row in rows):
        raise ValueError("The bound Bamboo resource was not witnessed on the current default catalog page; access remains unverified.")

async def _project_witness(data, project=None):
    if project is not None and _key(project) != data["project_key"]:
        raise ValueError("The selected Bamboo project does not match the current credential binding.")
    rows, page = await _catalog(data, "projects")
    _witness(rows, "key", data["project_key"])

def _bound_plans(rows, project):
    return [row for row in rows if row["projectKey"] == project]

def _bounded(rows, maximum, page, provider_returned):
    return {"items": rows[:maximum], "returned": min(len(rows), maximum), "provider_returned": provider_returned,
        "local_truncated": len(rows) > maximum, "provider_page_metadata": page,
        "completion": "unknown; default catalog page, returned size/startIndex/maxResult scope unspecified"}

class BambooCINode(WorkflowNode):
    integration_type = "automation-bambooci"
    scope_registry = BAMBOOCI_SCOPES
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="bound project keys", label_keys=("key",), proves="reachability")
    @classmethod
    def get_config_model(cls):
        return BambooCINodeConfig
    @classmethod
    async def validate_credential_access(cls, credential_data):
        # Staging passes the decrypted credential to this hook. PATs do not
        # rotate, so the inherited freshen_credential hook is sufficient.
        try:
            data = _credential(credential_data)
            await _project_witness(data)
        except (ValueError, RuntimeError):
            return {"valid": None, "error": "Bamboo project access could not be verified."}
        return {"valid": True}
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        data = _credential(credential_data)
        if field_name not in {"project_key", "plan_key"} or page_token is not None or context is not None and not isinstance(context, dict):
            raise ValueError("Use a supported Bamboo key selector; no catalog continuation is documented.")
        search = _text(search).casefold() if search is not None else None
        if field_name == "project_key":
            rows, _ = await _catalog(data, "projects")
            _witness(rows, "key", data["project_key"])
            rows = [row for row in rows if row["key"] == data["project_key"]]
            key = "key"
        else:
            project = _key((context or {}).get("project_key"))
            await _project_witness(data, project)
            rows, _ = await _catalog(data, "plans")
            rows, key = _bound_plans(rows, project), "planKey"
        return {"options": [{"value": row[key], "label": row[key]} for row in rows if search is None or search in row[key].casefold()], "next_page_token": None}
    async def execute(self, inputs):
        if not isinstance(self.config, BambooCINodeConfig) or not self.config.credentials:
            raise ValueError("Bamboo configuration and a bound existing PAT are required.")
        raw = (self.node_data or {}).get("credentials")
        if not (self.node_data or {}).get("credential_id") and isinstance(raw, dict):
            _credential(raw)
        # The common execution loader resolves saved credentials, including
        # workflow access. Like other PAT nodes on staging, use that loaded value.
        data = _credential(self.config.credentials.model_dump(mode="json"))
        c, op = self.config.config, self.config.config.operation
        common = {"proof": "Configured public instance and independently bound project catalog/detail access; no principal, account or team ownership is inferred."}
        if op == "get_plan" and c.plan_key.split("-", 1)[0] != data["project_key"]:
            raise ValueError("The selected Bamboo plan does not match the bound project.")
        if op in {"check_connection", "list_projects"}:
            rows, page = await _catalog(data, "projects", c.include_names)
            _witness(rows, "key", data["project_key"])
            result = _bounded([row for row in rows if row["key"] == data["project_key"]], c.max_items, page, len(rows))
            return {**common, **result, **({"protected_catalog": True} if op == "check_connection" else {})}
        await _project_witness(data, c.project_key)
        common["selected_project_key"] = c.project_key
        if op == "get_project":
            return {**common, "project": _row(await _request(data, "project", project=c.project_key), "projects", c.include_names, c.project_key)}
        rows, page = await _catalog(data, "plans", c.include_names)
        selected = _bound_plans(rows, c.project_key)
        if op == "list_plans":
            return {**common, **_bounded(selected, c.max_items, page, len(rows))}
        if op == "get_plan":
            if c.plan_key.split("-", 1)[0] != c.project_key:
                raise ValueError("The selected Bamboo plan does not match the bound project.")
            _witness(selected, "planKey", c.plan_key)
            row = _row(await _request(data, "plan", plan=c.plan_key), "plans", c.include_names, c.plan_key)
            if row["projectKey"] != c.project_key:
                raise RuntimeError("Bamboo detail project ancestry did not match the current binding.")
            return {**common, "plan": row}
        raise ValueError("Unsupported Bamboo metadata operation.")
