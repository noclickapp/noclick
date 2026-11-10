"""ProductPlan v2 protected roadmap metadata and ordinary parked-bar CRUD.

Existing user-bound tokens only; no health-check identity, arbitrary REST,
sharing changes, unpark controls, invitations or customer synchronization.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote, quote_plus

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, ValidationResult, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from utils import ssrf
from repositories.credentials import credential_access_predicate

NODE_TYPE = "automation-productplan"
FAMILIES = ("productplan_pat",)
BASE_URL = "https://app.productplan.com/api/v2"
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 1000
MAX_ID = 9223372036854775807
WRITE_OPS = ("create_bar", "update_bar", "delete_bar")


class _ProductPlanPublicBackend(ssrf._PinnedNetworkBackend):
    """Pin public DNS results even when staging permits private development hosts."""
    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        addresses = await ssrf._resolve_host_addresses(host, port)
        last_error = None
        for address in addresses:
            try:
                return await self._backend.connect_tcp(address, port, timeout=timeout,
                    local_address=local_address, socket_options=socket_options)
            except Exception as exc:
                last_error = exc
        raise last_error


def guarded_async_client(**kwargs):
    async def public_request(request):
        if request.url.scheme != "https" or request.url.host != "app.productplan.com" or request.url.port not in (None, 443):
            raise ValueError("Unsupported ProductPlan origin")
        await ssrf._resolve_host_addresses(request.url.host, 443)
    transport = kwargs.pop("transport", None)
    if transport is None:
        transport = httpx.AsyncHTTPTransport(trust_env=False)
        if not hasattr(transport._pool, "_network_backend"):
            raise RuntimeError("ProductPlan transport cannot pin DNS")
        transport._pool._network_backend = _ProductPlanPublicBackend()
    elif not isinstance(transport, httpx.MockTransport):
        raise ValueError("Unsupported ProductPlan test transport")
    return httpx.AsyncClient(transport=transport, event_hooks={"request": [public_request]}, **kwargs)


@dataclass(frozen=True)
class ProductPlanCredentialRow:
    credential_type: Optional[str]
    owner_id: str
    token_version: int
    updated_at: datetime
    approval_revision: int
    revoked_at: Optional[datetime]
    credential: Any = field(repr=False)


class ProductPlanCredentialsRepo:
    """Node-local authority read using staging's canonical credential ACL."""
    def __init__(self, pool):
        self._pool = pool

    async def fetch_validation_authority(self, credential_id, user_id, org_id):
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT c.credential_type,c.owner_id,c.token_version,c.updated_at,"
                f"c.approval_revision,c.revoked_at,c.credential FROM credentials c "
                f"WHERE c.id=$1 AND {credential_access_predicate()}",
                credential_id, user_id, org_id)
        return ProductPlanCredentialRow(**{**dict(row), "owner_id": str(row["owner_id"])}) if row else None

def _token(value):
    if not isinstance(value, str) or len(value) != 64 or any(ord(c) <= 32 or ord(c) >= 127 for c in value):
        raise ValueError("Supply the existing 64-character ProductPlan API token, without Bearer")
    return value


class ProductPlanPATCredential(BaseModel):
    credential_type: Literal["productplan_pat"] = Field("productplan_pat", json_schema_extra={"ui:hidden": True})
    personal_access_token: str = Field(..., title="Existing API Token", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(extra="ignore", json_schema_extra={
        "x-credential-url": "https://productplan.readme.io/reference/authentication",
        "x-credential-instructions": "Supply an existing user-bound ProductPlan API token. Sent as Authorization: Bearer TOKEN to app.productplan.com/api/v2. API/plan access and resource permissions depend on the account; a protected read does not prove write access or account identity. No token creation, OAuth, refresh or environment fallback.",
    })
    _secret = field_validator("personal_access_token")(_token)


def _op(name, label, category):
    return Field(name, title=label, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})


def _whole(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,19}", value):
        value = int(value)
    if type(value) is not int:
        raise ValueError("Use a whole positive resource ID or page number")
    return value


def _text(value):
    if value is not None and (not isinstance(value, str) or not value.strip() or any(ord(c) < 32 and c not in "\n\r\t" or ord(c) == 127 for c in value)):
        raise ValueError("Use bounded nonempty text")
    return value


def _date(value):
    if value is not None:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Use YYYY-MM-DD")
        date.fromisoformat(value)
    return value


def _dynamic(name, parent=None):
    result = {"x-dynamic-options": {"field_name": name, "searchable": True, "allow_custom": True}, "x-resource-type": "productplan_" + name.removesuffix("_id"), "x-resource-id-path": name}
    if parent:
        result["x-dynamic-options"]["depends_on"] = parent
    return result


class ProductPlanOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductPlanCheckConfig(ProductPlanOperation):
    operation: Literal["test_connection"] = _op("test_connection", "Check Protected Roadmap Access", "Connection")


class ProductPlanPageConfig(ProductPlanOperation):
    page: int = Field(1, ge=1, le=100000, description="Explicit v2 page number. No automatic full collection traversal.")
    page_size: int = Field(50, ge=1, le=500, description="ProductPlan documented maximum: 500 items per page.")
    search: Optional[str] = Field(None, max_length=128, description="Name substring, encoded using the documented bracket-filter parameter. Key results accept an exact numeric ID instead.")
    _pages = field_validator("page", "page_size", mode="before")(_whole)
    _search = field_validator("search")(_text)


class ProductPlanRoadmapScope(ProductPlanOperation):
    roadmap_id: int = Field(..., ge=1, le=MAX_ID, title="Roadmap", json_schema_extra=_dynamic("roadmap_id"))
    _roadmap = field_validator("roadmap_id", mode="before")(_whole)


class ProductPlanBarScope(ProductPlanRoadmapScope):
    bar_id: int = Field(..., ge=1, le=MAX_ID, title="Bar", json_schema_extra=_dynamic("bar_id", "roadmap_id"))
    _bar = field_validator("bar_id", mode="before")(_whole)


class ProductPlanListRoadmapsConfig(ProductPlanPageConfig):
    operation: Literal["list_roadmaps"] = _op("list_roadmaps", "List Roadmaps", "Roadmaps")
    owned_only: bool = Field(False, description="Exclude roadmaps shared with this token's user.")
    edit_only: bool = Field(False, description="Request only roadmaps the token's user can edit; writes still verify current roadmap permission.")


class ProductPlanGetRoadmapConfig(ProductPlanRoadmapScope):
    operation: Literal["get_roadmap"] = _op("get_roadmap", "Get Roadmap Metadata", "Roadmaps")


class ProductPlanListBarsConfig(ProductPlanPageConfig, ProductPlanRoadmapScope):
    operation: Literal["list_roadmap_bars"] = _op("list_roadmap_bars", "List Roadmap Bars", "Bars")


class ProductPlanGetBarConfig(ProductPlanBarScope):
    operation: Literal["get_bar"] = _op("get_bar", "Get Scoped Bar Metadata", "Bars")


class ProductPlanCreateBarConfig(ProductPlanRoadmapScope):
    operation: Literal["create_bar"] = _op("create_bar", "Create Parked Bar", "Bars")
    confirm_mutation: bool = Field(False, description="Confirm an owned roadmap change. New bars stay parked; notification behavior is not verified.")
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=4000, json_schema_extra={"ui:widget": "textarea"})
    starts_on: Optional[str] = Field(None, description="YYYY-MM-DD; omitted when blank.")
    ends_on: Optional[str] = Field(None, description="YYYY-MM-DD; omitted when blank.")
    percent_done: Optional[int] = Field(None, ge=0, le=100)
    tags: list[str] = Field(default_factory=list, max_length=50, json_schema_extra={"ui:widget": "list"})
    lane: Optional[str] = Field(None, max_length=128, description="Exact lane name from the current roadmap, if supplied.")
    legend: Optional[str] = Field(None, max_length=128, description="Exact legend name from the current roadmap, if supplied.")
    _text_fields = field_validator("name", "description", "lane", "legend")(_text)
    _dates = field_validator("starts_on", "ends_on")(_date)

    @field_validator("percent_done", mode="before")
    @classmethod
    def whole_progress(cls, value):
        return _whole(value) if value is not None else None

    @field_validator("tags")
    @classmethod
    def bounded_tags(cls, value):
        if len(set(value)) != len(value) or any(not isinstance(v, str) or not v.strip() or len(v) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in v) for v in value):
            raise ValueError("Use distinct nonempty tags of at most 128 characters")
        return value

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.starts_on and self.ends_on and self.starts_on > self.ends_on:
            raise ValueError("The start date must precede or equal the end date")
        return self


class ProductPlanUpdateBarConfig(ProductPlanBarScope):
    operation: Literal["update_bar"] = _op("update_bar", "Update Bar Metadata", "Bars")
    confirm_mutation: bool = Field(False, description="Confirm a scoped metadata change. Untouched fields are omitted; notifications are not verified.")
    new_name: Optional[str] = Field(None, max_length=200)
    description_mode: Literal["keep", "set", "clear"] = Field("keep")
    description: Optional[str] = Field(None, max_length=4000, json_schema_extra={"ui:widget": "textarea"})
    progress_mode: Literal["keep", "set", "clear"] = Field("keep")
    percent_done: Optional[int] = Field(None, ge=0, le=100)
    tags_mode: Literal["keep", "set", "clear"] = Field("keep")
    tags: list[str] = Field(default_factory=list, max_length=50, json_schema_extra={"ui:widget": "list"})
    _text_fields = field_validator("new_name", "description")(_text)
    _progress = field_validator("percent_done", mode="before")(ProductPlanCreateBarConfig.whole_progress.__func__)
    _tags = field_validator("tags")(ProductPlanCreateBarConfig.bounded_tags.__func__)


class ProductPlanDeleteBarConfig(ProductPlanBarScope):
    operation: Literal["delete_bar"] = _op("delete_bar", "Delete Leaf Bar", "Bars")
    confirm_mutation: bool = Field(False, description="Confirm owned disposable leaf-bar cleanup. Containers or bars with children are refused. HTTP 204 does not prove absence.")


class ProductPlanObjectiveScope(ProductPlanOperation):
    objective_id: int = Field(..., ge=1, le=MAX_ID, title="Objective", json_schema_extra=_dynamic("objective_id"))
    _objective = field_validator("objective_id", mode="before")(_whole)


class ProductPlanListObjectivesConfig(ProductPlanPageConfig):
    operation: Literal["list_objectives"] = _op("list_objectives", "List Objectives", "Strategy")


class ProductPlanGetObjectiveConfig(ProductPlanObjectiveScope):
    operation: Literal["get_objective"] = _op("get_objective", "Get Objective Metadata", "Strategy")


class ProductPlanListKeyResultsConfig(ProductPlanPageConfig, ProductPlanObjectiveScope):
    operation: Literal["list_key_results"] = _op("list_key_results", "List Objective Key Results", "Strategy")


class ProductPlanGetKeyResultConfig(ProductPlanObjectiveScope):
    operation: Literal["get_key_result"] = _op("get_key_result", "Get Scoped Key Result", "Strategy")
    key_result_id: int = Field(..., ge=1, le=MAX_ID, title="Key Result", json_schema_extra=_dynamic("key_result_id", "objective_id"))
    _key_result = field_validator("key_result_id", mode="before")(_whole)


class ProductPlanListIdeasConfig(ProductPlanPageConfig):
    operation: Literal["list_ideas"] = _op("list_ideas", "List Idea Metadata", "Discovery")


class ProductPlanGetIdeaConfig(ProductPlanOperation):
    operation: Literal["get_idea"] = _op("get_idea", "Get Idea Metadata", "Discovery")
    idea_id: int = Field(..., ge=1, le=MAX_ID, title="Idea", json_schema_extra=_dynamic("idea_id"))
    _idea = field_validator("idea_id", mode="before")(_whole)


class ProductPlanLaunchScope(ProductPlanOperation):
    launch_id: int = Field(..., ge=1, le=MAX_ID, title="Launch", json_schema_extra=_dynamic("launch_id"))
    _launch = field_validator("launch_id", mode="before")(_whole)


class ProductPlanListLaunchesConfig(ProductPlanPageConfig):
    operation: Literal["list_launches"] = _op("list_launches", "List Launch Metadata", "Launches")


class ProductPlanGetLaunchConfig(ProductPlanLaunchScope):
    operation: Literal["get_launch"] = _op("get_launch", "Get Launch Metadata", "Launches")


class ProductPlanListTasksConfig(ProductPlanPageConfig, ProductPlanLaunchScope):
    operation: Literal["list_launch_tasks"] = _op("list_launch_tasks", "List Launch Task Metadata", "Launches")


class ProductPlanListTeamsConfig(ProductPlanPageConfig):
    operation: Literal["list_teams"] = _op("list_teams", "List Teams", "Teams")


ProductPlanConfig = Annotated[Union[ProductPlanCheckConfig, ProductPlanListRoadmapsConfig, ProductPlanGetRoadmapConfig, ProductPlanListBarsConfig, ProductPlanGetBarConfig, ProductPlanCreateBarConfig, ProductPlanUpdateBarConfig, ProductPlanDeleteBarConfig, ProductPlanListObjectivesConfig, ProductPlanGetObjectiveConfig, ProductPlanListKeyResultsConfig, ProductPlanGetKeyResultConfig, ProductPlanListIdeasConfig, ProductPlanGetIdeaConfig, ProductPlanListLaunchesConfig, ProductPlanGetLaunchConfig, ProductPlanListTasksConfig, ProductPlanListTeamsConfig], Field(discriminator="operation")]


class ProductPlanNodeConfig(NodeConfig[ProductPlanConfig, ProductPlanPATCredential]):
    pass


class ProductPlanAPIError(ValueError):
    def __init__(self, message, *, authority_rejected=False):
        super().__init__(message)
        self.authority_rejected = authority_rejected


def _shape(data):
    if not isinstance(data, dict) or data.get("credential_type") not in (None, FAMILIES[0]):
        raise ValueError("ProductPlan credential family is unsupported")
    try:
        shaped = ProductPlanPATCredential.model_validate({**data, "credential_type": FAMILIES[0]}).model_dump()
    except Exception:
        raise ValueError("ProductPlan requires its existing issued API token") from None
    return {**data, **shaped}


def _original_family(data):
    if not isinstance(data, dict):
        raise ValueError("ProductPlan configuration is invalid")
    creds = data.get("credentials")
    saved = data.get("credential_id") or data.get("credentialIds")
    if saved and not isinstance(creds, dict) or isinstance(creds, dict) and (creds.get("credential_type") is not None or saved) and creds.get("credential_type") not in FAMILIES:
        raise ValueError("ProductPlan saved credential family is missing or unsupported")


def _secret(data):
    return data["personal_access_token"]


def _binding(data):
    return (data["credential_type"], _secret(data), data.get("owner_id"), data.get("token_version"), data.get("updated_at"), data.get("approval_revision"))


@dataclass(frozen=True, repr=False)
class _LookupAuthority:
    pool: Any
    user_id: str
    credential_id: str
    organization_id: Optional[str]
    workflow_id: Optional[str]


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
        row = await ProductPlanCredentialsRepo(actual_pool).fetch_validation_authority(cid, principal, org_id)
        if row is None:
            return None
        if row.revoked_at is not None or row.credential_type not in FAMILIES or not isinstance(row.owner_id, str) or not row.owner_id or type(row.token_version) is not int or row.token_version < 1 or type(row.approval_revision) is not int or row.approval_revision < 0:
            raise ValueError("ProductPlan current credential is unavailable, revoked or its family is unsupported")
        try:
            blob = get_encryption().decrypt_credential(row.credential)
        except Exception:
            raise ValueError("ProductPlan current credential could not be decrypted") from None
        if not isinstance(blob, dict):
            raise ValueError("ProductPlan current credential data is invalid")
        return _shape({**blob, "credential_type": row.credential_type, "owner_id": row.owner_id, "token_version": row.token_version, "updated_at": row.updated_at.isoformat() if row.updated_at else None, "approval_revision": row.approval_revision})
    result = await load(credential_id, user_id, pool, organization_id)
    if result is None and workflow_id:
        owner = await get_workflow_owner_id(pool, workflow_id)
        if owner and owner != user_id and await is_credential_authorized_for_workflow(pool, workflow_id, credential_id):
            result = await load(credential_id, owner, pool, organization_id)
    if result is None and workflow_id:
        lender = await credential_lender(pool, workflow_id, credential_id)
        if lender and lender != str(user_id):
            result = await load(credential_id, lender, pool, organization_id)
    if result is None:
        raise ValueError("ProductPlan current credential is unavailable or access denied")
    return {**result, "_productplan_authority": _LookupAuthority(pool, user_id, credential_id, organization_id, workflow_id)}


def _context(data, context):
    result = {k: v for k, v in context.items() if not k.startswith("_")}
    result["_user_id"] = context.get("_user_id")
    bound = data.get("_productplan_authority") if isinstance(data, dict) else None
    if type(bound) is _LookupAuthority:
        if bound.user_id != context.get("_user_id"):
            raise ValueError("ProductPlan picker actor does not match saved authority")
        result.update({"_approval_pool": bound.pool, "_user_id": bound.user_id, "_credential_id": bound.credential_id, "_organization_id": bound.organization_id, "_workflow_id": bound.workflow_id or context.get("_workflow_id")})
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
        return re.sub(r"(?i)([?&](?:access_token|api_key|token|signature|auth|key)=)[^&#\s]+", r"\1[redacted]", value)
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


def _route_allowed(route, method):
    if method == "POST":
        return route == "/bars"
    if method in ("PATCH", "DELETE"):
        return re.fullmatch(r"/bars/[1-9][0-9]{0,18}", route) is not None
    if method != "GET":
        return False
    return route in ("/roadmaps", "/strategy/objectives", "/discovery/ideas", "/launches", "/teams") or re.fullmatch(r"/roadmaps/[1-9][0-9]{0,18}(?:/bars)?|/bars/[1-9][0-9]{0,18}|/strategy/objectives/[1-9][0-9]{0,18}(?:/key_results(?:/[1-9][0-9]{0,18})?)?|/discovery/ideas/[1-9][0-9]{0,18}|/launches/[1-9][0-9]{0,18}(?:/tasks)?", route) is not None


async def _request(data, context, route, *, method="GET", params=None, body=None):
    write = method != "GET"
    if not _route_allowed(route, method) or method in ("POST", "PATCH") and not isinstance(body, dict) or method in ("GET", "DELETE") and body is not None:
        raise ValueError("Unsupported ProductPlan native route or effect")
    current = await _current_data(data, **_authority(context))
    if _binding(current) != _binding(data):
        raise ValueError("ProductPlan current credential changed; rerun with current authority")
    suffix = " Write outcome is unverified; independently inspect the owned bar before retrying." if write else ""
    if body is not None:
        _bounded(body)
        if len(json.dumps(body, allow_nan=False).encode()) > 16384:
            raise ValueError("ProductPlan bar payload exceeds the local bound; no request was sent")
    expected = 201 if method == "POST" else 204 if write else 200
    try:
        async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, BASE_URL + route,
                                     headers={"Authorization": "Bearer " + _secret(current), "Accept": "application/json", **({"Content-Type": "application/json"} if body is not None else {})},
                                     **({"params": params} if params else {}), **({"json": body} if body is not None else {})) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(raw) + len(chunk) > MAX_BYTES:
                        raise ProductPlanAPIError("ProductPlan response exceeds the local byte bound." + suffix)
                    raw.extend(chunk)
                if response.status_code in (401, 403):
                    raise ProductPlanAPIError(f"ProductPlan HTTP {response.status_code}: authority rejected." + suffix, authority_rejected=True)
                if response.status_code != expected:
                    raise ProductPlanAPIError(f"ProductPlan HTTP {response.status_code}: documented success is unverified." + suffix)
                if expected == 204:
                    if raw:
                        raise ProductPlanAPIError("ProductPlan 204 response unexpectedly contains a body." + suffix)
                    return None
                if expected == 201 and not raw:
                    return None
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ProductPlanAPIError("ProductPlan documented JSON response is unverified." + suffix)
                try:
                    result = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    _bounded(result)
                except (ValueError, UnicodeError, RecursionError):
                    raise ProductPlanAPIError("ProductPlan response JSON is unverified." + suffix) from None
                if not isinstance(result, dict) or result.get("errors") or result.get("status") in ("error", "rejected", "pending_approval", "not_executed", "forbidden"):
                    raise ProductPlanAPIError("ProductPlan returned an unsuccessful or unverified response." + suffix)
                # POST has no published success-body schema: discard all optional body data.
                return None if expected == 201 else result
    except ProductPlanAPIError:
        raise
    except (httpx.HTTPError, OSError, ValueError, UnicodeError):
        raise ProductPlanAPIError("ProductPlan transport failed; result is unverified." + suffix) from None


def _id(value):
    if type(value) is not int or not 1 <= value <= MAX_ID:
        raise ProductPlanAPIError("ProductPlan resource identifier is unverified")
    return value


def _project(row, kind, *, wanted=None, parent=None):
    if not isinstance(row, dict):
        raise ProductPlanAPIError("ProductPlan selected metadata is unverified")
    identifier = _id(row.get("id"))
    if wanted is not None and identifier != wanted:
        raise ProductPlanAPIError("ProductPlan returned another resource")
    fields = {
        "roadmap": {"name": str, "permission": str, "is_version": bool, "created_at": str, "updated_at": str},
        "bar": {"name": str, "starts_on": str, "ends_on": str, "percent_done": int, "lane": str, "legend": str, "parked": bool, "is_container": bool, "child_bar_count": int, "created_at": str, "updated_at": str},
        "objective": {"name": str, "subject": str, "risk_status": str, "location_status": str, "start_date": str, "end_date": str, "key_results_count": int, "bar_count": int, "opportunity_count": int, "created_at": str, "updated_at": str},
        "key_result": {"start": "number", "target": "number", "current": "number", "progress": int, "type": str, "created_at": str, "updated_at": str},
        "idea": {"name": str, "location_status": str, "opportunities_count": int, "created_at": str, "updated_at": str},
        "launch": {"name": str, "launch_date": str, "status": str, "progress": int, "bar_count": int, "checklist_section_count": int, "task_count": int, "created_at": str, "updated_at": str},
        "task": {"name": str, "status": str, "due_date": str, "checklist_section_id": int},
        "team": {"name": str},
    }[kind]
    out = {"id": identifier}
    for key, expected in fields.items():
        if key not in row:
            continue
        value = row[key]
        if value is None:
            out[key] = None
            continue
        correct = type(value) in (int, float) and math.isfinite(value) if expected == "number" else type(value) is expected
        if not correct or isinstance(value, str) and (len(value) > 1024 or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ProductPlanAPIError("ProductPlan selected field is unverified")
        if type(value) is int and (abs(value) > MAX_ID or key.endswith("_count") and value < 0 or key == "checklist_section_id" and value < 1):
            raise ProductPlanAPIError("ProductPlan selected integer is unverified")
        out[key] = value
    if kind != "key_result" and (not isinstance(out.get("name"), str) or not out["name"].strip()):
        raise ProductPlanAPIError("ProductPlan resource name is unverified")
    choices = {
        "roadmap": {"permission": ("owner", "editor", "viewer")},
        "objective": {"risk_status": ("low_risk", "medium_risk", "high_risk"), "location_status": ("active", "archived")},
        "key_result": {"type": ("PercentResult", "MoneyResult", "NumberResult")},
        "idea": {"location_status": ("visible", "archived")},
        "launch": {"status": ("low_risk", "medium_risk", "high_risk", "launched")},
        "task": {"status": ("to_do", "in_progress", "completed", "blocked")},
    }.get(kind, {})
    for key, allowed in choices.items():
        if key not in row or row[key] is None and not (key == "risk_status" or kind == "launch" and key == "status") or row[key] is not None and row[key] not in allowed:
            raise ProductPlanAPIError("ProductPlan resource status or permission is unverified")
    for key in ("percent_done",):
        if out.get(key) is not None and not 0 <= out[key] <= 100:
            raise ProductPlanAPIError("ProductPlan progress is unverified")
    if kind == "key_result" and any(key not in out or out[key] is None for key in ("start", "target", "current", "progress", "type")):
        raise ProductPlanAPIError("ProductPlan key-result metrics are unverified")
    if kind == "roadmap" and type(row.get("is_version")) is not bool:
        raise ProductPlanAPIError("ProductPlan roadmap version marker is unverified")
    if kind == "bar":
        reference = row.get("roadmap")
        if not isinstance(reference, dict) or _id(reference.get("id")) != parent:
            raise ProductPlanAPIError("ProductPlan bar does not belong to the selected roadmap")
        if type(row.get("parked")) is not bool or type(row.get("is_container")) is not bool or type(row.get("child_bar_count")) is not int or row["child_bar_count"] < 0:
            raise ProductPlanAPIError("ProductPlan bar structure is unverified")
        out["roadmap_id"] = reference["id"]
    if kind in ("bar", "idea") and "tags" in row:
        tags = row["tags"]
        if not isinstance(tags, list) or len(tags) > 100 or any(not isinstance(v, str) or len(v) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in v) for v in tags):
            raise ProductPlanAPIError("ProductPlan tag metadata is unverified")
        out["tags"] = tags
    return out


def _page(result, kind, page, size, *, parent=None):
    rows, paging = result.get("results"), result.get("paging")
    if not isinstance(rows, list) or len(rows) > size or not isinstance(paging, dict) or any(type(paging.get(k)) is not int or not 0 <= paging[k] <= MAX_ID for k in ("record_count", "page_count", "current_page", "page_size")):
        raise ProductPlanAPIError("ProductPlan collection or paging metadata is unverified")
    count, pages = paging["record_count"], paging["page_count"]
    if paging["current_page"] != page or paging["page_size"] != len(rows) or count < len(rows) or count and (pages < page or not rows or count > pages * size or (page - 1) * size + len(rows) > count or page == pages and (page - 1) * size + len(rows) != count) or not count and (rows or pages not in (0, 1) or page != 1):
        raise ProductPlanAPIError("ProductPlan page counters are inconsistent; exhaustion is unverified")
    out = [_project(row, kind, parent=parent) for row in rows]
    if len({r["id"] for r in out}) != len(out):
        raise ProductPlanAPIError("ProductPlan page repeats resource identifiers")
    return {"results": out, "paging": {k: paging[k] for k in ("record_count", "page_count", "current_page", "page_size")}, "next_page": page + 1 if page < pages else None, "collection_exhausted": page >= pages}


COLLECTIONS = {
    "roadmap_id": ("/roadmaps", "roadmap", None, "name_i_cont"),
    "bar_id": ("/roadmaps/{parent}/bars", "bar", "roadmap_id", "name_i_cont"),
    "objective_id": ("/strategy/objectives", "objective", None, "label_name_i_cont"),
    "key_result_id": ("/strategy/objectives/{parent}/key_results", "key_result", "objective_id", "id_eq"),
    "idea_id": ("/discovery/ideas", "idea", None, "name_i_cont"),
    "launch_id": ("/launches", "launch", None, "name_i_cont"),
}
LIST_FIELDS = {"list_roadmaps": "roadmap_id", "list_roadmap_bars": "bar_id", "list_objectives": "objective_id", "list_key_results": "key_result_id", "list_ideas": "idea_id", "list_launches": "launch_id"}


def _query(page, size, search, field):
    params = {"page": page, "page_size": size}
    if field == "roadmap_id":
        params["q[is_version_eq]"] = "false"
    if search:
        filter_name = COLLECTIONS[field][3] if field in COLLECTIONS else "name_i_cont"
        if filter_name == "id_eq":
            try:
                params["q[id_eq]"] = _id(_whole(search))
            except ValueError:
                raise ValueError("Key-result search requires an exact positive numeric ID") from None
        else:
            params["q[" + filter_name + "]"] = search
    return params


async def _roadmap(data, context, identifier, *, write=False):
    raw = await _request(data, context, "/roadmaps/" + str(identifier))
    _project(raw, "roadmap", wanted=identifier)
    if write and raw.get("permission") not in ("owner", "editor"):
        raise ValueError("The current roadmap permission does not allow a bar change")
    return raw


def _updates(cfg):
    body = {}
    if cfg.new_name is not None:
        body["name"] = cfg.new_name
    for mode, field in ((cfg.description_mode, "description"), (cfg.progress_mode, "percent_done"), (cfg.tags_mode, "tags")):
        if mode == "clear":
            body[field] = [] if field == "tags" else None
        elif mode == "set":
            value = getattr(cfg, field)
            if value is None or field == "tags" and not value:
                raise ValueError("Set mode requires an explicit nonempty value; use Clear to clear")
            body[field] = value
    if not body:
        raise ValueError("Choose at least one bar metadata change; no request was sent")
    return body


class ProductPlanNode(WorkflowNode):
    integration_type = "automation-productplan"
    credential_provider_labels = {"productplan": "Productplan Account"}
    auto_select_credential = False
    node_type = NODE_TYPE
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="test_connection", noun="ProductPlan API access", proves="reachability")
    edit_examples = ["List bars within a selected roadmap", "Report objective key-result progress", "Create a confirmed parked bar in an editable owned roadmap"]

    @classmethod
    def get_config_model(cls):
        return ProductPlanNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        _original_family(config_data)
        shaped = dict(config_data)
        if config_data.get("credentials") is not None:
            shaped["credentials"] = _shape(config_data["credentials"])
        try:
            ProductPlanNodeConfig.model_validate(runtime_config_view(shaped, ProductPlanNodeConfig))
        except ValueError:
            raise ValueError("ProductPlan configuration is invalid; check token family and selected metadata scope") from None
        return super().parse_config(shaped)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _original_family(config_data)
            shaped = dict(config_data)
            if config_data.get("credentials") is not None:
                shaped["credentials"] = _shape(config_data["credentials"])
            ProductPlanNodeConfig.model_validate(runtime_config_view(shaped, ProductPlanNodeConfig))
        except (ValueError, TypeError):
            return ValidationResult(valid=False, errors=["ProductPlan configuration or credential family is invalid"], satisfied_set=None)
        return super().validate_config(shaped)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Staging freshens before it supplies the trusted workflow context to the
        # picker. Carry only server-supplied authority; load the row in the picker.
        if credential_id:
            return {**_shape(credential_data), "_productplan_authority": _LookupAuthority(
                pool, user_id, credential_id, None, None)}
        return _shape(credential_data)

    @classmethod
    async def validate_credential_access(cls, data, *, validation_context=None):
        try:
            _shape(data)
        except ValueError:
            return {"valid": False, "error": "ProductPlan credential shape is invalid"}
        # Staging's hook has no current-row context. Its connection-evidence
        # dispatcher performs the protected read with saved credential authority.
        return {"valid": None, "error": "Save and check current ProductPlan roadmap access"}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, ProductPlanNodeConfig) or self.config.credentials is None:
            raise ValueError("ProductPlan requires its explicit native credential and configuration")
        cfg = self.config.config
        if cfg.operation in WRITE_OPS and not cfg.confirm_mutation:
            raise ValueError("Confirm the owned ProductPlan bar operation")
        # Validate sparse intent before any read or provider transport.
        body = _updates(cfg) if cfg.operation == "update_bar" else None
        context = {"_approval_pool": (self.node_data or {}).get("_approval_pool"), "_credential_id": (self.node_data or {}).get("credential_id"), "_user_id": self.user_id, "_organization_id": self.organization_id, "_workflow_id": self.workflow_id}
        data = await _current_data(self.config.credentials.model_dump(), **_authority(context))
        result = await self._operation(cfg, data, context, body)
        return {"status": "success", "operation": cfg.operation, "data": _redact(result, _secret(data))}

    async def _operation(self, cfg, data, context, body=None):
        op = cfg.operation
        if op == "test_connection":
            page = _page(await _request(data, context, "/roadmaps", params=_query(1, 1, None, "roadmap_id")), "roadmap", 1, 1)
            return {"protected_read_completed": True, "account_identity_verified": False, "write_permission_verified": False, "roadmaps_returned": len(page["results"]), "collection_exhausted": page["collection_exhausted"]}
        if op == "get_roadmap":
            return {"roadmap": _project(await _roadmap(data, context, cfg.roadmap_id), "roadmap", wanted=cfg.roadmap_id)}
        if op in LIST_FIELDS:
            field = LIST_FIELDS[op]
            route, kind, parent_field, _ = COLLECTIONS[field]
            parent = getattr(cfg, parent_field) if parent_field else None
            if field == "bar_id":
                await _roadmap(data, context, parent)
            params = _query(cfg.page, cfg.page_size, cfg.search, field)
            if op == "list_roadmaps":
                params.update({"exclude_shared": str(cfg.owned_only).lower(), "edit_only": str(cfg.edit_only).lower()})
            page = _page(await _request(data, context, route.format(parent=parent), params=params), kind, cfg.page, cfg.page_size, parent=parent)
            return {**({parent_field: parent} if parent_field else {}), **page}
        if op == "get_bar":
            await _roadmap(data, context, cfg.roadmap_id)
            return {"bar": _project(await _request(data, context, "/bars/" + str(cfg.bar_id)), "bar", wanted=cfg.bar_id, parent=cfg.roadmap_id)}
        if op in WRITE_OPS:
            raw = await _roadmap(data, context, cfg.roadmap_id, write=True)
            if op == "create_bar":
                for field in ("lane", "legend"):
                    selected = getattr(cfg, field)
                    choices = raw.get("lanes" if field == "lane" else "legends")
                    if selected is not None and (not isinstance(choices, list) or selected not in choices):
                        raise ValueError("The selected lane or legend is not in the current roadmap metadata")
                body = {"roadmap_id": cfg.roadmap_id, "name": cfg.name, "parked": True, "is_container": False, "tags": cfg.tags}
                for field in ("description", "starts_on", "ends_on", "percent_done", "lane", "legend"):
                    if getattr(cfg, field) is not None:
                        body[field] = getattr(cfg, field)
                await _request(data, context, "/bars", method="POST", body=body)
                return {"accepted": True, "http_status": 201, "roadmap_id": cfg.roadmap_id, "created_id": None, "created_id_verified": False, "parked_requested": True, "independent_readback_verified": False, "notification_behavior_verified": False}
            bar = _project(await _request(data, context, "/bars/" + str(cfg.bar_id)), "bar", wanted=cfg.bar_id, parent=cfg.roadmap_id)
            if op == "delete_bar" and (bar["is_container"] or bar["child_bar_count"] != 0):
                raise ValueError("Only an owned leaf bar can be deleted; no write was sent")
            await _request(data, context, "/bars/" + str(cfg.bar_id), method="DELETE" if op == "delete_bar" else "PATCH", body=None if op == "delete_bar" else body)
            return {"accepted": True, "http_status": 204, "roadmap_id": cfg.roadmap_id, "bar_id": cfg.bar_id, "absence_verified": False, "independent_readback_verified": False, "notification_behavior_verified": False}
        details = {
            "get_objective": ("/strategy/objectives/", "objective_id", "objective"),
            "get_idea": ("/discovery/ideas/", "idea_id", "idea"),
            "get_launch": ("/launches/", "launch_id", "launch"),
        }
        if op in details:
            route, field, kind = details[op]
            identifier = getattr(cfg, field)
            return {kind: _project(await _request(data, context, route + str(identifier)), kind, wanted=identifier)}
        if op == "get_key_result":
            result = await _request(data, context, f"/strategy/objectives/{cfg.objective_id}/key_results/{cfg.key_result_id}")
            return {"objective_id": cfg.objective_id, "parent_scope_source": "protected_request_route", "key_result": _project(result, "key_result", wanted=cfg.key_result_id)}
        if op in ("list_launch_tasks", "list_teams"):
            parent = cfg.launch_id if op == "list_launch_tasks" else None
            route, kind = (f"/launches/{parent}/tasks", "task") if parent else ("/teams", "team")
            page = _page(await _request(data, context, route, params=_query(cfg.page, cfg.page_size, cfg.search, "task_id" if parent else "team_id")), kind, cfg.page, cfg.page_size)
            return {**({"launch_id": parent, "parent_scope_source": "protected_request_route"} if parent else {}), **page}
        raise ValueError("Unsupported ProductPlan native operation")

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        if field_name not in COLLECTIONS:
            return {"options": [], "next_page_token": None}
        context = _context(credential_data, context or {})
        if search is not None and not isinstance(search, str):
            raise ValueError("Use a string ProductPlan picker search")
        query = (search or "").strip()
        if len(query) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in query):
            raise ValueError("Use a bounded ProductPlan picker search")
        route, kind, parent_field, _ = COLLECTIONS[field_name]
        try:
            parent = _id(_whole(context.get(parent_field))) if parent_field else None
        except ValueError:
            raise ValueError("Select the required ProductPlan parent first") from None
        # Parent and query must be valid before current-row loading or decrypting.
        params = _query(1, 25, query, field_name)
        data = await _current_data(credential_data, **_authority(context))
        binding = hashlib.sha256(json.dumps([field_name, parent, query, context.get("_credential_id"), context.get("_user_id"), context.get("_organization_id"), context.get("_workflow_id"), _binding(data)], separators=(",", ":")).encode()).hexdigest()
        page, seen = 1, []
        if page_token:
            try:
                if not isinstance(page_token, str) or len(page_token) > 24000:
                    raise ValueError()
                saved = json.loads(base64.urlsafe_b64decode(page_token + "=" * (-len(page_token) % 4)))
                if not isinstance(saved, dict) or set(saved) != {"page", "binding", "seen"} or saved["binding"] != binding or type(saved["page"]) is not int or not 2 <= saved["page"] <= 40 or not isinstance(saved["seen"], list) or not 1 <= len(saved["seen"]) < MAX_ROWS or len(set(saved["seen"])) != len(saved["seen"]):
                    raise ValueError()
                for identifier in saved["seen"]:
                    _id(identifier)
                page, seen = saved["page"], saved["seen"]
            except (ValueError, TypeError, UnicodeError, RecursionError):
                raise ValueError("ProductPlan continuation belongs to another actor, credential, search or parent scope") from None
        if field_name == "bar_id":
            await _roadmap(data, context, parent)
        params["page"] = page
        result = _page(await _request(data, context, route.format(parent=parent), params=params), kind, page, 25, parent=parent)
        identifiers = [row["id"] for row in result["results"]]
        if set(seen).intersection(identifiers):
            raise ProductPlanAPIError("ProductPlan picker repeats identifiers across pages; restart the picker")
        seen += identifiers
        token = None
        if result["next_page"] is not None:
            if page >= 40 or len(seen) >= MAX_ROWS:
                raise ProductPlanAPIError("ProductPlan picker reached its 1,000-item bound before exhaustion; narrow the search or supply an exact scoped ID")
            token = base64.urlsafe_b64encode(json.dumps({"page": page + 1, "binding": binding, "seen": seen}, separators=(",", ":")).encode()).decode().rstrip("=")
        return {"options": [{"value": str(row["id"]), "label": (row.get("name") or "Key result") + " (" + str(row["id"]) + ")"} for row in result["results"]], "next_page_token": token}
