"""Native Yodeck Beta v2 metadata reads, scoped to an existing workspace witness.

Only supplied tokens and seven closed GET routes are supported. Configuration,
content, device capabilities and returned pagination URLs never become outputs.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_serializer
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.credentials import resolve_credential_with_owner_fallback
from utils.encryption import get_encryption
from utils.ssrf import guarded_async_client

TYPE = "yodeck_token"
API = "https://app.yodeck.com/api/v2"
AUTH_KEY = "_yodeck_authority"
CURRENT_ORGANIZATION = object()
MAX_BODY = 4 * 1024 * 1024
UNAVAILABLE = "Yodeck credential is unavailable or its current authority changed"
UNVERIFIED = "Yodeck metadata response could not be verified"
ID = Annotated[StrictInt, Field(ge=1, le=9223372036854775807)]
Count = Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]
Offset = Annotated[StrictInt, Field(ge=0, le=1000000)]
Limit = Annotated[StrictInt, Field(ge=1, le=100)]
Text = Annotated[StrictStr, Field(max_length=512)]


def decimal_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > 9223372036854775807:
        raise ValueError("Enter a canonical positive decimal resource ID")
    return value


ResourceID = Annotated[StrictStr, BeforeValidator(decimal_id), Field(pattern=r"^[1-9][0-9]{0,18}$", min_length=1, max_length=19)]


def header_atom(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or any(ord(c) < 33 or ord(c) > 126 or c == ":" for c in value):
        raise ValueError("The nonsecret label must be a short header-safe string without spaces or a colon")
    return value


def token(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 16384 or any(ord(c) < 33 or ord(c) > 126 for c in value) or value.lower().startswith(("http:", "https:", "bearer ", "token ", "basic ")):
        raise ValueError("Supply the issued token value without a URL, whitespace or authentication prefix")
    return value


class YodeckTokenCredential(BaseModel):
    model_config = ConfigDict(title="Yodeck API Token", extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": TYPE,
        "x-credential-help-url": "https://app.yodeck.com/api-docs/",
        "x-credential-instructions": "Supply an existing Yodeck API token value, a nonsecret label and an existing accessible workspace ID. Requests use Authorization: Token label:value. This integration does not issue tokens or log in. The selected workspace is an access witness, not account or actor identity. Permissions and entitlement remain specific to the token's role.",
    })
    credential_type: Literal["yodeck_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    token_label: Annotated[StrictStr, BeforeValidator(header_atom)] = Field("noclick", title="Token Label", description="Nonsecret label for the documented Token label:value header; local header-safe limit is 128 characters.")
    token_value: Annotated[StrictStr, BeforeValidator(token)] = Field(..., title="API Token Value", repr=False, json_schema_extra={"ui:widget": "password"})
    workspace_id: ResourceID = Field(..., title="Workspace ID", description="Exact existing accessible workspace ID as decimal text. Every operation verifies this witness and child workspace ancestry.")

    @model_serializer(mode="wrap")
    def connect_tag(self, handler):
        return {**handler(self), "credential_type": TYPE}


def credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
        raise ValueError("Yodeck requires its original supplied token credential")
    try:
        return YodeckTokenCredential.model_validate(raw)
    except Exception:
        raise ValueError("Yodeck credential fields are invalid") from None


def raw_guard(data):
    if isinstance(data, dict) and data.get("credentials") is not None:
        raw = data["credentials"]
        if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
            raise ValueError("Yodeck credential type is not supported")


def op(value, title, description):
    return Field(value, title=title, description=description, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Signage Metadata", "x-is-trigger": False})


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    include_names: StrictBool = Field(False, title="Include Resource Names", description="Opt in to resource display names. Content, descriptions, player/network/configuration, URLs, registration codes and capabilities remain omitted.")


class Paging(Config):
    offset: Offset = Field(0, title="Offset", description="Documented numeric offset; one page only, local maximum 1,000,000. Returned links are never followed.")
    limit: Limit = Field(20, title="Limit", description="Documented numeric limit. The 1–100 cap is local, not a claimed vendor maximum.")


class ListWorkspaces(Paging):
    operation: Literal["list_workspaces"] = op("list_workspaces", "List Workspace Metadata", "Verify the credential's selected workspace, then read one accessible workspace catalog page. This is resource access, not actor/account ownership.")


class GetWorkspace(Config):
    operation: Literal["get_workspace"] = op("get_workspace", "Get Selected Workspace Metadata", "Read the exact workspace witness configured in the credential; no workspace settings or working hours.")


class ListFolders(Paging):
    operation: Literal["list_folders"] = op("list_folders", "List Workspace Folder Metadata", "Verify the selected workspace and filter folders with the documented workspace query; validate every returned parent.")
    parent_folder_id: Optional[ResourceID] = Field(None, title="Parent Folder ID", description="Optional explicit existing folder ID. The parent is independently read and must belong to the selected workspace. Omitted or null means no parent filter.")


class GetFolder(Config):
    operation: Literal["get_folder"] = op("get_folder", "Get Workspace Folder Metadata", "Verify an exact existing folder ID and its selected-workspace ancestry.")
    folder_id: ResourceID = Field(..., title="Folder ID", description="Existing decimal folder ID. The picker is limited to the credential's selected workspace.", json_schema_extra={"x-dynamic-options": {"allow_custom": True}})


class ListPlaylists(Paging):
    operation: Literal["list_playlists"] = op("list_playlists", "List Workspace Playlist Metadata", "Read one playlist catalog page and locally keep the selected workspace. The published route has no workspace query; count and continuation describe the full catalog.")


class GetPlaylist(Config):
    operation: Literal["get_playlist"] = op("get_playlist", "Get Workspace Playlist Metadata", "Verify an exact existing playlist ID and workspace ancestry. Playlist elements, media and thumbnails are omitted whole.")
    playlist_id: ResourceID = Field(..., title="Playlist ID", description="Existing decimal playlist ID. The saved picker locally filters a single catalog page by the selected workspace.", json_schema_extra={"x-dynamic-options": {"allow_custom": True}})


class ListScreens(Paging):
    operation: Literal["list_screens"] = op("list_screens", "List Workspace Screen Metadata", "Request subset=basic explicitly; only ID, UUID, online/registered/last_seen and exact workspace ID are returned. No expanded fallback.")


OPERATIONS = (ListWorkspaces, GetWorkspace, ListFolders, GetFolder, ListPlaylists, GetPlaylist, ListScreens)
YodeckConfig = Annotated[Union[ListWorkspaces, GetWorkspace, ListFolders, GetFolder, ListPlaylists, GetPlaylist, ListScreens], Field(discriminator="operation")]


class YodeckNodeConfig(NodeConfig[YodeckConfig, YodeckTokenCredential]):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    node_type: Literal["automation-yodeck"] = "automation-yodeck"


@dataclass(eq=False)
class Authority:
    credential: YodeckTokenCredential = field(repr=False)
    pool: Any = field(default=None, repr=False)
    user_id: Any = None
    credential_id: Any = None
    organization_id: Any = None
    workflow_id: Any = None
    anchor: Any = field(default=None, repr=False)
    resolve_organization: bool = False

    @classmethod
    async def create(cls, raw, *, pool=None, user_id=None, credential_id=None, organization_id=CURRENT_ORGANIZATION, workflow_id=None):
        shaped = credential(raw)
        if credential_id and not user_id:
            raise ValueError(UNAVAILABLE)
        current = cls(shaped, pool, user_id, credential_id, organization_id, workflow_id, resolve_organization=organization_id is CURRENT_ORGANIZATION)
        if credential_id:
            if pool is None:
                from utils.database_pool import get_native_pool
                current.pool = get_native_pool()
            if current.resolve_organization:
                current.organization_id = await current.current_organization()
            current.credential, current.anchor = await current.load()
            if current.credential != shaped:
                raise ValueError(UNAVAILABLE)
        return current

    async def current_organization(self):
        from wss.handlers.workflow_handler import get_user_org_context
        async with self.pool.acquire() as conn:
            return await get_user_org_context(conn, self.user_id)

    async def load(self):
        result = await resolve_credential_with_owner_fallback(
            self.credential_id, self.user_id, self.pool,
            org_id=self.organization_id, workflow_id=self.workflow_id)
        if not result:
            raise ValueError(UNAVAILABLE)
        shaped = credential(result)
        return shaped, shaped.model_dump()

    async def require_current(self):
        if self.credential_id:
            if self.resolve_organization and await self.current_organization() != self.organization_id:
                raise ValueError(UNAVAILABLE)
            latest, anchor = await self.load()
            if latest != self.credential or anchor != self.anchor:
                raise ValueError(UNAVAILABLE)


_PRIVATE = ContextVar("yodeck_private_transport", default=False)


class _PrivateFilter(logging.Filter):
    def filter(self, record):
        if _PRIVATE.get():
            record.msg, record.args = "Yodeck transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _PrivateFilter()


class ApiError(ValueError):
    def __init__(self, status):
        self.status_code = status
        meaning = "token authentication was rejected" if status == 401 else "metadata access is forbidden" if status == 403 else "resource was not found" if status == 404 else "rate limit reached; no automatic retry" if status == 429 else "request outcome is not successful"
        super().__init__(f"Yodeck returned HTTP {status}: {meaning}")


class OutcomeUnverified(RuntimeError):
    pass


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


async def request(auth, route, params=None):
    if not re.fullmatch(r"/(?:workspaces|folders|playlists)(?:/[1-9][0-9]{0,18})?|/screens", route):
        raise ValueError("Unsupported Yodeck metadata route")
    params = params or {}
    allowed = {"limit", "offset"} if route == "/workspaces" or route == "/playlists" else {"limit", "offset", "workspace", "parent_folder"} if route == "/folders" else {"limit", "offset", "workspace", "subset"} if route == "/screens" else set()
    if set(params) - allowed:
        raise ValueError("Unsupported Yodeck metadata query")
    for key, value in params.items():
        if key == "subset":
            if value != "basic":
                raise ValueError("Yodeck screens require the fixed basic subset")
        elif type(value) is not int or not (0 if key == "offset" else 1) <= value <= (100 if key == "limit" else 1000000 if key == "offset" else 9223372036854775807):
            raise ValueError("Invalid Yodeck numeric query")
    if route == "/screens" and params.get("subset") != "basic":
        raise ValueError("Yodeck screens require the fixed basic subset")
    await auth.require_current()
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"}
    names |= {name for name in logging.Logger.manager.loggerDict if name.startswith(("httpx.", "httpcore."))}
    for name in names:
        logging.getLogger(name).addFilter(_FILTER)
    private = _PRIVATE.set(True)
    try:
        with suppress_http_instrumentation():
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                req = client.build_request("GET", API + route, params=params, headers={"Authorization": "Token " + auth.credential.token_label + ":" + auth.credential.token_value, "Accept": "application/json"})
                await auth.require_current()
                response = await client.send(req, stream=True)
                try:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        await auth.require_current()
                        raw.extend(chunk)
                        if len(raw) > MAX_BODY:
                            raise OutcomeUnverified("Yodeck response exceeds the local 4 MiB bound; no partial output")
                    await auth.require_current()
                    if response.status_code != 200:
                        raise ApiError(response.status_code)
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise OutcomeUnverified(UNVERIFIED)
                    try:
                        return json.loads(raw, object_pairs_hook=strict_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    except (ValueError, UnicodeError, RecursionError):
                        raise OutcomeUnverified(UNVERIFIED) from None
                finally:
                    await response.aclose()
    except httpx.RequestError:
        await auth.require_current()
        raise OutcomeUnverified("Yodeck transport outcome is unverified") from None
    finally:
        _PRIVATE.reset(private)


def timestamp(value):
    # The spec's last_applied example has no timezone. Preserve that fact.
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})?", value):
        raise ValueError("Invalid resource time")
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


Timestamp = Annotated[StrictStr, BeforeValidator(timestamp)]


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class Workspace(Response):
    id: ID
    parent_workspace_id: Optional[ID] = None
    last_applied: Optional[Timestamp] = None
    name: Optional[Text] = None


class Folder(Response):
    id: ID
    workspace_id: Optional[ID]
    parent_folder_id: Optional[ID]
    name: Optional[Text] = None


class Playlist(Response):
    id: ID
    workspace_id: Optional[ID]
    created_at: Optional[Timestamp] = None
    last_modified: Optional[Timestamp] = None
    name: Optional[Text] = None


class Screen(Response):
    id: ID
    uuid: StrictStr
    workspace_id: Optional[ID]
    online: StrictBool
    registered: StrictBool
    last_seen: Optional[Timestamp]
    name: Optional[Text] = None


RESOURCE = {Workspace: "workspace", Folder: "folder", Playlist: "playlist", Screen: "screen"}


def minimum_id(value):
    if value is None:
        return None
    if not isinstance(value, dict) or type(value.get("id")) is not int or not 1 <= value["id"] <= 9223372036854775807:
        raise OutcomeUnverified("Yodeck nested parent ID could not be verified")
    return value["id"]


def projected(model, raw, include_names=False):
    if not isinstance(raw, dict) or any(key in raw for key in ("error", "errors")):
        raise OutcomeUnverified(UNVERIFIED)
    derived = {"workspace_id", "parent_workspace_id", "parent_folder_id", "online", "registered", "last_seen"}
    selected = {name: raw[name] for name in model.model_fields if name in raw and name not in derived and (name != "name" or include_names)}
    try:
        if model is Workspace and "parent_workspace" in raw:
            selected["parent_workspace_id"] = minimum_id(raw["parent_workspace"])
        if model is not Workspace:
            if "workspace" not in raw:
                raise ValueError("Missing workspace ancestry")
            selected["workspace_id"] = minimum_id(raw["workspace"])
        if model is Folder:
            if "parent_folder" not in raw:
                raise ValueError("Missing folder ancestry")
            selected["parent_folder_id"] = minimum_id(raw["parent_folder"])
        if model is Screen:
            state = raw.get("state")
            if not isinstance(state, dict) or "last_seen" not in state or "uuid" not in selected or str(UUID(selected["uuid"])) != selected["uuid"]:
                raise ValueError("Missing screen metadata")
            selected.update({name: state[name] for name in ("online", "registered", "last_seen")})
        result = model.model_validate(selected).model_dump(exclude_unset=True)
    except Exception:
        raise OutcomeUnverified(UNVERIFIED) from None
    result["resource_type"] = RESOURCE[model]
    return result


def page_result(model, raw, cfg, workspace=None, parent=None):
    if not isinstance(raw, dict) or any(key in raw for key in ("error", "errors")) or type(raw.get("count")) is not int or not 0 <= raw["count"] <= 9223372036854775807 or not isinstance(raw.get("results"), list) or len(raw["results"]) > cfg.limit:
        raise OutcomeUnverified("Yodeck pagination envelope could not be verified")
    if any(key not in raw or raw[key] is not None and (not isinstance(raw[key], str) or not raw[key] or len(raw[key]) > 8192) for key in ("next", "previous")):
        raise OutcomeUnverified("Yodeck nullable pagination markers could not be verified")
    for key in ("next", "previous"):
        if raw[key] is not None:
            try:
                marker = urlsplit(raw[key])
                if marker.scheme not in {"http", "https"} or not marker.hostname or any(c.isspace() or ord(c) < 32 for c in raw[key]):
                    raise ValueError()
                marker.port
            except ValueError:
                raise OutcomeUnverified("Yodeck pagination marker is not a documented URL") from None
    catalog = [projected(model, item, cfg.include_names) for item in raw["results"]]
    if len({item["id"] for item in catalog}) != len(catalog) or raw["count"] < len(catalog):
        raise OutcomeUnverified("Yodeck returned inconsistent resource counts or IDs")
    if model is Playlist:
        items = [item for item in catalog if item["workspace_id"] == workspace]
    else:
        items = catalog
        if workspace is not None and any(item["workspace_id"] != workspace for item in items):
            raise OutcomeUnverified("Yodeck resource does not match the selected workspace")
    if parent is not None and any(item["parent_folder_id"] != parent for item in items):
        raise OutcomeUnverified("Yodeck folder does not match the requested parent")
    more = raw["next"] is not None
    if more and not catalog:
        raise OutcomeUnverified("Yodeck empty page has an unverified continuation")
    next_offset = cfg.offset + len(catalog) if more else None
    if next_offset is not None and next_offset > 1000000:
        raise OutcomeUnverified("Yodeck reached the local offset bound; no partial output")
    return {"items": items, "returned_count": len(items), "catalog_page_count": len(catalog), "provider_count": raw["count"], "count_scope": "full_accessible_playlist_catalog" if model is Playlist else "requested_catalog", "offset": cfg.offset, "limit": cfg.limit, "has_more": more, "next_offset": next_offset, "has_previous": raw["previous"] is not None, "snapshot_consistent": False}


async def exact_detail(auth, model, route, identifier, include_names=False, workspace=None):
    item = projected(model, await request(auth, route), include_names)
    if item["id"] != identifier or workspace is not None and item["workspace_id"] != workspace:
        raise OutcomeUnverified("Yodeck returned a different resource ID or workspace ancestry")
    return item


async def operate(auth, cfg):
    workspace = int(auth.credential.workspace_id)
    witness = await exact_detail(auth, Workspace, f"/workspaces/{workspace}", workspace, cfg.include_names)
    if isinstance(cfg, GetWorkspace):
        return witness
    if isinstance(cfg, GetFolder):
        return await exact_detail(auth, Folder, f"/folders/{cfg.folder_id}", int(cfg.folder_id), cfg.include_names, workspace)
    if isinstance(cfg, GetPlaylist):
        return await exact_detail(auth, Playlist, f"/playlists/{cfg.playlist_id}", int(cfg.playlist_id), cfg.include_names, workspace)
    params = {"offset": cfg.offset, "limit": cfg.limit}
    parent = None
    if isinstance(cfg, ListWorkspaces):
        model, route = Workspace, "/workspaces"
        workspace = None
    elif isinstance(cfg, ListFolders):
        model, route = Folder, "/folders"
        params["workspace"] = workspace
        if cfg.parent_folder_id is not None:
            parent = int(cfg.parent_folder_id)
            await exact_detail(auth, Folder, f"/folders/{parent}", parent, workspace=workspace)
            params["parent_folder"] = parent
    elif isinstance(cfg, ListPlaylists):
        model, route = Playlist, "/playlists"
    elif isinstance(cfg, ListScreens):
        model, route = Screen, "/screens"
        params.update(workspace=workspace, subset="basic")
    else:
        raise ValueError("Unsupported Yodeck metadata operation")
    return page_result(model, await request(auth, route, params), cfg, workspace, parent)


def picker_binding(auth, field_name):
    return {"provider": TYPE, "field": field_name, "user": str(auth.user_id), "credential": str(auth.credential_id), "organization": str(auth.organization_id), "workflow": str(auth.workflow_id), "grant": hashlib.sha256(json.dumps(auth.credential.model_dump(), sort_keys=True).encode()).hexdigest(), "authority": hashlib.sha256(repr(auth.anchor).encode()).hexdigest()}


class YodeckNode(WorkflowNode):
    integration_type = "automation-yodeck"
    connection_evidence = ConnectionEvidence(operation="list_workspaces", noun="accessible Yodeck workspaces", label_keys=("id",), proves="reachability")

    @classmethod
    def get_config_model(cls):
        return YodeckNodeConfig

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
        if credential_data is None:
            return None
        auth = await Authority.create(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)
        return {**auth.credential.model_dump(), AUTH_KEY: auth}

    @classmethod
    async def validate_credential_access(cls, raw, *, validation_context=None):
        try:
            if validation_context is not None:
                await validation_context.revalidate()
                result = await validation_context.run_operation("list_workspaces", {})
                return (True, None) if result.get("status") == "success" else (None, UNVERIFIED)
            auth = await Authority.create(raw)
            await operate(auth, ListWorkspaces())
            return True, None
        except ApiError as error:
            return (False, str(error)) if error.status_code in (401, 403) else (None, str(error))
        except Exception:
            if validation_context is not None:
                await validation_context.revalidate()
            return None, UNVERIFIED

    async def execute(self, inputs):
        raw_guard(self.node_data)
        if not isinstance(self.config, YodeckNodeConfig) or self.config.credentials is None:
            raise ValueError("Yodeck supplied token and workspace witness are required")
        auth = await Authority.create(self.config.credentials.model_dump(), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data.get("credential_id"), organization_id=self.organization_id, workflow_id=self.workflow_id)
        result = await operate(auth, self.config.config)
        await auth.require_current()
        return {"status": "success", "operation": self.config.config.operation, "data": result}

    @classmethod
    async def load_field_options(cls, *, field_name, credential_data=None, context=None, page_token=None, search=None):
        context = context or {}
        auth = credential_data.get(AUTH_KEY) if isinstance(credential_data, dict) else None
        if not isinstance(auth, Authority) or not auth.credential_id or not auth.user_id or context.get("_user_id") != auth.user_id:
            raise ValueError("Yodeck picker requires a current saved credential authorized for this actor")
        if field_name not in {"folder_id", "playlist_id"}:
            raise ValueError("Unsupported Yodeck metadata picker")
        if search is not None and (not isinstance(search, str) or len(search) > 512 or any(ord(c) < 32 for c in search)):
            raise ValueError("Yodeck picker search is invalid")
        await auth.require_current()
        offset = 0
        if page_token is not None:
            try:
                if not isinstance(page_token, str) or len(page_token) > 8192:
                    raise ValueError()
                sealed = get_encryption().decrypt_credential(page_token)
                if not isinstance(sealed, dict) or set(sealed) != {"binding", "offset", "expires_at"} or sealed["binding"] != picker_binding(auth, field_name) or type(sealed["expires_at"]) is not int or sealed["expires_at"] <= time.time() or type(sealed["offset"]) is not int or not 0 <= sealed["offset"] <= 1000000:
                    raise ValueError()
                offset = sealed["offset"]
            except Exception:
                raise ValueError("Yodeck picker continuation is invalid, expired or bound to a different credential/scope") from None
        cfg = ListFolders(offset=offset, limit=100) if field_name == "folder_id" else ListPlaylists(offset=offset, limit=100)
        result = await operate(auth, cfg)
        options = [{"value": str(item["id"]), "label": str(item["id"])} for item in result["items"]]
        if search:
            options = [item for item in options if search.casefold() in item["label"].casefold()]
        await auth.require_current()
        continuation = None
        if result["next_offset"] is not None:
            continuation = get_encryption().encrypt_credential({"binding": picker_binding(auth, field_name), "offset": result["next_offset"], "expires_at": int(time.time()) + 600})
        return {"options": options, "next_page_token": continuation}
