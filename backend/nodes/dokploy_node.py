"""Native Dokploy v0.30.8 metadata and explicitly owned empty-object workflows."""
from contextvars import ContextVar
import ipaddress
import json
import logging
import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Discriminator, Field, TypeAdapter, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import normalize_search, filter_options_by_search
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from utils.ssrf import assert_exact_url_origin, guarded_async_client

FAMILY = "dokploy_api_key"
NODE_TYPE = "automation-dokploy"
CONTRACT = "v0.30.8"
MAX_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 1000
_PRIVATE = ContextVar("dokploy_private_transport", default=False)
SERVICE_KEYS = {"applications": ("applicationId", "applicationStatus"), "compose": ("composeId", "composeStatus"),
    "mariadb": ("mariadbId", "applicationStatus"), "mongo": ("mongoId", "applicationStatus"),
    "mysql": ("mysqlId", "applicationStatus"), "postgres": ("postgresId", "applicationStatus"),
    "redis": ("redisId", "applicationStatus"), "libsql": ("libsqlId", "applicationStatus")}


def record_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Use the exact Dokploy record ID")
    return value


def instance_origin(value):
    try:
        if not isinstance(value, str) or len(value) > 512 or value != value.strip():
            raise ValueError()
        parsed = urlsplit(value)
        host = parsed.hostname
        if (parsed.scheme != "https" or not host or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path not in ("", "/") or parsed.port not in (None, 443)
                or "%" in value or "\\" in value or any(ord(c) < 33 or ord(c) > 126 for c in value)):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
        if (host != host.lower() or host.endswith(".") or "." not in host or
                not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")) or
                host.endswith((".localhost", ".local", ".internal", ".test", ".invalid", ".example"))):
            raise ValueError()
        canonical = "https://" + host
        if value not in (canonical, canonical + "/"):
            raise ValueError()
        return canonical
    except Exception:
        raise ValueError("Use the canonical public HTTPS Dokploy instance origin without a path or port") from None


def supplied_key(value):
    if not isinstance(value, str):
        raise ValueError("Supply your existing Dokploy API key")
    value = clean_secret(value, field_name="Dokploy API key")
    if not value or len(value) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError("Supply a bounded Dokploy API key without spaces or controls")
    return value


class DokployAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Dokploy API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.dokploy.com/docs/api",
        "x-credential-instructions": "Use your existing API/CLI token from the owned instance profile; an administrator must permit API access. Public HTTPS only. Confirm the instance implements the pinned Dokploy v0.30.8 contract. Expected user and organization IDs are verified against protected user.get before operations. No OAuth, key generation, refresh or permission change occurs here.",
    })
    credential_type: Literal["dokploy_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    instance_url: str = Field(..., title="Public HTTPS Instance", description="Canonical origin only, for example https://deploy.your-domain.com; no /api path, private network or transport override.")
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password", "ui:sensitive": True})
    user_id: str = Field(..., title="Expected Dokploy User ID")
    organization_id: str = Field(..., title="Expected Dokploy Organization ID", description="The active organization attached to the API key, distinct from your NoClick organization.")
    api_contract: Literal["v0.30.8"] = Field(CONTRACT, title="Confirmed Instance API Contract", description="Operator confirmation of the installed contract; this is not a provider version probe.")
    _origin = field_validator("instance_url", mode="before")(instance_origin)
    _key = field_validator("api_key", mode="before")(supplied_key)
    _ids = field_validator("user_id", "organization_id", mode="before")(record_id)


def credential(data):
    try:
        if not isinstance(data, dict) or data.get("credential_type") != FAMILY:
            raise ValueError()
        if any(data.get(k) not in (None, "") for k in ("access_token", "refresh_token", "client_secret", "password", "session_token", "base_url", "server_url", "host")):
            raise ValueError()
        return DokployAPIKeyCredential.model_validate(data).model_dump()
    except Exception:
        raise ValueError("Connect a native Dokploy public-instance API-key credential") from None


class _BoundCredential(dict):
    """Keep the staging resolver context for rechecks during multi-request operations."""
    def __init__(self, data, authority):
        super().__init__(data)
        self.authority = authority


async def current_credential(data):
    shaped = credential(data)
    if isinstance(data, _BoundCredential):
        from utils.credentials import resolve_credential_with_owner_fallback
        current = await resolve_credential_with_owner_fallback(**data.authority)
        if not current or credential(current) != shaped:
            raise ValueError("Dokploy saved credential is unavailable or changed; reload")
    return shaped


def resource(name, parents=()):
    return {"x-resource-type": "dokploy_" + name, "x-dynamic-options": {
        "field_name": name + "_id", "searchable": True, "allow_custom": True,
        **({"depends_on": list(parents)} if parents else {})}}


class _Operation(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, extra="ignore")
    _ids = field_validator("project_id", "environment_id", "application_id", "compose_id", mode="before", check_fields=False)(record_id)


class CurrentUser(_Operation):
    operation: Literal["get_current_user"] = Field("get_current_user", title="Get Bound Current User and Team")


class ListProjects(_Operation):
    operation: Literal["list_projects"] = Field("list_projects", title="List Accessible Project Metadata")


class _Project(_Operation):
    project_id: str = Field(..., title="Project", json_schema_extra=resource("project"))


class GetProject(_Project):
    operation: Literal["get_project"] = Field("get_project", title="Get Project Metadata")


class ListEnvironments(_Project):
    operation: Literal["list_environments"] = Field("list_environments", title="List Project Environments")


class _Environment(_Project):
    environment_id: str = Field(..., title="Environment", json_schema_extra=resource("environment", ("project_id",)))


class GetEnvironment(_Environment):
    operation: Literal["get_environment"] = Field("get_environment", title="Get Environment Metadata")


class ListServices(_Environment):
    operation: Literal["list_services"] = Field("list_services", title="List Environment Service Status", description="Metadata for application, compose and database service records; no configuration or environment values.")


class _Application(_Environment):
    application_id: str = Field(..., title="Application", json_schema_extra=resource("application", ("project_id", "environment_id")))


class GetApplication(_Application):
    operation: Literal["get_application"] = Field("get_application", title="Get Application Status", description="Reads the selected environment's safe service metadata; does not fetch application configuration.")


class ListApplicationDeployments(_Application):
    operation: Literal["list_application_deployments"] = Field("list_application_deployments", title="List Existing Application Deployments")


class _Compose(_Environment):
    compose_id: str = Field(..., title="Compose", json_schema_extra=resource("compose", ("project_id", "environment_id")))


class GetCompose(_Compose):
    operation: Literal["get_compose"] = Field("get_compose", title="Get Compose Status")


class ListComposeDeployments(_Compose):
    operation: Literal["list_compose_deployments"] = Field("list_compose_deployments", title="List Existing Compose Deployments")


def disposable_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"noclick-[a-z0-9][a-z0-9-]{1,75}", value):
        raise ValueError("Use a unique disposable name beginning noclick-")
    return value


class _OwnedWrite(_Operation):
    owned_disposable_confirmed: Literal[True] = Field(..., title="Owned Disposable Instance and Object Confirmed", description="Only your isolated instance/object, no external automation and no concurrent service creation. This confirmation does not establish those facts.")
    description: Optional[str] = Field(None, max_length=1000, title="Description", description="Plain metadata; never put credentials or environment values here.")
    @field_validator("owned_disposable_confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if type(value) is not bool or value is not True:
            raise ValueError("Explicitly confirm the owned disposable instance and object")
        return value


class CreateProject(_OwnedWrite):
    operation: Literal["create_project"] = Field("create_project", title="Create Empty Disposable Project", description="Also creates Dokploy's default production environment and provider permission/audit records. No service is created.")
    name: str = Field(..., title="Disposable Project Name")
    _name = field_validator("name", mode="before")(disposable_name)


class _ExistingWrite(_OwnedWrite, _Project):
    expected_project_name: str = Field(..., title="Current Disposable Project Name", description="Exact name check before mutation; all known service collections must be empty.")
    _name = field_validator("expected_project_name", mode="before")(disposable_name)


class UpdateProject(_ExistingWrite):
    operation: Literal["update_project"] = Field("update_project", title="Update Empty Project Metadata")
    name: str = Field(..., title="New Disposable Project Name")
    _new_name = field_validator("name", mode="before")(disposable_name)


class DeleteProject(_ExistingWrite):
    operation: Literal["delete_project"] = Field("delete_project", title="Remove Empty Disposable Project", description="Deletes project and its empty environments/tags via provider database cascades. No atomic child-version guard exists; isolated concurrency is required.")


class CreateEnvironment(_ExistingWrite):
    operation: Literal["create_environment"] = Field("create_environment", title="Create Empty Disposable Environment")
    name: str = Field(..., title="Disposable Environment Name")
    _new_name = field_validator("name", mode="before")(disposable_name)


class _ExistingEnvironmentWrite(_ExistingWrite, _Environment):
    expected_environment_name: str = Field(..., title="Current Disposable Environment Name")
    _env_name = field_validator("expected_environment_name", mode="before")(disposable_name)


class UpdateEnvironment(_ExistingEnvironmentWrite):
    operation: Literal["update_environment"] = Field("update_environment", title="Update Empty Environment Metadata")
    name: str = Field(..., title="New Disposable Environment Name")
    _new_name = field_validator("name", mode="before")(disposable_name)


class DeleteEnvironment(_ExistingEnvironmentWrite):
    operation: Literal["delete_environment"] = Field("delete_environment", title="Remove Empty Nondefault Environment", description="The provider refuses default or populated environments. Native owner, exact-name and emptiness checks precede removal.")


DokployOperation = Annotated[Union[CurrentUser, ListProjects, GetProject, ListEnvironments, GetEnvironment, ListServices, GetApplication, GetCompose, ListApplicationDeployments, ListComposeDeployments, CreateProject, UpdateProject, DeleteProject, CreateEnvironment, UpdateEnvironment, DeleteEnvironment], Discriminator("operation")]
OPS = ("get_current_user", "list_projects", "get_project", "list_environments", "get_environment", "list_services", "get_application", "get_compose", "list_application_deployments", "list_compose_deployments", "create_project", "update_project", "delete_project", "create_environment", "update_environment", "delete_environment")


class DokployNodeConfig(NodeConfig[DokployOperation, DokployAPIKeyCredential]):
    pass


class _Privacy(logging.Filter):
    def filter(self, record):
        return not _PRIVATE.get()


def _privacy():
    for name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"):
        log = logging.getLogger(name)
        if not any(isinstance(f, _Privacy) for f in log.filters):
            log.addFilter(_Privacy())


class _RequestRefused(ValueError):
    pass


class _NotFound(_RequestRefused):
    pass


def _json(payload):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError()
            out[key] = value
        return out
    return json.loads(payload, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


GET_PARAMETERS = {"user.get": set(), "project.all": set(), "project.one": {"projectId"},
    "environment.one": {"environmentId"}, "environment.byProjectId": {"projectId"},
    "deployment.all": {"applicationId"}, "deployment.allByCompose": {"composeId"}}
POST_PARAMETERS = {"project.create": {"name", "description"}, "project.update": {"projectId", "name", "description"},
    "project.remove": {"projectId"}, "environment.create": {"name", "description", "projectId"},
    "environment.update": {"environmentId", "name", "description"}, "environment.remove": {"environmentId"}}


async def request(data, procedure, *, body=None, params=None):
    current = await current_credential(data)
    mapping = POST_PARAMETERS if body is not None else GET_PARAMETERS
    values = body if body is not None else params or {}
    if procedure not in mapping or not isinstance(values, dict) or set(values) - mapping[procedure]:
        raise ValueError("Unsupported native Dokploy procedure or fields")
    required = mapping[procedure] - {"description"} if procedure not in ("project.update", "environment.update") else mapping[procedure] - {"description"}
    if not required.issubset(values):
        raise ValueError("Missing native Dokploy procedure fields")
    url = current["instance_url"] + "/api/" + procedure
    assert_exact_url_origin(url, current["instance_url"])
    _privacy()
    marker = _PRIVATE.set(True)
    try:
        async with guarded_async_client(timeout=25.0, follow_redirects=False, trust_env=False) as client:
            async with client.stream("POST" if body is not None else "GET", url, params=params,
                    json=body, headers={"Accept": "application/json", "x-api-key": current["api_key"]}) as response:
                await current_credential(data)
                if response.status_code == 404:
                    raise _NotFound("Dokploy did not find the selected metadata record")
                if response.status_code in {400, 401, 403, 405, 422}:
                    raise _RequestRefused("Dokploy refused current access, permission or selected operation")
                if response.status_code != 200:
                    raise RuntimeError("Dokploy did not confirm the documented status; mutation outcome may be unknown")
                payload = bytearray()
                async for chunk in response.aiter_bytes():
                    payload.extend(chunk)
                    if len(payload) > MAX_BYTES:
                        raise RuntimeError("Dokploy response exceeded the metadata limit; mutation outcome may be unknown")
                await current_credential(data)
                if "json" not in response.headers.get("content-type", "").lower():
                    raise RuntimeError("Dokploy did not return JSON metadata; mutation outcome may be unknown")
                try:
                    raw = _json(bytes(payload))
                except (ValueError, TypeError):
                    raise RuntimeError("Dokploy returned malformed JSON; mutation outcome may be unknown") from None
                if not isinstance(raw, (dict, list)) or isinstance(raw, dict) and ("code" in raw or "error" in raw):
                    raise RuntimeError("Dokploy returned invalid or error metadata; mutation outcome may be unknown")
                return raw
    except _RequestRefused:
        raise
    except ValueError:
        raise ValueError("Dokploy operation refused by current authority or public-origin policy") from None
    except Exception as exc:
        if isinstance(exc, RuntimeError) and str(exc).startswith("Dokploy "):
            raise
        raise RuntimeError("Dokploy operation could not be completed; mutation outcome may be unknown") from None
    finally:
        _PRIVATE.reset(marker)


def metadata_text(value):
    if not isinstance(value, str) or len(value) > 2000 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise RuntimeError("Dokploy returned invalid metadata text")
    return value


def _record(raw, key, fields=()):
    if not isinstance(raw, dict):
        raise RuntimeError("Dokploy returned an invalid record envelope")
    out = {key: response_id(raw.get(key))}
    for field in fields:
        if raw.get(field) is not None:
            out[field] = metadata_text(raw[field])
    return out


def response_id(value):
    try:
        return record_id(value)
    except ValueError:
        raise RuntimeError("Dokploy returned an invalid metadata record ID") from None


def _collection(raw):
    if not isinstance(raw, list) or len(raw) > MAX_RECORDS:
        raise RuntimeError("Dokploy metadata collection is invalid or exceeds the local bound")
    return raw


def _unique(rows, key):
    if len({row[key] for row in rows}) != len(rows):
        raise RuntimeError("Dokploy returned duplicate metadata record IDs")
    return rows


async def identity(data):
    current = await current_credential(data)
    raw = await request(data, "user.get")
    if not isinstance(raw, dict) or not isinstance(raw.get("user"), dict):
        raise RuntimeError("Dokploy did not return the documented current-member identity envelope")
    ids = {key: response_id(raw.get(key)) for key in ("id", "userId", "organizationId")}
    if ids["userId"] != response_id(raw["user"].get("id")) or ids["userId"] != current["user_id"] or ids["organizationId"] != current["organization_id"]:
        raise ValueError("Dokploy current user or active team differs from the saved binding")
    role = metadata_text(raw.get("role"))
    return {"id": ids["userId"], "memberId": ids["id"], "organizationId": ids["organizationId"], "role": role}


async def owner_witness(data):
    who = await identity(data)
    if who["role"] != "owner":
        raise ValueError("Dokploy empty-object writes require the current organization owner")
    return who


def project_metadata(raw, org):
    out = _record(raw, "projectId", ("name", "description", "createdAt"))
    if response_id(raw.get("organizationId")) != org:
        raise ValueError("Dokploy project is outside the bound organization")
    out["organizationId"] = org
    return out


async def project(data, project_id, org):
    raw = await request(data, "project.one", params={"projectId": project_id})
    out = project_metadata(raw, org)
    if out["projectId"] != project_id:
        raise ValueError("Dokploy returned a different project")
    return raw, out


def environment_metadata(raw, project_id):
    out = _record(raw, "environmentId", ("name", "description"))
    parent = raw.get("projectId") or (raw.get("project") or {}).get("projectId")
    if response_id(parent) != project_id:
        raise ValueError("Dokploy environment is outside the selected project")
    if type(raw.get("isDefault")) is not bool:
        raise RuntimeError("Dokploy environment default flag is unverified")
    out.update(projectId=project_id, isDefault=raw["isDefault"])
    return out


async def environment(data, project_id, environment_id, org):
    await project(data, project_id, org)
    raw = await request(data, "environment.one", params={"environmentId": environment_id})
    out = environment_metadata(raw, project_id)
    if out["environmentId"] != environment_id or raw.get("projectId") != project_id:
        raise ValueError("Dokploy environment parent or selected ID differs")
    if not isinstance(raw.get("project"), dict) or project_metadata(raw["project"], org)["projectId"] != project_id:
        raise ValueError("Dokploy environment team or parent witness is missing")
    return raw, out


def service_metadata(raw, kind, environment_id):
    key, status_key = SERVICE_KEYS[kind]
    out = _record(raw, key, ("name", "description", "createdAt"))
    if raw.get(status_key) is not None:
        status = raw[status_key]
        if status not in {"idle", "running", "done", "error"}:
            raise RuntimeError("Dokploy returned an unknown service status")
        out["status"] = status
    out.update(service_type=kind, environmentId=environment_id)
    return out


def services(raw, environment_id):
    rows = []
    for kind in SERVICE_KEYS:
        for item in _collection(raw.get(kind)):
            rows.append(service_metadata(item, kind, environment_id))
    if len(rows) > MAX_RECORDS or len({(r["service_type"], next(r[k] for k in (v[0] for v in SERVICE_KEYS.values()) if k in r)) for r in rows}) != len(rows):
        raise RuntimeError("Dokploy service metadata is excessive or duplicated")
    return rows


def require_empty(raw):
    # Every v0.30.8 service family must be present; missing/filtered data is not emptiness.
    if any(_collection(raw.get(kind)) for kind in SERVICE_KEYS):
        raise ValueError("Dokploy disposable object is not empty")


async def empty_project(data, cfg, org):
    raw, out = await project(data, cfg["project_id"], org)
    if out.get("name") != cfg["expected_project_name"]:
        raise ValueError("Dokploy disposable project's current name changed")
    for env in _collection(raw.get("environments")):
        record_id(env.get("environmentId"))
        require_empty(env)
    return raw, out


async def records(data, args):
    cfg = TypeAdapter(DokployOperation).validate_python(args).model_dump()
    who = await identity(data)
    org = who["organizationId"]
    common = {"read_completed": True, "identity_verified": True, "organization_id": org}
    op = cfg["operation"]
    if op == "get_current_user":
        return {**common, **who, "record": who}
    if op == "list_projects":
        rows = [project_metadata(row, org) for row in _collection(await request(data, "project.all"))]
        return {**common, "records": _unique(rows, "projectId"), "pagination": "unpaginated", "local_record_limit": MAX_RECORDS}
    if op in {"create_project", "update_project", "delete_project", "create_environment", "update_environment", "delete_environment"}:
        if who["role"] != "owner":
            raise ValueError("Dokploy empty-object writes require the current organization owner")
        if op != "create_project":
            await empty_project(data, cfg, org)
        if op == "create_project":
            existing = _collection(await request(data, "project.all"))
            if any(p.get("name") == cfg["name"] for p in existing):
                raise ValueError("Dokploy disposable project name already exists")
            await owner_witness(data)
            body = {k: cfg[k] for k in ("name", "description") if cfg[k] is not None}
            raw = await request(data, "project.create", body=body)
            if not isinstance(raw, dict) or not isinstance(raw.get("project"), dict) or not isinstance(raw.get("environment"), dict):
                raise RuntimeError("Dokploy creation envelope unverified; do not retry automatically")
            created = project_metadata(raw["project"], org)
            env = environment_metadata(raw["environment"], created["projectId"])
            if created.get("name") != cfg["name"] or not env["isDefault"] or env.get("name") != "production":
                raise RuntimeError("Dokploy creation readback differs; do not retry automatically")
            checked_raw, checked = await project(data, created["projectId"], org)
            children = _collection(checked_raw.get("environments"))
            for child in children:
                require_empty(child)
            if checked.get("name") != cfg["name"] or not any(child.get("environmentId") == env["environmentId"] and child.get("isDefault") is True for child in children):
                raise RuntimeError("Dokploy project creation readback differs")
            return {**common, "mutation_completed": True, "record": checked, "default_environment": env}
        if op in {"update_project", "delete_project"}:
            await owner_witness(data)
            body = {"projectId": cfg["project_id"]}
            if op == "update_project":
                body.update({k: cfg[k] for k in ("name", "description") if cfg[k] is not None})
            raw = await request(data, "project.update" if op == "update_project" else "project.remove", body=body)
            if project_metadata(raw, org)["projectId"] != cfg["project_id"]:
                raise RuntimeError("Dokploy mutation readback differs; do not retry automatically")
            if op == "delete_project":
                remaining = _collection(await request(data, "project.all"))
                if any(row.get("projectId") == cfg["project_id"] for row in remaining):
                    raise RuntimeError("Dokploy project removal is not confirmed")
                return {**common, "mutation_completed": True, "deleted_id": cfg["project_id"], "absence_readback": True}
            _, checked = await project(data, cfg["project_id"], org)
            if checked.get("name") != cfg["name"] or cfg["description"] is not None and checked.get("description") != cfg["description"]:
                raise RuntimeError("Dokploy project update readback differs")
            return {**common, "mutation_completed": True, "record": checked}
        if op == "create_environment":
            raw_envs = _collection(await request(data, "environment.byProjectId", params={"projectId": cfg["project_id"]}))
            if any(row.get("name") == cfg["name"] for row in raw_envs):
                raise ValueError("Dokploy disposable environment name already exists")
            await owner_witness(data)
            body = {"projectId": cfg["project_id"], "name": cfg["name"]}
            if cfg["description"] is not None:
                body["description"] = cfg["description"]
            raw = await request(data, "environment.create", body=body)
            created = environment_metadata(raw, cfg["project_id"])
            _, checked = await environment(data, cfg["project_id"], created["environmentId"], org)
            if checked.get("name") != cfg["name"] or checked["isDefault"]:
                raise RuntimeError("Dokploy environment creation readback differs")
            return {**common, "mutation_completed": True, "record": checked}
        raw, out = await environment(data, cfg["project_id"], cfg["environment_id"], org)
        require_empty(raw)
        if out["isDefault"] or out.get("name") != cfg["expected_environment_name"]:
            raise ValueError("Dokploy environment is default or its disposable name changed")
        await owner_witness(data)
        body = {"environmentId": cfg["environment_id"]}
        if op == "update_environment":
            body.update({k: cfg[k] for k in ("name", "description") if cfg[k] is not None})
        changed = environment_metadata(await request(data, "environment.update" if op == "update_environment" else "environment.remove", body=body), cfg["project_id"])
        if changed["environmentId"] != cfg["environment_id"]:
            raise RuntimeError("Dokploy environment mutation readback differs")
        if op == "delete_environment":
            remaining = _collection(await request(data, "environment.byProjectId", params={"projectId": cfg["project_id"]}))
            if any(row.get("environmentId") == cfg["environment_id"] for row in remaining):
                raise RuntimeError("Dokploy environment removal is not confirmed")
            return {**common, "mutation_completed": True, "deleted_id": cfg["environment_id"], "absence_readback": True}
        _, checked = await environment(data, cfg["project_id"], cfg["environment_id"], org)
        if checked.get("name") != cfg["name"] or cfg["description"] is not None and checked.get("description") != cfg["description"]:
            raise RuntimeError("Dokploy environment update readback differs")
        return {**common, "mutation_completed": True, "record": checked}
    if op == "get_project":
        _, out = await project(data, cfg["project_id"], org)
        return {**common, "record": out}
    if op == "list_environments":
        await project(data, cfg["project_id"], org)
        rows = [environment_metadata(r, cfg["project_id"]) for r in _collection(await request(data, "environment.byProjectId", params={"projectId": cfg["project_id"]}))]
        return {**common, "records": _unique(rows, "environmentId"), "pagination": "unpaginated"}
    raw, out = await environment(data, cfg["project_id"], cfg["environment_id"], org)
    if op == "get_environment":
        return {**common, "record": out}
    rows = services(raw, cfg["environment_id"])
    if op == "list_services":
        return {**common, "records": rows, "pagination": "unpaginated"}
    kind, key = ("applications", "applicationId") if "application" in op else ("compose", "composeId")
    selected = cfg["application_id" if kind == "applications" else "compose_id"]
    match = [r for r in rows if r["service_type"] == kind and r[key] == selected]
    if len(match) != 1:
        raise ValueError("Dokploy service was not witnessed in the selected project/environment")
    if op in {"get_application", "get_compose"}:
        return {**common, "record": match[0]}
    procedure = "deployment.all" if kind == "applications" else "deployment.allByCompose"
    deployments = []
    for row in _collection(await request(data, procedure, params={key: selected})):
        record = _record(row, "deploymentId", ("title", "createdAt", "startedAt", "finishedAt"))
        if row.get(key) != selected or row.get("status") not in {"running", "done", "error", "cancelled"}:
            raise ValueError("Dokploy deployment parent or status differs")
        record.update({key: selected, "status": row["status"]})
        deployments.append(record)
    return {**common, "records": _unique(deployments, "deploymentId"), "pagination": "unpaginated"}


class DokployNode(WorkflowNode):
    integration_type = "automation-dokploy"
    scope_registry = ScopeRegistry(provider="dokploy", enforcement=Enforcement.STRICT, requirements={op: ScopeRequirement(scopes=(), credential_types=(FAMILY,)) for op in OPS})
    # Use the admitted operation seam: the direct picker probe bypasses saved
    # credential approval and supplies label/value rows rather than project rows.
    connection_evidence = ConnectionEvidence(noun="Dokploy projects", operation="list_projects", identity_operation="get_current_user", label_keys=("name", "projectId"), identity_keys=("id", "organizationId"))
    edit_examples = ["List projects and environment service status", "Read existing application deployment receipts", "Manage explicitly confirmed empty disposable project metadata"]
    @classmethod
    def get_config_model(cls):
        return DokployNodeConfig
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
                return {"valid": False, "errors": ["Connect a native Dokploy API key"], "satisfied_set": None}
        return super().validate_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Supplied API keys do not rotate automatically."""
        return credential(credential_data)

    @classmethod
    async def validate_credential_access(cls, credential_data, **kwargs):
        try:
            data = credential(credential_data)
        except ValueError:
            return {"valid": False, "error": "Dokploy credential shape is invalid"}
        try:
            await records(data, {"operation": "get_current_user"})
        except (ValueError, _RequestRefused):
            return {"valid": False, "error": "Dokploy refused the current credential, user or organization"}
        except Exception:
            return {"valid": None, "error": "Dokploy current access could not be judged"}
        return {"valid": True, "proves": "account", "identity_verified": True}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"project_id", "environment_id", "application_id", "compose_id"}:
            raise ValueError("Unsupported Dokploy picker")
        if page_token is not None:
            raise ValueError("Dokploy metadata endpoints are unpaginated; reload options")
        search = normalize_search(search)
        if search and (len(search) > 200 or any(ord(c) < 32 for c in search)):
            raise ValueError("Use a bounded Dokploy picker search")
        context = context or {}
        args = {"operation": "list_projects"}
        if field_name != "project_id":
            args = {"operation": "list_environments", "project_id": record_id(context.get("project_id"))}
        if field_name in {"application_id", "compose_id"}:
            args.update(operation="list_services", environment_id=record_id(context.get("environment_id")))
        result = await records(credential_data, args)
        key = {"project_id": "projectId", "environment_id": "environmentId", "application_id": "applicationId", "compose_id": "composeId"}[field_name]
        options = [{"value": row[key], "label": row.get("name") or row[key]} for row in result["records"] if key in row]
        return {"options": filter_options_by_search(options, search), "next_page_token": None}
    async def execute(self, inputs):
        if not isinstance(self.config, DokployNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a native Dokploy API key")
        data = credential(self.config.credentials.model_dump())
        if self.node_data.get("credentials") is not None and credential(self.node_data["credentials"]) != data:
            raise ValueError("Dokploy raw credential differs from the parsed credential")
        if self.node_data.get("credential_id"):
            from utils.database_pool import get_native_pool
            authority = dict(credential_id=self.node_data["credential_id"], user_id=self.user_id,
                pool=getattr(self, "_approval_pool", None) or get_native_pool(),
                org_id=getattr(self, "organization_id", None), workflow_id=getattr(self, "workflow_id", None))
            data = _BoundCredential(data, authority)
        return await records(data, self.config.config.model_dump())
