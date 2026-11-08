"""Humanitec organization, application and orchestration metadata.

Only application creation without an environment and explicit name updates
can write. No deployments, pipeline runs, secrets, provisioning or deletes.
"""
from __future__ import annotations
import base64
import contextvars
from dataclasses import asdict, dataclass
from uuid import UUID
from datetime import datetime
import hashlib
import hmac
import json
import logging
import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import parse_qsl, urljoin, urlsplit
from pydantic import BaseModel, ConfigDict, Discriminator, Field, StringConstraints, TypeAdapter, field_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.humanitec import HUMANITEC_SCOPES
from utils.ssrf import assert_exact_url_origin, guarded_async_client

from repositories.credentials import credential_access_predicate
from repositories.organization import OrgRepo


class HumanitecAuthorityRepo:
    """Read the saved credential anchor under the shared access predicate."""
    def __init__(self, pool):
        self.pool = pool

    async def organization(self, caller_id):
        async with self.pool.acquire() as conn:
            return await OrgRepo(self.pool).get_primary_org_id(conn, caller_id)

    async def load(self, credential_id, principal_id, organization_id):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(f"""
                SELECT c.credential, c.owner_id, c.credential_type, c.token_version,
                       c.updated_at, c.revoked_at
                FROM credentials c
                WHERE c.id = $1::uuid AND {credential_access_predicate()}
            """, credential_id, principal_id, organization_id)


CURRENT_ORGANIZATION = object()


@dataclass(frozen=True)
class HumanitecCredentialAnchor:
    credential_id: str
    caller_id: str
    principal_id: str
    organization_id: str | None
    current_organization: bool
    workflow_id: str | None
    owner_id: str
    credential_type: str
    token_version: int


class HumanitecCredentialStore:
    def __init__(self, pool, user_id, credential_id, *, validate,
                 organization_id=CURRENT_ORGANIZATION, workflow_id=None):
        self.pool = pool
        self.user_id = str(UUID(str(user_id)))
        self.credential_id = str(UUID(str(credential_id)))
        self.organization_id = organization_id
        self.workflow_id = str(UUID(str(workflow_id))) if workflow_id else None
        self.validate = validate
        self.current = None

    async def load(self):
        from utils.credentials import (
            resolve_credential_with_owner_fallback, get_workflow_owner_id,
            is_credential_authorized_for_workflow, credential_lender,
        )
        from utils.encryption import get_encryption
        if self.pool is None:
            from utils.database_pool import get_native_pool
            self.pool = get_native_pool()
        self.current = None
        repo = HumanitecAuthorityRepo(self.pool)
        current_org = self.organization_id is CURRENT_ORGANIZATION
        org = await repo.organization(self.user_id) if current_org else self.organization_id
        principal = self.user_id
        row = await repo.load(self.credential_id, principal, org)
        if row is None and self.workflow_id:
            owner = await get_workflow_owner_id(self.pool, self.workflow_id)
            if owner and owner != self.user_id and await is_credential_authorized_for_workflow(self.pool, self.workflow_id, self.credential_id):
                principal = owner
                row = await repo.load(self.credential_id, principal, org)
        if row is None and self.workflow_id:
            lender = await credential_lender(self.pool, self.workflow_id, self.credential_id)
            if lender and lender != self.user_id:
                principal = lender
                row = await repo.load(self.credential_id, principal, org)
        if (row is None or row['revoked_at'] is not None
                or row['credential_type'] != 'humanitec_service_token'
                or type(row['token_version']) is not int or row['token_version'] < 1):
            raise ValueError('Humanitec saved credential unavailable under current authority')
        resolved = await resolve_credential_with_owner_fallback(
            self.credential_id, self.user_id, self.pool, org_id=org, workflow_id=self.workflow_id,
        )
        if resolved is None:
            raise ValueError('Humanitec saved credential unavailable under current authority')
        data = get_encryption().decrypt_credential(row['credential'])
        data['credential_type'] = row['credential_type']
        data = self.validate(data)
        if data != self.validate(resolved):
            raise ValueError('Humanitec saved credential changed during resolution')
        self.current = HumanitecCredentialAnchor(
            self.credential_id, self.user_id, str(principal), org, current_org,
            self.workflow_id, str(row['owner_id']), row['credential_type'], row['token_version'],
        )
        return {**data, 'token_version': row['token_version']}


ORIGIN = "https://api.humanitec.io"
MAX_JSON = 2 * 1024 * 1024
MAX_COLLECTION = 1000
TENANT_ID = Annotated[str, StringConstraints(pattern=r"^[a-z0-9](?:-?[a-z0-9]+)+$", max_length=50)]
OPAQUE_ID = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
WRITES = {"create_application", "rename_application", "rename_environment"}
_PRIVATE = contextvars.ContextVar("humanitec_private_transport", default=False)

class _PrivateFilter(logging.Filter):
    def filter(self, record): return not _PRIVATE.get()

for _name in ("httpx", "httpcore", "httpcore.connection", "httpcore.connection_pool", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks_proxy"):
    logging.getLogger(_name).addFilter(_PrivateFilter())

class HumanitecDenied(ValueError): pass
class HumanitecUnavailable(ValueError): pass
class _AuthorityChanged(HumanitecUnavailable): pass

def _text(value, maximum=256, *, empty=False):
    if not isinstance(value, str) or not (0 if empty else 1) <= len(value) <= maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Supply bounded Humanitec text without controls.")
    return value

def _id(value, *, tenant=False):
    pattern = r"[a-z0-9](?:-?[a-z0-9]+)+" if tenant else r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}"
    if not isinstance(value, str) or not re.fullmatch(pattern, value) or (tenant and len(value) > 50):
        raise HumanitecUnavailable("Humanitec resource identifiers are malformed.")
    return value

def _dates(raw, output, names):
    for name in names:
        value = raw.get(name)
        if value is not None:
            try:
                _text(value, 64)
                if datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is None: raise ValueError()
            except Exception: raise HumanitecUnavailable("Humanitec returned a malformed metadata timestamp.") from None
            output[name] = value

class HumanitecServiceTokenCredential(BaseModel):
    model_config = ConfigDict(title="Humanitec Service User Token", extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://developer.humanitec.com/platform-orchestrator/docs/platform-orchestrator/security/authentication/"})
    credential_type: Literal["humanitec_service_token"] = Field("humanitec_service_token", json_schema_extra={"ui:hidden": True})
    service_token: str = Field(..., repr=False, json_schema_extra={"ui:widget": "password"}, description="Already issued service-user API token; sent only as Bearer to api.humanitec.io. No browser login, OAuth app, refresh or token mint is configured.")
    organization_id: TENANT_ID = Field(..., description="Exact existing Humanitec organization ID. All API paths and saved-authority checks remain scoped to this organization.")
    allow_metadata_writes: bool = Field(False, strict=True, description="Off by default. Allows explicitly confirmed app creation without an environment and app/environment name changes. Notifications/automation effects are not assumed suppressed; irreversible cascading deletes are omitted.")
    @field_validator("service_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 32768 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply an issued Humanitec service token without whitespace.")
        return value

def _credential(value):
    if isinstance(value, HumanitecServiceTokenCredential): return value
    if not isinstance(value, dict) or value.get("credential_type") != "humanitec_service_token":
        raise ValueError("Attach the native Humanitec service-user token family.")
    try: return HumanitecServiceTokenCredential.model_validate({key: item for key, item in value.items() if key not in ("token_version", "updated_at")})
    except Exception: raise ValueError("Check the native Humanitec token, organization and current metadata policy.") from None

class _SavedCredential(dict):
    def __init__(self, data, store): super().__init__(data); self.store = store

def _op(value, label, category="Metadata"):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})

def _selector(kind, parents=()):
    return {"x-resource-type": "humanitec_" + kind, "x-dynamic-options": {"field_name": kind + "_id", "searchable": True, "allow_custom": True, **({"depends_on": list(parents)} if parents else {})}}

class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    @field_validator("name", "expected_name", "search", mode="before", check_fields=False)
    @classmethod
    def text(cls, value, info): return _text(value, 256 if info.field_name != "search" else 128, empty=info.field_name == "search")
    @field_validator("metadata_confirmed", mode="before", check_fields=False)
    @classmethod
    def confirmation(cls, value):
        if value is not True: raise ValueError("Metadata confirmation must be Boolean true.")
        return value

class _Page(_Config):
    per_page: int = Field(25, strict=True, ge=1, le=100)
    page_token: Optional[str] = Field(None, max_length=8192, description="Native continuation bound to current saved authority, organization, parents and filters. Never a provider URL.")
    search: str = Field("", max_length=128, description="Native label filter; pipeline searches inspect the current provider page only.")
class _App(_Config):
    app_id: TENANT_ID = Field(..., json_schema_extra=_selector("app"))
class _Environment(_App):
    environment_id: TENANT_ID = Field(..., json_schema_extra=_selector("environment", ("app_id",)))
class _Pipeline(_App):
    pipeline_id: OPAQUE_ID = Field(..., json_schema_extra=_selector("pipeline", ("app_id",)))
class HumanitecTestConfig(_Config):
    operation: Literal["test_connection"] = _op("test_connection", "Test Current Token and Organization", "Connection")
class HumanitecOrganizationConfig(_Config):
    operation: Literal["get_organization"] = _op("get_organization", "Get Selected Organization")
class HumanitecApplicationsConfig(_Page):
    operation: Literal["list_applications"] = _op("list_applications", "List Applications")
class HumanitecApplicationConfig(_App):
    operation: Literal["get_application"] = _op("get_application", "Get Application Metadata")
class HumanitecEnvironmentTypesConfig(_Page):
    operation: Literal["list_environment_types"] = _op("list_environment_types", "List Environment Type Metadata")
class HumanitecEnvironmentsConfig(_App, _Page):
    operation: Literal["list_environments"] = _op("list_environments", "List Application Environments")
class HumanitecEnvironmentConfig(_Environment):
    operation: Literal["get_environment"] = _op("get_environment", "Get Environment Metadata")
class HumanitecDeploymentsConfig(_Environment, _Page):
    operation: Literal["list_deployments"] = _op("list_deployments", "List Observed Deployment Statuses")
class HumanitecDeploymentConfig(_Environment):
    operation: Literal["get_deployment"] = _op("get_deployment", "Get Observed Deployment Status")
    deployment_id: OPAQUE_ID = Field(..., json_schema_extra=_selector("deployment", ("app_id", "environment_id")))
class HumanitecPipelinesConfig(_App, _Page):
    operation: Literal["list_pipelines"] = _op("list_pipelines", "List Pipeline Metadata")
    trigger_type: Optional[str] = Field(None, pattern=r"^[a-z][a-z0-9_]{0,63}$", description="Optional documented trigger filter. Does not trigger or run a pipeline.")
class HumanitecPipelineConfig(_Pipeline):
    operation: Literal["get_pipeline"] = _op("get_pipeline", "Get Current Pipeline Metadata")
class HumanitecRunsConfig(_Pipeline, _Page):
    operation: Literal["list_pipeline_runs"] = _op("list_pipeline_runs", "List Observed Pipeline Run Statuses")
    environment_id: Optional[TENANT_ID] = Field(None, json_schema_extra=_selector("environment", ("app_id",)))
    status_filters: list[Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]] = Field(default_factory=list, max_length=8, description="Documented repeated status filter. Provider states are not invented or used to execute runs.")
    completed: Optional[bool] = Field(None, strict=True, description="Optional provider completion filter; observation does not execute a run.")
    @field_validator("status_filters")
    @classmethod
    def unique(cls, values):
        if len(set(values)) != len(values): raise ValueError("Use unique Humanitec status filters.")
        return values
class HumanitecRunConfig(_Pipeline):
    operation: Literal["get_pipeline_run"] = _op("get_pipeline_run", "Get Observed Pipeline Run Metadata")
    run_id: OPAQUE_ID = Field(..., json_schema_extra=_selector("run", ("app_id", "pipeline_id")))
class HumanitecCreateApplicationConfig(_Config):
    operation: Literal["create_application"] = _op("create_application", "Create Application Without Environment", "Metadata Writes")
    app_id: TENANT_ID = Field(..., description="New application ID; no initial environment, deployment or provisioning is requested. This node provides no cascading deletion or cleanup action.")
    name: str = Field(..., min_length=1, max_length=256)
    metadata_confirmed: Literal[True] = Field(..., description="Explicitly confirm this provider metadata write.")
class HumanitecRenameApplicationConfig(_App):
    operation: Literal["rename_application"] = _op("rename_application", "Rename Application", "Metadata Writes")
    name: str = Field(..., min_length=1, max_length=256)
    expected_name: str = Field(..., min_length=1, max_length=256, description="Must match the immediately observed current name. Vendor atomic compare-and-swap is not claimed.")
    metadata_confirmed: Literal[True] = Field(...)
class HumanitecRenameEnvironmentConfig(_Environment):
    operation: Literal["rename_environment"] = _op("rename_environment", "Rename Environment", "Metadata Writes")
    name: str = Field(..., min_length=1, max_length=256)
    expected_name: str = Field(..., min_length=1, max_length=256)
    metadata_confirmed: Literal[True] = Field(...)

HumanitecOperation = Annotated[Union[HumanitecTestConfig, HumanitecOrganizationConfig, HumanitecApplicationsConfig, HumanitecApplicationConfig, HumanitecEnvironmentTypesConfig, HumanitecEnvironmentsConfig, HumanitecEnvironmentConfig, HumanitecDeploymentsConfig, HumanitecDeploymentConfig, HumanitecPipelinesConfig, HumanitecPipelineConfig, HumanitecRunsConfig, HumanitecRunConfig, HumanitecCreateApplicationConfig, HumanitecRenameApplicationConfig, HumanitecRenameEnvironmentConfig], Discriminator("operation")]
class HumanitecNodeConfig(NodeConfig[HumanitecOperation, HumanitecServiceTokenCredential]): pass

def _row(raw):
    if not isinstance(raw, dict): raise HumanitecUnavailable("Humanitec metadata response is malformed.")
    return raw

def _environment(raw, selected=None, *, full=True):
    raw = _row(raw)
    result = {"id": _id(raw.get("id"), tenant=True), "name": _text(raw.get("name")), "type": _text(raw.get("type"), 128)}
    if selected is not None and result["id"] != selected: raise HumanitecDenied("Humanitec returned a different selected environment.")
    if full:
        if raw.get("status") not in ("active", "deleting"): raise HumanitecUnavailable("Humanitec environment status is malformed.")
        result["status"] = raw["status"]
        _dates(raw, result, ("created_at", "status_changed_at"))
    return result

def _application(raw, org, selected=None):
    raw = _row(raw)
    if "org_id" in raw and raw["org_id"] != org: raise HumanitecDenied("Humanitec application belongs to a different organization.")
    result = {"id": _id(raw.get("id"), tenant=True), "name": _text(raw.get("name")), "organization_id": org}
    if selected is not None and result["id"] != selected: raise HumanitecDenied("Humanitec returned a different selected application.")
    # The published API sample omits org_id and lifecycle status and uses a
    # singleton environment object; the operator guide uses an environment array.
    # Keep absent lifecycle metadata absent, while rejecting conflicting values.
    if "status" in raw:
        if raw["status"] not in ("active", "deleting"):
            raise HumanitecUnavailable("Humanitec application status is malformed.")
        result["status"] = raw["status"]
    envs = raw.get("envs")
    if isinstance(envs, dict): envs = [envs]
    if not isinstance(envs, list) or len(envs) > MAX_COLLECTION: raise HumanitecUnavailable("Humanitec application environment metadata exceeds its bound or is malformed.")
    result["environments"] = [_environment(item, full=False) for item in envs]
    if len({row["id"] for row in result["environments"]}) != len(envs): raise HumanitecUnavailable("Humanitec duplicated environment metadata.")
    _dates(raw, result, ("created_at", "status_changed_at"))
    return result

def _deployment(raw, env, selected=None):
    raw = _row(raw)
    if raw.get("env_id") != env: raise HumanitecDenied("Humanitec deployment belongs to a different environment.")
    result = {"id": _id(raw.get("id")), "environment_id": env, "status": _text(raw.get("status"), 64)}
    if result["status"] not in ("pending", "in progress", "succeeded", "failed"): raise HumanitecUnavailable("Humanitec returned an unrecognized deployment status.")
    if selected is not None and result["id"] != selected: raise HumanitecDenied("Humanitec returned a different selected deployment.")
    _dates(raw, result, ("created_at", "status_changed_at"))
    return result

def _pipeline(raw, org, app, selected=None):
    raw = _row(raw)
    if raw.get("org_id") != org or raw.get("app_id") != app: raise HumanitecDenied("Humanitec pipeline belongs to a different organization or application.")
    result = {"id": _id(raw.get("id")), "name": _text(raw.get("name")), "organization_id": org, "app_id": app, "status": _text(raw.get("status"), 64), "version": _id(raw.get("version"))}
    if selected is not None and result["id"] != selected: raise HumanitecDenied("Humanitec returned a different selected pipeline.")
    triggers = raw.get("trigger_types")
    if not isinstance(triggers, list) or len(triggers) > 32: raise HumanitecUnavailable("Humanitec pipeline trigger metadata is malformed.")
    result["trigger_types"] = [_text(item, 64) for item in triggers]
    _dates(raw, result, ("created_at",))
    return result

def _run(raw, org, app, pipeline, selected=None, env=None):
    raw = _row(raw)
    if raw.get("org_id") != org or raw.get("app_id") != app or raw.get("pipeline_id") != pipeline: raise HumanitecDenied("Humanitec run belongs to a different organization, application or pipeline.")
    result = {"id": _id(raw.get("id")), "organization_id": org, "app_id": app, "pipeline_id": pipeline, "pipeline_version": _id(raw.get("pipeline_version")), "status": _text(raw.get("status"), 64)}
    if selected is not None and result["id"] != selected: raise HumanitecDenied("Humanitec returned a different selected run.")
    envs = raw.get("env_ids")
    if not isinstance(envs, list) or len(envs) > 100: raise HumanitecUnavailable("Humanitec run environment metadata is malformed.")
    result["environment_ids"] = [_id(item, tenant=True) for item in envs]
    if len(set(result["environment_ids"])) != len(envs) or (env and env not in envs): raise HumanitecDenied("Humanitec run does not match its selected environment filter.")
    _dates(raw, result, ("created_at", "executing_at", "completed_at", "cancellation_requested_at"))
    return result

def _ticket(credential, authority, config, *, payload=None, token=None):
    scope = hashlib.sha256(json.dumps([credential.model_dump(), asdict(authority) if authority else None, config.model_dump(exclude={"page_token"})], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if token is None:
        body = base64.urlsafe_b64encode(json.dumps({"v": 1, "scope": scope, "payload": payload}, separators=(",", ":")).encode()).decode().rstrip("=")
        result = body + "." + hmac.new(credential.service_token.encode(), body.encode(), hashlib.sha256).hexdigest()
        if len(result) > 8192: raise HumanitecUnavailable("Humanitec continuation exceeds its native bound.")
        return result
    try:
        if not isinstance(token, str) or len(token) > 8192: raise ValueError()
        body, signature = token.rsplit(".", 1)
        if not hmac.compare_digest(signature, hmac.new(credential.service_token.encode(), body.encode(), hashlib.sha256).hexdigest()): raise ValueError()
        parsed = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if not isinstance(parsed, dict) or set(parsed) != {"v", "scope", "payload"} or type(parsed["v"]) is not int or parsed["v"] != 1 or parsed["scope"] != scope or not isinstance(parsed["payload"], dict): raise ValueError()
        return parsed["payload"]
    except Exception: raise ValueError("Humanitec continuation does not match the current saved authority, organization, parents and filters.") from None

def _next_page(response, path, params):
    header = response.headers.get("link")
    if header is None: return None
    if len(header) > 8192 or any(ord(c) < 32 or ord(c) == 127 for c in header): raise HumanitecUnavailable("Humanitec pagination metadata is malformed.")
    for member in re.split(r",\s*(?=<)", header):
        if not re.fullmatch(r'\s*<[^<>]+>\s*(?:;\s*[A-Za-z][A-Za-z0-9_-]*\s*=\s*(?:"[^"]*"|[^\s;,]+)\s*)+', member): raise HumanitecUnavailable("Humanitec Link syntax is malformed.")
    if len(re.findall(r'rel\s*=\s*["\']?next\b', header, re.I)) > 1: raise HumanitecUnavailable("Humanitec duplicated its next-page relation.")
    link = response.links.get("next")
    if not link and re.search(r'rel\s*=\s*["\']?next\b', header, re.I): raise HumanitecUnavailable("Humanitec next-page relation could not be parsed.")
    if not link: return None
    url = urlsplit(urljoin(ORIGIN + path, link.get("url", "")))
    if url.scheme != "https" or url.netloc != "api.humanitec.io" or url.path != path or url.fragment: raise HumanitecUnavailable("Humanitec next-page origin or parent changed; no URL is followed.")
    values = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True)
    page = [value for name, value in values if name == "page"]
    allowed = {key for key, _ in params} | {"page"}
    if len(page) != 1 or any(key not in allowed for key, _ in values): raise HumanitecUnavailable("Humanitec continuation parameters are malformed.")
    for key in {key for key, _ in values} - {"page"}:
        if sorted(value for name, value in values if name == key) != sorted(str(value) for name, value in params if name == key): raise HumanitecUnavailable("Humanitec continuation changed its current query filters.")
    return _text(page[0], 512)

class HumanitecNode(WorkflowNode):
    integration_type = "automation-humanitec"
    workflow_credential_refresh = True
    scope_registry = HUMANITEC_SCOPES
    connection_evidence = ConnectionEvidence(noun="Humanitec organization", identity_operation="test_connection", proves="account", label_keys=("organization_name",), identity_keys=("organization_name", "organization_id"))
    edit_examples = ["List applications in my Humanitec organization", "Read deployment status without deploying", "Inspect pipeline run metadata without inputs or secrets", "Rename an application after explicit confirmation"]
    @classmethod
    def get_config_model(cls): return HumanitecNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        data = config_data
        credential = _credential(data["credentials"]) if isinstance(data, dict) and data.get("credentials") is not None else None
        try:
            view = runtime_config_view(data, HumanitecNodeConfig)
            if credential is not None: view["credentials"] = credential.model_dump()
            if isinstance(view.get("config"), dict):
                view["config"] = {key: item for key, item in view["config"].items() if not key.endswith("__label") and key not in ("_settings", "agent_tool_operations")}
                if not view["config"]: view.pop("config")
            return TypeAdapter(HumanitecNodeConfig).validate_python(view)
        except Exception: raise ConfigValidationError("Check the native Humanitec operation, current credential and typed fields.") from None
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._freshen_for_execution(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)
    @classmethod
    async def _freshen_for_execution(cls, data, **kwargs):
        credential = _credential(data)
        store = HumanitecCredentialStore(kwargs.get("pool"), kwargs.get("user_id"), kwargs["credential_id"], validate=lambda item: _credential(item).model_dump(), organization_id=kwargs.get("organization_id", CURRENT_ORGANIZATION), workflow_id=kwargs.get("workflow_id")) if kwargs.get("credential_id") else data.store if isinstance(data, _SavedCredential) else None
        if not store: return credential.model_dump()
        try: return _SavedCredential(await store.load(), store)
        except Exception:
            raise HumanitecUnavailable("Humanitec saved credential unavailable under current authority.") from None
    @classmethod
    async def validate_credential_access(cls, data):
        # Staging calls this hook with decrypted data, without a saved-row context.
        # Probe only the supplied token/organization; it proves no actor identity.
        try:
            credential = _credential(data)
            raw, _ = await cls._request("GET", "/orgs/" + credential.organization_id, credential=credential)
            raw = _row(raw)
            if raw.get("id") != credential.organization_id:
                raise HumanitecDenied("Humanitec returned a different organization.")
            _text(raw.get("name"))
            return {"valid": True}
        except HumanitecDenied:
            return {"valid": False, "error": "Humanitec refused the token or selected organization permission."}
        except Exception:
            return {"valid": None, "error": "Humanitec organization access could not be verified."}
    @classmethod
    async def _request(cls, method, path, *, credential, params=None, body=None):
        root = "/orgs/" + credential.organization_id
        app = re.escape(root) + r"/apps/[a-z0-9-]{2,50}"
        allowed = (method == "GET" and (path in (root, root + "/apps", root + "/env-types") or any(re.fullmatch(pattern, path) for pattern in (app, app + r"/envs(?:/[a-z0-9-]{2,50}(?:/deploys(?:/[A-Za-z0-9_-]{1,128})?)?)?", app + r"/pipelines(?:/[A-Za-z0-9_-]{1,128}(?:/runs(?:/[A-Za-z0-9_-]{1,128})?)?)?")))) or (method == "POST" and path == root + "/apps") or (method == "PATCH" and any(re.fullmatch(pattern, path) for pattern in (app, app + r"/envs/[a-z0-9-]{2,50}")))
        if not allowed: raise ValueError("Unsupported native Humanitec transport path.")
        if method == "GET" and body is not None: raise ValueError("Humanitec metadata GET has no request body.")
        if method == "POST" and (not isinstance(body, dict) or set(body) != {"id", "name", "skip_environment_creation"} or body["skip_environment_creation"] is not True): raise ValueError("Humanitec app creation must explicitly skip environment creation.")
        if method == "PATCH" and (not isinstance(body, dict) or set(body) != {"name"}): raise ValueError("Only documented Humanitec name updates are supported.")
        query = params or []
        keys = {key for key, _ in query}
        allowed_keys = {"per_page", "page", "trigger"} if path.endswith("/pipelines") else {"per_page", "page", "env", "status", "completed"} if path.endswith("/runs") else set()
        if keys - allowed_keys: raise ValueError("Unsupported native Humanitec metadata query.")
        assert_exact_url_origin(ORIGIN + path, ORIGIN)
        private = _PRIVATE.set(True)
        try:
            async with guarded_async_client( trust_env=False, follow_redirects=False, timeout=25) as client:
                async with client.stream(method, ORIGIN + path, headers={"Authorization": "Bearer " + credential.service_token, "Accept": "application/json", "User-Agent": "NoClick/1.0 (+https://www.noclick.com)"}, params=query, json=body) as response:
                    if response.status_code in (401, 403): raise HumanitecDenied("Humanitec refused the current token or operation permission; raw details withheld.")
                    if response.status_code != (201 if method == "POST" else 200): raise HumanitecUnavailable("Humanitec request could not be verified, including not-visible/conflict/rate/service errors; no retry or raw response disclosure.")
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(content) + len(chunk) > MAX_JSON: raise HumanitecUnavailable("Humanitec exceeded its native response bound.")
                        content.extend(chunk)
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json": raise HumanitecUnavailable("Humanitec returned an unexpected content type.")
                    payload = json.loads(content, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    if not isinstance(payload, (dict, list)) or (isinstance(payload, dict) and any(payload.get(key) not in (None, [], {}) for key in ("error", "errors", "exception"))): raise HumanitecUnavailable("Humanitec returned an error despite HTTP success.")
                    return payload, _next_page(response, path, query) if path.endswith(("/pipelines", "/runs")) else None
        except (HumanitecDenied, HumanitecUnavailable): raise
        except Exception: raise HumanitecUnavailable("Humanitec transport or response could not be verified; token, URLs and body details withheld.") from None
        finally: _PRIVATE.reset(private)

    async def execute(self, inputs):
        supplied = _credential(self.config.credentials)
        saved = await self._freshen_for_execution(supplied.model_dump(), credential_id=self.node_data.get("credential_id"), user_id=self.user_id, pool=self.node_data.get("_approval_pool"), organization_id=self.organization_id, workflow_id=self.workflow_id)
        credential, config = _credential(saved), self.config.config
        if config is None: raise ValueError("Choose a native Humanitec operation.")
        store = saved.store if isinstance(saved, _SavedCredential) else None
        authority = store.current if store else None
        operation, root = config.operation, "/orgs/" + credential.organization_id
        self.scope_registry.require(operation)
        if operation in WRITES and not credential.allow_metadata_writes: raise HumanitecDenied("Metadata writes are disabled on the current saved Humanitec credential.")
        calls, mutation_started, receipt_seen = 0, False, False
        async def current():
            if store:
                try: changed = _credential(await store.load()) != credential or store.current != authority
                except Exception: raise _AuthorityChanged("Current Humanitec authority could not be verified.") from None
                if changed: raise _AuthorityChanged("Current Humanitec token, owner/access/version, organization or policy changed.")
        async def call(method, path, **kwargs):
            nonlocal calls, mutation_started, receipt_seen
            await current()
            calls += 1
            if calls > 10: raise HumanitecUnavailable("Humanitec exceeded its native request budget.")
            if method != "GET": mutation_started = True
            result = await self._request(method, path, credential=credential, **kwargs)
            if method != "GET": receipt_seen = True
            await current()
            return result
        async def get(path): return (await call("GET", path))[0]
        org = credential.organization_id
        try:
            if operation in ("test_connection", "get_organization", "create_application"):
                raw = _row(await get(root))
                if raw.get("id") != org: raise HumanitecDenied("Humanitec returned a different selected organization.")
                organization = {"organization_id": _id(raw["id"], tenant=True), "organization_name": _text(raw.get("name"))}
                _dates(raw, organization, ("created_at",))
                if operation != "create_application":
                    return {"status": "success", "action": operation, "data": {**organization, "reachable": True, "authentication_verified": True, "account_identity_verified": True, "subject_identity_verified": None, "paid_entitlement_verified": None}}
            app_path = root + "/apps/" + config.app_id if hasattr(config, "app_id") else None
            application = _application(await get(app_path), org, config.app_id) if app_path and operation != "create_application" else None
            env_path = app_path + "/envs/" + config.environment_id if getattr(config, "environment_id", None) else None
            environment = _environment(await get(env_path), config.environment_id) if env_path else None
            pipeline_path = app_path + "/pipelines/" + config.pipeline_id if hasattr(config, "pipeline_id") else None
            pipeline = _pipeline(await get(pipeline_path), org, config.app_id, config.pipeline_id) if pipeline_path else None
            if operation == "get_application": return {"status": "success", "action": operation, "data": application}
            if operation == "get_environment": return {"status": "success", "action": operation, "data": environment}
            if operation == "get_deployment": return {"status": "success", "action": operation, "data": _deployment(await get(env_path + "/deploys/" + config.deployment_id), config.environment_id, config.deployment_id)}
            if operation == "get_pipeline": return {"status": "success", "action": operation, "data": pipeline}
            if operation == "get_pipeline_run": return {"status": "success", "action": operation, "data": _run(await get(pipeline_path + "/runs/" + config.run_id), org, config.app_id, config.pipeline_id, config.run_id)}
            if operation in WRITES:
                previous_name = None
                if operation == "create_application":
                    raw, _ = await call("POST", root + "/apps", body={"id": config.app_id, "name": config.name, "skip_environment_creation": True})
                    _application(raw, org, config.app_id)
                    readback = _application(await get(app_path), org, config.app_id)
                    if readback["environments"]: raise HumanitecUnavailable("Humanitec app readback unexpectedly includes environments.")
                else:
                    before, path = (application, app_path) if operation == "rename_application" else (environment, env_path)
                    if before.get("status") == "deleting" or before["name"] != config.expected_name: raise HumanitecDenied("Humanitec current metadata does not match the explicitly expected active resource.")
                    previous_name = before["name"]
                    raw, _ = await call("PATCH", path, body={"name": config.name})
                    readback = _application(raw, org, config.app_id) if operation == "rename_application" else _environment(raw, config.environment_id)
                    readback = _application(await get(path), org, config.app_id) if operation == "rename_application" else _environment(await get(path), config.environment_id)
                if readback["name"] != config.name: raise HumanitecUnavailable("Humanitec current name readback does not match the request.")
                return {"status": "success", "action": operation, "data": {"resource": readback, "previous_name": previous_name, "request_accepted": True, "readback_verified": True, "concurrency_verified": None, "automation_effects_verified": None, "cleanup_available_in_node": False if operation == "create_application" else None}}
            local = operation in ("list_applications", "list_environment_types", "list_environments", "list_deployments")
            paths = {"list_applications": root + "/apps", "list_environment_types": root + "/env-types", "list_environments": (app_path or "") + "/envs", "list_deployments": (env_path or "") + "/deploys", "list_pipelines": (app_path or "") + "/pipelines", "list_pipeline_runs": (pipeline_path or "") + "/runs"}
            params = [("per_page", str(config.per_page))] if not local else []
            if operation == "list_pipelines" and config.trigger_type is not None: params.append(("trigger", config.trigger_type))
            if operation == "list_pipeline_runs":
                if config.environment_id: params.append(("env", config.environment_id))
                params.extend(("status", value) for value in config.status_filters)
                if config.completed is not None: params.append(("completed", str(config.completed).lower()))
            cursor = _ticket(credential, authority, config, token=config.page_token) if config.page_token else {}
            seen = []
            if not local and cursor:
                if set(cursor) != {"page", "seen"} or not isinstance(cursor["seen"], list) or len(cursor["seen"]) >= 50 or any(not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{64}", item) for item in cursor["seen"]): raise ValueError("Humanitec provider continuation is malformed or exhausted.")
                params.append(("page", _text(cursor["page"], 512))); seen = cursor["seen"]
            raw, next_page = await call("GET", paths[operation], params=params)
            if not isinstance(raw, list) or len(raw) > (MAX_COLLECTION if local else config.per_page): raise HumanitecUnavailable("Humanitec list metadata exceeds its bound or is malformed.")
            def shaped(row):
                if operation == "list_applications": return _application(row, org)
                if operation == "list_environments": return _environment(row)
                if operation == "list_deployments": return _deployment(row, config.environment_id)
                if operation == "list_pipelines": return _pipeline(row, org, config.app_id)
                if operation == "list_pipeline_runs": return _run(row, org, config.app_id, config.pipeline_id, env=config.environment_id)
                row = _row(row)
                return {"id": _id(row.get("id"), tenant=True), "description": _text(row.get("description"), 512, empty=True)}
            items = [shaped(row) for row in raw]
            if len({row["id"] for row in items}) != len(items): raise HumanitecUnavailable("Humanitec duplicated list resource identities.")
            filtered = [row for row in items if config.search.casefold() in (row.get("name", row["id"])).casefold()]
            next_token = None
            if local:
                digest = hashlib.sha256(json.dumps(filtered, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                offset = cursor.get("offset", 0)
                if cursor and (set(cursor) != {"offset", "snapshot"} or type(offset) is not int or not 0 < offset < len(filtered) or cursor["snapshot"] != digest): raise ValueError("Humanitec bounded collection changed; restart its native pagination.")
                page = filtered[offset:offset + config.per_page]
                if offset + len(page) < len(filtered): next_token = _ticket(credential, authority, config, payload={"offset": offset + len(page), "snapshot": digest})
            else:
                page = filtered
                marker = hashlib.sha256((cursor.get("page", "") if cursor else "").encode()).hexdigest()
                if next_page:
                    if not items or next_page == cursor.get("page") or hashlib.sha256(next_page.encode()).hexdigest() in seen + [marker]: raise HumanitecUnavailable("Humanitec pagination did not advance.")
                    next_token = _ticket(credential, authority, config, payload={"page": next_page, "seen": seen + [marker]})
            return {"status": "success", "action": operation, "data": {"items": page, "next_page_token": next_token, "pagination_source": "native_bounded_collection" if local else "provider_link", "search_scope": "bounded_collection" if local else "observed_page_only", "snapshot_verified": True if local else None}}
        except Exception:
            if not mutation_started: raise
            return {"status": "unknown", "data": {"request_accepted": True if receipt_seen else None, "readback_verified": None, "concurrency_verified": None, "automation_effects_verified": None, "retry_safe": False, "app_id": config.app_id, "environment_id": getattr(config, "environment_id", None)}, "error": "A Humanitec metadata write may have occurred; verify current provider state before retrying. No rollback or raw response is disclosed."}

    @classmethod
    async def load_field_options(cls, field_name, user_id=None, *, credential_data=None, credential_id=None, context=None, search=None, page_token=None, **kwargs):
        operations = {"app_id": "list_applications", "environment_id": "list_environments", "deployment_id": "list_deployments", "pipeline_id": "list_pipelines", "run_id": "list_pipeline_runs"}
        if field_name not in operations: return {"options": [], "next_page_token": None}
        context = context or {}; user_id = user_id or context.get("_user_id")
        saved = await cls._freshen_for_execution(credential_data, credential_id=credential_id, user_id=user_id, **kwargs)
        if isinstance(saved, _SavedCredential):
            store = saved.store
            if str(user_id) != store.user_id: raise HumanitecDenied("Humanitec picker caller changed.")
            credential_id = store.credential_id; kwargs = {**kwargs, "pool": store.pool, "organization_id": store.current.organization_id, "workflow_id": store.workflow_id}
        arguments = {"per_page": 100, "page_token": page_token, "search": _text(search, 128, empty=True) if search else ""}
        for parent in (() if field_name == "app_id" else ("app_id", "environment_id") if field_name == "deployment_id" else ("app_id", "pipeline_id") if field_name == "run_id" else ("app_id",)):
            if not context.get(parent): return {"options": [], "next_page_token": None}
            arguments[parent] = _id(context[parent], tenant=parent != "pipeline_id")
        from nodes.core.run_op import run_node_operation
        result = await run_node_operation(node_type="automation-humanitec", operation=operations[field_name], arguments=arguments, credential_data=saved, credential_id=credential_id, user_id=user_id, pool=kwargs.get("pool"), organization_id=kwargs.get("organization_id"), workflow_id=kwargs.get("workflow_id"))
        if result.get("executed") is False or result.get("status") in ("pending_approval", "rejected"): return result
        page = result["data"]
        return {"options": [{"value": row["id"], "label": row.get("name") or row["id"] + (" · " + row["status"] if row.get("status") else ""), "metadata": {"organization_id": _credential(saved).organization_id, **{key: value for key, value in arguments.items() if key.endswith("_id")}, "observed_page_only": page["search_scope"] == "observed_page_only"}} for row in page["items"]], "next_page_token": page["next_page_token"]}
