"""Coolify v1 team-bound metadata workflows; no deployment actions or secrets.

Publisher contract pinned to coollabsio/coolify 41ed5b7. Project/environment
DELETE is intentionally absent: isEmpty() does not count shared variables and
model deletion cascades to those variables. Metadata writes are not replayed.
"""
from __future__ import annotations

import ipaddress
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictInt, StrictStr, model_serializer, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.credentials import resolve_credential_with_owner_fallback
from utils.ssrf import guarded_async_client, normalize_https_origin

TYPE = "coolify_token"
AUTH_KEY = "_coolify_authority"
CURRENT_ORGANIZATION = object()
UNAVAILABLE = "Coolify credential is unavailable or its authority changed"
UNVERIFIED = "Coolify response could not be verified"
ID = Annotated[StrictInt, Field(ge=1, le=9007199254740991)]
UUID = Annotated[StrictStr, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]


def api_origin(value):
    if not isinstance(value, str): raise ValueError("Supply a canonical public HTTPS Coolify origin")
    try:
        normalized = normalize_https_origin(value, field_name="Coolify origin")
        parsed = urlsplit(normalized)
        host = parsed.hostname or ""
        port = parsed.port
        if normalized != value or port is not None and not 1 <= port <= 65535: raise ValueError()
        try: ipaddress.ip_address(host)
        except ValueError: pass
        else: raise ValueError()
        labels = host.split(".")
        if len(labels) < 2 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels): raise ValueError()
        if host.endswith((".localhost", ".local", ".internal", ".test", ".invalid", ".example", ".home", ".lan")) or not re.fullmatch(r"[a-z]{2,63}", labels[-1]): raise ValueError()
    except Exception: raise ValueError("Supply the exact lowercase public HTTPS origin without /api, slash, userinfo, query or fragment") from None
    return normalized


def token(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,19}\|[A-Za-z0-9_-]{16,512}", value):
        raise ValueError("Paste the complete issued Coolify ID|secret API token")
    return value


def form_id(value):
    return int(value) if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,15}", value) else value


def metadata_text(value, *, description=False):
    if not isinstance(value, str): raise ValueError("Supply ordinary Coolify metadata text")
    allowed = " -_.,!?()'\"+=*@/&" if description else " -_.@/&()#,:+"
    minimum = 0 if description else 3
    if not minimum <= len(value) <= 255 or not description and value.strip() != value or any(unicodedata.category(c)[0] not in "LMN" and c not in allowed for c in value):
        raise ValueError("Coolify metadata must use ordinary text, up to 255 characters; names require at least 3")
    return value


Name = Annotated[StrictStr, BeforeValidator(metadata_text), Field(min_length=3, max_length=255)]
Description = Annotated[StrictStr, BeforeValidator(lambda value: metadata_text(value, description=True)), Field(max_length=255)]


class CoolifyTokenCredential(BaseModel):
    model_config = ConfigDict(title="Coolify Token", extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://coolify.io/docs/api/authorization",
        "x-credential-instructions": "Create a team-scoped Coolify API token. Paste the entire ID|secret value. Use read for metadata and write for project/environment changes; write also requires the owner's/admin's current role. No deploy, read:sensitive or root ability is needed. Cloud defaults to https://app.coolify.io. Self-host API access must already be enabled and publicly reachable over HTTPS; this integration cannot adjust IP rules or trust private addresses. The selected team ID is verified against /teams/current, not public health. Team proof does not establish human identity or every permission.",
    })
    credential_type: Literal["coolify_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_url: Annotated[StrictStr, BeforeValidator(api_origin)] = Field("https://app.coolify.io", title="Coolify HTTPS Origin", description="Canonical lowercase public HTTPS origin only. An intentional non-default HTTPS port is allowed; no API path or trailing slash.")
    expected_team_id: Annotated[ID, BeforeValidator(form_id)] = Field(..., title="Bound Coolify Team ID", description="Positive ID of the team that issued this token.")
    api_token: Annotated[StrictStr, BeforeValidator(token)] = Field(..., title="Coolify API Token", repr=False, json_schema_extra={"ui:widget": "password"})

    @model_serializer(mode="wrap")
    def connect_tag(self, handler):
        return {**handler(self), "credential_type": TYPE}


def credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") != TYPE: raise ValueError("Coolify requires its original supplied-token credential type")
    try: return CoolifyTokenCredential.model_validate(raw)
    except Exception: raise ValueError("Coolify credential fields are invalid") from None


def raw_guard(data):
    if not isinstance(data, dict): return
    raw = data.get("credentials")
    if raw is not None and (not isinstance(raw, dict) or raw.get("credential_type") != TYPE): raise ValueError("Coolify credential type is not supported")


def op(name, title, description, **extra):
    return Field(name, title=title, description=description, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": title, "x-category": "Infrastructure Metadata", "x-is-trigger": False, **extra})


def picker(field, parent=None):
    return {"x-resource-type": "coolify_" + field.removesuffix("_uuid"), "x-dynamic-options": {"field_name": field, "allow_custom": True, "searchable": False, "custom_placeholder": "Exact Coolify UUID", **({"depends_on": parent} if parent else {})}}


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CheckConnection(Config):
    operation: Literal["check_connection"] = op("check_connection", "Check Team Access", "Verify the token's protected bound team; public health is not credential evidence.")


class GetCurrentTeam(Config):
    operation: Literal["get_current_team"] = op("get_current_team", "Get Current Team", "Read the token-bound team's ID and name, excluding members, billing and security settings.")


class Page(Config):
    limit: Annotated[StrictInt, Field(ge=1, le=100)] = Field(20, title="Result Limit", description="Local slice of a bounded unpaginated Coolify inventory; not a provider page-size parameter.")
    offset: Annotated[StrictInt, Field(ge=0, le=1000)] = Field(0, title="Result Offset", description="Local offset; inventory larger than 1,000 rows is refused rather than silently truncated.")


class ListProjects(Page):
    operation: Literal["list_projects"] = op("list_projects", "List Projects", "Read a bounded current-team project inventory and return one local slice.")


class Project(Config):
    project_uuid: UUID = Field(..., title="Project UUID", json_schema_extra=picker("project_uuid"))


class GetProject(Project):
    operation: Literal["get_project"] = op("get_project", "Get Project", "Verify current-team membership and project identity; return environment metadata without variables.")


class CreateProject(Config):
    operation: Literal["create_project"] = op("create_project", "Create Empty Project", "Create project name/description in the bound team, including Coolify's default production environment. No resources are deployed. Verify an independent GET; do not retry an ambiguous write.", **{"x-creates-resource": True, "x-resource-type": "coolify_project", "x-resource-id-path": "data.project.uuid"})
    name: Name = Field(..., title="Project Name")
    description: Optional[Description] = Field(None, title="Project Description")


class Changes(Config):
    name: Optional[Name] = Field(None, title="New Name")
    description: Optional[Description] = Field(None, title="New Description", description="Omit to preserve; explicit null clears the description.")

    @model_validator(mode="after")
    def changed_fields(self):
        if not self.model_fields_set.intersection({"name", "description"}) or "name" in self.model_fields_set and self.name is None: raise ValueError("Supply a name or description change; a name cannot be null")
        return self


class UpdateProject(Project, Changes):
    operation: Literal["update_project"] = op("update_project", "Update Project Metadata", "PATCH only supplied name/description. Provider returns 201 for an update; verify an independent GET. No resource changes.")


class ListEnvironments(Project, Page):
    operation: Literal["list_environments"] = op("list_environments", "List Project Environments", "Read environment UUIDs under the selected current-team project.")


class Environment(Project):
    environment_uuid: UUID = Field(..., title="Environment UUID", description="Exact environment UUID; names are not used as path identifiers.", json_schema_extra=picker("environment_uuid", "project_uuid"))


class GetEnvironment(Environment):
    operation: Literal["get_environment"] = op("get_environment", "Get Environment", "GET the documented project/UUID route. Validate numeric project parent and discard nested configuration and secrets.")


class CreateEnvironment(Project):
    operation: Literal["create_environment"] = op("create_environment", "Create Empty Environment", "Create an empty named environment under the selected project. Does not create variables or resources. Verify by UUID and project ID; a duplicate name returns 409.", **{"x-creates-resource": True, "x-resource-type": "coolify_environment", "x-resource-id-path": "data.environment.uuid"})
    name: Name = Field(..., title="Environment Name")


class UpdateEnvironment(Environment, Changes):
    operation: Literal["update_environment"] = op("update_environment", "Update Environment Metadata", "PATCH only supplied name/description. Retain stable UUID through rename; verify independent parent-bound GET. No environment-variable changes.")


class ListApplications(Environment, Page):
    operation: Literal["list_applications"] = op("list_applications", "List Environment Applications", "Read the current-team application inventory, validate each environment ID, and return only this environment's metadata.")


class Application(Environment):
    application_uuid: UUID = Field(..., title="Application UUID", description="Enter an exact application UUID from this environment. Parent binding is checked before deployment reads.")


class GetApplication(Application):
    operation: Literal["get_application"] = op("get_application", "Get Application Metadata", "Read identity/status and verify the exact environment; discard commands, Compose, credentials, network URLs and settings.")


class ListServices(Environment, Page):
    operation: Literal["list_services"] = op("list_services", "List Environment Services", "Read the team service inventory and return only this environment's identity metadata, excluding Compose and nested credentials.")


class GetService(Environment):
    operation: Literal["get_service"] = op("get_service", "Get Service Metadata", "Validate service environment and return ID/name/timestamps without nested applications, databases or secrets.")
    service_uuid: UUID = Field(..., title="Service UUID", description="Enter an exact service UUID from this environment.")


class ListDeployments(Application):
    operation: Literal["list_deployments"] = op("list_deployments", "List Application Deployments", "One provider skip/take history page for the exact application. Return status/IDs/timestamps without logs, snapshots or server URLs.")
    skip: Annotated[StrictInt, Field(ge=0, le=10000)] = Field(0, title="Deployments to Skip")
    take: Annotated[StrictInt, Field(ge=1, le=100)] = Field(20, title="Deployments to Take")


class GetDeployment(Application):
    operation: Literal["get_deployment"] = op("get_deployment", "Get Deployment Status", "Read a deployment and verify its numeric application parent; does not start, cancel or change it.")
    deployment_uuid: UUID = Field(..., title="Deployment UUID")


OPERATIONS = (CheckConnection, GetCurrentTeam, ListProjects, GetProject, CreateProject, UpdateProject, ListEnvironments, GetEnvironment, CreateEnvironment, UpdateEnvironment, ListApplications, GetApplication, ListServices, GetService, ListDeployments, GetDeployment)
CoolifyConfig = Annotated[Union[CheckConnection, GetCurrentTeam, ListProjects, GetProject, CreateProject, UpdateProject, ListEnvironments, GetEnvironment, CreateEnvironment, UpdateEnvironment, ListApplications, GetApplication, ListServices, GetService, ListDeployments, GetDeployment], Field(discriminator="operation")]


class CoolifyNodeConfig(NodeConfig[CoolifyConfig, CoolifyTokenCredential]):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    node_type: Literal["automation-coolify"] = "automation-coolify"


@dataclass(eq=False)
class Authority:
    credential: CoolifyTokenCredential
    pool: Any = None
    user_id: Any = None
    credential_id: Any = None
    organization_id: Any = None
    workflow_id: Any = None
    anchor: Any = None

    @classmethod
    async def create(cls, raw, *, pool=None, user_id=None, credential_id=None, organization_id=CURRENT_ORGANIZATION, workflow_id=None):
        shaped = credential(raw)
        if credential_id and not user_id: raise ValueError(UNAVAILABLE)
        current = cls(shaped, pool, user_id, credential_id, organization_id, workflow_id)
        if credential_id:
            if pool is None:
                from utils.database_pool import get_native_pool
                current.pool = get_native_pool()
            if organization_id is CURRENT_ORGANIZATION:
                from wss.handlers.workflow_handler import get_user_org_context
                async with current.pool.acquire() as conn:
                    current.organization_id = await get_user_org_context(conn, user_id)
            current.credential, current.anchor = await current.load()
        return current

    async def load(self):
        # Staging's shared resolver owns row access, revocation and workflow
        # owner/lender fallback. Re-read it before requests and output; compare
        # the typed credential without depending on PR-only authority snapshots.
        result = await resolve_credential_with_owner_fallback(
            self.credential_id, self.user_id, self.pool,
            org_id=self.organization_id, workflow_id=self.workflow_id,
        )
        if not result: raise ValueError(UNAVAILABLE)
        shaped = credential(result)
        return shaped, shaped.model_dump()

    async def require_current(self):
        if self.credential_id:
            latest, anchor = await self.load()
            if latest != self.credential or anchor != self.anchor: raise ValueError(UNAVAILABLE)


class ApiError(ValueError):
    def __init__(self, status, retry_after=None):
        self.status_code = status
        self.retry_after = retry_after
        super().__init__(f"Coolify API returned HTTP {status}" + (f"; retry after {retry_after} seconds" if retry_after is not None else ""))


class OutcomeUnverified(RuntimeError): pass


def positive(value):
    if type(value) is not int or not 1 <= value <= 9007199254740991: raise OutcomeUnverified(UNVERIFIED)
    return value


def uuid(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value): raise OutcomeUnverified(UNVERIFIED)
    return value


def text(raw, key, *, nullable=False, maximum=255):
    value = raw.get(key)
    if nullable and value is None: return None
    if not isinstance(value, str) or len(value) > maximum: raise OutcomeUnverified(UNVERIFIED)
    return value


def entity(raw, expected=None):
    if not isinstance(raw, dict): raise OutcomeUnverified(UNVERIFIED)
    positive(raw.get("id")); uuid(raw.get("uuid"))
    if expected is not None and raw["uuid"] != expected: raise OutcomeUnverified("Coolify returned a different resource")
    return raw


def rows(raw):
    if not isinstance(raw, list) or len(raw) > 1000: raise OutcomeUnverified("Coolify inventory exceeds its bounded response contract")
    values = [entity(row) for row in raw]
    if len({row["uuid"] for row in values}) != len(values) or len({row["id"] for row in values}) != len(values): raise OutcomeUnverified(UNVERIFIED)
    return values


def project_projection(raw):
    return {"id": raw["id"], "uuid": raw["uuid"], "name": text(raw, "name"), "description": text(raw, "description", nullable=True)}


def environment_projection(raw, project_id=None):
    result = {"id": raw["id"], "uuid": raw["uuid"], "name": text(raw, "name")}
    if project_id is not None:
        if positive(raw.get("project_id")) != project_id: raise OutcomeUnverified("Coolify environment belongs to a different project")
        result.update(project_id=project_id, description=text(raw, "description", nullable=True))
    return result


def resource_projection(raw, *, application=False):
    result = {"id": raw["id"], "uuid": raw["uuid"], "name": text(raw, "name"), "environment_id": positive(raw.get("environment_id")), **{key: text(raw, key, nullable=True, maximum=100) for key in ("created_at", "updated_at")}}
    if application: result["status"] = text(raw, "status", maximum=100)
    return result


def deployment_projection(raw, application_id, expected=None):
    if not isinstance(raw, dict): raise OutcomeUnverified(UNVERIFIED)
    identifier = uuid(raw.get("deployment_uuid"))
    if expected is not None and identifier != expected: raise OutcomeUnverified(UNVERIFIED)
    parent = raw.get("application_id")
    # Publisher OpenAPI describes this relationship as string; actual storage
    # also serializes integer IDs. This is response-only, never config coercion.
    if isinstance(parent, str) and re.fullmatch(r"[1-9][0-9]{0,15}", parent): parent = int(parent)
    if positive(parent) != application_id: raise OutcomeUnverified("Coolify deployment belongs to a different application")
    return {"id": positive(raw.get("id")), "deployment_uuid": identifier, "application_id": parent, "status": text(raw, "status", maximum=100), **{key: text(raw, key, nullable=True, maximum=100) for key in ("created_at", "updated_at")}}


def local_page(items, cfg):
    values = items[cfg.offset:cfg.offset + cfg.limit]
    next_offset = cfg.offset + len(values) if cfg.offset + len(values) < len(items) else None
    return {"items": values, "total": len(items), "next_offset": next_offset, "paging": "local_inventory_slice"}


async def request(auth, method, path, *, body=None, params=None, success=(200,)):
    await auth.require_current()
    try:
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, auth.credential.api_url + "/api/v1/" + path, json=body, params=params, headers={"Authorization": "Bearer " + auth.credential.api_token, "Accept": "application/json", "User-Agent": "NoClick-Coolify/1.0"}) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > 4194304: raise OutcomeUnverified(UNVERIFIED)
                    raw.extend(chunk)
                    await auth.require_current()
                await auth.require_current()
                if response.status_code not in success:
                    delay = response.headers.get("retry-after", "")
                    raise ApiError(response.status_code, int(delay) if re.fullmatch(r"[0-9]{1,6}", delay) else None)
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json": raise OutcomeUnverified(UNVERIFIED)
                try: data = json.loads(raw)
                except (ValueError, UnicodeError): raise OutcomeUnverified(UNVERIFIED) from None
                return response.status_code, data
    except httpx.RequestError: raise OutcomeUnverified("Coolify transport outcome is unverified; a write may already have been accepted") from None


async def current_team(auth):
    _, raw = await request(auth, "GET", "teams/current")
    if not isinstance(raw, dict) or positive(raw.get("id")) != auth.credential.expected_team_id: raise OutcomeUnverified("Coolify token is bound to a different team")
    return {"id": raw["id"], "name": text(raw, "name"), "description": text(raw, "description", nullable=True), "binding": "token_team", "permissions": "not_inferred"}


async def project(auth, identifier):
    _, inventory = await request(auth, "GET", "projects")
    selected = next((row for row in rows(inventory) if row["uuid"] == identifier), None)
    if selected is None: raise ValueError("Coolify project is not in the bound team inventory")
    _, raw = await request(auth, "GET", "projects/" + identifier)
    raw = entity(raw, identifier)
    if raw["id"] != selected["id"]: raise OutcomeUnverified(UNVERIFIED)
    return project_projection(raw)


async def environment(auth, cfg, parent):
    _, inventory = await request(auth, "GET", f"projects/{cfg.project_uuid}/environments")
    selected = next((row for row in rows(inventory) if row["uuid"] == cfg.environment_uuid), None)
    if selected is None: raise ValueError("Coolify environment is not in the selected project")
    _, raw = await request(auth, "GET", f"projects/{cfg.project_uuid}/{cfg.environment_uuid}")
    raw = entity(raw, cfg.environment_uuid)
    if raw["id"] != selected["id"]: raise OutcomeUnverified(UNVERIFIED)
    return environment_projection(raw, parent["id"])


async def resource(auth, cfg, env, *, service=False):
    identifier = cfg.service_uuid if service else cfg.application_uuid
    _, raw = await request(auth, "GET", ("services/" if service else "applications/") + identifier)
    projected = resource_projection(entity(raw, identifier), application=not service)
    if projected["environment_id"] != env["id"]: raise OutcomeUnverified("Coolify resource belongs to a different environment")
    return projected


def changed_body(cfg):
    return {key: getattr(cfg, key) for key in ("name", "description") if key in cfg.model_fields_set}


def ack_uuid(raw):
    if not isinstance(raw, dict): raise OutcomeUnverified(UNVERIFIED)
    return uuid(raw.get("uuid"))


def matches(raw, body):
    if any(raw.get(key) != value for key, value in body.items()): raise OutcomeUnverified("Coolify write was acknowledged but metadata readback differs")


async def operate(auth, cfg):
    team = await current_team(auth)
    if isinstance(cfg, (CheckConnection, GetCurrentTeam)): return team
    if isinstance(cfg, ListProjects):
        _, raw = await request(auth, "GET", "projects")
        return local_page([project_projection(row) for row in rows(raw)], cfg)
    if isinstance(cfg, CreateProject):
        body = {"name": cfg.name, "description": cfg.description}
        status, ack = await request(auth, "POST", "projects", body=body, success=(201,))
        created = await project(auth, ack_uuid(ack))
        matches(created, body)
        return {"project": created, "status_code": status, "write_acknowledged": True, "readback_verified": True}
    parent = await project(auth, cfg.project_uuid)
    if isinstance(cfg, GetProject):
        _, raw = await request(auth, "GET", f"projects/{cfg.project_uuid}/environments")
        return {**parent, "environments": [environment_projection(row) for row in rows(raw)]}
    if isinstance(cfg, UpdateProject):
        body = changed_body(cfg)
        status, ack = await request(auth, "PATCH", "projects/" + cfg.project_uuid, body=body, success=(201,))
        if ack_uuid(ack) != cfg.project_uuid: raise OutcomeUnverified(UNVERIFIED)
        updated = await project(auth, cfg.project_uuid); matches(updated, body)
        return {"project": updated, "status_code": status, "write_acknowledged": True, "readback_verified": True}
    if isinstance(cfg, ListEnvironments):
        _, raw = await request(auth, "GET", f"projects/{cfg.project_uuid}/environments")
        return local_page([environment_projection(row) for row in rows(raw)], cfg)
    if isinstance(cfg, CreateEnvironment):
        status, ack = await request(auth, "POST", f"projects/{cfg.project_uuid}/environments", body={"name": cfg.name}, success=(201,))
        created = await environment(auth, GetEnvironment(project_uuid=cfg.project_uuid, environment_uuid=ack_uuid(ack)), parent)
        matches(created, {"name": cfg.name})
        return {"environment": created, "status_code": status, "write_acknowledged": True, "readback_verified": True}
    env = await environment(auth, cfg, parent)
    if isinstance(cfg, GetEnvironment): return env
    if isinstance(cfg, UpdateEnvironment):
        body = changed_body(cfg)
        status, ack = await request(auth, "PATCH", f"projects/{cfg.project_uuid}/environments/{cfg.environment_uuid}", body=body)
        if ack_uuid(ack) != cfg.environment_uuid: raise OutcomeUnverified(UNVERIFIED)
        updated = await environment(auth, cfg, parent); matches(updated, body)
        return {"environment": updated, "status_code": status, "write_acknowledged": True, "readback_verified": True}
    if isinstance(cfg, (ListApplications, ListServices)):
        app = isinstance(cfg, ListApplications)
        _, raw = await request(auth, "GET", "applications" if app else "services")
        projected = [resource_projection(row, application=app) for row in rows(raw)]
        return local_page([row for row in projected if row["environment_id"] == env["id"]], cfg)
    if isinstance(cfg, GetService): return await resource(auth, cfg, env, service=True)
    app = await resource(auth, cfg, env)
    if isinstance(cfg, GetApplication): return app
    if isinstance(cfg, ListDeployments):
        _, raw = await request(auth, "GET", "deployments/applications/" + cfg.application_uuid, params={"skip": cfg.skip, "take": cfg.take})
        if not isinstance(raw, dict) or type(raw.get("count")) is not int or raw["count"] < 0 or not isinstance(raw.get("deployments"), list) or len(raw["deployments"]) > cfg.take: raise OutcomeUnverified(UNVERIFIED)
        items = [deployment_projection(row, app["id"]) for row in raw["deployments"]]
        if len({row["deployment_uuid"] for row in items}) != len(items) or len({row["id"] for row in items}) != len(items): raise OutcomeUnverified(UNVERIFIED)
        return {"items": items, "total": raw["count"], "skip": cfg.skip, "take": cfg.take, "next_skip": cfg.skip + len(items) if items and cfg.skip + len(items) < raw["count"] else None, "paging": "provider_skip_take"}
    if isinstance(cfg, GetDeployment):
        _, raw = await request(auth, "GET", "deployments/" + cfg.deployment_uuid)
        return deployment_projection(raw, app["id"], cfg.deployment_uuid)
    raise ValueError("Unsupported Coolify operation")


class CoolifyNode(WorkflowNode):
    integration_type = "automation-coolify"
    connection_evidence = ConnectionEvidence(identity_operation="check_connection", identity_keys=("name",), noun="Coolify team")

    @classmethod
    def get_config_model(cls): return CoolifyNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw_guard(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        raw_guard(config_data)
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        auth = await Authority.create(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)
        return {**auth.credential.model_dump(), AUTH_KEY: auth}

    @classmethod
    async def validate_credential_access(cls, raw):
        try:
            auth = await Authority.create(raw)
            await current_team(auth); await auth.require_current()
            return {"valid": True}
        except ApiError as error:
            return {"valid": False if error.status_code == 401 else None, "error": str(error)}
        except Exception:
            return {"valid": None, "error": "Coolify team access is unverified"}

    async def execute(self, inputs):
        raw_guard(self.node_data)
        if self.config.credentials is None: raise ValueError("Coolify credentials are required")
        auth = await Authority.create(self.config.credentials.model_dump(), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data.get("credential_id"), organization_id=self.organization_id, workflow_id=self.workflow_id)
        data = await operate(auth, self.config.config)
        await auth.require_current()
        return {"status": "success", "operation": self.config.config.operation, "data": data}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in ("project_uuid", "environment_uuid") or search or context is not None and not isinstance(context, dict): raise ValueError("Use a Coolify project/environment picker or enter an exact custom UUID")
        try:
            offset = 0 if page_token is None else int(page_token) if isinstance(page_token, str) and re.fullmatch(r"[1-9][0-9]{0,3}", page_token) else -1
            cfg = ListProjects(limit=100, offset=offset) if field_name == "project_uuid" else ListEnvironments(project_uuid=(context or {}).get("project_uuid"), limit=100, offset=offset)
        except Exception: raise ValueError("Supply the typed parent project and valid local page offset") from None
        auth = credential_data.get(AUTH_KEY) if isinstance(credential_data, dict) else None
        if auth is not None and (not isinstance(auth, Authority) or auth.credential != credential(credential_data)): raise ValueError(UNAVAILABLE)
        if auth is None: auth = await Authority.create(credential_data)
        data = await operate(auth, cfg); await auth.require_current()
        return {"options": [{"value": row["uuid"], "label": row["name"]} for row in data["items"]], "next_page_token": str(data["next_offset"]) if data["next_offset"] is not None else None}
