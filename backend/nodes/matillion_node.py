"""Current Maia / Matillion DPC metadata and explicit execution lifecycle.

Fixed regional API hosts and existing issued bearer or OAuth client credentials.
No AI model calls, provisioning, deployments, secrets, billing or arbitrary HTTP.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote, quote_plus

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, ValidationResult, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence

NODE_TYPE = "automation-matillion"
FAMILIES = ("matillion_bearer_token", "matillion_client_credentials")
REGIONS = {"eu1": "https://eu1.api.matillion.com/dpc", "us1": "https://us1.api.matillion.com/dpc", "au1": "https://au1.api.matillion.com/dpc"}
TOKEN_URL = "https://id.core.matillion.com/oauth/dpc/token"
AUDIENCE = "https://api.matillion.com"
UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 1000
STATUSES = ("RUNNING", "SUCCESS", "FAILED", "CANCELLING", "CANCELLED", "FORBIDDEN", "SKIPPED", "UNKNOWN")
Status = Literal["RUNNING", "SUCCESS", "FAILED", "CANCELLING", "CANCELLED", "FORBIDDEN", "SKIPPED", "UNKNOWN"]
WRITE_OPS = ("start_pipeline_execution", "cancel_pipeline_execution")


def _secret_value(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 8192 or any(ord(c) <= 32 or ord(c) >= 127 for c in value) or value.startswith("Bearer "):
        raise ValueError("Supply the existing issued credential without a header prefix or whitespace")
    return value


def _expiry(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Use the actual timezone-aware expiry")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Use the actual timezone-aware expiry") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Token expiry requires a timezone")
    return parsed


class MatillionRegionCredential(BaseModel):
    region: Literal["eu1", "us1", "au1"] = Field(..., title="Account Region", description="Select the actual account region. Current official OpenAPI lists EU1, US1 and AU1; hosts are fixed and never inferred from token claims.")


class MatillionBearerTokenCredential(MatillionRegionCredential):
    credential_type: Literal["matillion_bearer_token"] = Field("matillion_bearer_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Existing API Bearer Token", json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = Field(None, title="Actual Expiry (Optional)", description="Only a known timezone-aware expiry. Issued API tokens last 30 minutes; no guessed mint time or JWT identity proof.")
    model_config = ConfigDict(title="Maia (Matillion) Bearer Token", extra="ignore", json_schema_extra={
        "x-credential-url": "https://docs.maia.ai/docs/api-reference/maia-api-authentication",
        "x-credential-instructions": "Supply an existing issued Maia/DPC API access token for this region. Exact Authorization: Bearer TOKEN. Token lifetime is 30 minutes; supply a new current token when needed. No token mint, refresh or environment fallback for this family. GitHub repository PATs are different credentials. Protected metadata reads do not prove execution privileges or account identity.",
    })
    _token = field_validator("access_token")(_secret_value)

    @field_validator("expires_at")
    @classmethod
    def actual_expiry(cls, value):
        if value is not None:
            _expiry(value)
        return value


class MatillionClientCredentialsCredential(MatillionRegionCredential):
    credential_type: Literal["matillion_client_credentials"] = Field("matillion_client_credentials", json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., max_length=256, title="Existing API Client ID")
    client_secret: str = Field(..., max_length=4096, title="Existing API Client Secret", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Maia (Matillion) Client ID and Secret", extra="ignore", json_schema_extra={
        "x-credential-url": "https://docs.maia.ai/docs/api-reference/maia-api-authentication",
        "x-credential-instructions": "Use an existing issued API client ID/secret. Native OAuth client_credentials sends a URL-encoded form to id.core.matillion.com/oauth/dpc/token with fixed audience https://api.matillion.com; resource calls use Bearer. Tokens remain in memory for one operation and are never persisted or returned. No app registration, user login, invented refresh token or role assignment. Actual account/project/environment roles and execution/credit access depend on the credential.",
    })
    _credentials = field_validator("client_id", "client_secret")(_secret_value)


MatillionCredential = Union[MatillionBearerTokenCredential, MatillionClientCredentialsCredential]


def _op(name, label, category):
    return Field(name, title=label, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})


def _uuid(value):
    if not isinstance(value, str) or not re.fullmatch(UUID_PATTERN, value.lower()):
        raise ValueError("Supply the exact canonical UUID")
    return value.lower()


def _name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 255 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Supply the exact bounded nonempty resource name")
    return value


def _whole(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,6}", value):
        value = int(value)
    if type(value) is not int:
        raise ValueError("Use a whole page or limit")
    return value


def _dynamic(field, parent=None):
    result = {"x-dynamic-options": {"field_name": field, "searchable": True, "allow_custom": True}, "x-resource-type": "matillion_" + field.removesuffix("_id").removesuffix("_name"), "x-resource-id-path": field}
    if parent:
        result["x-dynamic-options"]["depends_on"] = parent
    return result


class MatillionOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MatillionCheckConfig(MatillionOperation):
    operation: Literal["test_connection"] = _op("test_connection", "Check Protected Project Access", "Connection")


class MatillionPageConfig(MatillionOperation):
    page: int = Field(0, ge=0, le=100000, description="Actual zero-based Maia page; one page is returned.")
    size: int = Field(25, ge=1, le=100, description="Native page limit 100. Most endpoints document 1–100; published pipelines allow up to 1000, but this node keeps the smaller bound.")
    _pages = field_validator("page", "size", mode="before")(_whole)


class MatillionProjectScope(MatillionOperation):
    project_id: str = Field(..., title="Project", json_schema_extra=_dynamic("project_id"))
    _project = field_validator("project_id")(_uuid)


class MatillionEnvironmentScope(MatillionProjectScope):
    environment_name: str = Field(..., title="Environment", json_schema_extra=_dynamic("environment_name", "project_id"))
    _environment = field_validator("environment_name")(_name)


class MatillionExecutionScope(MatillionProjectScope):
    pipeline_execution_id: str = Field(..., title="Pipeline Execution", json_schema_extra=_dynamic("pipeline_execution_id", "project_id"))
    _execution = field_validator("pipeline_execution_id")(_uuid)


class MatillionListProjectsConfig(MatillionPageConfig):
    operation: Literal["list_projects"] = _op("list_projects", "List Projects", "Projects")


class MatillionListEnvironmentsConfig(MatillionPageConfig, MatillionProjectScope):
    operation: Literal["list_environments"] = _op("list_environments", "List Project Environments", "Environments")


class MatillionListPipelinesConfig(MatillionPageConfig, MatillionEnvironmentScope):
    operation: Literal["list_published_pipelines"] = _op("list_published_pipelines", "List Published Environment Pipelines", "Pipelines")


class MatillionListArtifactsConfig(MatillionPageConfig, MatillionEnvironmentScope):
    operation: Literal["list_artifacts"] = _op("list_artifacts", "List Environment Artifact Metadata", "Artifacts")
    enabled_only: bool = Field(True)


class MatillionGetArtifactConfig(MatillionEnvironmentScope):
    operation: Literal["get_artifact_metadata"] = _op("get_artifact_metadata", "Get Artifact Metadata", "Artifacts")
    version_name: str = Field(..., title="Artifact Version", json_schema_extra=_dynamic("version_name", "environment_name"), description="Exact explicit version; no implicit latest readback.")
    _version = field_validator("version_name")(_name)


class MatillionListExecutionsConfig(MatillionProjectScope):
    operation: Literal["list_pipeline_executions"] = _op("list_pipeline_executions", "List Project Execution Metadata", "Executions")
    environment_name: Optional[str] = Field(None, title="Environment Filter", json_schema_extra=_dynamic("environment_name", "project_id"))
    pipeline_name_search: Optional[str] = Field(None, max_length=128, description="Documented case-insensitive pipeline-name substring filter.")
    status_filter: Optional[Status] = Field(None)
    limit: int = Field(25, ge=1, le=100)
    continuation: Optional[str] = Field(None, max_length=24000, description="Only the node's bound continuation from the same current actor/credential/project/filter. Continuation wraps the provider cursor and remains private workflow metadata; it is not account identity proof.")
    _limit = field_validator("limit", mode="before")(_whole)

    @field_validator("environment_name", "pipeline_name_search")
    @classmethod
    def optional_name(cls, value):
        return _name(value) if value is not None else None


class MatillionGetExecutionConfig(MatillionExecutionScope):
    operation: Literal["get_pipeline_execution_metadata"] = _op("get_pipeline_execution_metadata", "Get Scoped Execution Metadata", "Executions")


class MatillionGetStatusConfig(MatillionExecutionScope):
    operation: Literal["get_pipeline_execution_status"] = _op("get_pipeline_execution_status", "Get Lightweight Execution Status", "Executions")


class MatillionListStepsConfig(MatillionPageConfig, MatillionExecutionScope):
    operation: Literal["list_execution_steps"] = _op("list_execution_steps", "List Execution Step Metadata", "Executions")


class MatillionListTasksConfig(MatillionPageConfig, MatillionExecutionScope):
    operation: Literal["list_execution_tasks"] = _op("list_execution_tasks", "List Execution Task Metadata", "Executions")
    status_filter: Optional[Status] = Field(None)


class MatillionStartConfig(MatillionEnvironmentScope):
    operation: Literal["start_pipeline_execution"] = _op("start_pipeline_execution", "Start Published Pipeline", "Execution Lifecycle")
    pipeline_name: str = Field(..., title="Published Pipeline", json_schema_extra=_dynamic("pipeline_name", "environment_name"))
    version_name: Optional[str] = Field(None, title="Artifact Version (Optional)", json_schema_extra=_dynamic("version_name", "environment_name"), description="When omitted, the provider executes the latest published version. Current artifact membership and execution permissions are ultimately enforced by Maia.")
    execution_tag: Optional[str] = Field(None, max_length=128, description="Documented concurrency tag; only one execution per tag/environment may run. 409 is not retried.")
    confirm_execution: bool = Field(False, description="Confirm this starts a real published pipeline, may move data and consume credits. No execution is performed during integration preparation.")
    _pipeline = field_validator("pipeline_name")(_name)

    @field_validator("version_name", "execution_tag")
    @classmethod
    def optional_name(cls, value):
        return _name(value) if value is not None else None


class MatillionCancelConfig(MatillionExecutionScope):
    operation: Literal["cancel_pipeline_execution"] = _op("cancel_pipeline_execution", "Cancel Scoped Pipeline Execution", "Execution Lifecycle")
    force_termination: bool = Field(False, description="Forceful termination may leave partially completed external data effects. Default is graceful cancellation.")
    confirm_execution: bool = Field(False, description="Confirm cancellation of this exact owned execution. An acknowledgement does not establish completion or rolled-back data effects.")


class MatillionListSharedArtifactsConfig(MatillionPageConfig):
    operation: Literal["list_shared_artifact_metadata"] = _op("list_shared_artifact_metadata", "List Shared Artifact Metadata", "Shared Artifacts")
    shared_pipeline_id_prefix: Optional[str] = Field(None, max_length=255, description="Optional exact published prefix filter; no publication or enable/disable action.")
    enabled_only: bool = Field(True)

    @field_validator("shared_pipeline_id_prefix")
    @classmethod
    def optional_name(cls, value):
        return _name(value) if value is not None else None


class MatillionGetSharedArtifactConfig(MatillionOperation):
    operation: Literal["get_shared_artifact_metadata"] = _op("get_shared_artifact_metadata", "Get Shared Artifact Metadata", "Shared Artifacts")
    shared_pipeline_id_prefix: str = Field(..., title="Shared Pipeline Prefix", max_length=255, description="Exact known published prefix. The generic shared-pipeline-list row contract is not published, so no invented ID picker is used.")
    version_name: str = Field(..., title="Explicit Artifact Version", max_length=255)
    _names = field_validator("shared_pipeline_id_prefix", "version_name")(_name)


MatillionConfig = Annotated[Union[MatillionCheckConfig, MatillionListProjectsConfig, MatillionListEnvironmentsConfig, MatillionListPipelinesConfig, MatillionListArtifactsConfig, MatillionGetArtifactConfig, MatillionListExecutionsConfig, MatillionGetExecutionConfig, MatillionGetStatusConfig, MatillionListStepsConfig, MatillionListTasksConfig, MatillionStartConfig, MatillionCancelConfig, MatillionListSharedArtifactsConfig, MatillionGetSharedArtifactConfig], Field(discriminator="operation")]


class MatillionNodeConfig(NodeConfig[MatillionConfig, MatillionCredential]):
    pass


class MatillionAPIError(ValueError):
    def __init__(self, message, *, authority_rejected=False):
        super().__init__(message)
        self.authority_rejected = authority_rejected


def _shape(data):
    if not isinstance(data, dict):
        raise ValueError("Maia credentials are invalid")
    family = data.get("credential_type")
    if family is None:
        bearer = bool(data.get("access_token"))
        client = bool(data.get("client_id")) and bool(data.get("client_secret"))
        if bearer == client:
            raise ValueError("Select an unambiguous Maia credential family")
        family = FAMILIES[0] if bearer else FAMILIES[1]
    if family not in FAMILIES:
        raise ValueError("Maia credential family is unsupported")
    model = MatillionBearerTokenCredential if family == FAMILIES[0] else MatillionClientCredentialsCredential
    try:
        shaped = model.model_validate({**data, "credential_type": family}).model_dump()
    except Exception:
        raise ValueError("Maia native credentials or account region are invalid") from None
    if shaped.get("expires_at") and _expiry(shaped["expires_at"]) <= datetime.now(timezone.utc):
        raise MatillionAPIError("Maia API token has expired; supply a current issued token", authority_rejected=True)
    return {**data, **shaped}


def _original_family(data):
    if not isinstance(data, dict):
        raise ValueError("Maia configuration is invalid")
    creds = data.get("credentials")
    saved = data.get("credential_id") or data.get("credentialIds")
    if saved and not isinstance(creds, dict) or isinstance(creds, dict) and (creds.get("credential_type") is not None or saved) and creds.get("credential_type") not in FAMILIES:
        raise ValueError("Maia saved credential family is missing or unsupported")


def _secrets(data):
    return [data["access_token"]] if data["credential_type"] == FAMILIES[0] else [data["client_id"], data["client_secret"]]


def _binding(data):
    return (data["credential_type"], tuple(_secrets(data)), data["region"], data.get("expires_at"), data.get("owner_id"), data.get("token_version"), data.get("updated_at"), data.get("approval_revision"))


async def _current_data(data, **context):
    """Validate credentials resolved by staging's shared access policy.

    Bearer tokens are supplied as issued; client credentials mint a token for
    this operation only. The node does not load credential repository rows.
    """
    return _shape(data)


def _context(data, context):
    return {**{k: v for k, v in context.items() if not k.startswith("_")},
            "_user_id": context.get("_user_id")}


def _authority(context):
    return {}


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
        return re.sub(r"(?i)([?&](?:access_token|api_key|token|signature|auth|key)=)[^&#\s]+", r"\1[redacted]", value)
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


@dataclass(frozen=True, repr=False)
class _TokenLease:
    access_token: str
    expires_at: Optional[datetime]
    binding: tuple


def _route_allowed(route, method):
    if method == "POST":
        return re.fullmatch(r"/v1/projects/" + UUID_PATTERN + r"/pipeline-executions", route) is not None
    if method == "PATCH":
        return re.fullmatch(r"/v1/projects/" + UUID_PATTERN + r"/pipeline-executions/" + UUID_PATTERN, route) is not None
    if method != "GET":
        return False
    return route in ("/v1/projects", "/v1/pipeline-executions", "/v1/shared-pipelines/artifacts", "/v1/shared-pipelines/artifacts/details") or re.fullmatch(r"/v1/projects/" + UUID_PATTERN + r"/(?:environments|published-pipelines|artifacts(?:/details)?|pipeline-executions/" + UUID_PATTERN + r"(?:/(?:status|steps|tasks))?)", route) is not None


async def _send(url, *, method, headers, params=None, body=None, form=None, expected=200, write=False):
    suffix = " Execution outcome is unverified; inspect the exact owned execution before retrying." if write else ""
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, url, headers=headers, **({"params": params} if params else {}), **({"json": body} if body is not None else {}), **({"data": form} if form is not None else {})) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(raw) + len(chunk) > MAX_BYTES:
                        raise MatillionAPIError("Maia response exceeds the local byte bound." + suffix)
                    raw.extend(chunk)
                if response.status_code in (401, 403):
                    raise MatillionAPIError(f"Maia HTTP {response.status_code}: authority rejected." + suffix, authority_rejected=True)
                if response.status_code != expected or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise MatillionAPIError(f"Maia HTTP {response.status_code}: documented JSON success is unverified." + suffix)
                try:
                    result = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    _bounded(result)
                except (ValueError, UnicodeError, RecursionError):
                    raise MatillionAPIError("Maia response JSON is unverified." + suffix) from None
                if not isinstance(result, dict) or result.get("error") or result.get("errors") or result.get("status") in ("error", "rejected", "pending_approval", "not_executed", "forbidden") or type(result.get("status")) is int and result["status"] >= 400:
                    raise MatillionAPIError("Maia returned an unsuccessful or unverified response." + suffix)
                return result
    except MatillionAPIError:
        raise
    except (httpx.HTTPError, OSError, ValueError, UnicodeError):
        raise MatillionAPIError("Maia transport failed; result is unverified." + suffix) from None


async def _lease(data, context):
    current = await _current_data(data, **_authority(context))
    if _binding(current) != _binding(data):
        raise ValueError("Maia current credential changed before authentication")
    if data["credential_type"] == FAMILIES[0]:
        return _TokenLease(data["access_token"], _expiry(data["expires_at"]) if data.get("expires_at") else None, _binding(data))
    form = {"grant_type": "client_credentials", "client_id": current["client_id"], "client_secret": current["client_secret"], "audience": AUDIENCE}
    started = datetime.now(timezone.utc)
    response = await _send(TOKEN_URL, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, form=form)
    try:
        token = _secret_value(response.get("access_token"))
        lifetime = response.get("expires_in")
        if response.get("token_type") != "Bearer" or type(lifetime) is not int or not 1 <= lifetime <= 1800:
            raise ValueError()
    except ValueError:
        raise MatillionAPIError("Maia OAuth token response is unverified; no resource request was sent") from None
    after = await _current_data(data, **_authority(context))
    if _binding(after) != _binding(current):
        raise ValueError("Maia credential owner, policy, region or app changed during authentication; token discarded")
    return _TokenLease(token, started + timedelta(seconds=lifetime), _binding(current))


async def _request(data, context, lease, route, *, method="GET", params=None, body=None):
    if not _route_allowed(route, method) or method == "GET" and body is not None or method in ("POST", "PATCH") and not isinstance(body, dict):
        raise ValueError("Unsupported Maia native route or effect")
    current = await _current_data(data, **_authority(context))
    if _binding(current) != _binding(data) or lease.binding != _binding(current):
        raise ValueError("Maia current credential changed; rerun with current authority")
    if lease.expires_at is not None and lease.expires_at <= datetime.now(timezone.utc):
        raise MatillionAPIError("Maia token has expired; no automatic renewal or execution replay", authority_rejected=True)
    if body is not None:
        _bounded(body)
        if len(json.dumps(body, allow_nan=False).encode()) > 4096:
            raise ValueError("Maia execution payload exceeds the local bound; no request was sent")
    return await _send(REGIONS[data["region"]] + route, method=method,
                       headers={"Authorization": "Bearer " + lease.access_token, "Accept": "application/json", "Content-Type": "application/json" if body is not None else "application/x-www-form-urlencoded"},
                       params=params, body=body, expected=201 if method == "POST" else 200, write=method != "GET")


def _identifier(value):
    try:
        return _uuid(value)
    except ValueError:
        raise MatillionAPIError("Maia returned identifier is unverified") from None


def _resource_name(value):
    try:
        return _name(value)
    except ValueError:
        raise MatillionAPIError("Maia returned resource name is unverified") from None


def _fields(row, fields):
    if not isinstance(row, dict):
        raise MatillionAPIError("Maia selected metadata is unverified")
    result = {}
    for key, expected in fields.items():
        if key not in row:
            continue
        value = row[key]
        if value is None:
            result[key] = None
        elif type(value) is not expected or isinstance(value, str) and (len(value) > 1024 or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise MatillionAPIError("Maia selected field is unverified")
        else:
            result[key] = value
    return result


def _status(value):
    if value not in STATUSES:
        raise MatillionAPIError("Maia execution status is unverified")
    return value


def _execution(row, *, project, wanted=None, environment=None):
    if not isinstance(row, dict) or _identifier(row.get("projectId")) != project:
        raise MatillionAPIError("Maia execution does not belong to the selected project")
    identifier = _identifier(row.get("pipelineExecutionId"))
    if wanted is not None and identifier != wanted:
        raise MatillionAPIError("Maia returned another pipeline execution")
    actual_environment = _resource_name(row.get("environmentName"))
    if environment is not None and actual_environment != environment:
        raise MatillionAPIError("Maia execution does not belong to the selected environment")
    out = {"pipelineExecutionId": identifier, "projectId": project, "environmentName": actual_environment, "pipelineName": _resource_name(row.get("pipelineName")), "status": _status(row.get("status")), **_fields(row, {"startedAt": str, "finishedAt": str, "pipelineType": str, "trigger": str})}
    if out.get("trigger") is not None and out["trigger"] not in ("DESIGNER", "API", "SCHEDULE", "SCHEDULE_RUN_NOW", "UNKNOWN"):
        raise MatillionAPIError("Maia execution trigger is unverified")
    return out


def _artifact(row, *, wanted=None, prefix=None):
    if not isinstance(row, dict):
        raise MatillionAPIError("Maia artifact metadata is unverified")
    version = _resource_name(row.get("versionName"))
    if wanted is not None and version != wanted:
        raise MatillionAPIError("Maia returned another artifact version")
    if type(row.get("enabled")) is not bool:
        raise MatillionAPIError("Maia artifact enabled marker is unverified")
    out = {"versionName": version, "enabled": row["enabled"], **_fields(row, {"createdAt": str, "deployedAt": str})}
    if prefix is not None or "sharedPipelineIdPrefix" in row:
        actual = _resource_name(row.get("sharedPipelineIdPrefix"))
        if prefix is not None and actual != prefix:
            raise MatillionAPIError("Maia returned another shared pipeline prefix")
        out["sharedPipelineIdPrefix"] = actual
    return out


def _project(row, kind):
    if kind == "project":
        return {"id": _identifier(row.get("id")), "name": _resource_name(row.get("name"))} if isinstance(row, dict) else _fields(row, {})
    if kind == "environment":
        return {"name": _resource_name(row.get("name")), **_fields(row, {"defaultAgentName": str})} if isinstance(row, dict) else _fields(row, {})
    if kind == "pipeline":
        return {"name": _resource_name(row.get("name")), **_fields(row, {"publishedTime": str})} if isinstance(row, dict) else _fields(row, {})
    if kind == "artifact":
        return _artifact(row)
    if kind == "shared_artifact":
        projected = _artifact(row)
        if "sharedPipelineIdPrefix" not in projected:
            raise MatillionAPIError("Maia shared artifact prefix is unverified")
        return projected
    if kind == "step":
        if not isinstance(row, dict):
            raise MatillionAPIError("Maia step metadata is unverified")
        out = {"id": _identifier(row.get("id")), "name": _resource_name(row.get("name"))}
        result = row.get("result")
        if not isinstance(result, dict):
            raise MatillionAPIError("Maia step result is unverified")
        return {**out, "result": {"status": _status(result.get("status")), **_fields(result, {"startedAt": str, "finishedAt": str})}}
    if kind == "task":
        if not isinstance(row, dict) or not isinstance(row.get("task"), dict) or not isinstance(row.get("pipeline"), dict):
            raise MatillionAPIError("Maia task metadata is unverified")
        task, pipeline = row["task"], row["pipeline"]
        result = task.get("result")
        if not isinstance(result, dict):
            raise MatillionAPIError("Maia task result is unverified")
        # Child execution tasks are documented; do not force root-ID equality.
        return {"id": _identifier(task.get("id")), "pipelineExecutionId": _identifier(pipeline.get("pipelineExecutionId")), "name": _resource_name(task.get("name")), **_fields(task, {"iterator": bool}), "result": {"status": _status(result.get("status")), **_fields(result, {"startedAt": str, "finishedAt": str})}}
    raise ValueError("Unsupported Maia metadata projection")


def _page(raw, page, size, project):
    rows = raw.get("results")
    if not isinstance(rows, list) or len(rows) > size or any(type(raw.get(k)) is not int or raw[k] < 0 or raw[k] > 9223372036854775807 for k in ("page", "size", "total")) or raw["page"] != page:
        raise MatillionAPIError("Maia page envelope is unverified")
    total, returned_size = raw["total"], raw["size"]
    if returned_size != size or total < page * size + len(rows) or total > page * size and not rows or len(rows) < size and page * size + len(rows) < total:
        raise MatillionAPIError("Maia page counters are inconsistent; exhaustion is unverified")
    out = [project(row) for row in rows]
    keys = [_row_key(row) for row in out]
    if len(set(keys)) != len(keys):
        raise MatillionAPIError("Maia page repeats metadata identifiers")
    more = (page + 1) * size < total
    return {"results": out, "page": page, "size": size, "total": total, "next_page": page + 1 if more else None, "collection_exhausted": not more}


def _row_key(row):
    if "sharedPipelineIdPrefix" in row:
        return row["sharedPipelineIdPrefix"] + "/" + row["versionName"]
    if "pipelineExecutionId" in row and "id" not in row:
        return row["pipelineExecutionId"]
    return row.get("id", row.get("versionName", row.get("name")))


def _continuation_binding(data, context, scope):
    return hashlib.sha256(json.dumps([scope, context.get("_credential_id"), context.get("_user_id"), context.get("_organization_id"), context.get("_workflow_id"), _binding(data)], separators=(",", ":")).encode()).hexdigest()


def _pack(value):
    return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")


def _unpack(token, binding, fields):
    try:
        if not isinstance(token, str) or len(token) > 24000:
            raise ValueError()
        value = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        _bounded(value)
        if not isinstance(value, dict) or set(value) != {"binding", *fields} or value["binding"] != binding:
            raise ValueError()
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("Maia continuation belongs to another actor, current credential, region, parent or filter") from None


async def _execution_scroll(data, context, lease, *, project, limit, environment=None, search=None, status=None, continuation=None):
    scope = ["execution-scroll", project, environment, search, status, limit]
    binding = _continuation_binding(data, context, scope)
    params = {"projectId": project, "limit": limit}
    seen, prior_tokens = [], []
    if environment:
        params["environmentName"] = environment
    if search:
        params["pipelineName"] = search
    if status:
        params["status"] = status
    if continuation:
        saved = _unpack(continuation, binding, {"cursor", "seen", "prior_tokens"})
        cursor = saved["cursor"]
        seen, prior_tokens = saved["seen"], saved["prior_tokens"]
        if not isinstance(cursor, str) or not cursor or len(cursor) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in cursor) or not isinstance(seen, list) or len(seen) >= MAX_ROWS or not isinstance(prior_tokens, list) or len(prior_tokens) > 40 or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in prior_tokens):
            raise ValueError("Maia execution continuation is invalid")
        for identifier in seen:
            _identifier(identifier)
        if len(set(seen)) != len(seen):
            raise ValueError("Maia execution continuation repeats identifiers")
        params["paginationToken"] = cursor
    raw = await _request(data, context, lease, "/v1/pipeline-executions", params=params)
    rows = raw.get("results")
    if not isinstance(rows, list) or len(rows) > limit:
        raise MatillionAPIError("Maia execution collection is unverified")
    out = [_execution(row, project=project, environment=environment) for row in rows]
    if (status is not None and any(row["status"] != status for row in out)) or (search and any(search.casefold() not in row["pipelineName"].casefold() for row in out)):
        raise MatillionAPIError("Maia execution collection does not match the selected filters")
    identifiers = [row["pipelineExecutionId"] for row in out]
    if len(set(identifiers)) != len(identifiers) or set(seen).intersection(identifiers):
        raise MatillionAPIError("Maia execution cursor repeats identifiers; restart the query")
    more = raw.get("more")
    if "more" in raw and (not isinstance(more, str) or not more or len(more) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in more)):
        raise MatillionAPIError("Maia execution cursor is unverified; exhaustion is unknown")
    token = None
    if more is not None:
        digest = hashlib.sha256(more.encode()).hexdigest()
        if digest in prior_tokens or not out or len(seen) + len(out) >= MAX_ROWS or len(prior_tokens) >= 40:
            raise MatillionAPIError("Maia execution cursor reached a local bound or repeated before exhaustion; narrow the query")
        token = _pack({"binding": binding, "cursor": more, "seen": seen + identifiers, "prior_tokens": prior_tokens + [digest]})
        if len(token) > 24000:
            raise MatillionAPIError("Maia execution continuation exceeds the local bound; narrow the query")
    return {"results": out, "next_continuation": token, "collection_exhausted": more is None}


async def _find_named(data, context, lease, route, kind, name, params=None):
    seen = set()
    for page in range(40):
        response = await _request(data, context, lease, route, params={"page": page, "size": 25, **(params or {})})
        result = _page(response, page, 25, lambda row: _project(row, kind))
        keys = [_row_key(row) for row in result["results"]]
        if seen.intersection(keys):
            raise MatillionAPIError("Maia scoped collection repeats metadata identifiers")
        seen.update(keys)
        for row in result["results"]:
            if row["name"] == name:
                return row
        if result["collection_exhausted"]:
            raise ValueError("The exact selected resource is not in the current protected parent collection")
    raise MatillionAPIError("Maia scoped collection reached its 1,000-item bound; membership is unverified")


async def _artifact_details(data, context, lease, project, environment, version):
    raw = await _request(data, context, lease, f"/v1/projects/{project}/artifacts/details", params={"environmentName": environment, "versionName": version})
    return _artifact(raw.get("details"), wanted=version)


async def _get_execution(data, context, lease, project, identifier):
    raw = await _request(data, context, lease, f"/v1/projects/{project}/pipeline-executions/{identifier}")
    return _execution(raw, project=project, wanted=identifier)


class MatillionNode(WorkflowNode):
    integration_type = "automation-matillion"
    node_type = NODE_TYPE
    credential_provider_labels = {"matillion": "Maia (Matillion)"}
    connection_evidence = ConnectionEvidence(operation="test_connection", noun="Maia API access", proves="reachability")
    edit_examples = ["Read published pipeline metadata in a selected environment", "Check an existing pipeline execution's lightweight status", "Start a confirmed published pipeline and retain its asynchronous execution ID"]

    @classmethod
    def get_config_model(cls):
        return MatillionNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        data = config_data
        _original_family(data)
        shaped = dict(data)
        if data.get("credentials") is not None:
            shaped["credentials"] = _shape(data["credentials"])
        try:
            MatillionNodeConfig.model_validate(runtime_config_view(shaped, MatillionNodeConfig))
        except ValueError:
            raise ValueError("Maia configuration is invalid; check credential family, region and selected metadata scope") from None
        return super().parse_config(shaped)

    @classmethod
    def validate_config(cls, config_data):
        data = config_data
        try:
            _original_family(data)
            shaped = dict(data)
            if data.get("credentials") is not None:
                shaped["credentials"] = _shape(data["credentials"])
            MatillionNodeConfig.model_validate(runtime_config_view(shaped, MatillionNodeConfig))
        except (ValueError, TypeError):
            return ValidationResult(valid=False, errors=["Maia configuration or credential family is invalid"], satisfied_set=None)
        return super().validate_config(shaped)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await _current_data(credential_data)

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, MatillionNodeConfig) or self.config.credentials is None:
            raise ValueError("Maia requires its explicit native credential and configuration")
        cfg = self.config.config
        if cfg.operation in WRITE_OPS and not cfg.confirm_execution:
            raise ValueError("Confirm the real scoped Maia execution lifecycle operation")
        context = {"_approval_pool": (self.node_data or {}).get("_approval_pool"), "_credential_id": (self.node_data or {}).get("credential_id"), "_user_id": self.user_id, "_organization_id": self.organization_id, "_workflow_id": self.workflow_id}
        data = await _current_data(self.config.credentials.model_dump(), **_authority(context))
        lease = await _lease(data, context)
        result = await self._operation(cfg, data, context, lease)
        for secret in [*_secrets(data), lease.access_token]:
            result = _redact(result, secret)
        return {"status": "success", "operation": cfg.operation, "data": result}

    async def _operation(self, cfg, data, context, lease):
        op = cfg.operation
        if op == "test_connection":
            result = _page(await _request(data, context, lease, "/v1/projects", params={"page": 0, "size": 1}), 0, 1, lambda row: _project(row, "project"))
            return {"protected_read_completed": True, "account_identity_verified": False, "execution_permission_verified": False, "projects_returned": len(result["results"]), "region": data["region"]}
        if op in ("list_projects", "list_environments", "list_published_pipelines", "list_artifacts", "list_shared_artifact_metadata"):
            routes = {"list_projects": ("/v1/projects", "project"), "list_shared_artifact_metadata": ("/v1/shared-pipelines/artifacts", "shared_artifact")}
            if op not in routes:
                routes[op] = (f"/v1/projects/{cfg.project_id}/" + {"list_environments": "environments", "list_published_pipelines": "published-pipelines", "list_artifacts": "artifacts"}[op], {"list_environments": "environment", "list_published_pipelines": "pipeline", "list_artifacts": "artifact"}[op])
            route, kind = routes[op]
            params = {"page": cfg.page, "size": cfg.size}
            if op in ("list_published_pipelines", "list_artifacts"):
                params["environmentName"] = cfg.environment_name
            if op in ("list_artifacts", "list_shared_artifact_metadata"):
                params["enabledOnly"] = str(cfg.enabled_only).lower()
            if op == "list_shared_artifact_metadata" and cfg.shared_pipeline_id_prefix:
                params["sharedPipelineIdPrefix"] = cfg.shared_pipeline_id_prefix
            result = _page(await _request(data, context, lease, route, params=params), cfg.page, cfg.size, lambda row: _project(row, kind))
            if op == "list_shared_artifact_metadata" and cfg.shared_pipeline_id_prefix and any(row["sharedPipelineIdPrefix"] != cfg.shared_pipeline_id_prefix for row in result["results"]):
                raise MatillionAPIError("Maia returned another shared artifact prefix")
            return {**({"project_id": cfg.project_id, "parent_scope_source": "protected_request_route"} if hasattr(cfg, "project_id") else {}), **({"environment_name": cfg.environment_name} if hasattr(cfg, "environment_name") else {}), **result}
        if op == "get_artifact_metadata":
            return {"project_id": cfg.project_id, "environment_name": cfg.environment_name, "parent_scope_source": "protected_request_route", "artifact": await _artifact_details(data, context, lease, cfg.project_id, cfg.environment_name, cfg.version_name)}
        if op == "get_shared_artifact_metadata":
            raw = await _request(data, context, lease, "/v1/shared-pipelines/artifacts/details", params={"sharedPipelineIdPrefix": cfg.shared_pipeline_id_prefix, "versionName": cfg.version_name})
            pipelines = raw.get("sharedPipelines")
            if not isinstance(pipelines, list) or len(pipelines) > MAX_ROWS:
                raise MatillionAPIError("Maia shared pipeline resources are unverified")
            ids = [_resource_name(row.get("sharedPipelineId")) if isinstance(row, dict) else _resource_name(None) for row in pipelines]
            if len(set(ids)) != len(ids):
                raise MatillionAPIError("Maia shared pipeline resource identifiers repeat")
            return {"artifact": _artifact(raw.get("artifactDetails"), wanted=cfg.version_name, prefix=cfg.shared_pipeline_id_prefix), "shared_pipeline_ids": ids}
        if op == "list_pipeline_executions":
            return await _execution_scroll(data, context, lease, project=cfg.project_id, limit=cfg.limit, environment=cfg.environment_name, search=cfg.pipeline_name_search, status=cfg.status_filter, continuation=cfg.continuation)
        if op == "get_pipeline_execution_metadata":
            return {"execution": await _get_execution(data, context, lease, cfg.project_id, cfg.pipeline_execution_id)}
        if op == "get_pipeline_execution_status":
            raw = await _request(data, context, lease, f"/v1/projects/{cfg.project_id}/pipeline-executions/{cfg.pipeline_execution_id}/status")
            return {"project_id": cfg.project_id, "pipeline_execution_id": cfg.pipeline_execution_id, "parent_scope_source": "protected_request_route", "execution_status": _status(raw.get("status"))}
        if op in ("list_execution_steps", "list_execution_tasks"):
            await _get_execution(data, context, lease, cfg.project_id, cfg.pipeline_execution_id)
            params = {"page": cfg.page, "size": cfg.size}
            if op == "list_execution_tasks" and cfg.status_filter:
                params["status"] = cfg.status_filter
            kind = "step" if op == "list_execution_steps" else "task"
            result = _page(await _request(data, context, lease, f"/v1/projects/{cfg.project_id}/pipeline-executions/{cfg.pipeline_execution_id}/" + ("steps" if kind == "step" else "tasks"), params=params), cfg.page, cfg.size, lambda row: _project(row, kind))
            return {"project_id": cfg.project_id, "root_pipeline_execution_id": cfg.pipeline_execution_id, "parent_scope_source": "protected_request_route", **result}
        if op == "start_pipeline_execution":
            await _find_named(data, context, lease, f"/v1/projects/{cfg.project_id}/environments", "environment", cfg.environment_name)
            await _find_named(data, context, lease, f"/v1/projects/{cfg.project_id}/published-pipelines", "pipeline", cfg.pipeline_name, {"environmentName": cfg.environment_name})
            body = {"environmentName": cfg.environment_name, "pipelineName": cfg.pipeline_name}
            if cfg.version_name:
                artifact = await _artifact_details(data, context, lease, cfg.project_id, cfg.environment_name, cfg.version_name)
                if not artifact["enabled"]:
                    raise ValueError("Selected artifact is disabled; no execution was started")
                body["versionName"] = cfg.version_name
            if cfg.execution_tag:
                body["executionTag"] = cfg.execution_tag
            raw = await _request(data, context, lease, f"/v1/projects/{cfg.project_id}/pipeline-executions", method="POST", body=body)
            try:
                identifier = _identifier(raw.get("pipelineExecutionId"))
            except ValueError:
                raise MatillionAPIError("Maia execution acknowledgement ID is unverified; independently inspect the owned environment before retrying") from None
            return {"accepted": True, "http_status": 201, "project_id": cfg.project_id, "environment_name": cfg.environment_name, "pipeline_execution_id": identifier, "execution_completed": False, "independent_readback_verified": False}
        if op == "cancel_pipeline_execution":
            existing = await _get_execution(data, context, lease, cfg.project_id, cfg.pipeline_execution_id)
            if existing["status"] not in ("RUNNING", "CANCELLING"):
                raise ValueError("Only a current running/cancelling scoped execution can be cancelled")
            raw = await _request(data, context, lease, f"/v1/projects/{cfg.project_id}/pipeline-executions/{cfg.pipeline_execution_id}", method="PATCH", body={"forceUpdate": cfg.force_termination, "status": "CANCELLED"})
            try:
                acknowledged = _identifier(raw.get("pipelineExecutionId"))
            except ValueError:
                raise MatillionAPIError("Maia cancellation acknowledgement ID is unverified; outcome is unknown and no replay occurs") from None
            if acknowledged != cfg.pipeline_execution_id:
                raise MatillionAPIError("Maia cancellation acknowledgement ID is unverified; outcome is unknown and no replay occurs")
            return {"accepted": True, "http_status": 200, "project_id": cfg.project_id, "pipeline_execution_id": cfg.pipeline_execution_id, "force_requested": cfg.force_termination, "cancellation_completed": False, "data_rollback_verified": False, "independent_readback_verified": False}
        raise ValueError("Unsupported Maia native operation")

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        if field_name not in ("project_id", "environment_name", "pipeline_name", "version_name", "pipeline_execution_id"):
            return {"options": [], "next_page_token": None}
        context = _context(credential_data, context or {})
        if search is not None and not isinstance(search, str):
            raise ValueError("Use a string Maia picker search")
        query = (search or "").strip()
        if len(query) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in query):
            raise ValueError("Use a bounded Maia picker search")
        # Validate all parent scope before loading/decrypting credentials or minting.
        project = _uuid(context.get("project_id")) if field_name != "project_id" else None
        environment = _name(context.get("environment_name")) if field_name in ("pipeline_name", "version_name") else None
        data = await _current_data(credential_data, **_authority(context))
        binding = _continuation_binding(data, context, ["picker", field_name, project, environment, query])
        page, seen, execution_continuation = 0, [], None
        if page_token:
            saved = _unpack(page_token, binding, {"page", "seen", "execution_continuation"})
            if type(saved["page"]) is not int or not 1 <= saved["page"] <= 39 or not isinstance(saved["seen"], list) or len(saved["seen"]) >= MAX_ROWS or any(not isinstance(v, str) or len(v) > 255 for v in saved["seen"]):
                raise ValueError("Maia picker continuation is invalid")
            page, seen, execution_continuation = saved["page"], saved["seen"], saved["execution_continuation"]
            if (field_name == "pipeline_execution_id" and (seen or not isinstance(execution_continuation, str) or not execution_continuation)) or (field_name != "pipeline_execution_id" and execution_continuation is not None):
                raise ValueError("Maia picker continuation shape is invalid")
            if len(set(seen)) != len(seen):
                raise ValueError("Maia picker continuation repeats resource identifiers")
        lease = await _lease(data, context)
        while page < 40:
            if field_name == "pipeline_execution_id":
                result = await _execution_scroll(data, context, lease, project=project, limit=25, search=query or None, continuation=execution_continuation)
                rows = result["results"]
                execution_continuation = result["next_continuation"]
                more = execution_continuation is not None
            else:
                routes = {"project_id": ("/v1/projects", "project"), "environment_name": (f"/v1/projects/{project}/environments", "environment"), "pipeline_name": (f"/v1/projects/{project}/published-pipelines", "pipeline"), "version_name": (f"/v1/projects/{project}/artifacts", "artifact")}
                route, kind = routes[field_name]
                params = {"page": page, "size": 25, **({"environmentName": environment} if environment else {}), **({"enabledOnly": "false"} if field_name == "version_name" else {})}
                result = _page(await _request(data, context, lease, route, params=params), page, 25, lambda row: _project(row, kind))
                rows, more = result["results"], not result["collection_exhausted"]
            keys = [_row_key(row) for row in rows]
            if set(seen).intersection(keys):
                raise MatillionAPIError("Maia picker repeats identifiers across pages; restart it")
            if field_name != "pipeline_execution_id":
                seen += keys  # Execution scrolling already tracks its own cross-page IDs.
            selected = [row for row in rows if field_name == "pipeline_execution_id" or not query or query.casefold() in str(row.get("name", row.get("versionName", ""))).casefold()]
            page += 1
            if more and (page >= 40 or len(seen) >= MAX_ROWS):
                raise MatillionAPIError("Maia picker reached its 1,000-item bound before exhaustion; narrow the search or supply an exact scoped resource")
            token = _pack({"binding": binding, "page": page, "seen": seen, "execution_continuation": execution_continuation}) if more else None
            if token and len(token) > 24000:
                raise MatillionAPIError("Maia picker continuation exceeds its local bound")
            if selected or not more:
                options = []
                for row in selected:
                    value = row["id"] if field_name == "project_id" else row["pipelineExecutionId"] if field_name == "pipeline_execution_id" else row["versionName"] if field_name == "version_name" else row["name"]
                    label = row.get("name", row.get("pipelineName", row.get("versionName", value)))
                    if field_name == "pipeline_execution_id":
                        label += " (" + row["status"] + ")"
                    options.append({"value": value, "label": label})
                return {"options": options, "next_page_token": token}
        raise MatillionAPIError("Maia picker did not establish exhaustion within its local bound")
