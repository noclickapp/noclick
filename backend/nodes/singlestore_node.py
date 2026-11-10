"""SingleStore Helios organization, project, cluster and Stage metadata workflows.

Closed Management API v2 routes never execute SQL, retrieve secrets or provision
compute. Directory writes are limited to metadata and checked empty folders.
"""
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import logging
import math
import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictStr, StrictBool, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import is_placeholder, is_url_shaped
from utils.ssrf import SSRFError, guarded_async_client

NODE_TYPE = "automation-singlestore"
FAMILIES = {"singlestore_management_api_key"}
API_URL = "https://api.singlestore.com/v2"
MAX_BYTES = 2_097_152
UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
ID = Annotated[StrictStr, Field(pattern=UUID_PATTERN)]
Name = Annotated[StrictStr, Field(min_length=1, max_length=200)]
Path = Annotated[StrictStr, Field(max_length=512)]
CLUSTER_FIELDS = "clusterID,name,projectID,groupID,provider,region,state,deploymentType,createdAt,lastResumedAt,terminatedAt,smartDRStatus,scalingProgress,kai,multiAZ"

def _dynamic(name, *parents):
    value = {"field_name": name, "allow_custom": True, "searchable": True}
    if parents:
        value["depends_on"] = list(parents)
    return {"x-dynamic-options": value}

def _path(value, *, folder=False, root=False):
    if not isinstance(value, str) or len(value) > 512 or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value) or any(c in value for c in "\\%?#"):
        raise ValueError("Use a plain relative Stage path without encoded separators or controls")
    if value == "" and root:
        return ""
    if not value or value.startswith("/") or "//" in value or (not folder and value.endswith("/")):
        raise ValueError("Use a non-root relative Stage path")
    parts = value.rstrip("/").split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise ValueError("Use Stage path segments without traversal")
    result = "/".join(parts) + ("/" if folder else "")
    if len(result) > 512:
        raise ValueError("Use a bounded Stage path")
    return result

class SingleStoreManagementCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"title": "SingleStore Management API",
            "x-credential-url": "https://docs.singlestore.com/cloud/reference/management-api/",
            "x-credential-instructions": "Use an issued hex-encoded Management API key for one organization and that organization's ID. The API key's existing permissions and expiration apply. No OAuth application, key minting or refresh is performed."})
    credential_type: Literal["singlestore_management_api_key"] = Field("singlestore_management_api_key", json_schema_extra={"ui:hidden": True})
    api_key: StrictStr = Field(..., min_length=1, max_length=4096, repr=False, title="Management API Key",
        json_schema_extra={"ui:widget": "password"})
    organization_id: ID = Field(..., title="SingleStore Organization ID",
        description="Expected orgID returned by the protected current-organization route. This key is bound to one organization.")

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        if is_placeholder(value) or is_url_shaped(value) or not re.fullmatch(r"[0-9a-fA-F]+", value):
            raise ValueError("Use an issued hex-encoded Management API key without a Bearer prefix")
        return value

    @field_validator("organization_id")
    @classmethod
    def org(cls, value):
        return value.lower()

def _credential(raw):
    if isinstance(raw, SingleStoreManagementCredential):
        return raw
    if not isinstance(raw, dict) or raw.get("credential_type") not in (None, *FAMILIES):
        raise ValueError("Connect SingleStore Management API credentials")
    return SingleStoreManagementCredential.model_validate(raw)

class _Config(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    @field_validator("*")
    @classmethod
    def clean(cls, value):
        if isinstance(value, str):
            if any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("Use metadata text without control characters")
            if re.fullmatch(UUID_PATTERN, value):
                return value.lower()
        return value

    @field_validator("name", check_fields=False)
    @classmethod
    def validate_project_name(cls, value):
        if not value.strip():
            raise ValueError("Use a nonblank project name")
        return value

    @field_validator("folder_path", "new_folder_path", check_fields=False)
    @classmethod
    def folder(cls, value):
        return _path(value, folder=True, root=True)

    @field_validator("file_path", check_fields=False)
    @classmethod
    def file(cls, value):
        return _path(value)

class GetOrganization(_Config):
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"ui:hidden": True})

class ListProjects(_Config):
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})

class GetProject(_Config):
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})
    project_id: ID = Field(..., json_schema_extra=_dynamic("project_id"))

class RenameProject(GetProject):
    operation: Literal["rename_project"] = Field("rename_project", json_schema_extra={"ui:hidden": True})
    name: Name = Field(..., description="Only the existing project's display name is changed, followed by a protected readback.")

class ListRegions(_Config):
    operation: Literal["list_regions"] = Field("list_regions", json_schema_extra={"ui:hidden": True})

class ListSharedTierRegions(_Config):
    operation: Literal["list_shared_tier_regions"] = Field("list_shared_tier_regions", json_schema_extra={"ui:hidden": True})

class ListClusters(GetProject):
    operation: Literal["list_clusters"] = Field("list_clusters", json_schema_extra={"ui:hidden": True})
    include_terminated: StrictBool = False

class GetCluster(GetProject):
    operation: Literal["get_cluster"] = Field("get_cluster", json_schema_extra={"ui:hidden": True})
    cluster_id: ID = Field(..., json_schema_extra=_dynamic("cluster_id", "project_id"),
        description="Current v2 cluster/workspace metadata. Returned project membership must match.")

class ListStageFolder(GetCluster):
    operation: Literal["list_stage_folder"] = Field("list_stage_folder", json_schema_extra={"ui:hidden": True})
    folder_path: Path = Field("", description="Plain relative folder path; omit for Stage root. No file content or download URL is returned.")

class GetStageFileMetadata(GetCluster):
    operation: Literal["get_stage_file_metadata"] = Field("get_stage_file_metadata", json_schema_extra={"ui:hidden": True})
    file_path: Path = Field(..., min_length=1, description="Plain relative file path. The documented metadata=true query is always sent; redirects are refused.")

class CreateStageFolder(GetCluster):
    operation: Literal["create_stage_folder"] = Field("create_stage_folder", json_schema_extra={"ui:hidden": True})
    folder_path: Path = Field(..., min_length=1, description="Create a folder with an empty body and a trailing slash. Parent must exist and target must be absent.")

class MoveEmptyStageFolder(CreateStageFolder):
    operation: Literal["move_empty_stage_folder"] = Field("move_empty_stage_folder", json_schema_extra={"ui:hidden": True})
    new_folder_path: Path = Field(..., min_length=1, description="New relative folder path. Source must be empty and destination absent. Checks are point-in-time; the API documents no conditional mutation.")

class DeleteEmptyStageFolder(CreateStageFolder):
    operation: Literal["delete_empty_stage_folder"] = Field("delete_empty_stage_folder", json_schema_extra={"ui:hidden": True},
        description="Delete a selected empty folder after readback. No root/file or recursive deletion is exposed.")

SingleStoreConfig = Annotated[Union[GetOrganization, ListProjects, GetProject, RenameProject,
    ListRegions, ListSharedTierRegions, ListClusters, GetCluster, ListStageFolder,
    GetStageFileMetadata, CreateStageFolder, MoveEmptyStageFolder, DeleteEmptyStageFolder], Field(discriminator="operation")]

class SingleStoreNodeConfig(NodeConfig[SingleStoreConfig, SingleStoreManagementCredential]):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    credentials: Optional[SingleStoreManagementCredential] = None


class CredentialValidationUnavailable(ValueError):
    """The stored SingleStore credential is no longer available."""


async def _authority_row(pool, credential_id, user_id, organization_id):
    # Reuse staging's canonical ACL predicate without extending its repository.
    from repositories.credentials import credential_access_predicate
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT c.credential, c.credential_type, c.owner_id, c.token_version, "
            "c.updated_at, c.approval_revision, c.revoked_at FROM credentials c "
            "WHERE c.id = $1 AND " + credential_access_predicate(),
            credential_id, user_id, organization_id,
        )
    if row is None or row["revoked_at"] is not None or row["credential_type"] not in FAMILIES:
        raise CredentialValidationUnavailable("Credential is unavailable or its type is not supported by SingleStore")
    return dict(row)


@dataclass(frozen=True)
class _Authority:
    credential_id: str
    actor: str
    actor_org: Optional[str]
    user_id: str
    organization_id: Optional[str]
    pool: object = field(repr=False)
    row: dict = field(repr=False)
    workflow_id: Optional[str] = None

    async def revalidate(self):
        from wss.handlers.workflow_handler import get_user_org_context
        from utils.credentials import get_workflow_owner_id, is_credential_authorized_for_workflow
        async with self.pool.acquire() as conn:
            actor_org = await get_user_org_context(conn, self.actor)
            effective_org = await get_user_org_context(conn, self.user_id)
        if actor_org != self.actor_org or effective_org != self.organization_id:
            raise CredentialValidationUnavailable("Credential access context changed; retry")
        if self.user_id != self.actor:
            if (await get_workflow_owner_id(self.pool, self.workflow_id) != self.user_id
                    or not await is_credential_authorized_for_workflow(self.pool, self.workflow_id, self.credential_id)):
                raise CredentialValidationUnavailable("Credential workflow authorization changed; retry")
        row = await _authority_row(self.pool, self.credential_id, self.user_id, self.organization_id)
        if row != self.row:
            raise CredentialValidationUnavailable("Credential authority changed; retry")
        return row

    async def load(self):
        from utils.encryption import get_encryption
        row = await self.revalidate()
        raw = get_encryption().decrypt_credential(row["credential"])
        if not isinstance(raw, dict):
            raise CredentialValidationUnavailable("Credential data is invalid")
        return {**raw, "credential_type": row["credential_type"]}


async def _current_authority(*, credential_id, user_id, pool, workflow_id=None):
    from wss.handlers.workflow_handler import get_user_org_context
    from utils.credentials import get_workflow_owner_id, is_credential_authorized_for_workflow
    if not user_id or pool is None:
        raise CredentialValidationUnavailable("Credential authority is unavailable")
    async with pool.acquire() as conn:
        actor_org = await get_user_org_context(conn, user_id)
    effective_user, effective_org = user_id, actor_org
    try:
        row = await _authority_row(pool, credential_id, user_id, actor_org)
    except CredentialValidationUnavailable:
        if not workflow_id:
            raise
        owner = await get_workflow_owner_id(pool, workflow_id)
        if not owner or not await is_credential_authorized_for_workflow(pool, workflow_id, credential_id):
            raise CredentialValidationUnavailable("Credential workflow authorization is unavailable") from None
        async with pool.acquire() as conn:
            effective_org = await get_user_org_context(conn, owner)
        row = await _authority_row(pool, credential_id, owner, effective_org)
        effective_user = owner
    return _Authority(credential_id, user_id, actor_org, effective_user, effective_org, pool, row, workflow_id)


_ACTIVE_AUTHORITY: ContextVar[Optional[_Authority]] = ContextVar("singlestore_authority", default=None)
_PRIVATE_REQUEST: ContextVar[bool] = ContextVar("singlestore_private_request", default=False)



class _PrivateRequestLogFilter(logging.Filter):
    def filter(self, record):
        return not _PRIVATE_REQUEST.get()


for _logger in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "utils.ssrf"):
    logging.getLogger(_logger).addFilter(_PrivateRequestLogFilter())


class _AuthRefused(ValueError):
    pass


class _BoundCredential(dict):
    """Opaque stored reference; the loader supplies staging's trusted workflow context."""
    def __init__(self, *, credential_id, user_id, pool, workflow_id=None):
        super().__init__()
        self.credential_id = credential_id
        self.user_id = user_id
        self.pool = pool
        self.workflow_id = workflow_id

    async def authority(self, workflow_id=None):
        return await _current_authority(credential_id=self.credential_id, user_id=self.user_id,
            pool=self.pool, workflow_id=workflow_id or self.workflow_id)


def _unique(pairs):
    raw = {}
    for key, value in pairs:
        if key in raw:
            raise ValueError("SingleStore returned duplicate JSON properties")
        raw[key] = value
    return raw

def _nonfinite(_value):
    raise ValueError("SingleStore returned non-finite JSON")

def _contains_key(raw, api_key):
    pending = [raw]
    while pending:
        item = pending.pop()
        if isinstance(item, str) and api_key in item:
            return True
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return False

class _NotFound(ValueError):
    pass

class _Session:
    def __init__(self, credential):
        self.credential = credential

    async def request(self, method, path, *, params=None, body=None):
        # Internal routes only. No endpoint, headers, arbitrary query or SQL is exposed.
        uuid = UUID_PATTERN[1:-1]
        simple = path in {"/organizations/current", "/projects", "/regions", "/regions/sharedtier", "/clusters"}
        project = re.fullmatch(r"/projects/" + uuid, path) is not None
        cluster = re.fullmatch(r"/clusters/" + uuid, path) is not None
        stage = re.fullmatch(r"/clusters/" + uuid + r"/stage/fs(?:/.*)?", path) is not None
        if not (simple or project or cluster or stage) or method not in {"GET", "PATCH", "PUT", "DELETE"}:
            raise ValueError("Unsupported SingleStore metadata route")
        params = params or {}
        if not isinstance(params, dict) or set(params) - {"fields", "projectID", "includeTerminated", "metadata"}:
            raise ValueError("Unsupported SingleStore metadata query")
        if method != "GET":
            valid = (project and method == "PATCH" and isinstance(body, dict) and set(body) == {"name"}
                or stage and path.endswith("/") and method == "PATCH" and isinstance(body, dict) and set(body) == {"newPath"}
                or stage and path.endswith("/") and method in {"PUT", "DELETE"} and body is None)
            if not valid or params:
                raise ValueError("Unsupported SingleStore metadata mutation")
        elif body is not None:
            raise ValueError("Metadata reads cannot contain a request body")
        authority = _ACTIVE_AUTHORITY.get()
        if authority and _credential(await authority.load()) != self.credential:
            raise CredentialValidationUnavailable("SingleStore credential or organization binding changed; retry")
        private = _PRIVATE_REQUEST.set(True)
        try:
            async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=20.0) as client:
                kwargs = {"params": params, "headers": {"Authorization": "Bearer " + self.credential.api_key, "Accept": "application/json"}}
                if body is not None:
                    kwargs["json"] = body
                async with client.stream(method, API_URL + path, **kwargs) as response:
                    if response.status_code in (401, 403):
                        raise _AuthRefused("SingleStore key or permission was rejected (HTTP " + str(response.status_code) + ")")
                    if response.status_code == 404:
                        raise _NotFound("SingleStore metadata was not found")
                    if response.status_code == 429:
                        raise ValueError("SingleStore rate limit reached; retry later")
                    if 300 <= response.status_code < 400:
                        raise ValueError("SingleStore redirect refused; no download or alternate host was followed")
                    if response.status_code != 200:
                        raise ValueError("SingleStore metadata request failed with HTTP " + str(response.status_code))
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise ValueError("SingleStore returned an unsupported metadata format")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_BYTES:
                            raise ValueError("SingleStore response exceeds the bounded metadata limit")
                    try:
                        raw = json.loads(data, object_pairs_hook=_unique, parse_constant=_nonfinite)
                    except (ValueError, UnicodeError, RecursionError):
                        raise ValueError("SingleStore returned invalid JSON metadata") from None
        except (httpx.HTTPError, SSRFError):
            raise ValueError("SingleStore public HTTPS request could not complete") from None
        finally:
            _PRIVATE_REQUEST.reset(private)
        if _contains_key(raw, self.credential.api_key):
            raise ValueError("SingleStore returned credential material")
        if isinstance(raw, dict) and (raw.get("error") is not None or raw.get("errors") not in (None, [])):
            raise ValueError("SingleStore returned an error object; no metadata was accepted")
        if authority:
            await authority.revalidate()
        return raw

def _text(value, maximum=1000):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("SingleStore returned invalid text metadata")
    return value

def _id(value):
    value = _text(value, 36)
    if not re.fullmatch(UUID_PATTERN, value):
        raise ValueError("SingleStore returned an invalid identifier")
    return value.lower()

def _object(value):
    if not isinstance(value, dict):
        raise ValueError("SingleStore returned invalid record metadata")
    return value

def _array(value):
    if not isinstance(value, list) or len(value) > 500:
        raise ValueError("SingleStore returned an invalid bounded collection")
    return value

def _strings(raw, fields):
    return {key: None if raw[key] is None else _text(raw[key]) for key in fields if key in raw}

def _distinct(rows, key):
    if len({row[key] for row in rows}) != len(rows):
        raise ValueError("SingleStore returned duplicate metadata identifiers")
    return rows

def _project(raw, expected=None):
    raw = _object(raw)
    value = _id(raw.get("projectID"))
    if expected is not None and value != expected:
        raise ValueError("SingleStore returned a different project")
    return {"projectID": value, **_strings(raw, ("name", "edition", "createdAt"))}

def _cluster(raw, project_id, cluster_id=None):
    raw = _object(raw)
    value = _id(raw.get("clusterID"))
    parent = _id(raw.get("projectID"))
    if parent != project_id or cluster_id is not None and value != cluster_id:
        raise ValueError("SingleStore returned a cluster outside the selected project")
    result = {"clusterID": value, "projectID": parent, **_strings(raw, ("name", "provider", "region", "state",
        "deploymentType", "createdAt", "lastResumedAt", "terminatedAt", "smartDRStatus"))}
    if raw.get("groupID") is not None:
        result["groupID"] = _id(raw["groupID"])
    for key in ("kai", "multiAZ"):
        if key in raw:
            if raw[key] is not None and type(raw[key]) is not bool:
                raise ValueError("SingleStore returned invalid cluster flags")
            result[key] = raw[key]
    if "scalingProgress" in raw:
        value = raw["scalingProgress"]
        if value is not None and (type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1):
            raise ValueError("SingleStore returned invalid cluster progress")
        result["scalingProgress"] = value
    return result

def _response_path(value, *, folder=False, root=False):
    if value == "/" and root:
        return ""
    value = _text(value, 513) if value != "" else value
    if value.startswith("/"):
        value = value[1:]
    return _path(value, folder=folder, root=root)

def _file(raw, expected=None):
    raw = _object(raw)
    kind = raw.get("type")
    if kind not in (None, "", "json", "directory"):
        raise ValueError("SingleStore returned unsupported Stage metadata")
    path = _response_path(raw.get("path"), folder=kind == "directory")
    if expected is not None and (path != expected or kind == "directory"):
        raise ValueError("SingleStore returned metadata for a different file")
    result = {"path": path, "type": kind, **_strings(raw, ("name", "created", "last_modified", "mimetype"))}
    if "writable" in raw:
        if type(raw["writable"]) is not bool:
            raise ValueError("SingleStore returned invalid writable metadata")
        result["writable"] = raw["writable"]
    if "size" in raw:
        if type(raw["size"]) is not int or raw["size"] < 0:
            raise ValueError("SingleStore returned invalid size metadata")
        result["size"] = raw["size"]
    return result

def _folder(raw, path):
    raw = _object(raw)
    if raw.get("type") != "directory" or _response_path(raw.get("path"), folder=True, root=True) != path:
        raise ValueError("SingleStore returned a different Stage directory")
    rows = [_file(item) for item in _array(raw.get("content"))]
    for row in rows:
        child = row["path"].rstrip("/")
        parent = child.rsplit("/", 1)[0] + "/" if "/" in child else ""
        if parent != path:
            raise ValueError("SingleStore returned a Stage entry outside the selected directory")
    return {"folder_path": path, "items": _distinct(rows, "path"), "returned_count": len(rows),
        "continuation_available": False}

def _stage_path(cluster_id, path):
    return "/clusters/" + cluster_id + "/stage/fs" + ("/" + quote(path, safe="/") if path else "")

def _ack(raw, expected, *, folder=False):
    raw = _object(raw)
    if _response_path(raw.get("path"), folder=folder) != expected:
        raise ValueError("SingleStore mutation acknowledgement did not match the selected path")
    return {"path": expected, **_strings(raw, ("name",))}

class SingleStoreNode(WorkflowNode):
    integration_type = "automation-singlestore"
    credential_provider_labels = {"singlestore": "SingleStore Organization"}
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(noun="organization", identity_operation="get_organization", identity_keys=("name", "orgID"), proves="account")

    @classmethod
    def get_config_model(cls):
        return SingleStoreNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        if isinstance(config_data, dict) and config_data.get("credential_id"):
            return super().parse_config({**config_data, "credentials": None})
        raw = config_data.get("credentials") if isinstance(config_data, dict) else None
        if raw is not None:
            _credential(raw)
        return super().parse_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if credential_id:
            return _BoundCredential(credential_id=credential_id, user_id=user_id, pool=pool)
        return _credential(credential_data).model_dump()

    @classmethod
    async def validate_credential_access(cls, credential_data):
        # Staging's post-connect hook supplies decrypted credentials only.
        try:
            await cls._organization(_Session(_credential(credential_data)))
            return {"valid": True}
        except _AuthRefused:
            return {"valid": False, "error": "SingleStore API key or access was rejected"}
        except ValueError:
            return {"valid": None, "error": "SingleStore access could not be verified"}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"project_id", "cluster_id"}:
            raise ValueError("Unsupported SingleStore picker")
        if page_token is not None:
            raise ValueError("These SingleStore metadata routes do not document pagination")
        if search is not None and (not isinstance(search, str) or len(search) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in search)):
            raise ValueError("Use a bounded metadata search")
        context = {} if context is None else context
        if not isinstance(context, dict):
            raise ValueError("Use a valid SingleStore picker context")
        # The dependent parent is validated before current-row reload/provider work.
        config = ListProjects() if field_name == "project_id" else ListClusters.model_validate({"project_id": context.get("project_id")})
        authority = await credential_data.authority(context.get("_workflow_id")) if isinstance(credential_data, _BoundCredential) else None
        binding = _ACTIVE_AUTHORITY.set(authority)
        try:
            credential = _credential(await authority.load()) if authority else _credential(credential_data)
            result = await cls._execute(_Session(credential), config)
            key = "projectID" if field_name == "project_id" else "clusterID"
            options = [{"value": row[key], "label": row.get("name") or row[key]} for row in result["items"]]
            if search:
                options = [row for row in options if search.casefold() in row["label"].casefold()]
            if authority:
                await authority.revalidate()
            return {"options": options, "next_page_token": None}
        finally:
            _ACTIVE_AUTHORITY.reset(binding)

    async def execute(self, inputs):
        if not isinstance(self.config, SingleStoreNodeConfig) or (self.config.credentials is None and not self.node_data.get("credential_id")):
            raise ValueError("Connect SingleStore Management API credentials")
        credential, authority = self.config.credentials, None
        if self.node_data.get("credential_id"):
            pool = self.node_data.get("_approval_pool")
            if pool is None:
                from utils.database_pool import get_native_pool
                pool = get_native_pool()
            authority = await _current_authority(credential_id=self.node_data["credential_id"], user_id=self.user_id, pool=pool, workflow_id=self.workflow_id)
            credential = _credential(await authority.load())
        binding = _ACTIVE_AUTHORITY.set(authority)
        try:
            result = await self._execute(_Session(credential), self.config.config)
            if authority:
                await authority.revalidate()
            return {"status": "success", "data": result}
        finally:
            _ACTIVE_AUTHORITY.reset(binding)

    @staticmethod
    async def _organization(session):
        raw = _object(await session.request("GET", "/organizations/current"))
        identity = _id(raw.get("orgID"))
        if identity != session.credential.organization_id:
            raise _AuthRefused("SingleStore key belongs to a different organization")
        return {"orgID": identity, **_strings(raw, ("name",))}

    @staticmethod
    async def _project(session, project_id):
        return _project(await session.request("GET", "/projects/" + project_id), project_id)

    @classmethod
    async def _cluster(cls, session, project_id, cluster_id):
        await cls._project(session, project_id)
        return _cluster(await session.request("GET", "/clusters/" + cluster_id,
            params={"fields": CLUSTER_FIELDS}), project_id, cluster_id)

    @staticmethod
    async def _folder(session, cluster_id, path):
        return _folder(await session.request("GET", _stage_path(cluster_id, path)), path)

    @classmethod
    async def _target_absent(cls, session, cluster_id, path):
        parent = path.rstrip("/").rsplit("/", 1)[0] + "/" if "/" in path.rstrip("/") else ""
        result = await cls._folder(session, cluster_id, parent)
        if any(row["path"].rstrip("/") == path.rstrip("/") for row in result["items"]):
            raise ValueError("The Stage target already exists; no overwrite is permitted")

    @classmethod
    async def _execute(cls, session, config):
        op = config.operation
        organization = await cls._organization(session)
        if op == "get_organization":
            return organization
        if op == "list_projects":
            rows = _distinct([_project(raw) for raw in _array(await session.request("GET", "/projects"))], "projectID")
            return {"items": rows, "returned_count": len(rows), "organization_id": organization["orgID"], "continuation_available": False}
        if op in {"list_regions", "list_shared_tier_regions"}:
            path = "/regions" + ("/sharedtier" if op == "list_shared_tier_regions" else "")
            rows = []
            for raw in _array(await session.request("GET", path, params={"fields": "provider,region,regionName"})):
                raw = _object(raw)
                rows.append({key: _text(raw.get(key), 200) for key in ("provider", "region", "regionName")})
            if len({(row["provider"], row["regionName"]) for row in rows}) != len(rows):
                raise ValueError("SingleStore returned duplicate regions")
            return {"items": rows, "returned_count": len(rows), "continuation_available": False,
                "identity_proof": False, "shared_tier": op == "list_shared_tier_regions"}
        if op == "get_project":
            return await cls._project(session, config.project_id)
        if op == "rename_project":
            before = await cls._project(session, config.project_id)
            raw = _object(await session.request("PATCH", "/projects/" + config.project_id, body={"name": config.name}))
            if _id(raw.get("projectID")) != config.project_id:
                raise ValueError("SingleStore acknowledged a different project")
            after = await cls._project(session, config.project_id)
            if after.get("name") != config.name:
                raise ValueError("SingleStore project name readback did not match")
            return {"project": after, "previous_name": before.get("name"), "accepted": True, "readback_verified": True, "effect": "project_name_update"}
        if op == "list_clusters":
            await cls._project(session, config.project_id)
            raw = await session.request("GET", "/clusters", params={"projectID": config.project_id,
                "includeTerminated": str(config.include_terminated).lower(), "fields": CLUSTER_FIELDS})
            rows = _distinct([_cluster(row, config.project_id) for row in _array(raw)], "clusterID")
            return {"items": rows, "returned_count": len(rows), "project_id": config.project_id, "continuation_available": False}
        cluster = await cls._cluster(session, config.project_id, config.cluster_id)
        if op == "get_cluster":
            return cluster
        if op == "list_stage_folder":
            return {**await cls._folder(session, config.cluster_id, config.folder_path), "cluster_id": config.cluster_id}
        if op == "get_stage_file_metadata":
            raw = await session.request("GET", _stage_path(config.cluster_id, config.file_path), params={"metadata": "true"})
            return {"file": _file(raw, config.file_path), "cluster_id": config.cluster_id, "content_included": False}
        # Folder mutations never accept Stage root or an arbitrary file path.
        path = _path(config.folder_path, folder=True)
        if op == "create_stage_folder":
            await cls._target_absent(session, config.cluster_id, path)
            _ack(await session.request("PUT", _stage_path(config.cluster_id, path)), path, folder=True)
            after = await cls._folder(session, config.cluster_id, path)
            if after["items"]:
                raise ValueError("Created Stage folder was not empty at readback; outcome requires review")
            return {"folder_path": path, "cluster_id": config.cluster_id, "accepted": True, "readback_verified": True, "effect": "stage_folder_create"}
        before = await cls._folder(session, config.cluster_id, path)
        if before["items"]:
            raise ValueError("Only an empty Stage folder may be moved or deleted")
        if op == "move_empty_stage_folder":
            target = _path(config.new_folder_path, folder=True)
            if target == path or target.startswith(path):
                raise ValueError("Use a different Stage destination outside the selected source")
            await cls._target_absent(session, config.cluster_id, target)
            _ack(await session.request("PATCH", _stage_path(config.cluster_id, path), body={"newPath": target}), target, folder=True)
            after = await cls._folder(session, config.cluster_id, target)
            if after["items"]:
                raise ValueError("Moved Stage folder was not empty at readback; outcome requires review")
            try:
                await cls._folder(session, config.cluster_id, path)
            except _NotFound:
                pass
            else:
                raise ValueError("Stage source still exists after the move; outcome requires review")
            return {"previous_folder_path": path, "folder_path": target, "cluster_id": config.cluster_id,
                "accepted": True, "readback_verified": True, "effect": "empty_stage_folder_move", "atomic_empty_guarantee": False}
        if op == "delete_empty_stage_folder":
            _ack(await session.request("DELETE", _stage_path(config.cluster_id, path)), path, folder=True)
            try:
                await cls._folder(session, config.cluster_id, path)
            except _NotFound:
                return {"folder_path": path, "cluster_id": config.cluster_id, "accepted": True,
                    "readback_verified": True, "effect": "empty_stage_folder_delete", "atomic_empty_guarantee": False}
            raise ValueError("Stage folder still exists after deletion; outcome requires review")
        raise ValueError("Unsupported SingleStore operation")

