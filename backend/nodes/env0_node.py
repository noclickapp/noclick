"""Native env zero organization, project, environment and deployment metadata.

Supplied key pairs remain in Basic headers at the fixed official API host.
Saved resource restrictions and provider resource ancestry gate acceptance.
"""
import base64
from datetime import datetime
import json
import re
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import normalize_search
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

FAMILY = "env0_api_key"
NODE_TYPE = "automation-env0"
ROOT = "https://api.env0.com"
KINDS = ("organizations", "projects", "environments", "deployments")
OPS = ("check_connection", "list_organizations", "get_organization", "list_projects", "get_project",
       "list_environments", "get_environment", "list_deployments", "get_deployment")
ENV_FIELDS = "id,organizationId,projectId,status,createdAt,updatedAt"
DEPLOYMENT_FIELDS = "id,environmentId,status,type,createdAt,updatedAt,queuedAt,startedAt,finishedAt"


def resource_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("Enter an existing env zero ID without a URL or path")
    return value


def strict_json(value):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result: raise ValueError("Duplicate JSON key")
            result[key] = item
        return result
    def constant(_): raise ValueError("Nonfinite JSON value")
    try: return json.loads(value, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, TypeError, UnicodeError): raise ValueError("Use valid bounded JSON") from None


def grants(value):
    if not isinstance(value, str) or len(value) > 30000: raise ValueError("Enter approved resource IDs as bounded JSON")
    raw = strict_json(value)
    if not isinstance(raw, dict) or set(raw) != set(KINDS): raise ValueError("Approve the four native resource kinds")
    for ids in raw.values():
        if not isinstance(ids, list) or len(ids) > 50: raise ValueError("Approve at most 50 IDs per kind")
        for item in ids: resource_id(item)
        if len(set(ids)) != len(ids): raise ValueError("Approve distinct resource IDs")
    return raw


class Env0APIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="env zero API Key",
        json_schema_extra={"x-credential-instructions": "Enter an existing API key ID and secret. Organization keys and personal keys have different permissions. Catalog access does not identify a principal or prove organization ownership.", "x-help-url": "https://docs.envzero.com/api-reference/organization/list-organizations"})
    credential_type: Literal["env0_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key_id: str = Field(..., title="API Key ID", json_schema_extra={"ui:widget": "password", "ui:sensitive": True})
    api_key_secret: str = Field(..., title="API Key Secret", json_schema_extra={"ui:widget": "password", "ui:sensitive": True})
    approved_resources_json: str = Field('{"organizations":[],"projects":[],"environments":[],"deployments":[]}', title="Approved Resource IDs",
        description="Existing IDs grouped by organizations, projects, environments and deployments. At most 50 per kind.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    include_labels: bool = Field(False, strict=True, title="Include Resource Names", description="Opt in to organization, project and environment names. Configuration, logs, plans, variables, user data and links remain omitted.")
    @field_validator("api_key_id", "api_key_secret")
    @classmethod
    def keys(cls, value, info):
        value = clean_secret(value, field_name="API key")
        if not value or len(value) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Enter the issued key value without a header prefix or whitespace")
        if info.field_name == "api_key_id" and ":" in value: raise ValueError("Enter the issued API key ID")
        if value.lower().startswith(("basic ", "bearer ", "token ")): raise ValueError("Enter the issued key value")
        return value
    @field_validator("approved_resources_json")
    @classmethod
    def resources(cls, value): grants(value); return value


def credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != FAMILY: raise ValueError("Connect a native env zero API key pair")
    if any(key in data for key in ("api_key", "token", "access_token", "refresh_token", "password", "username", "base_url", "host", "cookie", "client_id", "authorization")):
        raise ValueError("Use only the native supplied env zero key-pair form")
    try: return Env0APIKeyCredential.model_validate(data).model_dump()
    except ValueError: raise ValueError("Complete the native env zero key pair and approved-resource form") from None


def dynamic(field, depends_on=()):
    return {"x-resource-type": "env0_" + field.removesuffix("_id"),
            "x-dynamic-options": {"field_name": field, "depends_on": list(depends_on), "searchable": True, "allow_custom": True}}


class NativeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CheckConnection(NativeModel):
    operation: Literal["check_connection"] = "check_connection"


class LocalLimit(NativeModel):
    limit: int = Field(50, strict=True, ge=1, le=100, description="Local output bound on an unpaged catalog; completion remains unknown.")


class Page(NativeModel):
    limit: int = Field(50, strict=True, ge=1, le=100, description="Documented API limit, encoded as a string. No total or completion inferred.")
    offset: int = Field(0, strict=True, ge=0, le=1_000_000, description="Explicit bounded API offset, encoded as a string. No automatic next page.")


class OrganizationSelection(NativeModel):
    organization_id: str = Field(..., title="Organization", json_schema_extra=dynamic("organization_id"))
    @field_validator("organization_id")
    @classmethod
    def org(cls, value): return resource_id(value)


class ProjectSelection(OrganizationSelection):
    project_id: str = Field(..., title="Project", json_schema_extra=dynamic("project_id", ("organization_id",)))
    @field_validator("project_id")
    @classmethod
    def project(cls, value): return resource_id(value)


class EnvironmentSelection(ProjectSelection):
    environment_id: str = Field(..., title="Environment", json_schema_extra=dynamic("environment_id", ("organization_id", "project_id")))
    @field_validator("environment_id")
    @classmethod
    def environment(cls, value): return resource_id(value)


class DeploymentSelection(EnvironmentSelection):
    deployment_id: str = Field(..., title="Deployment", json_schema_extra=dynamic("deployment_id", ("organization_id", "project_id", "environment_id")))
    @field_validator("deployment_id")
    @classmethod
    def deployment(cls, value): return resource_id(value)


class ListOrganizations(LocalLimit):
    operation: Literal["list_organizations"] = "list_organizations"


class GetOrganization(OrganizationSelection):
    operation: Literal["get_organization"] = "get_organization"


class ListProjects(OrganizationSelection, LocalLimit):
    operation: Literal["list_projects"] = "list_projects"
    is_archived: Optional[bool] = Field(None, strict=True, description="Optional documented isArchived string filter; omitted leaves provider default.")


class GetProject(ProjectSelection):
    operation: Literal["get_project"] = "get_project"


class ListEnvironments(ProjectSelection, Page):
    operation: Literal["list_environments"] = "list_environments"


class GetEnvironment(EnvironmentSelection):
    operation: Literal["get_environment"] = "get_environment"


class ListDeployments(EnvironmentSelection, Page):
    operation: Literal["list_deployments"] = "list_deployments"


class GetDeployment(DeploymentSelection):
    operation: Literal["get_deployment"] = "get_deployment"


Operation = Annotated[Union[CheckConnection, ListOrganizations, GetOrganization, ListProjects, GetProject,
    ListEnvironments, GetEnvironment, ListDeployments, GetDeployment], Field(discriminator="operation")]


class Env0NodeConfig(NodeConfig[Operation, Env0APIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class Projection(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)
    id: str = Field(max_length=128)
    @field_validator("id", "organizationId", "projectId", "environmentId", "parentProjectId", check_fields=False)
    @classmethod
    def ids(cls, value): return resource_id(value) if value is not None else value
    @field_validator("createdAt", "updatedAt", "queuedAt", "startedAt", "finishedAt", check_fields=False)
    @classmethod
    def times(cls, value):
        if value is not None:
            try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError: raise ValueError("Unverified timestamp") from None
            if parsed.tzinfo is None: raise ValueError("Unverified timestamp timezone")
        return value


class Organization(Projection):
    createdAt: Optional[str] = Field(None, max_length=64)
    updatedAt: Optional[str] = Field(None, max_length=64)
    name: Optional[str] = Field(None, max_length=500, exclude=True)


class Project(Projection):
    organizationId: str = Field(max_length=128)
    parentProjectId: Optional[str] = Field(None, max_length=128)
    isArchived: Optional[bool] = None
    name: Optional[str] = Field(None, max_length=500, exclude=True)


class Environment(Projection):
    organizationId: str = Field(max_length=128)
    projectId: str = Field(max_length=128)
    status: Literal["CREATED", "INACTIVE", "ACTIVE", "FAILED", "TIMEOUT", "WAITING_FOR_USER", "DEPLOY_IN_PROGRESS",
        "DESTROY_IN_PROGRESS", "TASK_IN_PROGRESS", "ABORTING", "ABORTED", "NEVER_DEPLOYED", "DRIFTED", "DRY_RUN_IN_PROGRESS"]
    createdAt: Optional[str] = Field(None, max_length=64)
    updatedAt: Optional[str] = Field(None, max_length=64)
    name: Optional[str] = Field(None, max_length=500, exclude=True)


class Deployment(Projection):
    environmentId: str = Field(max_length=128)
    status: Literal["IN_PROGRESS", "WAITING_FOR_USER", "TIMEOUT", "FAILURE", "SUCCESS", "CANCELLED", "INTERNAL_FAILURE",
        "ABORTING", "ABORTED", "QUEUED", "SKIPPED", "NEVER_DEPLOYED"]
    type: Literal["deploy", "destroy", "prPlan", "driftDetection", "task", "remotePlan", "dryRun", "moduleTest"]
    createdAt: Optional[str] = Field(None, max_length=64)
    updatedAt: Optional[str] = Field(None, max_length=64)
    queuedAt: Optional[str] = Field(None, max_length=64)
    startedAt: Optional[str] = Field(None, max_length=64)
    finishedAt: Optional[str] = Field(None, max_length=64)

async def current_credential(data):
    return credential(data)


async def request(data, path, *, params=None):
    now = await current_credential(data)
    try:
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", ROOT + path, headers={"Authorization": "Basic " + base64.b64encode((now["api_key_id"] + ":" + now["api_key_secret"]).encode("utf-8")).decode("ascii"),
                "Accept": "application/json", "Content-Type": "application/json"}, params=params) as response:
                await current_credential(data)
                status = response.status_code
                if status in {400, 401, 403, 404, 422}: raise ValueError(f"env zero Cloud refused the metadata read (HTTP {status})")
                if status != 200: raise RuntimeError(f"env zero Cloud metadata read did not complete (HTTP {status}); no automatic retry")
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json": raise RuntimeError("env zero Cloud returned an unexpected response type")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 2_000_000: raise RuntimeError("env zero Cloud response exceeds the native metadata limit")
                await current_credential(data)
    except httpx.HTTPError: raise RuntimeError("env zero Cloud metadata transport did not complete; no automatic retry") from None
    try: return strict_json(bytes(content))
    except ValueError: raise RuntimeError("env zero Cloud returned invalid JSON") from None


def typed(model, raw):
    try: return model.model_validate(raw)
    except ValueError: raise RuntimeError("env zero returned unverified metadata") from None


def array(model, raw, *, max_items=1000):
    if not isinstance(raw, list) or len(raw) > max_items: raise RuntimeError("env zero returned an unverified or oversized bare metadata array")
    rows = [typed(model, item) for item in raw]
    if len({row.id for row in rows}) != len(rows): raise RuntimeError("env zero repeated a metadata resource ID")
    return rows


def output(row, now):
    result = row.model_dump(exclude_none=True)
    name = getattr(row, "name", None)
    if now["include_labels"] and name is not None: result["name"] = name
    return result


def selected(now, kind, value):
    value = resource_id(value)
    if value not in grants(now["approved_resources_json"])[kind]: raise ValueError("Resource is outside the saved env zero approved-ID restriction")
    return value


def env_fields(now):
    return ENV_FIELDS + (",name" if now["include_labels"] else "")


async def organization_witness(data, value):
    now = await current_credential(data)
    value = selected(now, "organizations", value)
    rows = array(Organization, await request(data, "/organizations"))
    if value not in {row.id for row in rows}: raise ValueError("Current organization catalog did not witness this ID; ownership and global absence are unverified")
    row = typed(Organization, await request(data, "/organizations/" + value))
    if row.id != value: raise RuntimeError("env zero organization detail did not confirm its catalog ID")
    await current_credential(data)
    return row


async def project_witness(data, org, value):
    now = await current_credential(data)
    value = selected(now, "projects", value)
    selected(now, "organizations", org)
    await organization_witness(data, org)
    rows = array(Project, await request(data, "/projects", params={"organizationId": org}))
    if any(row.organizationId != org for row in rows): raise RuntimeError("env zero project catalog did not confirm organization ancestry")
    if value not in {row.id for row in rows}: raise ValueError("Current project catalog did not witness this ID; ownership and global absence are unverified")
    row = typed(Project, await request(data, "/projects/" + value))
    if row.id != value or row.organizationId != org: raise RuntimeError("env zero project detail did not confirm its current parent")
    await current_credential(data)
    return row


async def environment_witness(data, org, project, value):
    now = await current_credential(data)
    value = selected(now, "environments", value)
    selected(now, "projects", project); selected(now, "organizations", org)
    await project_witness(data, org, project)
    row = typed(Environment, await request(data, "/environments/" + value, params={"fields": env_fields(now)}))
    if row.id != value or row.organizationId != org or row.projectId != project:
        raise RuntimeError("env zero environment detail did not confirm its current organization and project")
    await current_credential(data)
    return row


async def deployment_witness(data, org, project, environment, value):
    now = await current_credential(data)
    value = selected(now, "deployments", value)
    selected(now, "environments", environment); selected(now, "projects", project); selected(now, "organizations", org)
    await environment_witness(data, org, project, environment)
    witnessed = False
    for page in range(5):
        rows = array(Deployment, await request(data, "/environments/" + environment + "/deployments",
            params={"limit": "100", "offset": str(page * 100)}), max_items=100)
        if any(row.environmentId != environment for row in rows): raise RuntimeError("env zero deployment catalog did not confirm environment ancestry")
        if value in {row.id for row in rows}: witnessed = True; break
    if not witnessed: raise ValueError("Deployment catalog witness budget exhausted; ancestry and global absence remain unverified")
    row = typed(Deployment, await request(data, "/environments/deployments/" + value, params={"fields": DEPLOYMENT_FIELDS}))
    if row.id != value or row.environmentId != environment: raise RuntimeError("env zero deployment detail did not confirm its current catalog parent")
    await current_credential(data)
    return row


def list_result(rows, limit, *, received_count, filtered_count=0, offset=None):
    result = {"status": "success", "results": rows[:limit], "received_count": received_count,
        "returned_count": min(len(rows), limit), "filtered_count": filtered_count, "locally_truncated": len(rows) > limit,
        "completion": "unknown", "resource_access_verified": True, "identity_verified": False, "organization_ownership_verified": False}
    if offset is not None: result["requested_offset"] = offset; result["requested_limit"] = limit
    return result


async def list_metadata(data, cfg):
    now = await current_credential(data)
    if isinstance(cfg, ListOrganizations):
        kind, model = "organizations", Organization
        if not grants(now["approved_resources_json"])[kind]: raise ValueError("Approve existing env zero organization IDs before listing")
        rows = array(model, await request(data, "/organizations"))
    elif isinstance(cfg, ListProjects):
        kind, model = "projects", Project
        selected(now, "organizations", cfg.organization_id)
        if not grants(now["approved_resources_json"])[kind]: raise ValueError("Approve existing env zero project IDs before listing")
        await organization_witness(data, cfg.organization_id)
        params = {"organizationId": cfg.organization_id}
        if cfg.is_archived is not None: params["isArchived"] = "true" if cfg.is_archived else "false"
        rows = array(model, await request(data, "/projects", params=params))
        if any(row.organizationId != cfg.organization_id for row in rows): raise RuntimeError("env zero project list did not confirm organization ancestry")
    elif isinstance(cfg, ListEnvironments):
        kind, model = "environments", Environment
        selected(now, "projects", cfg.project_id); selected(now, "organizations", cfg.organization_id)
        if not grants(now["approved_resources_json"])[kind]: raise ValueError("Approve existing env zero environment IDs before listing")
        await project_witness(data, cfg.organization_id, cfg.project_id)
        rows = array(model, await request(data, "/environments", params={"organizationId": cfg.organization_id,
            "projectId": cfg.project_id, "limit": str(cfg.limit), "offset": str(cfg.offset)}), max_items=cfg.limit)
        if any(row.organizationId != cfg.organization_id or row.projectId != cfg.project_id for row in rows):
            raise RuntimeError("env zero environment list did not confirm current parent IDs")
    else:
        kind, model = "deployments", Deployment
        selected(now, "environments", cfg.environment_id); selected(now, "projects", cfg.project_id); selected(now, "organizations", cfg.organization_id)
        if not grants(now["approved_resources_json"])[kind]: raise ValueError("Approve existing env zero deployment IDs before listing")
        await environment_witness(data, cfg.organization_id, cfg.project_id, cfg.environment_id)
        rows = array(model, await request(data, "/environments/" + cfg.environment_id + "/deployments",
            params={"limit": str(cfg.limit), "offset": str(cfg.offset)}), max_items=cfg.limit)
        if any(row.environmentId != cfg.environment_id for row in rows): raise RuntimeError("env zero deployment list did not confirm its current parent")
    allowed = grants(now["approved_resources_json"])[kind]
    projected = [output(row, now) for row in rows if row.id in allowed]
    await current_credential(data)
    return list_result(projected, cfg.limit, received_count=len(rows), filtered_count=len(rows)-len(projected),
        offset=cfg.offset if isinstance(cfg, (ListEnvironments, ListDeployments)) else None)


class Env0Node(WorkflowNode):
    integration_type = "automation-env0"
    connection_evidence = ConnectionEvidence(identity_operation="check_connection", noun="env zero organization catalog access",
        label_keys=(), identity_keys=(), proves="reachability")
    scope_registry = ScopeRegistry(provider="env0", enforcement=Enforcement.STRICT,
        requirements={op: ScopeRequirement(scopes=(), credential_types=(FAMILY,), note="Supplied organization or personal API-key ID/secret Basic header at api.env0.com. Their current permissions differ; no caller identity, organization ownership or invented OAuth scope.") for op in OPS})
    edit_examples = ["Read metadata for an approved env zero environment", "List deployment status for an approved environment", "Read an approved project"]
    @classmethod
    def get_config_model(cls): return Env0NodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None: credential(config_data["credentials"])
        return super().parse_config(config_data)
    @classmethod
    def validate_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: credential(config_data["credentials"])
            except ValueError: return {"valid": False, "errors": ["Complete the native env zero credential form"], "satisfied_set": None}
        return super().validate_config(config_data)
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        await current_credential(credential_data)
        if page_token is not None: raise ValueError("Choose an explicit native offset; no picker continuation is inferred")
        context = context or {}
        models = {"organization_id": ListOrganizations, "project_id": ListProjects,
                  "environment_id": ListEnvironments, "deployment_id": ListDeployments}
        if field_name not in models: return {"options": [], "next_page_token": None, "completion": "unknown"}
        required = {"organization_id": (), "project_id": ("organization_id",),
                    "environment_id": ("organization_id", "project_id"),
                    "deployment_id": ("organization_id", "project_id", "environment_id")}[field_name]
        if any(not context.get(key) for key in required): raise ValueError("Select the current env zero parent IDs first")
        args = {key: context[key] for key in required}
        args["limit"] = 100
        if field_name in {"environment_id", "deployment_id"}:
            args["offset"] = context.get("offset", 0)
        cfg = models[field_name](**args)
        result = await list_metadata(credential_data, cfg)
        if result["locally_truncated"]: raise ValueError("env zero options exceed the native local bound; completion is unverified")
        options = [{"value": row["id"], "label": row.get("name") or row["id"],
            "metadata": {"completion": "unknown", "identity_verified": False}} for row in result["results"]]
        term = (normalize_search(search) or "").casefold()
        if term: options = [row for row in options if term in (row["label"] + " " + row["value"]).casefold()]
        await current_credential(credential_data)
        return {"options": options, "next_page_token": None, "completion": "unknown"}
    async def execute(self, inputs: dict) -> dict:
        data = credential(self.config.credentials.model_dump() if self.config.credentials else None)
        cfg = self.config.config
        now = await current_credential(data)
        if isinstance(cfg, CheckConnection):
            rows = array(Organization, await request(data, "/organizations"))
            await current_credential(data)
            return {"status": "success", "witness_verified": True, "received_count": len(rows), "completion": "unknown",
                "resource_access_verified": True, "identity_verified": False, "organization_ownership_verified": False}
        if isinstance(cfg, (ListOrganizations, ListProjects, ListEnvironments, ListDeployments)): return await list_metadata(data, cfg)
        if isinstance(cfg, GetOrganization): row = await organization_witness(data, cfg.organization_id)
        elif isinstance(cfg, GetProject): row = await project_witness(data, cfg.organization_id, cfg.project_id)
        elif isinstance(cfg, GetEnvironment): row = await environment_witness(data, cfg.organization_id, cfg.project_id, cfg.environment_id)
        else: row = await deployment_witness(data, cfg.organization_id, cfg.project_id, cfg.environment_id, cfg.deployment_id)
        await current_credential(data)
        return {"status": "success", "data": output(row, now), "parent_link_verified": True,
            "resource_access_verified": True, "identity_verified": False, "organization_ownership_verified": False}
