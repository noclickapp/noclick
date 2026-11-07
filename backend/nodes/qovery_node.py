"""Organization-bound Qovery machine-token metadata operations.

This native node projects deployment metadata without secrets or deploy controls.
Empty project/environment edits use explicit preflight and separate readbacks.
"""
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import hmac
import json
import re
from typing import Annotated, Any, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

ROOT = "https://api.qovery.com"
TYPE = "qovery_api_token"
MAX_BYTES = 2 * 1024 * 1024
ID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
Identifier = Annotated[str, Field(pattern="^" + ID_PATTERN + "$")]
Snapshot = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ServiceKind = Literal["application", "container", "database", "helm", "job"]
SERVICE_TYPES = {"APPLICATION", "CONTAINER", "DATABASE", "HELM", "JOB", "TERRAFORM", "ARGOCD_APP", "AGENTIC_WORKFLOW"}
STATES = {"BUILDING", "BUILD_ERROR", "CANCELED", "CANCELING", "DELETED", "DELETE_ERROR", "DELETE_QUEUED", "DELETING", "DEPLOYED", "DEPLOYING", "DEPLOYMENT_ERROR", "DEPLOYMENT_QUEUED", "EXECUTING", "QUEUED", "READY", "RECAP", "RESTARTED", "RESTARTING", "RESTART_ERROR", "RESTART_QUEUED", "STOPPED", "STOPPING", "STOP_ERROR", "STOP_QUEUED", "UNAVAILABLE", "WAITING_DELETING", "WAITING_RESTARTING", "WAITING_RUNNING", "WAITING_STOPPING"}
CLUSTER_STATES = (STATES - {"EXECUTING", "RECAP", "UNAVAILABLE", "WAITING_DELETING", "WAITING_RESTARTING", "WAITING_RUNNING", "WAITING_STOPPING"}) | {"DRY_RUN", "INVALID_CREDENTIALS"}
OPERATIONS = {"get_organization", "list_projects", "get_project", "create_empty_project", "update_empty_project", "list_environments", "get_environment", "create_empty_environment", "rename_empty_environment", "get_environment_status", "list_clusters", "get_cluster", "get_cluster_status", "list_services", "get_service_status", "list_environment_deployments", "list_service_deployments"}


def parse_uuid(value):
    if not isinstance(value, str) or not re.fullmatch(ID_PATTERN, value.lower()):
        raise ValueError("Supply an exact Qovery UUID")
    return str(UUID(value))


def clean_name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Use a nonblank metadata name of up to 256 characters")
    return value


class QoveryAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Qovery API Token", extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://www.qovery.com/docs/api-reference/authentication"})
    credential_type: Literal["qovery_api_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    organization_id: Identifier = Field(..., title="Authorized Organization UUID", description="Exact organization approved for this machine API token. Parent records must belong to this organization.")
    api_token: str = Field(..., min_length=1, max_length=8192, repr=False, title="Machine API Token", description="Supply only the machine API token, without a prefix. Sent as Authorization: Token. Human OIDC Bearer tokens, scope discovery and token creation are not implemented.", json_schema_extra={"ui:widget": "password"})
    _org = field_validator("organization_id", mode="before")(parse_uuid)

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        if any(ord(c) < 33 or ord(c) > 126 for c in value) or value.lower().startswith(("bearer ", "token ")):
            raise ValueError("Supply the opaque machine API token without a header prefix")
        return value

    @model_serializer(mode="wrap")
    def canonical(self, handler):
        return {**handler(self), "credential_type": TYPE}


def guard(data):
    if not isinstance(data, dict) or data.get("credential_type") != TYPE:
        raise ValueError("Connect a typed Qovery machine-token credential")
    try:
        return QoveryAPITokenCredential.model_validate({k: v for k, v in data.items() if k not in {"_qovery_reader", "token_version", "updated_at"}})
    except ValueError:
        raise ValueError("Qovery credential is invalid; reconnect it") from None


def authority(value):
    return value.credential_type, value.organization_id, value.api_token


async def current(credential_id, user_id, organization_id=None, workflow_id=None, *, pool=None):
    if not user_id:
        raise ValueError("Stored Qovery credentials require a caller")
    from utils.database_pool import get_native_pool
    from utils.credentials import resolve_credential_with_owner_fallback
    data = await resolve_credential_with_owner_fallback(
        credential_id, user_id, pool or get_native_pool(),
        org_id=organization_id, workflow_id=workflow_id,
    )
    if data is None:
        raise ValueError("Qovery credential is unavailable; reconnect it")
    return guard(data)


@dataclass(repr=False)
class Reader:
    credential_id: Any
    user_id: Any
    organization_id: Any = None
    workflow_id: Any = None
    pool: Any = None
    anchor: Any = field(default=None, repr=False)
    expected: Any = field(default=None, repr=False)

    async def read(self):
        value = await current(self.credential_id, self.user_id, self.organization_id, self.workflow_id, pool=self.pool)
        if self.expected is not None and authority(value) != self.expected:
            raise ValueError("Qovery cached credential changed; reload it")
        binding = authority(value)
        if self.anchor is not None and binding != self.anchor:
            raise ValueError("Qovery saved credential changed during this call; inspect before retrying")
        self.anchor = binding
        return value


def op(value, title, category):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": category, "x-is-trigger": False})


def resource(name, parent=None):
    dyn = {"field_name": name, "searchable": True, "allow_custom": True}
    if parent:
        dyn["depends_on"] = parent
    return {"x-resource-type": "qovery_" + name.removesuffix("_id"), "x-dynamic-options": dyn}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    _ids = field_validator("project_id", "environment_id", "cluster_id", "service_id", "start_id", mode="before", check_fields=False)(parse_uuid)
    _names = field_validator("name", mode="before", check_fields=False)(clean_name)

    @model_validator(mode="before")
    @classmethod
    def empty_controls(cls, data):
        # The native editor normalizes unset optional controls to None.
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if not (k in {"description", "start_id", "clear_description"} and v is None)}
        return data


class Project(Input):
    project_id: Identifier = Field(..., title="Project", json_schema_extra=resource("project_id"))


class Environment(Project):
    environment_id: Identifier = Field(..., title="Environment", json_schema_extra=resource("environment_id", "project_id"))


class Cluster(Input):
    cluster_id: Identifier = Field(..., title="Organization Cluster", json_schema_extra=resource("cluster_id"))


class Service(Environment):
    service_kind: ServiceKind = Field(..., title="Service Kind", description="Status/history routes are supported only for these five documented kinds. The selected service's actual kind is checked before the route is called.")
    service_id: Identifier = Field(..., title="Service", json_schema_extra=resource("service_id", "environment_id"))


class GetOrganization(Input):
    operation: Literal["get_organization"] = op("get_organization", "Get Authorized Organization", "Organization")


class ListProjects(Input):
    operation: Literal["list_projects"] = op("list_projects", "List Organization Projects", "Projects")


class GetProject(Project):
    operation: Literal["get_project"] = op("get_project", "Get Project Metadata", "Projects")


class CreateProject(Input):
    operation: Literal["create_empty_project"] = op("create_empty_project", "Create Empty Project", "Projects")
    name: str = Field(..., min_length=1, max_length=256, title="Project Name")
    description: str | None = Field(None, max_length=4096, title="Description", description="Optional plain metadata, without secrets. No environment or service is created.")


class UpdateProject(Project):
    operation: Literal["update_empty_project"] = op("update_empty_project", "Update Empty Project Metadata", "Projects")
    name: str = Field(..., min_length=1, max_length=256, title="Project Name")
    description: str | None = Field(None, max_length=4096, title="New Description", description="Omitted text preserves the current description. Use Clear Description to send an explicit empty string.")
    clear_description: bool = Field(False, title="Clear Description")
    expected_snapshot: Snapshot = Field(..., title="Expected Project Snapshot", description="From Get Project. The empty check is a local preflight, not an atomic provider lock.")

    @model_validator(mode="after")
    def clear_control(self):
        if self.clear_description and self.description is not None:
            raise ValueError("Use either a new description or Clear Description")
        return self


class ListEnvironments(Project):
    operation: Literal["list_environments"] = op("list_environments", "List Project Environments", "Environments")


class GetEnvironment(Environment):
    operation: Literal["get_environment"] = op("get_environment", "Get Environment Metadata", "Environments")


class CreateEnvironment(Project):
    operation: Literal["create_empty_environment"] = op("create_empty_environment", "Create Empty Environment", "Environments")
    cluster_id: Identifier = Field(..., title="Existing Organization Cluster", json_schema_extra=resource("cluster_id"))
    name: str = Field(..., min_length=1, max_length=256, title="Environment Name")
    mode: Literal["DEVELOPMENT", "PRODUCTION", "STAGING"] = Field("DEVELOPMENT", title="Environment Mode", description="Metadata mode only; no services, cloning or deployment request. Existing project rules may affect later behavior.")


class RenameEnvironment(Environment):
    operation: Literal["rename_empty_environment"] = op("rename_empty_environment", "Rename Empty Environment", "Environments")
    name: str = Field(..., min_length=1, max_length=256, title="New Name")
    expected_snapshot: Snapshot = Field(..., title="Expected Environment Snapshot", description="From Get Environment. Requires an empty service inventory; this preflight is not an atomic server condition.")


class EnvironmentStatus(Environment):
    operation: Literal["get_environment_status"] = op("get_environment_status", "Get Environment Deployment Status", "Status")


class ListClusters(Input):
    operation: Literal["list_clusters"] = op("list_clusters", "List Organization Cluster Metadata", "Clusters")


class GetCluster(Cluster):
    operation: Literal["get_cluster"] = op("get_cluster", "Get Organization Cluster Metadata", "Clusters")


class ClusterStatus(Cluster):
    operation: Literal["get_cluster_status"] = op("get_cluster_status", "Get Cluster Status", "Status")


class ListServices(Environment):
    operation: Literal["list_services"] = op("list_services", "List Environment Service Metadata", "Services")


class ServiceStatus(Service):
    operation: Literal["get_service_status"] = op("get_service_status", "Get Service Deployment Status", "Status")


class EnvironmentDeployments(Environment):
    operation: Literal["list_environment_deployments"] = op("list_environment_deployments", "List Environment Deployment Metadata", "Deployments")
    start_id: Identifier | None = Field(None, title="Start After Deployment UUID", description="Documented startId cursor. Omit for the first page; a full page does not prove another page exists.")


class ServiceDeployments(Service):
    operation: Literal["list_service_deployments"] = op("list_service_deployments", "List Service Deployment Metadata", "Deployments")
    start_id: Identifier | None = Field(None, title="Start After Deployment UUID", description="Documented startId cursor for this exact service. One page per run; no automatic traversal.")


Config = Annotated[Union[GetOrganization, ListProjects, GetProject, CreateProject, UpdateProject, ListEnvironments, GetEnvironment, CreateEnvironment, RenameEnvironment, EnvironmentStatus, ListClusters, GetCluster, ClusterStatus, ListServices, ServiceStatus, EnvironmentDeployments, ServiceDeployments], Field(discriminator="operation")]


class QoveryNodeConfig(NodeConfig[Config, QoveryAPITokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate response field")
        result[key] = value
    return result


def reject_number(_value):
    raise ValueError("Nonfinite response number")


async def request(value, method, path, *, params=None, body=None, reader=None):
    org = "/organization/" + value.organization_id
    reads = path in {org, org + "/project", org + "/cluster"} or re.fullmatch(org + r"/cluster/" + ID_PATTERN + r"/status", path) or re.fullmatch(r"/project/" + ID_PATTERN + r"(?:/environment)?|/environment/" + ID_PATTERN + r"(?:/(?:services|status|deploymentHistory))?|/(?:application|container|database|helm|job)/" + ID_PATTERN + r"/(?:status|deploymentHistory)", path)
    create = method == "POST" and (path == org + "/project" or re.fullmatch(r"/project/" + ID_PATTERN + r"/environment", path))
    update = method == "PUT" and re.fullmatch(r"/(?:project|environment)/" + ID_PATTERN, path)
    if not (method == "GET" and reads or create or update):
        raise ValueError("Unsupported Qovery metadata resource")
    params = dict(params or {})
    if params and (method != "GET" or not re.fullmatch(r"/(?:environment|application|database)/" + ID_PATTERN + r"/deploymentHistory", path) or set(params) != {"startId"} or parse_uuid(params["startId"]) != params["startId"]):
        raise ValueError("Unsupported Qovery metadata query")
    if method == "GET" and body is not None or method != "GET" and not isinstance(body, dict):
        raise ValueError("Unsupported Qovery metadata body")
    if create or update:
        allowed = {"name", "description"} if "/project" in path and not path.endswith("/environment") else {"name", "cluster", "mode"} if create else {"name"}
        if set(body) - allowed or "name" not in body:
            raise ValueError("Unsupported Qovery metadata fields")
    if reader:
        value = await reader.read()
    headers = {"Accept": "application/json", "Cache-Control": "no-store", "Authorization": "Token " + value.api_token}
    if body is not None:
        headers["Content-Type"] = "application/json"
    expected = 201 if create and path.endswith("/environment") else 200
    try:
        async with guarded_async_client(timeout=12, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, ROOT + path, params=params, json=body, headers=headers) as response:
                if response.status_code != expected:
                    status = response.status_code
                    hint = "the machine token" if status == 401 else "organization/project role permissions" if status == 403 else "the selected resource" if status == 404 else "a concurrent metadata change" if status == 409 else "rate limits; retry manually later" if status == 429 else "the documented response contract or service availability"
                    raise ValueError(f"Qovery request failed (HTTP {status}); check {hint}. Inspect writes before retrying")
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ValueError("Qovery returned an unexpected response format")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise ValueError("Qovery response exceeded the 2 MiB local limit")
    except httpx.HTTPError:
        raise ValueError("Qovery connection failed; inspect writes before retrying") from None
    if reader:
        await reader.read()
    try:
        payload = json.loads(data, object_pairs_hook=unique_json, parse_constant=reject_number)
        if not isinstance(payload, dict) or "errors" in payload or "error" in payload:
            raise ValueError()
        return payload
    except (ValueError, TypeError, UnicodeError):
        raise ValueError("Qovery returned malformed metadata; inspect writes before retrying") from None


def text(value, *, empty=False, limit=1024):
    if not isinstance(value, str) or len(value) > limit or not empty and not value.strip() or any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in value):
        raise ValueError("Malformed Qovery metadata text")
    return value


def integer(value, *, maximum=2147483647):
    if type(value) not in {int, float} or not 0 <= value <= maximum or int(value) != value:
        raise ValueError("Malformed Qovery metadata count")
    return int(value)


def boolean(value):
    if type(value) is not bool:
        raise ValueError("Malformed Qovery metadata flag")
    return value


def timestamp(value):
    value = text(value, limit=64)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
    except ValueError:
        raise ValueError("Malformed Qovery metadata timestamp") from None
    return value


def base_record(payload, expected=None, *, named=True):
    if not isinstance(payload, dict):
        raise ValueError("Malformed Qovery metadata record")
    identifier = parse_uuid(payload.get("id"))
    if expected is not None and identifier != expected:
        raise ValueError("Qovery returned a different metadata resource")
    result = {"id": identifier, "created_at": timestamp(payload.get("created_at"))}
    if named:
        result["name"] = text(payload.get("name"))
    if payload.get("updated_at") is not None:
        result["updated_at"] = timestamp(payload["updated_at"])
    return result


def parent_id(payload, field_name, expected):
    reference = payload.get(field_name)
    if not isinstance(reference, dict) or parse_uuid(reference.get("id")) != expected:
        raise ValueError("Qovery metadata belongs to a different " + field_name)
    return expected


def organization_record(payload, expected):
    return base_record(payload, expected)


def project_record(payload, organization, expected=None):
    result = base_record(payload, expected)
    result["organization_id"] = parent_id(payload, "organization", organization)
    result["associated_environments_count"] = integer(payload.get("associated_environments_count"))
    if payload.get("description") is not None:
        result["description"] = text(payload["description"], empty=True, limit=4096)
    return result


def environment_record(payload, organization, project, expected=None):
    result = base_record(payload, expected)
    result["organization_id"] = parent_id(payload, "organization", organization)
    result["project_id"] = parent_id(payload, "project", project)
    result["cluster_id"] = parse_uuid(payload.get("cluster_id"))
    mode = payload.get("mode")
    if mode not in {"DEVELOPMENT", "PREVIEW", "PRODUCTION", "STAGING"}:
        raise ValueError("Unsupported Qovery environment mode")
    result["mode"] = mode
    if payload.get("cluster_name") is not None:
        result["cluster_name"] = text(payload["cluster_name"])
    if payload.get("expires_at") is not None:
        result["expires_at"] = timestamp(payload["expires_at"])
    return result


def cluster_record(payload, organization):
    result = base_record(payload)
    result["organization_id"] = parent_id(payload, "organization", organization)
    result["region"] = text(payload.get("region"))
    result["cloud_provider"] = text(payload.get("cloud_provider"), limit=64)
    for key in ("production", "is_default", "is_demo"):
        if key in payload:
            result[key] = boolean(payload[key])
    if payload.get("status") is not None:
        if payload["status"] not in CLUSTER_STATES:
            raise ValueError("Unsupported Qovery cluster state")
        result["status"] = payload["status"]
    return result


def service_record(payload, environment):
    result = base_record(payload)
    result["environment_id"] = parent_id(payload, "environment", environment)
    if payload.get("service_type") not in SERVICE_TYPES:
        raise ValueError("Unsupported Qovery service metadata kind")
    result["service_type"] = payload["service_type"]
    return result


def results(payload, projector):
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list) or len(payload["results"]) > 1000:
        raise ValueError("Unexpected or oversized Qovery metadata inventory")
    items = [projector(item) for item in payload["results"]]
    if len({item["id"] for item in items}) != len(items):
        raise ValueError("Qovery repeated a metadata resource ID")
    return items


def snapshot(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def status_record(payload, expected, kind):
    if not isinstance(payload, dict):
        raise ValueError("Malformed Qovery deployment status")
    key = "cluster_id" if kind == "cluster" else "id"
    if parse_uuid(payload.get(key)) != expected:
        raise ValueError("Qovery returned status for a different resource")
    state_key = "status" if kind == "cluster" else "state"
    state = payload.get(state_key)
    if state not in (CLUSTER_STATES if kind == "cluster" else STATES):
        raise ValueError("Unsupported Qovery deployment state")
    result = {"id": expected, "state": state}
    if kind == "cluster":
        result["is_deployed"] = boolean(payload.get("is_deployed"))
        if payload.get("reason") not in {"UNSPECIFIED", "MAINTENANCE"}:
            raise ValueError("Unsupported Qovery cluster status reason")
        result["reason"] = payload["reason"]
    elif kind == "environment":
        if payload.get("last_deployment_state") not in STATES:
            raise ValueError("Unsupported Qovery last deployment state")
        result["last_deployment_state"] = payload["last_deployment_state"]
    else:
        if payload.get("service_deployment_status") not in {"NEVER_DEPLOYED", "OUT_OF_DATE", "UP_TO_DATE"}:
            raise ValueError("Unsupported Qovery service deployment status")
        result["service_deployment_status"] = payload["service_deployment_status"]
        result["is_part_last_deployment"] = boolean(payload.get("is_part_last_deployment"))
        result["deployment_requests_count"] = integer(payload.get("deployment_requests_count"))
        result["deployment_request_id"] = parse_uuid(payload["deployment_request_id"]) if payload.get("deployment_request_id") is not None else None
    # Deliberately omit metrics, steps, logs, commit/image/source and actor data.
    return result


def history_page(payload, kind, start_id):
    def project(row):
        result = base_record(row, named=False)
        accepted = {"FAILED", "SUCCESS"} if kind == "application" else STATES
        if "status" in row:
            if row["status"] not in accepted:
                raise ValueError("Unsupported Qovery deployment history status")
            result["status"] = row["status"]
        return result
    items = results(payload, project)
    page, size = integer(payload.get("page")), integer(payload.get("page_size"), maximum=1000)
    if page < 1 or size < 1 or len(items) > size or start_id in {i["id"] for i in items}:
        raise ValueError("Malformed Qovery deployment history page")
    full = len(items) == size
    cursor_supported = kind in {"environment", "application", "database"}
    return {"items": items, "count": len(items), "page": page, "page_size": size, "has_more": None if full else False, "next_start_id": items[-1]["id"] if full and cursor_supported else None, "next_page_requires_read": full and cursor_supported, "cursor_supported": cursor_supported, "recent_window_only": not cursor_supported}


class QoveryNode(WorkflowNode):
    integration_type = "automation-qovery"
    connection_evidence = ConnectionEvidence(operation="get_organization", noun="authorized organizations", proves="reachability", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return QoveryNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        if isinstance(config_data, dict) and config_data.get("credentials"):
            config_data = {**config_data, "credentials": guard(config_data["credentials"]).model_dump()}
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        if isinstance(config_data, dict) and config_data.get("credentials"):
            try:
                config_data = {**config_data, "credentials": guard(config_data["credentials"]).model_dump()}
            except ValueError as error:
                return {"valid": False, "errors": [str(error)], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._freshen_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
        )

    @classmethod
    async def _freshen_credential(cls, data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=None):
        value = guard(data)
        if credential_id:
            reader = Reader(credential_id, user_id, organization_id, workflow_id, pool, expected=authority(value))
            value = await reader.read()
            return {**value.model_dump(), "_qovery_reader": reader}
        return value.model_dump()

    @staticmethod
    async def _organization(value, reader):
        return organization_record(await request(value, "GET", "/organization/" + value.organization_id, reader=reader), value.organization_id)

    @staticmethod
    async def _project(value, identifier, reader):
        return project_record(await request(value, "GET", "/project/" + identifier, reader=reader), value.organization_id, identifier)

    @staticmethod
    async def _environments(value, identifier, reader):
        return results(await request(value, "GET", "/project/" + identifier + "/environment", reader=reader), lambda item: environment_record(item, value.organization_id, identifier))

    @staticmethod
    async def _environment(value, project, identifier, reader):
        return environment_record(await request(value, "GET", "/environment/" + identifier, reader=reader), value.organization_id, project, identifier)

    @staticmethod
    async def _clusters(value, reader):
        return results(await request(value, "GET", "/organization/" + value.organization_id + "/cluster", reader=reader), lambda item: cluster_record(item, value.organization_id))

    @staticmethod
    async def _services(value, environment, reader):
        return results(await request(value, "GET", "/environment/" + environment + "/services", reader=reader), lambda item: service_record(item, environment))

    @staticmethod
    def _member(items, identifier):
        result = next((item for item in items if item["id"] == identifier), None)
        if result is None:
            raise ValueError("Qovery resource is not in this parent's authorized inventory")
        return result

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"project_id", "environment_id", "cluster_id", "service_id"}:
            return {"options": [], "next_page_token": None}
        value = guard(credential_data)
        context = context or {}
        if not isinstance(context, dict):
            raise ValueError("Supply native Qovery parent context")
        reader = credential_data.get("_qovery_reader")
        search = search or ""
        if not isinstance(search, str) or len(search) > 256 or any(ord(c) < 32 for c in search):
            raise ValueError("Use up to 256 characters of metadata search")
        # Context selects resources only; caller/workflow/org authority is never read here.
        project = parse_uuid(context.get("project_id")) if field_name in {"environment_id", "service_id"} else None
        environment = parse_uuid(context.get("environment_id")) if field_name == "service_id" else None
        kind = context.get("service_kind") if field_name == "service_id" else None
        if kind is not None and kind not in {"application", "container", "database", "helm", "job"}:
            raise ValueError("Unsupported Qovery service picker kind")
        await cls._organization(value, reader)
        if project:
            await cls._project(value, project, reader)
        if field_name == "project_id":
            items = results(await request(value, "GET", "/organization/" + value.organization_id + "/project", reader=reader), lambda item: project_record(item, value.organization_id))
        elif field_name == "environment_id":
            items = await cls._environments(value, project, reader)
        elif field_name == "cluster_id":
            items = await cls._clusters(value, reader)
        else:
            await cls._environment(value, project, environment, reader)
            items = [item for item in await cls._services(value, environment, reader) if item["service_type"].lower() in {"application", "container", "database", "helm", "job"} and (kind is None or item["service_type"].lower() == kind)]
        items = [item for item in items if search.casefold() in (item["name"] + " " + item["id"]).casefold()]
        binding = snapshot({"field": field_name, "project": project, "environment": environment, "kind": kind, "search": search, "inventory": items})
        offset = 0
        key = json.dumps(authority(value)).encode()
        if page_token is not None:
            try:
                if not isinstance(page_token, str) or len(page_token) > 4096:
                    raise ValueError()
                raw, signature = page_token.rsplit(".", 1)
                saved = json.loads(raw)
                if saved["binding"] != binding or type(saved["offset"]) is not int or saved["offset"] < 50 or saved["offset"] % 50 or not hmac.compare_digest(signature, hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()):
                    raise ValueError()
                offset = saved["offset"]
            except (ValueError, AttributeError, KeyError, TypeError):
                raise ValueError("Qovery continuation does not match the current token, organization, parent, search and inventory") from None
        if offset and offset >= len(items):
            raise ValueError("Qovery inventory changed; start the picker again")
        selected = items[offset:offset + 50]
        raw = json.dumps({"binding": binding, "offset": offset + 50}, sort_keys=True, separators=(",", ":"))
        token = raw + "." + hmac.new(key, raw.encode(), hashlib.sha256).hexdigest() if offset + 50 < len(items) else None
        return {"options": [{"value": item["id"], "label": item["name"] + (" · " + item["service_type"] if "service_type" in item else "") + " · " + item["id"]} for item in selected], "next_page_token": token}

    async def execute(self, input_data):
        cfg = self.config.config
        raw = self.node_data.get("credentials") or (self.config.credentials.model_dump() if self.config.credentials is not None else None)
        data = await self._freshen_credential(raw, credential_id=self.node_data.get("credential_id"), user_id=self.user_id, workflow_id=self.workflow_id, organization_id=self.organization_id, pool=self.node_data.get("_approval_pool"))
        value, reader = guard(data), data.get("_qovery_reader")
        organization = await self._organization(value, reader)
        operation = cfg.operation
        if operation == "get_organization":
            return {**organization, "items": [organization], "count": 1, "human_identity_verified": False, "token_scope_verified": False}
        if operation == "list_projects":
            items = results(await request(value, "GET", "/organization/" + value.organization_id + "/project", reader=reader), lambda row: project_record(row, value.organization_id))
            return {"items": items, "count": len(items), "pagination": "not_documented"}
        if operation in {"list_clusters", "get_cluster", "get_cluster_status"}:
            items = await self._clusters(value, reader)
            if operation == "list_clusters":
                return {"items": items, "count": len(items), "pagination": "not_documented"}
            item = self._member(items, cfg.cluster_id)
            if operation == "get_cluster":
                return item
            return status_record(await request(value, "GET", f"/organization/{value.organization_id}/cluster/{cfg.cluster_id}/status", reader=reader), cfg.cluster_id, "cluster")
        if operation == "create_empty_project":
            body = {"name": cfg.name}
            if cfg.description is not None:
                body["description"] = cfg.description
            created = project_record(await request(value, "POST", "/organization/" + value.organization_id + "/project", body=body, reader=reader), value.organization_id)
            item = await self._project(value, created["id"], reader)
            children = await self._environments(value, item["id"], reader)
            if item["name"] != cfg.name or item["associated_environments_count"] != 0 or children or cfg.description is not None and item.get("description") != cfg.description:
                raise ValueError("Qovery project create accepted but readback differs or is not empty; inspect before retrying")
            return {**item, "snapshot": snapshot(item), "created": True, "empty_at_readback": True}
        project = await self._project(value, cfg.project_id, reader)
        if operation == "get_project":
            return {**project, "snapshot": snapshot(project)}
        if operation == "list_environments":
            items = await self._environments(value, cfg.project_id, reader)
            return {"items": items, "count": len(items), "project_id": cfg.project_id, "pagination": "not_documented"}
        if operation == "update_empty_project":
            if snapshot(project) != cfg.expected_snapshot or project["associated_environments_count"] != 0 or await self._environments(value, cfg.project_id, reader):
                raise ValueError("Project snapshot changed or contains environments; read it again")
            body = {"name": cfg.name}
            if cfg.clear_description:
                body["description"] = ""
            elif cfg.description is not None:
                body["description"] = cfg.description
            elif "description" in project:
                body["description"] = project["description"]
            project_record(await request(value, "PUT", "/project/" + cfg.project_id, body=body, reader=reader), value.organization_id, cfg.project_id)
            item = await self._project(value, cfg.project_id, reader)
            if item["name"] != cfg.name or item["associated_environments_count"] != 0 or await self._environments(value, cfg.project_id, reader) or "description" in body and item.get("description") != body["description"]:
                raise ValueError("Qovery project update accepted but readback differs; inspect before retrying")
            return {**item, "snapshot": snapshot(item), "updated": True, "empty_at_readback": True, "atomic_precondition": False}
        if operation == "create_empty_environment":
            self._member(await self._clusters(value, reader), cfg.cluster_id)
            created = environment_record(await request(value, "POST", f"/project/{cfg.project_id}/environment", body={"name": cfg.name, "cluster": cfg.cluster_id, "mode": cfg.mode}, reader=reader), value.organization_id, cfg.project_id)
            item = await self._environment(value, cfg.project_id, created["id"], reader)
            if item["name"] != cfg.name or item["cluster_id"] != cfg.cluster_id or item["mode"] != cfg.mode or await self._services(value, item["id"], reader):
                raise ValueError("Qovery environment create accepted but readback differs or contains services; inspect before retrying")
            return {**item, "snapshot": snapshot(item), "created": True, "empty_at_readback": True, "deployment_requested": False}
        environment = await self._environment(value, cfg.project_id, cfg.environment_id, reader)
        if operation == "get_environment":
            return {**environment, "snapshot": snapshot(environment)}
        if operation == "get_environment_status":
            return status_record(await request(value, "GET", "/environment/" + cfg.environment_id + "/status", reader=reader), cfg.environment_id, "environment")
        if operation == "rename_empty_environment":
            if snapshot(environment) != cfg.expected_snapshot or await self._services(value, cfg.environment_id, reader):
                raise ValueError("Environment snapshot changed or contains services; read it again")
            environment_record(await request(value, "PUT", "/environment/" + cfg.environment_id, body={"name": cfg.name}, reader=reader), value.organization_id, cfg.project_id, cfg.environment_id)
            item = await self._environment(value, cfg.project_id, cfg.environment_id, reader)
            if item["name"] != cfg.name or any(item.get(k) != environment.get(k) for k in {"cluster_id", "mode", "expires_at"}) or await self._services(value, cfg.environment_id, reader):
                raise ValueError("Qovery environment rename accepted but readback differs; inspect before retrying")
            return {**item, "snapshot": snapshot(item), "updated": True, "empty_at_readback": True, "atomic_precondition": False, "deployment_requested": False}
        if operation == "list_environment_deployments":
            return history_page(await request(value, "GET", "/environment/" + cfg.environment_id + "/deploymentHistory", params={"startId": cfg.start_id} if cfg.start_id else None, reader=reader), "environment", cfg.start_id)
        services = await self._services(value, cfg.environment_id, reader)
        if operation == "list_services":
            return {"items": services, "count": len(services), "environment_id": cfg.environment_id, "pagination": "not_documented"}
        selected = self._member(services, cfg.service_id)
        if selected["service_type"].lower() != cfg.service_kind:
            raise ValueError("Selected Qovery service has a different actual kind")
        path = "/" + cfg.service_kind + "/" + cfg.service_id
        if operation == "get_service_status":
            return status_record(await request(value, "GET", path + "/status", reader=reader), cfg.service_id, "service")
        if operation == "list_service_deployments":
            if cfg.start_id and cfg.service_kind not in {"application", "database"}:
                raise ValueError("Only application/database histories document startId; other kinds return their recent window")
            return history_page(await request(value, "GET", path + "/deploymentHistory", params={"startId": cfg.start_id} if cfg.start_id else None, reader=reader), cfg.service_kind, cfg.start_id)
        raise ValueError("Unsupported Qovery operation")
