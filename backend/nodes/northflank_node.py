"""Northflank scoped metadata and empty-project management.

Fixed v1 routes return closed metadata, never environment, repository, registry,
build arguments or addon credentials. No workload provisioning or execution.
"""
import json
import re
from typing import Annotated, Any, Dict, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client
from utils.credentials import strip_non_blob_keys

FAMILY = "northflank_api_token"
BASE = "https://api.northflank.com/v1"
MAX_BYTES = 2 * 1024 * 1024


def _text(value, maximum=256, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Use bounded Northflank text without control characters")
    return value


def _id(value):
    value = _text(value, 128)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value): raise ValueError("Use the exact Northflank resource ID")
    return value


def _uid(value):
    value = _text(value, 24)
    if len(value) != 24: raise ValueError("Use Northflank's permanent 24-character resource UID")
    return value


def _description(value):
    value = _text(value, 200)
    if not re.fullmatch(r'''[a-zA-Z0-9.,?\s\\/'"()\[\];`%^&*\-_:!]+''', value): raise ValueError("Use the documented project description characters")
    return value


class NorthflankAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Northflank API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://northflank.com/docs/v1/api/use-the-api",
        "x-credential-instructions": "Supply an issued user or team API token. Use token default for its authenticated context, or explicitly bind requests to a known team ID using the documented /teams/{teamId} routes. Team ID is resource routing, not a verified principal identity. Team tokens require a configured API role; choose only needed read permissions and project manage permissions if using empty-project writes. No OAuth, token mint or refresh is automated. Paid access and role permissions remain unverified."})
    credential_type: Literal["northflank_api_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., repr=False, title="Issued User or Team API Token", json_schema_extra={"ui:widget": "password"})
    target: Literal["token_default", "team"] = Field(..., title="Actual API Routing Context", description="Explicit resource context; not an assertion about the token's principal.")
    team_id: str | None = Field(None, title="Known Team ID", description="Required only for explicit team routes. Not auto-discovered or inferred.")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = _text(value, 4096)
        if any(c.isspace() for c in value) or value.lower().startswith(("bearer ", "basic ")): raise ValueError("Supply the raw issued token, without an authorization prefix")
        return clean_secret(value, field_name="Northflank API token", key=True)

    @field_validator("team_id", mode="before")
    @classmethod
    def team(cls, value): return _id(value) if value is not None else None

    @model_validator(mode="after")
    def target_binding(self):
        if (self.target == "team") != (self.team_id is not None): raise ValueError("Explicit team routing requires exactly one team ID")
        return self


def _credential(raw):
    if isinstance(raw, NorthflankAPITokenCredential): raw = raw.model_dump(mode="json")
    if isinstance(raw, dict): raw = strip_non_blob_keys(raw)
    if not isinstance(raw, dict) or raw.get("credential_type") != FAMILY or raw.get("target") not in {"token_default", "team"} or set(raw) - {"credential_type", "api_token", "target", "team_id"}:
        raise ValueError("Select the authoritative Northflank token family and explicit routing context")
    try: return NorthflankAPITokenCredential.model_validate(raw)
    except Exception: raise ValueError("Northflank issued token or team routing shape is unsupported") from None


def _stored(raw): return _credential(raw).model_dump(mode="json")


def _op(value, title, category): return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": category, "x-is-trigger": False})
def _pick(name, parent=None): return Field(..., title=name.replace("_", " ").title(), json_schema_extra={"x-resource-type": name, "x-dynamic-options": {"field_name": name, "allow_custom": True, **({"depends_on": parent} if parent else {})}})


class _Config(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _Page(_Config):
    per_page: int = Field(50, strict=True, ge=1, le=100, title="Results in This Page")
    page: int = Field(1, strict=True, ge=1, le=1000000, title="Page Number", description="Use page or cursor; cursor is preferred for subsequent pages.")
    cursor: str | None = Field(None, title="Provider Cursor")
    @field_validator("cursor", mode="before")
    @classmethod
    def cursor_value(cls, value): return _uid(value) if value is not None else None
    @model_validator(mode="after")
    def page_mode(self):
        if self.cursor is not None and self.page != 1: raise ValueError("Use a cursor or a page number, not both")
        return self


class _Project(_Config):
    project_id: str = _pick("project_id")
    @field_validator("project_id", mode="before")
    @classmethod
    def project(cls, value): return _id(value)


class NorthflankCheckConnectionConfig(_Config):
    operation: Literal["check_connection"] = _op("check_connection", "Check Protected Project Reachability", "Connection")


class NorthflankListRegionsConfig(_Config):
    operation: Literal["list_regions"] = _op("list_regions", "List Available Regions", "Regions")


class NorthflankListProjectsConfig(_Page):
    operation: Literal["list_projects"] = _op("list_projects", "List Project Metadata Page", "Projects")


class NorthflankGetProjectConfig(_Project):
    operation: Literal["get_project"] = _op("get_project", "Get Project Metadata and Workload Counts", "Projects")


class NorthflankCreateProjectConfig(_Config):
    operation: Literal["create_project"] = _op("create_project", "Create Empty Project", "Projects")
    name: str = Field(..., min_length=3, max_length=39, title="Project Name")
    region: str = _pick("region")
    description: str | None = Field(None, max_length=200, title="Description")
    color: str | None = Field(None, title="Display Color", pattern=r"^#([a-fA-F0-9]{6}|[a-fA-F0-9]{3})$")
    @field_validator("name", mode="before")
    @classmethod
    def name_value(cls, value):
        value = _text(value, 39)
        if not re.fullmatch(r"[a-zA-Z]((-|\s)?[a-zA-Z0-9]+((-|\s)[a-zA-Z0-9]+)*)?", value): raise ValueError("Use the documented Northflank project name")
        return value
    @field_validator("region", mode="before")
    @classmethod
    def region_value(cls, value): return _id(value)
    @field_validator("description", mode="before")
    @classmethod
    def description_value(cls, value): return _description(value) if value is not None else None


class _EmptyProject(_Project):
    expected_project_uid: str = Field(..., title="Expected Permanent Project UID", description="Read it from Get Project before writing; prevents an ID reused by a different project.")
    confirm_owned_empty_project: Literal[True] = Field(..., title="This Is an Owned Disposable Empty Project", description="Only disposable projects. Visible workload checks supplement the server's atomic nonempty deletion guard.")
    @field_validator("expected_project_uid", mode="before")
    @classmethod
    def expected_uid(cls, value): return _uid(value)
    @field_validator("confirm_owned_empty_project", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True: raise ValueError("Explicitly confirm the owned disposable empty project")
        return value


class NorthflankUpdateProjectConfig(_EmptyProject):
    operation: Literal["update_project"] = _op("update_project", "Update Empty Project Description or Color", "Projects")
    description: str | None = Field(None, max_length=200, title="New Description")
    color: str | None = Field(None, title="New Display Color", pattern=r"^#([a-fA-F0-9]{6}|[a-fA-F0-9]{3})$")
    @field_validator("description", mode="before")
    @classmethod
    def description_value(cls, value): return _description(value) if value is not None else None
    @model_validator(mode="after")
    def nonempty_patch(self):
        if self.description is None and self.color is None: raise ValueError("Provide a description or color")
        return self


class NorthflankDeleteProjectConfig(_EmptyProject):
    operation: Literal["delete_project"] = _op("delete_project", "Delete Empty Project (Refuse All Child Deletion)", "Projects")


class NorthflankListServicesConfig(_Project, _Page):
    operation: Literal["list_services"] = _op("list_services", "List Service Metadata and Status Page", "Services")


class _Service(_Project):
    service_id: str = _pick("service_id", "project_id")
    @field_validator("service_id", mode="before")
    @classmethod
    def service(cls, value): return _id(value)


class NorthflankGetServiceConfig(_Service):
    operation: Literal["get_service"] = _op("get_service", "Get Service Metadata and Status", "Services")


class NorthflankListDeploymentsConfig(_Service, _Page):
    operation: Literal["list_deployments"] = _op("list_deployments", "List Deployment Metadata Page", "Deployments")
    release_type: Literal["stable", "canary"] | None = Field(None, title="Current Release Role", description="Optional current rollout role, not the original deployment role.")


class NorthflankListJobsConfig(_Project, _Page):
    operation: Literal["list_jobs"] = _op("list_jobs", "List Job Metadata Page", "Jobs")


class _Job(_Project):
    job_id: str = _pick("job_id", "project_id")
    @field_validator("job_id", mode="before")
    @classmethod
    def job(cls, value): return _id(value)


class NorthflankGetJobConfig(_Job):
    operation: Literal["get_job"] = _op("get_job", "Get Job Metadata", "Jobs")


class NorthflankListRunsConfig(_Job, _Page):
    operation: Literal["list_runs"] = _op("list_runs", "List Existing Job Run Status Page", "Job Runs")


class NorthflankGetRunConfig(_Job):
    operation: Literal["get_run"] = _op("get_run", "Get Existing Job Run Status", "Job Runs")
    run_id: str = _pick("run_id", "job_id")
    @field_validator("run_id", mode="before")
    @classmethod
    def run(cls, value): return _id(value)


class NorthflankListAddonsConfig(_Project, _Page):
    operation: Literal["list_addons"] = _op("list_addons", "List Addon Metadata and Status Page", "Addons")


class NorthflankGetAddonConfig(_Project):
    operation: Literal["get_addon"] = _op("get_addon", "Get Addon Metadata and Status", "Addons")
    addon_id: str = _pick("addon_id", "project_id")
    @field_validator("addon_id", mode="before")
    @classmethod
    def addon(cls, value): return _id(value)


NorthflankOperation = Annotated[Union[NorthflankCheckConnectionConfig, NorthflankListRegionsConfig, NorthflankListProjectsConfig, NorthflankGetProjectConfig, NorthflankCreateProjectConfig, NorthflankUpdateProjectConfig, NorthflankDeleteProjectConfig, NorthflankListServicesConfig, NorthflankGetServiceConfig, NorthflankListDeploymentsConfig, NorthflankListJobsConfig, NorthflankGetJobConfig, NorthflankListRunsConfig, NorthflankGetRunConfig, NorthflankListAddonsConfig, NorthflankGetAddonConfig], Field(discriminator="operation")]


class NorthflankNodeConfig(NodeConfig[NorthflankOperation, NorthflankAPITokenCredential]):
    model_config = ConfigDict(title="Northflank Node Configuration", hide_input_in_errors=True)


def _object(value):
    if not isinstance(value, dict): raise ValueError("Northflank returned an unsupported object")
    return value


def _metadata(raw, kind, parent=None, *, mutation=False):
    raw = _object(raw)
    out = {"id": _id(raw.get("id"))}
    if kind != "run" and kind != "deployment":
        out["name"] = _text(raw.get("name"), 200)
        if not mutation or raw.get("uid") is not None: out["uid"] = _uid(raw.get("uid"))
    if parent is not None:
        if raw.get("projectId") is not None and raw["projectId"] != parent: raise ValueError("Northflank returned a resource from a different project")
        out["project_id"] = parent  # Proven by the exact parent-scoped route, not a guessed response field.
    for name in ("createdAt", "updatedAt", "description", "serviceType", "jobType", "stageId"):
        if raw.get(name) is not None: out[name] = _text(raw[name], 256, empty=name == "description")
    for name in ("disabledCI", "disabledCD", "suspended"):
        if raw.get(name) is not None:
            if type(raw[name]) is not bool: raise ValueError()
            out[name] = raw[name]
    if kind == "project":
        deployment = raw.get("deployment")
        if deployment is not None: out["region"] = _id(_object(deployment).get("region"))
        elif raw.get("region") is not None: out["region"] = _id(raw["region"])
        if raw.get("color") is not None:
            if not isinstance(raw["color"], str) or not re.fullmatch(r"#(?:[a-fA-F0-9]{6}|[a-fA-F0-9]{3})", raw["color"]): raise ValueError()
            out["color"] = raw["color"]
    elif kind == "service" and raw.get("status") is not None:
        status = _object(raw["status"])
        out["status"] = {}
        for phase in ("build", "deployment"):
            if status.get(phase) is not None:
                value = _object(status[phase])
                out["status"][phase] = {"status": _text(value.get("status"), 80)}
                for name in ("lastTransitionTime", "reason"):
                    if value.get(name) is not None: out["status"][phase][name] = _text(value[name], 80)
    elif kind == "addon":
        if raw.get("status") is not None: out["status"] = _text(raw["status"], 80)
        if raw.get("spec") is not None: out["addon_type"] = _text(_object(raw["spec"]).get("type"), 80)
    elif kind == "run":
        if raw.get("status") not in {"SUCCESS", "RUNNING", "FAILED"}: raise ValueError()
        out["status"] = raw["status"]
        if type(raw.get("concluded")) is not bool: raise ValueError()
        out["concluded"] = raw["concluded"]
        for name in ("startedAt", "concludedAt"):
            if raw.get(name) is not None: out[name] = _text(raw[name], 80, empty=True)
        for name in ("active", "failed", "succeeded", "backoffLimit", "completions"):
            if type(raw.get(name)) is not int or raw[name] < 0: raise ValueError()
            out[name] = raw[name]
    elif kind == "deployment":
        out["createdAt"] = _text(raw.get("createdAt"), 80)
        if raw.get("name") is not None: out["name"] = _text(raw["name"], 200)
        if raw.get("active") is not None:
            if type(raw["active"]) is not bool: raise ValueError()
            out["active"] = raw["active"]
        if raw.get("releaseType") is not None:
            if raw["releaseType"] not in {"stable", "canary"}: raise ValueError()
            out["releaseType"] = raw["releaseType"]
        if raw.get("instances") is not None:
            if type(raw["instances"]) not in {int, float} or raw["instances"] < 0: raise ValueError()
            out["instances"] = raw["instances"]
    return out


def _rows(data, name, maximum=100):
    rows = _object(data).get(name)
    if not isinstance(rows, list) or len(rows) > maximum or any(not isinstance(row, dict) for row in rows): raise ValueError("Northflank returned an unsupported collection")
    ids = [_id(row.get("id")) for row in rows]
    if len(set(ids)) != len(ids): raise ValueError("Northflank returned duplicate resource IDs")
    return rows


def _page(payload, name, kind, config, parent=None):
    rows = _rows(payload.get("data"), name, config.per_page)
    meta = _object(payload.get("pagination"))
    if type(meta.get("hasNextPage")) is not bool or type(meta.get("count")) not in {int, float} or meta["count"] != len(rows): raise ValueError("Northflank pagination is inconsistent")
    cursor = _uid(meta.get("cursor")) if meta.get("cursor") is not None else None
    if meta["hasNextPage"] and (not rows or cursor is None or cursor == config.cursor): raise ValueError("Northflank pagination did not advance")
    return {"data": [_metadata(row, kind, parent) for row in rows], "count": len(rows), "has_more": meta["hasNextPage"], "next_cursor": cursor if meta["hasNextPage"] else None, "snapshot_stable": False}


def _error(action, message, *, status=None, attempted=False, mutation_attempted=False):
    return {"status": "error", "action": action, "error": message, "executed": attempted,
        **({"http_status": status, "status_code": status} if status is not None else {}),
        "mutation_attempted": mutation_attempted, "mutation_outcome": "unverified" if mutation_attempted else "not_attempted", "_halt_downstream": True}


class _ProviderError(Exception):
    def __init__(self, result): self.result = result


class _Session:
    def __init__(self, raw, action):
        self.raw, self.key, self.action = raw, _credential(raw), action
        self.attempted, self.mutation_attempted, self.status = False, False, None
        self.prefix = "/teams/" + self.key.team_id if self.key.target == "team" else ""
        self.bound_children = {}
    async def request(self, path, *, method="GET", params=None, body=None):
        # Only enumerated read routes and project-only metadata mutations.
        read = re.fullmatch(r"/projects(?:/[A-Za-z0-9_-]+(?:/(?:services|jobs|addons)(?:/[A-Za-z0-9_-]+(?:/(?:deployments|runs)(?:/[A-Za-z0-9_-]+)?)?)?)?)?", path)
        write = (method == "POST" and path == "/projects") or (method in {"PATCH", "DELETE"} and re.fullmatch(r"/projects/[A-Za-z0-9_-]+", path))
        if not ((method == "GET" and (read or path == "/regions")) or write): raise ValueError("Unsupported Northflank route")
        try:
            key = _credential(self.raw)
            self.status = None
            async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
                self.attempted = True
                self.mutation_attempted |= method != "GET"
                async with client.stream(method, BASE + ("" if path == "/regions" else self.prefix) + path, params=params, json=body, headers={"Authorization": "Bearer " + key.api_token, "Accept": "application/json", **({"Content-Type": "application/json"} if body is not None else {})}) as response:
                    self.status = response.status_code
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > MAX_BYTES: raise ValueError()
                        raw.extend(chunk)
            if self.status != 200:
                raise _ProviderError(_error(self.action, "Northflank refused this request; check scoped role permissions or project dependencies. No retry occurred", status=self.status, attempted=True, mutation_attempted=self.mutation_attempted))
            payload = json.loads(raw)
            _object(payload)
            _object(payload.get("data"))
            if any(payload.get(name) is not None for name in ("error", "errors")): raise ValueError()
            return payload
        except _ProviderError: raise
        except (httpx.HTTPError, SSRFError): raise _ProviderError(_error(self.action, "Northflank transport outcome could not be established; no retry occurred", status=self.status, attempted=self.attempted, mutation_attempted=self.mutation_attempted)) from None
    async def project(self, project_id, *, empty=False, expected_uid=None):
        payload = await self.request("/projects/" + _id(project_id))
        raw = payload["data"]
        row = _metadata(raw, "project")
        if row["id"] != project_id or (expected_uid is not None and row["uid"] != expected_uid): raise ValueError("Selected permanent project binding differs")
        counts = {name: len(_rows(raw, name, 10000)) for name in ("services", "jobs", "addons")}
        self.children = {name: {item["id"]: _uid(item.get("uid")) for item in raw[name]} for name in counts}
        if empty and any(counts.values()): raise ValueError("The selected project contains workloads")
        row["workload_counts"] = counts
        return row
    async def resource(self, project_id, collection, resource_id):
        expected_uid = self.children.get(collection, {}).get(resource_id)
        if expected_uid is None: raise ValueError("Selected child is not present in the protected project metadata")
        payload = await self.request(f"/projects/{project_id}/{collection}/{resource_id}")
        row = _metadata(payload["data"], {"services": "service", "jobs": "job", "addons": "addon"}[collection], project_id)
        if row["id"] != resource_id or row["uid"] != expected_uid: raise ValueError("Selected permanent child resource binding differs")
        self.bound_children[(collection, resource_id)] = expected_uid
        return row


class NorthflankNode(WorkflowNode):
    integration_type = "automation-northflank"
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="Northflank project API", proves="reachability")
    edit_examples = ["List Northflank project metadata", "Read service and job run status without secrets", "Create and read back an owned empty project"]
    @classmethod
    def get_config_model(cls): return NorthflankNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: _stored(config_data["credentials"])
            except ValueError as error: raise ConfigValidationError(str(error)) from None
        return super().parse_config(config_data)
    @classmethod
    async def validate_credential_access(cls, credential_data):
        result = await cls._dispatch(_credential(credential_data), NorthflankCheckConnectionConfig())
        if result.get("protected_reachability_verified") is True:
            return {"valid": True}
        return {"valid": False if result.get("status_code") in {401, 403} else None,
                "error": result.get("error", "Northflank protected reachability could not be verified")}
    @classmethod
    async def _dispatch(cls, credential, config):
        session = _Session(credential, config.operation)
        try:
            action = config.operation
            if action == "check_connection":
                payload = await session.request("/projects", params={"per_page": 1, "page": 1})
                _page(payload, "projects", "project", NorthflankListProjectsConfig(per_page=1))
                out = {"data": [], "protected_reachability_verified": True, "principal_identity_proven": False, "routing_context": session.key.target}
            elif action == "list_regions":
                payload = await session.request("/regions")
                out = {"data": [{"id": _id(row["id"]), "name": _text(row.get("name")), "regionName": _text(row.get("regionName"))} for row in _rows(payload["data"], "regions", 500)], "has_more": False, "protected_project_evidence": False}
            elif action == "list_projects":
                payload = await session.request("/projects", params=_paging(config))
                out = _page(payload, "projects", "project", config)
            elif action == "create_project":
                regions = _rows((await session.request("/regions"))["data"], "regions", 500)
                if config.region not in {_id(row["id"]) for row in regions}: raise ValueError("Select a currently published region")
                body = {name: getattr(config, name) for name in ("name", "region", "description", "color") if getattr(config, name) is not None}
                result = _metadata((await session.request("/projects", method="POST", body=body))["data"], "project", mutation=True)
                out = {"data": result, "mutation_outcome": "acknowledged", "readback_required": True, "readback_operation": "get_project"}
            elif action in {"get_project", "update_project", "delete_project"}:
                row = await session.project(config.project_id, empty=action != "get_project", expected_uid=getattr(config, "expected_project_uid", None))
                if action == "get_project": out = {"data": row}
                elif action == "update_project":
                    body = {name: getattr(config, name) for name in ("description", "color") if getattr(config, name) is not None}
                    result = _metadata((await session.request("/projects/" + config.project_id, method="PATCH", body=body))["data"], "project", mutation=True)
                    if result["id"] != config.project_id: raise ValueError()
                    out = {"data": result, "mutation_outcome": "acknowledged", "readback_required": True, "readback_operation": "get_project"}
                else:
                    payload = await session.request("/projects/" + config.project_id, method="DELETE", params={"delete_child_objects": "false"})
                    if payload["data"] != {}: raise ValueError("Unexpected project deletion acknowledgment")
                    out = {"data": {}, "project_id": config.project_id, "expected_project_uid": config.expected_project_uid, "mutation_outcome": "acknowledged", "readback_required": True, "readback_operation": "get_project", "expected_readback_http_status": 404}
            else:
                project = await session.project(config.project_id)
                if action in {"list_services", "list_jobs", "list_addons"}:
                    name = {"list_services": "services", "list_jobs": "jobs", "list_addons": "addons"}[action]
                    kind = {"services": "service", "jobs": "job", "addons": "addon"}[name]
                    out = _page(await session.request(f"/projects/{config.project_id}/{name}", params=_paging(config)), name, kind, config, config.project_id)
                elif action in {"get_service", "get_job", "get_addon"}:
                    collection, field = {"get_service": ("services", "service_id"), "get_job": ("jobs", "job_id"), "get_addon": ("addons", "addon_id")}[action]
                    out = {"data": await session.resource(config.project_id, collection, getattr(config, field))}
                elif action == "list_deployments":
                    service = await session.resource(config.project_id, "services", config.service_id)
                    if service.get("serviceType") == "build": raise ValueError("A build-only service has no deployments")
                    params = _paging(config)
                    if config.release_type is not None: params["releaseType"] = config.release_type
                    out = _page(await session.request(f"/projects/{config.project_id}/services/{config.service_id}/deployments", params=params), "deployments", "deployment", config, config.project_id)
                    out["service_id"] = config.service_id
                else:
                    await session.resource(config.project_id, "jobs", config.job_id)
                    path = f"/projects/{config.project_id}/jobs/{config.job_id}/runs"
                    if action == "list_runs": out = _page(await session.request(path, params=_paging(config)), "runs", "run", config, config.project_id)
                    else:
                        row = _metadata((await session.request(path + "/" + config.run_id))["data"], "run", config.project_id)
                        if row["id"] != config.run_id: raise ValueError()
                        out = {"data": row}
                    out["job_id"] = config.job_id
                out.update(project_id=config.project_id, project_uid=project["uid"])
                # Discard a child response if the project ID was reused during
                # the read. This is not an atomic snapshot of all workloads.
                await session.project(config.project_id, expected_uid=project["uid"])
                if any(session.children[collection].get(resource_id) != uid for (collection, resource_id), uid in session.bound_children.items()): raise ValueError("Selected child changed during the scoped read")
            encoded = json.dumps(out, ensure_ascii=False, allow_nan=False)
            if session.key.api_token in encoded: raise ValueError()
            return {"status": "success", "action": action, "executed": True, "http_status": session.status, "mutation_attempted": session.mutation_attempted, **out}
        except _ProviderError as error: return error.result
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError): return _error(config.operation, "Northflank selected parent or bounded response could not be established; reconcile any attempted mutation before repeating", status=session.status, attempted=session.attempted, mutation_attempted=session.mutation_attempted)
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"project_id", "service_id", "job_id", "addon_id", "run_id", "region"}: raise ValueError("Unsupported Northflank selector")
        key = _credential(credential_data)
        context = context or {}
        if search is not None: _text(search, 100, empty=True)
        scope = {"field": field_name, "target": key.target, "team_id": key.team_id}
        if field_name in {"service_id", "job_id", "addon_id", "run_id"}: scope["project_id"] = _id(context.get("project_id"))
        if field_name == "run_id": scope["job_id"] = _id(context.get("job_id"))
        cursor = None
        if page_token is not None:
            if field_name == "region" or not isinstance(page_token, str) or len(page_token) > 768: raise ValueError("Unsupported Northflank page token")
            try: page = json.loads(page_token)
            except (TypeError, ValueError): raise ValueError("Northflank page token is malformed") from None
            if not isinstance(page, dict) or set(page) != {"scope", "cursor"} or page["scope"] != scope: raise ValueError("Northflank page token differs from current parent or routing context")
            cursor = _uid(page["cursor"])
        models = {"project_id": NorthflankListProjectsConfig, "service_id": NorthflankListServicesConfig, "job_id": NorthflankListJobsConfig, "addon_id": NorthflankListAddonsConfig, "run_id": NorthflankListRunsConfig, "region": NorthflankListRegionsConfig}
        values = {name: scope[name] for name in ("project_id", "job_id") if name in scope}
        if field_name != "region": values.update(per_page=100, cursor=cursor)
        result = await cls._dispatch(credential_data, models[field_name](**values))
        if result.get("status") != "success": raise ValueError(result["error"])
        options = [{"value": row["id"], "label": row.get("name", row["id"]), "metadata": {**scope, **({"uid": row["uid"]} if "uid" in row else {})}} for row in result["data"]]
        if search: options = [row for row in options if search.casefold() in row["label"].casefold()]
        more = result.get("has_more", False)
        return {"options": options, "has_more": more, "next_page_token": json.dumps({"scope": scope, "cursor": result["next_cursor"]}, sort_keys=True, separators=(",", ":")) if more else None}
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        initial = _credential(self.node_data.get("credentials") if self.node_data.get("credentials") is not None else self.config.credentials)
        return await self._dispatch(initial, self.config.config)


def _paging(config):
    return {"per_page": config.per_page, **({"cursor": config.cursor} if config.cursor is not None else {"page": config.page})}
