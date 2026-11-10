"""Native Dacast channel, video, folder and playlist metadata reads.

Supplied keys stay in headers at the fixed documented v2 API.
Saved resource restrictions apply to metadata reads and scheduled polling.
"""
from datetime import date, datetime
import json
import re
from typing import Annotated, Literal, Optional, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import normalize_search
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

FAMILY = "dacast_api_key"
NODE_TYPE = "automation-dacast"
ROOT = "https://developer.dacast.com/v2"
OPS = ("check_connection", "list_channels", "list_videos", "get_video",
       "list_folders", "get_folder", "list_playlists", "on_new_folder")
ROUTES = {"channels": "/channel", "videos": "/vod", "folders": "/folder", "playlists": "/playlists"}


def resource_id(value, family="videos"):
    if family == "folders":
        if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value):
            raise ValueError("Enter an existing Dacast numeric-string folder ID without a URL or whitespace")
    else:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value):
            raise ValueError("Enter a canonical lowercase Dacast media UUID without a URL or whitespace")
        if UUID(value).int == 0: raise ValueError("Use a nonzero Dacast media UUID")
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


def approved_resources(value):
    if not isinstance(value, str) or len(value) > 15000: raise ValueError("Enter approved Dacast resource IDs as JSON")
    raw = strict_json(value)
    if not isinstance(raw, dict) or set(raw) != set(ROUTES): raise ValueError("Use channels, videos, folders and playlists ID arrays")
    for family, items in raw.items():
        if not isinstance(items, list) or len(items) > 50: raise ValueError("Approve at most 50 existing IDs per family")
        ids = [resource_id(item, family) for item in items]
        if len(set(ids)) != len(ids): raise ValueError("Approve distinct IDs within each family")
    return raw


class DacastAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Dacast API Key",
        json_schema_extra={"x-credential-instructions": "Enter an existing API key and approve existing resource IDs. This node sends X-Api-Key and X-Format: default at the documented fixed API. Resource access is not a principal or account ownership check; actual API entitlement remains unknown until acceptance.", "x-help-url": "https://docs.dacast.com/docs/getting-started"})
    credential_type: Literal["dacast_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password", "ui:sensitive": True})
    approved_resources_json: str = Field('{"channels":[],"videos":[],"folders":[],"playlists":[]}', title="Approved Resource IDs", description="JSON string arrays of channel/video/playlist UUIDs and numeric-string folder IDs. Maximum 50 per family is a NoClick limit.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    monitor_all_folders: bool = Field(False, strict=True, title="Monitor All Folders", description="Allow the new-folder trigger to watch all folders, including newly created IDs outside the approved list. Manual reads still require approved IDs; names remain controlled by Include Resource Names.")
    include_labels: bool = Field(False, strict=True, title="Include Resource Names", description="Opt in to channel/video/playlist titles and folder names. Descriptions, all links, stream settings, passwords and custom content are always omitted.")
    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value or len(value) > 4096 or value.lower().startswith(("bearer ", "token ")) or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Enter the issued API key without a header prefix or whitespace")
        return value
    @field_validator("approved_resources_json")
    @classmethod
    def resources(cls, value):
        approved_resources(value)
        return value


def credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != FAMILY: raise ValueError("Connect a native Dacast API key")
    if any(key in data for key in ("api_token", "api_secret", "access_token", "refresh_token", "password", "base_url", "host", "cookie", "client_id")):
        raise ValueError("Use only the native supplied Dacast API-key form")
    try: return DacastAPIKeyCredential.model_validate(data).model_dump()
    except ValueError: raise ValueError("Complete the native Dacast key and approved-resource form") from None


def dynamic(name):
    return {"x-resource-type": "dacast_" + name.removesuffix("_id"),
            "x-dynamic-options": {"field_name": name, "searchable": True, "allow_custom": True}}


class NativeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CheckConnection(NativeModel):
    operation: Literal["check_connection"] = "check_connection"


class Paged(NativeModel):
    page: int = Field(1, strict=True, ge=1, le=10000, description="Documented page number. NoClick bounds page numbers; no returned paging URL is followed.")
    per_page: int = Field(25, strict=True, ge=1, le=100, title="Page Size", description="At most 100 records per request. Video/channel APIs document 100; other routes have this conservative NoClick bound.")
    title: Optional[str] = Field(None, max_length=200, title="Title Filter", description="Documented title/name substring filter, repeated unchanged across picker pages.")


class MediaPage(Paged):
    online: Optional[bool] = Field(None, strict=True, title="Enabled for Playback", description="Optional enabled/disabled filter. This does not mean someone is currently broadcasting.")
    start_date: Optional[str] = Field(None, title="Created After", description="Documented YYYY-MM-DD filter; playlist dates are inclusive.")
    end_date: Optional[str] = Field(None, title="Created Before", description="Documented YYYY-MM-DD filter; playlist dates are inclusive.")
    @field_validator("start_date", "end_date")
    @classmethod
    def date_value(cls, value):
        if value is None: return value
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value): raise ValueError("Enter YYYY-MM-DD")
        try: date.fromisoformat(value)
        except ValueError: raise ValueError("Enter a valid date") from None
        return value
    @model_validator(mode="after")
    def ordered_dates(self):
        if self.start_date and self.end_date and self.start_date > self.end_date: raise ValueError("Created After must not follow Created Before")
        return self


class ListChannels(MediaPage):
    operation: Literal["list_channels"] = "list_channels"


class ListVideos(MediaPage):
    operation: Literal["list_videos"] = "list_videos"
    channel_id: Optional[str] = Field(None, title="Recording Channel", description="Optional documented stream_id filter. Its channel UUID is witnessed in the current channel catalog; the list filter alone does not prove each video's ancestry.", json_schema_extra=dynamic("channel_id"))
    @field_validator("channel_id")
    @classmethod
    def channel_value(cls, value): return resource_id(value, "channels") if value is not None else value


class GetVideo(NativeModel):
    operation: Literal["get_video"] = "get_video"
    video_id: str = Field(..., title="Video", json_schema_extra=dynamic("video_id"))
    channel_id: Optional[str] = Field(None, title="Recording Channel", description="For a recording, optionally require its detail stream_id to match this freshly witnessed approved channel. Leave empty for an ordinary VOD.", json_schema_extra=dynamic("channel_id"))
    @field_validator("video_id", "channel_id")
    @classmethod
    def media_value(cls, value): return resource_id(value) if value is not None else value


class ListFolders(Paged):
    per_page: int = Field(25, strict=True, ge=1, le=50, title="Page Size")
    operation: Literal["list_folders"] = "list_folders"


class GetFolder(NativeModel):
    operation: Literal["get_folder"] = "get_folder"
    folder_id: str = Field(..., title="Folder", json_schema_extra=dynamic("folder_id"))
    @field_validator("folder_id")
    @classmethod
    def folder_value(cls, value): return resource_id(value, "folders")


class ListPlaylists(MediaPage):
    operation: Literal["list_playlists"] = "list_playlists"


class OnNewFolder(PollTriggerConfigBase):
    operation: Literal["on_new_folder"] = Field("on_new_folder", title="On New Folder", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Folder",
        "description": "Emit newly seen approved folders, or enable Monitor All Folders in the credential to watch newly created folder IDs.",
    })


Operation = Annotated[Union[OnNewFolder, CheckConnection, ListChannels, ListVideos, GetVideo, ListFolders, GetFolder, ListPlaylists],
                      Field(discriminator="operation")]


class DacastNodeConfig(NodeConfig[Operation, DacastAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class Projection(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)


class Media(Projection):
    id: str
    title: Optional[str] = Field(None, max_length=500, exclude=True)
    online: bool
    creation_date: Optional[str] = Field(None, max_length=100)
    save_date: Optional[str] = Field(None, max_length=100)
    @field_validator("id")
    @classmethod
    def id_value(cls, value): return resource_id(value)
    @field_validator("creation_date", "save_date")
    @classmethod
    def timestamp(cls, value):
        if value is None: return value
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})", value): raise ValueError("Use a documented date-time")
        try: datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError: raise ValueError("Use a valid date-time") from None
        return value


class Channel(Media):
    pass


class Video(Media):
    duration: Optional[str] = Field(None, pattern=r"^[0-9]{2,6}:[0-5][0-9]:[0-5][0-9]$")
    container: Optional[str] = Field(None, max_length=50, pattern=r"^[a-zA-Z0-9_. -]+$")
    vcodec: Optional[str] = Field(None, max_length=50, pattern=r"^[a-zA-Z0-9_. -]+$")
    acodec: Optional[str] = Field(None, max_length=50, pattern=r"^[a-zA-Z0-9_. -]+$")
    video_width: Optional[int] = Field(None, ge=0, le=100000)
    video_height: Optional[int] = Field(None, ge=0, le=100000)
    disk_usage: Optional[int] = Field(None, ge=0, le=10**15)
    filesize: Optional[str] = Field(None, pattern=r"^[0-9]{1,16}$")
    stream_id: Optional[str] = Field(None, exclude=True)
    @field_validator("stream_id")
    @classmethod
    def parent_value(cls, value): return resource_id(value, "channels") if value is not None else value


class Folder(Projection):
    id: str
    name: Optional[str] = Field(None, max_length=500, exclude=True)
    created_at: Optional[str] = Field(None, pattern=r"^[0-9]{1,12}$")
    @field_validator("id")
    @classmethod
    def id_value(cls, value): return resource_id(value, "folders")


class Playlist(Media):
    pass


MODELS = {"channels": Channel, "videos": Video, "folders": Folder, "playlists": Playlist}

async def current_credential(data):
    # Staging's shared loaders own saved-credential access and admission.
    return credential(data)


async def request(data, path, *, params=None):
    now = await current_credential(data)
    try:
        async with guarded_async_client( timeout=30, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", ROOT + path, headers={"X-Api-Key": now["api_key"], "X-Format": "default",
                "Accept": "application/json", "Content-Type": "application/json"}, params=params) as response:
                await current_credential(data)
                status = response.status_code
                if status in {400, 401, 403, 404, 422}: raise ValueError(f"Dacast refused the metadata read (HTTP {status})")
                if status != 200: raise RuntimeError(f"Dacast metadata read did not complete (HTTP {status}); no automatic retry")
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json": raise RuntimeError("Dacast returned an unexpected response type")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 2_000_000: raise RuntimeError("Dacast response exceeds the native metadata limit")
                await current_credential(data)
    except httpx.HTTPError: raise RuntimeError("Dacast metadata transport did not complete; no automatic retry") from None
    try: return strict_json(bytes(content))
    except ValueError: raise RuntimeError("Dacast returned invalid JSON") from None


def typed(model, raw):
    try: return model.model_validate(raw)
    except ValueError: raise RuntimeError("Dacast returned unverified metadata") from None


def selected_resource(now, family, value):
    value = resource_id(value, family)
    if value not in approved_resources(now["approved_resources_json"])[family]:
        raise ValueError("Resource is outside the saved Dacast approved-ID restriction")
    return value


def require_list_grant(now, family):
    if not approved_resources(now["approved_resources_json"])[family]: raise ValueError("Approve existing resource IDs before listing this family")


def output(row, now):
    result = row.model_dump(exclude_none=True)
    if now["include_labels"]:
        label = row.name if isinstance(row, Folder) else row.title
        if label is not None: result["name" if isinstance(row, Folder) else "title"] = label
    return result


def page_result(raw, family, cfg):
    count_key = "totalCount" if family == "channels" else "total_count"
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), list) or len(raw["data"]) > cfg.per_page:
        raise RuntimeError("Dacast returned an unverified catalog envelope")
    count = raw.get(count_key)
    if not isinstance(count, str) or not re.fullmatch(r"[0-9]{1,12}", count):
        raise RuntimeError("Dacast returned an unverified route-specific count")
    paging = raw.get("paging")
    if not isinstance(paging, dict) or "next" not in paging or (paging["next"] is not None and (not isinstance(paging["next"], str) or not paging["next"] or len(paging["next"]) > 10000)):
        raise RuntimeError("Dacast returned unverified pagination metadata")
    rows = [typed(MODELS[family], item) for item in raw["data"]]
    if len({row.id for row in rows}) != len(rows): raise RuntimeError("Dacast repeated a resource ID within the page")
    total, more = int(count), paging["next"] is not None
    if total < len(rows) or (more and (not rows or total <= (cfg.page - 1) * cfg.per_page + len(rows))):
        raise RuntimeError("Dacast returned inconsistent pagination metadata")
    if not more and total > cfg.page * cfg.per_page:
        raise RuntimeError("Dacast returned incomplete pagination metadata")
    return rows, total, more


def query(family, cfg):
    params = {"page": cfg.page, "per_page": cfg.per_page}
    if cfg.title is not None: params["title"] = cfg.title
    if isinstance(cfg, MediaPage):
        if cfg.online is not None: params["online"] = "true" if cfg.online else "false"
        if cfg.start_date is not None: params["start_date"] = cfg.start_date
        if cfg.end_date is not None: params["end_date"] = cfg.end_date
    if isinstance(cfg, ListVideos) and cfg.channel_id is not None: params["stream_id"] = cfg.channel_id
    return params


async def fetch_page(data, family, cfg):
    return page_result(await request(data, ROUTES[family], params=query(family, cfg)), family, cfg)


async def resource_witness(data, family, value):
    if family not in {"videos", "folders"}: raise ValueError("Use a documented Dacast metadata detail operation")
    now = await current_credential(data)
    selected = selected_resource(now, family, value)
    row = typed(MODELS[family], await request(data, ROUTES[family] + "/" + selected))
    if row.id != selected: raise RuntimeError("Dacast returned a foreign selected resource ID")
    await current_credential(data)
    return row


async def channel_witness(data, channel_id):
    now = await current_credential(data)
    selected_resource(now, "channels", channel_id)
    seen = set()
    for page in range(1, 6):
        rows, _, more = await fetch_page(data, "channels", ListChannels(page=page, per_page=100))
        for row in rows:
            if row.id in seen: raise RuntimeError("Dacast repeated a channel across witness pages")
            seen.add(row.id)
            if row.id == channel_id:
                await current_credential(data)
                return row
        if not more: raise ValueError("Selected channel was not returned by the current catalog")
    raise RuntimeError("Dacast channel witness exceeded five pages; absence and completion are unverified")


async def list_metadata(data, cfg):
    now = await current_credential(data)
    family = {"list_channels": "channels", "list_videos": "videos", "list_folders": "folders", "list_playlists": "playlists"}[cfg.operation]
    require_list_grant(now, family)
    if isinstance(cfg, ListVideos) and cfg.channel_id is not None: await channel_witness(data, cfg.channel_id)
    rows, total, more = await fetch_page(data, family, cfg)
    allowed = approved_resources(now["approved_resources_json"])[family]
    projected = [output(row, now) for row in rows if row.id in allowed]
    await current_credential(data)
    return {"status": "success", "results": projected, "provider_total_count": total, "received_count": len(rows),
        "returned_count": len(projected), "filtered_count": len(rows) - len(projected), "page": cfg.page,
        "per_page": cfg.per_page, "has_more": more, "next_page": cfg.page + 1 if more else None,
        "completion": "provider_paging_reported", "resource_access_verified": True, "identity_verified": False,
        "account_ownership_verified": False,
        **({"filter_channel_witness_verified": True} if isinstance(cfg, ListVideos) and cfg.channel_id is not None else {})}


class DacastNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-dacast"
    connection_evidence = ConnectionEvidence(identity_operation="check_connection", noun="Dacast catalog access",
        label_keys=(), identity_keys=(), proves="reachability")
    scope_registry = ScopeRegistry(provider="dacast", enforcement=Enforcement.STRICT,
        requirements={op: ScopeRequirement(scopes=(), credential_types=(FAMILY,), note="Supplied X-Api-Key header at the fixed v2 API. Current resource acceptance and saved grants remain authoritative. No OAuth scope or principal identity is inferred.") for op in OPS})
    edit_examples = ["Read metadata for an approved video", "List approved folders", "Read a recording and verify its channel UUID"]
    @classmethod
    def get_config_model(cls): return DacastNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None: credential(config_data["credentials"])
        return super().parse_config(config_data)
    @classmethod
    def validate_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: credential(config_data["credentials"])
            except ValueError: return {"valid": False, "errors": ["Complete the native Dacast credential form"], "satisfied_set": None}
        return super().validate_config(config_data)
    @classmethod
    def resolve_agent_event(cls, output):
        folders = output.get("folders")
        if not isinstance(folders, list) or not folders:
            return None
        descriptions = [f"{row.get('name') or 'Folder'} (ID {row['id']})" for row in folders]
        return {"text": "New folders in the connected Dacast catalog: " + "; ".join(descriptions),
                "conversation_key": "dacast:folders", "data": {"folders": folders}}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        now = await current_credential(credential_data)
        mapping = {"channel_id": ("channels", ListChannels), "video_id": ("videos", ListVideos), "folder_id": ("folders", ListFolders)}
        if field_name not in mapping: return {"options": [], "next_page_token": None}
        if page_token is None: page = 1
        elif isinstance(page_token, str) and re.fullmatch(r"[1-9][0-9]{0,4}", page_token): page = int(page_token)
        else: raise ValueError("Dacast picker continuation must be a bounded page number, never a URL")
        if page > 10000: raise ValueError("Dacast picker page exceeds the native bound")
        family, model = mapping[field_name]
        cfg = model(page=page, per_page=50 if family == "folders" else 100, title=normalize_search(search))
        result = await list_metadata(credential_data, cfg)
        if result["has_more"] and page >= 10000: raise ValueError("Dacast picker exceeded its page bound; completion is unverified")
        options = [{"value": row["id"], "label": row.get("name") or row.get("title") or row["id"],
                    "metadata": {"completion": "provider_paging_reported", "identity_verified": False}} for row in result["results"]]
        await current_credential(credential_data)
        return {"options": options, "next_page_token": str(result["next_page"]) if result["has_more"] else None}
    async def execute(self, inputs: dict) -> dict:
        if self.config.credentials is None:
            raise ValueError("Connect a Dacast API key")
        data = self.config.credentials.model_dump()
        cfg = self.config.config
        now = await current_credential(data)
        if isinstance(cfg, OnNewFolder):
            # Descending ID order is creation order per the folder contract.
            # Scan every page before advancing the baseline.
            allowed = approved_resources(now["approved_resources_json"])["folders"]
            if not now["monitor_all_folders"]:
                require_list_grant(now, "folders")
            folders, seen = [], set()
            for page_number in range(1, 201):
                page_cfg = ListFolders(page=page_number, per_page=50)
                raw = await request(data, "/folder", params={**query("folders", page_cfg), "sort": "id", "order": "desc"})
                rows, _, more = page_result(raw, "folders", page_cfg)
                for row in rows:
                    if row.id in seen:
                        raise RuntimeError("Dacast repeated a folder across polling pages")
                    seen.add(row.id)
                    if now["monitor_all_folders"] or row.id in allowed:
                        folders.append(output(row, now))
                if not more:
                    break
            else:
                raise RuntimeError("Dacast folder poll exceeds 10,000 folders; no baseline advanced")
            fresh = await self._filter_unseen(folders, lambda folder: folder["id"])
            return {"folders": fresh, "new_folder_count": len(fresh)}
        if isinstance(cfg, CheckConnection):
            rows, _, more = await fetch_page(data, "channels", ListChannels(per_page=1))
            await current_credential(data)
            return {"status": "success", "witness_verified": True, "received_count": len(rows), "has_more": more,
                "resource_access_verified": True, "identity_verified": False, "account_ownership_verified": False}
        if isinstance(cfg, Paged): return await list_metadata(data, cfg)
        if isinstance(cfg, GetVideo):
            selected_resource(now, "videos", cfg.video_id)
            if cfg.channel_id is not None: await channel_witness(data, cfg.channel_id)
            row = await resource_witness(data, "videos", cfg.video_id)
            if cfg.channel_id is not None and row.stream_id != cfg.channel_id: raise ValueError("Dacast video detail does not confirm the selected recording channel")
        else:
            row = await resource_witness(data, "folders", cfg.folder_id)
        await current_credential(data)
        return {"status": "success", "data": output(row, now), "resource_access_verified": True,
                "identity_verified": False, "account_ownership_verified": False,
                **({"channel_id": cfg.channel_id, "parent_link_verified": True} if isinstance(cfg, GetVideo) and cfg.channel_id is not None else {})}
